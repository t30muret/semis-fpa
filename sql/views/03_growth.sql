-- v_growth: quarter-over-quarter and year-over-year revenue growth.
-- LAG(x, n) reads the value n rows earlier within the same company, ordered by date.

SET search_path TO fpa;

CREATE OR REPLACE VIEW v_growth AS
SELECT
    ticker,
    period_end,
    calendar_quarter,
    revenue,
    ROUND(100 * (revenue / NULLIF(LAG(revenue, 1) OVER w, 0) - 1), 2) AS revenue_qoq_pct,
    ROUND(100 * (revenue / NULLIF(LAG(revenue, 4) OVER w, 0) - 1), 2) AS revenue_yoy_pct
FROM v_income_q
WINDOW w AS (PARTITION BY ticker ORDER BY period_end);
