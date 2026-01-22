from learning.datasets import load_feature_dataset

def get_dataset(symbol: str | None = None):
    return load_feature_dataset(symbol=symbol)
