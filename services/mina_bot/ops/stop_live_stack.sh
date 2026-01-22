#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"

stop_proc "bot_live"
stop_proc "monitor_live"
stop_proc "dashboard_live"
