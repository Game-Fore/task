"""Загрузка окна дат: источник → raw → core, атомарно и идемпотентно.

Всё, что меняется в хранилище, выполняется в ОДНОЙ транзакции:
  1. advisory-lock: параллельный запуск того же шага ждёт, а не пишет одновременно;
  2. окно задаётся через set_config(..., is_local => true) — живёт до конца транзакции;
  3. raw: удалить окно → COPY из источника;
  4. core: справочники целиком, затем удалить окно → staging с DQ → карантин / core.
Повторный запуск за то же окно удаляет и заново вставляет те же строки — результат не меняется.
При ошибке на любом шаге транзакция откатывается и хранилище остаётся в прежнем состоянии.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg
from psycopg import IsolationLevel

from etl.dq_rules import build_staging_query
from etl.extract import copy_source_to_raw

SQL_DIR = Path(__file__).resolve().parents[1] / "sql" / "etl"

log = logging.getLogger(__name__)


@dataclass
class LoadStats:
    start: date
    end: date
    raw_rows: dict[str, int] = field(default_factory=dict)
    core_prices: int = 0
    quarantined: int = 0
    quarantine_by_reason: dict[str, int] = field(default_factory=dict)
    price_body_groups: int = 0
    price_dates: int = 0


def _run_sql_file(conn: psycopg.Connection, name: str) -> None:
    # Файлы без параметров (окно читается из set_config), поэтому несколько операторов в одном execute допустимы.
    conn.execute((SQL_DIR / name).read_text(encoding="utf-8"))


def _count_in_window(conn: psycopg.Connection, query: str) -> int:
    return conn.execute(query).fetchone()[0]


def load_window(source: psycopg.Connection, dwh: psycopg.Connection, start: date, end: date) -> LoadStats:
    if start > end:
        raise ValueError(f"start_date {start} позже end_date {end}")
    stats = LoadStats(start=start, end=end)
    log.info("load started", extra={"step": "load", "start_date": start, "end_date": end})

    # Единый снимок источника для всех таблиц: дочерние строки не разойдутся с prices.
    source.isolation_level = IsolationLevel.REPEATABLE_READ
    source.read_only = True

    with source.transaction(), dwh.transaction():
        dwh.execute("SELECT pg_advisory_xact_lock(hashtext('etl_load'))")
        dwh.execute("SELECT set_config('etl.window_start', %s, true), set_config('etl.window_end', %s, true)",
                    (start.isoformat(), end.isoformat()))

        _run_sql_file(dwh, "010_raw_delete_window.sql")
        stats.raw_rows = copy_source_to_raw(source, dwh, start, end)

        _run_sql_file(dwh, "020_core_dims.sql")
        _run_sql_file(dwh, "030_core_delete_window.sql")
        dwh.execute(build_staging_query())
        _run_sql_file(dwh, "040_core_quarantine.sql")
        _run_sql_file(dwh, "050_core_prices.sql")
        _run_sql_file(dwh, "060_core_price_body_groups.sql")
        _run_sql_file(dwh, "070_core_price_dates.sql")

        in_window = "loading_date BETWEEN core.etl_window_start() AND core.etl_window_end()"
        stats.core_prices = _count_in_window(dwh, f"SELECT count(*) FROM core.prices WHERE {in_window}")
        stats.quarantined = _count_in_window(dwh, f"SELECT count(*) FROM core.dq_quarantine_prices WHERE {in_window}")
        stats.quarantine_by_reason = dict(dwh.execute(
            f"SELECT reason, count(*) FROM core.dq_quarantine_prices, unnest(reasons) AS reason "
            f"WHERE {in_window} GROUP BY reason ORDER BY reason"
        ).fetchall())
        window_prices = f"SELECT price_id FROM core.prices WHERE {in_window}"
        stats.price_body_groups = _count_in_window(
            dwh, f"SELECT count(*) FROM core.price_body_groups WHERE price_id IN ({window_prices})")
        stats.price_dates = _count_in_window(
            dwh, f"SELECT count(*) FROM core.price_dates WHERE price_id IN ({window_prices})")

    log.info("dq quarantine", extra={"step": "load", "rows": stats.quarantined,
                                     "by_reason": stats.quarantine_by_reason})
    log.info("load finished", extra={"step": "load", "start_date": start, "end_date": end,
                                     "raw_prices": stats.raw_rows.get("prices", 0),
                                     "core_prices": stats.core_prices, "quarantined": stats.quarantined,
                                     "price_body_groups": stats.price_body_groups,
                                     "price_dates": stats.price_dates})
    return stats
