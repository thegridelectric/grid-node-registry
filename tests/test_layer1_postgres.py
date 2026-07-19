"""Layer 1 — the `AuthoritySource` against a real Postgres (broker-free).

The cheap integration tier under the Layer-2 rabbit experiment: seed the `d1`
dev universe into a real Postgres and exercise `PostgresAuthority` directly.
Proves the seed loads `validate_registry`-clean, reads resolve, creates enter
through the command path, a re-parent on a mirrored home rewrites its whole
subtree — aliases and the alias-ledger claims, zero edge rows — atomically,
and a non-tree edge (a loop's closing span) is first-class while a stored
tree edge is rejected.
"""

from __future__ import annotations

import uuid

import pytest

from gnr.db.authority import CreateError, PostgresAuthority, ReparentError
from gnr.db.models import AliasAssignmentSql, CommandLogSql, ConnectivityEdgeSql, GNodeSql
from gnr.db.validate import validate_registry
from gnr.dev_universe import DEV_POSITION, DEV_UNIVERSE, seed_dev_universe
from gnr.ids import command_hash, edge_id
from gnr.sema.enums import BaseGNodeClass, GNodeStatus
from gnr.sema.types import GNodeCreateCmd, GNodeGt, GNodeReparentCmd

pytestmark = pytest.mark.integration

KEENE = "d1.isone.me.versant.keene"
BEECH_LTN = f"{KEENE}.beech"
ELM_LTN = f"{KEENE}.elm"


def _authority(session_factory) -> PostgresAuthority:
    return PostgresAuthority(session_factory=session_factory, universe=DEV_UNIVERSE)


def _new_cn():
    """A fresh ConnectivityNode to introduce under keene (alias `keene.sub`)."""
    return GNodeGt(
        g_node_id=str(uuid.uuid4()),
        alias=f"{KEENE}.sub",
        base_class=BaseGNodeClass.ConnectivityNode,
        g_node_class="ConnectivityNode",
        status=GNodeStatus.Active,
        position_point_id=DEV_POSITION.id,
        display_name="sub",
    )


@pytest.fixture
def seeded(session_factory):
    """Load the dev universe; return {alias: GNodeGt}."""
    with session_factory() as s:
        gnodes = seed_dev_universe(s)
    return {g.alias: g for g in gnodes}


def test_seed_loads_validate_clean(seeded, session_factory):
    with session_factory() as s:
        assert validate_registry(s, DEV_UNIVERSE) == []


def test_reads_resolve(seeded, session_factory):
    auth = _authority(session_factory)
    keene = seeded[KEENE]

    by_alias = auth.get_by_alias(KEENE)
    assert by_alias is not None and by_alias.g_node_id == keene.g_node_id
    assert auth.get_by_id(keene.g_node_id).alias == KEENE
    assert auth.assert_active(keene.g_node_id) is True
    assert auth.assert_active(str(uuid.uuid4())) is False

    # The dev fleet is radial: parent-child structure lives in the aliases, and
    # no non-tree edges exist, so the edge view is empty on both sides.
    edges = auth.fetch_edges(keene.g_node_id)
    assert edges.parents == [] and edges.children == []


