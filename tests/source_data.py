from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import psycopg
from psycopg import sql

# тот же справочник, что в synthetic.sql
BODY_TYPES = [
    (1, "бортовая", 1, 15), (2, "изотермический", 2, 2), (3, "контейнер", 3, 3), (4, "рефрижератор", 4, 4),
    (5, "трал", 5, 5), (15, "борт", 15, 15), (26, "контейнерная площадка", 26, 3),
    (46, "рефрижератор мультирежимный", 46, 4), (47, "рефрижератор с перегородкой", 47, 4),
    (48, "рефрижератор-тушевоз", 48, 4), (50, "самосвал", 50, 50), (56, "тентованный", 56, 56),
    (57, "тент бок", 57, 56), (58, "тент верх", 58, 56), (59, "тент зад и бок", 59, 56),
    (60, "тент задняя загрузка", 60, 56), (61, "тент полная растентовка", 61, 56), (65, "фургон", 65, 65),
    (68, "цистерна", 68, 68),
]

# дубли gc_id: у Москвы то же имя, у Казани другое написание
CITIES = [
    (1, "Москва, г. Москва", 1001, 55.7558, 37.6173),
    (2, "Казань, Республика Татарстан", 1003, 55.7961, 49.1064),
    (3, "Екатеринбург, Свердловская обл.", 1004, 56.8389, 60.6057),
    (4, "Казань г, Татарстан", 1003, 55.7961, 49.1064),
    (5, "Москва, г. Москва", 1001, 55.7558, 37.6173),
]

RATE_DATE = date(2026, 9, 12)
RATES = {"643": 1.0, "840": 90.0, "978": 100.0}

DEFAULT_PRICE: dict[str, Any] = {
    "created_at": datetime(2026, 9, 12, 10, 0),
    "updated_at": datetime(2026, 9, 12, 10, 0),
    "subscriber_id": 101,
    "organization_id": 100001,
    "loading_date": date(2026, 9, 15),
    "loading_city_gcid": 1001,
    "unloading_city_gcid": 1003,
    "distance": 897.0,
    "total_weight": 20.0,
    "total_volume": 82.0,
    "body_type": 56,
    "price": 84500.0,
    "currency_code": "643",
    "complex": False,
    "price_type": 3,
    "is_fact": True,
    "nearest_rate_date": RATE_DATE,
    "outlier_mark": False,
    "weight_category": "FTL",
    "volume_category": "FTL",
}


def reset_source(conn: psycopg.Connection) -> None:
    conn.execute("TRUNCATE prices, price_body_types, price_dates, price_participants, cities, body_types, "
                 "exchange_rates, price_group_stats RESTART IDENTITY CASCADE")
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO body_types (id, name, "id_from_1C", std_id) VALUES (%s, %s, %s, %s)', BODY_TYPES)
        cur.executemany(
            "INSERT INTO cities (id, full_name_local, full_name_gc, gc_id, name, latitude, longitude) "
            "VALUES (%s, %s, %s, %s, split_part(%s, ',', 1), %s, %s)",
            [(cid, full, full, gc, full, lat, lon) for cid, full, gc, lat, lon in CITIES],
        )
        cur.executemany("INSERT INTO exchange_rates (num_code, value, setting_date) VALUES (%s, %s, %s)",
                        [(code, value, RATE_DATE) for code, value in RATES.items()])


def add_price(conn: psycopg.Connection, price_id: int, *, body_type_ids: Iterable[int] = (),
              price_dates: Iterable[date] | None = None, **overrides: Any) -> None:
    row = {**DEFAULT_PRICE, **overrides, "id": price_id}
    row.setdefault("end_loading_date", row["loading_date"])
    conn.execute(
        sql.SQL("INSERT INTO prices ({cols}) VALUES ({vals})").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, row)),
            vals=sql.SQL(", ").join(sql.Placeholder() * len(row)),
        ),
        list(row.values()),
    )
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO price_body_types (price_id, body_type_id) VALUES (%s, %s)",
                        [(price_id, bt) for bt in body_type_ids])
        cur.executemany("INSERT INTO price_dates (price_id, price_date) VALUES (%s, %s)",
                        [(price_id, d) for d in (price_dates or [row["loading_date"]])])
