#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

BASE="${BASE:-http://localhost:8200}"

echo "== UI index =="
HTML="$(curl -fsS "$BASE/")"
echo "$HTML" | grep -q 'id="root"' || { echo "FAIL: root div not found"; exit 1; }

echo "== UI index headers =="
curl -fsSI "$BASE/" | grep -i "content-type: text/html" >/dev/null

ASSET_PATH="$(echo "$HTML" | rg -o '"/assets/[^"]+\\.js"' | head -n1 | tr -d '"')"
if [ -z "$ASSET_PATH" ]; then
  echo "FAIL: no asset path found in HTML"
  exit 1
fi

echo "== UI asset =="
curl -fsS "$BASE$ASSET_PATH" >/dev/null

echo "== Gateway health =="
curl -fsS "$BASE/api/health" | jq -e '.status=="ok" and .service=="gateway"' >/dev/null

echo "✅ smoke_ui_static done"
