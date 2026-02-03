#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"

status_proc "dashboard_live"
status_proc "monitor_live"
status_proc "bot_live"
