#!/usr/bin/env bash
# выполняется один раз, на пустом volume: источник со сгенерированными данными и пустая база хранилища
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
