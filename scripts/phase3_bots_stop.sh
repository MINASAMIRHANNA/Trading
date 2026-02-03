#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Phase 3: stop/remove Mina bots + monitors =="

docker compose -f docker-compose.yml -f docker-compose.bots.yml stop \
  mina_pump_bot \
  mina_live_bot mina_live_monitor \
  mina_paper_bot mina_paper_monitor || true

docker compose -f docker-compose.yml -f docker-compose.bots.yml rm -f \
  mina_pump_bot \
  mina_live_bot mina_live_monitor \
  mina_paper_bot mina_paper_monitor || true

echo "== docker compose ps =="
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
