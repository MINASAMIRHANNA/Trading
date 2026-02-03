#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE_URL:-http://localhost:8200}"
KEY="${GATEWAY_API_KEY:-}"

code() {
  curl -s -o /dev/null -w "%{http_code}" "$@"
}

echo "== Health =="
curl -s "$BASE/health" && echo

echo "== Auth status (public endpoint) =="
curl -s "$BASE/api/auth/status" && echo

if [[ -z "$KEY" ]]; then
  echo "== Auth is disabled (GATEWAY_API_KEY not set) -> /api/* should be public =="
  echo -n "HTTP /api/unified/overview: "
  code "$BASE/api/unified/overview" && echo
  echo "== Done =="
  exit 0
fi

echo "== Auth is enabled -> /api/* should require header OR cookie =="

echo -n "HTTP /api/unified/overview (no creds): "
code "$BASE/api/unified/overview" && echo

echo -n "HTTP /api/unified/overview (header): "
code -H "X-API-Key: $KEY" "$BASE/api/unified/overview" && echo

COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

echo "== Login (sets HttpOnly cookie) =="
curl -s -c "$COOKIE_JAR" -H "Content-Type: application/json" \
  -d "{\"api_key\":\"$KEY\"}" \
  "$BASE/api/auth/login" && echo

echo -n "HTTP /api/unified/overview (cookie): "
code -b "$COOKIE_JAR" "$BASE/api/unified/overview" && echo

echo "== Logout (clears cookie) =="
curl -s -b "$COOKIE_JAR" "$BASE/api/auth/logout" && echo

echo "== Done =="
