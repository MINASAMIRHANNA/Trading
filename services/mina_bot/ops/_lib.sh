#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS_DIR="$ROOT_DIR/.pids"
LOGS_DIR="$ROOT_DIR/logs/runbook"

mkdir -p "$PIDS_DIR" "$LOGS_DIR"

# Activate venv (prefer monorepo venv; never override an already-activated venv)
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  if [[ -n "${TRADING_VENV:-}" && -f "${TRADING_VENV}/bin/activate" ]]; then
    # shellcheck disable=SC1090
    source "${TRADING_VENV}/bin/activate"
  elif [[ -f "$ROOT_DIR/../../.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/../../.venv/bin/activate"
  elif [[ -f "$ROOT_DIR/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
  fi
fi

# Postgres PRIMARY defaults (override via systemd Environment=...)
setup_postgres_env() {
  # Toggle backend
  export MINA_DB_BACKEND="${MINA_DB_BACKEND:-postgres}"
  # Use local socket/peer auth by default (no password) if the service runs as user 'mina'
  export MINA_PG_DSN="${MINA_PG_DSN:-postgresql:///trading}"
  # Schema-per-mode recommended: mina_live / mina_paper / mina_pump
  if [[ -n "${MINA_PG_SCHEMA:-}" ]]; then
    : # keep explicit
  elif [[ -n "${BOT_ROLE:-}" ]]; then
    export MINA_PG_SCHEMA="mina_${BOT_ROLE}"
  fi
}

is_alive() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" 2>/dev/null
}

pidfile_for() {
  local name="$1"
  echo "$PIDS_DIR/${name}.pid"
}

read_pid() {
  local pf
  pf="$(pidfile_for "$1")"
  if [[ -f "$pf" ]]; then
    cat "$pf" 2>/dev/null || true
  else
    echo ""
  fi
}

write_pid() {
  local name="$1"
  local pid="$2"
  echo "$pid" > "$(pidfile_for "$name")"
}

start_proc() {
  local name="$1"
  local logfile="$2"
  shift 2

  local existing
  existing="$(read_pid "$name")"
  if is_alive "$existing"; then
    echo "[RUNBOOK] $name already running (pid=$existing)"
    return 0
  fi

  echo "[RUNBOOK] Starting $name ..."
  (cd "$ROOT_DIR" && nohup "$@" >> "$logfile" 2>&1 & echo $! > "$(pidfile_for "$name")")
  sleep 0.5
  local newpid
  newpid="$(read_pid "$name")"
  if is_alive "$newpid"; then
    echo "[RUNBOOK] $name started (pid=$newpid) logs=$logfile"
  else
    echo "[RUNBOOK] ERROR: $name failed to start. Check logs: $logfile"
    return 1
  fi
}

stop_proc() {
  local name="$1"
  local pid
  pid="$(read_pid "$name")"

  if ! is_alive "$pid"; then
    echo "[RUNBOOK] $name not running"
    rm -f "$(pidfile_for "$name")" 2>/dev/null || true
    return 0
  fi

  echo "[RUNBOOK] Stopping $name (pid=$pid) ..."
  kill "$pid" 2>/dev/null || true

  # Wait up to 5s
  for _ in {1..10}; do
    if ! is_alive "$pid"; then
      echo "[RUNBOOK] $name stopped"
      rm -f "$(pidfile_for "$name")" 2>/dev/null || true
      return 0
    fi
    sleep 0.5
  done

  echo "[RUNBOOK] $name did not stop gracefully. Forcing..."
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$(pidfile_for "$name")" 2>/dev/null || true
}

status_proc() {
  local name="$1"
  local pid
  pid="$(read_pid "$name")"
  if is_alive "$pid"; then
    echo "[RUNBOOK] $name: RUNNING (pid=$pid)"
  else
    echo "[RUNBOOK] $name: STOPPED"
  fi
}
