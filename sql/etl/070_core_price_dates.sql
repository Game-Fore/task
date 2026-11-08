-- Помесячная развёртка валидных сделок окна. Будущие даты сохраняются: отсечение по as_of — в витрине.
INSERT INTO core.price_dates (price_id, price_date, month)
SELECT d.price_id, d.price_date, date_trunc('month', d.price_date)::date
FROM raw.price_dates d
JOIN core.prices p ON p.price_id = d.price_id
WHERE p.loading_date BETWEEN core.etl_window_start() AND core.etl_window_end();
