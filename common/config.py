"""Конфигурация из переменных окружения.

Значений по умолчанию для подключения здесь нет намеренно: их задаёт docker-compose.yml
(или .env), а код падает сразу и с понятной ошибкой, если переменная не передана.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return value


def _require_date(name: str) -> date:
    return date.fromisoformat(_require(name))


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str


@dataclass(frozen=True)
class Settings:
    db: DbConfig
    source_db: str
    dwh_db: str
    etl_start_date: date
    etl_end_date: date
    as_of: date
    log_level: str


def load_settings() -> Settings:
    return Settings(
        db=DbConfig(
            host=_require("DB_HOST"),
            port=int(_require("DB_PORT")),
            user=_require("DB_USER"),
            password=_require("DB_PASSWORD"),
        ),
        source_db=_require("SOURCE_DB"),
        dwh_db=_require("DWH_DB"),
        etl_start_date=_require_date("ETL_START_DATE"),
        etl_end_date=_require_date("ETL_END_DATE"),
        as_of=_require_date("AS_OF"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
