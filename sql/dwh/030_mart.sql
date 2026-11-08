-- mart: карточка маршрута и рыночный коридор ставок.
--
-- route_month_stats — базовые метрики ячейки, пересчитываются ETL-шагом `etl mart`.
-- mart_route_card   — представление для BI: + MoM/YoY и уровень надёжности. Сравнения с соседними
--                     месяцами вынесены во view, чтобы пересчёт месяца M никогда не оставлял устаревшими
--                     MoM месяца M+1 и YoY месяца M+12.

CREATE TABLE IF NOT EXISTS mart.route_month_stats (
    -- зерно: месяц × город отправления × город назначения × группа кузова × весовая категория
    month               date           NOT NULL,
    loading_city_gcid   integer        NOT NULL,
    unloading_city_gcid integer        NOT NULL,
    body_group          text           NOT NULL,
    weight_category     varchar(4)     NOT NULL,
    -- атрибуты для BI (денормализованы из core.dim_city)
    loading_city        text           NOT NULL,
    loading_region      text,
    unloading_city      text           NOT NULL,
    unloading_region    text,
    -- рыночный коридор, руб./рейс без НДС
    p25_trip            numeric(14, 2) NOT NULL,
    median_trip         numeric(14, 2) NOT NULL,
    p75_trip            numeric(14, 2) NOT NULL,
    avg_trip            numeric(14, 2) NOT NULL,
    -- рыночный коридор, руб./км
    p25_km              numeric(12, 2) NOT NULL,
    median_km           numeric(12, 2) NOT NULL,
    p75_km              numeric(12, 2) NOT NULL,
    -- доказательная база
    trips_count         integer        NOT NULL,
    carriers_count      integer        NOT NULL,
    cv_rate             numeric(10, 4),
    last_price_date     date           NOT NULL,
    as_of               date           NOT NULL,
    refreshed_at        timestamptz    NOT NULL DEFAULT now(),
    PRIMARY KEY (month, loading_city_gcid, unloading_city_gcid, body_group, weight_category)
);
-- Сценарий «карточка одного маршрута»: история по паре городов, кузову и весу.
CREATE INDEX IF NOT EXISTS route_month_stats_route_idx
    ON mart.route_month_stats (loading_city_gcid, unloading_city_gcid, body_group, weight_category, month);

CREATE OR REPLACE VIEW mart.mart_route_card AS
SELECT c.month,
       c.loading_city_gcid,
       c.loading_city,
       c.loading_region,
       c.unloading_city_gcid,
       c.unloading_city,
       c.unloading_region,
       c.body_group,
       c.weight_category,
       c.p25_trip,
       c.median_trip,
       c.p75_trip,
       c.avg_trip,
       c.p25_km,
       c.median_km,
       c.p75_km,
       c.trips_count,
       c.carriers_count,
       c.cv_rate,
       -- только календарно предыдущий месяц / тот же месяц прошлого года; нет ячейки — NULL
       round((c.median_trip / nullif(prev_month.median_trip, 0) - 1) * 100, 2) AS mom_pct,
       round((c.median_trip / nullif(prev_year.median_trip, 0) - 1) * 100, 2)  AS yoy_pct,
       CASE
           WHEN c.trips_count >= 30 AND c.carriers_count >= 5 AND c.as_of - c.last_price_date <= 30 THEN 'HIGH'
           WHEN c.trips_count >= 10 THEN 'MEDIUM'
           ELSE 'LOW_DATA'
       END AS reliability_level,
       c.last_price_date,
       c.as_of,
       c.refreshed_at
FROM mart.route_month_stats c
LEFT JOIN mart.route_month_stats prev_month
       ON prev_month.month = (c.month - interval '1 month')::date
      AND prev_month.loading_city_gcid = c.loading_city_gcid
      AND prev_month.unloading_city_gcid = c.unloading_city_gcid
      AND prev_month.body_group = c.body_group
      AND prev_month.weight_category = c.weight_category
LEFT JOIN mart.route_month_stats prev_year
       ON prev_year.month = (c.month - interval '12 months')::date
      AND prev_year.loading_city_gcid = c.loading_city_gcid
      AND prev_year.unloading_city_gcid = c.unloading_city_gcid
      AND prev_year.body_group = c.body_group
      AND prev_year.weight_category = c.weight_category;
