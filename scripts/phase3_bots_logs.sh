#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Tail all nautilus engine services
exec docker compose -f docker-compose.yml -f docker-compose.bots.yml logs -f --tail=120 \
  nautilus_paper_engine \
  nautilus_live_engine \
  nautilus_pump_engine
