from typing import Dict, List
import numpy as np


# ----------------------------
# Configuration (can be tuned)
# ----------------------------

MIN_TRADES_REQUIRED = 5
MIN_EXPECTANCY = 0.0
MAX_ACCEPTABLE_DRAWDOWN = -0.05
CONFIDENCE_CAP = 0.95


# ----------------------------
# Helper Scorers
# ----------------------------

def score_expectancy(expectancy: float) -> float:
    if expectancy <= 0:
        return 0.0
    return min(expectancy * 1000, 1.0)


def score_drawdown(max_dd: float) -> float:
    if max_dd < MAX_ACCEPTABLE_DRAWDOWN:
        return 0.0
    return 1.0 - abs(max_dd)


def score_sample_size(trades: int) -> float:
    return min(trades / MIN_TRADES_REQUIRED, 1.0)


# ----------------------------
# Core Decision Logic
# ----------------------------

def evaluate_strategy_viability(stats: Dict) -> Dict:
    """
    Evaluate a single strategy and return a viability score.
    """

    trades = stats["trades"]
    expectancy = stats["expectancy"]
    max_dd = stats["max_drawdown"]

    if trades < MIN_TRADES_REQUIRED:
        return {
            "viable": False,
            "reason": "Insufficient sample size",
            "score": 0.0,
            "metrics": {
                "trades": trades,
                "expectancy": None,
                "max_drawdown": None,
            },
        }

    expectancy_score = score_expectancy(expectancy)
    drawdown_score = score_drawdown(max_dd)
    sample_score = score_sample_size(trades)

    total_score = np.mean([
        expectancy_score,
        drawdown_score,
        sample_score,
    ])

    return {
        "viable": expectancy > MIN_EXPECTANCY and max_dd >= MAX_ACCEPTABLE_DRAWDOWN,
        "score": round(float(total_score), 3),
        "metrics": {
            "expectancy": expectancy,
            "max_drawdown": max_dd,
            "trades": trades,
        },
    }


# ----------------------------
# Decision Engine
# ----------------------------

def make_decision(
    strategies: Dict[str, Dict],
    current_regime: str | None = None,
) -> Dict:
    """
    Main decision engine.
    """

    evaluated = {}

    for name, stats in strategies.items():
        evaluated[name] = evaluate_strategy_viability(stats)
    progress = calculate_data_progress(strategies)

    # Filter viable strategies
    viable = {
        name: v for name, v in evaluated.items()
        if v["viable"]
    }

    if not viable:

        return {
            "decision": "DO_NOT_TRADE",
            "confidence": 0.9,
            "reason": "No strategy meets minimum viability criteria",
            "recommended_strategy": None,
            "data_progress": progress,
            "details": evaluated,
            "warnings": [
                "Capital preservation mode",
                "Wait for better market conditions",
            ],
            "execution_plan": {
                "allowed": False,
                "reason": "Execution disabled in v1",
                "dry_run_available": True
        }
        }

    # Pick best strategy by score
    best_strategy = max(
        viable.items(),
        key=lambda x: x[1]["score"]
    )

    confidence = min(
        best_strategy[1]["score"],
        CONFIDENCE_CAP
    )

    warnings: List[str] = []

    if current_regime and "downtrend" in current_regime.lower():
        warnings.append("Current market regime is unfavorable")

    if best_strategy[1]["metrics"]["expectancy"] < 0.0001:
        warnings.append("Edge is weak — trade selectively")

    return {
        "decision": "TRADE_SELECTIVELY",
        "recommended_strategy": best_strategy[0],
        "confidence": round(confidence, 2),
        "details": evaluated,
        "warnings": warnings,
    }
def calculate_data_progress(strategies: Dict) -> float:
    """
    Calculate progress toward minimum viable dataset.
    """
    trades_counts = [
        s.get("trades", 0)
        for s in strategies.values()
    ]

    if not trades_counts:
        return 0.0

    avg_trades = sum(trades_counts) / len(trades_counts)
    progress = min(avg_trades / MIN_TRADES_REQUIRED, 1.0)

    return round(progress, 2)
