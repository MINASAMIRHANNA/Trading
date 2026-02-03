#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PY_BIN=${PY_BIN:-python3}

if [[ ! -d .venv ]]; then
  "$PY_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install -U pip setuptools wheel

# Install all service requirements into the single venv
python -m pip install -r services/brain/requirements.txt -r services/mina_bot/requirements.txt -r gateway/requirements.txt

python - <<'PY'
import sys
print('✅ Root venv ready')
print('Python:', sys.version)
PY
