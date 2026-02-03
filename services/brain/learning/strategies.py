STRATEGIES = {
    "Baseline": {
        "description": "All trades without filters",
        "filters": {}
    },
    "Uptrend Only": {
        "description": "Trade only during uptrend regimes",
        "filters": {
            "market_regime_encoded": [1]
        }
    },
    "Counter Trend": {
        "description": "Trade only counter-trend setups",
        "filters": {
            "directional_alignment": [-1]
        }
    },
    "Uptrend + Counter": {
        "description": "Counter-trend trades inside uptrend regimes",
        "filters": {
            "market_regime_encoded": [1],
            "directional_alignment": [-1]
        }
    },
}
