"""Применение DDL хранилища из sql/dwh/*.sql.

Все файлы идемпотентны (IF NOT EXISTS / CREATE OR REPLACE) и применяются целиком при каждом
запуске, в лексикографическом порядке имён, в одной транзакции: либо схема обновилась вся,
либо не изменилась. Advisory-lock не даёт двум параллельным запускам применять DDL одновременно.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "sql" / "dwh"

log = logging.getLogger(__name__)


def run_migrations(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    files = sorted(migrations_dir.glob("*.sql"))
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('dwh_migrate'))")
        for path in files:
            # Без параметров psycopg выполняет текст как есть, допускаются несколько операторов.
            conn.execute(path.read_text(encoding="utf-8"))
            log.info("migration applied", extra={"step": "migrate", "file": path.name})
    log.info("migrations done", extra={"step": "migrate", "files_applied": len(files)})
    return [p.name for p in files]
