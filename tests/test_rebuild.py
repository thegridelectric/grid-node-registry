"""Rebuild-from-capture — the restore path against real Postgres (Layer 1).

Genesis enters as commands (the fleet posture: everything Pending,
parents-first); the capture stream is each published command body plus each
resulting `g.node.forest` broadcast, in order. The proof: wipe the registry,
replay the capture, land in an identical validate-clean state — every
broadcast checkpoint matching (deterministic apply), and a command the
registry originally refused re-refusing on replay (executor *Durability*).
"""

from __future__ import annotations

import uuid

import pytest

from gnr.db.authority import CreateError, PostgresAuthority
from gnr.db.models import (
    AliasAssignmentSql,
    CommandLogSql,
    ConnectivityEdgeSql,
    GNodeSql,
    PositionPointSql,
)
from gnr.db.validate import validate_registry
from gnr.rebuild import checkpoint_state, replay
from gnr.sema.enums import BaseGNodeClass as B
from gnr.sema.enums import GNodeStatus as S
from gnr.sema.types import GNodeCreateCmd, GNodeGt, GNodeReparentCmd

pytestmark = pytest.mark.integration

UNIVERSE = "d1"


def _wipe(session_factory):
    with session_factory() as s:
        for table in (
            ConnectivityEdgeSql,
            AliasAssignmentSql,
            GNodeSql,
            PositionPointSql,
            CommandLogSql,
        ):
            s.query(table).delete(synchronize_session=False)
        s.commit()


def _pending(alias: str, bc: B) -> GNodeGt:
    return GNodeGt(
        g_node_id=str(uuid.uuid4()),
        alias=alias,
        base_class=bc,
        g_node_class=bc.value,
        status=S.Pending,
        # Pending-first (create.cmd/001 axiom 1): a location is registered
        # after creation, never carried in the command.
        position_point_id=None,
        display_name=alias.rsplit(".", 1)[-1],
    )


def _line(sema_type) -> bytes:
    return sema_type.to_bytes()


def test_wipe_replay_reaches_identical_state(session_factory):
    _wipe(session_factory)
    auth = PostgresAuthority(session_factory=session_factory, universe=UNIVERSE)
    capture: list[bytes] = []

    # Genesis: a Pending copper chain + home, parents-first, as commands.
    chain = [
        _pending("d1.isone", B.MarketMaker),
        _pending("d1.isone.keene", B.ConnectivityNode),
        _pending("d1.isone.keene.willow", B.LeafTransactiveNode),
    ]
    for node in chain:
        cmd = GNodeCreateCmd(new_node=node)
        capture.append(_line(cmd))
        capture.append(_line(auth.apply_create(cmd)))

    # A refused command — the ear hears every publish, including ones the
    # registry says no to: a second create claiming a held alias under a
    # fresh GNodeId (aliases are never recycled).
    ghost = _pending("d1.isone.keene.willow", B.LeafTransactiveNode)
    ghost_cmd = GNodeCreateCmd(new_node=ghost)
    capture.append(_line(ghost_cmd))
    with pytest.raises(CreateError):
        auth.apply_create(ghost_cmd)

    # A re-parent: introduce keene.sub, move the willow subtree beneath it.
    sub = _pending("d1.isone.keene.sub", B.ConnectivityNode)
    rcmd = GNodeReparentCmd(new_node=sub, moved_child_g_node_ids=[chain[2].g_node_id])
    capture.append(_line(rcmd))
    capture.append(_line(auth.apply_reparent(rcmd)))

    original = auth.get_forest(["d1.isone"]).to_dict()

    # Wipe → replay → identical, validate-clean, checkpoints all matching.
    _wipe(session_factory)
    report = replay(capture, auth)

    assert report.ok, report.mismatches
    assert report.applied == 4
    assert report.refused == 1
    assert report.checkpoints == 4
    assert report.skipped_type_names == set()
    assert checkpoint_state(
        auth.get_forest(["d1.isone"]).to_dict()
    ) == checkpoint_state(original)
    with session_factory() as s:
        assert validate_registry(s, UNIVERSE) == []
