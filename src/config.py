"""Project configuration: companies, XBRL tags, known structural breaks, paths."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
FROZEN_DIR = ROOT / "forecasts" / "frozen"

# SEC requires a User-Agent with your name and email on every request.
# Set it once in PowerShell:  $env:SEC_USER_AGENT = "Your Name your.email@example.com"
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()

# Each company may span several SEC filers (CIKs) after re-domiciles or mergers.
# List the CURRENT filer first: when two filers report the same period, the first wins.
# `expect` is checked against the entity name EDGAR returns, to catch a wrong CIK.
COMPANIES = [
    {"ticker": "COHR", "name": "Coherent", "ciks": [820318], "expect": ["COHERENT", "II-VI"]},
    {"ticker": "LITE", "name": "Lumentum", "ciks": [1633978], "expect": ["LUMENTUM"]},
    {"ticker": "ANET", "name": "Arista Networks", "ciks": [1596532], "expect": ["ARISTA"]},
    {"ticker": "FN", "name": "Fabrinet", "ciks": [1408710], "expect": ["FABRINET"]},
    {"ticker": "CSCO", "name": "Cisco", "ciks": [858877], "expect": ["CISCO"]},
    {"ticker": "MRVL", "name": "Marvell", "ciks": [1835632, 1058057], "expect": ["MARVELL"]},
    {"ticker": "AVGO", "name": "Broadcom", "ciks": [1730168, 1649338, 1441634], "expect": ["BROADCOM", "AVAGO"]},
    {"ticker": "CIEN", "name": "Ciena", "ciks": [936395], "expect": ["CIENA"]},
]

# Candidate us-gaap tags per metric. Companies switch tags over time (ASC 606 in 2018),
# so every candidate is collected; build_quarters picks one value per period.
METRIC_TAGS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "rnd": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
}

# Large acquisitions that break the history. Close dates are approximate:
# confirm each against the company's 8-K and correct here (Phase 1, weekend 2).
# Quarters within 4 quarters after a close are flagged in the backtest.
EVENTS = [
    ("AVGO", "2018-11-05", "CA Technologies acquisition closes"),
    ("AVGO", "2019-11-04", "Symantec enterprise business acquisition closes"),
    ("AVGO", "2023-11-22", "VMware acquisition closes"),
    ("MRVL", "2018-07-06", "Cavium acquisition closes"),
    ("MRVL", "2021-04-20", "Inphi acquisition closes"),
    ("LITE", "2018-12-10", "Oclaro acquisition closes"),
    ("LITE", "2022-08-03", "NeoPhotonics acquisition closes"),
    ("COHR", "2019-09-24", "II-VI acquires Finisar"),
    ("COHR", "2022-07-01", "II-VI acquires Coherent, renamed Coherent Corp."),
    ("CSCO", "2024-03-18", "Splunk acquisition closes"),
]

# Backtest settings
MIN_TRAIN_QUARTERS = 16          # need 4 years of history before the first forecast
BACKTEST_FIRST_ORIGIN = "2017-01-01"
HORIZONS = [1, 2, 3, 4]
INTERVAL_QUANTILES = (0.10, 0.90)  # 80% band
