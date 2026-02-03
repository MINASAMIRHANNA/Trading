#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"

stop_proc "bot_paper"
stop_proc "monitor_paper"
stop_proc "dashboard_paper"
