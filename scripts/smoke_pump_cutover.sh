#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_curl_json.sh
source "${HERE}/_curl_json.sh"

BASE="${BASE_URL:-http://localhost:8200}"
KEY="${X_API_KEY:-${API_KEY:-trading-dev}}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-trading_migration}"
export COMPOSE_PROJECT_NAME

HDR=(-H "X-API-Key: ${KEY}")
DC=(docker compose -f docker-compose.yml -f docker-compose.bots.yml)

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

json_get() {
  local raw="$1"
  local path="$2"
  python3 - "$raw" "$path" <<'PY'
import json,sys
raw=sys.argv[1]
path=sys.argv[2]
try:
    obj=json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
val=obj
for part in path.split('.'):
    if part == '':
        continue
    if isinstance(val, dict):
        val = val.get(part)
    else:
        val = None
        break
if val is None:
    print("")
elif isinstance(val, (dict,list)):
    print(json.dumps(val, ensure_ascii=True))
else:
    print(val)
PY
}

psql_val() {
  local q="$1"
  "${DC[@]}" exec -T postgres psql -U trading -d trading -At -c "$q" | tr -d '\r'
}

expect_2xx() {
  local code="$1"
  local label="$2"
  if [[ ! "$code" =~ ^(2|3) ]]; then
    fail "${label} expected 2xx, got ${code}"
  fi
}

wait_for_status() {
  local cmd_id="$1"
  local expected="$2"
  local tries="${3:-20}"
  local i status
  for ((i=1; i<=tries; i++)); do
    status="$(psql_val "SELECT COALESCE(status,'') FROM mina_pump.commands WHERE id = ${cmd_id} LIMIT 1;")"
    if [[ "${status}" == "${expected}" ]]; then
      return 0
    fi
    sleep 1
  done
  fail "command ${cmd_id} did not reach status=${expected}"
}

echo "== Health =="
curl_json "${BASE}/health" "${HDR[@]}" >/dev/null || fail "gateway health failed"

echo "== Configure SAFE pump test settings =="
"${DC[@]}" exec -T postgres psql -U trading -d trading <<'SQL'
INSERT INTO mina_pump.settings (key, value, updated_at, source) VALUES
  ('execution_enabled', '1', now()::text, 'smoke_pump_cutover'),
  ('mode', 'SIM', now()::text, 'smoke_pump_cutover'),
  ('kill_switch', '0', now()::text, 'smoke_pump_cutover'),
  ('kill_switch_reason', '', now()::text, 'smoke_pump_cutover')
ON CONFLICT (key) DO UPDATE SET
  value = EXCLUDED.value,
  updated_at = EXCLUDED.updated_at,
  source = EXCLUDED.source;
SQL

echo "== Configure pump runtime/strategy risk =="
RISK_BODY='{"profile_id":"qa_pump_open","name":"QA Pump Open","params_json":{"min_score":0.0,"min_confidence":0.0,"max_concurrent_positions":100,"cooldown_sec":0,"max_loss_streak":999,"account_size_usd":10000,"max_drawdown_pct":100.0,"max_daily_loss_pct":100.0,"max_notional_per_trade":100000}}'
RISK_RESP="$(curl_capture "${BASE}/api/risk/profiles" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${RISK_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "pump risk profile upsert"

RUNTIME_BODY='{"role":"pump","active_risk_profile":"qa_pump_open","execution_mode":"TEST","allow_auto_approve":true,"allow_manual_execute":true}'
RUNTIME_RESP="$(curl_capture "${BASE}/api/runtime/role" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${RUNTIME_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "pump runtime update"

STRATEGY_BODY='{"strategy_id":"BASELINE_SCALP","role":"pump","enabled":true,"min_confidence":0.0,"min_score":0.0,"max_positions":100,"cooldown_sec":0,"params_json":{}}'
STRATEGY_RESP="$(curl_capture "${BASE}/api/strategies" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${STRATEGY_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "pump strategy update"

SYMBOL1="PUMPCUT$((RANDOM%100000))A"
SYMBOL2="PUMPCUT$((RANDOM%100000))B"

echo "== Step A/B/C: publish -> approve -> DONE + OPEN trade =="
P1_BODY='{"symbol":"'"${SYMBOL1}"'","side":"BUY","price":1.0,"confidence":0.99,"score":0.99,"execution_allowed":false,"strategy":"BASELINE_SCALP","source":"smoke_pump_cutover"}'
P1_RESP="$(curl_capture "${BASE}/api/unified/pump/publish" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${P1_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "publish pump signal #1"
SIG1_ID="$(json_get "${P1_RESP}" "id")"
[[ -n "${SIG1_ID}" ]] || fail "publish #1 missing signal id"

A1_BODY='{"note":"smoke-pump-cutover"}'
A1_RESP="$(curl_capture "${BASE}/api/unified/pump/signals/${SIG1_ID}/approve" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${A1_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "approve pump signal #1"
CMD1_ID="$(json_get "${A1_RESP}" "command_id")"
[[ -n "${CMD1_ID}" ]] || fail "approve #1 missing command_id; response=${A1_RESP}"

