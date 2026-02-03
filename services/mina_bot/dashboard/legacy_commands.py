"""
Legacy command handling (fallback).

This module keeps the pre-Repo SQL logic in a separate file so dashboard/app.py stays small.
It is used ONLY when the shared CommandsRepo path fails for any reason.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional
import json
import time
from datetime import datetime, timezone

from mina_core.db.repos.base import row_to_dict, safe_json_loads


def _ms_now() -> int:
    return int(time.time() * 1000)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _commands_cols(db) -> set[str]:
    """Return set of columns present in commands table (best-effort for sqlite/pg_compat)."""
    conn = getattr(db, "conn", None)
    if conn is None:
        return set()
    lock = getattr(db, "lock", None)
    # Works for sqlite and pg_compat (SELECT ... LIMIT 1)
    sql = "SELECT * FROM commands LIMIT 1"
    try:
        if lock is None:
            cur = conn.execute(sql)  # type: ignore
        else:
            with lock:
                cur = conn.execute(sql)  # type: ignore
        desc = getattr(cur, "description", None)
        if not desc:
            return set()
        return {str(c[0]) for c in desc}
    except Exception:
        return set()


def list_commands_legacy(db, *, status: str = "", cmd: str = "", limit: int = 50, since_ms: int = 0) -> Dict[str, Any]:
    lim = max(1, min(int(limit or 50), 500))
    st = str(status or "").strip().upper()
    cmdq = str(cmd or "").strip().upper()
    since = int(since_ms or 0)

    cols = _commands_cols(db)
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

    try:
        conn = getattr(db, "conn", None)
        if conn is None:
            return {"ok": False, "items": [], "error": "db.conn not available"}
        lock = getattr(db, "lock", None)
        if lock is None:
            rows = conn.execute(sql, tuple(params)).fetchall()  # type: ignore
        else:
            with lock:
                rows = conn.execute(sql, tuple(params)).fetchall()  # type: ignore

        out: List[Dict[str, Any]] = []
        for r in (rows or []):
            d = row_to_dict(r)
            try:
                if d.get("params") and isinstance(d.get("params"), str):
                    d["params"] = safe_json_loads(d.get("params"))
            except Exception:
                pass
            out.append(d)
        return {"ok": True, "items": out, "count": len(out)}
    except Exception as e:
        return {"ok": False, "items": [], "error": str(e)}


def insert_command_legacy(db, cmd: str, params: Optional[dict] = None, source: str = "dashboard") -> int:
    conn = getattr(db, "conn", None)
    if conn is None:
        raise RuntimeError("db.conn not available")
    lock = getattr(db, "lock", None)

    cols = _commands_cols(db)
    now = _utc_iso_now()
    now_ms = _ms_now()
    payload = params if isinstance(params, dict) else {}
    params_json = json.dumps(payload, ensure_ascii=False)

    # Support multiple schema versions
    fields: List[str] = ["cmd", "params"]
    values: List[Any] = [cmd, params_json]
    if "status" in cols:
        fields.append("status")
        values.append("PENDING")
    if "source" in cols:
        fields.append("source")
        values.append(source)
    if "created_at" in cols:
        fields.append("created_at")
        values.append(now)
    if "created_at_ms" in cols:
        fields.append("created_at_ms")
        values.append(int(now_ms))

    ph = ",".join(["?"] * len(fields))
    sql = f"INSERT INTO commands ({','.join(fields)}) VALUES ({ph})"

    if lock is None:
        cur = conn.execute(sql, tuple(values))  # type: ignore
        conn.commit()  # type: ignore
    else:
        with lock:
            cur = conn.execute(sql, tuple(values))  # type: ignore
            conn.commit()  # type: ignore
    try:
        return int(getattr(cur, "lastrowid", None) or 0)
    except Exception:
        return 0


def cancel_command_legacy(db, cmd_id: int) -> Tuple[int, str]:
    """Return (updated_rows, message)."""
    cid = int(cmd_id)
    cols = _commands_cols(db)
    conn = getattr(db, "conn", None)
    if conn is None:
        return 0, "db.conn not available"
    lock = getattr(db, "lock", None)

    now = _utc_iso_now()
    now_ms = _ms_now()

    try:
        if "status" not in cols:
            # Legacy: delete row
            sql = "DELETE FROM commands WHERE id=?"
            if lock is None:
                cur = conn.execute(sql, (cid,))  # type: ignore
                conn.commit()  # type: ignore
            else:
                with lock:
                    cur = conn.execute(sql, (cid,))  # type: ignore
                    conn.commit()  # type: ignore
            return int(getattr(cur, "rowcount", 0) or 0), "deleted (legacy schema)"

        set_cols: List[str] = ["status='CANCELLED'"]
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
            cur = conn.execute(sql, tuple(params))  # type: ignore
            conn.commit()  # type: ignore
        else:
            with lock:
                cur = conn.execute(sql, tuple(params))  # type: ignore
                conn.commit()  # type: ignore
        return int(getattr(cur, "rowcount", 0) or 0), "cancelled"
    except Exception as e:
        # best-effort rollback handled by pg_compat in postgres path
        try:
            conn.rollback()  # type: ignore
        except Exception:
            pass
        return 0, str(e)


def retry_command_legacy(db, cmd_id: int, *, source: str = "dashboard-retry") -> Tuple[int, str]:
    """Requeue same cmd/params as a new row and return new id."""
    cid = int(cmd_id)
    conn = getattr(db, "conn", None)
    if conn is None:
        raise RuntimeError("db.conn not available")
    lock = getattr(db, "lock", None)

    # Fetch old row
    if lock is None:
        r = conn.execute("SELECT * FROM commands WHERE id=?", (cid,)).fetchone()  # type: ignore
    else:
        with lock:
            r = conn.execute("SELECT * FROM commands WHERE id=?", (cid,)).fetchone()  # type: ignore
    if not r:
        raise RuntimeError("not found")

    d = row_to_dict(r)
    cmd = str(d.get("cmd") or "").strip().upper()
    params = d.get("params")
    if isinstance(params, str):
        params = safe_json_loads(params)
    if not isinstance(params, dict):
        params = {}

    new_id = insert_command_legacy(db, cmd, params=params, source=source)

    # Mark old row as CANCELLED to avoid re-processing (if schema supports)
    cols = _commands_cols(db)
    if "status" in cols:
        try:
            now = _utc_iso_now()
            now_ms = _ms_now()
            set_cols: List[str] = ["status='CANCELLED'"]
            p2: List[Any] = []
            if "last_error" in cols:
                set_cols.append("last_error=?")
                p2.append(f"retried as #{new_id}")
            if "done_at" in cols:
                set_cols.append("done_at=?")
                p2.append(now)
            if "done_at_ms" in cols:
                set_cols.append("done_at_ms=?")
                p2.append(int(now_ms))
            p2.append(cid)
            sql2 = f"UPDATE commands SET {', '.join(set_cols)} WHERE id=?"
            if lock is None:
                conn.execute(sql2, tuple(p2))  # type: ignore
                conn.commit()  # type: ignore
            else:
                with lock:
                    conn.execute(sql2, tuple(p2))  # type: ignore
                    conn.commit()  # type: ignore
        except Exception:
            try:
                conn.rollback()  # type: ignore
            except Exception:
                pass

    return int(new_id or 0), cmd
