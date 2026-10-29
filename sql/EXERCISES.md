# SQL views to write

`01_income_q.sql` is a worked example. Write the rest yourself. This is the SQL your resume
line claims, and interviewers will ask you to explain it. Save each as its own file in
`sql/views/` (the number sets the run order), then rerun `python src\load_postgres.py`.
Every file starts with `SET search_path TO fpa;` and uses `CREATE OR REPLACE VIEW`.

Test a query in pgAdmin's Query Tool first, then paste it into the file.

| File | View | Columns to produce | Skill | Check your answer |
| --- | --- | --- | --- | --- |
| `02_margins.sql` | `v_margins` | ticker, period_end, calendar_quarter, gross_margin_pct, rnd_pct, sga_pct, operating_margin_pct | arithmetic on a view, `NULLIF` to avoid divide-by-zero | Cisco FY26 Q4 gross margin ~64.1% |
| `03_growth.sql` | `v_growth` | ticker, period_end, revenue, revenue_qoq_pct, revenue_yoy_pct | `LAG() OVER (PARTITION BY ticker ORDER BY period_end)` | YoY uses `LAG(revenue, 4)` |
| `04_ttm.sql` | `v_ttm` | ticker, period_end, revenue_ttm, gross_profit_ttm, quarters_in_window | `SUM() OVER (... ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)` | keep only rows where quarters_in_window = 4 |
| `05_peer_rank.sql` | `v_peer_rank` | calendar_quarter, ticker, gross_margin_pct, revenue_yoy_pct, margin_rank, growth_rank, peers_reporting | `RANK() OVER (PARTITION BY calendar_quarter ...)` joining two views | ranks run 1 to 8 in recent quarters |
| `06_forecast_scores.sql` | `v_forecast_scores` | everything in `forecasts` plus actual, error, abs_error, inside_band | join forecasts to actuals on the nearest quarter end (within 12 days); revenue error in %, margin error in points | the 2026Q1 Cisco backtest rows match `backtest_forecasts.csv` |
| `07_accuracy.sql` | `v_accuracy` | source, ticker, metric, model, horizon, n, mape_or_mae, bias, band_coverage | `GROUP BY` with `FILTER (WHERE NOT event_window)` | pooled ets_rev h=1 MAPE ~7.3% |

**Two harder ones (bonus, good interview stories):**

- **Coherent operating income.** EDGAR stops tagging Coherent's `OperatingIncomeLoss` after mid-2024.
  Rebuild it as gross profit − R&D − SG&A − other operating expense and check your formula on the
  quarters where both exist (2022–2024). That's a reconciliation, the same habit as your VRP rebuild.
- **Actuals for scoring use `value_first`**, not `value_latest`. In `06_forecast_scores.sql`,
  explain in a comment why.

When you get stuck, paste your query and the error into chat. Ask for a hint first, then for
the answer, so you can still explain every line.
