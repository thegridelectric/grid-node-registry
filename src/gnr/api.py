"""HTTP / FastAPI read façade — the registry's read surface for non-rabbit consumers.

**Reads ride HTTP; the write + change broadcast ride rabbit** (see executor *Write
path & egress*). This is an **internal service API** — no mTLS; topology +
`position_points` privacy is the network perimeter's job. Thin by design: it
translates HTTP onto the transport-agnostic `AuthoritySource` reads and holds no
registry logic of its own — the twin of the `GnrRabbit` write adapter.

Routes follow the house pattern `POST /<from-node-or-service>/<sema-type-with-hyphens>`:
the first segment names the party (here the **service**, `gnr`), the second is the
inbound Sema `TypeName` with dots → hyphens, and **the body is always a full Sema
type** (uniform contract — no ad-hoc scalar payloads).

FIS bootstraps its authority-scoped `GNodeId ↔ alias` map from
`POST /gnr/g-node-forest-request` (a forest under its copper roots), then rides
`g.node.forest` broadcasts for deltas. Provisioning + analytics use the same query.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from gnr.db.authority import AuthoritySource, PostgresAuthority
from gnr.sema.property_format import LeftRightDot, UUID4Str
from gnr.sema.types import GNodeForestRequest


def create_app(authority: AuthoritySource | None = None) -> FastAPI:
    """Build the read-façade app over an `AuthoritySource` (Postgres by default)."""
    source: AuthoritySource = authority or PostgresAuthority()
    app = FastAPI(title="Grid Node Registry — read API")

    @app.get("/ping")
    def ping() -> dict:
        return {"status": "ok"}

    @app.post("/gnr/g-node-forest-request")
    def g_node_forest_request(request: GNodeForestRequest) -> dict:
        """The forest under the requested root aliases, returned as a `g.node.forest`."""
        return source.get_forest(request.roots).to_dict()

    # Point lookups are single scalars, so they are GETs with a path param rather
    # than a Sema-type body (the sanctioned exception to "the body is a Sema type").
    @app.get("/gnr/g-node-by-id/{g_node_id}")
    def g_node_by_id(g_node_id: UUID4Str) -> dict:
        """A single GNode by its immutable GNodeId (404 if unknown)."""
        gt = source.get_by_id(g_node_id)
        if gt is None:
            raise HTTPException(status_code=404, detail=f"no GNode with id {g_node_id!r}")
        return gt.to_dict()

    @app.get("/gnr/g-node-by-alias/{alias}")
    def g_node_by_alias(alias: LeftRightDot) -> dict:
        """The GNode that owns `alias` now — for a **past** (renamed-away) alias this
        returns the same GNode in its current form (new `Alias`), so the caller
        compares queried vs returned `Alias` to detect staleness. 404 if the alias was
        never assigned."""
        gt = source.resolve_alias(alias)
        if gt is None:
            raise HTTPException(status_code=404, detail=f"alias {alias!r} was never assigned")
        return gt.to_dict()

    return app


# Module-level app for `uvicorn gnr.api:app` (uses the default Postgres AuthoritySource).
app = create_app()
