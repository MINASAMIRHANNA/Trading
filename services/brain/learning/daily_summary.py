from datetime import date
import pandas as pd

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
        "best_regime": (
            daily.groupby("market_regime")["pnl_pct"].mean().idxmax()
        ),
        "worst_regime": (
            daily.groupby("market_regime")["pnl_pct"].mean().idxmin()
        ),
    }

    return summary
