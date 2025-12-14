"""
Database Service - Async SQLAlchemy operations
"""

import json
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Any
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.orm import selectinload

from src.models.database import (
    Base, User, Role, UserRole, Transaction, ServerEconomy, SalaryChange,
    CaseUse, OfficerLog, ChannelConfig, GameSession, VoiceSession,
    RateLimitEntry, SecurityLog, BotStats, TransactionType, RoleType, GameType, LogType
)


class DatabaseService:
    """Async database service with SQLAlchemy 2.0"""
    
    def __init__(self, database_url: str = "sqlite+aiosqlite:///./data/bot.db"):
        self.engine = create_async_engine(
            database_url,
            echo=False,
            pool_pre_ping=True,
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    
    async def init_db(self) -> None:
        """Initialize database tables"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Initialize server economy if not exists
        async with self.session() as session:
            result = await session.execute(select(ServerEconomy))
            if not result.scalar_one_or_none():
                economy = ServerEconomy(
                    total_budget=50000.0,
                    tax_rate=10.0,
                    soldier_value=10000.0
                )
                session.add(economy)
                await session.commit()
    
    @asynccontextmanager
    async def session(self):
        """Context manager for database sessions with automatic rollback on error"""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    
    # ==================== USER OPERATIONS ====================
    
    async def get_or_create_user(self, discord_id: int) -> User:
        """Get or create a user by Discord ID"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == discord_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(discord_id=discord_id)
                session.add(user)
                await session.commit()
                await session.refresh(user)
            
            return user
    
    async def get_user(self, discord_id: int) -> Optional[User]:
        """Get a user by Discord ID"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == discord_id)
            )
            return result.scalar_one_or_none()
    
    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get a user by internal ID"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()
    
    async def update_user_balance(
        self, 
        discord_id: int, 
        amount: float, 
        transaction_type: TransactionType,
        tax_amount: float = 0.0,
        description: str = None,
        related_user_id: int = None
    ) -> Tuple[bool, float, float]:
        """
        Update user balance with transaction logging.
        Returns (success, before_balance, after_balance)
        """
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(discord_id=discord_id)
                session.add(user)
                await session.flush()
            
            before_balance = user.balance
            new_balance = before_balance + amount - tax_amount
            
            if new_balance < 0:
                return False, before_balance, before_balance
            
            user.balance = new_balance
            
            # Log transaction
            transaction = Transaction(
                user_id=user.id,
                amount=amount,
                transaction_type=transaction_type,
                tax_amount=tax_amount,
                before_balance=before_balance,
                after_balance=new_balance,
                description=description,
                related_user_id=related_user_id
            )
            session.add(transaction)
            
            await session.commit()
            return True, before_balance, new_balance
    
    async def set_user_balance(
        self,
        discord_id: int,
        new_balance: float,
        description: str = "Admin set balance"
    ) -> Tuple[bool, float, float]:
        """Set user balance to a specific value"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(discord_id=discord_id, balance=new_balance)
                session.add(user)
                await session.flush()
                before_balance = 0
            else:
                before_balance = user.balance
                user.balance = new_balance
            
            transaction = Transaction(
                user_id=user.id,
                amount=new_balance - before_balance,
                transaction_type=TransactionType.ADMIN_SET,
                tax_amount=0,
                before_balance=before_balance,
                after_balance=new_balance,
                description=description
            )
            session.add(transaction)
            
            await session.commit()
            return True, before_balance, new_balance
    
    async def update_user_roles(
        self, 
        discord_id: int, 
        is_officer: bool = None, 
        is_sergeant: bool = None, 
        is_soldier: bool = None
    ) -> None:
        """Update user role flags"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == discord_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(discord_id=discord_id)
                session.add(user)
            
            if is_officer is not None:
                user.is_officer = is_officer
            if is_sergeant is not None:
                user.is_sergeant = is_sergeant
            if is_soldier is not None:
                user.is_soldier = is_soldier
            
            await session.commit()
    
    async def get_leaderboard(
        self, 
        order_by: str = "balance", 
        limit: int = 10, 
        offset: int = 0
    ) -> List[User]:
        """Get leaderboard sorted by balance or pb_time"""
        async with self.session() as session:
            if order_by == "balance":
                query = select(User).order_by(User.balance.desc())
            else:
                query = select(User).order_by(User.total_pb_time.desc())
            
            result = await session.execute(query.limit(limit).offset(offset))
            return list(result.scalars().all())
    
    async def get_all_active_users(self) -> List[User]:
        """Get all users with soldier/sergeant/officer status"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(
                    or_(User.is_soldier == True, User.is_sergeant == True, User.is_officer == True)
                )
            )
            return list(result.scalars().all())
    
    async def update_pb_time(self, discord_id: int, seconds: int) -> None:
        """Add PB time to user"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = result.scalar_one_or_none()
            
            if user:
                user.total_pb_time += seconds
                user.last_pb_reward = datetime.utcnow()
                await session.commit()
    
    async def blacklist_user(self, discord_id: int, duration_hours: int) -> None:
        """Blacklist a user for a duration"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == discord_id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                user.is_blacklisted = True
                user.blacklist_until = datetime.utcnow() + timedelta(hours=duration_hours)
                user.rate_limit_violations += 1
                await session.commit()
    
    async def check_blacklist(self, discord_id: int) -> bool:
        """Check if user is currently blacklisted"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == discord_id)
            )
            user = result.scalar_one_or_none()
            
            if not user or not user.is_blacklisted:
                return False
            
            if user.blacklist_until and user.blacklist_until < datetime.utcnow():
                user.is_blacklisted = False
                user.blacklist_until = None
                await session.commit()
                return False
            
            return True
    
    # ==================== SERVER ECONOMY ====================
    
    async def get_server_economy(self) -> ServerEconomy:
        """Get server economy state"""
        async with self.session() as session:
            result = await session.execute(select(ServerEconomy))
            economy = result.scalar_one_or_none()
            
            if not economy:
                economy = ServerEconomy()
                session.add(economy)
                await session.commit()
                await session.refresh(economy)
            
            return economy
    
    async def update_server_budget(self, amount: float, add: bool = True) -> Tuple[bool, float]:
        """Update server budget. Returns (success, new_budget)"""
        async with self.session() as session:
            result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = result.scalar_one_or_none()
            
            if not economy:
                economy = ServerEconomy()
                session.add(economy)
                await session.flush()
            
            if add:
                economy.total_budget += amount
            else:
                if economy.total_budget < amount:
                    return False, economy.total_budget
                economy.total_budget -= amount
            
            await session.commit()
            return True, economy.total_budget
    
    async def set_tax_rate(self, rate: float) -> None:
        """Set server tax rate"""
        async with self.session() as session:
            result = await session.execute(select(ServerEconomy))
            economy = result.scalar_one_or_none()
            
            if economy:
                economy.tax_rate = max(0, min(100, rate))
                await session.commit()
    
    async def set_soldier_value(self, value: float) -> Tuple[float, float, int]:
        """Set soldier value and recalculate budget. Returns (old_value, new_value, soldier_count)"""
        async with self.session() as session:
            result = await session.execute(select(ServerEconomy).with_for_update())
            economy = result.scalar_one_or_none()
            
            if economy:
                old_value = economy.soldier_value
                
                # Count soldiers
                soldier_count_result = await session.execute(
                    select(func.count(User.id)).where(User.is_soldier == True)
                )
                soldier_count = soldier_count_result.scalar() or 0
                
                # Calculate budget difference (no longer adjust budget - closed-loop economy)
                # old_soldier_contribution = old_value * soldier_count
                # new_soldier_contribution = value * soldier_count
                # budget_diff = new_soldier_contribution - old_soldier_contribution
                
                # Update economy
                economy.soldier_value = value
                # economy.total_budget += budget_diff
                
                await session.commit()
                return old_value, value, soldier_count
            
            return 0, value, 0
    
    async def add_taxes_collected(self, amount: float) -> None:
        """Add to total taxes collected"""
        async with self.session() as session:
            result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = result.scalar_one_or_none()
            
            if economy:
                economy.total_taxes_collected += amount
                economy.total_budget += amount
                await session.commit()
    
    async def add_rewards_paid(self, amount: float) -> None:
        """Add to total rewards paid (deduct from budget)"""
        async with self.session() as session:
            result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = result.scalar_one_or_none()
            
            if economy:
                economy.total_rewards_paid += amount
                economy.total_budget -= amount
                await session.commit()
    
    # ==================== ROLE SHOP ====================
    
    async def get_all_roles(self, available_only: bool = True) -> List[Role]:
        """Get all shop roles"""
        async with self.session() as session:
            query = select(Role)
            if available_only:
                query = query.where(Role.is_available == True)
            
            result = await session.execute(query.order_by(Role.price))
            return list(result.scalars().all())
    
    async def get_role(self, role_id: int = None, discord_id: int = None) -> Optional[Role]:
        """Get a role by ID or Discord ID"""
        async with self.session() as session:
            if role_id:
                query = select(Role).where(Role.id == role_id)
            elif discord_id:
                query = select(Role).where(Role.discord_id == discord_id)
            else:
                return None
            
            result = await session.execute(query)
            return result.scalar_one_or_none()
    
    async def add_shop_role(
        self,
        discord_id: int,
        name: str,
        role_type: RoleType,
        price: float,
        color_hex: str = None,
        description: str = None
    ) -> Role:
        """Add a role to the shop"""
        async with self.session() as session:
            role = Role(
                discord_id=discord_id,
                name=name,
                role_type=role_type,
                price=price,
                color_hex=color_hex,
                description=description
            )
            session.add(role)
            await session.commit()
            await session.refresh(role)
            return role
    
    async def remove_shop_role(self, discord_id: int) -> bool:
        """Remove a role from the shop"""
        async with self.session() as session:
            result = await session.execute(
                select(Role).where(Role.discord_id == discord_id)
            )
            role = result.scalar_one_or_none()
            
            if role:
                await session.delete(role)
                await session.commit()
                return True
            return False
    
    async def get_user_roles(self, discord_id: int) -> List[UserRole]:
        """Get all roles owned by a user"""
        async with self.session() as session:
            result = await session.execute(
                select(UserRole)
                .join(User)
                .where(User.discord_id == discord_id)
                .options(selectinload(UserRole.role))
            )
            return list(result.scalars().all())
    
    async def get_user_active_roles_count(self, discord_id: int) -> int:
        """Get count of active roles for a user"""
        async with self.session() as session:
            result = await session.execute(
                select(func.count(UserRole.id))
                .join(User)
                .where(User.discord_id == discord_id, UserRole.is_active == True)
            )
            return result.scalar() or 0
    
    async def purchase_role(self, discord_id: int, role_discord_id: int) -> Tuple[bool, str]:
        """Purchase a role for a user. Returns (success, message)"""
        async with self.session() as session:
            # Get user
            user_result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return False, "User not found"
            
            # Get role
            role_result = await session.execute(
                select(Role).where(Role.discord_id == role_discord_id)
            )
            role = role_result.scalar_one_or_none()
            
            if not role:
                return False, "Role not found"
            
            if not role.is_available:
                return False, "Role is not available"
            
            # Check if already owned
            existing = await session.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id
                )
            )
            if existing.scalar_one_or_none():
                return False, "You already own this role"
            
            # Check balance
            if user.balance < role.price:
                return False, f"Insufficient balance. Need ${role.price:.2f}"
            
            # Process purchase
            before_balance = user.balance
            user.balance -= role.price
            
            user_role = UserRole(user_id=user.id, role_id=role.id)
            session.add(user_role)
            
            # Add money to server budget (closed-loop economy)
            economy_result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = economy_result.scalar_one_or_none()
            if economy:
                economy.total_budget += role.price
            
            # Log transaction
            transaction = Transaction(
                user_id=user.id,
                amount=-role.price,
                transaction_type=TransactionType.ROLE_PURCHASE,
                tax_amount=0,
                before_balance=before_balance,
                after_balance=user.balance,
                description=f"Purchased role: {role.name}"
            )
            session.add(transaction)
            
            await session.commit()
            return True, f"Successfully purchased {role.name}!"
    
    async def sell_role(
        self, 
        discord_id: int, 
        role_discord_id: int, 
        refund_percentage: float = 10
    ) -> Tuple[bool, str, float]:
        """Sell a role. Returns (success, message, refund_amount)"""
        async with self.session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return False, "User not found", 0
            
            role_result = await session.execute(
                select(Role).where(Role.discord_id == role_discord_id)
            )
            role = role_result.scalar_one_or_none()
            
            if not role:
                return False, "Role not found", 0
            
            user_role_result = await session.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id
                )
            )
            user_role = user_role_result.scalar_one_or_none()
            
            if not user_role:
                return False, "You don't own this role", 0
            
            refund = role.price * (refund_percentage / 100)
            
            # Check if server has enough budget for refund
            economy_result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = economy_result.scalar_one_or_none()
            if economy and economy.total_budget < refund:
                return False, "Server budget too low for refund", 0
            
            before_balance = user.balance
            user.balance += refund
            
            # Deduct refund from server budget (closed-loop economy)
            if economy:
                economy.total_budget -= refund
            
            await session.delete(user_role)
            
            transaction = Transaction(
                user_id=user.id,
                amount=refund,
                transaction_type=TransactionType.ROLE_SELL,
                tax_amount=0,
                before_balance=before_balance,
                after_balance=user.balance,
                description=f"Sold role: {role.name}"
            )
            session.add(transaction)
            
            await session.commit()
            return True, f"Sold {role.name} for ${refund:.2f}", refund
    
    async def toggle_role_active(
        self, 
        discord_id: int, 
        role_discord_id: int, 
        max_active: int = 5
    ) -> Tuple[bool, str, bool]:
        """Toggle role active status. Returns (success, message, new_state)"""
        async with self.session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == discord_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return False, "User not found", False
            
            role_result = await session.execute(
                select(Role).where(Role.discord_id == role_discord_id)
            )
            role = role_result.scalar_one_or_none()
            
            if not role:
                return False, "Role not found", False
            
            user_role_result = await session.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id
                )
            )
            user_role = user_role_result.scalar_one_or_none()
            
            if not user_role:
                return False, "You don't own this role", False
            
            if not user_role.is_active:
                # Check max active limit
                active_count = await session.execute(
                    select(func.count(UserRole.id)).where(
                        UserRole.user_id == user.id,
                        UserRole.is_active == True
                    )
                )
                if active_count.scalar() >= max_active:
                    return False, f"Maximum {max_active} active roles allowed", False
            
            user_role.is_active = not user_role.is_active
            await session.commit()
            
            status = "equipped" if user_role.is_active else "unequipped"
            return True, f"Role {status} successfully", user_role.is_active
    
    # ==================== CASE SYSTEM ====================
    
    async def can_use_case(self, discord_id: int, cooldown_hours: int = 24) -> Tuple[bool, Optional[datetime]]:
        """Check if user can use case. Returns (can_use, next_available_time)"""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            result = await session.execute(
                select(CaseUse)
                .where(CaseUse.user_id == user.id)
                .order_by(CaseUse.last_used.desc())
            )
            case_use = result.scalar_one_or_none()
            
            if not case_use:
                return True, None
            
            next_available = case_use.last_used + timedelta(hours=cooldown_hours)
            if datetime.utcnow() >= next_available:
                return True, None
            
            return False, next_available
    
    async def record_case_use(self, discord_id: int) -> None:
        """Record a case usage"""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            case_use = CaseUse(user_id=user.id)
            session.add(case_use)
            await session.commit()
    
    # ==================== OFFICER SYSTEM ====================
    
    async def log_officer_accept(
        self, 
        officer_discord_id: int, 
        recruit_discord_id: int
    ) -> OfficerLog:
        """Log an officer accepting a recruit"""
        async with self.session() as session:
            officer = await self.get_or_create_user(officer_discord_id)
            recruit = await self.get_or_create_user(recruit_discord_id)
            
            log = OfficerLog(
                officer_id=officer.id,
                recruit_id=recruit.id,
                recruit_discord_id=recruit_discord_id,
                pb_time_at_accept=recruit.total_pb_time
            )
            session.add(log)
            await session.commit()
            await session.refresh(log)
            return log
    
    async def get_officer_stats(self, discord_id: int) -> dict:
        """Get officer recruitment statistics"""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            # Total recruits
            total_result = await session.execute(
                select(func.count(OfficerLog.id)).where(OfficerLog.officer_id == user.id)
            )
            total_recruits = total_result.scalar() or 0
            
            # Pending 10h rewards
            pending_result = await session.execute(
                select(func.count(OfficerLog.id)).where(
                    OfficerLog.officer_id == user.id,
                    OfficerLog.pb_10h_rewarded == False
                )
            )
            pending_rewards = pending_result.scalar() or 0
            
            # Claimed 10h rewards
            claimed_result = await session.execute(
                select(func.count(OfficerLog.id)).where(
                    OfficerLog.officer_id == user.id,
                    OfficerLog.pb_10h_rewarded == True
                )
            )
            claimed_rewards = claimed_result.scalar() or 0
            
            return {
                "total_recruits": total_recruits,
                "pending_rewards": pending_rewards,
                "claimed_rewards": claimed_rewards
            }
    
    async def get_pending_10h_bonuses(self) -> List[Tuple[OfficerLog, User]]:
        """Get all pending 10h bonuses to check"""
        async with self.session() as session:
            result = await session.execute(
                select(OfficerLog, User)
                .join(User, OfficerLog.recruit_id == User.id)
                .where(OfficerLog.pb_10h_rewarded == False)
            )
            return list(result.all())
    
    async def mark_10h_bonus_rewarded(self, log_id: int) -> None:
        """Mark a 10h bonus as rewarded"""
        async with self.session() as session:
            result = await session.execute(
                select(OfficerLog).where(OfficerLog.id == log_id)
            )
            log = result.scalar_one_or_none()
            
            if log:
                log.pb_10h_rewarded = True
                log.pb_10h_rewarded_at = datetime.utcnow()
                await session.commit()
    
    # ==================== GAME SESSIONS ====================
    
    async def create_game_session(
        self,
        discord_id: int,
        game_type: GameType,
        bet_amount: float,
        game_state: dict,
        message_id: int = None,
        channel_id: int = None,
        ttl_minutes: int = 5
    ) -> GameSession:
        """Create a new game session"""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            # Remove any existing sessions for this game
            await session.execute(
                delete(GameSession).where(
                    GameSession.user_id == user.id,
                    GameSession.game_type == game_type
                )
            )
            
            game_session = GameSession(
                user_id=user.id,
                game_type=game_type,
                bet_amount=bet_amount,
                game_state=json.dumps(game_state),
                message_id=message_id,
                channel_id=channel_id,
                expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes)
            )
            session.add(game_session)
            await session.commit()
            await session.refresh(game_session)
            return game_session
    
    async def get_game_session(
        self, 
        discord_id: int, 
        game_type: GameType
    ) -> Optional[GameSession]:
        """Get an active game session"""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            result = await session.execute(
                select(GameSession).where(
                    GameSession.user_id == user.id,
                    GameSession.game_type == game_type,
                    GameSession.expires_at > datetime.utcnow()
                )
            )
            return result.scalar_one_or_none()
    
    async def update_game_session(
        self, 
        session_id: int, 
        game_state: dict,
        message_id: int = None
    ) -> None:
        """Update a game session state"""
        async with self.session() as session:
            result = await session.execute(
                select(GameSession).where(GameSession.id == session_id)
            )
            game_session = result.scalar_one_or_none()
            
            if game_session:
                game_session.game_state = json.dumps(game_state)
                if message_id:
                    game_session.message_id = message_id
                await session.commit()
    
    async def delete_game_session(self, session_id: int) -> None:
        """Delete a game session"""
        async with self.session() as session:
            await session.execute(
                delete(GameSession).where(GameSession.id == session_id)
            )
            await session.commit()
    
    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired game sessions. Returns count of deleted sessions."""
        async with self.session() as session:
            result = await session.execute(
                delete(GameSession).where(GameSession.expires_at < datetime.utcnow())
            )
            await session.commit()
            return result.rowcount
    
    # ==================== VOICE SESSIONS ====================
    
    async def start_voice_session(
        self, 
        discord_id: int, 
        channel_id: int, 
        is_master: bool = False
    ) -> VoiceSession:
        """Start a voice session"""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            # End any existing active sessions
            await session.execute(
                update(VoiceSession)
                .where(VoiceSession.user_id == user.id, VoiceSession.is_active == True)
                .values(is_active=False, left_at=datetime.utcnow())
            )
            
            voice_session = VoiceSession(
                user_id=user.id,
                channel_id=channel_id,
                is_in_master=is_master
            )
            session.add(voice_session)
            await session.commit()
            await session.refresh(voice_session)
            return voice_session
    
    async def end_voice_session(self, discord_id: int) -> Optional[int]:
        """End a voice session. Returns duration in seconds."""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            result = await session.execute(
                select(VoiceSession).where(
                    VoiceSession.user_id == user.id,
                    VoiceSession.is_active == True
                )
            )
            voice_session = result.scalar_one_or_none()
            
            if voice_session:
                voice_session.is_active = False
                voice_session.left_at = datetime.utcnow()
                voice_session.duration_seconds = int(
                    (voice_session.left_at - voice_session.joined_at).total_seconds()
                )
                await session.commit()
                return voice_session.duration_seconds
            
            return None
    
    async def get_active_voice_sessions(self) -> List[VoiceSession]:
        """Get all active voice sessions"""
        async with self.session() as session:
            result = await session.execute(
                select(VoiceSession)
                .where(VoiceSession.is_active == True)
                .options(selectinload(VoiceSession.user))
            )
            return list(result.scalars().all())
    
    async def claim_master_bonus(self, discord_id: int) -> bool:
        """Claim daily master channel bonus. Returns True if claimed."""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            # Check for today's claim
            today = datetime.utcnow().date()
            result = await session.execute(
                select(VoiceSession).where(
                    VoiceSession.user_id == user.id,
                    VoiceSession.is_in_master == True,
                    VoiceSession.master_bonus_claimed == True,
                    func.date(VoiceSession.joined_at) == today
                )
            )
            
            if result.scalar_one_or_none():
                return False  # Already claimed today
            
            # Find current master session and claim
            result = await session.execute(
                select(VoiceSession).where(
                    VoiceSession.user_id == user.id,
                    VoiceSession.is_active == True,
                    VoiceSession.is_in_master == True
                )
            )
            voice_session = result.scalar_one_or_none()
            
            if voice_session:
                voice_session.master_bonus_claimed = True
                await session.commit()
                return True
            
            return False
    
    # ==================== CHANNEL CONFIG ====================
    
    async def get_channel_config(self, config_type: LogType) -> Optional[int]:
        """Get channel ID for a config type"""
        async with self.session() as session:
            result = await session.execute(
                select(ChannelConfig).where(ChannelConfig.config_type == config_type)
            )
            config = result.scalar_one_or_none()
            return config.channel_id if config else None
    
    async def set_channel_config(self, config_type: LogType, channel_id: int) -> None:
        """Set channel ID for a config type"""
        async with self.session() as session:
            result = await session.execute(
                select(ChannelConfig).where(ChannelConfig.config_type == config_type)
            )
            config = result.scalar_one_or_none()
            
            if config:
                config.channel_id = channel_id
            else:
                config = ChannelConfig(config_type=config_type, channel_id=channel_id)
                session.add(config)
            
            await session.commit()
    
    # ==================== RATE LIMITING ====================
    
    async def record_rate_limit_action(self, discord_id: int, action_type: str) -> None:
        """Record a rate-limited action"""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            entry = RateLimitEntry(
                user_id=user.id,
                action_type=action_type
            )
            session.add(entry)
            await session.commit()
    
    async def get_action_count(
        self, 
        discord_id: int, 
        action_type: str, 
        minutes: int = 1
    ) -> int:
        """Get action count within time window"""
        async with self.session() as session:
            user = await self.get_or_create_user(discord_id)
            
            cutoff = datetime.utcnow() - timedelta(minutes=minutes)
            result = await session.execute(
                select(func.count(RateLimitEntry.id)).where(
                    RateLimitEntry.user_id == user.id,
                    RateLimitEntry.action_type == action_type,
                    RateLimitEntry.timestamp > cutoff
                )
            )
            return result.scalar() or 0
    
    async def cleanup_old_rate_limits(self, hours: int = 1) -> int:
        """Clean up old rate limit entries"""
        async with self.session() as session:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            result = await session.execute(
                delete(RateLimitEntry).where(RateLimitEntry.timestamp < cutoff)
            )
            await session.commit()
            return result.rowcount
    
    # ==================== SECURITY LOGGING ====================
    
    async def log_security_event(
        self,
        user_discord_id: int,
        event_type: str,
        description: str,
        severity: str = "medium",
        action_taken: str = None
    ) -> None:
        """Log a security event"""
        async with self.session() as session:
            log = SecurityLog(
                user_discord_id=user_discord_id,
                event_type=event_type,
                description=description,
                severity=severity,
                action_taken=action_taken
            )
            session.add(log)
            await session.commit()
    
    # ==================== STATISTICS ====================
    
    async def get_total_users(self) -> int:
        """Get total user count"""
        async with self.session() as session:
            result = await session.execute(select(func.count(User.id)))
            return result.scalar() or 0
    
    async def get_total_balance(self) -> float:
        """Get sum of all user balances"""
        async with self.session() as session:
            result = await session.execute(select(func.sum(User.balance)))
            return result.scalar() or 0.0
    
    async def get_recent_transactions(self, limit: int = 10) -> List[Transaction]:
        """Get recent transactions"""
        async with self.session() as session:
            result = await session.execute(
                select(Transaction)
                .order_by(Transaction.timestamp.desc())
                .limit(limit)
                .options(selectinload(Transaction.user))
            )
            return list(result.scalars().all())
    
    async def update_bot_stat(self, stat_name: str, stat_value: float) -> None:
        """Update a bot statistic"""
        async with self.session() as session:
            result = await session.execute(
                select(BotStats).where(BotStats.stat_name == stat_name)
            )
            stat = result.scalar_one_or_none()
            
            if stat:
                stat.stat_value = stat_value
            else:
                stat = BotStats(stat_name=stat_name, stat_value=stat_value)
                session.add(stat)
            
            await session.commit()
    
    async def get_bot_stat(self, stat_name: str) -> Optional[float]:
        """Get a bot statistic"""
        async with self.session() as session:
            result = await session.execute(
                select(BotStats).where(BotStats.stat_name == stat_name)
            )
            stat = result.scalar_one_or_none()
            return stat.stat_value if stat else None


# Global database instance
db = DatabaseService()
