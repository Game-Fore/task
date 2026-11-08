from __future__ import annotations

import argparse

from common.config import load_settings
from common.db import connect
from common.log import setup_logging
from ml.score import score
from ml.train import train_models


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m ml")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("train", help="обучить модели и посчитать метрики на test")
    commands.add_parser("score", help="записать прогнозы в mart.ml_price_predictions")
    args = parser.parse_args()

    settings = load_settings()
    setup_logging(settings.log_level)

    with connect(settings.db, settings.dwh_db) as dwh:
        if args.command == "train":
            train_models(dwh, settings.as_of, settings.ml_models_dir)
        elif args.command == "score":
            score(dwh, settings.as_of, settings.ml_models_dir)


if __name__ == "__main__":
    main()
