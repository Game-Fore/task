"""Справочник городов (дедупликация gc_id) и помесячная развёртка сделок."""

from __future__ import annotations

from datetime import date

from tests.source_data import add_price


def test_city_duplicates_resolved_to_min_id(source, dwh, run_load):
    source.execute("INSERT INTO cities (id, full_name_local, full_name_gc, gc_id, name) "
                   "VALUES (6, 'Байконур', 'Байконур', 1099, 'Байконур')")
    add_price(source, 1)
    run_load()

    cities = {row[0]: row[1:] for row in dwh.execute(
        "SELECT gc_id, source_city_id, city_name, region_name FROM core.dim_city"
    ).fetchall()}
    assert cities == {
        1001: (1, "Москва", "г. Москва"),
        1003: (2, "Казань", "Республика Татарстан"),   # не дубль id=4 «Казань г, Татарстан»
        1004: (3, "Екатеринбург", "Свердловская обл."),
        1099: (6, "Байконур", None),                   # без запятой — региона нет
    }


def test_join_with_duplicated_cities_does_not_multiply_prices(source, dwh, run_load):
    # 1001 и 1003 — оба дублированы в cities
    for price_id in (1, 2, 3):
        add_price(source, price_id, loading_city_gcid=1001, unloading_city_gcid=1003)
    run_load()

    assert dwh.execute("SELECT count(*), count(DISTINCT price_id) FROM core.prices").fetchone() == (3, 3)


def test_long_term_price_keeps_all_months(source, dwh, run_load):
    add_price(source, 1, loading_date=date(2026, 8, 20), end_loading_date=date(2026, 10, 5),
              price_dates=[date(2026, 8, 20), date(2026, 9, 20), date(2026, 10, 5)])
    run_load()

    months = [row[0] for row in dwh.execute(
        "SELECT month FROM core.price_dates WHERE price_id = 1 ORDER BY month").fetchall()]
    assert months == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]
