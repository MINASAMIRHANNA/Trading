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
LIVE_HDR=(-H "X-Live-Confirm: true" -H "X-Live-Confirm-Ack: true")
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
    status="$(psql_val "SELECT COALESCE(status,'') FROM mina_live.commands WHERE id = ${cmd_id} LIMIT 1;")"
    if [[ "$status" == "$expected" ]]; then
      return 0
    fi
    sleep 1
  done
  fail "command ${cmd_id} did not reach status=${expected}"
}

echo "== Health =="
curl_json "${BASE}/health" "${HDR[@]}" >/dev/null || fail "gateway health failed"

echo "== Configure SAFE live test settings =="
"${DC[@]}" exec -T postgres psql -U trading -d trading <<'SQL'
INSERT INTO gateway.shared_settings (key, value, updated_at, updated_by) VALUES
  ('live_execution_enabled', '1', now(), 'smoke_live_cutover'),
  ('live_double_confirm_required', '1', now(), 'smoke_live_cutover'),
  ('live_pin_enabled', '0', now(), 'smoke_live_cutover'),
  ('live_max_daily_loss', '0', now(), 'smoke_live_cutover'),
  ('live_max_open_positions', '100', now(), 'smoke_live_cutover'),
  ('live_max_leverage', '50', now(), 'smoke_live_cutover'),
  ('live_max_notional', '1000000', now(), 'smoke_live_cutover'),
  ('live_cooldown_sec', '0', now(), 'smoke_live_cutover'),
  ('live_rollout_stage', 'LIVE-0', now(), 'smoke_live_cutover')
ON CONFLICT (key) DO UPDATE SET
  value = EXCLUDED.value,
  updated_at = EXCLUDED.updated_at,
  updated_by = EXCLUDED.updated_by;

INSERT INTO mina_live.settings (key, value, updated_at, source) VALUES
  ('execution_enabled', '1', now()::text, 'smoke_live_cutover'),
  ('live_execution_enabled', '1', now()::text, 'smoke_live_cutover'),
  ('USE_TESTNET', 'TRUE', now()::text, 'smoke_live_cutover'),
  ('mode', 'TEST', now()::text, 'smoke_live_cutover'),
  ('kill_switch', '0', now()::text, 'smoke_live_cutover'),
  ('kill_switch_reason', '', now()::text, 'smoke_live_cutover')
ON CONFLICT (key) DO UPDATE SET
  value = EXCLUDED.value,
  updated_at = EXCLUDED.updated_at,
  source = EXCLUDED.source;
SQL

echo "== Configure live runtime/strategy risk =="
RISK_BODY='{"profile_id":"qa_live_open","name":"QA Live Open","params_json":{"min_score":0.0,"min_confidence":0.0,"max_concurrent_positions":100,"cooldown_sec":0,"max_loss_streak":999,"account_size_usd":10000,"max_drawdown_pct":100.0,"max_daily_loss_pct":100.0,"max_notional_per_trade":100000}}'
RISK_RESP="$(curl_capture "${BASE}/api/risk/profiles" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${RISK_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "risk profile upsert"

RUNTIME_BODY='{"role":"live","active_risk_profile":"qa_live_open","execution_mode":"TEST","allow_auto_approve":true,"allow_manual_execute":true,"live_confirm":true,"live_confirm_ack":true}'
RUNTIME_RESP="$(curl_capture "${BASE}/api/runtime/role" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${RUNTIME_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "runtime role update"

STRATEGY_BODY='{"strategy_id":"BASELINE_SCALP","role":"live","enabled":true,"min_confidence":0.0,"min_score":0.0,"max_positions":100,"cooldown_sec":0,"params_json":{},"live_confirm":true,"live_confirm_ack":true}'
STRATEGY_RESP="$(curl_capture "${BASE}/api/strategies" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${STRATEGY_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "live strategy update"

echo "== Step A/B/C: publish -> approve -> DONE + OPEN trade =="
P1_BODY='{"symbol":"SOLUSDT","side":"BUY","price":150,"confidence":0.99,"score":0.99,"execution_allowed":false,"strategy":"BASELINE_SCALP","source":"smoke_live_cutover"}'
P1_RESP="$(curl_capture "${BASE}/api/unified/live/publish" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${P1_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "publish live signal #1"
SIG1_ID="$(json_get "${P1_RESP}" "id")"
[[ -n "${SIG1_ID}" ]] || fail "publish #1 missing signal id"

