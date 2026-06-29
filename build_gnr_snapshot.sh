#!/usr/bin/env bash
# (re)build the gnr Sema snapshot from gnr_seed_request.yaml (homed here in the
# consumer repo) and copy it into src/gnr/sema/. Drives the generator in the
# sibling sema repo; the only sema-side write is its gitignored output/ scratch.
# Local (Python) class names come from the seed request's local_names rule.
set -euo pipefail

gnr_root="$(cd "$(dirname "$0")" && pwd)"
sema_root="$(cd "$gnr_root/../sema" && pwd)"
seed="$gnr_root/gnr_seed_request.yaml"

cd "$sema_root"
uv run sema snapshot prepare "$seed"
uv run sema snapshot build --package-name gnr

rsync -a --delete --exclude='__pycache__' --exclude='.DS_Store' \
  output/sema/ "$gnr_root/src/gnr/sema/"
echo "gnr snapshot rebuilt (local names from seed request) + copied to src/gnr/sema/."
