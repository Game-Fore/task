-- Очистка raw перед копированием: окно сделок (сначала дочерние строки) и справочники целиком.
DELETE FROM raw.price_dates
WHERE price_id IN (SELECT id FROM raw.prices
                   WHERE loading_date BETWEEN core.etl_window_start() AND core.etl_window_end());

DELETE FROM raw.price_body_types
WHERE price_id IN (SELECT id FROM raw.prices
                   WHERE loading_date BETWEEN core.etl_window_start() AND core.etl_window_end());

DELETE FROM raw.prices
WHERE loading_date BETWEEN core.etl_window_start() AND core.etl_window_end();

-- DELETE, а не TRUNCATE: TRUNCATE берёт ACCESS EXCLUSIVE и не MVCC-безопасен для параллельных читателей.
DELETE FROM raw.cities;
DELETE FROM raw.body_types;
DELETE FROM raw.exchange_rates;
