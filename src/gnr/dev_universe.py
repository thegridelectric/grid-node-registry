"""Seed a dev universe (`d1.*`) — a `validate_registry`-clean forest for harness/dev.

A static, self-contained description of a dev fleet: a copper backbone with
two local markets (`keene` under Maine, `newhaven` under Connecticut), the
Active homes under each (an LTN + TerminalAsset + Scada apiece), one
**Pending** home (`willow` under keene — created locationless, the
pending-first posture; its position point and activation arrive with the
TaValidator work), and the logical simulation services. No external inputs —
the aliases + classes live here as a flat map, so nothing breaks when the
layout pipeline changes elsewhere. The universe token `d1` is **not** a
GNode (it is a namespace); the top-level copper nodes and the cloud services
are **forest roots**. Every GNode's id is a function of its alias — a
simulation of the fleet, not the production nodes — so it runs against a dev
broker + database without touching real money.

This seed is the one source of d1 GNode identity. `export_dev_universe`
writes it as one `g.node.gt` file per GNode; every other repo that needs a
d1 alias, GNodeId or PositionPointId copies its file from that export at a
pinned registry commit and never types one by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

from gnr.db.alias_ledger import claim_alias
from gnr.db.models import (
    AliasAssignmentSql,
    ConnectivityEdgeSql,
    GNodeSql,
    PositionPointSql,
)
from gnr.display_name import default_display_name
from gnr.ids import deterministic_uuid4
from gnr.sema.enums import BaseGNodeClass as B
from gnr.sema.enums import GNodeStatus as S
from gnr.sema.property_format import LeftRightDot
from gnr.sema.types import GNodeGt

DEV_UNIVERSE = "d1"
KEENE = "d1.isone.me.versant.keene"
NEWHAVEN = "d1.isone.ct.newhaven"
# Each local market's homes. `beech1` and `beech2` are twins: two leaves
# built from one spec, so two variants run head to head in one market; the
# alias says nothing about the variant, which is only in the operational
# params. A home that exists only as a simulation takes a number; a home
# that stands in for one real house keeps its name.
KEENE_HOMES = (
    "beech1",
    "beech2",
    "elm",
    "fir",
    "larch",
    "maple",
    "oak",
    "spruce",
    "willow",
)
NEWHAVEN_HOMES = ("hazel1", "orange1", "willow1")
# willow is the dev universe's non-Active home: Pending and locationless —
# the posture every physical GNode is born into (pending-first); location
# registration and activation arrive with the TaValidator work.
PENDING_HOME = f"{KEENE}.willow"


def _dev_universe_specs() -> dict[LeftRightDot, tuple[B, str]]:
    """The dev universe as a flat `alias -> (base_class, g_node_class)` map.

    `d1.isone` and the cloud services are **forest roots** (their alias-parent
    is the bare universe token `d1`, which is not a GNode): a cloud GNode
    service that is not grid topology hangs directly under the universe root.
    Copper (`MarketMaker`/`ConnectivityNode`) g_node_class equals the
    base_class value (axiom 1); the Logical services carry their role name.
    """
    specs: dict[LeftRightDot, tuple[B, str]] = {
        # copper backbone — d1.isone is a forest root
        "d1.isone": (B.MarketMaker, "MarketMaker"),
        "d1.isone.me": (B.ConnectivityNode, "ConnectivityNode"),
        "d1.isone.me.versant": (B.ConnectivityNode, "ConnectivityNode"),
        KEENE: (B.MarketMaker, "MarketMaker"),
        "d1.isone.ct": (B.ConnectivityNode, "ConnectivityNode"),
        NEWHAVEN: (B.MarketMaker, "MarketMaker"),
        # logical simulation services, each a Logical forest root
        "d1.time": (B.Logical, "TimeCoordinator"),
        "d1.flo": (B.Logical, "Flo"),
        "d1.weather": (B.Logical, "WeatherForecastService"),
        "d1.price": (B.Logical, "PriceForecastService"),
    }
    for market, homes in ((KEENE, KEENE_HOMES), (NEWHAVEN, NEWHAVEN_HOMES)):
        for home in homes:
            specs[f"{market}.{home}"] = (B.LeafTransactiveNode, "LeafTransactiveNode")
            specs[f"{market}.{home}.ta"] = (B.TerminalAsset, "TerminalAsset")
            specs[f"{market}.{home}.scada"] = (B.Logical, "Scada")
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
    """The dev-universe GNodes — the copper backbone, the homes, and the services."""
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
                display_name=default_display_name(alias, g_node_class),
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


def export_filename(g: GNodeGt) -> str:
    """The export file of one GNode, in the sema filename grammar:
    `<alias>-<type.name>-<version>.json`."""
    return f"{g.alias}-{g.type_name}-{g.version}.json"


def export_dev_universe(out_dir: Path) -> list[Path]:
    """Write the dev universe as one `g.node.gt` wire-form file per GNode.

    `out_dir` ends up holding exactly the seed: an export file for an
    alias the seed lacks is removed. Returns the files written, in
    alias order.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    gnodes = sorted(build_dev_universe(), key=lambda g: g.alias)
    wanted = {export_filename(g) for g in gnodes}
    for stale in out_dir.glob("*-g.node.gt-*.json"):
        if stale.name not in wanted:
            stale.unlink()
    written: list[Path] = []
    for g in gnodes:
        path = out_dir / export_filename(g)
        path.write_text(json.dumps(g.to_dict(), indent=2) + "\n")
        written.append(path)
    return written
