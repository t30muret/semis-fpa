-- Semiconductor FP&A database schema (PostgreSQL 16)
-- Rebuilt from scratch by src/load_postgres.py every run: everything here can be
-- regenerated from EDGAR plus the committed frozen-forecast files.

DROP SCHEMA IF EXISTS fpa CASCADE;
CREATE SCHEMA fpa;
SET search_path TO fpa;

-- One row per company
CREATE TABLE companies (
    ticker        TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    current_cik   INTEGER NOT NULL
);

-- One row per company x fiscal quarter. Peer comparisons join on calendar_quarter,
-- because fiscal years end in different months (Cisco July, Broadcom October, ...).
CREATE TABLE fiscal_calendar (
    ticker            TEXT    NOT NULL REFERENCES companies,
    period_end        DATE    NOT NULL,
    period_start      DATE    NOT NULL,
    fiscal_year       INTEGER NOT NULL,
    fiscal_quarter    INTEGER NOT NULL CHECK (fiscal_quarter BETWEEN 1 AND 4),
    calendar_quarter  TEXT    NOT NULL,          -- e.g. '2026Q2'
    PRIMARY KEY (ticker, period_end)
);

-- Long format: one row per company x quarter x metric.
-- value_first  = as first reported (what was known at the time; used for scoring)
-- value_latest = after any later restatement (used for analysis)
CREATE TABLE financials_q (
    ticker        TEXT    NOT NULL,
    period_end    DATE    NOT NULL,
    metric        TEXT    NOT NULL,
    value_first   NUMERIC NOT NULL,
    first_filed   DATE    NOT NULL,
    value_latest  NUMERIC NOT NULL,
    latest_filed  DATE    NOT NULL,
    source_tag    TEXT    NOT NULL,              -- XBRL tag, or 'derived'
    method        TEXT    NOT NULL,              -- 'reported' or how it was derived
    PRIMARY KEY (ticker, period_end, metric),
    FOREIGN KEY (ticker, period_end) REFERENCES fiscal_calendar
);

-- Backtest and live forecasts in one table, so they are scored the same way.
CREATE TABLE forecasts (
    forecast_id         SERIAL PRIMARY KEY,
    source              TEXT    NOT NULL CHECK (source IN ('backtest', 'live')),
    forecast_date       DATE    NOT NULL,        -- data cut-off (backtest) or freeze date (live)
    ticker              TEXT    NOT NULL REFERENCES companies,
    metric              TEXT    NOT NULL,        -- 'revenue' or 'gross_margin_pct'
    model               TEXT    NOT NULL,
    is_chosen           BOOLEAN NOT NULL,
    horizon             INTEGER NOT NULL CHECK (horizon BETWEEN 1 AND 4),
    origin_period_end   DATE    NOT NULL,        -- last quarter the model saw
    target_period_end   DATE    NOT NULL,        -- live: estimated; match within 12 days
    point               NUMERIC NOT NULL,
    low80               NUMERIC,
    high80              NUMERIC,
    event_window        BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX ON forecasts (ticker, metric, target_period_end);

CREATE TABLE events (
    ticker       TEXT NOT NULL REFERENCES companies,
    event_date   DATE NOT NULL,
    description  TEXT NOT NULL
);

-- Filled by hand from earnings releases and 10-Q segment notes (weekend 2-3)
CREATE TABLE segments_q (
    ticker              TEXT    NOT NULL REFERENCES companies,
    period_end          DATE    NOT NULL,
    segment             TEXT    NOT NULL,
    revenue             NUMERIC NOT NULL,
    operating_profit    NUMERIC,
    source_note         TEXT,
    PRIMARY KEY (ticker, period_end, segment)
);

CREATE TABLE guidance (
    ticker            TEXT    NOT NULL REFERENCES companies,
    period_end        DATE    NOT NULL,          -- quarter being guided
    issued_date       DATE    NOT NULL,
    revenue_low       NUMERIC,
    revenue_high      NUMERIC,
    gm_low_pct        NUMERIC,                   -- GAAP only, to match EDGAR
    gm_high_pct       NUMERIC,
    PRIMARY KEY (ticker, period_end)
);
