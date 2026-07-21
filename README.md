# Grid Node Registry

The **authoritative record of GridWorks grid nodes**: every GNode (the copper
backbone of ConnectivityNodes and MarketMakers, the LeafTransactiveNodes and
TerminalAssets behind them, and the logical services), its immutable
`GNodeId`, its dotted **alias** (a materialized path — the parent relation is
derived from the alias, never stored), its lifecycle status, and the non-tree
copper edges the alias tree cannot express. The Fleet Index Service consults
it to authorize runtime instances; provisioning and analytics read it; anyone
may read its topology.

Two surfaces, one handler core:

- **Writes ride RabbitMQ** as sema commands (`g.node.create.cmd`,
  `g.node.reparent.cmd`); every applied command is content-hashed into an
  append-only `command_log`, and each mutation broadcasts the affected
  forest (`g.node.forest`) on the audience-known radio channel.
- **Reads ride HTTP** — a **public, read-only API** (see below). Privacy is
  carried by the data shape: topology only, opaque position-point ids.

The registry's Postgres is a materialized view of the logged command stream;
rebuild-from-capture is the durability story, not database backups.

## Universes

Every GNode alias begins with a **universe** segment, and its first letter is
the kind — a ladder where each step adds a requirement:

- `d` = **dev** — runs locally on a single computer: all comms go through
  localhost brokers (the isolation guarantee; the test harness and CI are dev
  universes).
- `h` = **hybrid** — the most flexible: distributed comms, real and simulated
  participants mixed, re-runnable (broker vhost `hw1__1`, `hw1__2`, … — one
  durable GNode set, many executions of time against it).
- `w` = **production** — Scadas and MarketMakers require Validation certs, and
  it is the only place real money moves. A `w…` registry refuses to boot until
  its trust machinery exists.

A registry instance is scoped to exactly one universe (`GNR_UNIVERSE`,
required, no default); every alias it holds or accepts carries that segment
first. **The universe segment is a namespace, not a GNode** — so every alias
has at least two words, and the registry holds a **forest** of copper
subtrees whose roots are the top-level copper nodes.

## Invariants (why the registry exists)

Enforced at every write (and auditable via `gnr.db.validate.validate_registry`):

- **Alias uniqueness through time** — an alias, once bound to a `GNodeId`, is
  permanently owned by it; aliases are never recycled across identities.
- **The active forest is parent-closed** — every active non-root's parent
  exists and is active.
- **Edges are non-tree only** — parent-child structure is the alias prefix;
  `connectivity_edges` holds only ties/loops/meshes.
- **Class hierarchy** — TerminalAsset under LeafTransactiveNode under the
  CopperNode backbone (ConnectivityNode/MarketMaker), up to a forest root.
- **Active physical nodes hold their PositionPoint** — a physical GNode may
  not be Active on an opaque position id alone; until its position is real it
  stays Pending.

## Configuration & secrets

One `.env` at the repo root, one `GNR_` prefix (`pydantic-settings`; nested
fields via `__`, e.g. `GNR_RABBIT__URL`). Start from the template and edit:

```
cp template.env .env
```

Broker and database credentials live only in `.env`, never in code.

**Write authorization (stop-gap):** when `GNR_WRITE_PROOF_SHA256` is set,
every create/re-parent command must carry a `Proof` whose sha256 matches, or
it is refused before touching anything. The secret stays with the operator
(`gnr create` reads it from `GNR_WRITE_PROOF` or prompts); the deploy holds
only the hash; rotation is a `.env` edit + service restart. Retired when
certificate-based identity lands.

## Local dev

A `docker-compose.yaml` runs a Postgres 16 for development:

```
docker compose up -d           # starts container `gnr-postgres`
uv run alembic upgrade head    # create the schema (single squashed baseline)
```

It publishes the container's 5432 on **host port 5435** (not 5432): a
host-local Postgres commonly holds `127.0.0.1:5432`, and macOS resolves
`localhost` to `::1` first, so a `5432:5432` publish gets shadowed and you see
`role "gnr" does not exist`. The matching URL is in `template.env` — note the
`+psycopg` driver (psycopg v3, the installed one). If you ever change the
container's credentials, remove the named volume first (`docker compose down`
then `docker volume rm gnr_pgdata`) — Postgres only runs its init on an empty
data dir.

To load the dev universe (the `d1` mirror of a small fleet, six Active homes
plus one Pending):

```
uv run python -c "
from gnr.db.session import SessionLocal
from gnr.dev_universe import seed_dev_universe
with SessionLocal() as s: seed_dev_universe(s)"
```

## The public read API

`uv run gnr api` serves the read façade (loopback :8000 by default; a TLS
proxy fronts it in deploy). Interactive docs at `/docs` — every request and
response body is a **sema word** (a versioned, immutable, registry-published
schema), and each schema in the docs links to its canonical definition.

- `POST /gnr/g-node-forest-request` — the forest under the requested roots
- `GET /gnr/g-node-by-id/{g_node_id}` — one GNode by immutable id
- `GET /gnr/g-node-by-alias/{alias}` — current owner of an alias; a
  renamed-away alias resolves to the same GNode in its current form (compare
  queried vs returned `Alias` to detect staleness)

Responses are byte-identical to the sema wire form (PascalCase keys, unset
fields absent), CORS-open, strictly read-only.

## Running as a service

`service/` holds the systemd units; on a box they are **copied** to
`/etc/systemd/system/` (a unit change = edit in repo, re-copy,
`sudo systemctl daemon-reload`). The box runs a clean checkout of a pushed
SHA — never edit on the box; update = `git pull && uv sync --frozen` +
restart.

| Process | What it is | Logs |
|---|---|---|
| `gnr-rabbit.service` | rabbit write loop (commands in, forest broadcasts out) | `~/.local/state/gridworks/gnr/log/<service-alias>.log` (rotating) + `journalctl -u gnr-rabbit` |
| `gnr-api.service` | public read-only HTTP façade, loopback :8000 (a TLS proxy fronts it) | `journalctl -u gnr-api` |
| `gnr-snapshot.timer` → `.service` | periodic one-shot `gnr snapshot` — re-broadcasts each forest root (anti-entropy); cadence lives in the timer file | `journalctl -u gnr-snapshot` |
| `gnr-postgres` (docker) | Postgres 16 | `docker logs gnr-postgres` |

## Tests

```
uv run pytest
```

Unit tests always run; the integration tiers (real Postgres and RabbitMQ via
`testcontainers`, or an already-running broker via `GNR_TEST_RABBIT_URL`)
self-skip when Docker isn't available. CI runs all tiers.
