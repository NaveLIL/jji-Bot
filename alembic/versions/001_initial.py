"""Initial migration

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=True),
        sa.Column('balance', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_earned', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_spent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_pb_time', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('muted_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_case', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', 'guild_id')
    )
    op.create_index('ix_users_balance', 'users', ['balance'], unique=False)
    op.create_index('ix_users_total_pb_time', 'users', ['total_pb_time'], unique=False)

    # Roles table
    op.create_table(
        'roles',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_roles_guild_id', 'roles', ['guild_id'], unique=False)

    # User roles table
    op.create_table(
        'user_roles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('role_id', sa.BigInteger(), nullable=False),
        sa.Column('is_equipped', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('purchased_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
        sa.ForeignKeyConstraint(['user_id', 'guild_id'], ['users.id', 'users.guild_id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'guild_id', 'role_id', name='uq_user_role')
    )

    # Transactions table
    op.create_table(
        'transactions',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('transaction_type', sa.String(length=50), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('balance_before', sa.Integer(), nullable=False),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('related_user_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['user_id', 'guild_id'], ['users.id', 'users.guild_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_transactions_created_at', 'transactions', ['created_at'], unique=False)
    op.create_index('ix_transactions_user_id', 'transactions', ['user_id'], unique=False)

    # Server economy table
    op.create_table(
        'server_economy',
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('budget', sa.Integer(), nullable=False, server_default='1000000'),
        sa.Column('total_distributed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_collected', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('guild_id')
    )

    # Case uses table
    op.create_table(
        'case_uses',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('amount_won', sa.Integer(), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['user_id', 'guild_id'], ['users.id', 'users.guild_id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Officer logs table
    op.create_table(
        'officer_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('officer_id', sa.BigInteger(), nullable=False),
        sa.Column('recruit_id', sa.BigInteger(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('reward_amount', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('bonus_paid', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('recruit_stayed_10h', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('recruited_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('bonus_paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['officer_id', 'guild_id'], ['users.id', 'users.guild_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_officer_logs_officer_id', 'officer_logs', ['officer_id'], unique=False)

    # Channel configs table
    op.create_table(
        'channel_configs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('channel_type', sa.String(length=50), nullable=False),
        sa.Column('channel_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id', 'channel_type', name='uq_channel_config')
    )

    # Security logs table
    op.create_table(
        'security_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_security_logs_event_type', 'security_logs', ['event_type'], unique=False)
    op.create_index('ix_security_logs_user_id', 'security_logs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('security_logs')
    op.drop_table('channel_configs')
    op.drop_table('officer_logs')
    op.drop_table('case_uses')
    op.drop_table('server_economy')
    op.drop_table('transactions')
    op.drop_table('user_roles')
    op.drop_table('roles')
    op.drop_table('users')
