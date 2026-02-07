#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

BASE_URL="${BASE_URL:-http://localhost:8200}"
API_KEY="${GATEWAY_API_KEY:-}"

curl_json() {
  local url="$1"
  if [[ -n "$API_KEY" ]]; then
    curl -sS -H "X-API-Key: ${API_KEY}" "$url"
  else
    curl -sS "$url"
  fi
}

echo "== Unified DB Wiring =="
resp=""
for i in $(seq 1 20); do
  set +e
  resp="$(curl_json "${BASE_URL}/api/system/db_wiring")"
  rc=$?
  set -e
  if [[ $rc -eq 0 ]] && [[ -n "$resp" ]]; then
    break
  fi
  sleep 2
done

if [[ -z "$resp" ]]; then
  echo "FAIL: empty response from /api/system/db_wiring"
  exit 1
fi

if command -v jq >/dev/null 2>&1; then
  echo "$resp" | jq .
  echo "$resp" | jq -e '.ok == true and .same_db == true and ((.missing_services // []) | length) == 0' >/dev/null
  db_name="$(echo "$resp" | jq -r '.database_name')"
  schemas="$(echo "$resp" | jq -r '.schemas | join(",")')"
  echo "PASS: unified db wiring (db=${db_name}, schemas=${schemas})"
else
  echo "$resp"
  echo "$resp" | grep -q '"ok":true'
  echo "$resp" | grep -q '"same_db":true'
  echo "$resp" | grep -q '"missing_services":\[\]'
  echo "PASS: unified db wiring"
fi

