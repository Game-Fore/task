from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ml.features import (CYCLICAL_PERIODS, FEATURES, FORBIDDEN_FEATURES, NUMERIC_FEATURES, SplitBounds,
                         assign_split, build_features, select_samples, split_bounds)
from ml.score import score
from ml.train import make_ridge, train_models
from tests.core_data import KAZAN, MOSCOW, SPB, add_deal, seed_cities

AS_OF = date(2026, 10, 26)
BOUNDS = SplitBounds(train_start=date(2026, 7, 26), test_start=date(2026, 10, 5), as_of=AS_OF)


def test_split_bounds_follow_the_task():
    assert split_bounds(AS_OF) == BOUNDS


@pytest.mark.parametrize(
    ("loading_date", "expected"),
    [
        (date(2026, 7, 25), None),          # раньше окна обучения
        (date(2026, 7, 26), "train"),       # начало train включительно
        (date(2026, 10, 4), "train"),
        (date(2026, 10, 5), "test"),        # граница входит только в test
        (date(2026, 10, 26), "test"),       # as_of включительно
        (date(2026, 10, 27), "future"),
    ],
)
def test_assign_split_boundaries(loading_date, expected):
    result = assign_split(pd.Series([pd.Timestamp(loading_date)]), BOUNDS).iloc[0]
    assert (None if pd.isna(result) else result) == expected


def _raw_rows(dates: list[date], **overrides) -> pd.DataFrame:
    base = {
        "distance": 1000.0, "total_weight": 20.0, "total_volume": 82.0,
        "origin_lat": 55.75, "origin_lon": 37.61, "dest_lat": 59.93, "dest_lon": 30.33,
        "origin_region": "г. Москва", "destination_region": "г. Санкт-Петербург",
        "origin_city": "Москва", "destination_city": "Санкт-Петербург",
        "body_group": "Тент", "body_type": 56, "weight_category": "FTL", "volume_category": "FTL",
    }
    return pd.DataFrame([{**base, **overrides, "loading_date": pd.Timestamp(d)} for d in dates])


def test_features_whitelist_has_no_target_derivatives():
    assert FORBIDDEN_FEATURES.isdisjoint(FEATURES)
    assert not [f for f in FEATURES if "price" in f or "outlier" in f]
    assert list(build_features(_raw_rows([date(2026, 9, 1)])).columns) == FEATURES


def test_cyclical_encoding_keeps_year_boundary_close():
    features = build_features(_raw_rows([date(2025, 12, 31), date(2026, 1, 1), date(2026, 7, 2)]))
    point = features[["day_of_year_sin", "day_of_year_cos"]].to_numpy()
    assert np.allclose((point ** 2).sum(axis=1), 1.0)                     # точки на единичной окружности
    assert np.linalg.norm(point[0] - point[1]) < 0.05                     # 31.12 и 1.01 — соседи
    assert np.linalg.norm(point[0] - point[2]) > 1.9                      # середина года — напротив
    assert set(CYCLICAL_PERIODS) == {"month", "day_of_week", "day_of_year"}


def test_missing_body_type_and_region_become_category():
    features = build_features(_raw_rows([date(2026, 9, 1)], body_type=None, origin_region=None))
    assert (features.loc[0, "body_type"], features.loc[0, "origin_region"]) == ("NA", "NA")


def test_outliers_cleaned_only_from_target_samples():
    df = pd.DataFrame({
        "split": ["train", "train", "test", "test", "future", "future", None],
        "outlier_mark": [False, True, False, True, False, True, False],
    })
    train, test, future = select_samples(df)
    assert (len(train), len(test), len(future)) == (1, 1, 2)


def test_ridge_preprocessing_is_fitted_on_train_only():
    train = build_features(_raw_rows([date(2026, 8, 1)] * 3, distance=100.0))
    train.loc[1, "distance"], train.loc[2, "distance"] = 200.0, 300.0
    test = build_features(_raw_rows([date(2026, 10, 10)] * 2, distance=10_000.0, origin_region="Новый регион"))

    model = make_ridge().fit(train, pd.Series([1.0, 2.0, 3.0]))
    model.predict(test)   # неизвестная категория в test не ломает скоринг

    scaler = model.named_steps["prep"].named_transformers_["num"].named_steps["scale"]
    assert scaler.mean_[NUMERIC_FEATURES.index("distance")] == pytest.approx(200.0)   # только train


@pytest.fixture
def ml_core(dwh):
    seed_cities(dwh)
    routes = [(MOSCOW, SPB, 700.0), (MOSCOW, KAZAN, 800.0), (SPB, KAZAN, 1500.0)]
    day = date(2026, 7, 26)
    i = 0
    while day <= date(2026, 11, 10):
        lc, uc, km = routes[i % 3]
        add_deal(dwh, round(72 * km + 6000 + 50 * (i % 7), 2), loading_date=day,
                 loading_city_gcid=lc, unloading_city_gcid=uc, distance=km,
                 outlier_mark=(day == date(2026, 10, 12)))
        day += timedelta(days=1)
        i += 1
    return dwh


def test_scoring_writes_test_and_future_predictions(ml_core, tmp_path):
    train_models(ml_core, AS_OF, tmp_path)
    written = score(ml_core, AS_OF, tmp_path)

    expected_rows = 21 + 15   # test: 22 дня минус выброс, future: 27.10–10.11
    assert written == {"catboost_v1": expected_rows, "ridge_v1": expected_rows}

    future_with_fact = ml_core.execute(
        "SELECT count(*) FROM mart.ml_price_predictions WHERE loading_date > %s "
        "AND (actual_price_rub IS NOT NULL OR abs_error_rub IS NOT NULL OR ape_pct IS NOT NULL)", (AS_OF,)
    ).fetchone()[0]
    assert future_with_fact == 0

    bad_errors = ml_core.execute(
        "SELECT count(*) FROM mart.ml_price_predictions WHERE loading_date <= %s "
        "AND abs(abs_error_rub - abs(actual_price_rub - predicted_price_rub)) > 0.01", (AS_OF,)
    ).fetchone()[0]
    assert bad_errors == 0


def test_scoring_is_idempotent_and_deterministic(ml_core, tmp_path):
    snapshot_sql = ("SELECT price_id, model_name, predicted_price_rub FROM mart.ml_price_predictions "
                    "ORDER BY price_id, model_name")
    train_models(ml_core, AS_OF, tmp_path)
    score(ml_core, AS_OF, tmp_path)
    first = ml_core.execute(snapshot_sql).fetchall()

    train_models(ml_core, AS_OF, tmp_path)   # переобучение с теми же seed
    score(ml_core, AS_OF, tmp_path)
    assert ml_core.execute(snapshot_sql).fetchall() == first
