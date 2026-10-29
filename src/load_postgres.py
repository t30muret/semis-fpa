"""Load the processed data and every frozen forecast into PostgreSQL, then build the views.

Run:  python src\\load_postgres.py

Connection: set your postgres password once per terminal (cmd):
    set "PGPASSWORD=the password you chose when installing PostgreSQL"
Defaults: user postgres, host localhost, port 5432, database semis_fpa (created if missing).
Override any of them with DATABASE_URL, e.g.
    set "DATABASE_URL=postgresql://postgres@localhost:5432/semis_fpa"

The fpa schema is dropped and rebuilt each run, so rerun this after every data refresh.
Then every file in sql/views/ runs in name order (01_..., 02_..., ...).
"""
import io
import os
import sys
from datetime import date
from urllib.parse import urlparse

import pandas as pd

from config import COMPANIES, EVENTS, FROZEN_DIR, PROCESSED_DIR, ROOT

DEFAULT_URL = "postgresql://postgres@localhost:5432/semis_fpa"


# ---------------------------------------------------------------- build tables (no database needed)
def build_tables() -> dict[str, pd.DataFrame]:
    long = pd.read_csv(PROCESSED_DIR / "quarters_long.csv")

    companies = pd.DataFrame([{"ticker": c["ticker"], "name": c["name"], "current_cik": c["ciks"][0]}
                              for c in COMPANIES])

    cal = (long.sort_values("metric")
               .drop_duplicates(["ticker", "period_end"])
               [["ticker", "period_end", "period_start", "fiscal_year", "fiscal_quarter", "calendar_quarter"]]
               .sort_values(["ticker", "period_end"]))

    fin = long[["ticker", "period_end", "metric", "value_first", "first_filed",
                "value_latest", "latest_filed", "source_tag", "method"]]

    fc_cols = ["source", "forecast_date", "ticker", "metric", "model", "is_chosen", "horizon",
               "origin_period_end", "target_period_end", "point", "low80", "high80", "event_window"]
    bt = pd.read_csv(PROCESSED_DIR / "backtest_forecasts.csv")
    choice = pd.read_csv(PROCESSED_DIR / "model_choice.csv")
    chosen = set(zip(choice.ticker, choice.metric, choice.chosen_model))
    bt = bt.assign(source="backtest", forecast_date=bt.origin_date,
                   is_chosen=[(t, m, n) in chosen for t, m, n in zip(bt.ticker, bt.metric, bt.model)],
                   point=bt.forecast, low80=None, high80=None)
    frames = [bt[fc_cols]]
    for f in sorted(FROZEN_DIR.glob("freeze_*.csv")):
        lv = pd.read_csv(f)
        lv = lv.assign(source="live", forecast_date=lv.freeze_timestamp_utc.str[:10],
                       origin_period_end=lv.last_actual_period_end,
                       target_period_end=lv.target_period_end_est, event_window=False)
        frames.append(lv[fc_cols])
    forecasts = pd.concat(frames, ignore_index=True)

    events = pd.DataFrame(EVENTS, columns=["ticker", "event_date", "description"])
    return {"companies": companies, "fiscal_calendar": cal, "financials_q": fin,
            "forecasts": forecasts, "events": events}


def to_csv_text(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="")
    return buf.getvalue()


# ---------------------------------------------------------------- database
def connect(url: str, dbname: str | None = None):
    import psycopg
    if dbname:
        url = url.rsplit("/", 1)[0] + "/" + dbname
    return psycopg.connect(url, autocommit=True)


def ensure_database(url: str) -> None:
    from psycopg import sql
    target = urlparse(url).path.lstrip("/")
    with connect(url, "postgres") as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
            print(f"Created database {target}")


def main() -> int:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        print('psycopg is not installed. Run:  pip install "psycopg[binary]"')
        return 1

    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    tables = build_tables()
    try:
        ensure_database(url)
        conn = connect(url)
    except Exception as exc:
        print(f"Could not connect to PostgreSQL: {exc}\n"
              "Check that PostgreSQL is running and that PGPASSWORD is set in this terminal:\n"
              '  set "PGPASSWORD=your postgres password"')
        return 1

    with conn:
        conn.execute((ROOT / "sql" / "schema.sql").read_text())
        conn.execute("SET search_path TO fpa")
        for name, df in tables.items():
            cols = ", ".join(df.columns)
            with conn.cursor().copy(f"COPY {name} ({cols}) FROM STDIN WITH (FORMAT csv)") as cp:
                cp.write(to_csv_text(df))
            print(f"  {name:16} {len(df):>7,} rows")

        views = sorted((ROOT / "sql" / "views").glob("*.sql"))
        for v in views:
            try:
                conn.execute(v.read_text())
                print(f"  view file {v.name} ok")
            except Exception as exc:
                print(f"  !! view file {v.name} failed:\n     {str(exc).strip()}")
    print(f"\nLoaded {date.today()}. Connect in pgAdmin to database '{urlparse(url).path.lstrip('/')}', schema fpa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
