import time
import json
from datetime import datetime, timezone

from binance.client import Client
from config import cfg
from database import DatabaseManager
from service_registry import register_service
from trading_executor import (
    ensure_stop_loss,
    ensure_hard_tp,
    ensure_trailing_stop,
    close_open_position,
    is_paper_trading,
    _get_symbol_precision,
    _format_val,
)


import os

class _NoPingClient(Client):
    """Disable spot ping() during init to avoid Spot-Testnet 502 killing futures modules."""
    def ping(self):
        try:
            return {}
        except Exception:
            return {}

def _futures_rest_base(use_testnet: bool) -> str:
    """Resolve futures REST base URL.

    Priority:
    1) Explicit DB-backed setting (BINANCE_FUTURES_REST_BASE)
    2) Optional OS env override (only if cfg.ALLOW_ENV_OVERRIDES=TRUE)
    3) Default by testnet
    """
    # 1) DB-backed explicit override (preferred)
    try:
        if hasattr(cfg, 'get_raw'):
            explicit = cfg.get_raw('BINANCE_FUTURES_REST_BASE') or cfg.get_raw('binance_futures_rest_base')
        else:
            explicit = None
        explicit = (explicit or '').strip()
        if explicit:
            return explicit.rstrip('/')
    except Exception:
        pass

    # 2) Backward-compat env override (disabled by default; keep Zero-ENV)
    try:
        if bool(getattr(cfg, 'ALLOW_ENV_OVERRIDES', False)):
            env = os.getenv('BINANCE_FUTURES_REST_BASE', '').strip()
            if env:
                return env.rstrip('/')
    except Exception:
        pass

    # 3) Default
    return 'https://demo-fapi.binance.com' if use_testnet else 'https://fapi.binance.com'


def _configure_futures_endpoints(c: Client, use_testnet: bool) -> None:

    rest_base = _futures_rest_base(use_testnet)
    candidates = {
        "FUTURES_URL": f"{rest_base}/fapi",
        "FUTURES_TESTNET_URL": f"{rest_base}/fapi",
        "FUTURES_DATA_URL": f"{rest_base}/futures/data",
        "FUTURES_TESTNET_DATA_URL": f"{rest_base}/futures/data",
    }
    for attr, url in candidates.items():
        if hasattr(c, attr):
            try:
                setattr(c, attr, url)
            except Exception:
                pass



