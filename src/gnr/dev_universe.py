"""Seed a dev universe (`d1.*`) — a `validate_registry`-clean forest for harness/dev.

A static, self-contained description of a dev fleet: a copper backbone, six
Active homes (each an LTN + TerminalAsset + Scada), one **Pending** home
(`willow` — the fleet-ingest posture: position staged as an opaque id with no
`position_points` row; activation arrives with the TaValidator work), and the
logical simulation services. No external inputs — the aliases + classes live
here as a flat map, so nothing breaks when the layout pipeline changes
elsewhere. The universe token `d1` is **not** a
GNode (it is a namespace); the top-level copper nodes are **forest roots**. Every
GNode carries a fresh GNodeId — a simulation of the fleet, not the production nodes
— so it runs against a dev broker + database without touching real money.
"""

from __future__ import annotations

import hashlib

from gnr.db.alias_ledger import claim_alias
from gnr.db.models import (
    AliasAssignmentSql,
    ConnectivityEdgeSql,
    GNodeSql,
    PositionPointSql,
)
from gnr.ids import deterministic_uuid4
from gnr.sema.enums import BaseGNodeClass as B, GNodeStatus as S
from gnr.sema.property_format import LeftRightDot
from gnr.sema.types import GNodeGt, PositionPointGt

DEV_UNIVERSE = "d1"
KEENE = "d1.isone.me.versant.keene"
_HOMES = ("beech", "elm", "fir", "maple", "oak", "spruce", "willow")
# willow is the dev universe's non-Active home: Pending, position staged (opaque
# id, no position_points row) — the posture every real home has between fleet
# ingest and TaValidator activation.
PENDING_HOME = f"{KEENE}.willow"


def _dev_universe_specs() -> dict[LeftRightDot, tuple[B, str]]:
    """The dev universe as a flat `alias -> (base_class, g_node_class)` map.

    `d1.isone` and `d1.time` are **forest roots** (their alias-parent is the bare
    universe token `d1`, which is not a GNode). Copper (`MarketMaker`/
    `ConnectivityNode`) g_node_class equals the base_class value (axiom 1); the
    Logical services carry their role name.
    """
    specs: dict[LeftRightDot, tuple[B, str]] = {
        # copper backbone — d1.isone is a forest root
        "d1.isone": (B.MarketMaker, "MarketMaker"),
        "d1.isone.me": (B.ConnectivityNode, "ConnectivityNode"),
        "d1.isone.me.versant": (B.ConnectivityNode, "ConnectivityNode"),
        KEENE: (B.MarketMaker, "MarketMaker"),
        # logical simulation services (used soon by simulated dev universes)
        "d1.time": (B.Logical, "TimeCoordinator"),  # a Logical forest root
        "d1.isone.me.weather": (B.Logical, "WeatherForecastService"),
        "d1.isone.me.price": (B.Logical, "PriceForecastService"),
    }
    for home in _HOMES:
        specs[f"{KEENE}.{home}"] = (B.LeafTransactiveNode, "LeafTransactiveNode")
        specs[f"{KEENE}.{home}.ta"] = (B.TerminalAsset, "TerminalAsset")
        specs[f"{KEENE}.{home}.scada"] = (B.Logical, "Scada")
    return specs


# Dev physical nodes each get a DISTINCT placeholder location (real grid nodes have
# distinct positions; a single shared point was a test smell). The points sit in the
# open mid-Atlantic on the ridge (~32°N 40°W) — nowhere a home could be, so a dev
# point is never mistaken for a real dwelling (somewhere to site Atlantis). The
# registry enforces nothing about positions (see the position-point-semantics
# exploration); distinctness here is fixture quality, not an invariant.
_ATLANTIS_LAT_UDEG = 32_000_000
_ATLANTIS_LON_UDEG = -40_000_000

# Hash domain-separation tags for deterministic dev ids — internal salts, NOT Sema
# names (see gnr.ids). Slash-delimited so they can't be read as a left.right.dot.
_POS_ID_DOMAIN = "gnr-det-id/dev-universe-position"
_GNODE_ID_DOMAIN = "gnr-det-id/dev-universe-gnode"


def dev_position_for(alias: LeftRightDot) -> PositionPointGt:
    """A distinct, deterministic open-ocean PositionPoint for a physical dev node.

    Derived from the alias (SHA-256, not the salted built-in `hash`), so seeds
    reproduce byte-for-byte and every node lands on its own point within a small
    mid-Atlantic patch (all open ocean).
    """
    h = hashlib.sha256(alias.encode()).digest()
    lat = _ATLANTIS_LAT_UDEG + int.from_bytes(h[16:20], "big") % 1_600_000  # ≤ +1.6°
    lon = _ATLANTIS_LON_UDEG + int.from_bytes(h[20:24], "big") % 1_600_000  # ≤ +1.6°
    return PositionPointGt(
        id=deterministic_uuid4(f"{_POS_ID_DOMAIN}/{alias}"),
        latitude_micro_deg=lat,
        longitude_micro_deg=lon,
    )


# A fixed canonical dev point for tests that mint ad-hoc nodes (its own Atlantis
# point; seeded so its FK resolves).
DEV_POSITION = dev_position_for("d1.atlantis-canonical")


def build_dev_universe() -> list[GNodeGt]:
    """The dev-universe GNodes — the copper backbone, six homes, and the services."""
    gnodes: list[GNodeGt] = []
    for alias, (base_class, g_node_class) in _dev_universe_specs().items():
        physical = base_class != B.Logical
        pending = alias.startswith(PENDING_HOME)
        gnodes.append(GNodeGt(
            g_node_id=deterministic_uuid4(f"{_GNODE_ID_DOMAIN}/{alias}"),
            alias=alias,
            base_class=base_class,
            g_node_class=g_node_class,
            status=S.Pending if pending else S.Active,
            position_point_id=dev_position_for(alias).id if physical else None,
            display_name=alias,
        ))
    return gnodes


def seed_dev_universe(session, reset: bool = True) -> list[GNodeGt]:
    """Load the dev universe into `session`'s database (re-runnable; resets first).

    Inserts a distinct PositionPoint per physical node, every dev GNode, and its
    alias-ledger claim. No edge rows: the tree is the alias structure, and the
    dev fleet is radial (`connectivity_edges` is reserved for non-tree copper —
    ties/loops; the harness inserts one where a test needs it). Commits, returns
    the GNodes.
    """
    if reset:
        for table in (ConnectivityEdgeSql, AliasAssignmentSql, GNodeSql, PositionPointSql):
            session.query(table).delete(synchronize_session=False)
        session.flush()

    gnodes = build_dev_universe()

    # A distinct PositionPoint per Active physical node, plus the canonical test
    # point; inserted before the GNodes so the position_point_id FKs resolve. The
    # Pending home's position stays STAGED — opaque id, no row — the fleet-ingest
    # posture (Active-physical-requires-PositionPoint lets Pending through).
    positions = {DEV_POSITION.id: DEV_POSITION}
    for g in gnodes:
        if g.position_point_id is not None and g.status != S.Pending:
            p = dev_position_for(g.alias)
            positions[p.id] = p
    for p in positions.values():
        session.add(PositionPointSql.from_gt(p))
    session.flush()

    for g in gnodes:
        session.add(GNodeSql.from_gt(g))
    session.flush()
    for g in gnodes:
        claim_alias(session, g.alias, g.g_node_id)
    session.commit()
    return gnodes
