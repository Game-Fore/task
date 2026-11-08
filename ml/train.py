from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import joblib
import psycopg
from catboost import CatBoostRegressor
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.features import (CATEGORICAL_FEATURES, FEATURES, NUMERIC_FEATURES, TARGET, build_features,
                         load_dataset, select_samples, split_bounds)
from ml.metrics import regression_metrics

SEED = 42
METADATA_FILE = "metadata.json"

# параметры фиксированы: подбирать итерации по test было бы утечкой
CATBOOST_PARAMS = {
    "loss_function": "RMSE",
    "iterations": 1000,
    "learning_rate": 0.05,
    "depth": 6,
    "random_seed": SEED,
    "thread_count": 4,  # от числа потоков зависит результат, фиксируем ради воспроизводимости
    "verbose": False,
    "allow_writing_files": False,
}

log = logging.getLogger(__name__)


def make_catboost() -> CatBoostRegressor:
    return CatBoostRegressor(**CATBOOST_PARAMS, cat_features=CATEGORICAL_FEATURES)


def make_ridge() -> Pipeline:
    # весь препроцессинг внутри Pipeline, поэтому fit на train не подсматривает в test
    numeric = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    preprocess = ColumnTransformer([
        ("num", numeric, NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    return Pipeline([("prep", preprocess), ("model", Ridge(alpha=1.0))])


MODELS: dict[str, Callable[[], object]] = {"catboost_v1": make_catboost, "ridge_v1": make_ridge}


def train_models(dwh: psycopg.Connection, as_of, models_dir: Path) -> dict[str, dict[str, float]]:
    bounds = split_bounds(as_of)
    dataset = load_dataset(dwh, bounds)
    train, test, future = select_samples(dataset)
    log.info("dataset loaded", extra={"step": "ml_train", "train_start": bounds.train_start,
                                      "test_start": bounds.test_start, "as_of": bounds.as_of,
                                      "train_rows": len(train), "test_rows": len(test), "future_rows": len(future)})
    if train.empty or test.empty:
        raise RuntimeError("пустая train или test выборка — проверьте загрузку core и AS_OF")

    x_train, y_train = build_features(train), train[TARGET]
    x_test, y_test = build_features(test), test[TARGET]

    models_dir.mkdir(parents=True, exist_ok=True)
    metrics: dict[str, dict[str, float]] = {}
    for name, factory in MODELS.items():
        model = factory()
        model.fit(x_train, y_train)
        metrics[name] = regression_metrics(y_test, model.predict(x_test))
        _atomic_dump(model, models_dir / f"{name}.joblib")
        log.info("model trained", extra={"step": "ml_train", "model": name, "test_rows": len(test), **metrics[name]})

    metadata = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": bounds.as_of.isoformat(),
        "train_start": bounds.train_start.isoformat(),
        "test_start": bounds.test_start.isoformat(),
        "train_rows": len(train),
        "test_rows": len(test),
        "features": FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "catboost_params": CATBOOST_PARAMS,
        "test_metrics": metrics,
    }
    tmp = models_dir / f"{METADATA_FILE}.tmp"
    tmp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, models_dir / METADATA_FILE)
    return metrics


def _atomic_dump(model: object, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    joblib.dump(model, tmp)
    os.replace(tmp, path)
