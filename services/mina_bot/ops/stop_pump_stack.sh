#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_lib.sh"

stop_proc "bot_pump"
stop_proc "dashboard_pump"
