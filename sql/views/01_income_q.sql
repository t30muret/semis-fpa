-- v_income_q: one row per company x quarter, every metric as its own column.
-- Worked example: pivots the long table with conditional aggregation.
-- Uses value_latest (restated figures) because this view is for analysis, not scoring.

SET search_path TO fpa;

CREATE OR REPLACE VIEW v_income_q AS
WITH wide AS (
    SELECT
        f.ticker,
        f.period_end,
        MAX(CASE WHEN f.metric = 'revenue'          THEN f.value_latest END) AS revenue,
        MAX(CASE WHEN f.metric = 'cost_of_revenue'  THEN f.value_latest END) AS cost_of_revenue,
        MAX(CASE WHEN f.metric = 'gross_profit'     THEN f.value_latest END) AS gross_profit,
        MAX(CASE WHEN f.metric = 'rnd'              THEN f.value_latest END) AS rnd,
        MAX(CASE WHEN f.metric = 'sga'              THEN f.value_latest END) AS sga_reported,
        MAX(CASE WHEN f.metric = 'sales_marketing'  THEN f.value_latest END) AS sales_marketing,
        MAX(CASE WHEN f.metric = 'g_and_a'          THEN f.value_latest END) AS g_and_a,
        MAX(CASE WHEN f.metric = 'operating_income' THEN f.value_latest END) AS operating_income
    FROM financials_q f
    GROUP BY f.ticker, f.period_end
)
SELECT
    c.ticker,
    c.period_end,
    c.fiscal_year,
    c.fiscal_quarter,
    c.calendar_quarter,
    w.revenue,
    w.cost_of_revenue,
    w.gross_profit,
    w.rnd,
    -- Cisco, Arista and Ciena split SG&A into two lines; add them back together
    COALESCE(w.sga_reported, w.sales_marketing + w.g_and_a) AS sga,
    w.operating_income
FROM fiscal_calendar c
JOIN wide w USING (ticker, period_end)
WHERE w.revenue IS NOT NULL;
