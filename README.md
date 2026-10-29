# Semiconductor FP&A Forecast & Variance Dashboard

Quarterly financials for 8 optical, networking and semiconductor companies (Coherent, Lumentum,
Arista, Fabrinet, Cisco, Marvell, Broadcom, Ciena) pulled from SEC EDGAR; revenue and gross-margin
forecasts scored out of sample, in a rolling backtest and in live forecasts frozen in git before
each earnings release.

**Status:** week 1 of 6. Data pipeline, forecast models, backtest and live freeze are in place.
PostgreSQL, segment data, variance bridges, Power BI and the memo come next.

## Run it (Windows, PowerShell)

One-time setup, from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
$env:SEC_USER_AGENT = "Your Name your.email@example.com"   # SEC requires this; set it each new window
```

Then, in order:

```powershell
python src\ingest_edgar.py      # download EDGAR data; check every row says "ok"
python src\build_quarters.py    # clean discrete quarters -> data\processed\
python src\backtest.py          # rolling backtest, picks a model per company
python src\freeze.py            # freezes the next 4 quarters -> forecasts\frozen\
```

After freezing, commit and push right away. The commit timestamp proves the forecast came first.

After each company files its 10-Q or 10-K, rerun `ingest_edgar.py`, `build_quarters.py`, then
`python src\score_live.py`.

Load everything into PostgreSQL (database `semis_fpa`, schema `fpa`) and build the SQL views:

```
set "PGPASSWORD=your postgres password"
python src\load_postgres.py
```

The SQL views live in `sql/views/`; see `sql/EXERCISES.md`.

## Method

**Clean quarters.** EDGAR's companyfacts API mixes 3-month, year-to-date and full-year values, and
restates past periods in later filings. `build_quarters.py` keeps true 3-month figures, derives the
rest (Q4 = full year − first nine months), and stores two values per quarter: the **first-reported**
figure (what was known at the time) and the **latest** figure.

**No look-ahead.** The backtest trains only on first-reported values available at each forecast
origin and scores against first-reported actuals, the same standard the live forecasts face.

**Models.**

| Metric | Baseline | Model |
| --- | --- | --- |
| Revenue | Seasonal naive: same quarter last year × (1 + trailing 4-quarter growth) | Holt-Winters on log revenue, damped trend + quarterly seasonality |
| Gross margin | Last quarter's margin | Holt-Winters on margin, quarterly seasonality |

Holt-Winters is implemented directly in `src/forecast.py` so every equation is visible. A model
replaces the baseline for a company only if it cuts average backtest error by at least 3%.

**80% bands** come from each model's own past errors at that horizon, so they can be checked:
about 80% of actuals should land inside.

**Acquisitions** (Broadcom–VMware, Marvell–Inphi and others, listed in `src/config.py`) are flagged,
and accuracy is reported outside those windows.

## Results

_Filled in after the backtest and the live scoring window (mid-December 2026)._

## Repo layout

```
src/config.py          companies, CIKs, XBRL tags, acquisition dates
src/ingest_edgar.py    download companyfacts JSON
src/build_quarters.py  discrete quarters, first-reported and latest values
src/forecast.py        models
src/backtest.py        rolling-origin backtest, model choice
src/freeze.py          writes a dated, never-overwritten forecast file
src/score_live.py      scores frozen forecasts once actuals are filed
tests/make_synthetic.py  fake EDGAR data with every known trap, for offline testing
forecasts/frozen/      committed forecast files
```
