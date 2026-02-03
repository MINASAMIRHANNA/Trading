#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="docker-compose.allinone.yml"


validate_compose_services() {
  local compose_file="$1"
  echo "\n== Compose sanity check =="
  echo "compose_file=$compose_file"
  local services
  services=$(docker compose -f "$compose_file" config --services | tr -d '\r' || true)
  if [ -z "$services" ]; then
    echo "ERROR: docker compose config returned no services. Are you in the Trading repo root?" >&2
    exit 1
  fi

  # Expect Mina bots/monitors/dashboards in All-in-one mode.
  local expected=(
    mina_paper_bot mina_paper_monitor
    mina_live_bot  mina_live_monitor
    mina_pump_bot  mina_pump_monitor
    mina_dashboard_paper mina_dashboard_live mina_dashboard_pump
  )

  local missing=0
  for s in "${expected[@]}"; do
    if ! echo "$services" | grep -qx "$s"; then
      echo "MISSING service: $s" >&2
      missing=1
    fi
  done

  if [ "$missing" -ne 0 ]; then
    echo "\nERROR: Your docker-compose.allinone.yml does not include Mina services." >&2
    echo "- Make sure you extracted the correct batch into ~/projects/Trading" >&2
    echo "- Then re-run: bash scripts/bootstrap_allinone.sh" >&2
    exit 1
  fi

  echo "OK: Mina services are present in compose."
}


echo "🚀 Trading All-in-one (Core + Bots)"
echo "Compose: ${COMPOSE_FILE}"
echo ""
echo "Options:"
echo "  --reset-volumes   (WARNING) removes Postgres volume"
echo ""

RESET_VOLUMES=0
if [[ "${1:-}" == "--reset-volumes" ]]; then
  RESET_VOLUMES=1
fi

validate_compose_services "$COMPOSE_FILE"

echo "🧹 Stopping stack..."
if [[ $RESET_VOLUMES -eq 1 ]]; then
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans
else
  docker compose -f "$COMPOSE_FILE" down --remove-orphans
fi

echo "🔧 Building images..."
docker compose -f "$COMPOSE_FILE" build

echo "▶️  Starting stack..."
docker compose -f "$COMPOSE_FILE" up -d

echo ""
echo "⏳ Waiting a bit for services..."
sleep 4

echo ""
echo "✅ Quick health checks:"
echo "- gateway   : http://localhost:8200/health"
echo "- brain_api : http://localhost:8100/health"
echo "- brain_ui  : http://localhost:5173/"
echo "- dashboards: paper=8000 live=8001 pump=8002"
echo ""
echo "Next:"
echo "  bash scripts/smoke_batch35.sh"
