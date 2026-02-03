#!/usr/bin/env bash
set -euo pipefail

# Helper to read logs from a service that might live in docker-compose.bots.yml.
# Usage:
#   bash scripts/compose_logs.sh <service> [--tail=120] [-f]
#
# Example:
#   bash scripts/compose_logs.sh mina_paper_bot --tail=200
SERVICE="${1:-}"
if [[ -z "${SERVICE}" ]]; then
  echo "Usage: $0 <service> [docker compose logs args...]" >&2
  exit 1
fi
shift || true

docker compose -f docker-compose.yml -f docker-compose.bots.yml logs "$@" "${SERVICE}"
