"""Pull segment and product-line revenue/profit from each 10-Q and 10-K's XBRL instance.

Run:  python src\\fetch_segments.py            (filings since 2021, all companies)
      python src\\fetch_segments.py --since 2019-01-01 --only COHR LITE

The companyfacts API only carries company totals. Segment figures live in the
"dimensional" facts of each filing (e.g. Revenue for StatementBusinessSegmentsAxis =
NetworkingSegmentMember), so this script downloads every filing's XBRL instance and keeps
every single-dimension, USD, duration fact for revenue-, gross-profit- and
operating-profit-like tags.

Downloads are cached in data/raw/filings/, so rerunning only fetches new filings.
Output: data/processed/segments_raw.csv (every candidate fact; mapped in build_segments.py)
"""
import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

from config import COMPANIES, PROCESSED_DIR, RAW_DIR, SEC_USER_AGENT

FILING_DIR = RAW_DIR / "filings"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"

# Tags worth keeping. Matched against the element's local name, any namespace
# (companies use their own tags for segment profit, e.g. cohr:SegmentOperatingIncome).
KEEP = re.compile(r"(Revenue|Revenues|SalesRevenue|GrossProfit|OperatingIncome|SegmentProfit|"
                  r"Contribution|OperatingProfit|CostOfRevenue|CostOfGoods)", re.I)
# note: plain "Tax" would drop RevenueFromContractWithCustomerExcludingAssessedTax
SKIP = re.compile(r"(Deferred|Remaining|Unbilled|Percent|IncomeTax|TaxExpense|Receivable|"
                  r"Liabilit|Obligation)", re.I)

session = requests.Session()


def get(url: str, cache: Path | None = None) -> bytes:
    if cache and cache.exists():
        return cache.read_bytes()
    for attempt in range(4):
        resp = session.get(url, timeout=90)
        time.sleep(0.15)  # SEC limit is 10 requests/second
        if resp.status_code == 200:
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(resp.content)
            return resp.content
        if resp.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"HTTP {resp.status_code} for {url}")
    raise RuntimeError(f"gave up on {url}")


def list_filings(cik: int, since: str) -> list[dict]:
    data = json.loads(get(SUBMISSIONS.format(cik=cik)))
    blocks = [data["filings"]["recent"]]
    for extra in data["filings"].get("files", []):
        blocks.append(json.loads(get("https://data.sec.gov/submissions/" + extra["name"])))
    out = []
    for b in blocks:
        for acc, form, filed, report in zip(b["accessionNumber"], b["form"], b["filingDate"], b["reportDate"]):
            if form in ("10-Q", "10-K") and filed >= since:
                out.append({"cik": cik, "accession": acc, "form": form, "filed": filed, "report_date": report})
    return out


def find_instance(cik: int, acc: str) -> str | None:
    """Name of the XBRL instance file inside a filing folder."""
    base = ARCHIVE.format(cik=cik, acc=acc.replace("-", ""))
    idx = json.loads(get(base + "index.json"))
    names = [i["name"] for i in idx["directory"]["item"]]
    xmls = [n for n in names if n.lower().endswith(".xml")
            and n != "FilingSummary.xml"
            and not re.search(r"_(cal|def|lab|pre)\.xml$", n, re.I)]
    for n in xmls:
        if n.lower().endswith("_htm.xml"):  # inline-XBRL filings (2019+): extracted instance
            return n
    return xmls[0] if xmls else None


def parse_instance(content: bytes) -> list[dict]:
    root = ET.fromstring(content)

    contexts = {}
    for ctx in root.iter(XBRLI + "context"):
        period = ctx.find(XBRLI + "period")
        start, end = period.find(XBRLI + "startDate"), period.find(XBRLI + "endDate")
        if start is None or end is None:
            continue  # instant (balance-sheet) context
        seg = ctx.find(f"{XBRLI}entity/{XBRLI}segment")
        members = [] if seg is None else list(seg)
        if not members or any(m.tag != XBRLDI + "explicitMember" for m in members):
            continue
        # Since ASU 2023-07 (2024+), segment tables often add a second label,
        # ConsolidationItemsAxis = OperatingSegmentsMember. Keep that pair as one fact.
        consolidation = ""
        if len(members) == 2:
            cons = [m for m in members if m.get("dimension", "").endswith("ConsolidationItemsAxis")]
            if len(cons) != 1:
                continue
            consolidation = (cons[0].text or "").strip().split(":")[-1]
            members = [m for m in members if m is not cons[0]]
        if len(members) != 1:
            continue
        m = members[0]
        contexts[ctx.get("id")] = {
            "start": start.text.strip(), "end": end.text.strip(),
            "dimension": m.get("dimension", "").split(":")[-1],
            "member": (m.text or "").strip().split(":")[-1],
            "consolidation": consolidation,
        }

    usd_units = set()
    for unit in root.iter(XBRLI + "unit"):
        measure = unit.find(XBRLI + "measure")
        if measure is not None and measure.text and measure.text.strip().endswith("USD"):
            usd_units.add(unit.get("id"))

    rows = []
    for el in root:
        ref = el.get("contextRef")
        if ref not in contexts or el.get("unitRef") not in usd_units:
            continue
        ns, _, local = el.tag[1:].partition("}")
        if not KEEP.search(local) or SKIP.search(local):
            continue
        try:
            value = float((el.text or "").strip())
        except ValueError:
            continue
        rows.append({"tag": local, "namespace": "us-gaap" if "fasb.org/us-gaap" in ns else "custom",
                     **contexts[ref], "value": value})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2021-01-01", help="first filing date to fetch")
    ap.add_argument("--only", nargs="*", default=[], help="tickers to fetch (default: all)")
    args = ap.parse_args()

    if not SEC_USER_AGENT or "@" not in SEC_USER_AGENT:
        print('Set your SEC User-Agent first, e.g. in cmd:\n'
              '  set "SEC_USER_AGENT=Your Name your.email@example.com"')
        return 1
    session.headers.update({"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})

    all_rows = []
    for co in COMPANIES:
        if args.only and co["ticker"] not in [t.upper() for t in args.only]:
            continue
        n_files = n_rows = 0
        for cik in co["ciks"]:
            for f in list_filings(cik, args.since):
                try:
                    acc_dir = FILING_DIR / str(cik) / f["accession"]
                    cached = list(acc_dir.glob("*.xml"))
                    name = cached[0].name if cached else find_instance(cik, f["accession"])
                    if not name:
                        print(f"  !! {co['ticker']} {f['accession']}: no XBRL instance found")
                        continue
                    base = ARCHIVE.format(cik=cik, acc=f["accession"].replace("-", ""))
                    rows = parse_instance(get(base + name, acc_dir / name))
                except Exception as exc:  # one bad filing shouldn't stop the run
                    print(f"  !! {co['ticker']} {f['accession']}: {exc}")
                    continue
                for r in rows:
                    r.update({"ticker": co["ticker"], **f})
                all_rows += rows
                n_files += 1
                n_rows += len(rows)
        print(f"  {co['ticker']:5} {n_files:>3} filings, {n_rows:>6,} segment facts")

    if not all_rows:
        print("No segment facts found.")
        return 2
    df = pd.DataFrame(all_rows)
    cols = ["ticker", "cik", "accession", "form", "filed", "report_date", "tag", "namespace",
            "dimension", "member", "consolidation", "start", "end", "value"]
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df[cols].to_csv(PROCESSED_DIR / "segments_raw.csv", index=False)
    print(f"\nWrote {len(df):,} rows to data/processed/segments_raw.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
