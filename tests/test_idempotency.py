from __future__ import annotations

from datetime import date

import pytest
from psycopg import sql

from tests.source_data import add_price

OCTOBER = (date(2026, 10, 1), date(2026, 10, 31))

# колонки времени загрузки меняются на каждом прогоне, их не сравниваем
FINGERPRINT_TABLES = {
    "raw.prices": ["_loaded_at"],
    "raw.price_body_types": ["_loaded_at"],
    "raw.price_dates": ["_loaded_at"],
    "core.dim_city": [],
    "core.dim_body_type": [],
    "core.exchange_rates": [],
    "core.prices": ["loaded_at"],
    "core.price_body_groups": [],
    "core.price_dates": [],
    "core.dq_quarantine_prices": ["quarantined_at"],
}


def fingerprint(dwh) -> dict[str, tuple[int, str]]:
    result = {}
    for table, technical in FINGERPRINT_TABLES.items():
        schema, name = table.split(".")
        row_text = sql.SQL("(to_jsonb(t) - {cols}::text[])::text").format(cols=sql.Literal(technical))
        query = sql.SQL("SELECT count(*), md5(coalesce(string_agg({r}, '|' ORDER BY {r}), '')) FROM {tbl} t").format(
            r=row_text, tbl=sql.Identifier(schema, name))
        result[table] = dwh.execute(query).fetchone()
    return result


@pytest.fixture
def seeded_source(source):
    add_price(source, 1, loading_date=date(2026, 9, 10))
    add_price(source, 2, loading_date=date(2026, 9, 20), body_type_ids=[56, 15])
    add_price(source, 3, loading_date=date(2026, 9, 25), price=0)                      # в карантин
    add_price(source, 4, loading_date=date(2026, 10, 3), currency_code="840", price=900)
    add_price(source, 5, loading_date=date(2026, 10, 15), end_loading_date=date(2026, 12, 15),
              price_dates=[date(2026, 10, 15), date(2026, 11, 15), date(2026, 12, 15)])
    add_price(source, 6, loading_date=date(2026, 10, 20), currency_code="978", nearest_rate_date=None)  # в карантин
    return source


def test_rerun_same_window_changes_nothing(seeded_source, dwh, run_load):
    first_stats = run_load()
    first = fingerprint(dwh)
    second_stats = run_load()

    assert fingerprint(dwh) == first
    assert (first_stats.core_prices, first_stats.quarantined) == (4, 2)
    assert (second_stats.core_prices, second_stats.quarantined) == (4, 2)


def test_rerun_of_narrow_window_keeps_rows_outside(seeded_source, dwh, run_load):
    run_load()
    before = fingerprint(dwh)
    loaded_at_before = dict(dwh.execute("SELECT price_id, loaded_at FROM core.prices").fetchall())

    run_load(*OCTOBER)

    assert fingerprint(dwh) == before
    loaded_at_after = dict(dwh.execute("SELECT price_id, loaded_at FROM core.prices").fetchall())
    assert {pid for pid in loaded_at_after if loaded_at_after[pid] == loaded_at_before[pid]} == {1, 2}  # сентябрь не тронут
    assert {pid for pid in loaded_at_after if loaded_at_after[pid] != loaded_at_before[pid]} == {4, 5}  # октябрь перезаписан


def test_row_deleted_in_source_disappears_after_rerun(seeded_source, dwh, run_load):
    run_load()
    seeded_source.execute("DELETE FROM prices WHERE id = 5")  # дочерние строки удалятся каскадом

    run_load(*OCTOBER)

    assert dwh.execute("SELECT count(*) FROM core.prices WHERE price_id = 5").fetchone()[0] == 0
    assert dwh.execute("SELECT count(*) FROM core.price_dates WHERE price_id = 5").fetchone()[0] == 0
    assert dwh.execute("SELECT count(*) FROM raw.prices WHERE id = 5").fetchone()[0] == 0
    assert sorted(r[0] for r in dwh.execute("SELECT price_id FROM core.prices").fetchall()) == [1, 2, 4]


def test_window_with_start_after_end_is_rejected(source, run_load):
    with pytest.raises(ValueError):
        run_load(date(2026, 10, 31), date(2026, 10, 1))
