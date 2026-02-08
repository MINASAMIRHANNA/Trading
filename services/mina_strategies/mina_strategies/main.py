from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, Iterable, List, Mapping


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value)


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _split_csv(raw: str) -> List[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def _stable_confidence(symbol: str, role: str) -> float:
    key = f"{symbol}:{role}".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    bucket = int(digest[:4], 16) % 20
    return round(0.51 + (bucket / 100.0), 4)


def _choose_side(symbol: str, role: str) -> str:
    key = f"{symbol}:{role}".encode("utf-8")
    digest = hashlib.md5(key).hexdigest()
    return "BUY" if int(digest[:2], 16) % 2 == 0 else "SELL"


def generate_signal_event(symbol: str, role: str, market_snapshot: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Strategy-only output contract (no execution side effects)."""
    trace_id = uuid.uuid4().hex
    decision_id = uuid.uuid4().hex
    confidence = _stable_confidence(symbol, role)
    side = _choose_side(symbol, role)
    schema_version = _env("SIGNAL_SCHEMA_VERSION", "v1")

    event = {
        "event_type": "SignalEvent",
        "schema_version": schema_version,
        "trace_id": trace_id,
        "decision_id": decision_id,
        "symbol": symbol,
        "side": side,
        "timeframe": "5m",
        "strategy": "mina_strategies_adapter",
        "confidence": confidence,
        "score": confidence,
        "exit_profile": {
            "name": "balanced_exit_v1",
            "take_profit_pct": 1.2,
            "stop_loss_pct": 0.8,
            "max_hold_min": 45,
        },
        "execution_allowed": False,
        "payload": {
            "source": "mina_strategies",
            "generated_at": now_utc_iso(),
            "market_snapshot": dict(market_snapshot or {}),
        },
    }
    return event


def publish_signal(base_url: str, role: str, payload: Mapping[str, Any], api_key: str = "") -> Dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/api/unified/{role}/publish"
    body = json.dumps(dict(payload), ensure_ascii=True).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["X-API-Key"] = api_key

    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            parsed = json.loads(raw) if raw else {}
            if not isinstance(parsed, dict):
                parsed = {"raw": raw}
            return {"ok": True, "status_code": int(resp.status), "response": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
        return {
            "ok": False,
            "status_code": int(getattr(exc, "code", 500)),
            "error": raw or str(exc),
        }
    except Exception as exc:
        return {"ok": False, "status_code": 0, "error": str(exc)}


def run_loop() -> None:
    base_url = _env("GATEWAY_BASE_URL", "http://gateway_api:8200")
    api_key = _env("GATEWAY_API_KEY", "")
    roles = [r.lower() for r in _split_csv(_env("MINA_STRATEGIES_ROLES", "paper"))]
    roles = [r for r in roles if r in {"paper", "live", "pump"}]
    if not roles:
        roles = ["paper"]

    symbols = [s.upper() for s in _split_csv(_env("MINA_STRATEGIES_SYMBOLS", "BTCUSDT,ETHUSDT"))]
    if not symbols:
        symbols = ["BTCUSDT"]

    interval_sec = max(5, int(float(_env("MINA_STRATEGIES_INTERVAL_SEC", "30"))))
    dry_run = _env("MINA_STRATEGIES_DRY_RUN", "0").strip().lower() in {"1", "true", "yes", "on"}

    idx = 0
    print(
        f"[mina_strategies] start roles={roles} symbols={symbols} interval={interval_sec}s dry_run={dry_run} base={base_url}"
    )

    while True:
        symbol = symbols[idx % len(symbols)]
        idx += 1

        for role in roles:
            market_snapshot = {
                "source": "synthetic",
                "generated_at": now_utc_iso(),
                "symbol": symbol,
            }
            signal = generate_signal_event(symbol=symbol, role=role, market_snapshot=market_snapshot)

            if dry_run:
                print(
                    "[mina_strategies] dry-run",
                    json.dumps({"role": role, "symbol": symbol, "signal": signal}, ensure_ascii=True),
                )
                continue

            result = publish_signal(base_url=base_url, role=role, payload=signal, api_key=api_key)
            if result.get("ok"):
                published_id = (result.get("response") or {}).get("id")
                print(
                    f"[mina_strategies] published role={role} symbol={symbol} id={published_id} trace_id={signal.get('trace_id')}"
                )
            else:
                print(
                    f"[mina_strategies] publish failed role={role} symbol={symbol} status={result.get('status_code')} err={result.get('error')}"
                )

        time.sleep(interval_sec)


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
