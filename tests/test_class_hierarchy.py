"""Copper sub-tree + class-hierarchy invariants — `gnr.db.validate` (no DB).

`check_class_hierarchy` operates on an in-memory `{alias: GNodeSql}` map, so these
are pure unit tests. A node whose parent is absent from the map is skipped (parent
existence is a different invariant), which lets each test isolate one rule.
"""
import uuid

from gnr.sema.enums import BaseGNodeClass as B, GNodeStatus as S
from gnr.db.models import GNodeSql
from gnr.db.validate import check_class_hierarchy, COPPER_CLASSES


def node(alias, bc, gnc=None):
    return GNodeSql(id=str(uuid.uuid4()), alias=alias, base_class=bc,
                    g_node_class=(gnc or bc.value), status=S.Active)


def tree(*nodes):
    return {n.alias: n for n in nodes}


def flagged(violations, n):
    return any(v.g_node_id == n.id for v in violations)


def test_copper_node_is_mm_and_cn():
    assert COPPER_CLASSES == frozenset({B.ConnectivityNode, B.MarketMaker})


def test_copper_backbone_parent_closed_ok():
    # MM/CN alternating, rooted at d1 — the dev-universe backbone
    nodes = tree(
        node("d1", B.Logical),
        node("d1.isone", B.MarketMaker),
        node("d1.isone.me", B.ConnectivityNode),
        node("d1.isone.me.versant", B.ConnectivityNode),
        node("d1.isone.me.versant.keene", B.MarketMaker),
    )
    assert check_class_hierarchy(nodes) == []


def test_copper_node_under_non_copper_rejected():
    bad = node("d1.a.mm", B.MarketMaker)
    nodes = tree(node("d1.a", B.LeafTransactiveNode), bad)  # MM under an LTN
    assert flagged(check_class_hierarchy(nodes), bad)


def test_leaf_transactive_node_parent_must_be_copper():
    ok = node("d1.mm.ltn", B.LeafTransactiveNode)
    assert check_class_hierarchy(tree(node("d1.mm", B.MarketMaker), ok)) == []
    bad = node("d1.ltn1.ltn2", B.LeafTransactiveNode)
    assert flagged(check_class_hierarchy(tree(node("d1.ltn1", B.LeafTransactiveNode), bad)), bad)


def test_terminalasset_parent_must_be_ltn():
    ok = node("d1.ltn.ta", B.TerminalAsset)
    assert check_class_hierarchy(tree(node("d1.ltn", B.LeafTransactiveNode), ok)) == []
    bad = node("d1.cn.ta", B.TerminalAsset)
    assert flagged(check_class_hierarchy(tree(node("d1.cn", B.ConnectivityNode), bad)), bad)


def test_scada_parent_must_be_ltn():
    ok = node("d1.ltn.scada", B.Logical, "Scada")
    assert check_class_hierarchy(tree(node("d1.ltn", B.LeafTransactiveNode), ok)) == []
    bad = node("d1.mm.scada", B.Logical, "Scada")
    assert flagged(check_class_hierarchy(tree(node("d1.mm", B.MarketMaker), bad)), bad)


def test_other_logical_is_unconstrained():
    ws = node("d1.mm.ws", B.Logical, "WeatherForecastService")
    assert check_class_hierarchy(tree(node("d1.mm", B.MarketMaker), ws)) == []
