#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_curl_json.sh
source "${HERE}/_curl_json.sh"

BASE="${BASE_URL:-http://localhost:8200}"
SYMBOL="${1:-BTCUSDT}"

echo "== Health =="
curl_json "${BASE}/health" || exit 1

echo "== Brain /api/decision via gateway =="
# Use -G so we don't depend on shell quoting for '?'.
curl_json -G "${BASE}/api/decision" --data-urlencode "symbol=${SYMBOL}"
