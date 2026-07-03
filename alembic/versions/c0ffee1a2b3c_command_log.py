"""command_log

Revision ID: c0ffee1a2b3c
Revises: d3dbdc344109
Create Date: 2026-07-03 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0ffee1a2b3c'
down_revision: Union[str, Sequence[str], None] = 'd3dbdc344109'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('command_log',
    sa.Column('command_hash', sa.String(), nullable=False),
    sa.Column('type_name', sa.String(), nullable=False),
    sa.Column('payload', sa.String(), nullable=False),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('command_hash')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('command_log')
