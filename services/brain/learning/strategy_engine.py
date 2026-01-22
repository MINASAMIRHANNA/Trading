import pandas as pd

def evaluate_strategy(df: pd.DataFrame, filters: dict) -> dict:
    filtered = df.copy()

    for col, allowed in filters.items():
        filtered = filtered[filtered[col].isin(allowed)]

    if filtered.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "expectancy": 0.0,
            "max_drawdown": 0.0,
        }

    pnl = filtered["pnl_pct"]

    equity = (1 + pnl).cumprod()
    drawdown = (equity / equity.cummax() - 1).min()

    return {
        "trades": int(len(filtered)),
        "win_rate": float((pnl > 0).mean()),
        "avg_pnl": float(pnl.mean()),
        "expectancy": float(pnl.mean()),
        "max_drawdown": float(drawdown),
    }
