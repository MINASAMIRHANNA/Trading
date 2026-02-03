#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-paper}"
SYMBOL="${2:-BTCUSDT}"
SIDE="${3:-BUY}"   # BUY or SELL
BASE="${BASE_URL:-http://localhost:8200}"

# Minimal publish payload compatible with Mina dashboard /publish
# This only stages the signal; you still need to approve it.
BODY=$(cat <<JSON
{
  "symbol": "${SYMBOL}",
  "timeframe": "1m",
  "strategy": "demo_seed",
  "side": "${SIDE}",
  "confidence": 0.55,
  "score": 0.55,
  "note": "seed_demo_signal",
  "payload": {
    "source": "seed_script",
    "explain": {"demo": true}
  }
}
JSON
)

curl -sS -X POST "${BASE}/api/unified/${ROLE}/signals/publish"   -H "Content-Type: application/json"   -d "${BODY}"
echo
