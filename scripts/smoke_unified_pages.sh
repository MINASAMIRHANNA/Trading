#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

BASE_URL="${BASE_URL:-http://localhost:8200}"
API_KEY="${GATEWAY_API_KEY:-}"

call_endpoint() {
  local name="$1"
  local method="$2"
  local path="$3"
  local body="${4:-}"
  local allow_error_ok="${5:-0}"

  local url="${BASE_URL}${path}"
  local -a args=( -sS -X "$method" "$url" -w $'\n%{http_code}' )
  if [[ -n "$API_KEY" ]]; then
    args+=( -H "X-API-Key: ${API_KEY}" )
  fi
  if [[ -n "$body" ]]; then
    args+=( -H "Content-Type: application/json" -d "$body" )
  fi

  local resp body_out code
  resp="$(curl "${args[@]}")"
  body_out="${resp%$'\n'*}"
  code="${resp##*$'\n'}"

  if [[ ! "$code" =~ ^[0-9]+$ ]]; then
    echo "FAIL: ${name} invalid http code"
    echo "$resp"
    exit 1
  fi
  if (( code >= 500 )); then
    echo "FAIL: ${name} HTTP ${code}"
    echo "$body_out"
    exit 1
  fi

  if command -v jq >/dev/null 2>&1; then
    echo "$body_out" | jq . >/dev/null 2>&1 || {
      echo "FAIL: ${name} non-JSON response"
      echo "$body_out"
      exit 1
    }
    if [[ "$allow_error_ok" == "1" ]]; then
      echo "$body_out" | jq -e '.ok == true or .ok == false or .error != null or .detail != null' >/dev/null || {
        echo "FAIL: ${name} missing ok/error"
        echo "$body_out"
        exit 1
      }
    else
      echo "$body_out" | jq -e '.ok == true or .roles != null or .items != null or .summary != null or .state != null or .schema_version != null or .gateway != null or .trades != null' >/dev/null || {
        echo "FAIL: ${name} unexpected payload"
        echo "$body_out"
        exit 1
      }
    fi
  fi

  if echo "$body_out" | grep -qi "upstream_request_error"; then
    echo "FAIL: ${name} upstream_request_error"
    echo "$body_out"
    exit 1
  fi

  echo "PASS: ${name}"
}

echo "== Unified Dashboard endpoint smoke =="
call_endpoint "unified overview" GET "/api/unified/overview"
call_endpoint "ops status paper" GET "/api/ops/status?role=paper"
call_endpoint "ops status live" GET "/api/ops/status?role=live"
call_endpoint "ops status pump" GET "/api/ops/status?role=pump"
call_endpoint "unified positions paper" GET "/api/unified/positions?role=paper&limit=20"
call_endpoint "unified logs all" GET "/api/unified/logs?role=all&limit=20"
call_endpoint "unified errors all" GET "/api/unified/errors?role=all&limit=20"
call_endpoint "portfolio summary" GET "/api/portfolio/summary?role=paper"
call_endpoint "portfolio equity" GET "/api/portfolio/equity?role=paper&limit=50"
call_endpoint "report paper arena" GET "/api/reports/paper_arena"
call_endpoint "report analytics" GET "/api/reports/analytics"
call_endpoint "report deep audit" GET "/api/reports/deep_audit_lab?role=paper&limit=20"
call_endpoint "report daily summary" GET "/api/reports/daily_summary" "" 1
call_endpoint "report strategy compare" GET "/api/reports/strategy_compare" "" 1
call_endpoint "doctor checks" GET "/api/doctor/checks?run_tests=false"
call_endpoint "api docs registry" GET "/api/api-docs/registry"
call_endpoint "learn state" GET "/api/learn/state"
call_endpoint "brain inspector overview" GET "/api/brain/inspector/overview?role=paper"
call_endpoint "brain inspector features" GET "/api/brain/inspector/features_sample?limit=10"
call_endpoint "brain inspector traces" GET "/api/brain/inspector/decision_traces?role=paper&limit=10"
call_endpoint "brain inspector traces alias" GET "/api/brain/inspector/traces?limit=10"
call_endpoint "snapshot" GET "/api/snapshot?role=paper&limit=20"
call_endpoint "notifications settings get" GET "/api/notifications/settings"

# Safe write-path checks (control-plane endpoints)
call_endpoint "ops command" POST "/api/ops/command" '{"role":"paper","target":"monitor","action":"restart","reason":"smoke_unified_pages"}'
call_endpoint "learn train" POST "/api/learn/train" '{"role":"paper"}'
call_endpoint "learn promote" POST "/api/learn/promote" '{"role":"paper"}' 1
call_endpoint "learn rollback" POST "/api/learn/rollback" '{"role":"paper"}' 1
call_endpoint "notifications settings post" POST "/api/notifications/settings" '{"enabled":true,"notify_signals_created":true,"notify_signals_approved":true,"notify_signals_opened":true,"notify_signals_closed":true,"notify_errors":true}'
call_endpoint "notifications test" POST "/api/notifications/test" '{}' 1
call_endpoint "manual execute" POST "/api/manual/execute" '{"role":"paper","symbol":"BTCUSDT","amount_usd":50,"market":"futures","direction":"LONG","time_in_force":"MARKET"}'
call_endpoint "snapshot point-in-time" POST "/api/snapshot" '{"role":"paper","symbol":"SOLUSDT","market":"futures","interval":"5m","at_local":"06/02/2026 14:30","at_utc":"2026-02-06T12:30:00Z"}'

echo "✅ smoke_unified_pages passed"
