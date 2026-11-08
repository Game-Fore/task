"""Конфигурация из переменных окружения.

Значений по умолчанию для подключения здесь нет намеренно: их задаёт docker-compose.yml
(или .env), а код падает сразу и с понятной ошибкой, если переменная не передана.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return value


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
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
