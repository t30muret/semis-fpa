"""Write fake companyfacts JSON that reproduces EDGAR's traps, for offline testing.

Traps included: YTD-only Q2/Q3 for one company, Q4 only in the 10-K, restated
comparatives filed a year later, a revenue tag switch in 2018, a company split
across two CIKs, and one company with no GrossProfit tag.
Truth is written to tests/truth.csv so build_quarters can be checked exactly.
"""
import calendar
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from config import COMPANIES, RAW_DIR  # noqa: E402

FY_END_MONTH = {"COHR": 6, "LITE": 6, "ANET": 12, "FN": 6, "CSCO": 7, "MRVL": 1, "AVGO": 10, "CIEN": 10}
YTD_ONLY = {"CSCO"}
NO_GP_TAG = {"FN"}
rng = np.random.default_rng(7)


def month_end(y, m):
    return date(y, m, calendar.monthrange(y, m)[1])


def add_months(d, k):
    m = d.month - 1 + k
    return month_end(d.year + m // 12, m % 12 + 1)


def fact(start, end, val, filed, form):
    return {"start": start.isoformat(), "end": end.isoformat(), "val": int(round(val)),
            "filed": filed.isoformat(), "form": form, "accn": "0000000000-00-000000"}


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    truth = []
    for co in COMPANIES:
        tk = co["ticker"]
        facts = {c: {} for c in co["ciks"]}
        fy_m = FY_END_MONTH[tk]
        base = rng.uniform(300e6, 3e9)
        season = np.array([0.97, 1.0, 1.01, 1.04])
        for fy in range(2012, 2027):
            fy_end = month_end(fy, fy_m)
            q_ends = [add_months(fy_end, -9 + 3 * i) for i in range(4)]
            if q_ends[0] > date(2026, 9, 30):
                break
            qs = []
            for i, e in enumerate(q_ends):
                t = (e.year - 2012) * 4 + i
                rev = base * (1.025 ** t) * season[i] * rng.normal(1, 0.03)
                gm = 0.45 + 0.03 * np.sin(t / 6) + rng.normal(0, 0.01)
                start = add_months(e, -3) + timedelta(days=1)
                qs.append((start, e, rev, rev * gm))
            cik = co["ciks"][-1] if (len(co["ciks"]) > 1 and fy < 2018) else co["ciks"][0]
            rev_tag = "Revenues" if fy < 2018 else "RevenueFromContractWithCustomerExcludingAssessedTax"
            store = facts[cik]

            def put(tag, f):
                store.setdefault(tag, {"units": {"USD": []}})["units"]["USD"].append(f)

            fy_start = qs[0][0]
            for i, (s, e, rev, gp) in enumerate(qs):
                if e > date(2026, 9, 30):
                    break
                cogs = rev - gp
                form = "10-K" if i == 3 else "10-Q"
                filed = e + timedelta(days=60 if i == 3 else 35)
                truth.append({"ticker": tk, "period_end": e.isoformat(), "revenue": round(rev), "gross_profit": round(gp)})
                vals = {rev_tag: rev, "CostOfRevenue": cogs}
                if tk not in NO_GP_TAG:
                    vals["GrossProfit"] = gp
                for tag, v in vals.items():
                    ytd = sum((r if tag == rev_tag else (r - g if tag == "CostOfRevenue" else g))
                              for (_, _, r, g) in qs[:i + 1])
                    if i == 3:
                        put(tag, fact(fy_start, e, ytd, filed, form))
                        continue
                    if i == 0 or tk not in YTD_ONLY:
                        put(tag, fact(s, e, v, filed, form))
                    if i > 0:
                        put(tag, fact(fy_start, e, ytd, filed, form))
                    # restated comparative in next year's 10-Q, 1% higher, filed a year later
                    if e < date(2025, 9, 30):
                        put(tag, fact(s, e, v * 1.01, filed + timedelta(days=365), "10-Q"))
        for cik, tags in facts.items():
            doc = {"cik": cik, "entityName": co["name"].upper() + " (SYNTHETIC)", "facts": {"us-gaap": tags}}
            (RAW_DIR / f"CIK{cik:010d}.json").write_text(json.dumps(doc))
    import csv
    with open(ROOT / "tests" / "truth.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=truth[0].keys())
        w.writeheader()
        w.writerows(truth)
    print(f"Wrote synthetic data for {len(COMPANIES)} companies, {len(truth)} true quarters")


if __name__ == "__main__":
    main()
