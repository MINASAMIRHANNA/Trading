# PATCH NOTES: Phase E3 Unified Observability

Date: 2026-02-08 (UTC)  
Workspace: `/Users/minasamir/projects/Trading`  
Branch: `codex/nautilus-migration-phaseA`

## Summary
Phase E3 adds a single DB-backed observability view across all runtime roles (`paper/live/pump`) without any dashboard dependencies.

New API:
- `GET /api/unified/observability`
- `GET /api/unified/observability?roles=paper,live` (optional role filter)

The endpoint returns, per role:
- engine health (`online`, `last_seen`, `engine name/id`)
- kill-switch state + reason
- last claimed command
- last trade snapshot
- live-only gate summary (`state`, allowlist, limits, testnet flags)

## Gateway Changes

### New module
Added: `gateway/gateway_api/observability.py`

Key implementation points:
- reads Postgres directly using `psycopg` (`dict_row`)
- role/schema mapping:
  - `paper -> mina_paper`
  - `live -> mina_live`
  - `pump -> mina_pump`
- robust settings parsing from `{schema}.settings`:
  - heartbeat keys: `last_heartbeat`, `bot_heartbeat`, `execution_monitor_heartbeat`, etc.
  - engine identity keys: `engine_id`, `engine_name`, `engine`, `worker_id`, `service_name`
  - kill-switch keys
  - live gate keys (`live_gate_state`, `live_symbol_allowlist`, `live_limits`, ...)
- last claim from `{schema}.commands` with fallback ordering
- last trade from `{schema}.trades` with timestamp normalization

### Resilience behavior
Endpoint is non-fatal per role:
- if a schema/table/column is missing, role item is returned with safe defaults (`engine.online=false`) and a structured entry is appended under `errors[]`
- DB connect failure also returns safe fallback items and a top-level error entry instead of HTTP 500

### Route wiring
Updated: `gateway/gateway_api/main.py`
- registered `GET /api/unified/observability`
- optional `roles` query parsing with role validation
- execution delegated via `asyncio.to_thread(...)` to avoid blocking the event loop

## Auth / Security
- Route remains under `/api/*`, so existing `X-API-Key` gateway auth behavior is preserved exactly as implemented.

## Database / Compatibility
- No schema or migration changes were introduced in Phase E3.
- No dashboard services were reintroduced.
- Existing unified endpoints and prior smokes remain intact.

## Scripts
Added: `scripts/smoke_observability.sh`
- validates response contract and role coverage
- validates live gate presence for `live`
- validates role filter behavior (`roles=paper,live`)
- prints concise per-role summary

## Example response (trimmed)
```json
{
  "ok": true,
  "generated_at": "2026-02-08T13:35:29Z",
  "items": [
    {
      "role": "paper",
      "engine": {"name": "nautilus_paper_engine", "online": true, "last_seen_seconds": 16},
      "kill_switch": {"on": true, "reason": "smoke_unified"}
    },
    {
      "role": "live",
      "engine": {"name": "nautilus_live_engine", "online": true, "last_seen_seconds": 15},
      "live_gate": {"state": "CONFIRMED", "allowlist_count": 3}
    }
  ],
  "errors": []
}
```
