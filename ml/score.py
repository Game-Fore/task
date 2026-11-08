from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import psycopg

from ml.features import FEATURES, TARGET, build_features, load_dataset, select_samples, split_bounds
from ml.train import METADATA_FILE, MODELS

PREDICTION_COLUMNS = [
    "price_id", "loading_date", "loading_city_gcid", "unloading_city_gcid", "body_group",
    "actual_price_rub", "predicted_price_rub", "abs_error_rub", "ape_pct", "model_name",
]

log = logging.getLogger(__name__)


def build_predictions(rows: pd.DataFrame, predicted: np.ndarray, model_name: str, with_actual: bool) -> pd.DataFrame:
    out = rows[["price_id", "loading_date", "loading_city_gcid", "unloading_city_gcid", "body_group"]].copy()
    out["loading_date"] = pd.to_datetime(out["loading_date"]).dt.date
    out["predicted_price_rub"] = np.round(predicted, 2)
    if with_actual:
        actual = rows[TARGET].to_numpy(dtype=float)
        abs_error = np.abs(actual - predicted)
        out["actual_price_rub"] = np.round(actual, 2)
        out["abs_error_rub"] = np.round(abs_error, 2)
        out["ape_pct"] = np.round(abs_error / actual * 100, 4)
    else:
        # у будущих заявок факта ещё нет, даже если price в источнике заполнен
        out["actual_price_rub"] = np.nan
        out["abs_error_rub"] = np.nan
        out["ape_pct"] = np.nan
    out["model_name"] = model_name
    return out[PREDICTION_COLUMNS]


def score(dwh: psycopg.Connection, as_of, models_dir: Path) -> dict[str, int]:
    metadata = json.loads((models_dir / METADATA_FILE).read_text(encoding="utf-8"))
    if metadata["features"] != FEATURES or metadata["as_of"] != as_of.isoformat():
        raise RuntimeError("модели обучены с другим набором признаков или другим AS_OF — запустите `ml train`")

    bounds = split_bounds(as_of)
    written: dict[str, int] = {}
    with dwh.transaction():
        dwh.execute("SELECT pg_advisory_xact_lock(hashtext('ml_score'))")
        _, test, future = select_samples(load_dataset(dwh, bounds))
        x_test, x_future = build_features(test), build_features(future)
        for name in MODELS:
            model = joblib.load(models_dir / f"{name}.joblib")
            frames = [build_predictions(test, model.predict(x_test), name, with_actual=True)]
            if not future.empty:
                frames.append(build_predictions(future, model.predict(x_future), name, with_actual=False))
            predictions = pd.concat(frames, ignore_index=True)

            dwh.execute("DELETE FROM mart.ml_price_predictions WHERE model_name = %s AND loading_date >= %s",
                        (name, bounds.test_start))
            _copy_frame(dwh, predictions)
            written[name] = len(predictions)
            log.info("predictions written", extra={"step": "ml_score", "model": name, "test_rows": len(test),
                                                   "future_rows": len(future), "rows": len(predictions)})
    return written


def _copy_frame(dwh: psycopg.Connection, frame: pd.DataFrame) -> None:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, header=False)  # NaN станет пустым полем, то есть NULL
    columns = ", ".join(PREDICTION_COLUMNS)
    with dwh.cursor() as cur, cur.copy(f"COPY mart.ml_price_predictions ({columns}) FROM STDIN WITH (FORMAT csv)") as copy:
        copy.write(buffer.getvalue())
