#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"

export BOT_ROLE="pump"
export BOT_ID="pump-1"
export BOT_VERSION="1.0.0"

DASH_LOG="$LOGS_DIR/pump_dashboard.log"
MON_LOG="$LOGS_DIR/pump_monitor.log"
BOT_LOG="$LOGS_DIR/pump_bot.log"

start_proc "dashboard_pump" "$DASH_LOG" uvicorn dashboard.app:app --host 0.0.0.0 --port 8002
start_proc "bot_pump" "$BOT_LOG" python pump_hunter.py

echo "[RUNBOOK] pump stack is up on port 8002."
