-- v_margins: each line of the income statement as a % of revenue.
-- NULLIF(revenue, 0) returns NULL instead of dividing by zero.

SET search_path TO fpa;

CREATE OR REPLACE VIEW v_margins AS
SELECT
    ticker,
    period_end,
    calendar_quarter,
    ROUND(100 * gross_profit     / NULLIF(revenue, 0), 2) AS gross_margin_pct,
    ROUND(100 * rnd              / NULLIF(revenue, 0), 2) AS rnd_pct,
    ROUND(100 * sga              / NULLIF(revenue, 0), 2) AS sga_pct,
    ROUND(100 * operating_income / NULLIF(revenue, 0), 2) AS operating_margin_pct
FROM v_income_q;
