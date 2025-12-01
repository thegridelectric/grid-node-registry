# ASL (Application Shared Language) Module

This directory contains the type definitions and serialization codec for the gridworks-ingester application.

The GridWorks ASL Registry at [schemas.electricity.works](https://schemas.electricity.works) is the authoritative source for all type definitions. See the [GitHub repository](https://github.com/thegridelectric/gridworks-asl) for implementation details.

## What is ASL?

ASL (Application Shared Language) is a protocol framework similar to Protocol Buffers or OpenAPI, but designed for distributed peer-to-peer systems rather than client-server architectures.

**Key concepts:**
- **À la carte selection** - Choose only the types you need (unlike monolithic SDKs)
- **Self-contained generation** - Get a complete `asl/` directory with no external dependencies
- **Version independence** - Each repo can use different versions without conflicts
- **Language neutral** - JSON Schema specs that generate idiomatic Python (or any language)

ASL provides structured, validated Python types for data that needs to be:
- Sent between intra-company application
- Stored in the database
- Shared with other organizations who also use ASL (e.g. GridWorks optimizers and transactive market makers).

Think of it as the evolution from REST APIs (where the server dictates the contract) to shared vocabulary (where peers collaborate on equal terms).

## Installation

This ASL seed is designed to be integrated directly into your gridworks-ingester repository.


This ASL seed is designed to be integrated directly into your gridworks-ingester repository. It expects to be a subfolder of `gwi`.

### Example Project Structure

If you have a repository structure like this:

```
gridworks-ingester/
├── README.md
├── requirements.txt
├── tests/
│   └── test_scada.py
└── src/
    └── gwi/
        ├── __init__.py
        └──  main.py   

```

After adding the ASL seed, it should look like:

```
gridwroks-ingester/
├── README.md
├── requirements.txt
├── tests/
│   └── test_scada.py
└── src/
    └── gwi/
        ├── __init__.py
        ├── main.py        
        └── asl/             # ← ADD THIS DIRECTORY HERE
            ├── __init__.py
            ├── codec.py
            ├── property_format.py
            ├── enums/
            ├── types/
            └── tests/
```

### Requirements

- Python 3.12 or higher (uses modern type hints and union syntax)
- pydantic >= 2.5.0 (for type validation and serialization)
- pytest >= 7.4.0 (for running tests)

### Integration Steps

1. **Verify Python version:**
   ```bash
   python --version  # Should show 3.12.x or higher
   ```

2. **Copy the `asl/` directory into your project:**
   ```bash
   # From your SCADA repository root
   cp -r path/to/seed/asl src/gwi/asl
   ```

3. **Add dependencies to your project's requirements:**
   
   If using `requirements.txt`, add:
   ```txt
   pydantic>=2.5.0
   pytest>=7.4.0
   ```
   
   If using `pyproject.toml`, add:
   ```toml
   [project]
   requires-python = ">=3.12"
   dependencies = [
       "pydantic>=2.5.0",
   ]
   
   [project.optional-dependencies]
   dev = [
       "pytest>=7.4.0",
   ]
   ```

4. **Update imports in your code:**
   ```python
   # Import from your package structure
   from gwi.asl.types import ScadaSnapshot, ChannelReading
   from gwi.asl.enums import RelayClosedOrOpen
   ```

5. **Verify the integration:**
   ```bash
   # Run the example tests
   pytest src/gwi/asl/tests/ -v -s
   ```

### Important Notes

- This is a seed, not a library - modify the types as needed for your system
- Keep the `asl/` structure intact for future updates
- The ASL types are self-contained with no dependencies beyond Pydantic
- Python 3.12+ is required for modern type hints (union syntax, Literal types)

## Message Passing Patterns

ASL types are designed for reliable message passing in distributed systems, particularly for electric grid telemetry and transactive dispatch. The framework supports two primary patterns:

### Direct Messages (Fire-and-Forget)  
Real-time telemetry where only the latest value matters:
```python
# Example: power readings sent without event wrapper
# No acknowledgment, no retry, no persistence
# Old values are worse than no values
```

**Note** that `power` is the foundational message for the system - it tracks the lifeblood rate of change of electrical energy on the electric grid as we collectively bring the load-side of the grid into the equation for grid balancing!

### Event-Wrapped Messages (Persistent)
Messages intended for storage and reliability guarantees are wrapped in events:
```python
# Example: scada.snapshot wrapped in scada.snapshot.event
# The event adds MessageId, TimeCreatedMs, and Src for tracking
# These get acknowledged, retried, and persisted
```

Messages requiring persistence and reliability guarantees follow the `.event` pattern:

**Pattern**: To create a new persistent message:
1. Define your base type (e.g., `sage.of.aquarius`)
2. Create an event wrapper that inherits from `EventBase`
3. Name it with `.event` suffix (e.g., `sage.of.aquarius.event`)
4. Include the base type as a field
```python
class SageOfAquariusEvent(EventBase):
    scada_snapshot: ScadaSnapshot
    type_name: Literal["sage.of.aquarius.event"] = "sage.of.aquarius.event"
```
5. Register **both** with GridWorks ASL

Events provide:
  - MessageId for deduplication
  - TimeCreatedMs for audit trails
  - Src for routing and storing "who" sent the message
  - Acknowledgment and retry mechanisms

**Note** I recommend for **now** MicroEraPower SCADA sends plain `scada.snapshot`'s to the uploader and lets the uploader wrap it as an event. This keeps MicroEraPower code simpler - you don't need to generate MessageIds or manage event metadata. But if you want to create events directly, that works too.


## Serialization: Local vs Wire Format

ASL maintains a clear separation between how types appear in code and how they travel:

### Python Objects (snake_case)
```python
reading = ChannelReading(
    name="temperature",
    value=2150,
    unit="CelsiusTimes100"
)
```

### Wire Format (CamelCase JSON)
```json
{
  "Name": "temperature",
  "Value": 2150,
  "Unit": "CelsiusTimes100",
  "TypeName": "channel.reading"
}
```

This dual representation allows idiomatic Python while maintaining protocol compatibility with other languages and systems.

## Version Management

ASL supports evolution without breaking existing systems:

### Versionless Types
New types can start without versions, adding them only when changes are needed:
```python
type_name: Literal["scada.snapshot"] = "scada.snapshot"
# No version field until iteration required
```

### Versioned Evolution
When types need to change:
```python
type_name: Literal["report"] = "report"
version: Literal["002"] = "002"
# Codec handles old versions transparently
```

## Database Persistence with models.py

When ASL messages need database storage, `models.py` provides SQLAlchemy ORM mappings. This separation of concerns means:

- **ASL types** define the message contract (what goes on the wire)
- **ORM models** define storage optimization (how it's queried)
- **Flexibility** to evolve storage without breaking message compatibility

The ingester typically:
1. Receives ASL messages in CamelCase JSON
2. Deserializes to Python objects
3. Transforms to ORM models for PostgreSQL
4. Archives raw JSON to S3 for replay/audit

## Property Formats: The Foundation

GridWorks ASL uses consistent property formats across all implementations. These formats encode both validation rules and semantic meaning:

### Core Formats

#### SpaceheatName
- **Pattern**: Alphanumeric words separated by hyphens
- **Example**: `primary-scada`, `hp-relay`, `zone-1-sensor`
- **Origin**: From GridWorks' origins in transactive space heating control
- **Usage**: Local actor names, channel identifiers

#### LeftRightDot  
- **Pattern**: Alphanumeric words separated by periods
- **Example**: `w.isone.ma.lily.scada`, `power.watts`
- **Purpose**: Hierarchical identifiers for grid topology and type names
- **Usage**: GNodeAlias (grid positions), ASL type names

#### HandleName
- **Pattern**: SpaceheatName words separated by periods
- **Example**: `admin.hp-relay`, `primary-scada.stat.zone1-relay`
- **Purpose**: Local command hierarchies within a facility
- **Usage**: Actor supervision trees

### Translation Rules

Periods must be translated to hyphens in two contexts:

1. **REST API Endpoints**: Avoid routing ambiguities
   - `POST /primary-scada/scada-snapshot` (not `.snapshot`)

2. **Message Topics**: Enable broker interoperability
   - MQTT uses `/` as separator: `gw/from/to/type`
   - RabbitMQ uses `.` as separator: `gw.from.to.type`
   - Solution: Never use periods in topic segments

Example translation:
```
GNodeAlias: w.isone.ma.lily.scada
Type: scada.snapshot
MQTT Topic: gw/w-isone-ma-lily-scada/to/ingester/scada-snapshot
Rabbit Routing Key: gw.w-isone-ma-lily-scada.to.ingester.scada-snapshot
```

## Testing

While full testing of the types can be provided to go in another non-production folder, 
`asl/tests/test_telemetry.py` is included as a demo script
```bash
python asl/tests/ -v
```