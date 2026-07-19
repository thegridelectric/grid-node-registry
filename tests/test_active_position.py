"""Active-physical-requires-PositionPoint invariant — `gnr.db.validate` (no DB).

`check_active_physical_have_position` operates on the in-memory `{alias:
GNodeSql}` map plus the set of `position_points` ids, so these are pure unit
tests: an Active physical GNode (base_class ≠ Logical) must hold its
PositionPoint row; Pending nodes and Logical nodes need none.
"""
import uuid

from gnr.sema.enums import BaseGNodeClass as B, GNodeStatus as S
from gnr.db.models import GNodeSql
from gnr.db.validate import check_active_physical_have_position

POS_ID = str(uuid.uuid4())


def node(alias, bc, status=S.Active, position_point_id=POS_ID):
    return GNodeSql(id=str(uuid.uuid4()), alias=alias, base_class=bc,
                    g_node_class=bc.value, status=status,
                    position_point_id=position_point_id)


def tree(*nodes):
    return {n.alias: n for n in nodes}


def flagged(violations, n):
    return any(v.g_node_id == n.id for v in violations)


def test_active_physical_with_position_row_clean():
    nodes = tree(
        node("d1.isone", B.MarketMaker),
        node("d1.isone.keene", B.ConnectivityNode),
        node("d1.isone.keene.beech", B.LeafTransactiveNode),
        node("d1.isone.keene.beech.ta", B.TerminalAsset, position_point_id=POS_ID),
    )
    assert check_active_physical_have_position(nodes, {POS_ID}) == []


def test_active_physical_without_position_row_flagged():
    # opaque id present but no position_points row behind it
    orphan = node("d1.isone.keene", B.ConnectivityNode, position_point_id=str(uuid.uuid4()))
    assert flagged(check_active_physical_have_position(tree(orphan), {POS_ID}), orphan)


def test_active_physical_with_null_position_flagged():
    bare = node("d1.isone.keene.beech", B.LeafTransactiveNode, position_point_id=None)
    assert flagged(check_active_physical_have_position(tree(bare), {POS_ID}), bare)


def test_pending_physical_without_position_clean():
    # the fleet-ingest posture: physical, positions staged, Pending until the
    # TaValidator work lands the positions and activates
    pending = node("d1.isone.keene.beech.ta", B.TerminalAsset,
                   status=S.Pending, position_point_id=None)
    assert check_active_physical_have_position(tree(pending), set()) == []


def test_active_logical_without_position_clean():
    scada = node("d1.isone.keene.beech.scada", B.Logical, position_point_id=None)
    assert check_active_physical_have_position(tree(scada), set()) == []
