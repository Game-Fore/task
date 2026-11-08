-- Все группы кузова сделки, без дублей внутри группы.
-- Есть связи в price_body_types → группы связанных типов (56 + 61 → один 'Тент'; 56 + 15 → 'Тент' и 'Борт').
-- Связей нет → fallback на prices.body_type, при NULL — 'Не указан'. Неизвестный код типа — 'Прочие'.
INSERT INTO core.price_body_groups (price_id, body_group)
SELECT pbt.price_id, coalesce(bt.body_group, 'Прочие')
FROM raw.price_body_types pbt
JOIN core.prices p ON p.price_id = pbt.price_id
LEFT JOIN core.dim_body_type bt ON bt.body_type_id = pbt.body_type_id
WHERE p.loading_date BETWEEN core.etl_window_start() AND core.etl_window_end()
UNION  -- UNION (не UNION ALL) схлопывает одинаковые группы одной цены
SELECT p.price_id,
       CASE WHEN p.body_type IS NULL THEN 'Не указан' ELSE coalesce(bt.body_group, 'Прочие') END
FROM core.prices p
LEFT JOIN core.dim_body_type bt ON bt.body_type_id = p.body_type
WHERE p.loading_date BETWEEN core.etl_window_start() AND core.etl_window_end()
  AND NOT EXISTS (SELECT 1 FROM raw.price_body_types x WHERE x.price_id = p.price_id);
