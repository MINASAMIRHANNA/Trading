from datetime import date
import pandas as pd


def _to_json_scalar(value):
    """Convert numpy/pandas scalars to native JSON-safe Python values."""
    try:
        if hasattr(value, "item"):
            return value.item()
    except Exception:
        pass
    return value


def build_daily_summary(df: pd.DataFrame) -> dict:
    today = date.today()

    daily = df.copy()
    daily["day"] = pd.to_datetime(daily["trade_time"]).dt.date
    daily = daily[daily["day"] == today]

    if daily.empty:
        return {
            "date": str(today),
            "trades": 0,
            "message": "No trades today. Good discipline or missed opportunity."
        }

    summary = {
        "date": str(today),
        "trades": int(len(daily)),
        "win_rate": float((daily["pnl_pct"] > 0).mean()),
        "avg_pnl": float(daily["pnl_pct"].mean()),
        "expectancy": float(daily["pnl_pct"].mean()),
        "best_regime": None,
        "worst_regime": None,
    }

    if "market_regime_encoded" in daily.columns and daily["market_regime_encoded"].notna().any():
        by_regime = daily.groupby("market_regime_encoded")["pnl_pct"].mean()
        if not by_regime.empty:
            summary["best_regime"] = _to_json_scalar(by_regime.idxmax())
            summary["worst_regime"] = _to_json_scalar(by_regime.idxmin())

    return summary
