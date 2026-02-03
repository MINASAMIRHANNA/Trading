#!/usr/bin/env bash
set -euo pipefail

echo "== docker compose ps =="
docker compose ps

echo

echo "== services in compose =="
docker compose config --services

echo

echo "== quick curls =="
urls=(
  "http://localhost:8200/health"
  "http://localhost:8200/api/_debug/routes"
  "http://localhost:5173/"
  "http://localhost:8000/api/stats"
)

for u in "${urls[@]}"; do
  echo "-- ${u}"
  (curl -sS -m 5 "${u}" | head -c 300 || echo "[curl failed]")
  echo
done
