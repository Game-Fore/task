# Smart Logistics Data & ML Platform

Тестовое задание Middle Data Engineer «Умная Логистика»: ETL → DWH → ML на PostgreSQL 17.

> README дополняется по мере реализации этапов.

## Запуск

```bash
docker-compose up --build
```

При первом старте PostgreSQL генерирует источник `deals_bigdata` (300 000 сделок, `sql/source/synthetic.sql`)
и создаёт пустое хранилище `dwh`. Сервис `pipeline` выполняет шаги из `docker/run_pipeline.sh`
(`etl migrate` → `etl load` → `etl mart`) и завершается. Все шаги идемпотентны: повторный `docker-compose up` безопасен.
Параметры — в `.env.example` (без `.env` используются значения по умолчанию из `docker-compose.yml`).

### Повторный запуск (backfill) за период

Окно задаётся по `prices.loading_date`, границы включительно. Окно перезаписывается атомарно:
повторный запуск за тот же период не меняет число строк и суммы.

```bash
docker compose run --rm pipeline python -m etl load --start-date 2026-10-01 --end-date 2026-10-31
```

После загрузки окна пересчитайте витрину с того же месяца (пересчитываются месяцы от `--start-date` до `AS_OF`):

```bash
docker compose run --rm pipeline python -m etl mart --start-date 2026-10-01
```

### Тесты

```bash
docker compose run --rm pipeline pytest
```

Тесты создают временные базы `source_test` / `dwh_test` на том же сервере (выданная схема источника
+ краевые строки) и вызывают ту же функцию загрузки, что и пайплайн.

## Архитектура

```
deals_bigdata (источник, OLTP)            dwh (хранилище)
  prices, price_dates,        COPY      raw.*   копия 1:1: сделки за окно, справочники целиком
  price_body_types,        ─────────►    │
  cities, body_types,       (Python)     │ SQL (ELT), одна транзакция на окно
  exchange_rates                         ▼
                                       core.*  DQ + карантин, price_rub, дедуплицированные измерения
                                         │ SQL, пересчёт месяцев [start, as_of]
                                         ▼
                                       mart.route_month_stats  →  view mart.mart_route_card
```

**Загрузка окна** (`etl/load.py`) — одна транзакция в `dwh` под `pg_advisory_xact_lock`:
удалить окно в `raw` → `COPY` из источника → справочники `core` целиком → удалить окно в `core` →
staging с DQ → карантин / `core.prices` → группы кузова и помесячные даты. Источник читается
в транзакции `REPEATABLE READ`, поэтому все таблицы выгружаются из одного снимка.

| Таблица | Содержание |
|---|---|
| `core.dim_city` | один `gc_id` = строка с минимальным `cities.id`; город и регион из `full_name_local` |
| `core.dim_body_type` | код кузова из 1С → `std_id` → группа: Тент / Рефрижератор / Изотерм / Борт / Прочие |
| `core.exchange_rates` | курсы ЦБ, PK `(currency_code, rate_date)` |
| `core.prices` | сделки, прошедшие DQ: `price_rub`, `fx_rate`, категории, основная группа кузова, флаги scope |
| `core.price_body_groups` | все группы кузова сделки, одна строка на (цена, группа) |
| `core.price_dates` | помесячная развёртка сделки (`price_date`, `month`) |
| `core.dq_quarantine_prices` | отбракованные строки: все коды причин + исходная строка (`jsonb`) |

**DQ-правила** (`etl/dq_rules.py`) — список «код причины + SQL-предикат»; из него строится один set-based
запрос, строка с хотя бы одной причиной уходит в карантин со всеми причинами сразу:
`PRICE_NON_POSITIVE`, `RUB_PRICE_LE_1000`, `DISTANCE_NON_POSITIVE`, `WEIGHT_NEGATIVE`, `VOLUME_NEGATIVE`,
`LOADING_CITY_UNKNOWN`, `UNLOADING_CITY_UNKNOWN`, `UNSUPPORTED_CURRENCY`, `FX_RATE_DATE_MISSING`, `FX_RATE_NOT_FOUND`.

На синтетическом источнике: 300 000 строк → 299 797 в `core.prices`, 203 в карантине
(164 `PRICE_NON_POSITIVE`, 39 `FX_RATE_DATE_MISSING`).

### Витрина «Карточка маршрута и коридор ставок»

Зерно: **месяц × город отправления × город назначения × группа кузова × весовая категория**.

- `mart.route_month_stats` — таблица с базовыми метриками ячейки (`sql/mart/010_route_month_stats.sql`):
  `p25_trip` / `median_trip` / `p75_trip` / `avg_trip` (руб./рейс без НДС), `p25_km` / `median_km` / `p75_km`
  (руб./км), `trips_count`, `carriers_count`, `cv_rate`, `last_price_date`, `as_of`.
