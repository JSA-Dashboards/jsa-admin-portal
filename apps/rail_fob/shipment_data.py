"""
USDA AMS Grain Rail Shipments — API Fetch & Transform
======================================================
Pulls live data from agtransport.usda.gov and returns a DataFrame with:

    Market Year   | string  | "2025/26"
    MY Week       | int     | 1-53 (week ending Friday, anchored to first
                  |         |  Friday on or after Sep 1 of the MY start year)
    MY Month      | int     | 1=Sep, 2=Oct, … 12=Aug
    Calendar Month| string  | "October"
    Railroad      | string  | BNSF / CN / CP / CPKC / CSX / KCS / NS / UP
    State         | string  | 2-letter abbreviation
    Destination   | string  | Western / Eastern / Central / Central/Canada / Central/Mexico
    Est Bushels   | int     | total railcars (field: "all") × 4,000

Marketing Year convention:
    Sep 1 → Aug 31.  The week whose ending Friday falls in that window
    belongs to that marketing year.

MY Week convention:
    Week 1 ends on the first Friday on or after Sep 1.
    Subsequent weeks count forward from there.
    Example: Sep 1 2014 = Monday → first Friday = Sep 5 → MY Week 1 ends Sep 5.
             Oct 17 2014 = Friday → delta = 42 days → MY Week 7.  ✓

KCS handling:
    KCS (Kansas City Southern) merged with CP in April 2023 to form CPKC.
    By default (KCS_MODE = 'keep') KCS stays as its own railroad in the data.
    Set KCS_MODE = 'cpkc'  to remap KCS → CPKC.
    Set KCS_MODE = 'drop'  to exclude KCS records entirely.

Destination mapping:
    Western       = BNSF, UP
    Eastern       = CSX, NS
    Central       = CN
    Central/Canada= CP, CPKC
    Central/Mexico= KCS
"""

import requests
import pandas as pd
from datetime import date, timedelta
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────
API_URL    = "https://agtransport.usda.gov/resource/27k8-utc2.json"
BUSHELS_PER_CAR = 4_000

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

VALID_STATES = {
    "AL","AR","AZ","CA","CO","CT","DE","FL","GA","IA","ID","IL","IN","KS","KY",
    "LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM",
    "NV","NY","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA",
    "WI","WV","WY",
}

# How to handle KCS records: 'cpkc' | 'keep' | 'drop'
# 'keep' = KCS stays as KCS pre-merger; CPKC is only post-April 2023 (correct)
KCS_MODE = "keep"

DESTINATION_MAP = {
    "BNSF": "Western",
    "UP":   "Western",
    "CSX":  "Eastern",
    "NS":   "Eastern",
    "CN":   "Central",
    "CP":   "Central/Canada",
    "CPKC": "Central/Canada",
    "KCS":  "Central/Mexico",
}

# ── Marketing Year helpers ─────────────────────────────────────────────────────
def marketing_year(dt: date) -> str:
    """Return marketing year string, e.g. '2025/26', for a given date."""
    if dt.month >= 9:
        return f"{dt.year}/{str(dt.year + 1)[2:]}"
    return f"{dt.year - 1}/{str(dt.year)[2:]}"


