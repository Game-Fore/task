-- та же витрина, что в PostgreSQL. quantileExactInclusive интерполирует как percentile_cont.
-- Округление повторяет float8 → numeric в PostgreSQL: toDecimal128 от float усекает (96964.894999…),
-- поэтому сначала округляем float и переводим в Decimal через строку, затем round по Decimal — половина от нуля
INSERT INTO route_month_stats_stage
SELECT month,
       loading_city_gcid,
       unloading_city_gcid,
       body_group,
       weight_category,
       any(loading_city),
       any(loading_region),
       any(unloading_city),
       any(unloading_region),
       round(toDecimal128(toString(round(quantileExactInclusive(0.25)(toFloat64(price_rub)), 6)), 6), 2),
       round(toDecimal128(toString(round(quantileExactInclusive(0.50)(toFloat64(price_rub)), 6)), 6), 2),
       round(toDecimal128(toString(round(quantileExactInclusive(0.75)(toFloat64(price_rub)), 6)), 6), 2),
       round(toDecimal128(toString(round(avg(toFloat64(price_rub)), 6)), 6), 2),
       round(toDecimal128(toString(round(quantileExactInclusive(0.25)(price_km), 6)), 6), 2),
       round(toDecimal128(toString(round(quantileExactInclusive(0.50)(price_km), 6)), 6), 2),
       round(toDecimal128(toString(round(quantileExactInclusive(0.75)(price_km), 6)), 6), 2),
       uniqExact(price_id),
       uniqExactIf(organization_id, price_type IN (3, 9)),
       if(count() >= 2 AND avg(toFloat64(price_rub)) != 0,
          round(toDecimal128(toString(round(stddevSamp(toFloat64(price_rub)) / avg(toFloat64(price_rub)), 8)), 8), 4),
          NULL),
       max(last_price_date),
       {as_of:Date}
FROM market_deals_stage
GROUP BY month, loading_city_gcid, unloading_city_gcid, body_group, weight_category
