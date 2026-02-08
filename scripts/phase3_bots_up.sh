#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Phase 3: bring up nautilus engines (paper/live/pump) =="

docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build \
  nautilus_paper_engine \
  nautilus_live_engine \
  nautilus_pump_engine

echo "== docker compose ps (nautilus engines) =="
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps

echo "== Gateway unified system_health (sanity) =="
(curl -sS http://localhost:8200/api/unified/paper/system_health || true); echo
(curl -sS http://localhost:8200/api/unified/live/system_health || true); echo
(curl -sS http://localhost:8200/api/unified/pump/system_health || true); echo

echo "== tail logs (example) =="
echo "  docker compose -f docker-compose.yml -f docker-compose.bots.yml logs -f --tail=120 nautilus_live_engine"
