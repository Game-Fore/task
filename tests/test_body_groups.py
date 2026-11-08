"""Унификация кузовов: группы по std_id, без дублей цены внутри группы, fallback-правила."""

from __future__ import annotations

import pytest

from tests.source_data import add_price

# Группы из требований задания: код типа кузова из 1С → бизнес-группа.
SPEC_GROUPS = {
    **{bt: "Тент" for bt in (56, 57, 58, 59, 60, 61)},
    **{bt: "Рефрижератор" for bt in (4, 46, 47, 48)},
    2: "Изотерм",
    **{bt: "Борт" for bt in (1, 15)},
    **{bt: "Прочие" for bt in (3, 5, 26, 50, 65, 68)},
}


def test_dim_body_type_matches_spec_groups(source, dwh, run_load):
    add_price(source, 1)
    run_load()

    assert dict(dwh.execute("SELECT body_type_id, body_group FROM core.dim_body_type").fetchall()) == SPEC_GROUPS


@pytest.mark.parametrize(
    ("body_type", "linked", "expected_groups", "expected_primary"),
    [
        (56, [], {"Тент"}, "Тент"),                                   # нет связей → fallback на prices.body_type
        (56, [56, 61], {"Тент"}, "Тент"),                             # два типа одной группы → одна строка
        (56, [56, 15], {"Тент", "Борт"}, "Тент"),                     # разные группы → цена в обеих
        (56, [57], {"Тент"}, "Тент"),                                 # дочерний код старых записей
        (4, [46, 2], {"Рефрижератор", "Изотерм"}, "Рефрижератор"),
        (None, [], {"Не указан"}, "Не указан"),
        (None, [15, 4], {"Борт", "Рефрижератор"}, "Рефрижератор"),    # основная — минимальный std_id (4 < 15)
        (3, [], {"Прочие"}, "Прочие"),
        (999, [], {"Прочие"}, "Прочие"),                              # код вне справочника
    ],
)
def test_price_body_groups(source, dwh, run_load, body_type, linked, expected_groups, expected_primary):
    add_price(source, 1, body_type=body_type, body_type_ids=linked)
    run_load()

    groups = [row[0] for row in dwh.execute(
        "SELECT body_group FROM core.price_body_groups WHERE price_id = 1").fetchall()]
    assert len(groups) == len(set(groups))
    assert set(groups) == expected_groups
    assert dwh.execute("SELECT body_group FROM core.prices WHERE price_id = 1").fetchone()[0] == expected_primary