wait_for_status "${CMD1_ID}" "DONE" 25
CLAIMED_BY="$(psql_val "SELECT COALESCE(claimed_by,'') FROM mina_pump.commands WHERE id = ${CMD1_ID};")"
[[ "${CLAIMED_BY}" == *"nautilus_pump_engine"* ]] || fail "command ${CMD1_ID} not claimed by nautilus_pump_engine"

OPEN_TRADE_ID="$(psql_val "SELECT id FROM mina_pump.trades WHERE symbol='${SYMBOL1}' AND UPPER(COALESCE(status,''))='OPEN' ORDER BY id DESC LIMIT 1;")"
[[ -n "${OPEN_TRADE_ID}" ]] || fail "no OPEN trade row inserted for pump signal #1"

echo "== Step D: kill-switch ON then approve another signal =="
KS_ON_BODY='{"enabled":true,"reason":"smoke_pump_cutover"}'
KS_ON_RESP="$(curl_capture "${BASE}/api/unified/pump/commands/kill_switch" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${KS_ON_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "pump kill-switch on"

P2_BODY='{"symbol":"'"${SYMBOL2}"'","side":"BUY","price":1.0,"confidence":0.99,"score":0.99,"execution_allowed":false,"strategy":"BASELINE_SCALP","source":"smoke_pump_cutover"}'
P2_RESP="$(curl_capture "${BASE}/api/unified/pump/publish" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${P2_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "publish pump signal #2"
SIG2_ID="$(json_get "${P2_RESP}" "id")"
[[ -n "${SIG2_ID}" ]] || fail "publish #2 missing signal id"

A2_BODY='{"note":"smoke-pump-cutover-kill-switch"}'
A2_RESP="$(curl_capture "${BASE}/api/unified/pump/signals/${SIG2_ID}/approve" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${A2_BODY}" || true)"
CMD2_ID=""
if [[ "${CURL_LAST_CODE}" == "409" ]]; then
  SIG2_STATUS="$(psql_val "SELECT COALESCE(status,'') FROM mina_pump.signal_inbox WHERE id = ${SIG2_ID};")"
  [[ "${SIG2_STATUS}" == "REJECTED" ]] || fail "signal #2 not REJECTED under kill-switch (gateway veto path)"
elif [[ "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
  CMD2_ID="$(json_get "${A2_RESP}" "command_id")"
  if [[ -n "${CMD2_ID}" ]]; then
    wait_for_status "${CMD2_ID}" "REJECTED" 25
  fi
  SIG2_STATUS="$(psql_val "SELECT COALESCE(status,'') FROM mina_pump.signal_inbox WHERE id = ${SIG2_ID};")"
  [[ "${SIG2_STATUS}" == "REJECTED" ]] || fail "signal #2 expected REJECTED under kill-switch, got ${SIG2_STATUS}"
else
  fail "approve #2 unexpected HTTP code ${CURL_LAST_CODE}"
fi

echo "== Step D2: direct OPEN command while kill-switch ON -> REJECTED =="
if [[ -z "${CMD2_ID}" ]]; then
  KS_OPEN_BODY='{"cmd":"EXECUTE_SIGNAL","params":{"symbol":"'"${SYMBOL2}"'","side":"BUY","confidence":0.99,"score":0.99,"strategy":"BASELINE_SCALP"}}'
  KS_OPEN_RESP="$(curl_capture "${BASE}/api/unified/pump/commands" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${KS_OPEN_BODY}" || true)"
  expect_2xx "${CURL_LAST_CODE}" "queue OPEN command while kill-switch ON"
  KS_OPEN_CMD_ID="$(json_get "${KS_OPEN_RESP}" "command_id")"
  [[ -n "${KS_OPEN_CMD_ID}" ]] || fail "kill-switch OPEN command missing command_id"
  wait_for_status "${KS_OPEN_CMD_ID}" "REJECTED" 25
else
  KS_OPEN_CMD_ID="${CMD2_ID}"
fi

echo "== Step E: CLOSE_ALL_POSITIONS allowed while kill-switch ON =="
CLOSE_BODY='{"reason":"smoke_pump_cutover_close"}'
CLOSE_RESP="$(curl_capture "${BASE}/api/unified/pump/commands/close_all" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${CLOSE_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "queue pump close_all"
CMD_CLOSE_ID="$(json_get "${CLOSE_RESP}" "command_id")"
[[ -n "${CMD_CLOSE_ID}" ]] || fail "close_all missing command_id"
wait_for_status "${CMD_CLOSE_ID}" "DONE" 25

echo "== Evidence =="
echo "pump_signal1_id=${SIG1_ID}"
echo "pump_command1_id=${CMD1_ID}"
echo "pump_trade_id=${OPEN_TRADE_ID}"
echo "pump_signal2_id=${SIG2_ID}"
echo "pump_signal2_status=${SIG2_STATUS}"
echo "pump_killswitch_command_id=${KS_OPEN_CMD_ID}"
echo "pump_close_command_id=${CMD_CLOSE_ID}"
echo "pump_close_status=DONE"

echo "✅ smoke_pump_cutover passed"
