from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .base import row_to_dict, safe_json_loads


def _utc_iso_now() -> str:
    # Keep formatting consistent across services (UTC Z).
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms_now() -> int:
    return int(time.time() * 1000)


def _execute(conn, sql: str, params: Sequence[Any] = ()):
    """Execute SQL on both sqlite3 connection and pg_compat connection."""
    if hasattr(conn, "execute"):
        return conn.execute(sql, tuple(params))
    cur = conn.cursor()
    cur.execute(sql, tuple(params))
    return cur


class CommandsRepo:
    """Canonical access layer for the commands table.

    This repo is used by the dashboard Command Center endpoints.
    It is compatible with SQLite and Postgres via pg_compat.
    """

    @staticmethod
    def cols(conn, lock=None) -> Set[str]:
        # First attempt: SQLite-style PRAGMA (works on sqlite and some compat layers)
        try:
            if lock is None:
                rows = _execute(conn, "PRAGMA table_info(commands)").fetchall()
            else:
                with lock:
                    rows = _execute(conn, "PRAGMA table_info(commands)").fetchall()
            cols = {r[1] for r in (rows or []) if len(r) > 1}
            if cols:
                return cols
        except Exception:
            pass

        # Fallback: Postgres information_schema
        try:
            q = (
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND table_name='commands'"
            )
            if lock is None:
                rows = _execute(conn, q).fetchall()
            else:
                with lock:
                    rows = _execute(conn, q).fetchall()
            return {str(r[0]) for r in (rows or []) if len(r) > 0}
        except Exception:
            return set()

    @staticmethod
    def insert(
        conn,
        lock,
        cmd: str,
        params: Optional[dict] = None,
        source: str = "dashboard",
        trace_id: Optional[str] = None,
    ) -> int:
        cols = CommandsRepo.cols(conn, lock)
        now_iso = _utc_iso_now()
        now_ms = _ms_now()

        data: Dict[str, Any] = {}
        if "cmd" in cols:
            data["cmd"] = str(cmd).strip().upper()
        if "params" in cols:
            data["params"] = json.dumps(params or {}, ensure_ascii=False)
        if "status" in cols:
            data["status"] = "PENDING"
        if "created_at" in cols:
            data["created_at"] = now_iso
        if "created_at_ms" in cols:
            data["created_at_ms"] = int(now_ms)
        if "source" in cols:
            data["source"] = str(source)

        # Trace linking (Gateway forwards X-Trace-Id). Best-effort only.
        if trace_id and ("trace_id" in cols or "traceId" in cols):
            data["trace_id"] = str(trace_id)

        # Trace linking (best-effort).
        if trace_id and ("trace_id" in cols or "traceId" in cols):
            data["trace_id"] = str(trace_id)

        # Very old schema (no compatible cols)
        if not data:
            raise RuntimeError("commands table has no compatible columns")

        keys = list(data.keys())
        qmarks = ",".join(["?"] * len(keys))
        sql = f"INSERT INTO commands({','.join(keys)}) VALUES({qmarks})"

        if lock is None:
            cur = _execute(conn, sql, tuple(data[k] for k in keys))
            conn.commit()
            return int(getattr(cur, "lastrowid", 0) or 0)
        with lock:
            cur = _execute(conn, sql, tuple(data[k] for k in keys))
            conn.commit()
            return int(getattr(cur, "lastrowid", 0) or 0)

    @staticmethod
    def list(
        conn,
        lock,
        *,
        status: str = "",
        cmd: str = "",
        limit: int = 50,
        since_ms: int = 0,
    ) -> List[Dict[str, Any]]:
        lim = max(1, min(int(limit or 50), 500))
        st = str(status or "").strip().upper()
        cmdq = str(cmd or "").strip().upper()
        since = int(since_ms or 0)

        cols = CommandsRepo.cols(conn, lock)
        has_status = "status" in cols
        has_ms = "created_at_ms" in cols

        sql = "SELECT * FROM commands WHERE 1=1"
        params: List[Any] = []
        if cmdq:
            sql += " AND cmd=?"
            params.append(cmdq)
        if st and has_status:
            sql += " AND status=?"
            params.append(st)
        if since > 0 and has_ms:
            sql += " AND created_at_ms >= ?"
            params.append(since)

        order = "created_at_ms DESC" if has_ms else "id DESC"
        sql += f" ORDER BY {order} LIMIT ?"
        params.append(lim)

        if lock is None:
            rows = _execute(conn, sql, tuple(params)).fetchall()
        else:
            with lock:
                rows = _execute(conn, sql, tuple(params)).fetchall()

        out: List[Dict[str, Any]] = []
        for r in (rows or []):
            d = row_to_dict(r)
            d["params"] = safe_json_loads(d.get("params"), {})
            out.append(d)
        return out

    @staticmethod
    def get(conn, lock, cmd_id: int) -> Optional[Dict[str, Any]]:
        cid = int(cmd_id)
        if lock is None:
            r = _execute(conn, "SELECT * FROM commands WHERE id=?", (cid,)).fetchone()
        else:
            with lock:
                r = _execute(conn, "SELECT * FROM commands WHERE id=?", (cid,)).fetchone()
        if not r:
            return None
        d = row_to_dict(r)
        d["params"] = safe_json_loads(d.get("params"), {})
        return d

    @staticmethod
    def cancel(conn, lock, cmd_id: int) -> Tuple[int, str]:
        """Cancel a pending command. Returns (updated_rows, message)."""
        cid = int(cmd_id)
        cols = CommandsRepo.cols(conn, lock)

        # Legacy: delete row
        if "status" not in cols:
            sql = "DELETE FROM commands WHERE id=?"
            if lock is None:
                cur = _execute(conn, sql, (cid,))
                conn.commit()
            else:
                with lock:
                    cur = _execute(conn, sql, (cid,))
                    conn.commit()
            return int(getattr(cur, "rowcount", 0) or 0), "deleted (legacy schema)"

        now = _utc_iso_now()
        now_ms = _ms_now()

        set_cols = ["status='CANCELLED'"]
        params: List[Any] = []
        if "last_error" in cols:
            set_cols.append("last_error=?")
            params.append("cancelled by dashboard")
        if "done_at" in cols:
            set_cols.append("done_at=?")
            params.append(now)
        if "done_at_ms" in cols:
            set_cols.append("done_at_ms=?")
            params.append(int(now_ms))
        params.append(cid)

        sql = f"UPDATE commands SET {', '.join(set_cols)} WHERE id=? AND status='PENDING'"
        if lock is None:
            cur = _execute(conn, sql, tuple(params))
            conn.commit()
        else:
            with lock:
                cur = _execute(conn, sql, tuple(params))
                conn.commit()
        return int(getattr(cur, "rowcount", 0) or 0), "cancelled"

    @staticmethod
    def retry(conn, lock, cmd_id: int, *, source: str = "dashboard_retry") -> int:
        """Retry a command by re-queuing it as a new row. Returns new command id."""
        rec = CommandsRepo.get(conn, lock, cmd_id)
        if not rec:
            raise RuntimeError("not found")

        cmd = str(rec.get("cmd") or "").strip().upper()
        params = rec.get("params")
        if not isinstance(params, dict):
            params = safe_json_loads(params, {})

        return CommandsRepo.insert(conn, lock, cmd, params=params, source=source)
