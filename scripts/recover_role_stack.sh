#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-paper}"

echo "== Rebuild stack for role: ${ROLE} =="

if [[ "${ROLE}" == "paper" ]]; then
  docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build mina_dashboard_paper mina_paper_monitor mina_paper_bot
elif [[ "${ROLE}" == "live" ]]; then
  docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build mina_dashboard_live mina_live_monitor mina_live_bot
elif [[ "${ROLE}" == "pump" ]]; then
  docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build mina_dashboard_pump mina_pump_bot
else
  echo "Unknown role: ${ROLE}"
  exit 2
fi

echo
docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
