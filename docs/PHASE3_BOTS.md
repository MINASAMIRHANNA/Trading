# Phase 3 — Mina bots inside Docker (Postgres PRIMARY)

Phase 3 runs the **bot processes** (live / paper / pump) and the **execution monitors** inside Docker.
Dashboards stay as the control surface, and Postgres stays the single source of truth.

## What this patch changes

- Updates `docker-compose.bots.yml` to:
  - force Postgres schema per role (`TRADING_PG_SCHEMA`)
  - set correct in-docker dashboard URLs (`DASHBOARD_URL`, `DASHBOARD_PUBLISH_URL`)
  - add `restart: unless-stopped`
  - make bots depend on their dashboards (prevents localhost mistakes)
- Adds helper scripts:
  - `scripts/phase3_apply_safe_defaults.sh` (sets **mode=PAPER** everywhere so no exchange orders)
  - `scripts/phase3_bots_up.sh`
  - `scripts/phase3_bots_stop.sh`
  - `scripts/phase3_bots_logs.sh`

## 1) Bring up base stack (Phase 2)

From repo root:

```bash
docker compose up -d --build
```

Sanity:

```bash
curl -s http://localhost:8001/api/db_ready
curl -s http://localhost:8000/api/db_ready
curl -s http://localhost:8002/api/db_ready
```

## 2) Apply safe defaults (recommended)

This ensures bots start in **PAPER** mode (no exchange orders) until you explicitly switch.

```bash
bash scripts/phase3_apply_safe_defaults.sh
```

## 3) Start bots + monitors

```bash
bash scripts/phase3_bots_up.sh
```

Tail logs:

```bash
bash scripts/phase3_bots_logs.sh
```

## 4) Verify activity (DB)

Check that bots are writing logs/events:

```bash
docker compose exec -T postgres psql -U trading -d trading -c "select count(*) from mina_live.logs;"
docker compose exec -T postgres psql -U trading -d trading -c "select count(*) from mina_pump.logs;"
```

Also check dashboards are still healthy:

```bash
curl -s http://localhost:8001/api/system_health
```

## 5) When ready: enable TESTNET trading (optional)

Either from the dashboard settings page, or via SQL:

```bash
docker compose exec -T postgres psql -U trading -d trading -c "insert into mina_live.settings(key,value,updated_at,source) values ('mode','TEST',now()::text,'manual') on conflict (key) do update set value=excluded.value, updated_at=excluded.updated_at, source=excluded.source;"
```

> **Important:** `mode=LIVE` will flip `USE_TESTNET=FALSE` and enable mainnet. Do that only when you’re 100% sure.

## 6) Stop/remove bots

```bash
bash scripts/phase3_bots_stop.sh
```
