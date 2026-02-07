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

extract_field() {
  local json="$1"
  local expr="$2"
  if command -v jq >/dev/null 2>&1; then
    echo "$json" | jq -r "$expr"
  else
    echo "$json"
  fi
}

check_one() {
  local name="$1"
  local url="$2"
  local expected_schema="$3"

  local body
  body="$(curl_json "$url")"
  if [[ -z "$body" ]]; then
    echo "FAIL: ${name} returned empty body"
    exit 1
  fi
  if echo "$body" | grep -q "upstream_request_error"; then
    echo "FAIL: ${name} upstream_request_error"
    echo "$body"
    exit 1
  fi

  local backend host db schema
  backend="$(extract_field "$body" '.backend')"
  host="$(extract_field "$body" '.dsn_host')"
  db="$(extract_field "$body" '.db_name')"
  schema="$(extract_field "$body" '.schema')"

  if [[ "$backend" != "postgres" ]]; then
    echo "FAIL: ${name} backend=${backend} (expected postgres)"
    exit 1
  fi
  if [[ "$schema" != "$expected_schema" ]]; then
    echo "FAIL: ${name} schema=${schema} (expected ${expected_schema})"
    exit 1
  fi

  echo "${name}|${host}|${db}|${schema}"
}

echo "== Datasource singleton check =="

rows=()
rows+=("$(check_one "gateway" "${BASE_URL}/api/meta/datasource" "gateway")")
rows+=("$(check_one "brain" "${BASE_URL}/api/brain/meta/datasource" "brain")")
rows+=("$(check_one "mina_paper" "${BASE_URL}/api/mina/paper/meta/datasource" "mina_paper")")
rows+=("$(check_one "mina_live" "${BASE_URL}/api/mina/live/meta/datasource" "mina_live")")
rows+=("$(check_one "mina_pump" "${BASE_URL}/api/mina/pump/meta/datasource" "mina_pump")")

ref_host=""
ref_db=""
for row in "${rows[@]}"; do
  IFS='|' read -r name host db schema <<< "$row"
  if [[ -z "$ref_host" ]]; then
    ref_host="$host"
    ref_db="$db"
  fi
  if [[ "$host" != "$ref_host" ]]; then
    echo "FAIL: host mismatch (${name} host=${host}, ref=${ref_host})"
    exit 1
  fi
  if [[ "$db" != "$ref_db" ]]; then
    echo "FAIL: db mismatch (${name} db=${db}, ref=${ref_db})"
    exit 1
  fi
done

echo "PASS: all services wired to one postgres (${ref_host}/${ref_db})"
