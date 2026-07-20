"""The HTTP read façade over a real Postgres — the FIS/provisioning read surface.

Boots the FastAPI app over a `PostgresAuthority` on the seeded dev universe and
drives it with an in-process client: a `g-node-forest-request` from a caller returns
the forest (subtrees) under the requested roots. Route shape is the house pattern
`POST /{from_node}/<sema-type-with-hyphens>`.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from gnr.api import create_app
from gnr.db.authority import PostgresAuthority
from gnr.dev_universe import DEV_POSITION, seed_dev_universe
from gnr.sema.enums import BaseGNodeClass, GNodeStatus
from gnr.sema.types import GNodeGt, GNodeReparentCmd

pytestmark = pytest.mark.integration

KEENE = "d1.isone.me.versant.keene"
BEECH_LTN = f"{KEENE}.beech"
_REQ_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"


@pytest.fixture
def client(session_factory):
    with session_factory() as s:
        seed_dev_universe(s)
    return TestClient(create_app(authority=PostgresAuthority(session_factory=session_factory, universe="d1")))


def _forest_request(roots):
    return {
        "Roots": roots,
        "RequestId": _REQ_ID,
        "TypeName": "g.node.forest.request",
        "Version": "000",
    }


def test_ping(client):
    assert client.get("/ping").json() == {"status": "ok"}


def test_forest_under_keene(client):
    r = client.post("/gnr/g-node-forest-request", json=_forest_request([KEENE]))
    assert r.status_code == 200
    forest = r.json()
    assert forest["TypeName"] == "g.node.forest"

    aliases = {n["Alias"] for n in forest["Nodes"]}
    # the root + a home's LTN / TerminalAsset are all in the subtree
    assert KEENE in aliases
    assert f"{KEENE}.beech" in aliases
    assert f"{KEENE}.beech.ta" in aliases
    # Edges carries only non-tree copper (ties/loops); the dev fleet is radial,
    # so it is empty — parent-child structure is derived from the aliases.
    assert forest["Edges"] == []


def test_g_node_by_id(client):
    forest = client.post("/gnr/g-node-forest-request", json=_forest_request([KEENE])).json()
    keene = next(n for n in forest["Nodes"] if n["Alias"] == KEENE)

    r = client.get(f"/gnr/g-node-by-id/{keene['GNodeId']}")
    assert r.status_code == 200 and r.json()["Alias"] == KEENE
    assert client.get("/gnr/g-node-by-id/00000000-0000-4000-8000-000000000000").status_code == 404


def test_g_node_by_alias_current(client):
    r = client.get(f"/gnr/g-node-by-alias/{KEENE}")
    assert r.status_code == 200 and r.json()["Alias"] == KEENE
    assert client.get("/gnr/g-node-by-alias/d1.nope.nope").status_code == 404


def test_g_node_by_alias_resolves_stale(client, session_factory):
    # current beech LTN
    beech = client.get(f"/gnr/g-node-by-alias/{BEECH_LTN}").json()
    beech_id = beech["GNodeId"]

    # rename it: introduce keene.sub and move the beech home beneath it
    new_cn = GNodeGt(
        g_node_id=str(uuid.uuid4()), alias=f"{KEENE}.sub",
        base_class=BaseGNodeClass.ConnectivityNode, g_node_class="ConnectivityNode",
        status=GNodeStatus.Active, position_point_id=DEV_POSITION.id, display_name="sub",
    )
    PostgresAuthority(session_factory=session_factory, universe="d1").apply_reparent(
        GNodeReparentCmd(new_node=new_cn, moved_child_g_node_ids=[beech_id])
    )

    # the OLD (now stale) alias resolves to the SAME node in its current form —
    # the caller sees returned Alias ≠ queried alias, i.e. stale.
    r = client.get(f"/gnr/g-node-by-alias/{BEECH_LTN}")
    assert r.status_code == 200
    resolved = r.json()
    assert resolved["GNodeId"] == beech_id
    assert resolved["Alias"] == f"{KEENE}.sub.beech"
