#!/usr/bin/env bash
# метаданные Airflow лежат в отдельной базе на том же PostgreSQL, создаём её, если нет
set -euo pipefail

python - <<'PY'
import os
import psycopg2

conn = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], user=os.environ["DB_USER"],
                        password=os.environ["DB_PASSWORD"], dbname="postgres")
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'airflow'")
    if cur.fetchone() is None:
        cur.execute("CREATE DATABASE airflow")
conn.close()
PY

airflow db migrate

if ! airflow users list -o plain | grep -qw "${AIRFLOW_ADMIN_USER}"; then
    airflow users create --username "${AIRFLOW_ADMIN_USER}" --password "${AIRFLOW_ADMIN_PASSWORD}" \
        --firstname Admin --lastname Admin --role Admin --email admin@example.com
fi
