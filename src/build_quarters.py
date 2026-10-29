"""Turn raw EDGAR companyfacts into clean, discrete fiscal quarters.

Run:  python src/build_quarters.py

Handles the usual EDGAR traps:
  * 10-Qs report year-to-date (6- and 9-month) figures as well as 3-month ones
  * 10-Ks report only the full year, so Q4 = full year - first nine months
  * the same period is restated in later filings: we keep BOTH the first-reported
    value (what was known at the time; used for backtests and scoring) and the
    latest value (best current figure; used for analysis and the live forecast)
  * tag changes over time (e.g. Revenues -> RevenueFromContractWithCustomer...)
  * companies spread across several filers (CIKs) after re-domiciles

Outputs (data/processed/):
  quarters_long.csv  one row per company x metric x quarter
  quarters_wide.csv  one row per company x quarter, latest values + margins
"""
import json
from datetime import date, timedelta

import pandas as pd

from config import COMPANIES, METRIC_TAGS, PROCESSED_DIR, RAW_DIR

QUARTER = (80, 100)
HALF = (170, 200)
NINE = (260, 290)
YEAR = (350, 380)
DAY = timedelta(days=1)


# ---------------------------------------------------------------- loading
def load_facts(co: dict) -> pd.DataFrame:
    """All duration facts in USD for every candidate tag, across the company's CIKs."""
    rows = []
    for rank, cik in enumerate(co["ciks"]):
        path = RAW_DIR / f"CIK{cik:010d}.json"
        if not path.exists():
            print(f"  !! {co['ticker']}: missing {path.name} (run ingest_edgar.py)")
            continue
        gaap = json.loads(path.read_text()).get("facts", {}).get("us-gaap", {})
        for metric, tags in METRIC_TAGS.items():
            for tag in tags:
                for f in gaap.get(tag, {}).get("units", {}).get("USD", []):
                    if "start" not in f or not str(f.get("form", "")).startswith("10-"):
                        continue
                    rows.append({
                        "metric": metric, "tag": tag, "rank": rank,
                        "start": date.fromisoformat(f["start"]),
                        "end": date.fromisoformat(f["end"]),
                        "val": float(f["val"]),
                        "filed": date.fromisoformat(f["filed"]),
                    })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["dur"] = (df["end"] - df["start"]).apply(lambda d: d.days)
    return df


def collapse_periods(facts: pd.DataFrame) -> list[dict]:
    """One record per (start, end) period: first-reported and latest value."""
    out = []
    for (start, end), g in facts.groupby(["start", "end"]):
        g_first = g.sort_values(["filed", "rank"]).iloc[0]
        g_last = g.sort_values(["filed", "rank"], ascending=[False, True]).iloc[0]
        out.append({
            "start": start, "end": end, "dur": (end - start).days,
            "first": g_first["val"], "first_filed": g_first["filed"],
            "latest": g_last["val"], "latest_filed": g_last["filed"],
            "rank": int(g["rank"].min()), "method": "reported",
        })
    return out


# ---------------------------------------------------------------- quarter logic
def _in(rng, d):
    return rng[0] <= d <= rng[1]


def _near(a: date, b: date, days: int = 7) -> bool:
    return abs((a - b).days) <= days


def _combine(base: dict, parts: list[dict], start: date, end: date, method: str) -> dict:
    """base minus the sum of parts, carried through for both vintages."""
    return {
        "start": start, "end": end, "dur": (end - start).days,
        "first": base["first"] - sum(p["first"] for p in parts),
        "first_filed": max([base["first_filed"]] + [p["first_filed"] for p in parts]),
        "latest": base["latest"] - sum(p["latest"] for p in parts),
        "latest_filed": max([base["latest_filed"]] + [p["latest_filed"] for p in parts]),
        "rank": base["rank"], "method": method,
    }


