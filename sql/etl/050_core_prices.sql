-- Валидные сделки окна → core.prices.
-- body_group здесь — ОСНОВНАЯ группа сделки (одна на цену, для ML и прогнозов):
--   группа prices.body_type → иначе группа связи из price_body_types с минимальным std_id → 'Не указан'.
-- Все группы сделки (для витрины) — в core.price_body_groups.
INSERT INTO core.prices (
    price_id, created_at, loading_date, end_loading_date, loading_city_gcid, unloading_city_gcid,
    distance, total_weight, total_volume, body_type, body_group, organization_id, price_type,
    is_fact, complex, outlier_mark, currency_code, price, nearest_rate_date, fx_rate, price_rub,
    weight_category, volume_category
)
SELECT s.id,
       s.created_at,
       s.loading_date,
       s.end_loading_date,
       s.loading_city_gcid,
       s.unloading_city_gcid,
       s.distance,
       s.total_weight,
       s.total_volume,
       s.body_type,
       CASE
           WHEN s.body_type IS NOT NULL THEN coalesce(main_bt.body_group, 'Прочие')
           ELSE coalesce(linked_bt.body_group, 'Не указан')
       END,
       s.organization_id,
       s.price_type,
       s.is_fact,
       s.complex,
       s.outlier_mark,
       s.currency_code,
       s.price,
       s.nearest_rate_date,
       s.fx_rate,
       round((s.price * s.fx_rate)::numeric, 2),
       coalesce(s.weight_category, core.f_weight_category(s.total_weight)),
       coalesce(s.volume_category, core.f_volume_category(s.total_volume))
FROM stg_prices s
LEFT JOIN core.dim_body_type main_bt ON main_bt.body_type_id = s.body_type
LEFT JOIN LATERAL (
    SELECT coalesce(bt.body_group, 'Прочие') AS body_group
    FROM raw.price_body_types pbt
    LEFT JOIN core.dim_body_type bt ON bt.body_type_id = pbt.body_type_id
    WHERE pbt.price_id = s.id
    ORDER BY bt.std_id NULLS LAST, pbt.body_type_id
    LIMIT 1
) linked_bt ON s.body_type IS NULL
WHERE cardinality(s.dq_reasons) = 0;
