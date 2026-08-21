"""
Livestock Inventory Dashboard — USDA NASS QuickStats
National · State · Agricultural District · County

John Stewart & Associates
Data source: USDA NASS QuickStats API (https://quickstats.nass.usda.gov)
"""

import io
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Theme ─────────────────────────────────────────────────────────────────────
DM_BG       = "#f6f8f7"
DM_SURFACE  = "#ffffff"
DM_SURFACE2 = "#eef3f0"
DM_BORDER   = "#d7e2dc"
DM_TEXT     = "#32373c"
DM_MUTED    = "#5f7267"
JPSI_GREEN  = "#16a34a"
POS         = "#16a34a"
NEG         = "#dc2626"

# Sequential scale for choropleths (dark-friendly)
SEQ_SCALE = [
    [0.00, "#12211b"],
    [0.20, "#16362a"],
    [0.40, "#1c5a3f"],
    [0.60, "#2f8f5b"],
    [0.80, "#57c07f"],
    [1.00, "#a7f3c7"],
]

# NASS API key comes from Streamlit secrets (Cloud) or an env var / local
# .streamlit/secrets.toml (dev). No key is committed to the repo.
try:
    API_KEY = st.secrets.get("NASS_API_KEY", "")
except Exception:
    API_KEY = ""
API_KEY = API_KEY or os.environ.get("NASS_API_KEY", "")

BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
COUNTY_GEOJSON_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"

# ── Series catalog ────────────────────────────────────────────────────────────
# Each entry -> the exact NASS short_desc plus display metadata.
# `period_pref` picks the default reference_period_desc when several exist.
# `levels`    restricts which geographic levels are offered (aquaculture is
#             national + state only; everything else supports county/ASD via
#             annual Survey and/or Census-year coverage).
# `note`      optional caption shown under the header for coverage caveats.
ALL_LEVELS = ["National", "State", "Agricultural District", "County"]
NAT_STATE  = ["National", "State"]
NATL_ONLY  = ["National"]
CENSUS_NOTE = ("Census-only series — figures are published only in Census of "
               "Agriculture years (…2012, 2017, 2022). Pick a Census year for "
               "state/district/county maps.")
SLAUGHTER_NOTE = ("Commercial slaughter is a flow (head slaughtered per year). "
                  "National & state annual totals are current and updated monthly.")

