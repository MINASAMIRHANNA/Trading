from fastapi import APIRouter
from api.deps import get_dataset
from learning.ml_analyzer import prepare_ml_dataset, train_logistic_model

router = APIRouter()


@router.get("/importance")
def feature_importance(symbol: str | None = None):
    df = get_dataset(symbol)

    X, y = prepare_ml_dataset(df)
    _, importance = train_logistic_model(X, y)

    # تحويل كل القيم لـ Python float
    return {feature: float(value) for feature, value in importance.to_dict().items()}
