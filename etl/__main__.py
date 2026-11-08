"""CLI пайплайна: `python -m etl <команда>`.

  migrate                                  применить DDL хранилища (sql/dwh)
  load [--start-date D] [--end-date D]     загрузить окно по prices.loading_date (границы включительно);
                                           по умолчанию окно из ETL_START_DATE / ETL_END_DATE
  mart [--start-date D]                    пересчитать витрину за месяцы [month(D), month(AS_OF)];
                                           по умолчанию D = ETL_START_DATE
"""

from __future__ import annotations

import argparse
from datetime import date

from common.config import load_settings
from common.db import connect
from common.log import setup_logging
from etl.load import load_window
from etl.mart import refresh_mart
from etl.migrate import run_migrations


def main() -> None:
    settings = load_settings()

    parser = argparse.ArgumentParser(prog="python -m etl")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="применить DDL хранилища (sql/dwh)")
    load = commands.add_parser("load", help="идемпотентная загрузка окна дат источник → raw → core")
    load.add_argument("--start-date", type=date.fromisoformat, default=settings.etl_start_date)
    load.add_argument("--end-date", type=date.fromisoformat, default=settings.etl_end_date)
    mart = commands.add_parser("mart", help="пересчитать витрину mart.route_month_stats до AS_OF")
    mart.add_argument("--start-date", type=date.fromisoformat, default=settings.etl_start_date)
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


if __name__ == "__main__":
    main()
