from typing import List, Optional, Dict, Any
import pandas as pd


def compute_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "expectancy": 0.0
        }

    return {
        "trades": len(df),
        "win_rate": float((df["pnl_pct"] > 0).mean()),
        "avg_pnl": float(df["pnl_pct"].mean()),
        "expectancy": float(df["pnl_pct"].mean())
    }


def simulate_strategy(
    df: pd.DataFrame,
    allowed_regimes: Optional[List[float]] = None,
    allowed_alignment: Optional[List[float]] = None,
    allowed_rsi_buckets: Optional[List[str]] = None,
    max_atr_pct: Optional[float] = None,
    symbol: Optional[str] = None,
    start_time: Optional[pd.Timestamp] = None,
    end_time: Optional[pd.Timestamp] = None
) -> Dict[str, Any]:
    """
    What-if simulator: apply filters to historical trades and
    compare actual vs simulated performance.
    """

    base_df = df.copy()

    # -----------------------------
    # Base (Actual) metrics
    # -----------------------------
    actual_metrics = compute_metrics(base_df)

    sim_df = base_df.copy()

    # -----------------------------
    # Apply filters
    # -----------------------------
    if symbol:
        sim_df = sim_df[sim_df["symbol"] == symbol]

    if start_time:
        sim_df = sim_df[pd.to_datetime(sim_df["trade_time"]) >= start_time]

    if end_time:
        sim_df = sim_df[pd.to_datetime(sim_df["trade_time"]) <= end_time]

    if allowed_regimes is not None:
        sim_df = sim_df[sim_df["market_regime_encoded"].isin(allowed_regimes)]

    if allowed_alignment is not None:
        sim_df = sim_df[sim_df["directional_alignment"].isin(allowed_alignment)]

    if allowed_rsi_buckets is not None and "rsi_bucket" in sim_df.columns:
        sim_df = sim_df[sim_df["rsi_bucket"].isin(allowed_rsi_buckets)]

    if max_atr_pct is not None and "atr_pct_at_entry" in sim_df.columns:
        sim_df = sim_df[sim_df["atr_pct_at_entry"] <= max_atr_pct]

    # -----------------------------
    # Simulated metrics
    # -----------------------------
    simulated_metrics = compute_metrics(sim_df)

    # -----------------------------
    # Delta
    # -----------------------------
    delta = {
        "trades": simulated_metrics["trades"] - actual_metrics["trades"],
        "win_rate": simulated_metrics["win_rate"] - actual_metrics["win_rate"],
        "avg_pnl": simulated_metrics["avg_pnl"] - actual_metrics["avg_pnl"],
        "expectancy": simulated_metrics["expectancy"] - actual_metrics["expectancy"],
    }

    return {
        "actual": actual_metrics,
        "simulated": simulated_metrics,
        "delta": delta,
        "simulated_df": sim_df
    }
