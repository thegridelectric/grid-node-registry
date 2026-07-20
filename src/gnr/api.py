"""HTTP / FastAPI read façade — the registry's public read surface.

**Reads ride HTTP; the write + change broadcast ride rabbit** (see executor *Write
path & egress*). This is a **public, read-only API** — the registry is backbone
infrastructure and anyone may read its topology (FIS, provisioning, analytics,
and outside readers alike), TLS-terminated by the fronting proxy, CORS-open so
browser apps can read the forest. Privacy is carried by the data shape, not a
perimeter: topology only, opaque `position_point_id`s. Thin by design: it
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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from gnr.db.authority import AuthoritySource, PostgresAuthority
from gnr.sema.property_format import LeftRightDot, UUID4Str
from gnr.sema.types import GNodeForest, GNodeForestRequest, GNodeGt
from gnr.settings import Settings


# Where a sema word's definition lives — one constant so the whole docs
# surface flips together when schemas.electricity.works stands up.
SEMA_DEFINITION_URL = (
    "https://github.com/thegridelectric/sema/blob/dev/"
    "definitions/types/{type_name}/{version}.yaml"
)


def create_app(authority: AuthoritySource | None = None) -> FastAPI:
    """Build the read-façade app over an `AuthoritySource` (Postgres by default)."""
    source: AuthoritySource = authority or PostgresAuthority(
        universe=Settings().universe
    )
    app = FastAPI(
        title="Grid Node Registry — read API",
        description=(
            "Public read-only view of the GridWorks GNodeForest. Every request "
            "and response body is a **sema word** — a versioned, immutable, "
            "registry-published schema; each schema below links to its definition."
        ),
    )
    # Public read-only surface: any origin may read; only the read verbs exist.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    def ping() -> dict:
        return {"status": "ok"}

    # Routes return the sema types themselves; `response_model_exclude_none=True`
    # (with FastAPI's by-alias default) makes the response byte-identical to the
    # runtime's `to_dict()` wire form — pinned by tests/test_api_wire.py, so the
    # OpenAPI schema documents the real sema shapes for the public audience.
    @app.post("/gnr/g-node-forest-request", response_model_exclude_none=True)
    def g_node_forest_request(request: GNodeForestRequest) -> GNodeForest:
        """The forest under the requested root aliases, returned as a `g.node.forest`."""
        return source.get_forest(request.roots)

    # Point lookups are single scalars, so they are GETs with a path param rather
    # than a Sema-type body (the sanctioned exception to "the body is a Sema type").
    @app.get("/gnr/g-node-by-id/{g_node_id}", response_model_exclude_none=True)
    def g_node_by_id(g_node_id: UUID4Str) -> GNodeGt:
        """A single GNode by its immutable GNodeId (404 if unknown)."""
        gt = source.get_by_id(g_node_id)
        if gt is None:
            raise HTTPException(status_code=404, detail=f"no GNode with id {g_node_id!r}")
        return gt

    @app.get("/gnr/g-node-by-alias/{alias}", response_model_exclude_none=True)
    def g_node_by_alias(alias: LeftRightDot) -> GNodeGt:
        """The GNode that owns `alias` now — for a **past** (renamed-away) alias this
        returns the same GNode in its current form (new `Alias`), so the caller
        compares queried vs returned `Alias` to detect staleness. 404 if the alias was
        never assigned."""
        gt = source.resolve_alias(alias)
        if gt is None:
            raise HTTPException(status_code=404, detail=f"alias {alias!r} was never assigned")
        return gt

    def openapi_with_sema_links() -> dict:
        """Every schema that is a sema word (TypeName/Version defaults present)
        links to its canonical definition — derived from the schema itself,
        never hand-maintained."""
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        for comp in schema.get("components", {}).get("schemas", {}).values():
            props = comp.get("properties", {})
            tn = props.get("TypeName", {}).get("default")
            ver = props.get("Version", {}).get("default")
            if tn and ver:
                url = SEMA_DEFINITION_URL.format(type_name=tn, version=ver)
                note = f"Sema word [`{tn}` v{ver}]({url})."
                comp["description"] = (
                    f"{comp['description']}\n\n{note}" if comp.get("description") else note
                )
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi_with_sema_links  # type: ignore[method-assign]

    return app


# Module-level app for `uvicorn gnr.api:app` (uses the default Postgres AuthoritySource).
app = create_app()
