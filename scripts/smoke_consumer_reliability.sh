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

wait_done_or_dead() {
  local cmd_id="$1"
  local tries="${2:-80}"
  local i row st
  for ((i=1; i<=tries; i++)); do
    row="$(psql_val "SELECT COALESCE(status,'')||'|'||COALESCE(attempt_count,0)||'|'||COALESCE(next_retry_at_ms,0)||'|'||COALESCE(dead_lettered,false) FROM mina_pump.commands WHERE id=${cmd_id} LIMIT 1;")"
    st="${row%%|*}"
    if [[ "${st}" == "DONE" || "${st}" == "DEAD" ]]; then
      echo "${row}"
      return 0
    fi
    sleep 0.5
  done
  fail "command ${cmd_id} did not reach DONE/DEAD"
}

echo "== Health =="
curl_json "${BASE}/health" "${HDR[@]}" >/dev/null || fail "gateway health failed"

echo "== Configure pump runtime/risk for reliability smoke =="
"${DC[@]}" exec -T postgres psql -U trading -d trading <<'SQL'
INSERT INTO mina_pump.settings (key, value, updated_at, source) VALUES
  ('execution_enabled', '1', now()::text, 'smoke_consumer_reliability'),
  ('mode', 'SIM', now()::text, 'smoke_consumer_reliability'),
  ('kill_switch', '0', now()::text, 'smoke_consumer_reliability'),
  ('kill_switch_reason', '', now()::text, 'smoke_consumer_reliability')
ON CONFLICT (key) DO UPDATE SET
  value = EXCLUDED.value,
  updated_at = EXCLUDED.updated_at,
  source = EXCLUDED.source;
SQL

RISK_BODY='{"profile_id":"qa_pump_open","name":"QA Pump Open","params_json":{"min_score":0.0,"min_confidence":0.0,"max_concurrent_positions":100,"cooldown_sec":0,"max_loss_streak":999,"account_size_usd":10000,"max_drawdown_pct":100.0,"max_daily_loss_pct":100.0,"max_notional_per_trade":100000}}'
RISK_RESP="$(curl_capture "${BASE}/api/risk/profiles" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${RISK_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "pump risk profile upsert"

RUNTIME_BODY='{"role":"pump","active_risk_profile":"qa_pump_open","execution_mode":"TEST","allow_auto_approve":true,"allow_manual_execute":true}'
RUNTIME_RESP="$(curl_capture "${BASE}/api/runtime/role" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${RUNTIME_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "pump runtime update"

STRATEGY_BODY='{"strategy_id":"BASELINE_SCALP","role":"pump","enabled":true,"min_confidence":0.0,"min_score":0.0,"max_positions":100,"cooldown_sec":0,"params_json":{}}'
STRATEGY_RESP="$(curl_capture "${BASE}/api/strategies" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${STRATEGY_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "pump strategy update"

echo "== Retry/backoff test: TEST_FAIL_ONCE =="
RETRY_BODY='{"cmd":"TEST_FAIL_ONCE","params":{"reason":"smoke_consumer_reliability"}}'
RETRY_RESP="$(curl_capture "${BASE}/api/unified/pump/commands" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${RETRY_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "queue TEST_FAIL_ONCE"
RETRY_CMD_ID="$(json_get "${RETRY_RESP}" "command_id")"
[[ -n "${RETRY_CMD_ID}" ]] || fail "TEST_FAIL_ONCE missing command_id"

seen_failed=0
seen_retry=0
for i in $(seq 1 120); do
  row="$(psql_val "SELECT COALESCE(status,''),COALESCE(attempt_count,0),COALESCE(next_retry_at_ms,0) FROM mina_pump.commands WHERE id=${RETRY_CMD_ID} LIMIT 1;")"
  status="$(echo "${row}" | cut -d'|' -f1)"
  attempts="$(echo "${row}" | cut -d'|' -f2)"
  retry_at="$(echo "${row}" | cut -d'|' -f3)"
  if [[ "${status}" == "FAILED" ]]; then
    seen_failed=1
  fi
  if [[ "${retry_at}" =~ ^[0-9]+$ ]] && (( retry_at > 0 )); then
    seen_retry=1
  fi
  if [[ "${status}" == "DONE" ]]; then
    break
  fi
  sleep 0.5
