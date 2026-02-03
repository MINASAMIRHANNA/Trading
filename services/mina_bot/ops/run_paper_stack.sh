#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"

export BOT_ROLE="paper"
export BOT_ID="paper-1"
export BOT_VERSION="1.0.0"

# Default to Postgres primary (override in systemd Environment= if needed)
setup_postgres_env

DASH_LOG="$LOGS_DIR/paper_dashboard.log"
MON_LOG="$LOGS_DIR/paper_monitor.log"
BOT_LOG="$LOGS_DIR/paper_bot.log"

start_proc "dashboard_paper" "$DASH_LOG" uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
start_proc "monitor_paper" "$MON_LOG" python execution_monitor.py
start_proc "bot_paper" "$BOT_LOG" python main.py

echo "[RUNBOOK] paper stack is up on port 8000."