A1_BODY='{"note":"smoke-live-cutover","live_confirm":true,"live_confirm_ack":true}'
A1_RESP="$(curl_capture "${BASE}/api/unified/live/signals/${SIG1_ID}/approve" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${A1_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "approve live signal #1"
CMD1_ID="$(json_get "${A1_RESP}" "command_id")"
[[ -n "${CMD1_ID}" ]] || fail "approve #1 missing command_id; response=${A1_RESP}"

wait_for_status "${CMD1_ID}" "DONE" 25
CLAIMED_BY="$(psql_val "SELECT COALESCE(claimed_by,'') FROM mina_live.commands WHERE id = ${CMD1_ID};")"
[[ "${CLAIMED_BY}" == *"nautilus_live_engine"* ]] || fail "command ${CMD1_ID} not claimed by nautilus_live_engine"

OPEN_TRADE_ID="$(psql_val "SELECT id FROM mina_live.trades WHERE symbol='SOLUSDT' AND UPPER(COALESCE(status,''))='OPEN' ORDER BY id DESC LIMIT 1;")"
[[ -n "${OPEN_TRADE_ID}" ]] || fail "no OPEN trade row inserted for live signal #1"

echo "== Step D: kill-switch ON then approve another -> REJECTED =="
KS_ON_BODY='{"enabled":true,"reason":"smoke_live_cutover","live_confirm":true,"live_confirm_ack":true}'
KS_ON_RESP="$(curl_capture "${BASE}/api/unified/live/commands/kill_switch" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${KS_ON_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "live kill-switch on"

P2_BODY='{"symbol":"ADAUSDT","side":"BUY","price":1.0,"confidence":0.99,"score":0.99,"execution_allowed":false,"strategy":"BASELINE_SCALP","source":"smoke_live_cutover"}'
P2_RESP="$(curl_capture "${BASE}/api/unified/live/publish" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${P2_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "publish live signal #2"
SIG2_ID="$(json_get "${P2_RESP}" "id")"
[[ -n "${SIG2_ID}" ]] || fail "publish #2 missing signal id"

A2_BODY='{"note":"smoke-live-cutover-kill-switch","live_confirm":true,"live_confirm_ack":true}'
A2_RESP="$(curl_capture "${BASE}/api/unified/live/signals/${SIG2_ID}/approve" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${A2_BODY}" || true)"
if [[ "${CURL_LAST_CODE}" == "409" ]]; then
  SIG2_STATUS="$(psql_val "SELECT COALESCE(status,'') FROM mina_live.signal_inbox WHERE id = ${SIG2_ID};")"
  [[ "${SIG2_STATUS}" == "REJECTED" ]] || fail "signal #2 not REJECTED under kill-switch (gateway veto path)"
elif [[ "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
  CMD2_ID="$(json_get "${A2_RESP}" "command_id")"
  if [[ -n "${CMD2_ID}" ]]; then
    wait_for_status "${CMD2_ID}" "REJECTED" 25
    SIG2_STATUS="$(psql_val "SELECT COALESCE(status,'') FROM mina_live.signal_inbox WHERE id = ${SIG2_ID};")"
  else
    SIG2_STATUS="$(psql_val "SELECT COALESCE(status,'') FROM mina_live.signal_inbox WHERE id = ${SIG2_ID};")"
    A2_DETAIL_ERR="$(json_get "${A2_RESP}" "detail.error")"
    if [[ "${SIG2_STATUS}" == "REJECTED" && ( "${A2_DETAIL_ERR}" == "strategy_risk_veto" || "${A2_RESP}" == *"kill_switch_on"* ) ]]; then
      :
    else
      fail "approve #2 missing command_id and not a recognized kill-switch veto; response=${A2_RESP}"
    fi
  fi
else
  fail "approve #2 unexpected HTTP code ${CURL_LAST_CODE}"
fi

echo "== Step E: CLOSE_ALL_POSITIONS allowed while kill-switch ON =="
CLOSE_BODY='{"reason":"smoke_live_cutover_close","live_confirm":true,"live_confirm_ack":true}'
CLOSE_RESP="$(curl_capture "${BASE}/api/unified/live/commands/close_all" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${CLOSE_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "queue live close_all"
CMD_CLOSE_ID="$(json_get "${CLOSE_RESP}" "command_id")"
[[ -n "${CMD_CLOSE_ID}" ]] || fail "close_all missing command_id"

wait_for_status "${CMD_CLOSE_ID}" "DONE" 25

echo "== Evidence =="
echo "signal1_id=${SIG1_ID} command1_id=${CMD1_ID} trade_id=${OPEN_TRADE_ID}"
echo "signal2_id=${SIG2_ID} signal2_status=${SIG2_STATUS}"
echo "close_command_id=${CMD_CLOSE_ID} close_status=DONE"

echo "✅ smoke_live_cutover passed"
