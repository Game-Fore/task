-- группы из price_body_types; если связей нет — группа prices.body_type, при NULL 'Не указан'.
-- UNION схлопывает повторы, поэтому 56 + 61 дают один 'Тент'
INSERT INTO core.price_body_groups (price_id, body_group)
SELECT pbt.price_id, coalesce(bt.body_group, 'Прочие')
FROM raw.price_body_types pbt
JOIN core.prices p ON p.price_id = pbt.price_id
LEFT JOIN core.dim_body_type bt ON bt.body_type_id = pbt.body_type_id
WHERE p.loading_date BETWEEN core.etl_window_start() AND core.etl_window_end()
UNION
SELECT p.price_id,
       CASE WHEN p.body_type IS NULL THEN 'Не указан' ELSE coalesce(bt.body_group, 'Прочие') END
FROM core.prices p
LEFT JOIN core.dim_body_type bt ON bt.body_type_id = p.body_type
WHERE p.loading_date BETWEEN core.etl_window_start() AND core.etl_window_end()
  AND NOT EXISTS (SELECT 1 FROM raw.price_body_types x WHERE x.price_id = p.price_id);