- `mart.mart_route_card` — представление для BI: те же метрики + `mom_pct`, `yoy_pct`, `reliability_level`.

Выборка: факты (`price_type IN (1, 2, 3, 4, 5, 9)`), `complex = false`, `outlier_mark = false`, `price > 0`,
`distance > 0`, `price_dates.price_date <= as_of`. Месяц — из `price_dates`, поэтому долгосрочная заявка
присутствует в нескольких месяцах.

На синтетическом источнике: 203 644 ячейки за 2023-10 … 2026-10; `HIGH` — 10, `MEDIUM` — 924,
`LOW_DATA` — 202 710. Витрина разреженная: в 78 % ячеек одна сделка — зерно «город × город × кузов × вес × месяц»
на 300 тыс. сделок почти везде даёт единичные наблюдения. Именно поэтому каждая строка несёт
`trips_count` / `carriers_count` / `reliability_level`. `mom_pct` заполнен у 75 986 ячеек, `yoy_pct` — у 42 624.

Примеры запросов:

```sql
-- Сводная таблица направлений за последний месяц (сценарий «тендер / бюджет»)
SELECT loading_city, unloading_city, body_group, weight_category,
       p25_trip, median_trip, p75_trip, median_km, trips_count, carriers_count, mom_pct, yoy_pct, reliability_level
FROM mart.mart_route_card
WHERE month = DATE '2026-10-01' AND reliability_level <> 'LOW_DATA'
ORDER BY trips_count DESC;

-- Карточка одного маршрута: помесячная история коридора (сценарий «спот / разбор отклонений»)
SELECT month, p25_trip, median_trip, p75_trip, p25_km, median_km, p75_km,
       trips_count, carriers_count, cv_rate, mom_pct, yoy_pct, reliability_level
FROM mart.mart_route_card
WHERE loading_city = 'Москва' AND unloading_city = 'Ростов-на-Дону'
  AND body_group = 'Тент' AND weight_category = 'FTL'
ORDER BY month;

-- Независимая сверка ячейки с core: перцентили по сырым сделкам должны совпасть с витриной
SELECT count(DISTINCT p.price_id) AS trips,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY p.price_rub)::numeric, 2) AS median_trip
FROM core.prices p
JOIN core.price_dates d       ON d.price_id = p.price_id AND d.month = DATE '2026-10-01'
JOIN core.price_body_groups g ON g.price_id = p.price_id AND g.body_group = 'Тент'
WHERE p.loading_city_gcid = 1001 AND p.unloading_city_gcid = 1008 AND p.weight_category = 'FTL'
  AND p.is_fact AND NOT p.complex AND NOT p.outlier_mark AND d.price_date <= DATE '2026-10-26';
-- → 112 | 126991.51, как в mart.mart_route_card
```

## Решения и допущения

- **Источник и хранилище — две базы в одном контейнере PostgreSQL.** ETL переносит данные через подключение,
  как с внешней OLTP-базой; вынести источник наружу — смена `DB_HOST`.
- **Идемпотентность — атомарная перезапись окна (`DELETE` + `INSERT` в одной транзакции).** В отличие от
  `ON CONFLICT`, удаляет и строки, исчезнувшие из источника внутри окна; читатели видят либо старое, либо
  новое состояние окна (MVCC). Справочники перезаписываются целиком через `DELETE` (не `TRUNCATE`:
  он берёт эксклюзивную блокировку и не MVCC-безопасен для параллельных читателей).
- **Окно передаётся SQL-файлам через `set_config('etl.window_*', ..., true)`**, локально для транзакции, —
  трансформации лежат в `sql/etl/` обычными SQL-файлами без параметров.
- **В `core` сохраняются все сделки, прошедшие DQ, включая ставки торгов (`price_type = 6`) и составные
  маршруты.** Это не битые данные, а другой scope: фильтры `is_fact`, `complex`, `outlier_mark` применяют
  витрины и ML.
- **`price_group_id` в `core` не переносится**: групповые агрегаты по таргету недоступны ML по построению.
- **Совпадение городов погрузки и выгрузки не отбраковывается** — по заданию это не production-DQ-правило.
- **Курс валюты.** USD/EUR конвертируются строго по курсу на `nearest_rate_date`; нет даты или нет курса на
  эту дату — карантин, без fallback по `loading_date`. RUB конвертируется с курсом 1.0 и при
  `nearest_rate_date IS NULL` (1 428 строк): требование точного курса относится к иностранной валюте.
- **Правило `price <= 1000` применяется только к RUB** (`0 < price <= 1000`, отдельный код причины).
- **Категории заполняются только при пропуске** (`COALESCE(источник, правило)`), значения источника не
  перезаписываются. Вес округляется до 0.1 т на `numeric` (половина — от нуля), функции
  `core.f_weight_category` / `core.f_volume_category`.
