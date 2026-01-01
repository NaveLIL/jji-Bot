"""
Redis Cache Service - Rate Limiting, Game State, Sessions
"""

import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import redis.asyncio as redis


class RedisService:
    """Redis service for caching and rate limiting"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis: Optional[redis.Redis] = None
        self._connected = False
    
    async def connect(self) -> bool:
        """Connect to Redis"""
        try:
            self.redis = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()
            self._connected = True
            return True
        except Exception as e:
            print(f"Redis connection failed: {e}. Running without Redis.")
            self._connected = False
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from Redis"""
        if self.redis:
            await self.redis.close()
            self._connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    # ==================== RATE LIMITING ====================
    
    async def check_rate_limit(
        self,
        user_id: int,
        action: str,
        limit: int,
        window_seconds: int = 60
    ) -> tuple[bool, int]:
        """
        Check rate limit for an action.
        Returns (is_allowed, remaining_count)
        """
        if not self._connected:
            return True, limit
        
        key = f"ratelimit:{action}:{user_id}"
        
        try:
            current = await self.redis.get(key)
            
            if current is None:
                await self.redis.setex(key, window_seconds, 1)
                return True, limit - 1
            
            current = int(current)
            
            if current >= limit:
                return False, 0
            
            await self.redis.incr(key)
            return True, limit - current - 1
        except Exception:
            return True, limit
    
    async def get_rate_limit_reset(self, user_id: int, action: str) -> Optional[int]:
        """Get seconds until rate limit resets"""
        if not self._connected:
            return None
        
        key = f"ratelimit:{action}:{user_id}"
        
        try:
            ttl = await self.redis.ttl(key)
            return ttl if ttl > 0 else None
        except Exception:
            return None
    
    async def reset_rate_limit(self, user_id: int, action: str) -> None:
        """Reset rate limit for a user action"""
        if not self._connected:
            return
        
        key = f"ratelimit:{action}:{user_id}"
        
        try:
            await self.redis.delete(key)
        except Exception:
            pass
    
    # ==================== GAME STATE ====================
    
    async def save_game_state(
        self,
        user_id: int,
        game_type: str,
        state: Dict[str, Any],
        ttl_seconds: int = 300
    ) -> bool:
        """Save game state to Redis"""
        if not self._connected:
            return False
        
        key = f"game:{game_type}:{user_id}"
        
        try:
            await self.redis.setex(
                key,
                ttl_seconds,
                json.dumps(state, default=str)
            )
            return True
        except Exception:
            return False
    
    async def get_game_state(
        self,
        user_id: int,
        game_type: str
    ) -> Optional[Dict[str, Any]]:
        """Get game state from Redis"""
        if not self._connected:
            return None
        
        key = f"game:{game_type}:{user_id}"
        
        try:
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception:
            return None
    
    async def delete_game_state(self, user_id: int, game_type: str) -> None:
        """Delete game state from Redis"""
        if not self._connected:
            return
        
        key = f"game:{game_type}:{user_id}"
        
        try:
            await self.redis.delete(key)
        except Exception:
            pass
    
    async def get_all_active_games(self, game_type: str) -> List[Dict[str, Any]]:
        """Get all active games of a type"""
        if not self._connected:
            return []
        
        pattern = f"game:{game_type}:*"
        
        try:
            keys = await self.redis.keys(pattern)
            games = []
            
            for key in keys:
                data = await self.redis.get(key)
                if data:
                    games.append(json.loads(data))
            
            return games
        except Exception:
            return []
    
    # ==================== COOLDOWNS ====================
    
    async def set_cooldown(
        self,
        user_id: int,
        action: str,
        seconds: int
    ) -> None:
        """Set a cooldown for a user action"""
        if not self._connected:
            return
        
        key = f"cooldown:{action}:{user_id}"
        
        try:
            await self.redis.setex(key, seconds, "1")
        except Exception:
            pass
    
    async def check_cooldown(
        self,
        user_id: int,
        action: str
    ) -> tuple[bool, Optional[int]]:
        """
        Check if user is on cooldown.
        Returns (is_on_cooldown, seconds_remaining)
        """
        if not self._connected:
            return False, None
        
        key = f"cooldown:{action}:{user_id}"
        
        try:
            ttl = await self.redis.ttl(key)
            if ttl > 0:
                return True, ttl
            return False, None
        except Exception:
            return False, None
    
    # ==================== USER BLACKLIST ====================
    
    async def blacklist_user(
        self,
        user_id: int,
        duration_seconds: int,
        reason: str = ""
    ) -> None:
        """Blacklist a user"""
        if not self._connected:
            return
        
        key = f"blacklist:{user_id}"
        
        try:
            await self.redis.setex(
                key,
                duration_seconds,
                json.dumps({"reason": reason, "until": (datetime.utcnow() + timedelta(seconds=duration_seconds)).isoformat()})
            )
        except Exception:
            pass
    
    async def is_blacklisted(self, user_id: int) -> tuple[bool, Optional[str]]:
        """Check if user is blacklisted. Returns (is_blacklisted, reason)"""
        if not self._connected:
            return False, None
        
        key = f"blacklist:{user_id}"
        
        try:
            data = await self.redis.get(key)
            if data:
                info = json.loads(data)
                return True, info.get("reason", "")
            return False, None
        except Exception:
            return False, None
    
    async def unblacklist_user(self, user_id: int) -> None:
        """Remove user from blacklist"""
        if not self._connected:
            return
        
        key = f"blacklist:{user_id}"
        
        try:
            await self.redis.delete(key)
        except Exception:
            pass
    
    # ==================== SESSION TRACKING ====================
    
    async def track_session(
        self,
        user_id: int,
        session_data: Dict[str, Any]
    ) -> None:
        """Track user session data"""
        if not self._connected:
            return
        
        key = f"session:{user_id}"
        
        try:
            await self.redis.hset(key, mapping={
                k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                for k, v in session_data.items()
            })
            await self.redis.expire(key, 86400)  # 24 hour expiry
        except Exception:
            pass
    
    async def get_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user session data"""
        if not self._connected:
            return None
        
        key = f"session:{user_id}"
        
        try:
            data = await self.redis.hgetall(key)
            if data:
                return {k: v for k, v in data.items()}
            return None
        except Exception:
            return None
    
    # ==================== STATISTICS ====================
    
    async def increment_stat(self, stat_name: str, amount: int = 1) -> None:
        """Increment a statistic counter"""
        if not self._connected:
            return
        
        key = f"stat:{stat_name}"
        
        try:
            await self.redis.incrby(key, amount)
        except Exception:
            pass
    
    async def get_stat(self, stat_name: str) -> int:
        """Get a statistic value"""
        if not self._connected:
            return 0
        
        key = f"stat:{stat_name}"
        
        try:
            value = await self.redis.get(key)
            return int(value) if value else 0
        except Exception:
            return 0
    
    async def set_stat(self, stat_name: str, value: int) -> None:
        """Set a statistic value"""
        if not self._connected:
            return
        
        key = f"stat:{stat_name}"
        
        try:
            await self.redis.set(key, value)
        except Exception:
            pass
    
    # ==================== PUBSUB FOR DISTRIBUTED EVENTS ====================
    
    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        """Publish a message to a channel"""
        if not self._connected:
            return
        
        try:
            await self.redis.publish(channel, json.dumps(message))
        except Exception:
            pass
    
    async def subscribe(self, channel: str):
        """Subscribe to a channel"""
        if not self._connected:
            return None
        
        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(channel)
            return pubsub
        except Exception:
            return None


# Global Redis instance
import os
cache = RedisService(os.getenv("REDIS_URL", "redis://localhost:6379"))
