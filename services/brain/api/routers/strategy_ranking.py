from fastapi import APIRouter
from learning.datasets import load_feature_dataset
from learning.strategy_ranker import rank_strategies
from learning.strategy_engine import evaluate_strategy
from learning.strategies import STRATEGIES

router = APIRouter()

@router.get("/")
def strategy_ranking(symbol: str | None = None):
    """
    Rank all available strategies based on performance and risk.
    """
    df = load_feature_dataset(symbol)

    strategies_stats = {}

    for name, strat in STRATEGIES.items():
        stats = evaluate_strategy(df, strat["filters"])
        strategies_stats[name] = {
            "trades": stats["trades"],
            "expectancy": stats["expectancy"],
            "max_drawdown": stats["max_drawdown"],
        }

    ranking = rank_strategies(strategies_stats)
    return ranking