SERIES = {
    # ── Livestock ─────────────────────────────────────────────────────────────
    "All Cattle & Calves":  {"cat": "Livestock",   "short_desc": "CATTLE, INCL CALVES - INVENTORY",         "period_pref": "FIRST OF JAN", "icon": "🐄", "levels": ALL_LEVELS},
    "Beef Cows":            {"cat": "Livestock",   "short_desc": "CATTLE, COWS, BEEF - INVENTORY",          "period_pref": "FIRST OF JAN", "icon": "🐂", "levels": ALL_LEVELS},
    "Milk Cows":            {"cat": "Livestock",   "short_desc": "CATTLE, COWS, MILK - INVENTORY",          "period_pref": "FIRST OF JAN", "icon": "🥛", "levels": ALL_LEVELS},
    "All Cows":             {"cat": "Livestock",   "short_desc": "CATTLE, COWS - INVENTORY",                "period_pref": "FIRST OF JAN", "icon": "🐮", "levels": ALL_LEVELS},
    "Calves":               {"cat": "Livestock",   "short_desc": "CATTLE, CALVES - INVENTORY",              "period_pref": "FIRST OF JAN", "icon": "🐄", "levels": ALL_LEVELS},
    "Cattle on Feed":       {"cat": "Livestock",   "short_desc": "CATTLE, ON FEED - INVENTORY",             "period_pref": "FIRST OF JAN", "icon": "🌽", "levels": ALL_LEVELS},
    "Hogs":                 {"cat": "Livestock",   "short_desc": "HOGS - INVENTORY",                        "period_pref": "FIRST OF DEC", "icon": "🐖", "levels": ALL_LEVELS},
    "Hogs — Breeding":      {"cat": "Livestock",   "short_desc": "HOGS, BREEDING - INVENTORY",              "period_pref": "FIRST OF DEC", "icon": "🐗", "levels": ALL_LEVELS},
    "Hogs — Market":        {"cat": "Livestock",   "short_desc": "HOGS, MARKET - INVENTORY",                "period_pref": "FIRST OF DEC", "icon": "🐖", "levels": ALL_LEVELS},
    "Sheep & Lambs":        {"cat": "Livestock",   "short_desc": "SHEEP, INCL LAMBS - INVENTORY",           "period_pref": "FIRST OF JAN", "icon": "🐑", "levels": ALL_LEVELS},
    "Sheep — Breeding":     {"cat": "Livestock",   "short_desc": "SHEEP, INCL LAMBS, BREEDING - INVENTORY", "period_pref": "FIRST OF JAN", "icon": "🐏", "levels": ALL_LEVELS},
    "Goats — All":          {"cat": "Livestock",   "short_desc": "GOATS - INVENTORY",                       "period_pref": "FIRST OF JAN", "icon": "🐐", "levels": ALL_LEVELS},

    # ── Poultry ───────────────────────────────────────────────────────────────
    # Layers & pullets: monthly Survey (national/state) + Census (county/ASD).
    "Table-Egg Layers":     {"cat": "Poultry",     "short_desc": "CHICKENS, LAYERS - INVENTORY",            "period_pref": "FIRST OF DEC", "icon": "🥚", "levels": ALL_LEVELS},
    "Replacement Pullets":  {"cat": "Poultry",     "short_desc": "CHICKENS, PULLETS, REPLACEMENT - INVENTORY", "period_pref": "FIRST OF DEC", "icon": "🐤", "levels": ALL_LEVELS},
    # Census-only birds.
    "Broilers":             {"cat": "Poultry",     "short_desc": "CHICKENS, BROILERS - INVENTORY",          "period_pref": "FIRST OF DEC", "icon": "🐔", "levels": ALL_LEVELS, "note": CENSUS_NOTE},
    "Turkeys":              {"cat": "Poultry",     "short_desc": "TURKEYS - INVENTORY",                     "period_pref": "FIRST OF DEC", "icon": "🦃", "levels": ALL_LEVELS, "note": CENSUS_NOTE},
    "Ducks":                {"cat": "Poultry",     "short_desc": "DUCKS - INVENTORY",                       "period_pref": "FIRST OF DEC", "icon": "🦆", "levels": ALL_LEVELS, "note": CENSUS_NOTE},

    # ── Aquaculture ───────────────────────────────────────────────────────────
    # Catfish inventory: annual Survey (Jan 1 / Jul 1), national + catfish states.
    "Catfish — Foodsize":       {"cat": "Aquaculture", "short_desc": "FOOD FISH, CATFISH, FOODSIZE - INVENTORY",       "period_pref": "FIRST OF JAN", "icon": "🐟", "levels": NAT_STATE, "note": "Aquaculture inventory is reported nationally and for the major catfish states (AL, AR, CA, MS, NC, TX) — no county detail."},
    "Catfish — Stockers":       {"cat": "Aquaculture", "short_desc": "FOOD FISH, CATFISH, STOCKERS - INVENTORY",       "period_pref": "FIRST OF JAN", "icon": "🐟", "levels": NAT_STATE, "note": "Aquaculture inventory is national + major catfish states only — no county detail."},
    "Catfish — Broodstock":     {"cat": "Aquaculture", "short_desc": "FOOD FISH, CATFISH, BROODSTOCK - INVENTORY",     "period_pref": "FIRST OF JAN", "icon": "🐟", "levels": NAT_STATE, "note": "Aquaculture inventory is national + major catfish states only — no county detail."},
    "Catfish — Fingerlings & Fry": {"cat": "Aquaculture", "short_desc": "FOOD FISH, CATFISH, FINGERLINGS & FRY - INVENTORY", "period_pref": "FIRST OF JAN", "icon": "🐟", "levels": NAT_STATE, "note": "Aquaculture inventory is national + major catfish states only — no county detail."},

    # ── Dairy ─────────────────────────────────────────────────────────────────
    # Milk PRODUCTION (a flow, in lbs) — annual "YEAR" total + monthly; national
    # and state are current, county/district were discontinued after 2009.
    "Milk":                 {"cat": "Dairy", "short_desc": "MILK - PRODUCTION, MEASURED IN LB",            "period_pref": "YEAR", "icon": "🥛", "unit": "HEAD_LB", "measure": "Production", "levels": NAT_STATE, "note": "Milk production is a flow measured in pounds. National & state totals are current (annual, updated monthly); county/district figures were discontinued after 2009, so they're not offered here."},
    "Milk per Cow":         {"cat": "Dairy", "short_desc": "MILK - PRODUCTION, MEASURED IN LB / HEAD",     "period_pref": "YEAR", "icon": "🐄", "unit": "LB_PER_HEAD", "measure": "Production", "levels": NAT_STATE, "note": "Average annual milk produced per cow (lb/head), national & state."},

    # ── Slaughter (commercial, head — a flow) ─────────────────────────────────
    "Cattle":               {"cat": "Slaughter", "short_desc": "CATTLE, GE 500 LBS, SLAUGHTER, COMMERCIAL - SLAUGHTERED, MEASURED IN HEAD", "period_pref": "YEAR", "icon": "🐄", "measure": "Slaughter", "levels": NAT_STATE, "note": SLAUGHTER_NOTE},
    "Calves":               {"cat": "Slaughter", "short_desc": "CATTLE, CALVES, SLAUGHTER, COMMERCIAL - SLAUGHTERED, MEASURED IN HEAD",     "period_pref": "YEAR", "icon": "🐄", "measure": "Slaughter", "levels": NAT_STATE, "note": SLAUGHTER_NOTE},
    "Hogs":                 {"cat": "Slaughter", "short_desc": "HOGS, SLAUGHTER, COMMERCIAL - SLAUGHTERED, MEASURED IN HEAD",               "period_pref": "YEAR", "icon": "🐖", "measure": "Slaughter", "levels": NAT_STATE, "note": SLAUGHTER_NOTE},
    "Chickens (Young)":     {"cat": "Slaughter", "short_desc": "CHICKENS, YOUNG, SLAUGHTER, FI - SLAUGHTERED, MEASURED IN HEAD",             "period_pref": "YEAR", "icon": "🐔", "measure": "Slaughter", "levels": NAT_STATE, "note": "Young chickens (broilers), federally inspected slaughter — a flow. National & state annual totals, updated monthly."},
    "Turkeys (Young)":      {"cat": "Slaughter", "short_desc": "TURKEYS, YOUNG, SLAUGHTER, FI - SLAUGHTERED, MEASURED IN HEAD",              "period_pref": "YEAR", "icon": "🦃", "measure": "Slaughter", "levels": NAT_STATE, "note": "Young turkeys, federally inspected slaughter — a flow. National & state annual totals, updated monthly."},
    "Ducks":                {"cat": "Slaughter", "short_desc": "DUCKS, SLAUGHTER, FI - SLAUGHTERED, MEASURED IN HEAD",                      "period_pref": "YEAR", "icon": "🦆", "measure": "Slaughter", "levels": NATL_ONLY, "note": "Federally inspected duck slaughter — national only, updated monthly."},

    # ── Meat Production (ready-to-cook / live weight, lb — a flow) ─────────────
    "Broiler Meat":         {"cat": "Production", "short_desc": "CHICKENS, BROILERS - PRODUCTION, MEASURED IN LB",  "period_pref": "YEAR", "icon": "🐔", "unit": "HEAD_LB", "measure": "Production", "levels": NAT_STATE, "note": "Broiler production (live-weight pounds) — annual, national & state."},
    "Turkey Meat":          {"cat": "Production", "short_desc": "TURKEYS - PRODUCTION, MEASURED IN LB",             "period_pref": "YEAR", "icon": "🦃", "unit": "HEAD_LB", "measure": "Production", "levels": NAT_STATE, "note": "Turkey production (live-weight pounds) — annual, national & state."},
}

