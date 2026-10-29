"""Freeze live forecasts for the next 4 quarters into a dated CSV you commit to GitHub.

Run:  python src/freeze.py                 (all companies)
      python src/freeze.py --exclude ANET  (skip a company that has already announced)

Rules this script enforces:
  * never overwrites an existing freeze file (a frozen forecast is never edited)
  * prints, per company, the quarter being forecast so you can confirm on the
    investor-relations page that it has NOT been announced yet
  * writes every model, not only the chosen one, so baselines are scored too

80% bands come from the backtest: the 10th and 90th percentiles of each model's
past errors at that horizon for that company (pooled across companies when a
company has fewer than 12 past errors).
"""
import argparse
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from common import company_series, fiscal_label_ahead, load_long, trailing_run
from build_quarters import calendar_quarter
from config import COMPANIES, FROZEN_DIR, HORIZONS, INTERVAL_QUANTILES, PROCESSED_DIR
from forecast import MODELS

LO, HI = INTERVAL_QUANTILES


def error_quantiles(bt: pd.DataFrame) -> dict:
    """(ticker, model, horizon) -> (q_lo, q_hi) of actual-vs-forecast errors."""
    clean = bt[~bt.event_window].copy()
    rev = clean.metric == "revenue"
    clean["e"] = np.where(rev, clean.log_ratio, clean.actual - clean.forecast)
    out = {}
    pooled = clean.groupby(["model", "horizon"])["e"]
    pooled_q = {k: (g.quantile(LO), g.quantile(HI)) for k, g in pooled}
    for (tk, model, h), g in clean.groupby(["ticker", "model", "horizon"])["e"]:
        out[(tk, model, h)] = (g.quantile(LO), g.quantile(HI)) if len(g) >= 12 else pooled_q[(model, h)]
    for (model, h), q in pooled_q.items():
        out.setdefault(("*", model, h), q)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", nargs="*", default=[], help="tickers that already announced")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    path = FROZEN_DIR / f"freeze_{now.date().isoformat()}.csv"
    if path.exists():
        raise SystemExit(f"{path.name} already exists. Frozen forecasts are never overwritten.")

    long = load_long()
    bt = pd.read_csv(PROCESSED_DIR / "backtest_forecasts.csv")
    choice = pd.read_csv(PROCESSED_DIR / "model_choice.csv")
    chosen = {(r.ticker, r.metric): r.chosen_model for r in choice.itertuples()}
    q = error_quantiles(bt)

    rows = []
    print("Confirm each 'next quarter' below has NOT been announced yet:\n")
    for co in COMPANIES:
        tk = co["ticker"]
        if tk in [x.upper() for x in args.exclude]:
            print(f"  {tk:5} skipped (--exclude)")
            continue
        s = company_series(long, tk)
        if len(s) < 16:
            print(f"  {tk:5} !! only {len(s)} clean quarters; skipped")
            continue
        last_end = s.index[-1]
        last_fy, last_fq = int(s["fiscal_year"].iloc[-1]), int(s["fiscal_quarter"].iloc[-1])
        target_end_1 = last_end + timedelta(days=91)
        note = "quarter has ended" if target_end_1.date() < now.date() else "quarter still in progress"
        print(f"  {tk:5} last reported {last_end.date()} ({fiscal_label_ahead(last_fy, last_fq, 0)}); "
              f"next = {fiscal_label_ahead(last_fy, last_fq, 1)}, ends ~{target_end_1.date()} ({note})")

        hist = {"revenue": s["rev_latest"].values, "gross_margin_pct": s["gm_latest"].values}
        for metric, models in MODELS.items():
            series = trailing_run(hist[metric])
            if len(series) < 16:
                continue
            for name, fn in models.items():
                fc = fn(series, HORIZONS)
                for h, f in zip(HORIZONS, fc):
                    lo_e, hi_e = q.get((tk, name, h), q.get(("*", name, h), (np.nan, np.nan)))
                    if metric == "revenue":
                        lo, hi = f * np.exp(lo_e), f * np.exp(hi_e)
                    else:
                        lo, hi = f + lo_e, f + hi_e
                    target_end = last_end + timedelta(days=91 * h)
                    nd = 0 if metric == "revenue" else 2
                    rows.append({
                        "freeze_timestamp_utc": now.isoformat(timespec="seconds"),
                        "ticker": tk, "metric": metric, "model": name,
                        "is_chosen": chosen.get((tk, metric)) == name,
                        "horizon": h,
                        "target_fiscal_label": fiscal_label_ahead(last_fy, last_fq, h),
                        "target_period_end_est": target_end.date(),
                        "target_calendar_quarter": calendar_quarter(target_end.date()),
                        "point": round(float(f), nd), "low80": round(float(lo), nd), "high80": round(float(hi), nd),
                        "guidance_mid": "",
                        "last_actual_period_end": last_end.date(),
                    })

    out = pd.DataFrame(rows)
    out.to_csv(path, index=False)
    print(f"\nWrote {len(out)} forecasts to forecasts/frozen/{path.name}")
    print("\nNext steps:")
    print("  1. Optional: fill guidance_mid for horizon 1 from each company's latest earnings release")
    print("     Revenue in dollars. Gross margin in percent, GAAP only to match EDGAR;")
    print("     many companies guide only non-GAAP margin, so leave it blank for those.")
    print("  2. Commit and push NOW. The commit timestamp is your proof:")
    print(f'       git add forecasts/frozen/{path.name}')
    print(f'       git commit -m "Freeze live forecasts {now.date()}"')
    print("       git push")


if __name__ == "__main__":
    main()
