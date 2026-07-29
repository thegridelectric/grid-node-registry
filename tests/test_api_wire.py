"""Wire-contract + docs-surface pins for the public read API (DB-free).

Routes return sema types via `response_model`; these tests pin (1) each
route's JSON to the runtime's own `to_dict()` wire form (PascalCase, None
fields absent), so per-route serialization flags can never silently drift the
wire, and (2) the derived sema-definition links in the OpenAPI document.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from gnr.api import SEMA_DEFINITION_URL, create_app
from gnr.sema.enums import BaseGNodeClass, GNodeStatus
from gnr.sema.types import GNodeForest, GNodeGt

GT = GNodeGt(
    g_node_id="7fc1cbb2-56b6-4a10-9d3c-25c8db26e264",
    alias="d1.isone",
    base_class=BaseGNodeClass.ConnectivityNode,
    g_node_class="ConnectivityNode",
    status=GNodeStatus.Active,
    position_point_id="f3b26cbe-3567-4d38-a2f5-79c3b1e2c8a1",
    display_name="isone",
)
FOREST = GNodeForest(roots=[GT.alias], nodes=[GT], edges=[])


class OneNodeSource:
    def get_forest(self, roots):
        return FOREST

    def get_by_id(self, g_node_id):
        return GT if g_node_id == GT.g_node_id else None

    def resolve_alias(self, alias):
        return GT if alias == GT.alias else None


client = TestClient(create_app(authority=OneNodeSource()))


def test_forest_response_is_wire_form():
    r = client.post(
        "/gnr/g-node-forest-request",
        json={
            "Roots": [GT.alias],
            "RequestId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
            "TypeName": "g.node.forest.request",
            "Version": "000",
        },
    )
    assert r.status_code == 200
    assert r.json() == FOREST.to_dict()


def test_by_id_response_is_wire_form():
    r = client.get(f"/gnr/g-node-by-id/{GT.g_node_id}")
    assert r.status_code == 200
    assert r.json() == GT.to_dict()
    # exclude-none: an unset optional (PrevAlias) is absent, not null
    assert "PrevAlias" not in r.json()


def test_by_alias_response_is_wire_form():
    r = client.get(f"/gnr/g-node-by-alias/{GT.alias}")
    assert r.status_code == 200
    assert r.json() == GT.to_dict()
    assert client.get("/gnr/g-node-by-alias/d1.nope").status_code == 404


def test_openapi_schemas_link_to_sema_definitions():
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    for name, type_name, version in [
        ("GNodeGt", "g.node.gt", "005"),
        ("GNodeForest", "g.node.forest", "001"),
        ("GNodeForestRequest", "g.node.forest.request", "000"),
    ]:
        url = SEMA_DEFINITION_URL.format(type_name=type_name, version=version)
        assert url in schemas[name]["description"], name
