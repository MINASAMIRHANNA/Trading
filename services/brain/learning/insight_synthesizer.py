def synthesize_insights(aggregates: dict, ml_importance) -> dict:
    """
    Combine rule-based stats and ML feature importance
    into actionable insights.
    """

    insights = {
        "strengths": [],
        "weaknesses": [],
        "recommendations": []
    }

    # -----------------------------
    # Rules-based insights
    # -----------------------------

    by_regime = aggregates.get("by_regime")

    if by_regime is not None:
        for _, row in by_regime.iterrows():
            if row["avg_pnl"] > 0:
                insights["strengths"].append(
                    f"Positive expectancy when market_regime_encoded = {row['market_regime_encoded']}"
                )
            else:
                insights["weaknesses"].append(
                    f"Negative expectancy when market_regime_encoded = {row['market_regime_encoded']}"
                )

    by_alignment = aggregates.get("by_alignment")
    if by_alignment is not None:
        for _, row in by_alignment.iterrows():
            if row["avg_pnl"] < 0:
                insights["weaknesses"].append(
                    f"Poor performance when directional_alignment = {row['directional_alignment']}"
                )

    # -----------------------------
    # ML-based insights
    # -----------------------------

    top_feature = ml_importance.idxmax()
    top_value = ml_importance.max()

    insights["strengths"].append(
        f"Most influential feature for profitability: {top_feature} (importance={top_value:.2f})"
    )

    if top_feature == "market_regime_encoded":
        insights["recommendations"].append(
            "Prioritize trades only during favorable market regimes (filter by regime)."
        )

    if "directional_alignment" in ml_importance.index:
        if ml_importance["directional_alignment"] < 0:
            insights["recommendations"].append(
                "Your edge may favor selective counter-trend trades rather than pure trend-following."
            )

    return insights
