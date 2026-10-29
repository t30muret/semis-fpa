-- v_variance: gross-profit bridges with calendar labels, ready for the dashboard waterfall.
-- One row per forecast; gp_volume + gp_mix + gp_rate = gp_variance.

SET search_path TO fpa;

CREATE OR REPLACE VIEW v_variance AS
SELECT
    b.source,
    b.ticker,
    c.name AS company,
    b.horizon,
    b.origin_period_end,
    b.target_period_end,
    cal.fiscal_year,
    cal.fiscal_quarter,
    cal.calendar_quarter,
    b.event_window,
    b.revenue_forecast,
    b.revenue_actual,
    b.revenue_variance,
    ROUND(100 * b.revenue_variance / NULLIF(b.revenue_forecast, 0), 2) AS revenue_variance_pct,
    b.gm_forecast_pct,
    b.gm_actual_pct,
    b.gp_forecast,
    b.gp_actual,
    b.gp_variance,
    b.gp_volume,
    b.gp_mix,
    b.gp_rate,
    b.has_segments,
    b.has_segment_margins
FROM variance_bridge b
JOIN companies c USING (ticker)
JOIN fiscal_calendar cal ON cal.ticker = b.ticker AND cal.period_end = b.target_period_end;

-- v_variance_long: the same bridge stacked one step per row, the shape Power BI's waterfall
-- chart wants. Steps: Forecast GP, Volume, Mix, Rate; the waterfall's total bar = actual GP.
CREATE OR REPLACE VIEW v_variance_long AS
SELECT source, ticker, company, horizon, target_period_end, calendar_quarter, step_order, step, amount
FROM v_variance
CROSS JOIN LATERAL (VALUES
    (0, 'Forecast GP', gp_forecast),
    (1, 'Volume', gp_volume),
    (2, 'Mix',    gp_mix),
    (3, 'Rate',   gp_rate)
) AS s(step_order, step, amount);
