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
  local tries="${3:-25}"
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

command_block_reason() {
  local cmd_id="$1"
  local raw
  raw="$(psql_val "SELECT COALESCE(ack_meta::text,'') FROM mina_live.commands WHERE id = ${cmd_id} LIMIT 1;")"
  python3 - "$raw" <<'PY'
import json,sys
raw=(sys.argv[1] or "").strip()
if not raw:
    print("")
    raise SystemExit(0)
obj=None
try:
    obj=json.loads(raw)
except Exception:
    obj=None
if isinstance(obj, str):
    try:
        obj=json.loads(obj)
    except Exception:
        obj=None
if isinstance(obj, dict):
    print(str(obj.get("blocked") or ""))
else:
    print("")
PY
}

publish_signal() {
  local symbol="$1"
  local source_tag="$2"
  local body
  body='{"symbol":"'"${symbol}"'","side":"BUY","price":100,"confidence":0.99,"score":0.99,"execution_allowed":false,"strategy":"BASELINE_SCALP","source":"'"${source_tag}"'"}'
  local resp
  resp="$(curl_capture "${BASE}/api/unified/live/publish" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${body}" || true)"
  expect_2xx "${CURL_LAST_CODE}" "publish ${source_tag}"
  local signal_id
  signal_id="$(json_get "${resp}" "id")"
  [[ -n "${signal_id}" ]] || fail "publish ${source_tag} missing signal id"
  echo "${signal_id}"
}

approve_signal() {
  local signal_id="$1"
  local note="$2"
  local body
  body='{"note":"'"${note}"'","live_confirm":true,"live_confirm_ack":true}'
  local resp
  resp="$(curl_capture "${BASE}/api/unified/live/signals/${signal_id}/approve" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${body}" || true)"
  expect_2xx "${CURL_LAST_CODE}" "approve signal ${signal_id}"
  local cmd_id
  cmd_id="$(json_get "${resp}" "command_id")"
  [[ -n "${cmd_id}" ]] || fail "approve signal ${signal_id} missing command_id; response=${resp}"
  echo "${cmd_id}"
}

echo "== Health =="
curl_json "${BASE}/health" "${HDR[@]}" >/dev/null || fail "gateway health failed"

echo "== Configure live runtime + strategy for deterministic safety-gate checks =="
SETTINGS_BODY='{"execution_enabled":"1","live_execution_enabled":"1","USE_TESTNET":"TRUE","mode":"TEST","kill_switch":"0","kill_switch_reason":"","live_testnet_only":"1","live_allow_real_execution":"0"}'
SETTINGS_RESP="$(curl_capture "${BASE}/api/unified/live/settings" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${SETTINGS_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "live settings update"

RISK_BODY='{"profile_id":"qa_live_safety_gate","name":"QA Live Safety Gate","params_json":{"min_score":0.0,"min_confidence":0.0,"max_concurrent_positions":100,"cooldown_sec":0,"max_loss_streak":999,"account_size_usd":10000,"max_drawdown_pct":100.0,"max_daily_loss_pct":100.0,"max_notional_per_trade":100000}}'
RISK_RESP="$(curl_capture "${BASE}/api/risk/profiles" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${RISK_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "risk profile upsert"

RUNTIME_BODY='{"role":"live","active_risk_profile":"qa_live_safety_gate","execution_mode":"TEST","allow_auto_approve":true,"allow_manual_execute":true,"live_confirm":true,"live_confirm_ack":true}'
RUNTIME_RESP="$(curl_capture "${BASE}/api/runtime/role" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${RUNTIME_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "runtime role update"

STRATEGY_BODY='{"strategy_id":"BASELINE_SCALP","role":"live","enabled":true,"min_confidence":0.0,"min_score":0.0,"max_positions":100,"cooldown_sec":0,"params_json":{},"live_confirm":true,"live_confirm_ack":true}'
STRATEGY_RESP="$(curl_capture "${BASE}/api/strategies" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${STRATEGY_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "live strategy update"

echo "== Reset live control-plane state (disarmed + empty allowlist + permissive limits) =="
DISARM_RESP="$(curl_capture "${BASE}/api/control/live/disarm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control disarm"

ALLOWLIST_CLEAR_RESP="$(curl_capture "${BASE}/api/control/live/allowlist" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"symbols":[]}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control allowlist clear"

LIMITS_PERMISSIVE_RESP="$(curl_capture "${BASE}/api/control/live/limits" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"max_open_positions":100,"max_notional":1000000,"max_daily_loss":100000}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control limits permissive"

echo "== Step 1: default DISARMED blocks open with LIVE_GATE_NOT_CONFIRMED =="
SIG1_ID="$(publish_signal "BTCUSDT" "smoke_live_safety_gate_step1")"
CMD1_ID="$(approve_signal "${SIG1_ID}" "step1-disarmed")"
wait_for_status "${CMD1_ID}" "REJECTED" 30
CMD1_REASON="$(command_block_reason "${CMD1_ID}")"
[[ "${CMD1_REASON}" == "LIVE_GATE_NOT_CONFIRMED" ]] || fail "step1 expected LIVE_GATE_NOT_CONFIRMED got ${CMD1_REASON}"

