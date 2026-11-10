-- пересчитываем до as_of, а не до конца окна: долгосрочная заявка живёт и в следующих месяцах
DELETE FROM mart.route_month_stats
WHERE month BETWEEN date_trunc('month', core.etl_window_start())::date
                AND date_trunc('month', core.etl_as_of())::date;

INSERT INTO mart.route_month_stats (
    month, loading_city_gcid, unloading_city_gcid, body_group, weight_category,
    loading_city, loading_region, unloading_city, unloading_region,
    p25_trip, median_trip, p75_trip, avg_trip, p25_km, median_km, p75_km,
    trips_count, carriers_count, cv_rate, last_price_date, as_of
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
FROM core.market_deals m
JOIN core.dim_city lc ON lc.gc_id = m.loading_city_gcid
JOIN core.dim_city uc ON uc.gc_id = m.unloading_city_gcid
WHERE m.month >= date_trunc('month', core.etl_window_start())
GROUP BY m.month, lc.gc_id, uc.gc_id, m.body_group, m.weight_category;
