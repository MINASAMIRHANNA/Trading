#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

BASE_URL="${BASE_URL:-http://localhost:8200}"
API_KEY="${GATEWAY_API_KEY:-}"

curl_json() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local -a args=( -sS -X "$method" "$url" )
  if [[ -n "$API_KEY" ]]; then
    args+=( -H "X-API-Key: ${API_KEY}" )
  fi
  if [[ -n "$body" ]]; then
    args+=( -H "Content-Type: application/json" -d "$body" )
  fi
  curl "${args[@]}"
}

check_ok() {
  local name="$1"
  local method="$2"
  local url="$3"
  local body="${4:-}"
  local res
  res="$(curl_json "$method" "$url" "$body")"
  if [[ -z "$res" ]]; then
    echo "FAIL: ${name} empty response"
    exit 1
  fi
  if echo "$res" | grep -qi "upstream_request_error"; then
    echo "FAIL: ${name} upstream_request_error"
    echo "$res"
    exit 1
  fi
  if command -v jq >/dev/null 2>&1; then
    echo "$res" | jq -e '.ok == true or .status == "ok" or .roles != null or .checks != null or .schema_version != null or .gateway != null' >/dev/null || {
      echo "FAIL: ${name} unexpected payload"
      echo "$res"
      exit 1
    }
  fi
  echo "PASS: ${name}"
}

echo "== Gateway core =="
check_ok "gateway health" GET "${BASE_URL}/health"
check_ok "unified overview" GET "${BASE_URL}/api/unified/overview"
check_ok "ops status" GET "${BASE_URL}/api/ops/status?role=all"
check_ok "ops runtime pump" GET "${BASE_URL}/api/ops/runtime?role=pump"
check_ok "stack health" GET "${BASE_URL}/api/stack/health"
check_ok "doctor checks" GET "${BASE_URL}/api/doctor/checks?run_tests=false"
check_ok "api docs registry" GET "${BASE_URL}/api/api-docs/registry"

echo "== Legacy dashboard write-block =="
set +e
ro_resp="$(curl -sS -X POST http://localhost:8000/api/commands/queue -H 'Content-Type: application/json' -d '{"cmd":"PING"}' -w $'\n%{http_code}')"
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  echo "WARN: Could not reach legacy dashboard for read-only check"
else
  ro_body="${ro_resp%$'\n'*}"
  ro_code="${ro_resp##*$'\n'}"
  if [[ "$ro_code" != "403" ]]; then
    echo "FAIL: expected legacy dashboard POST to be blocked with 403 (got ${ro_code})"
    echo "$ro_body"
    exit 1
  fi
  if ! echo "$ro_body" | grep -q "Dashboard is read-only. Use Unified Dashboard."; then
    echo "FAIL: expected read-only message missing"
    echo "$ro_body"
    exit 1
  fi
  echo "PASS: legacy dashboard write blocked"
fi

echo "== Pump entrypoint runtime assertion =="
runtime_body="$(curl_json GET "${BASE_URL}/api/ops/runtime?role=pump")"
if [[ -z "$runtime_body" ]]; then
  echo "FAIL: empty runtime response for pump"
  exit 1
fi
if ! echo "$runtime_body" | grep -q "pump_hunter.py"; then
  echo "FAIL: pump runtime entrypoint does not report pump_hunter.py"
  echo "$runtime_body"
  exit 1
fi
echo "PASS: pump runtime entrypoint is pump_hunter.py"

echo "== Single DB verification =="
bash scripts/verify_single_db.sh

echo "✅ smoke_stack passed"
