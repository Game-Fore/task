from __future__ import annotations

import argparse
from datetime import date

from common.config import load_clickhouse_config, load_settings
from common.db import connect
from common.log import setup_logging
from etl.load import load_window
from etl.mart import refresh_mart
from etl.migrate import run_migrations


def main() -> None:
    settings = load_settings()

    parser = argparse.ArgumentParser(prog="python -m etl")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="применить DDL хранилища")
    load = commands.add_parser("load", help="загрузить окно по loading_date (границы включительно)")
    load.add_argument("--start-date", type=date.fromisoformat, default=settings.etl_start_date)
    load.add_argument("--end-date", type=date.fromisoformat, default=settings.etl_end_date)
    mart = commands.add_parser("mart", help="пересчитать витрину с месяца start-date до AS_OF")
    mart.add_argument("--start-date", type=date.fromisoformat, default=settings.etl_start_date)
    clickhouse = commands.add_parser("clickhouse", help="перенести сделки рынка в ClickHouse и сверить витрину")
    clickhouse.add_argument("--start-date", type=date.fromisoformat, default=settings.etl_start_date)
    args = parser.parse_args()

    setup_logging(settings.log_level)

    if args.command == "migrate":
        with connect(settings.db, settings.dwh_db) as conn:
            run_migrations(conn)
    elif args.command == "load":
        with connect(settings.db, settings.source_db) as source, connect(settings.db, settings.dwh_db) as dwh:
            load_window(source, dwh, args.start_date, args.end_date)
    elif args.command == "mart":
        with connect(settings.db, settings.dwh_db) as dwh:
            refresh_mart(dwh, args.start_date, settings.as_of)
    elif args.command == "clickhouse":
        from etl.clickhouse import connect_clickhouse, sync_clickhouse

        with connect(settings.db, settings.dwh_db) as dwh:
            sync_clickhouse(dwh, connect_clickhouse(load_clickhouse_config()), args.start_date, settings.as_of)


if __name__ == "__main__":
    main()
