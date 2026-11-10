from __future__ import annotations

import dataclasses
import os
from datetime import date
from decimal import Decimal

import pytest

from common.config import load_clickhouse_config
from common.db import connect
from etl.clickhouse import compare_stats, connect_clickhouse, sync_clickhouse
from tests.conftest import AS_OF, DWH_TEST_DB
from tests.core_data import add_deal, seed_cities

OCT = date(2026, 10, 1)
# ключ, trips, carriers, last_price_date, mom, yoy, reliability, 7 денежных метрик, cv
ROW = (OCT, 1001, 1002, "Тент", "FTL", 2, 1, date(2026, 10, 10), None, None, "LOW_DATA",
       *[Decimal("100.00")] * 7, Decimal("0.0100"))


def _with(row: tuple, index: int, value) -> tuple:
    return row[:index] + (value,) + row[index + 1:]


def test_parity_accepts_identical_marts():
    report = compare_stats([ROW], [ROW])
    assert report.ok and report.cells_off_by_cent == 0


@pytest.mark.parametrize(
    ("index", "value", "ok"),
    [
        (5, 3, False),                    # другое число сделок
        (8, Decimal("6.00"), False),      # MoM посчитан с другим масштабом
        (10, "MEDIUM", False),            # другой уровень надёжности
        (12, Decimal("100.01"), True),    # копейка в медиане — в допуске
        (12, Decimal("100.02"), False),
    ],
)
def test_parity_detects_differences(index, value, ok):
    assert compare_stats([ROW], [_with(ROW, index, value)]).ok is ok


def test_parity_detects_missing_cell():
    assert not compare_stats([ROW], []).ok


needs_clickhouse = pytest.mark.skipif(not os.environ.get("CLICKHOUSE_HOST"), reason="ClickHouse не поднят")


@pytest.fixture
def clickhouse():
    cfg = dataclasses.replace(load_clickhouse_config(), database="mart_test")
    client = connect_clickhouse(cfg)
    client.command("DROP DATABASE IF EXISTS mart_test")
    yield connect_clickhouse(cfg)
    client.command("DROP DATABASE IF EXISTS mart_test")


@needs_clickhouse
def test_sync_matches_postgres_including_rounding_ties(dwh, run_mart, settings, clickhouse):
    seed_cities(dwh)
    # медиана двух сделок 96964.895: во float это 96964.89499…, обе витрины должны дать .90
    add_deal(dwh, 96964.89, loading_date=date(2026, 10, 5), organization_id=1)
    add_deal(dwh, 96964.90, loading_date=date(2026, 10, 6), organization_id=2)
    add_deal(dwh, 90000.00, loading_date=date(2026, 9, 6))
    run_mart()

    with connect(settings.db, DWH_TEST_DB) as conn:
        report = sync_clickhouse(conn, clickhouse, date(2023, 1, 1), AS_OF)

    assert report.ok and report.cells_ch == 2 and report.cells_off_by_cent == 0
    median, mom = clickhouse.query(
        "SELECT median_trip, mom_pct FROM route_card WHERE month = {m:Date}", parameters={"m": OCT}).result_rows[0]
    assert (median, mom) == (Decimal("96964.90"), Decimal("7.74"))


@needs_clickhouse
def test_resync_replaces_partitions_and_drops_emptied_month(dwh, run_mart, settings, clickhouse):
    seed_cities(dwh)
    september = add_deal(dwh, 90000.00, loading_date=date(2026, 9, 6))
    add_deal(dwh, 95000.00, loading_date=date(2026, 10, 6))
    run_mart()
    with connect(settings.db, DWH_TEST_DB) as conn:
        sync_clickhouse(conn, clickhouse, date(2023, 1, 1), AS_OF)
        sync_clickhouse(conn, clickhouse, date(2023, 1, 1), AS_OF)
    assert clickhouse.query("SELECT count() FROM market_deals").result_rows[0][0] == 2

    for table in ("core.price_dates", "core.price_body_groups", "core.prices"):
        dwh.execute(f"DELETE FROM {table} WHERE price_id = %s", (september,))
    run_mart(start=date(2026, 9, 1))
    with connect(settings.db, DWH_TEST_DB) as conn:
        report = sync_clickhouse(conn, clickhouse, date(2026, 9, 1), AS_OF)

    assert report.ok
    assert clickhouse.query("SELECT groupArray(month) FROM route_month_stats").result_rows[0][0] == [OCT]
