def apply_strategy(df, filters: dict):
    filtered = df.copy()

    if "regimes" in filters:
        filtered = filtered[filtered["market_regime_encoded"].isin(filters["regimes"])]

    if "alignment" in filters:
        filtered = filtered[filtered["directional_alignment"].isin(filters["alignment"])]

    return {
        "trades": len(filtered),
        "win_rate": float((filtered["pnl_pct"] > 0).mean()),
        "expectancy": float(filtered["pnl_pct"].mean()),
    }
