# Trading Monorepo — Mina_Bot Primary Postgres (Schema-per-Mode)

This replacement switches **Mina_Bot** to use **PostgreSQL as the primary database**,
with **one database** (default: `trading`) and **one schema per mode**:

- `mina_live`
- `mina_paper`
- `mina_pump`

It keeps existing `/api/*` endpoints intact and the Gateway still serves the UI on `/`.

## What changed

- Added `services/mina_bot/pg_compat.py`: a small sqlite-compat layer backed by `psycopg`.
- Updated `services/mina_bot/database.py`: chooses Postgres backend when `MINA_DB_BACKEND=postgres`.
- Updated `services/mina_bot/dashboard/app.py`: reports schema size for Postgres.
- Updated Mina runbooks (`services/mina_bot/ops/run_*_stack.sh`): default to Postgres primary.
- Added migration script: `ops/postgres/migrate_sqlite_to_postgres.py`.

## Environment variables

You can override these via systemd `Environment=` lines.

- `MINA_DB_BACKEND` (default: `postgres`)
- `MINA_PG_DSN` (default: `postgresql:///trading`)  
  Uses local socket peer auth (no password) when the service user is the same as the PG role.
- `MINA_PG_SCHEMA` (default: `mina_<BOT_ROLE>`) where BOT_ROLE is `live|paper|pump`.

## One-time setup (schemas)

```bash
psql -d trading -c "CREATE SCHEMA IF NOT EXISTS mina_live;  CREATE SCHEMA IF NOT EXISTS mina_paper;  CREATE SCHEMA IF NOT EXISTS mina_pump;"
```

## Migration from SQLite (safe)

Stop Mina services first.

```bash
sudo systemctl stop mina-live.service mina-paper.service mina-pump.service || true

# Copy each old sqlite DB into its schema
python3 ops/postgres/migrate_sqlite_to_postgres.py --mode live  --sqlite services/mina_bot/bot_data_live.db  --schema mina_live
python3 ops/postgres/migrate_sqlite_to_postgres.py --mode paper --sqlite services/mina_bot/bot_data_paper.db --schema mina_paper
python3 ops/postgres/migrate_sqlite_to_postgres.py --mode pump  --sqlite services/mina_bot/bot_data_pump.db  --schema mina_pump
```

Then start services.

```bash
sudo systemctl start mina-live.service mina-paper.service mina-pump.service
```

## Quick tests

```bash
curl -sS http://127.0.0.1:8200/api/health/aggregate | jq

curl -sS http://127.0.0.1:8200/api/mina/live/system_health | jq
curl -sS http://127.0.0.1:8200/api/mina/paper/system_health | jq
curl -sS http://127.0.0.1:8200/api/mina/pump/system_health | jq

# Confirm data exists in Postgres
psql -d trading -c "SET search_path TO mina_live,public;  SELECT COUNT(*) AS trades FROM trades;"
```

## Rollback plan

If you need to rollback quickly:

1. `export MINA_DB_BACKEND=sqlite` in the systemd units (or remove the env line)
2. Restart the Mina services.

The original sqlite DB files are not deleted by this migration.
