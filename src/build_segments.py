"""Turn segments_raw.csv into clean quarterly segment revenue and gross profit.

Run:  python src\\build_segments.py

Uses the segment map in config.SEGMENTS. Quarters are built with the same logic as
build_quarters.py (Q4 = full year - nine months, etc.). Values are the LATEST reported,
because companies recast past quarters when they reorganise segments, and the recast
figures are the ones comparable with today's structure.

A quarter is kept only if its segments add up to total company revenue within 2%.
Output: data/processed/segments_q.csv
"""
from collections import defaultdict
from datetime import date

import pandas as pd

from build_quarters import collapse_periods, discrete_quarters
from config import PROCESSED_DIR, SEG_REVENUE_TAGS, SEGMENT_TOLERANCE, SEGMENTS

OK_CONSOLIDATION = {"", "OperatingSegmentsMember"}


def member_quarters(raw: pd.DataFrame, member: str, tags: list[str]) -> dict[date, float]:
    """Quarterly values (latest reported) for one member, from any of the given tags."""
    sub = raw[(raw.member == member) & raw.tag.isin(tags)]
    if sub.empty:
        return {}
    facts = pd.DataFrame({
        "start": sub.start.map(date.fromisoformat), "end": sub.end.map(date.fromisoformat),
        "val": sub.value.astype(float), "filed": sub.filed.map(date.fromisoformat), "rank": 0,
    })
    return {end: q["latest"] for end, q in discrete_quarters(collapse_periods(facts)).items()}


def nearest(d: date, keys, days: int = 6):
    best = min(keys, key=lambda k: abs((k - d).days), default=None)
    return best if best is not None and abs((best - d).days) <= days else None


def build_company(tk: str, spec: dict, raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw[(raw.ticker == tk) & (raw.dimension == spec["axis"])
              & raw.consolidation.isin(OK_CONSOLIDATION)]
    rows = []
    for seg, alternatives in spec["segments"].items():
        rev_by_alt = [[member_quarters(raw, m, SEG_REVENUE_TAGS) for m in alt] for alt in alternatives]
        gp_by_alt = [[member_quarters(raw, m, ["GrossProfit", "SegmentGrossProfit"]) for m in alt]
                     for alt in alternatives]
        cost_by_alt = [[member_quarters(raw, m, spec.get("cost_tags", [])) for m in alt]
                       for alt in alternatives]
        ends = sorted({e for alt in rev_by_alt for d in alt for e in d})
        for end in ends:
            for i, alt in enumerate(rev_by_alt):
                keys = [nearest(end, d.keys()) for d in alt]
                if all(k is not None for k in keys):
                    revenue = sum(d[k] for d, k in zip(alt, keys))
                    gp = None
                    gk = [nearest(end, d.keys()) for d in gp_by_alt[i]]
                    ck = [nearest(end, d.keys()) for d in cost_by_alt[i]]
                    if all(k is not None for k in gk):
                        gp = sum(d[k] for d, k in zip(gp_by_alt[i], gk))
                    elif ck and all(k is not None for k in ck):
                        gp = revenue - sum(d[k] for d, k in zip(cost_by_alt[i], ck))
                    rows.append({"ticker": tk, "period_end": end, "segment": seg,
                                 "revenue": revenue, "gross_profit": gp})
                    break
    return pd.DataFrame(rows)


def main() -> None:
    raw = pd.read_csv(PROCESSED_DIR / "segments_raw.csv", dtype={"consolidation": str}).fillna({"consolidation": ""})
    wide = pd.read_csv(PROCESSED_DIR / "quarters_wide.csv")
    totals = {(r.ticker, date.fromisoformat(r.period_end)): r.revenue for r in wide.itertuples()}

    frames = []
    for tk, spec in SEGMENTS.items():
        seg = build_company(tk, spec, raw)
        if seg.empty:
            print(f"  {tk:5} !! no segment data")
            continue
        n_segs = len(spec["segments"])
        company_ends = [e for (t, e) in totals if t == tk]
        keep, dropped = [], defaultdict(int)
        for end, g in seg.groupby("period_end"):
            match = nearest(end, company_ends)
            if len(g) != n_segs or match is None:
                dropped["incomplete"] += 1
                continue
            total = totals[(tk, match)]
            if (g.revenue <= 0).any():
                # a Q4 derived as full year - nine months goes negative when the 10-K
                # redefines segments without recasting the quarters (Lumentum FY2026)
                dropped["segments redefined"] += 1
                continue
            if abs(g.revenue.sum() / total - 1) > SEGMENT_TOLERANCE:
                dropped["doesn't add up"] += 1
                continue
            g = g.assign(period_end=match)
            if g.gross_profit.isna().any():
                g = g.assign(gross_profit=None)
            keep.append(g)
        if not keep:
            print(f"  {tk:5} !! no complete quarters ({dict(dropped)})")
            continue
        out = pd.concat(keep)
        frames.append(out)
        ends = sorted(out.period_end.unique())
        has_gp = out.gross_profit.notna().groupby(out.period_end).all().sum()
        note = f"  dropped: {dict(dropped)}" if dropped else ""
        print(f"  {tk:5} {len(ends):>3} quarters {ends[0]} to {ends[-1]}, "
              f"{n_segs} segments, gross profit in {has_gp}{note}")

    df = pd.concat(frames, ignore_index=True).sort_values(["ticker", "period_end", "segment"])
    df.to_csv(PROCESSED_DIR / "segments_q.csv", index=False)
    print(f"\nWrote {len(df):,} rows to data/processed/segments_q.csv")


if __name__ == "__main__":
    main()
