import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
import base64
import pathlib
from datetime import date
from io import BytesIO

# st.Page runs this file via exec(), not as a standalone script, so its own
# directory is never added to sys.path automatically -- without this, the
# local nass_cache_client import below raises ModuleNotFoundError.
sys.path.insert(0, str(Path(__file__).parent))

# ── Constants ────────────────────────────────────────────────────────────────
# This dashboard reads NASS data from a shared, scheduled-pull cache (see
# usda-nass-etl) instead of calling the API live -- it no longer needs a
# NASS API key at all.
from nass_cache_client import fetch_cached

THIS_YEAR = date.today().year

# ── FAS PSD (WASDE) ───────────────────────────────────────────────────────────
PSD_BASE = "https://apps.fas.usda.gov/psdonline/api"

# NASS commodity name → FAS PSD commodity code
PSD_CODE = {
    "Corn":      "0440000",
    "Soybeans":  "2222000",
    "Wheat":     "0410000",
    "Cotton":    "5151000",
    "Sorghum":   "0459100",
    "Barley":    "0430000",
    "Canola":    "2226000",
    "Peanuts":   "2191000",
}

# Balance sheet row order: (attributeName fragment, display label, row_type)
# row_type: "supply" | "use" | "total" | "stocks" | "divider"
PSD_BS_ROWS = [
    ("Beginning Stocks",      "Beginning Stocks",      "stocks"),
    ("Production",            "Production",            "supply"),
    ("Imports",               "Imports",               "supply"),
    ("Total Supply",          "Total Supply",          "total"),
    ("Feed Dom. Consumption", "Feed & Residual",        "use"),
    ("FSI Dom. Consumption",  "Food / Seed / Indust.", "use"),
    ("Dom. Consumption",      "Dom. Consumption",      "total"),
    ("Exports",               "Exports",               "use"),
    ("Ending Stocks",         "Ending Stocks",         "stocks"),
]

# Multi-commodity S/U comparison — always corn/beans/wheat regardless of sidebar
PSD_SU_COMMODITIES = [
    ("Corn",     "0440000"),
    ("Soybeans", "2222000"),
    ("Wheat",    "0410000"),
]

# ── JPSI brand palette (light theme) ────────────────────────────────────────
# Sidebar stays dark (JPSI banner); main content is light.
TEAL      = "#5ba5af"   # JPSI primary CTA teal
TEAL_DIM  = "#3d7a84"   # darker teal
AMBER     = "#d97706"   # amber adjusted for light bg
GREEN     = "#16a34a"   # green adjusted for light bg
RED       = "#dc2626"   # red adjusted for light bg
WHITE     = "#ffffff"

# Light content surfaces
PAGE_BG   = "#f5f6f7"   # main app background
CARD_BG   = "#ffffff"   # chart / card surface
BORDER    = "#e5e7eb"   # subtle border
TXT       = "#111827"   # primary text
TXT_SEC   = "#6b7280"   # secondary / label text
GRID_CLR  = "#e5e7eb"   # chart gridlines

# Sidebar (dark — matches JPSI banner)
DARK_ALT  = "#2d3236"   # sidebar bg
DARK_BG   = "#2d3236"   # kept for any legacy references
DARK_CARD = CARD_BG     # kept so existing chart inline layouts get white bg
GRAY      = "#9ca3af"   # sidebar secondary text

BLUE      = TEAL        # alias so chart helpers keep working

# ── Logo ─────────────────────────────────────────────────────────────────────
LOGO_WHITE  = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"
_LOGO_FILE  = pathlib.Path(__file__).parent / "assets" / "jsa_50th_logo.png"
if _LOGO_FILE.exists():
    LOGO_COLOR = "data:image/png;base64," + base64.b64encode(_LOGO_FILE.read_bytes()).decode()
else:
    LOGO_COLOR = "https://www.jpsi.com/wp-content/uploads/2023/04/Group-2.png"

STATE_ABBREV = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT",
    "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY",
}
ABBREV_STATE = {v: k for k, v in STATE_ABBREV.items()}

# Approximate geographic centers for state label placement
STATE_CENTERS = {
    "AL":(32.8,-86.8),"AZ":(34.3,-111.1),"AR":(34.8,-92.2),"CA":(37.2,-119.5),
    "CO":(39.0,-105.5),"CT":(41.6,-72.7),"DE":(39.0,-75.5),"FL":(28.6,-81.5),
    "GA":(32.9,-83.4),"ID":(44.4,-114.6),"IL":(40.0,-89.2),"IN":(39.9,-86.3),
    "IA":(42.1,-93.5),"KS":(38.5,-98.4),"KY":(37.5,-85.3),"LA":(31.0,-91.8),
    "ME":(45.4,-69.0),"MD":(39.1,-76.8),"MA":(42.2,-71.5),"MI":(44.3,-85.4),
    "MN":(46.4,-93.1),"MS":(32.7,-89.7),"MO":(38.4,-92.6),"MT":(47.0,-110.0),
    "NE":(41.5,-99.9),"NV":(39.3,-117.1),"NH":(43.7,-71.6),"NJ":(40.2,-74.7),
    "NM":(34.5,-106.1),"NY":(42.9,-75.5),"NC":(35.5,-79.4),"ND":(47.5,-100.5),
    "OH":(40.3,-82.8),"OK":(35.6,-97.5),"OR":(44.1,-120.5),"PA":(40.9,-77.8),
    "SC":(33.8,-80.9),"SD":(44.4,-100.2),"TN":(35.8,-86.4),"TX":(31.1,-97.6),
    "UT":(39.4,-111.1),"VT":(44.0,-72.7),"VA":(37.8,-79.5),"WA":(47.4,-120.5),
    "WV":(38.6,-80.6),"WI":(44.3,-89.8),"WY":(43.0,-107.6),
}

