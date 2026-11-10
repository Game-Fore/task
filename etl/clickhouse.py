from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import clickhouse_connect
import psycopg
from clickhouse_connect.driver.client import Client

from common.config import ClickHouseConfig

SQL_DIR = Path(__file__).resolve().parents[1] / "sql" / "clickhouse"

DEAL_COLUMNS = [
    "month", "loading_city_gcid", "unloading_city_gcid", "body_group", "weight_category", "price_id",
    "loading_city", "loading_region", "unloading_city", "unloading_region",
    "organization_id", "price_type", "price_rub", "price_km", "last_price_date",
]

_MARKET_DEALS_QUERY = """
    SELECT m.month, m.loading_city_gcid, m.unloading_city_gcid, m.body_group, m.weight_category, m.price_id,
           lc.city_name, lc.region_name, uc.city_name, uc.region_name,
           m.organization_id, m.price_type, m.price_rub, m.price_km, m.last_price_date
    FROM core.market_deals m
    JOIN core.dim_city lc ON lc.gc_id = m.loading_city_gcid
    JOIN core.dim_city uc ON uc.gc_id = m.unloading_city_gcid
    WHERE m.month >= date_trunc('month', core.etl_window_start())
"""

KEY_COLUMNS = ["month", "loading_city_gcid", "unloading_city_gcid", "body_group", "weight_category"]
EXACT_COLUMNS = ["trips_count", "carriers_count", "last_price_date", "mom_pct", "yoy_pct", "reliability_level"]
MONEY_COLUMNS = ["p25_trip", "median_trip", "p75_trip", "avg_trip", "p25_km", "median_km", "p75_km"]
STATS_COLUMNS = KEY_COLUMNS + EXACT_COLUMNS + MONEY_COLUMNS + ["cv_rate"]
MONEY_TOLERANCE = 0.01
CV_TOLERANCE = 0.0001

log = logging.getLogger(__name__)


@dataclass
class ParityReport:
    cells_pg: int = 0
    cells_ch: int = 0
    missing_keys: int = 0
    exact_mismatches: int = 0
    cells_off_by_cent: int = 0
    max_money_diff: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def connect_clickhouse(cfg: ClickHouseConfig) -> Client:
    admin = clickhouse_connect.get_client(host=cfg.host, port=cfg.port, username=cfg.user, password=cfg.password)
    admin.command(f"CREATE DATABASE IF NOT EXISTS {cfg.database}")
    return clickhouse_connect.get_client(host=cfg.host, port=cfg.port, username=cfg.user,
                                         password=cfg.password, database=cfg.database)


def _statements(path: Path) -> list[str]:
    return [s.strip() for s in re.split(r";\s*$", path.read_text(encoding="utf-8"), flags=re.M) if s.strip()]


def _partitions(start: date, as_of: date) -> list[int]:
    result, year, month = [], start.year, start.month
    while (year, month) <= (as_of.year, as_of.month):
        result.append(year * 100 + month)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def sync_clickhouse(dwh: psycopg.Connection, ch: Client, start: date, as_of: date) -> ParityReport:
    """Переносит сделки рынка за месяцы [start, as_of] в ClickHouse, считает там витрину и сверяет с PostgreSQL."""
    for statement in _statements(SQL_DIR / "001_schema.sql"):
        ch.command(statement)

    partitions = _partitions(start, as_of)
    window = (date(start.year, start.month, 1), as_of)
    with dwh.transaction():
        dwh.execute("SELECT pg_advisory_xact_lock(hashtext('clickhouse_sync'))")
        dwh.execute("SELECT set_config('etl.window_start', %s, true), set_config('etl.as_of', %s, true)",
                    (start.isoformat(), as_of.isoformat()))
        deals = dwh.execute(_MARKET_DEALS_QUERY).fetchall()
        log.info("market deals read", extra={"step": "clickhouse", "rows": len(deals), "partitions": len(partitions)})

        # окно собирается в staging и подменяет секции целиком: месяц без сделок станет пустым
        ch.command("TRUNCATE TABLE market_deals_stage")
        ch.command("TRUNCATE TABLE route_month_stats_stage")
        if deals:
            ch.insert("market_deals_stage", deals, column_names=DEAL_COLUMNS)
        ch.command((SQL_DIR / "010_route_month_stats.sql").read_text(encoding="utf-8"), parameters={"as_of": as_of})
        for partition in partitions:
            ch.command(f"ALTER TABLE market_deals REPLACE PARTITION {partition} FROM market_deals_stage")
            ch.command(f"ALTER TABLE route_month_stats REPLACE PARTITION {partition} FROM route_month_stats_stage")
        ch.command("TRUNCATE TABLE market_deals_stage")
        ch.command("TRUNCATE TABLE route_month_stats_stage")

        pg_rows = dwh.execute(
            f"SELECT {', '.join(STATS_COLUMNS)} FROM mart.mart_route_card WHERE month BETWEEN %s AND %s", window
        ).fetchall()

    ch_rows = ch.query(
        f"SELECT {', '.join(STATS_COLUMNS)} FROM route_card WHERE month BETWEEN {{start:Date}} AND {{end:Date}}",
        parameters={"start": window[0], "end": window[1]},
    ).result_rows
    report = compare_stats(pg_rows, ch_rows)
    log.info("parity " + ("ok" if report.ok else "failed"),
             extra={"step": "clickhouse", "cells_pg": report.cells_pg, "cells_ch": report.cells_ch,
                    "cells_off_by_cent": report.cells_off_by_cent, "max_money_diff": report.max_money_diff,
                    "errors": report.errors[:5]})
    if not report.ok:
        raise RuntimeError(f"витрины PostgreSQL и ClickHouse расходятся: {report.errors[:5]}")
    return report


def compare_stats(pg_rows: list[tuple], ch_rows: list[tuple]) -> ParityReport:
    """Счётчики и даты должны совпасть точно, денежные метрики — с допуском в копейку из-за округления float."""
    n_key = len(KEY_COLUMNS)
    pg = {tuple(r[:n_key]): r[n_key:] for r in pg_rows}
    ch = {tuple(r[:n_key]): r[n_key:] for r in ch_rows}
    report = ParityReport(cells_pg=len(pg), cells_ch=len(ch))
    if pg.keys() != ch.keys():
        report.missing_keys = len(pg.keys() ^ ch.keys())
        report.errors.append(f"разный набор ячеек: {report.missing_keys} ключей только в одной витрине")

    n_exact, n_money = len(EXACT_COLUMNS), len(MONEY_COLUMNS)
    for key in pg.keys() & ch.keys():
        a, b = pg[key], ch[key]
        if tuple(a[:n_exact]) != tuple(b[:n_exact]):
            report.exact_mismatches += 1
            report.errors.append(f"{key}: счётчики {a[:n_exact]} != {b[:n_exact]}")
        diffs = [abs(float(x) - float(y)) for x, y in zip(a[n_exact:n_exact + n_money], b[n_exact:n_exact + n_money])]
        if any(diffs):
            report.cells_off_by_cent += 1
            report.max_money_diff = max(report.max_money_diff, *diffs)
        if max(diffs) > MONEY_TOLERANCE + 1e-9:
            report.errors.append(f"{key}: денежные метрики расходятся на {max(diffs):.4f}")
        cv_pg, cv_ch = a[-1], b[-1]
        if (cv_pg is None) != (cv_ch is None) or (cv_pg is not None and abs(float(cv_pg) - float(cv_ch)) > CV_TOLERANCE):
            report.errors.append(f"{key}: cv_rate {cv_pg} != {cv_ch}")
    report.max_money_diff = round(report.max_money_diff, 4)
    return report
