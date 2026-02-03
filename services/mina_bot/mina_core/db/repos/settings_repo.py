from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from .base import row_to_dict


def _execute(conn, sql: str, params: Sequence[Any] = ()):  # noqa: ANN401
    if hasattr(conn, "execute"):
        return conn.execute(sql, tuple(params))
    cur = conn.cursor()
    cur.execute(sql, tuple(params))
    return cur


class SettingsRepo:
    """Backend-agnostic access to the `settings` + `settings_audit` tables.

    Used by the dashboard to avoid calling DatabaseManager methods directly.
    Works with SQLite connections and pg_compat CompatConn.
    """

    @staticmethod
    def ensure(conn, lock=None) -> None:
        try:
            from mina_core.db.ddl import ensure_settings_table, ensure_settings_audit_table

            if lock is None:
                ensure_settings_table(conn)
                ensure_settings_audit_table(conn)
            else:
                ensure_settings_table(conn, lock=lock)
                ensure_settings_audit_table(conn, lock=lock)
        except Exception:
            # Keep silent; callers have legacy fallback.
            pass

    @staticmethod
    def get(conn, key: str, lock=None) -> Optional[str]:
        key = str(key)
        SettingsRepo.ensure(conn, lock=lock)
        sql = "SELECT value FROM settings WHERE key=? LIMIT 1"
        try:
            if lock is None:
                row = _execute(conn, sql, (key,)).fetchone()
            else:
                with lock:
                    row = _execute(conn, sql, (key,)).fetchone()
            if not row:
                return None
            try:
                return row["value"]
            except Exception:
                return row[0]
        except Exception:
            return None

    @staticmethod
    def list_all(conn, lock=None) -> Dict[str, str]:
        SettingsRepo.ensure(conn, lock=lock)
        sql = "SELECT key, value FROM settings"
        try:
            if lock is None:
                rows = _execute(conn, sql).fetchall() or []
            else:
                with lock:
                    rows = _execute(conn, sql).fetchall() or []
            out: Dict[str, str] = {}
            for r in rows:
                d = row_to_dict(r)
                out[str(d.get("key"))] = str(d.get("value")) if d.get("value") is not None else ""
            return out
        except Exception:
            return {}

    @staticmethod
    def set(
        conn,
        key: str,
        value: Any,
        *,
        source: str = "system",
        bump_version: bool = True,
        audit: bool = True,
        lock=None,
    ) -> None:
        """Upsert a setting, optionally bumping version and writing audit."""
        key = str(key)
        new_val = str(value)
        SettingsRepo.ensure(conn, lock=lock)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        def _do():
            # Read old
            try:
                row = _execute(conn, "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                old_val = row["value"] if row else None
            except Exception:
                old_val = None

            # Prefer full upsert with version bump
            try:
                if bump_version:
                    _execute(
                        conn,
                        """
                        INSERT INTO settings(key,value,updated_at,version,source)
                        VALUES(?,?,?,?,?)
                        ON CONFLICT(key) DO UPDATE SET
                            value=excluded.value,
                            updated_at=excluded.updated_at,
                            version=COALESCE(settings.version,0)+1,
                            source=excluded.source
                        """,
                        (key, new_val, now, 0, source),
                    )
                else:
                    _execute(
                        conn,
                        """
                        INSERT INTO settings(key,value,updated_at,version,source)
                        VALUES(?,?,?,?,?)
                        ON CONFLICT(key) DO UPDATE SET
                            value=excluded.value,
                            updated_at=excluded.updated_at,
                            source=excluded.source
                        """,
                        (key, new_val, now, 0, source),
                    )
            except Exception:
                # Fallback to legacy replace
                _execute(conn, "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, new_val))

            if audit and (old_val != new_val):
                try:
                    _execute(
                        conn,
                        "INSERT INTO settings_audit (key, old_value, new_value, source, created_at) VALUES (?, ?, ?, ?, ?)",
                        (key, old_val, new_val, source, now),
                    )
                except Exception:
                    pass

            try:
                conn.commit()
            except Exception:
                pass

        if lock is None:
            _do()
        else:
            with lock:
                _do()
