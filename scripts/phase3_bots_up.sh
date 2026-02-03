#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Phase 3: bring up Mina bots + monitors =="

docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build \
  mina_pump_bot \
  mina_live_bot mina_live_monitor \
  mina_paper_bot mina_paper_monitor

echo "== docker compose ps (bots + monitors) =="
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps

echo "== dashboards /api/db_ready (sanity) =="
(curl -sS http://localhost:8001/api/db_ready || true); echo
(curl -sS http://localhost:8000/api/db_ready || true); echo
(curl -sS http://localhost:8002/api/db_ready || true); echo

echo "== tail logs (example) =="
echo "  docker compose -f docker-compose.yml -f docker-compose.bots.yml logs -f --tail=120 mina_live_bot"
