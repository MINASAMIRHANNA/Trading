# QA REPORT: Phase E4 QA Hardening

Date: 2026-02-08 (UTC)  
Workspace: `/Users/minasamir/projects/Trading`  
Branch: `codex/nautilus-migration-phaseA`  
Compose project: `trading_migration`

## Scope
Validated a deterministic QA pack for:
- consumer reliability evidence
- live safety gate evidence
- unified observability evidence

Also revalidated existing smokes remain passing.

## Commands Run
```bash
python -m compileall gateway services/mina_strategies services/nautilus_engine

export COMPOSE_PROJECT_NAME=trading_migration
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.bots.yml up -d --build

bash scripts/smoke_all.sh paper
bash scripts/smoke_all.sh live
bash scripts/smoke_all.sh pump
bash scripts/smoke_live_cutover.sh
bash scripts/smoke_pump_cutover.sh
bash scripts/smoke_consumer_reliability.sh
bash scripts/smoke_live_safety_gate.sh
bash scripts/smoke_observability.sh
bash scripts/smoke_qa_pack.sh
```

## Result Summary
- `compileall`: PASS
- `smoke_all.sh paper`: PASS
- `smoke_all.sh live`: PASS
- `smoke_all.sh pump`: PASS
- `smoke_live_cutover.sh`: PASS
- `smoke_pump_cutover.sh`: PASS
- `smoke_consumer_reliability.sh`: PASS
- `smoke_live_safety_gate.sh`: PASS
- `smoke_observability.sh`: PASS
- `smoke_qa_pack.sh`: PASS

## QA Pack Evidence Output
From `/tmp/qa_pack.log`:

```text
reliability_retry_cmd_id=89 final_status=DONE attempt_count=1 next_retry_at_ms=0 done_at_ms=1770558380257
reliability_dead_cmd_id=90 status=DEAD dead_lettered=t dead_letter_row_id=9
reliability_idempotency_signal_inbox_id=23 first_trade_id=16 duplicate_cmd_id=92 duplicate_ack_contains_idempotent=true
safety_gate_not_confirmed_signal_id=84 command_id=132 reason=LIVE_GATE_NOT_CONFIRMED
safety_confirmed_pass_signal_id=86 command_id=134 trade_id=22
safety_allowlist_block_signal_id=87 command_id=135 reason=SYMBOL_NOT_ALLOWED
safety_limits_block_signal_id=88 command_id=136 reason=LIMIT_MAX_OPEN_POSITIONS
safety_killswitch_open_reject_signal_id=90 command_id= reason=kill_switch_gateway_veto
safety_close_allowed_command_id=139 status=DONE
paper online=True last_claim=61/CLOSE_ALL_POSITIONS/DONE last_trade=3/SOLUSDT/CLOSED
live  online=True gate=CONFIRMED kill=False last_claim=138/KILL_SWITCH_ON/DONE last_trade=22/SOLUSDT/CLOSED
pump  online=True last_claim=93/CLOSE_ALL_POSITIONS/DONE last_trade=16/RELIAB7257/CLOSED
errors_count=0
qa_pack_log_path=/tmp/qa_pack.log
```

## Determinism / Non-determinism Notes
Observed sources of non-determinism before hardening:
- residual live gate/allowlist/kill-switch state from previous smokes
- asynchronous kill-switch command application timing

Mitigation implemented in `smoke_qa_pack.sh`:
- deterministic pre-run reset (disarm + allowlist clear + permissive limits + kill-switch OFF)
- deterministic post-run cleanup with same reset path (trap on exit)
- evidence sourced directly from DB IDs and command rows after scenario execution

Expected variant retained intentionally:
- kill-switch open may appear as gateway veto (`kill_switch_gateway_veto`) with empty command id, or as engine-side rejected command id; QA pack captures and reports the concrete observed path/reason.

## Final Status
Phase E4 QA hardening target achieved with deterministic evidence capture and recorded artifact output.
