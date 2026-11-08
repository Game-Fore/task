-- Карантин: строки окна, нарушившие хотя бы одно DQ-правило (stg_prices строит etl/dq_rules.py).
INSERT INTO core.dq_quarantine_prices (price_id, loading_date, reasons, raw_row)
SELECT s.id,
       s.loading_date,
       s.dq_reasons,
       to_jsonb(s) - 'dq_reasons' - 'fx_rate' - '_loaded_at'
FROM stg_prices s
WHERE cardinality(s.dq_reasons) > 0;
