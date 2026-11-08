from __future__ import annotations

import pytest

from tests.source_data import add_price


@pytest.mark.parametrize(
    ("weight", "expected"),
    [
        (0.0, "OTH"), (0.44, "OTH"),
        (0.45, "L5T"),                  # 0.45 → 0.5, округление не банковское
        (0.5, "L5T"), (2.44, "L5T"),
        (2.45, "5T"), (2.5, "5T"), (4.94, "5T"),
        (4.95, "10T"), (5.0, "10T"), (9.94, "10T"),
        (9.95, "FTL"), (10.0, "FTL"), (29.94, "FTL"),
        (29.95, "G20T"), (30.0, "G20T"), (38.0, "G20T"),
    ],
)
def test_weight_category_boundaries(dwh, weight, expected):
    assert dwh.execute("SELECT core.f_weight_category(%s)", (weight,)).fetchone()[0] == expected


@pytest.mark.parametrize(
    ("volume", "expected"),
    [(0.0, "OTH"), (0.1, "FTL"), (82.0, "FTL"), (120.0, "FTL"), (120.1, "OTH"), (150.0, "OTH")],
)
def test_volume_category_boundaries(dwh, volume, expected):
    assert dwh.execute("SELECT core.f_volume_category(%s)", (volume,)).fetchone()[0] == expected


def test_missing_categories_are_filled_and_present_ones_kept(source, dwh, run_load):
    add_price(source, 1, total_weight=9.95, weight_category=None, total_volume=120.0, volume_category=None)
    add_price(source, 2, total_weight=20.0, weight_category="OTH", total_volume=0.0, volume_category="FTL")
    run_load()

    rows = dict(dwh.execute(
        "SELECT price_id, (weight_category, volume_category) FROM core.prices ORDER BY price_id"
    ).fetchall())
    assert rows[1] == ("FTL", "FTL")   # пропуски заполнены по правилам
    assert rows[2] == ("OTH", "FTL")   # значения источника не перезаписываются