# Unit metadata: how each series' values are filtered, formatted and labelled.
UNITS = {
    "HEAD":        {"filter": "HEAD",       "word": "head",    "axis": "Head"},
    "HEAD_LB":     {"filter": "LB",         "word": "lb",      "axis": "Pounds"},
    "LB_PER_HEAD": {"filter": "LB / HEAD",  "word": "lb/cow",  "axis": "Lb per cow"},
}

CATEGORIES = ["Livestock", "Poultry", "Aquaculture", "Dairy", "Slaughter", "Production"]
FLOW_MEASURES = {"Production", "Slaughter"}  # use annual-only years for the map

# State FIPS -> USPS alpha (for USA-states choropleth we use alpha directly)
STATE_ABBR = {
    'ALABAMA':'AL','ALASKA':'AK','ARIZONA':'AZ','ARKANSAS':'AR','CALIFORNIA':'CA','COLORADO':'CO',
    'CONNECTICUT':'CT','DELAWARE':'DE','FLORIDA':'FL','GEORGIA':'GA','HAWAII':'HI','IDAHO':'ID',
    'ILLINOIS':'IL','INDIANA':'IN','IOWA':'IA','KANSAS':'KS','KENTUCKY':'KY','LOUISIANA':'LA',
    'MAINE':'ME','MARYLAND':'MD','MASSACHUSETTS':'MA','MICHIGAN':'MI','MINNESOTA':'MN','MISSISSIPPI':'MS',
    'MISSOURI':'MO','MONTANA':'MT','NEBRASKA':'NE','NEVADA':'NV','NEW HAMPSHIRE':'NH','NEW JERSEY':'NJ',
    'NEW MEXICO':'NM','NEW YORK':'NY','NORTH CAROLINA':'NC','NORTH DAKOTA':'ND','OHIO':'OH','OKLAHOMA':'OK',
    'OREGON':'OR','PENNSYLVANIA':'PA','RHODE ISLAND':'RI','SOUTH CAROLINA':'SC','SOUTH DAKOTA':'SD',
    'TENNESSEE':'TN','TEXAS':'TX','UTAH':'UT','VERMONT':'VT','VIRGINIA':'VA','WASHINGTON':'WA',
    'WEST VIRGINIA':'WV','WISCONSIN':'WI','WYOMING':'WY',
}

# st.set_page_config removed — the JSA Admin Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{ background-color:{DM_BG}; color:{DM_TEXT}; }}
  [data-testid="stSidebar"] {{ background-color:{DM_SURFACE}; border-right:1px solid {DM_BORDER}; }}
  [data-testid="stSidebar"] * {{ color:{DM_TEXT} !important; }}
  .metric-card {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-radius:8px;
    padding:14px 18px; text-align:center; height:100%; }}
  .metric-label {{ color:{DM_MUTED}; font-size:0.74rem; text-transform:uppercase;
    letter-spacing:0.06em; margin-bottom:4px; }}
  .metric-value {{ color:{DM_TEXT}; font-size:1.55rem; font-weight:700; line-height:1.1; }}
  .metric-sub  {{ color:{DM_MUTED}; font-size:0.78rem; margin-top:2px; }}
  .delta-pos {{ color:{POS}; font-size:0.85rem; }}
  .delta-neg {{ color:{NEG}; font-size:0.85rem; }}
  .delta-neu {{ color:{DM_MUTED}; font-size:0.85rem; }}
  .section-header {{ color:{DM_MUTED}; font-size:0.75rem; text-transform:uppercase;
    letter-spacing:0.1em; margin:8px 0 4px; }}
  div[data-testid="stDataFrame"] {{ background:{DM_SURFACE}; border-radius:8px; }}
  .stTabs [data-baseweb="tab-list"] {{ background:{DM_SURFACE}; border-radius:8px; }}
  .stTabs [data-baseweb="tab"] {{ color:{DM_MUTED}; }}
  .stTabs [aria-selected="true"] {{ color:{JPSI_GREEN} !important; }}
  h1,h2,h3 {{ color:{DM_TEXT}; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.7rem;
    border:1px solid {DM_BORDER}; color:{DM_MUTED}; margin-left:6px; }}
