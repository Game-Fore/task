from __future__ import annotations

from dataclasses import dataclass

from psycopg import sql

RUB, USD, EUR = "643", "840", "978"


@dataclass(frozen=True)
class DqRule:
    code: str
    predicate: str  # истинен для невалидной строки


# p — raw.prices, lc / uc — core.dim_city, fx — core.exchange_rates (все через LEFT JOIN)
DQ_RULES: tuple[DqRule, ...] = (
    DqRule("PRICE_NON_POSITIVE", "p.price <= 0"),
    DqRule("RUB_PRICE_LE_1000", f"p.currency_code = '{RUB}' AND p.price > 0 AND p.price <= 1000"),
    DqRule("DISTANCE_NON_POSITIVE", "p.distance <= 0"),
    DqRule("WEIGHT_NEGATIVE", "p.total_weight < 0"),
    DqRule("VOLUME_NEGATIVE", "p.total_volume < 0"),
    DqRule("LOADING_CITY_UNKNOWN", "lc.gc_id IS NULL"),
    DqRule("UNLOADING_CITY_UNKNOWN", "uc.gc_id IS NULL"),
    DqRule("UNSUPPORTED_CURRENCY", f"p.currency_code NOT IN ('{RUB}', '{USD}', '{EUR}')"),
    DqRule("FX_RATE_DATE_MISSING", f"p.currency_code IN ('{USD}', '{EUR}') AND p.nearest_rate_date IS NULL"),
    DqRule("FX_RATE_NOT_FOUND",
           f"p.currency_code IN ('{USD}', '{EUR}') AND p.nearest_rate_date IS NOT NULL AND fx.rate IS NULL"),
)


def reasons_expression(rules: tuple[DqRule, ...] = DQ_RULES) -> sql.Composed:
    cases = [
        sql.SQL("CASE WHEN ({predicate}) THEN {code} END").format(
            predicate=sql.SQL(rule.predicate), code=sql.Literal(rule.code)
        )
        for rule in rules
    ]
    return sql.SQL("array_remove(ARRAY[{cases}]::text[], NULL)").format(cases=sql.SQL(", ").join(cases))


def build_staging_query() -> sql.Composed:
    # рубли считаем по курсу 1.0 даже без nearest_rate_date, валюту — только по точной дате
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
