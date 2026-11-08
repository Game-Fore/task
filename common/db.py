from __future__ import annotations

import psycopg

from common.config import DbConfig


def connect(db: DbConfig, dbname: str) -> psycopg.Connection:
    return psycopg.connect(
        host=db.host,
        port=db.port,
        user=db.user,
        password=db.password,
        dbname=dbname,
        application_name="smart-logistics-pipeline",
    )
