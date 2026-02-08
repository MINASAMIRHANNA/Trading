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

LOG_PATH="${QA_PACK_LOG_PATH:-/tmp/qa_pack.log}"
mkdir -p "$(dirname "${LOG_PATH}")" 2>/dev/null || true
: > "${LOG_PATH}"
exec > >(tee -a "${LOG_PATH}") 2>&1

HDR=(-H "X-API-Key: ${KEY}")
LIVE_HDR=(-H "X-Live-Confirm: true" -H "X-Live-Confirm-Ack: true")
DC=(docker compose -f docker-compose.yml -f docker-compose.bots.yml)

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

expect_2xx() {
  local code="$1"
  local label="$2"
  if [[ ! "${code}" =~ ^(2|3) ]]; then
    fail "${label} expected 2xx, got ${code}"
  fi
}

json_get() {
  local raw="$1"
  local path="$2"
  python3 - "$raw" "$path" <<'PY'
import json
import sys
raw = sys.argv[1]
path = sys.argv[2]
try:
    obj = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
val = obj
for part in path.split("."):
    if not part:
        continue
    if isinstance(val, dict):
        val = val.get(part)
    else:
        val = None
        break
if val is None:
    print("")
elif isinstance(val, (dict, list)):
    print(json.dumps(val, ensure_ascii=True))
else:
    print(val)
PY
}

kv_from_line() {
  local line="$1"
  local key="$2"
  echo "${line}" | sed -n "s/.*${key}=\\([^ ]*\\).*/\\1/p" | tail -n1
}

psql_val() {
  local q="$1"
  "${DC[@]}" exec -T postgres psql -U trading -d trading -At -c "$q" | tr -d '\r'
}

run_and_capture() {
  local cmd="$1"
  local out rc
  set +e
  out="$(eval "${cmd}" 2>&1)"
  rc=$?
  set -e
  echo "${out}"
  if [[ "${rc}" -ne 0 ]]; then
    fail "command failed (${rc}): ${cmd}"
  fi
}

wait_command_status() {
  local schema="$1"
  local cmd_id="$2"
  local expected="$3"
  local tries="${4:-40}"
  local i status
  for ((i=1; i<=tries; i++)); do
    status="$(psql_val "SELECT COALESCE(status,'') FROM ${schema}.commands WHERE id=${cmd_id} LIMIT 1;")"
    if [[ "${status}" == "${expected}" ]]; then
      echo "${status}"
      return 0
    fi
    sleep 0.5
  done
  echo "${status:-}"
  return 1
}

