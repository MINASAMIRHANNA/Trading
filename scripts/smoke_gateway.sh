#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

BASE="${BASE:-http://localhost:8200}"

if command -v jq >/dev/null 2>&1; then
  JQ="jq"
else
  JQ="cat"
fi

echo "== ops/status =="
curl -sS "$BASE/api/ops/status?role=paper" | $JQ >/dev/null || true

echo "== portfolio/summary =="
curl -sS "$BASE/api/portfolio/summary?role=paper" | $JQ >/dev/null || true

echo "== doctor/run =="
curl -sS -X POST "$BASE/api/doctor/run" | $JQ >/dev/null || true

echo "== api-index =="
curl -sS "$BASE/api/api-index" | $JQ >/dev/null || true

echo "✅ smoke_gateway done"
