-- Unified Postgres schema for the Trading monorepo (safe migration path).
--
-- This schema is intentionally minimal and focuses on *shared* cross-service
-- data first (settings / logs / events). Mina_Bot still uses SQLite as its
-- primary runtime DB for now, but can mirror into these tables.
--
-- Run:
--   psql -d trading -f ops/postgres/schema.sql

CREATE TABLE IF NOT EXISTS shared_settings (
  bot_role     TEXT NOT NULL,
  key          TEXT NOT NULL,
  value        TEXT,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (bot_role, key)
);

CREATE TABLE IF NOT EXISTS shared_events (
  id           BIGSERIAL PRIMARY KEY,
  bot_role     TEXT NOT NULL,
  event_type   TEXT NOT NULL,
  data         JSONB,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shared_events_role_time ON shared_events(bot_role, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shared_events_type_time ON shared_events(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS shared_logs (
  id            BIGSERIAL PRIMARY KEY,
  bot_role      TEXT NOT NULL,
  level         TEXT NOT NULL,
  msg           TEXT NOT NULL,
  source        TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at_ms BIGINT
);

CREATE INDEX IF NOT EXISTS idx_shared_logs_role_time ON shared_logs(bot_role, created_at DESC);


-- Gateway audit log
CREATE SCHEMA IF NOT EXISTS gateway;

CREATE TABLE IF NOT EXISTS gateway.audit_log (
  id            BIGSERIAL PRIMARY KEY,
  ts_utc         TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor         TEXT NOT NULL DEFAULT 'unknown',
  action        TEXT NOT NULL,
  role          TEXT,
  target_id     TEXT,
  trace_id      TEXT,
  request_json  JSONB,
  response_json JSONB,
  ok            BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_gateway_audit_ts ON gateway.audit_log(ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_gateway_audit_role ON gateway.audit_log(role);
CREATE INDEX IF NOT EXISTS idx_gateway_audit_action ON gateway.audit_log(action);
