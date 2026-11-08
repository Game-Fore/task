"""Правила качества данных (DQ) для сделок.

Единственный источник истины о том, какие строки отбраковываются. Каждое правило — код причины
и SQL-предикат, истинный для НЕВАЛИДНОЙ строки. Из списка строится один set-based запрос:
для каждой строки окна вычисляется массив всех нарушенных правил, строки с непустым массивом
идут в карантин, остальные — в core. Предикаты — константы кода, не пользовательский ввод.

Алиасы в предикатах (см. build_staging_query):
  p  — raw.prices,
  lc / uc — core.dim_city для города погрузки / выгрузки (LEFT JOIN, NULL — города нет),
  fx — core.exchange_rates по (currency_code, nearest_rate_date) (LEFT JOIN).
"""

from __future__ import annotations

from dataclasses import dataclass

from psycopg import sql

RUB, USD, EUR = "643", "840", "978"
FOREIGN_CURRENCIES = (USD, EUR)


@dataclass(frozen=True)
class DqRule:
    code: str
    description: str
    predicate: str


DQ_RULES: tuple[DqRule, ...] = (
    DqRule("PRICE_NON_POSITIVE", "цена <= 0",
           "p.price <= 0"),
    DqRule("RUB_PRICE_LE_1000", "рублёвая цена в диапазоне (0; 1000] — source-validation",
           f"p.currency_code = '{RUB}' AND p.price > 0 AND p.price <= 1000"),
    DqRule("DISTANCE_NON_POSITIVE", "дистанция <= 0",
           "p.distance <= 0"),
    DqRule("WEIGHT_NEGATIVE", "отрицательный вес",
           "p.total_weight < 0"),
    DqRule("VOLUME_NEGATIVE", "отрицательный объём",
           "p.total_volume < 0"),
    DqRule("LOADING_CITY_UNKNOWN", "города погрузки нет в справочнике cities",
           "lc.gc_id IS NULL"),
    DqRule("UNLOADING_CITY_UNKNOWN", "города выгрузки нет в справочнике cities",
           "uc.gc_id IS NULL"),
    DqRule("UNSUPPORTED_CURRENCY", "валюта не RUB/USD/EUR",
           f"p.currency_code NOT IN ('{RUB}', '{USD}', '{EUR}')"),
    DqRule("FX_RATE_DATE_MISSING", "иностранная валюта без nearest_rate_date",
           f"p.currency_code IN ('{USD}', '{EUR}') AND p.nearest_rate_date IS NULL"),
    DqRule("FX_RATE_NOT_FOUND", "нет курса ЦБ точно на nearest_rate_date (fallback не используется)",
           f"p.currency_code IN ('{USD}', '{EUR}') AND p.nearest_rate_date IS NOT NULL AND fx.rate IS NULL"),
)


def reasons_expression(rules: tuple[DqRule, ...] = DQ_RULES) -> sql.Composed:
    """array_remove(ARRAY[CASE WHEN <предикат> THEN '<код>' END, ...], NULL)::text[]"""
    cases = [
        sql.SQL("CASE WHEN ({predicate}) THEN {code} END").format(
            predicate=sql.SQL(rule.predicate), code=sql.Literal(rule.code)
        )
        for rule in rules
    ]
    return sql.SQL("array_remove(ARRAY[{cases}]::text[], NULL)").format(cases=sql.SQL(", ").join(cases))


def build_staging_query() -> sql.Composed:
    """Временная таблица stg_prices: строки raw.prices окна + курс + массив причин отбраковки.
    RUB конвертируется по курсу 1.0 независимо от nearest_rate_date; USD/EUR — только по точной дате."""
    return sql.SQL("""
        CREATE TEMP TABLE stg_prices ON COMMIT DROP AS
        SELECT p.*,
               CASE WHEN p.currency_code = {rub} THEN 1.0::double precision ELSE fx.rate END AS fx_rate,
               {reasons} AS dq_reasons
        FROM raw.prices p
        LEFT JOIN core.dim_city lc ON lc.gc_id = p.loading_city_gcid
        LEFT JOIN core.dim_city uc ON uc.gc_id = p.unloading_city_gcid
        LEFT JOIN core.exchange_rates fx
               ON fx.currency_code = p.currency_code AND fx.rate_date = p.nearest_rate_date
        WHERE p.loading_date BETWEEN core.etl_window_start() AND core.etl_window_end()
    """).format(rub=sql.Literal(RUB), reasons=reasons_expression())
