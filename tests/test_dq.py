"""DQ-правила, карантин и конвертация валют."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from etl.dq_rules import DQ_RULES
from tests.source_data import add_price


def quarantine_reasons(dwh, price_id: int) -> list[str] | None:
    row = dwh.execute("SELECT reasons FROM core.dq_quarantine_prices WHERE price_id = %s", (price_id,)).fetchone()
    return row[0] if row else None


def core_row(dwh, price_id: int):
    return dwh.execute("SELECT fx_rate, price_rub FROM core.prices WHERE price_id = %s", (price_id,)).fetchone()


@pytest.mark.parametrize(
    ("overrides", "expected_reasons"),
    [
        ({"price": 0}, ["PRICE_NON_POSITIVE"]),
        ({"price": -5}, ["PRICE_NON_POSITIVE"]),
        ({"price": 1000}, ["RUB_PRICE_LE_1000"]),
        ({"distance": 0}, ["DISTANCE_NON_POSITIVE"]),
        ({"total_weight": -1}, ["WEIGHT_NEGATIVE"]),
        ({"total_volume": -1}, ["VOLUME_NEGATIVE"]),
        ({"loading_city_gcid": 9999}, ["LOADING_CITY_UNKNOWN"]),
        ({"unloading_city_gcid": 9999}, ["UNLOADING_CITY_UNKNOWN"]),
        ({"currency_code": "156", "price": 5000}, ["UNSUPPORTED_CURRENCY"]),
        ({"currency_code": "840", "price": 900, "nearest_rate_date": None}, ["FX_RATE_DATE_MISSING"]),
        # курс есть только на 2026-09-12; на 13-е точного курса нет, fallback не применяется
        ({"currency_code": "978", "price": 900, "nearest_rate_date": date(2026, 9, 13)}, ["FX_RATE_NOT_FOUND"]),
        # одна строка — все нарушенные правила сразу
        ({"currency_code": "840", "price": 0, "nearest_rate_date": None}, ["PRICE_NON_POSITIVE", "FX_RATE_DATE_MISSING"]),
    ],
)
def test_invalid_row_goes_to_quarantine_with_reasons(source, dwh, run_load, overrides, expected_reasons):
    add_price(source, 1, **overrides)
    add_price(source, 2)  # валидная соседняя строка

    stats = run_load()

    assert quarantine_reasons(dwh, 1) == expected_reasons
    assert core_row(dwh, 1) is None
    assert core_row(dwh, 2) is not None
    assert (stats.core_prices, stats.quarantined) == (1, 1)


def test_quarantine_keeps_source_row(source, dwh, run_load):
    add_price(source, 1, price=0, currency_code="840", nearest_rate_date=None)
    run_load()

    raw_row = dwh.execute("SELECT raw_row FROM core.dq_quarantine_prices WHERE price_id = 1").fetchone()[0]
    assert raw_row["id"] == 1
    assert raw_row["currency_code"] == "840"
    assert raw_row["price"] == 0
    assert "dq_reasons" not in raw_row


def test_rule_codes_are_unique():
    codes = [rule.code for rule in DQ_RULES]
    assert len(codes) == len(set(codes))


def test_same_loading_and_unloading_city_is_not_rejected(source, dwh, run_load):
    add_price(source, 1, loading_city_gcid=1001, unloading_city_gcid=1001)
    run_load()

    assert quarantine_reasons(dwh, 1) is None
    assert core_row(dwh, 1) is not None


@pytest.mark.parametrize(
    ("overrides", "expected_rate", "expected_rub"),
    [
        ({"price": 1000.01}, 1.0, Decimal("1000.01")),                                  # граница RUB-правила
        ({"price": 84500, "nearest_rate_date": None}, 1.0, Decimal("84500.00")),        # RUB без даты курса
        ({"currency_code": "840", "price": 900}, 90.0, Decimal("81000.00")),            # USD по точной дате
        ({"currency_code": "978", "price": 500}, 100.0, Decimal("50000.00")),           # EUR <= 1000 — валидно
    ],
)
def test_valid_rows_are_converted_to_rub(source, dwh, run_load, overrides, expected_rate, expected_rub):
    add_price(source, 1, **overrides)
    run_load()

    assert quarantine_reasons(dwh, 1) is None
    assert core_row(dwh, 1) == (expected_rate, expected_rub)
