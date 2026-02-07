"""DDL helpers for Mina_Bot.

Why
----
Mina_Bot historically duplicated small DDL snippets across modules (dashboard,
utilities, learning). With Postgres, a single failed SQL statement can leave the
current transaction in an aborted state, breaking subsequent statements until a
rollback.

This module centralizes **idempotent** DDL to reduce schema drift and make
bootstrap behaviour consistent across SQLite and Postgres (via `pg_compat`).

Design goals
------------
- **Idempotent**: safe to call multiple times.
- **Backend-agnostic**: works with sqlite3 connections and pg_compat CompatConn.
- **Small surface area**: only core tables that multiple modules rely on.

Notes
-----
- We keep the SQL as "sqlite-friendly" as possible; `pg_compat` translates a
  subset to Postgres.
- Callers that need strict behaviour can let exceptions bubble; most callers
  should wrap in try/except (dashboard already does).

"""

from __future__ import annotations

from typing import Iterable, Optional


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _rollback_quietly(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _commit_quietly(conn) -> None:
    try:
        conn.commit()
    except Exception:
        pass


def run_ddl(conn, statements: Iterable[str]) -> None:
    """Execute DDL statements.

    For Postgres, a previous failure can leave the transaction aborted, so we
    rollback first.
    """
    _rollback_quietly(conn)
    cur = None
    try:
        cur = conn.cursor()
        for s in statements:
            cur.execute(s)
        _commit_quietly(conn)
    except Exception:
        # Best effort: try to recover the connection for the next request.
        _rollback_quietly(conn)
        raise
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass


def _with_lock(lock: Optional[object]):
    """Return a context manager for `lock` when it supports `with`."""
    # We avoid importing contextlib here to keep this tiny.
    class _Noop:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    if lock is None:
        return _Noop()
    try:
        # If it's a proper context manager (threading.Lock), this works.
        lock.__enter__  # type: ignore[attr-defined]
        lock.__exit__  # type: ignore[attr-defined]
        return lock  # type: ignore[return-value]
    except Exception:
        return _Noop()


# ---------------------------------------------------------------------
# Core tables (used across multiple modules)
# ---------------------------------------------------------------------

_SETTINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT,
    version INTEGER DEFAULT 0,
    source TEXT
)
"""

_SETTINGS_AUDIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS settings_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT,
    old_value TEXT,
    new_value TEXT,
    source TEXT,
    created_at TEXT,
    created_at_ms INTEGER
)
"""

_SETTINGS_AUDIT_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_settings_audit_key_time ON settings_audit(key, created_at)",
]

_COMMANDS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cmd TEXT,
    params TEXT,
    trace_id TEXT,
    status TEXT DEFAULT 'PENDING',
    created_at TEXT,
    created_at_ms INTEGER,
    source TEXT,
    claimed_by TEXT,
    claimed_at TEXT,
    claimed_at_ms INTEGER,
    done_at TEXT,
    done_at_ms INTEGER,
    last_error TEXT,
    ack_meta TEXT
)
"""

_COMMANDS_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(status, created_at_ms)",
    "CREATE INDEX IF NOT EXISTS idx_commands_cmd_status ON commands(cmd, status)",
    "CREATE INDEX IF NOT EXISTS idx_commands_trace_id ON commands(trace_id)",
]

_LOGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT,
    msg TEXT,
    created_at TEXT,
    created_at_ms INTEGER,
    source TEXT
)
"""

_EQUITY_HISTORY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS equity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    timestamp_ms INTEGER,
    date_utc TEXT,
    total_balance REAL,
    unrealized_pnl REAL,
    source TEXT,
    meta TEXT
)
"""

_EQUITY_HISTORY_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_equity_time ON equity_history(timestamp_ms)",
    "CREATE INDEX IF NOT EXISTS idx_equity_date ON equity_history(date_utc)",
]

_REJECTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    reason TEXT,
    value REAL,
    threshold REAL,
    timestamp TEXT
)
"""


_SCHEMA_META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
)
"""


_LEARNING_STATS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS learning_stats_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_utc TEXT NOT NULL,
    strategy TEXT,
    exit_profile TEXT,
    trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    pnl_sum REAL DEFAULT 0.0,
    avg_pnl REAL DEFAULT 0.0,
    avg_confidence REAL DEFAULT 0.0,
    created_at TEXT
)
"""

_LEARNING_STATS_INDEX_SQL = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_learning_stats_daily_key ON learning_stats_daily(day_utc, strategy, exit_profile)",
]

