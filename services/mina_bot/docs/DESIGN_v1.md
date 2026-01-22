# Mina_Bot v1.0 — Design Lock (Baseline)

> **Policy:** This repository is the official baseline for Mina_Bot. Future changes must be additive/backward-compatible and must not remove existing working features.

## 1) Architecture

### Roles (3 services)
All services share the same codebase and Core modules, and are selected via `BOT_ROLE`:

- `BOT_ROLE=pump` — **Pump Hunter** (v1 = signal-only, no trading execution allowed).
- `BOT_ROLE=live` — **Live Bot** (no paper trading; modes are TEST/LIVE only).
- `BOT_ROLE=paper` — **Paper Bot / Arena** (paper-only trading for evaluation/tournaments).

### Databases
Each role uses a separate SQLite DB file (role-aware pinning):

- `bot_data_pump.db`
- `bot_data_live.db`
- `bot_data_paper.db`

Pin files are stored in project root:

- `.db_path_pump`
- `.db_path_live`
- `.db_path_paper`

### Dashboards
v1 uses **3 dashboards** (separate processes/ports):

- Paper: `8000`
- Live: `8001`
- Pump: `8002`

## 2) Integration Contract (Events)

A generic append-only `events` table stores contract-compatible events:

- `SignalEvent`
- `TradeEvent`
- `HealthEvent`

All events include:

- `bot_id`, `bot_role`, `bot_version`, `ts_utc`

This allows future external analytics to consume events without coupling to internal DB tables.

## 3) Confidence System (v1)

Confidence is treated as:

- **Calibrated probability** (model score calibrated)
- **Gatekeeper meta-model** (second-stage pass/fail)
- **Veto filters** (spread/liquidity/volatility/OOD)
- **Dynamic thresholds** based on regime

## 4) Appendix A — Conservative Defaults (Seed)

### Live (conservative)
- `MAX_OPEN_TRADES=2`
- `DAILY_LOSS_LIMIT_PCT=2.0`
- `CONSECUTIVE_LOSSES_LIMIT=3`
- `RISK_PER_TRADE_PCT=0.35`
- `LEVERAGE_CAP=5`
- SL/TP (ATR): `SL_ATR_MULT=1.2`, `TP_ATR_MULT=1.8`
- Trailing: `TRAIL_ACTIVATION_ATR=1.0`, `TRAIL_CALLBACK_ATR=0.35`

### Paper (wider for learning)
- `MAX_OPEN_TRADES=6`
- `DAILY_LOSS_LIMIT_PCT=6.0`
- `RISK_PER_TRADE_PCT=0.6`
- `LEVERAGE_CAP=10`

### Pump (signal-only)
- `PUMP_MAX_SIGNALS_PER_DAY=40`
- `PUMP_MAX_SIGNALS_PER_SYMBOL_PER_DAY=2`
- `PUMP_MIN_GAP_BETWEEN_SIGNALS_MIN=10`
- `PUMP_CONF_MIN_PUBLISH=0.55`
- `PUMP_CONF_HIGH=0.70`

## 5) Run Scripts

Use scripts under `ops/`:

- `bash ops/run_paper_stack.sh`
- `bash ops/run_live_stack.sh`
- `bash ops/run_pump_stack.sh`

Each stack has corresponding `stop_*` and `status_*` scripts.
