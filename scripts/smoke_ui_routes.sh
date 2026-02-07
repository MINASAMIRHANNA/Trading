#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || true

echo "== UI build =="
pushd services/brain/dashboard >/dev/null
npm run build
popd >/dev/null

echo "✅ smoke_ui_routes done"
