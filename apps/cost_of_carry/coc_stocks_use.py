"""US stocks-to-use ratio by marketing year — used to flag "similar" prior years on the
seasonal charts' highlight feature.

Primary source is USDA FAS **PSD's bulk CSV download**, which carries the whole US
balance sheet back to 1960 (corn, wheat) / 1964 (soybeans) and forward to the current
projection, in one keyless request. PSD's REST endpoints are not usable — psdonline/api
404s, opendata/api 500s or rejects the key — but the published download works.

Fallback is USDA's monthly WASDE report CSV, which only reaches back to the August 2021
report (earlier months 404), i.e. marketing year 2019/20. Each WASDE CSV carries three
marketing years, so every 3rd August report tiles the window with no gaps.

The two agree closely; PSD revises history, so older years can differ from what the
WASDE of the day said.
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


# One keyless zip per PSD group; the grains file carries corn and wheat, oilseeds soybeans.
PSD_CSV_URLS = {
    "grains": "https://apps.fas.usda.gov/psdonline/downloads/psd_grains_pulses_csv.zip",
    "oilseeds": "https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip",
}

# product code -> (PSD group, PSD commodity description). Wheat classes share one
# balance sheet, as in WASDE_COMMODITY_NAMES.
PSD_COMMODITIES = {
    "ZC": ("grains", "Corn"),
    "ZW": ("grains", "Wheat"),
    "KE": ("grains", "Wheat"),
    "HRS": ("grains", "Wheat"),
    "ZS": ("oilseeds", "Oilseed, Soybean"),
}


def _fetch_psd_group(group: str) -> pd.DataFrame:
    import io
    import zipfile

    resp = requests.get(PSD_CSV_URLS[group], headers=_HEADERS, timeout=120)
    resp.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    return pd.read_csv(archive.open(archive.namelist()[0]), low_memory=False)


def fetch_psd_stocks_to_use(product_code: str) -> dict[int, float]:
    """{marketing_year_start: ending stocks / total use * 100} for the US, full history.

    Total use is PSD's Total Distribution less Ending Stocks — the same identity as
    WASDE's "Use, Total" line. Empty on any failure, so the caller can fall back."""
    entry = PSD_COMMODITIES.get(product_code)
    if not entry:
        return {}
    group, commodity = entry
    try:
        frame = _fetch_psd_group(group)
    except Exception:
        return {}

    rows = frame[
        (frame["Country_Name"].astype(str).str.strip() == "United States")
        & (frame["Commodity_Description"].astype(str).str.strip() == commodity)
        & (frame["Attribute_Description"].isin(["Ending Stocks", "Total Distribution"]))
    ]
    if not len(rows):
        return {}
    # PSD republishes each marketing year monthly; the latest month is the current view.
    latest = (rows.sort_values("Month")
                  .groupby(["Market_Year", "Attribute_Description"], as_index=False)
                  .last())
    wide = latest.pivot(index="Market_Year", columns="Attribute_Description", values="Value")
    if "Ending Stocks" not in wide or "Total Distribution" not in wide:
        return {}
    use = wide["Total Distribution"] - wide["Ending Stocks"]
    ratio = (wide["Ending Stocks"] / use * 100).where(use > 0).dropna()
    return {int(year): round(float(value), 2) for year, value in ratio.items()}


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

    PSD first (full history, one request); WASDE's CSV only if PSD is unreachable, in
    which case the answer is limited to marketing year 2019/20 forward. Empty on any
    failure — this is a convenience overlay for the highlight feature, never worth
    failing a chart over.
    """
    psd = fetch_psd_stocks_to_use(product_code)
    if psd:
        return psd
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
