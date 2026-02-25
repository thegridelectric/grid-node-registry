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


## Database change management

Using alembic for change managmenet. E.g.

```
uv run alembic revision --autogenerate -m "description e.g. initial schema"
uv run alembic upgrade head
```
## Logs
By default, logs should be written to
```
~/.local/state/gridworks/gnr/log/
```
This follows the GridWorks convention.

## Next steps.
  0. Set up a dev environment for postgres and then use alembic to generate
  the table.
    - I tried setting up docker-compose.yaml but the postgres roles were failing.
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