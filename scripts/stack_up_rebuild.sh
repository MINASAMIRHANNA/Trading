#!/usr/bin/env bash
set -euo pipefail

# Run from repo root (where docker-compose.yml exists)

echo "== docker compose down =="
docker compose down --remove-orphans

echo "== docker compose up (build) =="
docker compose up -d --build

echo "== docker compose ps =="
docker compose ps

echo "== Quick health check (gateway) =="
(curl -sS http://localhost:8200/health || true); echo
