-- v_peer_rank: each company ranked against peers in the same CALENDAR quarter.
-- Partitioning by calendar_quarter (not fiscal) lines up companies whose fiscal years
-- end in different months.

SET search_path TO fpa;

CREATE OR REPLACE VIEW v_peer_rank AS
SELECT
    m.calendar_quarter,
    m.ticker,
    m.gross_margin_pct,
    m.operating_margin_pct,
    g.revenue_yoy_pct,
    RANK() OVER (PARTITION BY m.calendar_quarter ORDER BY m.gross_margin_pct DESC)          AS margin_rank,
    RANK() OVER (PARTITION BY m.calendar_quarter ORDER BY g.revenue_yoy_pct DESC NULLS LAST) AS growth_rank,
    COUNT(*) OVER (PARTITION BY m.calendar_quarter)                                         AS peers_reporting
FROM v_margins m
JOIN v_growth g USING (ticker, period_end);