def test_reparent_rewrites_subtree(seeded, session_factory):
    auth = _authority(session_factory)
    beech_ltn = seeded[BEECH_LTN]

    # Introduce a new ConnectivityNode under keene and move the beech home beneath
    # it — the whole beech subtree (LTN + scada + ta) re-parents in one shot.
    new_cn = GNodeGt(
        g_node_id=str(uuid.uuid4()),
        alias=f"{KEENE}.sub",
        base_class=BaseGNodeClass.ConnectivityNode,
        g_node_class="ConnectivityNode",
        status=GNodeStatus.Active,
        position_point_id=DEV_POSITION.id,
        display_name="sub",
    )
    cmd = GNodeReparentCmd(
        new_node=new_cn,
        moved_child_g_node_ids=[beech_ltn.g_node_id],
    )

    broadcast = auth.apply_reparent(cmd)

    # The broadcast carries the new node + the rewritten beech subtree.
    broadcast_aliases = {g.alias for g in broadcast.nodes}
    assert f"{KEENE}.sub" in broadcast_aliases
    assert f"{KEENE}.sub.beech" in broadcast_aliases
    assert f"{KEENE}.sub.beech.scada" in broadcast_aliases
    assert f"{KEENE}.sub.beech.ta" in broadcast_aliases

    # The DB reflects the rewrite: ids are stable, aliases moved, old freed.
    assert auth.get_by_alias(BEECH_LTN) is None
    moved = auth.get_by_alias(f"{KEENE}.sub.beech")
    assert moved is not None and moved.g_node_id == beech_ltn.g_node_id
    assert moved.prev_alias == BEECH_LTN
    assert auth.get_by_alias(f"{KEENE}.sub.beech.scada") is not None
    assert auth.get_by_alias(f"{KEENE}.sub.beech.ta") is not None

    # No edge rows anywhere: the re-parent is purely the alias rewrite (the
    # tree is the alias structure; edges are reserved for non-tree copper).
    assert broadcast.edges == []
    with session_factory() as s:
        # Registry still valid after the atomic mutation.
        assert validate_registry(s, DEV_UNIVERSE) == []
        assert s.query(ConnectivityEdgeSql).count() == 0

        # Alias-ledger: the moved node still owns its original alias forever, and
        # now also owns the new one (alias-uniqueness-through-time).
        owner = s.get(AliasAssignmentSql, f"{KEENE}.sub.beech")
        assert owner is not None and owner.g_node_id == beech_ltn.g_node_id
        old = s.get(AliasAssignmentSql, BEECH_LTN)
        assert old is not None and old.g_node_id == beech_ltn.g_node_id


def test_reparent_self_collision_aborts(seeded, session_factory):
    """A generated alias the ledger already binds to another node aborts atomically.

    Pre-create a node that permanently owns `keene.sub.beech`; a re-parent that
    would regenerate that alias for a *different* node must roll the whole thing
    back, leaving the registry untouched and still valid.
    """
    auth = _authority(session_factory)
    beech_ltn = seeded[BEECH_LTN]
    colliding_alias = f"{KEENE}.sub.beech"

    # A long-retired node that once owned the alias the re-parent would generate.
    with session_factory() as s:
        squatter = GNodeGt(
            g_node_id=str(uuid.uuid4()),
            alias=colliding_alias,
            base_class=BaseGNodeClass.LeafTransactiveNode,
            g_node_class="LeafTransactiveNode",
            status=GNodeStatus.PermanentlyDeactivated,
            position_point_id=DEV_POSITION.id,
            display_name="squatter",
        )
        from gnr.db.alias_ledger import claim_alias

        s.add(GNodeSql.from_gt(squatter))
        s.flush()
        claim_alias(s, colliding_alias, squatter.g_node_id)
        s.commit()
        squatter_id = squatter.g_node_id

    new_cn = GNodeGt(
        g_node_id=str(uuid.uuid4()),
        alias=f"{KEENE}.sub",
        base_class=BaseGNodeClass.ConnectivityNode,
        g_node_class="ConnectivityNode",
        status=GNodeStatus.Active,
        position_point_id=DEV_POSITION.id,
        display_name="sub",
    )
    cmd = GNodeReparentCmd(new_node=new_cn, moved_child_g_node_ids=[beech_ltn.g_node_id])

    # The PRE-CHECK fails up front with an explicit collision error naming the
    # alias — not a raw ledger abort mid-rewrite.
    with pytest.raises(ReparentError, match="alias collision") as exc_info:
        auth.apply_reparent(cmd)
    assert colliding_alias in str(exc_info.value)

    # Nothing moved: beech keeps its original alias, the new CN never landed.
    assert auth.get_by_alias(BEECH_LTN) is not None
    assert auth.get_by_id(new_cn.g_node_id) is None
    # The colliding alias still belongs to the squatter, not beech.
    with session_factory() as s:
        owner = s.get(AliasAssignmentSql, colliding_alias)
        assert owner.g_node_id == squatter_id


def test_reparent_command_logged(seeded, session_factory):
    """Distributed-readiness #2: the applied command is appended to the
    content-addressed command log in the same transaction."""
    auth = _authority(session_factory)
    beech_ltn = seeded[BEECH_LTN]
    cmd = GNodeReparentCmd(new_node=_new_cn(), moved_child_g_node_ids=[beech_ltn.g_node_id])

    auth.apply_reparent(cmd)

    with session_factory() as s:
        row = s.get(CommandLogSql, command_hash(cmd.to_bytes()))
        assert row is not None and row.type_name == "g.node.reparent.cmd"


