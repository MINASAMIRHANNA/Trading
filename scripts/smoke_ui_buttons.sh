#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

UI_BASE_URL="${UI_BASE_URL:-http://localhost:5173}"
GATEWAY_BASE_URL="${GATEWAY_BASE_URL:-http://localhost:8200}"

echo "== Ensure stack is running =="
if ! curl -fsS "${GATEWAY_BASE_URL}/health" >/dev/null 2>&1; then
  docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build
fi

if ! curl -fsS "${UI_BASE_URL}" >/dev/null 2>&1; then
  echo "FAIL: Unified Dashboard is not reachable at ${UI_BASE_URL}"
  exit 1
fi

echo "== Install dashboard test dependencies =="
npm --prefix services/brain/dashboard install

echo "== Run Unified button tests =="
UI_BASE_URL="${UI_BASE_URL}" \
  npm --prefix services/brain/dashboard run test:ui:buttons

echo "✅ smoke_ui_buttons passed"
