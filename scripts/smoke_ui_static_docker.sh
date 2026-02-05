#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

# Run the static UI smoke test from inside the gateway container.
docker compose exec -T gateway_api bash -lc \
  'BASE=http://gateway_api:8200 bash /app/scripts/smoke_ui_static.sh'

echo "✅ smoke_ui_static_docker done"
