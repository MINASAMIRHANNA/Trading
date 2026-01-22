def build_llm_context(df, daily_summary, regime_stats, feature_importance):
    context = f"""
You are a trading performance coach.
You do NOT give trading signals.
You analyze past performance only.

=== DAILY SUMMARY ===
Trades: {daily_summary.get("trades")}
Win Rate: {daily_summary.get("win_rate")}
Expectancy: {daily_summary.get("expectancy")}
Best Regime: {daily_summary.get("best_regime")}
Worst Regime: {daily_summary.get("worst_regime")}

=== REGIME PERFORMANCE ===
{regime_stats.to_string()}

=== FEATURE IMPORTANCE ===
{feature_importance}

Your task:
- Explain performance
- Identify mistakes
- Suggest improvements
- Warn against risky behavior
"""
    return context
