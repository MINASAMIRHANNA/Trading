# Unified Postgres plan (safe migration)

This monorepo currently runs successfully using **SQLite per service**.
To avoid breaking the working system, we start with a **mirror/backfill** approach:

- Mina_Bot continues to use SQLite as its primary runtime database.
- When `TRADING_PG_DSN` is set, Mina_Bot also mirrors:
  - settings
  - logs
  - events
  into Postgres tables (`shared_*`).

This gives Gateway + Brain a single place to read cross-service data without having to
query each service, and it sets us up for a full migration later.

## Files

- `schema.sql` – creates `shared_settings`, `shared_logs`, `shared_events`.
- `migrate_sqlite_to_postgres.py` – one-time backfill from Mina_Bot sqlite DB files.

## Later phases

1. Switch Gateway aggregation to read from Postgres (optional).
2. Migrate high-value Mina_Bot tables (signals/trades/positions) from SQLite to Postgres.
3. Remove SQLite once all services are validated on Postgres.
