#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"

export BOT_ROLE="live"
export BOT_ID="live-1"
export BOT_VERSION="1.0.0"

DASH_LOG="$LOGS_DIR/live_dashboard.log"
MON_LOG="$LOGS_DIR/live_monitor.log"
BOT_LOG="$LOGS_DIR/live_bot.log"

start_proc "dashboard_live" "$DASH_LOG" uvicorn dashboard.app:app --host 0.0.0.0 --port 8001
start_proc "monitor_live" "$MON_LOG" python execution_monitor.py
start_proc "bot_live" "$BOT_LOG" python main.py

echo "[RUNBOOK] live stack is up on port 8001."
