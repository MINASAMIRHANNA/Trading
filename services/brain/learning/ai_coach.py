def generate_ai_coach(summary: dict) -> dict:
    advice = []

    if summary.get("trades", 0) == 0:
        advice.append("No trades today. Consider whether conditions were truly unfavorable or signals were missed.")
        return {"advice": advice}

    if summary["win_rate"] < 0.4:
        advice.append("Low win rate detected. Consider being more selective with trade entries.")

    if summary["expectancy"] < 0:
        advice.append("Negative expectancy. Avoid trading in weak or unclear market regimes.")

    if "downtrend" in summary.get("worst_regime", ""):
        advice.append("Most losses occurred in downtrend. Filtering downtrend trades may improve results.")

    if summary["trades"] > 5:
        advice.append("High trade count detected. Possible overtrading.")

    if not advice:
        advice.append("Good discipline today. Continue following your filters.")

    return {
        "confidence": round(len(advice) / 5, 2),
        "advice": advice
    }