def test_reparent_replay_idempotent(seeded, session_factory):
    """Distributed-readiness #2: re-applying an identical command is idempotent
    success — its content hash is already in the log, so the retrier gets the
    affected subtree's current state back (never a double-apply, never an error
    it can't distinguish from a rejection)."""
    auth = _authority(session_factory)
    beech_ltn = seeded[BEECH_LTN]
    cmd = GNodeReparentCmd(new_node=_new_cn(), moved_child_g_node_ids=[beech_ltn.g_node_id])

    first = auth.apply_reparent(cmd)
    replay = auth.apply_reparent(cmd)  # e.g. an at-least-once retry after a timeout

    # Same current state back; nothing double-applied; registry still valid.
    assert {g.alias for g in replay.nodes} == {g.alias for g in first.nodes}
    assert {g.g_node_id for g in replay.nodes} == {g.g_node_id for g in first.nodes}
    with session_factory() as s:
        assert validate_registry(s, DEV_UNIVERSE) == []
        assert s.query(GNodeSql).filter_by(alias=f"{KEENE}.sub").count() == 1


# ---- the create path (populate's write) -------------------------------------


def _new_home_cn(alias: str) -> GNodeGt:
    return GNodeGt(
        g_node_id=str(uuid.uuid4()),
        alias=alias,
        base_class=BaseGNodeClass.ConnectivityNode,
        g_node_class="ConnectivityNode",
        status=GNodeStatus.Active,
        position_point_id=DEV_POSITION.id,
        display_name=alias.rsplit(".", 1)[-1],
    )


def test_create_enters_through_command_path(seeded, session_factory):
    """apply_create claims the alias, logs the command, touches no edge rows."""
    auth = _authority(session_factory)
    node = _new_home_cn(f"{KEENE}.sub9")
    cmd = GNodeCreateCmd(new_node=node)

    forest = auth.apply_create(cmd)

    assert [g.alias for g in forest.nodes] == [node.alias]
    assert forest.edges == []
    assert auth.get_by_alias(node.alias).g_node_id == node.g_node_id
    with session_factory() as s:
        assert validate_registry(s, DEV_UNIVERSE) == []
        owner = s.get(AliasAssignmentSql, node.alias)
        assert owner is not None and owner.g_node_id == node.g_node_id
        row = s.get(CommandLogSql, command_hash(cmd.to_bytes()))
        assert row is not None and row.type_name == "g.node.create.cmd"
        assert s.query(ConnectivityEdgeSql).count() == 0

    # Replay is idempotent success, not a double-apply.
    replay = auth.apply_create(cmd)
    assert [g.alias for g in replay.nodes] == [node.alias]
    with session_factory() as s:
        assert s.query(GNodeSql).filter_by(alias=node.alias).count() == 1


def test_create_requires_parent_first(seeded, session_factory):
    """Parents-first: a node under a nonexistent parent is rejected."""
    auth = _authority(session_factory)
    orphan = _new_home_cn(f"{KEENE}.nowhere.orphan")
    with pytest.raises(CreateError, match="create parents first"):
        auth.apply_create(GNodeCreateCmd(new_node=orphan))
    assert auth.get_by_id(orphan.g_node_id) is None


def test_create_rejects_foreign_universe(seeded, session_factory):
    """The universe guard-rail on the write path: this registry serves d1."""
    auth = _authority(session_factory)
    foreign = _new_home_cn("hw1.isone.me.versant.keene.sub9")
    with pytest.raises(CreateError, match="serves 'd1'"):
        auth.apply_create(GNodeCreateCmd(new_node=foreign))


def test_create_rejects_recycled_alias(seeded, session_factory):
    """Alias-uniqueness-through-time holds at create: a vacated alias may never
    bind a different GNodeId."""
    auth = _authority(session_factory)
    beech_ltn = seeded[BEECH_LTN]
    # Move beech away so its old alias is vacated (live-unique would allow reuse).
    auth.apply_reparent(GNodeReparentCmd(
        new_node=_new_cn(), moved_child_g_node_ids=[beech_ltn.g_node_id],
    ))
    pretender = GNodeGt(
        g_node_id=str(uuid.uuid4()),
        alias=BEECH_LTN,
        base_class=BaseGNodeClass.LeafTransactiveNode,
        g_node_class="LeafTransactiveNode",
        status=GNodeStatus.Active,
        position_point_id=DEV_POSITION.id,
        display_name="pretender",
    )
    with pytest.raises(CreateError, match="permanently owned"):
        auth.apply_create(GNodeCreateCmd(new_node=pretender))


# ---- non-tree edges: how a loop enters the registry --------------------------


