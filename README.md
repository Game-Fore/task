# Smart Logistics Data & ML Platform

Тестовое задание Middle Data Engineer «Умная Логистика»: ETL → DWH → ML на PostgreSQL 17.

> README дополняется по мере реализации этапов.

## Запуск

```bash
docker-compose up --build
```

При первом старте PostgreSQL генерирует источник `deals_bigdata` (300 000 сделок, `sql/source/synthetic.sql`)
и создаёт пустое хранилище `dwh`. Сервис `pipeline` применяет DDL хранилища и завершается.
Параметры — в `.env.example` (без `.env` используются значения по умолчанию из `docker-compose.yml`).

## Структура

```
docker-compose.yml, .env.example
docker/                    Dockerfile пайплайна, init-скрипт PostgreSQL
sql/source/                схема и генератор источника (выданы с заданием, без изменений)
sql/dwh/                   DDL хранилища: схемы raw / core / mart
common/                    конфигурация из env, подключение к БД, JSON-логирование
etl/                       CLI пайплайна (`python -m etl migrate`)
```
