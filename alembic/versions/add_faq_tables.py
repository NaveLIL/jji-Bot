"""Add FAQ tables

Revision ID: add_faq_tables
Revises: 82d02328889d_add_salarychange_and_constraints
Create Date: 2026-01-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_faq_tables'
down_revision: Union[str, None] = '82d02328889d_add_salarychange_and_constraints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create faq_panels table
    op.create_table(
        'faq_panels',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), nullable=False),  # Unique per guild, not globally
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('color', sa.Integer(), default=0x2F3136, nullable=False),
        sa.Column('footer_text', sa.String(256), nullable=True),
        sa.Column('thumbnail_url', sa.String(512), nullable=True),
        sa.Column('message_id', sa.BigInteger(), nullable=True),
        sa.Column('channel_id', sa.BigInteger(), nullable=True),
        sa.Column('guild_id', sa.BigInteger(), nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('name', 'guild_id', name='uq_faq_panel_name_guild'),  # Unique per guild
    )
    op.create_index('idx_faq_panel_message', 'faq_panels', ['message_id', 'channel_id'])
    op.create_index('idx_faq_panel_guild', 'faq_panels', ['guild_id'])
    
    # Create faq_entries table
    op.create_table(
        'faq_entries',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('panel_id', sa.Integer(), sa.ForeignKey('faq_panels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('emoji', sa.String(64), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('order_index', sa.Integer(), default=0, nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('idx_faq_entry_panel', 'faq_entries', ['panel_id', 'order_index'])


def downgrade() -> None:
    op.drop_index('idx_faq_entry_panel', 'faq_entries')
    op.drop_table('faq_entries')
    
    op.drop_index('idx_faq_panel_guild', 'faq_panels')
    op.drop_index('idx_faq_panel_message', 'faq_panels')
    op.drop_table('faq_panels')
