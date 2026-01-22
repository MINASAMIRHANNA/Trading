#!/usr/bin/env bash
set -euo pipefail

# Run Brain API on 8100.
# Run the Brain dashboard (Vite) in a separate terminal:
#   cd services/brain/dashboard && npm run dev

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRAIN="$ROOT/services/brain"

if [[ ! -d "$BRAIN" ]]; then
  echo "Missing $BRAIN. Copy trading-intelligence-platform into services/brain first." >&2
  exit 1
fi

cd "$BRAIN"
exec uvicorn api.main:app --host 127.0.0.1 --port 8100
