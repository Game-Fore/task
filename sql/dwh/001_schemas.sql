-- Слои хранилища dwh.
CREATE SCHEMA IF NOT EXISTS raw;
COMMENT ON SCHEMA raw IS 'Копия таблиц источника deals_bigdata 1:1 (сделки за окно загрузки, справочники целиком)';

CREATE SCHEMA IF NOT EXISTS core;
COMMENT ON SCHEMA core IS 'Очищенные и нормализованные данные: DQ, карантин, price_rub, дедуплицированные измерения';

CREATE SCHEMA IF NOT EXISTS mart;
COMMENT ON SCHEMA mart IS 'Аналитические витрины для BI и прогнозы ML';
