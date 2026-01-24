"""
Database Service - Async SQLAlchemy operations
"""

import json
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Any
from contextlib import asynccontextmanager
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.orm import selectinload

from src.models.database import (
    Base, User, Role, UserRole, Transaction, ServerEconomy, SalaryChange,
    CaseUse, OfficerLog, ChannelConfig, GameSession, PvPGameSession, VoiceSession,
    RateLimitEntry, SecurityLog, BotStats, TransactionType, RoleType, GameType, LogType
)
from src.utils.helpers import calculate_tax
from src.services.economy_logger import economy_logger, EconomyAction


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
        # In-process locks to serialize operations on specific user IDs
        # This prevents lost-updates in SQLite testing environments
        # where row-level SELECT...FOR UPDATE locking isn't effective.
        self._locks: dict[int, asyncio.Lock] = {}
    
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
                # Check if there are pending changes before committing
                if session.new or session.dirty or session.deleted:
                    await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def _acquire_locks(self, ids: List[int]):
        """Acquire in-process asyncio locks for a list of integer IDs.

        Locks are acquired in ascending order to prevent deadlocks when
        multiple IDs are requested concurrently.
        """
        ids_sorted = sorted(set(ids))
        locks = []
        try:
            for i in ids_sorted:
                lock = self._locks.get(i)
                if lock is None:
                    lock = asyncio.Lock()
                    self._locks[i] = lock
                locks.append(lock)
            for l in locks:
                await l.acquire()
            yield
        finally:
            for l in reversed(locks):
                try:
                    l.release()
                except RuntimeError:
                    # ignore release errors if lock is not acquired
                    pass
    
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
    
    async def transfer_money(
        self,
        sender_id: int,
        recipient_id: int,
        amount: float,
        description: str = None
    ) -> dict:
        """
        Atomically transfer money from sender to recipient with tax.
        Returns dict with success status and details.
        """
        if amount <= 0:
            return {"success": False, "error": "Amount must be positive"}
        
        # Acquire in-process locks for sender and recipient to avoid
        # lost-updates in environments (like SQLite testing) where
        # SELECT ... FOR UPDATE may not provide sufficient row-level locking.
        async with self._acquire_locks([sender_id, recipient_id]):
            async with self.session() as session:
                # Sort IDs to ensure consistent locking order (Deadlock Prevention)
                first_id, second_id = sorted([sender_id, recipient_id])

            # Lock both users in consistent order
            stmt = select(User).where(User.discord_id.in_([first_id, second_id])).order_by(User.discord_id).with_for_update()
            result = await session.execute(stmt)
            users = {u.discord_id: u for u in result.scalars().all()}

            sender = users.get(sender_id)
            recipient = users.get(recipient_id)

            # Create if missing
            if not sender:
                sender = User(discord_id=sender_id)
                session.add(sender)

            if not recipient:
                recipient = User(discord_id=recipient_id)
                session.add(recipient)

            if not sender or not recipient:
                await session.flush()
                # If newly created, they are locked by insertion

            if sender.balance < amount:
                return {"success": False, "error": "Insufficient funds"}

            # Get Economy for Tax
            economy_res = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = economy_res.scalar_one_or_none()
            if not economy:
                economy = ServerEconomy()
                session.add(economy)
                await session.flush()

            # Calculate Tax
            net_amount, tax_amount = calculate_tax(amount, economy.tax_rate)

            # Update Sender
            sender_before = sender.balance
            sender.balance -= amount
            sender_after = sender.balance

            tx_sender = Transaction(
                user_id=sender.id,
                amount=-amount,
                transaction_type=TransactionType.TRANSFER_OUT,
                tax_amount=tax_amount,
                before_balance=sender_before,
                after_balance=sender_after,
                description=description or f"Transfer to {recipient_id}",
                related_user_id=recipient.id
            )
            session.add(tx_sender)

            # Update Recipient
            recipient_before = recipient.balance
            recipient.balance += net_amount
            recipient_after = recipient.balance

            tx_recipient = Transaction(
                user_id=recipient.id,
                amount=net_amount,
                transaction_type=TransactionType.TRANSFER_IN,
                tax_amount=0,
                before_balance=recipient_before,
                after_balance=recipient_after,
                description=description or f"Transfer from {sender_id}",
                related_user_id=sender.id
            )
            session.add(tx_recipient)

            # Update Economy (Tax)
            if tax_amount > 0:
                economy.total_taxes_collected += tax_amount
                economy.total_budget += tax_amount

            await session.commit()

            return {
                "success": True,
                "sender_before": sender_before,
                "sender_after": sender_after,
                "recipient_before": recipient_before,
                "recipient_after": recipient_after,
                "net_amount": net_amount,
                "tax": tax_amount,
                "budget_before": economy.total_budget - tax_amount,
                "budget_after": economy.total_budget
            }

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
                # commit is handled by context manager
    
    async def set_soldier_value(self, value: float) -> Tuple[float, float, int]:
        """Set soldier value and recalculate budget. Returns (old_value, new_value, soldier_count)"""
        async with self.session() as session:
            result = await session.execute(select(ServerEconomy))
            economy = result.scalar_one_or_none()
            
            if economy:
                old_value = economy.soldier_value
                
                # Count soldiers
                soldier_count_result = await session.execute(
                    select(func.count(User.id)).where(User.is_soldier == True)
                )
                soldier_count = soldier_count_result.scalar() or 0
                
                # Update economy
                economy.soldier_value = value
                
                # commit is handled by context manager
                return old_value, value, soldier_count
            
            return 0, value, 0
    
    async def pay_from_budget_atomic(
        self,
        discord_id: int,
        gross_amount: float,
        net_amount: float,
        tax_amount: float,
        transaction_type: TransactionType,
        description: str = None
    ) -> dict:
        """
        Atomically pay a user from server budget with tax handling.
        Budget pays gross_amount, user receives net_amount, tax stays in budget.
        Returns dict with success status and details.
        """
        async with self.session() as session:
            # Lock economy first
            economy_result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = economy_result.scalar_one_or_none()
            
            if not economy:
                return {"success": False, "error": "Economy not initialized"}
            
            # Check budget
            if economy.total_budget < net_amount:
                return {"success": False, "error": "Insufficient server budget"}
            
            # Lock user
            user_result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                user = User(discord_id=discord_id)
                session.add(user)
                await session.flush()
            
            before_balance = user.balance
            before_budget = economy.total_budget
            
            # Update balances atomically
            user.balance += net_amount
            economy.total_budget -= net_amount  # Only net goes out, tax stays
            economy.total_rewards_paid += gross_amount
            
            if tax_amount > 0:
                economy.total_taxes_collected += tax_amount
            
            # Log transaction
            transaction = Transaction(
                user_id=user.id,
                amount=net_amount,
                transaction_type=transaction_type,
                tax_amount=tax_amount,
                before_balance=before_balance,
                after_balance=user.balance,
                description=description
            )
            session.add(transaction)
            
            await session.commit()
            
            return {
                "success": True,
                "before_balance": before_balance,
                "after_balance": user.balance,
                "before_budget": before_budget,
                "after_budget": economy.total_budget,
                "net_amount": net_amount,
                "tax": tax_amount
            }
    
    async def admin_adjust_balance_atomic(
        self,
        discord_id: int,
        amount: float,
        transaction_type: TransactionType,
        description: str = None
    ) -> dict:
        """
        Atomically adjust user balance with budget synchronization.
        For admin operations (addbalance, fine, confiscate).
        If amount > 0: pay from budget to user
        If amount < 0: take from user and return to budget
        Returns dict with success status and details.
        """
        async with self.session() as session:
            # Lock economy first
            economy_result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = economy_result.scalar_one_or_none()
            
            if not economy:
                return {"success": False, "error": "Economy not initialized"}
            
            # Check budget if adding money
            if amount > 0 and economy.total_budget < amount:
                return {"success": False, "error": "Insufficient server budget"}
            
            # Lock user
            user_result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                user = User(discord_id=discord_id)
                session.add(user)
                await session.flush()
            
            # Check user balance if removing money
            if amount < 0 and user.balance < abs(amount):
                return {"success": False, "error": "Insufficient user balance"}
            
            before_balance = user.balance
            before_budget = economy.total_budget
            
            # Update balances atomically
            user.balance += amount
            
            if amount > 0:
                # Admin gives money: deduct from budget, track rewards
                economy.total_budget -= amount
                economy.total_rewards_paid += amount
            else:
                # Admin takes money: return to budget
                economy.total_budget += abs(amount)
            
            # Log transaction
            transaction = Transaction(
                user_id=user.id,
                amount=amount,
                transaction_type=transaction_type,
                before_balance=before_balance,
                after_balance=user.balance,
                description=description
            )
            session.add(transaction)
            
            await session.commit()
            
            return {
                "success": True,
                "before_balance": before_balance,
                "after_balance": user.balance,
                "before_budget": before_budget,
                "after_budget": economy.total_budget
            }
    
    async def place_bet_atomic(
        self,
        discord_id: int,
        bet_amount: float,
        description: str = "Game bet"
    ) -> dict:
        """
        Atomically deduct bet from user and add to server budget.
        Returns dict with success status and balance details.
        """
        async with self.session() as session:
            # Lock user first
            user_result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return {"success": False, "error": "User not found"}
            
            if user.balance < bet_amount:
                return {"success": False, "error": "Insufficient funds"}
            
            # Lock economy
            economy_result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = economy_result.scalar_one_or_none()
            
            if not economy:
                return {"success": False, "error": "Economy not initialized"}
            
            before_balance = user.balance
            before_budget = economy.total_budget
            
            # Atomically update both
            user.balance -= bet_amount
            economy.total_budget += bet_amount
            
            # Log transaction
            transaction = Transaction(
                user_id=user.id,
                amount=-bet_amount,
                transaction_type=TransactionType.GAME_LOSS,
                tax_amount=0,
                before_balance=before_balance,
                after_balance=user.balance,
                description=description
            )
            session.add(transaction)
            
            await session.commit()
            
            return {
                "success": True,
                "before_balance": before_balance,
                "after_balance": user.balance,
                "before_budget": before_budget,
                "after_budget": economy.total_budget
            }
    
    async def resolve_game_win_atomic(
        self,
        discord_id: int,
        bet_amount: float,
        profit_amount: float,
        tax_rate: float,
        description: str = "Game win"
    ) -> dict:
        """
        Atomically resolve a game win: pay back bet + profit (minus tax).
        Tax stays in budget.
        Returns dict with success status and details.
        """
        async with self.session() as session:
            # Lock user
            user_result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return {"success": False, "error": "User not found"}
            
            # Lock economy
            economy_result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = economy_result.scalar_one_or_none()
            
            if not economy:
                return {"success": False, "error": "Economy not initialized"}
            
            # Calculate tax on profit only
            tax_amount = profit_amount * (tax_rate / 100)
            net_profit = profit_amount - tax_amount
            total_payout = bet_amount + net_profit
            
            before_balance = user.balance
            before_budget = economy.total_budget
            
            # Check budget
            if economy.total_budget < total_payout:
                return {"success": False, "error": "Insufficient server budget"}
            
            # Atomically update
            user.balance += total_payout
            economy.total_budget -= total_payout
            economy.total_rewards_paid += total_payout
            
            if tax_amount > 0:
                economy.total_taxes_collected += tax_amount
            
            # Log transaction
            transaction = Transaction(
                user_id=user.id,
                amount=total_payout,
                transaction_type=TransactionType.GAME_WIN,
                tax_amount=tax_amount,
                before_balance=before_balance,
                after_balance=user.balance,
                description=description
            )
            session.add(transaction)
            
            await session.commit()
            
            return {
                "success": True,
                "before_balance": before_balance,
                "after_balance": user.balance,
                "before_budget": before_budget,
                "after_budget": economy.total_budget,
                "total_payout": total_payout,
                "net_profit": net_profit,
                "tax": tax_amount
            }
    
    async def add_taxes_collected(self, amount: float, add_to_budget: bool = True) -> None:
        """Add to total taxes collected. Option to skip adding to budget (if already there)."""
        async with self.session() as session:
            result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = result.scalar_one_or_none()
            
            if economy:
                economy.total_taxes_collected += amount
                if add_to_budget:
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
    
    async def purchase_role_with_tax(
        self, 
        discord_id: int, 
        role_discord_id: int,
        tax_rate: float
    ) -> Tuple[bool, str, float]:
        """
        Purchase a role with tax atomically.
        Returns (success, message, tax_amount)
        Tax goes to budget, role price also goes to budget.
        """
        async with self.session() as session:
            # Get user with lock
            user_result = await session.execute(
                select(User).where(User.discord_id == discord_id).with_for_update()
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return False, "User not found", 0
            
            # Get role
            role_result = await session.execute(
                select(Role).where(Role.discord_id == role_discord_id)
            )
            role = role_result.scalar_one_or_none()
            
            if not role:
                return False, "Role not found", 0
            
            if not role.is_available:
                return False, "Role is not available", 0
            
            # Check if already owned
            existing = await session.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id
                )
            )
            if existing.scalar_one_or_none():
                return False, "You already own this role", 0
            
            # Calculate total with tax
            tax_amount = role.price * (tax_rate / 100)
            total_cost = role.price + tax_amount
            
            # Check balance for total
            if user.balance < total_cost:
                return False, f"Insufficient balance. Need ${total_cost:.2f}", 0
            
            # Lock economy
            economy_result = await session.execute(
                select(ServerEconomy).with_for_update()
            )
            economy = economy_result.scalar_one_or_none()
            
            # Process purchase atomically
            before_balance = user.balance
            user.balance -= total_cost
            
            user_role = UserRole(user_id=user.id, role_id=role.id)
            session.add(user_role)
            
            # Add to budget: role price + tax
            if economy:
                economy.total_budget += total_cost
                economy.total_taxes_collected += tax_amount
            
            # Log transaction (full amount including tax)
            transaction = Transaction(
                user_id=user.id,
                amount=-total_cost,
                transaction_type=TransactionType.ROLE_PURCHASE,
                tax_amount=tax_amount,
                before_balance=before_balance,
                after_balance=user.balance,
                description=f"Purchased role: {role.name} (incl. tax)"
            )
            session.add(transaction)
            
            await session.commit()
            return True, f"Successfully purchased {role.name}!", tax_amount
    
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
                .limit(1)
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

    async def create_pvp_game_session(
        self,
        game_id: str,
        player_a_id: int,
        player_b_id: int,
        player_a_bet: float,
        player_b_bet: float,
        state: str,
        shoe_state: str,
        player_a_hand: str,
        player_b_hand: str,
        dealer_hand: str,
        ttl_minutes: int = 15
    ) -> PvPGameSession:
        """Create a new PvP game session"""
        async with self.session() as session:
            # Check for existing active sessions for these players?
            # Ideally done before calling this, but we can enforce uniqueness if needed.

            # Use get_or_create to ensure user records exist
            user_a = await self.get_or_create_user(player_a_id)
            user_b = await self.get_or_create_user(player_b_id)

            game = PvPGameSession(
                id=game_id,
                player_a_id=user_a.id,
                player_b_id=user_b.id,
                player_a_bet=player_a_bet,
                player_b_bet=player_b_bet,
                state=state,
                shoe_state=shoe_state,
                player_a_hand=player_a_hand,
                player_b_hand=player_b_hand,
                dealer_hand=dealer_hand,
                expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes)
            )
            session.add(game)
            await session.commit()
            return game

    async def get_pvp_game_session(self, game_id: str, for_update: bool = False) -> Optional[PvPGameSession]:
        """Get PvP game session by ID"""
        async with self.session() as session:
            stmt = select(PvPGameSession).where(PvPGameSession.id == game_id)
            if for_update:
                stmt = stmt.with_for_update()
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def start_pvp_game_atomic(
        self,
        game_id: str,
        player_a_id: int,
        player_b_id: int,
        bet_amount: float,
        state: str,
        shoe_state: str,
        player_a_hand: str,
        player_b_hand: str,
        dealer_hand: str,
        ttl_minutes: int = 15
    ) -> Tuple[bool, str, Optional[PvPGameSession]]:
        """Atomically deduct bets and create PvP game session"""
        async with self.session() as session:
            # Sort IDs to avoid deadlocks
            first_id, second_id = sorted([player_a_id, player_b_id])

            # Lock users
            stmt = select(User).where(User.discord_id.in_([first_id, second_id])).order_by(User.discord_id).with_for_update()
            user_result = await session.execute(stmt)
            users = {u.discord_id: u for u in user_result.scalars().all()}

            user_a = users.get(player_a_id)
            user_b = users.get(player_b_id)

            if not user_a:
                # Should create if missing? Usually callers ensure users exist.
                # If missing here, it's safer to fail.
                return False, f"User {player_a_id} not found", None
            if not user_b:
                return False, f"User {player_b_id} not found", None

            if user_a.balance < bet_amount:
                return False, f"<@{player_a_id}> has insufficient funds", None
            if user_b.balance < bet_amount:
                return False, f"<@{player_b_id}> has insufficient funds", None

            # Deduct funds
            # Lock Economy
            econ_result = await session.execute(select(ServerEconomy).with_for_update())
            economy = econ_result.scalar_one_or_none()
            if not economy:
                 economy = ServerEconomy()
                 session.add(economy)

            # Update balances and logs
            user_a.balance -= bet_amount
            tx_a = Transaction(
                user_id=user_a.id,
                amount=-bet_amount,
                transaction_type=TransactionType.GAME_LOSS,
                tax_amount=0,
                before_balance=user_a.balance + bet_amount,
                after_balance=user_a.balance,
                description="PvP Blackjack Bet"
            )
            session.add(tx_a)

            user_b.balance -= bet_amount
            tx_b = Transaction(
                user_id=user_b.id,
                amount=-bet_amount,
                transaction_type=TransactionType.GAME_LOSS,
                tax_amount=0,
                before_balance=user_b.balance + bet_amount,
                after_balance=user_b.balance,
                description="PvP Blackjack Bet"
            )
            session.add(tx_b)

            economy.total_budget += (bet_amount * 2)

            # Log economy event for PvP bet placement
            try:
                # use economy_logger to record bet placement as GAME_BET
                await economy_logger.log(
                    EconomyAction.GAME_BET,
                    amount=bet_amount * 2,
                    before_balance=None,
                    after_balance=None,
                    before_budget=economy.total_budget - (bet_amount * 2),
                    after_budget=economy.total_budget,
                    description=f"PvP Blackjack bets placed: {player_a_id} & {player_b_id}",
                    details={
                        "Player A": f"<@{player_a_id}> (${bet_amount})",
                        "Player B": f"<@{player_b_id}> (${bet_amount})"
                    },
                    source="PvP Start"
                )
            except Exception:
                # Logging failure should not block game start
                pass

            # Create Session
            game = PvPGameSession(
                id=game_id,
                player_a_id=user_a.id,
                player_b_id=user_b.id,
                player_a_bet=bet_amount,
                player_b_bet=bet_amount,
                state=state,
                shoe_state=shoe_state,
                player_a_hand=player_a_hand,
                player_b_hand=player_b_hand,
                dealer_hand=dealer_hand,
                expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes)
            )
            session.add(game)

            await session.commit()
            return True, "Game started", game

    async def update_pvp_game_session(
        self,
        game_id: str,
        state: str,
        shoe_state: str,
        player_a_hand: str,
        player_b_hand: str,
        dealer_hand: str,
        current_turn: Optional[int] = None,
        message_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        check_funds_for_player: Optional[int] = None,
        deduct_amount: float = 0.0
    ) -> Tuple[bool, str]:
        """
        Update PvP game session state.
        Optionally check funds and deduct amount (for Double/Split).
        """
        async with self.session() as session:
            # If deducting funds, we need to lock the session AND the user
            game = None
            if check_funds_for_player:
                # Lock session first
                result = await session.execute(
                    select(PvPGameSession).where(PvPGameSession.id == game_id).with_for_update()
                )
                game = result.scalar_one_or_none()

                if not game:
                    return False, "Game not found"

                # Check turn validity to prevent race conditions?
                # Assuming caller logic handled turn check, but DB check is safer.

                # Lock User
                user_res = await session.execute(
                    select(User).where(User.discord_id == check_funds_for_player).with_for_update()
                )
                user = user_res.scalar_one_or_none()

                if not user:
                    return False, "User not found"

                if user.balance < deduct_amount:
                    return False, "Insufficient funds"

                # Deduct funds
                # Lock Economy
                econ_res = await session.execute(select(ServerEconomy).with_for_update())
                economy = econ_res.scalar_one_or_none()
                if not economy: economy = ServerEconomy(); session.add(economy)

                user.balance -= deduct_amount
                economy.total_budget += deduct_amount

                # Update Game Session bet amounts
                # If player A, update player_a_bet
                if user.discord_id == game.player_a_id: # Note: player_a_id is User.id in DB model, wait.
                    # In PvPGameSession model: player_a_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
                    # user_res above fetched User by discord_id. user.id is the internal ID.
                    # So we compare user.id with game.player_a_id
                    pass

                # We need to know which player this is to update the correct bet column
                if user.id == game.player_a_id:
                    game.player_a_bet += deduct_amount
                elif user.id == game.player_b_id:
                    game.player_b_bet += deduct_amount

                # Log transaction
                tx = Transaction(
                    user_id=user.id,
                    amount=-deduct_amount,
                    transaction_type=TransactionType.GAME_LOSS,
                    tax_amount=0,
                    before_balance=user.balance + deduct_amount,
                    after_balance=user.balance,
                    description="PvP Blackjack Extra Bet (Double/Split)"
                )
                session.add(tx)

            else:
                # Just update game state
                result = await session.execute(
                    select(PvPGameSession).where(PvPGameSession.id == game_id)
                )
                game = result.scalar_one_or_none()
                if not game:
                    return False, "Game not found"

            # Apply updates
            game.state = state
            game.shoe_state = shoe_state
            game.player_a_hand = player_a_hand
            game.player_b_hand = player_b_hand
            game.dealer_hand = dealer_hand
            if current_turn is not None:
                game.current_turn = current_turn
            if message_id is not None:
                game.message_id = message_id
            if channel_id is not None:
                game.channel_id = channel_id

            await session.commit()
            return True, "Updated"

    async def delete_pvp_game_session(self, game_id: str) -> None:
        """Delete PvP game session"""
        async with self.session() as session:
             await session.execute(
                 delete(PvPGameSession).where(PvPGameSession.id == game_id)
             )
             await session.commit()

    async def resolve_pvp_payout(
        self,
        player_a_id: int,
        player_b_id: int,
        player_a_bet: float,
        player_b_bet: float,
        results: dict  # Map player_id -> net_profit (can be negative)
    ) -> dict:
        """
        Atomically resolve PvP payouts.
        results: {player_id: net_profit_excluding_stake}
        Example:
          Win 100 bet -> profit 100. Payout = 200 (100 stake + 100 profit).
          Lose 100 bet -> profit -100. Payout = 0.
          Push 100 bet -> profit 0. Payout = 100.

        This method assumes bets were ALREADY deducted.
        It calculates tax on POSITIVE profit.
        It updates user balances and server budget.
        """
        async with self.session() as session:
            # Lock users
            stmt = select(User).where(User.discord_id.in_([player_a_id, player_b_id])).order_by(User.discord_id).with_for_update()
            user_result = await session.execute(stmt)
            users = {u.discord_id: u for u in user_result.scalars().all()}

            # Lock economy
            econ_result = await session.execute(select(ServerEconomy).with_for_update())
            economy = econ_result.scalar_one_or_none()
            if not economy:
                 economy = ServerEconomy()
                 session.add(economy)

            payout_summary = {}

            for pid, bet_amount in [(player_a_id, player_a_bet), (player_b_id, player_b_bet)]:
                user = users.get(pid)
                if not user:
                    continue # Should not happen

                # Get raw result (winnings - losses)
                # Results dict contains the 'net change' from the game logic perspective.
                # E.g. blackjack win 1.5x on 100 -> +150
                # Loss -> -100
                # Push -> 0

                raw_profit = results.get(pid, 0.0)

                tax = 0.0
                payout = 0.0

                # If raw_profit is positive, we tax it.
                # Payout = Bet + Raw_Profit - Tax
                # But wait, logic:
                # If I bet 100 and win 150. Raw profit is 150.
                # Total returned to user = 100 (original) + 150 (win).
                # Tax is on 150.

                # If I lose 100. Raw profit is -100.
                # Total returned = 100 - 100 = 0.

                # If Push. Raw profit 0.
                # Total returned = 100 + 0 = 100.

                # Calculate return amount
                base_return = bet_amount + raw_profit

                if raw_profit > 0:
                     # Calculate tax on the profit portion
                     _, tax = calculate_tax(raw_profit, economy.tax_rate)
                     final_return = base_return - tax

                     # Update Economy
                     economy.total_taxes_collected += tax
                     # Profit comes from budget?
                     # In closed loop:
                     # Bet was added to budget when placed.
                     # Winnings are removed from budget.
                     # Tax stays in budget.

                     # So we remove (final_return) from budget.
                     # Wait, if I bet 100, budget +100.
                     # I win 150. Total return 250. Tax 15 (10% of 150). Net return 235.
                     # Budget change: +100 (bet) - 235 (payout) = -135.
                     # Net effect on budget: -135.
                     # Player profit: +135.
                     # Tax collected: 15.

                     # Is tax 'staying in budget' correct? Yes.
                     # If no tax, return 250. Budget -150. Player +150.

                     economy.total_budget -= final_return
                     economy.total_rewards_paid += final_return # Track payouts

                     # Update User
                     user.balance += final_return

                     # Log
                     tx = Transaction(
                        user_id=user.id,
                        amount=final_return,
                        transaction_type=TransactionType.GAME_WIN,
                        tax_amount=tax,
                        before_balance=user.balance - final_return,
                        after_balance=user.balance,
                        description=f"PvP Blackjack Win (Profit ${raw_profit:.2f})"
                     )
                     session.add(tx)

                     # Log game win event for this player
                     try:
                         await economy_logger.log_game(
                             game_name="PvP Blackjack",
                             user_id=user.discord_id,
                             user_name=str(user.discord_id),
                             bet=bet_amount,
                             result="WIN",
                             winnings=final_return,
                             profit=raw_profit - tax,
                             user_before=(user.balance - final_return),
                             user_after=user.balance,
                             budget_before=(economy.total_budget + final_return - tax),
                             budget_after=economy.total_budget,
                             details={
                                 "Raw Profit": f"${raw_profit:,.2f}",
                                 "Tax": f"${tax:,.2f}",
                                 "Final Return": f"${final_return:,.2f}"
                             }
                         )
                     except Exception:
                         pass

                elif raw_profit < 0:
                    # Loss path. base_return may be > 0 for partial returns (surrender/etc).
                    final_return = base_return

                    if final_return > 0:
                        # Partial return (e.g., surrender) — move funds from budget back to user
                        economy.total_budget -= final_return
                        user.balance += final_return

                        tx = Transaction(
                            user_id=user.id,
                            amount=final_return,
                            transaction_type=TransactionType.GAME_WIN,  # Technically a return
                            tax_amount=0,
                            before_balance=user.balance - final_return,
                            after_balance=user.balance,
                            description=f"PvP Blackjack Return (Loss/Surrender)"
                        )
                        session.add(tx)

                        try:
                            await economy_logger.log_game(
                                game_name="PvP Blackjack",
                                user_id=user.discord_id,
                                user_name=str(user.discord_id),
                                bet=bet_amount,
                                result="RETURN",
                                winnings=final_return,
                                profit=raw_profit,
                                user_before=(user.balance - final_return),
                                user_after=user.balance,
                                budget_before=(economy.total_budget + final_return),
                                budget_after=economy.total_budget,
                                details={"Note": "Partial return / surrender or loss-with-refund"}
                            )
                        except Exception:
                            pass
                    else:
                        # Full loss (no return). Log LOSS so it appears in the economy channel.
                        # Note: Bet was already deducted at game start, so we show balance change from that point
                        balance_before_bet = user.balance + bet_amount  # What balance was BEFORE bet was placed
                        try:
                            await economy_logger.log_game(
                                game_name="PvP Blackjack",
                                user_id=user.discord_id,
                                user_name=str(user.discord_id),
                                bet=bet_amount,
                                result="LOSS",
                                winnings=0,
                                profit=-bet_amount,  # Show actual loss amount
                                user_before=balance_before_bet,  # Balance before bet was placed
                                user_after=user.balance,  # Current balance (after bet was taken)
                                budget_before=economy.total_budget - bet_amount,  # Budget before bet
                                budget_after=economy.total_budget,  # Budget now includes lost bet
                                details={"Note": "Full loss - bet was deducted at game start"}
                            )
                        except Exception:
                            pass

                else:
                     # Push (0 profit)
                     final_return = bet_amount
                     economy.total_budget -= final_return
                     user.balance += final_return

                     tx = Transaction(
                        user_id=user.id,
                        amount=final_return,
                        transaction_type=TransactionType.GAME_WIN,
                        tax_amount=0,
                        before_balance=user.balance - final_return,
                        after_balance=user.balance,
                        description="PvP Blackjack Push"
                     )
                     session.add(tx)
                     try:
                         await economy_logger.log_game(
                             game_name="PvP Blackjack",
                             user_id=user.discord_id,
                             user_name=str(user.discord_id),
                             bet=bet_amount,
                             result="PUSH",
                             winnings=final_return,
                             profit=0,
                             user_before=(user.balance - final_return),
                             user_after=user.balance,
                             budget_before=(economy.total_budget + final_return),
                             budget_after=economy.total_budget,
                             details={"Note": "Push - refund"}
                         )
                     except Exception:
                         pass

                payout_summary[pid] = {
                    "payout": final_return if 'final_return' in locals() else 0.0,
                    "tax": tax,
                    "profit": raw_profit
                }

            await session.commit()
            return payout_summary

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
    
    async def get_economy_stats(self) -> dict:
        """Get comprehensive economy statistics for admin panel"""
        async with self.session() as session:
            # Active voice sessions with role breakdown
            sessions_result = await session.execute(
                select(VoiceSession)
                .where(VoiceSession.is_active == True)
                .options(selectinload(VoiceSession.user))
            )
            sessions = list(sessions_result.scalars().all())
            
            soldiers_in_voice = 0
            sergeants_in_voice = 0
            officers_in_voice = 0
            
            for vs in sessions:
                if vs.user:
                    if vs.user.is_officer:
                        officers_in_voice += 1
                    elif vs.user.is_sergeant:
                        sergeants_in_voice += 1
                    elif vs.user.is_soldier:
                        soldiers_in_voice += 1
            
            # User counts by role
            soldier_count = await session.execute(
                select(func.count(User.id)).where(User.is_soldier == True)
            )
            sergeant_count = await session.execute(
                select(func.count(User.id)).where(User.is_sergeant == True)
            )
            officer_count = await session.execute(
                select(func.count(User.id)).where(User.is_officer == True)
            )
            
            # Game statistics - wins and losses today
            today = datetime.utcnow().date()
            
            game_wins_result = await session.execute(
                select(func.count(Transaction.id), func.sum(Transaction.amount))
                .where(
                    Transaction.transaction_type == TransactionType.GAME_WIN,
                    func.date(Transaction.timestamp) == today
                )
            )
            game_wins_row = game_wins_result.one()
            game_wins_count = game_wins_row[0] or 0
            game_wins_amount = game_wins_row[1] or 0.0
            
            game_losses_result = await session.execute(
                select(func.count(Transaction.id), func.sum(Transaction.amount))
                .where(
                    Transaction.transaction_type == TransactionType.GAME_LOSS,
                    func.date(Transaction.timestamp) == today
                )
            )
            game_losses_row = game_losses_result.one()
            game_losses_count = game_losses_row[0] or 0
            game_losses_amount = abs(game_losses_row[1] or 0.0)
            
            # Recent admin actions (last 10)
            admin_types = [
                TransactionType.ADMIN_ADD, 
                TransactionType.ADMIN_SET,
                TransactionType.FINE,
                TransactionType.CONFISCATE
            ]
            admin_actions_result = await session.execute(
                select(Transaction)
                .where(Transaction.transaction_type.in_(admin_types))
                .order_by(Transaction.timestamp.desc())
                .limit(10)
                .options(selectinload(Transaction.user))
            )
            admin_actions = list(admin_actions_result.scalars().all())
            
            return {
                "active_sessions": len(sessions),
                "soldiers_in_voice": soldiers_in_voice,
                "sergeants_in_voice": sergeants_in_voice,
                "officers_in_voice": officers_in_voice,
                "total_soldiers": soldier_count.scalar() or 0,
                "total_sergeants": sergeant_count.scalar() or 0,
                "total_officers": officer_count.scalar() or 0,
                "game_wins_today": game_wins_count,
                "game_wins_amount": game_wins_amount,
                "game_losses_today": game_losses_count,
                "game_losses_amount": game_losses_amount,
                "admin_actions": admin_actions
            }

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
    
    async def get_24h_budget_change(self) -> float:
        """Get budget change over the last 24 hours from transactions"""
        async with self.session() as session:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            
            # Budget increases: taxes, game losses, fines, confiscations
            budget_in_types = [
                TransactionType.TAX, 
                TransactionType.GAME_LOSS, 
                TransactionType.FINE, 
                TransactionType.CONFISCATE,
                TransactionType.MUTE_PENALTY
            ]
            
            in_result = await session.execute(
                select(func.sum(func.abs(Transaction.amount)))
                .where(
                    Transaction.transaction_type.in_(budget_in_types),
                    Transaction.timestamp > cutoff
                )
            )
            budget_in = in_result.scalar() or 0.0
            
            # Also add tax amounts collected
            tax_result = await session.execute(
                select(func.sum(Transaction.tax_amount))
                .where(Transaction.timestamp > cutoff)
            )
            tax_collected = tax_result.scalar() or 0.0
            
            # Budget decreases: salaries, rewards, game wins, case rewards, admin adds
            budget_out_types = [
                TransactionType.SALARY,
                TransactionType.MASTER_BONUS,
                TransactionType.GAME_WIN,
                TransactionType.CASE_REWARD,
                TransactionType.OFFICER_REWARD,
                TransactionType.PB_10H_BONUS,
                TransactionType.ADMIN_ADD
            ]
            
            out_result = await session.execute(
                select(func.sum(Transaction.amount))
                .where(
                    Transaction.transaction_type.in_(budget_out_types),
                    Transaction.timestamp > cutoff
                )
            )
            budget_out = out_result.scalar() or 0.0
            
            # Net change: in - out + taxes
            return budget_in + tax_collected - budget_out
    
    async def get_24h_balance_change(self) -> float:
        """Get total user balance change over the last 24 hours"""
        async with self.session() as session:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            
            # Sum all balance changes (amount - tax_amount for each transaction)
            result = await session.execute(
                select(func.sum(Transaction.amount - Transaction.tax_amount))
                .where(Transaction.timestamp > cutoff)
            )
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

    # ==================== FAQ SYSTEM ====================
    
    async def create_faq_panel(
        self,
        name: str,
        title: str,
        guild_id: int,
        created_by: int,
        description: str = None,
        color: int = 0x3498DB,
        footer_text: str = None,
        thumbnail_url: str = None
    ) -> dict:
        """Create a new FAQ panel"""
        from src.models.database import FAQPanel
        
        async with self.session() as session:
            # Check if name already exists for this guild
            result = await session.execute(
                select(FAQPanel).where(
                    FAQPanel.name == name,
                    FAQPanel.guild_id == guild_id
                )
            )
            if result.scalar_one_or_none():
                return {"success": False, "error": f"Panel with name '{name}' already exists"}
            
            panel = FAQPanel(
                name=name,
                title=title,
                description=description,
                color=color,
                footer_text=footer_text,
                thumbnail_url=thumbnail_url,
                guild_id=guild_id,
                created_by=created_by
            )
            session.add(panel)
            await session.commit()
            await session.refresh(panel)
            
            return {
                "success": True,
                "panel": {
                    "id": panel.id,
                    "name": panel.name,
                    "title": panel.title
                }
            }
    
    async def get_faq_panel_by_name(self, name: str, guild_id: int) -> Optional[dict]:
        """Get a FAQ panel by name"""
        from src.models.database import FAQPanel, FAQEntry
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQPanel).where(
                    FAQPanel.name == name,
                    FAQPanel.guild_id == guild_id
                )
            )
            panel = result.scalar_one_or_none()
            
            if not panel:
                return None
            
            # Count entries
            entry_count = await session.execute(
                select(func.count(FAQEntry.id)).where(FAQEntry.panel_id == panel.id)
            )
            
            return {
                "id": panel.id,
                "name": panel.name,
                "title": panel.title,
                "description": panel.description,
                "color": panel.color,
                "footer_text": panel.footer_text,
                "thumbnail_url": panel.thumbnail_url,
                "message_id": panel.message_id,
                "channel_id": panel.channel_id,
                "guild_id": panel.guild_id,
                "entry_count": entry_count.scalar() or 0
            }
    
    async def get_faq_panel_by_id(self, panel_id: int) -> Optional[dict]:
        """Get a FAQ panel by ID"""
        from src.models.database import FAQPanel
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQPanel).where(FAQPanel.id == panel_id)
            )
            panel = result.scalar_one_or_none()
            
            if not panel:
                return None
            
            return {
                "id": panel.id,
                "name": panel.name,
                "title": panel.title,
                "description": panel.description,
                "color": panel.color,
                "footer_text": panel.footer_text,
                "thumbnail_url": panel.thumbnail_url,
                "message_id": panel.message_id,
                "channel_id": panel.channel_id,
                "guild_id": panel.guild_id
            }
    
    async def get_all_faq_panels(self, guild_id: int) -> List[dict]:
        """Get all FAQ panels for a guild"""
        from src.models.database import FAQPanel, FAQEntry
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQPanel).where(FAQPanel.guild_id == guild_id)
                .order_by(FAQPanel.created_at.desc())
            )
            panels = result.scalars().all()
            
            panel_list = []
            for panel in panels:
                # Count entries
                entry_count = await session.execute(
                    select(func.count(FAQEntry.id)).where(FAQEntry.panel_id == panel.id)
                )
                
                panel_list.append({
                    "id": panel.id,
                    "name": panel.name,
                    "title": panel.title,
                    "message_id": panel.message_id,
                    "channel_id": panel.channel_id,
                    "entry_count": entry_count.scalar() or 0
                })
            
            return panel_list
    
    async def get_all_published_faq_panels(self) -> List[dict]:
        """Get all published FAQ panels (for persistent view registration)"""
        from src.models.database import FAQPanel
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQPanel).where(FAQPanel.message_id.isnot(None))
            )
            panels = result.scalars().all()
            
            return [
                {
                    "id": panel.id,
                    "name": panel.name,
                    "message_id": panel.message_id,
                    "channel_id": panel.channel_id
                }
                for panel in panels
            ]
    
    async def update_faq_panel(
        self,
        panel_id: int,
        title: str = None,
        description: str = None,
        color: int = None,
        footer_text: str = None,
        thumbnail_url: str = None
    ) -> dict:
        """Update a FAQ panel"""
        from src.models.database import FAQPanel
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQPanel).where(FAQPanel.id == panel_id)
            )
            panel = result.scalar_one_or_none()
            
            if not panel:
                return {"success": False, "error": "Panel not found"}
            
            if title is not None:
                panel.title = title
            if description is not None:
                panel.description = description
            if color is not None:
                panel.color = color
            if footer_text is not None:
                panel.footer_text = footer_text
            if thumbnail_url is not None:
                panel.thumbnail_url = thumbnail_url
            
            await session.commit()
            
            return {
                "success": True,
                "panel": {
                    "id": panel.id,
                    "name": panel.name,
                    "message_id": panel.message_id
                }
            }
    
    async def update_faq_panel_message(
        self,
        panel_id: int,
        message_id: int,
        channel_id: int
    ) -> dict:
        """Update FAQ panel message location"""
        from src.models.database import FAQPanel
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQPanel).where(FAQPanel.id == panel_id)
            )
            panel = result.scalar_one_or_none()
            
            if not panel:
                return {"success": False, "error": "Panel not found"}
            
            panel.message_id = message_id
            panel.channel_id = channel_id
            
            await session.commit()
            return {"success": True}
    
    async def delete_faq_panel(self, panel_id: int) -> dict:
        """Delete a FAQ panel and all its entries"""
        from src.models.database import FAQPanel
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQPanel).where(FAQPanel.id == panel_id)
            )
            panel = result.scalar_one_or_none()
            
            if not panel:
                return {"success": False, "error": "Panel not found"}
            
            await session.delete(panel)
            await session.commit()
            return {"success": True}
    
    async def add_faq_entry(
        self,
        panel_id: int,
        label: str,
        content: str,
        emoji: str = None
    ) -> dict:
        """Add an entry to a FAQ panel"""
        from src.models.database import FAQPanel, FAQEntry
        
        async with self.session() as session:
            # Verify panel exists
            panel_result = await session.execute(
                select(FAQPanel).where(FAQPanel.id == panel_id)
            )
            if not panel_result.scalar_one_or_none():
                return {"success": False, "error": "Panel not found"}
            
            # Get max order index
            max_order = await session.execute(
                select(func.max(FAQEntry.order_index))
                .where(FAQEntry.panel_id == panel_id)
            )
            next_order = (max_order.scalar() or -1) + 1
            
            entry = FAQEntry(
                panel_id=panel_id,
                label=label,
                content=content,
                emoji=emoji,
                order_index=next_order
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            
            return {
                "success": True,
                "entry": {
                    "id": entry.id,
                    "label": entry.label,
                    "order_index": entry.order_index
                }
            }
    
    async def get_faq_entries(self, panel_id: int) -> List[dict]:
        """Get all entries for a FAQ panel"""
        from src.models.database import FAQEntry
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQEntry)
                .where(FAQEntry.panel_id == panel_id)
                .order_by(FAQEntry.order_index)
            )
            entries = result.scalars().all()
            
            return [
                {
                    "id": entry.id,
                    "label": entry.label,
                    "emoji": entry.emoji,
                    "content": entry.content,
                    "order_index": entry.order_index
                }
                for entry in entries
            ]
    
    async def get_faq_entry(self, entry_id: int) -> Optional[dict]:
        """Get a single FAQ entry"""
        from src.models.database import FAQEntry
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQEntry).where(FAQEntry.id == entry_id)
            )
            entry = result.scalar_one_or_none()
            
            if not entry:
                return None
            
            return {
                "id": entry.id,
                "panel_id": entry.panel_id,
                "label": entry.label,
                "emoji": entry.emoji,
                "content": entry.content,
                "order_index": entry.order_index
            }
    
    async def update_faq_entry(
        self,
        entry_id: int,
        label: str = None,
        content: str = None,
        emoji: str = None
    ) -> dict:
        """Update a FAQ entry"""
        from src.models.database import FAQEntry
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQEntry).where(FAQEntry.id == entry_id)
            )
            entry = result.scalar_one_or_none()
            
            if not entry:
                return {"success": False, "error": "Entry not found"}
            
            if label is not None:
                entry.label = label
            if content is not None:
                entry.content = content
            if emoji is not None:
                entry.emoji = emoji if emoji else None
            
            await session.commit()
            return {"success": True}
    
    async def delete_faq_entry(self, entry_id: int) -> dict:
        """Delete a FAQ entry"""
        from src.models.database import FAQEntry
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQEntry).where(FAQEntry.id == entry_id)
            )
            entry = result.scalar_one_or_none()
            
            if not entry:
                return {"success": False, "error": "Entry not found"}
            
            await session.delete(entry)
            await session.commit()
            return {"success": True}
    
    async def reorder_faq_entry(self, entry_id: int, new_order: int) -> dict:
        """Reorder a FAQ entry"""
        from src.models.database import FAQEntry
        
        async with self.session() as session:
            result = await session.execute(
                select(FAQEntry).where(FAQEntry.id == entry_id)
            )
            entry = result.scalar_one_or_none()
            
            if not entry:
                return {"success": False, "error": "Entry not found"}
            
            # Get all entries for this panel
            all_entries = await session.execute(
                select(FAQEntry)
                .where(FAQEntry.panel_id == entry.panel_id)
                .order_by(FAQEntry.order_index)
            )
            entries = list(all_entries.scalars().all())
            
            # Remove target entry from list
            entries = [e for e in entries if e.id != entry_id]
            
            # Insert at new position
            new_order = max(0, min(new_order, len(entries)))
            entries.insert(new_order, entry)
            
            # Update all order indices
            for i, e in enumerate(entries):
                e.order_index = i
            
            await session.commit()
            return {"success": True}


# Global database instance
db = DatabaseService()