echo "== Step 2: ARMED (not confirmed) still blocks open =="
ARM_RESP="$(curl_capture "${BASE}/api/control/live/arm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control arm"
GATE_TOKEN="$(json_get "${ARM_RESP}" "token")"
[[ -n "${GATE_TOKEN}" ]] || fail "arm did not return token"

SIG2_ID="$(publish_signal "ETHUSDT" "smoke_live_safety_gate_step2")"
CMD2_ID="$(approve_signal "${SIG2_ID}" "step2-armed")"
wait_for_status "${CMD2_ID}" "REJECTED" 30
CMD2_REASON="$(command_block_reason "${CMD2_ID}")"
[[ "${CMD2_REASON}" == "LIVE_GATE_NOT_CONFIRMED" ]] || fail "step2 expected LIVE_GATE_NOT_CONFIRMED got ${CMD2_REASON}"

echo "== Step 3: CONFIRMED allows open (safe test mode) =="
CONFIRM_RESP="$(curl_capture "${BASE}/api/control/live/confirm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"token":"'"${GATE_TOKEN}"'"}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control confirm"
CONFIRM_STATE="$(json_get "${CONFIRM_RESP}" "gate.state")"
[[ "${CONFIRM_STATE}" == "CONFIRMED" ]] || fail "confirm did not set gate to CONFIRMED"

SIG3_ID="$(publish_signal "SOLUSDT" "smoke_live_safety_gate_step3")"
CMD3_ID="$(approve_signal "${SIG3_ID}" "step3-confirmed")"
wait_for_status "${CMD3_ID}" "DONE" 30
TRADE3_ID="$(psql_val "SELECT id FROM mina_live.trades WHERE signal_inbox_id = ${SIG3_ID} ORDER BY id DESC LIMIT 1;")"
[[ -n "${TRADE3_ID}" ]] || fail "step3 expected trade row for signal ${SIG3_ID}"

echo "== Step 4: allowlist rejection =="
ALLOWLIST_RESP="$(curl_capture "${BASE}/api/control/live/allowlist" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"symbols":["BTCUSDT"]}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control allowlist set"

SIG4_ID="$(publish_signal "ADAUSDT" "smoke_live_safety_gate_step4")"
CMD4_ID="$(approve_signal "${SIG4_ID}" "step4-allowlist")"
wait_for_status "${CMD4_ID}" "REJECTED" 30
CMD4_REASON="$(command_block_reason "${CMD4_ID}")"
[[ "${CMD4_REASON}" == "SYMBOL_NOT_ALLOWED" ]] || fail "step4 expected SYMBOL_NOT_ALLOWED got ${CMD4_REASON}"

echo "== Step 5: max_open_positions limit rejection =="
ALLOWLIST_RESP2="$(curl_capture "${BASE}/api/control/live/allowlist" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"symbols":["ADAUSDT","SOLUSDT","BTCUSDT"]}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control allowlist widen"

LIMITS_ZERO_RESP="$(curl_capture "${BASE}/api/control/live/limits" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"max_open_positions":0,"max_notional":1000000,"max_daily_loss":100000}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control limits max_open_positions=0"

SIG5_ID="$(publish_signal "ADAUSDT" "smoke_live_safety_gate_step5")"
CMD5_ID="$(approve_signal "${SIG5_ID}" "step5-limit-open-positions")"
wait_for_status "${CMD5_ID}" "REJECTED" 30
CMD5_REASON="$(command_block_reason "${CMD5_ID}")"
[[ "${CMD5_REASON}" == "LIMIT_MAX_OPEN_POSITIONS" ]] || fail "step5 expected LIMIT_MAX_OPEN_POSITIONS got ${CMD5_REASON}"

echo "== Step 6: DISARM blocks opens again =="
DISARM_RESP2="$(curl_capture "${BASE}/api/control/live/disarm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control disarm step6"
LIMITS_PERMISSIVE_RESP2="$(curl_capture "${BASE}/api/control/live/limits" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"max_open_positions":100,"max_notional":1000000,"max_daily_loss":100000}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control limits permissive step6"

SIG6_ID="$(publish_signal "BTCUSDT" "smoke_live_safety_gate_step6")"
CMD6_ID="$(approve_signal "${SIG6_ID}" "step6-disarm")"
wait_for_status "${CMD6_ID}" "REJECTED" 30
CMD6_REASON="$(command_block_reason "${CMD6_ID}")"
[[ "${CMD6_REASON}" == "LIVE_GATE_NOT_CONFIRMED" ]] || fail "step6 expected LIVE_GATE_NOT_CONFIRMED got ${CMD6_REASON}"

