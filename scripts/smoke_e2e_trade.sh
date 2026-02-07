#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

BASE_URL="${BASE_URL:-http://localhost:8200}"
ROLE="${ROLE:-paper}"
SCHEMA="mina_${ROLE}"
SYMBOL="${SYMBOL:-BTCUSDT}"

POSTGRES_CID="$(docker compose ps -q postgres 2>/dev/null || true)"
if [[ -z "${POSTGRES_CID}" ]]; then
  POSTGRES_CID="$(docker compose -f docker-compose.allinone.yml ps -q postgres 2>/dev/null || true)"
fi
if [[ -z "${POSTGRES_CID}" ]]; then
  POSTGRES_CID="$(docker ps --filter 'name=postgres' --format '{{.ID}}' | head -n1 || true)"
fi
if [[ -z "${POSTGRES_CID}" ]]; then
  echo "❌ Could not find postgres container"
  exit 1
fi

psql_exec() {
  docker exec -i "${POSTGRES_CID}" psql -U trading -d trading -v ON_ERROR_STOP=1 -X -q -tA "$@"
}

ensure_role_workers() {
  local r="$1"
  local bot="mina_${r}_bot"
  local mon="mina_${r}_monitor"
  local running
  running="$(docker compose ps --services --status running 2>/dev/null || true)"
  if ! echo "$running" | grep -q "^${bot}$"; then
    docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d "${bot}" >/dev/null 2>&1 || true
  fi
  if ! echo "$running" | grep -q "^${mon}$"; then
    docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d "${mon}" >/dev/null 2>&1 || true
  fi
}

now_iso="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
now_ms="$(python - <<'PY'
import time
print(int(time.time()*1000))
PY
)"

payload="{\"symbol\":\"${SYMBOL}\",\"side\":\"LONG\",\"strategy\":\"SMOKE_TEST\",\"timeframe\":\"5m\",\"confidence\":0.95,\"score\":0.95,\"source\":\"smoke\"}"

echo "== Ensure role workers are running =="
ensure_role_workers "${ROLE}"

echo "== Ensure smoke-safe runtime settings =="
psql_exec -c "INSERT INTO ${SCHEMA}.settings(key,value,updated_at,source) VALUES ('kill_switch','0','${now_iso}','smoke_e2e') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at, source=EXCLUDED.source;"
psql_exec -c "INSERT INTO ${SCHEMA}.settings(key,value,updated_at,source) VALUES ('cooldown_after_trade_sec','0','${now_iso}','smoke_e2e') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at, source=EXCLUDED.source;"
psql_exec -c "INSERT INTO ${SCHEMA}.settings(key,value,updated_at,source) VALUES ('cooldown_after_sl_sec','0','${now_iso}','smoke_e2e') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at, source=EXCLUDED.source;"

echo "== Insert test signal =="
signal_id="$(
  psql_exec -c "INSERT INTO ${SCHEMA}.signal_inbox (received_at, received_at_ms, source, status, symbol, timeframe, strategy, side, confidence, score, payload, note) VALUES ('${now_iso}', ${now_ms}, 'smoke', 'PENDING_APPROVAL', '${SYMBOL}', '5m', 'SMOKE_TEST', 'LONG', 0.95, 0.95, \$\$${payload}\$\$, 'smoke') RETURNING id;"
)"
signal_id="$(echo "$signal_id" | tr -cd '0-9')"
if [[ -z "$signal_id" ]]; then
  echo "❌ Failed to insert signal_inbox row"
  exit 1
fi
echo "signal_id=$signal_id"

echo "== Approve signal =="
curl -sS -X POST "${BASE_URL}/api/mina/${ROLE}/signals/approve" \
  -H "Content-Type: application/json" \
  -d "{\"id\":${signal_id},\"note\":\"smoke\"}" >/dev/null

echo "== Wait for OPEN trade =="
trade_id=""
for _ in $(seq 1 30); do
  trade_id="$(psql_exec -c "select id from ${SCHEMA}.trades where status='OPEN' and symbol='${SYMBOL}' order by id desc limit 1;")"
  trade_id="$(echo "$trade_id" | tr -d '[:space:]')"
  if [[ -n "$trade_id" ]]; then
    break
  fi
  sleep 2
done
if [[ -z "$trade_id" ]]; then
  echo "❌ No OPEN trade found"
  exit 1
fi
echo "trade_id=$trade_id"

echo "== Close trade via command =="
curl -sS -X POST "${BASE_URL}/api/mina/${ROLE}/commands/queue" \
  -H "Content-Type: application/json" \
  -d "{\"cmd\":\"CLOSE_TRADE\",\"params\":{\"trade_id\":${trade_id},\"reason\":\"SMOKE_CLOSE\"}}" >/dev/null

echo "== Wait for CLOSED trade =="
status=""
for _ in $(seq 1 30); do
  status="$(psql_exec -c "select status from ${SCHEMA}.trades where id=${trade_id};")"
  status="$(echo "$status" | tr -d '[:space:]')"
  if [[ "$status" == "CLOSED" ]]; then
    break
  fi
  sleep 2
done
if [[ "$status" != "CLOSED" ]]; then
  echo "❌ Trade did not close (status=$status)"
  exit 1
fi

echo "== Brain sync =="
curl -sS -X POST "${BASE_URL}/api/unified/sync/run?role=${ROLE}&limit=500" | jq -e '.ok == true' >/dev/null || true

echo "== Brain overview =="
overview="$(curl -sS "${BASE_URL}/api/overview")"
echo "$overview" | jq .
trades_count="$(echo "$overview" | jq -r '.trades // .stats?.trades // .brain?.trades // 0')"
if [[ "${trades_count}" -lt 1 ]]; then
  echo "❌ Brain overview trades count did not increase"
  exit 1
fi

echo "✅ E2E PAPER trade smoke OK (signal_id=${signal_id}, trade_id=${trade_id})"
