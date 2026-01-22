"""market_regime.py

Micro market-regime classification for a *single symbol* based on its recent OHLCV.

This is intentionally lightweight and DB-configurable.

Regime labels (Appendix A):
  - TREND
  - RANGE
  - HIGH_VOL
  - LOW_VOL

The output is used for:
  - dynamic confidence floors (CONF_THRESH_*)
  - optional position size factors (SIZE_FACTOR_*)
  - veto filters (e.g., VETO_ATR_PCT_MAX)

Notes:
  - Uses existing indicators.py implementations (ATR/ADX/EMA).
  - Safe defaults are provided if settings are missing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from indicators import atr, adx, ema


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        return int(float(x))
    except Exception:
        return default


def _get_setting(db: Any, key: str, default: Any = None) -> Any:
    """DB settings accessor (DatabaseManager-like)."""
    try:
        if db is None:
            return default
        v = db.get_setting(key)
        if v is None or str(v).strip() == "":
            return default
        return v
    except Exception:
        return default


def classify_regime(
    df: pd.DataFrame,
    price: float,
    market_type: str = "futures",
    timeframe: str = "",
    db: Any = None,
) -> Dict[str, Any]:
    """Return a regime dict.

    The logic is designed to be stable and explainable:
      1) Compute ATR% and ADX.
      2) Tag HIGH_VOL / LOW_VOL by ATR% thresholds.
      3) Otherwise use ADX + EMA slope to decide TREND vs RANGE.
    """

    mkt = str(market_type or "futures").strip().lower()
    tf = str(timeframe or "").strip()

    # Indicator lengths
    atr_len = _safe_int(_get_setting(db, "ind_atr_len", 14), 14)
    adx_len = _safe_int(_get_setting(db, "ind_adx_len", 14), 14)
    ma_fast = _safe_int(_get_setting(db, "ind_ma_fast", 50), 50)

    atr_v = 0.0
    adx_v = 0.0
    slope = 0.0
    atr_pct = 0.0

    try:
        atr_v = _safe_float(atr(df, atr_len).iloc[-1], 0.0)
    except Exception:
        atr_v = 0.0
    try:
        adx_v = _safe_float(adx(df, adx_len).iloc[-1], 0.0)
    except Exception:
        adx_v = 0.0

    try:
        if price and float(price) > 0:
            atr_pct = float(atr_v) / float(price)
    except Exception:
        atr_pct = 0.0

    # EMA slope (fast MA)
    try:
        e = ema(df, ma_fast)
        ema_now = _safe_float(e.iloc[-1], 0.0)
        # use 5 bars back for slope stability
        ema_prev = _safe_float(e.iloc[-6] if len(e) >= 6 else e.iloc[0], 0.0)
        if ema_prev:
            slope = (ema_now - ema_prev) / ema_prev
    except Exception:
        slope = 0.0

    # Thresholds (DB-configurable)
    adx_trend_th = _safe_float(_get_setting(db, "REGIME_ADX_TREND", 22), 22.0)
    adx_range_th = _safe_float(_get_setting(db, "REGIME_ADX_RANGE", 18), 18.0)
    slope_trend_th = _safe_float(_get_setting(db, "REGIME_SLOPE_TREND", 0.002), 0.002)

    # Volatility thresholds differ slightly spot vs futures.
    if mkt == "spot":
        high_vol_th = _safe_float(_get_setting(db, "REGIME_ATR_PCT_HIGH_SPOT", 0.015), 0.015)
        low_vol_th = _safe_float(_get_setting(db, "REGIME_ATR_PCT_LOW_SPOT", 0.007), 0.007)
    else:
        high_vol_th = _safe_float(_get_setting(db, "REGIME_ATR_PCT_HIGH_FUT", 0.022), 0.022)
        low_vol_th = _safe_float(_get_setting(db, "REGIME_ATR_PCT_LOW_FUT", 0.010), 0.010)

    label = "RANGE"
    # Priority: volatility extremes
    if atr_pct >= high_vol_th:
        label = "HIGH_VOL"
    elif atr_pct <= low_vol_th:
        label = "LOW_VOL"
    else:
        # Trend vs range
        if adx_v >= adx_trend_th and abs(slope) >= slope_trend_th:
            label = "TREND"
        elif adx_v < adx_range_th:
            label = "RANGE"
        else:
            # ambiguous middle: treat as TREND only if slope is meaningful, otherwise RANGE
            label = "TREND" if abs(slope) >= (slope_trend_th * 0.75) else "RANGE"

    return {
        "label": label,
        "market_type": mkt,
        "tf": tf,
        "atr": float(atr_v),
        "atr_pct": float(atr_pct),
        "adx": float(adx_v),
        "slope": float(slope),
        "thresholds": {
            "adx_trend": float(adx_trend_th),
            "adx_range": float(adx_range_th),
            "slope_trend": float(slope_trend_th),
            "high_vol": float(high_vol_th),
            "low_vol": float(low_vol_th),
        },
    }


def regime_conf_floor_pct(regime_label: str, db: Any = None) -> Optional[float]:
    """Return confidence floor as PERCENT for a given regime label.

    Reads DB keys: CONF_THRESH_TREND/RANGE/HIGH_VOL/LOW_VOL.
    Values may be stored as probability (0..1) or percent (0..100).
    """
    lbl = str(regime_label or "").strip().upper()
    if not lbl:
        return None
    key = f"CONF_THRESH_{lbl}"
    v = _get_setting(db, key, None)
    if v is None:
        return None
    try:
        x = float(v)
    except Exception:
        return None
    # accept 0..1 or 0..100
    if 0.0 <= x <= 1.5:
        return max(0.0, min(100.0, x * 100.0))
    return max(0.0, min(100.0, x))


def regime_size_factor(regime_label: str, db: Any = None) -> float:
    """Return sizing multiplier for a given regime label.

    DB keys: SIZE_FACTOR_TREND/RANGE/HIGH_VOL/LOW_VOL.
    Defaults follow Appendix A: TREND=1.0, RANGE=0.7, HIGH_VOL=0.6, LOW_VOL=0.8.
    """
    lbl = str(regime_label or "").strip().upper()
    if not lbl:
        return 1.0
    defaults = {
        "TREND": 1.0,
        "RANGE": 0.7,
        "HIGH_VOL": 0.6,
        "LOW_VOL": 0.8,
    }
    key = f"SIZE_FACTOR_{lbl}"
    v = _get_setting(db, key, defaults.get(lbl, 1.0))
    try:
        f = float(v)
    except Exception:
        f = defaults.get(lbl, 1.0)
    # keep within sane bounds
    if f < 0.1:
        f = 0.1
    if f > 2.0:
        f = 2.0
    return float(f)
