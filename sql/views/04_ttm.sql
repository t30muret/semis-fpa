-- v_ttm: trailing-twelve-month totals (current quarter + 3 before it).
-- The window count is filtered in an outer query because WHERE runs before window functions.

SET search_path TO fpa;

CREATE OR REPLACE VIEW v_ttm AS
WITH t AS (
    SELECT
        ticker,
        period_end,
        calendar_quarter,
        SUM(revenue)          OVER w AS revenue_ttm,
        SUM(gross_profit)     OVER w AS gross_profit_ttm,
        SUM(operating_income) OVER w AS operating_income_ttm,
        COUNT(*)              OVER w AS quarters_in_window
    FROM v_income_q
    WINDOW w AS (PARTITION BY ticker ORDER BY period_end
                 ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)
)
SELECT
    t.*,
    ROUND(100 * gross_profit_ttm / NULLIF(revenue_ttm, 0), 2) AS gross_margin_ttm_pct
FROM t
WHERE quarters_in_window = 4;
