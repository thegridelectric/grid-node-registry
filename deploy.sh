#!/bin/bash
set -euo pipefail
#
# Deploy the registry to the gnr box — the one-word "go".
#
# What it does, per the deployment pattern (gwbase executor §8): put the box
# on the pushed tip of MAIN (clean checkout, never a dirty tree), sync the
# locked deps, restart the services, and health-check. Run from anywhere;
# needs your ssh access to the box (per-person key).
#
#   ./deploy.sh
#
# Deploys main ONLY: merge dev → main and push first — that merge is the
# deploy decision.

HOST="${GNR_HOST:-gnr.electricity.works}"

echo "→ deploying origin/main to $HOST"
ssh "gnr@$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/grid-node-registry
git fetch origin
git switch main 2>/dev/null || git switch -c main origin/main
git reset --hard origin/main
~/.local/bin/uv sync --frozen
sudo systemctl restart gnr-rabbit gnr-api
REMOTE

sleep 5
echo "→ health checks"
curl -fsS "https://$HOST/ping" >/dev/null && echo "  api: ok"
ssh "gnr@$HOST" 'systemctl is-active gnr-rabbit gnr-api | tr "\n" " "; echo; cd ~/grid-node-registry && echo "  running: $(git log --oneline -1)"'
echo "→ deployed."
