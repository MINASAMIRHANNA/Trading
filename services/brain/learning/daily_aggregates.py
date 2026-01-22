import pandas as pd


def build_daily_aggregates(df: pd.DataFrame) -> dict:
    """
    Build daily performance aggregates for rule-based learning.
    """

    insights = {}

    # -----------------------------
    # Overall performance
    # -----------------------------
    insights["overall"] = {
        "trades": len(df),
        "win_rate": (df["pnl_pct"] > 0).mean(),
        "avg_pnl": df["pnl_pct"].mean(),
        "expectancy": df["pnl_pct"].mean()
    }

    # -----------------------------
    # By market regime
    # -----------------------------
    regime_stats = (
        df.groupby("market_regime_encoded")
        .agg(
            trades=("pnl_pct", "count"),
            win_rate=("pnl_pct", lambda x: (x > 0).mean()),
            avg_pnl=("pnl_pct", "mean")
        )
        .reset_index()
    )

    insights["by_regime"] = regime_stats

    # -----------------------------
    # By directional alignment
    # -----------------------------
    align_stats = (
        df.groupby("directional_alignment")
        .agg(
            trades=("pnl_pct", "count"),
            win_rate=("pnl_pct", lambda x: (x > 0).mean()),
            avg_pnl=("pnl_pct", "mean")
        )
        .reset_index()
    )

    insights["by_alignment"] = align_stats

    # -----------------------------
    # By RSI bucket
    # -----------------------------
    if "rsi_bucket" in df.columns:
        rsi_stats = (
            df.groupby("rsi_bucket")
            .agg(
                trades=("pnl_pct", "count"),
                win_rate=("pnl_pct", lambda x: (x > 0).mean()),
                avg_pnl=("pnl_pct", "mean")
            )
            .reset_index()
        )

        insights["by_rsi_bucket"] = rsi_stats

    return insights
