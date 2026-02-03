from fastapi import APIRouter
from learning.datasets import load_feature_dataset
from learning.strategy_engine import evaluate_strategy
from learning.strategies import STRATEGIES

router = APIRouter()

@router.get("/")
def compare_strategies(symbol: str | None = None):
    df = load_feature_dataset(symbol=symbol)

    results = {}
    for name, strat in STRATEGIES.items():
        results[name] = {
            **evaluate_strategy(df, strat["filters"]),
            "description": strat["description"]
        }

    return results
