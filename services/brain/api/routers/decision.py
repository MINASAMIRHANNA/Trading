from fastapi import APIRouter
from learning.datasets import load_feature_dataset
from learning.decision_engine import make_decision
from learning.strategy_engine import evaluate_strategy
from learning.strategies import STRATEGIES

router = APIRouter()

@router.get("/")
def decision(symbol: str | None = None):
    """
    Return trading decision based on strategy viability.
    """
    df = load_feature_dataset(symbol=symbol)

    strategies_stats = {}

    for name, strat in STRATEGIES.items():
        stats = evaluate_strategy(df, strat["filters"])
        strategies_stats[name] = {
            "trades": stats["trades"],
            "expectancy": stats["expectancy"],
            "max_drawdown": stats["max_drawdown"],
        }

    # Optional: detect current regime (simple version)
    current_regime = None
    if "market_regime_encoded" in df.columns and not df.empty:
        raw = df.iloc[-1]["market_regime_encoded"]
        try:
            enc = int(raw)
        except Exception:
            enc = None
        if enc == 1:
            current_regime = "uptrend"
        elif enc == 0:
            current_regime = "downtrend"
        else:
            current_regime = "unknown"

    decision_output = make_decision(
        strategies=strategies_stats,
        current_regime=current_regime,
    )

    return decision_output
