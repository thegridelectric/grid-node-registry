"""The stop-gap write-authorization gate — `_check_proof` on the write path.

When the deploy configures `write_proof_sha256`, every write command must
carry the matching opaque `Proof`: missing or wrong → refused before any
state is touched (no node row, no ledger claim, no command_log entry — an
unproven command learns nothing). Unset → gate off (the dev-harness posture,
covered by every other Layer-1 test).
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from gnr.db.authority import CreateError, PostgresAuthority, ReparentError
from gnr.db.models import AliasAssignmentSql, CommandLogSql, GNodeSql
from gnr.dev_universe import DEV_POSITION, seed_dev_universe
from gnr.sema.enums import BaseGNodeClass as B, GNodeStatus as S
from gnr.sema.types import GNodeCreateCmd, GNodeGt, GNodeReparentCmd

pytestmark = pytest.mark.integration

SECRET = "open-sesame-but-longer"
SECRET_SHA = hashlib.sha256(SECRET.encode()).hexdigest()
KEENE = "d1.isone.me.versant.keene"


@pytest.fixture
def gated(session_factory):
    with session_factory() as s:
        seed_dev_universe(s)
    return PostgresAuthority(
        session_factory=session_factory, universe="d1",
        write_proof_sha256=SECRET_SHA,
    )


def _pending_cn(alias: str) -> GNodeGt:
    return GNodeGt(
        g_node_id=str(uuid.uuid4()), alias=alias,
        base_class=B.ConnectivityNode, g_node_class="ConnectivityNode",
        status=S.Pending, position_point_id=str(uuid.uuid4()),
        display_name=alias.rsplit(".", 1)[-1],
    )


def test_create_without_proof_refused(gated, session_factory):
    node = _pending_cn(f"{KEENE}.gate1")
    with session_factory() as s:
        logs_before = s.query(CommandLogSql).count()
    with pytest.raises(CreateError, match="Proof"):
        gated.apply_create(GNodeCreateCmd(new_node=node))
    with session_factory() as s:
        assert s.query(GNodeSql).filter_by(alias=node.alias).count() == 0
        assert s.get(AliasAssignmentSql, node.alias) is None
        assert s.query(CommandLogSql).count() == logs_before


def test_create_with_wrong_proof_refused(gated):
    with pytest.raises(CreateError, match="Proof"):
        gated.apply_create(GNodeCreateCmd(
            new_node=_pending_cn(f"{KEENE}.gate2"), proof="wrong",
        ))


def test_create_with_proof_lands(gated):
    node = _pending_cn(f"{KEENE}.gate3")
    forest = gated.apply_create(GNodeCreateCmd(new_node=node, proof=SECRET))
    assert [g.alias for g in forest.nodes] == [node.alias]


def _active_cn(alias: str) -> GNodeGt:
    # Active (with the seeded canonical position) so the re-parent outcome is
    # decided by the proof gate, not by parent-closed-active.
    return GNodeGt(
        g_node_id=str(uuid.uuid4()), alias=alias,
        base_class=B.ConnectivityNode, g_node_class="ConnectivityNode",
        status=S.Active, position_point_id=DEV_POSITION.id,
        display_name=alias.rsplit(".", 1)[-1],
    )


def test_reparent_without_proof_refused(gated, session_factory):
    with session_factory() as s:
        beech_id = s.query(GNodeSql).filter_by(alias=f"{KEENE}.beech").one().id
    with pytest.raises(ReparentError, match="Proof"):
        gated.apply_reparent(GNodeReparentCmd(
            new_node=_active_cn(f"{KEENE}.sub"),
            moved_child_g_node_ids=[beech_id],
        ))
    assert gated.get_by_alias(f"{KEENE}.beech") is not None  # nothing moved


def test_reparent_with_proof_lands(gated, session_factory):
    with session_factory() as s:
        beech_id = s.query(GNodeSql).filter_by(alias=f"{KEENE}.beech").one().id
    gated.apply_reparent(GNodeReparentCmd(
        new_node=_active_cn(f"{KEENE}.sub"),
        moved_child_g_node_ids=[beech_id], proof=SECRET,
    ))
    moved = gated.get_by_alias(f"{KEENE}.sub.beech")
    assert moved is not None and moved.g_node_id == beech_id
