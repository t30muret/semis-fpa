-- v_accuracy: forecast accuracy by source, company, metric, model and horizon.
-- FILTER (WHERE NOT event_window) leaves out quarters right after big acquisitions.
-- mape_or_mae: revenue = mean absolute % error (0.073 = 7.3%); margin = mean absolute error in points.
-- bias: average signed error; negative = forecasts too low.

SET search_path TO fpa;

CREATE OR REPLACE VIEW v_accuracy AS
SELECT
    source,
    ticker,
    metric,
    model,
    BOOL_OR(is_chosen)                                    AS is_chosen,
    horizon,
    COUNT(*)              FILTER (WHERE NOT event_window) AS n,
    AVG(abs_error)        FILTER (WHERE NOT event_window) AS mape_or_mae,
    AVG(error)            FILTER (WHERE NOT event_window) AS bias,
    AVG(inside_band::int) FILTER (WHERE NOT event_window) AS band_coverage
FROM v_forecast_scores
GROUP BY source, ticker, metric, model, horizon;
