"""Add partial unique index on voice_sessions for active rows

Revision ID: add_unique_active_voice_session
Revises: add_squad_to_officer_logs
Create Date: 2026-04-27

Ensures at most one active voice session per user. Prevents duplicate
active rows caused by Discord sending repeated voice state events.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'add_unique_active_voice_session'
down_revision: Union[str, None] = 'add_squad_to_officer_logs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    inspector = sa.inspect(bind)
    if 'voice_sessions' not in inspector.get_table_names():
        # Table is created at runtime by Base.metadata.create_all in fresh
        # databases. The model already declares the partial unique index,
        # so create_all will produce it. Nothing to do here.
        return

    # Best-effort cleanup: keep only the newest active session per user
    # so the unique index can be created without conflicts.
    if dialect == 'sqlite':
        op.execute(
            """
            UPDATE voice_sessions
            SET is_active = 0,
                left_at = COALESCE(left_at, CURRENT_TIMESTAMP)
            WHERE is_active = 1
              AND id NOT IN (
                  SELECT MAX(id) FROM voice_sessions
                  WHERE is_active = 1
                  GROUP BY user_id
              )
            """
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_voice_session_active_user "
            "ON voice_sessions(user_id) WHERE is_active = 1"
        )
    elif dialect == 'postgresql':
        op.execute(
            """
            UPDATE voice_sessions
            SET is_active = false,
                left_at = COALESCE(left_at, NOW())
            WHERE is_active = true
              AND id NOT IN (
                  SELECT MAX(id) FROM voice_sessions
                  WHERE is_active = true
                  GROUP BY user_id
              )
            """
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_voice_session_active_user "
            "ON voice_sessions(user_id) WHERE is_active = true"
        )
    else:
        # Fallback: non-partial unique index will fail if duplicates exist,
        # so do nothing for unsupported dialects.
        pass


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_voice_session_active_user")
