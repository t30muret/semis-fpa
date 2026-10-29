"""Download SEC EDGAR companyfacts JSON for every filer in config.COMPANIES.

Run:  python src/ingest_edgar.py
Saves data/raw/CIK##########.json and prints each filer's EDGAR entity name so you
can confirm every CIK points at the company you meant.
"""
import json
import sys
import time

import requests

from config import COMPANIES, RAW_DIR, SEC_USER_AGENT

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def main() -> int:
    if not SEC_USER_AGENT or "@" not in SEC_USER_AGENT:
        print('Set your SEC User-Agent first, e.g. in PowerShell:\n'
              '  $env:SEC_USER_AGENT = "Your Name your.email@example.com"')
        return 1

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})

    problems = 0
    for co in COMPANIES:
        for cik in co["ciks"]:
            resp = session.get(URL.format(cik=cik), timeout=60)
            time.sleep(0.2)  # SEC allows 10 requests/second; stay well under
            if resp.status_code != 200:
                print(f"  !! {co['ticker']} CIK {cik}: HTTP {resp.status_code}")
                problems += 1
                continue
            data = resp.json()
            name = data.get("entityName", "?")
            ok = any(word in name.upper() for word in co["expect"])
            n_tags = len(data.get("facts", {}).get("us-gaap", {}))
            flag = "ok" if ok else "!! NAME MISMATCH - check this CIK"
            print(f"  {co['ticker']:5} CIK {cik:>8}  {name:<45} {n_tags:>4} us-gaap tags  {flag}")
            problems += 0 if ok else 1
            (RAW_DIR / f"CIK{cik:010d}.json").write_text(json.dumps(data))

    print("\nDone." if not problems else f"\nDone with {problems} problem(s) above.")
    return 0 if not problems else 2


if __name__ == "__main__":
    sys.exit(main())