- **Группы кузова.** Все группы сделки — в `core.price_body_groups`: связи из `price_body_types`
  (одна строка на группу: 56 + 61 → один «Тент»; 56 + 15 → «Тент» и «Борт»), без связей — группа
  `prices.body_type`, при `NULL` — «Не указан»; код вне справочника — «Прочие». Для ML и прогнозов нужна одна
  группа на сделку — `core.prices.body_group`: группа `prices.body_type`, иначе связь с минимальным `std_id`,
  иначе «Не указан».
- **В `core` нет внешних ключей**: справочники перезаписываются через `DELETE`, а ссылочную целостность
  сделок обеспечивают DQ-правила.
- **Дата снимка `AS_OF = 2026-10-26` задаётся параметром**, а не системной датой: граница истории витрины
  и точка отсчёта свежести.
- **Перцентили — `percentile_cont`** (линейная интерполяция, как numpy / pandas по умолчанию и как в
  источнике при расчёте `price_group_stats`). На малых выборках даёт гладкую медиану (на двух сделках — их
  среднее), `percentile_disc` вернул бы одно из наблюдений.
- **Сделка в витрине — одна строка на «сделка × месяц × группа кузова»**: сделка с кузовами двух групп
  учитывается в обеих, но внутри группы — один раз.
- **Пересчёт витрины — месяцы `[month(start_date), month(as_of)]`**, а не только окно загрузки: долгосрочная
  заявка из окна присутствует и в более поздних месяцах, в более ранние не попадает никогда.
- **MoM / YoY и `reliability_level` — в представлении**, а не в таблице: пересчёт месяца M иначе оставлял бы
  устаревшими MoM месяца M+1 и YoY месяца M+12. Сравнение — только с ячейкой календарно предыдущего месяца /
  того же месяца прошлого года, по `median_trip`; нет ячейки — `NULL`.
- **Свежесть для `HIGH` — `as_of − max(price_date) ячейки ≤ 30 дней`.** Исторические месяцы поэтому
  никогда не получают `HIGH`, даже при плотной выборке.
- **`volume_category` в витрину не входит** ни в зерно, ни атрибутом: в ячейке сделки с разной объёмной
  категорией, единственного значения у ячейки нет.
- **Последний день снимка не размечен по выбросам.** `outlier_mark` проставляет ночной джоб (до 02:30);
  записи, созданные 2026-10-26 после него, имеют `outlier_mark = false` по умолчанию, флаг не пересчитывается —
  это входной фильтр. Проверка на данных: таких записей 5 790, и **все они — плановые погрузки после as_of**
  (`loading_date` 2026-10-27 … 2027-02-13; 4 862 факта и 928 ставок торгов). В генераторе `created_at`
  отстоит от `loading_date` не более чем на ~2 часа вперёд, поэтому ни одна сделка с погрузкой до 26.10
  не создана после разметки: в историю витрины и в train/test ML неразмеченные записи не попадают. Ограничение
  касается только будущих заявок — для них `outlier_mark` не используется (таргета нет).
- **Флаг источника неполный и вне последнего дня.** По коду генератора выбросы (×0.25 / ×4) создаются для
  2,4 % строк, а помечаются 2 %: около 0,4 % ценовых аномалий не размечены никогда. В базовом решении флаг
  не пересчитывается (по заданию), такие строки остаются в витрине и в ML-выборках.

## Ограничения

- Окно выгружается по `prices.loading_date`, а в источнике нет индекса по этому полю — выгрузка делает полный
  проход `prices` (на 300 тыс. строк незаметно). В production — индекс или инкрементальная выгрузка по
  `updated_at` / CDC.
- Ключ окна должен быть неизменным: если у сделки в источнике изменится `loading_date`, её старая копия
  останется в прежнем окне (повторная загрузка нового окна упадёт на PK `raw.prices`, а не задвоит данные).
  Для изменяемых данных нужен upsert по `id` с tombstone-удалениями (CDC).

## Структура

```
docker-compose.yml, .env.example, pyproject.toml, requirements.txt
docker/                    Dockerfile пайплайна, init-скрипт PostgreSQL, run_pipeline.sh
sql/source/                схема и генератор источника (выданы с заданием, без изменений)
sql/dwh/                   DDL хранилища (raw, core, mart), идемпотентный
sql/etl/                   SQL-трансформации загрузки окна raw → core
sql/mart/                  SQL пересчёта витрины mart.route_month_stats
common/                    конфигурация из env, подключение к БД, JSON-логирование
etl/                       CLI (`python -m etl migrate | load | mart`), extract (COPY), DQ-правила, загрузка, витрина
tests/                     pytest: DQ, категории, справочники, группы кузова, витрина, идемпотентность
```