def my_week(dt: date) -> int:
    """
    Return MY Week number (1-based) for a given week-ending Friday date.
    Week 1 = week whose ending Friday is the first Friday on or after Sep 1
    of the marketing year's start year.
    """
    sep1_year = dt.year if dt.month >= 9 else dt.year - 1
    sep1 = date(sep1_year, 9, 1)

    # Nearest Friday on or after Sep 1  (weekday: Mon=0 … Fri=4)
    days_ahead = (4 - sep1.weekday()) % 7
    first_friday = sep1 + timedelta(days=days_ahead)

    delta = (dt - first_friday).days
    return max(1, delta // 7 + 1)


# ── API Fetch ─────────────────────────────────────────────────────────────────
def fetch_raw(app_token: Optional[str] = None) -> list:
    """
    Download rail records from the USDA AMS API.
    Fetches the last 8 marketing years — sufficient for 6-yr olympic avg
    plus current and prior year comparisons.
    Pass an app token to avoid throttling (free at agtransport.usda.gov).
    """
    # 8 MY's back = ~Sep of (current_year - 8).
    cutoff_year = date.today().year - 8
    cutoff = f"{cutoff_year}-09-01T00:00:00.000"

    headers = {"X-App-Token": app_token} if app_token else {}
    rows = []
    offset = 0
    limit  = 50_000

    while True:
        params = {
            "$limit":  limit,
            "$offset": offset,
            "$order":  "date ASC",
            "$where":  f"date >= '{cutoff}'",
        }
        resp = requests.get(API_URL, params=params, headers=headers, timeout=45)
        resp.raise_for_status()
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    return rows


# ── Transform ─────────────────────────────────────────────────────────────────
def transform(rows: list, kcs_mode: str = KCS_MODE) -> pd.DataFrame:
    """
    Convert raw API rows to a clean DataFrame.
    """
    df = pd.DataFrame(rows)

    # ── Date ──────────────────────────────────────────────────────────────────
    # 'date' = week-ending Friday (confirmed: week 41/2014 → Oct 17 2014 = Friday)
    df["_dt"] = pd.to_datetime(df["date"]).dt.date

    # ── Est Bushels ────────────────────────────────────────────────────────────
    df["Est Bushels"] = (
        pd.to_numeric(df["all"], errors="coerce").fillna(0).astype(int)
        * BUSHELS_PER_CAR
    )

    # ── Marketing Year & MY Week ───────────────────────────────────────────────
    df["Market Year"]    = df["_dt"].apply(marketing_year)
    df["MY Week"]        = df["_dt"].apply(my_week)

    # ── MY Month (marketing year month: Sep=1, Oct=2 … Aug=12) ───────────────
    df["MY Month"] = df["_dt"].apply(
        lambda d: d.month - 8 if d.month >= 9 else d.month + 4
    )

    # ── Calendar Month (name from date, not from the raw 'month' field) ────────
    df["Calendar Month"] = df["_dt"].apply(lambda d: MONTHS[d.month - 1])

    # ── Railroad ───────────────────────────────────────────────────────────────
    df["Railroad"] = df["railroad"].str.strip().str.upper()

    if kcs_mode == "cpkc":
        df["Railroad"] = df["Railroad"].replace("KCS", "CPKC")
    elif kcs_mode == "drop":
        df = df[df["Railroad"] != "KCS"]
    # else kcs_mode == 'keep' → leave KCS as-is

    # ── Destination ───────────────────────────────────────────────────────────
    df["Destination"] = df["Railroad"].map(DESTINATION_MAP).fillna("Other")

    # ── State ─────────────────────────────────────────────────────────────────
    df["State"] = df["state"].str.strip().str.upper()

    # KCS only reports a national total (state='TOTAL' in the API).
    # Remap to 'US' so it contributes to railroad-level totals but is
    # automatically excluded from any state-level analysis that filters
    # to VALID_STATES (2-letter abbreviations only).
    df.loc[df["Railroad"] == "KCS", "State"] = "US"

    # Keep rows that are either a valid US state OR the KCS national total
    df = df[df["State"].isin(VALID_STATES) | (df["State"] == "US")]

    # ── Output columns only ────────────────────────────────────────────────────
    return (
        df[["Market Year", "MY Week", "MY Month", "Calendar Month",
            "Railroad", "State", "Destination", "Est Bushels"]]
        .sort_values(["Market Year", "MY Week", "Railroad", "State"])
        .reset_index(drop=True)
    )


# ── Public entry point ────────────────────────────────────────────────────────
def load_usda_data(app_token: Optional[str] = None, kcs_mode: str = KCS_MODE) -> pd.DataFrame:
    """Fetch + transform in one call. Use this from Streamlit."""
    rows = fetch_raw(app_token)
    return transform(rows, kcs_mode=kcs_mode)


# ── Quick sanity check ────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Fetching USDA rail data …")
    df = load_usda_data()
    print(f"  Rows loaded : {len(df):,}")
    print(f"  Market years: {df['Market Year'].min()} to {df['Market Year'].max()}")
    print(f"  Railroads   : {sorted(df['Railroad'].unique())}")
    print(f"  Week range  : {df['MY Week'].min()}–{df['MY Week'].max()}")
    print()

    # Confirm the week-7 anchor
    sample = df[
        (df["Market Year"] == "2014/15") &
        (df["MY Week"] == 7) &
        (df["Railroad"] == "BNSF") &
        (df["State"] == "AR")
    ]
    print("Spot-check — BNSF / AR / 2014/15 / Week 7:")
    print(sample.to_string(index=False))
    print()
    print("First 5 rows:")
    print(df.head().to_string(index=False))
