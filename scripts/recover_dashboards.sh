#!/usr/bin/env bash
set -euo pipefail

echo "== Rebuild Mina dashboards =="
docker compose up -d --build mina_dashboard_paper mina_dashboard_live mina_dashboard_pump

echo
echo "== Status =="
docker compose ps mina_dashboard_paper mina_dashboard_live mina_dashboard_pump

echo
echo "== Quick health checks =="
curl -sS http://localhost:8000/health || true; echo
curl -sS http://localhost:8001/health || true; echo
curl -sS http://localhost:8002/health || true; echo
