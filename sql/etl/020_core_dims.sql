-- Справочники core: полная перезапись из raw.

-- gc_id в источнике не уникален: оставляем строку с минимальным cities.id.
-- Без этого JOIN сделок со справочником размножит строки.
-- Город и регион — по первой запятой full_name_local: 'Казань, Республика Татарстан'.
DELETE FROM core.dim_city;
INSERT INTO core.dim_city (gc_id, source_city_id, city_name, region_name, full_name_local, latitude, longitude)
SELECT DISTINCT ON (c.gc_id)
       c.gc_id,
       c.id,
       btrim(split_part(c.full_name_local, ',', 1)),
       CASE WHEN strpos(c.full_name_local, ',') > 0
            THEN nullif(btrim(substr(c.full_name_local, strpos(c.full_name_local, ',') + 1)), '')
       END,
       c.full_name_local,
       c.latitude,
       c.longitude
FROM raw.cities c
ORDER BY c.gc_id, c.id;

-- Бизнес-группа кузова по стандарту std_id: Тент (56), Рефрижератор (4), Изотерм (2), Борт (15),
-- остальные стандарты — Прочие.
DELETE FROM core.dim_body_type;
INSERT INTO core.dim_body_type (body_type_id, name, std_id, body_group)
SELECT b.id,
       b.name,
       b.std_id,
       CASE b.std_id
           WHEN 56 THEN 'Тент'
           WHEN 4  THEN 'Рефрижератор'
           WHEN 2  THEN 'Изотерм'
           WHEN 15 THEN 'Борт'
           ELSE 'Прочие'
       END
FROM raw.body_types b;

DELETE FROM core.exchange_rates;
INSERT INTO core.exchange_rates (currency_code, rate_date, rate)
SELECT r.num_code, r.setting_date, r.value
FROM raw.exchange_rates r;
