#!/usr/bin/env bash
set -euo pipefail

DB_USER="${DB_USER:-trading}"
DB_NAME="${DB_NAME:-trading}"

echo "== Checking *_ms columns types in mina_* schemas =="
docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<'SQL'
WITH cols AS (
  SELECT n.nspname AS schema,
         c.relname AS table,
         a.attname AS column,
         pg_catalog.format_type(a.atttypid, a.atttypmod) AS type
  FROM pg_catalog.pg_attribute a
  JOIN pg_catalog.pg_class c ON a.attrelid = c.oid
  JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
  WHERE a.attnum > 0 AND NOT a.attisdropped
    AND n.nspname LIKE 'mina_%'
    AND a.attname LIKE '%\_ms' ESCAPE '\'
)
SELECT schema, table, column, type
FROM cols
ORDER BY schema, table, column;
SQL
echo "== Done =="
