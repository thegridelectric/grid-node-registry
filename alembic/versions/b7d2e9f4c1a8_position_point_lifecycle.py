"""position-point lifecycle: encrypted shape, FK, identity backfill

The location store takes its encrypted-coordinate shape (identity row +
nullable ciphertext payload; plaintext coordinates never stored), every
already-carried position_point_id gets its identity row, and
g_nodes.position_point_id becomes a real foreign key.

Revision ID: b7d2e9f4c1a8
Revises: a0b1c2d3e4f5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2e9f4c1a8"
down_revision: str | Sequence[str] | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Shape: plaintext coordinates go (none ever existed in prod; dev
    # placeholders are disposable), the encrypted payload columns arrive
    # NULL — "identity registered, coordinates pending".
    op.drop_column("position_points", "latitude_micro_deg")
    op.drop_column("position_points", "longitude_micro_deg")
    op.add_column(
        "position_points", sa.Column("ciphertext", sa.LargeBinary(), nullable=True)
    )
    op.add_column("position_points", sa.Column("key_id", sa.String(), nullable=True))
    op.add_column("position_points", sa.Column("alg", sa.String(), nullable=True))

    # Identity backfill: every carried id gets its row before the FK lands,
    # so the existing fleet stays valid.
    op.execute(
        """
        INSERT INTO position_points (id, created_at)
        SELECT DISTINCT g.position_point_id, now()
        FROM g_nodes g
        WHERE g.position_point_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM position_points p WHERE p.id = g.position_point_id
          )
        """
    )

    op.create_foreign_key(
        "fk_g_nodes_position_point_id",
        "g_nodes",
        "position_points",
        ["position_point_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_g_nodes_position_point_id", "g_nodes", type_="foreignkey")
    op.drop_column("position_points", "alg")
    op.drop_column("position_points", "key_id")
    op.drop_column("position_points", "ciphertext")
    op.add_column(
        "position_points",
        sa.Column(
            "latitude_micro_deg", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "position_points",
        sa.Column(
            "longitude_micro_deg", sa.Integer(), nullable=False, server_default="0"
        ),
    )
