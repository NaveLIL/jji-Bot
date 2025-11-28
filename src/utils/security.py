"""
Security and Rate Limiting Utilities
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple
from functools import wraps
import discord
from discord import app_commands

from src.services.cache import cache
from src.services.database import db
from src.utils.metrics import metrics


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded"""
    def __init__(self, reset_in: int, action: str):
        self.reset_in = reset_in
        self.action = action
        super().__init__(f"Rate limit exceeded for {action}. Reset in {reset_in}s")


class UserBlacklisted(Exception):
    """Exception raised when user is blacklisted"""
    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(f"User is blacklisted: {reason}")


async def check_rate_limit(
    user_id: int,
    action: str,
    limit: int,
    window_seconds: int = 60
) -> Tuple[bool, int]:
    """
    Check rate limit for a user action.
    Returns (is_allowed, remaining_count)
    """
    # Try Redis first
    allowed, remaining = await cache.check_rate_limit(
        user_id, action, limit, window_seconds
    )
    
    if not allowed:
        # Track violation
        metrics.track_rate_limit(action)
        await db.record_rate_limit_action(user_id, action)
        
        # Check for repeat violations
        violation_count = await db.get_action_count(user_id, "violation", minutes=60)
        
        if violation_count >= 5:
            # Auto-kick after 5 violations
            await db.log_security_event(
                user_id,
                "rate_limit_kick",
                f"Auto-kicked after {violation_count} rate limit violations in 1 hour",
                severity="high",
                action_taken="kick"
            )
            metrics.track_kick("rate_limit")
        elif violation_count >= 3:
            # Blacklist for 1 hour after 3 violations
            await cache.blacklist_user(user_id, 3600, "Rate limit violations")
            await db.blacklist_user(user_id, 1)
            metrics.track_blacklist("rate_limit")
    
    return allowed, remaining


async def check_user_allowed(user_id: int) -> Tuple[bool, Optional[str]]:
    """
    Check if user is allowed to use bot.
    Returns (is_allowed, reason_if_not)
    """
    # Check Redis blacklist first
    is_blacklisted, reason = await cache.is_blacklisted(user_id)
    if is_blacklisted:
        return False, reason
    
    # Check database blacklist
    db_blacklisted = await db.check_blacklist(user_id)
    if db_blacklisted:
        return False, "Account temporarily suspended"
    
    return True, None


def rate_limited(action: str, limit: int = 3, window: int = 60):
    """
    Decorator for rate limiting commands.
    Usage: @rate_limited("economy", limit=5, window=60)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            user_id = interaction.user.id
            
            # Check if user is allowed
            allowed, reason = await check_user_allowed(user_id)
            if not allowed:
                await interaction.response.send_message(
                    f"❌ You are currently restricted: {reason}",
                    ephemeral=True
                )
                return
            
            # Check rate limit
            is_allowed, remaining = await check_rate_limit(
                user_id, action, limit, window
            )
            
            if not is_allowed:
                reset_in = await cache.get_rate_limit_reset(user_id, action) or window
                await interaction.response.send_message(
                    f"⏳ Slow down! You can use this again in **{reset_in}** seconds.\n"
                    f"Limit: {limit} per {window}s",
                    ephemeral=True
                )
                return
            
            return await func(self, interaction, *args, **kwargs)
        return wrapper
    return decorator


def game_rate_limited(cooldown_seconds: int = 30):
    """
    Decorator for game command cooldowns.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            user_id = interaction.user.id
            action = f"game_{func.__name__}"
            
            # Check cooldown
            on_cooldown, remaining = await cache.check_cooldown(user_id, action)
            
            if on_cooldown:
                await interaction.response.send_message(
                    f"⏳ Game on cooldown! Wait **{remaining}** seconds.",
                    ephemeral=True
                )
                return
            
            # Check general rate limit
            is_allowed, _ = await check_rate_limit(user_id, "games", 10, 60)
            
            if not is_allowed:
                await interaction.response.send_message(
                    "⏳ Too many games! Take a short break.",
                    ephemeral=True
                )
                return
            
            # Set cooldown
            await cache.set_cooldown(user_id, action, cooldown_seconds)
            
            return await func(self, interaction, *args, **kwargs)
        return wrapper
    return decorator


async def check_suspicious_activity(
    user_id: int,
    action: str,
    amount: float = 0,
    average_multiplier: float = 5.0,
    max_transactions_per_hour: int = 100
) -> Tuple[bool, str]:
    """
    Check for suspicious activity patterns.
    Returns (is_suspicious, reason)
    """
    # Check transaction frequency
    tx_count = await db.get_action_count(user_id, "transaction", minutes=60)
    
    if tx_count > max_transactions_per_hour:
        await db.log_security_event(
            user_id,
            "high_transaction_frequency",
            f"{tx_count} transactions in 1 hour (limit: {max_transactions_per_hour})",
            severity="high",
            action_taken="flagged"
        )
        metrics.track_security_event("high_frequency", "high")
        return True, "Unusual transaction frequency"
    
    # Check for unusual bet sizes (would need average calculation)
    # This is a placeholder - implement with actual average tracking
    
    return False, ""


async def handle_exploit_attempt(
    user_id: int,
    exploit_type: str,
    description: str,
    auto_kick: bool = True
) -> None:
    """Handle a detected exploit attempt"""
    await db.log_security_event(
        user_id,
        f"exploit_{exploit_type}",
        description,
        severity="critical",
        action_taken="kick" if auto_kick else "flagged"
    )
    
    metrics.track_security_event(exploit_type, "critical")
    
    if auto_kick:
        await cache.blacklist_user(user_id, 86400 * 365, f"Exploit: {exploit_type}")
        metrics.track_kick(f"exploit_{exploit_type}")


def admin_only():
    """Decorator to restrict commands to admins only"""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ This command requires administrator permissions.",
                    ephemeral=True
                )
                return
            return await func(self, interaction, *args, **kwargs)
        return wrapper
    return decorator


def officer_only():
    """Decorator to restrict commands to officers only"""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            from src.utils.helpers import load_config
            
            config = load_config()
            officer_role_id = config.get("roles", {}).get("officer")
            
            if officer_role_id:
                has_role = any(r.id == officer_role_id for r in interaction.user.roles)
                if not has_role:
                    await interaction.response.send_message(
                        "❌ This command is for officers only.",
                        ephemeral=True
                    )
                    return
            
            return await func(self, interaction, *args, **kwargs)
        return wrapper
    return decorator
