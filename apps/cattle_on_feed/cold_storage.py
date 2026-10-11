"""
USDA Cold Storage — end-of-month stocks, the full published history.

Data comes from QuickStats, NOT from the monthly PDF at
`esmis.nal.usda.gov/.../cost{MM}{YY}.pdf`. The PDF is one month with two
comparison columns; QuickStats carries the same numbers back to **1917** for
beef, pork, lamb, turkey and cheese, and to 1915 for butter, which is what
makes a real MoM/YoY history possible at all. Read through the shared NASS cache
(usda-nass-etl jobs/cold_storage.py), so the view needs no NASS key and no new
secret.

USDA REVISES THE PRIOR MONTH, AND QUICKSTATS CARRIES THE REVISION. Each
release rewrites the month it reports and the one before it — visible in
`load_time`, where both Jun and Jul 2026 carry 2026-08-24. The revisions are
not always small: total beef for 31 Jul 2026 was published at 382,714 thousand
lb in the August report and restated to 398,285 in the September one, +4.1%,
essentially all of it in boneless. That single restatement moves July's YoY
from -3.8% to +0.1% — it crosses zero. So a figure on this page can change
after the fact, and when it does that is USDA revising, not a fetch bug. It
also means a page built on one archived PDF would go on showing a number USDA
no longer publishes, which the live query cannot do.

Two NASS spellings that cost a query if guessed:

- `freq_desc` is **POINT IN TIME**, not MONTHLY. Filtering on MONTHLY returns
  nothing at all, with a 400 that reads "bad request - invalid query" and means
  "no rows" (see the usda-nass-etl CLAUDE.md on that status code).
- `reference_period_desc` is **"END OF AUG"**, so the month is the LAST token.
  `app._month_num` already reads it that way and is reused here.

The series are NATIONAL only. NASS publishes regional cold storage in the
report's back half, but not into QuickStats, so there is no state or region
breakout to offer and none is implied anywhere on the page.

Vendored nowhere. Unlike `snowflake_db.py` and friends this name exists once in
the repo, so the by-name `sys.modules` collision the portal lives with does not
apply — same footing as `cof_recap`.
"""
import pandas as pd

from nass_cache_client import fetch_cached

# Label -> QuickStats short_desc. Order is the order of USDA's own Frozen Red
# Meat table, beef first, with the headline poultry and dairy lines after it so
# the view covers the report rather than just the cattle corner of it.
#
# TOTAL FROZEN RED MEAT IS COMPUTED, and is the one series here that USDA does
# not publish into QuickStats. It is beef + pork + veal + lamb & mutton, which
# is an identity and not an approximation: for 31 Aug 2026 those four sum to
# 862,128 thousand lb against USDA's printed total of 862,128. The report has
# no fifth red-meat bucket for the sum to miss. Its history starts 1944, the
# year veal starts, rather than 1917.
TOTAL_RED_MEAT = "Total red meat (computed)"

SERIES = {
    "Beef, total":            "BEEF, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Beef, boneless":         "BEEF, BONELESS, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Beef cuts (bone-in)":    "BEEF, BONE-IN, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Pork, total":            "PORK, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Pork bellies":           "PORK, BELLIES, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Pork hams":              "PORK, HAMS, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Pork trimmings":         "PORK, TRIMMINGS, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Veal":                   "VEAL, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Lamb & mutton":          "LAMB & MUTTON, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Chicken, total":         "CHICKENS, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Turkey, total":          "TURKEYS, COLD STORAGE, FROZEN - STOCKS, MEASURED IN LB",
    "Butter":                 "BUTTER, COLD STORAGE - STOCKS, MEASURED IN LB",
    "Cheese, natural":        "CHEESE, NATURAL, COLD STORAGE, CHILLED - STOCKS, MEASURED IN LB",
}

# The four that make up the computed total, in the report's own order.
RED_MEAT_PARTS = ["Beef, total", "Pork, total", "Veal", "Lamb & mutton"]

# First year each series carries, from the published history as of Sep 2026.
# Shown on the page so "as far back as you can" is a stated fact rather than
# something the reader has to infer from where the line starts.
FIRST_YEAR = {
    "Beef, total": 1917, "Beef, boneless": 1972, "Beef cuts (bone-in)": 1972,
    "Pork, total": 1917, "Pork bellies": 1957, "Pork hams": 1957,
    "Pork trimmings": 1961, "Veal": 1944, "Lamb & mutton": 1917,
    "Chicken, total": 1940, "Turkey, total": 1917,
    "Butter": 1915, "Cheese, natural": 1917,
    TOTAL_RED_MEAT: 1944,
}

REPORT_URL = "https://www.nass.usda.gov/Publications/Todays_Reports/reports/cost{mm:02d}{yy:02d}.pdf"


def report_url(year: int, month: int) -> str:
    """The released PDF for a given report month (the month AFTER the stocks date)."""
    return REPORT_URL.format(mm=month, yy=year % 100)


