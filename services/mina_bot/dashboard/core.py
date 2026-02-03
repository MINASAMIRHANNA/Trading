"""Dashboard core (shared state + helpers).

Batch-20: extracted from dashboard/app.py to support route modules.
"""

import os
import sys
import json
import math
import asyncio
import secrets
import requests
import subprocess
import re
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta


from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.auth_middleware import AuthMiddleware
from dashboard.constants import SESSION_COOKIE_NAME, SESSION_COOKIE_VALUE

# =========================================
# PATH FIX (so dashboard can import bot modules)
# =========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # .../crypto_bot/dashboard
PROJECT_ROOT = os.path.dirname(BASE_DIR)                       # .../crypto_bot
sys.path.append(PROJECT_ROOT)


# Bot imports (root level)
from database import DatabaseManager
from config import cfg
from binance.client import Client

from fetcher import fetch_klines, fetch_klines_window, fetch_klines_range
from indicators import ema, rsi, volume_spike, atr, adx
from pump_detector import detect_pre_pump

# Optional modules
try:
    from audit_lab import AuditLab  # should exist under dashboard/ or root (because PROJECT_ROOT is on sys.path)
except Exception:
    AuditLab = None

try:
    # if present (root level), gives rich project status + maintenance helpers
    from project_doctor import collect_status, run_maintenance
except Exception:
    collect_status = None
    run_maintenance = None

# =========================================
# INIT: DB + Templates + App
# =========================================
# Prefer single DB path (Zero-ENV): config.cfg decides bot_data.db
_DB_PATH = getattr(cfg, "DB_FILE", None)
if not _DB_PATH:
    cand = os.path.join(PROJECT_ROOT, "bot_data.db")
    if os.path.exists(cand):
        _DB_PATH = cand

db = DatabaseManager(db_file=_DB_PATH) if _DB_PATH else DatabaseManager()

lab = None
if AuditLab and not bool(getattr(cfg, "DISABLE_AUDIT_LAB", False)):
    try:
        lab = AuditLab()
    except Exception as e:
        print(f"[WARN] AuditLab disabled (init failed): {e}")
        lab = None

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _ms_now() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _row_to_dict(r) -> dict:
    """Convert sqlite3.Row / pg_compat.HybridRow / dict into a plain dict safely."""
    if r is None:
        return {}
    if isinstance(r, dict):
        return r

    # sqlite3.Row and many mapping-like rows support dict(row)
    try:
        return dict(r)  # type: ignore[arg-type]
    except Exception:
        pass

    # pg_compat.HybridRow: keys() + __getitem__
    if hasattr(r, "keys"):
        try:
            return {k: r[k] for k in r.keys()}  # type: ignore[index]
        except Exception:
            pass

    # fallback: (columns, values)
    cols = getattr(r, "columns", None)
    vals = getattr(r, "values", None)
    if cols and vals:
        try:
            return dict(zip(list(cols), list(vals)))
        except Exception:
            pass

    return {}

def _safe_last(x, default: float = 0.0) -> float:
    """Safely get the last numeric value from pandas Series/ndarray/list/scalar."""
    try:
        if x is None:
            return default
        # pandas Series / DataFrame column
        if hasattr(x, "iloc"):
            v = x.iloc[-1]
            return float(v) if v is not None else default
        # list/tuple
        if isinstance(x, (list, tuple)):
            return float(x[-1]) if x else default
        # numpy array
        try:
            import numpy as np  # local import (optional)
            if isinstance(x, np.ndarray):
                return float(x.flat[-1]) if x.size else default
        except Exception:
            pass
        # scalar
        return float(x)
    except Exception:
        return default


def _normalize_side(raw) -> str | None:
    """Normalize various encodings to BUY/SELL. Returns None for invalid/WAIT."""
    try:
        if raw is None:
            return None
        s = str(raw).strip().upper()
        if not s:
            return None
        if s in {"WAIT", "HOLD", "NONE", "0"}:
            return None
        if s in {"BUY", "LONG", "BULL", "1", "+1"}:
            return "BUY"
        if s in {"SELL", "SHORT", "BEAR", "-1"}:
            return "SELL"

        # token-based parsing (avoids bugs like 'STRONG_SHORT' containing 'LONG' in 'STRONG')
        tokens = [t for t in re.split(r"[^A-Z]+", s) if t]
        buy_tokens = {"BUY", "LONG", "BULL"}
        sell_tokens = {"SELL", "SHORT", "BEAR"}

        has_buy = any(t in buy_tokens for t in tokens)
        has_sell = any(t in sell_tokens for t in tokens)

        if has_buy and has_sell:
            return None
        if has_sell:
            return "SELL"
        if has_buy:
            return "BUY"
        return None
    except Exception:
        return None


def _positions_status_map() -> Dict[str, Dict[str, Any]]:
    """Map symbol -> position snapshot from execution_monitor (best-effort)."""
    try:
        raw = db.get_setting("positions_status")
        if not raw:
            return {}
        if isinstance(raw, dict):
            j = raw
        else:
            j = json.loads(raw) if isinstance(raw, str) else json.loads(str(raw))
        pos_list = j.get("positions") or []
        out: Dict[str, Dict[str, Any]] = {}
        for p in pos_list:
            sym = str(p.get("symbol") or "").upper().strip()
            if sym:
                out[sym] = p
        return out
    except Exception:
        return {}



def _execmon_age_seconds() -> int:
    """How old is the execution_monitor heartbeat."""
    hb = db.get_setting("execution_monitor_heartbeat")
    if not hb:
        return 999999
    try:
        t = datetime.fromisoformat(str(hb).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return int((now - t.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return 999999


def _public_price(symbol: str, market_type: str = "futures") -> float:
    """Best-effort public price fetch (no auth needed)."""
    symbol = str(symbol).upper().strip()
    mt = str(market_type or "futures").lower().strip()
    try:
        if mt == "spot":
            r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": symbol}, timeout=6)
            if r.ok:
                return float(r.json().get("price") or 0.0)
        else:
            # Futures: mark price via premiumIndex is usually best.
            r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", params={"symbol": symbol}, timeout=6)
            if r.ok:
                j = r.json()
                for k in ("markPrice", "indexPrice", "lastPrice"):
                    if j.get(k) is not None:
                        return float(j.get(k) or 0.0)
            # fallback
            r2 = requests.get("https://fapi.binance.com/fapi/v1/ticker/price", params={"symbol": symbol}, timeout=6)
            if r2.ok:
                return float(r2.json().get("price") or 0.0)
    except Exception:
        pass
    return 0.0

# =============================
# Batch-20 additions
# =============================

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

from dashboard import signals_workflow as _signals


def _ensure_signal_inbox_table():
    return _signals.ensure_signal_inbox_table(db)


def _extract_field(d: dict, *keys, default=None):
    return _signals.extract_field(d, *keys, default=default)


def _store_signal_inbox(data: dict) -> int:
    return _signals.store_signal_inbox(db, data)


def _fetch_signals(status: str = None, limit: int = 50):
    return _signals.fetch_signals(db, status=status, limit=limit)


def _get_signal_by_id(sid: int):
    return _signals.get_signal_by_id(db, int(sid))


def _update_signal_status(sid: int, status: str, note: str = None) -> bool:
    return _signals.update_signal_status(db, int(sid), status, note=note)


# Export everything (including _helpers) for route modules.
__all__ = [n for n in globals().keys() if not n.startswith('__')]
