"""Seed a dev universe (`d1.*`) — a `validate_registry`-clean forest for harness/dev.

A static, self-contained description of a dev fleet: a copper backbone, six
Active homes (each an LTN + TerminalAsset + Scada), one **Pending** home
(`willow` — created locationless, the pending-first posture; its position
point and activation arrive with the TaValidator work), and the
logical simulation services. No external inputs — the aliases + classes live
here as a flat map, so nothing breaks when the layout pipeline changes
elsewhere. The universe token `d1` is **not** a
GNode (it is a namespace); the top-level copper nodes are **forest roots**. Every
GNode carries a fresh GNodeId — a simulation of the fleet, not the production nodes
— so it runs against a dev broker + database without touching real money.
"""

from __future__ import annotations

from gnr.db.alias_ledger import claim_alias
from gnr.db.models import (
    AliasAssignmentSql,
    ConnectivityEdgeSql,
    GNodeSql,
    PositionPointSql,
)
from gnr.ids import deterministic_uuid4
from gnr.sema.enums import BaseGNodeClass as B
from gnr.sema.enums import GNodeStatus as S
from gnr.sema.property_format import LeftRightDot
from gnr.sema.types import GNodeGt

DEV_UNIVERSE = "d1"
KEENE = "d1.isone.me.versant.keene"
_HOMES = ("beech", "elm", "fir", "maple", "oak", "spruce", "willow")
# willow is the dev universe's non-Active home: Pending and locationless —
# the posture every physical GNode is born into (pending-first); location
# registration and activation arrive with the TaValidator work.
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


# Dev physical nodes each get a DISTINCT location identity (real grid nodes
# have distinct positions; a single shared point was a test smell). Rows are
# identity-only — the coordinate payload is ciphertext populated by the
# validator registration flow, which no dev universe runs.

# Hash domain-separation tags for deterministic dev ids — internal salts, NOT Sema
# names (see gnr.ids). Slash-delimited so they can't be read as a left.right.dot.
_POS_ID_DOMAIN = "gnr-det-id/dev-universe-position"
_GNODE_ID_DOMAIN = "gnr-det-id/dev-universe-gnode"


def dev_position_id_for(alias: LeftRightDot) -> str:
    """A distinct, deterministic location identity for a physical dev node.

    Derived from the alias, so seeds reproduce byte-for-byte and every node
    holds its own registered identity row.
    """
    return deterministic_uuid4(f"{_POS_ID_DOMAIN}/{alias}")


# A fixed canonical dev location identity for tests that mint ad-hoc nodes
# (seeded so its FK resolves).
DEV_POSITION_ID = dev_position_id_for("d1.atlantis-canonical")


def build_dev_universe() -> list[GNodeGt]:
    """The dev-universe GNodes — the copper backbone, six homes, and the services."""
    gnodes: list[GNodeGt] = []
    for alias, (base_class, g_node_class) in _dev_universe_specs().items():
        physical = base_class != B.Logical
        pending = alias.startswith(PENDING_HOME)
        gnodes.append(
            GNodeGt(
                g_node_id=deterministic_uuid4(f"{_GNODE_ID_DOMAIN}/{alias}"),
                alias=alias,
                base_class=base_class,
                g_node_class=g_node_class,
                status=S.Pending if pending else S.Active,
                # Pending home: created locationless (the pending-first posture);
                # Active physical nodes hold their registered location identity.
                position_point_id=(
                    dev_position_id_for(alias) if physical and not pending else None
                ),
                display_name=alias,
            )
        )
    return gnodes


def seed_dev_universe(session, reset: bool = True) -> list[GNodeGt]:
    """Load the dev universe into `session`'s database (re-runnable; resets first).

    Inserts a distinct location-identity row per Active physical node, every
    dev GNode, and its alias-ledger claim. No edge rows: the tree is the alias structure, and the
    dev fleet is radial (`connectivity_edges` is reserved for non-tree copper —
    ties/loops; the harness inserts one where a test needs it). Commits, returns
    the GNodes.
    """
    if reset:
        for table in (
            ConnectivityEdgeSql,
            AliasAssignmentSql,
            GNodeSql,
            PositionPointSql,
        ):
            session.query(table).delete(synchronize_session=False)
        session.flush()

    gnodes = build_dev_universe()

    # A distinct location-identity row per Active physical node, plus the
    # canonical test id; inserted before the GNodes so the position_point_id
    # FKs resolve. The Pending home is created locationless — the
    # pending-first posture (its identity arrives with registration, its
    # position point by activation).
    position_ids = {DEV_POSITION_ID}
    position_ids.update(
        g.position_point_id for g in gnodes if g.position_point_id is not None
    )
    for pid in sorted(position_ids):
        session.add(PositionPointSql(id=pid))
    session.flush()

    for g in gnodes:
        session.add(GNodeSql.from_gt(g))
    session.flush()
    for g in gnodes:
        claim_alias(session, g.alias, g.g_node_id)
    session.commit()
    return gnodes
