import pandas as pd


def _empty_group_df(group_col: str) -> pd.DataFrame:
    return pd.DataFrame([], columns=[group_col, "trades", "win_rate", "avg_pnl"])


def build_daily_aggregates(df: pd.DataFrame) -> dict:
    """Build performance aggregates used by the Brain API.

    This function is intentionally defensive:
    - If there is no data yet (fresh DB), it returns zeroed stats and empty frames
      instead of raising KeyError.
    - It tolerates missing optional columns.
    """

    if df is None:
        df = pd.DataFrame()

    # Ensure expected columns exist so downstream code doesn't explode.
    for col in ["pnl_pct", "market_regime_encoded", "directional_alignment"]:
        if col not in df.columns:
            df[col] = pd.Series(dtype="float64")

    trades = int(len(df))
    if trades == 0:
        return {
            "overall": {
                "trades": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "expectancy": 0.0,
            },
            "by_regime": _empty_group_df("market_regime_encoded"),
            "by_alignment": _empty_group_df("directional_alignment"),
            "by_rsi_bucket": _empty_group_df("rsi_bucket"),
        }

    pnl = pd.to_numeric(df["pnl_pct"], errors="coerce")
    pnl = pnl.dropna()

    win_rate = float((pnl > 0).mean()) if len(pnl) else 0.0
    avg_pnl = float(pnl.mean()) if len(pnl) else 0.0
    expectancy = avg_pnl

    insights: dict = {}

    insights["overall"] = {
        "trades": trades,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "expectancy": expectancy,
    }

    # By market regime
    if "market_regime_encoded" in df.columns and len(df["market_regime_encoded"].dropna()) > 0:
        regime_stats = (
            df.groupby("market_regime_encoded")
            .agg(
                trades=("pnl_pct", "count"),
                win_rate=("pnl_pct", lambda x: (pd.to_numeric(x, errors="coerce") > 0).mean()),
                avg_pnl=("pnl_pct", lambda x: pd.to_numeric(x, errors="coerce").mean()),
            )
            .reset_index()
        )
    else:
        regime_stats = _empty_group_df("market_regime_encoded")

    insights["by_regime"] = regime_stats

    # By directional alignment
    if "directional_alignment" in df.columns and len(df["directional_alignment"].dropna()) > 0:
        align_stats = (
            df.groupby("directional_alignment")
            .agg(
                trades=("pnl_pct", "count"),
                win_rate=("pnl_pct", lambda x: (pd.to_numeric(x, errors="coerce") > 0).mean()),
                avg_pnl=("pnl_pct", lambda x: pd.to_numeric(x, errors="coerce").mean()),
            )
            .reset_index()
        )
    else:
        align_stats = _empty_group_df("directional_alignment")

    insights["by_alignment"] = align_stats

    # By RSI bucket (optional)
    if "rsi_bucket" in df.columns and len(df["rsi_bucket"].dropna()) > 0:
        rsi_stats = (
            df.groupby("rsi_bucket")
            .agg(
                trades=("pnl_pct", "count"),
                win_rate=("pnl_pct", lambda x: (pd.to_numeric(x, errors="coerce") > 0).mean()),
                avg_pnl=("pnl_pct", lambda x: pd.to_numeric(x, errors="coerce").mean()),
            )
            .reset_index()
        )
    else:
        rsi_stats = _empty_group_df("rsi_bucket")

    insights["by_rsi_bucket"] = rsi_stats

    return insights
