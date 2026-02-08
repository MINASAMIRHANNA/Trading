#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Phase 3: stop/remove engines + pump legacy services =="

docker compose -f docker-compose.yml -f docker-compose.bots.yml stop \
  nautilus_paper_engine \
  nautilus_live_engine \
  mina_pump_bot \
  mina_pump_monitor || true

docker compose -f docker-compose.yml -f docker-compose.bots.yml rm -f \
  nautilus_paper_engine \
  nautilus_live_engine \
  mina_pump_bot \
  mina_pump_monitor || true

echo "== docker compose ps =="
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
