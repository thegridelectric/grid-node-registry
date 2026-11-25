#!/bin/bash
# Run locally everything CI runs, so a push won't go red. Mirrors
# .github/workflows/tests.yml (lint + tests jobs). Usage: ./ci.sh
set -euo pipefail

step() { printf '\n=== %s ===\n' "$1"; shift; "$@"; }

# Resolve the env exactly as CI does.
step "uv sync (locked)" uv sync --all-groups --locked

# lint
step "ruff check" uv run ruff check --no-fix .
step "ruff format --check" uv run ruff format --check .
step "sema snapshot staging check" uv run python -P \
  src/gnr/sema/check_staging.py src/gnr/sema_seed_request.yaml \
  --deploy-branch main

# tests need docker (testcontainers: postgres + rabbit).
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: docker is not running — the test suite uses testcontainers." >&2
  exit 1
fi
step "tests" uv run pytest -q

printf '\nAll CI checks passed.\n'