done
[[ "${seen_failed}" -eq 1 ]] || fail "TEST_FAIL_ONCE did not enter FAILED state"
[[ "${seen_retry}" -eq 1 ]] || fail "TEST_FAIL_ONCE did not set next_retry_at_ms"
retry_final="$(psql_val "SELECT COALESCE(status,''),COALESCE(attempt_count,0) FROM mina_pump.commands WHERE id=${RETRY_CMD_ID} LIMIT 1;")"
[[ "${retry_final%%|*}" == "DONE" ]] || fail "TEST_FAIL_ONCE did not finish DONE"

echo "== Dead-letter test: TEST_ALWAYS_FAIL with max_attempts=2 =="
DEAD_BODY='{"cmd":"TEST_ALWAYS_FAIL","params":{"reason":"smoke_consumer_reliability"}}'
DEAD_RESP="$(curl_capture "${BASE}/api/unified/pump/commands" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${DEAD_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "queue TEST_ALWAYS_FAIL"
DEAD_CMD_ID="$(json_get "${DEAD_RESP}" "command_id")"
[[ -n "${DEAD_CMD_ID}" ]] || fail "TEST_ALWAYS_FAIL missing command_id"

psql_val "UPDATE mina_pump.commands SET max_attempts=2 WHERE id=${DEAD_CMD_ID};" >/dev/null

seen_dead_failed=0
seen_dead_retry=0
for i in $(seq 1 180); do
  row="$(psql_val "SELECT COALESCE(status,''),COALESCE(attempt_count,0),COALESCE(next_retry_at_ms,0),COALESCE(dead_lettered,false) FROM mina_pump.commands WHERE id=${DEAD_CMD_ID} LIMIT 1;")"
  status="$(echo "${row}" | cut -d'|' -f1)"
  attempts="$(echo "${row}" | cut -d'|' -f2)"
  retry_at="$(echo "${row}" | cut -d'|' -f3)"
  deadflag="$(echo "${row}" | cut -d'|' -f4)"
  if [[ "${status}" == "FAILED" ]]; then
    seen_dead_failed=1
  fi
  if [[ "${retry_at}" =~ ^[0-9]+$ ]] && (( retry_at > 0 )); then
    seen_dead_retry=1
  fi
  if [[ "${deadflag}" == "t" || "${deadflag}" == "true" || "${status}" == "DEAD" ]]; then
    break
  fi
  sleep 0.5
done
[[ "${seen_dead_failed}" -eq 1 ]] || fail "TEST_ALWAYS_FAIL did not enter FAILED state before dead-letter"
[[ "${seen_dead_retry}" -eq 1 ]] || fail "TEST_ALWAYS_FAIL did not schedule retry before dead-letter"
dead_row="$(psql_val "SELECT COALESCE(status,''),COALESCE(attempt_count,0),COALESCE(dead_lettered,false) FROM mina_pump.commands WHERE id=${DEAD_CMD_ID} LIMIT 1;")"
dead_status="$(echo "${dead_row}" | cut -d'|' -f1)"
dead_attempts="$(echo "${dead_row}" | cut -d'|' -f2)"
dead_flag="$(echo "${dead_row}" | cut -d'|' -f3)"
[[ "${dead_status}" == "DEAD" ]] || fail "dead-letter command status is ${dead_status}, expected DEAD"
[[ "${dead_flag}" == "t" || "${dead_flag}" == "true" ]] || fail "dead-lettered flag not set"
[[ "${dead_attempts}" -ge 2 ]] || fail "dead-letter attempt_count is ${dead_attempts}, expected >=2"
dead_letter_rows="$(psql_val "SELECT COUNT(*) FROM mina_pump.command_dead_letters WHERE command_id=${DEAD_CMD_ID};")"
[[ "${dead_letter_rows}" -ge 1 ]] || fail "no dead-letter row for command ${DEAD_CMD_ID}"

echo "== Idempotency test: duplicate EXECUTE_SIGNAL should open one trade only =="
SYM="RELIAB$((RANDOM%100000))"
PUBLISH_BODY='{"symbol":"'"${SYM}"'","side":"BUY","price":1.0,"confidence":0.99,"score":0.99,"execution_allowed":false,"strategy":"BASELINE_SCALP","source":"smoke_consumer_reliability"}'
PUB_RESP="$(curl_capture "${BASE}/api/unified/pump/publish" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${PUBLISH_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "publish reliability signal"
SIG_ID="$(json_get "${PUB_RESP}" "id")"
[[ -n "${SIG_ID}" ]] || fail "publish reliability signal missing id"

