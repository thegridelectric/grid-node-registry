"""Seed a dev universe (`d1.*`) that mirrors the deployed fleet + its parent GNodes.

Reads the deployed home layouts from the sibling `tlayouts/output`, re-aliases the
universe `hw1 → d1`, and — with the copper-backbone parent chain — seeds the
registry so it validates clean. The dev universe carries **fresh GNodeIds**: it is
a simulation of the fleet for harness/dev work, not the production nodes
themselves, so it can run against a dev broker + database without touching real
money. Imports no scada code — only the layout JSON + the registry's own types.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from gnr.db.alias_ledger import claim_alias
from gnr.db.models import (
    AliasAssignmentSql,
    ConnectivityEdgeSql,
    GNodeSql,
    PositionPointSql,
)
from gnr.db.validate import parent_alias
from gnr.sema.enums import BaseGNodeClass as B, GNodeStatus as S
from gnr.sema.types import GNodeGt, PositionPointGt

DEV_UNIVERSE = "d1"
PROD_UNIVERSE = "hw1"

# The copper backbone the deployed homes hang under (alias, base_class).
PARENT_CHAIN: list[tuple[str, B]] = [
    ("d1", B.Logical),  # universe root
    ("d1.isone", B.MarketMaker),
    ("d1.isone.me", B.ConnectivityNode),
    ("d1.isone.me.versant", B.ConnectivityNode),
    ("d1.isone.me.versant.keene", B.MarketMaker),
]

# One placeholder location shared by all physical dev nodes (axiom 2 needs a
# PositionPoint; the harness tests topology/identity, not geography).
DEV_POSITION = PositionPointGt(
    id="11111111-1111-4111-8111-111111111111",
    latitude_micro_deg=44_570_000,
    longitude_micro_deg=-69_710_000,
)


def _default_tlayouts_dir() -> Path:
    override = os.environ.get("GNR_TLAYOUTS_DIR")
    if override:
        return Path(override)
    # .../GridWorks/grid-node-registry/src/gnr/dev_universe.py -> .../GridWorks/tlayouts/output
    return Path(__file__).resolve().parents[3] / "tlayouts" / "output"


def _to_dev(alias: str) -> str:
    """Re-alias a production alias into the dev universe (`hw1.… → d1.…`)."""
    if alias.startswith(PROD_UNIVERSE + "."):
        return DEV_UNIVERSE + "." + alias.split(".", 1)[1]
    return alias


def _home_nodes(layout: dict) -> list[tuple[str, B, str]]:
    """(alias, base_class, g_node_class) for a home's LTN, Scada, and TerminalAsset."""
    scada_alias = _to_dev(layout["MyScadaGNode"]["Alias"])
    ta_alias = _to_dev(layout["MyTerminalAssetGNode"]["Alias"])
    ltn_block = layout.get("MyLeafTransactiveNodeGNode")
    # `fir` has no LTN block — derive it as the Scada's parent (drop `.scada`).
    ltn_alias = _to_dev(ltn_block["Alias"]) if ltn_block else scada_alias.rsplit(".", 1)[0]
    return [
        (ltn_alias, B.LeafTransactiveNode, "LeafTransactiveNode"),
        (scada_alias, B.Logical, "Scada"),
        (ta_alias, B.TerminalAsset, "TerminalAsset"),
    ]


def build_dev_universe(tlayouts_dir: str | Path | None = None) -> list[GNodeGt]:
    """The dev-universe GNodes — parent chain + every uploaded home's LTN/Scada/TA."""
    tdir = Path(tlayouts_dir) if tlayouts_dir else _default_tlayouts_dir()
    specs: list[tuple[str, B, str]] = [(a, bc, bc.value) for (a, bc) in PARENT_CHAIN]
    for path in sorted(tdir.glob("*.uploaded.json")):
        specs += _home_nodes(json.loads(path.read_text()))

    gnodes: list[GNodeGt] = []
    seen: set[str] = set()
    for alias, base_class, g_node_class in specs:
        if alias in seen:
            continue
        seen.add(alias)
        physical = base_class != B.Logical
        gnodes.append(GNodeGt(
            g_node_id=str(uuid.uuid4()),
            alias=alias,
            base_class=base_class,
            g_node_class=g_node_class,
            status=S.Active,
            position_point_id=DEV_POSITION.id if physical else None,
            display_name=alias,
        ))
    return gnodes


def seed_dev_universe(session, tlayouts_dir: str | Path | None = None, reset: bool = True) -> list[GNodeGt]:
    """Load the dev universe into `session`'s database (re-runnable; resets first).

    Inserts the placeholder PositionPoint, every dev GNode, its alias-ledger claim,
    and a covering parent→child edge for each non-root node. Commits, returns the
    GNodes.
    """
    if reset:
        for table in (ConnectivityEdgeSql, AliasAssignmentSql, GNodeSql, PositionPointSql):
            session.query(table).delete(synchronize_session=False)
        session.flush()

    if session.get(PositionPointSql, DEV_POSITION.id) is None:
        session.add(PositionPointSql.from_gt(DEV_POSITION))

    gnodes = build_dev_universe(tlayouts_dir)
    by_alias = {g.alias: g for g in gnodes}
    for g in gnodes:
        session.add(GNodeSql.from_gt(g))
    session.flush()
    for g in gnodes:
        claim_alias(session, g.alias, g.g_node_id)
    for g in gnodes:
        pa = parent_alias(g.alias)
        if pa is not None and pa in by_alias:
            session.add(ConnectivityEdgeSql(
                id=str(uuid.uuid4()),
                from_g_node_id=by_alias[pa].g_node_id,
                to_g_node_id=g.g_node_id,
                status=S.Active,
            ))
    session.commit()
    return gnodes
