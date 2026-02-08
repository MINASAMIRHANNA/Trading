# Trading Monorepo Runbook (Local Docker)

## Architecture
- Single UI/API control plane: `brain_ui -> gateway_api -> postgres/brain_api`.
- Mina role data is DB-backed in Postgres schemas: `mina_paper`, `mina_live`, `mina_pump`.
- Gateway control/audit schema remains `gateway`.
- Legacy `mina_dashboard_paper/live/pump` services are removed from runtime.

## Services & Ports
- Gateway API: [http://localhost:8200](http://localhost:8200)
- Brain API: [http://localhost:8100](http://localhost:8100)
- Brain UI: [http://localhost:5173](http://localhost:5173)
- Postgres: `localhost:5432` (container: `postgres:5432`)

## Start/Stop

```bash
export COMPOSE_PROJECT_NAME=trading_migration

docker compose -f docker-compose.yml down --remove-orphans

docker compose -f docker-compose.yml up -d --build

docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build

docker compose -f docker-compose.yml -f docker-compose.bots.yml ps
```

Stop:

```bash
docker compose -f docker-compose.yml -f docker-compose.bots.yml down --remove-orphans
```

## Quick Health Checks

```bash
curl -s http://localhost:8200/health
curl -s http://localhost:8200/api/unified/overview | head
curl -s http://localhost:8200/api/unified/paper/system_health | head
curl -s http://localhost:8200/api/unified/live/system_health | head
curl -s http://localhost:8200/api/unified/pump/system_health | head
```

## Demo Data (Seed)

```bash
bash scripts/seed_demo_data.sh paper
```

## Smoke Tests

```bash
bash scripts/smoke_unified.sh http://localhost:8200
bash scripts/smoke_all.sh paper
bash scripts/smoke_all.sh live
bash scripts/smoke_all.sh pump
bash scripts/smoke_signals.sh paper
bash scripts/smoke_actions.sh paper
```

## Optional Phase B Skeleton Services

```bash
docker compose -f docker-compose.yml -f docker-compose.bots.yml --profile phaseb up -d --build
```

This starts:
- `nautilus_engine` (paper simulation command executor)
- `mina_strategies` (strategy-only signal publisher via Gateway)

## Troubleshooting

### Gateway/UI issues

```bash
docker compose -f docker-compose.yml logs --tail=200 gateway_api
docker compose -f docker-compose.yml logs --tail=200 brain_ui
docker compose -f docker-compose.yml logs --tail=200 brain_api
```

### Bot/monitor issues

```bash
docker compose -f docker-compose.yml -f docker-compose.bots.yml logs --tail=200 mina_paper_bot
docker compose -f docker-compose.yml -f docker-compose.bots.yml logs --tail=200 mina_live_bot
docker compose -f docker-compose.yml -f docker-compose.bots.yml logs --tail=200 mina_pump_bot
docker compose -f docker-compose.yml -f docker-compose.bots.yml logs --tail=200 mina_paper_monitor
docker compose -f docker-compose.yml -f docker-compose.bots.yml logs --tail=200 mina_live_monitor
```

### DB schema sanity

```bash
docker compose -f docker-compose.yml exec -T postgres psql -U trading -d trading -c "\dn"
docker compose -f docker-compose.yml exec -T postgres psql -U trading -d trading -c "\dt mina_paper.*"
```

## Optional Gateway API Key

If `GATEWAY_API_KEY` is set, all `/api/*` endpoints require `X-API-Key`.
