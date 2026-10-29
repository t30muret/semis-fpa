"""Score every frozen forecast that now has a reported actual.

Run after each company files its 10-Q/10-K (refresh the data first):
  python src/ingest_edgar.py
  python src/build_quarters.py
  python src/score_live.py

Actuals are first-reported values. A frozen forecast matches the reported quarter
whose period end is within 12 days of its estimated target date.
Output: data/processed/live_scorecard.csv
"""
import numpy as np
import pandas as pd

from common import company_series, load_long
from config import COMPANIES, FROZEN_DIR, PROCESSED_DIR


def main() -> None:
    files = sorted(FROZEN_DIR.glob("freeze_*.csv"))
    if not files:
        print("No frozen forecasts yet.")
        return
    frozen = pd.concat([pd.read_csv(f, parse_dates=["target_period_end_est"]) for f in files])
    long = load_long()

    rows = []
    for co in COMPANIES:
        tk = co["ticker"]
        s = company_series(long, tk)
        for r in frozen[frozen.ticker == tk].itertuples():
            gaps = abs((s.index - r.target_period_end_est).days)
            if len(gaps) == 0 or gaps.min() > 12:
                continue
            q = s.iloc[int(np.argmin(gaps))]
            actual = q["rev_first"] if r.metric == "revenue" else q["gm_first"]
            if pd.isna(actual):
                continue
            err = r.point / actual - 1 if r.metric == "revenue" else r.point - actual
            rows.append({**r._asdict(), "actual_period_end": q.name.date(), "actual": actual,
                         "error": err, "inside_80_band": r.low80 <= actual <= r.high80})
    out = pd.DataFrame(rows).drop(columns=["Index"], errors="ignore")
    out.to_csv(PROCESSED_DIR / "live_scorecard.csv", index=False)
    if out.empty:
        print("No frozen forecasts have actuals yet.")
        return
    show = out[out.horizon == 1][["ticker", "metric", "model", "is_chosen", "point", "actual", "error", "inside_80_band"]]
    print(show.to_string(index=False))
    print(f"\n{len(out)} live forecasts scored; written to data/processed/live_scorecard.csv")


if __name__ == "__main__":
    main()