_THRESHOLD_ADJ_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS threshold_adjustments_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_utc TEXT NOT NULL,
    strategy TEXT,
    exit_profile TEXT,
    trades INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    adjustment INTEGER DEFAULT 0,
    meta TEXT,
    created_at TEXT
)
"""

_THRESHOLD_ADJ_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_threshold_adjust_daily_day ON threshold_adjustments_daily(day_utc)",
]


# ---------------------------------------------------------------------
# Dashboard approvals table (signal inbox)
# ---------------------------------------------------------------------

_SIGNAL_INBOX_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signal_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT,
    received_at_ms INTEGER,
    source TEXT DEFAULT 'bot',
    status TEXT DEFAULT 'RECEIVED',
    symbol TEXT,
    timeframe TEXT,
    strategy TEXT,
    side TEXT,
    confidence REAL,
    score REAL,
    payload TEXT,
    approved_at_ms INTEGER,
    rejected_at_ms INTEGER,
    executed_at_ms INTEGER,
    note TEXT
)
"""

_SIGNAL_INBOX_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_signal_inbox_status ON signal_inbox(status)",
    "CREATE INDEX IF NOT EXISTS idx_signal_inbox_received ON signal_inbox(received_at_ms)",
    "CREATE INDEX IF NOT EXISTS idx_signal_inbox_symbol ON signal_inbox(symbol)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_inbox_dedupe_key ON signal_inbox(dedupe_key)",
]


# ---------------------------------------------------------------------
# Public ensure/bootstraps
# ---------------------------------------------------------------------


def ensure_schema_meta_table(conn, lock: Optional[object] = None) -> None:
    with _with_lock(lock):
        run_ddl(conn, [_SCHEMA_META_TABLE_SQL])


def set_schema_meta(conn, key: str, value: str, lock: Optional[object] = None) -> None:
    """Upsert a schema meta key/value."""
    key = str(key)
    val = str(value)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _with_lock(lock):
        # Try modern UPSERT (works in SQLite 3.24+ and Postgres).
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO schema_meta(key,value,updated_at)
                VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, val, now),
            )
            _commit_quietly(conn)
            try:
                cur.close()
            except Exception:
                pass
            return
        except Exception:
            _rollback_quietly(conn)
        # Fallback legacy insert/replace.
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO schema_meta(key,value,updated_at) VALUES (?,?,?)", (key, val, now))
        _commit_quietly(conn)
        try:
            cur.close()
        except Exception:
            pass


def get_schema_meta(conn, key: str, lock: Optional[object] = None) -> Optional[str]:
    key = str(key)
    with _with_lock(lock):
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM schema_meta WHERE key=? LIMIT 1", (key,))
            row = cur.fetchone()
            try:
                cur.close()
            except Exception:
                pass
            if not row:
                return None
            try:
                return row["value"]  # sqlite Row / HybridRow
            except Exception:
                return row[0]
        except Exception:
            return None


def list_schema_meta(conn, lock: Optional[object] = None) -> dict:
    with _with_lock(lock):
        try:
            cur = conn.cursor()
            cur.execute("SELECT key, value, updated_at FROM schema_meta")
            rows = cur.fetchall() or []
            try:
                cur.close()
            except Exception:
                pass
            out = {}
            for r in rows:
                try:
                    k = r["key"]; v = r["value"]
                except Exception:
                    k = r[0]; v = r[1]
                out[str(k)] = str(v) if v is not None else ""
            return out
        except Exception:
            return {}


def ensure_settings_table(conn, lock: Optional[object] = None) -> None:
    with _with_lock(lock):
        run_ddl(conn, [_SETTINGS_TABLE_SQL])


def ensure_settings_audit_table(conn, lock: Optional[object] = None) -> None:
    with _with_lock(lock):
        run_ddl(conn, [_SETTINGS_AUDIT_TABLE_SQL, *_SETTINGS_AUDIT_INDEX_SQL])


def ensure_commands_table(conn, lock: Optional[object] = None) -> None:
    with _with_lock(lock):
        # Create base table first.
        run_ddl(conn, [_COMMANDS_TABLE_SQL])
        # Additive schema updates (safe to ignore if already applied)
        try:
            run_ddl(conn, ["ALTER TABLE commands ADD COLUMN IF NOT EXISTS trace_id TEXT"])
        except Exception:
            # column may already exist
            pass
        # Indexes (trace_id index requires the column above)
        try:
            run_ddl(conn, _COMMANDS_INDEX_SQL)
        except Exception:
            pass


