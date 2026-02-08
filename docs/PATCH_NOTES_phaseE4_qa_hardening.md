# PATCH NOTES: Phase E4 QA Hardening

Date: 2026-02-08 (UTC)  
Workspace: `/Users/minasamir/projects/Trading`  
Branch: `codex/nautilus-migration-phaseA`

## Summary
Phase E4 adds a repeatable QA pack smoke that aggregates reliability, safety, and observability evidence into one deterministic run.

Added:
- `scripts/smoke_qa_pack.sh`

The new smoke:
- runs reliability validation (retry/backoff, dead-letter, idempotency)
- runs live safety validation (gate, allowlist, limits, kill-switch, close allowed)
- runs final unified observability snapshot
- prints concrete IDs/reason codes
- writes a run artifact log to `/tmp/qa_pack.log`

## Script Behavior
`smoke_qa_pack.sh` composes existing validated smokes and adds deterministic control-plane reset/cleanup around them.

### Deterministic setup
Before scenarios:
- live gate disarm (`/api/control/live/disarm`)
- live allowlist clear (`/api/control/live/allowlist`)
- permissive test limits set (`/api/control/live/limits`)
- live kill-switch forced OFF via command route

### Reliability evidence section
Parses IDs from `smoke_consumer_reliability.sh`, then queries Postgres for exact final fields:
- retry command: `final_status`, `attempt_count`, `next_retry_at_ms`, `done_at_ms`
- dead-letter command: `status`, `dead_lettered`, `dead_letter_row_id`
- idempotency: `signal_inbox_id`, first trade id, duplicate command id, idempotent ack flag

### Safety evidence section
Parses IDs/reasons from `smoke_live_safety_gate.sh`:
- gate-not-confirmed reject
- confirmed pass + trade id
- allowlist reject
- limits reject
- kill-switch open reject (engine reject or gateway veto path)
- close allowed under kill-switch

### Observability evidence section
Reads `/api/unified/observability` and prints:
- paper/live/pump summary lines (online, last claim, last trade)
- live gate + kill-switch in summary
- `errors_count`

### Cleanup
At exit (trap):
- disarm live gate
- clear allowlist
- reset permissive limits
- force live kill-switch OFF

## Compatibility / Safety
- No breaking changes.
- No DB schema changes.
- All timestamps/evidence remain UTC-based.
- Existing smoke suite remains intact and passing.
