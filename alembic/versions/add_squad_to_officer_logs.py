"""Add squad column to officer_logs

Revision ID: add_squad_to_officer_logs
Revises: add_faq_tables
Create Date: 2026-04-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_squad_to_officer_logs'
down_revision: Union[str, None] = 'add_faq_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add squad column to officer_logs with default 'main' for existing rows."""
    with op.batch_alter_table('officer_logs') as batch_op:
        batch_op.add_column(
            sa.Column(
                'squad',
                sa.String(length=16),
                nullable=False,
                server_default='main',
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('officer_logs') as batch_op:
        batch_op.drop_column('squad')