def discrete_quarters(periods: list[dict]) -> dict[date, dict]:
    """Return {quarter_end: record}, deriving quarters missing from YTD and annual figures."""
    quarters: dict[date, dict] = {}
    for p in periods:
        if _in(QUARTER, p["dur"]):
            cur = quarters.get(p["end"])
            if cur is None or (p["rank"], abs(p["dur"] - 91)) < (cur["rank"], abs(cur["dur"] - 91)):
                quarters[p["end"]] = p

    halves = [p for p in periods if _in(HALF, p["dur"])]
    nines = [p for p in periods if _in(NINE, p["dur"])]
    years = [p for p in periods if _in(YEAR, p["dur"])]

    def q_starting(d):
        return next((q for q in quarters.values() if _near(q["start"], d)), None)

    def add(cand):
        """Add a derived quarter, or improve the vintages of one already known.

        A 3-month figure sometimes first appears only as next year's comparative,
        while the same quarter could already be derived from YTD figures a year
        earlier. Keep the earliest-filed value as 'first' and the newest as 'latest'.
        """
        key = next((e for e in quarters if _near(e, cand["end"], 5)), None)
        if key is None:
            quarters[cand["end"]] = cand
            return
        cur = dict(quarters[key])
        if cand["first_filed"] < cur["first_filed"]:
            cur["first"], cur["first_filed"] = cand["first"], cand["first_filed"]
        if cand["latest_filed"] > cur["latest_filed"]:
            cur["latest"], cur["latest_filed"] = cand["latest"], cand["latest_filed"]
        quarters[key] = cur

    for _ in range(2):  # second pass picks up quarters that depend on derived ones
        for h in halves:
            q1 = q_starting(h["start"])
            if q1 and q1["end"] < h["end"]:
                add(_combine(h, [q1], q1["end"] + DAY, h["end"], "derived_h1_minus_q1"))
        for n in nines:
            h = next((x for x in halves if _near(x["start"], n["start"]) and x["end"] < n["end"]), None)
            if h:
                add(_combine(n, [h], h["end"] + DAY, n["end"], "derived_9m_minus_6m"))
        for y in years:
            n = next((x for x in nines if _near(x["start"], y["start"]) and x["end"] < y["end"]), None)
            if n:
                add(_combine(y, [n], n["end"] + DAY, y["end"], "derived_fy_minus_9m"))
                continue
            q1 = q_starting(y["start"])
            q2 = q_starting(q1["end"] + DAY) if q1 else None
            q3 = q_starting(q2["end"] + DAY) if q2 else None
            if q3 and q3["end"] < y["end"]:
                add(_combine(y, [q1, q2, q3], q3["end"] + DAY, y["end"], "derived_fy_minus_3q"))
    return quarters


# ---------------------------------------------------------------- labels
def calendar_quarter(end: date) -> str:
    """Nearest calendar quarter end, e.g. a 2025-11-02 period end -> '2025Q3'."""
    cands = [date(y, m, d) for y in (end.year - 1, end.year, end.year + 1)
             for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))]
    best = min(cands, key=lambda c: abs((c - end).days))
    return f"{best.year}Q{(best.month - 1) // 3 + 1}"


def fiscal_label(end: date, fy_ends: list[date]) -> tuple[int, int]:
    """Fiscal year (named for the calendar year it ends in) and quarter number."""
    anchor = min(fy_ends, key=lambda e: abs((e - end).days))
    k = round((end - anchor).days / 91.3)
    idx = 4 + k
    return anchor.year + (idx - 1) // 4, (idx - 1) % 4 + 1


