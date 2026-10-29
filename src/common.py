"""Shared helpers: load modeling series and flag acquisition windows."""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from config import EVENTS, PROCESSED_DIR


def load_long() -> pd.DataFrame:
    df = pd.read_csv(PROCESSED_DIR / "quarters_long.csv",
                     parse_dates=["period_start", "period_end", "first_filed", "latest_filed"])
    return df


def company_series(long: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Revenue and gross margin per quarter, first-reported and latest, oldest first.

    Only the most recent unbroken run of quarters is kept, because a gap in the
    history would scramble the seasonal pattern the models rely on.
    """
    sub = long[long.ticker == ticker]
    def pick(metric, col):
        return sub[sub.metric == metric].set_index("period_end")[col]
    s = pd.DataFrame({
        "rev_first": pick("revenue", "value_first"),
        "rev_latest": pick("revenue", "value_latest"),
        "gp_first": pick("gross_profit", "value_first"),
        "gp_latest": pick("gross_profit", "value_latest"),
        "filed_first": pick("revenue", "first_filed"),
        "fiscal_year": pick("revenue", "fiscal_year"),
        "fiscal_quarter": pick("revenue", "fiscal_quarter"),
        "calendar_quarter": pick("revenue", "calendar_quarter"),
    }).dropna(subset=["rev_first"]).sort_index()
    s["gm_first"] = 100 * s["gp_first"] / s["rev_first"]
    s["gm_latest"] = 100 * s["gp_latest"] / s["rev_latest"]

    ends = list(s.index)
    start = 0
    for i in range(len(ends) - 1, 0, -1):
        if not 77 <= (ends[i] - ends[i - 1]).days <= 105:
            start = i
            break
    return s.iloc[start:]


def in_event_window(ticker: str, target_end, quarters: int = 4) -> bool:
    """True if the quarter ends within `quarters` quarters after a big acquisition closed."""
    t = pd.Timestamp(target_end).date()
    for tk, d, _ in EVENTS:
        close = date.fromisoformat(d)
        if tk == ticker and close <= t <= close + timedelta(days=92 * quarters):
            return True
    return False


def fiscal_label_ahead(last_fy: int, last_fq: int, h: int) -> str:
    idx = last_fq + h
    return f"FY{last_fy + (idx - 1) // 4} Q{(idx - 1) % 4 + 1}"


def trailing_run(values) -> np.ndarray:
    """The values after the last missing one, so a model never fits across a hole."""
    v = np.asarray(values, dtype=float)
    missing = np.where(np.isnan(v))[0]
    return v[missing[-1] + 1:] if len(missing) else v