</style>
""", unsafe_allow_html=True)

if not API_KEY:
    st.error(
        "**NASS_API_KEY is not set.** Add it under *Settings → Secrets* on "
        "Streamlit Cloud, or create a local `.streamlit/secrets.toml` with "
        "`NASS_API_KEY = \"your-key\"`. Get a free key at "
        "https://quickstats.nass.usda.gov/api."
    )
    st.stop()


# ── Data layer ────────────────────────────────────────────────────────────────

def _nass_request(params: dict) -> dict:
    params = {**params, "key": API_KEY, "format": "JSON"}
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                return {}
    return {}


def _clean(df: pd.DataFrame, unit: str = "HEAD") -> pd.DataFrame:
    """Parse Value, drop suppressed/aggregate rows, keep TOTAL domain + the
    series' unit (HEAD for head counts, LB / 'LB / HEAD' for milk)."""
    if df.empty:
        return df
    if "domain_desc" in df.columns:
        df = df[df["domain_desc"].str.upper() == "TOTAL"]
    if "unit_desc" in df.columns:
        df = df[df["unit_desc"].str.upper().str.strip() == unit.upper()]
    df = df.copy()
    df["Value"] = pd.to_numeric(
        df["Value"].astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["Value", "year"])
    return df


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_national(short_desc: str, unit: str = "HEAD") -> pd.DataFrame:
    payload = _nass_request({"short_desc": short_desc, "agg_level_desc": "NATIONAL"})
    df = _clean(pd.DataFrame(payload.get("data", [])), unit)
    if df.empty:
        return df
    keep = ["year", "Value", "reference_period_desc", "source_desc", "freq_desc"]
    return df[[c for c in keep if c in df.columns]].sort_values("year")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_state_year(short_desc: str, year: int, unit: str = "HEAD") -> pd.DataFrame:
    """All states for a single year (for the US choropleth + rankings)."""
    payload = _nass_request({
        "short_desc": short_desc, "agg_level_desc": "STATE", "year": year,
    })
    df = _clean(pd.DataFrame(payload.get("data", [])), unit)
    if df.empty:
        return df
    keep = ["year", "state_alpha", "state_name", "Value",
            "reference_period_desc", "source_desc"]
    df = df[[c for c in keep if c in df.columns]]
    return df


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_state_series(short_desc: str, state_alpha: str, unit: str = "HEAD") -> pd.DataFrame:
    """Full time series for one state."""
    payload = _nass_request({
        "short_desc": short_desc, "agg_level_desc": "STATE", "state_alpha": state_alpha,
    })
    df = _clean(pd.DataFrame(payload.get("data", [])), unit)
    if df.empty:
        return df
    keep = ["year", "state_alpha", "Value", "reference_period_desc", "source_desc"]
    return df[[c for c in keep if c in df.columns]].sort_values("year")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_county_year(short_desc: str, state_alpha: str, year: int) -> pd.DataFrame:
    """All counties in one state for a single year. Merges SURVEY + CENSUS,
    preferring SURVEY when a county appears in both."""
    payload = _nass_request({
        "short_desc": short_desc, "agg_level_desc": "COUNTY",
        "state_alpha": state_alpha, "year": year,
    })
    df = _clean(pd.DataFrame(payload.get("data", [])))
    if df.empty:
        return df
    for c in ["county_ansi", "state_fips_code", "asd_code"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    # drop combined-county / district / state aggregate rows
    df = df[~df["county_ansi"].isin(["998", "999", "000", "", "nan"])]
    df = df.dropna(subset=["county_ansi"])
    df["fips"] = df["state_fips_code"].str.zfill(2) + df["county_ansi"].str.zfill(3)
    # prefer SURVEY over CENSUS for duplicated fips
    if "source_desc" in df.columns:
        df["_pri"] = (df["source_desc"].str.upper() == "SURVEY").astype(int)
        df = df.sort_values("_pri", ascending=False).drop_duplicates("fips").drop(columns="_pri")
    keep = ["fips", "state_alpha", "county_name", "asd_desc", "asd_code",
            "Value", "source_desc", "year"]
    return df[[c for c in keep if c in df.columns]]


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_county_series(short_desc: str, state_alpha: str) -> pd.DataFrame:
    """Full time series for every county in a state (for county trends)."""
    payload = _nass_request({
        "short_desc": short_desc, "agg_level_desc": "COUNTY", "state_alpha": state_alpha,
    })
    df = _clean(pd.DataFrame(payload.get("data", [])))
    if df.empty:
        return df
    for c in ["county_ansi", "state_fips_code"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    df = df[~df["county_ansi"].isin(["998", "999", "000", "", "nan"])]
    df["fips"] = df["state_fips_code"].str.zfill(2) + df["county_ansi"].str.zfill(3)
    keep = ["fips", "county_name", "asd_desc", "year", "Value", "source_desc",
            "reference_period_desc"]
    return df[[c for c in keep if c in df.columns]].sort_values("year")


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def load_county_geojson() -> dict:
    with urllib.request.urlopen(COUNTY_GEOJSON_URL, timeout=60) as r:
        return json.load(r)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def available_years(short_desc: str, agg_level: str, freq: str = "") -> list:
    params = {"key": API_KEY, "param": "year",
              "short_desc": short_desc, "agg_level_desc": agg_level}
    if freq:  # e.g. ANNUAL — for flow (production) series, exclude partial years
        params["freq_desc"] = freq
    url = ("https://quickstats.nass.usda.gov/api/get_param_values/?"
           + urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(url, timeout=45) as r:
            yrs = json.load(r).get("year", [])
        return sorted({int(y) for y in yrs}, reverse=True)
    except Exception:
        return []


def pick_period(df: pd.DataFrame, pref: str) -> pd.DataFrame:
    """When a series carries several reference periods, keep the preferred one
    (falling back to the most common)."""
    if "reference_period_desc" not in df.columns or df.empty:
        return df
    periods = df["reference_period_desc"].dropna().unique().tolist()
    if len(periods) <= 1:
        return df
    if pref in periods:
        chosen = pref
    else:
        chosen = df["reference_period_desc"].value_counts().idxmax()
    return df[df["reference_period_desc"] == chosen]


# ── Formatting / chart helpers ────────────────────────────────────────────────

def fmt_head(v) -> str:
    """Unit-agnostic magnitude formatter (works for head counts and pounds)."""
    if pd.isna(v):
        return "N/A"
    v = float(v)
    if abs(v) >= 1_000_000_000:
        return f"{v/1_000_000_000:.2f}B"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"{v/1_000:.0f}K"
    return f"{v:,.0f}"


def delta_html(cur, prev, pct=True, word="head") -> str:
    if pd.isna(cur) or pd.isna(prev) or prev == 0:
        return '<div class="delta-neu">— vs prior</div>'
    diff = cur - prev
    pctv = diff / prev * 100
    cls = "delta-pos" if diff >= 0 else "delta-neg"
    sign = "+" if diff >= 0 else ""
    tail = f"{sign}{pctv:.1f}% YoY" if pct else f"{sign}{fmt_head(diff)} YoY"
    return f'<div class="{cls}">{sign}{fmt_head(diff)} {word} · {tail}</div>'


def metric_card(label, value, sub_html="") -> str:
    return (f'<div class="metric-card"><div class="metric-label">{label}</div>'
            f'<div class="metric-value">{value}</div>{sub_html}</div>')


AXIS = dict(gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True, zeroline=False)


def apply_layout(fig, title="", height=420, y_title="Head"):
    fig.update_layout(
        title=dict(text=title, font=dict(color=DM_TEXT, size=14), x=0),
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=DM_BORDER, borderwidth=0),
        margin=dict(l=60, r=20, t=45, b=40), hovermode="x unified", height=height,
    )
    fig.update_xaxes(**AXIS)
    fig.update_yaxes(**AXIS, title_text=y_title)


def map_layout(fig, title="", height=520):
    fig.update_layout(
        title=dict(text=title, font=dict(color=DM_TEXT, size=14), x=0),
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11),
        margin=dict(l=0, r=0, t=45, b=0), height=height,
        geo=dict(bgcolor=DM_SURFACE2, lakecolor=DM_SURFACE2, landcolor=DM_SURFACE,
                 subunitcolor=DM_BORDER, showlakes=False),
    )


def to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    return buf.getvalue()


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.markdown("## 🐄 Animal Inventory")
st.sidebar.markdown(
    f'<span style="color:{DM_MUTED};font-size:0.72rem;">Inventory · Milk · Slaughter · Production</span>',
    unsafe_allow_html=True)
st.sidebar.markdown(
    f'<span style="color:{DM_MUTED};font-size:0.75rem;">USDA NASS QuickStats</span>',
    unsafe_allow_html=True)
st.sidebar.divider()

category = st.sidebar.radio("Category", CATEGORIES, index=0, horizontal=True)
cat_series = [name for name, s in SERIES.items() if s["cat"] == category]
series_name = st.sidebar.selectbox("Series", cat_series, index=0)
series = SERIES[series_name]
short_desc = series["short_desc"]

# Unit + measure metadata (head counts vs milk pounds; inventory vs production)
unit_meta = UNITS[series.get("unit", "HEAD")]
UNIT   = unit_meta["filter"]   # unit_desc filter passed to fetch/_clean
UWORD  = unit_meta["word"]     # lower-case word in hover text ("head"/"lb")
UAXIS  = unit_meta["axis"]     # axis / colorbar / column label
MEASURE = series.get("measure", "Inventory")

allowed_levels = series.get("levels", ALL_LEVELS)
default_level = "State" if "State" in allowed_levels else allowed_levels[0]
level = st.sidebar.radio(
    "Geographic level",
    allowed_levels,
    index=allowed_levels.index(default_level),
)

STATE_NAMES = sorted(STATE_ABBR.keys())
sel_state_name = None
sel_state_alpha = None
if level in ("County", "Agricultural District"):
    sel_state_name = st.sidebar.selectbox(
        "State", [s.title() for s in STATE_NAMES],
        index=[s.title() for s in STATE_NAMES].index("Texas"),
    )
    sel_state_alpha = STATE_ABBR[sel_state_name.upper()]

# Year selector — options depend on level
agg_for_years = {
    "National": "NATIONAL", "State": "STATE",
    "Agricultural District": "COUNTY", "County": "COUNTY",
}[level]
# Flows (production/slaughter): only offer years with a complete annual total.
yr_freq = "ANNUAL" if MEASURE in FLOW_MEASURES else ""
yr_opts = available_years(short_desc, agg_for_years, yr_freq)
if not yr_opts:
    yr_opts = list(range(datetime.now().year, 1996, -1))
sel_year = None
if level in ("State", "Agricultural District", "County"):
    sel_year = st.sidebar.selectbox("Year (map & rankings)", yr_opts, index=0)

st.sidebar.divider()
st.sidebar.markdown(
    f'<div class="section-header">About</div>'
    f'<p style="color:{DM_MUTED};font-size:0.72rem;line-height:1.4;">'
    f'<b>Livestock</b> & layer/pullet <b>poultry</b>: NASS Survey (national/state) '
    f'plus Census county coverage (2017, 2022). <b>Broilers, turkeys, ducks</b>: '
    f'Census years only. <b>Aquaculture</b> (catfish): annual Survey, national + '
    f'catfish states. <b>Dairy</b> (milk production, lbs): annual/monthly Survey, '
    f'national + state. District totals are aggregated up from county estimates.</p>',
    unsafe_allow_html=True)


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<h1 style="margin-bottom:0">{series['icon']} {series_name} — {MEASURE}</h1>
<p style="color:{DM_MUTED};margin-top:4px">
  {short_desc} &nbsp;·&nbsp; USDA NASS QuickStats
  <span class="badge">{category}</span>
  <span class="badge">{level}</span>
</p>
""", unsafe_allow_html=True)
if series.get("note"):
    st.markdown(
        f'<p style="color:{DM_MUTED};font-size:0.78rem;background:{DM_SURFACE};'
        f'border:1px solid {DM_BORDER};border-radius:6px;padding:8px 12px;margin:4px 0;">'
        f'ℹ️ {series["note"]}</p>', unsafe_allow_html=True)
st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# NATIONAL
# ══════════════════════════════════════════════════════════════════════════════
if level == "National":
    with st.spinner("Loading national series…"):
        nat = pick_period(fetch_national(short_desc, UNIT), series["period_pref"])
    if nat.empty:
        st.error("No national data returned for this series.")
        st.stop()
    nat = nat.groupby("year", as_index=False)["Value"].sum().sort_values("year")

    latest = nat.iloc[-1]
    prev = nat.iloc[-2] if len(nat) > 1 else None
    yr5 = nat[nat["year"] >= latest["year"] - 5]
    peak = nat.loc[nat["Value"].idxmax()]
    trough = nat.loc[nat["Value"].idxmin()]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        sub = delta_html(latest["Value"], prev["Value"], word=UWORD) if prev is not None else ""
        st.markdown(metric_card(f"{int(latest['year'])} {MEASURE}",
                                fmt_head(latest["Value"]), sub), unsafe_allow_html=True)
    with c2:
        avg5 = yr5["Value"].mean()
        vs = delta_html(latest["Value"], avg5, word=UWORD)
        st.markdown(metric_card("vs 5-Yr Avg", fmt_head(avg5), vs), unsafe_allow_html=True)
    with c3:
        st.markdown(metric_card("Period High",
                    fmt_head(peak["Value"]),
                    f'<div class="metric-sub">{int(peak["year"])}</div>'),
                    unsafe_allow_html=True)
    with c4:
        st.markdown(metric_card("Period Low",
                    fmt_head(trough["Value"]),
                    f'<div class="metric-sub">{int(trough["year"])}</div>'),
                    unsafe_allow_html=True)

    st.markdown("")
    t_trend, t_yoy, t_data = st.tabs(["📈 Long-Run Trend", "📊 Year-over-Year Change", "📋 Data"])

    with t_trend:
        rng = st.slider("Year range", int(nat["year"].min()), int(nat["year"].max()),
                        (max(int(nat["year"].min()), 1990), int(nat["year"].max())))
        d = nat[(nat["year"] >= rng[0]) & (nat["year"] <= rng[1])]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=d["year"], y=d["Value"], mode="lines+markers",
                      line=dict(color=JPSI_GREEN, width=2.5),
                      marker=dict(size=4),
                      hovertemplate="%{{x}}: %{{y:,.0f}} {UWORD}<extra></extra>".format(UWORD=UWORD)))
        apply_layout(fig, f"U.S. {series_name} {MEASURE}", 440, UAXIS)
        st.plotly_chart(fig, use_container_width=True)

    with t_yoy:
        d = nat.copy()
        d["yoy"] = d["Value"].diff()
        d = d.dropna(subset=["yoy"])
        d = d[d["year"] >= d["year"].max() - 25]
        fig = go.Figure(go.Bar(
            x=d["year"], y=d["yoy"],
            marker_color=[POS if v >= 0 else NEG for v in d["yoy"]],
            hovertemplate="%{{x}}: %{{y:+,.0f}} {UWORD}<extra></extra>".format(UWORD=UWORD)))
        fig.add_hline(y=0, line_color=DM_BORDER)
        apply_layout(fig, f"Annual Change in {MEASURE}", 400, f"Δ {UAXIS}")
        st.plotly_chart(fig, use_container_width=True)

    with t_data:
        out = nat.copy()
        out.columns = ["Year", UAXIS]
        st.dataframe(out.sort_values("Year", ascending=False), use_container_width=True,
                     height=430,
                     column_config={UAXIS: st.column_config.NumberColumn(format="%d")})
        st.download_button("⬇ Download Excel", to_excel(out),
                           file_name=f"national_{short_desc[:20]}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════════════════════════════════════════════════
# STATE
# ══════════════════════════════════════════════════════════════════════════════
elif level == "State":
    with st.spinner(f"Loading state data for {sel_year}…"):
        sdf = pick_period(fetch_state_year(short_desc, sel_year, UNIT), series["period_pref"])
    if sdf.empty:
        st.warning(f"No state-level data for {series_name} in {sel_year}.")
        st.stop()
    sdf = (sdf.groupby(["state_alpha"], as_index=False)
              .agg(Value=("Value", "sum"),
                   state_name=("state_name", "first") if "state_name" in sdf.columns else ("state_alpha", "first")))
    sdf = sdf[sdf["state_alpha"].isin(STATE_ABBR.values())]

    total = sdf["Value"].sum()
    top = sdf.loc[sdf["Value"].idxmax()]
    n_states = len(sdf)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(metric_card(f"{sel_year} Reported Total", fmt_head(total),
                    f'<div class="metric-sub">{n_states} states reporting</div>'),
                    unsafe_allow_html=True)
    with c2:
        st.markdown(metric_card("Top State", fmt_head(top["Value"]),
                    f'<div class="metric-sub">{top.get("state_name", top["state_alpha"])}</div>'),
                    unsafe_allow_html=True)
    with c3:
        top5 = sdf.nlargest(5, "Value")["Value"].sum()
        st.markdown(metric_card("Top-5 Share",
                    f"{top5/total*100:.0f}%",
                    f'<div class="metric-sub">of reported {MEASURE.lower()}</div>'),
                    unsafe_allow_html=True)
    with c4:
        st.markdown(metric_card("Median State", fmt_head(sdf["Value"].median()),
                    '<div class="metric-sub">reporting states</div>'),
                    unsafe_allow_html=True)

    st.markdown("")
    t_map, t_rank, t_trend, t_data = st.tabs(
        ["🗺️ State Map", "🏆 Rankings", "📈 State Trend", "📋 Data"])

    with t_map:
        fig = go.Figure(go.Choropleth(
            locations=sdf["state_alpha"], locationmode="USA-states",
            z=sdf["Value"], colorscale=SEQ_SCALE,
            marker_line_color=DM_BORDER, marker_line_width=0.5,
            colorbar=dict(title=UAXIS, outlinewidth=0, tickfont=dict(color=DM_TEXT)),
            text=sdf.get("state_name", sdf["state_alpha"]),
            hovertemplate="%{{text}}: %{{z:,.0f}} {UWORD}<extra></extra>".format(UWORD=UWORD),
        ))
        fig.update_geos(scope="usa", bgcolor=DM_SURFACE2, lakecolor=DM_SURFACE2,
                        landcolor=DM_SURFACE, subunitcolor=DM_BORDER)
        map_layout(fig, f"{series_name} {MEASURE} by State — {sel_year}", 540)
        st.plotly_chart(fig, use_container_width=True)

    with t_rank:
        rank = sdf.sort_values("Value", ascending=True).tail(25)
        fig = go.Figure(go.Bar(
            x=rank["Value"], y=rank.get("state_name", rank["state_alpha"]),
            orientation="h", marker_color=JPSI_GREEN,
            hovertemplate="%{{y}}: %{{x:,.0f}} {UWORD}<extra></extra>".format(UWORD=UWORD)))
        apply_layout(fig, f"Top States — {sel_year}", max(400, 22*len(rank)), "")
        fig.update_xaxes(title_text=UAXIS)
        fig.update_yaxes(title_text="", showgrid=False)
        st.plotly_chart(fig, use_container_width=True)

    with t_trend:
        pick = st.selectbox("State", sorted(sdf.get("state_name", sdf["state_alpha"]).tolist()))
        alpha = STATE_ABBR.get(str(pick).upper(),
                               sdf.loc[sdf.get("state_name", sdf["state_alpha"]) == pick, "state_alpha"].iloc[0]
                               if not sdf.empty else pick)
        ss = pick_period(fetch_state_series(short_desc, alpha, UNIT), series["period_pref"])
        if ss.empty:
            st.info("No time series for this state.")
        else:
            ss = ss.groupby("year", as_index=False)["Value"].sum()
            fig = go.Figure(go.Scatter(
                x=ss["year"], y=ss["Value"], mode="lines+markers",
                line=dict(color=JPSI_GREEN, width=2.5), marker=dict(size=4),
                hovertemplate="%{{x}}: %{{y:,.0f}} {UWORD}<extra></extra>".format(UWORD=UWORD)))
            apply_layout(fig, f"{pick} — {series_name} {MEASURE}", 430, UAXIS)
            st.plotly_chart(fig, use_container_width=True)

    with t_data:
        out = sdf.copy()
        cols = {"state_alpha": "State", "state_name": "State Name", "Value": UAXIS}
        out = out.rename(columns=cols)
        disp = [c for c in ["State Name", "State", UAXIS] if c in out.columns]
        out = out[disp].sort_values(UAXIS, ascending=False)
        out.insert(0, "Rank", range(1, len(out) + 1))
        st.dataframe(out, use_container_width=True, height=460, hide_index=True,
                     column_config={UAXIS: st.column_config.NumberColumn(format="%d")})
        st.download_button("⬇ Download Excel", to_excel(out),
                           file_name=f"state_{sel_year}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════════════════════════════════════════════════
# COUNTY
# ══════════════════════════════════════════════════════════════════════════════
elif level == "County":
    with st.spinner(f"Loading {sel_state_name} counties for {sel_year}…"):
        cdf = fetch_county_year(short_desc, sel_state_alpha, sel_year)
    if cdf.empty:
        st.warning(
            f"No county data for {series_name} in {sel_state_name} ({sel_year}). "
            f"County estimates are published for major livestock states annually and "
            f"for all counties in Census years (2017, 2022). Try a Census year.")
        st.stop()

    geo = load_county_geojson()
    src_mix = cdf["source_desc"].value_counts().to_dict() if "source_desc" in cdf.columns else {}
    total = cdf["Value"].sum()
    top = cdf.loc[cdf["Value"].idxmax()]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(metric_card(f"{sel_state_name} Total ({sel_year})", fmt_head(total),
                    f'<div class="metric-sub">{len(cdf)} counties reported</div>'),
                    unsafe_allow_html=True)
    with c2:
        st.markdown(metric_card("Top County", fmt_head(top["Value"]),
                    f'<div class="metric-sub">{str(top["county_name"]).title()}</div>'),
                    unsafe_allow_html=True)
    with c3:
        top10 = cdf.nlargest(10, "Value")["Value"].sum()
        st.markdown(metric_card("Top-10 Counties",
                    f"{top10/total*100:.0f}%",
                    '<div class="metric-sub">of state inventory</div>'),
                    unsafe_allow_html=True)
    with c4:
        src_txt = " · ".join(f"{k.title()}:{v}" for k, v in src_mix.items()) or "—"
        st.markdown(metric_card("Data Source", src_txt.split(" · ")[0].split(":")[0] or "—",
                    f'<div class="metric-sub">{src_txt}</div>'),
                    unsafe_allow_html=True)

    st.markdown("")
    t_map, t_rank, t_trend, t_data = st.tabs(
        ["🗺️ County Map", "🏆 Rankings", "📈 County Trend", "📋 Data"])

    with t_map:
        fig = go.Figure(go.Choropleth(
            geojson=geo, locations=cdf["fips"], featureidkey="id",
            z=cdf["Value"], colorscale=SEQ_SCALE,
            marker_line_color=DM_BORDER, marker_line_width=0.4,
            colorbar=dict(title="Head", outlinewidth=0, tickfont=dict(color=DM_TEXT)),
            text=cdf["county_name"].str.title(),
            hovertemplate="%{text}: %{z:,.0f} head<extra></extra>",
        ))
        fig.update_geos(fitbounds="locations", visible=False,
                        bgcolor=DM_SURFACE2, subunitcolor=DM_BORDER)
        map_layout(fig, f"{series_name} — {sel_state_name} Counties ({sel_year})", 560)
        st.plotly_chart(fig, use_container_width=True)

    with t_rank:
        n = st.slider("Show top N counties", 5, 40, 20)
        rank = cdf.sort_values("Value", ascending=True).tail(n)
        fig = go.Figure(go.Bar(
            x=rank["Value"], y=rank["county_name"].str.title(),
            orientation="h", marker_color=JPSI_GREEN,
            hovertemplate="%{y}: %{x:,.0f} head<extra></extra>"))
        apply_layout(fig, f"Top {n} Counties — {sel_state_name} {sel_year}",
                     max(400, 22*n), "")
        fig.update_xaxes(title_text="Head")
        fig.update_yaxes(title_text="", showgrid=False)
        st.plotly_chart(fig, use_container_width=True)

    with t_trend:
        county_pick = st.selectbox("County", sorted(cdf["county_name"].str.title().unique()))
        allc = pick_period(fetch_county_series(short_desc, sel_state_alpha), series["period_pref"])
        cs = allc[allc["county_name"].str.title() == county_pick]
        if cs.empty:
            st.info("No time series for this county.")
        else:
            cs = cs.groupby("year", as_index=False)["Value"].sum()
            fig = go.Figure(go.Scatter(
                x=cs["year"], y=cs["Value"], mode="lines+markers",
                line=dict(color=JPSI_GREEN, width=2.5), marker=dict(size=5),
                hovertemplate="%{x}: %{y:,.0f} head<extra></extra>"))
            apply_layout(fig, f"{county_pick} County — {series_name}", 430, "Head")
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Gaps indicate years not separately published for this county "
                       "(Survey coverage varies; Census years fill in all counties).")

    with t_data:
        out = cdf.copy()
        out["county_name"] = out["county_name"].str.title()
        ren = {"county_name": "County", "asd_desc": "Ag District",
               "Value": "Head", "source_desc": "Source", "fips": "FIPS"}
        out = out.rename(columns=ren)
        disp = [c for c in ["County", "Ag District", "Head", "Source", "FIPS"] if c in out.columns]
        out = out[disp].sort_values("Head", ascending=False)
        out.insert(0, "Rank", range(1, len(out) + 1))
        st.dataframe(out, use_container_width=True, height=470, hide_index=True,
                     column_config={"Head": st.column_config.NumberColumn(format="%d")})
        st.download_button("⬇ Download Excel", to_excel(out),
                           file_name=f"county_{sel_state_alpha}_{sel_year}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════════════════════════════════════════════════
# AGRICULTURAL DISTRICT  (aggregated from counties)
# ══════════════════════════════════════════════════════════════════════════════
elif level == "Agricultural District":
    with st.spinner(f"Aggregating {sel_state_name} counties into districts ({sel_year})…"):
        cdf = fetch_county_year(short_desc, sel_state_alpha, sel_year)
    if cdf.empty or "asd_desc" not in cdf.columns:
        st.warning(
            f"No county-level detail to build districts for {series_name} in "
            f"{sel_state_name} ({sel_year}). Ag-district totals require county "
            f"estimates — try a Census year (2017, 2022) or a major livestock state.")
        st.stop()

    cdf = cdf.dropna(subset=["asd_desc"])
    cdf = cdf[cdf["asd_desc"].astype(str).str.strip() != ""]
    asd = (cdf.groupby(["asd_code", "asd_desc"], as_index=False)
              .agg(Value=("Value", "sum"), n_counties=("fips", "nunique")))
    asd = asd.sort_values("Value", ascending=False)
    if asd.empty:
        st.warning("No agricultural-district aggregates could be formed.")
        st.stop()

    geo = load_county_geojson()
    # map each county to its district value so the choropleth shows district blocks
    dist_val = asd.set_index("asd_desc")["Value"].to_dict()
    cdf = cdf.copy()
    cdf["district_value"] = cdf["asd_desc"].map(dist_val)

    total = asd["Value"].sum()
    top = asd.iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(metric_card(f"{sel_state_name} Total ({sel_year})", fmt_head(total),
                    f'<div class="metric-sub">{len(asd)} districts</div>'),
                    unsafe_allow_html=True)
    with c2:
        st.markdown(metric_card("Top District", fmt_head(top["Value"]),
                    f'<div class="metric-sub">{str(top["asd_desc"]).title()}</div>'),
                    unsafe_allow_html=True)
    with c3:
        st.markdown(metric_card("Top District Share",
                    f"{top['Value']/total*100:.0f}%",
                    '<div class="metric-sub">of state inventory</div>'),
                    unsafe_allow_html=True)
    with c4:
        st.markdown(metric_card("Counties Rolled Up", f"{int(asd['n_counties'].sum())}",
                    '<div class="metric-sub">into districts</div>'),
                    unsafe_allow_html=True)

    st.markdown("")
    t_map, t_rank, t_data = st.tabs(["🗺️ District Map", "🏆 District Rankings", "📋 Data"])

    with t_map:
        fig = go.Figure(go.Choropleth(
            geojson=geo, locations=cdf["fips"], featureidkey="id",
            z=cdf["district_value"], colorscale=SEQ_SCALE,
            marker_line_color=DM_BORDER, marker_line_width=0.3,
            colorbar=dict(title="Head", outlinewidth=0, tickfont=dict(color=DM_TEXT)),
            text=cdf["asd_desc"].str.title(),
            customdata=cdf["county_name"].str.title(),
            hovertemplate="<b>%{text}</b> district<br>%{customdata} Co.<br>"
                          "District total: %{z:,.0f} head<extra></extra>",
        ))
        fig.update_geos(fitbounds="locations", visible=False,
                        bgcolor=DM_SURFACE2, subunitcolor=DM_BORDER)
        map_layout(fig, f"{series_name} by Ag District — {sel_state_name} ({sel_year})", 560)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Counties are shaded by their agricultural-district total, so each "
                   "district reads as one block. Districts are USDA NASS crop-reporting districts.")

    with t_rank:
        rank = asd.sort_values("Value", ascending=True)
        fig = go.Figure(go.Bar(
            x=rank["Value"], y=rank["asd_desc"].str.title(),
            orientation="h", marker_color=JPSI_GREEN,
            customdata=rank["n_counties"],
            hovertemplate="%{y}: %{x:,.0f} head · %{customdata} counties<extra></extra>"))
        apply_layout(fig, f"Ag Districts — {sel_state_name} {sel_year}",
                     max(380, 30*len(rank)), "")
        fig.update_xaxes(title_text="Head")
        fig.update_yaxes(title_text="", showgrid=False)
        st.plotly_chart(fig, use_container_width=True)

    with t_data:
        out = asd.rename(columns={"asd_desc": "Ag District", "asd_code": "Code",
                                  "Value": "Head", "n_counties": "Counties"})
        out["Ag District"] = out["Ag District"].str.title()
        out = out[["Ag District", "Code", "Counties", "Head"]].sort_values("Head", ascending=False)
        out.insert(0, "Rank", range(1, len(out) + 1))
        st.dataframe(out, use_container_width=True, height=430, hide_index=True,
                     column_config={"Head": st.column_config.NumberColumn(format="%d")})
        st.download_button("⬇ Download Excel", to_excel(out),
                           file_name=f"asd_{sel_state_alpha}_{sel_year}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown(
    f'<p style="color:{DM_MUTED};font-size:0.72rem;text-align:center">'
    f'Data: USDA NASS QuickStats · Inventory (head) &amp; Milk Production (lb) · '
    f'Survey &amp; Census · Cached 6h &nbsp;|&nbsp; John Stewart &amp; Associates</p>',
    unsafe_allow_html=True)
st.markdown(
    f'<div style="padding:10px 20px 20px;color:#6b7280;font-size:0.70rem;line-height:1.6;">'
    f'Trading commodity futures, options on futures, cash commodities, and over-the-counter '
    f'derivative products involves substantial risk of loss and may not be suitable for all investors. '
    f'This communication is provided for informational purposes only and does not constitute investment '
    f'advice, a recommendation, or an offer or solicitation to buy or sell any futures, options, cash '
    f'commodities, or derivative products. John Stewart &amp; Associates, Inc. does not accept orders '
    f'to buy or sell any financial instruments via email. The information contained herein has been '
    f'obtained from sources believed to be reliable; however, its accuracy and completeness are not '
    f'guaranteed. Any opinions expressed are solely those of the author, are subject to change without '
    f'notice, and should not be relied upon as a basis for investment decisions. Past performance is '
    f'not indicative of future results. This message may contain confidential or proprietary '
    f'information intended solely for the use of the designated recipient. '
    f'&copy; John Stewart &amp; Associates, Inc. {datetime.now().year}'
    f'</div>',
    unsafe_allow_html=True,
)
