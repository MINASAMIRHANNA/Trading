#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Phase 3: stop/remove nautilus engines =="

docker compose -f docker-compose.yml -f docker-compose.bots.yml stop \
  nautilus_paper_engine \
  nautilus_live_engine \
  nautilus_pump_engine || true

docker compose -f docker-compose.yml -f docker-compose.bots.yml rm -f \
  nautilus_paper_engine \
  nautilus_live_engine \
  nautilus_pump_engine || true

echo "== docker compose ps =="
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
