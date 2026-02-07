#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

BASE_URL="${BASE_URL:-http://localhost:8200}"
API_KEY="${GATEWAY_API_KEY:-}"

have() { command -v "$1" >/dev/null 2>&1; }

curl_json() {
  local url="$1"
  if [[ -n "$API_KEY" ]]; then
    curl -sS -H "X-API-Key: ${API_KEY}" "$url"
  else
    curl -sS "$url"
  fi
}

require_http_ok_json() {
  local name="$1"
  local url="$2"
  local body
  body="$(curl_json "$url")"
  if [[ -z "$body" ]]; then
    echo "FAIL: ${name} returned empty body"
    exit 1
  fi
  if echo "$body" | grep -qi "upstream_request_error"; then
    echo "FAIL: ${name} upstream_request_error"
    echo "$body"
    exit 1
  fi
  if have jq; then
    echo "$body" | jq -e '.ok == true or .status == "ok" or .roles != null or .summary != null' >/dev/null || {
      echo "FAIL: ${name} unexpected payload"
      echo "$body"
      exit 1
    }
  fi
  echo "PASS: ${name}"
}

echo "== Verify running services use one TRADING_PG_DSN =="
containers="$(docker compose ps -q || true)"
if [[ -z "${containers// /}" ]]; then
  containers="$(docker ps --filter 'name=trading' --format '{{.ID}}' || true)"
fi
if [[ -z "${containers// /}" ]]; then
  echo "FAIL: no running containers found"
  exit 1
fi

dsn_map_file="/tmp/trading_dsn_map.$$"
rm -f "$dsn_map_file"
for cid in $containers; do
  env_lines="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$cid" 2>/dev/null || true)"
  name="$(docker inspect --format '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##' || echo "$cid")"
  dsn="$(echo "$env_lines" | sed -n 's/^TRADING_PG_DSN=//p' | tail -n1)"
  if [[ -n "$dsn" ]]; then
    dsn="$(echo "$dsn" | sed -E 's#^postgresql\+psycopg:#postgresql:#')"
    echo "${name}|${dsn}" >> "$dsn_map_file"
  fi
done

if [[ ! -s "$dsn_map_file" ]]; then
  echo "FAIL: no TRADING_PG_DSN found in running containers"
  exit 1
fi

cut -d'|' -f2 "$dsn_map_file" | sort -u > /tmp/trading_dsns.$$ || true
unique_count="$(wc -l < /tmp/trading_dsns.$$ | tr -d '[:space:]')"
if [[ "$unique_count" != "1" ]]; then
  echo "FAIL: multiple TRADING_PG_DSN values detected"
  while IFS='|' read -r name dsn; do
    echo "  ${name} => ${dsn}"
  done < "$dsn_map_file"
  rm -f "$dsn_map_file"
  rm -f /tmp/trading_dsns.$$
  exit 1
fi
single_dsn="$(head -n1 /tmp/trading_dsns.$$)"
rm -f "$dsn_map_file"
rm -f /tmp/trading_dsns.$$
echo "PASS: single TRADING_PG_DSN => $single_dsn"

echo "== Verify schemas/tables in Postgres =="
pg_cid="$(docker compose ps -q postgres || true)"
if [[ -z "$pg_cid" ]]; then
  pg_cid="$(docker ps --filter 'name=postgres' --format '{{.ID}}' | head -n1 || true)"
fi
if [[ -z "$pg_cid" ]]; then
  echo "FAIL: postgres container not found"
  exit 1
fi

psql_cmd=(docker exec -i "$pg_cid" psql -U trading -d trading -v ON_ERROR_STOP=1 -X -q -tA)

for schema in mina_paper mina_live mina_pump brain; do
  exists="$(${psql_cmd[@]} -c "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name='${schema}');")"
  exists="$(echo "$exists" | tr -d '[:space:]')"
  [[ "$exists" == "t" || "$exists" == "true" ]] || { echo "FAIL: schema missing => ${schema}"; exit 1; }
  echo "PASS: schema exists => ${schema}"
done

for schema in mina_paper mina_live mina_pump; do
  for tbl in trades events logs commands settings; do
    t_exists="$(${psql_cmd[@]} -c "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='${schema}' AND table_name='${tbl}');")"
    t_exists="$(echo "$t_exists" | tr -d '[:space:]')"
    [[ "$t_exists" == "t" || "$t_exists" == "true" ]] || { echo "FAIL: missing table ${schema}.${tbl}"; exit 1; }
  done
  echo "PASS: required tables exist in ${schema}"
done

for tbl in sync_state; do
  t_exists="$(${psql_cmd[@]} -c "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='brain' AND table_name='${tbl}');")"
  t_exists="$(echo "$t_exists" | tr -d '[:space:]')"
  [[ "$t_exists" == "t" || "$t_exists" == "true" ]] || { echo "FAIL: missing table brain.${tbl}"; exit 1; }
done
echo "PASS: required tables exist in brain"

echo "== Verify Gateway reads each schema =="
require_http_ok_json "ops status paper" "${BASE_URL}/api/ops/status?role=paper"
require_http_ok_json "ops status live" "${BASE_URL}/api/ops/status?role=live"
require_http_ok_json "ops status pump" "${BASE_URL}/api/ops/status?role=pump"
require_http_ok_json "unified stats paper" "${BASE_URL}/api/unified/paper/stats"
require_http_ok_json "unified stats live" "${BASE_URL}/api/unified/live/stats"
require_http_ok_json "unified stats pump" "${BASE_URL}/api/unified/pump/stats"
require_http_ok_json "brain inspector" "${BASE_URL}/api/brain/inspector/overview?role=all"
require_http_ok_json "portfolio summary" "${BASE_URL}/api/portfolio/summary?role=all"

echo "✅ verify_single_db passed"
