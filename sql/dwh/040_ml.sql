CREATE TABLE IF NOT EXISTS mart.ml_price_predictions (
    price_id            bigint         NOT NULL,
    loading_date        date           NOT NULL,
    loading_city_gcid   integer        NOT NULL,
    unloading_city_gcid integer        NOT NULL,
    body_group          text           NOT NULL,
    actual_price_rub    numeric(14, 2),
    predicted_price_rub numeric(14, 2) NOT NULL,
    abs_error_rub       numeric(14, 2),
    ape_pct             numeric(10, 4),
    model_name          text           NOT NULL,
    scored_at           timestamptz    NOT NULL DEFAULT now(),
    PRIMARY KEY (price_id, model_name),
    CONSTRAINT ml_price_predictions_error_chk CHECK (
        (actual_price_rub IS NULL) = (abs_error_rub IS NULL) AND (actual_price_rub IS NULL) = (ape_pct IS NULL))
);
CREATE INDEX IF NOT EXISTS ml_price_predictions_model_date_idx
    ON mart.ml_price_predictions (model_name, loading_date);
