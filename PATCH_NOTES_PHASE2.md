# Postgres Reorg Phase 2 Patch

This patch makes the remaining SQLite-specific diagnostics and DB-introspection code safe under **Postgres PRIMARY**.

## What changed

### 1) `services/mina_bot/mina_core/utils/db_path.py`
- **Postgres PRIMARY** no longer writes/maintains `.db_path`, `.db_path_live`, `.db_path_paper`, `.db_path_pump`.
- In Postgres mode, `get_db_path()` returns a deterministic path (so legacy scripts still show a DB_FILE), but **no pin files are created**.

### 2) `services/mina_bot/tools/runtime_diag.py`
- Diagnostics are now **backend-aware**:
  - If `MINA_DB_BACKEND=postgres` it queries counts from `mina_<role>.*` tables in Postgres.
  - If not, it runs the old SQLite integrity/table checks.
- This prevents false failures like “DB file not found” when you are on Postgres.

### 3) `services/mina_bot/mina_core/db/database.py`
- `_table_columns()` now supports **Postgres** via `information_schema.columns` (instead of `PRAGMA table_info`).
- `_commands_has_status()` now works in Postgres (used by command reset logic).
- The "safe create_tables" wrapper skips `PRAGMA quick_check` and SQLite quarantine logic when Postgres is active.

## Expected results
- Running `docker compose exec mina_dashboard_live python tools/runtime_diag.py` should complete successfully on Postgres.
- `.db_path_*` files should stop re-appearing inside containers when `MINA_DB_BACKEND=postgres`.

