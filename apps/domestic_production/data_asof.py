"""The "Data as of" line above the tabs: which USDA report the numbers on the page come from, and when our copy was last refreshed.

* NASS vintage: read from the data itself. The cached national pull carries every report period NASS has published for a crop year
  (YEAR - NOV FORECAST, YEAR - SEP FORECAST, YEAR - JUN ACREAGE, ...); the newest one for the current year is the report the latest
  numbers come from. Before the first forecast of a year it falls back to the last Annual Summary.
* Refresh time: the newest successful pull of this dashboard's lists in the shared cache (usda-nass-etl runs 6:30 am and 3:00 pm
  Central on weekdays and weekends alike; the 3:00 pm run catches same-day USDA releases).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from nass_cache_client import _sf_connect, _use_sf, cache_freshness

# NASS reference periods in the order they are published within a crop year, with the report each one is.
REPORTS = [
    ("YEAR - MAR ACREAGE", "March Prospective Plantings"),
    ("YEAR - MAY FORECAST", "May Crop Production"),
    ("YEAR - JUN ACREAGE", "June Acreage"),
    ("YEAR - JUN FORECAST", "June Crop Production"),
    ("YEAR - JUL FORECAST", "July Crop Production"),
    ("YEAR - AUG FORECAST", "August Crop Production"),
    ("YEAR - SEP FORECAST", "September Crop Production"),
    ("YEAR - OCT FORECAST", "October Crop Production"),
    ("YEAR - NOV FORECAST", "November Crop Production"),
    ("YEAR - DEC FORECAST", "December Crop Production"),
]
_ORDER = {p: i for i, (p, _) in enumerate(REPORTS)}
_NAME = dict(REPORTS)
_CENTRAL = None


def central():
    global _CENTRAL
    if _CENTRAL is None:
        try:
            from zoneinfo import ZoneInfo
            _CENTRAL = ZoneInfo("America/Chicago")
        except Exception:                                    # no tz database (a bare Windows Python): fixed standard time
            _CENTRAL = timezone(timedelta(hours=-6))
    return _CENTRAL


def nass_vintage(df: pd.DataFrame, this_year: int):
    """(report name, crop year, release date or None) of the newest NASS report in `df` (one metric's cached national pull).
    The current crop year is used when it has any rows, otherwise the latest year there is; None when df is empty."""
    if df is None or df.empty or "year" not in df.columns or "reference_period_desc" not in df.columns:
        return None
    years = pd.to_numeric(df["year"], errors="coerce")
    present = sorted({int(y) for y in years.dropna() if y <= this_year}, reverse=True)
    if not present:
        return None
    year = present[0]
    rows = df[years == year]
    periods = {str(p).strip().upper() for p in rows["reference_period_desc"].dropna()}
    in_season = sorted((p for p in periods if p in _ORDER), key=_ORDER.get)
    period = in_season[-1] if in_season else None
    name = _NAME[period] if period else "Annual Summary"
    pick = rows[rows["reference_period_desc"].str.upper().str.strip() == (period or "YEAR")]
    released = None
    if "load_time" in pick.columns:
        stamps = pd.to_datetime(pick["load_time"], errors="coerce").dropna()
        if not stamps.empty:
            released = stamps.max().date()
    return name, year, released


@st.cache_data(ttl=300, show_spinner=False)
def cache_refreshed(dashboards: tuple = ("domestic-production-dashboard", "asd-county-tab")):
    """Newest successful pull of these job lists in the shared cache, as a tz-aware datetime, or None."""
    try:
        if _use_sf():
            conn = _sf_connect()
            try:
                cur = conn.cursor()
                cur.execute("SELECT MAX(fetched_at) FROM nass_cache WHERE error IS NULL AND dashboard IN (%s)"
                            % ",".join(["%s"] * len(dashboards)), list(dashboards))
                value = cur.fetchone()[0]
            finally:
                conn.close()
        else:
            value = cache_freshness()                        # legacy backend: newest row of the whole cache
        if not value:
            return None
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.to_pydatetime()
    except Exception:
        return None


def fmt_moment(dt: datetime) -> str:
    local = dt.astimezone(central())
    return f"{local:%b} {local.day}, {local.hour % 12 or 12}:{local:%M} {'am' if local.hour < 12 else 'pm'} CT"


def line(df: pd.DataFrame, commodity: str, this_year: int, refreshed: datetime | None) -> str:
    """The text of the strip (HTML-safe: only the labels are bold)."""
    parts = []
    v = nass_vintage(df, this_year)
    if v:
        name, year, released = v
        when = f", released {released:%b} {released.day}" if released else ""
        parts.append(f"<b>USDA NASS</b>: {name}, {year} {commodity.lower()}{when}")
    if refreshed:
        parts.append(f"<b>Our copy refreshed</b> {fmt_moment(refreshed)}")
    return "  &middot;  ".join(parts)


def render(df: pd.DataFrame, commodity: str, this_year: int, color: str, border: str) -> None:
    text = line(df, commodity, this_year, cache_refreshed())
    if text:
        st.markdown(
            f"<div style='margin:2px 0 10px;padding:6px 12px;border:1px solid {border};border-radius:6px;"
            f"font-size:12.5px;color:{color};'><span style='letter-spacing:.06em;font-weight:700;"
            f"text-transform:uppercase;font-size:11px;margin-right:10px'>Data as of</span>{text}</div>",
            unsafe_allow_html=True,
        )
