"""Historical fed funds, for pricing past % of full carry at the rate of the day.

The app's live interest rate is front-month ZQ-implied fed funds + a fixed spread. Holding
that one rate for every past session misstates history badly — fed funds sat near 0.1%
through 2021 and above 5% in 2023-24 — so each historical session is priced at the
effective fed funds rate that day plus the same spread.

Source: Board of Governors of the Federal Reserve System (US), Federal Funds Effective
Rate [DFF], H.15 Selected Interest Rates, retrieved from FRED, Federal Reserve Bank of
St. Louis; https://fred.stlouisfed.org/series/DFF. Public domain, citation requested.

DFF is published for every calendar day (weekends carry the prior business day), so a
session always has a value. The live FRED download is preferred; if it is unreachable
the committed snapshot in data/fed_funds_dff.csv is used instead.

Note the small convention difference this leaves: history uses the *effective* rate on
the day, while today's rate in the app is the *ZQ futures-implied* rate for the month.
"""
from __future__ import annotations

from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF&cosd=2006-01-01"
SNAPSHOT_PATH = Path(__file__).parent / "data" / "fed_funds_dff.csv"

_LAST_SOURCE = "none"


def fed_funds_source() -> str:
    """'fred', 'snapshot', or 'none' — which source served the last load."""
    return _LAST_SOURCE


def _parse(csv_text: str) -> pd.Series:
    frame = pd.read_csv(StringIO(csv_text))
    frame.columns = [c.strip().lower() for c in frame.columns]
    date_col = "observation_date" if "observation_date" in frame.columns else frame.columns[0]
    value_col = "dff" if "dff" in frame.columns else frame.columns[1]
    # FRED marks missing observations with "." — drop them rather than read them as zero.
    values = pd.to_numeric(frame[value_col], errors="coerce")
    series = pd.Series(values.to_numpy(), index=pd.to_datetime(frame[date_col]).dt.date)
    return series.dropna().sort_index()


def load_fed_funds_history(timeout: float = 15.0) -> pd.Series:
    """Daily effective fed funds, percent, indexed by date (ascending)."""
    global _LAST_SOURCE
    try:
        resp = requests.get(FRED_URL, timeout=timeout)
        resp.raise_for_status()
        series = _parse(resp.text)
        if len(series):
            _LAST_SOURCE = "fred"
            return series
    except Exception:
        pass  # fall through to the snapshot

    if SNAPSHOT_PATH.exists():
        series = _parse(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        if len(series):
            _LAST_SOURCE = "snapshot"
            return series

    _LAST_SOURCE = "none"
    return pd.Series(dtype=float)


def annual_rates_on(fed_funds: pd.Series, dates, spread_pct: float, fallback: float) -> pd.Series:
    """Decimal annual carry rate per date: (fed funds that day + spread) / 100.

    Dates past the end of the series carry the latest published value forward; dates
    before its start, or an empty series, use `fallback` (already a decimal)."""
    index = list(dates)
    if fed_funds is None or not len(fed_funds):
        return pd.Series([fallback] * len(index), index=index, dtype=float)
    merged = fed_funds.reindex(sorted(set(fed_funds.index) | set(index))).ffill()
    aligned = merged.reindex(index)
    return ((aligned + spread_pct) / 100).fillna(fallback)


def refresh_snapshot() -> int:
    """Rewrite the committed fallback from FRED. Returns the number of rows written."""
    resp = requests.get(FRED_URL, timeout=30)
    resp.raise_for_status()
    series = _parse(resp.text)
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"observation_date": series.index, "DFF": series.values}).to_csv(
        SNAPSHOT_PATH, index=False
    )
    return len(series)


if __name__ == "__main__":
    print(f"wrote {refresh_snapshot():,} rows to {SNAPSHOT_PATH}")
