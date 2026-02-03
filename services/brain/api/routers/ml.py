import os

from fastapi import APIRouter

from api.deps import get_dataset
from learning.ml_analyzer import prepare_ml_dataset, train_logistic_model

router = APIRouter()


@router.get("/importance")
def feature_importance(symbol: str | None = None):
    """Return feature importance for the current dataset.

    Safe defaults: if there isn't enough data to train a model (or the target has one class),
    return an empty dict rather than 500.
    """

    df = get_dataset(symbol=symbol)
    min_samples = int(os.getenv("ML_MIN_SAMPLES", "20"))

    if df is None or len(df) < min_samples:
        return {}

    X, y = prepare_ml_dataset(df)

    if X is None or len(X) < min_samples:
        return {}

    # Need both classes for a classifier
    try:
        if hasattr(y, "nunique") and y.nunique() < 2:
            return {}
    except Exception:
        return {}

    try:
        _, importance = train_logistic_model(X, y)
    except Exception:
        return {}

    # Convert to plain dict
    return importance.to_dict()
