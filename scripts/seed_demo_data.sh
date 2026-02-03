#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-all}"

PG_USER="${PG_USER:-trading}"
PG_DB="${PG_DB:-trading}"

schemas=()
case "$ROLE" in
  all|"") schemas=("mina_paper" "mina_live" "mina_pump");;
  paper) schemas=("mina_paper");;
  live)  schemas=("mina_live");;
  pump)  schemas=("mina_pump");;
  *)
    echo "Usage: $0 [all|paper|live|pump]" >&2
    exit 1
    ;;
esac

psql_exec() {
  docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 "$@"
}

epoch_ms() {
python3 - <<'PY'
import time
print(int(time.time()*1000))
PY
}

utc_now() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

echo "== Seeding Mina dashboards (Postgres) =="

for schema in "${schemas[@]}"; do
  echo "-- schema=${schema}"

  # 1) Migrate any *_ms columns that are still INTEGER -> BIGINT (legacy DBs)
  cols="$(psql_exec -t -A -c "
    SELECT table_name||'.'||column_name
    FROM information_schema.columns
    WHERE table_schema='${schema}'
      AND column_name LIKE '%\\_ms' ESCAPE '\\'
      AND data_type='integer'
    ORDER BY table_name, column_name;
  " 2>/dev/null || true)"

  if [[ -n "${cols// /}" ]]; then
    while IFS= read -r tc; do
      [[ -z "${tc}" ]] && continue
      t="${tc%%.*}"
      c="${tc#*.}"
      psql_exec -q -c "ALTER TABLE \"${schema}\".\"${t}\" ALTER COLUMN \"${c}\" TYPE BIGINT;" >/dev/null 2>&1 || true
    done <<< "${cols}"
  fi

  # 2) Ensure dedupe index exists (used by ON CONFLICT)
  psql_exec -q -c "CREATE UNIQUE INDEX IF NOT EXISTS ${schema}_idx_signal_inbox_dedupe_key ON \"${schema}\".signal_inbox(dedupe_key);" >/dev/null 2>&1 || true

  # 3) Insert a demo signal (idempotent by dedupe_key)
  NOW_UTC="$(utc_now)"
  NOW_MS="$(epoch_ms)"
  psql_exec -q -c "
    INSERT INTO \"${schema}\".signal_inbox
      (received_at, received_at_ms, source, status, symbol, timeframe, strategy, side, confidence, score, payload, note, dedupe_key)
    VALUES
      ('${NOW_UTC}', ${NOW_MS}, 'seed', 'RECEIVED', 'BTCUSDT', '1m', 'demo', 'BUY', 0.91, 0.91,
       '{"demo": true, "source": "seed_demo_data.sh"}', 'seed demo', 'seed:signal:btc')
    ON CONFLICT (dedupe_key) DO UPDATE
      SET received_at=EXCLUDED.received_at,
          received_at_ms=EXCLUDED.received_at_ms;
  " >/dev/null 2>&1 || true

  # 4) Insert demo trades (idempotent via WHERE NOT EXISTS)
  NOW_UTC="$(utc_now)"
  NOW_MS="$(epoch_ms)"

  psql_exec -q -c "
    INSERT INTO \"${schema}\".trades(
      symbol, signal, entry_price, quantity, stop_loss, take_profits,
      status, timestamp, timestamp_ms,
      pnl, confidence, market_type, strategy_tag, explain
    )
    SELECT
      'BTCUSDT','BUY', 42000.0, 0.01, 41000.0,
      '[{"price":43000,"qty":0.005},{"price":44000,"qty":0.005}]',
      'OPEN', '${NOW_UTC}', ${NOW_MS},
      0.0, 0.90,
      'futures','demo',
      'seed open trade'
    WHERE NOT EXISTS (
      SELECT 1 FROM \"${schema}\".trades
      WHERE strategy_tag='demo' AND explain='seed open trade' AND status='OPEN'
      LIMIT 1
    );
  " >/dev/null 2>&1 || true

  NOW_UTC="$(utc_now)"
  NOW_MS="$(epoch_ms)"

  psql_exec -q -c "
    INSERT INTO \"${schema}\".trades(
      symbol, signal, entry_price, quantity, stop_loss, take_profits,
      status, timestamp, timestamp_ms,
      close_price, close_reason, closed_at, closed_at_ms,
      pnl, confidence, market_type, strategy_tag, explain
    )
    SELECT
      'ETHUSDT','SELL', 2500.0, 0.05, 2550.0,
      '[{"price":2450,"qty":0.05}]',
      'CLOSED', '${NOW_UTC}', ${NOW_MS},
      2450.0, 'seed_take_profit', '${NOW_UTC}', ${NOW_MS},
      2.4, 0.87,
      'futures','demo',
      'seed closed trade'
    WHERE NOT EXISTS (
      SELECT 1 FROM \"${schema}\".trades
      WHERE strategy_tag='demo' AND close_reason='seed_take_profit' AND status='CLOSED'
      LIMIT 1
    );
  " >/dev/null 2>&1 || true

  echo ""
  psql_exec -c "SELECT count(*) AS trades_total FROM \"${schema}\".trades;" | tail -n +1
  psql_exec -c "SELECT count(*) AS closed_trades FROM \"${schema}\".trades WHERE status='CLOSED';" | tail -n +1
  psql_exec -c "SELECT count(*) AS signals_total FROM \"${schema}\".signal_inbox;" | tail -n +1
  echo ""
done

echo "== Seeding Brain analytics (SQLite in brain_api container) =="
curl -s -X POST "http://localhost:8100/api/demo/seed?n=25&symbol=BTCUSDT" | cat
echo ""
echo "== Done =="
echo "Try:"
echo "  curl -s http://localhost:8200/api/unified/overview | jq"
