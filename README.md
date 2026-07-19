# Grid Node Registry


Three SQLAlchemy models exist for

  - `GNodeSql`
  - `PositionPointSql`
  - `ConnectivityEdgeSql`

and corresponding Sema gt ("gridwork type") types for serialization/deserialization. These types are used for I/O to the registry and also do a certain amount of validation of the structure.

Here is how to go back and forth:
```
gt = GNodeGt(**payload)
db_obj = GNodeSql.from_gt(gt)
session.add(db_obj)

gt = db_obj.to_gt()
return codec.encode(gt)

```

## Universes

Every GNode alias begins with a **universe** segment, and its first letter is the
kind — a ladder where each step adds a requirement:

- `d` = **dev** — runs locally on a single computer: all comms go through
  localhost brokers (the isolation guarantee; the test harness and CI are dev
  universes).
- `h` = **hybrid** — the most flexible: distributed comms, real and simulated
  participants mixed, re-runnable (broker vhost `hw1__1`, `hw1__2`, … — one
  durable GNode set, many executions of time against it).
- `w` = **production** — Scadas and MarketMakers require Validation certs, and it
  is the only place real money moves.

There are many dev/hybrid universes (`d1`, `d2`, `hw1`, …) and exactly one
production universe. A registry instance is scoped to a single universe:

```
universe_of(alias) = alias.split(".")[0]     # d1.isone.me.versant.keene.beech -> d1
```

A **dev universe** mirrors the deployed production systems re-aliased into `d1.*`,
so the registry (and the services around it) can be exercised end-to-end against a
real broker and database without touching real money. The test harness is built as
such a dev universe.

**The universe segment is a namespace, not a GNode.** `d1` (the bare universe token)
is **not** a GNodeAlias — it is the namespace the registry is scoped to. So every
GNodeAlias has **at least two words**, and the registry holds a **forest of copper
subtrees** rather than one rooted tree: the forest roots are the top-level copper
nodes (a top-level `MarketMaker` like `d1.isone`, whose alias-parent is the bare
token). A GNode is a *forest root* iff its alias-parent is the universe token.

## Requirements

Python version requirement: 3.12.x
Reason: SQLAlchemy/Alembic/Postgres driver stability and CI reproducibility.

## Configuration & Secrets 

The Grid Node Registry uses `pydantic-settings` for runtime configuration.

All configuration is loaded through the `Settings` class:
```
from gnr.settings import Settings
import dotenv

settings = Settings(_env_file=dotenv.find_dotenv())
```
By default, all variables are loaded from a .env file in the project root.
To get started:

 1. Copy the provided template:
```
cp template.env .env
```
 2. Edit the `.env` file to include your database credentials and any overrides.


## Local Postgres (dev)

A `docker-compose.yaml` runs a Postgres 16 for development:

```
docker compose up -d           # starts container `gnr-postgres`
```

It publishes the container's 5432 on **host port 5435** (not 5432): a
host-local Postgres commonly holds `127.0.0.1:5432`, and macOS resolves
`localhost` to `::1` first, so a `5432:5432` publish gets shadowed and you see
`role "gnr" does not exist`. The matching URL is in `template.env`
(`postgresql+psycopg://gnr:gnrpass@localhost:5435/gnr`) — note the `+psycopg`
driver (psycopg v3, the installed one). If you ever change the container's
credentials, remove the named volume first (`docker compose down` then
`docker volume rm gnr_pgdata`) — Postgres only runs its init on an empty data
dir, so a stale volume keeps the old roles.

## Database change management

Using alembic for change management. E.g.

```
uv run alembic revision --autogenerate -m "description e.g. initial schema"
uv run alembic upgrade head
```

The initial migration (all three tables) is committed under
`alembic/versions/`; `uv run alembic upgrade head` against a fresh dev Postgres
creates the schema.
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
| `gnr-postgres` (docker) | Postgres 16 | `docker logs gnr-postgres` |

## Next steps.
  0. ~~Set up a dev environment for postgres and then use alembic to generate
  the table.~~ **Done** — `docker compose up -d` (host port 5435), then
  `uv run alembic upgrade head`. A `GNodeGt` round-trips against the live DB
  (`gt → GNodeSql.from_gt → session → to_gt`). See *Local Postgres (dev)* above.
  1. Add history tables 
  2. Enforce core invariants that aren't caught by Sema
     - Alias Uniqueness through time
     - Active GNode tree must be parent-closed
     - Active physical GNode subtree must be parent-closed
     - **ConnectivityEdge consistency** GNodeIds and Aliases match
     - **ConnectivityEdge coverage**
   That is, For every non-root physical GNode with alias A:

```
For every non-root GNode with alias A:
    Let P = parent alias of A
    The registry MUST contain exactly one ConnectivityEdge
    with FromGNodeId = <UUID(P)> AND ToGNodeId = <UUID(A)>
```

 3. Manage lifecycle states
    - **GNodeStatus**
       - Pending -> Active only
       - Active -> {Suspended, PermanentlyDeactivated}
       - Suspended -> {Active, PermanentlyDeactivated}
       - PermanentlyDeactivated -> no change
    - **BaseGNodeClass**  ConnectivityNode <-> MarketMaker 
 4. Implement API Endpoints (FastAPI)
 5. Set up tests & CI