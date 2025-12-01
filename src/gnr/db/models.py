"""
SQLAlchemy models for the GridNodeRegistry.

Each SQL row corresponds to a serialized ASL GT snapshot.
ASL types are used for validation (via the codec) before any insert/update.
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
    relationship,
    declarative_base,
)

from gnr.asl.enums import GNodeStatus, BaseGNodeClass
from gnr.asl.types import (
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
        """Serialize database row → ASL GT."""
        return PositionPointGt(
            id=self.id,
            latitude_micro_deg=self.latitude_micro_deg,
            longitude_micro_deg=self.longitude_micro_deg,
        )

    @staticmethod
    def from_gt(gt: PositionPointGt) -> "PositionPointSql":
        """Create SQL row from ASL GT after full ASL validation."""
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

    position_point_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("position_points.id"), nullable=True
    )
    position_point: Mapped[Optional[PositionPointSql]] = relationship()

    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    # -------------------
    #  ASL ↔ SQL Helpers
    # -------------------

    def to_gt(self) -> GNodeGt:
        """Serialize SQL row → ASL GT."""
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
        """Create SQL model from an ASL GT instance (already validated)."""
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

    from_g_node_alias: Mapped[str] = mapped_column(String, index=True)
    to_g_node_alias: Mapped[str] = mapped_column(String, index=True)

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
    #  ASL ↔ SQL Helpers
    # -------------------

    def to_gt(self) -> ConnectivityEdgeGt:
        return ConnectivityEdgeGt(
            id=self.id,
            from_g_node_id=self.from_g_node_id,
            to_g_node_id=self.to_g_node_id,
            from_g_node_alias=self.from_g_node_alias,
            to_g_node_alias=self.to_g_node_alias,
            status=self.status,
        )

    @staticmethod
    def from_gt(gt: ConnectivityEdgeGt) -> "ConnectivityEdgeSql":
        return ConnectivityEdgeSql(
            id=gt.id,
            from_g_node_id=gt.from_g_node_id,
            to_g_node_id=gt.to_g_node_id,
            from_g_node_alias=gt.from_g_node_alias,
            to_g_node_alias=gt.to_g_node_alias,
            status=gt.status,
        )