# ---------------------------------------------------------------- main
def build_company(co: dict) -> pd.DataFrame:
    facts = load_facts(co)
    if facts.empty:
        return pd.DataFrame()

    records = []
    fy_ends: list[date] = []
    for metric, tags in METRIC_TAGS.items():
        per_end: dict[date, dict] = {}
        for tag in tags:
            sub = facts[(facts.metric == metric) & (facts.tag == tag)]
            if sub.empty:
                continue
            periods = collapse_periods(sub)
            if metric == "revenue":
                fy_ends += [p["end"] for p in periods if _in(YEAR, p["dur"])]
            for end, q in discrete_quarters(periods).items():
                q = {**q, "source_tag": tag}
                cur = per_end.get(end)
                # several tags can cover one quarter: prefer the current filer, then the largest
                if cur is None or (q["rank"], -abs(q["latest"])) < (cur["rank"], -abs(cur["latest"])):
                    per_end[end] = q
        for end, q in per_end.items():
            records.append({"ticker": co["ticker"], "metric": metric, **q})

    df = pd.DataFrame(records)
    if df.empty:
        return df

    # drop near-duplicate quarter ends (old and new filer disagreeing by a few days)
    keep = []
    for metric, g in df.sort_values(["metric", "end"]).groupby("metric"):
        last = None
        for _, r in g.iterrows():
            if last is not None and (r["end"] - last["end"]).days < 30:
                if r["rank"] < last["rank"]:
                    keep[-1] = r
                    last = r
                continue
            keep.append(r)
            last = r
    df = pd.DataFrame(keep)

    # gross profit fallback: revenue - cost of revenue where GrossProfit isn't tagged
    rev = df[df.metric == "revenue"].set_index("end")
    cogs = df[df.metric == "cost_of_revenue"].set_index("end")
    have_gp = set(df[df.metric == "gross_profit"]["end"])
    extra = []
    for end in rev.index.intersection(cogs.index):
        if end in have_gp:
            continue
        r, c = rev.loc[end], cogs.loc[end]
        extra.append({**r.to_dict(), "end": end, "metric": "gross_profit",
                      "first": r["first"] - c["first"], "latest": r["latest"] - c["latest"],
                      "first_filed": max(r["first_filed"], c["first_filed"]),
                      "latest_filed": max(r["latest_filed"], c["latest_filed"]),
                      "method": "derived_rev_minus_cogs", "source_tag": "derived"})
    if extra:
        df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)

    fy_ends = sorted(set(fy_ends))
    if not fy_ends:
        print(f"  !! {co['ticker']}: no annual revenue found; fiscal labels unavailable")
    df["calendar_quarter"] = df["end"].apply(calendar_quarter)
    if fy_ends:
        labels = df["end"].apply(lambda e: fiscal_label(e, fy_ends))
        df["fiscal_year"] = labels.str[0]
        df["fiscal_quarter"] = labels.str[1]
    return df


def check_continuity(df: pd.DataFrame) -> None:
    for ticker, g in df[df.metric == "revenue"].sort_values("period_end").groupby("ticker"):
        ends = list(g["period_end"])
        gaps = [(a, b) for a, b in zip(ends, ends[1:]) if not 77 <= (b - a).days <= 105]
        span = f"{ends[0]} to {ends[-1]}" if ends else "none"
        msg = f"  {ticker:5} {len(ends):>3} revenue quarters, {span}"
        if gaps:
            msg += f"  !! {len(gaps)} gap(s): " + ", ".join(f"{a}->{b}" for a, b in gaps[:4])
        print(msg)


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    frames = [build_company(co) for co in COMPANIES]
    df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    df = df.rename(columns={"start": "period_start", "end": "period_end",
                            "first": "value_first", "latest": "value_latest"})
    cols = ["ticker", "metric", "period_start", "period_end", "fiscal_year", "fiscal_quarter",
            "calendar_quarter", "value_first", "first_filed", "value_latest", "latest_filed",
            "source_tag", "method"]
    df = df[cols].sort_values(["ticker", "metric", "period_end"])
    df.to_csv(PROCESSED_DIR / "quarters_long.csv", index=False)

    wide = df.pivot_table(index=["ticker", "period_end", "fiscal_year", "fiscal_quarter", "calendar_quarter"],
                          columns="metric", values="value_latest").reset_index()
    if {"revenue", "gross_profit"} <= set(wide.columns):
        wide["gross_margin_pct"] = 100 * wide["gross_profit"] / wide["revenue"]
        bad = wide[(wide.gross_margin_pct < 0) | (wide.gross_margin_pct > 100)]
        if not bad.empty:
            print(f"  !! {len(bad)} quarter(s) with gross margin outside 0-100%: check tags")
    if {"revenue", "operating_income"} <= set(wide.columns):
        wide["operating_margin_pct"] = 100 * wide["operating_income"] / wide["revenue"]
    wide.to_csv(PROCESSED_DIR / "quarters_wide.csv", index=False)

    check_continuity(df)
    derived = (df.method != "reported").sum()
    print(f"\nWrote {len(df):,} rows ({derived:,} derived quarters) to data/processed/")


if __name__ == "__main__":
    main()