def test_loop_enters_as_non_tree_edge(seeded, session_factory):
    """HOW A LOOP OCCURS: the copper between beech and elm closes a loop the
    spanning tree cannot express, so it enters as a `connectivity_edges` row
    between two nodes neither of which is the other's alias-parent. The tree
    itself is never stored — it is the alias structure."""
    beech = seeded[BEECH_LTN]
    elm = seeded[ELM_LTN]
    with session_factory() as s:
        s.add(ConnectivityEdgeSql(
            id=edge_id(beech.g_node_id, elm.g_node_id),
            from_g_node_id=beech.g_node_id,
            to_g_node_id=elm.g_node_id,
            status=GNodeStatus.Active,
        ))
        s.commit()
        # A non-tree edge is first-class: the registry stays valid.
        assert validate_registry(s, DEV_UNIVERSE) == []

    auth = _authority(session_factory)
    # It is visible from both endpoints…
    assert [e.to_g_node_id for e in auth.fetch_edges(beech.g_node_id).children] == [elm.g_node_id]
    assert [e.from_g_node_id for e in auth.fetch_edges(elm.g_node_id).parents] == [beech.g_node_id]
    # …and rides any forest that contains both endpoints.
    forest = auth.get_forest([KEENE])
    assert len(forest.edges) == 1
    assert forest.edges[0].id == edge_id(beech.g_node_id, elm.g_node_id)


def test_stored_tree_edge_is_rejected(seeded, session_factory):
    """A stored parent-child edge is a modeling error, either direction: the
    tree is derived from aliases, never stored."""
    keene = seeded[KEENE]
    beech = seeded[BEECH_LTN]
    with session_factory() as s:
        s.add(ConnectivityEdgeSql(
            id=edge_id(keene.g_node_id, beech.g_node_id),
            from_g_node_id=keene.g_node_id,
            to_g_node_id=beech.g_node_id,
            status=GNodeStatus.Active,
        ))
        s.commit()
        violations = validate_registry(s, DEV_UNIVERSE)
        assert len(violations) == 1
        assert violations[0].invariant == "edge_non_tree"
        assert "mirrors a parent-child tree edge" in violations[0].detail


def test_create_pending_fleet_parents_first(seeded, session_factory):
    """Fleet bootstrap: everything enters Pending, parents-first (activation
    comes with the TaValidator work). A Pending parent accepts a Pending
    child; an Active child under a Pending parent is rejected by the
    parent-closed-active invariant."""
    auth = _authority(session_factory)

    def pending_cn(alias: str) -> GNodeGt:
        node = _new_home_cn(alias)
        return node.model_copy(update={"status": GNodeStatus.Pending})

    parent = pending_cn(f"{KEENE}.pfx")
    child = pending_cn(f"{KEENE}.pfx.sub")
    auth.apply_create(GNodeCreateCmd(new_node=parent))
    auth.apply_create(GNodeCreateCmd(new_node=child))
    assert auth.get_by_alias(child.alias).status == GNodeStatus.Pending
    with session_factory() as s:
        assert validate_registry(s, DEV_UNIVERSE) == []

    eager = _new_home_cn(f"{KEENE}.pfx.eager")  # Active under a Pending parent
    with pytest.raises(CreateError, match="parent_closed_active"):
        auth.apply_create(GNodeCreateCmd(new_node=eager))


def test_create_active_physical_without_position_rejected(seeded, session_factory):
    """The write guardrail for Active-physical-requires-PositionPoint: an
    Active physical GNode whose position_point_id has no `position_points` row
    bounces, and the whole transaction rolls back (no node row, no ledger
    claim). The same alias then lands as Pending with an opaque position id —
    the fleet-ingest posture (activation arrives with the TaValidator
    positions)."""
    auth = _authority(session_factory)
    alias = f"{KEENE}.sub8"
    ghost = _new_home_cn(alias).model_copy(
        update={"position_point_id": str(uuid.uuid4())}  # opaque id, no row
    )
    with pytest.raises(CreateError, match="active_position"):
        auth.apply_create(GNodeCreateCmd(new_node=ghost))
    with session_factory() as s:
        assert s.query(GNodeSql).filter_by(alias=alias).count() == 0
        assert s.get(AliasAssignmentSql, alias) is None

    pending = ghost.model_copy(update={"status": GNodeStatus.Pending})
    forest = auth.apply_create(GNodeCreateCmd(new_node=pending))
    assert [g.alias for g in forest.nodes] == [alias]
