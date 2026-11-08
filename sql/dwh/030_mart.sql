CREATE TABLE IF NOT EXISTS mart.route_month_stats (
    month               date           NOT NULL,
    loading_city_gcid   integer        NOT NULL,
    unloading_city_gcid integer        NOT NULL,
    body_group          text           NOT NULL,
    weight_category     varchar(4)     NOT NULL,
    loading_city        text           NOT NULL,
    loading_region      text,
    unloading_city      text           NOT NULL,
    unloading_region    text,
    p25_trip            numeric(14, 2) NOT NULL,
    median_trip         numeric(14, 2) NOT NULL,
    p75_trip            numeric(14, 2) NOT NULL,
    avg_trip            numeric(14, 2) NOT NULL,
    p25_km              numeric(12, 2) NOT NULL,
    median_km           numeric(12, 2) NOT NULL,
    p75_km              numeric(12, 2) NOT NULL,
    trips_count         integer        NOT NULL,
    carriers_count      integer        NOT NULL,
    cv_rate             numeric(10, 4),
    last_price_date     date           NOT NULL,
    as_of               date           NOT NULL,
    refreshed_at        timestamptz    NOT NULL DEFAULT now(),
    PRIMARY KEY (month, loading_city_gcid, unloading_city_gcid, body_group, weight_category)
);
CREATE INDEX IF NOT EXISTS route_month_stats_route_idx
    ON mart.route_month_stats (loading_city_gcid, unloading_city_gcid, body_group, weight_category, month);

-- MoM/YoY во view, а не в таблице: иначе пересчёт месяца оставлял бы устаревшими соседние
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
