-- сделки рынка из core.market_deals; названия городов денормализованы, LowCardinality их сжимает
CREATE TABLE IF NOT EXISTS market_deals
(
    month               Date,
    loading_city_gcid   UInt32,
    unloading_city_gcid UInt32,
    body_group          LowCardinality(String),
    weight_category     LowCardinality(String),
    price_id            UInt64,
    loading_city        LowCardinality(String),
    loading_region      LowCardinality(Nullable(String)),
    unloading_city      LowCardinality(String),
    unloading_region    LowCardinality(Nullable(String)),
    organization_id     Nullable(UInt32),
    price_type          UInt8,
    price_rub           Decimal(14, 2),
    price_km            Float64,
    last_price_date     Date
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(month)
ORDER BY (loading_city_gcid, unloading_city_gcid, body_group, weight_category, month, price_id);

-- staging с той же структурой и секционированием: из него секции подменяются через REPLACE PARTITION
CREATE TABLE IF NOT EXISTS market_deals_stage AS market_deals;

CREATE TABLE IF NOT EXISTS route_month_stats
(
    month               Date,
    loading_city_gcid   UInt32,
    unloading_city_gcid UInt32,
    body_group          LowCardinality(String),
    weight_category     LowCardinality(String),
    loading_city        LowCardinality(String),
    loading_region      LowCardinality(Nullable(String)),
    unloading_city      LowCardinality(String),
    unloading_region    LowCardinality(Nullable(String)),
    p25_trip            Decimal(14, 2),
    median_trip         Decimal(14, 2),
    p75_trip            Decimal(14, 2),
    avg_trip            Decimal(14, 2),
    p25_km              Decimal(12, 2),
    median_km           Decimal(12, 2),
    p75_km              Decimal(12, 2),
    trips_count         UInt32,
    carriers_count      UInt32,
    cv_rate             Nullable(Decimal(10, 4)),
    last_price_date     Date,
    as_of               Date
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(month)
ORDER BY (loading_city_gcid, unloading_city_gcid, body_group, weight_category, month);

CREATE TABLE IF NOT EXISTS route_month_stats_stage AS route_month_stats;

CREATE OR REPLACE VIEW route_card AS
SELECT c.month AS month,
       c.loading_city_gcid AS loading_city_gcid,
       c.loading_city AS loading_city,
       c.loading_region AS loading_region,
       c.unloading_city_gcid AS unloading_city_gcid,
       c.unloading_city AS unloading_city,
       c.unloading_region AS unloading_region,
       c.body_group AS body_group,
       c.weight_category AS weight_category,
       c.p25_trip AS p25_trip,
       c.median_trip AS median_trip,
       c.p75_trip AS p75_trip,
       c.avg_trip AS avg_trip,
       c.p25_km AS p25_km,
       c.median_km AS median_km,
       c.p75_km AS p75_km,
       c.trips_count AS trips_count,
       c.carriers_count AS carriers_count,
       c.cv_rate AS cv_rate,
       c.last_price_date AS last_price_date,
       c.as_of AS as_of,
       -- Decimal / Decimal сохраняет масштаб делимого, поэтому поднимаем его до 10 знаков
       round((toDecimal128(c.median_trip, 10) / nullIf(prev_month.median_trip, 0) - 1) * 100, 2) AS mom_pct,
       round((toDecimal128(c.median_trip, 10) / nullIf(prev_year.median_trip, 0) - 1) * 100, 2)  AS yoy_pct,
       multiIf(c.trips_count >= 30 AND c.carriers_count >= 5 AND dateDiff('day', c.last_price_date, c.as_of) <= 30, 'HIGH',
               c.trips_count >= 10, 'MEDIUM',
               'LOW_DATA') AS reliability_level
FROM route_month_stats AS c
LEFT JOIN route_month_stats AS prev_month
       ON prev_month.loading_city_gcid = c.loading_city_gcid
      AND prev_month.unloading_city_gcid = c.unloading_city_gcid
      AND prev_month.body_group = c.body_group
      AND prev_month.weight_category = c.weight_category
      AND prev_month.month = addMonths(c.month, -1)
LEFT JOIN route_month_stats AS prev_year
       ON prev_year.loading_city_gcid = c.loading_city_gcid
      AND prev_year.unloading_city_gcid = c.unloading_city_gcid
      AND prev_year.body_group = c.body_group
      AND prev_year.weight_category = c.weight_category
      AND prev_year.month = addMonths(c.month, -12)
SETTINGS join_use_nulls = 1;
