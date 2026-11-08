-- Очистка окна в core перед вставкой (атомарная перезапись окна: DELETE + INSERT в одной транзакции).
DELETE FROM core.price_dates
WHERE price_id IN (SELECT price_id FROM core.prices
                   WHERE loading_date BETWEEN core.etl_window_start() AND core.etl_window_end());

DELETE FROM core.price_body_groups
WHERE price_id IN (SELECT price_id FROM core.prices
                   WHERE loading_date BETWEEN core.etl_window_start() AND core.etl_window_end());

DELETE FROM core.prices
WHERE loading_date BETWEEN core.etl_window_start() AND core.etl_window_end();

DELETE FROM core.dq_quarantine_prices
WHERE loading_date BETWEEN core.etl_window_start() AND core.etl_window_end();
