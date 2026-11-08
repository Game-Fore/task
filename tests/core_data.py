from __future__ import annotations

from datetime import date
from itertools import count
from typing import Any, Iterable

import psycopg
from psycopg import sql

MOSCOW, SPB, KAZAN = 1001, 1002, 1003

CITIES = [
    (MOSCOW, 1, "Москва", "г. Москва", "Москва, г. Москва", 55.7558, 37.6173),
    (SPB, 2, "Санкт-Петербург", "г. Санкт-Петербург", "Санкт-Петербург, г. Санкт-Петербург", 59.9343, 30.3351),
    (KAZAN, 3, "Казань", "Республика Татарстан", "Казань, Республика Татарстан", 55.7961, 49.1064),
]

DEFAULT_CORE_PRICE: dict[str, Any] = {
    "loading_date": date(2026, 9, 15),
    "loading_city_gcid": MOSCOW,
    "unloading_city_gcid": SPB,
    "distance": 1000.0,
    "total_weight": 20.0,
    "total_volume": 82.0,
    "body_type": 56,
    "body_group": "Тент",
    "organization_id": 1,
    "price_type": 3,
    "is_fact": True,
    "complex": False,
    "outlier_mark": False,
    "currency_code": "643",
    "fx_rate": 1.0,
    "weight_category": "FTL",
    "volume_category": "FTL",
}

_ids = count(1)


def seed_cities(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO core.dim_city (gc_id, source_city_id, city_name, region_name, full_name_local, "
            "latitude, longitude) VALUES (%s, %s, %s, %s, %s, %s, %s)", CITIES)


def add_deal(conn: psycopg.Connection, price_rub: float, *, dates: Iterable[date] | None = None,
             groups: Iterable[str] = ("Тент",), **overrides: Any) -> int:
    price_id = next(_ids)
    row = {**DEFAULT_CORE_PRICE, **overrides, "price_id": price_id, "price": price_rub, "price_rub": price_rub}
    conn.execute(
        sql.SQL("INSERT INTO core.prices ({cols}) VALUES ({vals})").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, row)),
            vals=sql.SQL(", ").join(sql.Placeholder() * len(row)),
        ),
        list(row.values()),
    )
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO core.price_dates (price_id, price_date, month) "
                        "VALUES (%s, %s, date_trunc('month', %s::date)::date)",
                        [(price_id, d, d) for d in (dates or [row["loading_date"]])])
        cur.executemany("INSERT INTO core.price_body_groups (price_id, body_group) VALUES (%s, %s)",
                        [(price_id, g) for g in groups])
    return price_id
