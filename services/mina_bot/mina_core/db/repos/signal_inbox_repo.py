from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import row_to_dict, safe_json_loads

class SignalInboxRepo:
    """Canonical access layer for signal_inbox table.
    Works with SQLite and Postgres through pg_compat.
    """

    @staticmethod
    def ensure(conn, lock=None) -> None:
        # Prefer centralized DDL helper (consistent Postgres behavior)
        try:
            from mina_core.db.ddl import ensure_signal_inbox_table
            ensure_signal_inbox_table(conn, lock=lock)
            return
        except Exception:
            pass

        # Fallback (legacy DDL)
        ctx = lock if lock is not None else nullcontext()
        with ctx:
            try:
                conn.rollback()
            except Exception:
                pass
            cur = conn.cursor()
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
            try:
                cur.execute("CREATE INDEX IF NOT EXISTS idx_signal_inbox_status ON signal_inbox(status)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_signal_inbox_received ON signal_inbox(received_at_ms)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_signal_inbox_symbol ON signal_inbox(symbol)")
            except Exception:
                # Some backends may not support IF NOT EXISTS in index creation
                pass
            conn.commit()
        
    @staticmethod
    def insert(conn, lock, received_at: str, received_ms: int, status: str,
               symbol: Optional[str], timeframe: Optional[str], strategy: Optional[str], side: Optional[str],
               confidence: Optional[float], score: Optional[float], payload: Dict[str, Any]) -> int:
        SignalInboxRepo.ensure(conn, lock=lock)
        payload_s = json.dumps(payload, ensure_ascii=False)
        with lock:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO signal_inbox
                (received_at, received_at_ms, source, status, symbol, timeframe, strategy, side, confidence, score, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    received_at,
                    int(received_ms),
                    "bot",
                    str(status).upper(),
                    symbol,
                    timeframe,
                    strategy,
                    side,
                    float(confidence) if confidence is not None else None,
                    float(score) if score is not None else None,
                    payload_s,
                ),
            )
            conn.commit()
            # sqlite: lastrowid; pg_compat maps it similarly
            try:
                return int(cur.lastrowid)
            except Exception:
                # If backend doesn't expose lastrowid, try returning id via select
                try:
                    cur2 = conn.cursor()
                    cur2.execute("SELECT MAX(id) FROM signal_inbox")
                    v = cur2.fetchone()
                    return int(v[0]) if v and v[0] is not None else 0
                except Exception:
                    return 0

    @staticmethod
    def list(conn, lock, status: Optional[str], limit: int) -> List[Dict[str, Any]]:
        SignalInboxRepo.ensure(conn, lock=lock)
        limit = max(1, min(int(limit or 50), 500))
        with lock:
            cur = conn.cursor()
            if status:
                cur.execute(
                    "SELECT * FROM signal_inbox WHERE status=? ORDER BY received_at_ms DESC LIMIT ?",
                    (str(status).upper(), limit),
                )
            else:
                cur.execute("SELECT * FROM signal_inbox ORDER BY received_at_ms DESC LIMIT ?", (limit,))
            rows = cur.fetchall() or []

        out: List[Dict[str, Any]] = []
        for r in rows:
            rr = row_to_dict(r)
            rr["payload"] = safe_json_loads(rr.get("payload"), {})
            out.append(rr)
        return out

    @staticmethod
    def get(conn, lock, sid: int) -> Optional[Dict[str, Any]]:
        SignalInboxRepo.ensure(conn, lock=lock)
        with lock:
            cur = conn.cursor()
            cur.execute("SELECT * FROM signal_inbox WHERE id=?", (int(sid),))
            r = cur.fetchone()
        if not r:
            return None
        rr = row_to_dict(r)
        rr["payload"] = safe_json_loads(rr.get("payload"), {})
        return rr

    
    @staticmethod
    def counts(conn, lock) -> Dict[str, Any]:
        """Return dict with total + by_status."""
        SignalInboxRepo.ensure(conn, lock=lock)
        with lock:
            cur = conn.cursor()
            try:
                rows = cur.execute("SELECT status, COUNT(*) FROM signal_inbox GROUP BY status").fetchall()
                by_status = {str(r[0]): int(r[1]) for r in (rows or []) if r and r[0] is not None}
            except Exception:
                by_status = {}
            try:
                total_row = cur.execute("SELECT COUNT(*) FROM signal_inbox").fetchone()
                total = int(total_row[0]) if total_row and total_row[0] is not None else 0
            except Exception:
                total = 0
        return {"TOTAL": total, "by_status": by_status}

    @staticmethod
    def update_status(conn, lock, sid: int, fields_sql: str, values: tuple) -> None:
        SignalInboxRepo.ensure(conn, lock=lock)
        with lock:
            cur = conn.cursor()
            cur.execute(f"UPDATE signal_inbox SET {fields_sql} WHERE id=?", values)
            conn.commit()
