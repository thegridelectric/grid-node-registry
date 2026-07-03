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
    # MM/CN alternating from the forest root d1.isone (the universe token d1 is
    # NOT a GNode, so d1.isone is a forest root — its alias-parent is the token).
    nodes = tree(
        node("d1.isone", B.MarketMaker),
        node("d1.isone.me", B.ConnectivityNode),
        node("d1.isone.me.versant", B.ConnectivityNode),
        node("d1.isone.me.versant.keene", B.MarketMaker),
    )
    assert check_class_hierarchy(nodes) == []


def test_copper_node_under_non_copper_rejected():
    bad = node("d1.mm.x.mm", B.MarketMaker)
    nodes = tree(node("d1.mm.x", B.LeafTransactiveNode), bad)  # MM under an LTN
    assert flagged(check_class_hierarchy(nodes), bad)


def test_leaf_transactive_node_parent_must_be_copper():
    ok = node("d1.mm.ltn", B.LeafTransactiveNode)
    assert check_class_hierarchy(tree(node("d1.mm", B.MarketMaker), ok)) == []
    bad = node("d1.x.ltn1.ltn2", B.LeafTransactiveNode)
    assert flagged(check_class_hierarchy(tree(node("d1.x.ltn1", B.LeafTransactiveNode), bad)), bad)


def test_terminalasset_parent_must_be_ltn():
    ok = node("d1.mm.ltn.ta", B.TerminalAsset)
    assert check_class_hierarchy(tree(node("d1.mm.ltn", B.LeafTransactiveNode), ok)) == []
    bad = node("d1.mm.cn.ta", B.TerminalAsset)
    assert flagged(check_class_hierarchy(tree(node("d1.mm.cn", B.ConnectivityNode), bad)), bad)


def test_scada_parent_must_be_ltn():
    ok = node("d1.mm.ltn.scada", B.Logical, "Scada")
    assert check_class_hierarchy(tree(node("d1.mm.ltn", B.LeafTransactiveNode), ok)) == []
    bad = node("d1.mm.x.scada", B.Logical, "Scada")
    assert flagged(check_class_hierarchy(tree(node("d1.mm.x", B.MarketMaker), bad)), bad)


def test_leaf_or_ta_cannot_be_a_forest_root():
    # A forest root (two-word alias) may only be a CopperNode or a non-Scada
    # Logical node; classes that require a specific parent cannot sit at a top.
    for bad in (node("d1.ltn", B.LeafTransactiveNode),
                node("d1.ta", B.TerminalAsset),
                node("d1.scada", B.Logical, "Scada")):
        assert flagged(check_class_hierarchy(tree(bad)), bad)
    for ok in (node("d1.mm", B.MarketMaker),
               node("d1.time", B.Logical, "TimeCoordinator")):
        assert check_class_hierarchy(tree(ok)) == []


def test_other_logical_is_unconstrained():
    ws = node("d1.mm.ws", B.Logical, "WeatherForecastService")
    assert check_class_hierarchy(tree(node("d1.mm", B.MarketMaker), ws)) == []
