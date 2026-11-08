"""Фикстуры: временные базы source_test / dwh_test на том же сервере PostgreSQL.

source_test создаётся из выданной sql/source/schema.sql и наполняется краевыми строками в каждом тесте,
dwh_test — нашими миграциями. Загрузка вызывается той же функцией load_window, что и в пайплайне,
поэтому тесты сквозные: extract (COPY) → DQ → core.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from common.config import load_settings
from common.db import connect
from etl.load import LoadStats, load_window
from etl.mart import MartStats, refresh_mart
from etl.migrate import run_migrations
from tests.source_data import reset_source

SOURCE_TEST_DB = "source_test"
DWH_TEST_DB = "dwh_test"
SOURCE_SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "source" / "schema.sql"

YEAR_2026 = (date(2026, 1, 1), date(2026, 12, 31))
AS_OF = date(2026, 10, 26)


@pytest.fixture(scope="session")
def settings():
    return load_settings()


def _admin(settings) -> psycopg.Connection:
    db = settings.db
    return psycopg.connect(host=db.host, port=db.port, user=db.user, password=db.password,
                           dbname="postgres", autocommit=True)


@pytest.fixture(scope="session")
def test_databases(settings):
    assert {SOURCE_TEST_DB, DWH_TEST_DB}.isdisjoint({settings.source_db, settings.dwh_db})
    with _admin(settings) as admin:
        for name in (SOURCE_TEST_DB, DWH_TEST_DB):
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with connect(settings.db, SOURCE_TEST_DB) as conn:
        conn.execute(SOURCE_SCHEMA.read_text(encoding="utf-8"))
    with connect(settings.db, DWH_TEST_DB) as conn:
        run_migrations(conn)
    yield
    with _admin(settings) as admin:
        for name in (SOURCE_TEST_DB, DWH_TEST_DB):
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def source(settings, test_databases):
    """Источник со справочниками и без сделок; autocommit — данные сразу видны загрузке."""
    with psycopg.connect(**_conn_kwargs(settings, SOURCE_TEST_DB), autocommit=True) as conn:
        reset_source(conn)
        yield conn


@pytest.fixture
def dwh(settings, test_databases):
    """Пустые raw/core/mart перед каждым тестом; autocommit — для подготовки данных и проверочных запросов."""
    with psycopg.connect(**_conn_kwargs(settings, DWH_TEST_DB), autocommit=True) as conn:
        tables = conn.execute(
            "SELECT format('%I.%I', schemaname, tablename) FROM pg_tables WHERE schemaname IN ('raw', 'core', 'mart')"
        ).fetchall()
        conn.execute(sql.SQL("TRUNCATE {}").format(sql.SQL(", ").join(sql.SQL(t) for (t,) in tables)))
        yield conn


@pytest.fixture
def run_load(settings, test_databases):
    def _run(start: date = YEAR_2026[0], end: date = YEAR_2026[1]) -> LoadStats:
        with connect(settings.db, SOURCE_TEST_DB) as src, connect(settings.db, DWH_TEST_DB) as dst:
            return load_window(src, dst, start, end)
    return _run


@pytest.fixture
def run_mart(settings, test_databases):
    def _run(start: date = date(2023, 1, 1), as_of: date = AS_OF) -> MartStats:
        with connect(settings.db, DWH_TEST_DB) as dst:
            return refresh_mart(dst, start, as_of)
    return _run


def _conn_kwargs(settings, dbname: str) -> dict:
    db = settings.db
    return {"host": db.host, "port": db.port, "user": db.user, "password": db.password, "dbname": dbname}
