"""
SQLAlchemy models for the GridNodeRegistry.

Each SQL row corresponds to a serialized Sema GT snapshot.
Sema types are used for validation (via the codec) before any insert/update.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Enum,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    declarative_base,
)

from gnr.sema.enums import GNodeStatus, BaseGNodeClass
from gnr.sema.types import (
    GNodeGt,
    ConnectivityEdgeGt,
    PositionPointGt,
)

Base = declarative_base()


# ============================================================
#  POSITION POINTS
# ============================================================

class PositionPointSql(Base):
    __tablename__ = "position_points"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    latitude_micro_deg: Mapped[int] = mapped_column()
    longitude_micro_deg: Mapped[int] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    def to_gt(self) -> PositionPointGt:
        """Serialize database row → Sema GT."""
        return PositionPointGt(
            id=self.id,
            latitude_micro_deg=self.latitude_micro_deg,
            longitude_micro_deg=self.longitude_micro_deg,
        )

    @staticmethod
    def from_gt(gt: PositionPointGt) -> "PositionPointSql":
        """Create SQL row from Sema GT after full Sema validation."""
        return PositionPointSql(
            id=gt.id,
            latitude_micro_deg=gt.latitude_micro_deg,
            longitude_micro_deg=gt.longitude_micro_deg,
        )


# ============================================================
#  G N O D E S
# ============================================================

class GNodeSql(Base):
    __tablename__ = "g_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    alias: Mapped[str] = mapped_column(String, index=True, unique=True)
    prev_alias: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    base_class: Mapped[BaseGNodeClass] = mapped_column(
        Enum(BaseGNodeClass, name="base_g_node_class")
    )

    g_node_class: Mapped[str] = mapped_column(String)

    status: Mapped[GNodeStatus] = mapped_column(
        Enum(GNodeStatus, name="g_node_status")
    )

    # An opaque location IDENTITY (a UUID), carried in the g.node.gt/command — NOT
    # an enforced FK. The coordinate DATA is owned + populated later (encrypted) by
    # a separate system (TaValidator), so an FK from here into a table gnr
    # write-only-populates-later is the wrong coupling. gnr owns identity + topology;
    # the (encrypted) geography lives elsewhere. See the positions-staging exploration.
    position_point_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    # -------------------
    #  Sema ↔ SQL Helpers
    # -------------------

    def to_gt(self) -> GNodeGt:
        """Serialize SQL row → Sema GT."""
        return GNodeGt(
            g_node_id=self.id,
            alias=self.alias,
            base_class=self.base_class,
            g_node_class=self.g_node_class,
            status=self.status,
            prev_alias=self.prev_alias,
            position_point_id=self.position_point_id,
            display_name=self.display_name,
        )

    @staticmethod
    def from_gt(gt: GNodeGt) -> "GNodeSql":
        """Create SQL model from an Sema GT instance (already validated)."""
        return GNodeSql(
            id=gt.g_node_id,
            alias=gt.alias,
            prev_alias=gt.prev_alias,
            base_class=gt.base_class,
            g_node_class=gt.g_node_class,
            status=gt.status,
            position_point_id=gt.position_point_id,
            display_name=gt.display_name,
        )


# ============================================================
#  CONNECTIVITY EDGES
# ============================================================

class ConnectivityEdgeSql(Base):
    __tablename__ = "connectivity_edges"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    from_g_node_id: Mapped[str] = mapped_column(
        ForeignKey("g_nodes.id"), index=True
    )
    to_g_node_id: Mapped[str] = mapped_column(
        ForeignKey("g_nodes.id"), index=True
    )

    status: Mapped[GNodeStatus] = mapped_column(
        Enum(GNodeStatus, name="connectivity_edge_status")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "from_g_node_id", "to_g_node_id",
            name="uq_connectivity_edges_from_to"
        ),
    )

    # -------------------
    #  Sema ↔ SQL Helpers
    # -------------------

    def to_gt(self) -> ConnectivityEdgeGt:
        return ConnectivityEdgeGt(
            id=self.id,
            from_g_node_id=self.from_g_node_id,
            to_g_node_id=self.to_g_node_id,
            status=self.status,
        )

    @staticmethod
    def from_gt(gt: ConnectivityEdgeGt) -> "ConnectivityEdgeSql":
        return ConnectivityEdgeSql(
            id=gt.id,
            from_g_node_id=gt.from_g_node_id,
            to_g_node_id=gt.to_g_node_id,
            status=gt.status,
        )


# ============================================================
#  ALIAS ASSIGNMENT LEDGER
# ============================================================

class AliasAssignmentSql(Base):
    """Append-only record of alias→GNodeId ownership, for all time.

    The `alias` primary key is the guarantee for the *alias-uniqueness-through-
    time* invariant: an alias, once bound to a `GNodeId`, is permanently owned by
    it and can never bind to a different one — even after the node renames away
    from it. `g_nodes.alias UNIQUE` only enforces *live* uniqueness (a rename
    frees the old value in that row), so the permanent binding lives here.
    Written on every create and every rename via `gnr.db.alias_ledger.claim_alias`.
    """

    __tablename__ = "alias_assignment"

    alias: Mapped[str] = mapped_column(String, primary_key=True)
    g_node_id: Mapped[str] = mapped_column(
        ForeignKey("g_nodes.id"), nullable=False, index=True
    )
    first_assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


# ============================================================
#  COMMAND LOG  (append-only; the chain-ready primitive)
# ============================================================

class CommandLogSql(Base):
    """Append-only log of applied mutation commands — the source-of-truth primitive.

    A ledger/chain is fundamentally an ordered log of signed commands with state
    derived from it. Every mutation (a re-parent; later a create) is appended here
    in the SAME transaction as the state change, keyed by a **content hash** of the
    command's canonical serialization (`gnr.ids.command_hash`). That gives:
      - **content-addressing** — the id IS the hash of the command bytes;
      - **replay-safety / idempotency** — a command whose hash is already present
        was already applied, so the PK rejects a re-apply;
      - the foundation for moving authority off single-writer Postgres later (the
        log moves to the chain; `g_nodes`/edges/`alias_assignment` become a
        projection of it).
    `applied_at` is local audit metadata, not authoritative state. See executor
    "Distributed-readiness".
    """

    __tablename__ = "command_log"

    command_hash: Mapped[str] = mapped_column(String, primary_key=True)
    type_name: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str] = mapped_column(String, nullable=False)  # canonical Sema JSON
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
