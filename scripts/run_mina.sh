#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MINA="$ROOT/services/mina_bot"

if [[ ! -d "$MINA" ]]; then
  echo "Missing $MINA. Copy Mina_Bot into services/mina_bot first." >&2
  exit 1
fi

cd "$MINA"

echo "Run Mina stacks in separate terminals (example):"
echo "  bash ops/run_paper_stack.sh"
echo "  bash ops/run_live_stack.sh"
echo "  bash ops/run_pump_stack.sh"
