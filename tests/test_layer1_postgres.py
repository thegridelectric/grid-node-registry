"""Layer 1 — the `AuthoritySource` against a real Postgres (broker-free).

The cheap integration tier under the Layer-2 rabbit experiment: seed the `d1`
dev universe into a real Postgres and exercise `PostgresAuthority` directly.
Proves the seed loads `validate_registry`-clean, reads resolve, and a re-parent
on a mirrored home rewrites its whole subtree — aliases, edges, and the
alias-ledger claims — atomically, leaving the registry valid.
"""

from __future__ import annotations

import uuid

import pytest

from gnr.db.authority import PostgresAuthority
from gnr.db.models import AliasAssignmentSql, ConnectivityEdgeSql, GNodeSql
from gnr.db.validate import validate_registry
from gnr.dev_universe import DEV_POSITION, seed_dev_universe
from gnr.sema.enums import BaseGNodeClass, GNodeStatus
from gnr.sema.types import GNodeGt, GNodeReparentCmd

pytestmark = pytest.mark.integration

KEENE = "d1.isone.me.versant.keene"
BEECH_LTN = f"{KEENE}.beech"


@pytest.fixture
def seeded(session_factory):
    """Load the dev universe; return {alias: GNodeGt}."""
    with session_factory() as s:
        gnodes = seed_dev_universe(s)
    return {g.alias: g for g in gnodes}


def test_seed_loads_validate_clean(seeded, session_factory):
    with session_factory() as s:
        assert validate_registry(s) == []


def test_reads_resolve(seeded, session_factory):
    auth = PostgresAuthority(session_factory=session_factory)
    keene = seeded[KEENE]

    by_alias = auth.get_by_alias(KEENE)
    assert by_alias is not None and by_alias.g_node_id == keene.g_node_id
    assert auth.get_by_id(keene.g_node_id).alias == KEENE
    assert auth.assert_active(keene.g_node_id) is True
    assert auth.assert_active(str(uuid.uuid4())) is False

    # keene (MarketMaker) parents the homes; beech LTN is one child edge.
    edges = auth.fetch_edges(keene.g_node_id)
    child_ids = {e.to_g_node_id for e in edges.children}
    assert seeded[BEECH_LTN].g_node_id in child_ids


def test_reparent_rewrites_subtree(seeded, session_factory):
    auth = PostgresAuthority(session_factory=session_factory)
    keene = seeded[KEENE]
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
    broadcast_aliases = {g.alias for g in broadcast.updated_nodes}
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

    with session_factory() as s:
        # Registry still valid after the atomic mutation.
        assert validate_registry(s) == []

        # Edges: keene→sub created; keene→beech retired; sub→beech active.
        keene_to_sub = (
            s.query(ConnectivityEdgeSql)
            .filter_by(from_g_node_id=keene.g_node_id, to_g_node_id=new_cn.g_node_id)
            .one()
        )
        assert keene_to_sub.status == GNodeStatus.Active

        keene_to_beech = (
            s.query(ConnectivityEdgeSql)
            .filter_by(from_g_node_id=keene.g_node_id, to_g_node_id=beech_ltn.g_node_id)
            .one()
        )
        assert keene_to_beech.status == GNodeStatus.PermanentlyDeactivated

        sub_to_beech = (
            s.query(ConnectivityEdgeSql)
            .filter_by(from_g_node_id=new_cn.g_node_id, to_g_node_id=beech_ltn.g_node_id, status=GNodeStatus.Active)
            .one()
        )
        assert sub_to_beech is not None

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
    auth = PostgresAuthority(session_factory=session_factory)
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

    with pytest.raises(Exception):
        auth.apply_reparent(cmd)

    # Nothing moved: beech keeps its original alias, the new CN never landed.
    assert auth.get_by_alias(BEECH_LTN) is not None
    assert auth.get_by_id(new_cn.g_node_id) is None
    # The colliding alias still belongs to the squatter, not beech.
    with session_factory() as s:
        owner = s.get(AliasAssignmentSql, colliding_alias)
        assert owner.g_node_id == squatter_id
