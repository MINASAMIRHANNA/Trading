#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8200}"
ROLE="${ROLE:-paper}"
ROLES="${ROLES:-$ROLE}"

echo
echo "== regression: roles=$ROLES ts=$(date -u +%Y%m%dT%H%M%SZ) =="
echo "BASE_URL=$BASE_URL"
echo

# 1) Fast functional checks
bash scripts/verify_all.sh

# 2) Deep diagnostics snapshot (non-fatal)
echo
echo "=============================="
echo " Doctor snapshot (non-fatal)"
echo "=============================="
bash scripts/project_doctor.sh || true

# 3) Optional: show sync state summary
echo
echo "=============================="
echo " Brain sync status summary"
echo "=============================="
curl -sS --max-time 5 "$BASE_URL/api/brain/sync/status" || true
echo

echo
echo "✅ regression finished."
