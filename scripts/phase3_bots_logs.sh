#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Tail all bot-related services
exec docker compose -f docker-compose.yml -f docker-compose.bots.yml logs -f --tail=120 \
  mina_pump_bot \
  mina_live_bot mina_live_monitor \
  mina_paper_bot mina_paper_monitor