def fetch_series(short_desc: str, month_num) -> pd.DataFrame:
    """One series, whole history, as date/value. Empty frame on any failure.

    Read from the shared NASS cache: the ETL pulls each series NATIONAL, with no
    year bounds, so the cache key never goes stale and the params here must hash
    identically to jobs/cold_storage.py. The longest series is ~1,300 rows.
    `month_num` is app._month_num, passed in so the two pages cannot drift on how
    "END OF AUG" is read.
    """
    params = {
        "source_desc":    "SURVEY",
        "sector_desc":    "ANIMALS & PRODUCTS",
        "short_desc":     short_desc,
        "agg_level_desc": "NATIONAL",
    }
    try:
        payload = fetch_cached(params)
    except Exception:
        return pd.DataFrame(columns=["date", "value"])

    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        return pd.DataFrame(columns=["date", "value"])

    df = pd.DataFrame(data)
    df["value"] = pd.to_numeric(
        df["Value"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df["month"] = df["reference_period_desc"].apply(month_num)
    df = df.dropna(subset=["value", "month"]).copy()
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    df["date"] = pd.to_datetime(dict(year=df["year"], month=df["month"], day=1))
    # A revision arrives as a rewritten row, but keep last-wins anyway so a
    # duplicate from NASS's side can never double a month into the grid.
    return (df[["date", "value"]]
            .drop_duplicates("date", keep="last")
            .sort_values("date")
            .reset_index(drop=True))


def monthly_frame(df: pd.DataFrame) -> pd.DataFrame:
    """date / value / mom / yoy, on a gap-safe full monthly grid.

    The grid matters. Beef has six missing months in 110 years, and a plain
    `pct_change` on the raw rows would quietly compare across them — printing a
    13-month "MoM" as though it were a month. Reindexing to every month and
    then nulling any change whose base month is absent makes a gap show up as
    a blank, which is what it is.
    """
    if df.empty:
        return pd.DataFrame(columns=["date", "value", "mom", "yoy", "mom_abs", "yoy_abs"])

    grid = pd.DataFrame({"date": pd.date_range(df["date"].min(), df["date"].max(), freq="MS")})
    out = grid.merge(df, on="date", how="left")
    v = out["value"]
    # Explicit shift rather than pct_change: pct_change pads NaNs by default,
    # which would bridge exactly the gaps this grid exists to expose.
    out["mom_abs"] = v - v.shift(1)
    out["yoy_abs"] = v - v.shift(12)
    out["mom"] = (v / v.shift(1) - 1) * 100
    out["yoy"] = (v / v.shift(12) - 1) * 100
    return out


def combine(frames: dict) -> pd.DataFrame:
    """Sum several raw series into one, over the months ALL of them report.

    An inner join, not a sum-with-zeros: veal starts in 1944 and treating its
    absent years as zero would print a red-meat total that is really
    beef+pork+lamb and looks like a step change in 1944.
    """
    live = [f for f in frames.values() if not f.empty]
    if len(live) != len(frames) or not live:
        return pd.DataFrame(columns=["date", "value"])
    out = live[0]
    for f in live[1:]:
        out = out.merge(f, on="date", how="inner", suffixes=("", "_r"))
        out["value"] = out["value"] + out["value_r"]
        out = out[["date", "value"]]
    return out.sort_values("date").reset_index(drop=True)


def yoy_runs(frame: pd.DataFrame, rising: bool = True) -> list:
    """Unbroken runs of months whose YoY change has one sign, oldest first.

    YoY AND NOT MoM, DELIBERATELY. Cold storage beef is strongly seasonal —
    stocks build from September into December and draw down through August —
    so a month-on-month rise in October is the calendar, not the market, and a
    "months of increases" count built on MoM would say the same thing every
    autumn. Year-over-year is the one that answers whether beef is actually
    accumulating.

    Months with no YoY (a gap, or the first twelve of the series) end a run
    rather than being skipped over, so a run is always genuinely consecutive.
    """
    s = frame.dropna(subset=["yoy"]).reset_index(drop=True)
    if s.empty:
        return []
    runs, start = [], 0
    sign = s["yoy"] > 0
    # A missing month between two rows breaks the run even when the sign holds.
    contiguous = s["date"].diff().dt.days.fillna(0).le(31)
    for i in range(1, len(s) + 1):
        broken = i == len(s) or sign[i] != sign[start] or not contiguous[i]
        if broken:
            if bool(sign[start]) == rising:
                runs.append({
                    "start":  s["date"][start],
                    "end":    s["date"][i - 1],
                    "months": i - start,
                    "avg":    float(s["yoy"][start:i].mean()),
                    "peak":   float(s["yoy"][start:i].max() if rising else s["yoy"][start:i].min()),
                })
            start = i
    return runs


def latest(frame: pd.DataFrame) -> dict:
    """The newest reported month, with its two changes. Empty dict if none."""
    live = frame.dropna(subset=["value"])
    if live.empty:
        return {}
    row = live.iloc[-1]
    return {
        "date":    row["date"],
        "value":   float(row["value"]),
        "mom":     None if pd.isna(row["mom"]) else float(row["mom"]),
        "yoy":     None if pd.isna(row["yoy"]) else float(row["yoy"]),
        "mom_abs": None if pd.isna(row["mom_abs"]) else float(row["mom_abs"]),
        "yoy_abs": None if pd.isna(row["yoy_abs"]) else float(row["yoy_abs"]),
    }
