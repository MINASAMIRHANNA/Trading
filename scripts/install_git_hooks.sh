#!/usr/bin/env bash
set -euo pipefail

if ! command -v git >/dev/null 2>&1; then
  echo "git not found"
  exit 1
fi

ROOT="$(git rev-parse --show-toplevel)"
HOOK_DIR="$ROOT/.git/hooks"
mkdir -p "$HOOK_DIR"

cat > "$HOOK_DIR/pre-commit" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
# Run project regression checks before each commit
bash scripts/regression.sh
HOOK

chmod +x "$HOOK_DIR/pre-commit"

echo "✅ Installed pre-commit hook: scripts/regression.sh"
