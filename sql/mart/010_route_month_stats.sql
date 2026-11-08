-- Пересчёт mart.route_month_stats за месяцы [month(window_start), month(as_of)].
-- Почему до as_of, а не до конца окна: долгосрочная заявка из окна живёт и в более поздних месяцах
-- (price_dates идут от loading_date вперёд), а в более ранние не попадает никогда.

DELETE FROM mart.route_month_stats
WHERE month BETWEEN date_trunc('month', core.etl_window_start())::date
                AND date_trunc('month', core.etl_as_of())::date;

INSERT INTO mart.route_month_stats (
    month, loading_city_gcid, unloading_city_gcid, body_group, weight_category,
    loading_city, loading_region, unloading_city, unloading_region,
    p25_trip, median_trip, p75_trip, avg_trip, p25_km, median_km, p75_km,
    trips_count, carriers_count, cv_rate, last_price_date, as_of
)
WITH market_deals AS (
    -- Одна строка на сделку × месяц × группу кузова: даже если у сделки окажутся две даты
    -- в одном месяце, в перцентили она войдёт один раз. Сделка с кузовами из двух групп
    -- учитывается в обеих группах (по требованию), но внутри группы — один раз.
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
    WHERE p.price_type IN (1, 2, 3, 4, 5, 9)          -- только факты (is_fact); ставки торгов (6) вне scope
      AND NOT p.complex                               -- простые прямые маршруты
      AND NOT p.outlier_mark                          -- выбросы по входному флагу источника
      AND p.price > 0 AND p.distance > 0              -- гарантировано DQ, повторено для независимости витрины
      AND d.price_date <= core.etl_as_of()            -- плановые даты после снимка — не история рынка
      AND d.month >= date_trunc('month', core.etl_window_start())
    GROUP BY p.price_id, d.month, g.body_group
)
SELECT m.month,
       lc.gc_id,
       uc.gc_id,
       m.body_group,
       m.weight_category,
       lc.city_name,
       lc.region_name,
       uc.city_name,
       uc.region_name,
       -- percentile_cont: линейная интерполяция между соседними наблюдениями (как numpy/pandas по умолчанию)
       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY m.price_rub)::numeric, 2),
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY m.price_rub)::numeric, 2),
       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY m.price_rub)::numeric, 2),
       round(avg(m.price_rub), 2),
       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY m.price_km)::numeric, 2),
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY m.price_km)::numeric, 2),
       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY m.price_km)::numeric, 2),
       count(DISTINCT m.price_id),
       count(DISTINCT m.organization_id) FILTER (WHERE m.price_type IN (3, 9)),
       CASE WHEN count(*) >= 2 AND avg(m.price_rub) <> 0
            THEN round(stddev_samp(m.price_rub) / avg(m.price_rub), 4)
       END,
       max(m.last_price_date),
       core.etl_as_of()
FROM market_deals m
JOIN core.dim_city lc ON lc.gc_id = m.loading_city_gcid
JOIN core.dim_city uc ON uc.gc_id = m.unloading_city_gcid
GROUP BY m.month, lc.gc_id, uc.gc_id, m.body_group, m.weight_category;
