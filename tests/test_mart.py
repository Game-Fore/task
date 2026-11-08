"""Витрина карточки маршрута: коридор ставок, доказательная база, MoM/YoY, надёжность, идемпотентность."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from psycopg.rows import dict_row

from tests.core_data import KAZAN, MOSCOW, SPB, add_deal, seed_cities

SEP_2026 = date(2026, 9, 1)


@pytest.fixture
def core(dwh):
    seed_cities(dwh)
    return dwh


def cell(dwh, month: date, *, loading=MOSCOW, unloading=SPB, body_group="Тент", weight_category="FTL"):
    with dwh.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT * FROM mart.mart_route_card WHERE month = %s AND loading_city_gcid = %s "
            "AND unloading_city_gcid = %s AND body_group = %s AND weight_category = %s",
            (month, loading, unloading, body_group, weight_category),
        ).fetchone()


def test_corridor_and_data_trust_metrics(core, run_mart):
    add_deal(core, 100_000, price_type=3, organization_id=1)
    add_deal(core, 200_000, price_type=9, organization_id=2)
    add_deal(core, 300_000, price_type=3, organization_id=1)   # тот же перевозчик
    add_deal(core, 400_000, price_type=1, organization_id=3)   # грузовладелец — не перевозчик
    run_mart()

    c = cell(core, SEP_2026)
    # percentile_cont интерполирует: P25 = 100k + 0.75 × (200k − 100k)
    assert (c["p25_trip"], c["median_trip"], c["p75_trip"], c["avg_trip"]) == (
        Decimal("175000.00"), Decimal("250000.00"), Decimal("325000.00"), Decimal("250000.00"))
    assert (c["p25_km"], c["median_km"], c["p75_km"]) == (Decimal("175.00"), Decimal("250.00"), Decimal("325.00"))
    assert (c["trips_count"], c["carriers_count"]) == (4, 2)
    assert c["cv_rate"] == Decimal("0.5164")   # stddev_samp(1,2,3,4 × 10⁵) / 250 000
    assert (c["loading_city"], c["unloading_region"]) == ("Москва", "г. Санкт-Петербург")


def test_cv_rate_is_null_for_single_observation(core, run_mart):
    add_deal(core, 100_000)
    run_mart()

    c = cell(core, SEP_2026)
    assert (c["trips_count"], c["cv_rate"]) == (1, None)


def test_out_of_scope_deals_are_excluded(core, run_mart):
    add_deal(core, 100_000)
    add_deal(core, 999_000, price_type=6, is_fact=False)   # ставка торгов
    add_deal(core, 999_000, complex=True)
    add_deal(core, 999_000, outlier_mark=True)
    run_mart()

    c = cell(core, SEP_2026)
    assert (c["trips_count"], c["median_trip"]) == (1, Decimal("100000.00"))


def test_deal_with_two_body_groups_counted_once_in_each(core, run_mart):
    add_deal(core, 100_000, groups=("Тент", "Борт"))
    run_mart()

    assert cell(core, SEP_2026, body_group="Тент")["trips_count"] == 1
    assert cell(core, SEP_2026, body_group="Борт")["trips_count"] == 1


def test_month_comes_from_price_dates_and_future_dates_are_excluded(core, run_mart):
    add_deal(core, 100_000, loading_date=date(2026, 8, 20),
             dates=[date(2026, 8, 20), date(2026, 9, 20), date(2026, 10, 28), date(2026, 11, 20)])
    run_mart()

    months = [r[0] for r in core.execute("SELECT month FROM mart.route_month_stats ORDER BY month").fetchall()]
    assert months == [date(2026, 8, 1), date(2026, 9, 1)]   # 28.10 и 20.11 позже as_of = 26.10


def test_mom_and_yoy_compare_only_calendar_neighbours(core, run_mart):
    add_deal(core, 100_000, loading_date=date(2025, 9, 10))
    add_deal(core, 100_000, loading_date=date(2026, 8, 10))
    add_deal(core, 110_000, loading_date=date(2026, 9, 10))
    run_mart()

    sep = cell(core, SEP_2026)
    assert (sep["mom_pct"], sep["yoy_pct"]) == (Decimal("10.00"), Decimal("10.00"))
    aug = cell(core, date(2026, 8, 1))
    # июля 2026 и августа 2025 нет — NULL, а не сравнение с «последним доступным» месяцем
    assert (aug["mom_pct"], aug["yoy_pct"]) == (None, None)


@pytest.mark.parametrize(
    ("trips", "carriers", "last_date", "expected"),
    [
        (30, 5, date(2026, 10, 20), "HIGH"),
        (30, 5, date(2026, 9, 26), "HIGH"),      # ровно 30 дней до as_of
        (30, 5, date(2026, 9, 25), "MEDIUM"),    # 31 день — несвежая
        (30, 4, date(2026, 10, 20), "MEDIUM"),   # мало перевозчиков
        (10, 0, date(2026, 10, 20), "MEDIUM"),
        (9, 0, date(2026, 10, 20), "LOW_DATA"),
    ],
)
def test_reliability_level(core, run_mart, trips, carriers, last_date, expected):
    for i in range(trips):
        is_carrier = i < carriers
        add_deal(core, 100_000 + i, loading_date=last_date,
                 price_type=3 if is_carrier else 1, organization_id=i + 1 if is_carrier else 999)
    run_mart()

    assert cell(core, last_date.replace(day=1))["reliability_level"] == expected


def snapshot(dwh) -> list[tuple]:
    return dwh.execute(
        "SELECT (to_jsonb(s) - 'refreshed_at')::text FROM mart.route_month_stats s ORDER BY 1").fetchall()


def test_refresh_is_idempotent_and_partial_refresh_keeps_earlier_months(core, run_mart):
    add_deal(core, 100_000, loading_date=date(2026, 8, 10))
    add_deal(core, 120_000, loading_date=date(2026, 9, 10), loading_city_gcid=KAZAN)
    add_deal(core, 130_000, loading_date=date(2026, 10, 10), dates=[date(2026, 10, 10)])
    run_mart()
    first = snapshot(core)

    run_mart()
    assert snapshot(core) == first

    refreshed_before = dict(core.execute("SELECT month, refreshed_at FROM mart.route_month_stats").fetchall())
    run_mart(start=date(2026, 10, 1))
    assert snapshot(core) == first
    refreshed_after = dict(core.execute("SELECT month, refreshed_at FROM mart.route_month_stats").fetchall())
    unchanged = {m for m in refreshed_after if refreshed_after[m] == refreshed_before[m]}
    assert unchanged == {date(2026, 8, 1), date(2026, 9, 1)}   # пересчитан только октябрь
