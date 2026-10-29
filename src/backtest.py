"""Rolling-origin backtest: forecast from every past quarter and score against what was reported.

Run:  python src/backtest.py

At each origin the models see only first-reported values for quarters up to that
point, so nothing restated later leaks into the forecast. Actuals are also the
first-reported values, which is what the live forecasts will be scored against.

Outputs (data/processed/):
  backtest_forecasts.csv  every forecast with its actual and error
  backtest_summary.csv    accuracy by company x metric x model x horizon
  model_choice.csv        model each company uses for the live freeze
"""
import warnings

import numpy as np
import pandas as pd

from common import company_series, in_event_window, load_long, trailing_run
from config import BACKTEST_FIRST_ORIGIN, COMPANIES, HORIZONS, MIN_TRAIN_QUARTERS, PROCESSED_DIR
from forecast import BASELINE, MODELS

warnings.filterwarnings("ignore", category=RuntimeWarning)


def run() -> pd.DataFrame:
    long = load_long()
    rows = []
    first_origin = pd.Timestamp(BACKTEST_FIRST_ORIGIN)
    for co in COMPANIES:
        tk = co["ticker"]
        s = company_series(long, tk)
        n = len(s)
        ends = list(s.index)
        for k in range(MIN_TRAIN_QUARTERS - 1, n - 1):
            if ends[k] < first_origin:
                continue
            series = {"revenue": s["rev_first"].values[:k + 1],
                      "gross_margin_pct": s["gm_first"].values[:k + 1]}
            actual = {"revenue": s["rev_first"].values, "gross_margin_pct": s["gm_first"].values}
            for metric, models in MODELS.items():
                hist = trailing_run(series[metric])
                if len(hist) < MIN_TRAIN_QUARTERS:
                    continue
                for name, fn in models.items():
                    try:
                        fc = fn(hist, HORIZONS)
                    except Exception as exc:  # keep going; report at the end
                        print(f"  !! {tk} {name} at {ends[k].date()}: {exc}")
                        continue
                    for h, f in zip(HORIZONS, fc):
                        if k + h >= n:
                            continue
                        a = actual[metric][k + h]
                        if np.isnan(a):
                            continue
                        rows.append({
                            "ticker": tk, "metric": metric, "model": name,
                            "is_baseline": name == BASELINE[metric],
                            "origin_period_end": ends[k].date(),
                            "origin_date": s["filed_first"].iloc[k].date(),
                            "horizon": h, "target_period_end": ends[k + h].date(),
                            "target_calendar_quarter": s["calendar_quarter"].iloc[k + h],
                            "forecast": f, "actual": a,
                            "event_window": in_event_window(tk, ends[k + h]),
                        })
    bt = pd.DataFrame(rows)
    rev = bt.metric == "revenue"
    bt["error"] = np.where(rev, bt.forecast / bt.actual - 1, bt.forecast - bt.actual)  # % or pp
    bt["log_ratio"] = np.where(rev, np.log(bt.actual / bt.forecast), np.nan)
    bt["abs_error"] = bt["error"].abs()
    return bt


def summarize(bt: pd.DataFrame) -> pd.DataFrame:
    clean = bt[~bt.event_window]
    g = clean.groupby(["ticker", "metric", "model", "horizon"])
    summ = g.agg(n=("error", "size"), mean_abs_error=("abs_error", "mean"),
                 bias=("error", "mean")).reset_index()
    base = summ[summ.model.isin(BASELINE.values())][["ticker", "metric", "horizon", "mean_abs_error"]]
    summ = summ.merge(base.rename(columns={"mean_abs_error": "baseline_mae"}),
                      on=["ticker", "metric", "horizon"], how="left")
    summ["relative_to_baseline"] = summ["mean_abs_error"] / summ["baseline_mae"]  # MASE-style; <1 beats naive
    return summ


def choose_models(summ: pd.DataFrame) -> pd.DataFrame:
    """Lowest average error across horizons 1-4; ties and near-ties go to the baseline."""
    avg = summ.groupby(["ticker", "metric", "model"])["mean_abs_error"].mean().reset_index()
    picks = []
    for (tk, metric), g in avg.groupby(["ticker", "metric"]):
        base_name = BASELINE[metric]
        base_err = g.loc[g.model == base_name, "mean_abs_error"].iloc[0]
        best = g.sort_values("mean_abs_error").iloc[0]
        chosen = best.model if best.mean_abs_error < 0.97 * base_err else base_name
        picks.append({"ticker": tk, "metric": metric, "chosen_model": chosen,
                      "chosen_error": g.loc[g.model == chosen, "mean_abs_error"].iloc[0],
                      "baseline_error": base_err})
    return pd.DataFrame(picks)


def main() -> None:
    bt = run()
    if bt.empty:
        print("No backtest rows: check data/processed/quarters_long.csv")
        return
    summ = summarize(bt)
    choice = choose_models(summ)
    bt.to_csv(PROCESSED_DIR / "backtest_forecasts.csv", index=False)
    summ.to_csv(PROCESSED_DIR / "backtest_summary.csv", index=False)
    choice.to_csv(PROCESSED_DIR / "model_choice.csv", index=False)

    clean = bt[~bt.event_window]
    print(f"Scored {len(bt):,} forecasts ({len(clean):,} outside acquisition windows)\n")
    pooled = clean.groupby(["metric", "model", "horizon"])["abs_error"].mean().unstack("horizon")
    rev = pooled.loc["revenue"] * 100
    gm = pooled.loc["gross_margin_pct"]
    print("Revenue MAPE (%) by horizon, all companies pooled")
    print(rev.round(1).to_string(), "\n")
    print("Gross margin mean absolute error (percentage points) by horizon")
    print(gm.round(2).to_string(), "\n")
    print("Model chosen for the live freeze (average error, h=1..4)")
    show = choice.copy()
    is_rev = show.metric == "revenue"
    for c in ("chosen_error", "baseline_error"):
        show[c] = np.where(is_rev, (show[c] * 100).round(1).astype(str) + "%",
                           show[c].round(2).astype(str) + " pp")
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