def ensure_logs_table(conn, lock: Optional[object] = None) -> None:
    with _with_lock(lock):
        run_ddl(conn, [_LOGS_TABLE_SQL])


def ensure_equity_history_table(conn, lock: Optional[object] = None) -> None:
    with _with_lock(lock):
        run_ddl(conn, [_EQUITY_HISTORY_TABLE_SQL, *_EQUITY_HISTORY_INDEX_SQL])


def ensure_rejections_table(conn, lock: Optional[object] = None) -> None:
    with _with_lock(lock):
        run_ddl(conn, [_REJECTIONS_TABLE_SQL])


def ensure_learning_tables(conn, lock: Optional[object] = None) -> None:
    with _with_lock(lock):
        run_ddl(
            conn,
            [
                _LEARNING_STATS_TABLE_SQL,
                *_LEARNING_STATS_INDEX_SQL,
                _THRESHOLD_ADJ_TABLE_SQL,
                *_THRESHOLD_ADJ_INDEX_SQL,
            ],
        )


def ensure_signal_inbox_table(conn, lock: Optional[object] = None) -> None:
    """Ensure the dashboard approvals table exists."""
    with _with_lock(lock):
        run_ddl(conn, [_SIGNAL_INBOX_TABLE_SQL, *_SIGNAL_INBOX_INDEX_SQL])


def bootstrap_core_tables(conn, lock: Optional[object] = None) -> None:
    """Bootstrap the small shared schema used by multiple services."""
    # Batch-11: ensure schema meta + stamp DDL version.
    ensure_schema_meta_table(conn, lock=lock)
    try:
        set_schema_meta(conn, 'mina_schema_version', '27', lock=lock)
        set_schema_meta(conn, 'mina_ddl_version', '27', lock=lock)
    except Exception:
        pass
    ensure_settings_table(conn, lock=lock)
    ensure_settings_audit_table(conn, lock=lock)
    ensure_commands_table(conn, lock=lock)
    ensure_logs_table(conn, lock=lock)
    ensure_equity_history_table(conn, lock=lock)
    ensure_rejections_table(conn, lock=lock)


def bootstrap_dashboard(conn, lock: Optional[object] = None) -> None:
    """Bootstrap tables required by the dashboard UI.

    Batch-5+: dashboards can safely bootstrap core shared tables too.
    This also ensures all ``*_ms`` columns are BIGINT in Postgres to avoid epoch-ms overflow.
    """
    bootstrap_core_tables(conn, lock=lock)
    ensure_learning_tables(conn, lock=lock)
    ensure_signal_inbox_table(conn, lock=lock)
    # Postgres safety: widen all *_ms columns (schema-wide) to BIGINT
    ensure_bigint_ms_columns(conn, lock=lock)


def ensure_bigint_ms_columns(conn, schema: Optional[str] = None, lock: Optional[object] = None) -> None:
    """Upgrade *_ms columns from INTEGER -> BIGINT in the target schema.

    Safe/idempotent; prevents 'integer out of range' when storing epoch-ms values.
    """
    # Resolve schema reliably (CompatConn exposes current_schema()).
    if schema is None:
        try:
            schema = conn.current_schema()  # type: ignore[attr-defined]
        except Exception:
            schema = None

    if not schema:
        # Fallback to Postgres current_schema()
        try:
            cur0 = conn.cursor()
            cur0.execute("SELECT current_schema()")
            schema = cur0.fetchone()[0]
        except Exception:
            schema = "public"

    # Lock (optional) for threaded startups
    if lock is not None:
        try:
            lock.acquire()
        except Exception:
            lock = None

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND column_name LIKE %s
              AND data_type = 'integer'
            ORDER BY table_name, column_name
            """,
            (schema, "%_ms"),
        )
        rows = cur.fetchall() or []
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return
    finally:
        if lock is not None:
            try:
                lock.release()
            except Exception:
                pass

    # Apply ALTERs (schema-qualified to avoid search_path surprises)
    for table, col in rows:
        try:
            cur.execute(f'ALTER TABLE "{schema}"."{table}" ALTER COLUMN "{col}" TYPE BIGINT')
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            continue

def required_tables() -> list[str]:
    """Tables that must exist for dashboards/monitors to operate."""
    return [
        "schema_meta",
        "settings",
        "settings_audit",
        "commands",
        "logs",
        "equity_history",
        "rejections",
        "learning_stats_daily",
        "threshold_adjustments_daily",
        "signal_inbox",
    ]
