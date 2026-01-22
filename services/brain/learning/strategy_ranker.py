from typing import Dict, List
import numpy as np

# ----------------------------
# Weights (can be tuned)
# ----------------------------

WEIGHTS = {
    "expectancy": 0.4,
    "drawdown": 0.3,
    "stability": 0.3,
}

MIN_TRADES = 5


# ----------------------------
# Normalizers
# ----------------------------

def normalize_positive(value: float, cap: float) -> float:
    """
    Normalize positive metric (higher is better).
    """
    if value <= 0:
        return 0.0
    return min(value / cap, 1.0)


def normalize_negative(value: float, worst: float) -> float:
    """
    Normalize negative metric (closer to 0 is better).
    """
    if value <= worst:
        return 0.0
    return 1.0 - abs(value / worst)


# ----------------------------
# Core Ranking Logic
# ----------------------------

def rank_strategies(strategies: Dict[str, Dict]) -> List[Dict]:
    """
    Rank strategies from best to worst.
    """

    ranked = []

    for name, stats in strategies.items():
        trades = stats.get("trades", 0)
        expectancy = stats.get("expectancy", 0.0)
        max_dd = stats.get("max_drawdown", 0.0)

        if trades < MIN_TRADES:
            ranked.append({
                "strategy": name,
                "rank": None,
                "score": 0.0,
                "status": "INSUFFICIENT_DATA",
                "metrics": stats,
            })
            continue

        expectancy_score = normalize_positive(expectancy, cap=0.002)
        drawdown_score = normalize_negative(max_dd, worst=-0.1)
        stability_score = min(trades / 20, 1.0)

        total_score = (
            WEIGHTS["expectancy"] * expectancy_score +
            WEIGHTS["drawdown"] * drawdown_score +
            WEIGHTS["stability"] * stability_score
        )

        ranked.append({
            "strategy": name,
            "score": round(float(total_score), 3),
            "status": "RANKED",
            "metrics": stats,
        })

    # Sort ranked strategies
    ranked_sorted = sorted(
        ranked,
        key=lambda x: x["score"],
        reverse=True
    )

    # Assign ranks
    for i, r in enumerate(ranked_sorted, start=1):
        if r["status"] == "RANKED":
            r["rank"] = i
        else:
            r["rank"] = None

    return ranked_sorted
