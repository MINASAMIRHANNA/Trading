#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

UI_BASE_URL="${UI_BASE_URL:-http://localhost:5173}"
GATEWAY_BASE_URL="${GATEWAY_BASE_URL:-http://localhost:8200}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.bots.yml)

echo "== Ensure stack is running =="
if ! curl -fsS "${GATEWAY_BASE_URL}/health" >/dev/null 2>&1; then
  docker compose "${COMPOSE_FILES[@]}" up -d --build
fi

if ! curl -fsS "${UI_BASE_URL}" >/dev/null 2>&1; then
  echo "FAIL: Unified Dashboard is not reachable at ${UI_BASE_URL}"
  exit 1
fi

echo "== Ensure pending signal exists for UI approve flow =="
pending_count="$(
  curl -fsS "${GATEWAY_BASE_URL}/api/unified/paper/signals?status=PENDING_APPROVAL&limit=1" \
    | jq -r '(.count // (.items|length) // 0)'
)"
if [[ "${pending_count}" == "0" ]]; then
  now_iso="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  now_ms="$(( $(date -u +%s) * 1000 ))"
  dedupe_key="ui_e2e_seed_${now_ms}"
  docker compose "${COMPOSE_FILES[@]}" exec -T postgres psql -U trading -d trading >/dev/null <<SQL
INSERT INTO mina_paper.signal_inbox
  (received_at, received_at_ms, source, status, symbol, timeframe, strategy, side, confidence, score, payload, note, dedupe_key)
VALUES
  (
    '${now_iso}',
    ${now_ms},
    'ui_e2e_seed',
    'PENDING_APPROVAL',
    'BTCUSDT',
    '5m',
    'UI_E2E_SEED',
    'LONG',
    0.91,
    0.91,
    '{"source":"ui_e2e_seed","strategy":"UI_E2E_SEED"}',
    'Seed for smoke_ui_e2e',
    '${dedupe_key}'
  )
ON CONFLICT (dedupe_key) DO NOTHING;
SQL
fi

echo "== Install dashboard test dependencies =="
npm --prefix services/brain/dashboard install

echo "== Run Unified UI E2E =="
UI_BASE_URL="${UI_BASE_URL}" npm --prefix services/brain/dashboard run test:ui:e2e

echo "✅ smoke_ui_e2e passed"