# ── Commodity definitions — add new crops here ───────────────────────────────
# Each commodity maps metric labels to NASS QuickStats parameters.
COMMODITIES = {
    "Corn": {
        "Planted Acres":   {"commodity_desc": "CORN", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",      "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres": {"commodity_desc": "CORN", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",      "reference_period_desc": "YEAR", "source_desc": "SURVEY", "util_practice_desc": "GRAIN"},
        "Yield (Bu/Ac)":   {"commodity_desc": "CORN", "statisticcat_desc": "YIELD",         "unit_desc": "BU / ACRE",  "reference_period_desc": "YEAR", "source_desc": "SURVEY", "util_practice_desc": "GRAIN"},
        "Production (Bu)": {"commodity_desc": "CORN", "statisticcat_desc": "PRODUCTION",    "unit_desc": "BU",         "reference_period_desc": "YEAR", "source_desc": "SURVEY", "util_practice_desc": "GRAIN"},
    },
    "Soybeans": {
        "Planted Acres":   {"commodity_desc": "SOYBEANS", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres": {"commodity_desc": "SOYBEANS", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Yield (Bu/Ac)":   {"commodity_desc": "SOYBEANS", "statisticcat_desc": "YIELD",         "unit_desc": "BU / ACRE", "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Production (Bu)": {"commodity_desc": "SOYBEANS", "statisticcat_desc": "PRODUCTION",    "unit_desc": "BU",        "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
    },
    "Wheat": {
        "Planted Acres":   {"commodity_desc": "WHEAT", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres": {"commodity_desc": "WHEAT", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Yield (Bu/Ac)":   {"commodity_desc": "WHEAT", "statisticcat_desc": "YIELD",         "unit_desc": "BU / ACRE", "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Production (Bu)": {"commodity_desc": "WHEAT", "statisticcat_desc": "PRODUCTION",    "unit_desc": "BU",        "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
    },
    "Cotton": {
        "Planted Acres":            {"commodity_desc": "COTTON", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",        "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres":          {"commodity_desc": "COTTON", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",        "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Yield (Lb/Ac)":            {"commodity_desc": "COTTON", "statisticcat_desc": "YIELD",         "unit_desc": "LB / ACRE",    "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Production (480 Lb Bales)":{"commodity_desc": "COTTON", "statisticcat_desc": "PRODUCTION",    "unit_desc": "480 LB BALES", "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
    },
    "Sorghum": {
        "Planted Acres":   {"commodity_desc": "SORGHUM", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres": {"commodity_desc": "SORGHUM", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY", "util_practice_desc": "GRAIN"},
        "Yield (Bu/Ac)":   {"commodity_desc": "SORGHUM", "statisticcat_desc": "YIELD",         "unit_desc": "BU / ACRE", "reference_period_desc": "YEAR", "source_desc": "SURVEY", "util_practice_desc": "GRAIN"},
        "Production (Bu)": {"commodity_desc": "SORGHUM", "statisticcat_desc": "PRODUCTION",    "unit_desc": "BU",        "reference_period_desc": "YEAR", "source_desc": "SURVEY", "util_practice_desc": "GRAIN"},
    },
    "Barley": {
        "Planted Acres":   {"commodity_desc": "BARLEY", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres": {"commodity_desc": "BARLEY", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Yield (Bu/Ac)":   {"commodity_desc": "BARLEY", "statisticcat_desc": "YIELD",         "unit_desc": "BU / ACRE", "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Production (Bu)": {"commodity_desc": "BARLEY", "statisticcat_desc": "PRODUCTION",    "unit_desc": "BU",        "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
    },
    "Canola": {
        "Planted Acres":    {"commodity_desc": "CANOLA", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres":  {"commodity_desc": "CANOLA", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Yield (Lb/Ac)":    {"commodity_desc": "CANOLA", "statisticcat_desc": "YIELD",         "unit_desc": "LB / ACRE", "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Production (Lb)":  {"commodity_desc": "CANOLA", "statisticcat_desc": "PRODUCTION",    "unit_desc": "LB",        "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
    },
    "Sugarbeets": {
        "Planted Acres":       {"commodity_desc": "SUGARBEETS", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",      "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres":     {"commodity_desc": "SUGARBEETS", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",      "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Yield (Tons/Ac)":     {"commodity_desc": "SUGARBEETS", "statisticcat_desc": "YIELD",         "unit_desc": "TONS / ACRE","reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Production (Tons)":   {"commodity_desc": "SUGARBEETS", "statisticcat_desc": "PRODUCTION",    "unit_desc": "TONS",       "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
    },
    "Peanuts": {
        "Planted Acres":   {"commodity_desc": "PEANUTS", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres": {"commodity_desc": "PEANUTS", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Yield (Lb/Ac)":   {"commodity_desc": "PEANUTS", "statisticcat_desc": "YIELD",         "unit_desc": "LB / ACRE", "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Production (Lb)": {"commodity_desc": "PEANUTS", "statisticcat_desc": "PRODUCTION",    "unit_desc": "LB",        "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
    },
    "Hay": {
        "Planted Acres":      {"commodity_desc": "HAY", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",      "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres":    {"commodity_desc": "HAY", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",      "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Yield (Tons/Ac)":    {"commodity_desc": "HAY", "statisticcat_desc": "YIELD",         "unit_desc": "TONS / ACRE","reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Production (Tons)":  {"commodity_desc": "HAY", "statisticcat_desc": "PRODUCTION",    "unit_desc": "TONS",       "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
    },
    "Sunflower": {
        "Planted Acres":   {"commodity_desc": "SUNFLOWER", "statisticcat_desc": "AREA PLANTED",  "unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Harvested Acres": {"commodity_desc": "SUNFLOWER", "statisticcat_desc": "AREA HARVESTED","unit_desc": "ACRES",     "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Yield (Lb/Ac)":   {"commodity_desc": "SUNFLOWER", "statisticcat_desc": "YIELD",         "unit_desc": "LB / ACRE", "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
        "Production (Lb)": {"commodity_desc": "SUNFLOWER", "statisticcat_desc": "PRODUCTION",    "unit_desc": "LB",        "reference_period_desc": "YEAR", "source_desc": "SURVEY"},
    },
}


LOGO_WHITE = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"
LOGO_FULL  = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"

# ── Per-commodity state table groups ─────────────────────────────────────────
# Each group renders individual state rows → optional subtotal row → spacer row.
# Keyed by commodity name matching COMMODITIES dict above.
COMMODITY_TABLE_GROUPS: dict = {
    "Corn": [
        {"states": ["IL", "IN", "OH", "MI", "KY"],                                   "subtotal": "Eastern Corn Belt"},
        {"states": ["IA", "NE", "KS", "CO", "MO"],                                   "subtotal": "Central Plains"},
        {"states": ["MN", "SD", "ND"],                                                "subtotal": "BN States"},
        {"states": ["MS", "AR", "LA", "TN"],                                          "subtotal": "Delta"},
        {"states": ["OK", "TX", "NM"],                                                "subtotal": "Southern Plains"},
        {"states": ["AL", "GA", "FL", "SC", "NC", "VA"],                             "subtotal": "SE States"},
        {"states": ["PA", "NY", "MD", "WV", "MA", "VT", "DE", "NJ", "NH", "ME", "CT"], "subtotal": "NE States"},
        {"states": ["WI"],                                                            "subtotal": None},
    ],
    "Soybeans": [
        {"states": ["IL", "IN", "OH", "MI", "KY"],  "subtotal": "Eastern Corn Belt"},
        {"states": ["IA", "MN", "MO"],              "subtotal": "Western Corn Belt"},
        {"states": ["ND", "SD", "NE", "KS"],        "subtotal": "Northern Plains"},
        {"states": ["AR", "MS", "TN", "LA"],        "subtotal": "Delta"},
        {"states": ["WI"],                          "subtotal": None},
    ],
    "Wheat": [
        {"states": ["KS", "OK", "TX"],              "subtotal": "Southern Plains (HRW)"},
        {"states": ["CO", "NE", "SD"],              "subtotal": "Central Plains (HRW)"},
        {"states": ["WA", "OR", "ID"],              "subtotal": "Pacific Northwest"},
        {"states": ["IL", "IN", "OH", "MI", "KY"],  "subtotal": "Eastern SRW Belt"},
        {"states": ["MT", "ND"],                    "subtotal": None},
    ],
    "Cotton": [
        {"states": ["TX", "OK", "NM"],              "subtotal": "Southwest"},
        {"states": ["GA", "AL", "SC", "NC"],        "subtotal": "Southeast"},
        {"states": ["MS", "AR", "TN"],              "subtotal": "Delta"},
        {"states": ["CA", "AZ"],                    "subtotal": None},
    ],
    "Sorghum": [
        {"states": ["KS", "TX", "OK"],              "subtotal": "Southern Plains"},
        {"states": ["SD", "NE", "CO"],              "subtotal": "Northern Plains"},
        {"states": ["MO", "AR", "LA"],              "subtotal": None},
    ],
    "Barley": [
        {"states": ["ND", "MT", "ID"],              "subtotal": "Northern Plains"},
        {"states": ["WA", "OR", "WY"],              "subtotal": "Pacific Northwest"},
        {"states": ["CO", "MN"],                    "subtotal": None},
    ],
    "Canola": [
        {"states": ["ND", "MT", "OK"],              "subtotal": None},
    ],
    "Sugarbeets": [
        {"states": ["ND", "MN", "MI"],              "subtotal": "Northern"},
        {"states": ["ID", "WY", "CO"],              "subtotal": "Western"},
        {"states": ["CA", "OR"],                    "subtotal": None},
    ],
    "Peanuts": [
        {"states": ["GA", "AL", "FL"],              "subtotal": "Southeast"},
        {"states": ["TX", "OK", "NM"],              "subtotal": "Southwest"},
        {"states": ["NC", "VA", "SC"],              "subtotal": "Mid-Atlantic"},
        {"states": ["AR", "MS"],                    "subtotal": None},
    ],
    "Hay": [
        {"states": ["TX", "CA", "KS"],              "subtotal": "South / West"},
        {"states": ["SD", "ND", "MT"],              "subtotal": "Northern Plains"},
        {"states": ["WI", "MN", "IA"],              "subtotal": "Midwest"},
        {"states": ["OK", "MO"],                    "subtotal": None},
    ],
    "Sunflower": [
        {"states": ["ND", "SD", "MN"],              "subtotal": "Northern Plains"},
        {"states": ["KS", "CO", "NE"],              "subtotal": "Central Plains"},
        {"states": ["TX"],                          "subtotal": None},
    ],
}

# ── Quarterly Stocks config ───────────────────────────────────────────────────
STOCKS_QUARTERS = ["DEC 1", "MAR 1", "JUN 1", "SEP 1"]
# NASS stores these as "FIRST OF ..." — map display label → API value
STOCKS_QUARTERS_API = {
    "DEC 1": "FIRST OF DEC",
    "MAR 1": "FIRST OF MAR",
    "JUN 1": "FIRST OF JUN",
    "SEP 1": "FIRST OF SEP",
}
# Maps each quarter to (prior_quarter_label, year_delta) for "vs Last Report"
PREV_QUARTER = {
    "DEC 1": ("SEP 1",  0),
    "MAR 1": ("DEC 1", -1),
    "JUN 1": ("MAR 1",  0),
    "SEP 1": ("JUN 1",  0),
}
# Quarter in which new-crop production enters storage — must add production to prior stocks
# to compute true disappearance for that quarter.
#   Fall-harvest crops (corn, soybeans, sorghum, barley): harvest Oct-Nov → enters Dec 1
#   Wheat (winter/spring):    harvest Jun-Jul           → enters Sep 1
HARVEST_QUARTER = {
    "Corn":     "DEC 1",
    "Soybeans": "DEC 1",
    "Sorghum":  "DEC 1",
    "Barley":   "DEC 1",
    "Wheat":    "SEP 1",
}

# Commodities that have quarterly grain stocks in NASS; maps to API params
STOCKS_META = {
    "Corn":     {"commodity_desc": "CORN",     "unit_desc": "BU"},
    "Soybeans": {"commodity_desc": "SOYBEANS", "unit_desc": "BU"},
    "Wheat":    {"commodity_desc": "WHEAT",    "unit_desc": "BU"},
    "Sorghum":  {"commodity_desc": "SORGHUM",  "unit_desc": "BU"},
    "Barley":   {"commodity_desc": "BARLEY",   "unit_desc": "BU"},
}

# ── Revision Tracker config ──────────────────────────────────────────────────
# Ordered NASS reference_period_desc values for each metric category
REVISION_PERIODS_ACRES = [
    "YEAR - JUN ACREAGE",
    "YEAR",
]
REVISION_PERIODS_YLDPROD = [
    "YEAR - MAY FORECAST",
    "YEAR - JUN FORECAST",
    "YEAR - JUL FORECAST",
    "YEAR - AUG FORECAST",
    "YEAR - SEP FORECAST",
    "YEAR - OCT FORECAST",
    "YEAR - NOV FORECAST",
    "YEAR",
]
PERIOD_SHORT = {
    "YEAR - JUN ACREAGE":  "Jun Acreage",
    "YEAR - MAY FORECAST": "May Fcst",
    "YEAR - JUN FORECAST": "Jun Fcst",
    "YEAR - JUL FORECAST": "Jul Fcst",
    "YEAR - AUG FORECAST": "Aug Fcst",
    "YEAR - SEP FORECAST": "Sep Fcst",
    "YEAR - OCT FORECAST": "Oct Fcst",
    "YEAR - NOV FORECAST": "Nov Fcst",
    "YEAR":                "Final",
}
# Curated checkpoints shown in the period-comparison dropdowns.
# The line chart always shows every available period; these are the
# key milestones for the column chart until we confirm more from NASS.
KEY_CMP_ACRES   = ["Jun Acreage", "Final"]
KEY_CMP_YLDPROD = ["May Fcst", "Jun Fcst", "Jul Fcst", "Aug Fcst", "Sep Fcst", "Oct Fcst", "Nov Fcst", "Final"]

# 10-step color palette: dark→bright teal, last year = amber
_REV_PALETTE = [
    "#1e4a50","#245860","#2b6870","#347a83","#3d8c95",
    "#479fa8","#51b1bb","#5bbfca","#67d2e0", AMBER,
]

# ── Page config ──────────────────────────────────────────────────────────────
# st.set_page_config removed — the JSA Admin Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=EB+Garamond:wght@400;600&display=swap');

  /* ── Base ── */
  .stApp {{
    background-color: {PAGE_BG};
    color: {TXT};
    font-family: 'Source Sans 3', 'Source Sans Pro', sans-serif;
  }}

  /* ── Sidebar (dark — JPSI banner style) ── */
  section[data-testid="stSidebar"] {{
    background-color: {DARK_ALT};
    border-right: 1px solid #1e2428;
  }}
  section[data-testid="stSidebar"] * {{
    font-family: 'Source Sans 3', sans-serif;
    color: #e5e7eb;
  }}
  section[data-testid="stSidebar"] hr {{
    border-color: #3d4349;
  }}
  section[data-testid="stSidebar"] .stSelectbox label,
  section[data-testid="stSidebar"] .stSlider label {{
    color: #9ca3af !important;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}
  section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{
    color: #9ca3af;
  }}

  /* ── Top accent bar ── */
  .jsa-topbar {{
    background: linear-gradient(90deg, {TEAL} 0%, {TEAL_DIM} 100%);
    height: 4px;
    width: 100%;
    margin-bottom: 0;
  }}

  /* ── Page header ── */
  .jsa-header {{
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 16px 0 14px;
    border-bottom: 2px solid {BORDER};
    margin-bottom: 20px;
  }}
  .jsa-header img {{ height: 38px; }}
  .jsa-header-divider {{
    width: 1px; height: 38px;
    background: {BORDER};
  }}
  .jsa-header-title {{
    font-family: 'EB Garamond', serif;
    font-size: 22px;
    font-weight: 600;
    color: {TXT};
    letter-spacing: -0.01em;
  }}
  .jsa-header-sub {{
    font-size: 12px;
    color: {TXT_SEC};
    margin-top: 2px;
    font-weight: 400;
  }}

  /* ── Sidebar logo ── */
  .jsa-sidebar-logo {{
    padding: 18px 0 14px;
    text-align: center;
    border-bottom: 1px solid #3d4349;
    margin-bottom: 4px;
  }}
  .jsa-sidebar-logo img {{ height: 28px; }}

  /* ── Tabs ── */
  .stTabs [data-baseweb="tab-list"] {{
    background-color: {WHITE};
    border-radius: 6px;
    gap: 2px;
    border: 1px solid {BORDER};
  }}
  .stTabs [data-baseweb="tab"] {{
    color: {TXT_SEC};
    border-radius: 5px;
    font-family: 'Source Sans 3', sans-serif;
    font-size: 13px;
    font-weight: 600;
  }}
  .stTabs [aria-selected="true"] {{
    color: {WHITE} !important;
    background-color: {TEAL} !important;
  }}

  /* ── KPI cards ── */
  .kpi-card {{
    background: {WHITE};
    border-radius: 8px;
    padding: 18px 20px 14px;
    border-top: 3px solid {TEAL};
    height: 100%;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  }}
  .kpi-label  {{ color: {TXT_SEC}; font-size: 11px; font-weight: 700;
                 text-transform: uppercase; letter-spacing: .08em; margin-bottom: 8px; }}
  .kpi-value  {{ color: {TXT}; font-size: 28px; font-weight: 700; line-height: 1.1; }}
  .kpi-year   {{ color: {TXT_SEC}; font-size: 11px; margin-top: 5px; }}
  .kpi-delta  {{ font-size: 13px; margin-top: 3px; font-weight: 600; }}
  .pos {{ color: {GREEN}; }}
  .neg {{ color: {RED}; }}

  /* ── Misc ── */
  .data-note {{
    background: #fffbeb;
    border-left: 3px solid {AMBER};
    padding: 8px 14px;
    border-radius: 4px;
    font-size: 13px;
    color: #92400e;
  }}
  hr {{ border-color: {BORDER}; margin: 16px 0; }}

  /* ── Pill-style radio ── */
  div[data-testid="stRadio"] > label {{ display: none; }}
  div[data-testid="stRadio"] > div {{
    display: flex; gap: 8px; flex-wrap: wrap;
  }}
  div[data-testid="stRadio"] > div > label {{
    background: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 20px;
    padding: 5px 16px;
    color: {TXT_SEC};
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }}
  div[data-testid="stRadio"] > div > label:hover {{
    border-color: {TEAL};
    color: {TEAL};
  }}
  div[data-testid="stRadio"] > div > label[data-checked="true"] {{
    background: {TEAL};
    border-color: {TEAL};
    color: {WHITE};
  }}

  /* ── Section headings inside tabs ── */
  .jsa-section-hdr {{
    font-family: 'EB Garamond', serif;
    font-size: 17px;
    font-weight: 600;
    color: {TXT};
    margin: 0 0 6px;
  }}
  .jsa-sub-hdr {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .07em;
    color: {TXT_SEC};
    margin: 18px 0 6px;
  }}
</style>
""", unsafe_allow_html=True)

# ── API helpers ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _fetch(params: dict) -> pd.DataFrame:
    # Reads the shared NASS cache (see usda-nass-etl) instead of calling
    # NASS live -- this dashboard no longer holds a NASS API key. The ETL
    # only caches ONE broad, unfiltered-by-year/-period row per
    # (commodity, metric, agg_level) -- callers that used to pass a narrow
    # year/reference_period_desc filter must instead call this with the
    # broad shape and filter the returned DataFrame themselves (see
    # load_national/load_state_history/load_state_snapshot etc. below).
    try:
        d = fetch_cached(params)
        return pd.DataFrame(d.get("data", []))
    except Exception as e:
        st.error(f"NASS cache error: {e}")
        return pd.DataFrame()

def _clean(val) -> float | None:
    try:
        return float(str(val).replace(",", "").strip())
    except Exception:
        return None

def _table_to_excel(rows: list, years: list, chg_label: str, title: str,
                    prior_lbl: str | None = None) -> bytes:
    """Convert table row dicts to a formatted Excel workbook and return bytes."""
    records = []
    for row in rows:
        if row.get("row_type") == "spacer":
            continue
        rec = {"State / Region": row.get("label", "")}
        for yr in years:
            rec[str(yr)] = row.get(yr)
        rec[chg_label]          = row.get("chg_vs_ly")
        rec["6-Yr Olympic Avg"] = row.get("olym")
        rec["% of Avg"]         = row.get("pct_of_avg")
        rec["Min"]              = row.get("min_val")
        rec["Max"]              = row.get("max_val")
        rec["% of U.S."]        = row.get("pct_us")
        if prior_lbl:
            rec[prior_lbl]              = row.get("prior_rpt_val")
            rec[f"Chg vs {prior_lbl}"]  = row.get("chg_vs_prior_rpt")
        records.append(rec)
    df = pd.DataFrame(records)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=title[:31])
        ws = writer.sheets[title[:31]]
        for col in ws.columns:
            max_len = max((len(str(c.value)) if c.value is not None else 0) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 20)
    return buf.getvalue()

def _render_export_buttons(rows: list, years: list, chg_label: str,
                           filename_stem: str, title: str,
                           prior_lbl: str | None = None):
    """Render Excel download + copyable dataframe expander for a table."""
    xlsx_bytes = _table_to_excel(rows, years, chg_label, title, prior_lbl=prior_lbl)
    c1, c2 = st.columns([1, 5])
    c1.download_button(
        "📥 Export to Excel",
        data=xlsx_bytes,
        file_name=f"{filename_stem}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"dl_{filename_stem}",
    )
    with c2.expander("📋 Copy-friendly table (for email / paste)"):
        records = []
        for row in rows:
            if row.get("row_type") == "spacer":
                continue
            rec = {"State / Region": row.get("label", "")}
            for yr in years:
                v = row.get(yr)
                rec[str(yr)] = round(v, 2) if v is not None else None
            rec[chg_label]          = (round(row["chg_vs_ly"], 1)
                                       if row.get("chg_vs_ly") is not None else None)
            rec["6-Yr Olympic Avg"] = (round(row["olym"], 2)
                                       if row.get("olym") is not None else None)
            rec["% of Avg"]         = (round(row["pct_of_avg"], 1)
                                       if row.get("pct_of_avg") is not None else None)
            if prior_lbl:
                pv = row.get("prior_rpt_val")
                cv = row.get("chg_vs_prior_rpt")
                rec[prior_lbl]             = round(pv, 2) if pv is not None else None
                rec[f"Chg vs {prior_lbl}"] = round(cv, 2) if cv is not None else None
            records.append(rec)
        st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)

def _fmt(v: float, metric: str) -> str:
    if "Yield" in metric or "/Ac" in metric:
        return f"{v:.1f}"
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"

def _ytick(metric: str) -> str:
    return ".1f" if ("Yield" in metric or "/Ac" in metric) else ",.0f"

def _bar_label(v: float, metric: str, no_unit: bool = False) -> str:
    if "Yield" in metric:
        unit = metric.split("(")[-1].replace(")", "").strip()
        return f"{v:.0f}" if no_unit else f"{v:.0f} {unit}"
    if "Acres" in metric:
        return f"{v/1_000_000:.1f}" if no_unit else f"{v/1_000_000:.1f}M Ac"
    if "Production" in metric or "Stocks" in metric:
        unit = metric.split("(")[-1].replace(")", "").strip()
        if "Bu" in unit:
            return f"{v/1_000_000:.0f}" if no_unit else f"{v/1_000_000:.0f}M Bu"
        elif "Lb" in unit:
            return f"{v/1_000_000:.0f}" if no_unit else f"{v/1_000_000:.0f}M Lbs"
        elif "Ton" in unit:
            return f"{v/1_000_000:.0f}" if no_unit else f"{v/1_000_000:.0f}M Tons"
        elif "Bales" in unit:
            return f"{v/1_000:.0f}" if no_unit else f"{v/1_000:.0f}K Bales"
    return _fmt(v, metric)

def _tbl_num(v, metric) -> str:
    """Table cell: scaled number, no unit suffix.
    Yield and Acres → 1 decimal; Production/Stocks → whole number."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if "Yield" in metric:
        return f"{v:.1f}"
    if "Acres" in metric:
        return f"{v / 1_000_000:.2f}"
    if "Production" in metric or "Stocks" in metric:
        unit = metric.split("(")[-1].replace(")", "").strip()
        return f"{round(v / 1_000):,}" if "Bales" in unit else f"{round(v / 1_000_000):,}"
    return f"{round(v):,}"

def _nom_chg_str(chg, metric, no_unit=False) -> str:
    """Signed nominal change in display units, 1 decimal. e.g. '+50.3M Bu'
    Pass no_unit=True for bar labels where the axis/title already shows the unit."""
    if chg is None or (isinstance(chg, float) and pd.isna(chg)):
        return "N/A"
    sign = "+" if chg >= 0 else ""
    if "Yield" in metric:
        unit = metric.split("(")[-1].replace(")", "").strip()
        return f"{sign}{chg:.1f}" if no_unit else f"{sign}{chg:.1f} {unit}"
    if "Acres" in metric:
        return f"{sign}{chg / 1_000_000:.1f}" if no_unit else f"{sign}{chg / 1_000_000:.1f}M Ac"
    if "Production" in metric:
        unit = metric.split("(")[-1].replace(")", "").strip()
        if "Bales" in unit:
            return f"{sign}{chg / 1_000:.0f}" if no_unit else f"{sign}{chg / 1_000:.0f}K Bales"
        if "Bu"  in unit: return f"{sign}{chg / 1_000_000:.0f}" if no_unit else f"{sign}{chg / 1_000_000:.0f}M Bu"
        if "Ton" in unit: return f"{sign}{chg / 1_000_000:.0f}" if no_unit else f"{sign}{chg / 1_000_000:.0f}M Tons"
        if "Lb"  in unit: return f"{sign}{chg / 1_000_000:.0f}" if no_unit else f"{sign}{chg / 1_000_000:.0f}M Lbs"
    return f"{sign}{chg:.1f}"

def _tbl_unit(metric) -> str:
    """Human-readable unit label for table title parenthetical."""
    if "Yield" in metric:
        return metric.split("(")[-1].replace(")", "").strip()
    if "Acres" in metric:
        return "Million Acres"
    if "Production" in metric or "Stocks" in metric:
        unit = metric.split("(")[-1].replace(")", "").strip()
        if "Bales" in unit:   return "Thousand Bales"
        if "Bu"   in unit:   return "Million Bushels"
        if "Ton"  in unit:   return "Million Tons"
        if "Lb"   in unit:   return "Million Lbs"
    return ""

def _olympic6(vals):
    """6-year olympic average: remove highest & lowest, average the rest.
    Accepts up to 6 values (or however many are non-null); needs ≥3 to compute."""
    clean = sorted(v for v in vals if v is not None and not pd.isna(v))
    if len(clean) < 3:
        return None
    return sum(clean[1:-1]) / len(clean[1:-1])

# ── Data loaders ─────────────────────────────────────────────────────────────
def _prefer_all_classes(df: pd.DataFrame) -> pd.DataFrame:
    """When NASS returns multiple class rows per year/state (e.g. Wheat has
    ALL CLASSES / WINTER / SPRING / DURUM), keep only 'ALL CLASSES' rows.
    If the column is absent or no 'ALL CLASSES' row exists, return df unchanged."""
    if "class_desc" not in df.columns:
        return df
    all_cls = df[df["class_desc"].str.upper().str.strip() == "ALL CLASSES"]
    return all_cls if not all_cls.empty else df

@st.cache_data(ttl=300, show_spinner=False)
def load_national(commodity: str, y0: int, y1: int) -> pd.DataFrame:
    params_map = COMMODITIES[commodity]
    frames = []
    for label, mp in params_map.items():
        df = _fetch({
            **mp,
            "agg_level_desc": "NATIONAL",
            "domain_desc":    "TOTAL",
            "freq_desc":      "ANNUAL",
            "year__GE":       str(y0),
            "year__LE":       str(y1),
        })
        if df.empty:
            continue
        # Prefer "ALL CLASSES" rows when commodity reports multiple classes
        df = _prefer_all_classes(df)
        df = df[["year", "Value"]].copy()
        df["year"]   = df["year"].astype(int)
        df["value"]  = df["Value"].apply(_clean)
        df["metric"] = label
        df = df.dropna(subset=["value"]).sort_values("year")
        df = df.drop_duplicates(subset=["year"])
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

PERIOD_PRIORITY = [
    "YEAR",
    "YEAR - NOV FORECAST",
    "YEAR - SEP FORECAST",
    "YEAR - AUG FORECAST",
    "YEAR - JUN ACREAGE",
    "YEAR - JUL FORECAST",
    "YEAR - MAR ACREAGE",   # Prospective Plantings — lowest priority fallback
]

# Ordered (display_label, NASS reference_period_desc) pairs per metric category,
# used by the "vs Prior Report" map view to populate period selectors.
REPORT_PERIODS = {
    "Acres": [
        ("Mar Intentions", "YEAR - MAR ACREAGE"),
        ("Jun Acreage",    "YEAR - JUN ACREAGE"),
        ("Final",          "YEAR"),
    ],
    "Yield": [
        ("May Fcst",  "YEAR - MAY FORECAST"),
        ("Jun Fcst",  "YEAR - JUN FORECAST"),
        ("Jul Fcst",  "YEAR - JUL FORECAST"),
        ("Aug Fcst",  "YEAR - AUG FORECAST"),
        ("Sep Fcst",  "YEAR - SEP FORECAST"),
        ("Oct Fcst",  "YEAR - OCT FORECAST"),
        ("Nov Fcst",  "YEAR - NOV FORECAST"),
        ("Final",     "YEAR"),
    ],
    "Production": [
        ("May Fcst",  "YEAR - MAY FORECAST"),
        ("Jun Fcst",  "YEAR - JUN FORECAST"),
        ("Jul Fcst",  "YEAR - JUL FORECAST"),
        ("Aug Fcst",  "YEAR - AUG FORECAST"),
        ("Sep Fcst",  "YEAR - SEP FORECAST"),
        ("Oct Fcst",  "YEAR - OCT FORECAST"),
        ("Nov Fcst",  "YEAR - NOV FORECAST"),
        ("Final",     "YEAR"),
    ],
}

def _get_report_periods(metric: str):
    if "Acres" in metric:
        return REPORT_PERIODS["Acres"]
    if "Yield" in metric:
        return REPORT_PERIODS["Yield"]
    if "Production" in metric:
        return REPORT_PERIODS["Production"]
    return REPORT_PERIODS["Acres"]

@st.cache_data(ttl=300, show_spinner=False)
def load_state_snapshot(commodity: str, year: int) -> pd.DataFrame:
    params_map = COMMODITIES[commodity]
    frames = []
    for label, mp in params_map.items():
        # Strip reference_period so we get all periods, then pick the best per state
        base = {k: v for k, v in mp.items() if k != "reference_period_desc"}
        df = _fetch({
            **base,
            "agg_level_desc": "STATE",
            "domain_desc":    "TOTAL",
            "freq_desc":      "ANNUAL",
            "year":           str(year),
        })
        if df.empty:
            continue
        # Prefer "ALL CLASSES" rows when commodity reports multiple classes
        df = _prefer_all_classes(df)
        df["value"]      = df["Value"].apply(_clean)
        df["state_abbr"] = df["state_name"].str.upper().map(STATE_ABBREV)
        df["metric"]     = label
        df = df.dropna(subset=["value", "state_abbr"])
        df = df[df["value"] > 0]  # drop suppressed zero rows

        # For each state pick the best available period in priority order
        best_rows = []
        for abbr, grp in df.groupby("state_abbr"):
            for period in PERIOD_PRIORITY:
                row = grp[grp["reference_period_desc"] == period]
                if not row.empty:
                    best_rows.append(row.iloc[0])
                    break
        if not best_rows:
            continue
        result = pd.DataFrame(best_rows)
        frames.append(result[["state_name", "state_abbr", "value", "metric"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

@st.cache_data(ttl=300, show_spinner=False)
def load_period_snapshot(commodity: str, metric: str, year: int, period: str) -> pd.DataFrame:
    """Fetch state-level values for an explicit NASS reference_period_desc."""
    if commodity not in COMMODITIES or metric not in COMMODITIES[commodity]:
        return pd.DataFrame()
    mp   = COMMODITIES[commodity][metric]
    base = {k: v for k, v in mp.items() if k != "reference_period_desc"}
    df   = _fetch({**base, "agg_level_desc": "STATE", "domain_desc": "TOTAL",
                   "reference_period_desc": period, "year": str(year)})
    if df.empty:
        return pd.DataFrame()
    df = _prefer_all_classes(df)
    df["value"]      = df["Value"].apply(_clean)
    df["state_abbr"] = df["state_name"].str.upper().map(STATE_ABBREV)
    df = df.dropna(subset=["value", "state_abbr"])
    df = df[df["value"] > 0]
    return df[["state_name", "state_abbr", "value"]].copy()

@st.cache_data(ttl=300, show_spinner=False)
def load_national_period_snapshot(commodity: str, metric: str, year: int, period: str) -> float | None:
    """Fetch the US national total for a specific NASS reference_period_desc."""
    if commodity not in COMMODITIES or metric not in COMMODITIES[commodity]:
        return None
    mp   = COMMODITIES[commodity][metric]
    base = {k: v for k, v in mp.items() if k != "reference_period_desc"}
    df   = _fetch({**base, "agg_level_desc": "NATIONAL", "domain_desc": "TOTAL",
                   "reference_period_desc": period, "year": str(year)})
    if df.empty:
        return None
    df = _prefer_all_classes(df)
    df["value"] = df["Value"].apply(_clean)
    df = df.dropna(subset=["value"])
    df = df[df["value"] > 0]
    return float(df["value"].iloc[0]) if not df.empty else None


# Map (commodity_name, hist_metric_label) → COMMODITIES metric key
_HIST_METRIC_MAP: dict[str, dict[str, str]] = {
    comm: {
        "Area Harvested": next((k for k in keys if "Harvested" in k), None),
        "Yield":          next((k for k in keys if "Yield" in k), None),
        "Production":     next((k for k in keys if "Production" in k), None),
    }
    for comm, keys in {c: list(COMMODITIES[c].keys()) for c in COMMODITIES}.items()
}


@st.cache_data(ttl=300, show_spinner=False)
def load_state_history(commodity: str, metric: str, y0: int, y1: int) -> pd.DataFrame:
    mp = COMMODITIES[commodity][metric]
    df = _fetch({
        **mp,
        "agg_level_desc": "STATE",
        "domain_desc":    "TOTAL",
        "freq_desc":      "ANNUAL",
        "year__GE":       str(y0),
        "year__LE":       str(y1),
    })
    if df.empty:
        return pd.DataFrame()
    # Prefer "ALL CLASSES" rows when commodity reports multiple classes
    df = _prefer_all_classes(df)
    df["year"]       = df["year"].astype(int)
    df["value"]      = df["Value"].apply(_clean)
    df["state_abbr"] = df["state_name"].str.upper().map(STATE_ABBREV)
    df = df.dropna(subset=["value", "state_abbr"])
    df = df.drop_duplicates(subset=["year", "state_abbr"])
    return df[["year", "value", "state_abbr", "state_name"]].sort_values(["state_abbr", "year"])

# ── Quarterly stocks loaders ─────────────────────────────────────────────────
def _stocks_base(commodity: str, quarter: str) -> dict:
    meta = STOCKS_META[commodity]
    # NASS stores quarterly stocks as "FIRST OF MAR" etc., not "MAR 1".
    api_period = STOCKS_QUARTERS_API.get(quarter, quarter)
    return {**meta, "statisticcat_desc": "STOCKS", "source_desc": "SURVEY",
            "domain_desc": "TOTAL", "reference_period_desc": api_period}

def _filter_storage(df: pd.DataFrame, storage: str) -> pd.DataFrame:
    """Filter a raw NASS stocks DataFrame to avoid double-counting.
    NASS returns 3 rows per state/year: the aggregate plus ON FARM and OFF FARM
    sub-rows. All share class_desc='ALL CLASSES'; the split is via
    util_practice_desc ('ON FARM'/'OFF FARM' in the value for sub-rows).
    For TOTAL we keep only the aggregate row using both filters."""
    if storage != "TOTAL":
        # ON FARM / OFF FARM explicit selection — filter class_desc
        if "class_desc" in df.columns:
            return df[df["class_desc"].str.upper() == storage]
        return df

    # TOTAL: keep ALL CLASSES rows that are NOT the on-farm or off-farm sub-rows
    out = df.copy()
    if "class_desc" in out.columns:
        out = out[out["class_desc"].str.upper() == "ALL CLASSES"]
    if "util_practice_desc" in out.columns:
        _util = out["util_practice_desc"].str.upper()
        out = out[~(_util.str.contains("ON FARM") | _util.str.contains("OFF FARM"))]
    return out if not out.empty else df

@st.cache_data(ttl=300, show_spinner=False)
def load_stocks_snapshot(commodity: str, quarter: str, year: int,
                         storage: str = "TOTAL") -> pd.DataFrame:
    if commodity not in STOCKS_META:
        return pd.DataFrame()
    df = _fetch({**_stocks_base(commodity, quarter),
                 "agg_level_desc": "STATE", "year": str(year)})
    if df.empty:
        return pd.DataFrame()
    df["value"]      = df["Value"].apply(_clean)
    df["state_abbr"] = df["state_name"].str.upper().map(STATE_ABBREV)
    df = df.dropna(subset=["value", "state_abbr"])
    df = df[df["value"] > 0]
    df = _filter_storage(df, storage)
    df = df.groupby(["state_name", "state_abbr"], as_index=False)["value"].sum()
    return df[["state_name", "state_abbr", "value"]].copy()

@st.cache_data(ttl=300, show_spinner=False)
def load_stocks_history(commodity: str, quarter: str, y0: int, y1: int,
                        storage: str = "TOTAL") -> pd.DataFrame:
    if commodity not in STOCKS_META:
        return pd.DataFrame()
    df = _fetch({**_stocks_base(commodity, quarter),
                 "agg_level_desc": "STATE", "year__GE": str(y0), "year__LE": str(y1)})
    if df.empty:
        return pd.DataFrame()
    df["year"]       = df["year"].astype(int)
    df["value"]      = df["Value"].apply(_clean)
    df["state_abbr"] = df["state_name"].str.upper().map(STATE_ABBREV)
    df = df.dropna(subset=["value", "state_abbr"])
    df = _filter_storage(df, storage)
    df = df.groupby(["year", "state_abbr", "state_name"], as_index=False)["value"].sum()
    return df[["year", "value", "state_abbr", "state_name"]].sort_values(["state_abbr", "year"])

@st.cache_data(ttl=300, show_spinner=False)
def load_stocks_national(commodity: str, quarter: str, y0: int, y1: int,
                         storage: str = "TOTAL") -> pd.DataFrame:
    if commodity not in STOCKS_META:
        return pd.DataFrame()
    df = _fetch({**_stocks_base(commodity, quarter),
                 "agg_level_desc": "NATIONAL", "year__GE": str(y0), "year__LE": str(y1)})
    if df.empty:
        return pd.DataFrame()
    df["year"]  = df["year"].astype(int)
    df["value"] = df["Value"].apply(_clean)
    df = df.dropna(subset=["value"])
    df = _filter_storage(df, storage)
    df = df.groupby("year", as_index=False)["value"].sum()
    return df[["year", "value"]].sort_values("year")

# ── Production loaders (for disappearance calculation) ───────────────────────
def _prod_fetch_params(commodity: str) -> dict:
    """Return NASS fetch params for state-level annual final production."""
    if commodity not in COMMODITIES:
        return {}
    prod_key = next((k for k in COMMODITIES[commodity] if "Production" in k), None)
    if not prod_key:
        return {}
    mp = COMMODITIES[commodity][prod_key]
    return {k: v for k, v in mp.items()
            if k not in ("reference_period_desc", "agg_level_desc")}

@st.cache_data(ttl=300, show_spinner=False)
def load_production_snapshot(commodity: str, year: int) -> pd.DataFrame:
    """State-level annual production for one year — used in disappearance snapshot."""
    base = _prod_fetch_params(commodity)
    if not base:
        return pd.DataFrame()
    df = _fetch({**base, "agg_level_desc": "STATE", "domain_desc": "TOTAL",
                 "freq_desc": "ANNUAL", "reference_period_desc": "YEAR",
                 "year": str(year)})
    if df.empty:
        return pd.DataFrame()
    df["value"]      = df["Value"].apply(_clean)
    df["state_abbr"] = df["state_name"].str.upper().map(STATE_ABBREV)
    df = df.dropna(subset=["value", "state_abbr"])
    df = df[df["value"] > 0]
    df = df.groupby(["state_abbr", "state_name"], as_index=False)["value"].sum()
    return df[["state_abbr", "state_name", "value"]].copy()

@st.cache_data(ttl=300, show_spinner=False)
def load_production_state_history(commodity: str, y0: int, y1: int) -> pd.DataFrame:
    """State-level annual production across a year range — used in disappearance table."""
    base = _prod_fetch_params(commodity)
    if not base:
        return pd.DataFrame()
    df = _fetch({**base, "agg_level_desc": "STATE", "domain_desc": "TOTAL",
                 "freq_desc": "ANNUAL", "reference_period_desc": "YEAR",
                 "year__GE": str(y0), "year__LE": str(y1)})
    if df.empty:
        return pd.DataFrame()
    df["year"]       = df["year"].astype(int)
    df["value"]      = df["Value"].apply(_clean)
    df["state_abbr"] = df["state_name"].str.upper().map(STATE_ABBREV)
    df = df.dropna(subset=["value", "state_abbr"])
    df = df[df["value"] > 0]
    df = df.groupby(["year", "state_abbr", "state_name"], as_index=False)["value"].sum()
    return df[["year", "state_abbr", "state_name", "value"]].sort_values(["state_abbr", "year"])

@st.cache_data(ttl=300, show_spinner=False)
def load_production_nat_history(commodity: str, y0: int, y1: int) -> pd.DataFrame:
    """National annual production across a year range — used in disappearance table footer."""
    base = _prod_fetch_params(commodity)
    if not base:
        return pd.DataFrame()
    df = _fetch({**base, "agg_level_desc": "NATIONAL", "domain_desc": "TOTAL",
                 "freq_desc": "ANNUAL", "reference_period_desc": "YEAR",
                 "year__GE": str(y0), "year__LE": str(y1)})
    if df.empty:
        return pd.DataFrame()
    df["year"]  = df["year"].astype(int)
    df["value"] = df["Value"].apply(_clean)
    df = df.dropna(subset=["value"])
    df = df[df["value"] > 0]
    df = df.groupby("year", as_index=False)["value"].sum()
    return df[["year", "value"]].sort_values("year")

# ── Grain storage capacity loader ────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def load_nass_storage_capacity(y0: int, y1: int) -> pd.DataFrame:
    """NASS grain storage capacity by state/year — on-farm and off-farm.
    Returns: year, state_abbr, short_desc, value_bu"""
    df = _fetch({
        "commodity_desc":    "GRAIN STORAGE CAPACITY",
        "statisticcat_desc": "CAPACITY",
        "agg_level_desc":    "STATE",
        "year__GE":          str(y0),
        "year__LE":          str(y1),
    })
    if df.empty:
        return pd.DataFrame()
    df["year"]       = df["year"].astype(int)
    df["value_bu"]   = df["Value"].apply(_clean)
    df["state_abbr"] = df["state_alpha"].str.upper()
    df = df.dropna(subset=["value_bu", "state_abbr"])
    df = df[df["value_bu"] > 0]
    # Drop aggregate rows (OTHER STATES, US TOTAL)
    df = df[~df["state_abbr"].isin(["OT", "US"])]
    return df[["year", "state_abbr", "short_desc", "value_bu"]].copy()

# ── Multi-commodity production loader (for storage vs production) ─────────────
_STORAGE_GRAINS = ["CORN", "SOYBEANS", "WHEAT", "OATS", "SORGHUM"]

@st.cache_data(ttl=3600, show_spinner=False)
def load_multi_commodity_production(y0: int, y1: int) -> pd.DataFrame:
    """State-level annual production for all storage grains across a year range.
    Returns: year, state_abbr, commodity_desc, value_bu"""
    frames = []
    for grain in _STORAGE_GRAINS:
        df = _fetch({
            "commodity_desc":       grain,
            "statisticcat_desc":    "PRODUCTION",
            "unit_desc":            "BU",
            "reference_period_desc":"YEAR",
            "agg_level_desc":       "STATE",
            "domain_desc":          "TOTAL",
            "source_desc":          "SURVEY",
            "year__GE":             str(y0),
            "year__LE":             str(y1),
        })
        if df.empty:
            continue
        df["year"]       = df["year"].astype(int)
        df["value_bu"]   = df["Value"].apply(_clean)
        df["state_abbr"] = df["state_name"].str.upper().map(STATE_ABBREV)
        df = df.dropna(subset=["value_bu", "state_abbr"])
        df = df[df["value_bu"] > 0]
        # Keep ALL CLASSES / ALL PRODUCTION PRACTICES rows only
        if "class_desc" in df.columns:
            df = df[df["class_desc"].str.upper().isin(["ALL CLASSES", ""])]
        if "prodn_practice_desc" in df.columns:
            df = df[df["prodn_practice_desc"].str.upper().str.contains("ALL PRODUCTION")]
        df["commodity_desc"] = grain
        frames.append(df[["year", "state_abbr", "commodity_desc", "value_bu"]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.groupby(["year", "state_abbr", "commodity_desc"], as_index=False)["value_bu"].sum()

# ── Revision-history loader ──────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_revision_data(commodity: str, metric: str, y0: int, y1: int,
                       agg_level: str = "NATIONAL") -> pd.DataFrame:
    """Fetch every reference_period_desc row for a metric across years.
    Returns: year, period, value  [+ state_abbr, state_name for STATE level]."""
    if commodity not in COMMODITIES or metric not in COMMODITIES[commodity]:
        return pd.DataFrame()
    mp   = COMMODITIES[commodity][metric]
    # Drop reference_period_desc (want all periods) AND source_desc (want both
    # SURVEY final values and FORECAST monthly estimates)
    base = {k: v for k, v in mp.items()
            if k not in ("reference_period_desc", "source_desc")}
    df   = _fetch({
        **base,
        "agg_level_desc": agg_level,
        "domain_desc":    "TOTAL",
        "year__GE":       str(y0),
        "year__LE":       str(y1),
    })
    if df.empty:
        return pd.DataFrame()
    df["year"]  = df["year"].astype(int)
    df["value"] = df["Value"].apply(_clean)
    df = df.dropna(subset=["value"])
    df = df[df["value"] > 0]
    # Sort by load_desc so keep="last" gives the most-recently published estimate
    if "load_desc" in df.columns:
        df = df.sort_values("load_desc")
    if agg_level == "STATE":
        df["state_abbr"] = df["state_name"].str.upper().map(STATE_ABBREV)
        df = df.dropna(subset=["state_abbr"])
        df = df.drop_duplicates(
            subset=["year", "reference_period_desc", "state_abbr"], keep="last")
        return (df[["year","reference_period_desc","value","state_abbr","state_name"]]
                .rename(columns={"reference_period_desc":"period"})
                .reset_index(drop=True))
    else:
        df = df.drop_duplicates(subset=["year","reference_period_desc"], keep="last")
        return (df[["year","reference_period_desc","value"]]
                .rename(columns={"reference_period_desc":"period"})
                .reset_index(drop=True))

# ── Chart base theme ─────────────────────────────────────────────────────────
def _base_layout(fig, title="", height=390):
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color=TXT, family="'EB Garamond', serif")),
        plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
        font=dict(color=TXT, family="'Source Sans 3', sans-serif"),
        height=height,
        margin=dict(l=55, r=20, t=48, b=40),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TXT_SEC)),
        xaxis=dict(gridcolor=GRID_CLR, linecolor=BORDER, tickfont=dict(color=TXT_SEC)),
        yaxis=dict(gridcolor=GRID_CLR, linecolor=BORDER, tickfont=dict(color=TXT_SEC)),
        hoverlabel=dict(bgcolor=TXT, font_color=WHITE, bordercolor=TEAL),
    )
    fig.add_layout_image(dict(
        source=LOGO_COLOR,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        xanchor="center", yanchor="middle",
        sizex=0.28, sizey=0.28,
        opacity=0.10,
        layer="below",
    ))
    return fig

# ── FAS PSD loaders ──────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _psd_get(path: str) -> list:
    try:
        r = requests.get(f"{PSD_BASE}/{path}", timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

@st.cache_data(ttl=3600, show_spinner=False)
def load_psd_countries() -> dict:
    """Returns {countryCode: countryName} sorted by name."""
    data = _psd_get("psd/countries")
    return dict(sorted({d["countryCode"]: d["countryName"] for d in data}.items(),
                        key=lambda x: x[1]))

@st.cache_data(ttl=3600, show_spinner=False)
def load_psd_country_year(comm_code: str, country: str, year: int) -> pd.DataFrame:
    data = _psd_get(f"psd/commodity/{comm_code}/country/{country}/year/{year}")
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df

@st.cache_data(ttl=3600, show_spinner=False)
def load_psd_world_year(comm_code: str, year: int) -> pd.DataFrame:
    data = _psd_get(f"psd/commodity/{comm_code}/world/year/{year}")
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df

@st.cache_data(ttl=3600, show_spinner=False)
def load_psd_all_countries_year(comm_code: str, year: int) -> pd.DataFrame:
    data = _psd_get(f"psd/commodity/{comm_code}/country/all/year/{year}")
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df

@st.cache_data(ttl=3600, show_spinner=False)
def load_psd_country_history(comm_code: str, country: str, y0: int, y1: int) -> pd.DataFrame:
    frames = []
    for yr in range(y0, y1 + 1):
        df = load_psd_country_year(comm_code, country, yr)
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def _psd_unit_label(df: pd.DataFrame) -> tuple[str, float]:
    """Return (display_unit_str, divisor) based on unitDescription in data."""
    if df.empty or "unitDescription" not in df.columns:
        return ("", 1.0)
    unit = df["unitDescription"].dropna().iloc[0] if not df["unitDescription"].dropna().empty else ""
    if "1000 Bushels" in unit or "1000 BU" in unit.upper():
        return ("mil bu", 1_000.0)
    if "480-Lb" in unit or "480 Lb" in unit or "Bales" in unit.lower():
        return ("thous bales", 1.0)
    if "1000 MT" in unit or "1000 Metric" in unit:
        return ("MMT", 1_000.0)
    return (unit, 1.0)

def _psd_fmt(v: float, divisor: float) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    disp = v / divisor
    if abs(disp) >= 1_000:
        return f"{disp:,.0f}"
    return f"{disp:,.1f}"

def _psd_attr(df: pd.DataFrame, key: str) -> float | None:
    """Pull a single value from a PSD df by attributeName (case-insensitive partial match)."""
    if df.empty or "attributeName" not in df.columns:
        return None
    # Try exact match first to avoid "Feed Dom. Consumption" matching "Dom. Consumption"
    exact = df["attributeName"].str.lower() == key.lower()
    if exact.any():
        vals = df.loc[exact, "value"].dropna()
    else:
        mask = df["attributeName"].str.contains(key, case=False, na=False)
        vals = df.loc[mask, "value"].dropna()
    return float(vals.iloc[0]) if not vals.empty else None


def _get_ctry_attr(df: pd.DataFrame, attr_key: str) -> dict:
    """Extract {countryCode: float} from an all-countries PSD df for a given attribute."""
    if df.empty or "attributeName" not in df.columns:
        return {}
    exact = df["attributeName"].str.lower() == attr_key.lower()
    if exact.any():
        sub = df[exact]
    else:
        sw = df["attributeName"].str.lower().str.startswith(attr_key.lower())
        sub = df[sw] if sw.any() else df[df["attributeName"].str.contains(attr_key, case=False, na=False)]
    if "countryCode" not in sub.columns:
        return {}
    out = {}
    for _, row in sub.iterrows():
        cc = str(row.get("countryCode", "")).strip()
        v = row.get("value")
        if cc and v is not None and not (isinstance(v, float) and pd.isna(v)):
            try:
                out[cc] = float(v)
            except (ValueError, TypeError):
                pass
    return out


# Monthly WASDE periods for NASS crop production history
# (display_suffix, nass_reference_period_desc, nass_year = mkt_year + year_offset)
_WASDE_HIST_PERIODS = [
    ("May",  "MAY FORECAST",  0),
    ("Jun",  "JUN FORECAST",  0),
    ("Jul",  "JUL FORECAST",  0),
    ("Aug",  "AUG FORECAST",  0),
    ("Sep",  "SEP FORECAST",  0),
    ("Oct",  "OCT FORECAST",  0),
    ("Nov",  "NOV FORECAST",  0),
    ("Final","YEAR",          0),  # January final crop production report
]

@st.cache_data(ttl=86400, show_spinner=False)
def load_wasde_excel_month(comm_name: str, mkt_year: int, report_year: int, report_month: int) -> dict:
    """Download a monthly WASDE Excel file and extract US balance sheet data for mkt_year.
    Returns {attr_label: float} or {} on failure."""
    mm = f"{report_month:02d}"
    yy = str(report_year)[-2:]
    url = f"https://www.usda.gov/oce/commodity/wasde/wasde{mm}{yy}.xlsx"
    try:
        resp = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception:
        return {}
    try:
        raw = BytesIO(resp.content)
        xf = pd.ExcelFile(raw, engine="openpyxl")
        sheet_targets = {
            "Corn":     ["coarse grain", "corn"],
            "Barley":   ["coarse grain"],
            "Sorghum":  ["coarse grain"],
            "Soybeans": ["soybean"],
            "Wheat":    ["wheat"],
            "Cotton":   ["cotton"],
        }
        priorities = sheet_targets.get(comm_name, [comm_name.lower()])
        target_sheet = next(
            (s for s in xf.sheet_names if any(k in s.lower() for k in priorities)), None
        )
        if target_sheet is None:
            return {}

        df = pd.read_excel(BytesIO(resp.content), sheet_name=target_sheet,
                           header=None, dtype=str, engine="openpyxl")
        mkt_str = f"{mkt_year}/{str(mkt_year + 1)[-2:]}"

        # Find column containing the marketing year string
        col_idx = None
        header_row = 0
        for ri in range(min(50, len(df))):
            for ci in range(len(df.columns)):
                cell = str(df.iat[ri, ci]).replace("\xa0", " ").strip()
                if cell == mkt_str or cell.startswith(mkt_str):
                    col_idx, header_row = ci, ri
                    break
            if col_idx is not None:
                break
        if col_idx is None:
            return {}

        # Row labels to extract (keyword → display name)
        LABELS = {
            "harv":            "Area Harvested",
            "yield":           "Yield",
            "production":      "Production",
            "beg":             "Beginning Stocks",
            "import":          "Imports",
            "total supply":    "Total Supply",
            "feed":            "Feed Dom. Consumption",
            "food":            "FSI Dom. Consumption",
            "domestic cons":   "Dom. Consumption",
            "export":          "Exports",
            "ending":          "Ending Stocks",
        }

        result = {}
        in_us = (comm_name not in ("Corn", "Barley", "Sorghum"))
        in_comm = in_us
        for ri in range(header_row + 1, min(header_row + 140, len(df))):
            c0 = str(df.iat[ri, 0]).replace("\xa0", " ").strip().lower()
            c1 = str(df.iat[ri, 1]).replace("\xa0", " ").strip().lower() if len(df.columns) > 1 else ""

            if comm_name.lower() in c0 or comm_name.lower() in c1:
                in_comm = True
            if in_comm and ("united states" in c0 or c0.startswith("u.s.")):
                in_us = True
            if in_us and ri > header_row + 5:
                if any(x in c0 for x in ["canada", "mexico", "world", "european", "brazil", "china"]):
                    break

            if not (in_comm and in_us):
                continue

            label = c0 if c0 and c0 != "nan" else c1
            for kw, attr in LABELS.items():
                if attr in result:
                    continue
                if kw in label:
                    raw_v = str(df.iat[ri, col_idx]).replace(",", "").strip()
                    try:
                        result[attr] = float(raw_v)
                    except (ValueError, TypeError):
                        pass
                    break
        return result
    except Exception:
        return {}


# ── Header ───────────────────────────────────────────────────────────────────
# Read commodity from session_state so header renders before the selectbox widget
_commodity_opts = list(COMMODITIES.keys())
_hdr_commodity  = st.session_state.get("commodity_sel", _commodity_opts[0])

st.markdown("<div class='jsa-topbar'></div>", unsafe_allow_html=True)
st.markdown(f"""
<div class='jsa-header'>
  <img src='{LOGO_COLOR}' alt='JSA'>
  <div class='jsa-header-divider'></div>
  <div>
    <div class='jsa-header-title'>{_hdr_commodity} Production Dashboard</div>
    <div class='jsa-header-sub'>National &amp; State Level &nbsp;·&nbsp; USDA NASS Annual Data &nbsp;·&nbsp; John Stewart &amp; Associates</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Filters ──────────────────────────────────────────────────────────────────
_fc1, _fc2, _fc3, _fc4, _fc5, _fc6 = st.columns([2, 3, 1.5, 1.5, 1.5, 0.8])
with _fc1:
    commodity = st.selectbox("Commodity", _commodity_opts, key="commodity_sel")
metric_list = list(COMMODITIES[commodity].keys())
with _fc2:
    year_range = st.slider("Historical Range", 1980, THIS_YEAR, (1990, THIS_YEAR), step=1)
with _fc3:
    map_year = st.selectbox("Map Year", list(range(THIS_YEAR, 1999, -1)))
with _fc4:
    stocks_year = st.selectbox("Stocks Year", list(range(THIS_YEAR, 1999, -1)))
with _fc5:
    wasde_year = st.selectbox("WASDE Year", list(range(THIS_YEAR, 1999, -1)), key="wasde_year_sel")
with _fc6:
    st.markdown("<div style='margin-top:26px'></div>", unsafe_allow_html=True)
    if st.button("🔄", help="Clear cached data and reload from USDA NASS", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)

# ── Load data ────────────────────────────────────────────────────────────────
with st.spinner("Fetching USDA NASS data..."):
    nat_df  = load_national(commodity, year_range[0], year_range[1])
    snap_df = load_state_snapshot(commodity, map_year)

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_nat, tab_state, tab_stocks, tab_revisions, tab_wasde, tab_storage_cap, tab_storage_vs_prod = st.tabs([
    "  📊  National Overview  ",
    "  🗺️  State Level  ",
    "  📦  Quarterly Stocks  ",
    "  🔄  Revision Tracker  ",
    "  🌾  WASDE  ",
    "  🏗️  Grain Storage  ",
    "  ⚖️  Storage vs Production  ",
])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — NATIONAL
# ═════════════════════════════════════════════════════════════════════════════
with tab_nat:
    if nat_df.empty:
        st.warning("No national data returned from NASS for this commodity/year range.")
        st.stop()

    latest = int(nat_df["year"].max())
    prev   = latest - 1

    # Flag if latest year is current — data may be preliminary or incomplete
    if latest == THIS_YEAR:
        st.markdown(
            f"<div class='data-note'>⚠️ <b>{THIS_YEAR} data is preliminary</b> — NASS releases estimates throughout the year. "
            f"Some metrics may not yet be available.</div><br>",
            unsafe_allow_html=True,
        )

    def get_val(metric, yr):
        rows = nat_df[(nat_df["metric"] == metric) & (nat_df["year"] == yr)]
        return float(rows["value"].values[0]) if len(rows) else None

    # ── KPI cards ────────────────────────────────────────────────────────────
    cols = st.columns(len(metric_list), gap="small")
    for i, metric in enumerate(metric_list):
        v      = get_val(metric, latest)
        v_prev = get_val(metric, prev)
        label  = metric.split("(")[0].strip()

        if v is None:
            cols[i].markdown(
                f"<div class='kpi-card'><div class='kpi-label'>{label}</div>"
                f"<div class='kpi-value' style='font-size:18px;color:{GRAY}'>Not yet available</div>"
                f"<div class='kpi-year'>{latest}</div></div>",
                unsafe_allow_html=True,
            )
            continue

        delta_html = ""
        if v_prev:
            pct  = (v - v_prev) / v_prev * 100
            cls  = "pos" if pct >= 0 else "neg"
            sign = "▲" if pct >= 0 else "▼"
            delta_html = f"<div class='kpi-delta {cls}'>{sign} {abs(pct):.1f}% vs {prev}</div>"

        unit = f" {metric.split('(')[-1].replace(')', '')}" if "(" in metric else ""
        cols[i].markdown(
            f"<div class='kpi-card'>"
            f"<div class='kpi-label'>{label}</div>"
            f"<div class='kpi-value'>{_fmt(v, metric)}</div>"
            f"{delta_html}"
            f"<div class='kpi-year'>{latest}{' — preliminary' if latest == THIS_YEAR else ''}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 4 trend charts (2×2) ──────────────────────────────────────────────────
    col_left, col_right = st.columns(2, gap="medium")
    panels = [col_left, col_right, col_left, col_right]

    for idx, metric in enumerate(metric_list):
        mdf = nat_df[nat_df["metric"] == metric].sort_values("year")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=mdf["year"], y=mdf["value"],
            mode="lines+markers",
            line=dict(color=BLUE, width=2.5),
            marker=dict(size=4, color=BLUE),
            fill="tozeroy",
            fillcolor="rgba(6,147,227,0.10)",
            name=metric,
            hovertemplate=f"<b>%{{x}}</b><br>{metric}: %{{y:{_ytick(metric)}}}<extra></extra>",
        ))
        fig.update_yaxes(tickformat=_ytick(metric))
        _base_layout(fig, title=metric)
        panels[idx % 4].plotly_chart(fig, use_container_width=True)

    # ── Production vs Harvested Acres dual-axis ───────────────────────────────
    prod_label = [m for m in metric_list if "Production" in m]
    harv_label = [m for m in metric_list if "Harvested" in m]

    if prod_label and harv_label:
        st.markdown(f"<h3 class='jsa-section-hdr'>Production vs. Harvested Acres</h3>", unsafe_allow_html=True)
        prod  = nat_df[nat_df["metric"] == prod_label[0]].sort_values("year")
        harv  = nat_df[nat_df["metric"] == harv_label[0]].sort_values("year")
        combo = prod.merge(harv, on="year", suffixes=("_prod", "_harv"))

        fig_dual = go.Figure()
        fig_dual.add_trace(go.Bar(
            x=combo["year"], y=combo["value_harv"],
            name="Harvested Acres",
            marker_color=BLUE, opacity=0.65, yaxis="y",
            hovertemplate="<b>%{x}</b><br>Harvested: %{y:,.0f} ac<extra></extra>",
        ))
        fig_dual.add_trace(go.Scatter(
            x=combo["year"], y=combo["value_prod"],
            name=prod_label[0],
            line=dict(color=AMBER, width=2.5),
            mode="lines+markers", marker=dict(size=4),
            yaxis="y2",
            hovertemplate=f"<b>%{{x}}</b><br>Production: %{{y:,.0f}}<extra></extra>",
        ))
        fig_dual.update_layout(
            plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
            font=dict(color=TXT), height=420,
            margin=dict(l=65, r=65, t=30, b=40),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TXT_SEC)),
            hoverlabel=dict(bgcolor=TXT, font_color=WHITE, bordercolor=TEAL),
            xaxis=dict(gridcolor=GRID_CLR, linecolor=BORDER, tickfont=dict(color=TXT_SEC)),
            yaxis=dict(title="Harvested Acres", tickformat=",.0f", gridcolor=GRID_CLR,
                       linecolor=BORDER, tickfont=dict(color=TXT_SEC), title_font=dict(color=TXT_SEC)),
            yaxis2=dict(title=prod_label[0], overlaying="y", side="right",
                        tickformat=",.0f", gridcolor="rgba(0,0,0,0)",
                        tickfont=dict(color=AMBER), title_font=dict(color=AMBER)),
        )
        st.plotly_chart(fig_dual, use_container_width=True)

    # ── Yield trend with 5-yr rolling avg ────────────────────────────────────
    yield_label = [m for m in metric_list if "Yield" in m]
    if yield_label:
        st.markdown(f"<h3 class='jsa-section-hdr'>Yield Trend with 5-Year Rolling Average</h3>", unsafe_allow_html=True)
        ydf = nat_df[nat_df["metric"] == yield_label[0]].sort_values("year").copy()
        ydf["roll5"] = ydf["value"].rolling(5, center=True).mean()

        fig_yield = go.Figure()
        fig_yield.add_trace(go.Bar(
            x=ydf["year"], y=ydf["value"],
            name="Annual Yield",
            marker_color=BLUE, opacity=0.6,
            hovertemplate="<b>%{x}</b><br>Yield: %{y:.1f}<extra></extra>",
        ))
        fig_yield.add_trace(go.Scatter(
            x=ydf["year"], y=ydf["roll5"],
            name="5-Yr Avg",
            line=dict(color=AMBER, width=2.5, dash="dash"),
            mode="lines",
            hovertemplate="<b>%{x}</b><br>5-Yr Avg: %{y:.1f}<extra></extra>",
        ))
        _base_layout(fig_yield, height=380)
        fig_yield.update_yaxes(tickformat=".1f", title=yield_label[0], title_font=dict(color=GRAY))
        st.plotly_chart(fig_yield, use_container_width=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — STATE LEVEL
# ═════════════════════════════════════════════════════════════════════════════
with tab_state:
    if snap_df.empty:
        st.warning(f"No state data available for {commodity} in {map_year}.")
    else:
        # ── Metric pill filter ────────────────────────────────────────────────
        prod_default = next((m for m in metric_list if "Production" in m), metric_list[0])
        map_metric = st.radio(
            "State metric",
            metric_list,
            index=metric_list.index(prod_default),
            horizontal=True,
            label_visibility="collapsed",
        )
        st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

        metric_snap = snap_df[snap_df["metric"] == map_metric].copy()

        if metric_snap.empty:
            st.warning(f"No state data for {map_metric} in {map_year}.")
        else:
            # ── Map view toggle ───────────────────────────────────────────────
            map_view = st.radio(
                "Map view",
                ["Value", "vs Last Year", "vs Olympic Avg", "vs Year", "vs Prior Report"],
                horizontal=True,
                label_visibility="collapsed",
                key="map_view",
            )
            comp_year = None
            if map_view == "vs Year":
                cv_col, _ = st.columns([2, 8])
                comp_year = cv_col.selectbox(
                    "Compare to",
                    [y for y in range(map_year - 1, 1989, -1)],
                    key="map_comp_year",
                )

            _rp_cur_lbl = _rp_prev_lbl = _rp_cur_nass = _rp_prev_nass = None
            if map_view == "vs Prior Report":
                _rp_opts   = _get_report_periods(map_metric)
                _rp_labels = [p[0] for p in _rp_opts]
                _rp_nass   = dict(_rp_opts)
                _rca, _rcb = st.columns(2)
                _rp_cur_lbl  = _rca.selectbox(
                    "Current Report", _rp_labels,
                    index=min(len(_rp_labels) - 1, 1),
                    key="rp_cur",
                )
                _rp_prev_lbl = _rcb.selectbox(
                    "Prior Report", _rp_labels,
                    index=0,
                    key="rp_prev",
                )
                _rp_cur_nass  = _rp_nass[_rp_cur_lbl]
                _rp_prev_nass = _rp_nass[_rp_prev_lbl]

            # ── Change display toggle (comparison modes only) ──────────────────
            chg_display = "% Change"
            if map_view in ("vs Last Year", "vs Olympic Avg", "vs Year", "vs Prior Report"):
                _cd_col, _ = st.columns([2, 8])
                chg_display = _cd_col.radio(
                    "Show change as",
                    ["% Change", "Nominal"],
                    horizontal=True,
                    label_visibility="collapsed",
                    key="chg_display",
                )
            lbl_display = chg_display
            st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)

            # ── Always load LY for hover ──────────────────────────────────────
            prior_snap = load_state_snapshot(commodity, map_year - 1)
            prior_metric = (
                prior_snap[prior_snap["metric"] == map_metric][["state_abbr", "value"]]
                .rename(columns={"value": "prior_value"})
                if not prior_snap.empty else pd.DataFrame(columns=["state_abbr", "prior_value"])
            )
            metric_snap = metric_snap.merge(prior_metric, on="state_abbr", how="left")
            metric_snap["chg_nom"] = metric_snap["value"] - metric_snap["prior_value"]
            metric_snap["chg_pct"] = metric_snap["chg_nom"] / metric_snap["prior_value"] * 100
            metric_snap["chg_pct_str"] = metric_snap.apply(
                lambda r: "N/A" if pd.isna(r["chg_pct"])
                else f"+{r['chg_pct']:.1f}%" if r["chg_pct"] >= 0
                else f"{r['chg_pct']:.1f}%", axis=1,
            )
            metric_snap["chg_nom_str"] = metric_snap["chg_nom"].apply(
                lambda v: _nom_chg_str(v, map_metric)
            )

            # ── Build color column per view mode ──────────────────────────────
            diverging   = False
            map_cscale  = [[0, "#e8f5f7"], [0.4, "#5ba5af"], [1, "#164e5a"]]
            color_range = None
            cbar_title  = map_metric

            def _pct_str(v):
                if v is None or (isinstance(v, float) and pd.isna(v)): return "N/A"
                return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

            if map_view == "Value":
                metric_snap["color_val"] = metric_snap["value"]
                metric_snap["lbl_str"]   = metric_snap["value"].apply(
                    lambda v: _bar_label(v, map_metric, no_unit=True))
                metric_snap["hover_a"] = metric_snap["chg_pct_str"]
                metric_snap["hover_b"] = metric_snap["chg_nom_str"]
                metric_snap["hover_c"] = ""
                hover_tmpl = (
                    "<b>%{customdata[1]}</b> (%{customdata[0]})<br>"
                    + map_metric + ": %{z:,.1f}<br>"
                    "vs LY: %{customdata[2]}  (%{customdata[3]})"
                    "<extra></extra>"
                )

            elif map_view == "vs Last Year":
                _diff = metric_snap["value"] - metric_snap["prior_value"]
                _pct  = _diff / metric_snap["prior_value"] * 100
                if chg_display == "% Change":
                    metric_snap["color_val"] = _pct
                    cbar_title = "% vs Last Year"
                else:
                    metric_snap["color_val"] = _diff
                    cbar_title = f"Chg vs LY ({_tbl_unit(map_metric)})"
                if lbl_display == "% Change":
                    metric_snap["lbl_str"] = _pct.apply(_pct_str)
                else:
                    metric_snap["lbl_str"] = _diff.apply(lambda v: _nom_chg_str(v, map_metric, no_unit=True))
                metric_snap["hover_a"] = metric_snap["value"].apply(lambda v: _bar_label(v, map_metric))
                metric_snap["hover_b"] = metric_snap["prior_value"].apply(
                    lambda v: _bar_label(v, map_metric) if v is not None and not pd.isna(v) else "N/A")
                metric_snap["hover_c"] = [
                    f"{_pct_str(p)}  ({_nom_chg_str(d, map_metric)})"
                    for p, d in zip(_pct, _diff)
                ]
                hover_tmpl = (
                    "<b>%{customdata[1]}</b> (%{customdata[0]})<br>"
                    f"vs LY: %{{customdata[4]}}<br>"
                    f"{map_year}: %{{customdata[2]}}<br>"
                    f"{map_year - 1}: %{{customdata[3]}}"
                    "<extra></extra>"
                )
                diverging  = True

            elif map_view == "vs Olympic Avg":
                hist_y0 = map_year - 5
                with st.spinner("Loading history for olympic average..."):
                    avg_hist = load_state_history(commodity, map_metric, hist_y0, map_year)
                avg_by_state = {}
                if not avg_hist.empty:
                    for abbr, grp in avg_hist.groupby("state_abbr"):
                        vals = [
                            float(grp.loc[grp["year"] == yr, "value"].iloc[0])
                            if yr in grp["year"].values else None
                            for yr in range(hist_y0, map_year + 1)
                        ]
                        avg_by_state[abbr] = _olympic6(vals)
                metric_snap["state_avg"] = metric_snap["state_abbr"].map(avg_by_state)
                _diff = metric_snap["value"] - metric_snap["state_avg"]
                _pct  = _diff / metric_snap["state_avg"] * 100
                if chg_display == "% Change":
                    metric_snap["color_val"] = _pct
                    cbar_title = "% vs Olympic Avg"
                else:
                    metric_snap["color_val"] = _diff
                    cbar_title = f"Chg vs Olympic Avg ({_tbl_unit(map_metric)})"
                if lbl_display == "% Change":
                    metric_snap["lbl_str"] = _pct.apply(_pct_str)
                else:
                    metric_snap["lbl_str"] = _diff.apply(lambda v: _nom_chg_str(v, map_metric, no_unit=True))
                metric_snap["hover_a"] = metric_snap["value"].apply(lambda v: _bar_label(v, map_metric))
                metric_snap["hover_b"] = metric_snap["state_avg"].apply(
                    lambda v: _bar_label(v, map_metric) if v is not None and not pd.isna(v) else "N/A")
                metric_snap["hover_c"] = [
                    f"{_pct_str(p)}  ({_nom_chg_str(d, map_metric)})"
                    for p, d in zip(_pct, _diff)
                ]
                hover_tmpl = (
                    "<b>%{customdata[1]}</b> (%{customdata[0]})<br>"
                    "vs Olympic Avg: %{customdata[4]}<br>"
                    f"{map_year}: %{{customdata[2]}}<br>"
                    "Olympic Avg: %{customdata[3]}"
                    "<extra></extra>"
                )
                diverging  = True

            elif map_view == "vs Year":
                with st.spinner(f"Loading {comp_year} data..."):
                    comp_snap_raw = load_state_snapshot(commodity, comp_year)
                comp_metric = (
                    comp_snap_raw[comp_snap_raw["metric"] == map_metric][["state_abbr", "value"]]
                    .rename(columns={"value": "comp_value"})
                    if not comp_snap_raw.empty
                    else pd.DataFrame(columns=["state_abbr", "comp_value"])
                )
                metric_snap = metric_snap.merge(comp_metric, on="state_abbr", how="left")
                _diff = metric_snap["value"] - metric_snap["comp_value"]
                _pct  = _diff / metric_snap["comp_value"] * 100
                if chg_display == "% Change":
                    metric_snap["color_val"] = _pct
                    cbar_title = f"% vs {comp_year}"
                else:
                    metric_snap["color_val"] = _diff
                    cbar_title = f"Chg vs {comp_year} ({_tbl_unit(map_metric)})"
                if lbl_display == "% Change":
                    metric_snap["lbl_str"] = _pct.apply(_pct_str)
                else:
                    metric_snap["lbl_str"] = _diff.apply(lambda v: _nom_chg_str(v, map_metric, no_unit=True))
                metric_snap["hover_a"] = metric_snap["value"].apply(lambda v: _bar_label(v, map_metric))
                metric_snap["hover_b"] = metric_snap["comp_value"].apply(
                    lambda v: _bar_label(v, map_metric) if v is not None and not pd.isna(v) else "N/A")
                metric_snap["hover_c"] = [
                    f"{_pct_str(p)}  ({_nom_chg_str(d, map_metric)})"
                    for p, d in zip(_pct, _diff)
                ]
                hover_tmpl = (
                    "<b>%{customdata[1]}</b> (%{customdata[0]})<br>"
                    f"vs {comp_year}: %{{customdata[4]}}<br>"
                    f"{map_year}: %{{customdata[2]}}<br>"
                    f"{comp_year}: %{{customdata[3]}}"
                    "<extra></extra>"
                )
                diverging  = True

            else:   # vs Prior Report
                with st.spinner(f"Loading {_rp_cur_lbl} and {_rp_prev_lbl} data..."):
                    _rp_cur_df  = load_period_snapshot(commodity, map_metric, map_year, _rp_cur_nass)
                    _rp_prev_df = load_period_snapshot(commodity, map_metric, map_year, _rp_prev_nass)
                _rp_cur_vals  = dict(zip(_rp_cur_df["state_abbr"],  _rp_cur_df["value"])) \
                                if not _rp_cur_df.empty else {}
                _rp_prev_vals = dict(zip(_rp_prev_df["state_abbr"], _rp_prev_df["value"])) \
                                if not _rp_prev_df.empty else {}
                metric_snap["value"]      = metric_snap["state_abbr"].map(_rp_cur_vals)
                metric_snap["comp_value"] = metric_snap["state_abbr"].map(_rp_prev_vals)
                metric_snap = metric_snap.dropna(subset=["value", "comp_value"])
                _diff = metric_snap["value"] - metric_snap["comp_value"]
                _pct  = _diff / metric_snap["comp_value"] * 100
                if chg_display == "% Change":
                    metric_snap["color_val"] = _pct
                    cbar_title = f"% vs {_rp_prev_lbl}"
                else:
                    metric_snap["color_val"] = _diff
                    cbar_title = f"Chg vs {_rp_prev_lbl} ({_tbl_unit(map_metric)})"
                if lbl_display == "% Change":
                    metric_snap["lbl_str"] = _pct.apply(_pct_str)
                else:
                    metric_snap["lbl_str"] = _diff.apply(lambda v: _nom_chg_str(v, map_metric, no_unit=True))
                metric_snap["hover_a"] = metric_snap["value"].apply(lambda v: _bar_label(v, map_metric))
                metric_snap["hover_b"] = metric_snap["comp_value"].apply(
                    lambda v: _bar_label(v, map_metric) if v is not None and not pd.isna(v) else "N/A")
                metric_snap["hover_c"] = [
                    f"{_pct_str(p)}  ({_nom_chg_str(d, map_metric)})"
                    for p, d in zip(_pct, _diff)
                ]
                hover_tmpl = (
                    "<b>%{customdata[1]}</b> (%{customdata[0]})<br>"
                    f"vs {_rp_prev_lbl}: %{{customdata[4]}}<br>"
                    f"{_rp_cur_lbl}: %{{customdata[2]}}<br>"
                    f"{_rp_prev_lbl}: %{{customdata[3]}}"
                    "<extra></extra>"
                )
                diverging  = True

            # Diverging scale: red ← 0 → green, symmetric range
            if diverging:
                map_cscale = [[0, "#ef4444"], [0.5, "#e8e8e8"], [1, "#22c55e"]]
                valid_cv   = metric_snap["color_val"].dropna()
                if not valid_cv.empty:
                    max_abs    = max(abs(valid_cv.min()), abs(valid_cv.max())) or 1
                    color_range = [-max_abs, max_abs]

            # ── Choropleth ───────────────────────────────────────────────────
            px_kwargs = dict(
                locations="state_abbr", locationmode="USA-states",
                color="color_val", scope="usa",
                color_continuous_scale=map_cscale,
                hover_name="state_name",
                hover_data={"color_val": False, "state_abbr": False},
                custom_data=["state_abbr", "state_name", "hover_a", "hover_b", "hover_c"],
                labels={"color_val": cbar_title},
                title=f"{commodity} — {map_metric} by State ({map_year})  [{cbar_title}]",
            )
            if color_range:
                px_kwargs["range_color"] = color_range

            fig_map = px.choropleth(metric_snap, **px_kwargs)

            tick_fmt = "+.1f" if (diverging and chg_display == "% Change") else ",.0f"
            fig_map.update_layout(
                geo=dict(bgcolor=PAGE_BG, lakecolor="#cce5f0", landcolor="#f0f0f0",
                         showlakes=True, showcoastlines=False),
                plot_bgcolor=PAGE_BG, paper_bgcolor=PAGE_BG,
                font=dict(color=TXT),
                title_font=dict(size=14, color=TXT),
                coloraxis_colorbar=dict(
                    title=dict(text=cbar_title, font=dict(color=GRAY, size=11)),
                    tickfont=dict(color=TXT_SEC), bgcolor=CARD_BG, bordercolor=BORDER,
                    tickformat=tick_fmt,
                    ticksuffix="%" if (diverging and chg_display == "% Change") else "",
                ),
                height=480,
                margin=dict(l=0, r=0, t=50, b=0),
                dragmode=False,
            )
            fig_map.update_traces(
                selector=dict(type="choropleth"),
                marker_line_color="white",
                marker_line_width=0.6,
                hovertemplate=hover_tmpl,
            )

            # All-50-states white border overlay
            all_state_abbrs = list(STATE_ABBREV.values())
            fig_map.add_trace(go.Choropleth(
                locations=all_state_abbrs, locationmode="USA-states",
                z=[0] * len(all_state_abbrs),
                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
                showscale=False,
                marker_line_color="white", marker_line_width=0.6,
                hoverinfo="skip",
            ))

            # State labels (absolute value or % change depending on mode)
            lbl_lats, lbl_lons, lbl_texts = [], [], []
            for _, row in metric_snap.iterrows():
                abbr = row["state_abbr"]
                if abbr in STATE_CENTERS:
                    lbl_lats.append(STATE_CENTERS[abbr][0])
                    lbl_lons.append(STATE_CENTERS[abbr][1])
                    lbl_texts.append(row["lbl_str"] if row["lbl_str"] not in ("N/A", "") else "")
            fig_map.add_trace(go.Scattergeo(
                lat=lbl_lats, lon=lbl_lons, text=lbl_texts,
                mode="text",
                textfont=dict(color="black", size=11, family="Open Sans", weight="bold"),
                showlegend=False, hoverinfo="skip",
            ))

            fig_map.add_layout_image(dict(
                source=LOGO_COLOR,
                xref="paper", yref="paper",
                x=0.99, y=0.01,
                xanchor="right", yanchor="bottom",
                sizex=0.18, sizey=0.18,
                opacity=0.13,
                layer="above",
            ))

            # Map is the filter — click a state to select it
            map_event = st.plotly_chart(
                fig_map,
                use_container_width=True,
                on_select="rerun",
                key=f"map_{commodity}_{map_year}_{map_metric}_{map_view}_{comp_year}_{_rp_cur_lbl}_{_rp_prev_lbl}",
                config={"scrollZoom": False, "displayModeBar": False},
            )

            # ── Resolve selected state from click event ───────────────────────
            valid_abbrs = set(metric_snap["state_abbr"].tolist())

            if map_event and map_event.selection and map_event.selection.points:
                pt  = map_event.selection.points[0]
                cd  = pt.get("customdata") or []
                abbr_from_click = cd[0] if len(cd) >= 1 else pt.get("location")
                if abbr_from_click in valid_abbrs:
                    st.session_state["sel_state"] = abbr_from_click

            # Validate persisted selection is still in current data
            persisted = st.session_state.get("sel_state")
            if persisted not in valid_abbrs:
                persisted = None
                st.session_state["sel_state"] = None

            selected_abbr = persisted
            selected_name = ABBREV_STATE.get(selected_abbr, "").title() if selected_abbr else None

            # Clear button
            c1, c2 = st.columns([1, 5])
            if selected_abbr:
                c1.caption(f"Selected: **{selected_abbr}**")
                if c2.button("✕ Clear", key="clear_state"):
                    st.session_state["sel_state"] = None
                    st.rerun()
            else:
                c1.caption("Click a state on the map")

            # ── Top-15 bar ────────────────────────────────────────────────────
            # X axis: always the top-15 states by absolute production (stable set)
            # Y axis / colors: adapt to the active map_view filter
            top15 = metric_snap.sort_values("value", ascending=False).head(15)

            if map_view == "Value":
                bar_colors = [
                    TEAL if row["state_abbr"] == selected_abbr else TEAL_DIM
                    for _, row in top15.iterrows()
                ]
                bar_y      = top15["value"]
                bar_text   = top15["value"].apply(lambda v: _bar_label(v, map_metric, no_unit=True))
                bar_hover  = (
                    f"<b>%{{x}}</b><br>{map_metric}: %{{y:{_ytick(map_metric)}}}"
                    "<extra></extra>"
                )
                bar_ytick  = _ytick(map_metric)
                bar_title  = f"Top 15 States — {map_metric} ({map_year})"
                customdata = None
            else:
                def _chg_bar_clr(row):
                    v = row.get("color_val")
                    if v is None or (isinstance(v, float) and pd.isna(v)):
                        return TEAL_DIM
                    pos = v >= 0
                    if selected_abbr and row["state_abbr"] != selected_abbr:
                        return "rgba(34,197,94,0.4)" if pos else "rgba(239,68,68,0.4)"
                    return GREEN if pos else RED
                bar_colors = [_chg_bar_clr(row) for _, row in top15.iterrows()]
                bar_y      = top15["color_val"]
                # Bar labels: strip unit suffix (title/axis already shows it);
                # for nominal mode rebuild with no_unit=True so "M Bu" is dropped
                if chg_display == "% Change":
                    bar_text = top15["lbl_str"]
                else:
                    bar_text = top15["color_val"].apply(
                        lambda v: _nom_chg_str(v, map_metric, no_unit=True)
                    )
                bar_hover  = (
                    f"<b>%{{x}}</b><br>"
                    f"{map_view}: %{{customdata[0]}}<br>"
                    f"{map_metric} ({map_year}): %{{customdata[1]}}"
                    "<extra></extra>"
                )
                bar_ytick  = ".1f%" if chg_display == "% Change" else _ytick(map_metric)
                bar_title  = f"Top 15 States — {map_metric} {map_view} ({map_year})"
                customdata = list(zip(
                    top15["lbl_str"],
                    top15["value"].apply(lambda v: _bar_label(v, map_metric)),
                ))
            fig_bar = go.Figure(go.Bar(
                x=top15["state_abbr"],
                y=bar_y,
                marker_color=bar_colors,
                customdata=customdata,
                text=bar_text,
                textposition="outside",
                textfont=dict(color=TXT_SEC, size=11),
                hovertemplate=bar_hover,
            ))
            _base_layout(fig_bar, title=bar_title, height=400)
            fig_bar.update_yaxes(tickformat=bar_ytick)
            fig_bar.update_layout(showlegend=False)
            st.plotly_chart(fig_bar, use_container_width=True)

            # ── 10-Year State Comparison Table ────────────────────────────────
            tbl_unit_lbl = _tbl_unit(map_metric)
            tbl_unit_sfx = f" <span style='color:{TEAL};font-weight:400;text-transform:none;letter-spacing:0'>({tbl_unit_lbl})</span>" if tbl_unit_lbl else ""
            st.markdown(
                f"<p style='color:{GRAY};font-size:12px;font-weight:700;text-transform:uppercase;"
                f"letter-spacing:.06em;margin:20px 0 6px'>"
                f"10-Year State Comparison — {map_metric}{tbl_unit_sfx}</p>",
                unsafe_allow_html=True,
            )

            tbl_y0         = map_year - 9
            tbl_years_list = list(range(tbl_y0, map_year + 1))

            with st.spinner("Loading comparison table..."):
                tbl_shist = load_state_history(commodity, map_metric, tbl_y0, map_year)

            if tbl_shist.empty or "state_abbr" not in tbl_shist.columns:
                c_msg, c_btn = st.columns([5, 1])
                c_msg.warning(
                    "⏱ State comparison data unavailable — NASS API timed out."
                )
                if c_btn.button("🔄 Retry", key="retry_tbl"):
                    st.cache_data.clear()
                    st.rerun()
            else:
                # National values — reuse the already-fetched nat_df (no extra API call)
                nat_yr_vals = (
                    nat_df[
                        (nat_df["metric"] == map_metric) &
                        (nat_df["year"].between(tbl_y0, map_year))
                    ]
                    .set_index("year")["value"].to_dict()
                )
                nat_recent6  = [nat_yr_vals.get(yr) for yr in tbl_years_list[-6:]]
                nat_olym_val = _olympic6(nat_recent6)

                # ── Interactive state filter ─────────────────────────────────
                # Default groups are commodity-specific; user can add/remove states.
                _default_groups = COMMODITY_TABLE_GROUPS.get(commodity, [])
                _default_abbrs  = [a for grp in _default_groups for a in grp["states"]]

                # All states available in NASS data for this commodity/year window
                _available_states = sorted(tbl_shist["state_abbr"].dropna().unique().tolist())

                with st.expander("📋 Customize Table States", expanded=False):
                    _sel_states = st.multiselect(
                        "States to include in table",
                        options=_available_states,
                        default=[s for s in _default_abbrs if s in _available_states],
                        key=f"tbl_states_{commodity}_{map_metric}",
                        help="Defaults to the key producing states for the selected commodity. "
                             "Add or remove states as needed.",
                    )

                # If user has customized away from default, flatten into one group
                # (regional subtotals only apply to the commodity-specific groupings)
                if set(_sel_states) == set(s for s in _default_abbrs if s in _available_states):
                    # Using default groups — preserve regional subtotals
                    _active_groups = [
                        {"states": [s for s in grp["states"] if s in _sel_states],
                         "subtotal": grp["subtotal"]}
                        for grp in _default_groups
                        if any(s in _sel_states for s in grp["states"])
                    ]
                else:
                    # Custom selection — flat list, no subtotals
                    _active_groups = [{"states": _sel_states, "subtotal": None}]

                all_abbrs = [a for grp in _active_groups for a in grp["states"]]

                # Per-state year→value lookups
                state_yr_vals = {}
                for abbr in all_abbrs:
                    sdf = tbl_shist[tbl_shist["state_abbr"] == abbr]
                    state_yr_vals[abbr] = {int(r["year"]): r["value"] for _, r in sdf.iterrows()}

                cur_yr  = tbl_years_list[-1]   # most recent year in window
                prev_yr = tbl_years_list[-2]   # prior year

                def _build_row(label, yr_map, row_type="state", prior_rpt_val=None):
                    row = {"label": label, "row_type": row_type}
                    all_vals = []
                    for yr in tbl_years_list:
                        v = yr_map.get(yr)
                        row[yr] = v
                        if v is not None:
                            all_vals.append(v)
                    recent6  = [yr_map.get(yr) for yr in tbl_years_list[-6:]]
                    olym     = _olympic6(recent6)
                    cur_v    = yr_map.get(cur_yr)
                    prev_v   = yr_map.get(prev_yr)
                    row["olym"]             = olym
                    row["min_val"]          = min(all_vals) if all_vals else None
                    row["max_val"]          = max(all_vals) if all_vals else None
                    row["pct_us"]           = (olym / nat_olym_val * 100) if (olym and nat_olym_val) else None
                    row["chg_vs_ly"]        = ((cur_v - prev_v) / prev_v * 100) if (cur_v and prev_v) else None
                    row["pct_of_avg"]       = (cur_v / olym * 100) if (cur_v and olym) else None
                    row["prior_rpt_val"]    = prior_rpt_val
                    row["chg_vs_prior_rpt"] = (cur_v - prior_rpt_val) if (cur_v is not None and prior_rpt_val is not None) else None
                    return row

                # For yield metrics load harvested acres so subtotals can be
                # weighted averages (Σ yield×acres / Σ acres) instead of sums
                is_yield = "Yield" in map_metric
                harv_yr_vals: dict = {}
                if is_yield:
                    harv_metric = next(
                        (m for m in COMMODITIES[commodity] if "Harvested" in m), None
                    )
                    if harv_metric:
                        with st.spinner("Loading harvested acres for yield weighting..."):
                            tbl_harv = load_state_history(commodity, harv_metric, tbl_y0, map_year)
                        if not tbl_harv.empty and "state_abbr" in tbl_harv.columns:
                            for abbr in all_abbrs:
                                hdf = tbl_harv[tbl_harv["state_abbr"] == abbr]
                                harv_yr_vals[abbr] = {
                                    int(r["year"]): r["value"] for _, r in hdf.iterrows()
                                }

                # ── Prior Report Comparison for table ────────────────────────
                _rp_tbl_opts  = [(l, p) for l, p in _get_report_periods(map_metric)
                                 if p != "YEAR"]
                _pr_tbl_lbl   = None
                _pr_state_vals: dict = {}
                _pr_us_val    = None

                if _rp_tbl_opts:
                    _pr_col, _ = st.columns([3, 7])
                    _pr_tbl_lbl = _pr_col.selectbox(
                        "Prior report to compare:",
                        [l for l, _ in _rp_tbl_opts],
                        index=0,
                        key=f"tbl_prior_{commodity}_{map_metric}",
                    )
                    _pr_tbl_nass = dict(_rp_tbl_opts)[_pr_tbl_lbl]
                    with st.spinner(f"Loading {_pr_tbl_lbl} data..."):
                        _pr_snap = load_period_snapshot(commodity, map_metric, map_year, _pr_tbl_nass)
                        _pr_us_val = load_national_period_snapshot(commodity, map_metric, map_year, _pr_tbl_nass)
                    if not _pr_snap.empty:
                        _pr_state_vals = dict(zip(_pr_snap["state_abbr"], _pr_snap["value"]))

                # Build all rows
                tbl_rows = []
                for g_idx, grp in enumerate(_active_groups):
                    grp_states = grp["states"]
                    for abbr in grp_states:
                        tbl_rows.append(_build_row(
                            abbr, state_yr_vals.get(abbr, {}), "state",
                            prior_rpt_val=_pr_state_vals.get(abbr),
                        ))
                    if grp["subtotal"] and len(grp_states) > 1:
                        sub_yr = {}
                        for yr in tbl_years_list:
                            if is_yield and harv_yr_vals:
                                # Weighted average: Σ(yield_i × harv_acres_i) / Σ harv_acres_i
                                numer = denom = 0.0
                                for a in grp_states:
                                    y = state_yr_vals.get(a, {}).get(yr)
                                    h = harv_yr_vals.get(a, {}).get(yr)
                                    if y is not None and h is not None and h > 0:
                                        numer += y * h
                                        denom += h
                                sub_yr[yr] = (numer / denom) if denom > 0 else None
                            else:
                                vals  = [state_yr_vals.get(a, {}).get(yr) for a in grp_states]
                                valid = [v for v in vals if v is not None]
                                sub_yr[yr] = sum(valid) if valid else None
                        # Subtotal prior = sum of states in group
                        sub_pr_vals = [_pr_state_vals.get(a) for a in grp_states
                                       if _pr_state_vals.get(a) is not None]
                        sub_pr_val  = sum(sub_pr_vals) if sub_pr_vals else None
                        tbl_rows.append(_build_row(grp["subtotal"], sub_yr, "subtotal",
                                                   prior_rpt_val=sub_pr_val))
                    if g_idx < len(_active_groups) - 1:
                        tbl_rows.append({"row_type": "spacer"})

                # US Total row (national data)
                us_yr_map = {yr: nat_yr_vals.get(yr) for yr in tbl_years_list}
                tbl_rows.append(_build_row("US Total", us_yr_map, "us",
                                           prior_rpt_val=_pr_us_val))

                # ── Render HTML table ─────────────────────────────────────────
                _TH  = (f"padding:7px 9px;text-align:right;background:{TEAL_DIM};color:{WHITE};"
                        f"font-weight:700;font-size:11px;white-space:nowrap;border-bottom:2px solid {TEAL};")
                _TH0 = (f"padding:7px 10px;text-align:left;background:{TEAL_DIM};color:{WHITE};"
                        f"font-weight:700;font-size:11px;border-bottom:2px solid {TEAL};")
                _THS = (f"padding:7px 10px;text-align:right;background:#f0f9fa;color:{TEAL};"
                        f"font-weight:700;font-size:11px;white-space:nowrap;"
                        f"border-bottom:2px solid {TEAL};border-left:2px solid {BORDER};")
                _THP = (f"padding:7px 10px;text-align:right;background:#f0f9fa;color:{AMBER};"
                        f"font-weight:700;font-size:11px;white-space:nowrap;"
                        f"border-bottom:2px solid {TEAL};border-left:1px solid {BORDER};")

                # Separate header style for % vs LY (green/red delta column)
                _THD = (f"padding:7px 9px;text-align:right;background:#f0f9fa;color:{TXT};"
                        f"font-weight:700;font-size:11px;white-space:nowrap;"
                        f"border-bottom:2px solid {TEAL};border-left:2px solid {BORDER};")

                chg_hdr_lbl = "% vs LY"
                yr_hdrs    = "".join(f"<th style='{_TH}'>{yr}</th>" for yr in tbl_years_list)
                # Optional prior report columns
                _pr_col_count = 2 if _pr_tbl_lbl else 0
                _pr_hdr_html  = ""
                if _pr_tbl_lbl:
                    _THR = (f"padding:7px 9px;text-align:right;background:#eff6ff;color:#1d4ed8;"
                            f"font-weight:700;font-size:11px;white-space:nowrap;"
                            f"border-bottom:2px solid {TEAL};border-left:2px solid {BORDER};")
                    _pr_hdr_html = (
                        f"<th style='{_THR}'>{_pr_tbl_lbl} ({map_year})</th>"
                        f"<th style='{_THR}'>Chg vs {_pr_tbl_lbl}</th>"
                    )
                thead_html = (
                    f"<thead><tr>"
                    f"<th style='{_TH0}'>State / Region</th>"
                    f"{yr_hdrs}"
                    f"<th style='{_THD}'>{chg_hdr_lbl}</th>"
                    f"<th style='{_THS}'>6-Yr Olympic Avg</th>"
                    f"<th style='{_THP}'>% of Avg</th>"
                    f"<th style='{_THS}'>Min</th>"
                    f"<th style='{_THS}'>Max</th>"
                    f"<th style='{_THP}'>% of U.S.</th>"
                    f"{_pr_hdr_html}"
                    f"</tr></thead>"
                )

                tbody_html = ""
                row_idx    = 0
                for row in tbl_rows:
                    rtype = row.get("row_type")
                    if rtype == "spacer":
                        colspan = 1 + len(tbl_years_list) + 6 + _pr_col_count
                        tbody_html += (
                            f"<tr><td colspan='{colspan}' "
                            f"style='height:9px;background:{BORDER};'></td></tr>"
                        )
                        continue

                    # Row base styles
                    if rtype == "us":
                        bg = "#e6f4f6"; c_lbl = TEAL_DIM; c_num = TEAL_DIM; c_sp = TEAL_DIM
                        c_pct = AMBER; fw_lbl = "700"; fs_lbl = "13px"
                        border_top = f"border-top:2px solid {TEAL};"
                    elif rtype == "subtotal":
                        bg = "#f0f9fa"; c_lbl = TEAL_DIM; c_num = TEAL_DIM; c_sp = TEAL_DIM
                        c_pct = AMBER; fw_lbl = "700"; fs_lbl = "12px"
                        border_top = f"border-top:1px solid {TEAL_DIM};"
                    else:
                        bg = WHITE if row_idx % 2 == 0 else "#f9fafb"
                        c_lbl = TXT; c_num = TXT_SEC; c_sp = TXT_SEC; c_pct = "#b45309"
                        fw_lbl = "400"; fs_lbl = "12px"; border_top = ""
                        row_idx += 1

                    # Per-row top2 / bottom2 for conditional formatting
                    yr_pairs = [(yr, row[yr]) for yr in tbl_years_list
                                if row.get(yr) is not None]
                    sorted_vals = sorted(yr_pairs, key=lambda x: x[1])
                    bottom2_yrs = {yr for yr, _ in sorted_vals[:2]}  if len(sorted_vals) >= 2 else set()
                    top2_yrs    = {yr for yr, _ in sorted_vals[-2:]} if len(sorted_vals) >= 2 else set()

                    td_lbl = (f"padding:7px 10px;text-align:left;background:{bg};color:{c_lbl};"
                              f"font-weight:{fw_lbl};font-size:{fs_lbl};{border_top}")
                    td_sp  = (f"padding:6px 10px;text-align:right;background:{bg};color:{c_sp};"
                              f"font-weight:600;font-size:12px;border-left:2px solid {BORDER};{border_top}")
                    td_pct = (f"padding:6px 10px;text-align:right;background:{bg};color:{c_pct};"
                              f"font-weight:700;font-size:12px;border-left:1px solid {BORDER};{border_top}")

                    # Year cells with conditional highlighting
                    yr_cells = ""
                    for yr in tbl_years_list:
                        v = row.get(yr)
                        if yr in top2_yrs and v is not None:
                            cell_bg  = "rgba(34,197,94,0.18)"
                            cell_clr = "#4ade80"
                            cell_fw  = "700"
                        elif yr in bottom2_yrs and v is not None:
                            cell_bg  = "rgba(239,68,68,0.18)"
                            cell_clr = "#f87171"
                            cell_fw  = "700"
                        else:
                            cell_bg  = bg
                            cell_clr = c_num
                            cell_fw  = "400"
                        yr_cells += (
                            f"<td style='padding:6px 9px;text-align:right;"
                            f"background:{cell_bg};color:{cell_clr};"
                            f"font-weight:{cell_fw};font-size:12px;{border_top}'>"
                            f"{_tbl_num(v, map_metric)}</td>"
                        )

                    # % vs LY — green if up, red if down
                    chg       = row.get("chg_vs_ly")
                    if chg is None:
                        chg_str  = "—"
                        chg_clr  = GRAY
                        chg_bg   = bg
                    elif chg >= 0:
                        chg_str  = f"▲ {chg:.1f}%"
                        chg_clr  = "#4ade80"
                        chg_bg   = "rgba(34,197,94,0.12)"
                    else:
                        chg_str  = f"▼ {abs(chg):.1f}%"
                        chg_clr  = "#f87171"
                        chg_bg   = "rgba(239,68,68,0.12)"
                    td_chg = (f"padding:6px 9px;text-align:right;background:{chg_bg};"
                              f"color:{chg_clr};font-weight:700;font-size:12px;"
                              f"border-left:2px solid {BORDER};{border_top}")

                    # % of Avg — ▲/▼ showing deviation from 100% (same style as % vs LY)
                    poa_val = row.get("pct_of_avg")
                    if poa_val is None:
                        poa_str = "—"; poa_clr = GRAY; poa_bg = bg
                    elif poa_val >= 100:
                        poa_str = f"▲ {poa_val - 100:.1f}%"; poa_clr = "#4ade80"; poa_bg = "rgba(34,197,94,0.12)"
                    else:
                        poa_str = f"▼ {100 - poa_val:.1f}%"; poa_clr = "#f87171"; poa_bg = "rgba(239,68,68,0.12)"
                    td_poa = (f"padding:6px 9px;text-align:right;background:{poa_bg};"
                              f"color:{poa_clr};font-weight:700;font-size:12px;"
                              f"border-left:1px solid {BORDER};{border_top}")

                    pct_val = row.get("pct_us")
                    pct_str = "—" if pct_val is None else f"{pct_val:.1f}%"

                    # Prior report columns
                    _pr_cells_html = ""
                    if _pr_tbl_lbl:
                        _pr_v   = row.get("prior_rpt_val")
                        _pr_chg = row.get("chg_vs_prior_rpt")
                        _pr_val_str = _tbl_num(_pr_v, map_metric) if _pr_v is not None else "—"
                        if _pr_chg is None:
                            _pr_chg_str = "—"; _pr_chg_clr = GRAY; _pr_chg_bg = bg
                        elif _pr_chg >= 0:
                            _pr_chg_str = f"▲ {_nom_chg_str(_pr_chg, map_metric)}"
                            _pr_chg_clr = "#4ade80"; _pr_chg_bg = "rgba(34,197,94,0.12)"
                        else:
                            _pr_chg_str = f"▼ {_nom_chg_str(abs(_pr_chg), map_metric)}"
                            _pr_chg_clr = "#f87171"; _pr_chg_bg = "rgba(239,68,68,0.12)"
                        _td_pr = (f"padding:6px 9px;text-align:right;background:#eff6ff;"
                                  f"color:#1d4ed8;font-weight:600;font-size:12px;"
                                  f"border-left:2px solid {BORDER};{border_top}")
                        _td_pr_chg = (f"padding:6px 9px;text-align:right;background:{_pr_chg_bg};"
                                      f"color:{_pr_chg_clr};font-weight:700;font-size:12px;"
                                      f"border-left:1px solid {BORDER};{border_top}")
                        _pr_cells_html = (
                            f"<td style='{_td_pr}'>{_pr_val_str}</td>"
                            f"<td style='{_td_pr_chg}'>{_pr_chg_str}</td>"
                        )

                    tbody_html += (
                        f"<tr>"
                        f"<td style='{td_lbl}'>{row['label']}</td>"
                        f"{yr_cells}"
                        f"<td style='{td_chg}'>{chg_str}</td>"
                        f"<td style='{td_sp}'>{_tbl_num(row.get('olym'),    map_metric)}</td>"
                        f"<td style='{td_poa}'>{poa_str}</td>"
                        f"<td style='{td_sp}'>{_tbl_num(row.get('min_val'), map_metric)}</td>"
                        f"<td style='{td_sp}'>{_tbl_num(row.get('max_val'), map_metric)}</td>"
                        f"<td style='{td_pct}'>{pct_str}</td>"
                        f"{_pr_cells_html}"
                        f"</tr>"
                    )

                st.markdown(
                    f"<div style='position:relative;border-radius:8px;border:1px solid {BORDER};"
                    f"margin-bottom:12px;'>"
                    f"<div style='overflow-x:auto;'>"
                    f"<table style='border-collapse:collapse;width:100%;font-family:Open Sans,sans-serif;'>"
                    f"{thead_html}<tbody>{tbody_html}</tbody></table></div>"
                    f"<img src='{LOGO_COLOR}' style='position:absolute;bottom:8px;right:10px;"
                    f"height:44px;opacity:0.12;pointer-events:none;z-index:1;' /></div>",
                    unsafe_allow_html=True,
                )
                _render_export_buttons(
                    tbl_rows, tbl_years_list,
                    chg_hdr_lbl,
                    f"{commodity}_{map_metric}_{map_year}".replace(" ", "_").replace("/", ""),
                    f"{commodity} {map_metric} {map_year}",
                    prior_lbl=_pr_tbl_lbl,
                )

            # ── State historical section ──────────────────────────────────────
            st.markdown("---")
            if selected_abbr is None:
                st.markdown(
                    f"<div style='background:{CARD_BG};border-radius:8px;padding:28px;text-align:center;"
                    f"color:{TXT_SEC};font-size:15px;border:1px dashed {BORDER};'>"
                    f"🗺️ &nbsp; Click a state on the map to view its historical trend"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<h3 class='jsa-section-hdr'>"
                    f"{selected_name} — Historical {map_metric}</h3>",
                    unsafe_allow_html=True,
                )

                with st.spinner(f"Loading {selected_name} history..."):
                    s_hist = load_state_history(commodity, map_metric, year_range[0], year_range[1])

                s_data = s_hist[s_hist["state_abbr"] == selected_abbr].sort_values("year")
                nat_data = nat_df[nat_df["metric"] == map_metric][["year", "value"]].sort_values("year")

                if s_data.empty:
                    st.warning(f"No historical data found for {selected_name}.")
                else:
                    col_l, col_r = st.columns(2, gap="medium")

                    # State trend
                    fig_st = go.Figure()
                    fig_st.add_trace(go.Scatter(
                        x=s_data["year"], y=s_data["value"],
                        mode="lines+markers",
                        line=dict(color=TEAL, width=2.5),
                        marker=dict(size=5),
                        fill="tozeroy", fillcolor="rgba(91,165,175,0.12)",
                        name=selected_name,
                        hovertemplate=f"<b>%{{x}}</b><br>{map_metric}: %{{y:{_ytick(map_metric)}}}<extra></extra>",
                    ))
                    _base_layout(fig_st, title=f"{selected_name} — {map_metric}", height=380)
                    fig_st.update_yaxes(tickformat=_ytick(map_metric))
                    col_l.plotly_chart(fig_st, use_container_width=True)

                    # State vs US
                    fig_vs = go.Figure()
                    fig_vs.add_trace(go.Scatter(
                        x=nat_data["year"], y=nat_data["value"],
                        mode="lines", name="U.S. Total",
                        line=dict(color=TXT_SEC, width=2, dash="dot"),
                        hovertemplate="<b>U.S.</b><br>%{x}: %{y:" + _ytick(map_metric) + "}<extra></extra>",
                    ))
                    fig_vs.add_trace(go.Scatter(
                        x=s_data["year"], y=s_data["value"],
                        mode="lines+markers", name=selected_name,
                        line=dict(color=TEAL, width=2.5),
                        marker=dict(size=5),
                        hovertemplate=f"<b>{selected_name}</b><br>%{{x}}: %{{y:{_ytick(map_metric)}}}<extra></extra>",
                    ))
                    _base_layout(fig_vs, title=f"{selected_name} vs. U.S. — {map_metric}", height=380)
                    fig_vs.update_yaxes(tickformat=_ytick(map_metric))
                    col_r.plotly_chart(fig_vs, use_container_width=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — QUARTERLY STOCKS
# ═════════════════════════════════════════════════════════════════════════════
with tab_stocks:
    if commodity not in STOCKS_META:
        st.info(
            f"Quarterly grain stocks data is not available for **{commodity}** in USDA NASS. "
            f"Available commodities: {', '.join(STOCKS_META.keys())}."
        )
    else:
        unit_key  = STOCKS_META[commodity]["unit_desc"]
        unit_disp = {"BU": "Bu", "TONS": "Tons"}.get(unit_key, unit_key)
        sk_metric = f"Stocks ({unit_disp})"

        # ── Default quarter: Jan–Mar→DEC 1, Apr–Jun→MAR 1, Jul–Sep→JUN 1, Oct–Dec→SEP 1
        _month = date.today().month
        _def_q = 0 if _month <= 3 else 1 if _month <= 6 else 2 if _month <= 9 else 3

        # ── Quarter pill filter ───────────────────────────────────────────────
        sk_quarter = st.radio(
            "Quarter",
            STOCKS_QUARTERS,
            index=_def_q,
            horizontal=True,
            label_visibility="collapsed",
            key="sk_quarter",
        )
        st.markdown("<div style='margin-bottom:6px'></div>", unsafe_allow_html=True)

        # ── Storage filter pills ──────────────────────────────────────────────
        sk_storage = st.radio(
            "Storage",
            ["Total", "On Farm", "Off Farm"],
            horizontal=True,
            label_visibility="collapsed",
            key="sk_storage",
        )
        storage_param = {"Total": "TOTAL", "On Farm": "ON FARM", "Off Farm": "OFF FARM"}[sk_storage]
        storage_lbl   = sk_storage
        st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)

        # ── Mode toggle: Stocks vs Disappearance ──────────────────────────────
        sk_mode = st.radio(
            "Mode",
            ["Stocks", "Disappearance"],
            horizontal=True,
            label_visibility="collapsed",
            key="sk_mode",
        )
        st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)

        # ── View toggle (only when On Farm / Off Farm selected AND Stocks mode) ─
        pct_mode = False
        if sk_storage != "Total" and sk_mode == "Stocks":
            sk_view  = st.radio(
                "View",
                ["Numerical", "% of Total"],
                horizontal=True,
                label_visibility="collapsed",
                key="sk_view",
            )
            pct_mode = (sk_view == "% of Total")

        # In disappearance mode "vs Last Report" is not meaningful — only offer
        # Value / vs Last Year
        _cmp_opts = (["Value", "vs Last Year"]
                     if sk_mode == "Disappearance"
                     else ["Value", "vs Last Year", "vs Last Report"])
        sk_cmp = st.radio(
            "Compare to",
            _cmp_opts,
            horizontal=True,
            label_visibility="collapsed",
            key="sk_cmp",
        )
        st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

        # ── Display-value helpers ─────────────────────────────────────────────
        def _sk_fmt_cell(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return "—"
            return f"{v:.1f}%" if pct_mode else _tbl_num(v, sk_metric)

        def _sk_bar_lbl(v):
            return f"{v:.1f}%" if pct_mode else _bar_label(v, sk_metric)

        # ── Resolve comparison period ─────────────────────────────────────────
        if sk_cmp == "vs Last Report":
            _prev_q, _prev_yr_delta = PREV_QUARTER[sk_quarter]
            _prev_yr  = stocks_year + _prev_yr_delta
            _cmp_label = f"{_prev_q} {_prev_yr}"
        elif sk_cmp == "vs Last Year":
            _prev_q, _prev_yr = sk_quarter, stocks_year - 1
            _cmp_label = str(stocks_year - 1)
        else:  # "Value" — no comparison
            _prev_q, _prev_yr = sk_quarter, stocks_year - 1
            _cmp_label = None

        # ── Load snapshot + comparison period ────────────────────────────────
        with st.spinner("Fetching USDA NASS stocks data..."):
            sk_snap       = load_stocks_snapshot(commodity, sk_quarter, stocks_year, storage_param)
            sk_snap_prior = load_stocks_snapshot(commodity, _prev_q, _prev_yr, storage_param)
            if pct_mode:
                sk_tot_snap       = load_stocks_snapshot(commodity, sk_quarter, stocks_year, "TOTAL")
                sk_tot_snap_prior = load_stocks_snapshot(commodity, _prev_q, _prev_yr, "TOTAL")
            else:
                sk_tot_snap = sk_tot_snap_prior = pd.DataFrame()
            # Disappearance mode: load the immediately-prior quarter + optional production
            if sk_mode == "Disappearance":
                _da_q_s, _da_yr_delta_s = PREV_QUARTER[sk_quarter]
                _da_yr_s = stocks_year + _da_yr_delta_s
                sk_da_prior_snap = load_stocks_snapshot(commodity, _da_q_s, _da_yr_s, "TOTAL")
                sk_da_prod_snap  = (load_production_snapshot(commodity, stocks_year)
                                    if HARVEST_QUARTER.get(commodity) == sk_quarter
                                    else pd.DataFrame())
            else:
                sk_da_prior_snap = sk_da_prod_snap = pd.DataFrame()

        if sk_snap.empty:
            c_msg, c_btn = st.columns([5, 1])
            c_msg.warning(f"No stocks data for {commodity} {sk_quarter} {stocks_year}.")
            if c_btn.button("🔄 Retry", key="retry_stocks"):
                st.cache_data.clear(); st.rerun()
        else:
            # ── Compute display values (Bu or % of total) ─────────────────────
            if pct_mode and not sk_tot_snap.empty:
                sk_snap = sk_snap.merge(
                    sk_tot_snap[["state_abbr", "value"]].rename(columns={"value": "tot_val"}),
                    on="state_abbr", how="left",
                )
                sk_snap["disp_val"] = sk_snap["value"] / sk_snap["tot_val"] * 100
            else:
                sk_snap["disp_val"] = sk_snap["value"]
                pct_mode = False   # fallback if total snap is empty

            # ── Disappearance override ─────────────────────────────────────────
            if sk_mode == "Disappearance":
                if not sk_da_prior_snap.empty:
                    _da_m = sk_snap[["state_abbr", "state_name", "value"]].merge(
                        sk_da_prior_snap[["state_abbr", "value"]].rename(
                            columns={"value": "_prior"}),
                        on="state_abbr", how="left",
                    )
                    if not sk_da_prod_snap.empty:
                        _da_m = _da_m.merge(
                            sk_da_prod_snap[["state_abbr", "value"]].rename(
                                columns={"value": "_prod"}),
                            on="state_abbr", how="left",
                        )
                        _da_m["_prod"] = _da_m["_prod"].fillna(0)
                    else:
                        _da_m["_prod"] = 0.0
                    _da_m["disp_val"] = _da_m["_prior"] + _da_m["_prod"] - _da_m["value"]
                    sk_snap["disp_val"] = (
                        _da_m.set_index("state_abbr")["disp_val"]
                        .reindex(sk_snap["state_abbr"].values).values
                    )
                else:
                    st.warning(
                        f"No {_da_q_s} {_da_yr_s} stocks data — cannot compute disappearance.")
                    sk_mode = "Stocks"

            # Prior-year display values
            if not sk_snap_prior.empty:
                if pct_mode and not sk_tot_snap_prior.empty:
                    sk_snap_prior = sk_snap_prior.merge(
                        sk_tot_snap_prior[["state_abbr", "value"]].rename(columns={"value": "tot_val"}),
                        on="state_abbr", how="left",
                    )
                    sk_snap_prior["prior_disp"] = sk_snap_prior["value"] / sk_snap_prior["tot_val"] * 100
                else:
                    sk_snap_prior["prior_disp"] = sk_snap_prior["value"]
                sk_snap = sk_snap.merge(
                    sk_snap_prior[["state_abbr", "prior_disp"]].rename(columns={"prior_disp": "prior_value"}),
                    on="state_abbr", how="left",
                )
            else:
                sk_snap["prior_value"] = None

            sk_snap["chg_nom"] = sk_snap["disp_val"] - sk_snap["prior_value"]
            sk_snap["chg_pct"] = sk_snap["chg_nom"] / sk_snap["prior_value"] * 100
            sk_snap["chg_pct_str"] = sk_snap.apply(
                lambda r: "N/A" if pd.isna(r["chg_pct"])
                else f"+{r['chg_pct']:.1f}%" if r["chg_pct"] >= 0 else f"{r['chg_pct']:.1f}%", axis=1)
            if pct_mode:
                sk_snap["chg_nom_str"] = sk_snap["chg_nom"].apply(
                    lambda v: "N/A" if (v is None or (isinstance(v, float) and pd.isna(v)))
                    else f"+{v:.1f} ppt" if v >= 0 else f"{v:.1f} ppt"
                )
            else:
                sk_snap["chg_nom_str"] = sk_snap["chg_nom"].apply(
                    lambda v: _nom_chg_str(v, sk_metric))

            # ── Choropleth map ────────────────────────────────────────────────
            if sk_mode == "Disappearance":
                _da_period_lbl = f"{_da_q_s} {_da_yr_s} → {sk_quarter} {stocks_year}"
                map_title     = f"{commodity} Disappearance — {_da_period_lbl} (Million Bu)"
                cbar_title    = "Disappearance (M Bu)"
                hover_val_fmt = ",.1f"
                hover_val_sfx = ""
            elif pct_mode:
                map_title  = f"{commodity} Stocks ({storage_lbl}) — {sk_quarter} {stocks_year} (% of Total)"
                cbar_title = "% of Total"
                hover_val_fmt = ".1f"
                hover_val_sfx = "%"
            else:
                map_title  = f"{commodity} Stocks ({storage_lbl}) — {sk_quarter} {stocks_year} (Million Bu)"
                cbar_title = sk_metric
                hover_val_fmt = ",.1f"
                hover_val_sfx = ""

            fig_sk = px.choropleth(
                sk_snap, locations="state_abbr", locationmode="USA-states",
                color="disp_val", scope="usa",
                color_continuous_scale=[[0, "#1a2a2c"], [0.4, "#5ba5af"], [1, "#b8dde2"]],
                hover_name="state_name",
                hover_data={"disp_val": ":.1f", "state_abbr": False},
                custom_data=["state_abbr", "state_name", "chg_pct_str", "chg_nom_str"],
                labels={"disp_val": cbar_title},
                title=map_title,
            )
            fig_sk.update_layout(
                geo=dict(bgcolor=PAGE_BG, lakecolor="#cce5f0", landcolor="#f0f0f0",
                         showlakes=True, showcoastlines=False),
                plot_bgcolor=PAGE_BG, paper_bgcolor=PAGE_BG,
                font=dict(color=TXT), title_font=dict(size=15, color=TXT),
                coloraxis_colorbar=dict(
                    title=dict(text=cbar_title, font=dict(color=GRAY, size=11)),
                    tickfont=dict(color=TXT_SEC), bgcolor=CARD_BG, bordercolor=BORDER,
                ),
                height=480, margin=dict(l=0, r=0, t=50, b=0), dragmode=False,
            )
            _sk_cmp_hover = (
                f"vs {_cmp_label}: " + "%{customdata[2]}  (%{customdata[3]})<br>"
                if _cmp_label else ""
            )
            fig_sk.update_traces(
                selector=dict(type="choropleth"),
                marker_line_color="white", marker_line_width=0.6,
                hovertemplate=(
                    "<b>%{customdata[1]}</b> (%{customdata[0]})<br>"
                    + cbar_title + f": %{{z:{hover_val_fmt}}}{hover_val_sfx}<br>"
                    + _sk_cmp_hover + "<extra></extra>"
                ),
            )
            # All-states outline
            all_abbrs_list = list(STATE_ABBREV.values())
            fig_sk.add_trace(go.Choropleth(
                locations=all_abbrs_list, locationmode="USA-states",
                z=[0] * len(all_abbrs_list),
                colorscale=[[0,"rgba(0,0,0,0)"],[1,"rgba(0,0,0,0)"]],
                showscale=False, marker_line_color="white",
                marker_line_width=0.6, hoverinfo="skip",
            ))
            # Value labels on map
            lbl_lats, lbl_lons, lbl_texts = [], [], []
            for _, row in sk_snap.iterrows():
                ab = row["state_abbr"]
                if ab in STATE_CENTERS:
                    lbl_lats.append(STATE_CENTERS[ab][0])
                    lbl_lons.append(STATE_CENTERS[ab][1])
                    lbl_texts.append(_sk_bar_lbl(row["disp_val"]))
            fig_sk.add_trace(go.Scattergeo(
                lat=lbl_lats, lon=lbl_lons, text=lbl_texts, mode="text",
                textfont=dict(color="black", size=11, family="Open Sans", weight="bold"),
                showlegend=False, hoverinfo="skip",
            ))

            # Click-to-select state
            sk_event = st.plotly_chart(
                fig_sk, use_container_width=True, on_select="rerun",
                key=f"sk_map_{commodity}_{sk_quarter}_{stocks_year}_{sk_storage}",
                config={"scrollZoom": False, "displayModeBar": False},
            )
            valid_sk_abbrs = set(sk_snap["state_abbr"].tolist())
            if sk_event and sk_event.selection and sk_event.selection.points:
                pt  = sk_event.selection.points[0]
                cd  = pt.get("customdata") or []
                ab  = cd[0] if len(cd) >= 1 else pt.get("location")
                if ab in valid_sk_abbrs:
                    st.session_state["sel_state_stocks"] = ab
            sk_persisted = st.session_state.get("sel_state_stocks")
            if sk_persisted not in valid_sk_abbrs:
                sk_persisted = None
                st.session_state["sel_state_stocks"] = None
            sk_selected_abbr = sk_persisted
            sk_selected_name = ABBREV_STATE.get(sk_selected_abbr, "").title() if sk_selected_abbr else None

            # Clear button
            c1, c2 = st.columns([1, 5])
            if sk_selected_abbr:
                c1.caption(f"Selected: **{sk_selected_abbr}**")
                if c2.button("✕ Clear", key="clear_state_stocks"):
                    st.session_state["sel_state_stocks"] = None; st.rerun()
            else:
                c1.caption("Click a state on the map")

            # ── Top-15 bar ────────────────────────────────────────────────────
            top15_sk    = sk_snap.sort_values("disp_val", ascending=False).head(15)
            bar_ytick   = ".1f" if pct_mode else ",.0f"
            bar_ysuffix = "%" if pct_mode else ""
            bar_col_lbl = ("% of Total" if pct_mode
                           else "Disappearance (M Bu)" if sk_mode == "Disappearance"
                           else sk_metric)
            if sk_mode == "Disappearance":
                bar_title_base = f"Top 15 States — Disappearance ({sk_quarter} {stocks_year}, M Bu)"
            elif pct_mode:
                bar_title_base = f"Top 15 States — {storage_lbl} Stocks ({sk_quarter} {stocks_year}) — % of Total"
            else:
                bar_title_base = f"Top 15 States — {storage_lbl} Stocks ({sk_quarter} {stocks_year})"

            _has_prior_bar = (
                sk_cmp != "Value"
                and "prior_value" in top15_sk.columns
                and not top15_sk["prior_value"].isna().all()
            )

            if _has_prior_bar:
                # ── Diverging change bar (same pattern as Production tab) ────────
                _pri_lbl   = _cmp_label if _cmp_label else "Prior"
                _cur_lbl   = f"{sk_quarter} {stocks_year}"
                bar_title  = f"{bar_title_base} vs {_pri_lbl}"

                # % change as bar height; hover shows nominal too
                _bar_chg_pct = top15_sk["chg_pct"]
                _bar_chg_nom = top15_sk["chg_nom_str"].fillna("N/A")
                _bar_cur_fmt = top15_sk["disp_val"].apply(_sk_bar_lbl)
                _bar_pri_fmt = top15_sk["prior_value"].apply(
                    lambda v: _sk_bar_lbl(v) if pd.notna(v) else "N/A")

                def _sk_chg_bar_clr(row):
                    v = row.get("chg_pct")
                    if v is None or (isinstance(v, float) and pd.isna(v)):
                        return TEAL_DIM
                    pos = v >= 0
                    if sk_selected_abbr and row["state_abbr"] != sk_selected_abbr:
                        return "rgba(22,163,74,0.35)" if pos else "rgba(220,38,38,0.35)"
                    return GREEN if pos else RED

                bar_clrs   = [_sk_chg_bar_clr(r) for _, r in top15_sk.iterrows()]
                bar_text   = top15_sk["chg_pct"].apply(
                    lambda v: (f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%")
                    if pd.notna(v) else "")
                customdata = list(zip(
                    _bar_chg_nom, _bar_cur_fmt, _bar_pri_fmt))

                fig_skbar = go.Figure(go.Bar(
                    x=top15_sk["state_abbr"],
                    y=_bar_chg_pct,
                    marker_color=bar_clrs,
                    customdata=customdata,
                    text=bar_text,
                    textposition="outside",
                    textfont=dict(size=11),
                    hovertemplate=(
                        f"<b>%{{x}}</b><br>"
                        f"Change: %{{customdata[0]}}<br>"
                        f"{_cur_lbl}: %{{customdata[1]}}<br>"
                        f"{_pri_lbl}: %{{customdata[2]}}"
                        f"<extra></extra>"
                    ),
                ))
                _base_layout(fig_skbar, title=bar_title, height=420)
                fig_skbar.update_yaxes(tickformat="+.1f", ticksuffix="%")
                fig_skbar.update_layout(showlegend=False)
                fig_skbar.add_hline(y=0, line_width=1, line_color=BORDER)
            else:
                # ── Single bar (Value mode) ────────────────────────────────────
                bar_title = bar_title_base
                bar_clrs  = [TEAL if r["state_abbr"] == sk_selected_abbr else TEAL_DIM
                             for _, r in top15_sk.iterrows()]
                fig_skbar = go.Figure(go.Bar(
                    x=top15_sk["state_abbr"], y=top15_sk["disp_val"],
                    marker_color=bar_clrs,
                    text=top15_sk["disp_val"].apply(_sk_bar_lbl),
                    textposition="outside", textfont=dict(color=WHITE, size=11),
                    hovertemplate=(
                        "<b>%{x}</b><br>" + bar_col_lbl
                        + ": %{y:" + bar_ytick + "}" + bar_ysuffix
                        + "<extra></extra>"
                    ),
                ))
                _base_layout(fig_skbar, title=bar_title, height=400)
                fig_skbar.update_yaxes(tickformat=bar_ytick, ticksuffix=bar_ysuffix)
                fig_skbar.update_layout(showlegend=False)

            st.plotly_chart(fig_skbar, use_container_width=True)

            # ── State comparison table ────────────────────────────────────────
            if sk_mode == "Disappearance":
                tbl_unit_lbl = _tbl_unit(sk_metric)
                tbl_unit_sfx = (f" <span style='color:{TEAL};font-weight:400;text-transform:none;"
                                f"letter-spacing:0'>({tbl_unit_lbl})</span>" if tbl_unit_lbl else "")
                tbl_hdr_lbl = f"Disappearance — {sk_quarter}{tbl_unit_sfx}"
            elif pct_mode:
                tbl_hdr_lbl = f"% of Total — {storage_lbl} {sk_quarter} Stocks"
            else:
                tbl_unit_lbl = _tbl_unit(sk_metric)
                tbl_unit_sfx = (f" <span style='color:{TEAL};font-weight:400;text-transform:none;"
                                f"letter-spacing:0'>({tbl_unit_lbl})</span>" if tbl_unit_lbl else "")
                tbl_hdr_lbl = f"{sk_quarter} Stocks{tbl_unit_sfx}"
            st.markdown(
                f"<p style='color:{GRAY};font-size:12px;font-weight:700;"
                f"text-transform:uppercase;letter-spacing:.06em;margin:20px 0 6px'>"
                f"10-Year State Comparison — {tbl_hdr_lbl}</p>",
                unsafe_allow_html=True,
            )

            sk_y0 = stocks_year - 9
            sk_years = list(range(sk_y0, stocks_year + 1))

            with st.spinner("Loading stocks comparison table..."):
                sk_hist = load_stocks_history(commodity, sk_quarter, sk_y0, stocks_year, storage_param)
                sk_nat  = load_stocks_national(commodity, sk_quarter, sk_y0, stocks_year, storage_param)
                if pct_mode:
                    sk_hist_tot = load_stocks_history(commodity, sk_quarter, sk_y0, stocks_year, "TOTAL")
                    sk_nat_tot  = load_stocks_national(commodity, sk_quarter, sk_y0, stocks_year, "TOTAL")
                else:
                    sk_hist_tot = sk_nat_tot = pd.DataFrame()
                # Disappearance mode: load prior quarter history + optional production
                if sk_mode == "Disappearance":
                    _da_q_t, _da_yr_delta_t = PREV_QUARTER[sk_quarter]
                    sk_da_ph = load_stocks_history(
                        commodity, _da_q_t,
                        sk_y0 + _da_yr_delta_t, stocks_year + _da_yr_delta_t, "TOTAL")
                    sk_da_phn = load_stocks_national(
                        commodity, _da_q_t,
                        sk_y0 + _da_yr_delta_t, stocks_year + _da_yr_delta_t, "TOTAL")
                    _da_is_harvest = (HARVEST_QUARTER.get(commodity) == sk_quarter)
                    sk_da_prsh = (load_production_state_history(commodity, sk_y0, stocks_year)
                                  if _da_is_harvest else pd.DataFrame())
                    sk_da_prnh = (load_production_nat_history(commodity, sk_y0, stocks_year)
                                  if _da_is_harvest else pd.DataFrame())
                else:
                    sk_da_ph = sk_da_phn = sk_da_prsh = sk_da_prnh = pd.DataFrame()

            if sk_hist.empty or "state_abbr" not in sk_hist.columns:
                c_msg2, c_btn2 = st.columns([5, 1])
                c_msg2.warning("⏱ Stocks comparison data unavailable — NASS API timed out.")
                if c_btn2.button("🔄 Retry", key="retry_stocks_tbl"):
                    st.cache_data.clear(); st.rerun()
            else:
                # Build display history (raw or pct of total)
                if pct_mode and not sk_hist_tot.empty and "state_abbr" in sk_hist_tot.columns:
                    _hm = sk_hist.merge(
                        sk_hist_tot[["year","state_abbr","value"]].rename(columns={"value":"tot_val"}),
                        on=["year","state_abbr"], how="left",
                    )
                    _hm["disp_val"] = _hm["value"] / _hm["tot_val"] * 100
                    sk_hist_disp = _hm[["year","state_abbr","state_name","disp_val"]].rename(columns={"disp_val":"value"})
                else:
                    sk_hist_disp = sk_hist

                if pct_mode and not sk_nat_tot.empty:
                    _nm = sk_nat.merge(
                        sk_nat_tot[["year","value"]].rename(columns={"value":"tot_val"}),
                        on="year", how="left",
                    )
                    _nm["disp_val"] = _nm["value"] / _nm["tot_val"] * 100
                    sk_nat_disp = _nm[["year","disp_val"]].rename(columns={"disp_val":"value"})
                else:
                    sk_nat_disp = sk_nat

                # ── Disappearance: override state and national history ─────────
                if sk_mode == "Disappearance" and not sk_da_ph.empty:
                    # Align prior quarter year to match the current quarter year
                    _da_ph2 = sk_da_ph.copy()
                    _da_ph2["year"] = _da_ph2["year"] - _da_yr_delta_t
                    # State-level disappearance
                    _hm2 = sk_hist_disp.merge(
                        _da_ph2[["year","state_abbr","value"]].rename(
                            columns={"value":"_prior"}),
                        on=["year","state_abbr"], how="left",
                    )
                    if not sk_da_prsh.empty:
                        _hm2 = _hm2.merge(
                            sk_da_prsh[["year","state_abbr","value"]].rename(
                                columns={"value":"_prod"}),
                            on=["year","state_abbr"], how="left",
                        )
                        _hm2["_prod"] = _hm2["_prod"].fillna(0)
                    else:
                        _hm2["_prod"] = 0.0
                    _hm2["disapp"] = _hm2["_prior"] + _hm2["_prod"] - _hm2["value"]
                    sk_hist_disp = _hm2[["year","state_abbr","state_name","disapp"]].rename(
                        columns={"disapp":"value"})
                    # National disappearance
                    if not sk_da_phn.empty:
                        _da_phn2 = sk_da_phn.copy()
                        _da_phn2["year"] = _da_phn2["year"] - _da_yr_delta_t
                        _nm2 = sk_nat_disp.merge(
                            _da_phn2[["year","value"]].rename(columns={"value":"_prior"}),
                            on="year", how="left",
                        )
                        if not sk_da_prnh.empty:
                            _nm2 = _nm2.merge(
                                sk_da_prnh[["year","value"]].rename(columns={"value":"_prod"}),
                                on="year", how="left",
                            )
                            _nm2["_prod"] = _nm2["_prod"].fillna(0)
                        else:
                            _nm2["_prod"] = 0.0
                        _nm2["disapp"] = _nm2["_prior"] + _nm2["_prod"] - _nm2["value"]
                        sk_nat_disp = _nm2[["year","disapp"]].rename(columns={"disapp":"value"})

                sk_nat_yr   = dict(zip(sk_nat_disp["year"], sk_nat_disp["value"])) if not sk_nat_disp.empty else {}
                sk_nat6     = [sk_nat_yr.get(yr) for yr in sk_years[-6:]]
                sk_nat_olym = _olympic6(sk_nat6)

                # ── Interactive state filter (stocks table) ───────────────────
                _sk_default_groups = COMMODITY_TABLE_GROUPS.get(commodity, [])
                _sk_default_abbrs  = [a for grp in _sk_default_groups for a in grp["states"]]
                _sk_avail_states   = sorted(sk_hist_disp["state_abbr"].dropna().unique().tolist())

                with st.expander("📋 Customize Table States", expanded=False):
                    _sk_sel_states = st.multiselect(
                        "States to include in table",
                        options=_sk_avail_states,
                        default=[s for s in _sk_default_abbrs if s in _sk_avail_states],
                        key=f"sk_tbl_states_{commodity}_{sk_quarter}",
                        help="Defaults to the key producing states for the selected commodity.",
                    )

                if set(_sk_sel_states) == set(s for s in _sk_default_abbrs if s in _sk_avail_states):
                    _sk_active_groups = [
                        {"states": [s for s in grp["states"] if s in _sk_sel_states],
                         "subtotal": grp["subtotal"]}
                        for grp in _sk_default_groups
                        if any(s in _sk_sel_states for s in grp["states"])
                    ]
                else:
                    _sk_active_groups = [{"states": _sk_sel_states, "subtotal": None}]

                sk_all_abbrs = [a for grp in _sk_active_groups for a in grp["states"]]

                sk_state_yr: dict = {}
                for abbr in sk_all_abbrs:
                    sdf = sk_hist_disp[sk_hist_disp["state_abbr"] == abbr]
                    sk_state_yr[abbr] = {int(r["year"]): r["value"] for _, r in sdf.iterrows()}

                sk_cur_yr, sk_prev_yr = sk_years[-1], sk_years[-2]

                def _sk_row(label, yr_map, row_type="state", prior_override=None):
                    row = {"label": label, "row_type": row_type}
                    all_vals = []
                    for yr in sk_years:
                        v = yr_map.get(yr); row[yr] = v
                        if v is not None: all_vals.append(v)
                    recent6 = [yr_map.get(yr) for yr in sk_years[-6:]]
                    olym    = _olympic6(recent6)
                    cur_v   = yr_map.get(sk_cur_yr)
                    prev_v  = prior_override if prior_override is not None else yr_map.get(sk_prev_yr)
                    row["olym"]       = olym
                    row["min_val"]    = min(all_vals) if all_vals else None
                    row["max_val"]    = max(all_vals) if all_vals else None
                    row["pct_us"]     = (olym / sk_nat_olym * 100) if (olym and sk_nat_olym) else None
                    if pct_mode:
                        row["chg_vs_ly"] = (cur_v - prev_v) if (cur_v is not None and prev_v is not None) else None
                    else:
                        row["chg_vs_ly"] = ((cur_v - prev_v) / prev_v * 100) if (cur_v and prev_v) else None
                    row["pct_of_avg"] = (cur_v / olym * 100) if (cur_v and olym) else None
                    return row

                # Build prior-quarter lookup for "vs Last Report" mode
                _sk_prev_q_st: dict = {}
                _sk_prev_q_nat: float | None = None
                if sk_cmp == "vs Last Report" and not sk_snap_prior.empty:
                    for _, _r in sk_snap_prior.iterrows():
                        _sk_prev_q_st[_r["state_abbr"]] = _r["value"]
                    _nat_pq = load_stocks_national(
                        commodity, _prev_q, _prev_yr, _prev_yr, storage_param)
                    _sk_prev_q_nat = _nat_pq["value"].iloc[0] if not _nat_pq.empty else None

                sk_rows = []
                for g_idx, grp in enumerate(_sk_active_groups):
                    grp_states = grp["states"]
                    for abbr in grp_states:
                        po = _sk_prev_q_st.get(abbr) if sk_cmp == "vs Last Report" else None
                        sk_rows.append(_sk_row(abbr, sk_state_yr.get(abbr, {}), "state", po))
                    if grp["subtotal"] and len(grp_states) > 1:
                        sub_yr = {}
                        for yr in sk_years:
                            vals  = [sk_state_yr.get(a, {}).get(yr) for a in grp_states]
                            valid = [v for v in vals if v is not None]
                            sub_yr[yr] = sum(valid) if valid else None
                        if sk_cmp == "vs Last Report":
                            sub_po = sum(_sk_prev_q_st.get(a, 0) for a in grp_states
                                         if _sk_prev_q_st.get(a)) or None
                        else:
                            sub_po = None
                        sk_rows.append(_sk_row(grp["subtotal"], sub_yr, "subtotal", sub_po))
                    if g_idx < len(_sk_active_groups) - 1:
                        sk_rows.append({"row_type": "spacer"})
                us_po = _sk_prev_q_nat if sk_cmp == "vs Last Report" else None
                sk_rows.append(_sk_row("US Total", {yr: sk_nat_yr.get(yr) for yr in sk_years}, "us", us_po))

                # ── Render table (same style as production table) ─────────────
                _TH  = (f"padding:7px 9px;text-align:right;background:{TEAL_DIM};color:{WHITE};"
                        f"font-weight:700;font-size:11px;white-space:nowrap;border-bottom:2px solid {TEAL};")
                _TH0 = (f"padding:7px 10px;text-align:left;background:{TEAL_DIM};color:{WHITE};"
                        f"font-weight:700;font-size:11px;border-bottom:2px solid {TEAL};")
                _THS = (f"padding:7px 10px;text-align:right;background:#f0f9fa;color:{TEAL};"
                        f"font-weight:700;font-size:11px;white-space:nowrap;"
                        f"border-bottom:2px solid {TEAL};border-left:2px solid {BORDER};")
                _THP = (f"padding:7px 10px;text-align:right;background:#f0f9fa;color:{AMBER};"
                        f"font-weight:700;font-size:11px;white-space:nowrap;"
                        f"border-bottom:2px solid {TEAL};border-left:1px solid {BORDER};")
                _THD = (f"padding:7px 9px;text-align:right;background:#f0f9fa;color:{TXT};"
                        f"font-weight:700;font-size:11px;white-space:nowrap;"
                        f"border-bottom:2px solid {TEAL};border-left:2px solid {BORDER};")

                _show_chg  = (sk_cmp != "Value")
                chg_hdr    = f"ppt vs {_cmp_label}" if pct_mode else f"% vs {_cmp_label}"
                yr_hdrs    = "".join(f"<th style='{_TH}'>{yr}</th>" for yr in sk_years)
                _chg_th    = f"<th style='{_THD}'>{chg_hdr}</th>" if _show_chg else ""
                sk_thead   = (f"<thead><tr><th style='{_TH0}'>State / Region</th>{yr_hdrs}"
                              f"{_chg_th}"
                              f"<th style='{_THS}'>6-Yr Olympic Avg</th>"
                              f"<th style='{_THP}'>% of Avg</th>"
                              f"<th style='{_THS}'>Min</th><th style='{_THS}'>Max</th>"
                              f"<th style='{_THP}'>% of U.S.</th></tr></thead>")

                sk_tbody = ""
                row_idx  = 0
                for row in sk_rows:
                    rtype = row.get("row_type")
                    if rtype == "spacer":
                        colspan = 1 + len(sk_years) + (5 if not _show_chg else 6)
                        sk_tbody += (f"<tr><td colspan='{colspan}' "
                                     f"style='height:9px;background:{BORDER};'></td></tr>")
                        continue
                    if rtype == "us":
                        bg = "#e6f4f6"; c_lbl = TEAL_DIM; c_num = TEAL_DIM; c_sp = TEAL_DIM
                        c_pct = AMBER; fw_lbl = "700"; fs_lbl = "13px"
                        border_top = f"border-top:2px solid {TEAL};"
                    elif rtype == "subtotal":
                        bg = "#f0f9fa"; c_lbl = TEAL_DIM; c_num = TEAL_DIM; c_sp = TEAL_DIM
                        c_pct = AMBER; fw_lbl = "700"; fs_lbl = "12px"
                        border_top = f"border-top:1px solid {TEAL_DIM};"
                    else:
                        bg = WHITE if row_idx % 2 == 0 else "#f9fafb"
                        c_lbl = TXT; c_num = TXT_SEC; c_sp = TXT_SEC; c_pct = "#b45309"
                        fw_lbl = "400"; fs_lbl = "12px"; border_top = ""
                        row_idx += 1

                    yr_pairs    = [(yr, row[yr]) for yr in sk_years if row.get(yr) is not None]
                    sorted_vals = sorted(yr_pairs, key=lambda x: x[1])
                    bottom2 = {yr for yr, _ in sorted_vals[:2]}  if len(sorted_vals) >= 2 else set()
                    top2    = {yr for yr, _ in sorted_vals[-2:]} if len(sorted_vals) >= 2 else set()

                    td_lbl = (f"padding:7px 10px;text-align:left;background:{bg};color:{c_lbl};"
                              f"font-weight:{fw_lbl};font-size:{fs_lbl};{border_top}")
                    td_sp  = (f"padding:6px 10px;text-align:right;background:{bg};color:{c_sp};"
                              f"font-weight:600;font-size:12px;border-left:2px solid {BORDER};{border_top}")
                    td_pct = (f"padding:6px 10px;text-align:right;background:{bg};color:{c_pct};"
                              f"font-weight:700;font-size:12px;border-left:1px solid {BORDER};{border_top}")

                    yr_cells = ""
                    for yr in sk_years:
                        v = row.get(yr)
                        if yr in top2 and v is not None:
                            cb = "rgba(34,197,94,0.18)"; cc = "#4ade80"; cf = "700"
                        elif yr in bottom2 and v is not None:
                            cb = "rgba(239,68,68,0.18)"; cc = "#f87171"; cf = "700"
                        else:
                            cb = bg; cc = c_num; cf = "400"
                        yr_cells += (f"<td style='padding:6px 9px;text-align:right;"
                                     f"background:{cb};color:{cc};font-weight:{cf};"
                                     f"font-size:12px;{border_top}'>"
                                     f"{_sk_fmt_cell(v)}</td>")

                    chg = row.get("chg_vs_ly")
                    if chg is None:
                        chg_str = "—"; chg_clr = GRAY; chg_bg = bg
                    elif chg >= 0:
                        chg_sfx = "ppt" if pct_mode else "%"
                        chg_str = f"▲ {chg:.1f}{chg_sfx}"; chg_clr = "#4ade80"; chg_bg = "rgba(34,197,94,0.12)"
                    else:
                        chg_sfx = "ppt" if pct_mode else "%"
                        chg_str = f"▼ {abs(chg):.1f}{chg_sfx}"; chg_clr = "#f87171"; chg_bg = "rgba(239,68,68,0.12)"
                    td_chg = (f"padding:6px 9px;text-align:right;background:{chg_bg};"
                              f"color:{chg_clr};font-weight:700;font-size:12px;"
                              f"border-left:2px solid {BORDER};{border_top}")

                    poa_val = row.get("pct_of_avg")
                    if poa_val is None:
                        poa_str = "—"; poa_clr = GRAY; poa_bg = bg
                    elif poa_val >= 100:
                        poa_str = f"▲ {poa_val - 100:.1f}%"; poa_clr = "#4ade80"; poa_bg = "rgba(34,197,94,0.12)"
                    else:
                        poa_str = f"▼ {100 - poa_val:.1f}%"; poa_clr = "#f87171"; poa_bg = "rgba(239,68,68,0.12)"
                    td_poa = (f"padding:6px 9px;text-align:right;background:{poa_bg};"
                              f"color:{poa_clr};font-weight:700;font-size:12px;"
                              f"border-left:1px solid {BORDER};{border_top}")

                    pct_val = row.get("pct_us")
                    pct_str = "—" if (pct_val is None or pct_mode) else f"{pct_val:.1f}%"

                    _chg_td = f"<td style='{td_chg}'>{chg_str}</td>" if _show_chg else ""
                    sk_tbody += (
                        f"<tr><td style='{td_lbl}'>{row['label']}</td>{yr_cells}"
                        f"{_chg_td}"
                        f"<td style='{td_sp}'>{_sk_fmt_cell(row.get('olym'))}</td>"
                        f"<td style='{td_poa}'>{poa_str}</td>"
                        f"<td style='{td_sp}'>{_sk_fmt_cell(row.get('min_val'))}</td>"
                        f"<td style='{td_sp}'>{_sk_fmt_cell(row.get('max_val'))}</td>"
                        f"<td style='{td_pct}'>{pct_str}</td></tr>"
                    )

                st.markdown(
                    f"<div style='position:relative;border-radius:8px;border:1px solid {BORDER};"
                    f"margin-bottom:12px;'>"
                    f"<div style='overflow-x:auto;'>"
                    f"<table style='border-collapse:collapse;width:100%;font-family:Open Sans,sans-serif;'>"
                    f"{sk_thead}<tbody>{sk_tbody}</tbody></table></div>"
                    f"<img src='{LOGO_COLOR}' style='position:absolute;bottom:8px;right:10px;"
                    f"height:44px;opacity:0.12;pointer-events:none;z-index:1;' /></div>",
                    unsafe_allow_html=True,
                )
                _render_export_buttons(
                    sk_rows, sk_years,
                    chg_hdr,
                    f"{commodity}_stocks_{sk_quarter}_{stocks_year}".replace(" ", "_"),
                    f"{commodity} Stocks {sk_quarter} {stocks_year}",
                )

            # ── State historical stocks ───────────────────────────────────────
            st.markdown("---")
            if sk_selected_abbr is None:
                st.markdown(
                    f"<div style='background:{CARD_BG};border-radius:8px;padding:28px;"
                    f"text-align:center;color:{TXT_SEC};font-size:15px;border:1px dashed {BORDER};'>"
                    f"🗺️ &nbsp; Click a state on the map to view its historical trend"
                    f"</div>", unsafe_allow_html=True,
                )
            else:
                hist_sfx = " (% of Total)" if pct_mode else ""
                st.markdown(
                    f"<h3 class='jsa-section-hdr'>"
                    f"{sk_selected_name} — Historical {sk_quarter} {storage_lbl} Stocks{hist_sfx}</h3>",
                    unsafe_allow_html=True,
                )
                with st.spinner(f"Loading {sk_selected_name} stocks history..."):
                    sk_full_hist = load_stocks_history(
                        commodity, sk_quarter, year_range[0], year_range[1], storage_param
                    )
                    sk_nat_full  = load_stocks_national(
                        commodity, sk_quarter, year_range[0], year_range[1], storage_param
                    )
                    if pct_mode:
                        sk_full_hist_tot = load_stocks_history(
                            commodity, sk_quarter, year_range[0], year_range[1], "TOTAL"
                        )
                        sk_nat_full_tot  = load_stocks_national(
                            commodity, sk_quarter, year_range[0], year_range[1], "TOTAL"
                        )

                # Convert to % of total for historical charts if needed
                if pct_mode and not sk_full_hist_tot.empty:
                    sk_full_hist = sk_full_hist.merge(
                        sk_full_hist_tot[["year","state_abbr","value"]].rename(columns={"value":"tot_val"}),
                        on=["year","state_abbr"], how="left",
                    )
                    sk_full_hist["value"] = sk_full_hist["value"] / sk_full_hist["tot_val"] * 100
                    sk_nat_full = sk_nat_full.merge(
                        sk_nat_full_tot[["year","value"]].rename(columns={"value":"tot_val"}),
                        on="year", how="left",
                    )
                    sk_nat_full["value"] = sk_nat_full["value"] / sk_nat_full["tot_val"] * 100

                s_sk = sk_full_hist[sk_full_hist["state_abbr"] == sk_selected_abbr].sort_values("year")
                n_sk = sk_nat_full.sort_values("year")

                if s_sk.empty:
                    st.warning(f"No historical stocks data found for {sk_selected_name}.")
                else:
                    col_l, col_r = st.columns(2, gap="medium")
                    h_ytick   = ".1f" if pct_mode else ",.0f"
                    h_ysuffix = "%" if pct_mode else ""
                    h_hover   = f"%{{y:.1f}}%" if pct_mode else "%{y:,.0f}"

                    fig_skt = go.Figure()
                    fig_skt.add_trace(go.Scatter(
                        x=s_sk["year"], y=s_sk["value"],
                        mode="lines+markers",
                        line=dict(color=TEAL, width=2.5), marker=dict(size=5),
                        fill="tozeroy", fillcolor="rgba(91,165,175,0.12)",
                        name=sk_selected_name,
                        hovertemplate=f"<b>%{{x}}</b><br>Stocks: {h_hover}<extra></extra>",
                    ))
                    _base_layout(fig_skt, title=f"{sk_selected_name} — {sk_quarter} {storage_lbl} Stocks{hist_sfx}", height=380)
                    fig_skt.update_yaxes(tickformat=h_ytick, ticksuffix=h_ysuffix)
                    col_l.plotly_chart(fig_skt, use_container_width=True)

                    fig_skv = go.Figure()
                    fig_skv.add_trace(go.Scatter(
                        x=n_sk["year"], y=n_sk["value"],
                        mode="lines", name="U.S. Total",
                        line=dict(color=TXT_SEC, width=2, dash="dot"),
                        hovertemplate=f"<b>U.S.</b><br>%{{x}}: {h_hover}<extra></extra>",
                    ))
                    fig_skv.add_trace(go.Scatter(
                        x=s_sk["year"], y=s_sk["value"],
                        mode="lines+markers", name=sk_selected_name,
                        line=dict(color=TEAL, width=2.5), marker=dict(size=5),
                        hovertemplate=f"<b>{sk_selected_name}</b><br>%{{x}}: {h_hover}<extra></extra>",
                    ))
                    _base_layout(fig_skv, title=f"{sk_selected_name} vs. U.S. — {sk_quarter} {storage_lbl} Stocks{hist_sfx}", height=380)
                    fig_skv.update_yaxes(tickformat=h_ytick, ticksuffix=h_ysuffix)
                    col_r.plotly_chart(fig_skv, use_container_width=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 4 — REVISION TRACKER
# ═════════════════════════════════════════════════════════════════════════════
with tab_revisions:
    # Map friendly labels → actual COMMODITIES metric keys
    rev_opts = {}
    for m in metric_list:
        if   "Planted"   in m: rev_opts.setdefault("Planted Acres",   m)
        elif "Harvested" in m: rev_opts.setdefault("Harvested Acres", m)
        elif "Yield"     in m: rev_opts.setdefault("Yield",           m)
        elif "Production" in m: rev_opts.setdefault("Production",     m)

    if not rev_opts:
        st.info(f"No revision data available for {commodity}.")
    else:
        # ── Controls row ─────────────────────────────────────────────────────
        rev_metric_lbl = st.radio(
            "Revision metric",
            list(rev_opts.keys()),
            horizontal=True,
            label_visibility="collapsed",
            key="rev_metric",
        )
        rev_metric = rev_opts[rev_metric_lbl]
        st.markdown("<div style='margin-bottom:6px'></div>", unsafe_allow_html=True)

        rev_level = st.radio(
            "Level",
            ["National", "State"],
            horizontal=True,
            label_visibility="collapsed",
            key="rev_level",
        )
        rev_state_abbr = rev_state_name = None
        if rev_level == "State":
            _sc, _ = st.columns([3, 9])
            rev_state_abbr = _sc.selectbox(
                "State",
                sorted(STATE_ABBREV.values()),
                key="rev_state",
            )
            rev_state_name = ABBREV_STATE.get(rev_state_abbr, "").title()
        st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

        # Revision period order for this metric type
        _is_acres = ("Acres" in rev_metric_lbl)
        rev_period_list = REVISION_PERIODS_ACRES if _is_acres else REVISION_PERIODS_YLDPROD

        rev_y0 = THIS_YEAR - 9
        rev_y1 = THIS_YEAR

        # ── Load data ─────────────────────────────────────────────────────────
        with st.spinner("Loading revision history from USDA NASS..."):
            rev_df_raw = load_revision_data(
                commodity, rev_metric, rev_y0, rev_y1,
                agg_level="STATE" if rev_level == "State" else "NATIONAL",
            )

        if rev_df_raw.empty:
            _cm, _cb = st.columns([5, 1])
            _cm.warning(f"No revision data found for {commodity} — {rev_metric_lbl}.")
            if _cb.button("🔄 Retry", key="retry_rev"):
                st.cache_data.clear(); st.rerun()
        else:
            # Filter to selected state
            rev_df = rev_df_raw.copy()
            if rev_level == "State" and rev_state_abbr:
                rev_df = rev_df[rev_df["state_abbr"] == rev_state_abbr].copy()

            # Keep only known revision periods and apply short labels
            rev_df = rev_df[rev_df["period"].isin(rev_period_list)].copy()
            rev_df["period_lbl"] = rev_df["period"].map(PERIOD_SHORT).fillna(rev_df["period"])

            # Ordered list of labels that are actually present
            all_labels    = [PERIOD_SHORT.get(p, p) for p in rev_period_list]
            present_lbls  = [l for l in all_labels if l in rev_df["period_lbl"].unique()]

            rev_df["period_cat"] = pd.Categorical(
                rev_df["period_lbl"], categories=all_labels, ordered=True)
            rev_df = rev_df.sort_values(["year", "period_cat"])

            if rev_df.empty or not present_lbls:
                st.info(
                    f"NASS does not publish interim {rev_metric_lbl} estimates — "
                    f"only the final annual value is available for {commodity}."
                )
            else:
                years_avail = sorted(rev_df["year"].unique())
                n_yrs       = len(years_avail)
                yr_colors   = (_REV_PALETTE * 2)[:n_yrs]   # cycle if somehow >10
                yr_colors[-1] = AMBER                       # most recent = amber

                loc_lbl = f" — {rev_state_name}" if rev_state_name else " — U.S. National"

                # ── Section header ────────────────────────────────────────────
                st.markdown(
                    f"<p style='color:{GRAY};font-size:12px;font-weight:700;"
                    f"text-transform:uppercase;letter-spacing:.06em;margin:4px 0 6px'>"
                    f"10-Year Estimate Revision Path — {rev_metric_lbl}{loc_lbl}</p>",
                    unsafe_allow_html=True,
                )

                # ── Chart 1: Line/dot revision paths ─────────────────────────
                fig_rev = go.Figure()
                for i, yr in enumerate(years_avail):
                    ydf = rev_df[rev_df["year"] == yr].sort_values("period_cat")
                    if ydf.empty: continue
                    is_latest = (yr == years_avail[-1])
                    fig_rev.add_trace(go.Scatter(
                        x=ydf["period_lbl"],
                        y=ydf["value"],
                        mode="lines+markers",
                        name=str(yr),
                        line=dict(color=yr_colors[i], width=2.5 if is_latest else 1.5),
                        marker=dict(size=9 if is_latest else 5, color=yr_colors[i]),
                        opacity=1.0 if is_latest else 0.75,
                        hovertemplate=(
                            f"<b>{yr}</b><br>"
                            "%{x}: %{y:,.2f}" if _is_acres else
                            f"<b>{yr}</b><br>%{{x}}: %{{y:{_ytick(rev_metric)}}}"
                        ) + "<extra></extra>",
                    ))

                _base_layout(fig_rev, height=440)
                fig_rev.update_layout(
                    xaxis=dict(
                        categoryorder="array", categoryarray=present_lbls,
                        gridcolor=GRID_CLR, tickfont=dict(color=TXT_SEC, size=11),
                        title=dict(text="Reporting Period", font=dict(color=GRAY, size=11)),
                    ),
                    yaxis=dict(
                        tickformat=_ytick(rev_metric),
                        title=dict(text=_tbl_unit(rev_metric), font=dict(color=GRAY, size=11)),
                    ),
                    legend=dict(
                        orientation="h", yanchor="bottom", y=1.02,
                        xanchor="left", x=0, font=dict(size=11, color=TXT),
                    ),
                    hovermode="x unified",
                )
                st.plotly_chart(fig_rev, use_container_width=True)

                # ── Trend callout ─────────────────────────────────────────────
                if len(present_lbls) >= 2 and "Final" in present_lbls:
                    _first_lbl   = present_lbls[0]
                    _completed   = [y for y in years_avail[:-1]][-3:]  # last 3 complete years
                    _rev_changes = []
                    for yr in _completed:
                        _ydf  = rev_df[rev_df["year"] == yr]
                        _vf   = _ydf.loc[_ydf["period_lbl"] == _first_lbl,  "value"]
                        _vfin = _ydf.loc[_ydf["period_lbl"] == "Final",     "value"]
                        if not _vf.empty and not _vfin.empty and _vf.iloc[0] != 0:
                            _rev_changes.append((_vfin.iloc[0] - _vf.iloc[0]) / _vf.iloc[0] * 100)
                    if _rev_changes:
                        _avg_chg   = sum(_rev_changes) / len(_rev_changes)
                        _all_up    = all(c > 0 for c in _rev_changes)
                        _all_down  = all(c < 0 for c in _rev_changes)
                        _direction = "higher" if _avg_chg > 0 else "lower"
                        _consist   = "consistently" if (_all_up or _all_down) else "generally"
                        _clr       = GREEN if _avg_chg > 0 else RED
                        _loc       = f"{rev_state_name} " if rev_state_name else ""
                        st.markdown(
                            f"<div style='background:{CARD_BG};border-left:4px solid {_clr};"
                            f"border-radius:6px;padding:10px 16px;margin:4px 0 18px'>"
                            f"<span style='color:{TXT_SEC};font-size:11px;font-weight:700;"
                            f"text-transform:uppercase;letter-spacing:.05em'>Recent Revision Trend</span><br>"
                            f"<span style='color:{TXT};font-size:13px'>"
                            f"Over the last {len(_rev_changes)} completed crop years, USDA has "
                            f"{_consist} revised {_loc}<b>{rev_metric_lbl}</b> "
                            f"<b style='color:{_clr}'>{_direction}</b> from "
                            f"<b>{_first_lbl}</b> to <b>Final</b> "
                            f"(average: <b style='color:{_clr}'>{_avg_chg:+.1f}%</b>)."
                            f"</span></div>",
                            unsafe_allow_html=True,
                        )

                # ── Chart 2: Period-to-Period column chart ────────────────────
                st.markdown("---")
                st.markdown(
                    f"<p style='color:{GRAY};font-size:12px;font-weight:700;"
                    f"text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px'>"
                    f"Period Comparison — select start &amp; end checkpoints</p>",
                    unsafe_allow_html=True,
                )

                # Only offer curated key checkpoints in the comparison dropdowns;
                # the line chart above already shows every available period.
                _key_pool = KEY_CMP_ACRES if _is_acres else KEY_CMP_YLDPROD
                _cmp_opts = [p for p in _key_pool if p in present_lbls]

                if len(_cmp_opts) >= 2:
                    _ca, _cb2, _cc = st.columns([2, 2, 2])
                    _from_lbl = _ca.selectbox(
                        "From",
                        _cmp_opts[:-1],
                        key="rev_from",
                    )
                    _to_opts  = [p for p in _cmp_opts
                                 if _cmp_opts.index(p) > _cmp_opts.index(_from_lbl)]
                    _to_lbl   = _cb2.selectbox(
                        "To",
                        _to_opts if _to_opts else [_cmp_opts[-1]],
                        index=len(_to_opts) - 1 if _to_opts else 0,
                        key="rev_to",
                    )
                    _col_view = _cc.radio(
                        "View as",
                        ["% Change", "Absolute"],
                        horizontal=True,
                        label_visibility="visible",
                        key="rev_view",
                    )

                    _comp_rows = []
                    for yr in years_avail:
                        _ydf   = rev_df[rev_df["year"] == yr]
                        _vs    = _ydf.loc[_ydf["period_lbl"] == _from_lbl, "value"]
                        _ve    = _ydf.loc[_ydf["period_lbl"] == _to_lbl,   "value"]
                        if not _vs.empty and not _ve.empty:
                            vs, ve = _vs.iloc[0], _ve.iloc[0]
                            delta  = ((ve - vs) / vs * 100) if _col_view == "% Change" else (ve - vs)
                            _comp_rows.append({"year": yr, "delta": delta,
                                               "v_start": vs, "v_end": ve})

                    if _comp_rows:
                        _comp_df  = pd.DataFrame(_comp_rows).dropna(subset=["delta"])
                        _avg_d    = _comp_df["delta"].mean()
                        _bar_clrs = [GREEN if d >= 0 else RED for d in _comp_df["delta"]]

                        if _col_view == "% Change":
                            _yt, _ys = "+.1f", "%"
                            _txt_fn  = lambda d: f"{d:+.1f}%"
                        else:
                            _yt, _ys = ",.0f", ""
                            _txt_fn  = lambda d: _nom_chg_str(d, rev_metric)

                        fig_col = go.Figure()
                        fig_col.add_trace(go.Bar(
                            x=_comp_df["year"].astype(str),
                            y=_comp_df["delta"],
                            marker_color=_bar_clrs,
                            text=[_txt_fn(d) for d in _comp_df["delta"]],
                            textposition="outside",
                            textfont=dict(color=WHITE, size=11),
                            hovertemplate=(
                                "<b>%{x}</b><br>"
                                + f"{_from_lbl} → {_to_lbl}: %{{y:{_yt}}}{_ys}<br>"
                                + "From: %{customdata[0]}<br>"
                                + "To:   %{customdata[1]}"
                                + "<extra></extra>"
                            ),
                            customdata=list(zip(
                                _comp_df["v_start"].apply(lambda v: _bar_label(v, rev_metric)),
                                _comp_df["v_end"].apply(lambda v: _bar_label(v, rev_metric)),
                            )),
                        ))
                        # Average line
                        fig_col.add_hline(
                            y=_avg_d, line_dash="dash",
                            line_color=AMBER, line_width=1.5,
                            annotation_text=f"Avg {_avg_d:+.1f}{_ys}",
                            annotation_position="top right",
                            annotation_font_color=AMBER,
                        )
                        fig_col.add_hline(y=0, line_color=GRAY, line_width=0.8)

                        _col_title = (
                            f"{rev_metric_lbl}: {_from_lbl} → {_to_lbl}{loc_lbl}"
                        )
                        _base_layout(fig_col, title=_col_title, height=390)
                        fig_col.update_yaxes(tickformat=_yt, ticksuffix=_ys)
                        fig_col.update_layout(showlegend=False)
                        st.plotly_chart(fig_col, use_container_width=True)
                    else:
                        st.info(
                            f"No years with data for both **{_from_lbl}** and **{_to_lbl}**. "
                            f"Try a different period pair."
                        )
                else:
                    st.info(
                        "Not enough key checkpoints found in NASS for this metric — "
                        "try a different commodity or metric."
                    )

# ═════════════════════════════════════════════════════════════════════════════
# TAB 5 — WASDE / World S&D  (FAS PSD)
# ═════════════════════════════════════════════════════════════════════════════
with tab_wasde:
    import calendar as _cal

    # ══════════════════════════════════════════════════════════════════════════
    # 1 — Filter Panel
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("⚙️  Filters", expanded=True):
        _fw1, _fw2, _fw3 = st.columns([2, 2, 4])

        _w_year_list = list(range(2000, THIS_YEAR + 1))
        _w_yr_beg = _fw1.selectbox(
            "Begin Year", _w_year_list,
            index=_w_year_list.index(max(2010, THIS_YEAR - 14)),
            key="w_yr_beg",
        )
        _w_yr_end = _fw2.selectbox(
            "End Year", _w_year_list,
            index=len(_w_year_list) - 1,
            key="w_yr_end",
        )
        _w_comm_list = [c for c in PSD_CODE]
        _w_comm = _fw3.selectbox(
            "Commodity",
            _w_comm_list,
            index=_w_comm_list.index(commodity) if commodity in _w_comm_list else 0,
            key="w_comm_f",
        )
        _w_psd_code = PSD_CODE.get(_w_comm, "")

        if not _w_psd_code:
            st.info(f"WASDE data not available for **{_w_comm}**.")
            st.stop()

        _fw4, _fw5 = st.columns([3, 2])
        with st.spinner("Loading country list…"):
            _w_ctry_map = load_psd_countries()
        _w_ctry_opts = ["World"] + [
            f"{name} ({code})" for code, name in _w_ctry_map.items()
            if code and code not in ("World",)
        ]
        _w_ctry_sel = _fw4.multiselect(
            "Countries / Groupings", _w_ctry_opts,
            default=["World"],
            key="w_ctry_f",
        )
        _w_remove_sel = _fw5.multiselect(
            "Countries to Remove",
            [o for o in _w_ctry_opts if o != "World"],
            placeholder="e.g. China (removed from World totals)",
            key="w_remove_f",
        )

        _fw6, _fw7, _fw8 = st.columns([3, 2, 3])
        _W_CAT_OPTS = [
            "Production", "Dom. Consumption", "Exports", "Imports",
            "Ending Stocks", "Beginning Stocks", "Total Supply",
        ]
        _W_CAT_ATTR = {
            "Production": "Production",
            "Dom. Consumption": "Dom. Consumption",
            "Exports": "Exports",
            "Imports": "Imports",
            "Ending Stocks": "Ending Stocks",
            "Beginning Stocks": "Beginning Stocks",
            "Total Supply": "Total Supply",
        }
        _w_cat = _fw6.selectbox("Category", _W_CAT_OPTS, key="w_cat_f")
        _w_cat_attr = _W_CAT_ATTR[_w_cat]
        _w_units_choice = _fw7.radio(
            "Units", ["Metric", "Imperial"], horizontal=True, key="w_units_f",
        )

        # Compare Report selector for Δ LR
        _today_d = date.today()
        _cur_rpt_m, _cur_rpt_y = _today_d.month, _today_d.year
        if _today_d.day < 13:
            _cur_rpt_m -= 1
            if _cur_rpt_m == 0:
                _cur_rpt_m = 12
                _cur_rpt_y -= 1
        _lr_opts: list[tuple[int, int, str]] = []
        _tmp_m, _tmp_y = _cur_rpt_m, _cur_rpt_y
        for _ in range(18):
            _tmp_m -= 1
            if _tmp_m == 0:
                _tmp_m = 12
                _tmp_y -= 1
            _lr_opts.append((_tmp_y, _tmp_m, f"{_cal.month_abbr[_tmp_m]}-{str(_tmp_y)[-2:]}"))
        _lr_labels = [f"{lbl} ({_cal.month_name[m]} {y})" for y, m, lbl in _lr_opts]
        _lr_idx = _fw8.selectbox(
            "Compare Report (for Δ LR)",
            range(len(_lr_labels)),
            format_func=lambda i: _lr_labels[i],
            key="w_lr_f",
        )
        _lr_year, _lr_month, _lr_label = _lr_opts[_lr_idx]

    # ── Shared setup ──────────────────────────────────────────────────────────
    def _parse_cc(s: str) -> str:
        return "World" if s == "World" else s.rsplit("(", 1)[-1].rstrip(")")

    def _cc_name(cc: str) -> str:
        return "World" if cc == "World" else _w_ctry_map.get(cc, cc)

    _w_ctry_codes = [_parse_cc(s) for s in _w_ctry_sel] if _w_ctry_sel else ["World"]
    _w_remove_codes = [_parse_cc(s) for s in _w_remove_sel] if _w_remove_sel else []
    _w_view_yrs = list(range(max(2000, _w_yr_beg), _w_yr_end + 1))

    _MMT_TO_MILBU = {
        "Corn": 39.3683, "Soybeans": 36.7437, "Wheat": 36.7437,
        "Barley": 39.3683, "Sorghum": 39.3683,
        "Canola": 44.0924, "Peanuts": 44.0924, "Rice": 44.0924,
        "Cotton": 1.0,
    }
    _conv_f = _MMT_TO_MILBU.get(_w_comm, 1.0)

    def _w_unit_label() -> str:
        if _w_units_choice == "Imperial":
            return "Mil. Bu" if _w_comm != "Cotton" else "Mil. Bales"
        return "MMT"

    def _w_divisor(df: pd.DataFrame | None = None) -> float:
        if df is not None and not df.empty:
            ul, d = _psd_unit_label(df)
            if "bu" in ul.lower():
                return d
        if _w_units_choice == "Imperial":
            return 1000.0 / _conv_f
        return 1000.0

    def _load_cc(cc: str, yr: int) -> pd.DataFrame:
        if cc == "World":
            return load_psd_world_year(_w_psd_code, yr)
        return load_psd_country_year(_w_psd_code, cc, yr)

    def _get_val(cc: str, yr: int, attr_key: str) -> float | None:
        df = _load_cc(cc, yr)
        v = _psd_attr(df, attr_key)
        if v is not None and cc == "World" and _w_remove_codes:
            for rc in _w_remove_codes:
                if rc == "World":
                    continue
                rm_v = _psd_attr(load_psd_country_year(_w_psd_code, rc, yr), attr_key)
                if rm_v is not None:
                    v -= rm_v
        return v

    _WTH  = (f"padding:7px 12px;text-align:right;background:{TEAL_DIM};color:{WHITE};"
             f"font-weight:700;font-size:11px;white-space:nowrap;border-bottom:2px solid {TEAL};")
    _WTH0 = (f"padding:7px 12px;text-align:left;background:{TEAL_DIM};color:{WHITE};"
             f"font-weight:700;font-size:11px;border-bottom:2px solid {TEAL};")
    _WTHD = (f"padding:7px 12px;text-align:right;background:{CARD_BG};color:{TXT};"
             f"font-weight:700;font-size:11px;white-space:nowrap;"
             f"border-bottom:2px solid {TEAL};border-left:2px solid {BORDER};")

    def _w_row_style(row_type: str, alt: bool) -> tuple[str, str, str]:
        if row_type == "total":
            return "#f0f9fa", TEAL_DIM, TEAL_DIM
        if row_type == "stocks":
            return "#e6f4f6", TEAL_DIM, TEAL_DIM
        bg = WHITE if not alt else "#f9fafb"
        return bg, TXT, TXT_SEC

    def _w_chg_cell(cur: float | None, prev: float | None, divisor: float) -> tuple[str, str, str]:
        if cur is None or prev is None or prev == 0:
            return "—", GRAY, "transparent"
        chg = (cur - prev) / divisor
        if abs(chg) < 0.05:
            return f"{'+'if chg>=0 else ''}{chg:.1f}", GRAY, "transparent"
        if chg > 0:
            return f"+{chg:.1f}", "#4ade80", "rgba(34,197,94,0.12)"
        return f"{chg:.1f}", "#f87171", "rgba(239,68,68,0.12)"

    # ══════════════════════════════════════════════════════════════════════════
    # 2 — Ranking Table
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("🏆  Ranking Table", expanded=True):
        _rk1, _rk2, _rk3, _rk4 = st.columns([5, 2, 1, 1])
        _rnk_view = _rk1.radio(
            "View", ["Current", "Δ LR", "Δ LY", "Δ 5YA"],
            horizontal=True, key="rnk_view",
            label_visibility="collapsed",
        )
        _rnk_topn  = _rk2.selectbox("Show", [10, 15, 20, 25, 50], index=1, key="rnk_topn")
        _rnk_pct   = _rk3.checkbox("% World", key="rnk_pct")
        _rnk_other = _rk4.checkbox("Other", key="rnk_other")

        _rnk_yr  = _w_yr_end
        _rnk_yrs = list(range(_rnk_yr - 5, _rnk_yr + 1))
        with st.spinner("Loading ranking data…"):
            _rnk_all_dfs = {yr: load_psd_all_countries_year(_w_psd_code, yr) for yr in _rnk_yrs}

        _cur_cats  = _get_ctry_attr(_rnk_all_dfs.get(_rnk_yr, pd.DataFrame()), _w_cat_attr)
        _ly_cats   = _get_ctry_attr(_rnk_all_dfs.get(_rnk_yr - 1, pd.DataFrame()), _w_cat_attr)
        _world_tot = _cur_cats.get("World") or 0

        _avg5: dict = {}
        for _cc0 in _cur_cats:
            _priors = [
                _get_ctry_attr(_rnk_all_dfs.get(yr, pd.DataFrame()), _w_cat_attr).get(_cc0)
                for yr in _rnk_yrs[:-1]
            ]
            _valid = [v for v in _priors if v is not None]
            _avg5[_cc0] = sum(_valid) / len(_valid) if _valid else None

        _rnk_rows: list[dict] = []
        for _cc0, _v0 in sorted(_cur_cats.items(), key=lambda kv: kv[1] or 0, reverse=True):
            if not _cc0 or _cc0 == "World" or _cc0 in _w_remove_codes:
                continue
            _rnk_rows.append({
                "code": _cc0, "name": _w_ctry_map.get(_cc0, _cc0),
                "cur": _v0, "ly": _ly_cats.get(_cc0), "avg5": _avg5.get(_cc0),
            })

        _top_rows = _rnk_rows[:_rnk_topn]
        _other_val = sum(r["cur"] or 0 for r in _rnk_rows[_rnk_topn:])

        if not _top_rows:
            st.warning("No ranking data returned from FAS PSD — API may be temporarily unavailable.")
        else:
            _rnk_div = _w_divisor(_rnk_all_dfs.get(_rnk_yr, pd.DataFrame()))
            _rnk_ul  = _w_unit_label()
            _show_chg = _rnk_view != "Current"
            _rth0 = (f"padding:7px 10px;text-align:left;background:{TEAL_DIM};color:{WHITE};"
                     f"font-weight:700;font-size:11px;border-bottom:2px solid {TEAL};")
            _rth  = (f"padding:7px 10px;text-align:right;background:{TEAL_DIM};color:{WHITE};"
                     f"font-weight:700;font-size:11px;white-space:nowrap;border-bottom:2px solid {TEAL};")
            _rthd = (f"padding:7px 10px;text-align:right;background:{CARD_BG};color:{TXT};"
                     f"font-weight:700;font-size:11px;white-space:nowrap;"
                     f"border-bottom:2px solid {TEAL};border-left:2px solid {BORDER};")
            _rth_pct = (f"padding:7px 10px;text-align:right;background:{TEAL_DIM};color:{TEAL};"
                        f"font-weight:700;font-size:11px;white-space:nowrap;border-bottom:2px solid {TEAL};")
            _chg_hdr = {"Δ LR": "Δ LR", "Δ LY": "Δ LY", "Δ 5YA": "Δ 5YA"}.get(_rnk_view, "")
            _rnk_head = (
                f"<thead><tr>"
                f"<th style='{_rth0}'>#</th>"
                f"<th style='{_rth0}'>Country</th>"
                f"<th style='{_rth}'>{_rnk_yr} ({_rnk_ul})</th>"
                + (f"<th style='{_rth_pct}'>% World</th>" if _rnk_pct and _world_tot else "")
                + (f"<th style='{_rthd}'>{_chg_hdr}</th>" if _show_chg else "")
                + "</tr></thead>"
            )
            _rnk_body = ""
            for _ri, _rrow in enumerate(_top_rows, 1):
                _bg = WHITE if _ri % 2 == 1 else "#f9fafb"
                _cur_disp = f"{_rrow['cur'] / _rnk_div:,.1f}" if _rrow["cur"] is not None else "—"
                _pct_s = (f"{_rrow['cur'] / _world_tot * 100:.1f}%"
                          if (_rnk_pct and _world_tot and _rrow["cur"]) else "")
                if _rnk_view == "Δ LY":
                    _ct, _cc_c, _cb = _w_chg_cell(_rrow["cur"], _rrow["ly"], _rnk_div)
                elif _rnk_view == "Δ 5YA":
                    _ct, _cc_c, _cb = _w_chg_cell(_rrow["cur"], _rrow["avg5"], _rnk_div)
                else:
                    _ct, _cc_c, _cb = "—", GRAY, "transparent"
                _rnk_body += (
                    f"<tr>"
                    f"<td style='padding:6px 10px;background:{_bg};color:{TXT_SEC};font-size:12px'>{_ri}</td>"
                    f"<td style='padding:6px 10px;background:{_bg};color:{TXT};font-weight:600;font-size:12px'>{_rrow['name']}</td>"
                    f"<td style='padding:6px 10px;text-align:right;background:{_bg};color:{AMBER};font-weight:700;font-size:12px'>{_cur_disp}</td>"
                    + (f"<td style='padding:6px 10px;text-align:right;background:{_bg};color:{TXT_SEC};font-size:12px'>{_pct_s}</td>" if _rnk_pct and _world_tot else "")
                    + (f"<td style='padding:6px 10px;text-align:right;background:{_cb};color:{_cc_c};font-weight:700;font-size:12px;border-left:1px solid {BORDER}'>{_ct}</td>" if _show_chg else "")
                    + "</tr>"
                )
            if _rnk_other and _other_val:
                _rnk_body += (
                    f"<tr>"
                    f"<td style='padding:6px 10px;background:{CARD_BG};color:{TXT_SEC};font-size:12px'>…</td>"
                    f"<td style='padding:6px 10px;background:{CARD_BG};color:{TXT_SEC};font-weight:600;font-size:12px'>"
                    f"Other ({len(_rnk_rows) - _rnk_topn} countries)</td>"
                    f"<td style='padding:6px 10px;text-align:right;background:{CARD_BG};color:{TXT_SEC};font-weight:700;font-size:12px'>"
                    f"{_other_val / _rnk_div:,.1f}</td>"
                    + (f"<td></td>" if _rnk_pct and _world_tot else "")
                    + (f"<td></td>" if _show_chg else "")
                    + "</tr>"
                )
            st.markdown(
                f"<div style='overflow-x:auto;border-radius:8px;border:1px solid {BORDER};margin-bottom:16px'>"
                f"<table style='border-collapse:collapse;width:100%;font-family:Open Sans,sans-serif'>"
                f"{_rnk_head}<tbody>{_rnk_body}</tbody></table></div>",
                unsafe_allow_html=True,
            )
            if _rnk_view == "Δ LR":
                st.caption("⚠️ Country-level Δ LR requires monthly WASDE snapshots. See S&D Table for US Δ LR detail.")

            _bx = [r["cur"] / _rnk_div if r["cur"] else 0 for r in _top_rows]
            _by = [r["name"] for r in _top_rows]
            fig_rnk = go.Figure(go.Bar(
                x=_bx, y=_by, orientation="h",
                marker_color=[TEAL if i < 3 else TEAL_DIM for i in range(len(_top_rows))],
                text=[f"{v:,.1f}" for v in _bx],
                textposition="outside",
                textfont=dict(color=WHITE, size=9),
            ))
            _base_layout(fig_rnk,
                         title=f"{_w_comm} {_w_cat} — Top {_rnk_topn} ({_rnk_yr}, {_rnk_ul})",
                         height=max(340, len(_top_rows) * 26))
            fig_rnk.update_xaxes(tickformat=",.1f", title=_rnk_ul)
            fig_rnk.update_yaxes(autorange="reversed")
            fig_rnk.update_layout(showlegend=False)
            st.plotly_chart(fig_rnk, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # 3 — Supply & Demand Table
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("📊  Supply & Demand Table", expanded=True):
        _sd_c1, _sd_c2, _sd_c3 = st.columns([5, 2, 3])
        _sd_view = _sd_c1.radio(
            "View", ["Current", "Δ LR", "Δ LY", "Δ 5YA"],
            horizontal=True, key="sd_view",
            label_visibility="collapsed",
        )
        _sd_units = _sd_c2.radio("Units", ["Imperial", "Metric"], horizontal=True, key="sd_units_r")

        # Build full sorted country list: World first, US second, rest ABC
        _sd_name_to_cc = {"World": "World", **{name: code for code, name in _w_ctry_map.items() if code}}
        _sd_all_sorted = sorted(n for n in _sd_name_to_cc if n != "World")
        _us_name = _w_ctry_map.get("US", "United States")
        if _us_name in _sd_all_sorted:
            _sd_all_sorted.remove(_us_name)
            _sd_all_sorted.insert(0, _us_name)
        _sd_ctry_disp = ["World"] + _sd_all_sorted
        _sd_ctry_sel = _sd_c3.selectbox("Country", _sd_ctry_disp, key="sd_ctry")
        _sd_cc = _sd_name_to_cc.get(_sd_ctry_sel, "World")

        _sd_yrs = (_w_view_yrs[-5:] if len(_w_view_yrs) > 5 else _w_view_yrs) or [_w_yr_end]

        with st.spinner(f"Loading S&D data for {_sd_ctry_sel}…"):
            _sd_dfs = {yr: _load_cc(_sd_cc, yr) for yr in _sd_yrs}
            if _sd_view == "Δ 5YA":
                _sd_hist5 = {yr: _load_cc(_sd_cc, yr) for yr in range(_w_yr_end - 5, _w_yr_end)}
            _sd_lr_data: dict = {}
            if _sd_view == "Δ LR":
                _sd_lr_data = load_wasde_excel_month(_w_comm, _w_yr_end, _lr_year, _lr_month)

        _sd_ne = [df for df in _sd_dfs.values() if not df.empty]
        if not _sd_ne:
            st.warning(f"No data for {_sd_ctry_sel} — FAS PSD may be temporarily unavailable.")
        else:
            _raw_ul, _raw_div = _psd_unit_label(_sd_ne[0])
            _is_bu = "bu" in _raw_ul.lower()
            if _sd_units == "Imperial":
                _sd_div = _raw_div if _is_bu else (1000.0 / _conv_f)
                _sd_ul  = "Mil. Bu" if not _is_bu else _raw_ul
            else:
                _sd_div = _raw_div if _is_bu else 1000.0
                _sd_ul  = _raw_ul if not _is_bu else "MMT"

            _sd5_avg: dict = {}
            if _sd_view == "Δ 5YA":
                for _ak, _, _ in PSD_BS_ROWS:
                    _vs = [_psd_attr(_sd_hist5.get(yr, pd.DataFrame()), _ak)
                           for yr in range(_w_yr_end - 5, _w_yr_end)]
                    _vv = [v for v in _vs if v is not None]
                    _sd5_avg[_ak] = sum(_vv) / len(_vv) if _vv else None

            def _sd_ref(ak: str) -> float | None:
                if _sd_view == "Δ LY":
                    return _psd_attr(_sd_dfs.get(_w_yr_end - 1, pd.DataFrame()), ak)
                if _sd_view == "Δ 5YA":
                    return _sd5_avg.get(ak)
                if _sd_view == "Δ LR":
                    return _sd_lr_data.get(ak) if _sd_lr_data else None
                return None

            _sd_chg_hdr = {"Δ LR": f"Δ LR ({_lr_label})", "Δ LY": "Δ LY", "Δ 5YA": "Δ 5YA"}.get(_sd_view, "")
            _show_sd_chg = _sd_view != "Current"
            _sd_ncols = len(_sd_yrs) + (1 if _show_sd_chg else 0)

            st.markdown(
                f"<p style='color:{GRAY};font-size:12px;font-weight:700;text-transform:uppercase;"
                f"letter-spacing:.06em;margin:8px 0 6px'>"
                f"{_sd_ctry_sel} — {_w_comm} Balance Sheet &nbsp;·&nbsp; "
                f"<span style='color:{TEAL}'>{_sd_ul}</span></p>",
                unsafe_allow_html=True,
            )

            _sd_yr_hdrs = "".join(f"<th style='{_WTH}'>{yr}</th>" for yr in _sd_yrs)
            _sd_head = (
                f"<thead><tr><th style='{_WTH0}'>Item</th>{_sd_yr_hdrs}"
                + (f"<th style='{_WTHD}'>{_sd_chg_hdr}</th>" if _show_sd_chg else "")
                + "</tr></thead>"
            )
            _sd_body = ""
            _sd_alt = 0
            for attr_key, disp_lbl, row_type in PSD_BS_ROWS:
                vals = {yr: _psd_attr(_sd_dfs.get(yr, pd.DataFrame()), attr_key) for yr in _sd_yrs}
                if all(v is None for v in vals.values()):
                    continue
                bg, lbl_c, num_c = _w_row_style(row_type, _sd_alt % 2 == 1)
                if row_type not in ("total", "stocks"):
                    _sd_alt += 1
                fw = "700" if row_type in ("total", "stocks") else "400"
                _td0 = (f"padding:6px 12px;text-align:left;background:{bg};color:{lbl_c};"
                        f"font-weight:{fw};font-size:12px;")
                _tdn = (f"padding:6px 12px;text-align:right;background:{bg};color:{num_c};"
                        f"font-weight:{fw};font-size:12px;")
                yr_cells = "".join(
                    f"<td style='{_tdn}'>{_psd_fmt(vals[yr], _sd_div)}</td>" for yr in _sd_yrs)
                if attr_key == "Ending Stocks":
                    _sd_body += f"<tr><td colspan='{_sd_ncols + 1}' style='height:2px;background:{TEAL_DIM}'></td></tr>"
                _sd_body += f"<tr><td style='{_td0}'>{disp_lbl}</td>{yr_cells}"
                if _show_sd_chg:
                    _ref = _sd_ref(attr_key)
                    _ct2, _cc2, _cb2 = _w_chg_cell(vals.get(_w_yr_end), _ref, _sd_div)
                    _tdc = (f"padding:6px 12px;text-align:right;background:{_cb2};"
                            f"color:{_cc2};font-weight:700;font-size:12px;border-left:2px solid {BORDER};")
                    _sd_body += f"<td style='{_tdc}'>{_ct2}</td>"
                _sd_body += "</tr>"

            # S/U row
            _su_row = []
            for yr in _sd_yrs:
                _es = _psd_attr(_sd_dfs.get(yr, pd.DataFrame()), "Ending Stocks")
                _tc = _psd_attr(_sd_dfs.get(yr, pd.DataFrame()), "Dom. Consumption")
                _ex = _psd_attr(_sd_dfs.get(yr, pd.DataFrame()), "Exports")
                _tu = (_tc or 0) + (_ex or 0)
                _su_row.append(_es / _tu * 100 if (_es is not None and _tu > 0) else None)
            _su_ref_v = None
            if _sd_view == "Δ LY":
                _es2 = _psd_attr(_sd_dfs.get(_w_yr_end - 1, pd.DataFrame()), "Ending Stocks")
                _tc2 = _psd_attr(_sd_dfs.get(_w_yr_end - 1, pd.DataFrame()), "Dom. Consumption")
                _ex2 = _psd_attr(_sd_dfs.get(_w_yr_end - 1, pd.DataFrame()), "Exports")
                _tu2 = (_tc2 or 0) + (_ex2 or 0)
                _su_ref_v = _es2 / _tu2 * 100 if (_es2 and _tu2) else None
            elif _sd_view == "Δ 5YA":
                _su_ps = []
                for yr5 in range(_w_yr_end - 5, _w_yr_end):
                    _df5 = _sd_hist5.get(yr5, pd.DataFrame())
                    _e5 = _psd_attr(_df5, "Ending Stocks")
                    _t5 = _psd_attr(_df5, "Dom. Consumption")
                    _x5 = _psd_attr(_df5, "Exports")
                    _u5 = (_t5 or 0) + (_x5 or 0)
                    if _e5 and _u5:
                        _su_ps.append(_e5 / _u5 * 100)
                _su_ref_v = sum(_su_ps) / len(_su_ps) if _su_ps else None
            elif _sd_view == "Δ LR" and _sd_lr_data:
                _es_lr = _sd_lr_data.get("Ending Stocks")
                _tc_lr = _sd_lr_data.get("Dom. Consumption")
                _ex_lr = _sd_lr_data.get("Exports")
                _tu_lr = (_tc_lr or 0) + (_ex_lr or 0)
                _su_ref_v = _es_lr / _tu_lr * 100 if (_es_lr and _tu_lr) else None

            _su_bg = "#e6f4f6"
            _sd_body += (
                f"<tr><td colspan='{_sd_ncols + 1}' style='height:2px;background:{TEAL_DIM}'></td></tr>"
                f"<tr><td style='padding:6px 12px;text-align:left;background:{_su_bg};"
                f"color:{AMBER};font-weight:700;font-size:12px;'>Stocks / Use Ratio</td>"
            )
            for _sv in _su_row:
                _sd_body += (
                    f"<td style='padding:6px 12px;text-align:right;background:{_su_bg};"
                    f"color:{AMBER};font-weight:700;font-size:12px;'>"
                    f"{'—' if _sv is None else f'{_sv:.1f}%'}</td>"
                )
            if _show_sd_chg:
                _su_cur2 = _su_row[-1] if _su_row else None
                _su_chg2 = (_su_cur2 - _su_ref_v) if (_su_cur2 is not None and _su_ref_v is not None) else None
                _su_cc3 = "#4ade80" if (_su_chg2 or 0) < 0 else ("#f87171" if (_su_chg2 or 0) > 0 else GRAY)
                _sd_body += (
                    f"<td style='padding:6px 12px;text-align:right;background:rgba(245,158,11,0.08);"
                    f"color:{_su_cc3};font-weight:700;font-size:12px;border-left:2px solid {BORDER};'>"
                    f"{'—' if _su_chg2 is None else f'{_su_chg2:+.1f} pp'}</td>"
                )
            _sd_body += "</tr>"

            st.markdown(
                f"<div style='overflow-x:auto;border-radius:8px;border:1px solid {BORDER};margin-bottom:18px'>"
                f"<table style='border-collapse:collapse;width:100%;font-family:Open Sans,sans-serif'>"
                f"{_sd_head}<tbody>{_sd_body}</tbody></table></div>",
                unsafe_allow_html=True,
            )
            if _sd_view == "Δ LR":
                if _sd_lr_data:
                    st.caption(f"✅ Δ LR sourced from the {_lr_label} USDA WASDE Excel file.")
                else:
                    st.caption(f"⚠️ {_lr_label} WASDE Excel not available — try a different Compare Report month.")

            # Supply vs Use chart
            _chart_yrs2 = _w_view_yrs[-10:] if len(_w_view_yrs) >= 10 else _w_view_yrs
            with st.spinner("Loading history chart…"):
                _sd_hist_ch = {yr: _load_cc(_sd_cc, yr) for yr in _chart_yrs2}
            _prod_v = [_psd_attr(_sd_hist_ch.get(yr, pd.DataFrame()), "Production") for yr in _chart_yrs2]
            _dom_v  = [_psd_attr(_sd_hist_ch.get(yr, pd.DataFrame()), "Dom. Consumption") for yr in _chart_yrs2]
            _exp_v  = [_psd_attr(_sd_hist_ch.get(yr, pd.DataFrame()), "Exports") for yr in _chart_yrs2]
            _es_v   = [_psd_attr(_sd_hist_ch.get(yr, pd.DataFrame()), "Ending Stocks") for yr in _chart_yrs2]
            _su_hist2 = []
            for _i2 in range(len(_chart_yrs2)):
                _tc2b = _dom_v[_i2]; _ex2b = _exp_v[_i2]; _es2b = _es_v[_i2]
                _tu2b = (_tc2b or 0) + (_ex2b or 0)
                _su_hist2.append(_es2b / _tu2b * 100 if (_es2b is not None and _tu2b > 0) else None)

            def _safe2(lst): return [v / _sd_div if v is not None else None for v in lst]

            _col_l, _col_r = st.columns(2, gap="medium")
            fig_su2 = go.Figure()
            fig_su2.add_trace(go.Bar(name="Production", x=_chart_yrs2, y=_safe2(_prod_v),
                                     marker_color=TEAL, opacity=0.85))
            fig_su2.add_trace(go.Bar(name="Dom. Consumption", x=_chart_yrs2, y=_safe2(_dom_v),
                                     marker_color="#e06c75", opacity=0.85))
            fig_su2.add_trace(go.Bar(name="Exports", x=_chart_yrs2, y=_safe2(_exp_v),
                                     marker_color=AMBER, opacity=0.75))
            fig_su2.add_trace(go.Scatter(name="End. Stocks", x=_chart_yrs2, y=_safe2(_es_v),
                                         mode="lines+markers", yaxis="y2",
                                         line=dict(color=TXT_SEC, width=2, dash="dot"),
                                         marker=dict(size=5)))
            _base_layout(fig_su2, title=f"{_sd_ctry_sel} {_w_comm} — Supply vs Use ({_sd_ul})", height=380)
            fig_su2.update_layout(
                barmode="group",
                yaxis=dict(title=_sd_ul, tickformat=",.1f"),
                yaxis2=dict(title=f"End. Stocks ({_sd_ul})", overlaying="y",
                            side="right", showgrid=False),
                legend=dict(orientation="h", y=-0.18, x=0),
            )
            _col_l.plotly_chart(fig_su2, use_container_width=True)

            _su_clrs2 = ["#4ade80" if (v or 99) < 15 else AMBER if (v or 99) < 20 else "#f87171"
                         for v in _su_hist2]
            fig_ratio2 = go.Figure(go.Bar(
                x=_chart_yrs2, y=_su_hist2, marker_color=_su_clrs2,
                text=[f"{v:.1f}%" if v is not None else "" for v in _su_hist2],
                textposition="outside", textfont=dict(color=WHITE, size=9),
            ))
            _base_layout(fig_ratio2, title=f"{_sd_ctry_sel} {_w_comm} — S/U Ratio (%)", height=380)
            fig_ratio2.update_yaxes(ticksuffix="%", tickformat=".1f")
            fig_ratio2.update_layout(showlegend=False)
            _col_r.plotly_chart(fig_ratio2, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # 4 — Time Series Chart
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("📈  Time Series Chart", expanded=True):
        _ts1, _ts2, _ts3, _ts4 = st.columns([4, 2, 1, 2])
        _ts_view = _ts1.radio(
            "View", ["Current", "Δ LR", "Δ LY", "Δ 5YA"],
            horizontal=True, key="ts_view", label_visibility="collapsed",
        )
        _ts_type   = _ts2.radio("Chart", ["Line", "Bar"], horizontal=True, key="ts_type")
        _ts_labels = _ts3.checkbox("Labels", key="ts_labels")
        _ts_seg    = _ts4.checkbox("Segment Countries", key="ts_seg")

        _ts_yrs = _w_view_yrs
        _ts_div = _w_divisor()
        _ts_ul  = _w_unit_label()

        with st.spinner("Loading time series…"):
            _ts_raw: dict = {}
            for _cc_ts in _w_ctry_codes:
                _ts_raw[_cc_ts] = {yr: _get_val(_cc_ts, yr, _w_cat_attr) for yr in _ts_yrs}

        if _ts_view in ("Δ LY", "Δ 5YA"):
            _ts_ref: dict = {}
            for _cc_ts in _w_ctry_codes:
                _ts_ref[_cc_ts] = {}
                for yr in _ts_yrs:
                    if _ts_view == "Δ LY":
                        _ts_ref[_cc_ts][yr] = _ts_raw[_cc_ts].get(yr - 1)
                    else:
                        _ps = [_ts_raw[_cc_ts].get(y) for y in range(yr - 5, yr)]
                        _pv = [v for v in _ps if v is not None]
                        _ts_ref[_cc_ts][yr] = sum(_pv) / len(_pv) if _pv else None

        fig_ts = go.Figure()
        _ts_colors = [TEAL, AMBER, "#e06c75", "#61afef", "#c678dd", "#56b6c2", WHITE]
        for _ci, _cc_ts in enumerate(_w_ctry_codes):
            _clr = _ts_colors[_ci % len(_ts_colors)]
            _lbl = _cc_name(_cc_ts)
            if _w_remove_codes and _cc_ts == "World":
                _lbl += " (excl. " + ", ".join(_cc_name(rc) for rc in _w_remove_codes) + ")"
            if _ts_view == "Current":
                _ys = [(_ts_raw[_cc_ts].get(yr) / _ts_div)
                       if _ts_raw[_cc_ts].get(yr) is not None else None for yr in _ts_yrs]
            elif _ts_view in ("Δ LY", "Δ 5YA"):
                _ys = []
                for yr in _ts_yrs:
                    _cur2 = _ts_raw[_cc_ts].get(yr)
                    _ref2 = _ts_ref[_cc_ts].get(yr)
                    _ys.append((_cur2 - _ref2) / _ts_div
                               if (_cur2 is not None and _ref2 is not None) else None)
            else:
                _ys = [(_ts_raw[_cc_ts].get(yr) / _ts_div)
                       if _ts_raw[_cc_ts].get(yr) is not None else None for yr in _ts_yrs]

            if _ts_type == "Bar":
                fig_ts.add_trace(go.Bar(
                    x=_ts_yrs, y=_ys, name=_lbl, marker_color=_clr,
                    text=[f"{v:.1f}" for v in _ys if v is not None] if _ts_labels else None,
                    textposition="outside" if _ts_labels else None,
                    textfont=dict(color=WHITE, size=9) if _ts_labels else None,
                ))
            else:
                fig_ts.add_trace(go.Scatter(
                    x=_ts_yrs, y=_ys, name=_lbl, mode="lines+markers",
                    line=dict(color=_clr, width=2), marker=dict(size=5),
                    text=[f"{v:.1f}" if v is not None else "" for v in _ys] if _ts_labels else None,
                    textposition="top center" if _ts_labels else None,
                    textfont=dict(color=WHITE, size=9) if _ts_labels else None,
                ))

        _ts_sfx = {
            "Current": "", "Δ LR": f" (Δ vs {_lr_label})",
            "Δ LY": " (Δ vs Prior Year)", "Δ 5YA": " (Δ vs 5-Yr Avg)",
        }.get(_ts_view, "")
        _base_layout(fig_ts, title=f"{_w_comm} {_w_cat}{_ts_sfx} ({_ts_ul})", height=440)
        if _ts_type == "Bar":
            fig_ts.update_layout(barmode="group" if len(_w_ctry_codes) > 1 else "relative")
        fig_ts.update_yaxes(tickformat=",.1f", title=_ts_ul, zeroline=True, zerolinecolor=GRAY)
        fig_ts.update_layout(legend=dict(orientation="h", y=-0.15, x=0), hovermode="x unified")
        if _ts_view == "Δ LR":
            st.caption("⚠️ Δ LR time series uses current FAS PSD data — historical monthly snapshots not available for trend view.")
        st.plotly_chart(fig_ts, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # 5 — World Map
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("🗺️  World Map", expanded=False):
        _mp1, _mp2 = st.columns([4, 2])
        _mp_view = _mp1.radio(
            "View", ["Current", "Δ LY", "Δ 5YA"],
            horizontal=True, key="mp_view", label_visibility="collapsed",
        )

        with st.spinner("Loading map data…"):
            _mp_df = load_psd_all_countries_year(_w_psd_code, _w_yr_end)
            _mp_ly_df = (load_psd_all_countries_year(_w_psd_code, _w_yr_end - 1)
                         if _mp_view == "Δ LY" else pd.DataFrame())
            _mp_hist = ({yr: load_psd_all_countries_year(_w_psd_code, yr)
                         for yr in range(_w_yr_end - 5, _w_yr_end)}
                        if _mp_view == "Δ 5YA" else {})

        if _mp_df.empty:
            st.warning("No world data for map — FAS PSD API may be temporarily unavailable.")
        else:
            _mp_div  = _w_divisor(_mp_df)
            _mp_ul   = _w_unit_label()
            _mp_cur  = _get_ctry_attr(_mp_df, _w_cat_attr)

            if _mp_view == "Δ LY":
                _mp_ly   = _get_ctry_attr(_mp_ly_df, _w_cat_attr)
                _mp_plot = {cc: (v - _mp_ly[cc]) / _mp_div
                            for cc, v in _mp_cur.items()
                            if cc != "World" and v is not None and _mp_ly.get(cc) is not None}
                _mp_title = f"{_w_comm} {_w_cat} Δ LY ({_w_yr_end}, {_mp_ul})"
            elif _mp_view == "Δ 5YA":
                _mp_ref_d = {}
                for cc in _mp_cur:
                    _ps = [_get_ctry_attr(_mp_hist.get(yr, pd.DataFrame()), _w_cat_attr).get(cc)
                           for yr in range(_w_yr_end - 5, _w_yr_end)]
                    _pv = [v for v in _ps if v is not None]
                    _mp_ref_d[cc] = sum(_pv) / len(_pv) if _pv else None
                _mp_plot = {cc: (v - _mp_ref_d[cc]) / _mp_div
                            for cc, v in _mp_cur.items()
                            if cc != "World" and v is not None and _mp_ref_d.get(cc) is not None}
                _mp_title = f"{_w_comm} {_w_cat} Δ 5YA ({_w_yr_end}, {_mp_ul})"
            else:
                _mp_plot = {cc: v / _mp_div for cc, v in _mp_cur.items()
                            if cc != "World" and v is not None}
                _mp_title = f"{_w_comm} {_w_cat} by Country ({_w_yr_end}, {_mp_ul})"

            for _rc in _w_remove_codes:
                _mp_plot.pop(_rc, None)

            _PSD_ISO3 = {
                "US": "USA", "BR": "BRA", "AR": "ARG", "CN": "CHN", "IN": "IND",
                "UA": "UKR", "RU": "RUS", "CA": "CAN", "AU": "AUS",
                "FR": "FRA", "DE": "DEU", "PL": "POL", "RO": "ROU",
                "MX": "MEX", "PH": "PHL", "EG": "EGY", "NG": "NGA",
                "ET": "ETH", "VN": "VNM", "TH": "THA", "ID": "IDN",
                "JP": "JPN", "KR": "KOR", "TR": "TUR", "PK": "PAK",
                "BD": "BGD", "ZA": "ZAF", "DZ": "DZA", "IQ": "IRQ",
                "IR": "IRN", "MY": "MYS", "KZ": "KAZ", "MZ": "MOZ",
                "TZ": "TZA", "SD": "SDN", "MA": "MAR", "PE": "PER",
                "CO": "COL", "CL": "CHL", "VE": "VEN", "BO": "BOL",
                "PY": "PRY", "UY": "URY", "GB": "GBR", "ES": "ESP",
                "IT": "ITA", "PT": "PRT", "HU": "HUN", "RS": "SRB",
                "GH": "GHA", "CI": "CIV", "KE": "KEN", "UG": "UGA",
                "ZM": "ZMB", "MW": "MWI", "ZW": "ZWE", "AO": "AGO",
                "CM": "CMR", "BA": "BIH", "SO": "SOM",
            }
            _mp_iso3, _mp_z, _mp_names = [], [], []
            for cc, v in _mp_plot.items():
                iso = _PSD_ISO3.get(cc)
                if iso:
                    _mp_iso3.append(iso)
                    _mp_z.append(v)
                    _mp_names.append(_w_ctry_map.get(cc, cc))

            if _mp_iso3:
                fig_map = go.Figure(go.Choropleth(
                    locations=_mp_iso3, z=_mp_z, text=_mp_names,
                    colorscale="RdYlGn" if _mp_view != "Current" else "Teal",
                    reversescale=(_mp_view == "Current"),
                    colorbar=dict(title=_mp_ul, thickness=14, len=0.6),
                    marker_line_color="#4a5568", marker_line_width=0.5,
                ))
                fig_map.update_layout(
                    title=dict(text=_mp_title, font=dict(color=TXT, size=14)),
                    paper_bgcolor=PAGE_BG, plot_bgcolor=PAGE_BG,
                    geo=dict(
                        bgcolor=PAGE_BG, showframe=False,
                        showcoastlines=True, coastlinecolor=BORDER,
                        showland=True, landcolor="#f0f0f0",
                        showocean=True, oceancolor="#cce5f0",
                        showlakes=False, projection_type="natural earth",
                    ),
                    margin=dict(l=0, r=0, t=40, b=0), height=480,
                )
                st.plotly_chart(fig_map, use_container_width=True)
            else:
                st.info("No country-level data available for this commodity/category.")

    # ══════════════════════════════════════════════════════════════════════════
    # 6 — Pie Chart
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("🥧  Pie Chart", expanded=False):
        _pie1, _pie2 = st.columns([3, 2])
        _pie_view = _pie1.radio(
            "View", ["Current", "Δ LY", "Δ 5YA"],
            horizontal=True, key="pie_view", label_visibility="collapsed",
        )
        _pie_topn = _pie2.selectbox("Show top", [10, 15, 20], key="pie_topn")

        with st.spinner("Loading pie data…"):
            _pie_df = load_psd_all_countries_year(_w_psd_code, _w_yr_end)
            _pie_ly = (load_psd_all_countries_year(_w_psd_code, _w_yr_end - 1)
                       if _pie_view == "Δ LY" else pd.DataFrame())

        if not _pie_df.empty:
            _pie_div  = _w_divisor(_pie_df)
            _pie_ul   = _w_unit_label()
            _pie_raw  = _get_ctry_attr(_pie_df, _w_cat_attr)
            if _pie_view == "Δ LY" and not _pie_ly.empty:
                _pie_ly_r = _get_ctry_attr(_pie_ly, _w_cat_attr)
                _pie_disp = {cc: abs(v - _pie_ly_r.get(cc, v)) / _pie_div
                             for cc, v in _pie_raw.items()
                             if cc != "World" and v is not None and _pie_ly_r.get(cc) is not None}
                _pie_title = f"{_w_comm} {_w_cat} — YoY Change Share ({_w_yr_end})"
            else:
                _pie_disp = {cc: v / _pie_div for cc, v in _pie_raw.items()
                             if cc != "World" and v is not None and v > 0}
                _pie_title = f"{_w_comm} {_w_cat} — Country Shares ({_w_yr_end}, {_pie_ul})"
            for _rc in _w_remove_codes:
                _pie_disp.pop(_rc, None)
            _pie_sorted = sorted(_pie_disp.items(), key=lambda kv: kv[1], reverse=True)
            _pie_top    = _pie_sorted[:_pie_topn]
            _pie_other  = sum(v for _, v in _pie_sorted[_pie_topn:])
            _pie_labels = [_w_ctry_map.get(cc, cc) for cc, _ in _pie_top]
            _pie_vals   = [v for _, v in _pie_top]
            if _pie_other > 0:
                _pie_labels.append("Other")
                _pie_vals.append(_pie_other)
            _PCLRS = [TEAL, AMBER, "#e06c75", "#61afef", "#c678dd",
                      "#56b6c2", "#98c379", "#d19a66", "#7f848e",
                      "#528bff", "#be5046", "#21c7a8", GRAY]
            fig_pie = go.Figure(go.Pie(
                labels=_pie_labels, values=_pie_vals,
                marker=dict(colors=_PCLRS[:len(_pie_labels)],
                            line=dict(color=PAGE_BG, width=1)),
                textfont=dict(color=TXT, size=11), hole=0.3,
            ))
            fig_pie.update_layout(
                title=dict(text=_pie_title, font=dict(color=TXT, size=14)),
                paper_bgcolor=PAGE_BG, plot_bgcolor=PAGE_BG,
                legend=dict(font=dict(color=TXT, size=11), bgcolor="rgba(0,0,0,0)"),
                margin=dict(t=60, b=20), height=480,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # 7 — Bar Chart
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("📊  Bar Chart", expanded=False):
        _bar2c1, _bar2c2 = st.columns([4, 2])
        _bar2_view = _bar2c1.radio(
            "View", ["Current", "Δ LY", "Δ 5YA"],
            horizontal=True, key="bar2_view", label_visibility="collapsed",
        )
        _bar2_topn = _bar2c2.selectbox("Show top", [10, 15, 20, 25], index=1, key="bar2_topn")

        with st.spinner("Loading bar data…"):
            _bar2_df = load_psd_all_countries_year(_w_psd_code, _w_yr_end)
            _bar2_ly = (load_psd_all_countries_year(_w_psd_code, _w_yr_end - 1)
                        if _bar2_view == "Δ LY" else pd.DataFrame())
            _bar2_hist = ({yr: load_psd_all_countries_year(_w_psd_code, yr)
                           for yr in range(_w_yr_end - 5, _w_yr_end)}
                          if _bar2_view == "Δ 5YA" else {})

        if not _bar2_df.empty:
            _bar2_div  = _w_divisor(_bar2_df)
            _bar2_ul   = _w_unit_label()
            _bar2_cur  = _get_ctry_attr(_bar2_df, _w_cat_attr)
            if _bar2_view == "Δ LY":
                _bar2_ly_r = _get_ctry_attr(_bar2_ly, _w_cat_attr)
                _bar2_vals = {cc: (v - _bar2_ly_r[cc]) / _bar2_div
                              for cc, v in _bar2_cur.items()
                              if cc != "World" and v is not None and _bar2_ly_r.get(cc) is not None}
                _bar2_title = f"{_w_comm} {_w_cat} YoY Change — Top {_bar2_topn} ({_w_yr_end})"
            elif _bar2_view == "Δ 5YA":
                _bar2_ref = {}
                for cc in _bar2_cur:
                    _ps = [_get_ctry_attr(_bar2_hist.get(yr, pd.DataFrame()), _w_cat_attr).get(cc)
                           for yr in range(_w_yr_end - 5, _w_yr_end)]
                    _pv = [v for v in _ps if v is not None]
                    _bar2_ref[cc] = sum(_pv) / len(_pv) if _pv else None
                _bar2_vals = {cc: (v - _bar2_ref[cc]) / _bar2_div
                              for cc, v in _bar2_cur.items()
                              if cc != "World" and v is not None and _bar2_ref.get(cc) is not None}
                _bar2_title = f"{_w_comm} {_w_cat} Δ 5YA — Top {_bar2_topn} ({_w_yr_end})"
            else:
                _bar2_vals = {cc: v / _bar2_div for cc, v in _bar2_cur.items()
                              if cc != "World" and v is not None}
                _bar2_title = f"{_w_comm} {_w_cat} — Top {_bar2_topn} Countries ({_w_yr_end}, {_bar2_ul})"
            for _rc in _w_remove_codes:
                _bar2_vals.pop(_rc, None)
            _bar2_srt  = sorted(_bar2_vals.items(), key=lambda kv: abs(kv[1]), reverse=True)[:_bar2_topn]
            _bar2_nms  = [_w_ctry_map.get(cc, cc) for cc, _ in _bar2_srt]
            _bar2_ys   = [v for _, v in _bar2_srt]
            _bar2_clrs = (
                ["#4ade80" if v >= 0 else "#f87171" for v in _bar2_ys]
                if _bar2_view != "Current"
                else [TEAL if i < 3 else TEAL_DIM for i in range(len(_bar2_ys))]
            )
            fig_bar2 = go.Figure(go.Bar(
                x=_bar2_ys, y=_bar2_nms, orientation="h",
                marker_color=_bar2_clrs,
                text=[f"{v:+,.1f}" if _bar2_view != "Current" else f"{v:,.1f}" for v in _bar2_ys],
                textposition="outside", textfont=dict(color=WHITE, size=9),
            ))
            _base_layout(fig_bar2, title=_bar2_title, height=max(340, len(_bar2_ys) * 26))
            fig_bar2.update_xaxes(tickformat=",.1f", title=_bar2_ul)
            fig_bar2.update_yaxes(autorange="reversed")
            fig_bar2.update_layout(showlegend=False)
            st.plotly_chart(fig_bar2, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # 8 — WASDE Revision History
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("📅  WASDE Revision History", expanded=False):
        _hist_mkt_yr = _w_yr_end
        st.markdown(
            f"<p style='color:{GRAY};font-size:12px;font-weight:700;text-transform:uppercase;"
            f"letter-spacing:.06em;margin:4px 0 10px'>"
            f"Monthly WASDE Revision History — {_w_comm} "
            f"<span style='color:{TEAL}'>{_hist_mkt_yr}/{str(_hist_mkt_yr+1)[-2:]}</span></p>",
            unsafe_allow_html=True,
        )
        _hist_comm_metric_keys = _HIST_METRIC_MAP.get(_w_comm, {})
        _hist_nass_metrics = {k: v for k, v in _hist_comm_metric_keys.items() if v is not None}

        _hist_cols: list[tuple[str, str, int]] = []
        _yr1_s = str(_hist_mkt_yr)[-2:]
        _yr2_s = str(_hist_mkt_yr + 1)[-2:]
        for _disp, _period, _yr_off in _WASDE_HIST_PERIODS:
            _sfx = _yr1_s if _yr_off == 0 else _yr2_s
            _hist_cols.append((f"{_disp}-{_sfx}", _period, _hist_mkt_yr + _yr_off))

        with st.spinner("Loading NASS monthly forecast data…"):
            _nass_data: dict[str, dict[str, float | None]] = {m: {} for m in _hist_nass_metrics}
            for _col_lbl, _period, _nass_yr in _hist_cols:
                for _metric_lbl, _comm_key in _hist_nass_metrics.items():
                    _nass_data[_metric_lbl][_col_lbl] = load_national_period_snapshot(
                        _w_comm, _comm_key, _nass_yr, _period)

        _excel_report_months: list[tuple[str, int, int]] = [
            (f"May-{_yr1_s}",  _hist_mkt_yr,     5),
            (f"Jun-{_yr1_s}",  _hist_mkt_yr,     6),
            (f"Jul-{_yr1_s}",  _hist_mkt_yr,     7),
            (f"Aug-{_yr1_s}",  _hist_mkt_yr,     8),
            (f"Sep-{_yr1_s}",  _hist_mkt_yr,     9),
            (f"Oct-{_yr1_s}",  _hist_mkt_yr,    10),
            (f"Nov-{_yr1_s}",  _hist_mkt_yr,    11),
            (f"Dec-{_yr1_s}",  _hist_mkt_yr,    12),
            (f"Jan-{_yr2_s}",  _hist_mkt_yr + 1, 1),
            (f"Feb-{_yr2_s}",  _hist_mkt_yr + 1, 2),
            (f"Mar-{_yr2_s}",  _hist_mkt_yr + 1, 3),
            (f"Apr-{_yr2_s}",  _hist_mkt_yr + 1, 4),
            (f"May-{_yr2_s}",  _hist_mkt_yr + 1, 5),
            (f"Jun-{_yr2_s}",  _hist_mkt_yr + 1, 6),
            (f"Jul-{_yr2_s}",  _hist_mkt_yr + 1, 7),
            (f"Aug-{_yr2_s}",  _hist_mkt_yr + 1, 8),
        ]
        _today_ym = (date.today().year, date.today().month)
        _excel_report_months = [
            (lbl, yr, mo) for lbl, yr, mo in _excel_report_months if (yr, mo) <= _today_ym
        ]
        _excel_data: dict[str, dict[str, float | None]] = {}
        _excel_cols_loaded: list[str] = []
        if _excel_report_months:
            with st.spinner(f"Downloading {len(_excel_report_months)} monthly WASDE files…"):
                for _col_lbl, _rep_yr, _rep_mo in _excel_report_months:
                    _ex = load_wasde_excel_month(_w_comm, _hist_mkt_yr, _rep_yr, _rep_mo)
                    if _ex:
                        _excel_data[_col_lbl] = _ex
                        _excel_cols_loaded.append(_col_lbl)

        _all_col_labels_ordered: list[str] = []
        _seen_cols: set = set()
        for _cl, _yr_ex, _mo_ex in _excel_report_months:
            if _cl not in _seen_cols:
                _all_col_labels_ordered.append(_cl)
                _seen_cols.add(_cl)
        for _cl, _pd2, _ny in _hist_cols:
            if _cl not in _seen_cols:
                _all_col_labels_ordered.append(_cl)
                _seen_cols.add(_cl)
        _col_labels_display = _all_col_labels_ordered

        _bs_rows_hist = [
            ("Area Harvested",         "Area Harvested",        "supply"),
            ("Yield",                  "Yield",                 "supply"),
            ("_sep1", "", "divider"),
            ("Beginning Stocks",       "Beg. Stocks",           "stocks"),
            ("Production",             "Production",            "supply"),
            ("Imports",                "Imports",               "supply"),
            ("Total Supply",           "Total Supply",          "total"),
            ("_sep2", "", "divider"),
            ("Exports",                "Exports",               "use"),
            ("Feed Dom. Consumption",  "Feed / Residual",       "use"),
            ("FSI Dom. Consumption",   "Food / Seed / Indust.", "use"),
            ("Dom. Consumption",       "Dom. Consumption",      "use"),
            ("_sep3", "", "divider"),
            ("Ending Stocks",          "Ending Stocks",         "stocks"),
        ]
        _ht_col_count = len(_col_labels_display) + 1
        _hist_th  = (f"padding:6px 8px;text-align:right;background:{TEAL_DIM};color:{WHITE};"
                     f"font-weight:700;font-size:10px;white-space:nowrap;border-bottom:2px solid {TEAL};")
        _hist_th0 = (f"padding:6px 10px;text-align:left;background:{TEAL_DIM};color:{WHITE};"
                     f"font-weight:700;font-size:10px;border-bottom:2px solid {TEAL};min-width:140px;")
        _hthead = f"<thead><tr><th style='{_hist_th0}'>Item</th>"
        for _cl in _col_labels_display:
            _cl_clr = TEAL if _cl in _excel_data else WHITE
            _hthead += f"<th style='{_hist_th}color:{_cl_clr}'>{_cl}</th>"
        _hthead += "</tr></thead>"

        _htbody = ""
        _alt_h = 0
        for _row_key, _row_lbl, _row_type in _bs_rows_hist:
            if _row_type == "divider":
                _htbody += f"<tr><td colspan='{_ht_col_count}' style='height:2px;background:{TEAL_DIM}'></td></tr>"
                continue
            _bg, _lbl_c, _num_c = _w_row_style(_row_type, _alt_h % 2 == 1)
            if _row_type not in ("total", "stocks"):
                _alt_h += 1
            _fw = "700" if _row_type in ("total", "stocks") else "400"
            _htd0 = (f"padding:5px 10px;text-align:left;background:{_bg};color:{_lbl_c};"
                     f"font-weight:{_fw};font-size:11px;white-space:nowrap;")
            _htdn = (f"padding:5px 8px;text-align:right;background:{_bg};color:{_num_c};"
                     f"font-weight:{_fw};font-size:11px;")
            _htbody += f"<tr><td style='{_htd0}'>{_row_lbl}</td>"
            for _cl in _col_labels_display:
                _val = None
                if _row_key in _nass_data:
                    _val = _nass_data[_row_key].get(_cl)
                if _val is None and _cl in _excel_data:
                    _val = _excel_data[_cl].get(_row_key)
                if _val is None:
                    _cell_str = "—"
                elif _row_key == "Yield":
                    _cell_str = f"{_val:.1f}"
                elif _row_key == "Area Harvested":
                    _cell_str = f"{_val:,.1f}"
                else:
                    _cell_str = f"{_val:,.0f}"
                _htbody += f"<td style='{_htdn}'>{_cell_str}</td>"
            _htbody += "</tr>"

        _htbody += f"<tr><td colspan='{_ht_col_count}' style='height:2px;background:{TEAL_DIM}'></td></tr>"
        _su_lbl_td = (f"padding:5px 10px;text-align:left;background:#e6f4f6;"
                      f"color:{AMBER};font-weight:700;font-size:11px;")
        _su_val_td = (f"padding:5px 8px;text-align:right;background:#e6f4f6;"
                      f"color:{AMBER};font-weight:700;font-size:11px;")
        _htbody += f"<tr><td style='{_su_lbl_td}'>Stocks / Use</td>"
        for _cl in _col_labels_display:
            _es_h = (_excel_data.get(_cl) or {}).get("Ending Stocks")
            _dc_h = (_excel_data.get(_cl) or {}).get("Dom. Consumption")
            _ex_h = (_excel_data.get(_cl) or {}).get("Exports")
            if _es_h is not None and (_dc_h is not None or _ex_h is not None):
                _tu_h = (_dc_h or 0) + (_ex_h or 0)
                _su_h = _es_h / _tu_h * 100 if _tu_h > 0 else None
                _su_str = f"{_su_h:.1f}%" if _su_h is not None else "—"
            else:
                _su_str = "—"
            _htbody += f"<td style='{_su_val_td}'>{_su_str}</td>"
        _htbody += "</tr>"

        st.markdown(
            f"<div style='overflow-x:auto;border-radius:8px;border:1px solid {BORDER};margin-bottom:12px'>"
            f"<table style='border-collapse:collapse;font-family:Open Sans,sans-serif;width:100%'>"
            f"{_hthead}<tbody>{_htbody}</tbody></table></div>",
            unsafe_allow_html=True,
        )
        if _excel_data:
            st.markdown(
                f"<p style='color:{TEAL};font-size:11px;margin:0'>🟢 Teal column headers = USDA WASDE Excel balance sheet data.</p>",
                unsafe_allow_html=True,
            )

    # ══════════════════════════════════════════════════════════════════════════
    # 9 — Multi-Commodity S/U
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("📈  Multi-Commodity S/U", expanded=False):
        _msu_y0  = _w_yr_end - 14
        _msu_yrs = list(range(_msu_y0, _w_yr_end + 1))
        _scope   = st.radio("Scope", ["US", "World"], horizontal=True, key="su_scope")

        with st.spinner("Loading multi-commodity S/U data…"):
            _su_data2: dict = {}
            for _cn, _cc_su in PSD_SU_COMMODITIES:
                _su_data2[_cn] = {}
                for yr in _msu_yrs:
                    df_yr = (load_psd_country_year(_cc_su, "US", yr) if _scope == "US"
                             else load_psd_world_year(_cc_su, yr))
                    _es = _psd_attr(df_yr, "Ending Stocks")
                    _tc = _psd_attr(df_yr, "Dom. Consumption")
                    _ex = _psd_attr(df_yr, "Exports")
                    _tu = (_tc or 0) + (_ex or 0)
                    _su_data2[_cn][yr] = _es / _tu * 100 if (_es is not None and _tu > 0) else None

        fig_multi = go.Figure()
        _su_colors_m = [TEAL, AMBER, "#e06c75"]
        for _i_m, (_cn, _cc_su) in enumerate(PSD_SU_COMMODITIES):
            _series = [_su_data2[_cn].get(yr) for yr in _msu_yrs]
            fig_multi.add_trace(go.Scatter(
                x=_msu_yrs, y=_series, name=_cn,
                mode="lines+markers",
                line=dict(color=_su_colors_m[_i_m], width=2.5),
                marker=dict(size=6),
            ))
        _base_layout(fig_multi,
                     title=f"{'US' if _scope == 'US' else 'World'} Stocks-to-Use — Corn / Soybeans / Wheat",
                     height=460)
        fig_multi.update_yaxes(ticksuffix="%", tickformat=".1f", title="S/U Ratio (%)")
        fig_multi.update_layout(
            legend=dict(orientation="h", y=-0.12, x=0.3),
            hovermode="x unified",
        )
        for _lvl, _llbl, _lclr in [(15, "Tight (15%)", "#f87171"), (20, "Normal (20%)", AMBER)]:
            fig_multi.add_hline(y=_lvl, line_dash="dot", line_color=_lclr, line_width=1,
                                annotation_text=_llbl, annotation_font_color=_lclr,
                                annotation_position="top right")
        st.plotly_chart(fig_multi, use_container_width=True)

        _sum_rows = ""
        for _cn, _cc_su in PSD_SU_COMMODITIES:
            _cur_su = _su_data2[_cn].get(_w_yr_end)
            _prv_su = _su_data2[_cn].get(_w_yr_end - 1)
            _cur_str = f"{_cur_su:.1f}%" if _cur_su is not None else "—"
            _prv_str = f"{_prv_su:.1f}%" if _prv_su is not None else "—"
            _chg_su  = (_cur_su - _prv_su) if (_cur_su is not None and _prv_su is not None) else None
            _chg_str = f"{_chg_su:+.1f} pp" if _chg_su is not None else "—"
            _chg_clr_su = "#4ade80" if (_chg_su or 0) < 0 else ("#f87171" if (_chg_su or 0) > 0 else GRAY)
            _sum_rows += (
                f"<tr>"
                f"<td style='padding:7px 14px;color:{TXT};font-weight:600;font-size:12px'>{_cn}</td>"
                f"<td style='padding:7px 14px;text-align:right;color:{GRAY};font-size:12px'>{_prv_str}</td>"
                f"<td style='padding:7px 14px;text-align:right;color:{AMBER};font-weight:700;font-size:12px'>{_cur_str}</td>"
                f"<td style='padding:7px 14px;text-align:right;color:{_chg_clr_su};font-weight:700;font-size:12px'>{_chg_str}</td>"
                f"</tr>"
            )
        _sum_th = (
            f"<thead><tr>"
            f"<th style='{_WTH0}'>Commodity</th>"
            f"<th style='{_WTH}'>{_w_yr_end - 1} S/U</th>"
            f"<th style='{_WTH}'>{_w_yr_end} S/U</th>"
            f"<th style='{_WTHD}'>YoY Change</th>"
            f"</tr></thead>"
        )
        st.markdown(
            f"<div style='overflow-x:auto;border-radius:8px;border:1px solid {BORDER};"
            f"margin-bottom:12px;margin-top:8px'>"
            f"<table style='border-collapse:collapse;width:50%;font-family:Open Sans,sans-serif;"
            f"background:{CARD_BG}'>"
            f"{_sum_th}<tbody>{_sum_rows}</tbody></table></div>",
            unsafe_allow_html=True,
        )

# ═════════════════════════════════════════════════════════════════════════════
# TAB 6 — GRAIN STORAGE CAPACITY  (NASS on-farm + off-farm)
# ═════════════════════════════════════════════════════════════════════════════
with tab_storage_cap:
    _OFF_DESC = "GRAIN STORAGE CAPACITY, OFF FARM - CAPACITY, MEASURED IN BU"
    _ON_DESC  = "GRAIN STORAGE CAPACITY, ON FARM - CAPACITY, MEASURED IN BU"

    with st.spinner("Loading NASS grain storage capacity..."):
        _sc_all = load_nass_storage_capacity(1990, THIS_YEAR)

    if _sc_all.empty:
        st.warning("NASS grain storage capacity data unavailable.")
    else:
        _sc_yrs     = sorted(_sc_all["year"].unique(), reverse=True)
        _sc_yr_opts = [int(y) for y in _sc_yrs]

        # ── Year selector ─────────────────────────────────────────────────
        _sc_col, _ = st.columns([2, 8])
        _sc_sel_yr = _sc_col.selectbox(
            "Year", _sc_yr_opts, key="sc_yr", index=0)
        _sc_yr_str = int(_sc_sel_yr)

        # ── KPI row ───────────────────────────────────────────────────────
        _sc_yr_df = _sc_all[_sc_all["year"] == _sc_yr_str]
        _sc_off   = _sc_yr_df[_sc_yr_df["short_desc"].str.contains("OFF FARM", na=False)]
        _sc_on    = _sc_yr_df[_sc_yr_df["short_desc"].str.contains("ON FARM",  na=False)]
        _sc_tot_off = _sc_off["value_bu"].sum()
        _sc_tot_on  = _sc_on["value_bu"].sum()
        _sc_total   = _sc_tot_off + _sc_tot_on
        _sc_states  = _sc_yr_df["state_abbr"].nunique()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Licensed Capacity", f"{_sc_total/1e9:.2f}B bu")
        k2.metric("Off-Farm (Commercial)",   f"{_sc_tot_off/1e9:.2f}B bu")
        k3.metric("On-Farm",                 f"{_sc_tot_on/1e9:.2f}B bu")
        k4.metric("States Reporting",        str(_sc_states))

        st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

        # ── Stacked horizontal bar by state ───────────────────────────────
        _sc_off_s = (_sc_off[["state_abbr","value_bu"]]
                     .rename(columns={"value_bu":"off_farm"}))
        _sc_on_s  = (_sc_on[["state_abbr","value_bu"]]
                     .rename(columns={"value_bu":"on_farm"}))
        _sc_state = (_sc_off_s.merge(_sc_on_s, on="state_abbr", how="outer")
                     .fillna(0))
        _sc_state["total"] = _sc_state["off_farm"] + _sc_state["on_farm"]
        _sc_state = _sc_state.sort_values("total", ascending=True)

        fig_sc = go.Figure()
        fig_sc.add_trace(go.Bar(
            name="Off-Farm (Commercial)",
            x=_sc_state["off_farm"] / 1e9, y=_sc_state["state_abbr"],
            orientation="h", marker_color="#f97316",
            hovertemplate="Off-Farm: %{x:.3f}B bu<extra></extra>",
        ))
        fig_sc.add_trace(go.Bar(
            name="On-Farm",
            x=_sc_state["on_farm"] / 1e9, y=_sc_state["state_abbr"],
            orientation="h", marker_color="#84cc16",
            hovertemplate="On-Farm: %{x:.3f}B bu<extra></extra>",
        ))
        _base_layout(fig_sc,
                     title=f"Grain Storage Capacity by State — {_sc_yr_str} (Billion Bu)",
                     height=max(420, len(_sc_state) * 22))
        fig_sc.update_layout(barmode="stack", showlegend=True,
                             legend=dict(orientation="h", y=1.04, x=0.5,
                                         xanchor="center",
                                         font=dict(color=TXT, size=11),
                                         bgcolor="rgba(0,0,0,0)"))
        fig_sc.update_xaxes(ticksuffix="B bu")
        st.plotly_chart(fig_sc, use_container_width=True)

        # ── National trend lines ──────────────────────────────────────────
        st.markdown(
            f"<p style='color:{GRAY};font-size:12px;font-weight:700;"
            f"text-transform:uppercase;letter-spacing:.06em;margin:20px 0 6px'>"
            f"National Storage Capacity Trend</p>",
            unsafe_allow_html=True,
        )
        _sc_nat = (_sc_all.groupby(["year","short_desc"])["value_bu"]
                   .sum().reset_index())
        _sc_trend_map = {
            "OFF FARM": ("Off-Farm (Commercial)", "#f97316"),
            "ON FARM":  ("On-Farm",               "#84cc16"),
        }
        fig_sc_trend = go.Figure()
        for _key, (_lbl, _clr) in _sc_trend_map.items():
            _sub = (_sc_nat[_sc_nat["short_desc"].str.contains(_key, na=False)]
                    .sort_values("year"))
            if _sub.empty:
                continue
            fig_sc_trend.add_trace(go.Scatter(
                x=_sub["year"], y=_sub["value_bu"] / 1e9,
                mode="lines+markers", name=_lbl,
                line=dict(color=_clr, width=2),
                marker=dict(color=_clr, size=5),
                hovertemplate=f"{_lbl}: %{{y:.3f}}B bu<extra></extra>",
            ))
        _base_layout(fig_sc_trend,
                     title="National Grain Storage Capacity (Billion Bu)", height=350)
        fig_sc_trend.update_yaxes(ticksuffix="B")
        fig_sc_trend.update_layout(showlegend=True,
                                   legend=dict(orientation="h", y=1.06, x=0.5,
                                               xanchor="center",
                                               font=dict(color=TXT, size=11),
                                               bgcolor="rgba(0,0,0,0)"))
        st.plotly_chart(fig_sc_trend, use_container_width=True)

        # ── State table ───────────────────────────────────────────────────
        st.markdown(
            f"<p style='color:{GRAY};font-size:12px;font-weight:700;"
            f"text-transform:uppercase;letter-spacing:.06em;margin:20px 0 6px'>"
            f"State Detail — {_sc_yr_str}</p>",
            unsafe_allow_html=True,
        )
        _sc_tbl = _sc_state.sort_values("total", ascending=False).copy()
        _sc_tbl["Off-Farm (M Bu)"] = (_sc_tbl["off_farm"] / 1e6).round(1)
        _sc_tbl["On-Farm (M Bu)"]  = (_sc_tbl["on_farm"]  / 1e6).round(1)
        _sc_tbl["Total (M Bu)"]    = (_sc_tbl["total"]    / 1e6).round(1)
        _sc_tbl["% Off-Farm"]      = (_sc_tbl["off_farm"] / _sc_tbl["total"] * 100).round(1)
        _sc_tbl = _sc_tbl[["state_abbr","Off-Farm (M Bu)","On-Farm (M Bu)",
                            "Total (M Bu)","% Off-Farm"]].rename(
            columns={"state_abbr": "State"})
        st.dataframe(_sc_tbl, use_container_width=True, hide_index=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 7 — STORAGE vs PRODUCTION
# ═════════════════════════════════════════════════════════════════════════════
with tab_storage_vs_prod:
    _SVC_Y0 = 2015

    with st.spinner("Loading production and storage data..."):
        _svc_prod = load_multi_commodity_production(_SVC_Y0, THIS_YEAR)
        _svc_cap  = load_nass_storage_capacity(_SVC_Y0, THIS_YEAR)

    if _svc_prod.empty:
        st.warning("Production data unavailable from NASS API.")
    else:
        # ── Controls ──────────────────────────────────────────────────────
        _svc_c1, _svc_c2, _svc_c3 = st.columns([2, 3, 5])
        _svc_prod_yrs  = sorted(_svc_prod["year"].unique(), reverse=True)
        _svc_yr        = _svc_c1.selectbox("Year", _svc_prod_yrs,
                                            key="svc_yr", index=0)
        _svc_layer     = _svc_c2.radio(
            "Storage Layer",
            ["NASS Total (On+Off)", "NASS Off-Farm", "NASS On-Farm"],
            horizontal=True, key="svc_layer", label_visibility="collapsed",
        )

        # ── Build state supply pivot ───────────────────────────────────────
        def _build_svc(yr):
            pg = _svc_prod[_svc_prod["year"] == yr]
            _grp = {
                "Corn & Sorghum": ["CORN", "SORGHUM"],
                "Soybeans":       ["SOYBEANS"],
                "Wheat":          ["WHEAT"],
                "Oats":           ["OATS"],
            }
            frames_svc = []
            for lbl, grains in _grp.items():
                sub = (pg[pg["commodity_desc"].isin(grains)]
                       .groupby("state_abbr")["value_bu"].sum()
                       .reset_index().rename(columns={"value_bu": lbl}))
                frames_svc.append(sub)
            df_s = frames_svc[0]
            for f in frames_svc[1:]:
                df_s = df_s.merge(f, on="state_abbr", how="outer")
            df_s = df_s.fillna(0)
            df_s["Total Supply"] = df_s[list(_grp.keys())].sum(axis=1)

            # Storage capacity
            if not _svc_cap.empty:
                _cap_yr_avail = sorted(_svc_cap["year"].unique())
                _cap_yr = yr if yr in _cap_yr_avail else (
                    max((y for y in _cap_yr_avail if y <= yr), default=_cap_yr_avail[-1])
                )
                _cap_sub = _svc_cap[_svc_cap["year"] == _cap_yr]
                _cap_off = (_cap_sub[_cap_sub["short_desc"].str.contains("OFF FARM", na=False)]
                            .groupby("state_abbr")["value_bu"].sum().reset_index()
                            .rename(columns={"value_bu": "_off"}))
                _cap_on  = (_cap_sub[_cap_sub["short_desc"].str.contains("ON FARM", na=False)]
                            .groupby("state_abbr")["value_bu"].sum().reset_index()
                            .rename(columns={"value_bu": "_on"}))
                df_s = df_s.merge(_cap_off, on="state_abbr", how="left")
                df_s = df_s.merge(_cap_on,  on="state_abbr", how="left")
                df_s["_off"] = df_s["_off"].fillna(0)
                df_s["_on"]  = df_s["_on"].fillna(0)
                if _svc_layer == "NASS Off-Farm":
                    df_s["Storage"] = df_s["_off"]
                elif _svc_layer == "NASS On-Farm":
                    df_s["Storage"] = df_s["_on"]
                else:
                    df_s["Storage"] = df_s["_off"] + df_s["_on"]
            else:
                df_s["Storage"] = 0.0

            df_s["Ratio"]    = df_s.apply(
                lambda r: r["Storage"] / r["Total Supply"]
                if r["Total Supply"] > 0 else None, axis=1)
            df_s["Surplus"]  = df_s["Storage"] - df_s["Total Supply"]
            return df_s

        _svc_df      = _build_svc(_svc_yr)
        _svc_df_prev = _build_svc(_svc_yr - 1) if (_svc_yr - 1) in _svc_prod["year"].values else pd.DataFrame()

        # ── National KPIs ─────────────────────────────────────────────────
        _nat_sup  = _svc_df["Total Supply"].sum()
        _nat_stor = _svc_df["Storage"].sum()
        _nat_rat  = _nat_stor / _nat_sup if _nat_sup > 0 else 0
        _nat_surp = _nat_stor - _nat_sup

        _nat_sup_p  = _svc_df_prev["Total Supply"].sum() if not _svc_df_prev.empty else None
        _nat_rat_p  = ((_svc_df_prev["Storage"].sum() / _nat_sup_p)
                       if (_nat_sup_p and _nat_sup_p > 0) else None)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric(f"Total Supply ({_svc_yr})", f"{_nat_sup/1e9:.2f}B bu",
                  delta=f"{(_nat_sup - _nat_sup_p)/1e6:+.0f}M bu YoY"
                  if _nat_sup_p else None)
        k2.metric(f"{_svc_layer} Capacity",   f"{_nat_stor/1e9:.2f}B bu")
        k3.metric("Storage / Supply Ratio",   f"{_nat_rat:.2f}x",
                  delta=f"{_nat_rat - _nat_rat_p:+.2f} YoY"
                  if _nat_rat_p else None)
        k4.metric("Surplus / (Deficit)",
                  f"{_nat_surp/1e6:+.0f}M bu",
                  delta_color="normal" if _nat_surp >= 0 else "inverse")

        st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

        # ── State stacked supply bar + storage line ────────────────────────
        _svc_chart = _svc_df.sort_values("Total Supply", ascending=False).head(30)
        _com_cols   = ["Corn & Sorghum", "Soybeans", "Wheat", "Oats"]
        _com_clrs   = ["#1f5c2e", "#a8d5e8", "#e0b800", "#c0392b"]
        _line_clr   = "#444444" if "Off" in _svc_layer or "Total" in _svc_layer else "#1055aa"

        fig_svc = go.Figure()
        for _com, _clr in zip(_com_cols, _com_clrs):
            if _com not in _svc_chart.columns:
                continue
            fig_svc.add_trace(go.Bar(
                name=_com,
                x=_svc_chart["state_abbr"],
                y=_svc_chart[_com] / 1e6,
                marker_color=_clr,
                hovertemplate=f"{_com}: %{{y:,.0f}}M bu<extra></extra>",
            ))
        if _svc_chart["Storage"].sum() > 0:
            _svc_ratio_lbl = _svc_chart["Ratio"].apply(
                lambda v: f"{v:.2f}x" if pd.notna(v) else "")
            fig_svc.add_trace(go.Scatter(
                name=_svc_layer,
                x=_svc_chart["state_abbr"],
                y=_svc_chart["Storage"] / 1e6,
                mode="lines+markers+text",
                line=dict(color=_line_clr, width=2, dash="dot"),
                marker=dict(color=_line_clr, size=6),
                text=_svc_ratio_lbl, textposition="top center",
                textfont=dict(size=9, color=_line_clr),
                hovertemplate=f"{_svc_layer}: %{{y:,.0f}}M bu<extra></extra>",
            ))
        _base_layout(fig_svc,
                     title=f"Grain Supply vs {_svc_layer} by State — {_svc_yr} (Million Bu)",
                     height=460)
        fig_svc.update_layout(barmode="stack", showlegend=True,
                              legend=dict(orientation="h", y=1.05, x=0.5,
                                          xanchor="center",
                                          font=dict(color=TXT, size=11),
                                          bgcolor="rgba(0,0,0,0)"))
        fig_svc.update_yaxes(ticksuffix="M")
        st.plotly_chart(fig_svc, use_container_width=True)

        # ── Historical trend ───────────────────────────────────────────────
        st.markdown(
            f"<p style='color:{GRAY};font-size:12px;font-weight:700;"
            f"text-transform:uppercase;letter-spacing:.06em;margin:20px 0 6px'>"
            f"National Historical Trend — Supply vs {_svc_layer}</p>",
            unsafe_allow_html=True,
        )
        _hist_yrs = sorted(_svc_prod["year"].unique())
        _hist_rows = []
        for _hy in _hist_yrs:
            _hdf = _build_svc(_hy)
            _hist_rows.append({
                "year":          _hy,
                "Corn & Sorghum":_hdf["Corn & Sorghum"].sum() / 1e6,
                "Soybeans":      _hdf["Soybeans"].sum()       / 1e6,
                "Wheat":         _hdf["Wheat"].sum()           / 1e6,
                "Oats":          _hdf["Oats"].sum()            / 1e6,
                "Storage":       _hdf["Storage"].sum()         / 1e6,
            })
        _hist_df = pd.DataFrame(_hist_rows)

        fig_hist = go.Figure()
        for _com, _clr in zip(_com_cols, _com_clrs):
            if _com not in _hist_df.columns:
                continue
            fig_hist.add_trace(go.Bar(
                name=_com, x=_hist_df["year"], y=_hist_df[_com],
                marker_color=_clr,
                hovertemplate=f"{_com}: %{{y:,.0f}}M bu<extra></extra>",
            ))
        if _hist_df["Storage"].sum() > 0:
            fig_hist.add_trace(go.Scatter(
                name=_svc_layer, x=_hist_df["year"], y=_hist_df["Storage"],
                mode="lines+markers",
                line=dict(color=_line_clr, width=2, dash="dot"),
                marker=dict(color=_line_clr, size=5),
                hovertemplate=f"{_svc_layer}: %{{y:,.0f}}M bu<extra></extra>",
            ))
        _base_layout(fig_hist, title="National Grain Supply vs Storage Capacity (Million Bu)",
                     height=380)
        fig_hist.update_layout(barmode="stack", showlegend=True,
                               legend=dict(orientation="h", y=1.06, x=0.5,
                                           xanchor="center",
                                           font=dict(color=TXT, size=11),
                                           bgcolor="rgba(0,0,0,0)"))
        fig_hist.update_yaxes(ticksuffix="M")
        st.plotly_chart(fig_hist, use_container_width=True)

        # ── State detail table ─────────────────────────────────────────────
        st.markdown(
            f"<p style='color:{GRAY};font-size:12px;font-weight:700;"
            f"text-transform:uppercase;letter-spacing:.06em;margin:20px 0 6px'>"
            f"State Detail — {_svc_yr}</p>",
            unsafe_allow_html=True,
        )
        _svc_tbl = _svc_df.sort_values("Total Supply", ascending=False).copy()
        if not _svc_df_prev.empty:
            _svc_tbl = _svc_tbl.merge(
                _svc_df_prev[["state_abbr","Ratio"]].rename(
                    columns={"Ratio": "Ratio Prev"}),
                on="state_abbr", how="left",
            )
        else:
            _svc_tbl["Ratio Prev"] = None

        _svc_tbl["Corn & Sorg (M)"] = (_svc_tbl["Corn & Sorghum"] / 1e6).round(0)
        _svc_tbl["Soybeans (M)"]    = (_svc_tbl["Soybeans"]        / 1e6).round(0)
        _svc_tbl["Wheat (M)"]       = (_svc_tbl["Wheat"]            / 1e6).round(0)
        _svc_tbl["Oats (M)"]        = (_svc_tbl["Oats"]             / 1e6).round(0)
        _svc_tbl["Supply (M)"]      = (_svc_tbl["Total Supply"]     / 1e6).round(0)
        _svc_tbl["Storage (M)"]     = (_svc_tbl["Storage"]          / 1e6).round(0)
        _svc_tbl["Surplus (M)"]     = (_svc_tbl["Surplus"]          / 1e6).round(0)
        _svc_tbl["Ratio"]           = _svc_tbl["Ratio"].apply(
            lambda v: f"{v:.2f}x" if pd.notna(v) else "—")
        _svc_tbl["Ratio Prev"]      = _svc_tbl["Ratio Prev"].apply(
            lambda v: f"{v:.2f}x" if pd.notna(v) else "—")

        _disp_cols = ["state_abbr", "Corn & Sorg (M)", "Soybeans (M)", "Wheat (M)",
                      "Oats (M)", "Supply (M)", "Storage (M)", "Surplus (M)",
                      "Ratio", "Ratio Prev"]
        _disp_cols = [c for c in _disp_cols if c in _svc_tbl.columns]
        st.dataframe(
            _svc_tbl[_disp_cols].rename(columns={"state_abbr": "State"}),
            use_container_width=True, hide_index=True,
        )

# ── Legal Disclaimer Footer ───────────────────────────────────────────────────

_disclaimer_year = date.today().year
st.markdown("<hr style='border-color:#e5e7eb;margin-top:32px;margin-bottom:16px'>", unsafe_allow_html=True)
st.markdown(
    f'<div style="color:#9ca3af;font-size:0.68rem;line-height:1.6;text-align:center;padding:0 24px 24px;">'
    f'Trading commodity futures, options on futures, cash commodities, and over-the-counter derivative products involves substantial risk of loss and may not be suitable for all investors. '
    f'This communication is provided for informational purposes only and does not constitute investment advice, a recommendation, or an offer or solicitation to buy or sell any futures, options, cash commodities, or derivative products. '
    f'John Stewart &amp; Associates, Inc. does not accept orders to buy or sell any financial instruments via email. '
    f'The information contained herein has been obtained from sources believed to be reliable; however, its accuracy and completeness are not guaranteed. '
    f'Any opinions expressed are solely those of the author, are subject to change without notice, and should not be relied upon as a basis for investment decisions. '
    f'Past performance is not indicative of future results. '
    f'This message may contain confidential or proprietary information intended solely for the use of the designated recipient. '
    f'&copy; John Stewart &amp; Associates, Inc. {_disclaimer_year}'
    f'</div>',
    unsafe_allow_html=True,
)
