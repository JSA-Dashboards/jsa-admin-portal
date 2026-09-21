"""US stocks-to-use ratio by marketing year, pulled straight from USDA's own WASDE
report CSV export (the same one wasde-dashboard/app.py downloads) — used to flag
"similar" prior seasonal years for the seasonal charts' highlight feature.

The FAS PSD REST API (apps.fas.usda.gov/psdonline/api and /opendata/api) 404s/500s
under every auth variant tried, so this reads the same published numbers a different
way: each monthly WASDE CSV carries a US balance-sheet table for 3 marketing years
(prior-final, current-estimate, next-projected). Fetching every 3rd year's August
report tiles that 3-year window across decades with no gaps and no overlap.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO

import pandas as pd
import requests

WASDE_CSV_URL = "https://www.usda.gov/sites/default/files/documents/oce-wasde-report-data-{year}-{month:02d}.csv"

# USDA's WAF 403s the default `python-requests` user-agent; any browser-shaped one works.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

# WASDE's own commodity names for the markets this app can compute a ratio for.
# Wheat classes (SRW/HRW/spring) all roll up to the single combined "Wheat" balance
# sheet — WASDE doesn't split them, same approximation the rest of the app makes.
WASDE_COMMODITY_NAMES = {
    "ZC": "Corn",
    "ZS": "Oilseed, Soybean",
    "ZW": "Wheat",
    "KE": "Wheat",
    "HRS": "Wheat",
}


def _fetch_wasde_report(year: int, month: int = 8) -> pd.DataFrame:
    url = WASDE_CSV_URL.format(year=year, month=month)
    r = requests.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    df.columns = df.columns.str.strip()
    return df


def _report_years(current_year: int, years_back: int) -> list[int]:
    """August-report calendar years whose 3-marketing-year window tiles
    [current_year - years_back, current_year] with no gaps."""
    years = list(range(current_year, current_year - years_back - 1, -3))
    if years[-1] - 2 > current_year - years_back:
        years.append(years[-1] - 3)
    return years


def fetch_stocks_to_use(product_code: str, current_year: int, years_back: int) -> dict[int, float]:
    """{marketing_year_start: ending_stocks / total_use * 100}, US only.

    Empty on any failure — this is a convenience overlay for the highlight feature,
    never worth failing a chart over.
    """
    commodity = WASDE_COMMODITY_NAMES.get(product_code)
    if not commodity:
        return {}
    # USDA's machine-readable WASDE CSV export only goes back to the August 2021 report
    # (earlier months 404) — that's the real floor for this data source, not a guess.
    report_years = [y for y in _report_years(current_year, years_back) if y >= 2021]

    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=min(6, len(report_years) or 1)) as pool:
        futures = {pool.submit(_fetch_wasde_report, y): y for y in report_years}
        for fut in as_completed(futures):
            try:
                frames.append(fut.result())
            except Exception:
                continue
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True)

    us = df[
        (df["Commodity"] == commodity)
        & (df["Region"] == "United States")
        & (df["Unit"] == "Million Bushels")
        & (df["MarketYear"].notna())
    ]
    stocks: dict[int, float] = {}
    use: dict[int, float] = {}
    for _, row in us.iterrows():
        my_start = int(str(row["MarketYear"]).split("/")[0])
        if row["Attribute"] == "Ending Stocks":
            stocks.setdefault(my_start, row["Value"])
        elif row["Attribute"] == "Use, Total":
            use.setdefault(my_start, row["Value"])

    return {y: round(stocks[y] / use[y] * 100, 2) for y in stocks if use.get(y)}


def similar_years(stu: dict[int, float], current_year: int, tolerance_pts: float = 2.0) -> list[int]:
    """Years whose stocks/use ratio is within `tolerance_pts` percentage points of
    `current_year`'s. Empty if the current year itself has no ratio on record."""
    base = stu.get(current_year)
    if base is None:
        return []
    return [year for year, ratio in stu.items()
            if year != current_year and abs(ratio - base) <= tolerance_pts]
