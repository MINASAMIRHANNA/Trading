# Trading Monorepo Runbook (Local Docker)

## Services & Ports

- Brain API: `http://localhost:8100`
- Unified Gateway API: `http://localhost:8200`
- Unified UI (Vite): `http://localhost:5173`
- Mina Dashboards:
  - Paper: `http://localhost:8000`
  - Live:  `http://localhost:8001`
  - Pump:  `http://localhost:8002`
- Postgres: `localhost:5432` (inside docker: `postgres:5432`)

## Start/Stop

```bash
docker compose down --remove-orphans
docker compose up -d --build
docker compose ps
```

## Quick Health Checks

```bash
curl -s http://localhost:8200/health
curl -s http://localhost:8200/api/unified/overview | head
curl -sL http://localhost:8100/api/overview | head
```

## Demo Data (Seed)

Seed a role (recommended: paper) or all roles.

The seed script is idempotent and will also auto-upgrade legacy *_ms columns to BIGINT (if needed) and ensure the signal dedupe index exists:

```bash
bash scripts/seed_demo_data.sh paper
```

## Smoke Tests

- Stack health:
```bash
bash scripts/smoke_stack.sh
```

- Signals approve flow (Gateway → Dashboard), audited:
```bash
bash scripts/smoke_signals.sh paper
```

- Commands queue flow (audited):
```bash
bash scripts/smoke_actions.sh paper
```

- Audit endpoints:
```bash
bash scripts/smoke_audit.sh
```

- End-to-end bundle:
```bash
bash scripts/smoke_all.sh paper
```

## Troubleshooting

### UI shows blank / page crashes
Rebuild UI without cache:

```bash
docker compose build --no-cache brain_ui
docker compose up -d --force-recreate brain_ui
docker compose logs --tail=200 brain_ui
```

### Approve/Reject returns 500
This usually indicates a DB schema mismatch. Check that `*_ms` columns are BIGINT:

```bash
bash scripts/check_ms_types.sh
```

### Gateway shows upstream errors
Inspect logs:

```bash
docker compose logs --tail=200 gateway_api
docker compose logs --tail=200 mina_dashboard_paper
```


## Optional Gateway API Key

By default the Gateway does **not** require auth.  
To enable it, set an API key in your environment before `docker compose up`:

```bash
export GATEWAY_API_KEY="trading-dev"
docker compose up -d --build
```

When enabled:
- `/health` and docs remain public
- all `/api/*` endpoints require header `X-API-Key: $GATEWAY_API_KEY`

The UI will automatically send this header because `brain_ui` inherits `VITE_API_KEY` from `GATEWAY_API_KEY` in `docker-compose.yml`.

