"""Пересчёт витрины mart.route_month_stats (представление mart.mart_route_card считается на лету).

Атомарная перезапись месяцев [month(start_date), month(as_of)] в одной транзакции под advisory-lock:
повторный запуск с теми же параметрами даёт ту же витрину, месяцы до start_date не трогаются.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg

SQL_DIR = Path(__file__).resolve().parents[1] / "sql" / "mart"

log = logging.getLogger(__name__)


@dataclass
class MartStats:
    start: date
    as_of: date
    rows_refreshed: int = 0
    rows_total: int = 0
    by_reliability: dict[str, int] = field(default_factory=dict)


def refresh_mart(dwh: psycopg.Connection, start: date, as_of: date) -> MartStats:
    stats = MartStats(start=start, as_of=as_of)
    log.info("mart refresh started", extra={"step": "mart", "start_date": start, "as_of": as_of})

    with dwh.transaction():
        dwh.execute("SELECT pg_advisory_xact_lock(hashtext('mart_refresh'))")
        dwh.execute("SELECT set_config('etl.window_start', %s, true), set_config('etl.as_of', %s, true)",
                    (start.isoformat(), as_of.isoformat()))
        dwh.execute((SQL_DIR / "010_route_month_stats.sql").read_text(encoding="utf-8"))

        refreshed = ("month BETWEEN date_trunc('month', core.etl_window_start())::date "
                     "AND date_trunc('month', core.etl_as_of())::date")
        stats.rows_refreshed = dwh.execute(
            f"SELECT count(*) FROM mart.route_month_stats WHERE {refreshed}").fetchone()[0]
        stats.rows_total = dwh.execute("SELECT count(*) FROM mart.route_month_stats").fetchone()[0]
        stats.by_reliability = dict(dwh.execute(
            "SELECT reliability_level, count(*) FROM mart.mart_route_card GROUP BY 1 ORDER BY 1").fetchall())

    log.info("mart refresh finished", extra={"step": "mart", "start_date": start, "as_of": as_of,
                                             "rows_refreshed": stats.rows_refreshed, "rows_total": stats.rows_total,
                                             "by_reliability": stats.by_reliability})
    return stats
