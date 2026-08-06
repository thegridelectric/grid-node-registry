"""initial schema

Revision ID: a0b1c2d3e4f5
Revises:
Create Date: 2026-07-04 00:00:00.000000

Squashed baseline — gnr is not yet deployed anywhere, so the incremental history
(initial → alias_assignment → command_log → drop-FK) is collapsed into one clean
migration reflecting the current model. Note `g_nodes.position_point_id` is an
**opaque UUID, NOT an FK**: the coordinate data is owned + populated later
(encrypted) by TaValidator, so gnr holds the location identity, not the row. See
the positions-staging exploration.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a0b1c2d3e4f5"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "position_points",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("latitude_micro_deg", sa.Integer(), nullable=False),
        sa.Column("longitude_micro_deg", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "g_nodes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("prev_alias", sa.String(), nullable=True),
        sa.Column(
            "base_class",
            sa.Enum(
                "TerminalAsset",
                "LeafTransactiveNode",
                "ConnectivityNode",
                "MarketMaker",
                "Logical",
                name="base_g_node_class",
            ),
            nullable=False,
        ),
        sa.Column("g_node_class", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "Pending",
                "Active",
                "Suspended",
                "PermanentlyDeactivated",
                name="g_node_status",
            ),
            nullable=False,
        ),
        sa.Column("position_point_id", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_g_nodes_alias"), "g_nodes", ["alias"], unique=True)
    op.create_table(
        "connectivity_edges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("from_g_node_id", sa.String(), nullable=False),
        sa.Column("to_g_node_id", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "Pending",
                "Active",
                "Suspended",
                "PermanentlyDeactivated",
                name="connectivity_edge_status",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["from_g_node_id"],
            ["g_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["to_g_node_id"],
            ["g_nodes.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_g_node_id", "to_g_node_id", name="uq_connectivity_edges_from_to"
        ),
    )
    op.create_index(
        op.f("ix_connectivity_edges_from_g_node_id"),
        "connectivity_edges",
        ["from_g_node_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connectivity_edges_to_g_node_id"),
        "connectivity_edges",
        ["to_g_node_id"],
        unique=False,
    )
    op.create_table(
        "alias_assignment",
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("g_node_id", sa.String(), nullable=False),
        sa.Column("first_assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["g_node_id"],
            ["g_nodes.id"],
        ),
        sa.PrimaryKeyConstraint("alias"),
    )
    op.create_index(
        op.f("ix_alias_assignment_g_node_id"),
        "alias_assignment",
        ["g_node_id"],
        unique=False,
    )
    op.create_table(
        "command_log",
        sa.Column("command_hash", sa.String(), nullable=False),
        sa.Column("type_name", sa.String(), nullable=False),
        sa.Column("payload", sa.String(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("command_hash"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("command_log")
    op.drop_index(op.f("ix_alias_assignment_g_node_id"), table_name="alias_assignment")
    op.drop_table("alias_assignment")
    op.drop_index(
        op.f("ix_connectivity_edges_to_g_node_id"), table_name="connectivity_edges"
    )
    op.drop_index(
        op.f("ix_connectivity_edges_from_g_node_id"), table_name="connectivity_edges"
    )
    op.drop_table("connectivity_edges")
    op.drop_index(op.f("ix_g_nodes_alias"), table_name="g_nodes")
    op.drop_table("g_nodes")
    op.drop_table("position_points")
