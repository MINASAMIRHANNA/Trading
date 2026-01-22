#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/gateway"

if [[ ! -d .venv ]]; then
  python -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt >/dev/null
pip install -e . >/dev/null

exec uvicorn gateway_api.main:app --host 127.0.0.1 --port 8200
