-- v_forecast_scores: every forecast (backtest and live) matched to its actual result.
--
-- Actuals use value_FIRST, the figure as originally reported. A forecaster is judged
-- against what the company announced at the time; restatements filed later were not
-- known yet, and using them would make the scores look better or worse than reality.
--
-- Live forecasts store an ESTIMATED quarter end, so the join picks the reported quarter
-- whose end date is closest, within 12 days (JOIN LATERAL ... ORDER BY ... LIMIT 1).

SET search_path TO fpa;

CREATE OR REPLACE VIEW v_forecast_scores AS
WITH actuals AS (
    SELECT
        ticker,
        period_end,
        MAX(CASE WHEN metric = 'revenue' THEN value_first END) AS revenue,
        100 * MAX(CASE WHEN metric = 'gross_profit' THEN value_first END)
            / NULLIF(MAX(CASE WHEN metric = 'revenue' THEN value_first END), 0) AS gross_margin_pct
    FROM financials_q
    GROUP BY ticker, period_end
),
matched AS (
    SELECT
        f.*,
        a.period_end AS actual_period_end,
        CASE WHEN f.metric = 'revenue' THEN a.revenue ELSE a.gross_margin_pct END AS actual
    FROM forecasts f
    JOIN LATERAL (
        SELECT *
        FROM actuals a
        WHERE a.ticker = f.ticker
          AND ABS(a.period_end - f.target_period_end) <= 12
        ORDER BY ABS(a.period_end - f.target_period_end)
        LIMIT 1
    ) a ON TRUE
)
SELECT
    m.*,
    -- revenue error in % of actual; margin error in percentage points
    CASE WHEN metric = 'revenue' THEN point / actual - 1 ELSE point - actual END      AS error,
    ABS(CASE WHEN metric = 'revenue' THEN point / actual - 1 ELSE point - actual END) AS abs_error,
    CASE WHEN low80 IS NULL THEN NULL ELSE actual BETWEEN low80 AND high80 END         AS inside_band
FROM matched m
WHERE actual IS NOT NULL;
