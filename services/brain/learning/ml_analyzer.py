import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline


FEATURE_COLS = [
    "entry_vs_close_pct",
    "entry_vs_ema_20_pct",
    "atr_pct_at_entry",
    "market_regime_encoded",
    "directional_alignment"
]

TARGET_COL = "pnl_positive"


def prepare_ml_dataset(df: pd.DataFrame):
    """
    Prepare dataset for ML:
    - Binary target: pnl_positive
    - Drop NaNs
    """
    data = df.copy()

    data["pnl_positive"] = (data["pnl_pct"] > 0).astype(int)

    data = data.dropna(subset=FEATURE_COLS + [TARGET_COL])

    X = data[FEATURE_COLS]
    y = data[TARGET_COL]

    return X, y


def train_logistic_model(X, y):
    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)

    importance = pd.Series(
        model.coef_[0],
        index=X.columns
    ).sort_values(ascending=False)

    return model, importance


def train_decision_tree(X, y, max_depth=3):
    model = DecisionTreeClassifier(
        max_depth=max_depth,
        min_samples_leaf=2
    )
    model.fit(X, y)

    importance = pd.Series(
        model.feature_importances_,
        index=X.columns
    ).sort_values(ascending=False)

    return model, importance
