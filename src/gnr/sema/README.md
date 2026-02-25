# Sema Module

This directory contains the type definitions and serialization codec for Grid Node Registry.

Sema [schemas.electricity.works](https://schemas.electricity.works) is the authoritative source for all type definitions. This local `sema`/` directory is a **frozen, project-specific snapshot** of the exact Sema words required by this repository.

Sema governs **serialized JSON exchanged at system boundaries.**
It does not govern runtime architecture, database schema, or internal object models.

## What is Sema?

Sema is a versioned JSON Schema vocabulary for structured, machine-verifiable serialization between independent systems.

Key characteristics:
  - Versioned types and enums
  - Explicit identity (`TypeName`, `Version`)
  - Dependency-tracked vocabulary

Sema makes meaning explicit at the boundary so that independent systems can interoperate safely.

## À La Carte Vocabulary

This repository does not import a monolithic SDK.

Instead:
  - Only the required vocabulary words are selected.
  - A complete sema/ directory is generated.
  - All dependencies are included.
  - No runtime dependency on a remote registry exists.

Each repository may use different vocabulary versions without conflict.

### `sema.snapshot.json`
`sema.snapshot.json` is a deterministic lockfile of the vocabulary used by this project.

It contains the exact versions of all selected types, enums, formats, and their full dependency closure — including their structural definitions and declared semantics. This prevents semantic drift and makes the boundary contract easier to reason about, including with AI-assisted tooling.


### Example Project Structure

Before adding Sema:

```
repo/
├── README.md
├── requirements.txt
├── tests/
│   └── test_scada.py
└── src/
    └── gnr/
        ├── __init__.py
        └──  main.py   

```

After adding the Sema snapshot:

```
repo/
├── README.md
├── requirements.txt
├── tests/
│   └── test_scada.py
└── src/
    └── gnr/
        ├── __init__.py
        ├── main.py        
        └── sema/
            ├── __init__.py
            ├── sema.snapshot.json
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

2. **Copy the `sema/` directory into your project:**
   ```bash
   # From your SCADA repository root
   cp -r path/to/seed/sema src/gnr/sema
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
   from gnr.sema.types import GNodeGt
   from gwi.sema.enums import BaseGNodeClass
   ```

5. **Verify the integration:**
   ```bash
   # Run the example tests
   pytest src/gwi/sema/tests/ -v -s
   ```
