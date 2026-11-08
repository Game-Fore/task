"""CLI пайплайна: `python -m etl <команда>`."""

from __future__ import annotations

import argparse

from common.config import load_settings
from common.db import connect
from common.log import setup_logging
from etl.migrate import run_migrations


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m etl")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="применить DDL хранилища (sql/dwh)")
    args = parser.parse_args()

    settings = load_settings()
    setup_logging(settings.log_level)

    if args.command == "migrate":
        with connect(settings.db, settings.dwh_db) as conn:
            run_migrations(conn)


if __name__ == "__main__":
    main()
