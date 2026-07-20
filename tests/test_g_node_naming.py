"""Naming rules for Scada and TerminalAsset GNodes — `g.node.gt` axiom 5.

Axiom 5 (AliasSuffixSemantics): an alias ends `.ta` **iff** GNodeClass is
TerminalAsset, and ends `.scada` **iff** GNodeClass is Scada. Enforced per-row by
the GNodeGt codec, so a violating instance fails to construct.
"""
import uuid

import pytest
from pydantic import ValidationError

from gnr.sema.enums import BaseGNodeClass as B, GNodeStatus as S
from gnr.sema.types import GNodeGt

PP = str(uuid.uuid4())


def gid() -> str:
    return str(uuid.uuid4())


# ---- TerminalAsset: alias ends ".ta" iff GNodeClass is TerminalAsset ----------

def test_terminalasset_with_ta_suffix_ok():
    GNodeGt(g_node_id=gid(), alias="d1.keene.beech.ta", base_class=B.TerminalAsset,
            g_node_class="TerminalAsset", status=S.Active, position_point_id=PP)


def test_terminalasset_without_ta_suffix_rejected():
    with pytest.raises(ValidationError):
        GNodeGt(g_node_id=gid(), alias="d1.keene.beech.heatpump", base_class=B.TerminalAsset,
                g_node_class="TerminalAsset", status=S.Active, position_point_id=PP)


def test_non_terminalasset_with_ta_suffix_rejected():
    # the "iff": a non-TA alias may NOT end .ta
    with pytest.raises(ValidationError):
        GNodeGt(g_node_id=gid(), alias="d1.keene.beech.ta", base_class=B.LeafTransactiveNode,
                g_node_class="LeafTransactiveNode", status=S.Active, position_point_id=PP)


# ---- Scada: alias ends ".scada" iff GNodeClass is Scada -----------------------

def test_scada_with_scada_suffix_ok():
    GNodeGt(g_node_id=gid(), alias="d1.keene.beech.scada", base_class=B.Logical,
            g_node_class="Scada", status=S.Active)


def test_scada_without_scada_suffix_rejected():
    with pytest.raises(ValidationError):
        GNodeGt(g_node_id=gid(), alias="d1.keene.beech.controller", base_class=B.Logical,
                g_node_class="Scada", status=S.Active)


def test_non_scada_with_scada_suffix_rejected():
    # the "iff": a non-Scada alias may NOT end .scada
    with pytest.raises(ValidationError):
        GNodeGt(g_node_id=gid(), alias="d1.keene.beech.scada", base_class=B.Logical,
                g_node_class="WeatherForecastService", status=S.Active)
