from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
import psycopg

TARGET = "price_rub"
FACT_PRICE_TYPES = (1, 2, 3, 4, 5, 9)

CYCLICAL_PERIODS = {"month": 12, "day_of_week": 7, "day_of_year": 365.25}

NUMERIC_FEATURES = [
    "distance", "total_weight", "total_volume",
    "origin_lat", "origin_lon", "dest_lat", "dest_lon",
    "year", "month", "day_of_week", "day_of_year",
    *(f"{name}_{fn}" for name in CYCLICAL_PERIODS for fn in ("sin", "cos")),
]
CATEGORICAL_FEATURES = [
    "origin_region", "destination_region", "origin_city", "destination_city",
    "body_group", "body_type", "weight_category", "volume_category",
]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# производные таргета и флаг очистки — в признаки не попадают
FORBIDDEN_FEATURES = {
    "price", "price_rub", "price_with_vat", "price_km", "price_per_km", "price_per_ton",
    "avg_price", "min_km_price", "max_km_price", "price_group_id",
    "transportation_cost", "customer_cost", "carrier_cost", "profit",
    "outlier_mark", "fx_rate",
}

MISSING_CATEGORY = "NA"


@dataclass(frozen=True)
class SplitBounds:
    train_start: date
    test_start: date
    as_of: date


def split_bounds(as_of: date) -> SplitBounds:
    ts = pd.Timestamp(as_of)
    return SplitBounds(
        train_start=(ts - pd.DateOffset(months=3)).date(),
        test_start=(ts - pd.Timedelta(weeks=3)).date(),
        as_of=as_of,
    )


_DATASET_QUERY = """
    SELECT p.price_id, p.loading_date, p.loading_city_gcid, p.unloading_city_gcid,
           p.distance, p.total_weight, p.total_volume, p.body_group, p.body_type,
           p.weight_category, p.volume_category, p.outlier_mark, p.price_rub,
           lc.city_name AS origin_city, lc.region_name AS origin_region,
           lc.latitude  AS origin_lat,  lc.longitude   AS origin_lon,
           uc.city_name AS destination_city, uc.region_name AS destination_region,
           uc.latitude  AS dest_lat,    uc.longitude   AS dest_lon
    FROM core.prices p
    JOIN core.dim_city lc ON lc.gc_id = p.loading_city_gcid
    JOIN core.dim_city uc ON uc.gc_id = p.unloading_city_gcid
    WHERE p.price_type = ANY(%(fact_types)s)
      AND NOT p.complex
      AND p.loading_date >= %(train_start)s
    ORDER BY p.price_id
"""


def load_dataset(conn: psycopg.Connection, bounds: SplitBounds) -> pd.DataFrame:
    # порядок строк фиксирован: от него зависят перестановки CatBoost
    with conn.cursor() as cur:
        cur.execute(_DATASET_QUERY, {"fact_types": list(FACT_PRICE_TYPES), "train_start": bounds.train_start})
        columns = [c.name for c in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=columns)
    df["loading_date"] = pd.to_datetime(df["loading_date"])
    df[TARGET] = df[TARGET].astype(float)
    df["split"] = assign_split(df["loading_date"], bounds)
    return df


def assign_split(loading_date: pd.Series, bounds: SplitBounds) -> pd.Series:
    d = pd.to_datetime(loading_date)
    train_start, test_start, as_of = (pd.Timestamp(x) for x in (bounds.train_start, bounds.test_start, bounds.as_of))
    split = pd.Series(pd.NA, index=d.index, dtype="object")
    split[(d >= train_start) & (d < test_start)] = "train"
    split[(d >= test_start) & (d <= as_of)] = "test"
    split[d > as_of] = "future"
    return split


def select_samples(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # outlier_mark чистит только таргет train/test; у будущих заявок таргета нет
    clean = ~df["outlier_mark"].astype(bool)
    train = df[(df["split"] == "train") & clean]
    test = df[(df["split"] == "test") & clean]
    future = df[df["split"] == "future"]
    return train, test, future


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    d = pd.to_datetime(df["loading_date"])
    out = pd.DataFrame(index=df.index)
    for col in ("distance", "total_weight", "total_volume", "origin_lat", "origin_lon", "dest_lat", "dest_lon"):
        out[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    parts = {"year": d.dt.year, "month": d.dt.month, "day_of_week": d.dt.dayofweek, "day_of_year": d.dt.dayofyear}
    for name, values in parts.items():
        out[name] = values.astype(int)
    for name, period in CYCLICAL_PERIODS.items():
        angle = 2 * np.pi * parts[name] / period
        out[f"{name}_sin"] = np.sin(angle)
        out[f"{name}_cos"] = np.cos(angle)

    for col in CATEGORICAL_FEATURES:
        values = df[col]
        if col == "body_type":
            values = values.map(lambda v: MISSING_CATEGORY if pd.isna(v) else str(int(v)))
        out[col] = values.fillna(MISSING_CATEGORY).astype(str)

    return out[FEATURES]
