#!/usr/bin/env bash
# Инициализация PostgreSQL при первом старте пустого volume
# (docker-entrypoint-initdb.d выполняется официальным образом только один раз).
#   1. Источник: эталонная схема + детерминированный генератор в базе $POSTGRES_DB.
#   2. Хранилище: пустая база $DWH_DB, её схемы создаёт `python -m etl migrate`.
set -eo pipefail

psql_run() {
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --no-psqlrc "$@"
}

echo "init: source schema -> ${POSTGRES_DB}"
psql_run --dbname "$POSTGRES_DB" -f /source/schema.sql

echo "init: synthetic data (n_prices=${N_PRICES}) -> ${POSTGRES_DB}"
psql_run --dbname "$POSTGRES_DB" -v n_prices="${N_PRICES}" -f /source/synthetic.sql

echo "init: create database ${DWH_DB}"
psql_run --dbname postgres -c "CREATE DATABASE \"${DWH_DB}\""