ensure_live_safe_reset() {
  set +e
  local body resp cmd_id

  resp="$(curl_capture "${BASE}/api/control/live/disarm" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{}' || true)"
  if [[ ! "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
    echo "[WARN] live disarm reset failed: code=${CURL_LAST_CODE} body=${resp}"
  fi

  resp="$(curl_capture "${BASE}/api/control/live/allowlist" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"symbols":[]}' || true)"
  if [[ ! "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
    echo "[WARN] live allowlist reset failed: code=${CURL_LAST_CODE} body=${resp}"
  fi

  # Keep limits permissive for deterministic smoke behavior while still safe by gate defaults.
  resp="$(curl_capture "${BASE}/api/control/live/limits" -X POST "${HDR[@]}" -H "Content-Type: application/json" -d '{"max_open_positions":100,"max_notional":1000000,"max_daily_loss":100000}' || true)"
  if [[ ! "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
    echo "[WARN] live limits reset failed: code=${CURL_LAST_CODE} body=${resp}"
  fi

  body='{"enabled":false,"reason":"smoke_qa_pack_reset","live_confirm":true,"live_confirm_ack":true}'
  resp="$(curl_capture "${BASE}/api/unified/live/commands/kill_switch" -X POST "${HDR[@]}" "${LIVE_HDR[@]}" -H "Content-Type: application/json" -d "${body}" || true)"
  if [[ "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
    cmd_id="$(json_get "${resp}" "command_id")"
    if [[ -n "${cmd_id}" ]]; then
      wait_command_status "mina_live" "${cmd_id}" "DONE" 40 >/dev/null || true
    fi
  else
    echo "[WARN] live kill_switch reset failed: code=${CURL_LAST_CODE} body=${resp}"
  fi
  set -e
}

cleanup() {
  echo "== Cleanup (restore safe live state) =="
  ensure_live_safe_reset
  echo "qa_pack_log_path=${LOG_PATH}"
}
trap cleanup EXIT

echo "== QA Pack Start =="
echo "qa_pack_log_path=${LOG_PATH}"
echo "base_url=${BASE}"

echo "== Health =="
curl_json "${BASE}/health" "${HDR[@]}" >/dev/null || fail "gateway health failed"

echo "== Deterministic reset =="
ensure_live_safe_reset

echo "== Reliability scenario =="
REL_OUT="$(run_and_capture "bash scripts/smoke_consumer_reliability.sh")"

RETRY_CMD_ID="$(echo "${REL_OUT}" | sed -n 's/^retry_cmd_id=\([0-9][0-9]*\)$/\1/p' | tail -n1)"
DEAD_CMD_ID="$(echo "${REL_OUT}" | sed -n 's/^dead_cmd_id=\([0-9][0-9]*\)$/\1/p' | tail -n1)"
IDEMP_SIG_ID="$(echo "${REL_OUT}" | sed -n 's/^idempotency_signal_id=\([0-9][0-9]*\)$/\1/p' | tail -n1)"
IDEMP_DUP_CMD_ID="$(echo "${REL_OUT}" | sed -n 's/^idempotency_duplicate_command_id=\([0-9][0-9]*\)$/\1/p' | tail -n1)"
IDEMP_TRADE_ID="$(echo "${REL_OUT}" | sed -n 's/^idempotency_trade_id=\([0-9][0-9]*\)$/\1/p' | tail -n1)"

[[ -n "${RETRY_CMD_ID}" ]] || fail "could not parse retry_cmd_id from reliability smoke"
[[ -n "${DEAD_CMD_ID}" ]] || fail "could not parse dead_cmd_id from reliability smoke"
[[ -n "${IDEMP_SIG_ID}" ]] || fail "could not parse idempotency_signal_id from reliability smoke"
[[ -n "${IDEMP_DUP_CMD_ID}" ]] || fail "could not parse idempotency_duplicate_command_id from reliability smoke"
[[ -n "${IDEMP_TRADE_ID}" ]] || fail "could not parse idempotency_trade_id from reliability smoke"

RETRY_ROW="$(psql_val "SELECT COALESCE(status,''),COALESCE(attempt_count,0),COALESCE(next_retry_at_ms,0),COALESCE(done_at_ms,0) FROM mina_pump.commands WHERE id=${RETRY_CMD_ID} LIMIT 1;")"
RETRY_STATUS="$(echo "${RETRY_ROW}" | cut -d'|' -f1)"
RETRY_ATTEMPT_COUNT="$(echo "${RETRY_ROW}" | cut -d'|' -f2)"
RETRY_NEXT_RETRY_AT_MS="$(echo "${RETRY_ROW}" | cut -d'|' -f3)"
RETRY_DONE_AT_MS="$(echo "${RETRY_ROW}" | cut -d'|' -f4)"

DEAD_ROW="$(psql_val "SELECT COALESCE(status,''),COALESCE(dead_lettered,false) FROM mina_pump.commands WHERE id=${DEAD_CMD_ID} LIMIT 1;")"
DEAD_STATUS="$(echo "${DEAD_ROW}" | cut -d'|' -f1)"
DEAD_DEAD_LETTERED="$(echo "${DEAD_ROW}" | cut -d'|' -f2)"
DEAD_LETTER_ROW_ID="$(psql_val "SELECT COALESCE(id,0) FROM mina_pump.command_dead_letters WHERE command_id=${DEAD_CMD_ID} ORDER BY id DESC LIMIT 1;")"

IDEMP_DUP_ACK_META="$(psql_val "SELECT COALESCE(ack_meta::text,'') FROM mina_pump.commands WHERE id=${IDEMP_DUP_CMD_ID} LIMIT 1;")"
IDEMP_ACK_FLAG="$(
python3 - "${IDEMP_DUP_ACK_META}" <<'PY'
import json
import sys
raw = (sys.argv[1] or "").strip()
if not raw:
    print("false")
    raise SystemExit(0)
obj = None
try:
    obj = json.loads(raw)
except Exception:
    obj = None
if isinstance(obj, str):
    try:
        obj = json.loads(obj)
    except Exception:
        obj = None
if isinstance(obj, dict):
    v = obj.get("idempotent")
    print("true" if bool(v) else "false")
else:
    print("false")
PY
)"

echo "reliability_retry_cmd_id=${RETRY_CMD_ID} final_status=${RETRY_STATUS} attempt_count=${RETRY_ATTEMPT_COUNT} next_retry_at_ms=${RETRY_NEXT_RETRY_AT_MS} done_at_ms=${RETRY_DONE_AT_MS}"
echo "reliability_dead_cmd_id=${DEAD_CMD_ID} status=${DEAD_STATUS} dead_lettered=${DEAD_DEAD_LETTERED} dead_letter_row_id=${DEAD_LETTER_ROW_ID}"
echo "reliability_idempotency_signal_inbox_id=${IDEMP_SIG_ID} first_trade_id=${IDEMP_TRADE_ID} duplicate_cmd_id=${IDEMP_DUP_CMD_ID} duplicate_ack_contains_idempotent=${IDEMP_ACK_FLAG}"

echo "== Live safety scenario =="
SAFE_OUT="$(run_and_capture "bash scripts/smoke_live_safety_gate.sh")"

STEP1_LINE="$(echo "${SAFE_OUT}" | rg '^step1_signal_id=' | tail -n1)"
STEP3_LINE="$(echo "${SAFE_OUT}" | rg '^step3_signal_id=' | tail -n1)"
STEP4_LINE="$(echo "${SAFE_OUT}" | rg '^step4_signal_id=' | tail -n1)"
STEP5_LINE="$(echo "${SAFE_OUT}" | rg '^step5_signal_id=' | tail -n1)"
STEP7_LINE="$(echo "${SAFE_OUT}" | rg '^step7_signal_id=' | tail -n1)"
CLOSE_LINE="$(echo "${SAFE_OUT}" | rg '^close_command_id=' | tail -n1)"

[[ -n "${STEP1_LINE}" ]] || fail "missing step1 evidence from live safety smoke"
[[ -n "${STEP3_LINE}" ]] || fail "missing step3 evidence from live safety smoke"
[[ -n "${STEP4_LINE}" ]] || fail "missing step4 evidence from live safety smoke"
[[ -n "${STEP5_LINE}" ]] || fail "missing step5 evidence from live safety smoke"
[[ -n "${STEP7_LINE}" ]] || fail "missing step7 evidence from live safety smoke"
[[ -n "${CLOSE_LINE}" ]] || fail "missing close evidence from live safety smoke"

STEP1_SIGNAL_ID="$(kv_from_line "${STEP1_LINE}" "step1_signal_id")"
STEP1_COMMAND_ID="$(kv_from_line "${STEP1_LINE}" "step1_command_id")"
STEP1_REASON="$(kv_from_line "${STEP1_LINE}" "reason")"

STEP3_SIGNAL_ID="$(kv_from_line "${STEP3_LINE}" "step3_signal_id")"
STEP3_COMMAND_ID="$(kv_from_line "${STEP3_LINE}" "step3_command_id")"
STEP3_TRADE_ID="$(kv_from_line "${STEP3_LINE}" "trade_id")"

STEP4_SIGNAL_ID="$(kv_from_line "${STEP4_LINE}" "step4_signal_id")"
STEP4_COMMAND_ID="$(kv_from_line "${STEP4_LINE}" "step4_command_id")"
STEP4_REASON="$(kv_from_line "${STEP4_LINE}" "reason")"

STEP5_SIGNAL_ID="$(kv_from_line "${STEP5_LINE}" "step5_signal_id")"
STEP5_COMMAND_ID="$(kv_from_line "${STEP5_LINE}" "step5_command_id")"
STEP5_REASON="$(kv_from_line "${STEP5_LINE}" "reason")"

STEP7_SIGNAL_ID="$(kv_from_line "${STEP7_LINE}" "step7_signal_id")"
STEP7_COMMAND_ID="$(kv_from_line "${STEP7_LINE}" "step7_command_id")"
STEP7_REASON="$(kv_from_line "${STEP7_LINE}" "reason")"

CLOSE_COMMAND_ID="$(kv_from_line "${CLOSE_LINE}" "close_command_id")"
CLOSE_STATUS="$(kv_from_line "${CLOSE_LINE}" "close_status")"

echo "safety_gate_not_confirmed_signal_id=${STEP1_SIGNAL_ID} command_id=${STEP1_COMMAND_ID} reason=${STEP1_REASON}"
echo "safety_confirmed_pass_signal_id=${STEP3_SIGNAL_ID} command_id=${STEP3_COMMAND_ID} trade_id=${STEP3_TRADE_ID}"
echo "safety_allowlist_block_signal_id=${STEP4_SIGNAL_ID} command_id=${STEP4_COMMAND_ID} reason=${STEP4_REASON}"
echo "safety_limits_block_signal_id=${STEP5_SIGNAL_ID} command_id=${STEP5_COMMAND_ID} reason=${STEP5_REASON}"
echo "safety_killswitch_open_reject_signal_id=${STEP7_SIGNAL_ID} command_id=${STEP7_COMMAND_ID} reason=${STEP7_REASON}"
echo "safety_close_allowed_command_id=${CLOSE_COMMAND_ID} status=${CLOSE_STATUS}"

echo "== Observability snapshot =="
OBS_RESP="$(curl_capture "${BASE}/api/unified/observability" "${HDR[@]}" || true)"
expect_2xx "${CURL_LAST_CODE}" "GET /api/unified/observability"
OBS_SUMMARY="$(
OBS_JSON="${OBS_RESP}" python3 - <<'PY'
import json
import os

raw = os.environ.get("OBS_JSON", "")
obj = json.loads(raw)
items = obj.get("items") or []
by_role = {str((it or {}).get("role") or ""): (it or {}) for it in items if isinstance(it, dict)}

def claim(item):
    c = item.get("last_claim") or {}
    cid = c.get("command_id")
    cmd = str(c.get("cmd") or "")
    st = str(c.get("status") or "")
    if cid is None:
        return "-/-/-"
    return f"{cid}/{cmd}/{st}"

def trade(item):
    t = item.get("last_trade") or {}
    tid = t.get("trade_id")
    sym = str(t.get("symbol") or "")
    st = str(t.get("status") or "")
    if tid is None:
        return "-/-/-"
    return f"{tid}/{sym}/{st}"

paper = by_role.get("paper", {})
live = by_role.get("live", {})
pump = by_role.get("pump", {})

print(
    "paper online="
    + str(bool((paper.get("engine") or {}).get("online")))
    + " last_claim="
    + claim(paper)
    + " last_trade="
    + trade(paper)
)
print(
    "live  online="
    + str(bool((live.get("engine") or {}).get("online")))
    + " gate="
    + str(((live.get("live_gate") or {}).get("state") or ""))
    + " kill="
    + str(bool((live.get("kill_switch") or {}).get("on")))
    + " last_claim="
    + claim(live)
    + " last_trade="
    + trade(live)
)
print(
    "pump  online="
    + str(bool((pump.get("engine") or {}).get("online")))
    + " last_claim="
    + claim(pump)
    + " last_trade="
    + trade(pump)
)
print("errors_count=" + str(len(obj.get("errors") or [])))
PY
)"
echo "${OBS_SUMMARY}"

echo "✅ smoke_qa_pack passed"
