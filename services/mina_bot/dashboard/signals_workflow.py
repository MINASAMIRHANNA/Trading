"""Signal inbox workflow (repo-first, legacy-safe).

Batch-18 goal:
- Move signal inbox + approve/reject workflow out of dashboard/app.py
- Keep behavior identical (repo-first + SQL fallback)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ms_now() -> int:
    """Epoch milliseconds.

    Note: If DB columns are int32 (legacy), ms will overflow. We migrate *_ms columns to BIGINT on Postgres,
    but keep a safety fallback to seconds if explicitly requested.
    """
    mode = (os.getenv('MINA_EPOCH_MS_MODE', 'ms') or 'ms').strip().lower()
    if mode in ('s', 'sec', 'second', 'seconds'):
        return int(datetime.now(timezone.utc).timestamp())
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def extract_field(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None and str(d[k]).strip() != "":
            return d[k]
    return default


def row_to_dict(r: Any) -> Dict[str, Any]:
    """Convert sqlite3.Row / pg_compat.HybridRow / dict into a plain dict safely."""
    if r is None:
        return {}
    if isinstance(r, dict):
        return r
    try:
        return dict(r)  # type: ignore[arg-type]
    except Exception:
        pass
    if hasattr(r, "keys"):
        try:
            return {k: r[k] for k in r.keys()}  # type: ignore[index]
        except Exception:
            pass
    cols = getattr(r, "columns", None)
    vals = getattr(r, "values", None)
    if cols and vals:
        try:
            return dict(zip(list(cols), list(vals)))
        except Exception:
            pass
    return {}


def ensure_signal_inbox_table(db: Any) -> None:
    """Ensure dashboard approval inbox exists."""
    # Repo-first
    try:
        from mina_core.db.repos.signal_inbox_repo import SignalInboxRepo

        SignalInboxRepo.ensure(db.conn, lock=db.lock)
        return
    except Exception:
        pass

    # Legacy fallback (kept for safety)
    with db.lock:
        try:
            db.conn.rollback()
        except Exception:
            pass
        cur = db.conn.cursor()
        cur.execute(
            """
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
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_signal_inbox_status ON signal_inbox(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_signal_inbox_received ON signal_inbox(received_at_ms)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_signal_inbox_symbol ON signal_inbox(symbol)")
        db.conn.commit()


def store_signal_inbox(db: Any, data: Dict[str, Any]) -> int:
    """Store an incoming signal/event into inbox."""
    ensure_signal_inbox_table(db)
    received_at = utc_iso_now()
    received_ms = ms_now()

    status = str(extract_field(data, "status", default="RECEIVED")).upper()
    if (data.get("execution_allowed") is False) and status in ("RECEIVED", "OK", "PUBLISHED", "SIGNAL"):
        status = "PENDING_APPROVAL"
    if status not in ("RECEIVED", "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXECUTED"):
        status = "RECEIVED"

    symbol = extract_field(data, "symbol", "pair", "s")
    strategy = extract_field(data, "strategy", "strategy_name")
    side = extract_field(data, "side", "signal", "direction")
    timeframe = extract_field(data, "timeframe", "tf")
    # Guard: ignore totally empty events
    if not symbol and not strategy and not side and status == "RECEIVED":
        return 0
    confidence = extract_field(data, "confidence", "conf", default=None)
    score = extract_field(data, "score", "pump_score", default=None)

    try:
        from mina_core.db.repos.signal_inbox_repo import SignalInboxRepo

        return SignalInboxRepo.insert(
            db.conn,
            db.lock,
            received_at=received_at,
            received_ms=received_ms,
            status=status,
            symbol=str(symbol) if symbol else None,
            timeframe=str(timeframe) if timeframe else None,
            strategy=str(strategy) if strategy else None,
            side=str(side) if side else None,
            confidence=float(confidence) if confidence is not None else None,
            score=float(score) if score is not None else None,
            payload=data,
        )
    except Exception:
        payload = json.dumps(data, ensure_ascii=False)
        with db.lock:
            cur = db.conn.cursor()
            cur.execute(
                """
                INSERT INTO signal_inbox
                (received_at, received_at_ms, source, status, symbol, timeframe, strategy, side, confidence, score, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    received_at,
                    received_ms,
                    "bot",
                    status,
                    str(symbol) if symbol else None,
                    str(timeframe) if timeframe else None,
                    str(strategy) if strategy else None,
                    str(side) if side else None,
                    float(confidence) if confidence is not None else None,
                    float(score) if score is not None else None,
                    payload,
                ),
            )
            db.conn.commit()
            try:
                return int(cur.lastrowid)
            except Exception:
                return 0


def fetch_signals(db: Any, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch signals for inbox UI."""
    try:
        from mina_core.db.repos.signal_inbox_repo import SignalInboxRepo

        return SignalInboxRepo.list(db.conn, db.lock, status=status, limit=limit)
    except Exception:
        ensure_signal_inbox_table(db)
        limit = max(1, min(int(limit or 50), 500))
        with db.lock:
            cur = db.conn.cursor()
            if status:
                cur.execute(
                    "SELECT * FROM signal_inbox WHERE status=? ORDER BY received_at_ms DESC LIMIT ?",
                    (str(status).upper(), limit),
                )
            else:
                cur.execute("SELECT * FROM signal_inbox ORDER BY received_at_ms DESC LIMIT ?", (limit,))
            rows = cur.fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            rr = row_to_dict(r)
            try:
                rr["payload"] = json.loads(rr.get("payload") or "{}")
            except Exception:
                rr["payload"] = {}
            out.append(rr)
        return out


def get_signal_by_id(db: Any, sid: int) -> Optional[Dict[str, Any]]:
    try:
        from mina_core.db.repos.signal_inbox_repo import SignalInboxRepo

        return SignalInboxRepo.get(db.conn, db.lock, sid=int(sid))
    except Exception:
        ensure_signal_inbox_table(db)
        with db.lock:
            cur = db.conn.cursor()
            cur.execute("SELECT * FROM signal_inbox WHERE id=?", (int(sid),))
            r = cur.fetchone()
        if not r:
            return None
        rr = row_to_dict(r)
        try:
            rr["payload"] = json.loads(rr.get("payload") or "{}")
        except Exception:
            rr["payload"] = {}
        return rr


def update_signal_status(db: Any, sid: int, status: str, note: Optional[str] = None) -> bool:
    """Update status/notes/timestamps for a signal inbox row."""
    ensure_signal_inbox_table(db)
    sid = int(sid)
    st = str(status).upper()
    ts = ms_now()

    fields = ["status=?"]
    vals: List[Any] = [st]

    if note is not None:
        fields.append("note=?")
        vals.append(str(note))
    if st == "APPROVED":
        fields.append("approved_at_ms=?")
        vals.append(ts)
    if st == "REJECTED":
        fields.append("rejected_at_ms=?")
        vals.append(ts)
    if st == "EXECUTED":
        fields.append("executed_at_ms=?")
        vals.append(ts)

    vals.append(sid)
    fields_sql = ", ".join(fields)

    try:
        from mina_core.db.repos.signal_inbox_repo import SignalInboxRepo

        SignalInboxRepo.update_status(db.conn, db.lock, sid=sid, fields_sql=fields_sql, values=tuple(vals))
        return True
    except Exception:
        with db.lock:
            cur = db.conn.cursor()
            cur.execute(f"UPDATE signal_inbox SET {fields_sql} WHERE id=?", tuple(vals))
            db.conn.commit()
        return True


def approve_signal(db: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    """Approve a signal and enqueue EXECUTE_SIGNAL. Mirrors dashboard/app.py behavior."""
    sid = data.get("id")
    note = str(data.get("note") or "")
    req_payload = data.get("payload")

    rec = None
    if sid:
        rec = get_signal_by_id(db, int(sid))
        if not rec:
            raise HTTPException(status_code=404, detail="Signal not found")

    merged: Dict[str, Any] = {}
    if rec and isinstance(rec.get("payload"), dict):
        merged.update(rec.get("payload") or {})
    if isinstance(req_payload, dict):
        merged.update(req_payload or {})

    # Fill missing essentials from DB row columns
    if rec:
        for k, v in {
            "symbol": rec.get("symbol"),
            "side": rec.get("side"),
            "strategy": rec.get("strategy"),
            "timeframe": rec.get("timeframe"),
            "confidence": rec.get("confidence"),
            "score": rec.get("score"),
        }.items():
            if v is None:
                continue
            if merged.get(k) in (None, ""):
                merged[k] = v

    # Normalize side for safety
    side_raw = str(merged.get("side") or merged.get("signal") or merged.get("direction") or "").strip().upper()
    if side_raw in ("BUY", "LONG"):
        merged["side"] = "LONG"
    elif side_raw in ("SELL", "SHORT"):
        merged["side"] = "SHORT"
    elif side_raw:
        merged["side"] = side_raw

    # Attach correlation ids
    if sid:
        merged["inbox_id"] = int(sid)
        merged["_dashboard_signal_id"] = int(sid)
    merged["_approved_by"] = "dashboard"
    merged["_approved_at"] = utc_iso_now()

    # Validate essentials
    symbol = str(merged.get("symbol") or "").strip().upper()
    # Normalize side (accept MANUAL_BUY / MANUAL_SELL etc.)
    side_raw = str(
        merged.get("side") or merged.get("signal") or merged.get("direction") or ""
    ).strip().upper()
    side_raw = side_raw.replace("-", "_").replace(" ", "_")

    if side_raw in ("BUY", "LONG", "MANUAL_BUY", "MANUAL_LONG"):
        side = "LONG"
        merged["side"] = "LONG"
    elif side_raw in ("SELL", "SHORT", "MANUAL_SELL", "MANUAL_SHORT"):
        side = "SHORT"
        merged["side"] = "SHORT"
    else:
        side = side_raw
        merged["side"] = side_raw
    if not symbol:
        raise HTTPException(status_code=400, detail="Missing symbol")
    if side not in ("LONG", "SHORT", "BUY", "SELL"):
        raise HTTPException(status_code=400, detail="Missing/invalid side")

    merged["symbol"] = symbol

    db.add_command("EXECUTE_SIGNAL", merged)
    if sid:
        update_signal_status(db, int(sid), "APPROVED", note=note)
    return {"status": "ok"}


def reject_signal(db: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    sid = data.get("id")
    reason = str(data.get("reason") or "Rejected by dashboard")
    note = str(data.get("note") or "")

    if not sid:
        raise HTTPException(status_code=400, detail="Missing id")

    rec = get_signal_by_id(db, int(sid))
    if not rec:
        raise HTTPException(status_code=404, detail="Signal not found")

    payload = rec.get("payload") or {}
    symbol = extract_field(payload, "symbol", "pair", "s", default=rec.get("symbol"))

    try:
        db.log_rejection(str(symbol) if symbol else "UNKNOWN", reason, 0, 0)
    except Exception:
        pass

    update_signal_status(db, int(sid), "REJECTED", note=note or reason)
    return {"status": "ok"}
