# PATCH NOTES: Phase E2 Live Safety Gate

Date: 2026-02-08 (UTC)
Workspace: `/Users/minasamir/projects/Trading`
Branch: `codex/nautilus-migration-phaseA`

## Summary
Phase E2 hardens live execution safety with a two-step gate and live-only runtime guardrails:
- control-plane endpoints for live gate arm/confirm/disarm
- live symbol allowlist and hard risk limits
- live engine enforcement before any OPEN command execution
- testnet-first behavior preserved by default

Kill-switch behavior is unchanged:
- OPEN commands are blocked when kill-switch is ON
- CLOSE commands remain allowed

## Gateway Changes
Updated: `gateway/gateway_api/main.py`

### 1) Live gate defaults (mina_live.settings, add-only)
New defaulted settings keys are now ensured for the live role:
- `live_gate_state` (`DISARMED|ARMED|CONFIRMED`, default `DISARMED`)
- `live_gate_armed_at_ms`
- `live_gate_confirmed_at_ms`
- `live_gate_token`
- `live_testnet_only` (default `1`)
- `live_allow_real_execution` (default `0`)
- `live_symbol_allowlist` (default `[]`)
- `live_limits` (default `{\"max_open_positions\":1,\"max_notional\":50,\"max_daily_loss\":10}`)
- `live_daily_pnl_key`

Defaults are ensured at startup and on control/status use without dropping or renaming any existing schema.

### 2) New control-plane endpoints
Added DB-backed endpoints:
- `GET /api/control/live/status`
- `POST /api/control/live/arm`
- `POST /api/control/live/confirm`
- `POST /api/control/live/disarm`
- `POST /api/control/live/allowlist`
- `POST /api/control/live/limits`

Behavior:
- `arm` rotates token and sets state `ARMED`
- `confirm` validates token and sets state `CONFIRMED`
- `disarm` resets state/token/timestamps
- allowlist/limits are normalized and persisted in live settings

Auth:
- endpoints are under `/api/*`, so existing `X-API-Key` gateway auth behavior is preserved.

### 3) Queueing behavior alignment
Live queue insertion now always enqueues DB commands for engine-side enforcement (instead of pre-blocking in the old gateway live opening precheck path). This keeps control-plane semantics and command lifecycle visibility consistent for live safety checks.

## Engine Changes
Updated: `services/nautilus_engine/nautilus_engine/main.py`

### 1) Live defaults ensure at startup
Engine now ensures live gate defaults on startup (live schema only), add-only via `settings` upsert-if-missing behavior.

### 2) Live open enforcement (role=live, opening commands)
Before executing live OPEN commands (`EXECUTE_SIGNAL` and other opening command types), engine enforces:
1. gate must be `CONFIRMED` (`LIVE_GATE_NOT_CONFIRMED`)
2. explicit execution enabled flags (`LIVE_EXECUTION_DISABLED`)
3. testnet/safe-mode requirement unless explicit real-execution override (`LIVE_TESTNET_ONLY` / `LIVE_REAL_EXECUTION_NOT_ALLOWED`)
4. symbol allowlist (`SYMBOL_NOT_ALLOWED`)
5. limits:
   - open positions cap (`LIMIT_MAX_OPEN_POSITIONS`)
   - intended notional cap (`LIMIT_MAX_NOTIONAL`)
   - daily loss cap (`LIMIT_MAX_DAILY_LOSS`)
   - conservative fallback for unavailable daily PnL (`LIMIT_DAILY_PNL_UNAVAILABLE`)

All rejections write structured `ack_meta` with `blocked` reason and a `live_guard` snapshot.

### 3) Close path remains safe
`CLOSE_ALL_POSITIONS` remains allowed even if:
- gate is `DISARMED`
- kill-switch is ON
- limits are exceeded

## Smoke/Test Updates

### Added
- `scripts/smoke_live_safety_gate.sh`
  - validates disarmed/armed/confirmed flow
  - validates allowlist and max-open-positions limit rejections
  - validates disarm re-block
  - validates kill-switch open-block + close-all-allowed

### Updated
- `scripts/smoke_live_cutover.sh`
  - now explicitly arms/confirms live gate
  - sets allowlist/limits for deterministic cutover behavior under Phase E2 guardrails

## Non-breaking / Constraints
- No table/column drops or renames
- UTC timestamps preserved
- Existing Phase D smoke suite remains passing
