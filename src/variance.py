"""Explain every forecast miss: volume, mix and rate.

Run:  python src\\variance.py      (after backtest.py, build_segments.py, and any freeze)

For each forecast from the CHOSEN models (backtest and live), with R = revenue,
GP = gross profit, gm = gross margin, s_i = segment share of revenue, m_i = segment gross margin:

  Forecast GP = R_f * gm_f
  Forecast segment mix s_f,i  = segment shares over the 4 quarters up to the forecast origin
  Forecast segment margins m_f,i = segment gross margins over the same 4 quarters

  Gross profit bridge (sums exactly to GP_actual - GP_forecast):
    volume = (R_a - R_f) * gm_f                       revenue came in higher/lower
    mix    = R_a * sum_i (s_a,i - s_f,i) * m_f,i      revenue shifted to richer/poorer segments
    rate   = everything else                          margins within segments moved
  Mix needs segment gross margins (Cisco, Arista, Broadcom and Ciena in recent years).
  Without them, mix is 0 and the shift sits inside rate; the row says so.

  Revenue by segment (sums exactly to R_a - R_f):
    volume_i = (R_a - R_f) * s_f,i                    the segment's share of the total miss
    mix_i    = R_a * (s_a,i - s_f,i)                  the segment grew faster/slower than the rest

Actuals are first-reported values, the same standard as forecast scoring.
Outputs: data/processed/variance_bridge.csv, data/processed/variance_segments.csv
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from config import FROZEN_DIR, PROCESSED_DIR


def load_forecasts() -> pd.DataFrame:
    """Chosen-model revenue and margin forecasts side by side, backtest and live."""
    choice = pd.read_csv(PROCESSED_DIR / "model_choice.csv")
    chosen = set(zip(choice.ticker, choice.metric, choice.chosen_model))

    bt = pd.read_csv(PROCESSED_DIR / "backtest_forecasts.csv")
    bt = bt[[(t, m, n) in chosen for t, m, n in zip(bt.ticker, bt.metric, bt.model)]]
    bt = bt.assign(source="backtest", target=bt.target_period_end, origin=bt.origin_period_end,
                   point=bt.forecast)[["source", "ticker", "metric", "horizon", "origin", "target",
                                       "point", "event_window"]]
    frames = [bt]
    for f in sorted(FROZEN_DIR.glob("freeze_*.csv")):
        lv = pd.read_csv(f)
        lv = lv[lv.is_chosen]
        frames.append(lv.assign(source="live", origin=lv.last_actual_period_end,
                                target=lv.target_period_end_est, event_window=False)
                      [["source", "ticker", "metric", "horizon", "origin", "target", "point", "event_window"]])
    fc = pd.concat(frames, ignore_index=True)
    wide = fc.pivot_table(index=["source", "ticker", "horizon", "origin", "target", "event_window"],
                          columns="metric", values="point").reset_index()
    return wide.rename(columns={"revenue": "revenue_forecast", "gross_margin_pct": "gm_forecast_pct"}) \
               .dropna(subset=["revenue_forecast", "gm_forecast_pct"])


def nearest(d: date, keys, days: int = 12):
    best = min(keys, key=lambda k: abs((k - d).days), default=None)
    return best if best is not None and abs((best - d).days) <= days else None


def main() -> None:
    fc = load_forecasts()
    long = pd.read_csv(PROCESSED_DIR / "quarters_long.csv")
    act = long[long.metric.isin(["revenue", "gross_profit"])] \
        .pivot_table(index=["ticker", "period_end"], columns="metric", values="value_first")
    actuals = {(t, date.fromisoformat(e)): (r.revenue, r.gross_profit) for (t, e), r in act.iterrows()}
    ends_by_tk = {}
    for t, e in actuals:
        ends_by_tk.setdefault(t, []).append(e)

    seg = pd.read_csv(PROCESSED_DIR / "segments_q.csv")
    seg["period_end"] = seg.period_end.map(date.fromisoformat)
    seg_by_tk = {t: g for t, g in seg.groupby("ticker")}

    bridges, seg_rows = [], []
    for r in fc.itertuples():
        target = nearest(date.fromisoformat(str(r.target)), ends_by_tk.get(r.ticker, []))
        if target is None:
            continue  # not reported yet
        R_a, GP_a = actuals[(r.ticker, target)]
        if pd.isna(R_a) or pd.isna(GP_a):
            continue
        R_f, gm_f = r.revenue_forecast, r.gm_forecast_pct / 100
        GP_f = R_f * gm_f
        origin = date.fromisoformat(str(r.origin))

        # segment mix: trailing 4 quarters to the origin vs. the target quarter
        shares_f = shares_a = margins_f = None
        g = seg_by_tk.get(r.ticker)
        if g is not None:
            last4 = sorted(g.period_end[g.period_end <= origin + timedelta(days=6)].unique())[-4:]
            hist = g[g.period_end.isin(last4)]
            tgt = g[g.period_end == target]
            consecutive = len(last4) == 4 and (last4[-1] - last4[0]).days <= 290 \
                and abs((last4[-1] - origin).days) <= 6
            if consecutive and not tgt.empty:
                tot = hist.groupby("segment")[["revenue", "gross_profit"]].sum(min_count=4)
                shares_f = tot.revenue / tot.revenue.sum()
                shares_a = tgt.set_index("segment").revenue / tgt.revenue.sum()
                if tot.gross_profit.notna().all() and hist.gross_profit.notna().all():
                    margins_f = tot.gross_profit / tot.revenue

        volume = (R_a - R_f) * gm_f
        mix = float(R_a * ((shares_a - shares_f) * margins_f).sum()) if margins_f is not None else 0.0
        rate = (GP_a - GP_f) - volume - mix
        bridges.append({
            "source": r.source, "ticker": r.ticker, "horizon": r.horizon,
            "origin_period_end": r.origin, "target_period_end": target, "event_window": r.event_window,
            "revenue_forecast": R_f, "revenue_actual": R_a, "revenue_variance": R_a - R_f,
            "gm_forecast_pct": 100 * gm_f, "gm_actual_pct": 100 * GP_a / R_a,
            "gp_forecast": GP_f, "gp_actual": GP_a, "gp_variance": GP_a - GP_f,
            "gp_volume": volume, "gp_mix": mix, "gp_rate": rate,
            "has_segments": shares_f is not None, "has_segment_margins": margins_f is not None,
        })
        if shares_f is not None:
            for s in shares_f.index:
                seg_rows.append({
                    "source": r.source, "ticker": r.ticker, "horizon": r.horizon,
                    "origin_period_end": r.origin, "target_period_end": target, "segment": s,
                    "share_forecast": shares_f[s], "share_actual": shares_a.get(s, np.nan),
                    "revenue_forecast": R_f * shares_f[s], "revenue_actual": R_a * shares_a.get(s, np.nan),
                    "revenue_volume": (R_a - R_f) * shares_f[s],
                    "revenue_mix": R_a * (shares_a.get(s, np.nan) - shares_f[s]),
                })

    b = pd.DataFrame(bridges)
    sg = pd.DataFrame(seg_rows)
    check = (b.gp_volume + b.gp_mix + b.gp_rate - b.gp_variance).abs().max()
    b.to_csv(PROCESSED_DIR / "variance_bridge.csv", index=False)
    sg.to_csv(PROCESSED_DIR / "variance_segments.csv", index=False)

    print(f"{len(b):,} bridges ({b.has_segments.sum():,} with segment mix, "
          f"{b.has_segment_margins.sum():,} with segment margins); {len(sg):,} segment rows")
    print(f"Bridge check: volume + mix + rate = total variance (max gap ${check:,.0f})\n")
    recent = b[(b.source == "backtest") & (b.horizon == 1)].sort_values("target_period_end") \
        .groupby("ticker").tail(1)
    show = recent[["ticker", "target_period_end", "revenue_variance", "gp_variance", "gp_volume", "gp_mix", "gp_rate"]].copy()
    for c in show.columns[2:]:
        show[c] = (show[c] / 1e6).round(0)
    print("Latest 1-quarter-ahead backtest bridge ($M):")
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