class ExecutionMonitor:
    """
    Monitors real execution state from Binance Futures and syncs it with DB.

    Features:
    - Periodically checks active trades against Binance position info.
    - When a position is closed, closes the trade in DB and clears trade_state.
    - Periodic equity snapshots (UTC) for Snapshot/Audit features.
      Uses DatabaseManager.add_equity_snapshot() when available; falls back to
      direct insert into equity_history for older DB versions.

    Notes:
    - This monitor is intended for Futures. Spot tracking can be added separately.
    """

    CHECK_INTERVAL = 5  # seconds

    def __init__(self):
        self.db = DatabaseManager()

        api_key = getattr(cfg, "BINANCE_API_KEY", None) or ""
        api_secret = getattr(cfg, "BINANCE_API_SECRET", None) or ""
        self.client = _NoPingClient(api_key, api_secret, testnet=False)
        _configure_futures_endpoints(self.client, bool(getattr(cfg, "USE_TESTNET", True)))

        try:
            self.bot_role = str(getattr(cfg, "BOT_ROLE", "") or os.getenv("BOT_ROLE") or "").strip().lower()
        except Exception:
            self.bot_role = str(os.getenv("BOT_ROLE") or "").strip().lower()
        if self.bot_role == "arena":
            self.bot_role = "paper"
        self.is_pump = self.bot_role == "pump"
        try:
            register_service(
                "mina_monitor",
                role=self.bot_role or None,
                schema_name=getattr(self.db, "pg_schema", None),
                meta={"entrypoint": "services/mina_bot/execution_monitor.py"},
            )
        except Exception:
            pass

        self.running = True
        self._last_health_event_ms = 0

        # Restart request tracking (from dashboard)
        self._last_restart_req = None
        try:
            # Initialize from DB to avoid restart loops after container restarts
            self._last_restart_req = str(self.db.get_setting("restart_monitor_ack") or "").strip() or None
        except Exception:
            self._last_restart_req = None

        # Positions cache (for Project Doctor)
        self._positions_cache = {}  # symbol -> snapshot dict
        # Orphan position reconciliation / safe close confirmation
        self._missing_pos_count = {}  # symbol -> consecutive cycles with no position (avoid false closes)
        try:
            self.confirm_position_closed_cycles = int(float(self.db.get_setting("confirm_position_closed_cycles") or 3))
            if self.confirm_position_closed_cycles < 2:
                self.confirm_position_closed_cycles = 2
        except Exception:
            self.confirm_position_closed_cycles = 3

        try:
            self.sync_orphan_positions = str(self.db.get_setting("sync_orphan_positions") or "TRUE").strip().upper() in ("1","TRUE","YES","ON","Y")
        except Exception:
            self.sync_orphan_positions = True

        try:
            self.orphan_sync_every_sec = int(float(self.db.get_setting("orphan_sync_every_sec") or 15))
            if self.orphan_sync_every_sec < 10:
                self.orphan_sync_every_sec = 10
        except Exception:
            self.orphan_sync_every_sec = 15
        self._last_orphan_sync_ts = 0.0


        # REST API metrics (rate limits / latency)
        self._api_metrics = {
            "updated_utc": None,
            "used_weight_1m": None,
            "last": {},
            "errors_total": 0,
            "rate_limit_hits": 0,
        }

        # Protection audit (orphan orders / missing protection)
        try:
            self.protection_audit_enabled = str(self.db.get_setting("protection_audit_enabled") or "TRUE").strip().upper() in ("1","TRUE","YES","ON","Y")
        except Exception:
            self.protection_audit_enabled = True
        try:
            self.protection_audit_every_sec = int(float(self.db.get_setting("protection_audit_every_sec") or 30))
            if self.protection_audit_every_sec < 5:
                self.protection_audit_every_sec = 5
        except Exception:
            self.protection_audit_every_sec = 30
        self._last_protection_audit_ts = 0.0


        # Snapshot controls (safe defaults if config values are missing)
        self.snapshot_enabled = bool(getattr(cfg, "SNAPSHOT_ENABLED", True))
        self.snapshot_every_sec = int(getattr(cfg, "EQUITY_SNAPSHOT_EVERY_SEC", 60))
        if self.snapshot_every_sec < 5:
            self.snapshot_every_sec = 5  # avoid excessive DB writes
        self.snapshot_retention_days = int(getattr(cfg, "SNAPSHOT_RETENTION_DAYS", 30))

        # Protection-order reconciliation (dashboard settings)
        # When enabled, we periodically ensure STOP_MARKET (and optional TP) orders exist on exchange
        # so positions stay protected even after restarts.
        try:
            self.ensure_protection_orders = str(self.db.get_setting("ensure_protection_orders") or "1").strip().upper() in ("1","TRUE","YES","ON","Y")
        except Exception:
            self.ensure_protection_orders = True
        try:
            self.ensure_protection_every_sec = int(float(self.db.get_setting("ensure_protection_every_sec") or 60))
            if self.ensure_protection_every_sec < 10:
                self.ensure_protection_every_sec = 10
        except Exception:
            self.ensure_protection_every_sec = 60
        self._last_ensure_ts_by_symbol = {}
        self._last_partial_remain_by_symbol = {}

        self._last_snapshot_ts = 0.0
        self._last_prune_ts = 0.0
        self._prune_every_sec = 6 * 3600  # safety net (daily_routine also prunes)

        # DB command polling (to drive dashboard/doctor buttons safely)
        self._last_cmd_poll_ts = 0.0
        try:
            self.cmd_poll_every_sec = int(float(self.db.get_setting("command_poll_every_sec") or 1))
            if self.cmd_poll_every_sec < 1:
                self.cmd_poll_every_sec = 1
        except Exception:
            self.cmd_poll_every_sec = 1


    def _reload_runtime_settings(self):
        """Reload frequently changed flags from DB (dashboard-controlled)."""
        try:
            self.ensure_protection_orders = str(self.db.get_setting("ensure_protection_orders") or "TRUE").strip().upper() in ("1","TRUE","YES","ON","Y")
        except Exception:
            pass
        try:
            v = int(float(self.db.get_setting("ensure_protection_every_sec") or self.ensure_protection_every_sec))
            if v < 10:
                v = 10
            self.ensure_protection_every_sec = v
        except Exception:
            pass
        try:
            self.protection_audit_enabled = str(self.db.get_setting("protection_audit_enabled") or "TRUE").strip().upper() in ("1","TRUE","YES","ON","Y")
        except Exception:
            pass
        try:
            v = int(float(self.db.get_setting("protection_audit_every_sec") or self.protection_audit_every_sec))
            if v < 5:
                v = 5
            self.protection_audit_every_sec = v
        except Exception:
            pass

    def stop(self):
        self.running = False


    def _claim_pending_commands_filtered(self, only_cmds, limit: int = 50, worker: str = "execmon"):
        """Best-effort filtered claim of commands from shared DB.

        We intentionally claim ONLY the commands owned by execution_monitor,
        so main.py will not consume them (and vice versa).

        Returns list of (id, cmd, params_json_text).
        """
        try:
            lim = int(limit)
        except Exception:
            lim = 50
        if lim <= 0:
            lim = 50

        cmd_list = []
        for c in (only_cmds or []):
            s = str(c or '').strip().upper()
            if s:
                cmd_list.append(s)
        if not cmd_list:
            return []

        try:
            db = self.db
            lock = getattr(db, 'lock', None)
            conn = getattr(db, 'conn', None)
            if conn is None:
                return []

            def _do_claim():
                now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
                now_ms = int(time.time() * 1000)
                try:
                    conn.execute('BEGIN IMMEDIATE')
                except Exception:
                    pass

                cur = conn.cursor()
                placeholders = ','.join(['?'] * len(cmd_list))
                rows = cur.execute(
                    f"SELECT id, cmd, params FROM commands WHERE status='PENDING' AND UPPER(cmd) IN ({placeholders}) ORDER BY id ASC LIMIT ?",
                    tuple(cmd_list) + (lim,),
                ).fetchall()

                claimed = []
                for r in (rows or []):
                    try:
                        cid = int(r[0])
                        upd = cur.execute(
                            "UPDATE commands SET status='IN_PROGRESS', claimed_by=?, claimed_at=?, claimed_at_ms=? WHERE id=? AND status='PENDING'",
                            (str(worker), now_iso, int(now_ms), int(cid)),
                        )
                        if (upd.rowcount or 0) == 1:
                            claimed.append((r[0], r[1], r[2]))
                    except Exception:
                        continue

                conn.commit()
                return claimed

            if lock is not None:
                with lock:
                    return _do_claim()
            return _do_claim()

        except Exception:
            return []

    def _process_ops_commands(self, active_trades):
        """Consume ops/maintenance commands intended for execution_monitor."""
        try:
            now_ts = time.time()
            if (now_ts - float(self._last_cmd_poll_ts or 0.0)) < float(getattr(self, 'cmd_poll_every_sec', 1) or 1):
                return
            self._last_cmd_poll_ts = now_ts

            restart_requested = False
            commands = self._claim_pending_commands_filtered(
                only_cmds=(
                    'CHECK_PROTECTION_NOW',
                    'CLOSE_TRADE',
                    'CLOSE_ALL_POSITIONS',
                    'RESTART_MONITOR',
                    'MONITOR_RESTART',
                    'MONITOR_STOP',
                    'MONITOR_START',
                    'REDUCE_POSITION',
                    'UPDATE_SLTP',
                ),
                limit=50,
                worker='execution_monitor',
            )

            for cid, cmd, params_str in (commands or []):
                cmd_ok = True
                cmd_err = ''
                try:
                    params = json.loads(params_str) if params_str else {}
                    if not isinstance(params, dict):
                        params = {}

                    c = str(cmd or '').strip().upper()

                    if c == 'CHECK_PROTECTION_NOW':
                        # Convert the command into the existing "force" mechanism.
                        tok = str(int(time.time() * 1000))
                        try:
                            self.db.set_setting('protection_audit_force', tok, source='execution_monitor', bump_version=False, audit=False)
                        except Exception:
                            self.db.set_setting('protection_audit_force', tok, source='execution_monitor')
                        # Run immediately in this cycle.
                        self._maybe_protection_audit(active_trades)

                    elif c in ('RESTART_MONITOR', 'MONITOR_RESTART'):
                        restart_requested = True
                        cmd_ok = True

                    elif c == 'MONITOR_STOP':
                        print("[EXEC_MON] 🛑 STOP command received. Exiting now...")
                        restart_requested = True
                        cmd_ok = True

                    elif c == 'MONITOR_START':
                        # Already running; acknowledge command.
                        print("[EXEC_MON] ▶️ START command received (already running).")
                        cmd_ok = True

                    elif c == 'UPDATE_SLTP':
                        trade_id = params.get('trade_id') or params.get('id')
                        symbol = params.get('symbol')
                        stop_loss = params.get('stop_loss')
                        take_profits = params.get('take_profits')

                        if not symbol and trade_id:
                            try:
                                rec = self.db.get_trade_by_id(int(trade_id))
                                symbol = (rec or {}).get('symbol')
                            except Exception:
                                symbol = None

                        if not symbol:
                            raise ValueError("UPDATE_SLTP missing symbol/trade_id")

                        try:
                            # Update DB fields (safe for both sqlite/pg compat)
                            conn = getattr(self.db, 'conn', None)
                            lock = getattr(self.db, 'lock', None)
                            if conn is not None:
                                set_parts = []
                                vals = []
                                if stop_loss is not None:
                                    set_parts.append("stop_loss=?")
                                    vals.append(float(stop_loss))
                                if take_profits is not None:
                                    set_parts.append("take_profits=?")
                                    if isinstance(take_profits, (list, dict)):
                                        vals.append(json.dumps(take_profits))
                                    else:
                                        vals.append(take_profits)
                                if set_parts:
                                    vals.append(int(trade_id) if trade_id else symbol)
                                    where = "id=?" if trade_id else "symbol=?"
                                    sql = f"UPDATE trades SET {', '.join(set_parts)} WHERE {where}"
                                    if lock is None:
                                        conn.execute(sql, tuple(vals))
                                        conn.commit()
                                    else:
                                        with lock:
                                            conn.execute(sql, tuple(vals))
                                            conn.commit()
                            # Force protection audit to apply new SL/TP
                            tok = str(int(time.time() * 1000))
                            try:
                                self.db.set_setting('protection_audit_force', tok, source='execution_monitor', bump_version=False, audit=False)
                            except Exception:
                                pass
                        except Exception as e:
                            raise ValueError(f"UPDATE_SLTP failed: {e}")

                    elif c == 'REDUCE_POSITION':
                        trade_id = params.get('trade_id') or params.get('id')
                        symbol = params.get('symbol')
                        reduce_pct = params.get('reduce_pct') or params.get('percent') or params.get('pct')
                        reduce_qty = params.get('reduce_qty') or params.get('qty')

                        if not symbol and trade_id:
                            try:
                                rec = self.db.get_trade_by_id(int(trade_id))
                                symbol = (rec or {}).get('symbol')
                            except Exception:
                                symbol = None

                        if not symbol:
                            raise ValueError("REDUCE_POSITION missing symbol/trade_id")

                        # Determine current position size from exchange
                        pos_amt = 0.0
                        try:
                            positions = self.client.futures_position_information(symbol=symbol) or []
                            if not isinstance(positions, list):
                                positions = []
                            for p in positions:
                                amt = float(p.get("positionAmt", 0) or 0)
                                if abs(amt) > 0:
                                    pos_amt = amt
                                    break
                        except Exception:
                            pos_amt = 0.0

                        if abs(pos_amt) <= 0:
                            raise ValueError("No open position to reduce")

                        qty = 0.0
                        try:
                            if reduce_qty is not None:
                                qty = float(reduce_qty)
                            elif reduce_pct is not None:
                                pct = float(reduce_pct)
                                if pct > 1:
                                    pct = pct / 100.0
                                qty = abs(pos_amt) * max(0.0, min(1.0, pct))
                        except Exception:
                            qty = 0.0

                        if qty <= 0:
                            raise ValueError("Invalid reduce qty")

                        side = "SELL" if pos_amt > 0 else "BUY"

                        # Paper/test: adjust DB quantity only
                        if is_paper_trading():
                            try:
                                rec = self.db.get_active_trade(symbol)
                                if rec:
                                    cur_qty = float(rec.get("quantity") or 0)
                                    new_qty = max(0.0, cur_qty - qty)
                                    conn = getattr(self.db, 'conn', None)
                                    lock = getattr(self.db, 'lock', None)
                                    if conn is not None:
                                        if lock is None:
                                            conn.execute("UPDATE trades SET quantity=? WHERE id=?", (new_qty, int(rec.get("id"))))
                                            conn.commit()
                                        else:
                                            with lock:
                                                conn.execute("UPDATE trades SET quantity=? WHERE id=?", (new_qty, int(rec.get("id"))))
                                                conn.commit()
                                    if new_qty <= 0:
                                        self.db.close_trade(int(rec.get("id")), reason="REDUCE_POSITION_FULL", close_price=float(rec.get("current_price") or 0))
                            except Exception:
                                pass
                        else:
                            prec = _get_symbol_precision(symbol)
                            if prec:
                                qty = _format_val(float(qty), prec['step_size'], prec['qty_precision'])
                            self.client.futures_create_order(
                                symbol=symbol,
                                side=side,
                                type="MARKET",
                                quantity=float(qty),
                                reduceOnly=True,
                            )

                    elif c == 'CLOSE_TRADE':

                        trade_id = params.get('trade_id') or params.get('id')

                        symbol = params.get('symbol')

                        reason = params.get('reason') or 'MANUAL_CLOSE_TRADE'


                        # Resolve target trades

                        target_trades = []

                        if trade_id is not None:

                            t = self.db.get_trade_by_id(int(trade_id))

                            if not t:

                                raise Exception(f"trade_not_found:{trade_id}")

                            target_trades = [t]

                            symbol = t.get('symbol')

                        elif symbol:

                            # Close ALL open trades for this symbol (safer than guessing)

                            for t in self.db.get_open_trades():

                                if str(t.get('symbol', '')).upper() == str(symbol).upper():

                                    target_trades.append(t)

                        else:

                            raise Exception('missing_trade_id_or_symbol')


                        symbol = str(symbol).upper()


                        # Attempt to close the exchange position (idempotent if already flat)

                        close_resp = self.client.close_open_position(symbol, reason=reason)

                        avg_price = float(close_resp.get('avgPrice', 0) or 0.0) if isinstance(close_resp, dict) else 0.0

                        close_price = avg_price if avg_price > 0 else (self._get_last_price(symbol) or 0.0)


                        # Finalize DB trades

                        for t in target_trades:

                            tid = int(t.get('id'))

                            self.db.close_trade(

                                tid,

                                reason=reason,

                                close_price=close_price,

                                exit_explain={

                                    'source': 'manual',

                                    'cmd': 'CLOSE_TRADE',

                                    'symbol': symbol,

                                    'command_id': cmd_id,

                                },

                            )


                        cmd_ok = True

                        cmd_err = ''


                    elif c == 'CLOSE_ALL_POSITIONS':


                        reason = str(params.get('reason') or 'MANUAL_CLOSE_ALL_POSITIONS').strip() or 'MANUAL_CLOSE_ALL_POSITIONS'



                        # Collect symbols from exchange + DB OPEN futures trades


                        symbols = set()


                        open_trades = []


                        try:


                            open_trades = self.db.get_open_trades() or []


                        except Exception:


                            open_trades = active_trades or []



                        # 1) Prefer exchange truth for futures positions


                        try:


                            pos_all = self._api_call('positions_all', self.client.futures_position_information) or []


                            for p in (pos_all or []):


                                try:


                                    amt = float(p.get('positionAmt') or 0)


                                except Exception:


                                    amt = 0.0


                                if abs(amt) > 0.0:


                                    symbols.add(str(p.get('symbol') or '').strip().upper())


                        except Exception:


                            pass



                        # 2) Include DB open trades (useful for paper mode / no-exchange-position scenarios)


                        try:


                            for t in (open_trades or []):


                                if str(t.get('status') or '').upper() == 'OPEN' and str(t.get('market_type') or '').lower() == 'futures':


                                    symbols.add(str(t.get('symbol') or '').strip().upper())


                        except Exception:


                            pass



                        symbols = [s for s in symbols if s]


                        if not symbols:


                            try:


                                self._set_ack_meta(int(cid), {'note': 'no_open_positions'})


                            except Exception:


                                pass


                        else:


                            # Group open trades by symbol for DB finalization


                            by_symbol = {}


                            for t in (open_trades or []):


                                if str(t.get('status') or '').upper() != 'OPEN':


                                    continue


                                sym = str(t.get('symbol') or '').strip().upper()


                                if not sym:


                                    continue


                                by_symbol.setdefault(sym, []).append(t)



                            for sym in symbols:


                                close_price = 0.0


                                # Try to close the exchange position first (best-effort). Even if there's no position, we still finalize DB.


                                try:


                                    res = close_open_position(sym, execution_allowed=True)


                                    if isinstance(res, dict) and res.get('ok'):


                                        try:


                                            close_price = float(((res.get('result') or {}) or {}).get('avgPrice') or 0.0)


                                        except Exception:


                                            close_price = 0.0


                                except Exception:


                                    # Continue: we still attempt DB finalization below


                                    pass



                                if close_price <= 0.0:


                                    try:


                                        close_price = float(self._get_last_price(sym) or 0.0)


                                    except Exception:


                                        close_price = 0.0



                                # Finalize ALL open trades for this symbol


                                for t in (by_symbol.get(sym) or []):


                                    try:


                                        self.db.close_trade(int(t.get('id')), reason, close_price, exit_explain={'source': 'manual', 'cmd': 'CLOSE_ALL_POSITIONS', 'symbol': sym})


                                    except Exception:


                                        pass


                    else:


                        raise ValueError(f'Unsupported command for execution_monitor: {c}')

                except Exception as e:
                    cmd_ok = False
                    cmd_err = str(e)

                finally:
                    try:
                        self.db.mark_command_done(int(cid), ok=bool(cmd_ok), error=str(cmd_err or ''))
                    except Exception:
                        try:
                            self.db.mark_command_done(int(cid))
                        except Exception:
                            pass
            if restart_requested:
                print("[EXEC_MON] 🔁 Restart command received. Exiting now...")
                os._exit(3)
        except Exception:
            return

    # ======================================================
    # MAIN LOOP
    # ======================================================
    def run(self):
        print("🧭 Execution Monitor ONLINE")
        while self.running:
            try:
                # heartbeat for dashboard/health checks (do not bump config version)
                try:
                    self.db.set_setting(
                        "execution_monitor_heartbeat",
                        datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        source="execution_monitor",
                        bump_version=False,
                        audit=False,
                    )
                except Exception:
                    pass

                # reload dashboard-controlled flags
                self._reload_runtime_settings()

                # Restart request (from dashboard). Works best when monitor runs under a loop/supervisor.
                try:
                    req = str(self.db.get_setting("restart_monitor_req") or "").strip()
                    ack = str(self.db.get_setting("restart_monitor_ack") or "").strip()
                    if req and req != ack and req != str(self._last_restart_req or ""):
                        self._last_restart_req = req
                        print(f"[EXEC_MON] 🔁 Restart token detected: {req}")
                        try:
                            self.db.set_setting(
                                "restart_monitor_ack",
                                req,
                                source="execution_monitor",
                                bump_version=False,
                                audit=False,
                            )
                            print(f"[EXEC_MON] ✅ Restart token acked: {req}")
                        except Exception:
                            pass
                        # Clear the request so a supervisor restart doesn't loop forever.
                        try:
                            self.db.set_setting(
                                "restart_monitor_req",
                                "",
                                source="execution_monitor",
                                bump_version=False,
                                audit=False,
                            )
                            print(f"[EXEC_MON] 🧹 Restart token cleared: {req}")
                        except Exception:
                            pass
                        print("[EXEC_MON] 🔁 Restart requested from Dashboard. Exiting now...")
                        os._exit(3)
                except Exception:
                    pass

                if self.is_pump:
                    if not getattr(self, "_pump_warned", False):
                        print("[EXEC_MON] Pump role detected; heartbeat-only mode (no execution).")
                        self._pump_warned = True
                    time.sleep(self.CHECK_INTERVAL)
                    continue


                ts = datetime.now().strftime("%H:%M:%S")
                print(f"🔍 [{ts}] Starting Execution Check...")
                try:
                    mode_now_dbg = str(self.db.get_setting("mode") or "TEST").upper()
                except Exception:
                    mode_now_dbg = "TEST"
                print(f"🧭 [MONITOR] Mode={mode_now_dbg}")
                active_trades = self.db.get_all_active_trades() if hasattr(self.db, "get_all_active_trades") else []

                # If DB shows no OPEN trades but exchange still has open positions, reconcile them.
                if getattr(self, "sync_orphan_positions", True) and len(active_trades) == 0:
                    try:
                        synced = self._maybe_sync_orphan_positions(verbose=True)
                        if synced:
                            active_trades = self.db.get_all_active_trades() if hasattr(self.db, "get_all_active_trades") else []
                            print(f"🧩 [MONITOR] Synced/Reopened from exchange: {synced}")
                    except Exception as e:
                        print(f"[EXEC_MON] Orphan sync error: {e}")
                print(f"📊 [MONITOR] Active Trades in DB: {len(active_trades)}")

                # Consume ops commands intended for execution_monitor (buttons/doctor)
                try:
                    self._process_ops_commands(active_trades)
                except Exception as _e:
                    print(f"[EXEC_MON] Command processing error: {_e}")

                for trade in active_trades:
                    self._check_trade(trade, verbose=True)

                # Write positions snapshot for Project Doctor (best-effort)
                try:
                    ps = {
                        "updated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        "count": len(self._positions_cache),
                        "positions": list(self._positions_cache.values()),
                    }
                    self.db.set_setting("positions_status", json.dumps(ps), source="execution_monitor", bump_version=False, audit=False)
                except Exception:
                    pass

                # Also persist API metrics for Doctor (rate limits/latency)
                try:
                    self.db.set_setting("api_metrics_execmon", json.dumps(self._api_metrics), source="execution_monitor", bump_version=False, audit=False)
                except Exception:
                    pass

                # Protection audit (orphan/missing protection)
                self._maybe_protection_audit(active_trades)

                # Snapshot + housekeeping
                self._maybe_take_snapshot(active_trades_count=len(active_trades))
                self._maybe_prune_snapshots()

                # Equity (throttled) for live visibility
                try:
                    now_ts = time.time()
                    if (now_ts - float(getattr(self, '_last_equity_log_ts', 0.0) or 0.0)) >= 10:
                        wallet, unreal, equity = self._get_futures_equity()
                        self._last_equity_log_ts = now_ts
                        self._last_equity_vals = (wallet, unreal, equity)
                    else:
                        wallet, unreal, equity = getattr(self, '_last_equity_vals', (0.0, 0.0, 0.0))
                    if equity and float(equity) != 0.0:
                        print(f"💰 [EQUITY] Wallet: {float(wallet):.2f} USDT | Unrealized PnL: {float(unreal):+.2f} USDT | Total: {float(equity):.2f} USDT")
                except Exception:
                    pass

                
                # HealthEvent (v1 split contract) throttled
                try:
                    now_ms = int(time.time() * 1000)
                    if (now_ms - int(getattr(self, '_last_health_event_ms', 0) or 0)) >= 60000:
                        self._last_health_event_ms = now_ms
                        if hasattr(self.db, 'log_health_event'):
                            try:
                                mode_now = str(self.db.get_setting('mode') or 'TEST').upper()
                            except Exception:
                                mode_now = 'TEST'
                            try:
                                db_file = getattr(self.db, 'db_file', None)
                            except Exception:
                                db_file = None
                            self.db.log_health_event({
                                'component': 'execution_monitor',
                                'mode': mode_now,
                                'open_trades': len(active_trades) if isinstance(active_trades, list) else 0,
                                'db_file': db_file or '',
                            }, source='execution_monitor')
                except Exception:
                    pass
                print(f"😴 [{ts}] Cycle Complete. Sleeping...")
                time.sleep(self.CHECK_INTERVAL)
            except KeyboardInterrupt:
                print("[EXEC_MON] Stopped by user")
                break
            except Exception as e:
                print(f"[EXEC_MON] Error: {e}")
                time.sleep(self.CHECK_INTERVAL)

    # ======================================================
    # CHECK SINGLE TRADE
    # ======================================================
    def _check_trade(self, trade, verbose: bool = False):
        symbol = trade.get("symbol")
        trade_id = trade.get("id")
        if not symbol or trade_id is None:
            return

        try:
            positions = self._api_call("position_info", self.client.futures_position_information, symbol=symbol) or []
            if not isinstance(positions, list):
                positions = []

            pos_amt = 0.0
            pos_hit = None
            for p in positions:
                amt = float(p.get("positionAmt", 0) or 0)
                if abs(amt) > 0:
                    pos_amt = amt
                    pos_hit = p
                    break

            # cache positions snapshot for doctor page
            try:
                snap = None
                for p in positions or []:
                    amt = float(p.get("positionAmt", 0) or 0)
                    if abs(amt) > 0:
                        snap = {
                            "symbol": symbol,
                            "positionAmt": amt,
                            "entryPrice": float(p.get("entryPrice", 0) or 0),
                            "markPrice": float(p.get("markPrice", 0) or 0),
                            "unrealizedProfit": float(p.get("unRealizedProfit", 0) or p.get("unrealizedProfit", 0) or 0),
                            "leverage": p.get("leverage"),
                            "updated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        }
                        break
                if snap:
                    self._positions_cache[symbol] = snap
                else:
                    # no open position => remove cache if present
                    if symbol in self._positions_cache:
                        self._positions_cache.pop(symbol, None)
            except Exception:
                pass

            qty = float(trade.get("quantity", 0) or 0)
            # Reset false-close counter when position is present
            if abs(pos_amt) >= 1e-12:
                self._missing_pos_count.pop(symbol, None)

            # Auto-reconcile stuck closes: if a trade is already CLOSING but we can
            # confirm there is no position (and no open orders), finalize it without
            # waiting for the missing-position counter.
            try:
                if (str(trade.get("status") or "").upper() == "OPEN"
                        and str(trade.get("fsm_state") or "").upper() == "CLOSING"
                        and abs(pos_amt) < 1e-12
                        and str(trade.get("protection_status") or "").upper() == "NO_POSITION"):
                    grace_ms = int(self.cfg.get("reconcile_closing_grace_ms", 15000) or 15000)
                    since_ms = int(trade.get("fsm_state_since_ms") or trade.get("fsm_state_updated_ms") or 0)
                    now_ms = int(time.time() * 1000)
                    if since_ms and (now_ms - since_ms) >= grace_ms:
                        details = trade.get("protection_details") or {}
                        if isinstance(details, str):
                            try:
                                details = json.loads(details) if details else {}
                            except Exception:
                                details = {}
                        open_orders_total = 0
                        if isinstance(details, dict):
                            try:
                                open_orders_total = int(details.get("open_orders_total") or 0)
                            except Exception:
                                open_orders_total = 0
                        if open_orders_total == 0:
                            px = float(trade.get("current_price") or 0)
                            if px <= 0:
                                try:
                                    px = float((pos_hit or {}).get("markPrice", 0) or 0)
                                except Exception:
                                    px = 0
                            if px <= 0:
                                try:
                                    px = float(self._get_last_price(symbol) or 0)
                                except Exception:
                                    px = 0
                            self.db.close_trade(
                                int(trade_id),
                                reason="RECONCILE_CLOSING_NO_POSITION",
                                close_price=px,
                                exit_explain={"source": "execmon", "reconciled": True}
                            )
                            if verbose:
                                print(f"     🧹 Reconciled stuck CLOSING trade {trade_id} ({symbol}) at {px:g}")
                            return
            except Exception:
                pass

            if verbose:
                try:
                    side_txt = "LONG" if pos_amt > 0 else "SHORT"
                    size = abs(float(pos_amt))
                    entry = float((pos_hit or {}).get("entryPrice", 0) or 0)
                    mark = float((pos_hit or {}).get("markPrice", 0) or 0)
                    pnl = float((pos_hit or {}).get("unRealizedProfit", 0) or (pos_hit or {}).get("unrealizedProfit", 0) or 0)
                    if mark <= 0:
                        try:
                            mark = float(self._get_last_price(symbol) or 0)
                        except Exception:
                            pass
                    print(f"  -- Analyzing {symbol} (ID: {trade_id})")
                    if entry > 0:
                        print(f"     📍 Position: {side_txt} | Size: {size:g} | Entry: {entry:g} | Mark: {mark:g} | PnL: {pnl:+.2f}")
                    else:
                        print(f"     📍 Position: {side_txt} | Size: {size:g} | Mark: {mark:g} | PnL: {pnl:+.2f}")
                except Exception:
                    print(f"  -- Analyzing {symbol} (ID: {trade_id})")

            # ---------------- POSITION CLOSED ----------------
            if abs(pos_amt) < 1e-12:
                # Note: Binance may return [] for futures_position_information(symbol=...) when the position is flat.
                # We should still be able to reconcile DB, but with extra confirmation cycles to avoid API glitches.
                pos_info_missing = False
                try:
                    pos_list = positions if isinstance(positions, list) else []
                except Exception:
                    pos_list = []

                # Fallback: fetch all positions and filter by symbol (helps on some testnet quirks)
                if not pos_list:
                    try:
                        all_pos = self._api_call(lambda: self.client.futures_position_information(), "futures_position_information(all)")
                        pos_list = [p for p in (all_pos or []) if str(p.get("symbol", "")) == symbol]
                    except Exception:
                        pos_list = []

                if not pos_list:
                    pos_info_missing = True
                    if verbose:
                        print(f"     ⚠️ position_info empty for {symbol} — treating as flat (will confirm).")

                cnt = int(self._missing_pos_count.get(symbol, 0) or 0) + 1
                self._missing_pos_count[symbol] = cnt
                base_need = int(getattr(self, "confirm_position_closed_cycles", 3) or 3)
                need = base_need + (2 if pos_info_missing else 0)
                if verbose:
                    print(f"     ⚠️ No position detected for {symbol} (confirm {cnt}/{need})")
                if cnt < need:
                    return

                # confirmed
                self._missing_pos_count.pop(symbol, None)

                price = self._get_last_price(symbol)
                try:
                    self.db.close_trade(
                        trade_id,
                        reason="POSITION_CLOSED",
                        close_price=price,
                        explain={"source": "execution_monitor"},
                    )
                except Exception:
                    # Older DB versions may not support explain
                    self.db.close_trade(trade_id, reason="POSITION_CLOSED", close_price=price)



                # cleanup protective reduceOnly / closePosition orders to avoid affecting future trades
                try:
                    orders = self.client.futures_get_open_orders(symbol=symbol) or []
                    for o in orders:
                        try:
                            otype = str(o.get("type", "")).upper()
                            if otype not in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"):
                                continue
                            cp = o.get("closePosition")
                            ro = o.get("reduceOnly")
                            if (cp is not None and str(cp).lower() in ("true","1")) or (ro is not None and str(ro).lower() in ("true","1")):
                                oid = o.get("orderId")
                                if oid is not None:
                                    self.client.futures_cancel_order(symbol=symbol, orderId=oid)
                        except Exception:
                            continue
                except Exception:
                    pass

                # If the exchange is already flat, any remaining open orders for this symbol are orphans.
                # Cancel all to prevent a stale SL/TP from affecting the next trade.
                try:
                    self.client.futures_cancel_all_open_orders(symbol=symbol)
                except Exception:
                    pass

                # clear state by symbol (NOT trade_id)
                try:
                    self.db.clear_trade_state(symbol)
                except Exception:
                    pass

                print(f"✅ Trade closed: {symbol}")
                return


            # ---------------- ENSURE PROTECTION ORDERS ----------------
            try:
                mode_now = str(self.db.get_setting("mode") or "TEST").upper()
                if str(mode_now).upper() in ("LIVE","TEST"):
                    ensure_enabled = self.ensure_protection_orders
                    try:
                        ensure_enabled = str(self.db.get_setting("ensure_protection_orders") or ("1" if self.ensure_protection_orders else "0")).strip().upper() in ("1","TRUE","YES","ON","Y")
                    except Exception:
                        pass
                    if ensure_enabled:
                        now = time.time()
                        last = float(self._last_ensure_ts_by_symbol.get(symbol, 0.0) or 0.0)
                        every = int(self.ensure_protection_every_sec or 60)
                        try:
                            every = int(float(self.db.get_setting("ensure_protection_every_sec") or every))
                        except Exception:
                            pass
                        if every < 10:
                            every = 10
                        if (now - last) >= every:
                            self._last_ensure_ts_by_symbol[symbol] = now
                            side_txt = "LONG" if pos_amt > 0 else "SHORT"
                            sl = float(trade.get("stop_loss", 0) or 0)
                            if sl > 0:
                                if verbose:
                                    try:
                                        print(f"     🛡️ Syncing SL for {symbol} at target price: {sl:g}")
                                    except Exception:
                                        pass
                                ok_sl = ensure_stop_loss(symbol, side_txt, sl, execution_allowed=True)
                                if verbose:
                                    try:
                                        if ok_sl:
                                            print(f"     [EXEC] ✅ SL ensured for {symbol} at {sl:g}")
                                        else:
                                            print(f"     [EXEC] ⚠️ SL not set/updated for {symbol} (check logs)")
                                    except Exception:
                                        pass
                            try:
                                hard_tp = str(self.db.get_setting("hard_tp_enabled") or "0").strip().upper() in ("1","TRUE","YES","ON","Y")
                            except Exception:
                                hard_tp = False
                            if hard_tp:
                                tps = trade.get("take_profits") or []
                                if isinstance(tps, (list, tuple)) and len(tps) > 0:
                                    try:
                                        tp = float(tps[-1])
                                        if verbose:
                                            try:
                                                print(f"     🎯 Syncing TP for {symbol} at target price: {tp:g}")
                                            except Exception:
                                                pass
                                        ok_tp = ensure_hard_tp(symbol, side_txt, tp, execution_allowed=True)
                                        if verbose:
                                            try:
                                                if ok_tp:
                                                    print(f"     [EXEC] ✅ TP ensured for {symbol} at {tp:g}")
                                                else:
                                                    print(f"     [EXEC] ⚠️ TP not set/updated for {symbol} (check logs)")
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass

                            # -------- Exchange Trailing Stop (native) --------
                            try:
                                ex_trail_enabled = str(self.db.get_setting("exchange_trailing_enabled") or "0").strip().upper() in ("1","TRUE","YES","ON","Y")
                            except Exception:
                                ex_trail_enabled = False

                            if ex_trail_enabled:
                                # Appendix A: ATR-based trailing (preferred) if we have atr_entry.
                                # Fallback: ROI-based trailing.
                                act_roi = 0.01
                                cb = None
                                _using_atr = False
                                try:
                                    atr_entry = float(trade.get("atr_entry") or 0.0)
                                except Exception:
                                    atr_entry = 0.0

                                # Try ATR-based config
                                try:
                                    act_atr = float(self.db.get_setting("exchange_trailing_activation_atr") or self.db.get_setting("TRAIL_ACTIVATION_ATR") or 0.0)
                                    cb_atr = float(self.db.get_setting("exchange_trailing_callback_atr") or self.db.get_setting("TRAIL_CALLBACK_ATR") or 0.0)
                                except Exception:
                                    act_atr = 0.0
                                    cb_atr = 0.0

                                entry = float(trade.get("entry_price", 0) or 0)
                                if act_atr and cb_atr and atr_entry > 0 and entry > 0:
                                    # Activation ROI = (act_atr * ATR) / entry
                                    try:
                                        act_roi = max(0.0, min(1.0, float(act_atr) * float(atr_entry) / float(entry)))
                                        _using_atr = True
                                    except Exception:
                                        _using_atr = False

                                if not _using_atr:
                                    try:
                                        act_roi = float(self.db.get_setting("exchange_trailing_activation_roi") or 0.01)
                                    except Exception:
                                        act_roi = 0.01
                                if act_roi < 0:
                                    act_roi = 0.0
                                if act_roi > 1:
                                    act_roi = 1.0

                                if cb is None:
                                    try:
                                        cb = float(self.db.get_setting("exchange_trailing_callback_rate") or 0.3)
                                    except Exception:
                                        cb = 0.3

                                wt = str(self.db.get_setting("exchange_trailing_working_type") or "MARK_PRICE").upper().strip()
                                if wt not in ("MARK_PRICE", "CONTRACT_PRICE"):
                                    wt = "MARK_PRICE"

                                # entry may already be computed above
                                if entry > 0:
                                    # pick working price to align with workingType
                                    px = 0.0
                                    try:
                                        if wt == "MARK_PRICE":
                                            mp = self.client.futures_mark_price(symbol=symbol)
                                            px = float((mp or {}).get("markPrice") or 0.0)
                                        else:
                                            px = float(self._get_last_price(symbol) or 0.0)
                                    except Exception:
                                        px = float(self._get_last_price(symbol) or 0.0)

                                    if px > 0:
                                        # If using ATR-based callback, convert ATR → callbackRate % of price
                                        if _using_atr and cb_atr and atr_entry > 0:
                                            try:
                                                cb = float(cb_atr) * float(atr_entry) / float(px) * 100.0
                                            except Exception:
                                                pass

                                        if side_txt == "LONG":
                                            roi = (px / entry) - 1.0
                                        else:
                                            roi = (entry / px) - 1.0

                                        if roi >= act_roi:
                                            # Binance requires callbackRate typically in [0.1..5]
                                            try:
                                                cb = float(cb)
                                                if cb < 0.1:
                                                    cb = 0.1
                                                if cb > 5.0:
                                                    cb = 5.0
                                            except Exception:
                                                cb = 0.3
                                            ensure_trailing_stop(
                                                symbol,
                                                side_txt,
                                                abs(pos_amt),
                                                activation_price=px,
                                                callback_rate=cb,
                                                working_type=wt,
                                                execution_allowed=True,
                                            )
            except Exception:
                pass
            # ---------------- PARTIAL CLOSE DETECT ----------------
            if qty > 0:
                remain = abs(pos_amt)
                delta = qty - remain
                tol = max(1e-8, qty * 0.002)  # ignore tiny diffs (rounding/stepSize)
                if delta > tol:
                    last = self._last_partial_remain_by_symbol.get(symbol)
                    if last is None or abs(last - remain) > tol:
                        self._last_partial_remain_by_symbol[symbol] = remain
                        try:
                            self.db.log(
                                f"Partial close detected {symbol}: remaining {remain}",
                                level="INFO",
                            )
                        except Exception:
                            pass

        except Exception as e:
            print(f"[EXEC_MON] Check failed {symbol}: {e}")

    # ======================================================
    # PRICE FETCH
    # ======================================================
    def _get_last_price(self, symbol):
        try:
            mark = self.client.futures_mark_price(symbol=symbol)
            return float(mark.get("markPrice", 0) or 0)
        except Exception:
            return 0.0

    @staticmethod
    def _utc_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # ======================================================
    # SNAPSHOTS
    # ======================================================
    # ======================================================
    # API METRICS (Rate limits / latency)
    # ======================================================

    def _set_ack_meta(self, command_id: int, meta: dict) -> None:
        # Best-effort write to commands.ack_meta if the column exists.
        try:
            cid = int(command_id)
        except Exception:
            return
        try:
            payload = json.dumps(meta or {}, ensure_ascii=False)
        except Exception:
            payload = '{}'

        try:
            conn = getattr(self.db, 'conn', None)
            lock = getattr(self.db, 'lock', None)
            if conn is None:
                return

            def _do():
                try:
                    cur = conn.cursor()
                    cols = [r[1] for r in cur.execute('PRAGMA table_info(commands)').fetchall()]
                    if 'ack_meta' not in cols:
                        return
                    cur.execute('UPDATE commands SET ack_meta=? WHERE id=?', (payload, cid))
                    conn.commit()
                except Exception:
                    try:
                        conn.commit()
                    except Exception:
                        pass

            if lock is not None:
                with lock:
                    _do()
            else:
                _do()
        except Exception:
            return

    def _api_call(self, name: str, fn, *args, **kwargs):
        t0 = time.time()
        try:
            res = fn(*args, **kwargs)
            ok = True
            err = ""
        except Exception as e:
            res = None
            ok = False
            err = str(e)

        dt_ms = int((time.time() - t0) * 1000)
        weight = None
        try:
            hdrs = getattr(getattr(self.client, "response", None), "headers", {}) or {}
            w = hdrs.get("x-mbx-used-weight-1m") or hdrs.get("X-MBX-USED-WEIGHT-1M")
            if w is not None:
                weight = int(w)
        except Exception:
            weight = None

        # classify rate-limit style errors
        if not ok:
            self._api_metrics["errors_total"] = int(self._api_metrics.get("errors_total") or 0) + 1
            if "429" in err or "418" in err or "-1003" in err or "too many requests" in err.lower():
                self._api_metrics["rate_limit_hits"] = int(self._api_metrics.get("rate_limit_hits") or 0) + 1

        self._api_metrics["updated_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if weight is not None:
            self._api_metrics["used_weight_1m"] = weight
        self._api_metrics.setdefault("last", {})[name] = {
            "ok": bool(ok),
            "latency_ms": dt_ms,
            "used_weight_1m": weight,
            "err": err[:220] if err else "",
            "ts_utc": self._api_metrics["updated_utc"],
        }

        return res


    def _maybe_sync_orphan_positions(self, verbose: bool = False) -> int:
        """Best-effort reconciliation:
        - If exchange has open futures positions but DB has 0 OPEN trades, reopen/sync so dashboard + monitor match reality.
        - Also avoids poisoning learning by incorrectly closing trades on transient API glitches.
        """
        try:
            if not getattr(self, "sync_orphan_positions", True):
                return 0
            now_ts = time.time()
            if (now_ts - float(getattr(self, "_last_orphan_sync_ts", 0.0) or 0.0)) < float(getattr(self, "orphan_sync_every_sec", 15) or 15):
                return 0
            self._last_orphan_sync_ts = now_ts

            positions = self._api_call("positions_all", self.client.futures_position_information)
            if not isinstance(positions, list) or not positions:
                return 0

            # Collect open positions (net view). In hedge mode there can be multiple rows per symbol.
            by_symbol = {}
            for p in positions:
                try:
                    sym = str(p.get("symbol", "")).upper().strip()
                    if not sym:
                        continue
                    amt = float(p.get("positionAmt", 0) or 0.0)
                except Exception:
                    continue
                if abs(amt) < 1e-12:
                    continue
                prev = by_symbol.get(sym)
                if prev is None:
                    by_symbol[sym] = p
                else:
                    try:
                        prev_amt = float(prev.get("positionAmt", 0) or 0.0)
                    except Exception:
                        prev_amt = 0.0
                    if abs(amt) > abs(prev_amt):
                        by_symbol[sym] = p

            if not by_symbol:
                return 0

            # helper: check if an OPEN trade exists for symbol
            def _get_open_trade_id(sym: str):
                try:
                    with self.db.lock:
                        cur = self.db.conn.cursor()
                        cur.execute("SELECT id FROM trades WHERE symbol=? AND status='OPEN' ORDER BY timestamp_ms DESC LIMIT 1", (sym,))
                        row = cur.fetchone()
                        return int(row[0]) if row else None
                except Exception:
                    return None

            synced = 0
            for sym, p in by_symbol.items():
                open_id = _get_open_trade_id(sym)
                try:
                    amt = float(p.get("positionAmt", 0) or 0.0)
                except Exception:
                    amt = 0.0
                qty = abs(float(amt))
                try:
                    entry = float(p.get("entryPrice", 0) or 0.0)
                except Exception:
                    entry = 0.0
                ps = str(p.get("positionSide", "BOTH") or "BOTH").upper()
                if ps == "SHORT":
                    sig = "SELL"
                elif ps == "LONG":
                    sig = "BUY"
                else:
                    sig = "BUY" if amt > 0 else "SELL"

                if open_id:
                    try:
                        with self.db.lock:
                            self.db.cursor.execute(
                                "UPDATE trades SET quantity=?, entry_price=?, signal=COALESCE(NULLIF(signal,''), ?) WHERE id=?",
                                (float(qty), float(entry), sig, int(open_id))
                            )
                            self.db.conn.commit()
                    except Exception:
                        pass
                    continue

                # Try to reopen last trade for this symbol (if it was falsely closed)
                last = None
                try:
                    if hasattr(self.db, "get_last_trade_for_symbol"):
                        last = self.db.get_last_trade_for_symbol(sym)
                except Exception:
                    last = None

                reopened = False
                if last and str(last.get("status", "")).upper() != "OPEN":
                    try:
                        tid = int(last.get("id"))
                        with self.db.lock:
                            self.db.cursor.execute(
                                "UPDATE trades SET status='OPEN', close_price=NULL, close_reason=NULL, closed_at=NULL, closed_at_ms=NULL, pnl=0 WHERE id=?",
                                (tid,)
                            )
                            self.db.cursor.execute(
                                "UPDATE trades SET quantity=?, entry_price=?, signal=? WHERE id=?",
                                (float(qty), float(entry), sig, tid)
                            )
                            self.db.conn.commit()
                        reopened = True
                        synced += 1
                        if verbose:
                            print(f"🧩 [ORPHAN_SYNC] Reopened {sym} trade_id={tid} ({sig} qty={qty:g})")
                    except Exception:
                        reopened = False

                if reopened:
                    continue

                # Otherwise insert a new OPEN trade
                try:
                    payload = {
                        "symbol": sym,
                        "signal": sig,
                        "entry_price": float(entry),
                        "quantity": float(qty),
                        "stop_loss": 0.0,
                        "take_profits": [],
                        "market_type": "futures",
                        "strategy_tag": "ORPHAN_SYNC",
                        "exit_profile": "ORPHAN",
                        "leverage": None,
                        "confidence": 0.0,
                        "explain": {"source": "orphan_sync", "positionSide": ps},
                        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    }
                    tid = self.db.add_trade(payload) if hasattr(self.db, "add_trade") else None
                    synced += 1
                    if verbose:
                        print(f"🧩 [ORPHAN_SYNC] Inserted {sym} trade_id={tid} ({sig} qty={qty:g})")
                except Exception:
                    continue

            return synced
        except Exception:
            return 0


    # ======================================================
    # PROTECTION AUDIT (Orphan orders / missing SL/TP/Trail)
    # ======================================================
    def _maybe_protection_audit(self, active_trades):
        try:
            if not self.protection_audit_enabled:
                return
            now = time.time()

            # Force audit now (triggered from dashboard)
            forced = False
            try:
                tok = str(self.db.get_setting("protection_audit_force") or "").strip()
                if tok and tok != str(getattr(self, "_last_protection_force_tok", "") or ""):
                    self._last_protection_force_tok = tok
                    forced = True
            except Exception:
                forced = False

            # Force orphan cleanup now (triggered from dashboard)
            cleanup_force = False
            try:
                tok2 = str(self.db.get_setting("orphan_orders_cleanup_force") or "").strip()
                if tok2 and tok2 != str(getattr(self, "_last_orphan_cleanup_tok", "") or ""):
                    self._last_orphan_cleanup_tok = tok2
                    cleanup_force = True
            except Exception:
                cleanup_force = False

            if (not forced) and (not cleanup_force):
                if (now - float(self._last_protection_audit_ts or 0.0)) < float(self.protection_audit_every_sec or 30):
                    return

            self._last_protection_audit_ts = now

            # Helper: persist per-trade protection status (never crash)
            def _persist_trade_protection(trade_id, pstatus, pdetails=None, perror=None):
                try:
                    if trade_id is None:
                        return
                    tid = int(trade_id)
                    if tid <= 0:
                        return
                    if hasattr(self.db, "update_trade_protection"):
                        self.db.update_trade_protection(
                            tid,
                            str(pstatus or "").strip().upper(),
                            details=(pdetails or {}),
                            error=(perror if perror else None),
                            source="execution_monitor",
                            emit_event=True,
                        )
                    else:
                        # Fallback (older DB versions): best-effort direct UPDATE
                        try:
                            with self.db.lock:
                                cols = set([c for c in self.db._table_columns("trades")]) if hasattr(self.db, "_table_columns") else set()
                                ups = {}
                                if "protection_status" in cols:
                                    ups["protection_status"] = str(pstatus or "").strip().upper()
                                if "protection_last_check_ms" in cols:
                                    ups["protection_last_check_ms"] = int(time.time() * 1000)
                                if "protection_details" in cols:
                                    ups["protection_details"] = json.dumps(pdetails or {})
                                if "protection_error" in cols:
                                    ups["protection_error"] = str(perror)[:800] if perror else None
                                if ups:
                                    set_clause = ",".join([f"{k}=?" for k in ups.keys()])
                                    vals = list(ups.values()) + [tid]
                                    self.db.cursor.execute(f"UPDATE trades SET {set_clause} WHERE id=?", vals)
                                    self.db.conn.commit()
                        except Exception:
                            pass
                except Exception:
                    return

            # Key availability gate (for signed endpoints)
            has_keys = bool((getattr(cfg, "BINANCE_API_KEY", "") or "").strip() and (getattr(cfg, "BINANCE_API_SECRET", "") or "").strip())

            # If keys are missing, we can't verify exchange protection.
            if not has_keys:
                # Update OPEN futures trades so UI doesn't look "stuck"
                for t in (active_trades or []):
                    try:
                        if str(t.get("status") or "").upper() != "OPEN":
                            continue
                        if str(t.get("market_type") or "").lower() != "futures":
                            continue
                        _persist_trade_protection(
                            t.get("id"),
                            "SKIPPED_NO_KEYS",
                            pdetails={
                                "note": "Missing BINANCE_API_KEY/SECRET; cannot call signed futures endpoints",
                                "mode": str(self.db.get_setting("mode") or "TEST"),
                                "use_testnet": bool(getattr(cfg, "USE_TESTNET", True)),
                            },
                            perror=None,
                        )
                    except Exception:
                        continue

                audit = {
                    "updated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "forced": bool(forced),
                    "cleanup_force": bool(cleanup_force),
                    "keys_present": False,
                    "symbols_checked": [str(t.get("symbol") or "").upper() for t in (active_trades or []) if str(t.get("market_type") or "").lower() == "futures"],
                    "counts": {"symbols": 0, "positions": 0, "open_orders": 0},
                    "issues": {"missing_sl": [], "missing_tp": [], "missing_trail": [], "duplicates": [], "orphan_orders": []},
                    "per_symbol": {},
                    "message": "Missing BINANCE_API_KEY/SECRET; protection audit skipped",
                }
                try:
                    self.db.set_setting("protection_audit_status", json.dumps(audit), source="execution_monitor", bump_version=False, audit=False)
                except Exception:
                    pass
                return

            # pull ALL open orders once (cheaper)
            open_orders = self._api_call("open_orders_all", self.client.futures_get_open_orders) or []
            # pull ALL positions once (to avoid false 'orphan' when DB is stale)
            pos_all = self._api_call("positions_all", self.client.futures_position_information) or []

            pos_by_symbol = {}
            try:
                for p in pos_all:
                    s = str(p.get("symbol") or "").upper()
                    if not s:
                        continue
                    try:
                        amt = float(p.get("positionAmt") or 0.0)
                    except Exception:
                        amt = 0.0
                    if abs(amt) > 0.0:
                        pos_by_symbol[s] = {
                            "positionAmt": amt,
                            "entryPrice": float(p.get("entryPrice") or 0.0) if p.get("entryPrice") is not None else 0.0,
                            "unRealizedProfit": float(p.get("unRealizedProfit") or 0.0) if p.get("unRealizedProfit") is not None else 0.0,
                            "marginType": p.get("marginType"),
                            "leverage": p.get("leverage"),
                        }
            except Exception:
                pos_by_symbol = {}

            orders_by_symbol = {}
            for o in (open_orders or []):
                s = str(o.get("symbol") or "").upper()
                if not s:
                    continue
                orders_by_symbol.setdefault(s, []).append(o)

            trades_by_symbol = {}
            for t in (active_trades or []):
                s = str(t.get("symbol") or "").upper()
                if s:
                    trades_by_symbol[s] = t

            symbols = sorted(set(list(orders_by_symbol.keys()) + list(pos_by_symbol.keys()) + list(trades_by_symbol.keys())))

            audit = {
                "updated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "forced": bool(forced),
                "cleanup_force": bool(cleanup_force),
                "keys_present": True,
                "symbols_checked": symbols,
                "counts": {
                    "symbols": len(symbols),
                    "positions": len(pos_by_symbol),
                    "open_orders": len(open_orders or []),
                },
                "issues": {
                    "missing_sl": [],
                    "missing_tp": [],
                    "missing_trail": [],
                    "duplicates": [],
                    "orphan_orders": [],
                },
                "per_symbol": {},
            }

            # settings that affect expectations
            hard_tp = str(self.db.get_setting("hard_tp_enabled") or "TRUE").strip().upper() in ("1","TRUE","YES","ON","Y")
            exch_trail = str(self.db.get_setting("exchange_trailing_enabled") or "FALSE").strip().upper() in ("1","TRUE","YES","ON","Y")
            try:
                act_roi = float(self.db.get_setting("exchange_trailing_activation_roi") or 0.01)
            except Exception:
                act_roi = 0.01

            def _is_protective(o):
                typ = str(o.get("type") or "").upper()
                return typ in ("STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET")

            for s in symbols:
                pos = pos_by_symbol.get(s)
                has_pos = pos is not None
                t = trades_by_symbol.get(s)
                ol = orders_by_symbol.get(s, [])
                prot = [o for o in ol if _is_protective(o)]

                # summarize counts
                type_counts = {}
                for o in prot:
                    typ = str(o.get("type") or "").upper()
                    type_counts[typ] = type_counts.get(typ, 0) + 1

                # expectation based on DB trade
                exp_sl = False
                exp_tp = False
                exp_trail = False
                sl_price = None
                if has_pos and self.ensure_protection_orders and t:
                    try:
                        sl = float(t.get("stop_loss") or 0.0)
                    except Exception:
                        sl = 0.0
                    if sl > 0:
                        exp_sl = True
                        sl_price = sl
                    if hard_tp:
                        # any configured TP list => expect at least one TP order
                        tp_list = t.get("take_profits")
                        if isinstance(tp_list, str):
                            try:
                                tp_list = json.loads(tp_list)
                            except Exception:
                                tp_list = []
                        if isinstance(tp_list, list) and len(tp_list) > 0:
                            exp_tp = True

                    # exchange trailing expected only after activation ROI met
                    if exch_trail:
                        try:
                            entry = float(t.get("entry_price") or 0.0)
                        except Exception:
                            entry = 0.0
                        # best effort mark price
                        mark = None
                        try:
                            mp = self._api_call(f"mark_price_{s}", self.client.futures_mark_price, symbol=s) or {}
                            mark = float(mp.get("markPrice") or 0.0)
                        except Exception:
                            mark = None
                        if entry > 0 and mark and mark > 0:
                            roi = (mark - entry) / entry if float(pos.get("positionAmt") or 0.0) > 0 else (entry - mark) / entry
                            if roi >= act_roi:
                                exp_trail = True

                has_sl = any(str(o.get("type") or "").upper() in ("STOP","STOP_MARKET") for o in prot)
                has_tp = any(str(o.get("type") or "").upper() in ("TAKE_PROFIT","TAKE_PROFIT_MARKET") for o in prot)
                has_trail = any(str(o.get("type") or "").upper() == "TRAILING_STOP_MARKET" for o in prot)

                # Update per-trade protection status (futures trades only)
                try:
                    if t and str(t.get("market_type") or "").lower() == "futures":
                        tid = int(t.get("id") or 0)
                        pdetails = {
                            "symbol": s,
                            "has_position": bool(has_pos),
                            "expected": {"sl": bool(exp_sl), "tp": bool(exp_tp), "trail": bool(exp_trail)},
                            "present": {"sl": bool(has_sl), "tp": bool(has_tp), "trail": bool(has_trail)},
                            "order_types": type_counts,
                            "open_orders_total": int(len(ol)),
                            "protective_orders": int(len(prot)),
                            "mode": str(self.db.get_setting("mode") or "TEST"),
                            "use_testnet": bool(getattr(cfg, "USE_TESTNET", True)),
                        }
                        if has_pos:
                            pdetails["position"] = pos

                        # Decide status
                        pstatus = "OK"
                        missing = []
                        if not has_pos:
                            pstatus = "NO_POSITION"
                        else:
                            if exp_sl and (not has_sl):
                                missing.append("SL")
                            if exp_tp and (not has_tp):
                                missing.append("TP")
                            if exp_trail and (not has_trail):
                                missing.append("TRAIL")
                            if missing:
                                pstatus = "MISSING_" + "_".join(missing)
                        _persist_trade_protection(tid, pstatus, pdetails, None)
                except Exception:
                    pass

                if exp_sl and not has_sl:
                    audit["issues"]["missing_sl"].append({"symbol": s, "expected_sl": sl_price})
                if exp_tp and not has_tp:
                    audit["issues"]["missing_tp"].append({"symbol": s})
                if exp_trail and not has_trail:
                    audit["issues"]["missing_trail"].append({"symbol": s})

                # duplicates (more than one protective order type)
                dups = {k: v for k, v in type_counts.items() if v and v > 1}
                if dups:
                    audit["issues"]["duplicates"].append({"symbol": s, "types": dups})

                # orphan protective orders (no position AND no active DB trade)
                if (not has_pos) and (t is None) and prot:
                    # keep lightweight list
                    oo = []
                    for o in prot[:30]:
                        oo.append({
                            "orderId": o.get("orderId"),
                            "type": o.get("type"),
                            "side": o.get("side"),
                            "reduceOnly": o.get("reduceOnly"),
                            "closePosition": o.get("closePosition"),
                            "stopPrice": o.get("stopPrice"),
                            "activationPrice": o.get("activatePrice") or o.get("activationPrice"),
                            "price": o.get("price"),
                            "origQty": o.get("origQty"),
                            "status": o.get("status"),
                        })
                    audit["issues"]["orphan_orders"].append({"symbol": s, "count": len(prot), "orders": oo})

                    # Optional cleanup: cancel ALL open orders for symbols that are orphaned
                    if cleanup_force:
                        try:
                            self._api_call(f"cancel_all_orphan_{s}", self.client.futures_cancel_all_open_orders, symbol=s)
                        except Exception:
                            pass

                # per-symbol summary for UI
                audit["per_symbol"][s] = {
                    "has_position": bool(has_pos),
                    "position": pos_by_symbol.get(s) if has_pos else None,
                    "db_trade": {
                        "id": t.get("id") if t else None,
                        "side": t.get("side") if t else None,
                        "qty": t.get("qty") if t else None,
                        "entry_price": t.get("entry_price") if t else None,
                        "stop_loss": t.get("stop_loss") if t else None,
                    } if t else None,
                    "open_orders": {
                        "total": len(ol),
                        "protective": len(prot),
                        "types": type_counts,
                    },
                }

            # persist to DB settings for Doctor
            try:
                self.db.set_setting("protection_audit_status", json.dumps(audit), source="execution_monitor", bump_version=False, audit=False)
            except Exception:
                pass

            # ack tokens so UI can show "handled"
            try:
                if forced:
                    self.db.set_setting("protection_audit_force_ack", str(int(time.time() * 1000)), source="execution_monitor", bump_version=False, audit=False)
            except Exception:
                pass
            try:
                if cleanup_force:
                    self.db.set_setting("orphan_orders_cleanup_ack", str(int(time.time() * 1000)), source="execution_monitor", bump_version=False, audit=False)
            except Exception:
                pass

        except Exception:
            # never crash monitor due to audit
            return


    def _maybe_take_snapshot(self, active_trades_count: int = 0) -> None:
        if not self.snapshot_enabled:
            return

        now = time.time()
        if (now - self._last_snapshot_ts) < self.snapshot_every_sec:
            return

        wallet, unreal, equity = self._get_futures_equity()
        meta = {
            "source": "execution_monitor",
            "active_trades": int(active_trades_count),
            "testnet": bool(getattr(cfg, "USE_TESTNET", True)),
            "wallet_balance": wallet,
            "unrealized_pnl": unreal,
        }

        if equity <= 0:
            fallback = self._fallback_equity_from_trades()
            if fallback is None:
                self._last_snapshot_ts = now
                return
            equity, closed_count = fallback
            meta["source"] = "execution_monitor_fallback"
            meta["closed_trades"] = int(closed_count or 0)
            meta["wallet_balance"] = 0.0
            meta["unrealized_pnl"] = 0.0
            meta["note"] = "fallback_equity_from_closed_trades"
        self._save_equity_snapshot(total_balance=equity, unrealized_pnl=unreal, meta=meta)
        self._last_snapshot_ts = now

    def _get_futures_equity(self):
        """
        Returns (wallet_balance, unrealized_pnl, equity/total_margin_balance) in USDT.
        Best-effort across Binance client variants.
        """
        # Preferred: futures_account() if keys are present
        try:
            acc = self.client.futures_account()
            wallet = float(acc.get("totalWalletBalance", 0) or 0)
            unreal = float(acc.get("totalUnrealizedProfit", 0) or 0)
            equity = float(acc.get("totalMarginBalance", 0) or 0)
            if equity <= 0:
                equity = wallet + unreal
            return wallet, unreal, equity
        except Exception:
            pass

        # Fallback: futures_account_balance() (public-ish)
        try:
            bals = self.client.futures_account_balance()
            for b in bals:
                if str(b.get("asset", "")).upper() == "USDT":
                    wallet = float(b.get("balance", 0) or 0)
                    return wallet, 0.0, wallet
        except Exception:
            pass

        return 0.0, 0.0, 0.0

    def _fallback_equity_from_trades(self):
        """Best-effort equity fallback when API keys are unavailable."""
        try:
            conn = getattr(self.db, "conn", None)
            if conn is None:
                return None
            lock = getattr(self.db, "lock", None)
            sql = "SELECT SUM(pnl) AS pnl_sum, COUNT(*) AS c FROM trades WHERE status='CLOSED'"
            if lock:
                with lock:
                    row = conn.execute(sql).fetchone()
            else:
                row = conn.execute(sql).fetchone()
            if not row:
                return None
            pnl_sum = float(row[0] or 0.0)
            cnt = int(row[1] or 0)
            return pnl_sum, cnt
        except Exception:
            return None

    def _save_equity_snapshot(self, total_balance: float, unrealized_pnl: float, meta: dict) -> None:
        # New API (database.new.py)
        try:
            if hasattr(self.db, "add_equity_snapshot"):
                self.db.add_equity_snapshot(
                    total_balance=float(total_balance),
                    unrealized_pnl=float(unrealized_pnl),
                    source="execution_monitor",
                    meta=meta,
                )
                return
        except Exception:
            pass

        # Legacy fallback insert
        try:
            ts = self._utc_iso()
            lock = getattr(self.db, "lock", None)
            cur = getattr(self.db, "cursor", None)
            conn = getattr(self.db, "conn", None)
            if cur is None or conn is None:
                return
            sql = "INSERT INTO equity_history (timestamp, total_balance, unrealized_pnl) VALUES (?, ?, ?)"
            if lock:
                with lock:
                    cur.execute(sql, (ts, float(total_balance), float(unrealized_pnl)))
                    conn.commit()
            else:
                cur.execute(sql, (ts, float(total_balance), float(unrealized_pnl)))
                conn.commit()
        except Exception:
            pass

    def _maybe_prune_snapshots(self) -> None:
        now = time.time()
        if (now - self._last_prune_ts) < self._prune_every_sec:
            return

        retention_days = int(self.snapshot_retention_days or 0)
        if retention_days <= 0:
            self._last_prune_ts = now
            return

        try:
            if hasattr(self.db, "prune_equity_history"):
                self.db.prune_equity_history(retention_days=retention_days)
        except Exception:
            pass

        self._last_prune_ts = now

# =========================================
# RUN
# =========================================
if __name__ == "__main__":
    ExecutionMonitor().run()
