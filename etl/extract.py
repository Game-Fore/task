from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)

_PRICES_IN_WINDOW = "loading_date BETWEEN {start} AND {end}"
_CHILDREN_IN_WINDOW = "price_id IN (SELECT id FROM prices WHERE loading_date BETWEEN {start} AND {end})"


@dataclass(frozen=True)
class RawTable:
    name: str
    columns: tuple[str, ...]
    source_filter: str | None = None  # None — таблица целиком


RAW_TABLES: tuple[RawTable, ...] = (
    RawTable("cities", ("id", "full_name_local", "full_name_gc", "gc_id", "name",
                        "longitude", "latitude", "created_at", "updated_at")),
    RawTable("body_types", ("id", "name", "id_from_1C", "std_id")),
    RawTable("exchange_rates", ("id", "num_code", "value", "setting_date")),
    RawTable("prices", ("id", "created_at", "updated_at", "subscriber_id", "organization_id",
                        "loading_date", "loading_city_gcid", "unloading_city_gcid", "distance",
                        "total_weight", "total_volume", "body_type", "price", "currency_code",
                        "complex", "price_type", "item_id", "is_fact", "nearest_rate_date",
                        "meta_item_id", "end_loading_date", "source", "external_item_uuid",
                        "outlier_mark", "weight_category", "volume_category", "price_group_id"),
             _PRICES_IN_WINDOW),
    RawTable("price_body_types", ("id", "price_id", "body_type_id"), _CHILDREN_IN_WINDOW),
    RawTable("price_dates", ("id", "price_id", "price_date"), _CHILDREN_IN_WINDOW),
)


def _columns(table: RawTable) -> sql.Composable:
    return sql.SQL(", ").join(map(sql.Identifier, table.columns))


def _copy_out_query(table: RawTable, start: date, end: date) -> sql.Composed:
    where = sql.SQL("")
    if table.source_filter:
        where = sql.SQL(" WHERE " + table.source_filter).format(start=sql.Literal(start), end=sql.Literal(end))
    return sql.SQL("COPY (SELECT {cols} FROM {table}{where}) TO STDOUT").format(
        cols=_columns(table), table=sql.Identifier(table.name), where=where
    )


def _copy_in_query(table: RawTable) -> sql.Composed:
    return sql.SQL("COPY {table} ({cols}) FROM STDIN").format(
        table=sql.Identifier("raw", table.name), cols=_columns(table)
    )


def copy_source_to_raw(source: psycopg.Connection, dwh: psycopg.Connection, start: date, end: date) -> dict[str, int]:
    # данные идут потоком из COPY TO STDOUT источника в COPY FROM STDIN хранилища, в память не грузятся
    copied: dict[str, int] = {}
    for table in RAW_TABLES:
        with source.cursor() as src_cur, dwh.cursor() as dst_cur:
            with src_cur.copy(_copy_out_query(table, start, end)) as copy_out, \
                    dst_cur.copy(_copy_in_query(table)) as copy_in:
                for block in copy_out:
                    copy_in.write(block)
            copied[table.name] = dst_cur.rowcount
        log.info("raw table copied", extra={"step": "extract", "table": f"raw.{table.name}",
                                            "rows": copied[table.name]})
    return copied
