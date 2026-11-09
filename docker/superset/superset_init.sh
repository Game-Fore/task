#!/usr/bin/env bash
set -euo pipefail

# база метаданных Superset и пользователь, который может только читать витрины
python - <<'PY'
import os

import psycopg2
from psycopg2 import sql


def connect(dbname):
    conn = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"], dbname=dbname)
    conn.autocommit = True
    return conn


conn = connect("postgres")
with conn.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'superset'")
    if cur.fetchone() is None:
        cur.execute("CREATE DATABASE superset")
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'bi_reader'")
    action = "ALTER" if cur.fetchone() else "CREATE"
    cur.execute(sql.SQL(action + " ROLE bi_reader LOGIN PASSWORD {}").format(
        sql.Literal(os.environ["BI_READER_PASSWORD"])))
conn.close()

conn = connect(os.environ["DWH_DB"])
with conn.cursor() as cur:
    cur.execute("GRANT USAGE ON SCHEMA mart TO bi_reader")
    cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA mart TO bi_reader")
    cur.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA mart GRANT SELECT ON TABLES TO bi_reader")
conn.close()
PY

superset db upgrade

if ! superset fab list-users | grep -qw "${SUPERSET_ADMIN_USER}"; then
    superset fab create-admin --username "${SUPERSET_ADMIN_USER}" --password "${SUPERSET_ADMIN_PASSWORD}" \
        --firstname Admin --lastname Admin --email admin@example.com
fi

superset init

# дашборд лежит в репозитории YAML-файлами; собираем из них zip, подставив пароль и имя базы
bundle="$(mktemp -d)/market_rates.zip"
python - "$bundle" <<'PY'
import os
import pathlib
import sys
import zipfile
from urllib.parse import quote

source = pathlib.Path("/app/dashboard_bundle")
values = {"{{BI_READER_PASSWORD}}": quote(os.environ["BI_READER_PASSWORD"], safe=""), "{{DWH_DB}}": os.environ["DWH_DB"]}
with zipfile.ZipFile(sys.argv[1], "w") as bundle:
    for path in sorted(source.rglob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        for placeholder, value in values.items():
            text = text.replace(placeholder, value)
        bundle.writestr(f"market_rates/{path.relative_to(source).as_posix()}", text)
PY

superset import-dashboards -p "$bundle" -u "${SUPERSET_ADMIN_USER}"