APPROVE_BODY='{"note":"smoke-consumer-reliability"}'
APPROVE_RESP="$(curl_capture "${BASE}/api/unified/pump/signals/${SIG_ID}/approve" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${APPROVE_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "approve reliability signal"
OPEN_CMD_ID="$(json_get "${APPROVE_RESP}" "command_id")"
[[ -n "${OPEN_CMD_ID}" ]] || fail "approve reliability signal missing command_id"

wait_done_or_dead "${OPEN_CMD_ID}" >/dev/null

DUP_BODY='{"cmd":"EXECUTE_SIGNAL","params":{"signal_id":'"${SIG_ID}"',"signal_inbox_id":'"${SIG_ID}"',"inbox_id":'"${SIG_ID}"',"_dashboard_signal_id":'"${SIG_ID}"',"symbol":"'"${SYM}"'","side":"BUY","confidence":0.99,"score":0.99,"strategy":"BASELINE_SCALP"}}'
DUP_RESP="$(curl_capture "${BASE}/api/unified/pump/commands" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d "${DUP_BODY}" || true)"
expect_2xx "${CURL_LAST_CODE}" "queue duplicate EXECUTE_SIGNAL"
DUP_CMD_ID="$(json_get "${DUP_RESP}" "command_id")"
[[ -n "${DUP_CMD_ID}" ]] || fail "duplicate EXECUTE_SIGNAL missing command_id"

dup_final="$(wait_done_or_dead "${DUP_CMD_ID}")"
dup_status="$(echo "${dup_final}" | cut -d'|' -f1)"
[[ "${dup_status}" == "DONE" ]] || fail "duplicate EXECUTE_SIGNAL did not end DONE"

trade_count="$(psql_val "SELECT COUNT(*) FROM mina_pump.trades WHERE signal_inbox_id=${SIG_ID};")"
[[ "${trade_count}" -eq 1 ]] || fail "idempotency violated: expected 1 trade for signal_inbox_id=${SIG_ID}, got ${trade_count}"
dup_ack_meta="$(psql_val "SELECT COALESCE(ack_meta::text,'') FROM mina_pump.commands WHERE id=${DUP_CMD_ID};")"
dup_idempotent="$(
python3 - "${dup_ack_meta}" <<'PY'
import json,sys
raw = (sys.argv[1] or "").strip()
if not raw:
    print("")
    raise SystemExit(0)
obj = None
for _ in range(2):
    try:
        obj = json.loads(raw)
        break
    except Exception:
        obj = None
        break
if isinstance(obj, dict):
    val = obj.get("idempotent")
    if isinstance(val, bool):
        print("true" if val else "false")
    elif val is None:
        print("")
    else:
        print(str(val).lower())
else:
    print("")
PY
)"
[[ "${dup_idempotent}" == "true" ]] || fail "duplicate command ack_meta.idempotent expected true"
trade_id="$(psql_val "SELECT id FROM mina_pump.trades WHERE signal_inbox_id=${SIG_ID} ORDER BY id DESC LIMIT 1;")"

echo "== Cleanup close_all =="
CLOSE_RESP="$(curl_capture "${BASE}/api/unified/pump/commands/close_all" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"reason":"smoke_consumer_reliability_cleanup"}' || true)"
expect_2xx "${CURL_LAST_CODE}" "queue cleanup close_all"

echo "== Evidence =="
echo "retry_cmd_id=${RETRY_CMD_ID}"
echo "dead_cmd_id=${DEAD_CMD_ID}"
echo "dead_letter_rows=${dead_letter_rows}"
echo "idempotency_signal_id=${SIG_ID}"
echo "idempotency_first_command_id=${OPEN_CMD_ID}"
echo "idempotency_duplicate_command_id=${DUP_CMD_ID}"
echo "idempotency_trade_id=${trade_id}"
echo "idempotency_trade_count=${trade_count}"

echo "✅ smoke_consumer_reliability passed"