echo "== Step 7: kill-switch blocks open but close_all remains allowed =="
KS_ON_BODY='{"enabled":true,"reason":"smoke_live_safety_gate","live_confirm":true,"live_confirm_ack":true}'
KS_ON_RESP="$(curl_capture "${BASE}/api/unified/live/commands/kill_switch" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${KS_ON_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "kill_switch ON"

ARM_RESP2="$(curl_capture "${BASE}/api/control/live/arm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control arm step7"
GATE_TOKEN2="$(json_get "${ARM_RESP2}" "token")"
[[ -n "${GATE_TOKEN2}" ]] || fail "arm step7 did not return token"
CONFIRM_RESP2="$(curl_capture "${BASE}/api/control/live/confirm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"token":"'"${GATE_TOKEN2}"'"}' || true)"
expect_2xx "${CURL_LAST_CODE}" "control confirm step7"

SIG7_ID="$(publish_signal "ETHUSDT" "smoke_live_safety_gate_step7")"
APP7_BODY='{"note":"step7-kill-switch","live_confirm":true,"live_confirm_ack":true}'
APP7_RESP="$(curl_capture "${BASE}/api/unified/live/signals/${SIG7_ID}/approve" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${APP7_BODY}" || true)"
if [[ "${CURL_LAST_CODE}" == "409" ]]; then
  SIG7_STATUS="$(psql_val "SELECT COALESCE(status,'') FROM mina_live.signal_inbox WHERE id = ${SIG7_ID} LIMIT 1;")"
  [[ "${SIG7_STATUS}" == "REJECTED" ]] || fail "step7 expected signal ${SIG7_ID} REJECTED under kill-switch veto"
  CMD7_ID=""
  CMD7_REASON="kill_switch_gateway_veto"
elif [[ "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
  CMD7_ID="$(json_get "${APP7_RESP}" "command_id")"
  if [[ -n "${CMD7_ID}" ]]; then
    wait_for_status "${CMD7_ID}" "REJECTED" 30
    CMD7_REASON="$(command_block_reason "${CMD7_ID}")"
    [[ "${CMD7_REASON}" == "kill_switch" ]] || fail "step7 expected kill_switch got ${CMD7_REASON}"
  else
    SIG7_STATUS="$(psql_val "SELECT COALESCE(status,'') FROM mina_live.signal_inbox WHERE id = ${SIG7_ID} LIMIT 1;")"
    APP7_DETAIL_ERR="$(json_get "${APP7_RESP}" "detail.error")"
    if [[ "${SIG7_STATUS}" == "REJECTED" && ( "${APP7_DETAIL_ERR}" == "strategy_risk_veto" || "${APP7_RESP}" == *"kill_switch_on"* ) ]]; then
      CMD7_ID=""
      CMD7_REASON="kill_switch_gateway_veto"
    else
      fail "step7 approve missing command_id; response=${APP7_RESP}"
    fi
  fi
else
  fail "step7 approve unexpected HTTP ${CURL_LAST_CODE}; response=${APP7_RESP}"
fi

CLOSE_BODY='{"reason":"smoke_live_safety_gate_close","live_confirm":true,"live_confirm_ack":true}'
CLOSE_RESP="$(curl_capture "${BASE}/api/unified/live/commands/close_all" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${CLOSE_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "queue close_all under kill_switch"
CLOSE_CMD_ID="$(json_get "${CLOSE_RESP}" "command_id")"
[[ -n "${CLOSE_CMD_ID}" ]] || fail "close_all missing command_id"
wait_for_status "${CLOSE_CMD_ID}" "DONE" 30

KS_OFF_BODY='{"enabled":false,"reason":"smoke_live_safety_gate_cleanup","live_confirm":true,"live_confirm_ack":true}'
KS_OFF_RESP="$(curl_capture "${BASE}/api/unified/live/commands/kill_switch" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${KS_OFF_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "kill_switch OFF cleanup"

echo "== Evidence =="
echo "step1_signal_id=${SIG1_ID} step1_command_id=${CMD1_ID} reason=${CMD1_REASON}"
echo "step2_signal_id=${SIG2_ID} step2_command_id=${CMD2_ID} reason=${CMD2_REASON}"
echo "step3_signal_id=${SIG3_ID} step3_command_id=${CMD3_ID} trade_id=${TRADE3_ID}"
echo "step4_signal_id=${SIG4_ID} step4_command_id=${CMD4_ID} reason=${CMD4_REASON}"
echo "step5_signal_id=${SIG5_ID} step5_command_id=${CMD5_ID} reason=${CMD5_REASON}"
echo "step6_signal_id=${SIG6_ID} step6_command_id=${CMD6_ID} reason=${CMD6_REASON}"
echo "step7_signal_id=${SIG7_ID} step7_command_id=${CMD7_ID} reason=${CMD7_REASON}"
echo "close_command_id=${CLOSE_CMD_ID} close_status=DONE"

echo "✅ smoke_live_safety_gate passed"
