-- внешних ключей нет: справочники перезаписываются целиком, целостность держат DQ-правила

-- параметры шага задаются set_config(..., true) на время транзакции
CREATE OR REPLACE FUNCTION core.etl_window_start() RETURNS date
    LANGUAGE sql STABLE AS $$ SELECT current_setting('etl.window_start')::date $$;
CREATE OR REPLACE FUNCTION core.etl_window_end() RETURNS date
    LANGUAGE sql STABLE AS $$ SELECT current_setting('etl.window_end')::date $$;
CREATE OR REPLACE FUNCTION core.etl_as_of() RETURNS date
    LANGUAGE sql STABLE AS $$ SELECT current_setting('etl.as_of')::date $$;

-- округление на numeric, а не float: 0.45 → 0.5 и 9.95 → 10.0
CREATE OR REPLACE FUNCTION core.f_weight_category(weight_t double precision) RETURNS varchar(4)
    LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
               WHEN w IS NULL THEN NULL
               WHEN w >= 30  THEN 'G20T'
               WHEN w >= 10  THEN 'FTL'
               WHEN w >= 5   THEN '10T'
               WHEN w >= 2.5 THEN '5T'
               WHEN w >= 0.5 THEN 'L5T'
               ELSE 'OTH'
           END
    FROM (SELECT round(weight_t::numeric, 1)) AS t(w)
$$;

CREATE OR REPLACE FUNCTION core.f_volume_category(volume_m3 double precision) RETURNS varchar(4)
    LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
               WHEN volume_m3 IS NULL THEN NULL
               WHEN volume_m3 > 0 AND volume_m3 <= 120 THEN 'FTL'
               ELSE 'OTH'
           END
$$;

CREATE TABLE IF NOT EXISTS core.dim_city (
    gc_id           integer PRIMARY KEY,
    source_city_id  bigint  NOT NULL,
    city_name       text    NOT NULL,
    region_name     text,
    full_name_local text    NOT NULL,
    latitude        double precision,
    longitude       double precision
);

CREATE TABLE IF NOT EXISTS core.dim_body_type (
    body_type_id integer PRIMARY KEY,
    name         text    NOT NULL,
    std_id       integer,
    body_group   text    NOT NULL
);

-- PK не даст дублю курса размножить сделки при JOIN: загрузка упадёт сразу
CREATE TABLE IF NOT EXISTS core.exchange_rates (
    currency_code varchar(3)       NOT NULL,
    rate_date     date             NOT NULL,
    rate          double precision NOT NULL,
    PRIMARY KEY (currency_code, rate_date)
);

-- все сделки, прошедшие DQ; scope (is_fact, complex, outlier_mark) применяют витрина и ML.
-- price_group_id сюда не переносим, чтобы агрегаты по таргету не могли попасть в модель
CREATE TABLE IF NOT EXISTS core.prices (
    price_id            bigint PRIMARY KEY,
    created_at          timestamp(0),
    loading_date        date             NOT NULL,
    end_loading_date    date,
    loading_city_gcid   integer          NOT NULL,
    unloading_city_gcid integer          NOT NULL,
    distance            double precision NOT NULL,
    total_weight        double precision NOT NULL,
    total_volume        double precision NOT NULL,
    body_type           integer,
    body_group          text             NOT NULL,
    organization_id     integer,
    price_type          smallint         NOT NULL,
    is_fact             boolean          NOT NULL,
    complex             boolean          NOT NULL,
    outlier_mark        boolean          NOT NULL,
    currency_code       varchar(3)       NOT NULL,
    price               double precision NOT NULL,
    nearest_rate_date   date,
    fx_rate             double precision NOT NULL,
    price_rub           numeric(14, 2)   NOT NULL,
    weight_category     varchar(4)       NOT NULL,
    volume_category     varchar(4)       NOT NULL,
    loaded_at           timestamptz      NOT NULL DEFAULT now(),
    CONSTRAINT prices_body_group_chk
        CHECK (body_group IN ('Тент', 'Рефрижератор', 'Изотерм', 'Борт', 'Прочие', 'Не указан'))
);
CREATE INDEX IF NOT EXISTS core_prices_loading_date_idx ON core.prices (loading_date);

CREATE TABLE IF NOT EXISTS core.price_body_groups (
    price_id   bigint NOT NULL,
    body_group text   NOT NULL,
    PRIMARY KEY (price_id, body_group),
    CONSTRAINT price_body_groups_body_group_chk
        CHECK (body_group IN ('Тент', 'Рефрижератор', 'Изотерм', 'Борт', 'Прочие', 'Не указан'))
);

CREATE TABLE IF NOT EXISTS core.price_dates (
    price_id   bigint NOT NULL,
    price_date date   NOT NULL,
    month      date   NOT NULL,
    PRIMARY KEY (price_id, price_date)
);
CREATE INDEX IF NOT EXISTS core_price_dates_month_idx ON core.price_dates (month);

CREATE TABLE IF NOT EXISTS core.dq_quarantine_prices (
    price_id       bigint      PRIMARY KEY,
    loading_date   date        NOT NULL,
    reasons        text[]      NOT NULL CHECK (cardinality(reasons) > 0),
    raw_row        jsonb       NOT NULL,
    quarantined_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS core_dq_quarantine_loading_date_idx ON core.dq_quarantine_prices (loading_date);

-- сделки рынка: одна строка на сделку × месяц × группу кузова, только scope витрины.
-- Из него считают витрину и PostgreSQL, и ClickHouse; as_of задаётся через set_config
CREATE OR REPLACE VIEW core.market_deals AS
SELECT p.price_id,
       d.month,
       g.body_group,
       p.loading_city_gcid,
       p.unloading_city_gcid,
       p.weight_category,
       p.organization_id,
       p.price_type,
       p.price_rub,
       p.price_rub / p.distance AS price_km,
       max(d.price_date)        AS last_price_date
FROM core.prices p
JOIN core.price_dates d       ON d.price_id = p.price_id
JOIN core.price_body_groups g ON g.price_id = p.price_id
WHERE p.price_type IN (1, 2, 3, 4, 5, 9)
  AND NOT p.complex
  AND NOT p.outlier_mark
  AND p.price > 0 AND p.distance > 0
  AND d.price_date <= core.etl_as_of()
GROUP BY p.price_id, d.month, g.body_group;
