# Unified Dashboard Button Contracts

All button writes are expected to go through Gateway `/api/*` only, with `trace_id` recorded in `gateway.ui_actions` (actor=`ui`) and role schema events/logs.

| Button ID | Page | UI selector (`data-testid`) | Expected API call | Expected DB side-effect | Expected event/log | Expected UI feedback | Idempotency |
|---|---|---|---|---|---|---|---|
| `ops.refresh` | Operations Center | `ops-refresh` | `GET /api/ops/status` + related reads | none (read-only) | none | status cards refreshed | n/a |
| `ops.restart.bot` | Operations Center | `ops-restart-bot` | `POST /api/ops/command` | insert `gateway.command_queue`, mirror to `mina_<role>.commands` | shared `OPS_COMMAND` audit | toast/message queued | dedupe by optional `dedupe_key` |
| `ops.restart.monitor` | Operations Center | `ops-restart-monitor` | `POST /api/ops/command` | insert command queue + role command mirror | shared `OPS_COMMAND` audit | toast/message queued | dedupe by optional `dedupe_key` |
| `ops.restart.pump` | Operations Center | `ops-restart-pump` | `POST /api/ops/command` | insert command queue + role command mirror | shared `OPS_COMMAND` audit | toast/message queued | dedupe by optional `dedupe_key` |
| `ops.kill.on` | Operations Center | `ops-kill-on` | `POST /api/unified/{role}/commands/kill_switch` | update role settings + command row | role event/log + audit | pill/status updates | idempotent by current setting |
| `ops.kill.off` | Operations Center | `ops-kill-off` | `POST /api/unified/{role}/commands/kill_switch` | update role settings + command row | role event/log + audit | pill/status updates | idempotent by current setting |
| `live.policy.save` | Operations Center | `live-policy-save` | `POST /api/live/safety_policy` | upsert `gateway.shared_settings` + `gateway.settings_audit` | audit row | success message | last-write-wins |
| `live.rollout.0` | Operations Center | `live-rollout-0` | `POST /api/live/rollout` | update rollout/caps settings in gateway | audit row | success message | idempotent per stage |
| `live.rollout.1` | Operations Center | `live-rollout-1` | `POST /api/live/rollout` | update rollout/caps settings in gateway | audit row | success message | idempotent per stage |
| `live.rollout.2` | Operations Center | `live-rollout-2` | `POST /api/live/rollout` | update rollout/caps settings in gateway | audit row | success message | idempotent per stage |
| `portfolio.apply` | Portfolio | `portfolio-apply` | `GET /api/portfolio/*` | none (read-only) | none | tables refreshed | n/a |
| `portfolio.export.db` | Portfolio | `portfolio-export-db` | `GET /api/portfolio/export.csv` | none (read-only export) | none | download starts | n/a |
| `portfolio.export.binance` | Portfolio | `portfolio-export-binance` | `GET /api/portfolio/binance/export.csv` | none (read-only export) | none | download starts | n/a |
| `portfolio.switch.live` | Portfolio | `portfolio-switch-live` | `POST /api/project/mode` | role settings updated by gateway | audit row | mode badge changes | idempotent per mode |
| `portfolio.switch.testnet` | Portfolio | `portfolio-switch-testnet` | `POST /api/project/mode` | role settings updated by gateway | audit row | mode badge changes | idempotent per mode |
| `portfolio.binance.connect` | Portfolio | `portfolio-binance-connect` | `POST /api/integrations/binance/connect` | upsert encrypted secret in `gateway.integration_secrets` | audit row | status badge/message | overwrite existing secret |
| `portfolio.binance.validate` | Portfolio | `portfolio-binance-validate` | `GET /api/integrations/binance/status?check=1` | none (read-only test) | none | status badge/message | n/a |
| `portfolio.binance.disconnect` | Portfolio | `portfolio-binance-disconnect` | `POST /api/integrations/binance/disconnect` | delete `gateway.integration_secrets` row | audit row | status badge/message | idempotent delete |
| `signals.refresh` | Signals | `signals-refresh` | `GET /api/unified/{role}/signals` | none (read-only) | none | table refresh | n/a |
| `signals.approve` | Signals | `signals-approve-<id>` | `POST /api/unified/{role}/signals/{id}/approve` | update `mina_<role>.signal_inbox.status=APPROVED`, insert `mina_<role>.commands` + command_queue row | role/shared events + audit | status updates immediately | keyed by `signal_id + trace_id` |
| `signals.reject` | Signals | `signals-reject-<id>` | `POST /api/unified/{role}/signals/{id}/reject` | update `mina_<role>.signal_inbox.status=REJECTED`, insert rejection row when available | role/shared events + audit | status updates immediately | keyed by `signal_id + trace_id` |
| `manual.execute.submit` | Manual Execution | `manual-exec-submit` | `POST /api/manual/execute` | insert `mina_<role>.commands`, insert `gateway.command_queue`, optional paper insert in `mina_paper.trades` | role events `MANUAL_EXECUTE_*` + logs + shared events | lifecycle `queued/acked/executed` + trade link when available | keyed by `trace_id` |
| `snapshot.run` | Historical Snapshot (UTC) | `snapshot-run` | `POST /api/snapshot` | insert role events `SNAPSHOT_REQUEST/RESULT`, optional `mina_<role>.snapshots_cache` | shared snapshot events + role log | summary cards + indicators table | keyed by `trace_id` |
| `snapshot.copy.json` | Historical Snapshot (UTC) | `snapshot-copy-json` | none (client clipboard) | none | none | copied message | n/a |
| `inspector.refresh` | Live Brain Inspector | `inspector-refresh` | `GET /api/brain/inspector/*` | none (read-only) | none | tables refreshed | n/a |
| `inspector.copy.trace` | Live Brain Inspector | `inspector-copy-trace` | none (client clipboard) | none | none | copied message | n/a |
| `learn.train` | Learn (Teach AI) | `learn-train` | `POST /api/learn/train` | update `brain.learning_runs`/settings tables (implementation dependent) | audit + role events | result message | keyed by role/window |
| `learn.promote` | Learn (Teach AI) | `learn-promote` | `POST /api/learn/promote` | update deployed version + settings audit | audit + role events | result message | role/version guarded |
| `learn.rollback` | Learn (Teach AI) | `learn-rollback` | `POST /api/learn/rollback` | revert deployed version + settings audit | audit + role events | result message | role/version guarded |
| `alerts.save` | Telegram Notifications | `alerts-save` | `POST /api/notifications/settings` | upsert notification keys in `gateway.shared_settings` | audit + optional settings event | saved message | last-write-wins |
| `alerts.test` | Telegram Notifications | `alerts-test` | `POST /api/notifications/test` | optional delivery log row (`gateway.alert_delivery_log`) | notifier event/log | success/failure message | n/a |
| `status.kill.on` | Status & Maintenance | `status-kill-on` | `POST /api/unified/paper/commands/kill_switch` | set paper kill-switch setting + queue command | role/shared events + audit | ON badge | idempotent by state |
| `status.kill.off` | Status & Maintenance | `status-kill-off` | `POST /api/unified/paper/commands/kill_switch` | clear paper kill-switch setting + queue command | role/shared events + audit | OFF badge | idempotent by state |
| `doctor.run.quick` | Project Doctor | `doctor-run-quick` | `GET /api/doctor/checks?run_tests=false` | none (read-only checks) | incident events may be emitted by backend | checks table refreshed | n/a |

## Verification Notes

- UI write actions must produce rows in `gateway.ui_actions` with `trace_id`, `page`, `button_id`, and request/response JSON.
- Ops/manual write actions must create a role command row (`mina_<role>.commands`) first, then command queue/audit rows.
- Manual execution progression is checked as `queued -> acked -> executed` from command status fields.
