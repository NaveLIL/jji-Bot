"""
SQLAlchemy 2.0 Database Models
Production-grade Discord Bot for JJI Regiment
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, 
    String, Text, Enum as SQLEnum, UniqueConstraint, Index,
    CheckConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


class TransactionType(str, Enum):
    """Types of economic transactions"""
    SALARY = "salary"
    MASTER_BONUS = "master_bonus"
    GAME_WIN = "game_win"
    GAME_LOSS = "game_loss"
    CASE_REWARD = "case_reward"
    ROLE_PURCHASE = "role_purchase"
    ROLE_SELL = "role_sell"
    OFFICER_REWARD = "officer_reward"
    PB_10H_BONUS = "pb_10h_bonus"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    TAX = "tax"
    MUTE_PENALTY = "mute_penalty"
    ADMIN_SET = "admin_set"
    ADMIN_ADD = "admin_add"
    FINE = "fine"
    CONFISCATE = "confiscate"


class RoleType(str, Enum):
    """Types of purchasable roles"""
    COLOR = "color"
    CUSTOM = "custom"


class GameType(str, Enum):
    """Types of games"""
    BLACKJACK = "blackjack"
    COINFLIP = "coinflip"


class LogType(str, Enum):
    """Types of log channels"""
    OFFICER = "officer"
    RECRUIT = "recruit"
    ECONOMY = "economy"
    GAMES = "games"
    SERVER = "server"
    SECURITY = "security"


class User(Base):
    """User model with economy data"""
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_pb_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # seconds
    join_date: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    last_pb_reward: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_voice_join: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_officer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_sergeant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_soldier: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blacklist_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rate_limit_violations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Relationships
    owned_roles: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[List["Transaction"]] = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    case_uses: Mapped[List["CaseUse"]] = relationship("CaseUse", back_populates="user", cascade="all, delete-orphan")
    officer_logs: Mapped[List["OfficerLog"]] = relationship("OfficerLog", back_populates="officer", foreign_keys="OfficerLog.officer_id", cascade="all, delete-orphan")
    recruit_logs: Mapped[List["OfficerLog"]] = relationship("OfficerLog", back_populates="recruit", foreign_keys="OfficerLog.recruit_id")
    game_sessions: Mapped[List["GameSession"]] = relationship("GameSession", back_populates="user", cascade="all, delete-orphan")
    voice_sessions: Mapped[List["VoiceSession"]] = relationship("VoiceSession", back_populates="user", cascade="all, delete-orphan")
    
    __table_args__ = (
        CheckConstraint('balance >= 0', name='check_balance_non_negative'),
        Index('idx_user_balance', 'balance'),
        Index('idx_user_pb_time', 'total_pb_time'),
    )
    
    def __repr__(self) -> str:
        return f"<User(discord_id={self.discord_id}, balance={self.balance})>"


class Role(Base):
    """Purchasable roles in the shop"""
    __tablename__ = "roles"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_type: Mapped[RoleType] = mapped_column(SQLEnum(RoleType), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    color_hex: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)  # #RRGGBB
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    
    # Relationships
    user_roles: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")
    
    __table_args__ = (
        CheckConstraint('price >= 0', name='check_price_non_negative'),
    )
    
    def __repr__(self) -> str:
        return f"<Role(name={self.name}, type={self.role_type}, price={self.price})>"


class UserRole(Base):
    """Junction table for user-owned roles"""
    __tablename__ = "user_roles"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    purchase_date: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="owned_roles")
    role: Mapped["Role"] = relationship("Role", back_populates="user_roles")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'role_id', name='unique_user_role'),
        Index('idx_user_role_active', 'user_id', 'is_active'),
    )
    
    def __repr__(self) -> str:
        return f"<UserRole(user_id={self.user_id}, role_id={self.role_id}, active={self.is_active})>"


class Transaction(Base):
    """Economic transaction log"""
    __tablename__ = "transactions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(SQLEnum(TransactionType), nullable=False)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    before_balance: Mapped[float] = mapped_column(Float, nullable=False)
    after_balance: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    related_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # For transfers
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False, index=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="transactions")
    
    __table_args__ = (
        Index('idx_transaction_type', 'transaction_type'),
        Index('idx_transaction_user_time', 'user_id', 'timestamp'),
    )
    
    def __repr__(self) -> str:
        return f"<Transaction(user_id={self.user_id}, type={self.transaction_type}, amount={self.amount})>"


class ServerEconomy(Base):
    """Server-wide economy settings and state"""
    __tablename__ = "server_economy"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    total_budget: Mapped[float] = mapped_column(Float, default=50000.0, nullable=False)
    tax_rate: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)  # Percentage
    soldier_value: Mapped[float] = mapped_column(Float, default=10000.0, nullable=False)
    total_soldiers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_taxes_collected: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_rewards_paid: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    __table_args__ = (
        CheckConstraint('tax_rate >= 0 AND tax_rate <= 100', name='check_tax_rate_valid'),
    )
    
    def __repr__(self) -> str:
        return f"<ServerEconomy(budget={self.total_budget}, tax_rate={self.tax_rate}%)>"


class CaseUse(Base):
    """Track case command usage for cooldowns"""
    __tablename__ = "case_uses"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    last_used: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    times_used_today: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="case_uses")
    
    __table_args__ = (
        Index('idx_case_user_date', 'user_id', 'last_used'),
    )


class OfficerLog(Base):
    """Track officer recruitment activities"""
    __tablename__ = "officer_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    officer_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recruit_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    recruit_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    pb_time_at_accept: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # seconds
    pb_10h_rewarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pb_10h_rewarded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    officer: Mapped["User"] = relationship("User", back_populates="officer_logs", foreign_keys=[officer_id])
    recruit: Mapped[Optional["User"]] = relationship("User", back_populates="recruit_logs", foreign_keys=[recruit_id])
    
    __table_args__ = (
        Index('idx_officer_pending', 'officer_id', 'pb_10h_rewarded'),
    )
    
    def __repr__(self) -> str:
        return f"<OfficerLog(officer_id={self.officer_id}, recruit_id={self.recruit_id})>"


class ChannelConfig(Base):
    """Configurable channel settings"""
    __tablename__ = "channel_configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_type: Mapped[LogType] = mapped_column(SQLEnum(LogType), unique=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    def __repr__(self) -> str:
        return f"<ChannelConfig(type={self.config_type}, channel_id={self.channel_id})>"


class GameSession(Base):
    """Active game sessions for persistence"""
    __tablename__ = "game_sessions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    game_type: Mapped[GameType] = mapped_column(SQLEnum(GameType), nullable=False)
    bet_amount: Mapped[float] = mapped_column(Float, nullable=False)
    game_state: Mapped[str] = mapped_column(Text, nullable=False)  # JSON serialized state
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="game_sessions")
    
    __table_args__ = (
        Index('idx_game_session_user', 'user_id', 'game_type'),
        Index('idx_game_session_expires', 'expires_at'),
    )
    
    def __repr__(self) -> str:
        return f"<GameSession(user_id={self.user_id}, game={self.game_type})>"


class VoiceSession(Base):
    """Track voice channel sessions for PB time"""
    __tablename__ = "voice_sessions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_in_master: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    master_bonus_claimed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="voice_sessions")
    
    __table_args__ = (
        Index('idx_voice_session_active', 'user_id', 'is_active'),
    )
    
    def __repr__(self) -> str:
        return f"<VoiceSession(user_id={self.user_id}, active={self.is_active})>"


class RateLimitEntry(Base):
    """Track rate limit violations"""
    __tablename__ = "rate_limit_entries"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)  # command, game, transaction
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    
    __table_args__ = (
        Index('idx_rate_limit_user_time', 'user_id', 'timestamp'),
    )


class SecurityLog(Base):
    """Security events and violations"""
    __tablename__ = "security_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # low, medium, high, critical
    action_taken: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    
    __table_args__ = (
        Index('idx_security_time', 'timestamp'),
        Index('idx_security_severity', 'severity'),
    )


class BotStats(Base):
    """Bot statistics and metrics"""
    __tablename__ = "bot_stats"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stat_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    stat_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
