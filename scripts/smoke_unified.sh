#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash scripts/smoke_unified.sh                 # role=paper, base=http://localhost:8200
#   bash scripts/smoke_unified.sh paper           # role=paper
#   bash scripts/smoke_unified.sh live            # role=live
#   bash scripts/smoke_unified.sh pump            # role=pump
#   bash scripts/smoke_unified.sh http://localhost:8200
#   bash scripts/smoke_unified.sh paper http://localhost:8200

ROLE="paper"
BASE="http://localhost:8200"

arg1="${1:-}"
arg2="${2:-}"

if [[ -n "$arg1" ]]; then
  if [[ "$arg1" =~ ^https?:// ]]; then
    BASE="$arg1"
  else
    ROLE="$arg1"
  fi
fi

if [[ -n "$arg2" ]]; then
  if [[ "$arg2" =~ ^https?:// ]]; then
    BASE="$arg2"
  fi
fi

curlx() {
  if [[ -n "${GATEWAY_API_KEY:-}" ]]; then
    curl -s -H "X-API-Key: ${GATEWAY_API_KEY}" "$@"
  else
    curl -s "$@"
  fi
}


echo "== Gateway health =="
curl -s "$BASE/health" || true
echo
echo "== Unified roles =="
curlx "$BASE/api/unified/roles" | head
echo
echo "== Unified overview =="
curlx "$BASE/api/unified/overview" | head -c 800
echo
echo "== ${ROLE} snapshot =="
curlx "$BASE/api/unified/${ROLE}/snapshot" | head -c 800
echo
echo "OK"
