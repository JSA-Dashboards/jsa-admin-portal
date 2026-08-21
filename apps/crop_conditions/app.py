import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
from datetime import datetime, timedelta
import warnings
import base64
import os
import io
from concurrent.futures import ThreadPoolExecutor
warnings.filterwarnings("ignore")

def _to_excel(df) -> bytes:
    """Return an Excel (.xlsx) byte string from a DataFrame or Styler."""
    data = df.data if hasattr(df, "data") else df
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        data.to_excel(writer, index=False)
    return buf.getvalue()

def _dl_btn(df, filename: str, label: str = "⬇ Download Excel"):
    st.download_button(
        label=label,
        data=_to_excel(df),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _show_chart(
    fig,
    filename: str = "chart",
    use_container_width: bool = True,
    extra_config: dict = None,
    key: str = None,
):
    _cfg = {"displayModeBar": False, "displaylogo": False}
    if extra_config:
        _cfg.update(extra_config)
    st.plotly_chart(fig, use_container_width=use_container_width, config=_cfg, key=key)

    _uid = filename.replace("-", "_").replace(" ", "_")
    import streamlit.components.v1 as _stc
    _stc.html(f"""
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:transparent;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
.bar{{display:flex;gap:7px;padding:3px 0 5px}}
.btn{{
  display:inline-flex;align-items:center;gap:5px;
  padding:4px 14px;border-radius:20px;
  border:1px solid #dde2e6;background:#f8fafb;
  color:#32373c;font-size:12px;font-weight:500;
  cursor:pointer;transition:all .15s;white-space:nowrap;line-height:1.5
}}
.btn:hover{{border-color:#0693e3;color:#0693e3;background:#edf6fe}}
.btn.ok{{border-color:#16a34a;color:#16a34a;background:#f0fdf4}}
.btn.err{{border-color:#dc2626;color:#dc2626;background:#fef2f2}}
</style>
<div class="bar">
  <button class="btn" id="{_uid}_dl">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
    </svg><span>Download PNG</span>
  </button>
  <button class="btn" id="{_uid}_cp">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2"/>
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
    </svg><span>Copy Image</span>
  </button>
</div>
<script>
(function(){{
  var uid='{_uid}', fname='{filename}';
  var dl=document.getElementById(uid+'_dl');
  var cp=document.getElementById(uid+'_cp');

  function findPlot(){{
    try{{
      var fr=window.frameElement;
      if(!fr) return null;
      var plots=Array.from(window.parent.document.querySelectorAll('.js-plotly-plot'));
      var myTop=fr.getBoundingClientRect().top;
      var best=null, bestGap=Infinity;
      plots.forEach(function(p){{
        var gap=myTop - p.getBoundingClientRect().bottom;
        if(gap>=0 && gap<bestGap){{bestGap=gap;best=p;}}
      }});
      return best;
    }}catch(e){{return null;}}
  }}

  function getUrl(cb){{
    var plot=findPlot();
    var P=window.parent.Plotly;
    if(!plot||!P){{cb(null,'Could not find chart');return;}}
    P.toImage(plot,{{format:'png',scale:2}})
      .then(function(url){{cb(url,null);}})
      .catch(function(e){{cb(null,e.message);}});
  }}

  function flash(btn,cls,txt,reset){{
    btn.className='btn '+cls;
    btn.querySelector('span').textContent=txt;
    setTimeout(function(){{btn.className='btn';btn.querySelector('span').textContent=reset;}},2200);
  }}

  dl.onclick=function(){{
    dl.querySelector('span').textContent='…';
    getUrl(function(url,err){{
      if(err){{flash(dl,'err','✗ Error','Download PNG');return;}}
      var a=document.createElement('a');a.href=url;a.download=fname+'.png';a.click();
      flash(dl,'ok','✓ Saved','Download PNG');
    }});
  }};

  cp.onclick=async function(){{
    cp.querySelector('span').textContent='…';
    getUrl(async function(url,err){{
      if(err){{flash(cp,'err','✗ Error','Copy Image');return;}}
      try{{
        var blob=await(await fetch(url)).blob();
        await navigator.clipboard.write([new ClipboardItem({{'image/png':blob}})]);
        flash(cp,'ok','✓ Copied!','Copy Image');
      }}catch(e){{flash(cp,'err','✗ '+e.message.slice(0,20),'Copy Image');}}
    }});
  }};
}})();
</script>
""", height=40)





# ── Constants ──────────────────────────────────────────────────────────────────
API_KEY  = st.secrets.get("NASS_API_KEY", "9A6D1EB8-4D94-3221-BA0C-ADD4533EA0C1")
BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"

PSD_BASE    = "https://apps.fas.usda.gov/psdonline/api"
PSD_US_CODE = "0000US"
PSD_ENDING_STOCKS_ATTR = 176
# Commodities whose PSD marketing year ends Sep 1 (psd_market_year = sel_usda_yr - 1)
# Values: (PSD commodity code, bushels per MT)
PSD_SEP1_MAP = {
    "CORN":     ("0440000", 39.368),
    "SOYBEANS": ("2222000", 36.744),
    "SORGHUM":  ("0459100", 39.368),
}

JPSI_DARK       = "#32373c"
JPSI_BLUE       = "#16a34a"   # JSA green — darkened for light-mode contrast
JPSI_WHITE      = "#ffffff"
JPSI_LIGHT_GRAY = "#f4f5f7"

# Light-mode palette
DM_BG      = "#f8fafb"   # page background
DM_SURFACE = "#ffffff"   # cards, sidebar, table rows
DM_SURFACE2= "#f2f5f7"   # slightly off-white — chart bg
DM_BORDER  = "#dde2e6"   # borders / dividers
DM_TEXT    = "#1e2533"   # primary text
DM_MUTED   = "#5a6878"   # secondary / caption text
DM_LAND    = "#e4eae4"   # map land colour (non-wheat states)

CONDITIONS = ["VERY POOR", "POOR", "FAIR", "GOOD", "EXCELLENT"]

# ── Winter Wheat Class groupings ───────────────────────────────────────────────
WHEAT_CLASSES = {
    "All Winter Wheat": None,   # no filter
    "HRW — Hard Red Winter":   {"KS","OK","TX","NE","SD","CO","WY","NM","MT"},
    "SRW — Soft Red Winter":   {"MO","AR","LA","MS","TN","AL","GA","SC","NC",
                                 "KY","IL","IN","OH","WI","MI","PA","NY","WV",
                                 "VA","MD","NJ","DE"},
    # Core soft-white states only — UT is primarily HRW; CA is mixed HRW/White
    # and its total-WINTER yield is not representative of soft-white yield
    "White Winter":            {"WA","ID","OR"},
}

MAP_COLORSCALE = [
    [0.00, "#a50026"],
    [0.20, "#d73027"],
    [0.40, "#f46d43"],
    [0.50, "#fee090"],
    [0.60, "#74c476"],
    [0.80, "#1a9850"],
    [1.00, "#006d2c"],
]

# Diverging blue→white→red for delta maps (positive = blue, negative = red/orange)
DELTA_COLORSCALE = [
    [0.00, "#67001f"],   # deep red   (most negative)
    [0.15, "#d73027"],
    [0.30, "#f46d43"],
    [0.42, "#fddbc7"],   # light salmon
    [0.50, "#f7f7f7"],   # white zero
    [0.58, "#d1e5f0"],   # light blue
    [0.70, "#4393c3"],
    [0.85, "#2166ac"],
    [1.00, "#053061"],   # deep blue  (most positive)
]

COMMODITIES = {
    "Corn": {
        "commodity_desc":              "CORN",
        "class_desc":                  "ALL CLASSES",
        "has_classes":                 False,
        "has_dormancy":                False,
        "crop_yr_cutoff":              None,    # planted & harvested same calendar year
        "season_start_month":          5,       # USDA starts reporting ~mid-May
        "chart_x_start":               (5, 15),
        "chart_x_end":                 (11, 1),
        "chart_ticks":                 [5, 6, 7, 8, 9, 10, 11],
        "chart_tick_labels":           ["May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov"],
        "scan_iso_range":              (20, 40),
        "yield_unit_desc":             "BU / ACRE", # exclude silage (TONS / ACRE)
        "production_unit_desc":        "BU",        # exclude silage production (TONS)
        "all_state_alphas": (
            "AL","AR","CO","CT","DE","GA","ID","IL","IN","IA","KS","KY","LA","ME",
            "MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC",
            "ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA",
            "WV","WI","WY",
        ),
    },
    "Soybeans": {
        "commodity_desc":        "SOYBEANS",
        "class_desc":            "ALL CLASSES",
        "has_classes":           False,
        "has_dormancy":          False,
        "crop_yr_cutoff":        None,    # planted & harvested same calendar year
        "season_start_month":    6,       # USDA starts reporting ~early June
        "chart_x_start":         (6, 1),
        "chart_x_end":           (11, 15),
        "chart_ticks":           [6, 7, 8, 9, 10, 11],
        "chart_tick_labels":     ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov"],
        "scan_iso_range":        (23, 42),
        "production_unit_desc":  "BU",    # exclude dollar-value production rows
        "all_state_alphas": (
            "AL","AR","DE","GA","IL","IN","IA","KS","KY","LA","MD","MI","MN","MS",
            "MO","MT","NE","NJ","NY","NC","ND","OH","OK","PA","SC","SD","TN","TX",
            "VA","WV","WI",
        ),
    },
    "Winter Wheat": {
        "commodity_desc":     "WHEAT",
        "class_desc":         "WINTER",
        "has_classes":        True,    # HRW/SRW/White sub-indexes
        "has_dormancy":       True,    # pre/post dormancy toggle
        "crop_yr_cutoff":     9,       # month >= 9 → crop_year = next calendar yr
        "season_start_month": 2,       # week selector / chart filter start month
        "chart_x_start":      (3, 15), # post-dormancy chart x-axis start (month, day)
        "chart_x_end":        (7, 15),
        "chart_ticks":        [1, 2, 3, 4, 5, 6, 7],
        "chart_tick_labels":  ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"],
        "scan_iso_range":     (5, 22), # ISO week range for look-back R² scan
        "all_state_alphas": (
            "AL","AZ","AR","CA","CO","DE","GA","ID","IL","IN","KS","KY","LA","MD",
            "MI","MS","MO","MT","NE","NV","NJ","NM","NY","NC","ND","OH","OK","OR",
            "PA","SC","SD","TN","TX","UT","VA","WA","WV","WI","WY",
        ),
    },
    "Spring Wheat (HRS)": {
        "commodity_desc":     "WHEAT",
        "class_desc":         "SPRING, (EXCL DURUM)",
        "has_classes":        False,
        "has_dormancy":       False,
        "crop_yr_cutoff":     None,    # all months → same calendar year
        "season_start_month": 4,
        "chart_x_start":      (4, 1),
        "chart_x_end":        (11, 1),
        "chart_ticks":        [4, 5, 6, 7, 8, 9, 10],
        "chart_tick_labels":  ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"],
        "scan_iso_range":     (15, 35),
        "all_state_alphas":   ("CO","ID","MN","MT","NV","ND","OR","SD","UT","WA","WY"),
    },
    "Spring Wheat (Durum)": {
        "commodity_desc":     "WHEAT",
        "class_desc":         "SPRING, DURUM",
        "has_classes":        False,
        "has_dormancy":       False,
        "crop_yr_cutoff":     None,
        "season_start_month": 4,
        "chart_x_start":      (4, 1),
        "chart_x_end":        (11, 1),
        "chart_ticks":        [4, 5, 6, 7, 8, 9, 10],
        "chart_tick_labels":  ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"],
        "scan_iso_range":     (15, 35),
        "all_state_alphas":   ("ID","MN","MT","ND","OR","SD","WA"),
    },
    "Sorghum": {
        "commodity_desc":        "SORGHUM",
        "class_desc":            "ALL CLASSES",
        "has_classes":           False,
        "has_dormancy":          False,
        "crop_yr_cutoff":        None,    # planted & harvested same calendar year
        "season_start_month":    6,       # USDA starts reporting ~late June
        "chart_x_start":         (6, 1),
        "chart_x_end":           (11, 15),
        "chart_ticks":           [6, 7, 8, 9, 10, 11],
        "chart_tick_labels":     ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov"],
        "scan_iso_range":        (25, 42),
        "yield_unit_desc":       "BU / ACRE", # exclude silage (TONS / ACRE)
        "production_unit_desc":  "BU",        # exclude silage (TONS) and dollar rows
        "all_state_alphas":      ("AL","AR","CO","GA","KS","LA","MO","NE","NM","OK","SD","TX"),
    },
}

# ── Production table: regional / class groupings per commodity ────────────────
# Each entry is a list of dicts: {states: [...], subtotal: "Label" | None}
# States are shown in listed order; a subtotal row is appended after each group
# when subtotal is not None.  States absent from all groups fall in "Other".
# Winter Wheat groups are built dynamically from WHEAT_CLASSES (see _tab_prod).
PROD_TABLE_GROUPS: dict = {
    "Corn": [
        {"states": ["IL", "IN", "OH", "MI", "KY"],  "subtotal": "Eastern Corn Belt"},
        {"states": ["IA", "NE", "KS"],               "subtotal": "UP States"},
        {"states": ["MN", "SD", "ND"],               "subtotal": "BN States"},
        {"states": ["MS", "AR", "LA", "TN"],         "subtotal": "Delta"},
        {"states": ["WI", "MO", "TX"],               "subtotal": None},
    ],
    "Soybeans": [
        {"states": ["IL", "IN", "OH", "MI"],         "subtotal": "Eastern Corn Belt"},
        {"states": ["IA", "MN", "MO"],               "subtotal": "Western Corn Belt"},
        {"states": ["ND", "SD", "NE", "KS"],         "subtotal": "Northern Plains"},
        {"states": ["AR", "MS", "TN", "LA"],         "subtotal": "Delta"},
        {"states": ["WI", "KY"],                     "subtotal": None},
    ],
    "Sorghum": [
        {"states": ["KS", "TX", "OK"],               "subtotal": "Southern Plains"},
        {"states": ["SD", "NE", "CO"],               "subtotal": "Northern Plains"},
        {"states": ["MO", "AR", "LA"],               "subtotal": None},
    ],
    "Spring Wheat (HRS)": [
        {"states": ["ND", "MN", "SD"],               "subtotal": "Northern Plains"},
        {"states": ["MT", "ID"],                     "subtotal": None},
    ],
    "Spring Wheat (Durum)": [
        {"states": ["ND", "MT", "SD"],               "subtotal": None},
    ],
}

# State centroids for map text labels (lon, lat)
STATE_CENTROIDS = {
    "AL": (32.77, -86.84), "AZ": (34.27, -111.66), "AR": (34.75, -92.37),
    "CA": (37.27, -119.61), "CO": (39.00, -105.55), "CT": (41.62, -72.73),
    "DE": (38.99, -75.51), "FL": (28.63, -82.35), "GA": (32.67, -83.44),
    "ID": (44.35, -114.61), "IL": (40.04, -89.20), "IN": (40.27, -86.13),
    "IA": (42.08, -93.50), "KS": (38.49, -98.32), "KY": (37.53, -85.30),
    "LA": (31.00, -92.45), "ME": (45.37, -68.97), "MD": (39.05, -76.64),
    "MA": (42.26, -71.81), "MI": (43.80, -84.90), "MN": (46.00, -94.50),
    "MS": (32.74, -89.67), "MO": (38.46, -92.29), "MT": (46.88, -110.36),
    "NE": (41.53, -99.80), "NV": (38.50, -117.02), "NH": (43.68, -71.58),
    "NJ": (40.19, -74.67), "NM": (34.52, -106.25), "NY": (42.75, -75.42),
    "NC": (35.54, -79.39), "ND": (47.45, -100.47), "OH": (40.29, -82.79),
    "OK": (35.59, -97.49), "OR": (43.94, -120.56), "PA": (40.88, -77.80),
    "RI": (41.68, -71.57), "SC": (33.90, -80.90), "SD": (44.44, -100.24),
    "TN": (35.86, -86.35), "TX": (31.47, -99.33), "UT": (39.32, -111.09),
    "VT": (44.07, -72.67), "VA": (37.52, -78.85), "WA": (47.38, -120.46),
    "WV": (38.64, -80.62), "WI": (44.62, -90.13), "WY": (42.96, -107.55),
}

# ── Marketing Year Helpers ─────────────────────────────────────────────────────
# Winter wheat marketing year: Jun(Y) – May(Y+1)
# USDA reports under the HARVEST year (Y).
# e.g. USDA year 2026 = marketing year 2026/27

def mkt_label(usda_year: int) -> str:
    """Convert USDA harvest year → marketing year label e.g. 2026 → '2026/27'."""
    return f"{usda_year}/{str(usda_year + 1)[2:]}"

def mkt_label_short(usda_year: int) -> str:
    """Short marketing year label for chart annotations e.g. 2026 → '26/27'."""
    return f"{str(usda_year)[2:]}/{str(usda_year + 1)[2:]}"

def usda_year(mkt_lbl: str) -> int:
    """Convert marketing year label → USDA harvest year e.g. '2026/27' → 2026."""
    return int(mkt_lbl.split("/")[0])

def default_usda_year() -> int:
    """
    Return the USDA year whose conditions are most likely being reported right now.
    - Nov–Jul  → crop in the field: harvest year = next calendar year if Nov-Dec,
                  current calendar year if Jan-Jul
    - Aug–Oct  → between seasons; return the year just harvested
    """
    now = datetime.now()
    if now.month >= 11:
        return now.year + 1   # Nov/Dec 2024 → 2025 crop just planted
    else:
        return now.year       # Jan-Oct 2025 → 2025 crop (planted fall 2024)

def available_usda_years(n: int = 42) -> list[int]:
    """Last n USDA harvest years, most recent first."""
    latest = default_usda_year()
    return list(range(latest, latest - n, -1))


# ── Data Layer ─────────────────────────────────────────────────────────────────

def _nass_get(params: dict, retries: int = 3, timeout: int = 60) -> dict:
    """GET the NASS API with automatic retries on timeout or server errors."""
    for attempt in range(retries):
        try:
            r = requests.get(BASE_URL, params=params, timeout=timeout)
            if r.status_code >= 500:
                # Server error (502, 503, etc.) — retry
                if attempt < retries - 1:
                    continue
                return {"_error": f"HTTP {r.status_code}", "_text": r.text[:300]}
            if r.status_code >= 400:
                # Client error — no point retrying
                return {"_error": f"HTTP {r.status_code}", "_text": r.text[:300]}
            try:
                return r.json()
            except Exception:
                return {"_error": "JSON decode failed", "_text": r.text[:300]}
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                continue   # retry immediately
            return {"_error": "timeout"}
        except Exception as e:
            return {"_error": str(e)}
    return {}


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_conditions(commodity_desc: str, class_desc: str, years: tuple, known_states: tuple = ()) -> pd.DataFrame:
    """
    Pull weekly crop condition data from USDA NASS Quick Stats.

    Strategy to stay under the NASS 50k-row-per-request limit:
    • State rows:  one API call PER STATE, using only year__GE (no year__LE).
      The NASS API silently ignores year__LE for weekly condition records, so
      year-chunked calls (e.g. year__GE=1986, year__LE=1988) actually return ALL
      years from 1986 to present for all ~40 states, which far exceeds the 50k
      row limit and causes those calls to fail silently.  Fetching one state at a
      time keeps each call to ~3,750 rows (one state × 37 yrs × 35 wks × 5 conds)
      — well under the limit — and returns the full historical record.
    • State discovery: a single cheap "current year only" call retrieves the list
      of states currently reporting, so we don't have to hard-code it per commodity.
    • US TOTAL:  fetched in a single bulk call (state_name=US TOTAL).
      National rows are ~7k total (35 wks × 5 conds × 40 yrs) — no limit risk.

    class_desc handling:
      We deliberately omit class_desc from the API query for conditions data.
      NASS QuickStats does not reliably index class_desc for weekly conditions records —
      the class appears in the short_desc field (e.g. "WHEAT, WINTER - CONDITION,
      MEASURED IN PCT GOOD") but is not stored as a separate indexed class_desc value
      for condition survey rows.  We fetch all classes and filter by short_desc below,
      which is the only robust approach.
    """
    if not years:
        return pd.DataFrame()

    year_list = sorted(years)
    min_year  = year_list[0]

    _base = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    commodity_desc,
        "statisticcat_desc": "CONDITION",
        "freq_desc":         "WEEKLY",
        "format":            "JSON",
        # class_desc intentionally omitted — see docstring
    }

    frames = []
    errors = []

    # ── Step 1: Discover which states currently report for this commodity ────────
    # Only fetch active reporters — fetching all historical states balloons memory.
    # The dropdown is populated separately from the commodity's all_state_alphas list.
    _disc_params = {**_base, "agg_level_desc": "STATE", "year__GE": year_list[-1]}
    _disc_payload = _nass_get(_disc_params)
    _reporting_states = sorted({
        r["state_alpha"] for r in _disc_payload.get("data", [])
        if len(r.get("state_alpha", "")) == 2 and r.get("state_alpha") != "US"
    }) or [
        "AL", "AR", "CA", "CO", "GA", "ID", "IL", "IN", "KS", "KY",
        "LA", "MD", "MI", "MN", "MO", "MS", "MT", "NC", "NE", "NJ",
        "NY", "OH", "OK", "OR", "PA", "SD", "TN", "TX", "VA", "WA",
        "WI", "WY",
    ]

    # ── Step 2: Fetch full history for each state — parallelised ─────────────────
    # year__LE is omitted intentionally — NASS ignores it for condition records
    # (confirmed via diagnostic: year__LE=1995 returned data through 2026).
    # Each per-state call returns ~3,750 rows regardless of history depth.
    # Using ThreadPoolExecutor so all ~35 state calls fire concurrently rather
    # than sequentially, cutting cold-start time from ~90s to ~5-10s.
    def _fetch_state(st):
        params = {**_base, "agg_level_desc": "STATE",
                  "state_alpha": st, "year__GE": min_year}
        return st, _nass_get(params)

    with ThreadPoolExecutor(max_workers=10) as _pool:
        _state_futures = {_pool.submit(_fetch_state, st): st for st in _reporting_states}
        for _fut in _state_futures:
            try:
                _st, _st_payload = _fut.result()
                if "_error" in _st_payload:
                    errors.append(f"State {_st}: {_st_payload['_error']}")
                elif "data" in _st_payload and _st_payload["data"]:
                    frames.append(pd.DataFrame(_st_payload["data"]))
            except Exception:
                pass

    # ── Step 3: US TOTAL — single bulk call ───────────────────────────────────────
    _us_params = {**_base, "state_name": "US TOTAL", "year__GE": min_year}
    _us_payload = _nass_get(_us_params)
    if "_error" in _us_payload:
        errors.append(f"US TOTAL: {_us_payload['_error']}")
    elif "data" in _us_payload and _us_payload["data"]:
        try:
            frames.append(pd.DataFrame(_us_payload["data"]))
        except Exception:
            pass

    if not frames:
        if errors:
            raise RuntimeError("NASS API errors: " + "; ".join(errors))
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df = df[["year", "week_ending", "state_alpha", "state_name", "short_desc", "Value"]].copy()
    df["Value"]       = pd.to_numeric(df["Value"], errors="coerce")
    df["week_ending"] = pd.to_datetime(df["week_ending"], errors="coerce")
    df["year"]        = df["year"].astype(int)

    # ── Filter to requested year range ────────────────────────────────────────────
    # Even though year__LE is ignored by NASS, we still honour the caller's `years`
    # tuple so that state data beyond the requested range is excluded.
    df = df[df["year"].isin(set(year_list))]

    # ── Filter by class using short_desc (always reliable) ───────────────────────
    # short_desc reliably contains the class name, e.g. "WHEAT, WINTER - CONDITION, ..."
    # Skip filtering for broad classes where commodity_desc alone is sufficient.
    _skip_sd_filter = {"ALL CLASSES", "ALL", "FIELD CORN", ""}
    if class_desc and class_desc.upper() not in _skip_sd_filter:
        # Use regex=False because some class_desc values (e.g. "SPRING, (EXCL DURUM)")
        # contain regex metacharacters.
        _has_class = df["short_desc"].str.contains(class_desc, case=False, na=False, regex=False)
        df = df[_has_class]

    for cond in CONDITIONS:
        df.loc[df["short_desc"].str.contains(cond, case=False, na=False), "condition"] = cond

    df = df.dropna(subset=["condition", "Value", "week_ending"])
    # Keep only 2-char state codes (state abbreviations + "US")
    df = df[df["state_alpha"].str.len() == 2]
    # Deduplicate across overlapping calls
    df = df.drop_duplicates(subset=["year", "week_ending", "state_alpha", "condition"])
    return df


def _states_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["state_alpha"] != "US"]


@st.cache_data(ttl=900, show_spinner=False)
def good_excellent(df: pd.DataFrame) -> pd.DataFrame:
    """Sum Good + Excellent % per state / USDA year / week."""
    s = _states_only(df)
    return (
        s[s["condition"].isin(["GOOD", "EXCELLENT"])]
        .groupby(["year", "week_ending", "state_alpha", "state_name"], as_index=False)["Value"]
        .sum()
        .rename(columns={"Value": "ge_pct"})
    )


@st.cache_data(ttl=900, show_spinner=False)
def poor_very_poor(df: pd.DataFrame) -> pd.DataFrame:
    """Sum Poor + Very Poor % per state / USDA year / week."""
    s = _states_only(df)
    return (
        s[s["condition"].isin(["POOR", "VERY POOR"])]
        .groupby(["year", "week_ending", "state_alpha", "state_name"], as_index=False)["Value"]
        .sum()
        .rename(columns={"Value": "pv_pct"})
    )


@st.cache_data(ttl=900, show_spinner=False)
def fair_condition(df: pd.DataFrame) -> pd.DataFrame:
    """Fair % per state / USDA year / week."""
    s = _states_only(df)
    return (
        s[s["condition"] == "FAIR"]
        .groupby(["year", "week_ending", "state_alpha", "state_name"], as_index=False)["Value"]
        .sum()
        .rename(columns={"Value": "fair_pct"})
    )


CONDITION_WEIGHTS = {"VERY POOR": 0, "POOR": 25, "FAIR": 50, "GOOD": 75, "EXCELLENT": 100}

# ── USDA RMA approximate final planting dates for corn (by state) ───────────────
# Source: USDA Risk Management Agency final planting dates for crop insurance.

# ── USDA Official Wheat Class Final Yields (bu/ac) ───────────────────────────
# Source: USDA ERS Wheat Data — Wheat by Class (ers.usda.gov/data-products/wheat-data/).
# Key = USDA harvest year (first year of marketing-year label). e.g. 2025 → 2025/26.
# NASS Quick Stats does not expose national class yields via API — no REST endpoint
# exists for HRW / SRW / White at the national level.
# UPDATE CADENCE: NASS publishes final class yields each November in the Small Grains
# Summary. Add the new harvest year row to each dict at that time.
# Values for the current (incomplete) crop year are USDA early-season estimates.

USDA_HRW_YIELD_FINAL: dict[int, float] = {
    1981: 29.34, 1982: 33.61, 1983: 39.66, 1984: 36.67, 1985: 35.66,
    1986: 32.29, 1987: 35.64, 1988: 32.91, 1989: 27.21, 1990: 36.80,
    1991: 32.96, 1992: 32.80, 1993: 35.41, 1994: 33.80, 1995: 29.79,
    1996: 29.52, 1997: 38.25, 1998: 43.17, 1999: 43.13, 2000: 35.87,
    2001: 36.72, 2002: 31.13, 2003: 41.79, 2004: 36.60, 2005: 37.77,
    2006: 31.99, 2007: 37.16, 2008: 40.00, 2009: 38.10, 2010: 42.09,
    2011: 36.36, 2012: 40.58, 2013: 36.65, 2014: 33.69, 2015: 35.77,
    2016: 49.48, 2017: 42.53, 2018: 39.08, 2019: 48.18, 2020: 42.24,
    2021: 43.62, 2022: 34.81, 2023: 38.58, 2024: 42.54, 2025: 45.81,
    2026: 39.00,   # USDA estimate — pre-harvest
}

USDA_SRW_YIELD_FINAL: dict[int, float] = {
    1981: 44.31, 1982: 37.27, 1983: 39.39, 1984: 42.17, 1985: 40.38,
    1986: 37.92, 1987: 45.98, 1988: 49.24, 1989: 45.79, 1990: 42.58,
    1991: 34.35, 1992: 49.34, 1993: 43.13, 1994: 51.60, 1995: 48.98,
    1996: 43.39, 1997: 54.18, 1998: 48.87, 1999: 56.63, 2000: 57.88,
    2001: 55.76, 2002: 49.56, 2003: 55.63, 2004: 54.17, 2005: 59.91,
    2006: 63.22, 2007: 50.03, 2008: 60.55, 2009: 55.85, 2010: 54.65,
    2011: 61.45, 2012: 60.50, 2013: 63.72, 2014: 63.50, 2015: 60.92,
    2016: 69.38, 2017: 67.70, 2018: 63.90, 2019: 64.06, 2020: 64.73,
    2021: 72.60, 2022: 70.19, 2023: 77.54, 2024: 74.11, 2025: 76.77,
    2026: 75.00,   # USDA estimate — pre-harvest
}

USDA_WHITE_YIELD_FINAL: dict[int, float] = {
    # National White wheat yield data begins marketing year 1991/92
    1991: 52.10, 1992: 54.30, 1993: 66.70, 1994: 61.10, 1995: 66.58,
    1996: 68.93, 1997: 70.19, 1998: 66.99, 1999: 60.39, 2000: 71.50,
    2001: 56.87, 2002: 56.45, 2003: 59.53, 2004: 64.51, 2005: 63.66,
    2006: 61.46, 2007: 59.15, 2008: 59.40, 2009: 61.92, 2010: 68.05,
    2011: 73.87, 2012: 68.26, 2013: 68.04, 2014: 56.30, 2015: 55.69,
    2016: 71.08, 2017: 67.53, 2018: 71.32, 2019: 69.48, 2020: 74.30,
    2021: 49.25, 2022: 67.64, 2023: 58.77, 2024: 68.71, 2025: 70.63,
    2026: 70.63,   # USDA estimate — pre-harvest
}

# ── Class Production Weights — fallback only (replaced by dynamic weights at runtime) ──
HRW_WEIGHTS   = {"KS": 0.46, "OK": 0.14, "TX": 0.12, "CO": 0.11, "NE": 0.08, "SD": 0.06, "MT": 0.02, "WY": 0.01}
SRW_WEIGHTS   = {"IL": 0.155, "OH": 0.123, "MO": 0.096, "KY": 0.091, "MI": 0.077, "TN": 0.066, "IN": 0.064, "NY": 0.056, "WI": 0.051, "PA": 0.041, "MD": 0.039, "VA": 0.021, "NC": 0.020, "AL": 0.017, "AR": 0.017, "GA": 0.013}
WHITE_WEIGHTS = {"WA": 0.57, "ID": 0.28, "OR": 0.15}   # WA/ID/OR core soft-white states only


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_hrw_production(years: tuple) -> pd.DataFrame:
    """
    Pull annual WINTER WHEAT PRODUCTION (BU) by state from USDA NASS.
    Used to compute HRW state weights (HRW states grow predominantly HRW,
    so total WINTER production is a reliable proxy for HRW production share).

    class_desc intentionally omitted — filter by short_desc after fetching
    (same approach as fetch_conditions / fetch_winter_wheat_acres).

    Reference-period priority: for completed crop years NASS publishes multiple
    estimates (May/Jun/Jul/Aug Crop Production forecasts + Annual Summary final).
    We select the most-final report available per state-year so that the displayed
    historical production matches the USDA official final, not an in-season forecast
    that may have been higher or lower.  Priority order mirrors fetch_ww_state_acres.
    """
    # Higher = more authoritative / final.
    _REF_PRIORITY: dict = {
        "YEAR":                 100,  # Annual Summary — always the definitive final
        "YEAR - AUG FORECAST":   70,  # August Crop Production — very close to final
        "YEAR - JUL FORECAST":   60,  # July Crop Production
        "YEAR - JUN FORECAST":   50,  # June Crop Production
        "YEAR - JUN ACREAGE":    45,  # June Acreage Report (sometimes carries production)
        "YEAR - MAY FORECAST":   30,  # May Crop Production (earliest in-season)
    }

    if not years:
        return pd.DataFrame()
    params = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    "WHEAT",
        # class_desc intentionally omitted — filter by short_desc after fetching
        "statisticcat_desc": "PRODUCTION",
        "unit_desc":         "BU",
        "agg_level_desc":    "STATE",          # pin to state rows — avoids county/district bloat
        "freq_desc":         "ANNUAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    payload = _nass_get(params)
    if "_error" in payload or "data" not in payload or not payload["data"]:
        return pd.DataFrame()
    df = pd.DataFrame(payload["data"])
    df = df[[c for c in ["year", "state_alpha", "state_name", "short_desc",
                         "reference_period_desc", "Value"]
              if c in df.columns]].copy()
    # Filter to WINTER wheat only via short_desc (same approach as conditions data)
    if "short_desc" in df.columns:
        df = df[df["short_desc"].str.contains("WINTER", case=False, na=False)]
    # Strip commas (NASS formats large numbers with commas) and handle (D)/(NA)
    df["Value"] = df["Value"].astype(str).str.replace(",", "", regex=False)
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"]  = df["year"].astype(int)
    df = df.dropna(subset=["Value"])
    # Keep only valid 2-char state codes, exclude US totals
    df = df[df["state_alpha"].str.len() == 2]
    df = df[df["state_alpha"] != "US"]
    # Priority-based deduplication: keep the most-final report per state-year.
    # This ensures we display the USDA Annual Summary (final) for completed years
    # rather than an in-season forecast that may differ from the official final.
    if "reference_period_desc" in df.columns:
        df["_priority"] = (df["reference_period_desc"]
                           .str.strip().str.upper()
                           .map(_REF_PRIORITY)
                           .fillna(0).astype(int))
        # Sort: highest priority first; within same priority prefer the TOTAL
        # "WHEAT, WINTER" row over any class-specific sub-row (larger value wins).
        df = (df.sort_values(["year", "state_alpha", "_priority", "Value"],
                             ascending=[True, True, False, False])
                .drop_duplicates(subset=["year", "state_alpha"], keep="first")
                .drop(columns=["_priority"]))
    else:
        # Fallback if NASS doesn't return reference_period_desc: take largest value
        # (keeps total "WHEAT, WINTER" over any class sub-row).
        df = df.groupby(["year", "state_alpha", "state_name"], as_index=False)["Value"].max()
    return df[["year", "state_alpha", "state_name", "Value"]].rename(
        columns={"Value": "production_bu"}
    )


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_ww_national_totals(years: tuple) -> pd.DataFrame:
    """
    Pull USDA-published national 'WHEAT, WINTER' totals using state_name=US TOTAL.
    One API call per statisticcat_desc so each response is small and unambiguous.
    Filters to short_desc starting with 'WHEAT, WINTER -' (all-class only, not HRW/SRW/White).
    Returns one row per year: year, production_bu, planted_ac, harvested_ac, yield_bu_ac, pct_harvested.
    """
    _REF_PRIORITY = {
        "YEAR": 100, "YEAR - AUG FORECAST": 70, "YEAR - JUL FORECAST": 60,
        "YEAR - JUN FORECAST": 50, "YEAR - JUN ACREAGE": 45, "YEAR - MAY FORECAST": 30,
    }
    if not years:
        return pd.DataFrame()

    _base = {
        "key":            API_KEY,
        "source_desc":    "SURVEY",
        "sector_desc":    "CROPS",
        "group_desc":     "FIELD CROPS",
        "commodity_desc": "WHEAT",
        "state_name":     "US TOTAL",
        "freq_desc":      "ANNUAL",
        "year__GE":       str(min(years)),
        "year__LE":       str(max(years)),
        "format":         "JSON",
    }

    def _best_by_year(df: pd.DataFrame) -> dict:
        """Return {year: value} picking highest-priority reference_period."""
        if df.empty or "Value" not in df.columns:
            return {}
        df = df.copy()
        df["_v"]   = pd.to_numeric(df["Value"].astype(str).str.replace(",", ""), errors="coerce")
        df["_pri"] = (df.get("reference_period_desc", pd.Series([""] * len(df)))
                      .str.strip().str.upper().map(_REF_PRIORITY).fillna(0).astype(int))
        df["year"] = df["year"].astype(int)
        df = df.dropna(subset=["_v"])
        result = {}
        for yr, grp in df.groupby("year"):
            result[int(yr)] = float(grp.sort_values("_pri", ascending=False)["_v"].iloc[0])
        return result

    # Confirmed short_desc strings from NASS QuickStats (Geo Level=NATIONAL, State=US TOTAL).
    # Using exact matches prevents picking up wrong-unit or class-specific rows.
    _SD_NATIONAL = {
        "WHEAT, WINTER - PRODUCTION, MEASURED IN BU":  "production_bu",
        "WHEAT, WINTER - ACRES HARVESTED":              "harvested_ac",
        "WHEAT, WINTER - ACRES PLANTED":                "planted_ac",
        "WHEAT, WINTER - YIELD, MEASURED IN BU / ACRE": "yield_bu_ac",
    }
    # Map short_desc to its statisticcat_desc for targeted API calls
    _SD_SCAT = {
        "WHEAT, WINTER - PRODUCTION, MEASURED IN BU":  "PRODUCTION",
        "WHEAT, WINTER - ACRES HARVESTED":              "AREA HARVESTED",
        "WHEAT, WINTER - ACRES PLANTED":                "AREA PLANTED",
        "WHEAT, WINTER - YIELD, MEASURED IN BU / ACRE": "YIELD",
    }
    _field_data: dict = {}   # {field_name: {year: value}}

    # One API call per statisticcat_desc; filter to exact short_desc
    for _sd, _field in _SD_NATIONAL.items():
        _scat = _SD_SCAT[_sd]
        _r = _nass_get({**_base, "statisticcat_desc": _scat})
        if "data" not in _r or not _r["data"]:
            continue
        _df = pd.DataFrame(_r["data"])
        if "short_desc" not in _df.columns:
            continue
        _df = _df[_df["short_desc"] == _sd]          # exact match — no wrong rows
        if _df.empty:
            continue
        _field_data[_field] = _best_by_year(_df)

    if "harvested_ac" not in _field_data or not _field_data["harvested_ac"]:
        return pd.DataFrame()

    # Assemble one row per year
    _all_yrs = sorted(set().union(*[set(v.keys()) for v in _field_data.values()]))
    _rows = []
    for _yr in _all_yrs:
        _row = {"year": _yr, "state_alpha": "US", "state_name": "🇺🇸 US Total"}
        for _f, _yv in _field_data.items():
            _row[_f] = _yv.get(_yr)
        _rows.append(_row)

    out = pd.DataFrame(_rows)
    # Fall back to yield × harvested for any year where NASS production is missing
    _prod_missing = out.get("production_bu", pd.Series(dtype=float)).isna()
    if _prod_missing.any() and "yield_bu_ac" in out.columns and "harvested_ac" in out.columns:
        out.loc[_prod_missing, "production_bu"] = (
            out.loc[_prod_missing, "yield_bu_ac"] * out.loc[_prod_missing, "harvested_ac"]
        ).round(0)
    out["pct_harvested"] = np.where(
        out.get("planted_ac", pd.Series(dtype=float)).fillna(0) > 0,
        (out["harvested_ac"] / out["planted_ac"] * 100).round(1),
        np.nan,
    )
    return out.sort_values("year").reset_index(drop=True)


def _fetch_class_production(class_desc: str, valid_states: set, years: tuple) -> pd.DataFrame:
    """
    Fetch annual wheat PRODUCTION (BU) by state for a specific class (e.g. SOFT RED WINTER,
    SOFT WHITE).  Using class-specific production as the weighting basis is the correct NASS
    methodology: national_yield = Σ(state_class_prod) / Σ(state_class_acres), which is
    equivalent to weighting state yields by their class-specific harvested acres.
    Falls back gracefully to empty DataFrame if NASS doesn't have the data.
    """
    if not years or not valid_states:
        return pd.DataFrame()
    params = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    "WHEAT",
        "class_desc":        class_desc,
        "statisticcat_desc": "PRODUCTION",
        "unit_desc":         "BU",
        "agg_level_desc":    "STATE",
        "freq_desc":         "ANNUAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    payload = _nass_get(params)
    if "data" not in payload or not payload["data"]:
        return pd.DataFrame()
    df = pd.DataFrame(payload["data"])
    df = df[[c for c in ["year", "state_alpha", "reference_period_desc", "Value"]
              if c in df.columns]].copy()
    df["Value"] = df["Value"].astype(str).str.replace(",", "", regex=False)
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"]  = df["year"].astype(int)
    df = df.dropna(subset=["Value"])
    df = df[df["state_alpha"].isin(valid_states)]
    if df.empty:
        return pd.DataFrame()
    # Priority dedup — keep most-final estimate per state-year (same as fetch_hrw_production)
    _REF_PRI = {"YEAR": 100, "YEAR - AUG FORECAST": 70, "YEAR - JUL FORECAST": 60,
                "YEAR - JUN FORECAST": 50, "YEAR - JUN ACREAGE": 45, "YEAR - MAY FORECAST": 30}
    if "reference_period_desc" in df.columns:
        df["_pri"] = (df["reference_period_desc"].str.strip().str.upper()
                      .map(_REF_PRI).fillna(0).astype(int))
        df = (df.sort_values(["year", "state_alpha", "_pri", "Value"],
                             ascending=[True, True, False, False])
                .drop_duplicates(subset=["year", "state_alpha"], keep="first")
                .drop(columns=["_pri"]))
    else:
        df = df.groupby(["year", "state_alpha"], as_index=False)["Value"].max()
    return df[["year", "state_alpha", "Value"]].rename(columns={"Value": "production_bu"})


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_srw_class_production(years: tuple) -> pd.DataFrame:
    """SOFT RED WINTER production by state — used for class-specific SRW weights."""
    SRW_STATES = {"IL", "IN", "OH", "KY", "MI", "MO", "TN", "AR", "MS", "AL",
                  "GA", "SC", "NC", "VA", "WV", "MD", "PA", "NY", "NJ", "DE", "WI", "LA"}
    return _fetch_class_production("SOFT RED WINTER", SRW_STATES, years)


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_white_class_production(years: tuple) -> pd.DataFrame:
    """SOFT WHITE production by state — used for class-specific White weights."""
    WHITE_STATES = {"WA", "OR", "ID"}
    return _fetch_class_production("SOFT WHITE", WHITE_STATES, years)


def compute_weights_from_class_production(
    prod_df: pd.DataFrame, fallback: dict, n_years: int = 10
) -> dict:
    """
    Compute fixed average weights from class-specific production (n-year average).
    Drop states with < 0.5% share; renormalise to 1.0.
    Falls back to `fallback` if prod_df is empty or computation fails.
    """
    if prod_df.empty:
        return fallback.copy()
    try:
        latest = sorted(prod_df["year"].unique())[-n_years:]
        sub    = prod_df[prod_df["year"].isin(latest)].groupby("state_alpha", as_index=False)["production_bu"].mean()
        total  = sub["production_bu"].sum()
        if total == 0:
            return fallback.copy()
        sub["share"] = sub["production_bu"] / total
        sub = sub[sub["share"] >= 0.005].copy()
        if sub.empty:
            return fallback.copy()
        norm = sub["share"].sum()
        return {r["state_alpha"]: round(r["share"] / norm, 4)
                for _, r in sub.sort_values("share", ascending=False).iterrows()}
    except Exception:
        return fallback.copy()


def compute_year_specific_weights_from_class_production(
    prod_df: pd.DataFrame,
) -> dict[int, dict[str, float]]:
    """
    Build a {year: {state: weight}} lookup using that year's actual class production.
    Used for year-specific weighting — the same methodology NASS uses for national yields.
    Returns empty dict if prod_df is empty.
    """
    if prod_df.empty:
        return {}
    result: dict[int, dict[str, float]] = {}
    for yr, grp in prod_df.groupby("year"):
        total = grp["production_bu"].sum()
        if total == 0:
            continue
        result[int(yr)] = {row["state_alpha"]: row["production_bu"] / total
                           for _, row in grp.iterrows()}
    return result


@st.cache_data(show_spinner=False, ttl=3600, persist="disk")
def fetch_commodity_production(commodity_desc: str, class_desc: str, years: tuple,
                               unit_desc: str | None = None) -> pd.DataFrame:
    """
    Generic annual PRODUCTION by state fetch for any commodity/class.
    Single bulk call via year__GE/LE.
    """
    if not years:
        return pd.DataFrame()
    params = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    commodity_desc,
        "class_desc":        class_desc,
        "statisticcat_desc": "PRODUCTION",
        "agg_level_desc":    "STATE",
        "freq_desc":         "ANNUAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    if unit_desc:
        params["unit_desc"] = unit_desc
    payload = _nass_get(params)
    frames = []
    if "data" in payload and payload["data"]:
        frames.append(pd.DataFrame(payload["data"]))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df[[c for c in ["year", "state_alpha", "state_name", "unit_desc",
                         "reference_period_desc", "Value"] if c in df.columns]].copy()
    df["Value"] = df["Value"].astype(str).str.replace(",", "", regex=False)
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"]  = df["year"].astype(int)
    df = df.dropna(subset=["Value"])
    df = df[df["state_alpha"].str.len() == 2]
    df = df[df["state_alpha"] != "US"]
    # Post-fetch unit filter — ensures silage tonnage etc. are excluded
    if unit_desc and "unit_desc" in df.columns:
        df = df[df["unit_desc"] == unit_desc]
    df = df.drop(columns=["unit_desc"], errors="ignore")
    # Priority dedup — keep most-final NASS report per state-year
    _REF_PRI_PROD = {
        "YEAR": 100, "YEAR - AUG FORECAST": 70, "YEAR - JUL FORECAST": 60,
        "YEAR - JUN FORECAST": 50, "YEAR - JUN ACREAGE": 45, "YEAR - MAY FORECAST": 30,
        "YEAR - SEP FORECAST": 80, "YEAR - OCT FORECAST": 85, "YEAR - NOV FORECAST": 90,
    }
    if "reference_period_desc" in df.columns:
        df["_pri"] = (df["reference_period_desc"].str.strip().str.upper()
                      .map(_REF_PRI_PROD).fillna(0).astype(int))
        df = (df.sort_values(["year", "state_alpha", "_pri", "Value"],
                             ascending=[True, True, False, False])
                .drop_duplicates(subset=["year", "state_alpha"], keep="first")
                .drop(columns=["_pri", "reference_period_desc"], errors="ignore"))
    else:
        df = df.groupby(["year", "state_alpha", "state_name"], as_index=False)["Value"].max()
    return df.rename(columns={"Value": "production_bu"})


def compute_hrw_weights(prod_df: pd.DataFrame, n_years: int = 10) -> dict:
    """
    Compute each HRW state's production share using the most recent n_years of
    NASS Winter wheat production data (NASS does not break state production out
    by sub-class; HRW states grow predominantly HRW so Winter = good proxy).
    States with < 0.5% share are dropped; remaining shares renormalised to 1.0.
    Falls back to HRW_WEIGHTS if the DataFrame is empty or computation fails.
    """
    if prod_df.empty:
        return HRW_WEIGHTS.copy()
    try:
        # Filter to HRW states only before computing shares
        hrw_states = WHEAT_CLASSES["HRW — Hard Red Winter"]
        recent_df  = prod_df[prod_df["state_alpha"].isin(hrw_states)].copy()
        if recent_df.empty:
            return HRW_WEIGHTS.copy()
        latest_years = sorted(recent_df["year"].unique())[-n_years:]
        recent       = recent_df[recent_df["year"].isin(latest_years)].copy()
        # One row per state per year — deduplicate by taking max value
        recent = recent.groupby(["year", "state_alpha"], as_index=False)["production_bu"].max()
        state_avg    = recent.groupby("state_alpha", as_index=False)["production_bu"].mean()
        total = state_avg["production_bu"].sum()
        if total == 0:
            return HRW_WEIGHTS.copy()
        state_avg["share"] = state_avg["production_bu"] / total
        # Drop noise states (< 0.5%)
        state_avg = state_avg[state_avg["share"] >= 0.005].copy()
        if state_avg.empty:
            return HRW_WEIGHTS.copy()
        # Renormalise so weights sum exactly to 1.0
        norm_total = state_avg["share"].sum()
        weights = {
            row["state_alpha"]: round(row["share"] / norm_total, 4)
            for _, row in state_avg.sort_values("share", ascending=False).iterrows()
        }
        return weights
    except Exception:
        return HRW_WEIGHTS.copy()


def _compute_class_weights(prod_df: pd.DataFrame, class_key: str, fallback: dict, n_years: int = 10) -> dict:
    """Generic production-weighted index helper for any WHEAT_CLASSES key."""
    if prod_df.empty:
        return fallback.copy()
    try:
        class_states = WHEAT_CLASSES[class_key]
        recent_df    = prod_df[prod_df["state_alpha"].isin(class_states)].copy()
        if recent_df.empty:
            return fallback.copy()
        latest_years = sorted(recent_df["year"].unique())[-n_years:]
        recent       = recent_df[recent_df["year"].isin(latest_years)].copy()
        recent       = recent.groupby(["year", "state_alpha"], as_index=False)["production_bu"].max()
        state_avg    = recent.groupby("state_alpha", as_index=False)["production_bu"].mean()
        total = state_avg["production_bu"].sum()
        if total == 0:
            return fallback.copy()
        state_avg["share"] = state_avg["production_bu"] / total
        state_avg = state_avg[state_avg["share"] >= 0.005].copy()
        if state_avg.empty:
            return fallback.copy()
        norm_total = state_avg["share"].sum()
        return {
            row["state_alpha"]: round(row["share"] / norm_total, 4)
            for _, row in state_avg.sort_values("share", ascending=False).iterrows()
        }
    except Exception:
        return fallback.copy()


def compute_srw_weights(prod_df: pd.DataFrame, n_years: int = 10) -> dict:
    return _compute_class_weights(prod_df, "SRW — Soft Red Winter", SRW_WEIGHTS, n_years)


def compute_white_weights(prod_df: pd.DataFrame, n_years: int = 10) -> dict:
    return _compute_class_weights(prod_df, "White Winter", WHITE_WEIGHTS, n_years)


def compute_class_weights_from_acres(acres_df: pd.DataFrame, class_key: str,
                                      fallback: dict, n_years: int = 10) -> dict:
    """
    Compute state weights using HARVESTED ACRES rather than production.

    This matches NASS's own methodology for computing published national class yields:
        National Yield = Σ(state_harvested_acres × state_yield) / Σ(state_harvested_acres)

    Using production (= acres × yield) as weights over-represents high-yielding states
    and under-represents low-yielding states, causing our index to diverge from NASS.
    Acres-based weights are yield-neutral and produce results consistent with NASS.
    """
    if acres_df.empty:
        return fallback.copy()
    try:
        class_states = WHEAT_CLASSES[class_key]
        # acres_df uses column "state" not "state_alpha"
        col = "state" if "state" in acres_df.columns else "state_alpha"
        sub = acres_df[acres_df[col].isin(class_states)].copy()
        if sub.empty:
            return fallback.copy()
        latest_years = sorted(sub["year"].unique())[-n_years:]
        sub = sub[sub["year"].isin(latest_years)]
        state_avg = (sub.groupby(col, as_index=False)["harvested_ac"].mean()
                       .rename(columns={col: "state_alpha"}))
        total = state_avg["harvested_ac"].sum()
        if total == 0:
            return fallback.copy()
        state_avg["share"] = state_avg["harvested_ac"] / total
        state_avg = state_avg[state_avg["share"] >= 0.005].copy()
        if state_avg.empty:
            return fallback.copy()
        norm_total = state_avg["share"].sum()
        return {
            row["state_alpha"]: round(row["share"] / norm_total, 4)
            for _, row in state_avg.sort_values("share", ascending=False).iterrows()
        }
    except Exception:
        return fallback.copy()


@st.cache_data(ttl=900, show_spinner=False)
def jsa_index(df: pd.DataFrame, cond_weights: dict | None = None) -> pd.DataFrame:
    """
    JSA weighted index per state / USDA year / week.
    Pass cond_weights to use empirically-calibrated weights; defaults to the
    equal-spaced CONDITION_WEIGHTS (VP=0 P=25 F=50 G=75 E=100).
    """
    _cw = cond_weights if cond_weights is not None else CONDITION_WEIGHTS
    s = _states_only(df).copy()
    s["weighted"] = s["condition"].map(_cw) * s["Value"] / 100
    return (
        s.groupby(["year", "week_ending", "state_alpha", "state_name"], as_index=False)["weighted"]
        .sum()
        .rename(columns={"weighted": "jsa_pct"})
    )


@st.cache_data(ttl=900, show_spinner=False)
def _us_series(raw_df: pd.DataFrame, condition: str, state_alpha: str = "US", cond_weights: dict | None = None) -> pd.DataFrame:
    """Return (year, week_ending, metric) for the given state (default: US TOTAL).
    Pass cond_weights to use empirically-calibrated JSA weights; defaults to CONDITION_WEIGHTS."""
    us = raw_df[raw_df["state_alpha"] == state_alpha].copy()
    if us.empty:
        return pd.DataFrame(columns=["year", "week_ending", "metric"])

    if condition == "Good + Excellent":
        rows = us[us["condition"].isin(["GOOD", "EXCELLENT"])]
    elif condition == "Poor + Very Poor":
        rows = us[us["condition"].isin(["POOR", "VERY POOR"])]
    elif condition == "Fair":
        rows = us[us["condition"] == "FAIR"]
    elif condition == "JSA Index":
        _cw = cond_weights if cond_weights is not None else CONDITION_WEIGHTS
        us["weighted"] = us["condition"].map(_cw) * us["Value"] / 100
        return (
            us.groupby(["year", "week_ending"], as_index=False)["weighted"]
            .sum()
            .rename(columns={"weighted": "metric"})
        )
    else:
        return pd.DataFrame(columns=["year", "week_ending", "metric"])

    return (
        rows.groupby(["year", "week_ending"], as_index=False)["Value"]
        .sum()
        .rename(columns={"Value": "metric"})
    )


@st.cache_data(ttl=900, show_spinner=False)
def hrw_series(raw_df: pd.DataFrame, condition: str, weights: dict | None = None, cond_weights: dict | None = None) -> pd.DataFrame:
    """
    Return (year, week_ending, metric) as a production-weighted HRW index.
    Pass `weights` to use dynamic state shares; defaults to HRW_WEIGHTS fallback.
    Pass `cond_weights` to use empirically-calibrated JSA weights; defaults to CONDITION_WEIGHTS.
    Normalises by the sum of weights present each week so missing states don't
    drag the index to zero.

    For years where NASS does not publish state-level condition data (typically
    before ~2012 in Quick Stats), falls back to the US national (US TOTAL) series
    so the full 1986-present history is preserved in the seasonal chart, ranking
    bar, and scatter plot.
    """
    _w         = weights if weights is not None else HRW_WEIGHTS
    hrw_states = set(_w.keys())
    base = _states_only(raw_df)
    hrw  = base[base["state_alpha"].isin(hrw_states)].copy()

    if condition == "JSA Index":
        _cw = cond_weights if cond_weights is not None else CONDITION_WEIGHTS
        if not hrw.empty:
            hrw["cond_val"] = hrw["condition"].map(_cw) * hrw["Value"] / 100
            agg = hrw.groupby(["year", "week_ending", "state_alpha"], as_index=False)["cond_val"].sum()
        else:
            agg = pd.DataFrame()
        val_col = "cond_val"
    elif condition == "Good + Excellent":
        if not hrw.empty:
            agg = (
                hrw[hrw["condition"].isin(["GOOD", "EXCELLENT"])]
                .groupby(["year", "week_ending", "state_alpha"], as_index=False)["Value"]
                .sum()
            )
        else:
            agg = pd.DataFrame()
        val_col = "Value"
    elif condition == "Poor + Very Poor":
        if not hrw.empty:
            agg = (
                hrw[hrw["condition"].isin(["POOR", "VERY POOR"])]
                .groupby(["year", "week_ending", "state_alpha"], as_index=False)["Value"]
                .sum()
            )
        else:
            agg = pd.DataFrame()
        val_col = "Value"
    elif condition == "Fair":
        if not hrw.empty:
            agg = (
                hrw[hrw["condition"] == "FAIR"]
                .groupby(["year", "week_ending", "state_alpha"], as_index=False)["Value"]
                .sum()
            )
        else:
            agg = pd.DataFrame()
        val_col = "Value"
    else:
        return pd.DataFrame(columns=["year", "week_ending", "metric"])

    # ── Build state-weighted HRW result ───────────────────────────────────────
    result_rows = []
    if not agg.empty:
        agg["w"] = agg["state_alpha"].map(_w)
        for (yr, wk), grp in agg.groupby(["year", "week_ending"]):
            grp = grp.dropna(subset=["w", val_col])
            if grp.empty:
                continue
            w_sum = grp["w"].sum()
            if w_sum == 0:
                continue
            val = (grp[val_col] * grp["w"]).sum() / w_sum
            result_rows.append({"year": int(yr), "week_ending": wk, "metric": val})

    state_result = pd.DataFrame(result_rows)

    # ── Fall back to US TOTAL for years missing from state-level data ─────────
    # NASS Quick Stats state-level weekly conditions data has a limited historical
    # archive (typically ~2012 onward for many states).  The US TOTAL row is
    # available back to 1986 and is a good HRW proxy since HRW states dominate
    # US winter wheat (KS alone ~25%).  Blending ensures full 1986-present history.
    us_result = _us_series(raw_df, condition, cond_weights=cond_weights)   # returns year / week_ending / metric
    if not us_result.empty:
        if not state_result.empty:
            hrw_years   = set(state_result["year"].unique())
            us_fallback = us_result[~us_result["year"].isin(hrw_years)].copy()
            if not us_fallback.empty:
                state_result = pd.concat([state_result, us_fallback], ignore_index=True)
        else:
            state_result = us_result.copy()

    if state_result.empty:
        return pd.DataFrame(columns=["year", "week_ending", "metric"])
    return state_result.sort_values(["year", "week_ending"]).reset_index(drop=True)


@st.cache_data(ttl=900, show_spinner=False)
def compute_hrw_kpis(raw_df: pd.DataFrame, condition: str, target_usda_year: int, target_week: pd.Timestamp | None = None, weights: dict | None = None) -> dict:
    """Compute HRW weighted-index KPIs (same structure as compute_national_kpis)."""
    nan4 = {"current": float("nan"), "wow": float("nan"), "yoy": float("nan"), "vs_olympic": float("nan")}
    series = hrw_series(raw_df, condition, weights=weights)
    if series.empty:
        return nan4

    yr = series[series["year"] == target_usda_year]
    if yr.empty:
        return nan4

    latest_week = target_week if target_week is not None else yr["week_ending"].max()
    if latest_week not in yr["week_ending"].values:
        idx = (yr["week_ending"] - latest_week).abs().idxmin()
        latest_week = yr.loc[idx, "week_ending"]

    cur = yr[yr["week_ending"] == latest_week]["metric"].values
    current = cur[0] if len(cur) else float("nan")

    # WoW
    prior_dt = yr[yr["week_ending"] < latest_week]["week_ending"].max()
    if pd.notna(prior_dt):
        pw = yr[yr["week_ending"] == prior_dt]["metric"].values
        wow = current - (pw[0] if len(pw) else float("nan"))
    else:
        wow = float("nan")

    # YoY
    py = series[series["year"] == target_usda_year - 1]
    if not py.empty:
        try:
            t_py = latest_week.replace(year=target_usda_year - 1)
        except ValueError:
            t_py = latest_week.replace(year=target_usda_year - 1, day=28)
        idx = (py["week_ending"] - t_py).abs().idxmin()
        yoy = current - py.loc[idx, "metric"]
    else:
        yoy = float("nan")

    # Olympic average (last 6 years prior to target)
    oly_years = sorted([y for y in series["year"].unique() if y < target_usda_year])[-6:]
    oly_vals = []
    for yr_o in oly_years:
        yr_data = series[series["year"] == yr_o]
        if yr_data.empty:
            continue
        try:
            t = latest_week.replace(year=yr_o)
        except ValueError:
            t = latest_week.replace(year=yr_o, day=28)
        idx = (yr_data["week_ending"] - t).abs().idxmin()
        oly_vals.append(yr_data.loc[idx, "metric"])
    oly = olympic_avg(oly_vals)

    return {"current": current, "wow": wow, "yoy": yoy, "vs_olympic": current - oly}


@st.cache_data(ttl=900, show_spinner=False)
def compute_national_kpis(raw_df: pd.DataFrame, condition: str, target_usda_year: int, target_week: pd.Timestamp | None = None) -> dict:
    """Compute national KPIs directly from USDA US TOTAL rows."""
    nan4 = {"current": float("nan"), "wow": float("nan"), "yoy": float("nan"), "vs_olympic": float("nan")}
    series = _us_series(raw_df, condition)
    if series.empty:
        return nan4

    yr = series[series["year"] == target_usda_year]
    if yr.empty:
        return nan4

    latest_week = target_week if target_week is not None else yr["week_ending"].max()
    # If a specific week is requested but not present, snap to closest available
    if latest_week not in yr["week_ending"].values:
        idx = (yr["week_ending"] - latest_week).abs().idxmin()
        latest_week = yr.loc[idx, "week_ending"]
    cur = yr[yr["week_ending"] == latest_week]["metric"].values
    current = cur[0] if len(cur) else float("nan")

    # WoW
    prior_dt = yr[yr["week_ending"] < latest_week]["week_ending"].max()
    if pd.notna(prior_dt):
        pw = yr[yr["week_ending"] == prior_dt]["metric"].values
        wow = current - (pw[0] if len(pw) else float("nan"))
    else:
        wow = float("nan")

    # YoY – closest calendar week in prior year
    py = series[series["year"] == target_usda_year - 1]
    if not py.empty:
        try:
            t_py = latest_week.replace(year=target_usda_year - 1)
        except ValueError:
            t_py = latest_week.replace(year=target_usda_year - 1, day=28)
        idx = (py["week_ending"] - t_py).abs().idxmin()
        yoy = current - py.loc[idx, "metric"]
    else:
        yoy = float("nan")

    # Olympic average (last 6 years prior to target)
    oly_years = sorted([y for y in series["year"].unique() if y < target_usda_year])[-6:]
    oly_vals = []
    for yr_o in oly_years:
        yr_data = series[series["year"] == yr_o]
        if yr_data.empty:
            continue
        try:
            t = latest_week.replace(year=yr_o)
        except ValueError:
            t = latest_week.replace(year=yr_o, day=28)
        idx = (yr_data["week_ending"] - t).abs().idxmin()
        oly_vals.append(yr_data.loc[idx, "metric"])
    oly = olympic_avg(oly_vals)

    return {"current": current, "wow": wow, "yoy": yoy, "vs_olympic": current - oly}


def olympic_avg(values: list) -> float:
    """6-year Olympic average: drop highest & lowest, mean the rest (min 3 values)."""
    vals = sorted([v for v in values if pd.notna(v)])
    if len(vals) < 3:
        return float("nan")
    if len(vals) > 6:
        vals = vals[-6:]
    return float(np.mean(vals[1:-1]))


def _fill_harvest_fallback(df: pd.DataFrame, cur_year: int, n_years: int = 5) -> pd.DataFrame:
    """
    For any row where year == cur_year and harvested_ac is NaN (USDA has not yet
    published harvested acres) but planted_ac is available, estimate harvested_ac as:

        planted_ac × olympic_avg(% harvested over the n most recent historical years)

    Works for both state-level DataFrames (requires 'state_alpha' column) and
    national-level DataFrames (no grouping needed).

    Adds a boolean column '_harvested_est' = True for every row that was estimated,
    so callers can annotate the UI (e.g. asterisk, footnote).

    Only fills rows for cur_year — historical rows are never touched.
    """
    if df.empty or "planted_ac" not in df.columns or "harvested_ac" not in df.columns:
        return df
    df = df.copy()
    df["_harvested_est"] = False

    grp_col = "state_alpha" if "state_alpha" in df.columns else None

    # Historical rows: before cur_year, both acres valid
    hist = df[
        (df["year"] < cur_year)
        & df["planted_ac"].notna() & (df["planted_ac"] > 0)
        & df["harvested_ac"].notna() & (df["harvested_ac"] > 0)
    ].copy()
    hist["_pct"] = hist["harvested_ac"] / hist["planted_ac"]

    # Current-year rows needing an estimate
    cur_mask = (
        (df["year"] == cur_year)
        & df["harvested_ac"].isna()
        & df["planted_ac"].notna()
        & (df["planted_ac"] > 0)
    )

    if not cur_mask.any():
        return df

    if grp_col:
        # State-level: compute a separate olympic avg per state
        for state in df.loc[cur_mask, grp_col].unique():
            state_pcts = (
                hist[hist[grp_col] == state]
                .sort_values("year")
                .tail(n_years)["_pct"]
                .tolist()
            )
            avg_pct = olympic_avg(state_pcts)
            if not np.isnan(avg_pct):
                mask = cur_mask & (df[grp_col] == state)
                df.loc[mask, "harvested_ac"] = (
                    df.loc[mask, "planted_ac"] * avg_pct
                ).round(0)
                df.loc[mask, "_harvested_est"] = True
    else:
        # National-level: single olympic avg across all historical rows
        nat_pcts = hist.sort_values("year").tail(n_years)["_pct"].tolist()
        avg_pct  = olympic_avg(nat_pcts)
        if not np.isnan(avg_pct):
            df.loc[cur_mask, "harvested_ac"] = (
                df.loc[cur_mask, "planted_ac"] * avg_pct
            ).round(0)
            df.loc[cur_mask, "_harvested_est"] = True

    return df


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_winter_wheat_acres(years: tuple, class_desc: str = "WINTER") -> pd.DataFrame:
    """
    Fetch national winter wheat planted and harvested acres from USDA NASS.
    Uses bulk calls (year__GE / year__LE) — 3 API calls total.
    class_desc: keyword matched against short_desc (e.g. 'WINTER', 'HARD RED WINTER').
    Returns DataFrame: year, planted_ac, harvested_ac, abandoned_ac, abandonment_pct, pct_harvested

    class_desc handling: class_desc is NOT sent to the API (NASS does not reliably
    index it for area records).  We fetch all wheat area data and filter by short_desc
    — the same approach used for conditions data.
    """
    if not years:
        return pd.DataFrame()
    min_yr, max_yr = min(years), max(years)
    yr_set = set(years)

    base = {
        "key":          API_KEY,
        "commodity_desc": "WHEAT",
        # class_desc intentionally omitted — filter by short_desc after fetching
        "agg_level_desc": "NATIONAL",
        "unit_desc":    "ACRES",
        "source_desc":  "SURVEY",
        "year__GE":     str(min_yr),
        "year__LE":     str(max_yr),
        "format":       "JSON",
    }

    def _parse(payload, val_key):
        if "_error" in payload:
            return []
        rows = []
        for r in payload.get("data", []):
            v  = pd.to_numeric(str(r.get("Value", "")).replace(",", ""), errors="coerce")
            yr = r.get("year")
            sd = r.get("short_desc", "")
            if pd.notna(v) and yr and int(yr) in yr_set:
                rows.append({"year": int(yr), "short_desc": sd, val_key: v})
        return rows

    def _class_filter(rows: list) -> list:
        """Keep only rows whose short_desc contains the class keyword."""
        _skip = {"ALL CLASSES", "ALL", ""}
        if class_desc and class_desc.upper() not in _skip:
            return [r for r in rows if class_desc.lower() in r.get("short_desc", "").lower()]
        return rows

    # Planted — query both reference periods; take max per year for full coverage
    planted_rows = []
    for ref in ["YEAR", "YEAR - DEC ACREAGE"]:
        planted_rows += _parse(
            _nass_get({**base, "statisticcat_desc": "AREA PLANTED", "reference_period_desc": ref}),
            "planted_ac",
        )
    planted_rows = _class_filter(planted_rows)

    # Harvested — annual final figure
    harvested_rows = _class_filter(_parse(
        _nass_get({**base, "statisticcat_desc": "AREA HARVESTED", "reference_period_desc": "YEAR"}),
        "harvested_ac",
    ))

    if not planted_rows or not harvested_rows:
        return pd.DataFrame()

    p_df = pd.DataFrame(planted_rows).groupby("year")["planted_ac"].max().reset_index()
    h_df = pd.DataFrame(harvested_rows).groupby("year")["harvested_ac"].max().reset_index()
    df   = p_df.merge(h_df, on="year", how="inner")
    df["harvested_ac"]    = df[["planted_ac", "harvested_ac"]].min(axis=1)  # physical cap
    df["abandoned_ac"]    = df["planted_ac"] - df["harvested_ac"]
    df["abandonment_pct"] = (df["abandoned_ac"] / df["planted_ac"] * 100).round(1)
    df["pct_harvested"]   = (df["harvested_ac"] / df["planted_ac"] * 100).round(1)
    return df.sort_values("year").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_ww_state_acres(years: tuple) -> pd.DataFrame:
    """
    Fetch state-level winter wheat planted and harvested acres from USDA NASS.
    Uses bulk range calls (year__GE / year__LE) for efficiency.
    Returns DataFrame: year, state, planted_ac, harvested_ac

    class_desc intentionally omitted from query — filter by short_desc after fetching.

    Planted acres: no reference_period_desc filter — captures all NASS reports
    (Jan Seedings, Mar Prospective Plantings, Jun Acreage, Crop Production, Annual
    Summary) and selects the highest-priority estimate per state-year so that
    final numbers (Annual Summary) automatically supersede earlier estimates.

    Merge uses outer join so a state-year is retained even if only planted OR
    harvested data is available (prevents recent years from being silently dropped
    when one series publishes before the other).
    """
    if not years:
        return pd.DataFrame()
    min_yr, max_yr = min(years), max(years)
    yr_set = set(years)

    # Priority order for reference_period_desc — higher = more authoritative.
    # Verified against actual NASS QuickStats output (May 2026 diagnostic).
    # YEAR = confirmed Annual Summary (always wins).
    # DEC ACREAGE is the *seedings* estimate (first pass, often overestimates
    # planted relative to the confirmed final) so it gets the lowest priority.
    _REF_PRIORITY: dict = {
        "YEAR":                 100,  # Final Annual Summary — always authoritative
        "YEAR - AUG FORECAST":   70,  # August Crop Production — very close to final
        "YEAR - JUN ACREAGE":    60,  # June Acreage Report
        "YEAR - MAR ACREAGE":    40,  # March Prospective Plantings
        "YEAR - DEC ACREAGE":    20,  # December Seedings — earliest estimate, often overestimates planted
    }

    base = {
        "key":            API_KEY,
        "commodity_desc": "WHEAT",
        "agg_level_desc": "STATE",
        "unit_desc":      "ACRES",
        "source_desc":    "SURVEY",
        "year__GE":       str(min_yr),
        "year__LE":       str(max_yr),
        "format":         "JSON",
    }

    def _parse_state(payload, val_key, include_ref=False):
        if "_error" in payload:
            return []
        rows = []
        for r in payload.get("data", []):
            v     = pd.to_numeric(str(r.get("Value", "")).replace(",", ""), errors="coerce")
            yr    = r.get("year")
            state = r.get("state_alpha", "").strip().upper()
            sd    = r.get("short_desc", "")
            if pd.notna(v) and v > 0 and yr and state and int(yr) in yr_set:
                row = {"year": int(yr), "state": state, "short_desc": sd, val_key: float(v)}
                if include_ref:
                    ref = r.get("reference_period_desc", "").strip().upper()
                    row["ref_period"] = ref   # store raw string for priority remapping
                rows.append(row)
        return rows

    def _winter_filter(rows: list) -> list:
        return [r for r in rows if "winter" in r.get("short_desc", "").lower()]

    # Planted — no reference_period_desc filter: one call gets all NASS reports
    planted_rows = _winter_filter(
        _parse_state(
            _nass_get({**base, "statisticcat_desc": "AREA PLANTED"}),
            "planted_ac",
            include_ref=True,
        )
    )

    # Harvested — no ref filter: gets YEAR (final) plus all monthly forecasts.
    # Priority ensures YEAR wins; forecasts fill in recent years before final publishes.
    _REF_PRIORITY_HARV: dict = {
        "YEAR":                 100,  # Final Annual Summary
        "YEAR - AUG FORECAST":   70,  # August Crop Production — harvest nearly done
        "YEAR - JUL FORECAST":   60,  # July Crop Production
        "YEAR - JUN ACREAGE":    50,  # June Acreage Report
        "YEAR - JUN FORECAST":   40,  # June Crop Production forecast
        "YEAR - MAY FORECAST":   30,  # May Crop Production (earliest)
    }
    harvested_rows = _winter_filter(
        _parse_state(
            _nass_get({**base, "statisticcat_desc": "AREA HARVESTED"}),
            "harvested_ac",
            include_ref=True,
        )
    )

    if not planted_rows:
        return pd.DataFrame()

    def _priority_dedup(rows, val_col, priority_map):
        """Keep the highest-priority reference period per (year, state); tie-break on value."""
        df = pd.DataFrame(rows)
        df["priority"] = df["ref_period"].map(priority_map).fillna(0).astype(int)
        return (df.sort_values(["year", "state", "priority", val_col],
                               ascending=[True, True, False, False])
                  .drop_duplicates(subset=["year", "state"], keep="first")
                  [["year", "state", val_col]])

    p_df = _priority_dedup(planted_rows,  "planted_ac",  _REF_PRIORITY)

    if not harvested_rows:
        h_df = pd.DataFrame(columns=["year", "state", "harvested_ac"])
    else:
        h_df = _priority_dedup(harvested_rows, "harvested_ac", _REF_PRIORITY_HARV)

    # Outer join: retain state-years present in either series
    df = p_df.merge(h_df, on=["year", "state"], how="outer")

    # Physical cap: harvested cannot exceed planted
    mask = df["planted_ac"].notna() & df["harvested_ac"].notna()
    df.loc[mask, "harvested_ac"] = df.loc[mask, ["planted_ac", "harvested_ac"]].min(axis=1)

    return df.sort_values(["year", "state"]).reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_class_state_acres(class_desc_str: str, years: tuple) -> pd.DataFrame:
    """
    Fetch state-level AREA PLANTED and AREA HARVESTED for a specific winter wheat
    class (e.g. 'HARD RED WINTER', 'SOFT RED WINTER', 'SOFT WHITE') from NASS.

    Uses the same reference-period priority dedup as fetch_ww_state_acres so that
    the final Annual Summary is always preferred over in-season estimates.

    Used to ensure % harvested regressions for HRW / SRW / White are calibrated on
    class-specific USDA final acres rather than total-winter-wheat state proxies,
    which can differ because some states grow multiple winter wheat classes.

    Returns DataFrame: year, state, planted_ac, harvested_ac.
    Returns empty DataFrame if NASS has no class-specific data for the request.
    """
    _REF_PRIORITY = {
        "YEAR": 100, "YEAR - AUG FORECAST": 70, "YEAR - JUL FORECAST": 60,
        "YEAR - JUN ACREAGE": 55, "YEAR - JUN FORECAST": 50,
        "YEAR - MAR ACREAGE": 40, "YEAR - DEC ACREAGE": 20,
    }
    _REF_PRIORITY_HARV = {
        "YEAR": 100, "YEAR - AUG FORECAST": 70, "YEAR - JUL FORECAST": 60,
        "YEAR - JUN ACREAGE": 50, "YEAR - JUN FORECAST": 40, "YEAR - MAY FORECAST": 30,
    }
    if not years:
        return pd.DataFrame()
    min_yr, max_yr = min(years), max(years)
    yr_set = set(years)
    base = {
        "key":            API_KEY,
        "commodity_desc": "WHEAT",
        "class_desc":     class_desc_str,
        "agg_level_desc": "STATE",
        "unit_desc":      "ACRES",
        "source_desc":    "SURVEY",
        "year__GE":       str(min_yr),
        "year__LE":       str(max_yr),
        "format":         "JSON",
    }

    def _parse(payload, val_key, pri_map):
        rows = []
        for r in payload.get("data", []):
            v     = pd.to_numeric(str(r.get("Value", "")).replace(",", ""), errors="coerce")
            yr    = r.get("year")
            state = r.get("state_alpha", "").strip().upper()
            ref   = r.get("reference_period_desc", "").strip().upper()
            if pd.notna(v) and v > 0 and yr and state and int(yr) in yr_set and len(state) == 2:
                rows.append({"year": int(yr), "state": state,
                             "value": float(v),
                             "priority": pri_map.get(ref, 0)})
        if not rows:
            return pd.DataFrame(columns=["year", "state", "value"])
        df = pd.DataFrame(rows)
        return (df.sort_values(["year", "state", "priority", "value"],
                               ascending=[True, True, False, False])
                  .drop_duplicates(subset=["year", "state"], keep="first")
                  [["year", "state", "value"]])

    plt_payload = _nass_get({**base, "statisticcat_desc": "AREA PLANTED"})
    hrv_payload = _nass_get({**base, "statisticcat_desc": "AREA HARVESTED"})

    p_df = _parse(plt_payload, "planted_ac",  _REF_PRIORITY)
    h_df = _parse(hrv_payload, "harvested_ac", _REF_PRIORITY_HARV)

    # NASS uses different class_desc values across commodities and stat categories.
    # White winter wheat is sometimes recorded as "SOFT WHITE WINTER" for area
    # queries even though production uses "SOFT WHITE".  Try the alternate descriptor
    # so we don't silently return empty and fall back to the total-WW proxy.
    if p_df.empty and h_df.empty:
        _alt_map = {
            "SOFT WHITE":        "SOFT WHITE WINTER",
            "SOFT WHITE WINTER": "SOFT WHITE",
            "HARD WHITE":        "HARD WHITE WINTER",
        }
        _alt = _alt_map.get(class_desc_str.upper())
        if _alt:
            _base_alt = {**base, "class_desc": _alt}
            _p2 = _parse(_nass_get({**_base_alt, "statisticcat_desc": "AREA PLANTED"}),
                         "planted_ac", _REF_PRIORITY)
            _h2 = _parse(_nass_get({**_base_alt, "statisticcat_desc": "AREA HARVESTED"}),
                         "harvested_ac", _REF_PRIORITY_HARV)
            if not _p2.empty or not _h2.empty:
                p_df, h_df = _p2, _h2

    if p_df.empty and h_df.empty:
        return pd.DataFrame()

    p_df = p_df.rename(columns={"value": "planted_ac"})
    h_df = h_df.rename(columns={"value": "harvested_ac"})

    df = p_df.merge(h_df, on=["year", "state"], how="outer")
    # Physical cap: harvested cannot exceed planted
    mask = df["planted_ac"].notna() & df["harvested_ac"].notna()
    df.loc[mask, "harvested_ac"] = df.loc[mask, ["planted_ac", "harvested_ac"]].min(axis=1)
    return df.sort_values(["year", "state"]).reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_class_national_acres(class_key: str, years: tuple) -> pd.DataFrame:
    """
    Fetch USDA NASS national (US TOTAL) area harvested for one winter wheat class
    using exact short_desc matching — the same proven approach as fetch_ww_national_totals.

    class_key must be one of: "HRW", "SRW", "White".

    NASS publishes class-specific AREA HARVESTED at national level (confirmed).
    NASS does NOT publish class-specific AREA PLANTED at national level — the seedings
    survey only reports total all-winter wheat, not broken down by class.

    Returns DataFrame: year, harvested_ac.
    Returns empty DataFrame if NASS has no harvested data for the class.

    Usage: the caller combines NASS class harvested (numerator) with state-sum planted
    (denominator) to compute % harvested.  This is the most accurate available
    approach since planted-by-class is not a published NASS series.
    """
    _SD_PREFIX = {
        "HRW":   "WHEAT, WINTER, RED, HARD",
        "SRW":   "WHEAT, WINTER, RED, SOFT",
        "White": "WHEAT, WINTER, WHITE",
    }
    _pfx = _SD_PREFIX.get(class_key)
    if not _pfx or not years:
        return pd.DataFrame()

    _REF_PRI = {
        "YEAR": 100, "YEAR - AUG FORECAST": 70, "YEAR - JUL FORECAST": 60,
        "YEAR - JUN ACREAGE": 55, "YEAR - JUN FORECAST": 50,
        "YEAR - MAR ACREAGE": 40, "YEAR - MAY FORECAST": 30, "YEAR - DEC ACREAGE": 20,
    }

    _base = {
        "key":            API_KEY,
        "source_desc":    "SURVEY",
        "sector_desc":    "CROPS",
        "group_desc":     "FIELD CROPS",
        "commodity_desc": "WHEAT",
        "state_name":     "US TOTAL",
        "freq_desc":      "ANNUAL",
        "year__GE":       str(min(years)),
        "year__LE":       str(max(years)),
        "format":         "JSON",
    }

    def _best_by_year(df: pd.DataFrame, sd_exact: str) -> dict:
        if df.empty or "short_desc" not in df.columns or "Value" not in df.columns:
            return {}
        df = df[df["short_desc"] == sd_exact].copy()
        if df.empty:
            return {}
        df["_v"]   = pd.to_numeric(df["Value"].astype(str).str.replace(",", ""), errors="coerce")
        df["_pri"] = (df.get("reference_period_desc", pd.Series([""] * len(df)))
                      .str.strip().str.upper().map(_REF_PRI).fillna(0).astype(int))
        df["year"] = df["year"].astype(int)
        df = df.dropna(subset=["_v"])
        result = {}
        for yr, grp in df.groupby("year"):
            result[int(yr)] = float(grp.sort_values("_pri", ascending=False)["_v"].iloc[0])
        return result

    _hrv_sd = f"{_pfx} - AREA HARVESTED, MEASURED IN ACRES"
    _h_raw  = _nass_get({**_base, "statisticcat_desc": "AREA HARVESTED"})
    _h_df   = pd.DataFrame(_h_raw.get("data", []))
    _hrv_by_yr = _best_by_year(_h_df, _hrv_sd)

    if not _hrv_by_yr:
        return pd.DataFrame()

    out = pd.DataFrame([
        {"year": yr, "harvested_ac": v}
        for yr, v in sorted(_hrv_by_yr.items())
    ])
    return out.sort_values("year").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_commodity_acres(commodity_desc: str, class_desc: str, years: tuple) -> pd.DataFrame:
    """
    Fetch state-level planted and harvested acres for any commodity from USDA NASS.
    Returns DataFrame: year, state_alpha, planted_ac, harvested_ac

    Uses priority-based deduplication (Final Annual Summary preferred, then in-season
    estimates) so that current-year planted acres from the June Acreage Report are
    included even when the Final Annual Summary is not yet published.
    """
    # Higher = more authoritative.  Final Annual Summary always wins.
    _REF_PRIORITY = {
        "YEAR":                100,
        "YEAR - AUG FORECAST":  70,
        "YEAR - JUL FORECAST":  65,
        "YEAR - JUN ACREAGE":   60,
        "YEAR - JUN FORECAST":  55,
        "YEAR - MAY FORECAST":  40,
        "YEAR - MAR ACREAGE":   35,
        "YEAR - DEC ACREAGE":   20,
    }
    if not years:
        return pd.DataFrame()
    min_yr, max_yr = min(years), max(years)
    base = {
        "key":            API_KEY,
        "commodity_desc": commodity_desc,
        "class_desc":     class_desc,
        "agg_level_desc": "STATE",
        "unit_desc":      "ACRES",
        "source_desc":    "SURVEY",
        "freq_desc":      "ANNUAL",
        "year__GE":       str(min_yr),
        "year__LE":       str(max_yr),
        "format":         "JSON",
        # No reference_period_desc filter — accept all report types and dedup below
    }
    frames = []
    for stat in ("AREA PLANTED", "AREA HARVESTED"):
        p = {**base, "statisticcat_desc": stat}
        pl = _nass_get(p)
        if "data" not in pl or not pl["data"]:
            continue
        df = pd.DataFrame(pl["data"])
        col = "planted_ac" if stat == "AREA PLANTED" else "harvested_ac"
        df["value"] = pd.to_numeric(
            df["Value"].astype(str).str.replace(",", "", regex=False), errors="coerce"
        )
        df["year"] = df["year"].astype(int)
        df["_pri"] = (df.get("reference_period_desc", pd.Series("", index=df.index))
                      .astype(str).str.strip().str.upper()
                      .map(_REF_PRIORITY).fillna(0).astype(int))
        df = df[["year", "state_alpha", "value", "_pri"]].dropna(subset=["value"])
        df = df[df["state_alpha"].str.len() == 2]
        df = df[df["state_alpha"] != "US"]
        df = df[df["value"] > 0]
        # Keep highest-priority estimate per (year, state); break ties by taking max value
        df = (df.sort_values(["year", "state_alpha", "_pri", "value"],
                             ascending=[True, True, False, False])
                .drop_duplicates(subset=["year", "state_alpha"], keep="first")
                .drop(columns=["_pri"]))
        df = df.rename(columns={"value": col})
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    merged = frames[0].merge(frames[1], on=["year", "state_alpha"], how="outer")
    # Physical cap: harvested <= planted
    if "planted_ac" in merged.columns and "harvested_ac" in merged.columns:
        mask = merged["planted_ac"].notna() & merged["harvested_ac"].notna()
        merged.loc[mask, "harvested_ac"] = merged.loc[mask, ["planted_ac", "harvested_ac"]].min(axis=1)
    return merged.sort_values(["year", "state_alpha"]).reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_planted_acres_for_year(year: int) -> pd.DataFrame:
    """Fetch state-level WINTER wheat AREA PLANTED from NASS for an exact crop year.

    Queries WITHOUT a reference_period_desc restriction so a single API call
    captures estimates from every NASS report published for that crop year:

        Jan  — Winter Wheat & Canola Seedings (first estimate; 2026 crop = fall 2025 planted)
        Mar  — Prospective Plantings (farmer intentions update)
        Jun  — Acreage Report (main realised acreage release)
        Monthly Crop Production — incremental updates through harvest
        Jan (next yr) — Final annual estimate

    When NASS publishes a new report and loads it into QuickStats, the next
    cache refresh (ttl=3600) automatically picks up the latest numbers.

    Among multiple entries per state, a priority table selects the most
    authoritative estimate available (verified against actual NASS output):
        YEAR (final Annual Summary)  >  YEAR - AUG FORECAST  >  YEAR - JUN ACREAGE
        >  YEAR - MAR ACREAGE  >  YEAR - DEC ACREAGE (seedings, often overestimates)

    Returns DataFrame with columns: state_alpha, planted_ac, ref_period.
    """
    # Higher number = more authoritative/final.
    # YEAR - DEC ACREAGE is the December Seedings report — the FIRST estimate
    # and is known to overestimate final planted acres, so it is lowest priority.
    _REF_PRIORITY: dict = {
        "YEAR":                 100,  # Final Annual Summary — always authoritative
        "YEAR - AUG FORECAST":   70,  # August Crop Production — very close to final
        "YEAR - JUN ACREAGE":    60,  # June Acreage Report
        "YEAR - MAR ACREAGE":    40,  # March Prospective Plantings
        "YEAR - DEC ACREAGE":    20,  # December Seedings — earliest, often overestimates
    }

    params = {
        "key":               API_KEY,
        "commodity_desc":    "WHEAT",
        "agg_level_desc":    "STATE",
        "unit_desc":         "ACRES",
        "source_desc":       "SURVEY",
        "statisticcat_desc": "AREA PLANTED",
        "year":              str(year),
        "format":            "JSON",
        # No reference_period_desc filter — return all reports for the year
    }
    payload = _nass_get(params)
    if "_error" in payload or "data" not in payload:
        return pd.DataFrame()

    rows: list = []
    for r in payload.get("data", []):
        sd   = r.get("short_desc", "")
        if "winter" not in sd.lower():
            continue
        v    = pd.to_numeric(str(r.get("Value", "")).replace(",", ""), errors="coerce")
        st_a = r.get("state_alpha", "").strip().upper()
        ref  = r.get("reference_period_desc", "").strip().upper()
        if pd.notna(v) and v > 0 and len(st_a) == 2 and st_a != "US":
            rows.append({
                "state_alpha": st_a,
                "planted_ac":  float(v),
                "priority":    _REF_PRIORITY.get(ref, 0),
                "ref_period":  ref,
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # For each state keep the row with the highest-priority reference period;
    # break ties by taking the larger value (more conservative / final tends to be larger)
    df = (df.sort_values(["state_alpha", "priority", "planted_ac"],
                         ascending=[True, False, False])
            .drop_duplicates(subset="state_alpha", keep="first")
            .reset_index(drop=True))
    return df[["state_alpha", "planted_ac", "ref_period"]]


def _class_acres_from_state(state_df: "pd.DataFrame", weights: dict) -> "pd.DataFrame":
    """
    Sum planted and harvested acres for all states present in `weights`,
    then compute abandonment metrics. Weights identify which states belong to
    the class; the actual acres are summed (not weighted) to reflect real acreage.
    """
    if state_df.empty or not weights:
        return pd.DataFrame()
    class_states = set(weights.keys())
    sub = state_df[state_df["state"].isin(class_states)]
    if sub.empty:
        return pd.DataFrame()
    df = sub.groupby("year").agg(
        planted_ac=("planted_ac", "sum"),
        harvested_ac=("harvested_ac", "sum"),
    ).reset_index()
    df["abandoned_ac"]    = df["planted_ac"] - df["harvested_ac"]
    df["abandonment_pct"] = (df["abandoned_ac"] / df["planted_ac"] * 100).round(1)
    df["pct_harvested"]   = (df["harvested_ac"] / df["planted_ac"] * 100).round(1)
    return df.sort_values("year").reset_index(drop=True)


def _render_abandon_panel(
    ab_df: "pd.DataFrame",
    jsa_snap: dict,
    class_label: str,
    accent_color: str,
    sel_usda_yr: int,
    use_jsa_model: bool = False,
    forecast_pct_override: "float | None" = None,
) -> None:
    """Render the % harvested time-series + scatter panel for one wheat class.

    use_jsa_model=True  → forecast uses 10-yr abandoned_ac ~ JSA regression ÷ planted.
    use_jsa_model=False → forecast uses pure 10-yr rolling avg abandoned acres ÷ planted.
    forecast_pct_override → when provided, skip the internal forecast computation and use
                            this value directly as _cur_pred_pct.  Pass the pre-computed
                            value from the production tab's _ph_cls so both tabs are
                            guaranteed to show the identical number.
    """
    if ab_df.empty:
        st.warning(f"No USDA NASS data available for {class_label}.")
        return

    # ── KPI metrics ────────────────────────────────────────────────────────
    _hist = ab_df[ab_df["year"] < sel_usda_yr].copy()
    _hist["jsa_index"] = _hist["year"].map(jsa_snap)
    _corr_df  = _hist.dropna(subset=["jsa_index", "pct_harvested"])
    _corr_val = (
        float(np.corrcoef(_corr_df["jsa_index"], _corr_df["pct_harvested"])[0, 1])
        if len(_corr_df) > 2 else float("nan")
    )

    if not _hist.empty:
        _avg_pct = _hist["pct_harvested"].mean()
        _min_row = _hist.loc[_hist["pct_harvested"].idxmin()]
        _max_row = _hist.loc[_hist["pct_harvested"].idxmax()]
    else:
        _avg_pct = float("nan")
        _min_row = _max_row = None

    _k1, _k2, _k3, _k4 = st.columns(4)
    with _k1:
        st.metric("Avg % Harvested", f"{_avg_pct:.1f}%" if not np.isnan(_avg_pct) else "N/A")
    with _k2:
        st.metric(
            "Best Year",
            f"{int(_max_row['year'])}  ({_max_row['pct_harvested']:.1f}%)" if _max_row is not None else "N/A",
        )
    with _k3:
        st.metric(
            "Worst Year",
            f"{int(_min_row['year'])}  ({_min_row['pct_harvested']:.1f}%)" if _min_row is not None else "N/A",
        )
    with _k4:
        _corr_str = f"{_corr_val:+.3f}" if not np.isnan(_corr_val) else "N/A"
        st.metric("JSA Correlation (r)", _corr_str)

    # ── Time-series: overlapping bars + % harvested line ──────────────────
    _fig_ts = go.Figure()
    _fig_ts.add_trace(go.Bar(
        x=ab_df["year"], y=ab_df["planted_ac"] / 1e6,
        name="Planted",
        marker_color="rgba(99,149,210,0.45)",
        hovertemplate="<b>%{x}</b><br>Planted: %{y:.3f}M ac<extra></extra>",
    ))
    _fig_ts.add_trace(go.Bar(
        x=ab_df["year"], y=ab_df["harvested_ac"] / 1e6,
        name="Harvested",
        marker_color="rgba(26,152,80,0.75)",
        hovertemplate="<b>%{x}</b><br>Harvested: %{y:.3f}M ac<extra></extra>",
    ))
    _fig_ts.add_trace(go.Scatter(
        x=ab_df["year"], y=ab_df["pct_harvested"],
        name="% Harvested",
        mode="lines+markers",
        line=dict(color=accent_color, width=2.5),
        marker=dict(size=5),
        yaxis="y2",
        hovertemplate="<b>%{x}</b><br>% Harvested: %{y:.1f}%<extra></extra>",
    ))
    _fig_ts.update_layout(
        barmode="overlay",
        xaxis=dict(title="Crop Year", gridcolor=DM_BORDER, color=DM_MUTED,
                   tickfont=dict(color=DM_MUTED), title_font=dict(color=DM_MUTED)),
        yaxis=dict(title="Acres (millions)", gridcolor=DM_BORDER, color=DM_MUTED,
                   tickfont=dict(color=DM_MUTED), title_font=dict(color=DM_MUTED),
                   tickformat=".1f"),
        yaxis2=dict(title="% Harvested", overlaying="y", side="right",
                    ticksuffix="%", showgrid=False,
                    tickfont=dict(color=accent_color), title_font=dict(color=accent_color)),
        paper_bgcolor=DM_BG, plot_bgcolor=DM_SURFACE2,
        legend=dict(bgcolor=DM_SURFACE, bordercolor=DM_BORDER, borderwidth=1,
                    font=dict(color=DM_TEXT), orientation="h",
                    yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=30, b=10),
        height=330,
        hovermode="x unified",
    )
    _wm_center(_fig_ts, opacity=0.05)
    _show_chart(_fig_ts, "planted_harvested_trend")

    # ── Nominal Abandoned Acres — theory test ─────────────────────────────────
    # Hypothesis: a structurally fixed volume of acres is abandoned for grazing
    # each year regardless of conditions.  If true, nominal abandoned acres will
    # be flat while planted acres shrink → rising abandonment % is a denominator
    # effect, not a worsening crop problem.
    _ab_hist = ab_df[ab_df["year"] < sel_usda_yr].dropna(subset=["abandoned_ac"]).copy()
    if not _ab_hist.empty and len(_ab_hist) >= 3:
        _ab_avg_ac   = float(_ab_hist["abandoned_ac"].mean())
        _ab_roll_n   = min(10, len(_ab_hist))
        _ab_rolling  = (
            _ab_hist.sort_values("year")["abandoned_ac"]
            .rolling(_ab_roll_n, min_periods=5)
            .mean()
            .values
        )

        _fig_ab = go.Figure()

        # Bar: nominal abandoned acres per year
        _ab_bar_colors = [
            "#ef4444" if v > _ab_avg_ac else "#f59e0b"
            for v in _ab_hist["abandoned_ac"]
        ]
        _fig_ab.add_trace(go.Bar(
            x=_ab_hist["year"],
            y=_ab_hist["abandoned_ac"] / 1e6,
            name="Abandoned Acres",
            marker_color=_ab_bar_colors,
            opacity=0.75,
            hovertemplate="<b>%{x}</b><br>Abandoned: %{y:.3f}M ac<extra></extra>",
        ))

        # Historical average line
        _fig_ab.add_hline(
            y=_ab_avg_ac / 1e6,
            line_color=JPSI_BLUE, line_width=2, line_dash="dash",
            annotation_text=f"Hist avg  {_ab_avg_ac/1e6:.3f}M ac",
            annotation_position="top left",
            annotation_font_color=JPSI_BLUE,
        )

        # 10-year rolling average
        _fig_ab.add_trace(go.Scatter(
            x=_ab_hist["year"].values,
            y=_ab_rolling / 1e6,
            mode="lines",
            name=f"{_ab_roll_n}-yr rolling avg",
            line=dict(color="#f59e0b", width=2),
            hovertemplate="<b>%{x}</b><br>%{y:.3f}M ac (rolling)<extra></extra>",
        ))

        # OLS trend line through nominal abandoned acres
        _ab_x   = _ab_hist["year"].values.astype(float)
        _ab_y   = _ab_hist["abandoned_ac"].values.astype(float)
        _ab_c   = np.polyfit(_ab_x, _ab_y, 1)
        _ab_trd = np.polyval(_ab_c, _ab_x)
        _ab_r2  = 1 - np.sum((_ab_y - _ab_trd)**2) / np.sum((_ab_y - _ab_y.mean())**2)
        _ab_dir = "▲ increasing" if _ab_c[0] > 0 else "▼ decreasing"
        _fig_ab.add_trace(go.Scatter(
            x=_ab_hist["year"].values,
            y=_ab_trd / 1e6,
            mode="lines",
            name=f"Trend ({_ab_dir}, R²={_ab_r2*100:.0f}%)",
            line=dict(color="#94a3b8", width=1.5, dash="dot"),
            hoverinfo="skip",
        ))

        _fig_ab.update_layout(
            title=dict(
                text="Nominal Abandoned Acres — Theory Test",
                font=dict(size=13, color=DM_TEXT), x=0,
            ),
            xaxis=dict(title="Crop Year", gridcolor=DM_BORDER, color=DM_MUTED,
                       tickfont=dict(color=DM_MUTED), title_font=dict(color=DM_MUTED)),
            yaxis=dict(title="Abandoned Acres (millions)", gridcolor=DM_BORDER,
                       tickformat=".3f", ticksuffix="M",
                       tickfont=dict(color=DM_MUTED), title_font=dict(color=DM_MUTED)),
            paper_bgcolor=DM_BG, plot_bgcolor=DM_SURFACE2,
            legend=dict(bgcolor=DM_SURFACE, bordercolor=DM_BORDER, borderwidth=1,
                        font=dict(color=DM_TEXT), orientation="h",
                        yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=40, b=10),
            height=320,
            hovermode="x unified",
        )
        _wm_center(_fig_ab, opacity=0.05)
        _show_chart(_fig_ab, "abandoned_acres")
        st.caption(
            f"**Theory check:** If abandoned acres are structurally fixed (flat trend), "
            f"a shrinking planted-acres base mechanically raises the abandonment % — "
            f"the denominator shrinks while the numerator stays constant. "
            f"Trend slope: **{_ab_c[0]/1e3:+.1f}K ac/yr** · R²={_ab_r2*100:.0f}% · "
            f"Hist avg: **{_ab_avg_ac/1e6:.3f}M ac**."
        )

    # ── Scatter: class JSA index vs % harvested ────────────────────────────
    _sc_df = _corr_df.copy()
    if _sc_df.empty:
        st.info("Not enough JSA data to plot correlation scatter — check that the yield model has loaded.")
        return

    _sc_x = _sc_df["jsa_index"].values
    _sc_y = _sc_df["pct_harvested"].values
    _sc_A = np.vstack([_sc_x, np.ones(len(_sc_x))]).T
    _sc_slope, _sc_intercept = np.linalg.lstsq(_sc_A, _sc_y, rcond=None)[0]
    _sc_yhat   = _sc_slope * _sc_x + _sc_intercept
    _sc_ss_res = float(np.sum((_sc_y - _sc_yhat) ** 2))
    _sc_ss_tot = float(np.sum((_sc_y - _sc_y.mean()) ** 2))
    _sc_r2     = 1 - _sc_ss_res / _sc_ss_tot if _sc_ss_tot > 0 else 0.0
    # Physical monotonicity check: higher JSA must → higher % harvested.
    # A negative slope is backward and no forecast star should be shown.
    _sc_slope_valid = _sc_slope > 0

    _sc_xline = [float(_sc_x.min()) - 2, float(_sc_x.max()) + 2]
    _sc_yline = [_sc_slope * v + _sc_intercept for v in _sc_xline]

    # ── Rolling-window regression lines (20-yr and 15-yr) ────────────────────
    def _window_reg(df, n_years):
        """OLS on the most recent n_years rows; returns (slope, intercept, r2) or None."""
        sub = df.sort_values("year").tail(n_years)
        if len(sub) < 5:
            return None
        x = sub["jsa_index"].values
        y = sub["pct_harvested"].values
        c = np.linalg.lstsq(np.vstack([x, np.ones(len(x))]).T, y, rcond=None)[0]
        yh = c[0] * x + c[1]
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = (1 - float(np.sum((y - yh) ** 2)) / ss_tot) if ss_tot > 0 else 0.0
        return float(c[0]), float(c[1]), r2

    _reg10 = _window_reg(_sc_df, 10)

    _sc_colors = [
        "#1a9850" if v >= _sc_y.mean() else "#d73027"
        for v in _sc_df["pct_harvested"]
    ]
    _sc_hist_max = float(_sc_y.max()) if len(_sc_y) > 0 else 100.0
    _sc_hist_min = float(_sc_y.min()) if len(_sc_y) > 0 else 0.0

    _cur_jsa   = jsa_snap.get(sel_usda_yr)
    _cur_label = mkt_label_short(sel_usda_yr)

    # ── Forecast: 10-yr abandoned acres ÷ planted  [+JSA tilt at class level] ─
    _ab2_df = ab_df[ab_df["year"] < sel_usda_yr].copy()
    _ab2_df["jsa_index"] = _ab2_df["year"].map(jsa_snap)
    _ab2_df = (_ab2_df.dropna(subset=["abandoned_ac", "planted_ac"])
                      .sort_values("year").tail(10))

    _cur_pred_pct    = None
    _pred_clamped    = False
    _opt2_valid      = False
    _opt2_fc_abandon = None
    _opt2_planted    = None
    _opt2_avg_yrs    = 0
    _opt2_slope      = None
    _opt2_intercept  = None
    _opt2_r2         = None
    _opt2_used_jsa   = False

    # Shared helper: get current planted acres from ab_df
    def _get_planted():
        _row = ab_df[ab_df["year"] == sel_usda_yr]
        if not _row.empty and pd.notna(_row.iloc[0].get("planted_ac")):
            return float(_row.iloc[0]["planted_ac"])
        return float(ab_df.dropna(subset=["planted_ac"]).sort_values("year").iloc[-1]["planted_ac"])

    if len(_ab2_df) >= 3:
        _opt2_avg_yrs = len(_ab2_df)
        _opt2_planted = _get_planted()

        if use_jsa_model and _cur_jsa is not None:
            # JSA regression on abandoned acres (class-level only — slope reliable)
            _ab2_jsa = _ab2_df.dropna(subset=["jsa_index"])
            if len(_ab2_jsa) >= 5:
                _ax = _ab2_jsa["jsa_index"].values
                _ay = _ab2_jsa["abandoned_ac"].values
                _ac = np.linalg.lstsq(
                    np.vstack([_ax, np.ones(len(_ax))]).T, _ay, rcond=None
                )[0]
                _opt2_slope, _opt2_intercept = float(_ac[0]), float(_ac[1])
                _a_yhat   = _opt2_slope * _ax + _opt2_intercept
                _a_ss_tot = float(np.sum((_ay - _ay.mean()) ** 2))
                _opt2_r2  = (1.0 - float(np.sum((_ay - _a_yhat) ** 2)) / _a_ss_tot
                             if _a_ss_tot > 0 else 0.0)
                _fc_raw   = _opt2_slope * float(_cur_jsa) + _opt2_intercept
                _opt2_fc_abandon = float(np.clip(_fc_raw, 0.0, float(_ay.max())))
                _opt2_used_jsa   = True

        if not _opt2_used_jsa:
            # Pure 10-yr rolling average — no JSA adjustment
            _opt2_fc_abandon = float(_ab2_df["abandoned_ac"].mean())

        # Convert to % harvested and clamp to historical observed range
        _raw_pred_pct = (1.0 - _opt2_fc_abandon / _opt2_planted) * 100.0
        _cur_pred_pct = float(np.clip(_raw_pred_pct, _sc_hist_min, _sc_hist_max))
        _pred_clamped = abs(_cur_pred_pct - _raw_pred_pct) > 0.05
        _opt2_valid   = True

    # Production-tab override: skip internal computation entirely and use the
    # pre-computed value so abandonment and production tabs show identical numbers.
    if forecast_pct_override is not None:
        _cur_pred_pct = float(forecast_pct_override)
        _pred_clamped = False
        _opt2_valid   = True

    _sc_col, _stats_col = st.columns([3, 1])
    with _sc_col:
        _fig_sc = go.Figure()

        # Full-history OLS regression line
        _fig_sc.add_trace(go.Scatter(
            x=_sc_xline, y=_sc_yline,
            mode="lines",
            line=dict(
                color="#6b7280" if not _sc_slope_valid else JPSI_BLUE,
                width=1.5, dash="dash",
            ),
            name=(
                "OLS fit (backward — not used)" if not _sc_slope_valid
                else f"All history  R²={_sc_r2*100:.0f}%"
            ),
            hoverinfo="skip",
        ))

        # 10-year rolling regression
        if _reg10:
            _s10, _i10, _r10 = _reg10
            _fig_sc.add_trace(go.Scatter(
                x=_sc_xline,
                y=[_s10 * v + _i10 for v in _sc_xline],
                mode="lines",
                line=dict(color="#a855f7", width=1.8, dash="longdash"),
                name=f"10-yr  R²={_r10*100:.0f}%",
                hoverinfo="skip",
            ))

        # Historical scatter points
        _fig_sc.add_trace(go.Scatter(
            x=_sc_df["jsa_index"].tolist(),
            y=_sc_df["pct_harvested"].tolist(),
            mode="markers+text",
            marker=dict(size=9, color=_sc_colors, opacity=0.85,
                        line=dict(color=DM_BG, width=1)),
            text=[mkt_label_short(int(y)) for y in _sc_df["year"]],
            textposition="top center",
            textfont=dict(size=8, color=DM_MUTED),
            hovertemplate=(
                "<b>%{text}</b><br>"
                f"{class_label} JSA Index: %{{x:.1f}}<br>"
                "% Harvested: %{y:.1f}%<extra></extra>"
            ),
            showlegend=False,
        ))

        if not _sc_slope_valid:
            # Backward slope — regression direction is physically wrong (more abandonment
            # in better conditions). Use historical average as the neutral forecast.
            _sc_avg_pct  = float(_sc_y.mean())
            _sc_xfull    = [float(_sc_x.min()) - 2, float(_sc_x.max()) + 2]
            # Horizontal average line
            _fig_sc.add_trace(go.Scatter(
                x=_sc_xfull, y=[_sc_avg_pct, _sc_avg_pct],
                mode="lines",
                line=dict(color="#f59e0b", width=2, dash="dot"),
                name=f"Hist. Avg {_sc_avg_pct:.1f}%",
                hoverinfo="skip",
            ))
            # Star on the average line (current-year forecast = historical mean)
            if _cur_jsa is not None:
                _fig_sc.add_trace(go.Scatter(
                    x=[_cur_jsa], y=[_sc_avg_pct],
                    mode="markers+text",
                    marker=dict(symbol="star", size=18, color="#facc15",
                                line=dict(color="#92400e", width=1.5)),
                    text=[_cur_label],
                    textposition="top center",
                    textfont=dict(size=9, color="#facc15"),
                    name=f"{_cur_label} (hist. avg)",
                    hovertemplate=(
                        f"<b>{_cur_label} — Forecast</b><br>"
                        f"{class_label} JSA Index: {_cur_jsa:.1f}<br>"
                        f"Forecast % Harvested: {_sc_avg_pct:.1f}%<br>"
                        f"<i>Regression slope is backward — using historical avg</i>"
                        f"<extra></extra>"
                    ),
                    showlegend=True,
                ))
            _fig_sc.add_annotation(
                x=0.01, y=0.99, xanchor="left", yanchor="top",
                xref="paper", yref="paper", showarrow=False,
                text="⚠ Backward slope: regression not used · Forecast = historical avg",
                font=dict(size=10, color="#f59e0b"),
                bgcolor="rgba(0,0,0,0.55)",
                bordercolor="#f59e0b", borderwidth=1,
            )
        elif _cur_jsa is not None and _cur_pred_pct is not None:
            # Valid positive slope — drop line + star on the regression line
            _fig_sc.add_trace(go.Scatter(
                x=[_cur_jsa, _cur_jsa],
                y=[min(_sc_y) - 2, _cur_pred_pct],
                mode="lines",
                line=dict(color="#facc15", width=1, dash="dot"),
                hoverinfo="skip",
                showlegend=False,
            ))
            _fig_sc.add_trace(go.Scatter(
                x=[_cur_jsa],
                y=[_cur_pred_pct],
                mode="markers+text",
                marker=dict(
                    symbol="star", size=18, color="#facc15",
                    line=dict(color="#92400e", width=1.5),
                ),
                text=[_cur_label],
                textposition="top center",
                textfont=dict(size=9, color="#facc15"),
                name=f"{_cur_label} (forecast)",
                hovertemplate=(
                    f"<b>{_cur_label} — Forecast</b><br>"
                    + (f"10-yr avg abandoned: {_opt2_fc_abandon/1e6:.3f}M ac<br>"
                       if _opt2_fc_abandon is not None else "")
                    + (f"Planted (denominator): {_opt2_planted/1e6:.3f}M ac<br>"
                       if _opt2_planted is not None else "")
                    + f"Forecast % Harvested: {_cur_pred_pct:.1f}%"
                    + (" ⚠ capped" if _pred_clamped else "")
                    + "<extra></extra>"
                ),
                showlegend=True,
            ))
            _method_lbl = (
                "★ Forecast: 10-yr abandoned_ac ~ JSA ÷ planted"
                if _opt2_used_jsa else
                "★ Forecast: 10-yr avg abandoned acres ÷ planted"
            )
            _fig_sc.add_annotation(
                x=0.01, y=0.01, xanchor="left", yanchor="bottom",
                xref="paper", yref="paper", showarrow=False,
                text=_method_lbl,
                font=dict(size=9, color=DM_MUTED),
            )
            if _pred_clamped:
                _fig_sc.add_annotation(
                    x=0.01, y=0.99, xanchor="left", yanchor="top",
                    xref="paper", yref="paper", showarrow=False,
                    text=f"⚠ Capped at historical {'max' if _cur_pred_pct == _sc_hist_max else 'min'} ({_cur_pred_pct:.1f}%)",
                    font=dict(size=10, color="#f59e0b"),
                    bgcolor="rgba(255,255,255,0.85)",
                    bordercolor="#f59e0b", borderwidth=1,
                )

        _fig_sc.update_layout(
            xaxis=dict(title=f"{class_label} JSA Condition Index",
                       gridcolor=DM_BORDER, color=DM_MUTED,
                       tickfont=dict(color=DM_MUTED), title_font=dict(color=DM_MUTED)),
            yaxis=dict(title="% of Planted Acres Harvested", ticksuffix="%",
                       gridcolor=DM_BORDER, color=DM_MUTED,
                       tickfont=dict(color=DM_MUTED), title_font=dict(color=DM_MUTED)),
            paper_bgcolor=DM_BG, plot_bgcolor=DM_SURFACE2,
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=DM_TEXT),
                        x=0.01, y=0.99, xanchor="left", yanchor="top"),
            margin=dict(l=10, r=10, t=20, b=10),
            height=330,
        )
        _wm_center(_fig_sc, opacity=0.05)
        _show_chart(_fig_sc, "planted_progress")

    with _stats_col:
        _corr_display = f"{_corr_val:+.3f}" if not np.isnan(_corr_val) else "N/A"
        _pred_display = f"{_cur_pred_pct:.1f}%" if _cur_pred_pct is not None else "—"
        _rows = [
            ("Pearson r",        _corr_display),
            ("All-hist R²",      f"{_sc_r2 * 100:.1f}%"),
            ("All-hist slope",   f"{_sc_slope:+.2f}% / pt"),
            ("n (all hist)",     f"{len(_sc_df)} yrs"),
        ]
        if _reg10:
            _rows.append(("10-yr % R²",    f"{_reg10[2]*100:.1f}%"))
        # Forecast model details
        if _opt2_valid:
            _rows.append(("── Forecast model ──", ""))
            if _opt2_used_jsa and _opt2_r2 is not None:
                _rows.append(("Method",        "JSA regression"))
                _rows.append(("Abandoned R²",  f"{_opt2_r2*100:.1f}%"))
                _rows.append(("Slope",
                              f"{_opt2_slope/1e3:+.1f}K ac/pt"))
            else:
                _rows.append(("Method",
                              f"{_opt2_avg_yrs}-yr rolling avg"))
            _rows.append(("Fc abandoned",
                          f"{_opt2_fc_abandon/1e6:.3f}M ac"))
            if _opt2_planted is not None:
                _rows.append(("Planted (denom)",
                              f"{_opt2_planted/1e6:.3f}M ac"))
        if _cur_pred_pct is not None:
            _rows.append((f"{_cur_label} Fc % harv", _pred_display))
        _td_lbl = f"color:{DM_MUTED};font-size:0.72rem;padding:3px 0 3px 0;white-space:nowrap"
        _td_val = f"color:{DM_TEXT};font-size:0.72rem;font-weight:600;text-align:right;padding:3px 0 3px 6px"
        _trs = "".join(
            f"<tr><td style='{_td_lbl}'>{lbl}</td><td style='{_td_val}'>{val}</td></tr>"
            for lbl, val in _rows
        )
        # Insert a visual divider row before the forecast if present
        if _cur_pred_pct is not None:
            _divider_row = f"<tr><td colspan='2' style='border-top:1px solid {DM_BORDER};padding:2px 0'></td></tr>"
            _trs = _trs[: _trs.rfind("<tr>")] + _divider_row + _trs[_trs.rfind("<tr>"):]
        _card = (
            f"<div style='background:{DM_SURFACE2};border:1px solid {DM_BORDER};"
            f"border-radius:8px;padding:10px 12px;margin-top:8px'>"
            f"<p style='color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;"
            f"letter-spacing:0.07em;margin:0 0 6px 0'>Regression Stats</p>"
            f"<table style='width:100%;border-collapse:collapse'>{_trs}</table>"
            f"</div>"
        )
        st.markdown(_card, unsafe_allow_html=True)



@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_yields(commodity_desc: str, class_desc: str, years: tuple,
                 unit_desc: str | None = None) -> pd.DataFrame:
    """
    Pull annual yield data (bu/acre) from USDA NASS Quick Stats.
    Makes TWO calls — agg_level_desc=STATE for state rows, agg_level_desc=NATIONAL for
    the US national row — then unions them.  This avoids the county/district row bloat
    that occurs without an agg_level filter and ensures the 'US' benchmark row is present.
    """
    if not years:
        return pd.DataFrame()

    _base = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    commodity_desc,
        "class_desc":        class_desc,
        "statisticcat_desc": "YIELD",
        "freq_desc":         "ANNUAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    if unit_desc:
        _base["unit_desc"] = unit_desc

    frames = []

    # Call 1: all state-level rows (agg_level_desc=STATE keeps rows well under NASS 50k limit)
    _p_state = {**_base, "agg_level_desc": "STATE"}
    _pl = _nass_get(_p_state)
    if "data" in _pl and _pl["data"]:
        frames.append(pd.DataFrame(_pl["data"]))

    # Call 2: US TOTAL national row — agg_level=NATIONAL is unreliable for class-specific queries;
    # filtering by state_name directly is more robust and returns only ~40 rows total.
    # For class_desc="ALL CLASSES" (corn, soybeans, sorghum), NASS may not index the national
    # row under that class tag — drop class_desc from the US call so we always get the row back.
    _p_us = {k: v for k, v in _base.items() if k != "class_desc"} if class_desc == "ALL CLASSES" else {**_base}
    _p_us["state_name"] = "US TOTAL"
    _pl_us = _nass_get(_p_us)
    if "data" in _pl_us and _pl_us["data"]:
        frames.append(pd.DataFrame(_pl_us["data"]))

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df[[c for c in ["year", "state_alpha", "state_name", "unit_desc",
                         "reference_period_desc", "Value"]
              if c in df.columns]].copy()
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"]  = df["year"].astype(int)
    df = df.dropna(subset=["Value"])
    # Keep only 2-char codes (state abbreviations + "US")
    df = df[df["state_alpha"].str.len() == 2]
    # Post-fetch unit filter — ensures silage (TONS/ACRE) etc. are excluded
    if unit_desc and "unit_desc" in df.columns:
        df = df[df["unit_desc"] == unit_desc]
    df = df.drop(columns=["unit_desc"], errors="ignore")
    df = df.rename(columns={"Value": "yield_bu_ac"})
    # Priority dedup — keep the most-final NASS report per state-year.
    # Averaging Annual Summary with in-season forecasts skews the yield history;
    # using only the definitive final ensures regression calibration is correct.
    _REF_PRI_YLD = {
        "YEAR":                 100,  # Annual Summary — always the definitive final
        "YEAR - AUG FORECAST":   70,
        "YEAR - JUL FORECAST":   60,
        "YEAR - JUN FORECAST":   50,
        "YEAR - JUN ACREAGE":    45,
        "YEAR - MAY FORECAST":   30,
    }
    if "reference_period_desc" in df.columns:
        df["_pri"] = (df["reference_period_desc"].str.strip().str.upper()
                      .map(_REF_PRI_YLD).fillna(0).astype(int))
        df = (df.sort_values(["year", "state_alpha", "_pri"],
                             ascending=[True, True, False])
                .drop_duplicates(subset=["year", "state_alpha"], keep="first")
                .drop(columns=["_pri"]))
    else:
        df = df.groupby(["year", "state_alpha"], as_index=False).agg(
            {"yield_bu_ac": "mean", "state_name": "last"}
        )
    df = df.drop(columns=["reference_period_desc"], errors="ignore")
    return df


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_usda_monthly_yield_history(commodity_desc: str, class_desc: str, years: tuple,
                                     unit_desc: str = "BU / ACRE",
                                     state_alpha: str | None = None) -> pd.DataFrame:
    """
    Fetch yield estimates for all USDA monthly crop production report periods
    (AUG/SEP/OCT/NOV forecasts + YEAR final) for LOO scatter benchmark comparison.
    Pass state_alpha to get a specific state; omit (or None) for US national.
    Returns DataFrame with columns: crop_year, ref_period, yield_bu_ac.
    """
    if not years:
        return pd.DataFrame()
    _params = {k: v for k, v in {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "commodity_desc":    commodity_desc,
        "statisticcat_desc": "YIELD",
        "unit_desc":         unit_desc,
        "freq_desc":         "ANNUAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "state_alpha":       state_alpha if state_alpha else None,
        "state_name":        None if state_alpha else "US TOTAL",
        "agg_level_desc":    "STATE" if state_alpha else None,
        "format":            "JSON",
    }.items() if v is not None}
    if class_desc and class_desc != "ALL CLASSES":
        _params["class_desc"] = class_desc
    _resp = _nass_get(_params)
    _rows = []
    for _rec in _resp.get("data", []):
        try:
            _val = float(str(_rec.get("Value", "")).replace(",", ""))
            _ref = str(_rec.get("reference_period_desc", "")).strip().upper()
            _yr  = int(_rec["year"])
            _rows.append({"crop_year": _yr, "ref_period": _ref, "yield_bu_ac": _val})
        except (ValueError, KeyError):
            continue
    if not _rows:
        return pd.DataFrame()
    _df = pd.DataFrame(_rows)
    # Map all NASS reference_period_desc variants to a canonical label using
    # substring matching — NASS uses different strings across commodities
    # (e.g. "YEAR - AUG FORECAST", "AUG FORECAST", "YEAR - AUGUST FORECAST", etc.)
    def _canonical(ref: str) -> str:
        r = ref.upper()
        if "AUG" in r:  return "AUG FORECAST"
        if "SEP" in r:  return "SEP FORECAST"
        if "OCT" in r:  return "OCT FORECAST"
        if "NOV" in r:  return "NOV FORECAST"
        if r == "YEAR": return "FINAL"
        return ""
    _df["canonical"] = _df["ref_period"].apply(_canonical)
    _df = _df[_df["canonical"] != ""].drop_duplicates(
        subset=["crop_year", "canonical"], keep="last"
    ).drop(columns=["ref_period"]).rename(columns={"canonical": "ref_period"}).reset_index(drop=True)
    return _df


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_first_of_sep_stocks(commodity_desc: str, years: tuple) -> pd.DataFrame:
    """Pull Sep 1 grain stocks from USDA NASS — STATE and NATIONAL totals."""
    # Keep params minimal: over-specifying (group_desc, freq_desc, domain_desc)
    # causes the QuickStats API to return 0 results for the Grain Stocks report.
    _base = {
        "key":                   API_KEY,
        "source_desc":           "SURVEY",
        "commodity_desc":        commodity_desc,
        "statisticcat_desc":     "STOCKS",
        "reference_period_desc": "FIRST OF SEP",
        "year__GE":              min(years),
        "year__LE":              max(years),
        "format":                "JSON",
    }
    frames = []
    for _lvl in ("STATE", "NATIONAL"):
        _pl = _nass_get({**_base, "agg_level_desc": _lvl})
        if "data" in _pl and _pl["data"]:
            frames.append(pd.DataFrame(_pl["data"]))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    _keep = [c for c in ["year", "state_alpha", "short_desc", "unit_desc", "Value"] if c in df.columns]
    df = df[_keep].copy()
    df["year"]  = df["year"].astype(int)
    df["Value"] = pd.to_numeric(df["Value"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df = df.dropna(subset=["Value"])
    # Keep only total stocks rows (exclude ON FARM / OFF FARM breakdowns)
    if "short_desc" in df.columns:
        _excl = df["short_desc"].str.upper().str.contains("ON FARM|OFF FARM", na=False)
        df = df[~_excl]
    # Normalise to raw BU
    if "unit_desc" in df.columns:
        df.loc[df["unit_desc"] == "1000 BU",    "Value"] *= 1_000
        df.loc[df["unit_desc"] == "1000000 BU", "Value"] *= 1_000_000
    # Ensure national rows carry state_alpha == "US"
    mask_natl = df["state_alpha"].str.upper().isin({"", "US", "US TOTAL"})
    df.loc[mask_natl, "state_alpha"] = "US"
    df = df[df["state_alpha"].str.len() == 2]
    df = df.sort_values("year").drop_duplicates(subset=["year", "state_alpha"], keep="last")
    return df.rename(columns={"Value": "stocks_bu"})[["year", "state_alpha", "stocks_bu"]].reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_quarterly_stocks(
    commodity_desc: str,
    ref_period: str,
    years: tuple,
) -> pd.DataFrame:
    """
    Fetch USDA NASS grain stocks for any quarterly reference period.
    ref_period: 'FIRST OF SEP' | 'FIRST OF DEC' | 'FIRST OF MAR' | 'FIRST OF JUN'
    Returns DataFrame with columns: year, state_alpha, stocks_bu
    """
    if not years:
        return pd.DataFrame()
    _base = {
        "key":                   API_KEY,
        "source_desc":           "SURVEY",
        "commodity_desc":        commodity_desc,
        "statisticcat_desc":     "STOCKS",
        "reference_period_desc": ref_period,
        "year__GE":              min(years),
        "year__LE":              max(years),
        "format":                "JSON",
    }
    frames = []
    for _lvl in ("STATE", "NATIONAL"):
        _pl = _nass_get({**_base, "agg_level_desc": _lvl})
        if "data" in _pl and _pl["data"]:
            frames.append(pd.DataFrame(_pl["data"]))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    _keep = [c for c in ["year", "state_alpha", "short_desc", "unit_desc", "Value"] if c in df.columns]
    df = df[_keep].copy()
    df["year"]  = df["year"].astype(int)
    df["Value"] = pd.to_numeric(
        df["Value"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    df = df.dropna(subset=["Value"])
    if "short_desc" in df.columns:
        _excl = df["short_desc"].str.upper().str.contains("ON FARM|OFF FARM", na=False)
        df = df[~_excl]
    if "unit_desc" in df.columns:
        df.loc[df["unit_desc"] == "1000 BU",    "Value"] *= 1_000
        df.loc[df["unit_desc"] == "1000000 BU", "Value"] *= 1_000_000
    mask_natl = df["state_alpha"].str.upper().isin({"", "US", "US TOTAL"})
    df.loc[mask_natl, "state_alpha"] = "US"
    df = df[df["state_alpha"].str.len() == 2]
    df = (df.sort_values("year")
            .drop_duplicates(subset=["year", "state_alpha"], keep="last"))
    return (df.rename(columns={"Value": "stocks_bu"})
              [["year", "state_alpha", "stocks_bu"]]
              .reset_index(drop=True))


def _build_sep1_disapp_df(
    sep1_df: pd.DataFrame,
    jun1_df: pd.DataFrame,
    prod_df: "pd.DataFrame | None",
    is_winter_wheat: bool,
    state_alpha: str = "US",
) -> pd.DataFrame:
    """
    Build historical Jun→Sep supply-retention ratios used to estimate Sep 1 stocks.

    The ratio approach is more stable than absolute disappearance because drawdown
    scales with the size of available supply.

    Regular crops (corn, soybeans, sorghum, spring wheat, etc.):
        Harvest finishes before Jun 1; Jun 1 = total available old-crop supply.
        retention_ratio[y] = Sep1[y] / Jun1[y]

    Winter wheat:
        Harvest runs Jun-Aug, so new-crop production enters the pipeline.
        Total Q1 supply = Jun1[y] + Production[y]
        retention_ratio[y] = Sep1[y] / (Jun1[y] + Production[y])

    Returns DataFrame: [year, jun1_bu, sep1_bu, prod_bu, total_supply_bu,
                         disappearance_bu, retention_ratio]
    `year` is the NASS year of the Sep 1 observation.
    """
    def _stk(df, yr):
        row = df[(df["year"] == yr) & (df["state_alpha"] == state_alpha)]
        return float(row["stocks_bu"].iloc[0]) if not row.empty else None

    def _prod(yr):
        if prod_df is None or prod_df.empty:
            return None
        row = prod_df[(prod_df["year"] == yr) & (prod_df["state_alpha"] == state_alpha)]
        for col in ("production_bu", "production"):
            if col in row.columns and not row.empty and pd.notna(row[col].iloc[0]):
                return float(row[col].iloc[0])
        return None

    sep_years = sorted(sep1_df[sep1_df["state_alpha"] == state_alpha]["year"].unique())
    rows = []
    for y in sep_years:
        j1 = _stk(jun1_df, y)
        s1 = _stk(sep1_df, y)
        if j1 is None or s1 is None or j1 == 0:
            continue
        p = _prod(y) if is_winter_wheat else None
        total_supply = (j1 + p) if (is_winter_wheat and p is not None) else j1
        disapp       = total_supply - s1
        ratio        = s1 / total_supply if total_supply > 0 else None
        rows.append({
            "year": y, "jun1_bu": j1, "sep1_bu": s1,
            "prod_bu": p, "total_supply_bu": total_supply,
            "disappearance_bu": disapp, "retention_ratio": ratio,
        })
    return pd.DataFrame(rows)


def _estimate_sep1_stocks(
    disapp_df: pd.DataFrame,
    jun1_df: pd.DataFrame,
    cur_year: int,
    is_winter_wheat: bool,
    prod_est_bu: "float | None",
    state_alpha: str = "US",
    n_avg: int = 5,
) -> "tuple[float | None, str]":
    """
    Forecast Sep 1 stocks using a supply-retention ratio applied to Jun 1 stocks.

    Ratio approach: Sep1 as a % of available supply is more stable year-to-year
    than absolute disappearance, which scales with stock size.

    Regular crops:
        ratio[y]  = Sep1[y] / Jun1[y]
        Sep1_est  = Jun1[cur] × avg_ratio

    Winter wheat (production enters Jun-Aug):
        ratio[y]  = Sep1[y] / (Jun1[y] + Production[y])
        Sep1_est  = (Jun1[cur] + prod_est) × avg_ratio

    Returns (estimate_bu, method_note_str). Returns (None, reason) if insufficient data.
    """
    j1_row = jun1_df[(jun1_df["year"] == cur_year) & (jun1_df["state_alpha"] == state_alpha)]
    if j1_row.empty:
        return None, f"Jun 1 {cur_year} stocks not yet available"
    j1_val = float(j1_row["stocks_bu"].iloc[0])

    hist_ratios = disapp_df[disapp_df["year"] < cur_year]["retention_ratio"].dropna()
    if len(hist_ratios) < 3:
        return None, "Insufficient history for retention-ratio average"
    avg_ratio = float(hist_ratios.tail(n_avg).mean())
    n_used    = min(n_avg, len(hist_ratios))

    if is_winter_wheat:
        if prod_est_bu is None:
            return None, "Production estimate required for winter wheat forecast"
        total_supply = j1_val + prod_est_bu
        est  = total_supply * avg_ratio
        note = (f"(Jun 1 {cur_year} + {cur_year} WW prod est) × "
                f"{n_used}-yr avg Sep1/Supply ratio ({avg_ratio*100:.1f}%)")
    else:
        est  = j1_val * avg_ratio
        note = (f"Jun 1 {cur_year} stocks × {n_used}-yr avg "
                f"Sep1/Jun1 retention ratio ({avg_ratio*100:.1f}%)")

    return max(0.0, est), note


def _backtest_state_sep1_methods(
    sep1_df: pd.DataFrame,
    jun1_df: pd.DataFrame,
    n_avg: int = 5,
    min_hist: int = 3,
) -> "tuple[pd.DataFrame, pd.DataFrame]":
    """
    Backtest three state-level Sep 1 estimation methods against actual NASS data.

    Methods tested (each receives the ACTUAL US Sep 1 total so we isolate
    state-allocation accuracy from national estimation error):

    1. National ratio × State Jun1:
       State_est = State_Jun1 × (US_Sep1_actual / US_Jun1)

    2. Historical state share × US total:
       State_est = US_Sep1_actual × avg(State_Sep1 / US_Sep1, last n_avg yrs)

    3. State retention ratio:
       State_est = State_Jun1 × avg(State_Sep1 / State_Jun1, last n_avg yrs)

    Returns (summary_df, detail_df):
      summary_df: [method, mape_pct, median_ape_pct, n_obs] sorted by mape_pct
      detail_df:  [method, state, year, actual_mbu, est_mbu, ape_pct]
    """
    sep_us   = (sep1_df[sep1_df["state_alpha"] == "US"]
                .set_index("year")["stocks_bu"])
    jun_us   = (jun1_df[jun1_df["state_alpha"] == "US"]
                .set_index("year")["stocks_bu"])
    states   = sorted(sep1_df[sep1_df["state_alpha"] != "US"]["state_alpha"].unique())
    all_yrs  = sorted(sep1_df["year"].unique())

    records = []
    for y in all_yrs:
        us_s1 = sep_us.get(y)
        us_j1 = jun_us.get(y)
        if us_s1 is None or us_j1 is None or float(us_j1) == 0:
            continue
        nat_ratio = float(us_s1) / float(us_j1)
        hist_yrs  = [yr for yr in all_yrs if yr < y][-n_avg:]
        if len(hist_yrs) < min_hist:
            continue

        for st in states:
            act_row = sep1_df[(sep1_df["year"] == y) & (sep1_df["state_alpha"] == st)]
            j1_row  = jun1_df[(jun1_df["year"] == y) & (jun1_df["state_alpha"] == st)]
            if act_row.empty or j1_row.empty:
                continue
            actual = float(act_row["stocks_bu"].iloc[0])
            st_j1  = float(j1_row["stocks_bu"].iloc[0])
            if actual <= 0 or st_j1 <= 0:
                continue

            # Method 1: national ratio applied to state Jun1
            m1 = st_j1 * nat_ratio

            # Method 2: historical state share of US Sep1 total
            shares = []
            for hy in hist_yrs:
                s_r = sep1_df[(sep1_df["year"] == hy) & (sep1_df["state_alpha"] == st)]
                u_v = sep_us.get(hy)
                if not s_r.empty and u_v and float(u_v) > 0:
                    shares.append(float(s_r["stocks_bu"].iloc[0]) / float(u_v))
            m2 = float(us_s1) * float(np.mean(shares)) if len(shares) >= 2 else None

            # Method 3: state retention ratio (Sep1/Jun1)
            ratios = []
            for hy in hist_yrs:
                s_r = sep1_df[(sep1_df["year"] == hy) & (sep1_df["state_alpha"] == st)]
                j_r = jun1_df[(jun1_df["year"] == hy) & (jun1_df["state_alpha"] == st)]
                if not s_r.empty and not j_r.empty:
                    jv = float(j_r["stocks_bu"].iloc[0])
                    if jv > 0:
                        ratios.append(float(s_r["stocks_bu"].iloc[0]) / jv)
            m3 = st_j1 * float(np.mean(ratios)) if len(ratios) >= 2 else None

            for name, est in [
                ("National ratio × State Jun1", m1),
                ("Hist. state share × US total", m2),
                ("State retention ratio",        m3),
            ]:
                if est is not None:
                    ape = abs(est - actual) / actual * 100
                    records.append({
                        "method": name, "state": st, "year": y,
                        "actual_mbu": actual / 1e6,
                        "est_mbu":    est / 1e6,
                        "ape_pct":    ape,
                    })

    if not records:
        return pd.DataFrame(), pd.DataFrame()

    detail  = pd.DataFrame(records)
    summary = (detail.groupby("method")["ape_pct"]
               .agg(mape_pct="mean", median_ape_pct="median", n_obs="count")
               .reset_index()
               .sort_values("mape_pct")
               .reset_index(drop=True))
    return summary, detail


def _estimate_state_sep1(
    state_alpha: str,
    state_jun1_bu: float,
    us_total_est_bu: float,
    us_jun1_bu: float,
    sep1_df: pd.DataFrame,
    jun1_df: pd.DataFrame,
    method: str,
    cur_year: int,
    n_avg: int = 5,
) -> "float | None":
    """
    Estimate state Sep 1 stocks from a known (or forecast) US total.

    method: 'national_ratio' | 'state_share' | 'state_ratio'
    """
    if us_total_est_bu <= 0 or state_jun1_bu <= 0:
        return None

    if method == "national_ratio":
        if us_jun1_bu <= 0:
            return None
        return state_jun1_bu * (us_total_est_bu / us_jun1_bu)

    elif method == "state_share":
        s_hist  = sep1_df[(sep1_df["state_alpha"] == state_alpha) &
                          (sep1_df["year"] < cur_year)].sort_values("year").tail(n_avg)
        us_hist = sep1_df[(sep1_df["state_alpha"] == "US") &
                          (sep1_df["year"] < cur_year)].set_index("year")["stocks_bu"]
        shares  = []
        for _, r in s_hist.iterrows():
            u = us_hist.get(r["year"])
            if u and float(u) > 0:
                shares.append(r["stocks_bu"] / float(u))
        return us_total_est_bu * float(np.mean(shares)) if shares else None

    elif method == "state_ratio":
        merged = (sep1_df[(sep1_df["state_alpha"] == state_alpha) &
                          (sep1_df["year"] < cur_year)]
                  .merge(jun1_df[(jun1_df["state_alpha"] == state_alpha) &
                                 (jun1_df["year"] < cur_year)],
                         on=["year", "state_alpha"], suffixes=("_s", "_j"))
                  .sort_values("year").tail(n_avg))
        if merged.empty:
            return None
        ratios = []
        for _, r in merged.iterrows():
            if r["stocks_bu_j"] > 0:
                ratios.append(r["stocks_bu_s"] / r["stocks_bu_j"])
        return state_jun1_bu * float(np.mean(ratios)) if ratios else None

    return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_psd_ending_stocks(commodity_desc: str, psd_market_year: int) -> "float | None":
    """
    Pull USDA FAS PSD projected US ending stocks (attribute 176) in bushels.
    Valid for Sep-1 marketing year crops (Corn, Soybeans, Sorghum) where
    psd_market_year = sel_usda_yr - 1 (e.g. viewing 2026 → psd_market_year=2025).
    Returns None for unsupported commodities or on API error.
    """
    cfg = PSD_SEP1_MAP.get(commodity_desc.upper())
    if cfg is None:
        return None
    psd_code, bu_per_mt = cfg
    try:
        resp = requests.get(
            f"{PSD_BASE}/data/get",
            params={"commodityCode": psd_code, "countryCode": PSD_US_CODE},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        df = pd.DataFrame(data)
        df = df[
            (df["attributeId"] == PSD_ENDING_STOCKS_ATTR) &
            (df["marketYear"]   == psd_market_year)
        ]
        if df.empty:
            return None
        # Most recent projection (highest projNo)
        row = df.sort_values("projNo", ascending=True).iloc[-1]
        # PSD value is in 1000 MT → convert to bushels
        return float(row["value"]) * 1_000.0 * bu_per_mt
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def compute_yield_trends(yield_df: pd.DataFrame, start_year: int = 1985) -> dict:
    """
    OLS linear trendline for every state (and US) using all years >= start_year.

    Cached with ttl=3600 so np.polyfit is not re-run on every Streamlit rerun.
    Without caching, LAPACK's floating-point arithmetic produces slightly different
    slope/intercept values between runs, causing the forecast to bounce.

    Returns
    -------
    dict keyed by state_alpha:
        slope, intercept, r2, equation  — regression parameters
        n                               — number of years used
        state_name                      — full name string
        years, actuals                  — lists for charting
    """
    results = {}
    for state, grp in yield_df.groupby("state_alpha"):
        grp = (grp[grp["year"] >= start_year]
               .sort_values("year")
               .dropna(subset=["yield_bu_ac"]))
        if len(grp) < 5:
            continue
        x       = grp["year"].values.astype(float)
        y       = grp["yield_bu_ac"].values.astype(float)
        c       = np.polyfit(x, y, 1)
        slope, intercept = float(c[0]), float(c[1])
        y_pred  = slope * x + intercept
        ss_res  = float(np.sum((y - y_pred) ** 2))
        ss_tot  = float(np.sum((y - y.mean()) ** 2))
        r2      = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        sign    = "+" if intercept >= 0 else "−"
        results[state] = {
            "slope":      slope,
            "intercept":  intercept,
            "r2":         r2,
            "equation":   f"y = {slope:.3f}x {sign} {abs(intercept):.1f}",
            "n":          len(grp),
            "state_name": grp["state_name"].iloc[-1] if "state_name" in grp.columns else state,
            "years":      grp["year"].tolist(),
            "actuals":    grp["yield_bu_ac"].tolist(),
        }
    return results


def _class_weighted_yield(yield_df: pd.DataFrame, weights: dict, series_key: str, series_name: str) -> pd.DataFrame:
    """Production-weighted average yield for any set of states — plugs into compute_yield_trends()."""
    sub = yield_df[yield_df["state_alpha"].isin(weights)].copy()
    sub["w"] = sub["state_alpha"].map(weights)
    rows = []
    for yr, grp in sub.groupby("year"):
        grp = grp.dropna(subset=["w", "yield_bu_ac"])
        if grp.empty:
            continue
        w_sum = grp["w"].sum()
        if w_sum == 0:
            continue
        rows.append({
            "year":        int(yr),
            "state_alpha": series_key,
            "state_name":  series_name,
            "yield_bu_ac": (grp["yield_bu_ac"] * grp["w"]).sum() / w_sum,
        })
    return pd.DataFrame(rows)


def hrw_weighted_yield(yield_df: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    return _class_weighted_yield(yield_df, weights if weights is not None else HRW_WEIGHTS, "HRW", "HRW Index")


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_soft_white_yields(years: tuple) -> pd.DataFrame:
    """
    Fetch NASS-published SOFT WHITE wheat yields for WA, OR, ID.
    NASS publishes class_desc=SOFT WHITE at state level for these three states,
    making it more accurate than using total WINTER wheat yields for the white index.
    Falls back gracefully to empty if NASS doesn't have the data.
    """
    if not years:
        return pd.DataFrame()
    params = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    "WHEAT",
        "class_desc":        "SOFT WHITE",
        "statisticcat_desc": "YIELD",
        "agg_level_desc":    "STATE",
        "freq_desc":         "ANNUAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    payload = _nass_get(params)
    if "data" not in payload or not payload["data"]:
        return pd.DataFrame()
    df = pd.DataFrame(payload["data"])
    df = df[[c for c in ["year", "state_alpha", "state_name", "Value"] if c in df.columns]].copy()
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"]  = df["year"].astype(int)
    df = df.dropna(subset=["Value"])
    df = df[df["state_alpha"].isin({"WA", "OR", "ID"})]
    df = df.groupby(["year", "state_alpha"], as_index=False).agg(
        {"Value": "mean", "state_name": "last"}
    )
    return df.rename(columns={"Value": "yield_bu_ac"})


def _white_weighted_yield(winter_yield_df: pd.DataFrame,
                           soft_white_yield_df: pd.DataFrame,
                           weights: dict) -> pd.DataFrame:
    """White weighted yield — uses NASS SOFT WHITE state yields where available."""
    return _class_weighted_yield_with_override(
        winter_yield_df, soft_white_yield_df, weights, "White", "White Index"
    )


def _fetch_class_yields(class_desc: str, valid_states: set, years: tuple) -> pd.DataFrame:
    """
    Generic helper: fetch NASS state-level yields for a specific wheat class.
    Returns empty DataFrame gracefully if NASS doesn't publish that class at state level.
    Used to get more accurate HRW / SRW / Soft White yields than using total WINTER yields.
    """
    if not years:
        return pd.DataFrame()
    params = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    "WHEAT",
        "class_desc":        class_desc,
        "statisticcat_desc": "YIELD",
        "agg_level_desc":    "STATE",
        "freq_desc":         "ANNUAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    payload = _nass_get(params)
    if "data" not in payload or not payload["data"]:
        return pd.DataFrame()
    df = pd.DataFrame(payload["data"])
    df = df[[c for c in ["year", "state_alpha", "state_name", "Value"] if c in df.columns]].copy()
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"]  = df["year"].astype(int)
    df = df.dropna(subset=["Value"])
    df = df[df["state_alpha"].isin(valid_states)]
    df = df.groupby(["year", "state_alpha"], as_index=False).agg(
        {"Value": "mean", "state_name": "last"}
    )
    return df.rename(columns={"Value": "yield_bu_ac"})


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_hrw_class_yields(years: tuple) -> pd.DataFrame:
    """
    Attempt to fetch NASS class_desc=HARD RED WINTER state-level yields.
    NASS doesn't always publish this at state level; falls back to empty gracefully.
    Where available, these are more accurate than total WINTER wheat yields for HRW states.
    """
    HRW_STATES = {"KS", "OK", "TX", "CO", "NE", "SD", "WY", "NM", "MT"}
    return _fetch_class_yields("HARD RED WINTER", HRW_STATES, years)


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_srw_class_yields(years: tuple) -> pd.DataFrame:
    """
    Fetch NASS class_desc=SOFT RED WINTER state-level yields.
    NASS publishes this for the core Midwest SRW states (IL, IN, OH, KY, MI, MO, etc.)
    These are more accurate than total WINTER yields since MO/AR grow mixed HRW+SRW.
    """
    SRW_STATES = {"IL", "IN", "OH", "KY", "MI", "MO", "TN", "AR", "MS", "AL",
                  "GA", "SC", "NC", "VA", "WV", "MD", "PA", "NY", "NJ", "DE", "WI", "LA"}
    return _fetch_class_yields("SOFT RED WINTER", SRW_STATES, years)


def _class_weighted_yield_with_override(winter_yield_df: pd.DataFrame,
                                         class_yield_df: pd.DataFrame,
                                         weights: dict,
                                         series_key: str,
                                         series_name: str) -> pd.DataFrame:
    """
    Compute production-weighted yield using class-specific NASS yields where NASS
    publishes them, falling back to total WINTER yields for any state/year gap.
    class_yield_df rows take priority over winter_yield_df rows for the same state+year.
    """
    frames = []
    if not class_yield_df.empty:
        frames.append(class_yield_df[class_yield_df["state_alpha"].isin(weights)])

    winter_sub = winter_yield_df[winter_yield_df["state_alpha"].isin(weights)].copy()
    if frames:
        covered = pd.concat(frames)[["year", "state_alpha"]].drop_duplicates()
        winter_sub = winter_sub.merge(covered, on=["year", "state_alpha"],
                                      how="left", indicator=True)
        winter_sub = winter_sub[winter_sub["_merge"] == "left_only"].drop(columns=["_merge"])
    frames.append(winter_sub)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return _class_weighted_yield(combined, weights, series_key, series_name)


def _compute_class_national_benchmark(
    class_yield_df: pd.DataFrame,
    acres_df: pd.DataFrame,
    class_states: set,
) -> pd.DataFrame:
    """
    Build a NASS-equivalent national class yield benchmark by computing:
        national_yield = Σ(state_class_yield × state_harvested_acres) / Σ(state_harvested_acres)
    using year-specific actual harvested acres — exactly NASS's own methodology.

    Used for SRW (SOFT RED WINTER state yields available) and White (SOFT WHITE state yields).
    Returns DataFrame: year, nass_yield.
    Only years where BOTH state yields AND state acres are available are included.
    """
    if class_yield_df.empty or acres_df.empty:
        return pd.DataFrame()
    col = "state" if "state" in acres_df.columns else "state_alpha"
    acres_sub = acres_df[acres_df[col].isin(class_states)]
    cls_sub   = class_yield_df[class_yield_df["state_alpha"].isin(class_states)]
    rows = []
    for yr, yield_grp in cls_sub.groupby("year"):
        yr_acres = acres_sub[acres_sub["year"] == int(yr)]
        if yr_acres.empty:
            continue
        acres_map = dict(zip(yr_acres[col], yr_acres["harvested_ac"]))
        g = yield_grp.dropna(subset=["yield_bu_ac"]).copy()
        g["acres"] = g["state_alpha"].map(acres_map).fillna(0.0)
        g = g[g["acres"] > 0]
        if g.empty:
            continue
        total_ac = float(g["acres"].sum())
        natl_yield = float((g["yield_bu_ac"] * g["acres"]).sum() / total_ac)
        rows.append({"year": int(yr), "nass_yield": natl_yield})
    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True) if rows else pd.DataFrame()


def _class_weighted_yield_dynamic(
    yield_df: pd.DataFrame,
    acres_df: pd.DataFrame,
    class_states: set,
    fallback_weights: dict,
    series_key: str,
    series_name: str,
) -> pd.DataFrame:
    """
    Compute YEAR-SPECIFIC harvested-acres-weighted yield — matches NASS methodology exactly.

    NASS national class yield = Σ(state_harvested_acres_i × state_yield_i) / Σ(state_harvested_acres_i)

    Using that year's actual acres eliminates the fixed-weight bias that arises when one
    state's share shifts significantly in a given year (e.g. KS drought → fewer harvested
    acres → lower KS weight in that year's NASS number, but our fixed 10-yr avg still
    overweights KS).  Falls back to fallback_weights for any year not in acres_df.
    """
    sub = yield_df[yield_df["state_alpha"].isin(class_states)].copy()
    if sub.empty:
        return pd.DataFrame()

    # Build per-year acres lookup: {year: {state: harvested_ac}}
    acres_lookup: dict[int, dict[str, float]] = {}
    if not acres_df.empty:
        col = "state" if "state" in acres_df.columns else "state_alpha"
        acr = acres_df[acres_df[col].isin(class_states)]
        for yr, grp in acr.groupby("year"):
            yr_dict = dict(zip(grp[col], grp["harvested_ac"]))
            if yr_dict:
                acres_lookup[int(yr)] = yr_dict

    rows = []
    for yr, grp in sub.groupby("year"):
        grp = grp.dropna(subset=["yield_bu_ac"]).copy()
        if grp.empty:
            continue
        yr_acres = acres_lookup.get(int(yr), {})
        if yr_acres:
            grp["w"] = grp["state_alpha"].map(yr_acres).fillna(0.0)
        else:
            grp["w"] = grp["state_alpha"].map(fallback_weights).fillna(0.0)
        w_sum = float(grp["w"].sum())
        if w_sum == 0:
            continue
        rows.append({
            "year":        int(yr),
            "state_alpha": series_key,
            "state_name":  series_name,
            "yield_bu_ac": float((grp["yield_bu_ac"] * grp["w"]).sum() / w_sum),
        })
    return pd.DataFrame(rows)


def _class_weighted_yield_with_override_dynamic(
    winter_yield_df: pd.DataFrame,
    class_yield_df: pd.DataFrame,
    acres_df: pd.DataFrame,
    class_states: set,
    fallback_weights: dict,
    series_key: str,
    series_name: str,
) -> pd.DataFrame:
    """
    Like _class_weighted_yield_with_override but uses YEAR-SPECIFIC harvested acres weights.
    NASS class-specific state yields (class_yield_df) take priority over total Winter yields.
    Dynamic per-year weights applied from acres_df (falls back to fallback_weights).
    """
    frames = []
    if not class_yield_df.empty:
        frames.append(class_yield_df[class_yield_df["state_alpha"].isin(class_states)])

    winter_sub = winter_yield_df[winter_yield_df["state_alpha"].isin(class_states)].copy()
    if frames:
        covered = pd.concat(frames)[["year", "state_alpha"]].drop_duplicates()
        winter_sub = winter_sub.merge(covered, on=["year", "state_alpha"],
                                      how="left", indicator=True)
        winter_sub = winter_sub[winter_sub["_merge"] == "left_only"].drop(columns=["_merge"])
    frames.append(winter_sub)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return _class_weighted_yield_dynamic(
        combined, acres_df, class_states, fallback_weights, series_key, series_name,
    )


def _white_weighted_yield_dynamic(
    winter_yield_df: pd.DataFrame,
    soft_white_yield_df: pd.DataFrame,
    acres_df: pd.DataFrame,
    fallback_weights: dict,
) -> pd.DataFrame:
    """White weighted yield using year-specific acres — NASS SOFT WHITE yields preferred."""
    white_states = WHEAT_CLASSES["White Winter"]
    return _class_weighted_yield_with_override_dynamic(
        winter_yield_df, soft_white_yield_df, acres_df,
        white_states, fallback_weights, "White", "White Index",
    )


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_nass_srw_national_yield(years: tuple) -> pd.DataFrame:
    """
    Pull NASS-published U.S. national Soft Red Winter YIELD (bu/ac).
    Uses state_name=US TOTAL — NASS stores national rows this way, not agg_level_desc=NATIONAL.
    Returns DataFrame with columns: year, nass_yield.
    """
    if not years:
        return pd.DataFrame()
    params = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    "WHEAT",
        "class_desc":        "SOFT RED WINTER",
        "statisticcat_desc": "YIELD",
        "freq_desc":         "ANNUAL",
        "state_name":        "US TOTAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    payload = _nass_get(params)
    if "data" not in payload or not payload["data"]:
        return pd.DataFrame()
    df = pd.DataFrame(payload["data"])
    df = df[[c for c in ["year", "state_alpha", "Value"] if c in df.columns]].copy()
    df["Value"] = df["Value"].astype(str).str.replace(",", "", regex=False)
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"]  = df["year"].astype(int)
    df = df.dropna(subset=["Value"])
    df = df[df["state_alpha"] == "US"]
    if df.empty:
        return pd.DataFrame()
    df = df.groupby("year", as_index=False)["Value"].mean()
    return df.rename(columns={"Value": "nass_yield"})


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_nass_white_national_yield(years: tuple) -> pd.DataFrame:
    """
    Pull NASS-published U.S. national Soft White YIELD (bu/ac).
    Uses state_name=US TOTAL — NASS stores national rows this way, not agg_level_desc=NATIONAL.
    Returns DataFrame with columns: year, nass_yield.
    """
    if not years:
        return pd.DataFrame()
    params = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    "WHEAT",
        "class_desc":        "SOFT WHITE",
        "statisticcat_desc": "YIELD",
        "freq_desc":         "ANNUAL",
        "state_name":        "US TOTAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    payload = _nass_get(params)
    if "data" not in payload or not payload["data"]:
        return pd.DataFrame()
    df = pd.DataFrame(payload["data"])
    df = df[[c for c in ["year", "state_alpha", "Value"] if c in df.columns]].copy()
    df["Value"] = df["Value"].astype(str).str.replace(",", "", regex=False)
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"]  = df["year"].astype(int)
    df = df.dropna(subset=["Value"])
    df = df[df["state_alpha"] == "US"]
    if df.empty:
        return pd.DataFrame()
    df = df.groupby("year", as_index=False)["Value"].mean()
    return df.rename(columns={"Value": "nass_yield"})


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def fetch_hrw_national_yield(years: tuple) -> pd.DataFrame:
    """
    Pull NASS-published U.S. national Hard Red Winter YIELD (bu/ac).
    Uses state_name=US TOTAL — NASS stores national rows this way, not agg_level_desc=NATIONAL.
    Returns DataFrame with columns: year, nass_yield.
    """
    if not years:
        return pd.DataFrame()
    params = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "CROPS",
        "group_desc":        "FIELD CROPS",
        "commodity_desc":    "WHEAT",
        "class_desc":        "HARD RED WINTER",
        "statisticcat_desc": "YIELD",
        "freq_desc":         "ANNUAL",
        "state_name":        "US TOTAL",
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    payload = _nass_get(params)
    if "data" not in payload or not payload["data"]:
        return pd.DataFrame()
    df = pd.DataFrame(payload["data"])
    df = df[[c for c in ["year", "state_alpha", "Value"] if c in df.columns]].copy()
    df["Value"] = df["Value"].astype(str).str.replace(",", "", regex=False)
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["year"]  = df["year"].astype(int)
    df = df.dropna(subset=["Value"])
    df = df[df["state_alpha"] == "US"].copy()
    if df.empty:
        return pd.DataFrame()
    df = df.groupby("year", as_index=False)["Value"].mean()
    return df.rename(columns={"Value": "nass_yield"})


def _trend_at(td: dict, yr: int) -> float:
    """Evaluate the trendline for a given harvest year."""
    return td["slope"] * yr + td["intercept"]


def _dev_pct(actual: float, trend: float) -> float:
    """Percentage deviation of actual yield from trendline yield."""
    return (actual - trend) / trend * 100 if trend else float("nan")


def _compute_analog_forecast(
    series_key: str,
    raw_df: pd.DataFrame,
    sel_week_ts,
    sel_usda_yr: int,
    yield_lookup: dict,
    trend_data: dict,
    hrw_weights: dict,
    class_weights_map: dict | None = None,
    crop_yr_cutoff: int | None = 9,
    cond_weights: dict | None = None,
    min_analogs: int = 3,
) -> dict | None:
    """
    Run the JSA analog model for any series key (state_alpha, 'US', 'HRW', 'SRW', or 'White').
    Pass cond_weights to use empirically-calibrated JSA weights; defaults to CONDITION_WEIGHTS.
    min_analogs: minimum number of analog years with both conditions AND yield data required
                 to produce a forecast; returns None if data is too sparse (prevents
                 unreliable forecasts for small states with limited NASS conditions history).
    Returns dict with keys: forecast, cur_trend, avg_dev, n_analogs, analogs, cur_jsa, jsa_snap
    or None if insufficient data.
    """
    if sel_week_ts is None or series_key not in trend_data:
        return None

    _cwm = class_weights_map or {"HRW": hrw_weights}
    if series_key in ("HRW", "SRW", "White"):
        _wts = _cwm.get(series_key, hrw_weights)
        jsa_df = hrw_series(raw_df, "JSA Index", weights=_wts, cond_weights=cond_weights).rename(columns={"metric": "jsa_val"})
    else:
        jsa_df = _us_series(raw_df, "JSA Index", series_key, cond_weights=cond_weights).rename(columns={"metric": "jsa_val"})

    if jsa_df.empty:
        return None

    jsa_df = jsa_df.copy()
    jsa_df["week_ending"] = pd.to_datetime(jsa_df["week_ending"])
    if crop_yr_cutoff:
        jsa_df["crop_year"] = (
            jsa_df["week_ending"].dt.year
            + (jsa_df["week_ending"].dt.month >= crop_yr_cutoff).astype(int)
        )
    else:
        jsa_df["crop_year"] = jsa_df["week_ending"].dt.year
    jsa_df["iso_week"] = jsa_df["week_ending"].dt.isocalendar().week.astype(int)
    jsa_iso = pd.Timestamp(sel_week_ts).isocalendar().week

    jsa_snap = {}
    for cy, grp in jsa_df.groupby("crop_year"):
        grp = grp.copy()
        grp["_d"] = (grp["iso_week"] - jsa_iso).abs()
        # Deterministic tiebreak: when two weeks are equidistant from the target ISO week,
        # prefer the later week (more recent data). Sort ascending on _d, descending on
        # week_ending so iloc[0] always picks the same row regardless of DataFrame order.
        best = grp.sort_values(["_d", "week_ending"], ascending=[True, False]).iloc[:1]
        if not best.empty:
            jsa_snap[cy] = float(best["jsa_val"].iloc[0])

    cur_jsa = jsa_snap.get(sel_usda_yr)
    if cur_jsa is None:
        return None

    # Deterministic analog selection: when JSA distances are tied, break by crop_year
    # (prefer more-recent analog years) so the 6 closest are always the same set.
    hist_diffs = sorted(
        [(cy, v) for cy, v in jsa_snap.items() if cy != sel_usda_yr],
        key=lambda x: (abs(x[1] - cur_jsa), -x[0]),   # primary: distance, secondary: recency
    )
    closest_6 = hist_diffs[:6]

    analog_lkup = yield_lookup.get(series_key, {})
    analogs = []
    for acy, ajsa in closest_6:
        ayld = analog_lkup.get(acy)
        analogs.append({
            "mkt_lbl":   mkt_label(acy),
            "crop_year": acy,
            "jsa_val":   ajsa,
            "jsa_diff":  ajsa - cur_jsa,
            "yield_act": ayld["yield"] if ayld else None,
            "yield_dev": ayld["dev"]   if ayld else None,
        })

    valid_devs = [a["yield_dev"] for a in analogs if a["yield_dev"] is not None]
    td = trend_data[series_key]
    cur_trend = _trend_at(td, sel_usda_yr)
    if not valid_devs or cur_trend == 0:
        return None
    if len(valid_devs) < min_analogs:
        # Too few analog years with both conditions and yield data to produce
        # a reliable forecast (common for small states with sparse NASS history)
        return None

    avg_dev  = sum(valid_devs) / len(valid_devs)
    forecast = cur_trend * (1 + avg_dev / 100)
    return {
        "forecast":   round(forecast, 1),
        "cur_trend":  cur_trend,
        "avg_dev":    avg_dev,
        "n_analogs":  len(valid_devs),
        "analogs":    sorted(analogs, key=lambda x: x["crop_year"]),
        "cur_jsa":    cur_jsa,
        "jsa_snap":   jsa_snap,
    }


# ── Condition Band Weight Calibration ─────────────────────────────────────────
# Tests whether the equal-spaced JSA weights (VP=0 P=25 F=50 G=75 E=100) are
# empirically optimal by regressing final yield deviation on condition band shares.
# Allows asymmetry (downside ≠ upside) and non-linearity to be detected.

def _build_condition_shares_df(
    raw_df: pd.DataFrame,
    series_key: str,
    weights: dict | None,
    sel_usda_yr: int,
    crop_yr_cutoff: int = 9,
) -> pd.DataFrame:
    """
    Build a long DataFrame (crop_year, iso_week, VP, P, F, G, E) where each
    condition column is the weighted % share for the active series.

    For "US": reads the US TOTAL row directly (NASS national aggregate).
    For "HRW"/"SRW"/"White": production-weighted average across class states.
    For individual states: reads that state's rows.
    """
    BAND = {"VERY POOR": "VP", "POOR": "P", "FAIR": "F", "GOOD": "G", "EXCELLENT": "E"}

    if series_key in ("HRW", "SRW", "White"):
        _w   = weights or {}
        _sts = set(_w.keys())
        src  = _states_only(raw_df)
        src  = src[src["state_alpha"].isin(_sts)].copy()
    elif series_key == "US":
        src = raw_df[raw_df["state_alpha"] == "US"].copy()
    else:
        src = raw_df[raw_df["state_alpha"] == series_key].copy()

    if src.empty:
        return pd.DataFrame()

    src = src.copy()
    src["week_ending"] = pd.to_datetime(src["week_ending"])
    src["iso_week"]    = src["week_ending"].dt.isocalendar().week.astype(int)
    if crop_yr_cutoff:
        src["crop_year"] = (
            src["week_ending"].dt.year
            + (src["week_ending"].dt.month >= crop_yr_cutoff).astype(int)
        )
    else:
        src["crop_year"] = src["week_ending"].dt.year

    src["band"] = src["condition"].map(BAND)
    src = src.dropna(subset=["band", "Value"])

    rows = []
    for (cy, iso_w), grp in src.groupby(["crop_year", "iso_week"]):
        if int(cy) >= sel_usda_yr:
            continue
        band_vals: dict[str, float] = {}
        for bc in ["VP", "P", "F", "G", "E"]:
            bgrp = grp[grp["band"] == bc]
            if bgrp.empty:
                band_vals[bc] = float("nan")
                continue
            if series_key in ("HRW", "SRW", "White"):
                bgrp = bgrp.copy()
                bgrp["w"] = bgrp["state_alpha"].map(_w)
                bgrp = bgrp.dropna(subset=["w"])
                w_sum = bgrp["w"].sum()
                band_vals[bc] = float((bgrp["Value"] * bgrp["w"]).sum() / w_sum) if w_sum > 0 else float("nan")
            else:
                band_vals[bc] = float(bgrp["Value"].sum())

        # Impute the one band that NASS occasionally omits from a week's report.
        # Because all 5 bands always sum to 100 %, any single missing band can
        # be recovered exactly: missing = 100 − Σ(other four).
        _known = {b: v for b, v in band_vals.items() if not np.isnan(v)}
        if len(_known) == 4:
            _missing_band = next(b for b in ["VP", "P", "F", "G", "E"] if b not in _known)
            band_vals[_missing_band] = max(0.0, 100.0 - sum(_known.values()))

        rows.append({"crop_year": int(cy), "iso_week": int(iso_w), **band_vals})

    return pd.DataFrame(rows)


def _run_band_regression(
    shares_df: pd.DataFrame,
    iso_week: int,
    yield_lookup: dict,
    series_key: str,
    min_years: int = 8,
) -> dict | None:
    """
    OLS: yield_dev = α + β_VP×VP + β_P×P + β_G×G + β_E×E  (Fair omitted = baseline).
    Returns empirical weights rescaled to 0-100, R² stats, asymmetry ratio.
    """
    if shares_df.empty:
        return None

    # Match closest ISO week per crop_year within ±2 weeks
    wk = shares_df[shares_df["iso_week"].between(iso_week - 2, iso_week + 2)].copy()
    if wk.empty:
        return None
    wk["_d"] = (wk["iso_week"] - iso_week).abs()
    wk = wk.sort_values("_d").groupby("crop_year", as_index=False).first().drop(columns=["_d"])

    # Attach yield deviations
    yld = yield_lookup.get(series_key, {})
    wk["yield_dev"] = wk["crop_year"].map(lambda cy: yld.get(cy, {}).get("dev") if isinstance(yld.get(cy), dict) else None)
    wk = wk.dropna(subset=["VP", "P", "F", "G", "E", "yield_dev"])
    if len(wk) < min_years:
        return None

    # OLS — Fair omitted as baseline; intercept represents yield at 100 % Fair
    X = np.column_stack([np.ones(len(wk)), wk["VP"].values, wk["P"].values,
                         wk["G"].values, wk["E"].values])
    y = wk["yield_dev"].values

    try:
        coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except Exception:
        return None

    alpha, b_VP, b_P, b_G, b_E = coef

    # Standard errors
    y_hat     = X @ coef
    residuals = y - y_hat
    dof       = max(len(y) - 5, 1)
    s2        = float(np.sum(residuals ** 2) / dof)
    try:
        XTX_inv = np.linalg.pinv(X.T @ X)
        se      = np.sqrt(np.diag(XTX_inv) * s2)
        se_VP, se_P, se_G, se_E = float(se[1]), float(se[2]), float(se[3]), float(se[4])
    except Exception:
        se_VP = se_P = se_G = se_E = float("nan")

    # R² of regression
    ss_tot       = float(np.sum((y - y.mean()) ** 2))
    ss_res       = float(np.sum(residuals ** 2))
    r2_empirical = (1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    # R² of current JSA (VP=0 P=25 F=50 G=75 E=100, divided by 100)
    jsa_vals = (0 * wk["VP"] + 25 * wk["P"] + 50 * wk["F"] + 75 * wk["G"] + 100 * wk["E"]) / 100
    corr_jsa = float(np.corrcoef(jsa_vals.values, y)[0, 1])
    r2_jsa   = corr_jsa ** 2 if not np.isnan(corr_jsa) else 0.0

    # Rescale regression coefficients to 0-100 index weight scale.
    # VP is anchored at 0 and E is anchored at 100; all other bands are
    # interpolated linearly between them.  This keeps the JSA index in the
    # 0-100 range while still capturing empirical asymmetry (e.g. Fair at 65
    # means Poor conditions drag more than Excellent conditions lift).
    rng = b_E - b_VP  # should be positive; if not, fall back to equal-spaced
    if abs(rng) > 0.001:
        w_emp = {
            "VP": 0.0,
            "P":  round(max(0.0, min(100.0, (b_P - b_VP) * 100.0 / rng)), 1),
            "F":  round(max(0.0, min(100.0, (0.0 - b_VP) * 100.0 / rng)), 1),
            "G":  round(max(0.0, min(100.0, (b_G - b_VP) * 100.0 / rng)), 1),
            "E":  100.0,
        }
    else:
        w_emp = {"VP": 0.0, "P": 25.0, "F": 50.0, "G": 75.0, "E": 100.0}

    # Asymmetry: how much more potent is downside vs upside (relative to Fair)
    upside   = b_E          # β for Excellent (positive)
    downside = abs(b_VP)    # |β| for Very Poor (should be negative)
    asymmetry = round(downside / upside, 3) if upside > 0.001 else None

    return {
        "n_years":          len(wk),
        "coef":             {"VP": b_VP, "P": b_P, "F": 0.0, "G": b_G, "E": b_E},
        "se":               {"VP": se_VP, "P": se_P, "F": 0.0, "G": se_G, "E": se_E},
        "weights_current":  {"VP": 0, "P": 25, "F": 50, "G": 75, "E": 100},
        "weights_empirical": w_emp,
        "r2_empirical":     round(r2_empirical, 4),
        "r2_jsa":           round(r2_jsa, 4),
        "r2_gain":          round(r2_empirical - r2_jsa, 4),
        "asymmetry":        asymmetry,
        "years_used":       sorted(wk["crop_year"].tolist()),
    }


def _scan_band_regression(
    shares_df: pd.DataFrame,
    yield_lookup: dict,
    series_key: str,
    iso_min: int = 5,
    iso_max: int = 22,
    min_years: int = 8,
) -> pd.DataFrame:
    """
    Scan ISO weeks iso_min–iso_max.  For each week return R² of current JSA
    and R² of the empirically-fitted 4-predictor model.
    """
    rows = []
    for iso_w in range(iso_min, iso_max + 1):
        res = _run_band_regression(shares_df, iso_w, yield_lookup, series_key, min_years)
        if res is None:
            continue
        rows.append({
            "iso_week":     iso_w,
            "r2_jsa":       round(res["r2_jsa"] * 100, 1),
            "r2_empirical": round(res["r2_empirical"] * 100, 1),
            "r2_gain":      round(res["r2_gain"] * 100, 1),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def _scan_best_week(_raw_df, _sel_usda_yr, _yield_devs_json,
                    _hrw_w_tup, _srw_w_tup, _white_w_tup,
                    _crop_yr_cutoff=9, _scan_iso_min=5, _scan_iso_max=22,
                    commodity_key: str = ""):
    """
    For every series with ≥8 years of yield deviation data, scan ISO weeks
    _scan_iso_min–_scan_iso_max
    (Feb–early Jun, post-dormancy) and return the week with the highest OLS R²
    between the JSA condition index and final yield deviation from trend.
    """
    import json
    yield_devs = json.loads(_yield_devs_json)
    hrw_w  = dict(_hrw_w_tup)
    srw_w  = dict(_srw_w_tup)
    white_w = dict(_white_w_tup)
    _cwm = {"HRW": hrw_w, "SRW": srw_w, "White": white_w}

    results = {}
    for sk, devs_str in yield_devs.items():
        devs = {int(yr): float(dv) for yr, dv in devs_str.items() if int(yr) < _sel_usda_yr}
        if len(devs) < 8:
            continue

        if sk in ("HRW", "SRW", "White"):
            jsa_df = hrw_series(_raw_df, "JSA Index", weights=_cwm[sk]).rename(columns={"metric": "jsa_val"})
        else:
            jsa_df = _us_series(_raw_df, "JSA Index", sk).rename(columns={"metric": "jsa_val"})
        if jsa_df.empty:
            continue

        jsa_df = jsa_df.copy()
        jsa_df["week_ending"] = pd.to_datetime(jsa_df["week_ending"])
        if _crop_yr_cutoff:
            jsa_df["crop_year"] = (
                jsa_df["week_ending"].dt.year
                + (jsa_df["week_ending"].dt.month >= _crop_yr_cutoff).astype(int)
            )
        else:
            jsa_df["crop_year"] = jsa_df["week_ending"].dt.year
        jsa_df["iso_week"] = jsa_df["week_ending"].dt.isocalendar().week.astype(int)
        jsa_hist = jsa_df[jsa_df["crop_year"] < _sel_usda_yr]

        candidate_weeks = sorted(jsa_hist[jsa_hist["iso_week"].between(_scan_iso_min, _scan_iso_max)]["iso_week"].unique())
        if not candidate_weeks:
            continue

        # Pre-compute per-crop-year numpy arrays once — avoids re-grouping inside the ISO-week loop
        pivot = {}  # {crop_year: (iso_week_arr, jsa_val_arr)}
        for cy, grp in jsa_hist.groupby("crop_year"):
            pivot[cy] = (grp["iso_week"].values, grp["jsa_val"].values)

        best_r2, best_iso, all_r2 = -1.0, None, {}
        for iso_w in candidate_weeks:
            # Find closest ISO week per crop_year using pre-computed arrays
            snap = {}
            for cy, (iso_arr, val_arr) in pivot.items():
                idx = int(np.argmin(np.abs(iso_arr - iso_w)))
                snap[cy] = float(val_arr[idx])

            pairs = [(snap[yr], devs[yr]) for yr in snap if yr in devs]
            if len(pairs) < 8:
                continue
            xs = np.array([p[0] for p in pairs])
            ys = np.array([p[1] for p in pairs])
            # corrcoef is faster than lstsq for R² and numerically stable
            corr = float(np.corrcoef(xs, ys)[0, 1])
            r2   = round(corr ** 2 if not np.isnan(corr) else 0.0, 4)
            all_r2[iso_w] = r2
            if r2 > best_r2:
                best_r2, best_iso = r2, iso_w

        if best_iso is not None:
            results[sk] = {"best_iso": best_iso, "r2": round(best_r2, 4),
                           "n_years": len(devs), "all_r2": all_r2}
    return results


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def _scan_best_week_harvest(_raw_df, _sel_usda_yr, _ph_data_json,
                            _hrw_w_tup, _srw_w_tup, _white_w_tup,
                            _crop_yr_cutoff=9, _scan_iso_min=5, _scan_iso_max=22,
                            commodity_key: str = ""):
    """
    For every series (US, HRW, SRW, White, and each state) with ≥8 years of
    % harvested history, scan ISO weeks _scan_iso_min–_scan_iso_max and find
    the week where the JSA condition index best predicts final % harvested
    (i.e. highest OLS R²).  Mirrors _scan_best_week but targets abandonment/
    % harvested rather than yield deviation from trend.

    Parameters
    ----------
    _ph_data_json : str  JSON-encoded {series_key: {year_str: pct_harvested}}
    """
    import json
    ph_data  = json.loads(_ph_data_json)
    hrw_w    = dict(_hrw_w_tup)
    srw_w    = dict(_srw_w_tup)
    white_w  = dict(_white_w_tup)
    _cwm     = {"HRW": hrw_w, "SRW": srw_w, "White": white_w}

    results = {}
    for sk, ph_by_year in ph_data.items():
        ph = {int(yr): float(v) for yr, v in ph_by_year.items()
              if int(yr) < _sel_usda_yr and v is not None}
        if len(ph) < 8:
            continue

        if sk in ("HRW", "SRW", "White"):
            jsa_df = hrw_series(_raw_df, "JSA Index",
                                weights=_cwm[sk]).rename(columns={"metric": "jsa_val"})
        else:
            jsa_df = _us_series(_raw_df, "JSA Index", sk).rename(columns={"metric": "jsa_val"})
        if jsa_df.empty:
            continue

        jsa_df = jsa_df.copy()
        jsa_df["week_ending"] = pd.to_datetime(jsa_df["week_ending"])
        if _crop_yr_cutoff:
            jsa_df["crop_year"] = (
                jsa_df["week_ending"].dt.year
                + (jsa_df["week_ending"].dt.month >= _crop_yr_cutoff).astype(int)
            )
        else:
            jsa_df["crop_year"] = jsa_df["week_ending"].dt.year
        jsa_df["iso_week"] = jsa_df["week_ending"].dt.isocalendar().week.astype(int)
        jsa_hist = jsa_df[jsa_df["crop_year"] < _sel_usda_yr]

        candidate_weeks = sorted(
            jsa_hist[jsa_hist["iso_week"].between(_scan_iso_min, _scan_iso_max)]["iso_week"].unique()
        )
        if not candidate_weeks:
            continue

        # Pre-compute per-crop-year numpy arrays once
        pivot = {}
        for cy, grp in jsa_hist.groupby("crop_year"):
            pivot[cy] = (grp["iso_week"].values, grp["jsa_val"].values)

        best_r2, best_iso, all_r2 = -1.0, None, {}
        for iso_w in candidate_weeks:
            snap = {}
            for cy, (iso_arr, val_arr) in pivot.items():
                idx = int(np.argmin(np.abs(iso_arr - iso_w)))
                snap[cy] = float(val_arr[idx])

            pairs = [(snap[yr], ph[yr]) for yr in snap if yr in ph]
            if len(pairs) < 8:
                continue
            xs   = np.array([p[0] for p in pairs])
            ys   = np.array([p[1] for p in pairs])
            corr = float(np.corrcoef(xs, ys)[0, 1])
            r2   = round(corr ** 2 if not np.isnan(corr) else 0.0, 4)
            all_r2[iso_w] = r2
            if r2 > best_r2:
                best_r2, best_iso = r2, iso_w

        if best_iso is not None:
            results[sk] = {
                "best_iso": best_iso,
                "r2":       round(best_r2, 4),
                "n_years":  len(ph),
                "all_r2":   all_r2,
            }
    return results


@st.cache_data(ttl=3600, show_spinner=False, persist="disk")
def _scan_cumulative_start(
    _raw_df, _sel_usda_yr, _yield_devs_json,
    _hrw_w_tup, _srw_w_tup, _white_w_tup,
    _forecast_iso_week: int,
    _crop_yr_cutoff: int = 9,
    _start_iso_min: int = 15,
    commodity_key: str = "",
) -> dict:
    """
    Standalone cumulative-conditions scan (does NOT touch the existing single-week model).

    For each candidate cumulative start week S from _start_iso_min to
    (_forecast_iso_week - 1), compute mean(JSA[S .. forecast_iso_week]) for
    every historical crop year, then independently fit two models:

        Model A  — Cumulative only:   yield_dev ~ cumul_JSA(S→W)
        Model B  — Two-factor:        yield_dev ~ snap_JSA(W) + cumul_JSA(S→W)

    Metrics per start week:
        r2_A, adj_r2_A, loo_rmse_A
        r2_B, adj_r2_B, loo_rmse_B
        f_stat   (partial F for the cumulative term added to single-week model)
        n_years

    Returns {series_key: pd.DataFrame(rows indexed by start week)}.
    """
    import json as _jmod

    yield_devs = _jmod.loads(_yield_devs_json)
    hrw_w  = dict(_hrw_w_tup)
    srw_w  = dict(_srw_w_tup)
    white_w = dict(_white_w_tup)
    _cwm = {"HRW": hrw_w, "SRW": srw_w, "White": white_w}

    def _adj_r2(r2, n, p):
        return 1 - (1 - r2) * (n - 1) / max(n - p - 1, 1)

    def _loo_rmse(X_mat, y_vec):
        """Leave-one-out RMSE for an OLS model with design matrix X_mat."""
        n = len(y_vec)
        sq = []
        for i in range(n):
            mask = np.ones(n, dtype=bool)
            mask[i] = False
            try:
                coef = np.linalg.lstsq(X_mat[mask], y_vec[mask], rcond=None)[0]
                sq.append((y_vec[i] - float(X_mat[i] @ coef)) ** 2)
            except Exception:
                pass
        return float(np.sqrt(np.mean(sq))) if sq else float("nan")

    results = {}
    for sk, devs_str in yield_devs.items():
        devs = {int(yr): float(dv) for yr, dv in devs_str.items()
                if int(yr) < _sel_usda_yr}
        if len(devs) < 8:
            continue

        if sk in ("HRW", "SRW", "White"):
            jsa_df = hrw_series(_raw_df, "JSA Index",
                                weights=_cwm[sk]).rename(columns={"metric": "jsa_val"})
        else:
            jsa_df = _us_series(_raw_df, "JSA Index", sk).rename(columns={"metric": "jsa_val"})
        if jsa_df.empty:
            continue

        jsa_df = jsa_df.copy()
        jsa_df["week_ending"] = pd.to_datetime(jsa_df["week_ending"])
        jsa_df["crop_year"] = (
            jsa_df["week_ending"].dt.year
            + (jsa_df["week_ending"].dt.month >= _crop_yr_cutoff).astype(int)
        )
        jsa_df["iso_week"] = jsa_df["week_ending"].dt.isocalendar().week.astype(int)
        jsa_hist = jsa_df[jsa_df["crop_year"] < _sel_usda_yr]

        # Build {crop_year: {iso_week: jsa_val}} for fast lookup
        pivot = {}
        for cy, grp in jsa_hist.groupby("crop_year"):
            pivot[cy] = dict(zip(grp["iso_week"].values, grp["jsa_val"].values))

        # Snapshot JSA at forecast week for each year (same as single-week model)
        snap = {}
        for cy, wk_dict in pivot.items():
            if not wk_dict:
                continue
            iso_arr = np.array(list(wk_dict.keys()))
            val_arr = np.array(list(wk_dict.values()))
            idx = int(np.argmin(np.abs(iso_arr - _forecast_iso_week)))
            snap[cy] = float(val_arr[idx])

        # Single-week R² baseline (reference line for charts)
        snap_pairs = [(snap[yr], devs[yr]) for yr in snap if yr in devs]
        if len(snap_pairs) >= 8:
            xs0 = np.array([p[0] for p in snap_pairs])
            ys0 = np.array([p[1] for p in snap_pairs])
            ss_tot0 = float(np.sum((ys0 - ys0.mean()) ** 2))
            X0 = np.column_stack([xs0, np.ones(len(xs0))])
            c0 = np.linalg.lstsq(X0, ys0, rcond=None)[0]
            r2_snap = float(1 - np.sum((ys0 - X0 @ c0) ** 2) / ss_tot0) if ss_tot0 > 0 else 0.0
            loo_snap = _loo_rmse(X0, ys0)
        else:
            r2_snap = loo_snap = float("nan")

        # Scan start weeks
        rows = []
        start_weeks = range(_start_iso_min, _forecast_iso_week)
        for sw in start_weeks:
            cumul = {}
            for cy, wk_dict in pivot.items():
                window_vals = [v for w, v in wk_dict.items()
                               if sw <= w <= _forecast_iso_week]
                if window_vals:
                    cumul[cy] = float(np.mean(window_vals))

            common = [yr for yr in cumul if yr in snap and yr in devs]
            if len(common) < 8:
                continue

            c_arr = np.array([cumul[yr] for yr in common])
            s_arr = np.array([snap[yr]  for yr in common])
            y_arr = np.array([devs[yr]  for yr in common])
            n     = len(common)
            ss_tot = float(np.sum((y_arr - y_arr.mean()) ** 2))
            if ss_tot <= 0:
                continue

            # Model A — cumulative only
            X_A   = np.column_stack([c_arr, np.ones(n)])
            c_A   = np.linalg.lstsq(X_A, y_arr, rcond=None)[0]
            r2_A  = float(1 - np.sum((y_arr - X_A @ c_A) ** 2) / ss_tot)
            arj_A = _adj_r2(r2_A, n, 1)
            loo_A = _loo_rmse(X_A, y_arr)

            # Model B — two-factor (snapshot + cumulative)
            X_B   = np.column_stack([s_arr, c_arr, np.ones(n)])
            c_B   = np.linalg.lstsq(X_B, y_arr, rcond=None)[0]
            r2_B  = float(1 - np.sum((y_arr - X_B @ c_B) ** 2) / ss_tot)
            arj_B = _adj_r2(r2_B, n, 2)
            loo_B = _loo_rmse(X_B, y_arr)

            # Partial F-stat: gain from adding cumulative term to single-week model
            ss_res_A1 = float(np.sum((y_arr - X0[:n] @ c0) ** 2)) if len(snap_pairs) == n else float("nan")
            ss_res_B  = float(np.sum((y_arr - X_B @ c_B) ** 2))
            dof_res   = max(n - 3, 1)
            f_stat = float((ss_res_A1 - ss_res_B) / ss_res_B * dof_res) if not np.isnan(ss_res_A1) and ss_res_B > 0 else float("nan")

            rows.append({
                "start_week":    sw,
                "n_years":       n,
                "r2_snap":       round(r2_snap * 100, 1),
                "loo_snap":      round(loo_snap, 2),
                "r2_A":          round(r2_A  * 100, 1),
                "adj_r2_A":      round(arj_A * 100, 1),
                "loo_rmse_A":    round(loo_A, 2),
                "r2_B":          round(r2_B  * 100, 1),
                "adj_r2_B":      round(arj_B * 100, 1),
                "loo_rmse_B":    round(loo_B, 2),
                "f_stat":        round(f_stat, 2) if not np.isnan(f_stat) else float("nan"),
                "gain_loo_vs_snap": round(loo_snap - loo_B, 2) if not np.isnan(loo_snap) else float("nan"),
            })

        if rows:
            results[sk] = {
                "rows":     pd.DataFrame(rows),
                "r2_snap":  round(r2_snap * 100, 1),
                "loo_snap": round(loo_snap, 2),
                "n_years":  len(devs),
            }

    return results


def _closest_week(ref_df: pd.DataFrame, target_dt: pd.Timestamp) -> pd.DataFrame:
    """Return rows from ref_df whose week_ending is closest to target_dt (date fallback)."""
    if ref_df.empty:
        return pd.DataFrame()
    idx = (ref_df["week_ending"] - target_dt).abs().idxmin()
    return ref_df[ref_df["week_ending"] == ref_df.loc[idx, "week_ending"]]


def _closest_week_iso(ref_df: pd.DataFrame, target_iso: int) -> pd.DataFrame:
    """Return rows from ref_df whose ISO week number is closest to target_iso."""
    if ref_df.empty:
        return pd.DataFrame()
    df = ref_df.copy()
    df["_iso"] = df["week_ending"].dt.isocalendar().week.astype(int)
    df["_diff"] = (df["_iso"] - target_iso).abs()
    best_wk = df.loc[df["_diff"].idxmin(), "week_ending"]
    return ref_df[ref_df["week_ending"] == best_wk]


def _match_week_in_year(src_df: pd.DataFrame, usda_year: int, target_iso: int) -> pd.Timestamp | None:
    """Return the week_ending date in usda_year whose ISO week is closest to target_iso."""
    yr_df = src_df[src_df["year"] == usda_year].copy()
    if yr_df.empty:
        return None
    yr_df["_iso"] = yr_df["week_ending"].dt.isocalendar().week.astype(int)
    yr_df["_diff"] = (yr_df["_iso"] - target_iso).abs()
    return yr_df.loc[yr_df["_diff"].idxmin(), "week_ending"]


def _condition_stats(
    cond_df: pd.DataFrame,
    pct_col: str,
    prefix: str,
    states: list,
    latest_week: pd.Timestamp,
    prior_week_dt,
    target_in_py: pd.Timestamp,
    target_usda_year: int,
    olympic_years: list,
    target_iso_week: int | None = None,
) -> pd.DataFrame:
    """Compute Current/WoW/YoY/Olympic stats for one condition dataframe."""
    yr     = cond_df[cond_df["year"] == target_usda_year]
    cur    = yr[yr["week_ending"] == latest_week]
    prior  = yr[yr["week_ending"] == prior_week_dt] if (not yr.empty and pd.notna(prior_week_dt)) else pd.DataFrame()

    # Prior year: match by ISO week when available, fall back to date proximity
    if target_iso_week is not None:
        py = _closest_week_iso(cond_df[cond_df["year"] == target_usda_year - 1], target_iso_week)
    else:
        py = _closest_week(cond_df[cond_df["year"] == target_usda_year - 1], target_in_py)

    rows = []
    for state in states:
        def _val(df):
            v = df[df["state_alpha"] == state][pct_col].values
            return v[0] if len(v) else float("nan")

        c   = _val(cur)
        p   = _val(prior)
        y   = _val(py)

        # Olympic average for this state — match by ISO week
        s_oly = cond_df[(cond_df["state_alpha"] == state) & (cond_df["year"].isin(olympic_years))]
        oly_vals = []
        for yr_o in olympic_years:
            yr_s = s_oly[s_oly["year"] == yr_o]
            if yr_s.empty:
                continue
            if target_iso_week is not None:
                row = _closest_week_iso(yr_s, target_iso_week)
            else:
                try:
                    t = latest_week.replace(year=yr_o)
                except ValueError:
                    t = latest_week.replace(year=yr_o, day=28)
                row = _closest_week(yr_s, t)
            if not row.empty:
                oly_vals.append(row[pct_col].iloc[0])
        oly = olympic_avg(oly_vals)

        rows.append({
            "state_alpha":          state,
            f"{prefix}_Current":    c,
            f"{prefix}_WoW":        c - p,
            f"{prefix}_YoY":        c - y,
            f"{prefix}_Olympic_Avg": oly,
            f"{prefix}_vs_Olympic": c - oly,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=900, show_spinner=False)
def build_comparison_table(
    ge_df: pd.DataFrame,
    pv_df: pd.DataFrame,
    fair_df: pd.DataFrame,
    jsa_df: pd.DataFrame,
    target_usda_year: int,
    target_week: pd.Timestamp | None = None,
) -> tuple:
    """
    For the given reporting week (default: most recent) compute per-state stats for
    G+E, P+VP, Fair and JSA.  Returns (table_df, latest_week_date).
    """
    yr_data = ge_df[ge_df["year"] == target_usda_year]
    if yr_data.empty:
        return pd.DataFrame(), pd.NaT

    latest_week   = target_week if target_week is not None else yr_data["week_ending"].max()
    prior_week_dt = yr_data[yr_data["week_ending"] < latest_week]["week_ending"].max()
    olympic_years = sorted([y for y in ge_df["year"].unique() if y < target_usda_year])[-6:]

    # ISO week of the selected week — used for accurate cross-year matching
    target_iso_week = int(latest_week.isocalendar().week)

    # Prior-year equivalent week: ISO-week match instead of calendar-date replace
    py_match = _match_week_in_year(ge_df, target_usda_year - 1, target_iso_week)
    target_in_py = py_match if py_match is not None else (
        latest_week.replace(year=target_usda_year - 1)
    )

    # Base: state list from G+E current week
    cur_ge = yr_data[yr_data["week_ending"] == latest_week]
    result = cur_ge[["state_alpha", "state_name", "ge_pct"]].rename(columns={"ge_pct": "GE_Current"})
    states = result["state_alpha"].tolist()

    kwargs = dict(
        states=states,
        latest_week=latest_week,
        prior_week_dt=prior_week_dt,
        target_in_py=target_in_py,
        target_usda_year=target_usda_year,
        olympic_years=olympic_years,
        target_iso_week=target_iso_week,
    )

    ge_stats   = _condition_stats(ge_df,   "ge_pct",   "GE",   **kwargs)
    pv_stats   = _condition_stats(pv_df,   "pv_pct",   "PV",   **kwargs)
    fair_stats = _condition_stats(fair_df, "fair_pct", "Fair", **kwargs)
    jsa_stats  = _condition_stats(jsa_df,  "jsa_pct",  "JSA",  **kwargs)

    # GE_Current already in result; merge the rest
    for stats_df in [ge_stats, pv_stats, fair_stats, jsa_stats]:
        cols = [c for c in stats_df.columns if c != "GE_Current"]
        result = result.merge(stats_df[["state_alpha"] + [c for c in stats_df.columns if c != "state_alpha" and c != "GE_Current"]],
                              on="state_alpha", how="left")

    # WoW / YoY for GE come from ge_stats (already merged as GE_WoW, GE_YoY)
    # Rename GE_WoW → WoW_Change and GE_YoY → YoY_Change for backwards compat
    result = result.rename(columns={
        "GE_WoW":         "WoW_Change",
        "GE_YoY":         "YoY_Change",
        "GE_Olympic_Avg": "Olympic_Avg",
        "GE_vs_Olympic":  "vs_Olympic",
    })

    return result.reset_index(drop=True), latest_week


# ── Helpers ────────────────────────────────────────────────────────────────────

# Color palette anchors
_RED    = (215, 48,  39)
_YELLOW = (254, 224, 144)
_GREEN  = (26,  152, 80)
_WHITE  = (255, 255, 255)

def _lerp(c1, c2, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))

def _rgb_hex(rgb) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

def _font_on(hex_bg: str) -> str:
    """Return '#000000' or '#ffffff' for legibility on hex_bg."""
    h = hex_bg.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "#000000" if (0.299*r + 0.587*g + 0.114*b) / 255 > 0.45 else "#ffffff"

def _seq_bg(val, lo, hi, reverse=False) -> str:
    """Red→yellow→green sequential for absolute values, data-range scaled."""
    if pd.isna(val) or hi == lo:
        t = 0.5
    else:
        t = max(0.0, min(1.0, (val - lo) / (hi - lo)))
    if reverse:
        t = 1.0 - t
    rgb = _lerp(_RED, _YELLOW, t * 2) if t < 0.5 else _lerp(_YELLOW, _GREEN, (t - 0.5) * 2)
    return _rgb_hex(rgb)

def _green_only_bg(val, lo, hi, reverse=False) -> str:
    """White→Green gradient for TW column; reversed = White→Red for P+VP."""
    if pd.isna(val) or hi == lo:
        t = 0.5
    else:
        t = max(0.0, min(1.0, (val - lo) / (hi - lo)))
    if reverse:
        rgb = _lerp(_WHITE, _RED, t)
    else:
        rgb = _lerp(_WHITE, _GREEN, t)
    return _rgb_hex(rgb)

def _div_bg(val, max_abs, reverse=False) -> str:
    """Diverging white-center for change values; green=positive, red=negative (or reversed)."""
    if pd.isna(val) or max_abs == 0:
        return "#ffffff"
    t = max(-1.0, min(1.0, val / max_abs))
    if reverse:
        t = -t
    rgb = _lerp(_WHITE, _GREEN, t) if t >= 0 else _lerp(_WHITE, _RED, -t)
    return _rgb_hex(rgb)

def _cell_css(bg: str) -> str:
    return f"background-color: {bg}; color: {_font_on(bg)}; font-weight: 600"


# Column config per condition (curr, wow, yoy, avg, vs_avg)
_COND_COLS = {
    "Good + Excellent": ("GE_Current",   "WoW_Change", "YoY_Change", "Olympic_Avg",      "vs_Olympic"),
    "Fair":             ("Fair_Current", "Fair_WoW",   "Fair_YoY",   "Fair_Olympic_Avg", "Fair_vs_Olympic"),
    "Poor + Very Poor": ("PV_Current",   "PV_WoW",     "PV_YoY",     "PV_Olympic_Avg",   "PV_vs_Olympic"),
    "JSA Index":        ("JSA_Current",  "JSA_WoW",    "JSA_YoY",    "JSA_Olympic_Avg",  "JSA_vs_Olympic"),
}


def make_styled_table(result: pd.DataFrame, condition: str, selected_usda_year: int):
    """Build the interactive heatmap-styled comparison table (JPSI column naming)."""
    is_pv    = (condition == "Poor + Very Poor")
    curr_col, wow_col, yoy_col, avg_col, vs_col = _COND_COLS[condition]

    # Reconstruct absolute LW and LY values from current + delta
    lw_vals = result[curr_col] - result[wow_col]
    ly_vals = result[curr_col] - result[yoy_col]

    _share_vals = result["Share %"] if "Share %" in result.columns else pd.Series([0.0] * len(result))

    disp = pd.DataFrame({
        "State":    result["state_name"],
        "Share %":  _share_vals.values,
        "TW":       result[curr_col],
        "LW":       lw_vals,
        "LY":       ly_vals,
        "5YA":      result[avg_col],
        "ΔLW":      result[wow_col],
        "ΔLY":      result[yoy_col],
        "Δ5YA":     result[vs_col],
    }).reset_index(drop=True)

    plain_cols  = ["LW", "LY", "5YA"]
    change_cols = ["ΔLW", "ΔLY", "Δ5YA"]

    tw_lo, tw_hi   = float(disp["TW"].min()), float(disp["TW"].max())
    sh_lo, sh_hi   = float(disp["Share %"].min()), float(disp["Share %"].max())
    col_max_abs = {
        c: (float(disp[c].dropna().abs().max()) if disp[c].notna().any() else 1.0)
        for c in change_cols
    }

    def style_row(row):
        styles = {}
        v  = row["TW"]
        bg = _green_only_bg(v, tw_lo, tw_hi, reverse=is_pv) if pd.notna(v) else "#f4f5f7"
        styles["TW"] = _cell_css(bg)
        for col in plain_cols:
            styles[col] = f"background-color: {DM_SURFACE}; color: {DM_TEXT}"
        for col in change_cols:
            v  = row[col]
            bg = _div_bg(v, col_max_abs[col], reverse=is_pv) if pd.notna(v) else DM_SURFACE2
            styles[col] = _cell_css(bg)
        styles["State"]   = f"background-color: {DM_SURFACE}; font-weight: 600; color: {DM_TEXT}"
        styles["Share %"] = f"background-color:{DM_SURFACE};color:{DM_MUTED}"
        return pd.Series(styles)

    def _fmt_plain(x):
        if pd.isna(x):
            return "N/A"
        return str(round(x))

    def _fmt_delta(x):
        if pd.isna(x):
            return "N/A"
        v = round(x)
        return f"{'+' if v > 0 else ''}{v}"

    fmt = {c: _fmt_plain for c in plain_cols}
    fmt["TW"]      = _fmt_plain
    fmt["ΔLW"]     = _fmt_delta
    fmt["ΔLY"]     = _fmt_delta
    fmt["Δ5YA"]    = _fmt_delta
    fmt["Share %"] = lambda x: f"{x:.1f}%" if pd.notna(x) else "—"

    return (
        disp.style
        .apply(style_row, axis=1)
        .format(fmt)
        .hide(axis="index")
        .set_table_styles([
            {"selector": "thead th", "props": [
                ("background-color", DM_SURFACE2),
                ("color", DM_TEXT),
                ("font-weight", "700"),
                ("border-bottom", f"2px solid {JPSI_BLUE}"),
            ]},
            {"selector": "tbody td", "props": [("background-color", DM_SURFACE)]},
            {"selector": "table",    "props": [("background-color", DM_SURFACE)]},
        ])
    )


def fmt_delta(val, suffix="%") -> str:
    if pd.isna(val):
        return "N/A"
    v = round(val)
    sign = "+" if v > 0 else ""
    return f"{sign}{v}{suffix}"


def delta_html(val: float) -> str:
    if pd.isna(val):
        return '<span style="color:#6c757d;font-weight:600">N/A</span>'
    color = "#1a9850" if val > 0 else ("#d73027" if val < 0 else "#6c757d")
    arrow = "▲" if val > 0 else ("▼" if val < 0 else "—")
    return f'<span style="color:{color};font-weight:700;font-size:1.6rem">{arrow} {abs(round(val))}</span>'


PV_COLORSCALE = [       # inverted: low P+VP = green (good), high = red (bad)
    [0.00, "#1a9850"],
    [0.25, "#91cf60"],
    [0.50, "#fee090"],
    [0.75, "#fc8d59"],
    [1.00, "#d73027"],
]

FAIR_COLORSCALE = [     # neutral blue: more Fair % = deeper blue
    [0.00, "#f7fbff"],
    [0.40, "#6baed6"],
    [1.00, "#084594"],
]

# Maps each condition name → (z_col, colorscale, colorbar_title, pct_col, wow_col, yoy_col, avg_col, vs_col, is_pv)
CONDITION_MAP = {
    "Good + Excellent": ("GE_Current",   MAP_COLORSCALE, "G+E %",     "GE_Current",   "WoW_Change", "YoY_Change", "Olympic_Avg",      "vs_Olympic",       False),
    "Fair":             ("Fair_Current", MAP_COLORSCALE, "Fair %",    "Fair_Current", "Fair_WoW",   "Fair_YoY",   "Fair_Olympic_Avg", "Fair_vs_Olympic",  False),
    "Poor + Very Poor": ("PV_Current",   PV_COLORSCALE,  "P+VP %",    "PV_Current",   "PV_WoW",     "PV_YoY",     "PV_Olympic_Avg",   "PV_vs_Olympic",    True),
    "JSA Index":        ("JSA_Current",  MAP_COLORSCALE, "JSA Score", "JSA_Current",  "JSA_WoW",    "JSA_YoY",    "JSA_Olympic_Avg",  "JSA_vs_Olympic",   False),
}


def build_map(
    data: pd.DataFrame,
    selected_usda_year: int,
    condition: str = "Good + Excellent",
    label_metric: str = "Current %",
) -> go.Figure:
    """
    Choropleth colored by the selected condition.
    State labels show the selected metric for that condition.
    Hover always shows all three conditions side by side.
    """
    data = data.copy()
    prior_lbl = mkt_label(selected_usda_year - 1)

    z_col, colorscale, cb_title, pct_col, wow_col, yoy_col, avg_col, vs_col, _is_pv = CONDITION_MAP[condition]

    # ── Hover: all three conditions ──
    def _pct(r, c):
        v = r.get(c)
        return f"{round(v):.0f}%" if pd.notna(v) else "N/A"

    def _chg(r, c):
        v = r.get(c)
        return fmt_delta(v, "%") if pd.notna(v) else "N/A"

    def _hover(r):
        ly_lbl = prior_lbl
        return (
            f"<b>{r['state_name']}</b><br><br>"
            f"<b style='color:#1a9850'>Good + Excellent</b><br>"
            f"&nbsp; Current: {_pct(r,'GE_Current')} &nbsp;|&nbsp; "
            f"LW: {_chg(r,'WoW_Change')} &nbsp;|&nbsp; "
            f"LY ({ly_lbl}): {_chg(r,'YoY_Change')} &nbsp;|&nbsp; "
            f"Avg: {_pct(r,'Olympic_Avg')} ({_chg(r,'vs_Olympic')})<br>"
            f"<b style='color:#6baed6'>Fair</b><br>"
            f"&nbsp; Current: {_pct(r,'Fair_Current')} &nbsp;|&nbsp; "
            f"LW: {_chg(r,'Fair_WoW')} &nbsp;|&nbsp; "
            f"LY ({ly_lbl}): {_chg(r,'Fair_YoY')} &nbsp;|&nbsp; "
            f"Avg: {_pct(r,'Fair_Olympic_Avg')} ({_chg(r,'Fair_vs_Olympic')})<br>"
            f"<b style='color:#d73027'>Poor + Very Poor</b><br>"
            f"&nbsp; Current: {_pct(r,'PV_Current')} &nbsp;|&nbsp; "
            f"LW: {_chg(r,'PV_WoW')} &nbsp;|&nbsp; "
            f"LY ({ly_lbl}): {_chg(r,'PV_YoY')} &nbsp;|&nbsp; "
            f"Avg: {_pct(r,'PV_Olympic_Avg')} ({_chg(r,'PV_vs_Olympic')})<br>"
            f"<b style='color:#7b2d8b'>JSA Index</b><br>"
            f"&nbsp; Current: {_pct(r,'JSA_Current')} &nbsp;|&nbsp; "
            f"LW: {_chg(r,'JSA_WoW')} &nbsp;|&nbsp; "
            f"LY ({ly_lbl}): {_chg(r,'JSA_YoY')} &nbsp;|&nbsp; "
            f"Avg: {_pct(r,'JSA_Olympic_Avg')} ({_chg(r,'JSA_vs_Olympic')})"
        )

    data["hover"] = data.apply(_hover, axis=1)

    # ── State label column based on selected metric ──
    label_col_map = {
        "Current %":      (pct_col, lambda v: f"{v:.0f}%"),
        "vs LW":          (wow_col, lambda v: fmt_delta(v, "")),
        "vs LY":          (yoy_col, lambda v: fmt_delta(v, "")),
        "vs Olympic Avg": (vs_col,  lambda v: fmt_delta(v, "")),
    }
    lbl_col, lbl_fmt = label_col_map.get(label_metric, (pct_col, lambda v: f"{v:.0f}%"))

    # ── Delta mode: recolor by change column with diverging hot/cold scale ──
    _delta_col_map = {
        "vs LW":          wow_col,
        "vs LY":          yoy_col,
        "vs Olympic Avg": vs_col,
    }
    _is_delta = label_metric in _delta_col_map
    if _is_delta:
        _dz_col   = _delta_col_map[label_metric]
        _dz_vals  = data[_dz_col].dropna()
        _dz_abs   = float(_dz_vals.abs().quantile(0.90)) if not _dz_vals.empty else 10
        _dz_cap   = max(float(_dz_abs), 5.0)            # at least ±5 pts range
        z_col      = _dz_col
        colorscale = DELTA_COLORSCALE
        z_min      = -_dz_cap
        z_max      =  _dz_cap
        cb_title   = {"vs LW": "Δ vs LW %", "vs LY": "Δ vs LY %",
                      "vs Olympic Avg": "Δ vs Avg %"}[label_metric]
        cb_suffix  = "%"
    else:
        # Current % — stretch scale to make colours more vivid
        z_vals = data[z_col].dropna()
        z_min  = max(0.0,   float(z_vals.min()) - 5) if not z_vals.empty else 0
        z_max  = min(100.0, float(z_vals.max()) + 5) if not z_vals.empty else 100
        cb_suffix = "%"

    fig = go.Figure(go.Choropleth(
        locations=data["state_alpha"],
        z=data[z_col],
        locationmode="USA-states",
        colorscale=colorscale,
        zmin=z_min, zmax=z_max,
        colorbar=dict(
            title=dict(text=cb_title, font=dict(color=DM_TEXT, size=12)),
            tickfont=dict(color=DM_TEXT),
            ticksuffix=cb_suffix,
            len=0.85,
        ),
        text=data["hover"],
        hovertemplate="%{text}<extra></extra>",
        marker_line_color="white",
        marker_line_width=0.8,
    ))

    # Scattergeo text labels
    lats, lons, labels, hovers = [], [], [], []
    for _, row in data.iterrows():
        st = row["state_alpha"]
        if st not in STATE_CENTROIDS:
            continue
        lat, lon = STATE_CENTROIDS[st]
        val = row.get(lbl_col)
        lats.append(lat)
        lons.append(lon)
        labels.append(lbl_fmt(val) if pd.notna(val) else "")
        hovers.append(row["hover"])

    fig.add_trace(go.Scattergeo(
        lat=lats, lon=lons,
        text=labels,
        hovertext=hovers,
        hovertemplate="%{hovertext}<extra></extra>",
        mode="text",
        textfont=dict(size=12, color="white", family="Arial Black"),
        showlegend=False,
    ))

    fig.update_layout(
        geo=dict(
            scope="usa",
            showlakes=False,
            bgcolor="white",
            landcolor="#d4dbe3",
            subunitcolor="#ffffff",
            subunitwidth=1.2,
            countrycolor="#cccccc",
        ),
        paper_bgcolor="white",
        margin=dict(l=0, r=0, t=48, b=10),
        height=500,
        dragmode=False,
    )
    _wm_map(fig)
    return fig


def build_stacked_area(
    raw_df: pd.DataFrame,
    state_alpha: str,
    state_name: str,
    usda_year: int,
    commodity_label: str = "Winter Wheat",
    cutoff_week: pd.Timestamp | None = None,
) -> go.Figure:
    """
    Stacked area chart of all 5 condition bands for a single state and USDA year.
    X-axis: calendar week of year.  Y-axis: stacked % summing to ~100.
    Shows weeks from the first week of February up to cutoff_week (or latest available).
    """
    # First week of Feb for the crop year
    # (Feb belongs to the same calendar year as the harvest year for Jan-Jul)
    feb_start = pd.Timestamp(year=usda_year, month=2, day=1)

    # Filter to state, year, Feb+
    df = raw_df[
        (raw_df["state_alpha"] == state_alpha) &
        (raw_df["year"] == usda_year) &
        (raw_df["week_ending"] >= feb_start)
    ].copy()

    # Apply cutoff
    if cutoff_week is not None:
        df = df[df["week_ending"] <= cutoff_week]

    if df.empty:
        return go.Figure()

    # Pivot: one row per week, one column per condition
    pivot = (
        df.pivot_table(index="week_ending", columns="condition", values="Value", aggfunc="sum")
        .sort_index()
        .reset_index()
    )

    # Formatted hover label for each week
    pivot["week_lbl"] = pivot["week_ending"].apply(
        lambda d: f"Wk ending {d.strftime('%b')} {d.day}, {d.year}"
    )

    # Condition order bottom → top (plotly stacks in trace order)
    STACK_ORDER = ["VERY POOR", "POOR", "FAIR", "GOOD", "EXCELLENT"]
    STACK_COLORS = {
        "VERY POOR": "#fee08b",
        "POOR":      "#d9ef8b",
        "FAIR":      "#a6d96a",
        "GOOD":      "#66bd63",
        "EXCELLENT": "#1a9850",
    }

    mkt_lbl = mkt_label(usda_year)
    fig = go.Figure()

    # Use actual week_ending Timestamps on x-axis so Plotly spaces weeks correctly
    x_dates = pivot["week_ending"].tolist()

    for cond in STACK_ORDER:
        y_vals = pivot[cond].fillna(0).tolist() if cond in pivot.columns else [0] * len(pivot)
        fig.add_trace(go.Scatter(
            x=x_dates,
            y=y_vals,
            name=cond,
            stackgroup="one",
            groupnorm="",          # raw %, not normalised (sum should be ~100)
            mode="none",
            fillcolor=STACK_COLORS[cond],
            line=dict(width=0.5, color=STACK_COLORS[cond]),
            customdata=pivot["week_lbl"].tolist(),
            hovertemplate=(
                f"<b>{cond}</b>: %{{y:.0f}}%<br>"
                "%{customdata}<extra></extra>"
            ),
        ))

    fig.update_layout(
        title=dict(
            text=(
                f"Stacked Area Chart for {commodity_label.upper()} "
                f"in {state_name.upper()} for {mkt_lbl}"
            ),
            font=dict(size=13, color="#66bd63"),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(
            title="Week Ending",
            type="date",
            tickformat="%b %d",
            dtick=604800000,   # 7 days in milliseconds — one tick per week
            showgrid=True,
            gridcolor=DM_BORDER,
            color=DM_MUTED,
            tickfont=dict(color=DM_MUTED),
            title_font=dict(color=DM_MUTED),
        ),
        yaxis=dict(
            title="Percent",
            range=[0, 100],
            ticksuffix="%",
            showgrid=True,
            gridcolor=DM_BORDER,
            color=DM_MUTED,
            tickfont=dict(color=DM_MUTED),
            title_font=dict(color=DM_MUTED),
        ),
        paper_bgcolor=DM_BG,
        plot_bgcolor=DM_SURFACE2,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1.0,
            xanchor="left",
            x=1.01,
            bgcolor=DM_SURFACE,
            bordercolor=DM_BORDER,
            borderwidth=1,
            traceorder="reversed",
            font=dict(size=11, color=DM_TEXT),
        ),
        margin=dict(l=10, r=130, t=55, b=10),
        height=350,
        hovermode="x unified",
    )
    return fig


# st.set_page_config removed — the JSA Admin Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

st.markdown(f"""
<style>
  /* ── App background ── */
  .stApp, .main, [data-testid="stAppViewContainer"] {{
    background-color: {DM_BG} !important;
  }}
  /* Catch all inner blocks */
  .block-container {{ background-color: {DM_BG} !important; }}

  /* ── Sidebar ── */
  [data-testid="stSidebar"] {{
    background-color: {DM_SURFACE} !important;
    border-right: 1px solid {DM_BORDER};
  }}
  [data-testid="stSidebar"] label,
  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] .stMarkdown,
  [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] div {{
    color: {DM_TEXT} !important;
  }}
  [data-testid="stSidebar"] hr {{ border-color: {DM_BORDER}; }}

  /* Selectbox / radio on dark */
  [data-testid="stSidebar"] .stSelectbox > div > div,
  [data-testid="stSidebar"] .stRadio > div {{
    background-color: {DM_SURFACE2} !important;
    color: {DM_TEXT} !important;
  }}

  /* Global text */
  html, body, p, span, div, label, h1, h2, h3, h4, h5 {{
    color: {DM_TEXT};
  }}
  .stMarkdown, .stCaption, .stText {{ color: {DM_MUTED} !important; }}

  /* ── Header ── */
  .dash-header {{
    background: {DM_SURFACE};
    border-bottom: 3px solid {JPSI_BLUE};
    padding: 20px 28px 16px 28px;
    margin: -4rem -4rem 1.5rem -4rem;
    display: flex;
    align-items: center;
    gap: 20px;
  }}
  .dash-header-logo {{ flex-shrink: 0; }}
  .dash-header-logo img {{ height: 56px; display: block; }}
  .dash-header-text {{ flex: 1; text-align: center; }}
  .dash-header-text h1 {{
    color: {DM_TEXT} !important;
    margin: 0;
    font-size: 1.65rem;
    font-weight: 700;
    letter-spacing: -0.01em;
  }}
  .dash-header-text p {{
    color: {DM_MUTED} !important;
    margin: 3px 0 0 0;
    font-size: 0.82rem;
  }}

  /* ── Column containers — prevent Streamlit dark override ── */
  [data-testid="stColumn"] > div,
  [data-testid="column"] > div {{
    background-color: transparent !important;
  }}

  /* ── KPI cards ── */
  .kpi-card {{
    background: {DM_SURFACE} !important;
    border-radius: 8px;
    padding: 20px 16px 14px 16px;
    text-align: center;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    border-top: 4px solid {JPSI_BLUE};
  }}
  .kpi-main  {{ font-size: 2rem; font-weight: 700; color: {DM_TEXT} !important; line-height: 1.1; }}
  .kpi-label {{ font-size: 0.72rem; color: {DM_MUTED} !important; text-transform: uppercase; letter-spacing: .06em; margin-top: 6px; }}

  /* HRW index cards — amber accent */
  .kpi-card-hrw {{
    background: {DM_SURFACE} !important;
    border-radius: 8px;
    padding: 20px 16px 14px 16px;
    text-align: center;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    border-top: 4px solid #f59e0b;
  }}
  /* SRW index cards — emerald accent */
  .kpi-card-srw {{
    background: {DM_SURFACE} !important;
    border-radius: 8px;
    padding: 20px 16px 14px 16px;
    text-align: center;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    border-top: 4px solid #10b981;
  }}
  /* White wheat index cards — indigo accent */
  .kpi-card-white {{
    background: {DM_SURFACE} !important;
    border-radius: 8px;
    padding: 20px 16px 14px 16px;
    text-align: center;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    border-top: 4px solid #818cf8;
  }}

  /* ── Section headers ── */
  .sec-hdr {{
    font-size: 1.05rem; font-weight: 600; color: {DM_TEXT};
    border-left: 4px solid {JPSI_BLUE};
    padding-left: 10px;
    margin: 1.6rem 0 0.8rem 0;
  }}

  /* ── Season note ── */
  .season-note {{
    background: #fefce8;
    border-left: 4px solid #f59e0b;
    padding: 10px 14px;
    border-radius: 4px;
    font-size: 0.85rem;
    color: {DM_MUTED};
    margin-bottom: 0.5rem;
  }}

  /* ── Table note ── */
  .table-note {{
    font-size: 0.78rem;
    color: {DM_MUTED};
    margin-bottom: 0.4rem;
  }}

  /* ── Streamlit dataframe wrapper ── */
  [data-testid="stDataFrame"] {{ background-color: {DM_SURFACE} !important; }}

  #MainMenu, footer, header {{ visibility: hidden; }}

  /* ── Hide sidebar entirely — filters moved to top bar ── */
  [data-testid="stSidebar"],
  [data-testid="stSidebarCollapsedControl"],
  [data-testid="stSidebarCollapseButton"] {{
    display: none !important;
  }}

  /* ── Top filter bar ── */
  .filter-bar {{
    background: {DM_SURFACE};
    border: 1px solid {DM_BORDER};
    border-top: 3px solid #0693e3;
    border-radius: 8px;
    padding: 12px 20px 8px 20px;
    margin-bottom: 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,.06);
  }}
  /* Bold blue labels */
  .filter-bar label,
  .filter-bar .stSelectbox label,
  .filter-bar .stButton label {{
    font-size: 11px !important;
    font-weight: 700 !important;
    color: #0693e3 !important;
    text-transform: uppercase !important;
    letter-spacing: .07em !important;
    margin-bottom: 3px !important;
  }}
  /* Dropdown input boxes */
  .filter-bar .stSelectbox > div > div {{
    background: {DM_BG} !important;
    border: 1px solid {DM_BORDER} !important;
    border-radius: 6px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: {DM_TEXT} !important;
    transition: border-color .15s !important;
  }}
  .filter-bar .stSelectbox > div > div:focus-within,
  .filter-bar .stSelectbox > div > div:hover {{
    border-color: #0693e3 !important;
    box-shadow: 0 0 0 2px rgba(6,147,227,.15) !important;
  }}
  /* Refresh button alignment */
  .filter-bar .stButton > button {{
    margin-top: 22px;
    border-radius: 6px !important;
    border: 1px solid {DM_BORDER} !important;
    background: {DM_BG} !important;
    color: {DM_TEXT} !important;
    font-size: 16px !important;
    padding: 4px 10px !important;
    transition: border-color .15s, background .15s !important;
  }}
  .filter-bar .stButton > button:hover {{
    border-color: #0693e3 !important;
    background: #f0f8ff !important;
  }}
</style>
""", unsafe_allow_html=True)

# ── Date helper ────────────────────────────────────────────────────────────────
def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{['th','st','nd','rd','th'][min(n % 10, 4)]}"

_today_str = datetime.now().strftime(f"%B {_ordinal(datetime.now().day)}, %Y")

# ── Logo helper — reads logo.png from the same folder as app.py ────────────────
def _logo_data_uri() -> str:
    """Return a base64 data URI for the logo file, or empty string if not found."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Try common filenames in order
    for fname in ("logo.png", "logo.jpg", "Picture1.png", "Picture1.jpg", "Picture 1.png", "Picture 1.jpg"):
        logo_path = os.path.join(base_dir, fname)
        if os.path.exists(logo_path):
            ext  = os.path.splitext(fname)[1].lower().lstrip(".")
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
            with open(logo_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            return f"data:{mime};base64,{encoded}"
    return ""

_logo_uri = _logo_data_uri()

def _chart_logo_data_uri() -> str:
    """Return base64 data URI for the full JSA logo used on line/scatter/trendline charts."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "JSA Logo.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    return _logo_uri   # fall back to main logo

_chart_logo_uri = _chart_logo_data_uri()

def _map_logo_data_uri() -> str:
    """Return base64 data URI for the state-map watermark logo (monogram)."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fname = "Transparent Smal logo.png"
    path  = os.path.join(base_dir, fname)
    if os.path.exists(path):
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    return _logo_uri   # fall back to main logo

_map_logo_uri = _map_logo_data_uri()

def _50yr_logo_data_uri() -> str:
    """Return base64 data URI for the 50-year anniversary logo (table watermark)."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "50 Year logo JSA.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    return _logo_uri   # fall back to main logo

_50yr_logo_uri = _50yr_logo_data_uri()

# Inject table watermark CSS now that the logo URI is known.
# Uses ::after pseudo-element so it overlays every st.dataframe/st.table
# without modifying individual call sites.
if _50yr_logo_uri:
    st.markdown(f"""
<style>
  div[data-testid="stDataFrame"] {{
    position: relative !important;
  }}
  div[data-testid="stDataFrame"]::after {{
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background-image: url("{_50yr_logo_uri}");
    background-size: 220px;
    background-repeat: no-repeat;
    background-position: center center;
    opacity: 0.055;
    pointer-events: none;
    z-index: 9999;
  }}
</style>
""", unsafe_allow_html=True)

def _wm(fig, x=0.985, y=0.015, sizex=0.18, sizey=0.18, opacity=0.07):
    """Add JSA logo watermark (bottom-right) to any Plotly figure."""
    if _logo_uri:
        fig.add_layout_image(
            source=_logo_uri,
            xref="paper", yref="paper",
            x=x, y=y,
            xanchor="right", yanchor="bottom",
            sizex=sizex, sizey=sizey,
            opacity=opacity,
            layer="above",
        )

def _wm_center(fig, opacity=0.07):
    """Add full JSA logo as a large centered background watermark."""
    src = _chart_logo_uri or _logo_uri
    if src:
        fig.add_layout_image(
            source=src,
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            xanchor="center", yanchor="middle",
            sizex=0.55, sizey=0.55,
            opacity=opacity,
            layer="below",
        )

def _wm_map(fig, opacity=0.20):
    """Add JSA monogram watermark centered in the gap between map and colorbar."""
    if _map_logo_uri:
        fig.add_layout_image(
            source=_map_logo_uri,
            xref="paper", yref="paper",
            x=0.93, y=0.5,
            xanchor="center", yanchor="middle",
            sizex=0.28, sizey=0.28,
            opacity=opacity,
            layer="above",
        )

def _tbl_wm():
    """Render JSA logo watermark overlaid on the table just above."""
    if _logo_uri:
        st.markdown(
            f'<div style="text-align:right;margin-top:-48px;margin-right:28px;'
            f'position:relative;z-index:100;pointer-events:none">'
            f'<img src="{_logo_uri}" style="height:36px;opacity:0.10"/></div>',
            unsafe_allow_html=True,
        )

_logo_html = (
    f'<img src="{_logo_uri}" alt="JSA Logo" style="height:56px;display:block;" />'
    if _logo_uri else
    f'<div style="font-size:1.1rem;font-weight:700;color:{DM_TEXT};font-family:Georgia,serif;">'
    f'John Stewart<br><span style="font-size:0.75rem;letter-spacing:.08em;color:{DM_MUTED}">AND ASSOCIATES</span></div>'
)

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="dash-header">
  <div class="dash-header-logo">
    {_logo_html}
  </div>
  <div class="dash-header-text">
    <h1>JSA Crop Conditions and Yield Model</h1>
    <p>Updated {_today_str} &nbsp;|&nbsp; Data: USDA NASS Quick Stats</p>
  </div>
  <div style="width:56px"></div><!-- spacer to centre the title -->
</div>
""", unsafe_allow_html=True)

# ── Top filter bar ─────────────────────────────────────────────────────────────
st.markdown('<div class="filter-bar">', unsafe_allow_html=True)

_fc1, _fc2, _fc3, _fc4, _fc5, _fc6, _fc7, _fc8 = st.columns(
    [1.3, 1.3, 1.3, 1.3, 1.6, 1.0, 1.1, 0.55]
)

with _fc1:
    commodity_label = st.selectbox("Commodity", list(COMMODITIES.keys()))
    commodity_cfg   = COMMODITIES[commodity_label]

with _fc2:
    usda_years    = available_usda_years(n=20)
    mkt_labels    = [mkt_label(y) for y in usda_years]
    default_label = mkt_label(default_usda_year())
    default_idx   = mkt_labels.index(default_label) if default_label in mkt_labels else 0
    selected_mkt  = st.selectbox("Marketing Year", mkt_labels, index=default_idx)
    sel_usda_yr   = usda_year(selected_mkt)

with _fc3:
    # Placeholder — filled after data loads so available weeks are known
    _week_slot = st.empty()

with _fc4:
    compare_mkt = st.selectbox(
        "Compare Year",
        ["— None —"] + mkt_labels,
        index=0,
    )
    cmp_usda_yr = None if compare_mkt == "— None —" else usda_year(compare_mkt)

with _fc5:
    condition = st.selectbox(
        "Condition",
        ["Good + Excellent", "Fair", "Poor + Very Poor", "JSA Index"],
    )

with _fc6:
    if commodity_cfg.get("has_classes", True):
        wheat_class = st.selectbox("Wheat Class", list(WHEAT_CLASSES.keys()), index=0)
    else:
        wheat_class = "All Winter Wheat"
        st.empty()

with _fc7:
    # Placeholder — filled after data loads with states that have data
    _state_dd_slot = st.empty()

with _fc8:
    if st.button("🔄", help="Refresh data from USDA NASS (use after Monday ~3 PM ET when USDA posts weekly conditions)"):
        st.cache_data.clear()
        st.rerun()

st.markdown('</div>', unsafe_allow_html=True)

# ── Load Data ──────────────────────────────────────────────────────────────────
# Fetch full NASS history back to 1986 plus the selected year
fetch_usda_years = list(range(1986, sel_usda_yr + 1))
if cmp_usda_yr and cmp_usda_yr not in fetch_usda_years:
    fetch_usda_years.append(cmp_usda_yr)

with st.spinner("Fetching USDA crop condition data…"):
    try:
        raw_df = fetch_conditions(
            commodity_cfg["commodity_desc"],
            commodity_cfg["class_desc"],
            tuple(sorted(fetch_usda_years)),
        )
    except RuntimeError as _fetch_err:
        st.error(
            f"USDA API returned an error for **{selected_commodity}** conditions data. "
            f"This is usually a temporary outage — try refreshing in a few minutes.\n\n"
            f"**Details:** {_fetch_err}"
        )
        st.stop()

if raw_df.empty:
    st.error(
        f"No condition data found for **{selected_commodity}**. "
        "The USDA API may be temporarily unavailable, or data for this commodity "
        "has not yet been published. Try refreshing in a few minutes."
    )
    st.stop()

ge_df   = good_excellent(raw_df)
pv_df   = poor_very_poor(raw_df)
fair_df = fair_condition(raw_df)
jsa_df  = jsa_index(raw_df)

# ── Auto-fallback: if selected year has no data yet, use most recent available ─
_avail_yrs = sorted(ge_df["year"].unique(), reverse=True)
if _avail_yrs and sel_usda_yr not in ge_df["year"].values:
    _fallback_yr = int(_avail_yrs[0])
    st.info(
        f"No condition data yet for **{mkt_label(sel_usda_yr)}** — "
        f"showing **{mkt_label(_fallback_yr)}** (most recent available)."
    )
    sel_usda_yr  = _fallback_yr
    selected_mkt = mkt_label(sel_usda_yr)

# ── Class weights ─────────────────────────────────────────────────────────────
# HRW:   WINTER wheat production by state (fixed 10-yr avg) — backtest confirmed best.
# SRW:   SOFT RED WINTER class-specific production (year-specific) — backtest best.
# White: SOFT WHITE class-specific production (year-specific) — both approaches equal,
#        class-specific used for consistency with SRW and to reduce overstatement.
# Class-specific production (= class acres × class yield) is the correct weighting
# basis — using total WINTER wheat production/acres overstates SRW and White because
# high-yielding core states dominate WINTER totals more than their class share.
# ── Year ranges — computed once after auto-fallback has set final sel_usda_yr ──
_prod_years     = tuple(range(max(1990, sel_usda_yr - 14), sel_usda_yr))
_acres_years    = tuple(range(1985, sel_usda_yr))
_srw_years_tup  = tuple(range(1985, sel_usda_yr))
_yield_years    = tuple(range(1985, sel_usda_yr + 1))
_prod_tab_years = tuple(range(1985, sel_usda_yr + 1))   # identical to _yield_years; kept named for clarity

_has_cls    = commodity_cfg.get("has_classes", True)
_c_desc     = commodity_cfg["commodity_desc"]
_cl_desc    = commodity_cfg["class_desc"]
_prod_unit  = commodity_cfg.get("production_unit_desc", "BU")
_yield_unit = commodity_cfg.get("yield_unit_desc")       # None for soybeans; filtered post-fetch

# ── Single parallel burst — all independent NASS fetches ──────────────────────
# Previously four sequential spinner blocks (class weights → yields → class yields
# → production tab). All are data-independent after fetch_conditions returns, so
# running them concurrently cuts cold-start by ~15 s for Winter Wheat.
with st.spinner("Loading USDA historical data…"):
    with ThreadPoolExecutor(max_workers=16) as _pool:
        # Annual yields — all commodities
        _f_yields      = _pool.submit(fetch_yields, _c_desc, _cl_desc, _yield_years, _yield_unit)
        _f_sep1_stocks = _pool.submit(fetch_first_of_sep_stocks, _c_desc, _prod_tab_years)
        _f_jun1_stocks = _pool.submit(fetch_quarterly_stocks, _c_desc, "FIRST OF JUN", _prod_tab_years)
        _f_psd_es      = _pool.submit(fetch_psd_ending_stocks, _c_desc, sel_usda_yr - 1)

        if _has_cls:
            # Class-weight production data
            _f_hrw_prod   = _pool.submit(fetch_hrw_production,        _prod_years)
            _f_ww_acres   = _pool.submit(fetch_ww_state_acres,        _acres_years)
            _f_srw_prod   = _pool.submit(fetch_srw_class_production,  _srw_years_tup)
            _f_white_prod = _pool.submit(fetch_white_class_production, _srw_years_tup)
            # Class-specific yields (HRW / SRW / Soft White)
            _f_hrw_cy    = _pool.submit(fetch_hrw_class_yields,  _yield_years)
            _f_srw_cy    = _pool.submit(fetch_srw_class_yields,  _yield_years)
            _f_white_cy  = _pool.submit(fetch_soft_white_yields, _yield_years)
            # Production tab — different year tuples from class-weight fetches above
            _f_pt_prod   = _pool.submit(fetch_hrw_production,     _prod_tab_years)
            _f_pt_acres  = _pool.submit(fetch_ww_state_acres,     _prod_tab_years)
            _f_pt_natl   = _pool.submit(fetch_ww_national_totals, _prod_tab_years)
            # Planted acres — both current and prior year submitted in parallel;
            # tab picks whichever has data (current preferred).
            # Also warms the Abandonment tab cache since _ab_years == _prod_tab_years.
            _f_planted_cur  = _pool.submit(fetch_planted_acres_for_year, sel_usda_yr)
            _f_planted_ly   = _pool.submit(fetch_planted_acres_for_year, sel_usda_yr - 1)
            _f_hrw_natl_ac  = _pool.submit(fetch_class_national_acres, "HRW",   _prod_tab_years)
            _f_srw_natl_ac  = _pool.submit(fetch_class_national_acres, "SRW",   _prod_tab_years)
            _f_wht_natl_ac  = _pool.submit(fetch_class_national_acres, "White", _prod_tab_years)
        else:
            # State-share production (non-wheat; short window for weighting)
            _f_com_prod  = _pool.submit(fetch_commodity_production, _c_desc, _cl_desc,
                                        _prod_years, _prod_unit)
            # Production tab (non-wheat; full history)
            _f_pt_prod_c = _pool.submit(fetch_commodity_production, _c_desc, _cl_desc,
                                        _prod_tab_years, _prod_unit)
            _f_pt_acr_c  = _pool.submit(fetch_commodity_acres,     _c_desc, _cl_desc,
                                        _prod_tab_years)

# ── Collect fetch results ──────────────────────────────────────────────────────
_yield_raw      = _f_yields.result()
_sep1_stocks_df = _f_sep1_stocks.result()
_jun1_stocks_df = _f_jun1_stocks.result()
_psd_es_bu      = _f_psd_es.result()

if _has_cls:
    _hrw_prod_df         = _f_hrw_prod.result()
    _ww_state_acres      = _f_ww_acres.result()
    _srw_prod_df         = _f_srw_prod.result()
    _white_prod_df       = _f_white_prod.result()
    _hrw_class_yield_df  = _f_hrw_cy.result()
    _srw_class_yield_df  = _f_srw_cy.result()
    _soft_white_yield_df = _f_white_cy.result()
    _prod_df_for_shares  = _hrw_prod_df
    # Production tab results
    _prod_tab_prod_df     = _f_pt_prod.result()
    _prod_tab_acres_df    = _f_pt_acres.result()
    _prod_tab_national_df = _f_pt_natl.result()
    _prod_tab_yield_df    = pd.DataFrame()
    # Pre-fetched Production/Abandonment tab data
    _pf_planted_cur  = _f_planted_cur.result()
    _pf_planted_ly   = _f_planted_ly.result()
    _pf_hrw_natl_ac  = _f_hrw_natl_ac.result()
    _pf_srw_natl_ac  = _f_srw_natl_ac.result()
    _pf_wht_natl_ac  = _f_wht_natl_ac.result()

    # HRW: WINTER production-weighted fixed average (confirmed best by backtest)
    _dynamic_hrw_weights = compute_hrw_weights(_hrw_prod_df, n_years=10)

    # SRW: class-specific production weighted (fixed avg for conditions index;
    #      year-specific built inline when constructing _yield_full below)
    _dynamic_srw_weights = (
        compute_weights_from_class_production(_srw_prod_df, SRW_WEIGHTS, n_years=10)
        if not _srw_prod_df.empty
        else compute_class_weights_from_acres(_ww_state_acres, "SRW — Soft Red Winter", SRW_WEIGHTS, n_years=10)
    )

    # White: class-specific production weighted (fixed avg for conditions index)
    _dynamic_white_weights = (
        compute_weights_from_class_production(_white_prod_df, WHITE_WEIGHTS, n_years=10)
        if not _white_prod_df.empty
        else compute_class_weights_from_acres(_ww_state_acres, "White Winter", WHITE_WEIGHTS, n_years=10)
    )

    # Year-specific production lookups for SRW and White yield series
    _srw_yr_prod_lookup   = compute_year_specific_weights_from_class_production(_srw_prod_df)
    _white_yr_prod_lookup = compute_year_specific_weights_from_class_production(_white_prod_df)
else:
    _hrw_prod_df = _srw_prod_df = _white_prod_df = pd.DataFrame()
    _hrw_class_yield_df = _srw_class_yield_df = _soft_white_yield_df = pd.DataFrame()
    _srw_yr_prod_lookup = _white_yr_prod_lookup = {}
    _dynamic_hrw_weights = _dynamic_srw_weights = _dynamic_white_weights = {}
    _prod_df_for_shares = _f_com_prod.result()
    # Production tab results
    _prod_tab_prod_df     = _f_pt_prod_c.result()
    _prod_tab_acres_df    = _f_pt_acr_c.result()
    _prod_tab_yield_df    = _yield_raw.copy()    # same year range as _yield_raw; reuse
    _prod_tab_national_df = pd.DataFrame()
    _pf_planted_cur = _pf_planted_ly = pd.DataFrame()
    _pf_hrw_natl_ac = _pf_srw_natl_ac = _pf_wht_natl_ac = pd.DataFrame()

# ── Production share per state (avg across available years) ───────────────────
def _compute_production_shares(prod_df: pd.DataFrame, min_share: float = 0.01) -> tuple[set, dict]:
    """Returns (significant_states set, {state_alpha: share_pct} dict)."""
    if prod_df.empty:
        return set(), {}
    avg   = prod_df.groupby("state_alpha")["production_bu"].mean()
    total = avg.sum()
    if total == 0:
        return set(), {}
    shares     = avg / total
    sig_states = set(shares[shares >= min_share].index)
    share_map  = {st: round(float(pct) * 100, 1) for st, pct in shares.items()}
    return sig_states, share_map

_significant_states, _state_share_pct = _compute_production_shares(_prod_df_for_shares)

# If production data is unavailable (API failure), fall back to the static HRW state set
# rather than silently showing ALL states (empty set is falsy → filter bypassed).
if not _significant_states and commodity_cfg.get("has_classes", True):
    _significant_states = set(HRW_WEIGHTS.keys())   # KS OK TX CO NE SD MT WY — excludes tiny NM

# _hrw_nass_us is populated from _yield_raw (US row) after the yield fetch below.
# NASS does not publish a standalone HRW national yield in Quick Stats;
# the US Winter Wheat yield is the closest available benchmark.
_hrw_nass_us     = pd.DataFrame()
_hrw_weighted_df = pd.DataFrame()
_hrw_nass_td     = None
_hrw_wtd_td      = None

# ── Class state sets (used for dynamic weight functions) ──────────────────────
_HRW_STATES   = WHEAT_CLASSES["HRW — Hard Red Winter"]
_SRW_STATES   = WHEAT_CLASSES["SRW — Soft Red Winter"]
_WHITE_STATES = WHEAT_CLASSES["White Winter"]

if not _yield_raw.empty:
    if commodity_cfg.get("has_classes", True):
        # Convert class-specific production dfs to "acres-equivalent" format so
        # _class_weighted_yield_dynamic can use them directly.
        # Σ(yield × production) / Σ(production) = production-weighted yield = NASS method.
        def _prod_to_acres_fmt(prod_df: pd.DataFrame) -> pd.DataFrame:
            if prod_df.empty:
                return pd.DataFrame()
            return (prod_df.rename(columns={"production_bu": "harvested_ac",
                                            "state_alpha":   "state"})
                           [["year", "state", "harvested_ac"]])

        _srw_wt_df   = _prod_to_acres_fmt(_srw_prod_df)
        _white_wt_df = _prod_to_acres_fmt(_white_prod_df)

        _yield_full = pd.concat([
            _yield_raw,
            # HRW: FIXED WINTER-production weights (backtest confirmed lowest MAE)
            _class_weighted_yield_with_override(
                _yield_raw, _hrw_class_yield_df, _dynamic_hrw_weights, "HRW", "HRW Index"),
            # SRW: YEAR-SPECIFIC class-production weights (backtest best; class-specific
            #      production eliminates overstatement from WINTER-total weighting)
            _class_weighted_yield_with_override_dynamic(
                _yield_raw, _srw_class_yield_df,
                _srw_wt_df if not _srw_wt_df.empty else _ww_state_acres,
                _SRW_STATES, _dynamic_srw_weights, "SRW", "SRW Index"),
            # White: YEAR-SPECIFIC class-production weights (same reason as SRW)
            _class_weighted_yield_with_override_dynamic(
                _yield_raw, _soft_white_yield_df,
                _white_wt_df if not _white_wt_df.empty else _ww_state_acres,
                _WHITE_STATES, _dynamic_white_weights, "White", "White Index"),
        ], ignore_index=True)
    else:
        _yield_full = _yield_raw.copy()
    _trend_data = compute_yield_trends(_yield_full, start_year=1985)
    _yield_lookup: dict[str, dict] = {}
    for _sk in _trend_data.keys():
        _yield_lookup[_sk] = {}
        _td_ref = _trend_data[_sk]
        for _, _lr in _yield_full[_yield_full["state_alpha"] == _sk].iterrows():
            _lyr  = int(_lr["year"])
            _lact = float(_lr["yield_bu_ac"])
            _ltrnd = _trend_at(_td_ref, _lyr)
            _yield_lookup[_sk][_lyr] = {
                "yield": _lact,
                "trend": _ltrnd,
                "dev":   _dev_pct(_lact, _ltrnd),
            }
else:
    _yield_full  = pd.DataFrame()
    _trend_data  = {}
    _yield_lookup: dict[str, dict] = {"US": {}}


# ── Active JSA condition weights ───────────────────────────────────────────────
# Default: equal-spaced (VP=0 P=25 F=50 G=75 E=100).
# Experimental toggle in sidebar enables empirically-calibrated weights derived
# from OLS regression of yield deviations on condition band shares.
_active_cw = CONDITION_WEIGHTS

# ── Fixed-weight class yields — computed in parallel for backtest comparison ──
# These use the traditional fixed 10-yr average weights, stored separately so
# we can display both approaches side-by-side in the backtest section and let
# the data decide which has lower average error vs NASS published class yields.
_hrw_fixed_df   = pd.DataFrame()
_srw_fixed_df   = pd.DataFrame()
_white_fixed_df = pd.DataFrame()
if commodity_cfg.get("has_classes", True) and not _yield_raw.empty:
    _hrw_fixed_df   = _class_weighted_yield_with_override(
        _yield_raw, _hrw_class_yield_df, _dynamic_hrw_weights, "HRW_fixed", "HRW Fixed Wt")
    _srw_fixed_df   = _class_weighted_yield_with_override(
        _yield_raw, _srw_class_yield_df, _dynamic_srw_weights, "SRW_fixed", "SRW Fixed Wt")
    _wh_fixed_tmp   = _white_weighted_yield(_yield_raw, _soft_white_yield_df, _dynamic_white_weights)
    if not _wh_fixed_tmp.empty:
        _white_fixed_df = _wh_fixed_tmp.assign(state_alpha="White_fixed", state_name="White Fixed Wt")

# ── Build HRW weighted yield + trendlines — Winter Wheat only ─────────────────
if commodity_cfg.get("has_classes", True):
    if not _yield_raw.empty:
        _hrw_weighted_df = hrw_weighted_yield(_yield_raw, weights=_dynamic_hrw_weights)
        if not _hrw_weighted_df.empty:
            _hrw_wtd_td_dict = compute_yield_trends(_hrw_weighted_df, start_year=1985)
            _hrw_wtd_td      = _hrw_wtd_td_dict.get("HRW")
        # Use NASS US Winter Wheat yield as benchmark (closest available from Quick Stats)
        _us_rows = _yield_raw[_yield_raw["state_alpha"] == "US"].copy()
        if not _us_rows.empty:
            _hrw_nass_us              = _us_rows.copy()
            _hrw_nass_us["state_name"] = "NASS US Winter Wheat"
            _hrw_nass_td_src           = _hrw_nass_us.assign(state_alpha="NASS_HRW")
            _hrw_nass_td_dict          = compute_yield_trends(_hrw_nass_td_src, start_year=1985)
            _hrw_nass_td               = _hrw_nass_td_dict.get("NASS_HRW")

# ── Backtest benchmarks — best available for each class ───────────────────────
# HRW: NASS doesn't publish state-level or national HRW yields — use US Winter Wheat
#      as the closest available proxy (already in _hrw_nass_us).
# SRW: NASS publishes state-level SOFT RED WINTER yields; compute national equivalent
#      using year-specific state acres — same formula NASS uses internally.
# White: same approach using NASS SOFT WHITE state yields for WA/OR/ID.
_nass_hrw_national_df   = pd.DataFrame()
_nass_srw_national_df   = pd.DataFrame()
_nass_white_national_df = pd.DataFrame()
if commodity_cfg.get("has_classes", True):
    # All three classes: use USDA official final yields from ERS Wheat by Class.
    # These are authoritative — NASS API does not expose national class yields.
    # Update each dict in November when NASS publishes the Small Grains Summary.
    def _usda_dict_to_df(d: dict) -> pd.DataFrame:
        return pd.DataFrame([{"year": yr, "nass_yield": yld} for yr, yld in d.items()])

    _nass_hrw_national_df   = _usda_dict_to_df(USDA_HRW_YIELD_FINAL)
    _nass_srw_national_df   = _usda_dict_to_df(USDA_SRW_YIELD_FINAL)
    _nass_white_national_df = _usda_dict_to_df(USDA_WHITE_YIELD_FINAL)

# ── Fill the week placeholder now that data is loaded ──────────────────────────
# Collect all Feb+ weeks from raw_df (state + US rows)
_yr_weeks = sorted(
    raw_df[
        (raw_df["year"] == sel_usda_yr) &
        (raw_df["week_ending"].dt.month >= commodity_cfg.get("season_start_month", 2))
    ]["week_ending"].unique()
)

if _yr_weeks:
    _week_labels      = [f"{pd.Timestamp(w).strftime('%b %d, %Y')}  (Wk {int(pd.Timestamp(w).isocalendar().week)})" for w in _yr_weeks]
    _most_recent_lbl  = _week_labels[-1]

    # Auto-advance to the newest week whenever data is refreshed.
    # Compares against the last-known latest label so that a user selecting an
    # older week is not overridden — only a genuinely new week triggers a reset.
    if st.session_state.get("_latest_week_label") != _most_recent_lbl:
        st.session_state["mkt_week_sel"]       = _most_recent_lbl
        st.session_state["_latest_week_label"] = _most_recent_lbl

    with _week_slot.container():
        _sel_week_label = st.selectbox(
            "Marketing Week",
            _week_labels,
            index=len(_week_labels) - 1,   # default = most recent
            key="mkt_week_sel",
        )
    sel_week = _yr_weeks[_week_labels.index(_sel_week_label)]
else:
    sel_week = None

# ── Comparison table ───────────────────────────────────────────────────────────
result, latest_week = build_comparison_table(ge_df, pv_df, fair_df, jsa_df, sel_usda_yr, target_week=sel_week)

# Default to the most recent data week when the sidebar has no week selected
# (e.g. between seasons, early-season, or first page load with empty _yr_weeks).
if sel_week is None and pd.notna(latest_week):
    sel_week = latest_week

if result.empty:
    # Could be between seasons (Aug–Oct) or very early in season
    now = datetime.now()
    if 8 <= now.month <= 10:
        msg = (f"No condition reports available yet for the {selected_mkt} marketing year. "
               "Winter wheat reporting typically begins in November.")
    else:
        msg = f"No data found for {selected_mkt}. The season may not have started yet."
    st.markdown(f'<div class="season-note">📋 {msg}</div>', unsafe_allow_html=True)
    st.stop()

# ── Apply wheat class filter ───────────────────────────────────────────────────
_class_states = WHEAT_CLASSES[wheat_class]
if _class_states is not None:
    result = result[result["state_alpha"].isin(_class_states)].reset_index(drop=True)

# Save map_result before the 1% production filter (map shows all USDA-reported states)
map_result = result.copy()

# ── Drop states below 1% of US winter wheat production (tables only) ──────────
if _significant_states:
    result = result[result["state_alpha"].isin(_significant_states)].reset_index(drop=True)

# ── Fill state dropdown placeholder ────────────────────────────────────────────
# Build from commodity's all_state_alphas (hardcoded historical list) merged with
# any states in raw_df — avoids fetching all historical states into memory just
# to populate the dropdown.  States that stopped reporting show in the list but
# will display "no data" when selected.
_ALPHA_TO_NAME = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia",
    "HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa",
    "KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland",
    "MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi",
    "MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire",
    "NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina",
    "ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania",
    "RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee",
    "TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington",
    "WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming",
}
_hist_alphas = set(commodity_cfg.get("all_state_alphas", ()))
_raw_alphas  = set(raw_df[raw_df["state_alpha"] != "US"]["state_alpha"].unique())
if _class_states is not None:
    _hist_alphas = _hist_alphas & set(_class_states)
    _raw_alphas  = _raw_alphas  & set(_class_states)
_dd_alphas = _hist_alphas | _raw_alphas
_state_name_lookup = {a: _ALPHA_TO_NAME.get(a, a) for a in _dd_alphas}
_state_dd_names = ["All"] + sorted(_state_name_lookup.values())
_state_dd_alpha = {"All": None, **{v: k for k, v in _state_name_lookup.items()}}

with _state_dd_slot.container():
    sel_state_name = st.selectbox(
        "State",
        _state_dd_names,
        index=0,
        key="state_dd",
    )
sel_state_alpha = _state_dd_alpha[sel_state_name]   # None when "All"

# Apply individual state filter — pull from map_result so states filtered out by
# the 1% production threshold still show their full data when selected directly.
if sel_state_alpha is not None:
    result = map_result[map_result["state_alpha"] == sel_state_alpha].reset_index(drop=True)


# ── Pre-compute condition KPI variables (needed by both tabs) ─────────────────
_cond_short     = {"Good + Excellent": "G+E", "Fair": "Fair", "Poor + Very Poor": "P+VP", "JSA Index": "JSA"}
prior_mkt_label = mkt_label(sel_usda_yr - 1)
_cond_abbr      = _cond_short.get(condition, condition)

_pre_nat_kpis   = compute_national_kpis(raw_df, condition, sel_usda_yr, target_week=sel_week)
_pre_nat_cur    = _pre_nat_kpis["current"]
_pre_nat_disp   = f"{round(_pre_nat_cur):.0f}" if pd.notna(_pre_nat_cur) else "N/A"

nat_kpis    = _pre_nat_kpis
nat_current = _pre_nat_cur
nat_display = _pre_nat_disp

if commodity_cfg.get("has_classes", True):
    hrw_kpis    = compute_hrw_kpis(raw_df, condition, sel_usda_yr, target_week=sel_week, weights=_dynamic_hrw_weights)
    hrw_current = hrw_kpis["current"]
    hrw_display = f"{round(hrw_current):.0f}" if pd.notna(hrw_current) else "N/A"
    _wt_sorted   = sorted(_dynamic_hrw_weights.items(), key=lambda x: x[1], reverse=True)
    _wt_subtitle = " · ".join(f"{s} {w*100:.0f}%" for s, w in _wt_sorted[:7])

    srw_kpis    = compute_hrw_kpis(raw_df, condition, sel_usda_yr, target_week=sel_week, weights=_dynamic_srw_weights)
    srw_current = srw_kpis["current"]
    srw_display = f"{round(srw_current):.0f}" if pd.notna(srw_current) else "N/A"
    _srw_sorted   = sorted(_dynamic_srw_weights.items(), key=lambda x: x[1], reverse=True)
    _srw_subtitle = " · ".join(f"{s} {w*100:.0f}%" for s, w in _srw_sorted[:7])

    white_kpis    = compute_hrw_kpis(raw_df, condition, sel_usda_yr, target_week=sel_week, weights=_dynamic_white_weights)
    white_current = white_kpis["current"]
    white_display = f"{round(white_current):.0f}" if pd.notna(white_current) else "N/A"
    _white_sorted   = sorted(_dynamic_white_weights.items(), key=lambda x: x[1], reverse=True)
    _white_subtitle = " · ".join(f"{s} {w*100:.0f}%" for s, w in _white_sorted[:7])
else:
    hrw_kpis = srw_kpis = white_kpis = {}
    hrw_display = srw_display = white_display = "N/A"
    _wt_sorted = _srw_sorted = _white_sorted = []
    _wt_subtitle = _srw_subtitle = _white_subtitle = ""

# ── Harvest-acres fallback: olympic-avg % harvested × planted when USDA has not
# yet published harvested acres for the current marketing year (corn / soybeans).
# Applied to state-level data only; the US Total row is computed from state sums
# downstream, so the national estimate is derived automatically.
# Winter Wheat uses its own harvest-pct logic in fetch_ww_national_totals /
# fetch_ww_state_acres, so no fallback is applied there.
_acres_harvest_estimated = False   # flag for UI footnote
if commodity_label != "Winter Wheat" and not _prod_tab_acres_df.empty:
    _prod_tab_acres_df = _fill_harvest_fallback(_prod_tab_acres_df, sel_usda_yr, n_years=5)
    _acres_harvest_estimated = bool(
        _prod_tab_acres_df.get("_harvested_est", pd.Series(False, dtype=bool)).any()
    )

# Pre-initialise so abandonment tab can read values computed in production tab
_ph_cls: dict = {}

_tab_cond, _tab_yield, _tab_prod, _tab_abandon, _tab_validation, _tab_info = st.tabs([
    "📊 Conditions", "📈 Yield Model", "📦 Production",
    "🌾 Abandonment Analysis", "📐 Model Validation", "ℹ️ Wheat Classes Reference",
])

with _tab_cond:
    # ── Condition index tiles — top of page ───────────────────────────────────────
    # ── Row 1: US National (always shown, blue) ───────────────────────────────────
    kpi_cols = st.columns(4)
    for col, (val, label) in zip(kpi_cols, [
        (nat_display,                        f"National {_cond_abbr}"),
        (delta_html(nat_kpis["wow"]),        "vs. Prior Week"),
        (delta_html(nat_kpis["yoy"]),        f"vs. {prior_mkt_label}"),
        (delta_html(nat_kpis["vs_olympic"]), "vs. Olympic Avg"),
    ]):
        with col:
            st.markdown(f"""
            <div class="kpi-card">
              <div class="kpi-main">{val}</div>
              <div class="kpi-label">{label}</div>
            </div>""", unsafe_allow_html=True)

    if commodity_cfg.get("has_classes", True):
        # ── Row 2: HRW Weighted Index ─────────────────────────────────────────────
        st.markdown(
            f'<div style="font-size:0.72rem;color:#f59e0b;text-transform:uppercase;'
            f'letter-spacing:.07em;margin:0.9rem 0 0.3rem 0;font-weight:600">'
            f'⬡ HRW Weighted Index &nbsp;—&nbsp; {_wt_subtitle}</div>',
            unsafe_allow_html=True,
        )
        hrw_cols = st.columns(4)
        for col, (val, label) in zip(hrw_cols, [
            (hrw_display,                        f"HRW Index {_cond_abbr}"),
            (delta_html(hrw_kpis["wow"]),        "vs. Prior Week"),
            (delta_html(hrw_kpis["yoy"]),        f"vs. {prior_mkt_label}"),
            (delta_html(hrw_kpis["vs_olympic"]), "vs. Olympic Avg"),
        ]):
            with col:
                st.markdown(f"""
                <div class="kpi-card-hrw">
                  <div class="kpi-main">{val}</div>
                  <div class="kpi-label">{label}</div>
                </div>""", unsafe_allow_html=True)
        with st.expander("📊 HRW Index State Weights — basis & yield validation", expanded=False):
            _n_prod_years  = len(_hrw_prod_df["year"].unique()) if not _hrw_prod_df.empty else 0
            _prod_yr_range = (f"{int(_hrw_prod_df['year'].min())}–{int(_hrw_prod_df['year'].max())}"
                              if not _hrw_prod_df.empty else "n/a")
            _acres_rows_n  = len(_ww_state_acres) if not _ww_state_acres.empty else 0
            st.caption(
                f"HRW weights: **production-based** ({_n_prod_years} yrs, {_prod_yr_range}). "
                f"Acres data fetched: {_acres_rows_n} rows. "
                f"Fallback static weights used if API unavailable."
            )
            _hrw_wt_rows = []
            for s, w in _wt_sorted:
                _lkup = _yield_lookup.get(s, {})
                _ly   = _lkup.get(sel_usda_yr - 1, {})
                _hrw_wt_rows.append({
                    "State": s, "Weight": f"{w*100:.1f}%",
                    "LY Yield (bu/ac)": f"{_ly.get('yield', float('nan')):.1f}" if _ly else "—",
                    "LY vs Trend": f"{_ly.get('dev', float('nan')):+.1f}%" if _ly else "—",
                })
            _hrw_wt_df = pd.DataFrame(_hrw_wt_rows)
            st.dataframe(_hrw_wt_df, use_container_width=False, hide_index=True)
            _dl_btn(_hrw_wt_df, "hrw_state_weights.xlsx", "⬇ Download HRW Weights")

        # ── Row 3: SRW Weighted Index ─────────────────────────────────────────────
        st.markdown(
            f'<div style="font-size:0.72rem;color:#10b981;text-transform:uppercase;'
            f'letter-spacing:.07em;margin:0.9rem 0 0.3rem 0;font-weight:600">'
            f'⬡ SRW Weighted Index &nbsp;—&nbsp; {_srw_subtitle}</div>',
            unsafe_allow_html=True,
        )
        srw_cols = st.columns(4)
        for col, (val, label) in zip(srw_cols, [
            (srw_display,                        f"SRW Index {_cond_abbr}"),
            (delta_html(srw_kpis["wow"]),        "vs. Prior Week"),
            (delta_html(srw_kpis["yoy"]),        f"vs. {prior_mkt_label}"),
            (delta_html(srw_kpis["vs_olympic"]), "vs. Olympic Avg"),
        ]):
            with col:
                st.markdown(f"""
                <div class="kpi-card-srw">
                  <div class="kpi-main">{val}</div>
                  <div class="kpi-label">{label}</div>
                </div>""", unsafe_allow_html=True)
        with st.expander("📊 SRW Index State Weights (dynamic — 10-yr NASS production avg)", expanded=False):
            _n_srw_yrs    = len(_hrw_prod_df["year"].unique()) if not _hrw_prod_df.empty else 0
            _srw_yr_range = (f"{int(_hrw_prod_df['year'].min())}–{int(_hrw_prod_df['year'].max())}"
                             if not _hrw_prod_df.empty else "n/a")
            st.caption(f"Weights computed from {_n_srw_yrs} years of USDA NASS Winter wheat production data "
                       f"({_srw_yr_range}), filtered to SRW states.  Fallback static weights used if API unavailable.")
            _srw_wt_df = pd.DataFrame([{"State": s, "Weight": f"{w*100:.1f}%", "Share (raw)": f"{w:.4f}"}
                                        for s, w in _srw_sorted])
            st.dataframe(_srw_wt_df, use_container_width=False, hide_index=True)
            _dl_btn(_srw_wt_df, "srw_state_weights.xlsx", "⬇ Download SRW Weights")

        # ── Row 4: White Wheat Weighted Index ─────────────────────────────────────
        st.markdown(
            f'<div style="font-size:0.72rem;color:#818cf8;text-transform:uppercase;'
            f'letter-spacing:.07em;margin:0.9rem 0 0.3rem 0;font-weight:600">'
            f'⬡ White Wheat Weighted Index &nbsp;—&nbsp; {_white_subtitle}</div>',
            unsafe_allow_html=True,
        )
        white_cols = st.columns(4)
        for col, (val, label) in zip(white_cols, [
            (white_display,                         f"White Index {_cond_abbr}"),
            (delta_html(white_kpis["wow"]),         "vs. Prior Week"),
            (delta_html(white_kpis["yoy"]),         f"vs. {prior_mkt_label}"),
            (delta_html(white_kpis["vs_olympic"]),  "vs. Olympic Avg"),
        ]):
            with col:
                st.markdown(f"""
                <div class="kpi-card-white">
                  <div class="kpi-main">{val}</div>
                  <div class="kpi-label">{label}</div>
                </div>""", unsafe_allow_html=True)
        with st.expander("📊 White Wheat Index State Weights — basis & yield validation", expanded=False):
            _n_white_yrs    = len(_ww_state_acres["year"].unique()) if not _ww_state_acres.empty else 0
            _white_yr_range = (f"{int(_ww_state_acres['year'].min())}–{int(_ww_state_acres['year'].max())}"
                               if not _ww_state_acres.empty else "n/a")
            st.caption(f"White weights: **harvested-acres-based** (WA/ID/OR only — UT/CA removed as non-soft-white). "
                       f"{_n_white_yrs} yrs data ({_white_yr_range}). Fallback used if API unavailable.")
            _white_wt_df = pd.DataFrame([{"State": s, "Weight": f"{w*100:.1f}%", "Share (raw)": f"{w:.4f}"}
                                          for s, w in _white_sorted])
            st.dataframe(_white_wt_df, use_container_width=False, hide_index=True)
            _dl_btn(_white_wt_df, "white_state_weights.xlsx", "⬇ Download White Weights")

    st.markdown("---")

    # ── State Map(s) — ─────────────────────────────────────────────────────────────
    label_metric = st.radio(
        "State label shows",
        ["Current %", "vs LW", "vs LY", "vs Olympic Avg"],
        horizontal=True,
        key="label_metric_tog",
        label_visibility="collapsed",
    )

    week_label = (f"{latest_week.strftime('%B %d, %Y')}  Wk {int(latest_week.isocalendar().week)}"
                  if pd.notna(latest_week) else "")

    compare_result = pd.DataFrame()
    compare_week   = pd.NaT

    if cmp_usda_yr:
        # Match the same ISO week in the compare year as the currently selected week
        _sel_iso = int(pd.Timestamp(sel_week).isocalendar().week) if sel_week is not None else None
        _cmp_target_week = (
            _match_week_in_year(ge_df, cmp_usda_yr, _sel_iso)
            if _sel_iso is not None else None
        )
        compare_result, compare_week = build_comparison_table(
            ge_df, pv_df, fair_df, jsa_df, cmp_usda_yr,
            target_week=_cmp_target_week,
        )
        if not compare_result.empty:
            if _class_states is not None:
                compare_result = compare_result[compare_result["state_alpha"].isin(_class_states)].reset_index(drop=True)
            if sel_state_alpha is not None:
                compare_result = compare_result[compare_result["state_alpha"] == sel_state_alpha].reset_index(drop=True)

    if cmp_usda_yr and not compare_result.empty:
        map_col1, map_col2 = st.columns(2)
    else:
        map_col1 = st.container()
        map_col2 = None

    # National KPIs for the bottom-left map overlay
    _map_nat_kpis   = compute_national_kpis(raw_df, condition, sel_usda_yr, target_week=sel_week)
    _map_nat_cur    = _map_nat_kpis["current"]
    _map_nat_disp   = f"{round(_map_nat_cur):.0f}" if pd.notna(_map_nat_cur) else "N/A"
    _map_cond_lbl   = {"Good + Excellent": "G+E", "Fair": "Fair", "Poor + Very Poor": "P+VP", "JSA Index": "JSA"}[condition]
    _map_unit       = "" if condition == "JSA Index" else "%"

    def _fmt_chg(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "N/A"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.0f}%"

    with map_col1:
        st.markdown(
            f'<div class="sec-hdr">{condition} % — {selected_mkt} &nbsp;({week_label})</div>',
            unsafe_allow_html=True,
        )
        _map_fig = build_map(map_result, sel_usda_yr, condition, label_metric)
        _map_fig.add_annotation(
            text=(
                f"<b>US {_map_cond_lbl}: {_map_nat_disp}{_map_unit}</b><br>"
                f"<span style='font-size:13px;color:#444'>"
                f"LW {_fmt_chg(_map_nat_kpis['wow'])}&nbsp;&nbsp;·&nbsp;&nbsp;"
                f"LY {_fmt_chg(_map_nat_kpis['yoy'])}&nbsp;&nbsp;·&nbsp;&nbsp;"
                f"Avg {_fmt_chg(_map_nat_kpis['vs_olympic'])}"
                f"</span>"
            ),
            xref="paper", yref="paper",
            x=0.99, y=0.99,
            xanchor="right", yanchor="top",
            showarrow=False,
            font=dict(size=17, color="#1a4a2e", family="Arial Black"),
            bgcolor="white",
            bordercolor="#d0d7de",
            borderwidth=1,
            borderpad=10,
        )
        _map_fig.update_layout(
            title=dict(
                text=f"<b>JSA {commodity_label} Crop Conditions by State</b>",
                x=0.5, xanchor="center",
                font=dict(size=15, color="#1a4a2e", family="Arial Black"),
            ),
            margin=dict(l=0, r=0, t=52, b=10),
        )
        _show_chart(_map_fig, "conditions_map",
            extra_config={"scrollZoom": False, "modeBarButtonsToRemove": ["zoom", "pan", "select", "lasso2d", "resetGeo"]})

    if cmp_usda_yr and not compare_result.empty and map_col2 is not None:
        cw_label = compare_week.strftime("%B %d, %Y") if pd.notna(compare_week) else ""
        with map_col2:
            st.markdown(
                f'<div class="sec-hdr">{condition} % — {compare_mkt} &nbsp;({cw_label})</div>',
                unsafe_allow_html=True,
            )
            _show_chart(build_map(compare_result, cmp_usda_yr, condition, label_metric),
                "conditions_compare_map",
                extra_config={"scrollZoom": False, "modeBarButtonsToRemove": ["zoom", "pan", "select", "lasso2d", "resetGeo"]})

    if cmp_usda_yr and not compare_result.empty:
        diff_df = map_result[["state_alpha", "state_name", "GE_Current"]].merge(
            compare_result[["state_alpha", "GE_Current"]].rename(columns={"GE_Current": "GE_Compare"}),
            on="state_alpha", how="inner"
        )
        diff_df["diff"] = diff_df["GE_Current"] - diff_df["GE_Compare"]
        st.markdown(
            f'<div class="sec-hdr">Difference: {selected_mkt} minus {compare_mkt} (percentage points)</div>',
            unsafe_allow_html=True,
        )
        fig_diff = go.Figure(go.Choropleth(
            locations=diff_df["state_alpha"],
            z=diff_df["diff"],
            locationmode="USA-states",
            colorscale="RdYlGn",
            zmid=0,
            colorbar=dict(title=dict(text="Δ %"), ticksuffix="%"),
            hovertemplate="<b>%{location}</b><br>Δ: %{z:+.1f}%<extra></extra>",
            marker_line_color="white",
            marker_line_width=0.8,
        ))
        fig_diff.update_layout(
            geo=dict(scope="usa", showlakes=False, bgcolor=DM_BG, landcolor=DM_LAND, subunitcolor=DM_BORDER),
            paper_bgcolor=DM_BG,
            margin=dict(l=0, r=0, t=10, b=0),
            height=370,
        )
        _show_chart(fig_diff, "conditions_diff")

    # _use_hrw_index controls seasonal chart series (not KPI visibility)
    _use_hrw_index = (wheat_class == "HRW — Hard Red Winter")

    # Active series context — state filter overrides wheat class selection
    # _series_key  : lookup key for _yield_lookup / _trend_data
    # _series_label: human-readable label for chart titles
    if sel_state_alpha:
        _series_key   = sel_state_alpha
        _series_label = sel_state_name
    elif _use_hrw_index:
        _series_key   = "HRW"
        _series_label = "HRW Index"
    else:
        _series_key   = "US"
        _series_label = "National"

    # ── Option B: Best-signal week locking ────────────────────────────────────────
    # Run the best-week scan early (cached, so the Validation tab re-uses the result).
    # Once the current season has passed the peak-R² ISO week for a series, the JSA
    # index is locked to that week instead of the user-selected week — giving the most
    # historically predictive snapshot rather than a moving target.
    import json as _json_bw
    _bw_scan_devs = {
        sk: {str(yr): v["dev"] for yr, v in yl.items() if v.get("dev") is not None}
        for sk, yl in _yield_lookup.items()
        if any(v.get("dev") is not None for v in yl.values())
    }
    _bw_iso_min, _bw_iso_max = commodity_cfg.get("scan_iso_range", (5, 22))
    _best_week_res: dict = {}
    if sel_week is not None and not _yield_full.empty and _bw_scan_devs:
        _best_week_res = _scan_best_week(
            raw_df, sel_usda_yr,
            _json_bw.dumps(_bw_scan_devs),
            tuple(sorted(_dynamic_hrw_weights.items())),
            tuple(sorted(_dynamic_srw_weights.items())),
            tuple(sorted(_dynamic_white_weights.items())),
            _crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
            _scan_iso_min=_bw_iso_min,
            _scan_iso_max=_bw_iso_max,
            commodity_key=commodity_label,
        )

    _cur_iso_week: "int | None" = (
        int(pd.Timestamp(sel_week).isocalendar().week) if sel_week is not None else None
    )

    def _effective_week_ts(sk: str) -> "pd.Timestamp | None":
        """Return the timestamp to use for JSA snapping (Option B locking).

        If the current season has already passed the peak-R² ISO week for
        series `sk`, return a timestamp for that best week so the regression
        uses the most predictive historical snapshot.  Otherwise fall back to
        the user-selected week (no data available for the best week yet).
        """
        if sel_week is None or _cur_iso_week is None:
            return None
        _bw   = _best_week_res.get(sk, {})
        _best = _bw.get("best_iso")
        if _best is not None and _cur_iso_week >= int(_best):
            try:
                # Convert ISO week → calendar date (Sunday = day 7) in the same year
                return pd.Timestamp.fromisocalendar(
                    int(pd.Timestamp(sel_week).year), int(_best), 7
                )
            except Exception:
                pass
        return pd.Timestamp(sel_week)

    # ── Analog forecasts — computed once here, reused in scatter, analog section, yield table ──
    _analog_result        = None
    _class_analog_results = {"US": None, "HRW": None, "SRW": None, "White": None}
    if sel_week is not None and not _yield_full.empty:
        _cwm = {"HRW": _dynamic_hrw_weights, "SRW": _dynamic_srw_weights, "White": _dynamic_white_weights}
        _analog_result = _compute_analog_forecast(
            _series_key, raw_df, _effective_week_ts(_series_key), sel_usda_yr,
            _yield_lookup, _trend_data, _dynamic_hrw_weights, class_weights_map=_cwm,
            crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
            cond_weights=_active_cw,
        )
        _csk_list = ("US", "HRW", "SRW", "White") if commodity_cfg.get("has_classes", True) else ("US",)
        for _csk in _csk_list:
            if _csk == _series_key:
                _class_analog_results[_csk] = _analog_result
            else:
                _class_analog_results[_csk] = _compute_analog_forecast(
                    _csk, raw_df, _effective_week_ts(_csk), sel_usda_yr,
                    _yield_lookup, _trend_data, _dynamic_hrw_weights, class_weights_map=_cwm,
                    crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                    cond_weights=_active_cw,
                )

    # ── Yield model helpers (used inline below each class row) ────────────────────
    def _yield_mkt_lbl(harvest_yr: int) -> str:
        return mkt_label(harvest_yr)

    def _ykpi(state_key: str):
        if _yield_full.empty or state_key not in _trend_data:
            return None
        td    = _trend_data[state_key]
        rows  = _yield_full[_yield_full["state_alpha"] == state_key].sort_values("year")
        if rows.empty:
            return None
        latest     = rows.iloc[-1]
        h_yr       = int(latest["year"])
        actual     = float(latest["yield_bu_ac"])
        trend_same = _trend_at(td, h_yr)
        proj_trend = _trend_at(td, sel_usda_yr)
        return {
            "h_yr":       h_yr,
            "mkt_lbl":    _yield_mkt_lbl(h_yr),
            "actual":     actual,
            "trend_same": trend_same,
            "dev":        _dev_pct(actual, trend_same),
            "proj_trend": proj_trend,
            "r2":         td["r2"],
            "equation":   td["equation"],
            "n":          td["n"],
        }

    def _jsa_reg_forecast(sk: str):
        """Return (forecast_bu_ac, dev_pct) from a linear OLS regression of
        historical (JSA index, yield deviation) pairs for series key sk.
        Returns (None, None) if insufficient data."""
        _af2      = _class_analog_results.get(sk)
        _yk2      = _ykpi(sk)
        if not _af2 or not _yk2:
            return None, None
        _snap2    = _af2.get("jsa_snap", {})
        _cj2      = _af2.get("cur_jsa")
        _lkup2    = _yield_lookup.get(sk, {})
        _trend2   = _yk2.get("proj_trend")
        if _cj2 is None or not _trend2:
            return None, None
        _pts2 = [
            (_snap2[cy], _lkup2[cy]["dev"])
            for cy in _snap2
            if cy != sel_usda_yr and cy in _lkup2 and _lkup2[cy].get("dev") is not None
        ]
        if len(_pts2) < 3:
            return None, None
        _x2 = np.array([p[0] for p in _pts2])
        _y2 = np.array([p[1] for p in _pts2])
        _lc2 = np.linalg.lstsq(np.vstack([_x2, np.ones(len(_x2))]).T, _y2, rcond=None)[0]
        _cj2_f = float(_cj2)
        _dev2 = float(_lc2[0] * _cj2_f + _lc2[1])
        _raw2 = _trend2 * (1 + _dev2 / 100)
        return round(_raw2, 1), round(_dev2, 1)

    def _yield_kpi_cards(sk, yk, card_class, label_prefix, color, subtitle=""):
        if not yk:
            return
        proj    = yk["proj_trend"]
        _rf, _  = _jsa_reg_forecast(sk)
        fcast   = _rf if _rf is not None else proj
        dv      = _dev_pct(fcast, proj) if proj else float("nan")
        r2_pct  = f"{yk['r2']*100:.1f}%"
        cur_mkt = mkt_label(sel_usda_yr)
        # Effective-week label on the JSA Model card
        _kb      = _best_week_res.get(sk, {})
        _kb_iso  = _kb.get("best_iso")
        _kb_lock = (
            _kb_iso is not None
            and _cur_iso_week is not None
            and _cur_iso_week >= int(_kb_iso)
        )
        _kb_wk_lbl = (
            f" · 📌 Wk {_kb_iso}" if _kb_lock
            else (f" · Wk {_cur_iso_week}" if _cur_iso_week else "")
        )
        st.markdown(
            f'<div style="font-size:0.72rem;color:{color};text-transform:uppercase;'
            f'letter-spacing:.07em;margin:0.9rem 0 0.3rem 0;font-weight:600">'
            f'⬡ {label_prefix} Yield{(" &nbsp;—&nbsp; " + subtitle) if subtitle else ""}'
            f'</div>',
            unsafe_allow_html=True,
        )
        _cols = st.columns(4)
        for _col, (_v, _l) in zip(_cols, [
            (f'{fcast:.1f} bu/ac',  f'JSA Model ({cur_mkt}){_kb_wk_lbl}'),
            (f'{proj:.1f} bu/ac',   f'Trend Yield ({cur_mkt})'),
            (delta_html(dv),        'Model vs Trend'),
            (r2_pct,                f'R²  (n={yk["n"]} yrs)'),
        ]):
            with _col:
                st.markdown(f'<div class="{card_class}"><div class="kpi-main">{_v}</div>'
                             f'<div class="kpi-label">{_l}</div></div>', unsafe_allow_html=True)

    _us_yk    = _ykpi("US")
    _hrw_yk   = _ykpi("HRW")
    _srw_yk   = _ykpi("SRW")
    _white_yk = _ykpi("White")

    # ── State Comparison Table ─────────────────────────────────────────────────────
    st.markdown(
        f'<div class="sec-hdr">State-by-State Detail — {condition}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Share % = avg share of US winter wheat production. "
        "TW = This Week (green gradient) · LW / LY / 5YA = plain values · "
        "ΔLW / ΔLY / Δ5YA = change columns (green = improvement, red = decline; reversed for P+VP)."
    )
    # Add production share and sort by it
    result["Share %"] = result["state_alpha"].map(_state_share_pct).fillna(0.0)
    result = result.sort_values("Share %", ascending=False).reset_index(drop=True)
    st.dataframe(
        make_styled_table(result, condition, sel_usda_yr),
        use_container_width=True,
        height=490,
    )
    _dl_btn(result, f"crop_conditions_{selected_mkt.replace('/','_')}_{condition.replace(' ','_')}.xlsx",
            "⬇ Download State Conditions Table")

    # ── Historical Trend ───────────────────────────────────────────────────────────
    _trend_label = _series_label
    _cond_abbr_chart = {"Good + Excellent": "G+E %", "Fair": "Fair %",
                        "Poor + Very Poor": "P+VP %", "JSA Index": "JSA Index"}[condition]
    _cond_sfx_chart  = "" if condition == "JSA Index" else "%"
    st.markdown(f'<div class="sec-hdr">{_trend_label} {_cond_abbr_chart} — Season Progression</div>', unsafe_allow_html=True)

    # Pre / Post dormancy toggle — Winter Wheat only
    if commodity_cfg.get("has_dormancy", True):
        _phase_col, _yr_range_col, _ = st.columns([3, 3, 2])
        with _phase_col:
            _season_phase = st.radio(
                "Season phase",
                ["Post Dormancy", "Pre Dormancy"],
                horizontal=True,
                key="season_phase",
            )
        _pre_dormancy = (_season_phase == "Pre Dormancy")
    else:
        _yr_range_col, _ = st.columns([3, 5])
        _pre_dormancy = False

    with _yr_range_col:
        _yr_range = st.radio(
            "History shown",
            ["All Years", "Past 10 Years", "Past 5 Years", "Most Similar Years"],
            index=0,          # default to All Years (1986–present)
            horizontal=True,
            key="seasonal_yr_range",
        )
    _yr_range_cutoff = {
        "All Years":          None,
        "Past 10 Years":      sel_usda_yr - 10,
        "Past 5 Years":       sel_usda_yr - 5,
        "Most Similar Years": None,   # cutoff handled separately via _similar_years
    }[_yr_range]

    # ── Primary series: state > HRW index > US national ──────────────────────────
    # Uses the selected condition (G+E, Fair, P+VP, or JSA Index) — not always G+E.
    if sel_state_alpha:
        _us_ge = _us_series(raw_df, condition, sel_state_alpha).rename(columns={"metric": "cond_pct"})
    elif _use_hrw_index and commodity_cfg.get("has_classes", True):
        _us_ge = hrw_series(raw_df, condition, weights=_dynamic_hrw_weights).rename(columns={"metric": "cond_pct"})
    else:
        _us_ge = _us_series(raw_df, condition).rename(columns={"metric": "cond_pct"})

    # Assign crop/harvest year — commodity-aware (vectorised, safe on views)
    _us_ge = _us_ge.copy()
    _us_ge["week_ending"] = pd.to_datetime(_us_ge["week_ending"])   # ensure datetime dtype
    _cutoff = commodity_cfg.get("crop_yr_cutoff")
    if _cutoff:
        _us_ge["crop_year"] = (
            _us_ge["week_ending"].dt.year
            + (_us_ge["week_ending"].dt.month >= _cutoff).astype(int)
        )
    else:
        _us_ge["crop_year"] = _us_ge["week_ending"].dt.year

    # Filter to the selected phase and normalise to a common x-axis year
    if _pre_dormancy:
        nat_trend   = _us_ge[_us_ge["week_ending"].dt.month >= 9].copy()
        tick_dates  = [datetime(2000, m, 1) for m in [9, 10, 11, 12]]
        tick_labels = ["Sep", "Oct", "Nov", "Dec"]
    else:
        _csm = commodity_cfg.get("season_start_month", 1)
        _cem = commodity_cfg.get("chart_x_end", (12, 1))[0]
        nat_trend   = _us_ge[(_us_ge["week_ending"].dt.month >= _csm) &
                              (_us_ge["week_ending"].dt.month <= _cem)].copy()
        tick_dates  = [datetime(2000, m, 1) for m in commodity_cfg.get("chart_ticks", [1,2,3,4,5,6,7])]
        tick_labels = commodity_cfg.get("chart_tick_labels", ["Jan","Feb","Mar","Apr","May","Jun","Jul"])

    # All weeks normalised to year 2000 for the shared x-axis
    nat_trend["season_dt"] = nat_trend["week_ending"].apply(lambda d: d.replace(year=2000))
    nat_trend = nat_trend.sort_values(["crop_year", "season_dt"])

    # ── Compute 6-year Olympic average + SD bands ───────────────────────────────────
    # Group by ISO week number so that equivalent weeks across different years align
    # (exact week_ending dates differ by 1-3 days between years, making season_dt unique per row)
    _oly_years = sorted([y for y in nat_trend["crop_year"].unique() if y < sel_usda_yr])[-6:]
    nat_trend["iso_week"] = nat_trend["week_ending"].dt.isocalendar().week.astype(int)

    # ── Most Similar Years: rolling Pearson correlation vs current year to-date ───
    _similar_years: set = set()
    if _yr_range == "Most Similar Years":
        _cur_data = (
            nat_trend[nat_trend["crop_year"] == sel_usda_yr][["iso_week", "cond_pct"]]
            .dropna()
            .set_index("iso_week")["cond_pct"]
        )
        if not _cur_data.empty:
            _cur_iso_set = set(_cur_data.index)
            _sim_rows = []
            for _hy in nat_trend["crop_year"].unique():
                if _hy >= sel_usda_yr:
                    continue
                _hy_data = (
                    nat_trend[nat_trend["crop_year"] == _hy][["iso_week", "cond_pct"]]
                    .dropna()
                    .set_index("iso_week")["cond_pct"]
                )
                _common_iso = _cur_iso_set & set(_hy_data.index)
                if len(_common_iso) < 4:   # need at least 4 matching weeks
                    continue
                _corr = float(
                    _cur_data[list(_common_iso)].corr(_hy_data[list(_common_iso)])
                )
                if not np.isnan(_corr):
                    _sim_rows.append({"year": _hy, "corr": _corr})
            if _sim_rows:
                _sim_df = (
                    pd.DataFrame(_sim_rows)
                    .sort_values("corr", ascending=False)
                    .head(5)
                    .reset_index(drop=True)
                )
                _similar_years    = set(_sim_df["year"].tolist())
                _similar_year_rank = {int(row["year"]): idx
                                      for idx, row in _sim_df.iterrows()}  # 0 = best match
            else:
                _similar_year_rank = {}
        else:
            _similar_year_rank = {}
    else:
        _similar_year_rank = {}

    _band_base = nat_trend[nat_trend["crop_year"].isin(_oly_years)].copy()

    _band_rows = []
    for iso_w, grp in _band_base.groupby("iso_week"):
        vals = grp["cond_pct"].dropna().tolist()
        if len(vals) < 2:
            continue
        oly_vals = sorted(vals)
        if len(oly_vals) >= 3:
            oly_vals = oly_vals[1:-1]           # drop high + low for olympic avg
        oly = float(np.mean(oly_vals))
        std = float(np.std(vals, ddof=1))       # SD of all 6 years
        # Use the mean normalised date for this week slot as the x-axis position
        sdt = grp["season_dt"].mean()
        _band_rows.append({
            "season_dt": sdt,
            "oly_avg":  oly,
            "upper2": min(100.0, oly + 2 * std),
            "lower2": max(  0.0, oly - 2 * std),
            "upper1": min(100.0, oly +     std),
            "lower1": max(  0.0, oly -     std),
        })
    bands = (
        pd.DataFrame(_band_rows).sort_values("season_dt").reset_index(drop=True)
        if _band_rows else
        pd.DataFrame(columns=["season_dt","oly_avg","upper2","lower2","upper1","lower1"])
    )

    from plotly.subplots import make_subplots as _make_subplots
    fig_trend = _make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.76, 0.24],
        vertical_spacing=0.03,
    )

    # Historical median per ISO week slot (group by week number so all years combine correctly;
    # different years land on different calendar days within the same ISO week, so groupby
    # season_dt would leave each year isolated — use iso_week as the key instead)
    _hist_for_median = nat_trend[nat_trend["crop_year"] < sel_usda_yr].copy()
    _hist_for_median["iso_week"] = _hist_for_median["week_ending"].dt.isocalendar().week.astype(int)
    _median_df = (
        _hist_for_median
        .groupby("iso_week", as_index=False)
        .agg(cond_pct=("cond_pct", "median"), season_dt=("season_dt", "mean"))
        .sort_values("season_dt")
    )

    if not bands.empty:
        _x = bands["season_dt"].tolist()

        # ±2 SD band (outer, lighter gray)
        fig_trend.add_trace(go.Scatter(
            x=_x, y=bands["upper2"].tolist(),
            mode="lines", line=dict(width=0),
            showlegend=False, hoverinfo="skip",
        ), row=1, col=1)
        fig_trend.add_trace(go.Scatter(
            x=_x, y=bands["lower2"].tolist(),
            mode="lines", line=dict(width=0),
            fill="tonexty", fillcolor="rgba(180,185,182,0.13)",
            name="Historical Range (±2 SD)",
            showlegend=True,
            hoverinfo="skip",
        ), row=1, col=1)

        # ±1 SD band (inner, slightly darker gray)
        fig_trend.add_trace(go.Scatter(
            x=_x, y=bands["upper1"].tolist(),
            mode="lines", line=dict(width=0),
            showlegend=False, hoverinfo="skip",
        ), row=1, col=1)
        fig_trend.add_trace(go.Scatter(
            x=_x, y=bands["lower1"].tolist(),
            mode="lines", line=dict(width=0),
            fill="tonexty", fillcolor="rgba(150,170,160,0.22)",
            name="Historical Range (±1 SD)",
            showlegend=True,
            hoverinfo="skip",
        ), row=1, col=1)

    # Historical median line
    if not _median_df.empty:
        fig_trend.add_trace(go.Scatter(
            x=_median_df["season_dt"].tolist(),
            y=_median_df["cond_pct"].tolist(),
            mode="lines",
            name="Historical Median",
            line=dict(color="#1e2533", width=2.5, dash="dash"),
            connectgaps=True,
            hovertemplate="<b>Historical Median</b>  %{x|%b %d}: %{y:.0f}%<extra></extra>",
        ), row=1, col=1)

    # ── Yield hover helper (uses lookup built at load time) ────────────────────────
    _yld_lkup_key = _series_key
    _yld_lkup     = _yield_lookup.get(_yld_lkup_key, {})

    def _yld_sfx(crop_yr: int) -> str:
        """Return an HTML hover suffix with yield and deviation for the given crop year."""
        v = _yld_lkup.get(crop_yr)
        if v:
            sign = "+" if v["dev"] >= 0 else ""
            return (f"<br>Yield: <b>{v['yield']:.1f} bu/ac</b>"
                    f"  |  Δ Trend: <b>{sign}{v['dev']:.1f}%</b>")
        # Current / future year — show trendline projection instead
        if _yld_lkup_key in _trend_data:
            proj = _trend_at(_trend_data[_yld_lkup_key], crop_yr)
            return f"<br>Trend Proj: <b>{proj:.1f} bu/ac</b>  (harvest pending)"
        return ""

    # All other marketing years — colored lines sampled from a spectral gradient so
    # each year is visually distinct.  Oldest year → cool/purple end; newest → warm/red end.
    _analog_hover_yrs = (
        {a["crop_year"] for a in _analog_result["analogs"][:4]}
        if _analog_result
        else set(_oly_years[-4:])     # fallback: 4 most recent Olympic average years
    )
    # Ensure the most recent available year (sel_usda_yr - 1) is included if outside the 4
    _analog_hover_yrs.add(sel_usda_yr - 1)

    _skip_years = {sel_usda_yr, sel_usda_yr - 1}
    if cmp_usda_yr:
        _skip_years.add(cmp_usda_yr)

    # Build year → color map from a continuous colorscale so every year is unique.
    # "Turbo" gives vivid, perceptually-uniform colors across ~40 years of history.
    import plotly.colors as _pc
    _hist_years_sorted = sorted([
        y for y in nat_trend["crop_year"].unique()
        if y not in _skip_years
        and (_yr_range_cutoff is None or y >= _yr_range_cutoff)
        and (_yr_range != "Most Similar Years" or y in _similar_years)
    ])
    _n_hist = max(len(_hist_years_sorted), 1)
    _hist_color_map = {
        yr: _pc.sample_colorscale("Turbo", [i / max(_n_hist - 1, 1)])[0]
        for i, yr in enumerate(_hist_years_sorted)
    }

    # Single "Previous Years" legend entry — clicking it shows/hides all gray history lines
    if _hist_years_sorted and _yr_range != "Most Similar Years":
        fig_trend.add_trace(go.Scatter(
            x=[None], y=[None], mode="lines",
            name="Previous Years",
            legendgroup="prev_years",
            line=dict(color="rgba(150,160,155,0.60)", width=1.5),
            showlegend=True,
        ), row=1, col=1)

    for _cy in _hist_years_sorted:
        _cy_data = nat_trend[nat_trend["crop_year"] == _cy].sort_values("season_dt")
        if _cy_data.empty:
            continue
        # Most Similar Years — highlight each line with a distinct colour + label
        if _yr_range == "Most Similar Years":
            _sim_rank    = _similar_year_rank.get(_cy, 4)
            _sim_palette = ["#4fc3f7", "#29b6f6", "#0288d1", "#01579b", "#80deea"]
            _cy_color    = _sim_palette[min(_sim_rank, 4)]
            _cy_width    = 2.0 - _sim_rank * 0.2
            _cy_opacity  = 1.0
            _lg          = None
        else:
            # Uniform thin gray — all history shown as context; hover identifies each year
            _cy_color   = "rgba(150,160,155,0.35)"
            _cy_width   = 0.8
            _cy_opacity = 1.0
            _lg         = "prev_years"   # linked to the single legend toggle above
        fig_trend.add_trace(go.Scatter(
            x=_cy_data["season_dt"],
            y=_cy_data["cond_pct"],
            mode="lines",
            name=mkt_label_short(_cy),
            legendgroup=_lg,
            line=dict(color=_cy_color, width=_cy_width),
            opacity=_cy_opacity,
            showlegend=(_yr_range == "Most Similar Years"),
            connectgaps=False,
            hovertemplate=(
                f"<b>{mkt_label(_cy)}</b>  %{{x|%b %d}}: %{{y:.1f}}{_cond_sfx_chart}"
                f"{_yld_sfx(_cy)}<extra></extra>"
            ),
        ), row=1, col=1)

    # Prior year (sel_usda_yr − 1) — auto-shown dashed line
    _prior_yr   = sel_usda_yr - 1
    _prior_lbl  = (f"HRW Index {mkt_label_short(_prior_yr)}" if _use_hrw_index
                   else mkt_label_short(_prior_yr))
    _prior_data = nat_trend[nat_trend["crop_year"] == _prior_yr].sort_values("season_dt")
    if not _prior_data.empty:
        fig_trend.add_trace(go.Scatter(
            x=_prior_data["season_dt"],
            y=_prior_data["cond_pct"],
            mode="lines",
            name=_prior_lbl,
            line=dict(color="#4a5568", width=2),
            connectgaps=False,
            hovertemplate=(
                f"<b>{_prior_lbl}</b>  %{{x|%b %d}}: %{{y:.1f}}{_cond_sfx_chart}"
                f"{_yld_sfx(_prior_yr)}<extra></extra>"
            ),
        ), row=1, col=1)

    # Compare year (sidebar selection) — orange dashed, only if different from prior year
    if cmp_usda_yr and cmp_usda_yr != _prior_yr:
        cy_data = nat_trend[nat_trend["crop_year"] == cmp_usda_yr].sort_values("season_dt")
        if not cy_data.empty:
            fig_trend.add_trace(go.Scatter(
                x=cy_data["season_dt"],
                y=cy_data["cond_pct"],
                mode="lines",
                name=mkt_label_short(cmp_usda_yr),
                line=dict(color="#ff7f0e", width=1.5, dash="dash"),
                connectgaps=False,
                hovertemplate=(
                    f"<b>{compare_mkt}</b>  %{{x|%b %d}}: %{{y:.1f}}{_cond_sfx_chart}"
                    f"{_yld_sfx(cmp_usda_yr)}<extra></extra>"
                ),
            ), row=1, col=1)

    # Current selected year — thin solid JPSI blue (or amber when HRW) with markers
    _cur_line_color = "#f59e0b" if _use_hrw_index else JPSI_BLUE
    _cur_yr_label   = (f"HRW Index {mkt_label_short(sel_usda_yr)}" if _use_hrw_index
                       else mkt_label_short(sel_usda_yr))
    sel_data = nat_trend[nat_trend["crop_year"] == sel_usda_yr].sort_values("season_dt")
    if not sel_data.empty:
        fig_trend.add_trace(go.Scatter(
            x=sel_data["season_dt"],
            y=sel_data["cond_pct"],
            mode="lines+markers",
            name=_cur_yr_label,
            line=dict(color=_cur_line_color, width=3),
            marker=dict(size=6, color=_cur_line_color),
            connectgaps=False,
            hovertemplate=(
                f"<b>{_cur_yr_label}</b>  %{{x|%b %d}}: %{{y:.1f}}{_cond_sfx_chart}"
                f"{_yld_sfx(sel_usda_yr)}<extra></extra>"
            ),
        ), row=1, col=1)

    # ── Weekly change bars (row 2) ─────────────────────────────────────────────
    if not sel_data.empty and len(sel_data) >= 2:
        _delta_df = sel_data.sort_values("season_dt").copy()
        _delta_df["delta"] = _delta_df["cond_pct"].diff()
        _delta_df = _delta_df.dropna(subset=["delta"])
        _bar_colors = [
            "rgba(26,152,80,0.85)" if d >= 0 else "rgba(180,100,50,0.85)"
            for d in _delta_df["delta"]
        ]
        fig_trend.add_trace(go.Bar(
            x=_delta_df["season_dt"].tolist(),
            y=_delta_df["delta"].tolist(),
            marker_color=_bar_colors,
            name="Wk Change",
            customdata=[int(pd.Timestamp(d).isocalendar().week)
                        for d in _delta_df["week_ending"]],
            hovertemplate="%{x|%b %d} (Wk %{customdata}): %{y:+.1f}%<extra></extra>",
            showlegend=True,
            width=5 * 24 * 60 * 60 * 1000,
        ), row=2, col=1)

    # Auto-fit x-axis to actual data extent with a small padding
    if not nat_trend.empty:
        from datetime import timedelta as _td
        _xmin = nat_trend["season_dt"].min()
        _xmax = nat_trend["season_dt"].max()
        _x_range = [_xmin - _td(days=7), _xmax + _td(days=7)]
    else:
        _x_range = None

    # Auto-fit y-axis: gather all plotted y values and pad by 5 pts each side
    _y_all = []
    if _yr_range == "Most Similar Years" and _similar_years:
        _nat_trend_visible = nat_trend[nat_trend["crop_year"].isin(_similar_years | {sel_usda_yr, sel_usda_yr - 1})]
    elif _yr_range_cutoff is not None:
        _nat_trend_visible = nat_trend[nat_trend["crop_year"] >= _yr_range_cutoff]
    else:
        _nat_trend_visible = nat_trend
    if not _nat_trend_visible.empty:
        _y_all.extend(_nat_trend_visible["cond_pct"].dropna().tolist())
    if not bands.empty:
        for _bc in ["upper2", "lower2"]:
            if _bc in bands.columns:
                _y_all.extend(bands[_bc].dropna().tolist())
    if _y_all:
        _y_lo = max(0,   round(min(_y_all)) - 5)
        _y_hi = min(100, round(max(_y_all)) + 5)
    else:
        _y_lo, _y_hi = 0, 100

    fig_trend.update_layout(
        xaxis=dict(
            tickvals=tick_dates,
            ticktext=tick_labels,
            showgrid=True,
            gridcolor=DM_BORDER,
            color=DM_MUTED,
            tickfont=dict(color=DM_MUTED),
            showticklabels=False,
            **({'range': _x_range} if _x_range else {}),
        ),
        xaxis2=dict(
            tickvals=tick_dates,
            ticktext=tick_labels,
            title="Month",
            showgrid=True,
            gridcolor=DM_BORDER,
            color=DM_MUTED,
            tickfont=dict(color=DM_MUTED),
            title_font=dict(color=DM_MUTED),
            **({'range': _x_range} if _x_range else {}),
        ),
        yaxis=dict(
            title=f"{_trend_label} {_cond_abbr_chart}",
            range=[_y_lo, _y_hi],
            ticksuffix=_cond_sfx_chart,
            gridcolor=DM_BORDER,
            color=DM_MUTED,
            tickfont=dict(color=DM_MUTED),
            title_font=dict(color=DM_MUTED),
        ),
        yaxis2=dict(
            title="Wk Δ",
            gridcolor=DM_BORDER,
            color=DM_MUTED,
            tickfont=dict(color=DM_MUTED, size=9),
            title_font=dict(color=DM_MUTED, size=10),
            ticksuffix="%",
            zeroline=True,
            zerolinecolor=DM_MUTED,
            zerolinewidth=1,
        ),
        paper_bgcolor=DM_BG,
        plot_bgcolor=DM_SURFACE2,
        legend=dict(
            bgcolor=DM_SURFACE, bordercolor=DM_BORDER, borderwidth=1,
            font=dict(color=DM_TEXT, size=10),
            orientation="h", yanchor="top", y=-0.10, xanchor="center", x=0.5,
        ),
        margin=dict(l=10, r=10, t=30, b=80),
        height=700,
        hovermode="x unified",
    )
    _wm_center(fig_trend)
    _show_chart(fig_trend, "conditions_trend")

    # ── Year-by-Year Ranking Bar Chart ────────────────────────────────────────────
    st.markdown(
        f'<div class="sec-hdr">Year-by-Year — {_series_label} {_cond_short.get(condition, condition)}'
        f' at Selected Week</div>',
        unsafe_allow_html=True,
    )

    _rank_col, _rank_spacer = st.columns([3, 5])
    with _rank_col:
        _rank_order = st.radio(
            "Bar order",
            ["Chronological", "Highest → Lowest"],
            horizontal=True,
            key="rank_order",
        )

    # Build per-year value at the ISO week matching sel_week — state > HRW > US
    if sel_state_alpha:
        _bar_src = _us_series(raw_df, condition, sel_state_alpha).rename(columns={"metric": "cond_val"})
    elif _use_hrw_index:
        _bar_src = hrw_series(raw_df, condition, weights=_dynamic_hrw_weights).rename(columns={"metric": "cond_val"})
    else:
        _bar_src = _us_series(raw_df, condition).rename(columns={"metric": "cond_val"})

    if not _bar_src.empty and sel_week is not None:
        _bar_cutoff = commodity_cfg.get("crop_yr_cutoff")
        _bar_src = _bar_src.copy()
        if _bar_cutoff:
            _bar_src["crop_year"] = (
                _bar_src["week_ending"].dt.year
                + (_bar_src["week_ending"].dt.month >= _bar_cutoff).astype(int)
            )
        else:
            _bar_src["crop_year"] = _bar_src["week_ending"].dt.year
        _bar_src["iso_week"] = _bar_src["week_ending"].dt.isocalendar().week.astype(int)
        _sel_iso = pd.Timestamp(sel_week).isocalendar().week

        _bar_rows = []
        for _bcy, _bgrp in _bar_src.groupby("crop_year"):
            # Apply the same year-range filter as the seasonal chart
            if _yr_range_cutoff is not None and _bcy < _yr_range_cutoff:
                continue
            if _yr_range == "Most Similar Years" and _bcy != sel_usda_yr and _bcy not in _similar_years:
                continue
            _bgrp = _bgrp.copy()
            _bgrp["iso_diff"] = (_bgrp["iso_week"] - _sel_iso).abs()
            _bbest = _bgrp.nsmallest(1, "iso_diff")
            if _bbest.empty:
                continue
            _bval  = float(_bbest["cond_val"].iloc[0])
            _bwk   = pd.Timestamp(_bbest["week_ending"].iloc[0])
            _byld  = _yld_lkup.get(_bcy)
            _is_cur = (_bcy == sel_usda_yr)

            # Projected trendline yield for years without final data
            if not _byld and _yld_lkup_key in _trend_data:
                _bproj = _trend_at(_trend_data[_yld_lkup_key], _bcy)
            else:
                _bproj = None

            _bar_rows.append({
                "crop_year":    _bcy,
                "mkt_lbl":      mkt_label(_bcy),
                "value":        _bval,
                "wk_lbl":       _bwk.strftime("%b %d"),
                "is_current":   _is_cur,
                "yield_actual": _byld["yield"] if _byld else None,
                "yield_trend":  _byld["trend"] if _byld else _bproj,
                "yield_dev":    _byld["dev"]   if _byld else None,
            })

        if _bar_rows:
            _bar_df = pd.DataFrame(_bar_rows)

            # Sort
            if _rank_order == "Highest → Lowest":
                _bar_df = _bar_df.sort_values("value", ascending=False).reset_index(drop=True)
            else:
                _bar_df = _bar_df.sort_values("crop_year").reset_index(drop=True)

            # Color: green gradient for past years, amber for current year
            _blo = float(_bar_df["value"].min())
            _bhi = float(_bar_df["value"].max())
            _bar_colors = []
            for _, _br in _bar_df.iterrows():
                if _br["is_current"]:
                    _bar_colors.append("#f59e0b")
                else:
                    _bar_colors.append(_seq_bg(_br["value"], _blo, _bhi,
                                               reverse=(condition == "Poor + Very Poor")))

            # Hover text
            _cond_sfx = "%" if condition != "JSA Index" else ""
            def _barhover(r):
                parts = [
                    f"<b>{r['mkt_lbl']}</b>  (wk ending {r['wk_lbl']})",
                    f"{condition}: <b>{r['value']:.0f}{_cond_sfx}</b>",
                ]
                if r["is_current"]:
                    if r["yield_trend"] is not None:
                        parts.append(f"Trend Yield: <b>{r['yield_trend']:.1f} bu/ac</b>  (harvest pending)")
                    else:
                        parts.append("Yield: <i>harvest pending</i>")
                else:
                    if r["yield_actual"] is not None:
                        _dsign = "+" if r["yield_dev"] >= 0 else ""
                        parts.append(f"Yield: <b>{r['yield_actual']:.1f} bu/ac</b>")
                        parts.append(f"Δ Trendline: <b>{_dsign}{r['yield_dev']:.1f}%</b>")
                    elif r["yield_trend"] is not None:
                        parts.append(f"Trend Yield: <b>{r['yield_trend']:.1f} bu/ac</b>  (no final data)")
                return "<br>".join(parts)

            _bar_df["hover"] = _bar_df.apply(_barhover, axis=1)

            _fig_bar = go.Figure(go.Bar(
                x=_bar_df["mkt_lbl"].tolist(),
                y=_bar_df["value"].tolist(),
                marker_color=_bar_colors,
                marker_line_width=0,
                text=[f"<b>{v:.0f}{_cond_sfx}</b>" for v in _bar_df["value"]],
                textposition="outside",
                textfont=dict(size=11, color=DM_TEXT),
                cliponaxis=False,
                hovertext=_bar_df["hover"].tolist(),
                hovertemplate="%{hovertext}<extra></extra>",
                showlegend=False,
            ))

            _fig_bar.update_layout(
                xaxis=dict(
                    tickangle=-45,
                    tickfont=dict(size=11, color=DM_TEXT, family="Arial Black"),
                    color=DM_TEXT,
                    showgrid=False,
                ),
                yaxis=dict(
                    title=f"{_cond_short.get(condition, condition)}"
                          f"{' %' if condition != 'JSA Index' else ' (score)'}",
                    range=[0, min(100, float(_bar_df["value"].max()) * 1.22)],
                    showgrid=True,
                    gridcolor=DM_BORDER,
                    color=DM_MUTED,
                    tickfont=dict(color=DM_MUTED),
                    title_font=dict(color=DM_MUTED),
                    ticksuffix=_cond_sfx,
                ),
                paper_bgcolor=DM_BG,
                plot_bgcolor=DM_SURFACE2,
                margin=dict(l=10, r=10, t=10, b=80),
                height=380,
                hovermode="closest",
                bargap=0.2,
            )

            # Annotation: current year marker label
            _cur_row = _bar_df[_bar_df["is_current"]]
            if not _cur_row.empty:
                _fig_bar.add_annotation(
                    x=_cur_row.iloc[0]["mkt_lbl"],
                    y=_cur_row.iloc[0]["value"],
                    text="◀ Current",
                    showarrow=True,
                    arrowhead=2,
                    arrowcolor="#f59e0b",
                    font=dict(size=10, color="#f59e0b"),
                    yshift=12,
                )

            _wm(_fig_bar)
            _show_chart(_fig_bar, "conditions_bar")

    elif sel_week is None:
        st.info("Select a marketing week in the sidebar to populate the ranking chart.")

with _tab_yield:
    _yield_kpi_cards("US", _us_yk, "kpi-card", "US Total", DM_MUTED)

    if commodity_cfg.get("has_classes", True):
        _yield_kpi_cards("HRW", _hrw_yk, "kpi-card-hrw", "HRW Weighted", "#f59e0b", _wt_subtitle)
        _yield_kpi_cards("SRW", _srw_yk, "kpi-card-srw", "SRW Weighted", "#10b981",
                         " · ".join(f"{s} {w*100:.0f}%" for s, w in _srw_sorted[:7]))
        _yield_kpi_cards("White", _white_yk, "kpi-card-white", "White Weighted", "#818cf8",
                         " · ".join(f"{s} {w*100:.0f}%" for s, w in _white_sorted[:7]))

    # ── R² by Week — Condition Index Predictive Power ─────────────────────────
    st.markdown(
        '<div class="sec-hdr">R² by Week — Condition Index Predictive Power</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "R² measures how well the JSA condition index at each ISO week predicts the season's "
        "final yield deviation from trend.  Higher R² = more predictive signal.  "
        "The gold star marks the peak-signal week used to anchor the yield model."
    )

    if not _best_week_res:
        st.info(
            "R² scan not available — requires yield data and a selected week.  "
            f"(yield loaded: {not _yield_full.empty},  week selected: {sel_week is not None})"
        )
    else:
        _r2w_keys = sorted(_best_week_res.keys())
        _r2w_default = _series_key if _series_key in _r2w_keys else ("US" if "US" in _r2w_keys else _r2w_keys[0])
        _r2w_col, _ = st.columns([2, 6])
        with _r2w_col:
            _r2w_sel = st.selectbox(
                "State / Series",
                _r2w_keys,
                index=_r2w_keys.index(_r2w_default),
                format_func=lambda k: "US Total" if k == "US" else k,
                key="r2w_series_sel",
            )

        _r2w_bw   = _best_week_res.get(_r2w_sel, {})
        _r2w_all  = _r2w_bw.get("all_r2", {})
        _r2w_best = _r2w_bw.get("best_iso")
        _r2w_n    = _r2w_bw.get("n_years", 0)
        _r2w_lbl  = "US Total" if _r2w_sel == "US" else _r2w_sel

        if _r2w_all:
            _r2w_df = (
                pd.DataFrame([
                    {"iso_week": int(k), "r2_pct": float(v) * 100}
                    for k, v in _r2w_all.items()
                ])
                .sort_values("iso_week")
                .reset_index(drop=True)
            )

            _r2w_fig = go.Figure()
            _r2w_fig.add_trace(go.Scatter(
                x=_r2w_df["iso_week"],
                y=_r2w_df["r2_pct"],
                mode="lines+markers",
                name="R² by week",
                line=dict(color=JPSI_BLUE, width=2),
                marker=dict(size=5, color=JPSI_BLUE),
                hovertemplate="Week %{x} — R²: %{y:.1f}%<extra></extra>",
            ))

            if _r2w_best is not None and int(_r2w_best) in _r2w_df["iso_week"].values:
                _r2w_peak_r2 = float(
                    _r2w_df.loc[_r2w_df["iso_week"] == int(_r2w_best), "r2_pct"].iloc[0]
                )
                _r2w_fig.add_trace(go.Scatter(
                    x=[int(_r2w_best)],
                    y=[_r2w_peak_r2],
                    mode="markers+text",
                    name=f"Peak Wk {_r2w_best}",
                    marker=dict(size=16, color="#f59e0b", symbol="star",
                                line=dict(color=DM_TEXT, width=1)),
                    text=[f"Wk {_r2w_best}: {_r2w_peak_r2:.0f}%"],
                    textposition="top center",
                    textfont=dict(color=DM_TEXT, size=11),
                    hovertemplate=(
                        f"<b>Peak Signal — Week {_r2w_best}</b><br>"
                        f"R²: {_r2w_peak_r2:.1f}%<extra></extra>"
                    ),
                ))
                _r2w_fig.add_vline(
                    x=int(_r2w_best),
                    line_dash="dot", line_color="#f59e0b", opacity=0.55,
                )

            _r2w_fig.update_layout(
                xaxis=dict(
                    title="ISO Week",
                    dtick=1,
                    showgrid=True, gridcolor=DM_BORDER,
                    color=DM_MUTED, tickfont=dict(color=DM_MUTED),
                    title_font=dict(color=DM_MUTED),
                ),
                yaxis=dict(
                    title="R² (%)",
                    range=[0, min(100, _r2w_df["r2_pct"].max() + 10)],
                    showgrid=True, gridcolor=DM_BORDER,
                    color=DM_MUTED, tickfont=dict(color=DM_MUTED),
                    title_font=dict(color=DM_MUTED),
                    ticksuffix="%",
                ),
                paper_bgcolor=DM_BG,
                plot_bgcolor=DM_SURFACE2,
                legend=dict(
                    orientation="h", x=0.5, xanchor="center", y=-0.18,
                    font=dict(color=DM_TEXT, size=11),
                    bgcolor="rgba(0,0,0,0)",
                ),
                margin=dict(l=10, r=10, t=40, b=60),
                height=340,
                hovermode="x unified",
                title=dict(
                    text=(
                        f"<b>{_r2w_lbl}</b>  —  R² by ISO Week"
                        + (f"  ·  Peak Wk {_r2w_best}"
                           f" ({_r2w_bw.get('r2', 0)*100:.0f}%)" if _r2w_best else "")
                        + (f"  ·  n = {_r2w_n} yrs" if _r2w_n else "")
                    ),
                    font=dict(size=12, color=DM_TEXT),
                    x=0.5, xanchor="center",
                ),
            )
            _wm_center(_r2w_fig)
            _show_chart(_r2w_fig, "r2_vs_week")
        else:
            st.info("Not enough data to compute R² by week for the selected series.")

    # ── Peak-lock vs current signal drift (only shown once past peak week) ────────
    _drift_bw    = _best_week_res.get(_series_key, {})
    _drift_best  = _drift_bw.get("best_iso")
    _drift_r2    = _drift_bw.get("r2")
    _drift_locked = (
        _drift_best is not None
        and _cur_iso_week is not None
        and _cur_iso_week > int(_drift_best)    # strictly past peak week
    )
    if _drift_locked and _analog_result and sel_week is not None:
        _drift_peak_jsa = _analog_result.get("cur_jsa")
        # Recompute JSA at the user-selected (current) week — no lock
        _drift_cwm = {"HRW": _dynamic_hrw_weights, "SRW": _dynamic_srw_weights,
                      "White": _dynamic_white_weights}
        _drift_live_af = _compute_analog_forecast(
            _series_key, raw_df, pd.Timestamp(sel_week), sel_usda_yr,
            _yield_lookup, _trend_data, _dynamic_hrw_weights,
            class_weights_map=_drift_cwm,
            crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
            cond_weights=_active_cw,
        )
        _drift_cur_jsa = _drift_live_af.get("cur_jsa") if _drift_live_af else None
        if _drift_peak_jsa is not None and _drift_cur_jsa is not None:
            _drift_delta  = round(_drift_cur_jsa - _drift_peak_jsa, 1)
            _drift_pk_ts  = _effective_week_ts(_series_key)
            _drift_pk_lbl = _drift_pk_ts.strftime("%b %d") if _drift_pk_ts else f"Wk {_drift_best}"
            _drift_cu_lbl = f"{pd.Timestamp(sel_week).strftime('%b %d')} Wk {int(pd.Timestamp(sel_week).isocalendar().week)}"
            _drift_r2_str = f"  ·  R² {_drift_r2*100:.0f}%" if _drift_r2 else ""
            st.markdown(
                f'<div class="sec-hdr">Condition Signal — Locked Week vs. Current</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                f"Forecast is anchored to peak-R² Wk {_drift_best} ({_drift_pk_lbl}{_drift_r2_str}). "
                f"Positive Δ means conditions have improved since the lock; negative means they've weakened."
            )
            _dc = st.columns(3)
            with _dc[0]:
                st.markdown(
                    f'<div class="kpi-card">'
                    f'<div class="kpi-main">{_drift_peak_jsa:.1f}</div>'
                    f'<div class="kpi-label">📌 JSA at Lock · Wk {_drift_best} ({_drift_pk_lbl})</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with _dc[1]:
                st.markdown(
                    f'<div class="kpi-card">'
                    f'<div class="kpi-main">{_drift_cur_jsa:.1f}</div>'
                    f'<div class="kpi-label">JSA Now · {_drift_cu_lbl}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with _dc[2]:
                _ds        = "+" if _drift_delta >= 0 else ""
                _dc_color  = "#10b981" if _drift_delta >= 0 else "#ef4444"
                st.markdown(
                    f'<div class="kpi-card">'
                    f'<div class="kpi-main" style="color:{_dc_color}">{_ds}{_drift_delta}</div>'
                    f'<div class="kpi-label">Δ JSA Since Lock</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    _sel_week_lbl = (f"{pd.Timestamp(sel_week).strftime('%b %d')} Wk {int(pd.Timestamp(sel_week).isocalendar().week)}"
                     if sel_week else "—")

    # ── State Yield Model Map ──────────────────────────────────────────────────────
    if not _yield_full.empty:
        st.markdown(
            f'<div class="sec-hdr">State Yield Model Map'
            f' &nbsp;·&nbsp; <span style="color:{JPSI_BLUE}">{_sel_week_lbl}</span></div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "JSA analog model forecast per state at the selected week. "
            "Heatmap color = % vs trendline by default. Toggle to compare alternate metrics."
        )

        if sel_week is not None:
            _ymcwm   = {"HRW": _dynamic_hrw_weights, "SRW": _dynamic_srw_weights, "White": _dynamic_white_weights}
            _ym_stts = [s for s in _trend_data if s not in {"US", "HRW", "SRW", "White"}]
            _sfcast  = {}
            for _ms in _ym_stts:
                _mf = _compute_analog_forecast(
                    _ms, raw_df, _effective_week_ts(_ms), sel_usda_yr,
                    _yield_lookup, _trend_data, _dynamic_hrw_weights, class_weights_map=_ymcwm,
                    crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                    cond_weights=_active_cw,
                )
                if not _mf:
                    continue

                # ── Regression-based yield (matches KPI cards & Production table) ──
                # Best-fit linear or quadratic regression over ALL historical
                # JSA–yield deviation pairs, evaluated at cur_jsa (clamped to
                # training range). Trendline used if regression cannot run (< 3 pts).
                _ms_snap = _mf.get("jsa_snap", {})
                _ms_cur  = _mf.get("cur_jsa")
                _ms_td   = _trend_data.get(_ms)
                _ms_tl   = _trend_at(_ms_td, sel_usda_yr) if _ms_td else None
                _ms_lkup = _yield_lookup.get(_ms, {})
                _reg_forecast = None
                _reg_dev      = None
                if _ms_cur is not None and _ms_tl:
                    _rpts = [
                        (_ms_snap[cy], _ms_lkup[cy]["dev"])
                        for cy in _ms_snap
                        if cy != sel_usda_yr
                        and cy in _ms_lkup
                        and _ms_lkup[cy].get("dev") is not None
                    ]
                    if len(_rpts) >= 3:
                        _rx = np.array([p[0] for p in _rpts])
                        _ry = np.array([p[1] for p in _rpts])
                        _rss = float(np.sum((_ry - _ry.mean()) ** 2))
                        _rlc = np.linalg.lstsq(
                            np.vstack([_rx, np.ones(len(_rx))]).T, _ry, rcond=None
                        )[0]
                        _ms_cur_f = float(_ms_cur)
                        _rdev = float(_rlc[0] * _ms_cur_f + _rlc[1])
                        _raw_fc = _ms_tl * (1 + _rdev / 100)
                        _reg_forecast = round(_raw_fc, 1)
                        _reg_dev      = round(_rdev, 1)

                # Use regression result; fall back to trendline (never 6-analog average)
                _fc_val = _reg_forecast if _reg_forecast is not None else _ms_tl
                if _fc_val is None:
                    continue
                _vs_tr  = _dev_pct(_fc_val, _ms_tl) if _ms_tl else _reg_dev

                _msl  = _yield_lookup.get(_ms, {})
                _lyy  = _msl.get(sel_usda_yr - 1, {}).get("yield")
                _osrc = sorted([y for y in _msl if y < sel_usda_yr], reverse=True)[:6]
                _ov   = sorted([_msl[y]["yield"] for y in _osrc if _msl[y].get("yield") is not None])
                if len(_ov) >= 3:
                    _ov = _ov[1:-1]
                _oa = float(np.mean(_ov)) if _ov else None
                _sfcast[_ms] = {
                    "forecast":  _fc_val,
                    "vs_trend":  _vs_tr,
                    "vs_ly":     _dev_pct(_fc_val, _lyy) if _lyy else None,
                    "vs_oly":    _dev_pct(_fc_val, _oa)  if _oa  else None,
                    "n_analogs": _mf["n_analogs"],
                }

            if _sfcast:
                _ym_tog = st.radio(
                    "Color metric",
                    ["vs Trend %", "vs Last Year %", "vs Olympic Avg %", "Forecast (bu/ac)"],
                    horizontal=True, key="ym_tog",
                )
                _ym_key = {"vs Trend %": "vs_trend", "vs Last Year %": "vs_ly",
                           "vs Olympic Avg %": "vs_oly", "Forecast (bu/ac)": "forecast"}[_ym_tog]

                _ymdf = pd.DataFrame([
                    {"state_alpha": s, "value": d.get(_ym_key), **d}
                    for s, d in _sfcast.items() if d.get(_ym_key) is not None
                ]).dropna(subset=["value"])

                if not _ymdf.empty:
                    _ym_pct = _ym_key != "forecast"
                    if _ym_pct:
                        _ym_zmin, _ym_zmax = -15, 15
                        _ym_cs = DELTA_COLORSCALE
                    else:
                        _ym_zmin, _ym_zmax = None, None
                        # Light → dark JSA green for absolute yield view
                        _ym_cs = [
                            [0.00, "#e8f5e2"],
                            [0.25, "#a5d48e"],
                            [0.50, "#4caf50"],
                            [0.75, "#1e7a34"],
                            [1.00, "#0d3d1a"],
                        ]

                    _ym_hov = []
                    for _, _r in _ymdf.iterrows():
                        _vt = _r.get("vs_trend"); _vl = _r.get("vs_ly"); _vo = _r.get("vs_oly")
                        _parts = [
                            f"<b>{_r['state_alpha']}</b>",
                            f"Forecast: <b>{_r['forecast']:.1f} bu/ac</b>",
                            (f"vs Trend: <b>{'+'if _vt>=0 else ''}{_vt:.1f}%</b>" if pd.notna(_vt) else None),
                            (f"vs LY: <b>{'+'if _vl>=0 else ''}{_vl:.1f}%</b>"    if pd.notna(_vl) else None),
                            (f"vs Oly: <b>{'+'if _vo>=0 else ''}{_vo:.1f}%</b>"   if pd.notna(_vo) else None),
                            f"Analogs: {int(_r['n_analogs'])}",
                        ]
                        _ym_hov.append("<br>".join(x for x in _parts if x))

                    # Colorbar: show min/max ticks only for a cleaner look
                    _cb_vals = _ymdf["value"]
                    _cb_tick0, _cb_tick1 = round(_cb_vals.min(), 1), round(_cb_vals.max(), 1)
                    _ym_fig = go.Figure(go.Choropleth(
                        locations=_ymdf["state_alpha"], z=_ymdf["value"],
                        locationmode="USA-states",
                        colorscale=_ym_cs, zmin=_ym_zmin, zmax=_ym_zmax,
                        marker_line_color="#ffffff", marker_line_width=1.2,
                        hovertext=_ym_hov, hovertemplate="%{hovertext}<extra></extra>",
                        colorbar=dict(
                            thickness=14, len=0.55, x=1.01, y=0.5,
                            tickvals=[_cb_tick0, _cb_tick1] if not _ym_pct else None,
                            ticktext=[str(_cb_tick0), str(_cb_tick1)] if not _ym_pct else None,
                            title=dict(text=_ym_tog, font=dict(color=DM_MUTED, size=10)),
                            tickfont=dict(color=DM_MUTED, size=10),
                            outlinewidth=0,
                        ),
                    ))

                    # Labels — yield value (white, bold) + % vs metric (smaller, below)
                    _lbl_lats, _lbl_lons, _lbl_yield, _lbl_pct = [], [], [], []
                    # Normalise z for choosing label colour (dark states → white text)
                    _z_min = _ymdf["value"].min(); _z_max = _ymdf["value"].max()
                    _z_rng = max(_z_max - _z_min, 1e-6)
                    for _, _r in _ymdf.iterrows():
                        _st2 = _r["state_alpha"]
                        if _st2 not in STATE_CENTROIDS:
                            continue
                        _slat, _slon = STATE_CENTROIDS[_st2]
                        _vt2 = _r.get("vs_trend")
                        _vt_lbl = (f"{'+'if _vt2>=0 else ''}{_vt2:.1f}%" if pd.notna(_vt2) else "")
                        _lbl_lats.append(_slat); _lbl_lons.append(_slon)
                        _lbl_yield.append(f"{_r['forecast']:.1f}")
                        _lbl_pct.append(_vt_lbl)

                    # White labels on all states — strong contrast against the green gradient
                    _ym_fig.add_trace(go.Scattergeo(
                        lat=_lbl_lats, lon=_lbl_lons,
                        text=_lbl_yield, mode="text",
                        textfont=dict(size=12, color="#ffffff", family="Arial Black"),
                        showlegend=False, hoverinfo="skip",
                    ))
                    _ym_fig.add_trace(go.Scattergeo(
                        lat=[l - 0.85 for l in _lbl_lats], lon=_lbl_lons,
                        text=_lbl_pct, mode="text",
                        textfont=dict(size=8, color="#ffffff", family="Arial"),
                        showlegend=False, hoverinfo="skip",
                    ))

                    _map_title = f"JSA Yield Model by State — {commodity_label} {selected_mkt}"
                    _ym_fig.update_layout(
                        title=dict(text=_map_title, x=0.5, xanchor="center",
                                   font=dict(size=14, color=DM_TEXT, family="Arial Black")),
                        geo=dict(scope="usa", showlakes=False, bgcolor="#ffffff",
                                 landcolor="#e8e8e8", subunitcolor="#ffffff",
                                 framecolor="#ffffff"),
                        paper_bgcolor="#ffffff",
                        margin=dict(l=0, r=0, t=40, b=10),
                        height=480, dragmode=False,
                    )
                    _wm_map(_ym_fig)
                    _show_chart(_ym_fig, "yield_model")
            else:
                st.info("No state forecasts available — insufficient yield history for this week.")
        else:
            st.info("Select a marketing week to generate state yield forecasts.")

        # ── Yield detail table ─────────────────────────────────────────────────────
        st.markdown(
            f'<div class="sec-hdr">State Yield Detail — {selected_mkt} Marketing Year</div>',
            unsafe_allow_html=True,
        )
        _prior_harvest_yr  = sel_usda_yr - 1
        st.caption(
            f"JSA Model = analog-adjusted yield forecast for {selected_mkt}. "
            f"Δ Trend = (JSA Model − Trendline) ÷ Trendline × 100. "
            f"Prior Yr = final reported yield for {prior_mkt_label}. "
            f"% vs Prior Yr = (JSA Model − Prior Yr) ÷ Prior Yr × 100."
        )

        # Build state → wheat class abbreviation lookup
        _class_abbr = {"HRW — Hard Red Winter": "HRW", "SRW — Soft Red Winter": "SRW", "White Winter": "White"}
        _state_class_map = {}
        for _cls_name, _cls_states in WHEAT_CLASSES.items():
            if _cls_states is None:
                continue
            for _st in _cls_states:
                _state_class_map[_st] = _class_abbr.get(_cls_name, _cls_name)

        # ── Helper: adjusted R² (penalises extra parameters vs linear) ──────────────
        def _adj_r2(r2: float, n: int, p: int) -> float:
            """Adjusted R²: penalises p predictors given n observations."""
            if n <= p + 1:
                return r2
            return 1.0 - (1.0 - r2) * (n - 1) / (n - p - 1)

        _synthetic_keys = {"US", "HRW", "SRW", "White"}
        _yield_rows  = []
        _fit_cmp_rows = []   # model-fit comparison rows for the expander
        for _sk in (["US", "HRW", "SRW", "White"] + sorted(
                [s for s in _trend_data if s not in _synthetic_keys])):
            if _sk not in _synthetic_keys:
                if _class_states is not None and _sk not in _class_states:
                    continue
                if _significant_states and _sk not in _significant_states:
                    continue
            if _sk not in _trend_data:
                continue
            _td   = _trend_data[_sk]
            _rows = _yield_full[_yield_full["state_alpha"] == _sk].sort_values("year")
            if _rows.empty:
                continue
            _name = ("🇺🇸  US Total"    if _sk == "US"
                     else "⬡  HRW Index"   if _sk == "HRW"
                     else "⬡  SRW Index"   if _sk == "SRW"
                     else "⬡  White Index" if _sk == "White"
                     else _td["state_name"])
            _wclass = ("All"   if _sk == "US"
                       else _sk  if _sk in ("HRW", "SRW", "White")
                       else _state_class_map.get(_sk, "—"))

            # Need _af for jsa_snap / cur_jsa (used by scatter + seasonal chart)
            _af = _compute_analog_forecast(
                _sk, raw_df, _effective_week_ts(_sk), sel_usda_yr,
                _yield_lookup, _trend_data, _dynamic_hrw_weights,
                class_weights_map={"HRW": _dynamic_hrw_weights, "SRW": _dynamic_srw_weights, "White": _dynamic_white_weights},
                crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                cond_weights=_active_cw,
            )
            _cur_trendline = _trend_at(_td, sel_usda_yr)

            # JSA Model — linear OLS regression (JSA index → yield deviation)
            _jsa_model   = float("nan")
            _delta_trend = float("nan")
            if _af and _cur_trendline:
                _m2_snap    = _af.get("jsa_snap", {})
                _m2_cur_jsa = _af.get("cur_jsa")
                _m2_lkup    = _yield_lookup.get(_sk, {})
                if _m2_cur_jsa is not None:
                    _m2_pts = [
                        (_m2_snap[cy], _m2_lkup[cy]["dev"])
                        for cy in _m2_snap
                        if cy != sel_usda_yr
                        and cy in _m2_lkup
                        and _m2_lkup[cy].get("dev") is not None
                    ]
                    if len(_m2_pts) >= 3:
                        _m2_x  = np.array([p[0] for p in _m2_pts])
                        _m2_y  = np.array([p[1] for p in _m2_pts])
                        _m2_n  = len(_m2_pts)
                        _ss_tot = float(np.sum((_m2_y - _m2_y.mean()) ** 2))

                        # Linear OLS fit (always used — linear only, no quadratic)
                        _lin_coeffs = np.linalg.lstsq(
                            np.vstack([_m2_x, np.ones(_m2_n)]).T, _m2_y, rcond=None
                        )[0]
                        _lin_yhat  = _lin_coeffs[0] * _m2_x + _lin_coeffs[1]
                        _lin_r2    = (1.0 - float(np.sum((_m2_y - _lin_yhat)**2)) / _ss_tot
                                      if _ss_tot > 0 else 0.0)
                        _lin_adj   = _adj_r2(_lin_r2, _m2_n, 1)

                        _m2_cur_jsa_f = float(_m2_cur_jsa)
                        _m2_pred_dev  = float(_lin_coeffs[0] * _m2_cur_jsa_f + _lin_coeffs[1])

                        _m2_raw_yield = _cur_trendline * (1 + _m2_pred_dev / 100)
                        _jsa_model   = round(_m2_raw_yield, 1)
                        _delta_trend = round(_m2_pred_dev, 1)

                        # Store for fit-comparison expander
                        _fit_cmp_rows.append({
                            "State":         _name,
                            "n pts":         _m2_n,
                            "Linear R²":     round(_lin_r2 * 100, 1),
                            "Linear Adj R²": round(_lin_adj * 100, 1),
                        })
            # Fallback to trendline if regression can't run
            if np.isnan(_jsa_model) and _cur_trendline:
                _jsa_model = round(_cur_trendline, 1)

            # Prior year final yield (harvest year = sel_usda_yr - 1)
            _py_row = _rows[_rows["year"] == _prior_harvest_yr]
            if not _py_row.empty:
                _py_act    = round(float(_py_row.iloc[-1]["yield_bu_ac"]), 1)
                _chg_vs_py = round((_jsa_model - _py_act) / _py_act * 100, 1) if _py_act and not np.isnan(_jsa_model) else float("nan")
            else:
                _py_act    = float("nan")
                _chg_vs_py = float("nan")

            _share_val = (100.0 if _sk == "US"
                          else sum(_state_share_pct.get(s, 0) for s in _dynamic_hrw_weights)   if _sk == "HRW"
                          else sum(_state_share_pct.get(s, 0) for s in _dynamic_srw_weights)   if _sk == "SRW"
                          else sum(_state_share_pct.get(s, 0) for s in _dynamic_white_weights) if _sk == "White"
                          else _state_share_pct.get(_sk, 0.0))

            _yield_rows.append({
                "State":                        _name,
                "Share %":                      _share_val,
                "Class":                        _wclass,
                "JSA Model (bu/ac)":            _jsa_model,
                "Δ Trend":                      _delta_trend,
                f"Prior Yr — {prior_mkt_label} (bu/ac)": _py_act,
                "% vs Prior Yr":                _chg_vs_py,
                "R²":                           round(_td["r2"] * 100, 1),
                "_order":                       (0 if _sk == "US" else 1 if _sk == "HRW" else 2 if _sk == "SRW" else 3 if _sk == "White" else 4),
            })

        if _yield_rows:
            _ytbl = (pd.DataFrame(_yield_rows)
                     .sort_values(["_order", "Share %"], ascending=[True, False])
                     .drop(columns=["_order"])
                     .reset_index(drop=True))
            # Remove wheat-class column for non-has_classes commodities
            if not commodity_cfg.get("has_classes", True):
                _ytbl = _ytbl.drop(columns=["Class"], errors="ignore")

            _dev_max   = max(abs(_ytbl["Δ Trend"].dropna()).max(), 1.0)
            _chg_max   = max(abs(_ytbl["% vs Prior Yr"].dropna()).max(), 1.0)
            _r2_lo     = float(_ytbl["R²"].min())
            _r2_hi     = float(_ytbl["R²"].max())
            _sh_lo     = float(_ytbl["Share %"].min())
            _sh_hi     = float(_ytbl["Share %"].max())
            _py_col    = f"Prior Yr — {prior_mkt_label} (bu/ac)"

            _class_colors = {"HRW": "#f59e0b", "SRW": JPSI_BLUE, "White": "#a78bfa", "All": DM_MUTED, "—": DM_MUTED}

            def _ystyle(row):
                base = f"background-color:{DM_SURFACE};color:{DM_TEXT}"
                s    = {c: base for c in _ytbl.columns}
                s["State"] = f"{base};font-weight:600"
                s["Share %"] = f"background-color:{DM_SURFACE};color:{DM_MUTED}"
                if "Class" in _ytbl.columns:
                    cls_color = _class_colors.get(row["Class"], DM_MUTED)
                    s["Class"] = f"background-color:{DM_SURFACE2};color:{cls_color};font-weight:700;text-align:center"
                dv = row["Δ Trend"]
                if pd.notna(dv):
                    s["Δ Trend"] = _cell_css(_div_bg(dv, _dev_max))
                cv = row["% vs Prior Yr"]
                if pd.notna(cv):
                    s["% vs Prior Yr"] = _cell_css(_div_bg(cv, _chg_max))
                r2 = row["R²"]
                if pd.notna(r2):
                    s["R²"] = _cell_css(_green_only_bg(r2, _r2_lo, _r2_hi))
                return pd.Series(s)

            _ystyled = (
                _ytbl.style
                .apply(_ystyle, axis=1)
                .format({
                    "Share %":           lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
                    "JSA Model (bu/ac)": lambda x: f"{x:.1f}" if pd.notna(x) else "N/A",
                    _py_col:             lambda x: f"{x:.1f}" if pd.notna(x) else "N/A",
                    "Δ Trend":           lambda x: f"{x:+.1f}%" if pd.notna(x) else "N/A",
                    "% vs Prior Yr":     lambda x: f"{x:+.1f}%" if pd.notna(x) else "N/A",
                    "R²":                lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
                })
                .hide(axis="index")
                .set_table_styles([
                    {"selector": "thead th", "props": [
                        ("background-color", DM_SURFACE2), ("color", DM_TEXT),
                        ("font-weight", "700"),
                        ("border-bottom", f"2px solid {JPSI_BLUE}"),
                    ]},
                    {"selector": "table", "props": [("background-color", DM_SURFACE)]},
                ])
            )
            _tbl_h = min(46 * len(_ytbl) + 56, 560)
            st.dataframe(_ystyled, use_container_width=True, height=_tbl_h)
            _dl_btn(_ytbl, f"state_yield_detail_{selected_mkt.replace('/','_')}.xlsx",
                    "⬇ Download Yield Detail Table")

            # ── Model fit summary expander ─────────────────────────────────────────
            if _fit_cmp_rows:
                with st.expander(
                    f"📐 JSA Model — Linear Regression Fit Summary "
                    f"({len(_fit_cmp_rows)} series)",
                    expanded=False,
                ):
                    st.caption(
                        "Linear OLS regression of JSA Condition Index vs. yield deviation "
                        "from trend, fitted per state. Adj R² penalises for sample size."
                    )
                    _fcmp_df = pd.DataFrame(_fit_cmp_rows)

                    def _fcmp_style(row):
                        base = f"background-color:{DM_SURFACE};color:{DM_TEXT}"
                        s    = {c: base for c in _fcmp_df.columns}
                        s["State"] = f"{base};font-weight:600"
                        s["n pts"] = f"background-color:{DM_SURFACE};color:{DM_MUTED}"
                        return pd.Series(s)

                    _fcmp_styled = (
                        _fcmp_df.style
                        .apply(_fcmp_style, axis=1)
                        .format({
                            "Linear R²":     lambda x: f"{x:.1f}%",
                            "Linear Adj R²": lambda x: f"{x:.1f}%",
                        })
                        .hide(axis="index")
                        .set_table_styles([
                            {"selector": "thead th", "props": [
                                ("background-color", DM_SURFACE2), ("color", DM_TEXT),
                                ("font-weight", "700"),
                                ("border-bottom", f"2px solid {JPSI_BLUE}"),
                            ]},
                            {"selector": "table", "props": [("background-color", DM_SURFACE)]},
                        ])
                    )
                    _fc_h = min(46 * len(_fcmp_df) + 56, 560)
                    st.dataframe(_fcmp_styled, use_container_width=True, height=_fc_h)

    # ── JSA Conditions Index vs. Yield Deviation Scatter ─────────────────────────
    # Class radio (only when no state is selected — state scatter uses state data)
    if sel_state_alpha:
        _sc_cls_key   = sel_state_alpha
        _sc_cls_label = _series_label
    else:
        if commodity_cfg.get("has_classes", True):
            _sc_cls_opts = ["US Total", "HRW", "SRW", "White"]
            _sc_cls_default_lbl = (
                "HRW"   if "HRW"   in wheat_class else
                "SRW"   if "SRW"   in wheat_class else
                "White" if "White" in wheat_class else
                "US Total"
            )
        else:
            _sc_cls_opts = ["US Total"]
            _sc_cls_default_lbl = "US Total"
        _sc_cls_sel = st.radio(
            "Index series",
            _sc_cls_opts,
            index=_sc_cls_opts.index(_sc_cls_default_lbl),
            horizontal=True,
            key="sc_cls_radio",
        )
        _sc_cls_key = {"US Total": "US", "HRW": "HRW", "SRW": "SRW", "White": "White"}.get(_sc_cls_sel, "US")
        _sc_cls_label = {"US": "US Total", "HRW": "HRW Index", "SRW": "SRW Index", "White": "White Index"}.get(_sc_cls_key, "National")

    # Build lock-status label for the scatter header
    _sc_eff_ts   = _effective_week_ts(_sc_cls_key)
    _sc_bw_info  = _best_week_res.get(_sc_cls_key, {})
    _sc_best_iso = _sc_bw_info.get("best_iso")
    _sc_best_r2  = _sc_bw_info.get("r2")
    _sc_locked   = (
        _sc_best_iso is not None
        and _cur_iso_week is not None
        and _cur_iso_week >= int(_sc_best_iso)
    )
    if _sc_locked and _sc_eff_ts is not None:
        _sc_lock_lbl = (
            f'&nbsp;·&nbsp;<span style="color:#f59e0b;font-size:0.8em">'
            f'📌 Locked to Wk&nbsp;{_sc_best_iso}'
            f' ({_sc_eff_ts.strftime("%b %d")})'
            f' — peak R²&nbsp;{_sc_best_r2*100:.0f}%</span>'
            if _sc_best_r2 is not None else
            f'&nbsp;·&nbsp;<span style="color:#f59e0b;font-size:0.8em">'
            f'📌 Locked to Wk&nbsp;{_sc_best_iso} ({_sc_eff_ts.strftime("%b %d")})</span>'
        )
        _sc_week_lbl = f"{_sc_eff_ts.strftime('%b %d')} Wk {int(_sc_eff_ts.isocalendar().week)}"
    else:
        _sc_lock_lbl = (
            f'&nbsp;·&nbsp;<span style="color:{DM_MUTED};font-size:0.8em">'
            f'🔓 Live — best week Wk&nbsp;{_sc_best_iso} not yet reached</span>'
            if _sc_best_iso else ""
        )
        _sc_week_lbl = (f"{pd.Timestamp(sel_week).strftime('%b %d')} Wk {int(pd.Timestamp(sel_week).isocalendar().week)}"
                        if sel_week else "—")

    st.markdown(
        f'<div class="sec-hdr">JSA Condition Index vs. Yield Deviation from Trend'
        f' &nbsp;·&nbsp; <span style="color:{JPSI_BLUE}">{_sc_cls_label}</span>'
        f'{_sc_lock_lbl}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Each point is a historical marketing year. "
        f"X-axis: JSA condition index at {'best-signal' if _sc_locked else 'selected'}"
        f" week ({_sc_week_lbl})"
        + (f" — locked to peak-R² week once passed" if _sc_locked else
           f" — will lock to Wk {_sc_best_iso} once reached" if _sc_best_iso else "")
        + f". Y-axis: final yield deviation from trendline."
        f" Star marks where the current JSA index falls on the best-fit regression line — the model's yield estimate."
    )

    _sc_result = _class_analog_results.get(_sc_cls_key) if not sel_state_alpha else _analog_result
    if _sc_result and sel_week is not None:
        _sc_jsa_snap = _sc_result["jsa_snap"]   # {crop_year: jsa_val}
        _sc_cur_jsa  = _sc_result["cur_jsa"]

        # Build scatter points: historical years with final yield
        _sc_rows = []
        _sc_lkup = _yield_lookup.get(_sc_cls_key, {})
        for _sc_yr, _sc_jv in _sc_jsa_snap.items():
            if _sc_yr == sel_usda_yr:
                continue
            _sc_yd = _sc_lkup.get(_sc_yr)
            if _sc_yd and _sc_yd.get("dev") is not None:
                _sc_rows.append({"year": _sc_yr, "jsa": _sc_jv, "dev": _sc_yd["dev"]})

        if _sc_rows:
            _sc_df = pd.DataFrame(_sc_rows)

            # ── Fit linear + quadratic; pick best by R² ──────────────────────────
            _sc_x  = _sc_df["jsa"].values
            _sc_y  = _sc_df["dev"].values
            _sc_ss_tot = float(np.sum((_sc_y - _sc_y.mean()) ** 2))

            # Linear OLS
            _sc_A   = np.vstack([_sc_x, np.ones(len(_sc_x))]).T
            _sc_lin = np.linalg.lstsq(_sc_A, _sc_y, rcond=None)[0]
            _sc_slope, _sc_intercept = float(_sc_lin[0]), float(_sc_lin[1])
            _sc_lin_yhat = _sc_slope * _sc_x + _sc_intercept
            _sc_lin_r2   = (1 - float(np.sum((_sc_y - _sc_lin_yhat) ** 2)) / _sc_ss_tot
                            if _sc_ss_tot > 0 else 0.0)

            # Linear regression only — always straight line
            _sc_r2        = _sc_lin_r2
            _sc_reg_dev   = _sc_slope * float(_sc_cur_jsa) + _sc_intercept

            _sc_xmin  = min(float(_sc_x.min()), float(_sc_cur_jsa)) - 3
            _sc_xmax  = max(float(_sc_x.max()), float(_sc_cur_jsa)) + 3
            _sc_xline = [_sc_xmin, _sc_xmax]
            _sc_yline = [_sc_slope * v + _sc_intercept for v in _sc_xline]

            # Vertical divider: where regression line crosses y=0
            _sc_x_cross = (-_sc_intercept / _sc_slope
                           if abs(_sc_slope) > 1e-9 else (_sc_xmin + _sc_xmax) / 2)
            _sc_x_cross = max(_sc_xmin + 1, min(_sc_xmax - 1, _sc_x_cross))

            # Y range for shapes (include regression estimate for current year)
            _sc_ylo = min(float(_sc_y.min()), _sc_reg_dev) - 3
            _sc_yhi = max(float(_sc_y.max()), _sc_reg_dev) + 3

            _sc_fig = go.Figure()

            # Quadrant colored rectangles (rgba — plotly doesn't accept hex+alpha)
            _sc_quads = [
                # top-right: strong conditions, above trend → green
                dict(x0=_sc_x_cross, x1=_sc_xmax + 5, y0=0, y1=_sc_yhi + 5,
                     fillcolor="rgba(26,152,80,0.13)", line_color="rgba(0,0,0,0)"),
                # top-left: weak conditions but above trend → muted blue/indigo
                dict(x0=_sc_xmin - 5, x1=_sc_x_cross, y0=0, y1=_sc_yhi + 5,
                     fillcolor="rgba(99,102,241,0.10)", line_color="rgba(0,0,0,0)"),
                # bottom-right: strong conditions but below trend → amber
                dict(x0=_sc_x_cross, x1=_sc_xmax + 5, y0=_sc_ylo - 5, y1=0,
                     fillcolor="rgba(245,158,11,0.11)", line_color="rgba(0,0,0,0)"),
                # bottom-left: weak conditions, below trend → red
                dict(x0=_sc_xmin - 5, x1=_sc_x_cross, y0=_sc_ylo - 5, y1=0,
                     fillcolor="rgba(215,48,39,0.14)", line_color="rgba(0,0,0,0)"),
            ]
            for _q in _sc_quads:
                _sc_fig.add_shape(type="rect", layer="below", **_q)

            # Above / Below trend band labels (subtle)
            _sc_fig.add_shape(type="line",
                x0=_sc_xmin - 5, x1=_sc_xmax + 5, y0=0, y1=0,
                line=dict(color=DM_MUTED, width=1, dash="dot"), layer="below")
            _sc_fig.add_shape(type="line",
                x0=_sc_x_cross, x1=_sc_x_cross, y0=_sc_ylo - 5, y1=_sc_yhi + 5,
                line=dict(color=DM_MUTED, width=1, dash="dot"), layer="below")

            # Historical scatter points
            _sc_colors = [
                "#1a9850" if d >= 0 else "#d73027" for d in _sc_df["dev"]
            ]
            _sc_hover = [
                f"<b>{mkt_label(int(r['year']))}</b><br>JSA Index: {r['jsa']:.1f}<br>"
                f"Δ Trend: {'+'if r['dev']>=0 else ''}{r['dev']:.1f}%"
                for _, r in _sc_df.iterrows()
            ]
            _sc_fig.add_trace(go.Scatter(
                x=_sc_df["jsa"].tolist(),
                y=_sc_df["dev"].tolist(),
                mode="markers+text",
                marker=dict(size=9, color=_sc_colors, opacity=0.80,
                            line=dict(color=DM_BG, width=1)),
                text=[mkt_label_short(int(y)) for y in _sc_df["year"]],
                textposition="top center",
                textfont=dict(size=9, color=DM_MUTED),
                hovertext=_sc_hover,
                hovertemplate="%{hovertext}<extra></extra>",
                name="Historical years",
                showlegend=False,
            ))

            # Best-fit regression line/curve
            _sc_fig.add_trace(go.Scatter(
                x=_sc_xline, y=_sc_yline,
                mode="lines",
                line=dict(color=JPSI_BLUE, width=1.5, dash="dash"),
                name=f"Linear regression  (R\u00b2={_sc_r2*100:.0f}%)",
                showlegend=True,
                hoverinfo="skip",
            ))

            # Crosshair drop lines for current year's model estimate
            _sc_fig.add_shape(type="line",
                x0=float(_sc_cur_jsa), x1=float(_sc_cur_jsa),
                y0=_sc_ylo, y1=_sc_reg_dev,
                line=dict(color="#f59e0b", width=1, dash="dot"), layer="above")
            _sc_fig.add_shape(type="line",
                x0=_sc_xmin, x1=float(_sc_cur_jsa),
                y0=_sc_reg_dev, y1=_sc_reg_dev,
                line=dict(color="#f59e0b", width=1, dash="dot"), layer="above")

            # Estimated yield bu/ac for the star label
            _sc_trendline_now = _trend_at(_trend_data.get(_sc_cls_key, {}), sel_usda_yr)
            _sc_est_yield     = (round(_sc_trendline_now * (1 + _sc_reg_dev / 100), 1)
                                 if _sc_trendline_now else None)

            # Current year star \u2014 plotted ON the regression line
            _sc_fig.add_trace(go.Scatter(
                x=[float(_sc_cur_jsa)],
                y=[_sc_reg_dev],
                mode="markers+text",
                marker=dict(size=18, symbol="star", color="#f59e0b",
                            line=dict(color=DM_BG, width=1)),
                text=[mkt_label_short(sel_usda_yr)],
                textposition="top center",
                textfont=dict(size=10, color="#f59e0b", family="Arial Black"),
                hovertemplate=(
                    f"<b>{mkt_label(sel_usda_yr)} \u2014 Model Estimate</b><br>"
                    f"JSA Index: {float(_sc_cur_jsa):.1f}<br>"
                    f"Reg. \u0394 Trend: {'+' if _sc_reg_dev >= 0 else ''}{_sc_reg_dev:.1f}%"
                    + (f"<br>Est. Yield: <b>{_sc_est_yield:.1f} bu/ac</b>" if _sc_est_yield else "")
                    + f"<extra></extra>"
                ),
                name=f"{mkt_label(sel_usda_yr)} model estimate",
                showlegend=True,
            ))

            # R² annotation — prominent, top-center just below band label
            _sc_fig.add_annotation(
                x=0.5, y=0.89, xanchor="center", yanchor="top",
                xref="paper", yref="paper",
                showarrow=False,
                text=f"Linear  R² = {_sc_r2*100:.0f}%",
                font=dict(size=15, color=JPSI_BLUE, family="Arial Black"),
            )

            # Corner labels
            _lbl_kw = dict(
                xref="paper", yref="paper",
                showarrow=False,
                font=dict(size=12, color=DM_TEXT),
                opacity=1.0,
            )
            _sc_fig.add_annotation(x=0.98, y=0.98, xanchor="right", yanchor="top",
                text="Strong Conditions / Above Trend", **_lbl_kw)
            _sc_fig.add_annotation(x=0.02, y=0.98, xanchor="left", yanchor="top",
                text="Weak Conditions / Above Trend", **_lbl_kw)
            _sc_fig.add_annotation(x=0.98, y=0.02, xanchor="right", yanchor="bottom",
                text="Strong Conditions / Below Trend", **_lbl_kw)
            _sc_fig.add_annotation(x=0.02, y=0.02, xanchor="left", yanchor="bottom",
                text="Weak Conditions / Below Trend", **_lbl_kw)

            # Band labels: ABOVE TREND / BELOW TREND
            _sc_fig.add_annotation(x=0.5, y=0.96, xanchor="center", yanchor="top",
                text="▲ ABOVE TREND",
                showarrow=False,
                font=dict(size=13, color="rgba(26,152,80,0.70)"),
                xref="paper", yref="paper",
            )
            _sc_fig.add_annotation(x=0.5, y=0.04, xanchor="center", yanchor="bottom",
                text="▼ BELOW TREND",
                showarrow=False,
                font=dict(size=13, color="rgba(215,48,39,0.70)"),
                xref="paper", yref="paper",
            )

            # Logo watermark
            _sc_wm_src = _chart_logo_uri or _logo_uri
            if _sc_wm_src:
                _sc_fig.add_layout_image(
                    source=_sc_wm_src,
                    xref="paper", yref="paper",
                    x=0.5, y=0.5,
                    xanchor="center", yanchor="middle",
                    sizex=0.55, sizey=0.55,
                    opacity=0.07,
                    layer="below",
                )

            _sc_fig.update_layout(
                xaxis=dict(
                    title="JSA Condition Index",
                    showgrid=True, gridcolor=DM_BORDER,
                    color=DM_MUTED, tickfont=dict(color=DM_MUTED),
                    title_font=dict(color=DM_MUTED),
                    range=[_sc_xmin, _sc_xmax],
                ),
                yaxis=dict(
                    title="Yield Deviation from Trend (%)",
                    showgrid=True, gridcolor=DM_BORDER,
                    color=DM_MUTED, tickfont=dict(color=DM_MUTED),
                    title_font=dict(color=DM_MUTED),
                    ticksuffix="%",
                    range=[_sc_ylo, _sc_yhi],
                ),
                paper_bgcolor=DM_BG,
                plot_bgcolor=DM_SURFACE2,
                margin=dict(l=60, r=20, t=20, b=60),
                height=480,
                hovermode="closest",
                legend=dict(
                    orientation="h",
                    x=0.5, y=-0.12,
                    xanchor="center",
                    font=dict(color=DM_MUTED, size=11),
                    bgcolor="rgba(0,0,0,0)",
                ),
            )
            _show_chart(_sc_fig, "seasonal_conditions")

            # ── Weekly condition change bars (companion panel below scatter) ──────────
            if not sel_data.empty and len(sel_data) >= 2:
                _sc_delta_df = sel_data.sort_values("season_dt").copy()
                _sc_delta_df["delta"] = _sc_delta_df["cond_pct"].diff()
                _sc_delta_df = _sc_delta_df.dropna(subset=["delta"])
                _sc_bar_colors = [
                    "rgba(26,152,80,0.85)" if d >= 0 else "rgba(180,100,50,0.85)"
                    for d in _sc_delta_df["delta"]
                ]
                _sc_delta_fig = go.Figure(go.Bar(
                    x=_sc_delta_df["season_dt"].tolist(),
                    y=_sc_delta_df["delta"].tolist(),
                    marker_color=_sc_bar_colors,
                    hovertemplate="%{x|%b %d} (Wk %{customdata}): %{y:+.1f}%<extra></extra>",
                    customdata=[int(pd.Timestamp(d).isocalendar().week)
                                for d in _sc_delta_df["week_ending"]],
                    width=5 * 24 * 60 * 60 * 1000,
                ))
                _sc_delta_fig.add_hline(y=0, line_color=DM_MUTED, line_width=1)
                _sc_delta_fig.update_layout(
                    xaxis=dict(
                        tickvals=tick_dates,
                        ticktext=tick_labels,
                        showgrid=True, gridcolor=DM_BORDER,
                        color=DM_MUTED, tickfont=dict(color=DM_MUTED),
                        **({'range': _x_range} if _x_range else {}),
                    ),
                    yaxis=dict(
                        title="Wk Δ (%)",
                        gridcolor=DM_BORDER, zeroline=False,
                        color=DM_MUTED, tickfont=dict(color=DM_MUTED),
                        title_font=dict(color=DM_MUTED, size=10),
                        ticksuffix="%",
                    ),
                    paper_bgcolor=DM_BG,
                    plot_bgcolor=DM_SURFACE2,
                    margin=dict(l=60, r=20, t=4, b=50),
                    height=160,
                    showlegend=False,
                    hovermode="x unified",
                )
                _show_chart(_sc_delta_fig, "seasonal_conditions_delta")

    elif sel_week is None:
        st.info("Select a marketing week to generate the scatter plot.")

    # ── Yield vs. 40-Year Trendline (1985 – present) ──────────────────────────────
    st.markdown('<div class="sec-hdr">Yield vs. Trendline (1985–Present)</div>', unsafe_allow_html=True)

    if _yield_full.empty:
        st.warning("Could not load yield data from USDA NASS. Try refreshing.")
    else:
        st.markdown("<div style='margin-top:0.6rem'></div>", unsafe_allow_html=True)

        # ── Yield trend chart ──────────────────────────────────────────────────────
        # Chart follows the same state selection as the rest of the dashboard
        _ych_key  = (sel_state_alpha if sel_state_alpha
                     else ("HRW" if _use_hrw_index else "US"))
        _ych_name = ("HRW Index"   if _ych_key == "HRW"
                     else "US Total" if _ych_key == "US"
                     else next((r["state_name"] for _, r in result.iterrows()
                                 if r["state_alpha"] == _ych_key), _ych_key))

        st.markdown(
            f'<div class="sec-hdr">Yield History & Trendline — {_ych_name}</div>',
            unsafe_allow_html=True,
        )

        if _ych_key in _trend_data:
            _td   = _trend_data[_ych_key]
            _hist = (_yield_full[_yield_full["state_alpha"] == _ych_key]
                     .sort_values("year"))

            # Trendline from first data year up to selected marketing year harvest
            _x_tr = list(range(min(_td["years"]), sel_usda_yr + 1))
            _y_tr = [_trend_at(_td, y) for y in _x_tr]

            # Convert harvest years → marketing year labels for hover
            _hist_mkt  = [_yield_mkt_lbl(int(y)) for y in _hist["year"]]
            _trend_mkt = [_yield_mkt_lbl(y) for y in _x_tr]

            _fig_yld = go.Figure()

            _fig_yld.add_trace(go.Scatter(
                x=_hist["year"].tolist(),
                y=_hist["yield_bu_ac"].tolist(),
                mode="lines+markers",
                name="Actual Yield",
                line=dict(color=JPSI_BLUE, width=1.8),
                marker=dict(size=5, color=JPSI_BLUE),
                customdata=_hist_mkt,
                hovertemplate="<b>%{customdata}</b>: %{y:.1f} bu/ac<extra>Actual</extra>",
            ))

            _fig_yld.add_trace(go.Scatter(
                x=_x_tr,
                y=_y_tr,
                mode="lines",
                name=f"Trendline  (R²={_td['r2']:.3f})",
                line=dict(color="#f59e0b", width=1.6, dash="dash"),
                customdata=_trend_mkt,
                hovertemplate="<b>%{customdata}</b>: %{y:.1f} bu/ac<extra>Trend</extra>",
            ))

            _fig_yld.update_layout(
                annotations=[dict(
                    x=0.01, y=0.97, xref="paper", yref="paper",
                    text=(f"<b>{_td['equation']}</b>"
                          f"&nbsp;&nbsp; R² = {_td['r2']:.3f}"
                          f"&nbsp;&nbsp; n = {_td['n']} yrs"),
                    showarrow=False,
                    font=dict(size=11, color=DM_TEXT),
                    align="left",
                    bgcolor=DM_SURFACE2,
                    bordercolor=DM_BORDER,
                    borderwidth=1,
                    borderpad=5,
                )],
                xaxis=dict(
                    title="Harvest Year",
                    dtick=5,
                    showgrid=True, gridcolor=DM_BORDER,
                    color=DM_MUTED, tickfont=dict(color=DM_MUTED),
                    title_font=dict(color=DM_MUTED),
                ),
                yaxis=dict(
                    title="Yield (bu/acre)",
                    showgrid=True, gridcolor=DM_BORDER,
                    color=DM_MUTED, tickfont=dict(color=DM_MUTED),
                    title_font=dict(color=DM_MUTED),
                ),
                paper_bgcolor=DM_BG,
                plot_bgcolor=DM_SURFACE2,
                legend=dict(
                    bgcolor=DM_SURFACE, bordercolor=DM_BORDER, borderwidth=1,
                    font=dict(color=DM_TEXT),
                ),
                margin=dict(l=10, r=10, t=20, b=10),
                height=380,
                hovermode="x unified",
            )
            _wm_center(_fig_yld)
            _show_chart(_fig_yld, "yield_history")
        else:
            st.info(f"No yield trend data available for {_ych_name}.")


with _tab_validation:
    if not _yield_full.empty:
        # ── HRW Model Validation: Weighted Estimate vs. USDA Official HRW Final ────
        if commodity_cfg.get("has_classes", True) and (not _hrw_nass_us.empty or not _hrw_weighted_df.empty):
            st.markdown(
                '<div class="sec-hdr">HRW Weighted Yield vs. USDA Official HRW — Model Validation</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "Compares our production-weighted HRW yield estimate (dynamic state weights × state Winter Wheat yields) "
                "against the NASS-published U.S. national Winter Wheat yield (blue line — note this is All Winter "
                "Wheat, not HRW-specific; the exact HRW benchmark is in the Backtest section below).  "
                "Deviation = Weighted Estimate − NASS US Winter Wheat.  "
                "Trendlines are independent OLS fits (1985–present)."
            )

        if commodity_cfg.get("has_classes", True) and not _hrw_nass_us.empty and not _hrw_weighted_df.empty:
            _val_cmp = pd.merge(
                _hrw_nass_us[["year", "yield_bu_ac"]].rename(columns={"yield_bu_ac": "nass_hrw"}),
                _hrw_weighted_df[["year", "yield_bu_ac"]].rename(columns={"yield_bu_ac": "wtd_hrw"}),
                on="year", how="inner",
            ).sort_values("year")

            _val_cmp["deviation"] = _val_cmp["wtd_hrw"] - _val_cmp["nass_hrw"]
            _val_cmp["dev_pct"]   = (_val_cmp["wtd_hrw"] - _val_cmp["nass_hrw"]) / _val_cmp["nass_hrw"] * 100

            # ── Accuracy stats ──────────────────────────────────────────────────────
            _rmse  = float(np.sqrt(np.mean(_val_cmp["deviation"] ** 2)))
            _mae   = float(_val_cmp["deviation"].abs().mean())
            _bias  = float(_val_cmp["deviation"].mean())
            _corr  = float(_val_cmp["nass_hrw"].corr(_val_cmp["wtd_hrw"]))
            _n_cmp = len(_val_cmp)

            _stat_cols = st.columns(4)
            for _sc, (_sv, _sl) in zip(_stat_cols, [
                (f"{_rmse:.2f} bu/ac",        f"RMSE  (n={_n_cmp} yrs)"),
                (f"{_mae:.2f} bu/ac",         "Mean Abs Error"),
                (f"{'+' if _bias>=0 else ''}{_bias:.2f} bu/ac", "Mean Bias (Wtd − NASS)"),
                (f"{_corr:.4f}",              "Pearson R (yield series)"),
            ]):
                with _sc:
                    st.markdown(
                        f'<div class="kpi-card-hrw"><div class="kpi-main">{_sv}</div>'
                        f'<div class="kpi-label">{_sl}</div></div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("<div style='margin-top:0.8rem'></div>", unsafe_allow_html=True)

            # ── Dual-series yield chart ─────────────────────────────────────────────
            _vc_fig = go.Figure()

            # Build trendline x range
            _tl_x = list(range(1985, sel_usda_yr + 2))

            # NASS trendline
            if _hrw_nass_td:
                _vc_fig.add_trace(go.Scatter(
                    x=_tl_x,
                    y=[_trend_at(_hrw_nass_td, y) for y in _tl_x],
                    mode="lines",
                    name="NASS Trend",
                    line=dict(color="rgba(6,147,227,0.4)", width=1.5, dash="dot"),
                    showlegend=True,
                ))
            # Weighted trendline
            if _hrw_wtd_td:
                _vc_fig.add_trace(go.Scatter(
                    x=_tl_x,
                    y=[_trend_at(_hrw_wtd_td, y) for y in _tl_x],
                    mode="lines",
                    name="Weighted Trend",
                    line=dict(color="rgba(245,158,11,0.4)", width=1.5, dash="dot"),
                    showlegend=True,
                ))

            # NASS US Winter Wheat actual — blue
            _vc_fig.add_trace(go.Scatter(
                x=_val_cmp["year"],
                y=_val_cmp["nass_hrw"],
                mode="lines+markers",
                name="NASS US Winter Wheat",
                line=dict(color=JPSI_BLUE, width=2),
                marker=dict(size=6, color=JPSI_BLUE),
                hovertemplate=(
                    "<b>NASS US Winter Wheat</b>  %{x}<br>"
                    "Yield: <b>%{y:.1f} bu/ac</b><extra></extra>"
                ),
            ))

            # Weighted estimate — amber
            _vc_fig.add_trace(go.Scatter(
                x=_val_cmp["year"],
                y=_val_cmp["wtd_hrw"],
                mode="lines+markers",
                name="Weighted Estimate",
                line=dict(color="#f59e0b", width=2),
                marker=dict(size=6, color="#f59e0b"),
                hovertemplate=(
                    "<b>Weighted HRW</b>  %{x}<br>"
                    "Yield: <b>%{y:.1f} bu/ac</b><extra></extra>"
                ),
            ))

            # Current year forecast from analog model (if available)
            if _series_key == "HRW" and not _yield_full.empty:
                _fcast_wtd = None
                if _hrw_wtd_td:
                    _fcast_trend = _trend_at(_hrw_wtd_td, sel_usda_yr)
                    # Use avg deviation from analog years if we have it
                    _analog_lkup_hrw = {}
                    for _, _rr in _hrw_weighted_df.iterrows():
                        _ryr = int(_rr["year"])
                        _rtd = _trend_at(_hrw_wtd_td, _ryr)
                        _analog_lkup_hrw[_ryr] = _dev_pct(float(_rr["yield_bu_ac"]), _rtd)
                    _fcast_wtd = _fcast_trend  # placeholder — trendline projection

                if _fcast_wtd is not None:
                    _vc_fig.add_trace(go.Scatter(
                        x=[sel_usda_yr],
                        y=[_fcast_wtd],
                        mode="markers",
                        name=f"{selected_mkt} Trend Proj",
                        marker=dict(size=12, color="#f59e0b", symbol="star"),
                        hovertemplate=(
                            f"<b>{selected_mkt} Trendline Proj</b><br>"
                            f"Yield: <b>{_fcast_wtd:.1f} bu/ac</b><extra></extra>"
                        ),
                    ))

            _vc_fig.update_layout(
                height=380,
                paper_bgcolor=DM_BG,
                plot_bgcolor=DM_SURFACE2,
                font=dict(color=DM_TEXT, size=12),
                legend=dict(
                    bgcolor=DM_SURFACE, bordercolor=DM_BORDER, borderwidth=1,
                    orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                ),
                xaxis=dict(
                    title="Harvest Year", gridcolor=DM_BORDER, zeroline=False,
                    tickfont=dict(size=11),
                ),
                yaxis=dict(
                    title="Yield (bu/ac)", gridcolor=DM_BORDER, zeroline=False,
                ),
                hovermode="x unified",
                margin=dict(l=60, r=20, t=30, b=50),
            )
            _show_chart(_vc_fig, "vintage_conditions")

            # ── Deviation bar chart ─────────────────────────────────────────────────
            _dev_colors = [
                "#1a9850" if d >= 0 else "#d73027"
                for d in _val_cmp["deviation"]
            ]
            _dev_fig = go.Figure(go.Bar(
                x=_val_cmp["year"],
                y=_val_cmp["deviation"],
                marker_color=_dev_colors,
                name="Weighted − NASS",
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Deviation: <b>%{y:+.2f} bu/ac</b><br>"
                    "Dev %: <b>%{customdata:+.1f}%</b><extra></extra>"
                ),
                customdata=_val_cmp["dev_pct"],
            ))
            _dev_fig.add_hline(y=0, line_color=DM_BORDER, line_width=1)
            _dev_fig.update_layout(
                height=220,
                paper_bgcolor=DM_BG,
                plot_bgcolor=DM_SURFACE2,
                font=dict(color=DM_TEXT, size=11),
                xaxis=dict(gridcolor=DM_BORDER, zeroline=False, tickfont=dict(size=11)),
                yaxis=dict(
                    title="Deviation (bu/ac)", gridcolor=DM_BORDER, zeroline=False,
                ),
                showlegend=False,
                margin=dict(l=60, r=20, t=10, b=40),
                title=dict(
                    text="Deviation: Weighted Estimate − NASS US HRW (green = overestimate, red = underestimate)",
                    font=dict(size=11, color=DM_MUTED),
                    x=0,
                ),
            )
            _show_chart(_dev_fig, "conditions_deviation")

            # ── Year-by-year comparison table ───────────────────────────────────────
            with st.expander("📋 Year-by-Year HRW Model Comparison", expanded=False):
                _tbl_rows = []
                for _, _vr in _val_cmp.iterrows():
                    _vyr = int(_vr["year"])
                    _nass_tl  = _trend_at(_hrw_nass_td, _vyr) if _hrw_nass_td else float("nan")
                    _wtd_tl   = _trend_at(_hrw_wtd_td, _vyr)  if _hrw_wtd_td  else float("nan")
                    _tbl_rows.append({
                        "Harvest Yr":       _vyr,
                        "Mkt Year":         _yield_mkt_lbl(_vyr),
                        "NASS US HRW (bu/ac)":    round(_vr["nass_hrw"], 1),
                        "NASS Trend (bu/ac)":     round(_nass_tl, 1) if pd.notna(_nass_tl) else None,
                        "Weighted Est. (bu/ac)":  round(_vr["wtd_hrw"], 1),
                        "Wtd Trend (bu/ac)":      round(_wtd_tl, 1) if pd.notna(_wtd_tl) else None,
                        "Deviation (bu/ac)":      round(_vr["deviation"], 2),
                        "Dev %":                  round(_vr["dev_pct"], 2),
                    })
                _cmp_tbl = (pd.DataFrame(_tbl_rows)
                            .sort_values("Harvest Yr", ascending=False)
                            .reset_index(drop=True))
                st.dataframe(_cmp_tbl, use_container_width=True, hide_index=True)
                _dl_btn(_cmp_tbl, f"analog_yield_comparison_{selected_mkt.replace('/','_')}.xlsx",
                        "⬇ Download Analog Table")

        else:
            st.info(
                "HRW class yield data not yet available. "
                "Ensure NASS API is reachable and refresh the dashboard."
            )

        # ── Multi-Class Backtest: Fixed Weights vs Year-Specific vs NASS ────────────
        if commodity_cfg.get("has_classes", True):
            st.markdown(
                '<div class="sec-hdr">Yield Model Backtest — Fixed Weights vs. Year-Specific vs. NASS</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "Side-by-side comparison of two weighting approaches against the true USDA benchmark.  "
                "**Fixed Weights** = 10-yr average state shares (same weight every year).  "
                "**Year-Specific** = that harvest year's actual harvested acres (matches NASS methodology).  "
                "**Benchmarks**: HRW = USDA official Hard Red Winter final yields from NASS Small Grains "
                "Summary (1981–present; hardcoded — NASS API does not expose national HRW class yields, and "
                "US Winter Wheat is NOT a valid proxy because it blends SRW and White classes). "
                "SRW = NASS SOFT RED WINTER state yields × state acres (computed). "
                "White = NASS SOFT WHITE state yields × state acres (computed).  "
                "**Lower MAE = better approach.**"
            )

            # ── Helper: build comparison using both approaches ────────────────────
            def _build_dual_backtest(
                dyn_key: str,          # state_alpha in _yield_full  (year-specific)
                fixed_df: pd.DataFrame,  # fixed-weight series
                nass_df: pd.DataFrame,
            ) -> pd.DataFrame:
                """
                Returns DataFrame with columns:
                  year, nass_yield,
                  fixed_model, fixed_diff, fixed_diff_pct,
                  dyn_model, dyn_diff, dyn_diff_pct
                """
                if nass_df.empty:
                    return pd.DataFrame()
                nass = nass_df[["year", "nass_yield"]].copy()

                dyn_rows = pd.DataFrame()
                if not _yield_full.empty:
                    dyn_rows = (_yield_full[_yield_full["state_alpha"] == dyn_key][["year", "yield_bu_ac"]]
                                .rename(columns={"yield_bu_ac": "dyn_model"}))

                fix_rows = pd.DataFrame()
                if not fixed_df.empty:
                    fix_rows = (fixed_df[["year", "yield_bu_ac"]]
                                .rename(columns={"yield_bu_ac": "fixed_model"}))

                merged = nass
                if not fix_rows.empty:
                    merged = merged.merge(fix_rows, on="year", how="left")
                else:
                    merged["fixed_model"] = float("nan")
                if not dyn_rows.empty:
                    merged = merged.merge(dyn_rows, on="year", how="left")
                else:
                    merged["dyn_model"] = float("nan")

                merged["fixed_diff"]     = merged["fixed_model"] - merged["nass_yield"]
                merged["fixed_diff_pct"] = (merged["fixed_diff"] / merged["nass_yield"] * 100).round(2)
                merged["dyn_diff"]       = merged["dyn_model"]   - merged["nass_yield"]
                merged["dyn_diff_pct"]   = (merged["dyn_diff"]   / merged["nass_yield"] * 100).round(2)
                return merged.sort_values("year", ascending=False).reset_index(drop=True)

            _bt_hrw   = _build_dual_backtest("HRW",   _hrw_fixed_df,   _nass_hrw_national_df)
            _bt_srw   = _build_dual_backtest("SRW",   _srw_fixed_df,   _nass_srw_national_df)
            _bt_white = _build_dual_backtest("White", _white_fixed_df, _nass_white_national_df)

            # ── Summary stats: which approach wins? ───────────────────────────────
            def _dual_stats(df: pd.DataFrame, label: str) -> list[dict]:
                if df.empty:
                    return []
                # Last 15 years available
                min_yr = df["year"].max() - 14
                sub = df[df["year"] >= min_yr].copy()
                if sub.empty:
                    return []
                out = []
                for col_diff, col_pct, approach in [
                    ("fixed_diff", "fixed_diff_pct", "Fixed Avg Weights"),
                    ("dyn_diff",   "dyn_diff_pct",   "Year-Specific Weights"),
                ]:
                    valid = sub[col_diff].dropna()
                    if valid.empty:
                        continue
                    out.append({
                        "Class":           label,
                        "Approach":        approach,
                        "Yrs":             len(valid),
                        "Avg Bias (bu/ac)": round(float(valid.mean()), 2),
                        "MAE (bu/ac)":     round(float(valid.abs().mean()), 2),
                        "Avg Bias %":      round(float(sub[col_pct].dropna().mean()), 1),
                        "Over Yrs":        int((valid > 0).sum()),
                        "Under Yrs":       int((valid < 0).sum()),
                    })
                return out

            _summary_rows = []
            for _bt, _lbl in [(_bt_hrw, "HRW"), (_bt_srw, "SRW"), (_bt_white, "White")]:
                _summary_rows.extend(_dual_stats(_bt, _lbl))

            if _summary_rows:
                _summary_df = pd.DataFrame(_summary_rows)
                # Highlight the better approach for each class (lower MAE)
                st.dataframe(_summary_df, use_container_width=False, hide_index=True)
                st.caption(
                    "**Lower MAE = better approach.**  "
                    "Positive Bias = model overestimates NASS · Negative = underestimates · "
                    "Last 15 available harvest years used for statistics."
                )
            else:
                st.info(
                    "No NASS national class yields returned (HRW / SRW / White).  "
                    "NASS may not publish these series via agg_level_desc=NATIONAL for all classes — "
                    "try refreshing or check the API directly."
                )

            # ── Detailed year-by-year comparison table ────────────────────────────
            with st.expander("📋 Year-by-Year Class Yield Backtest — Fixed vs Year-Specific vs NASS", expanded=False):
                _bt_tabs = st.tabs(["⬡ HRW", "⬡ SRW", "⬡ White"])
                for _cls_tab, _cls_bt, _cls_lbl, _cls_fn in zip(
                    _bt_tabs,
                    [_bt_hrw, _bt_srw, _bt_white],
                    ["HRW", "SRW", "White"],
                    ["hrw", "srw", "white"],
                ):
                    with _cls_tab:
                        if _cls_bt.empty:
                            st.info(
                                f"No NASS national {_cls_lbl} yield data available.  "
                                "NASS may not publish this series; check API or refresh."
                            )
                        else:
                            _tbl = _cls_bt.copy()
                            _tbl = _tbl.rename(columns={
                                "year":           "Harvest Yr",
                                "nass_yield":     f"NASS {_cls_lbl}",
                                "fixed_model":    "Fixed Wt Model",
                                "fixed_diff":     "Fixed Diff",
                                "fixed_diff_pct": "Fixed Diff %",
                                "dyn_model":      "Yr-Specific Model",
                                "dyn_diff":       "Yr-Spec Diff",
                                "dyn_diff_pct":   "Yr-Spec Diff %",
                            })
                            for _c in [f"NASS {_cls_lbl}", "Fixed Wt Model", "Fixed Diff",
                                       "Yr-Specific Model", "Yr-Spec Diff"]:
                                if _c in _tbl.columns:
                                    _tbl[_c] = _tbl[_c].round(2)
                            for _c in ["Fixed Diff %", "Yr-Spec Diff %"]:
                                if _c in _tbl.columns:
                                    _tbl[_c] = _tbl[_c].round(2)
                            _tbl["Harvest Yr"] = _tbl["Harvest Yr"].astype(int)
                            st.dataframe(_tbl, use_container_width=True, hide_index=True)

                            # Per-class avg bias callout
                            _sub15 = _cls_bt[_cls_bt["year"] >= _cls_bt["year"].max() - 14]
                            if not _sub15.empty:
                                _pairs = [
                                    ("Fixed Avg",    _sub15["fixed_diff"].dropna(), _sub15["fixed_diff_pct"].dropna()),
                                    ("Year-Specific", _sub15["dyn_diff"].dropna(),   _sub15["dyn_diff_pct"].dropna()),
                                ]
                                _callout_parts = []
                                for _ap_lbl, _diffs, _pcts in _pairs:
                                    if not _diffs.empty:
                                        _b  = float(_diffs.mean())
                                        _bp = float(_pcts.mean())
                                        _sign = "over" if _b >= 0 else "under"
                                        _color = "#1a9850" if _b >= 0 else "#d73027"
                                        _callout_parts.append(
                                            f'<span style="color:{_color}">'
                                            f'<b>{_ap_lbl}</b>: {_sign}estimates by '
                                            f'{abs(_b):.2f} bu/ac ({abs(_bp):.1f}%)</span>'
                                        )
                                if _callout_parts:
                                    st.markdown(
                                        "Avg bias (15 yr) — " + " &nbsp;|&nbsp; ".join(_callout_parts),
                                        unsafe_allow_html=True,
                                    )
                            _dl_btn(_tbl, f"{_cls_fn}_yield_backtest.xlsx",
                                    f"⬇ Download {_cls_lbl} Backtest")

    # ── Condition Band Weight Calibration — Research Backtest ─────────────────────
    # Hidden from public once validated.  Tests whether the equal-spaced JSA weights
    # (VP=0 P=25 F=50 G=75 E=100) are empirically optimal and whether asymmetry exists.
    with st.expander("🔬  Condition Band Weight Calibration — Research Backtest", expanded=False):
        st.caption(
            "**Research tool — internal use only.**  "
            "Runs OLS regression of final yield deviation on the five condition band shares "
            "(Very Poor, Poor, Fair, Good, Excellent) at each ISO week.  "
            "Tests whether the current equal-spaced JSA weights (0 / 25 / 50 / 75 / 100) "
            "are empirically optimal and whether downside (Very Poor) is stronger than "
            "upside (Excellent) — the **asymmetry hypothesis**."
        )

        # Series selector — default to active series
        _cal_series_opts = (
            ["US", "HRW", "SRW", "White"]
            if commodity_cfg.get("has_classes", True)
            else ["US"]
        )
        _cal_default_idx = (
            _cal_series_opts.index(_series_key)
            if _series_key in _cal_series_opts else 0
        )
        _cal_series = st.selectbox(
            "Series for calibration",
            _cal_series_opts,
            index=_cal_default_idx,
            key="cal_series_sel",
        )
        _cal_weights_map = {
            "HRW": _dynamic_hrw_weights,
            "SRW": _dynamic_srw_weights,
            "White": _dynamic_white_weights,
            "US": None,
        }
        _cal_wts = _cal_weights_map.get(_cal_series)

        # ── Build condition shares DataFrame ───────────────────────────────────────
        with st.spinner("Building condition share history…"):
            _cal_shares = _build_condition_shares_df(
                raw_df, _cal_series, _cal_wts, sel_usda_yr,
                crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
            )

        if _cal_shares.empty:
            st.warning("Not enough condition data to run calibration for this series.")
        else:
            # ── Identify best-signal week via cached scan (same call used in Abandonment tab) ──
            import json as _cal_json
            _cal_devs_raw = {
                sk: {str(yr): v["dev"] for yr, v in yl.items() if v.get("dev") is not None}
                for sk, yl in _yield_lookup.items()
                if any(v.get("dev") is not None for v in yl.values())
            }
            _cal_scan_iso_min, _cal_scan_iso_max = commodity_cfg.get("scan_iso_range", (5, 22))
            with st.spinner("Identifying best-signal week…"):
                _cal_scan_res = _scan_best_week(
                    raw_df, sel_usda_yr,
                    _cal_json.dumps(_cal_devs_raw),
                    tuple(sorted(_dynamic_hrw_weights.items())),
                    tuple(sorted(_dynamic_srw_weights.items())),
                    tuple(sorted(_dynamic_white_weights.items())),
                    _crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                    _scan_iso_min=_cal_scan_iso_min,
                    _scan_iso_max=_cal_scan_iso_max,
                    commodity_key=commodity_label,
                )
            _bw_res = _cal_scan_res.get(_cal_series)
            _cal_best_iso = _bw_res["best_iso"] if _bw_res else 14   # fallback week 14

            st.markdown(
                f"**Best-signal ISO week for {_cal_series}:** "
                f"week {_cal_best_iso} &nbsp;·&nbsp; "
                f"Current JSA R² at that week: "
                f"{_bw_res['r2']*100:.1f}% &nbsp;·&nbsp; "
                f"n = {_bw_res['n_years']} years"
                if _bw_res else
                f"Using ISO week {_cal_best_iso} (best-week scan not available for this series)."
            )

            # ── Run regression at best-signal week ────────────────────────────────
            _cal_reg = _run_band_regression(
                _cal_shares, _cal_best_iso, _yield_lookup, _cal_series
            )

            if _cal_reg is None:
                st.warning(f"Insufficient yield/condition data to run regression for {_cal_series} at week {_cal_best_iso}.")
            else:
                # ── Weights comparison bar chart ───────────────────────────────────
                _cal_bands  = ["VP", "P", "F", "G", "E"]
                _cal_labels = ["Very Poor", "Poor", "Fair", "Good", "Excellent"]
                _cal_cur_w  = [_cal_reg["weights_current"][b]  for b in _cal_bands]
                _cal_emp_w  = [_cal_reg["weights_empirical"][b] for b in _cal_bands]
                # ±1 SE expressed in the same rescaled weight units (SE × scale factor)
                _rng = _cal_reg["coef"]["E"] - _cal_reg["coef"]["VP"]
                _cal_scale = 100.0 / _rng if abs(_rng) > 0.001 else 1.0
                _cal_err   = [
                    _cal_reg["se"].get(b, 0) * _cal_scale for b in _cal_bands
                ]

                _cal_fig = go.Figure()
                _cal_fig.add_trace(go.Bar(
                    name="Current (0/25/50/75/100)",
                    x=_cal_labels,
                    y=_cal_cur_w,
                    marker_color="rgba(74,222,128,0.6)",
                    marker_line_color=JPSI_BLUE,
                    marker_line_width=1.5,
                ))
                _cal_fig.add_trace(go.Bar(
                    name="Empirical (regression-fitted)",
                    x=_cal_labels,
                    y=_cal_emp_w,
                    error_y=dict(type="data", array=_cal_err, color=DM_MUTED,
                                 thickness=1.5, width=6),
                    marker_color="rgba(245,158,11,0.70)",
                    marker_line_color="#f59e0b",
                    marker_line_width=1.5,
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Empirical weight: %{y:.1f}<br>"
                        "±1 SE: ±%{error_y.array:.1f}"
                        "<extra></extra>"
                    ),
                ))
                _cal_fig.update_layout(
                    barmode="group",
                    xaxis=dict(color=DM_MUTED, tickfont=dict(color=DM_TEXT)),
                    yaxis=dict(
                        title="Index weight (0–100 scale, VP = 0, E = 100)",
                        range=[-5, 110],
                        gridcolor=DM_BORDER, color=DM_MUTED,
                        tickfont=dict(color=DM_MUTED),
                    ),
                    paper_bgcolor=DM_BG, plot_bgcolor=DM_SURFACE2,
                    legend=dict(
                        orientation="h", x=0.5, xanchor="center", y=-0.18,
                        font=dict(color=DM_TEXT, size=11),
                        bgcolor="rgba(0,0,0,0)",
                    ),
                    margin=dict(l=10, r=10, t=30, b=60),
                    height=380,
                    title=dict(
                        text=(
                            f"<b>{_cal_series} — Condition Band Weights: Current vs Empirical</b>"
                            f"  ·  ISO week {_cal_best_iso}"
                            f"  ·  n = {_cal_reg['n_years']} years"
                        ),
                        font=dict(size=13, color=DM_TEXT),
                        x=0.5, xanchor="center",
                    ),
                )
                # Reference line at 50 (midpoint, for context)
                _cal_fig.add_hline(y=50, line_dash="dot", line_color=DM_MUTED,
                                   annotation_text="Midpoint (50)",
                                   annotation_position="top right",
                                   annotation_font=dict(color=DM_MUTED, size=10))
                _show_chart(_cal_fig, "calendar_heatmap")

                # ── Asymmetry + R² summary metrics ────────────────────────────────
                _asym = _cal_reg["asymmetry"]
                _r2j  = _cal_reg["r2_jsa"]  * 100
                _r2e  = _cal_reg["r2_empirical"] * 100
                _r2g  = _cal_reg["r2_gain"]  * 100

                _asym_interp = (
                    f"**Downside is {_asym:.2f}× stronger** than upside — very poor conditions "
                    f"drag yield below trend more than excellent conditions lift it."
                    if _asym and _asym > 1.10 else
                    f"**Upside is {1/_asym:.2f}× stronger** than downside — somewhat unusual, "
                    f"may indicate limited Very Poor observations."
                    if _asym and _asym < 0.90 else
                    "**Approximately symmetric** — downside and upside appear roughly equal in magnitude."
                ) if _asym else "Asymmetry could not be computed (check data)."

                _r2g_interp = (
                    f"Empirical weights improve R² by **{_r2g:.1f} percentage points** — "
                    f"recalibration may be worthwhile."
                    if _r2g > 5 else
                    f"Empirical weights improve R² by only **{_r2g:.1f} pp** — "
                    f"current equal-spacing is well-supported by the data."
                )

                _kc1, _kc2, _kc3 = st.columns(3)
                with _kc1:
                    st.metric("Current JSA R²", f"{_r2j:.1f}%",
                              help="Correlation² between current JSA index and final yield deviation at best-signal week")
                with _kc2:
                    st.metric("Empirical Model R²", f"{_r2e:.1f}%",
                              delta=f"{_r2g:+.1f} pp vs current JSA",
                              help="R² from the 4-predictor OLS (VP, P, G, E — Fair omitted)")
                with _kc3:
                    st.metric("Asymmetry ratio  |β_VP| / β_E",
                              f"{_asym:.2f}×" if _asym else "N/A",
                              help="Ratio of Very Poor drag to Excellent lift. >1 = downside stronger, <1 = upside stronger")

                st.info(f"**Asymmetry:** {_asym_interp}\n\n**R² gain:** {_r2g_interp}")

                # ── Coefficient table ──────────────────────────────────────────────
                _coef_rows = []
                for bc, lbl in zip(_cal_bands, _cal_labels):
                    _co  = _cal_reg["coef"][bc]
                    _se  = _cal_reg["se"][bc]
                    _t   = _co / _se if _se > 0 else float("nan")
                    _p   = float(2 * (1 - min(abs(_t) / 3, 1))) if not np.isnan(_t) else float("nan")   # rough approximation
                    _sig = "***" if abs(_t) > 3 else ("**" if abs(_t) > 2 else ("*" if abs(_t) > 1.7 else ""))
                    _coef_rows.append({
                        "Band":             lbl,
                        "Current Weight":   _cal_reg["weights_current"][bc],
                        "Empirical Weight": _cal_reg["weights_empirical"][bc],
                        "β (yield_dev / pp)": round(_co, 4),
                        "SE":               round(_se, 4) if not np.isnan(_se) else "N/A",
                        "t-stat":           round(_t,  2)  if not np.isnan(_t)  else "N/A",
                        "Sig.":             _sig,
                    })
                st.dataframe(
                    pd.DataFrame(_coef_rows).set_index("Band"),
                    use_container_width=True,
                )
                st.caption(
                    "β = change in yield deviation (%) per 1 percentage-point increase in that "
                    "condition band's share, replacing Fair (omitted baseline).  "
                    "Sig.: * p<0.10, ** p<0.05, *** p<0.01 (approximate).  "
                    f"Years used: {', '.join(str(y) for y in _cal_reg['years_used'])}."
                )

                # ── R² by week scan ────────────────────────────────────────────────
                st.markdown("---")
                st.markdown("**R² by ISO Week — Current JSA vs Empirical 4-band model**")
                st.caption(
                    "Higher R² = conditions at that week are more predictive of final yield deviation.  "
                    "Gap between lines = potential gain from recalibrating weights."
                )
                with st.spinner("Scanning ISO weeks…"):
                    _scan_iso_min = commodity_cfg.get("scan_iso_range", (5, 40))[0]
                    _scan_iso_max = commodity_cfg.get("scan_iso_range", (5, 40))[1]
                    _r2_scan_df = _scan_band_regression(
                        _cal_shares, _yield_lookup, _cal_series,
                        iso_min=_scan_iso_min, iso_max=_scan_iso_max,
                    )

                if not _r2_scan_df.empty:
                    _r2_fig = go.Figure()
                    _r2_fig.add_trace(go.Scatter(
                        x=_r2_scan_df["iso_week"], y=_r2_scan_df["r2_jsa"],
                        mode="lines+markers",
                        name="Current JSA (equal weights)",
                        line=dict(color=JPSI_BLUE, width=2),
                        marker=dict(size=5),
                        hovertemplate="Week %{x} — JSA R²: %{y:.1f}%<extra></extra>",
                    ))
                    _r2_fig.add_trace(go.Scatter(
                        x=_r2_scan_df["iso_week"], y=_r2_scan_df["r2_empirical"],
                        mode="lines+markers",
                        name="Empirical (4-band OLS)",
                        line=dict(color="#f59e0b", width=2),
                        marker=dict(size=5),
                        hovertemplate="Week %{x} — Empirical R²: %{y:.1f}%<extra></extra>",
                    ))
                    # Shade gap between lines
                    _r2_fig.add_trace(go.Scatter(
                        x=pd.concat([_r2_scan_df["iso_week"], _r2_scan_df["iso_week"][::-1]]).tolist(),
                        y=pd.concat([_r2_scan_df["r2_empirical"], _r2_scan_df["r2_jsa"][::-1]]).tolist(),
                        fill="toself",
                        fillcolor="rgba(245,158,11,0.12)",
                        line=dict(width=0),
                        showlegend=False,
                        hoverinfo="skip",
                    ))
                    # Mark best-signal week
                    if _cal_best_iso in _r2_scan_df["iso_week"].values:
                        _bw_row = _r2_scan_df[_r2_scan_df["iso_week"] == _cal_best_iso].iloc[0]
                        _r2_fig.add_vline(
                            x=_cal_best_iso, line_dash="dot", line_color=DM_MUTED,
                            annotation_text=f"Best week (wk {_cal_best_iso})",
                            annotation_position="top right",
                            annotation_font=dict(color=DM_MUTED, size=10),
                        )
                    _r2_fig.update_layout(
                        xaxis=dict(
                            title="ISO Week",
                            gridcolor=DM_BORDER, color=DM_MUTED,
                            tickfont=dict(color=DM_MUTED),
                        ),
                        yaxis=dict(
                            title="R² (%)",
                            range=[0, max(100, _r2_scan_df["r2_empirical"].max() + 5)],
                            gridcolor=DM_BORDER, color=DM_MUTED,
                            tickfont=dict(color=DM_MUTED),
                            ticksuffix="%",
                        ),
                        paper_bgcolor=DM_BG, plot_bgcolor=DM_SURFACE2,
                        legend=dict(
                            orientation="h", x=0.5, xanchor="center", y=-0.18,
                            font=dict(color=DM_TEXT, size=11),
                            bgcolor="rgba(0,0,0,0)",
                        ),
                        margin=dict(l=10, r=10, t=20, b=60),
                        height=340,
                        hovermode="x unified",
                    )
                    _show_chart(_r2_fig, "scan_r2")

                # ── Multi-class comparison summary ─────────────────────────────────
                if commodity_cfg.get("has_classes", True):
                    st.markdown("---")
                    st.markdown("**Cross-class summary — Asymmetry & R² gain at each series' best week**")
                    _cls_rows = []
                    for _sk_c, _wts_c in [("US", None), ("HRW", _dynamic_hrw_weights),
                                           ("SRW", _dynamic_srw_weights), ("White", _dynamic_white_weights)]:
                        _sh_c = _build_condition_shares_df(
                            raw_df, _sk_c, _wts_c, sel_usda_yr,
                            crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                        )
                        if _sh_c.empty:
                            continue
                        _bw_c = _cal_scan_res.get(_sk_c)
                        _iso_c = _bw_c["best_iso"] if _bw_c else 14
                        _reg_c = _run_band_regression(_sh_c, _iso_c, _yield_lookup, _sk_c)
                        if _reg_c is None:
                            continue
                        _cls_rows.append({
                            "Series":              _sk_c,
                            "Best ISO Week":       _iso_c,
                            "n Years":             _reg_c["n_years"],
                            "JSA R²":              f"{_reg_c['r2_jsa']*100:.1f}%",
                            "Empirical R²":        f"{_reg_c['r2_empirical']*100:.1f}%",
                            "R² Gain (pp)":        f"{_reg_c['r2_gain']*100:+.1f}",
                            "Asymmetry |VP|/E":    f"{_reg_c['asymmetry']:.2f}×" if _reg_c["asymmetry"] else "N/A",
                            "Emp. VP weight":      _reg_c["weights_empirical"]["VP"],
                            "Emp. E weight":       _reg_c["weights_empirical"]["E"],
                        })
                    if _cls_rows:
                        st.dataframe(pd.DataFrame(_cls_rows).set_index("Series"), use_container_width=True)
                        st.caption(
                            "Asymmetry >1.0 means Very Poor conditions drag yield below trend more than "
                            "Excellent conditions lift it above trend (relative to Fair baseline).  "
                            "R² Gain shows how much the in-sample fit improves with free-form weights — "
                            "small gains validate the current equal-spacing."
                        )

    # ── Cumulative Conditions — Start Week Scan ───────────────────────────────────
    with st.expander("📈  Cumulative Conditions — Start Week Scan (Research)", expanded=False):
        st.caption(
            "**Research tool — standalone, does not alter the existing single-week model.**  "
            "For each candidate start week S, computes `mean(JSA[S → forecast week])` across "
            "all historical years and fits two models independently:  \n"
            "**Model A** — Cumulative only: `yield_dev ~ mean_JSA(S→W)`  \n"
            "**Model B** — Two-factor: `yield_dev ~ snap_JSA(W) + mean_JSA(S→W)`  \n"
            "Metrics shown: in-sample R², adjusted R², and leave-one-year-out RMSE (the real test). "
            "Lower LOO-RMSE = better out-of-sample forecast accuracy."
        )

        _cum_series_opts = (
            ["US", "HRW", "SRW", "White"]
            if commodity_cfg.get("has_classes", True)
            else ["US"]
        )
        _cum_series = st.selectbox(
            "Series", _cum_series_opts,
            index=_cum_series_opts.index(_series_key) if _series_key in _cum_series_opts else 0,
            key="cum_series_sel",
        )

        # Forecast week: default to current ISO week, clamped to scan range
        _cscan_min, _cscan_max = commodity_cfg.get("scan_iso_range", (5, 22))
        _cum_default_fw = _cscan_max if _cur_iso_week is None else max(_cscan_min, min(_cur_iso_week, _cscan_max))
        _cum_fw = st.slider(
            "Forecast week (cumulative window endpoint)",
            min_value=_cscan_min, max_value=_cscan_max,
            value=_cum_default_fw,
            key="cum_fw_slider",
            help="The week at which the single-week snapshot is taken and the cumulative window ends.",
        )
        _cum_start_min = st.slider(
            "Earliest possible cumulative start week",
            min_value=max(1, _cscan_min), max_value=max(1, _cum_fw - 2),
            value=max(_cscan_min, min(15, _cum_fw - 3)),
            key="cum_start_min_slider",
            help="Scan will test every start week from here through forecast week − 1.",
        )

        import json as _cum_json
        # Only scan the selected series — scanning all states is 30x slower with no benefit
        _cum_devs_raw = {}
        if _cum_series in _yield_lookup:
            _yl = _yield_lookup[_cum_series]
            _cum_devs_raw = {
                _cum_series: {str(yr): v["dev"] for yr, v in _yl.items() if v.get("dev") is not None}
            }

        with st.spinner("Running cumulative start-week scan…"):
            _cum_scan_res = _scan_cumulative_start(
                raw_df, sel_usda_yr,
                _cum_json.dumps(_cum_devs_raw),
                tuple(sorted(_dynamic_hrw_weights.items())),
                tuple(sorted(_dynamic_srw_weights.items())),
                tuple(sorted(_dynamic_white_weights.items())),
                _forecast_iso_week=_cum_fw,
                _crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                _start_iso_min=_cum_start_min,
                commodity_key=commodity_label,
            )

        _cum_res = _cum_scan_res.get(_cum_series)
        if _cum_res is None or _cum_res["rows"].empty:
            st.info("Not enough data to run cumulative scan for this series / forecast week combination.")
        else:
            _cum_df     = _cum_res["rows"]
            _r2_snap    = _cum_res["r2_snap"]
            _loo_snap   = _cum_res["loo_snap"]

            # Optimal rows (by LOO-RMSE)
            _best_A_idx = _cum_df["loo_rmse_A"].idxmin()
            _best_B_idx = _cum_df["loo_rmse_B"].idxmin()
            _best_A_sw  = int(_cum_df.loc[_best_A_idx, "start_week"])
            _best_B_sw  = int(_cum_df.loc[_best_B_idx, "start_week"])
            _best_B_loo = float(_cum_df.loc[_best_B_idx, "loo_rmse_B"])
            _best_B_r2  = float(_cum_df.loc[_best_B_idx, "r2_B"])
            _best_B_arj = float(_cum_df.loc[_best_B_idx, "adj_r2_B"])
            _gain_loo   = round(_loo_snap - _best_B_loo, 2)

            st.markdown(
                f"**Single-week baseline (Wk {_cum_fw}):** "
                f"R² = {_r2_snap:.1f}% &nbsp;·&nbsp; LOO-RMSE = {_loo_snap:.2f} bu/ac  \n"
                f"**Best cumulative-only start (Model A):** ISO Wk {_best_A_sw} &nbsp;·&nbsp; "
                f"LOO-RMSE = {float(_cum_df.loc[_best_A_idx,'loo_rmse_A']):.2f} bu/ac  \n"
                f"**Best two-factor start (Model B):** ISO Wk {_best_B_sw} &nbsp;·&nbsp; "
                f"R² = {_best_B_r2:.1f}% &nbsp;·&nbsp; Adj R² = {_best_B_arj:.1f}% &nbsp;·&nbsp; "
                f"LOO-RMSE = {_best_B_loo:.2f} bu/ac &nbsp;·&nbsp; "
                f"LOO gain vs single-week = **{'+'if _gain_loo>=0 else ''}{_gain_loo:.2f} bu/ac**"
            )

            # ── Chart: R² curves ──────────────────────────────────────────────────
            _cum_fig = go.Figure()
            _cum_fig.add_hline(
                y=_r2_snap, line_dash="dot",
                line_color=JPSI_BLUE, line_width=1.5,
                annotation_text=f"Single-week Wk {_cum_fw} R² ({_r2_snap:.1f}%)",
                annotation_font_color=JPSI_BLUE, annotation_font_size=11,
                annotation_position="top left",
            )
            _cum_fig.add_trace(go.Scatter(
                x=_cum_df["start_week"], y=_cum_df["r2_A"],
                mode="lines+markers", name="Model A — Cumulative only",
                line=dict(color="#f59e0b", width=2),
                marker=dict(size=5),
                hovertemplate="Start Wk %{x}<br>Cumul-only R²: %{y:.1f}%<extra></extra>",
            ))
            _cum_fig.add_trace(go.Scatter(
                x=_cum_df["start_week"], y=_cum_df["r2_B"],
                mode="lines+markers", name="Model B — Two-factor",
                line=dict(color="#4ade80", width=2),
                marker=dict(size=5),
                hovertemplate="Start Wk %{x}<br>Two-factor R²: %{y:.1f}%<extra></extra>",
            ))
            _cum_fig.update_layout(
                title=dict(text=f"R² vs Cumulative Start Week — {_cum_series} (forecast Wk {_cum_fw})",
                           x=0.5, xanchor="center", font=dict(size=13, color=DM_TEXT)),
                xaxis=dict(title="Cumulative Start Week (ISO)",
                           gridcolor=DM_BORDER, color=DM_MUTED, tickfont=dict(color=DM_MUTED)),
                yaxis=dict(title="R² (%)", gridcolor=DM_BORDER, color=DM_MUTED,
                           tickfont=dict(color=DM_MUTED), ticksuffix="%",
                           range=[0, max(100, _cum_df["r2_B"].max() + 5)]),
                paper_bgcolor=DM_BG, plot_bgcolor=DM_SURFACE2,
                legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.20,
                            font=dict(color=DM_TEXT, size=11), bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=10, r=10, t=40, b=60), height=340, hovermode="x unified",
            )
            _show_chart(_cum_fig, "cumulative_analog")

            # ── Chart: LOO-RMSE curves ────────────────────────────────────────────
            _loo_fig = go.Figure()
            _loo_fig.add_hline(
                y=_loo_snap, line_dash="dot",
                line_color=JPSI_BLUE, line_width=1.5,
                annotation_text=f"Single-week LOO-RMSE ({_loo_snap:.2f})",
                annotation_font_color=JPSI_BLUE, annotation_font_size=11,
                annotation_position="top right",
            )
            _loo_fig.add_trace(go.Scatter(
                x=_cum_df["start_week"], y=_cum_df["loo_rmse_A"],
                mode="lines+markers", name="Model A — Cumulative only",
                line=dict(color="#f59e0b", width=2), marker=dict(size=5),
                hovertemplate="Start Wk %{x}<br>LOO-RMSE: %{y:.2f} bu/ac<extra></extra>",
            ))
            _loo_fig.add_trace(go.Scatter(
                x=_cum_df["start_week"], y=_cum_df["loo_rmse_B"],
                mode="lines+markers", name="Model B — Two-factor",
                line=dict(color="#4ade80", width=2), marker=dict(size=5),
                hovertemplate="Start Wk %{x}<br>LOO-RMSE: %{y:.2f} bu/ac<extra></extra>",
            ))
            # Mark the best B start week
            _loo_fig.add_vline(
                x=_best_B_sw, line_dash="dash", line_color="#4ade80", line_width=1,
                annotation_text=f"Best: Wk {_best_B_sw}",
                annotation_font_color="#4ade80", annotation_font_size=10,
            )
            _loo_fig.update_layout(
                title=dict(text=f"LOO-RMSE vs Cumulative Start Week — {_cum_series} (forecast Wk {_cum_fw})",
                           x=0.5, xanchor="center", font=dict(size=13, color=DM_TEXT)),
                xaxis=dict(title="Cumulative Start Week (ISO)",
                           gridcolor=DM_BORDER, color=DM_MUTED, tickfont=dict(color=DM_MUTED)),
                yaxis=dict(title="LOO-RMSE (bu/ac)", gridcolor=DM_BORDER, color=DM_MUTED,
                           tickfont=dict(color=DM_MUTED), ticksuffix=" bu/ac"),
                paper_bgcolor=DM_BG, plot_bgcolor=DM_SURFACE2,
                legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.20,
                            font=dict(color=DM_TEXT, size=11), bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=10, r=10, t=40, b=60), height=340, hovermode="x unified",
            )
            _show_chart(_loo_fig, "loo_scatter_backtest")

            # ── Detail table ──────────────────────────────────────────────────────
            with st.expander("📋 Full start-week scan table", expanded=False):
                _disp_df = _cum_df[[
                    "start_week", "n_years",
                    "r2_A", "adj_r2_A", "loo_rmse_A",
                    "r2_B", "adj_r2_B", "loo_rmse_B",
                    "f_stat", "gain_loo_vs_snap",
                ]].copy()
                _disp_df.columns = [
                    "Start Wk", "n Yrs",
                    "A R²%", "A Adj R²%", "A LOO-RMSE",
                    "B R²%", "B Adj R²%", "B LOO-RMSE",
                    "F-stat (cumul term)", "LOO gain vs snap",
                ]
                st.dataframe(_disp_df, use_container_width=True, hide_index=True)
                st.caption(
                    "Model A = cumulative JSA only. Model B = single-week snapshot + cumulative JSA. "
                    f"Baseline (single-week Wk {_cum_fw}): R² = {_r2_snap:.1f}%, LOO-RMSE = {_loo_snap:.2f} bu/ac. "
                    "F-stat: partial F for adding the cumulative term to the single-week model — "
                    "values > ~4 suggest the cumulative term is statistically meaningful. "
                    "LOO gain vs snap = single-week LOO-RMSE minus two-factor LOO-RMSE "
                    "(positive = two-factor wins out-of-sample)."
                )

    # ── Look-Back R² Simulation ────────────────────────────────────────────────────
    st.markdown(
        '<div class="sec-hdr">Look-Back R² Simulation — Best Predictive Marketing Week</div>',
        unsafe_allow_html=True,
    )
    _scan_iso_min_cap, _scan_iso_max_cap = commodity_cfg.get("scan_iso_range", (5, 22))
    _scan_wk_start_lbl = datetime.fromisocalendar(2024, _scan_iso_min_cap, 3).strftime("%b %d").lstrip("0").replace(" 0", " ")
    _scan_wk_end_lbl   = datetime.fromisocalendar(2024, _scan_iso_max_cap, 3).strftime("%b %d").lstrip("0").replace(" 0", " ")
    st.caption(
        f"Scans every marketing week (ISO weeks {_scan_iso_min_cap}–{_scan_iso_max_cap}, "
        f"{_scan_wk_start_lbl}–{_scan_wk_end_lbl}) and finds which week "
        "historically produces the highest R² between the JSA condition index and final yield "
        "deviation from trend.  Run on all years with complete yield data, excluding the current season."
    )

    import json as _json
    _scan_devs_raw = {}
    for _sk2, _yl2 in _yield_lookup.items():
        _sk2_devs = {str(yr): v["dev"] for yr, v in _yl2.items() if v.get("dev") is not None}
        if _sk2_devs:
            _scan_devs_raw[_sk2] = _sk2_devs

    def _iso_lbl(iso_w: int) -> str:
        try:
            d = datetime.fromisocalendar(2024, int(iso_w), 3)
            return f"Wk {iso_w} · {d.strftime('%b %d')}"
        except Exception:
            return f"Wk {iso_w}"

    with st.spinner("Running look-back scan across all weeks and series…"):
        _scan_iso_min, _scan_iso_max = commodity_cfg.get("scan_iso_range", (5, 22))
        _scan_res = _scan_best_week(
            raw_df, sel_usda_yr,
            _json.dumps(_scan_devs_raw),
            tuple(sorted(_dynamic_hrw_weights.items())),
            tuple(sorted(_dynamic_srw_weights.items())),
            tuple(sorted(_dynamic_white_weights.items())),
            _crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
            _scan_iso_min=_scan_iso_min,
            _scan_iso_max=_scan_iso_max,
            commodity_key=commodity_label,
        )

    if _scan_res:
        _priority_ord = {"US": 0, "HRW": 1, "SRW": 2, "White": 3}
        _idx_pool  = ("US", "HRW", "SRW", "White") if commodity_cfg.get("has_classes", True) else ("US",)
        _idx_keys  = [k for k in _idx_pool if k in _scan_res]
        _st_keys   = sorted(
            [k for k in _scan_res if k not in _priority_ord],
            key=lambda k: -_scan_res[k]["r2"],
        )

        _scan_idx_rows = []
        for _sk3 in _idx_keys:
            _sr3 = _scan_res[_sk3]
            _lbl3 = {"US": "🇺🇸 US Total", "HRW": "⬡ HRW Index", "SRW": "⬡ SRW Index", "White": "⬡ White Index"}[_sk3]
            _scan_idx_rows.append({
                "Series":    _lbl3,
                "Best Week": _iso_lbl(_sr3["best_iso"]),
                "Peak R²":   f"{_sr3['r2']*100:.0f}%",
                "Yrs":       _sr3["n_years"],
            })

        _scan_st_rows = []
        for _sk3 in _st_keys:
            _sr3 = _scan_res[_sk3]
            _scan_st_rows.append({
                "State":     _sk3,
                "Best Week": _iso_lbl(_sr3["best_iso"]),
                "Peak R²":   f"{_sr3['r2']*100:.0f}%",
                "Yrs":       _sr3["n_years"],
            })

        _scan_idx_df = pd.DataFrame(_scan_idx_rows)
        _scan_st_df  = pd.DataFrame(_scan_st_rows)
        _sc1, _sc2 = st.columns([1, 2])
        with _sc1:
            st.markdown(f'<div style="font-size:0.78rem;font-weight:600;color:{JPSI_BLUE};'
                        f'margin-bottom:4px">Index & National</div>', unsafe_allow_html=True)
            st.dataframe(_scan_idx_df, hide_index=True, use_container_width=True,
                         height=min(46 * len(_scan_idx_rows) + 56, 260))
            _dl_btn(_scan_idx_df, "lookback_index_national.xlsx", "⬇ Download")
        with _sc2:
            st.markdown(f'<div style="font-size:0.78rem;font-weight:600;color:{JPSI_BLUE};'
                        f'margin-bottom:4px">State Level — sorted by peak R²</div>', unsafe_allow_html=True)
            st.dataframe(_scan_st_df, hide_index=True, use_container_width=True,
                         height=min(46 * len(_scan_st_rows) + 56, 520))
            _dl_btn(_scan_st_df, "lookback_state_level.xlsx", "⬇ Download")

    else:
        st.info("Insufficient yield data to run look-back simulation.")

    # ── JSA Conditions Backtest (US national) ─────────────────────────────────────
    if not _yield_full.empty:
        st.markdown(
            '<div class="sec-hdr">JSA Conditions Yield Model Backtest</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Backtest of the JSA conditions-based yield model at the best-signal ISO week vs "
            "USDA final yields. USDA condition ratings already embed planting timing — reporters "
            "visually rate late-planted fields as Poor/Fair relative to timely-planted fields at "
            "the same calendar date, so no separate late planting adjustment is applied."
        )

        try:
            # ── Step 1: Get JSA at best-signal ISO week for each historical year ────
            _bt_us_scan = _scan_res.get("US") if "_scan_res" in dir() and _scan_res else None
            if _bt_us_scan is None:
                st.info("Run the Look-Back R² Simulation above first to identify the best-signal week.")
            else:
                _bt_best_iso = int(_bt_us_scan["best_iso"])

                # Build JSA history for US
                _bt_jsa_df = _us_series(raw_df, "JSA Index", "US").copy()
                _bt_jsa_df["week_ending"] = pd.to_datetime(_bt_jsa_df["week_ending"])
                _bt_crop_cut = commodity_cfg.get("crop_yr_cutoff", None)
                if _bt_crop_cut:
                    _bt_jsa_df["crop_year"] = (
                        _bt_jsa_df["week_ending"].dt.year
                        + (_bt_jsa_df["week_ending"].dt.month >= _bt_crop_cut).astype(int)
                    )
                else:
                    _bt_jsa_df["crop_year"] = _bt_jsa_df["week_ending"].dt.year
                _bt_jsa_df["iso_week"] = _bt_jsa_df["week_ending"].dt.isocalendar().week.astype(int)

                # Snap each crop-year's JSA to the best-signal ISO week
                _bt_jsa_snap: dict[int, float] = {}
                for _bcy, _bcg in _bt_jsa_df[_bt_jsa_df["crop_year"] < sel_usda_yr].groupby("crop_year"):
                    _idx = int(np.argmin(np.abs(_bcg["iso_week"].values - _bt_best_iso)))
                    _bt_jsa_snap[int(_bcy)] = float(_bcg.iloc[_idx]["metric"])

                # ── Step 2: OLS regression — JSA index → yield deviation (%) ────────
                _bt_yl_us = _yield_lookup.get("US", {})
                _bt_reg_pairs = [
                    (float(_bt_jsa_snap[yr]), float(_bt_yl_us[yr]["dev"]))
                    for yr in _bt_jsa_snap
                    if yr in _bt_yl_us and _bt_yl_us[yr].get("dev") is not None
                ]
                if len(_bt_reg_pairs) < 8:
                    st.info("Insufficient overlapping JSA + yield data for regression (need ≥ 8 years).")
                else:
                    _bt_xs = np.array([p[0] for p in _bt_reg_pairs])
                    _bt_ys = np.array([p[1] for p in _bt_reg_pairs])
                    _bt_c  = np.polyfit(_bt_xs, _bt_ys, 1)
                    _bt_slope, _bt_icept = float(_bt_c[0]), float(_bt_c[1])

                    # ── Step 4: Build backtest row for each year ──────────────────────
                    _bt_rows = []
                    for yr in sorted(_bt_jsa_snap.keys()):
                        if yr not in _bt_yl_us or _bt_yl_us[yr].get("dev") is None:
                            continue
                        _bty_act   = float(_bt_yl_us[yr]["yield"])
                        _bty_trend = float(_bt_yl_us[yr]["trend"])
                        _bty_dev   = float(_bt_yl_us[yr]["dev"])
                        _jsa_val   = _bt_jsa_snap[yr]

                        # JSA forecast: trend × (1 + predicted_dev/100)
                        _pred_dev_pct = _bt_slope * _jsa_val + _bt_icept
                        _jsa_forecast = _bty_trend * (1.0 + _pred_dev_pct / 100.0)

                        _bt_rows.append({
                            "Year":           yr,
                            "Mkt Year":       _yield_mkt_lbl(yr),
                            "Trend (bu/ac)":  round(_bty_trend, 1),
                            "Actual (bu/ac)": round(_bty_act, 1),
                            "JSA Index (wk)": round(_jsa_val, 1),
                            "JSA Forecast":   round(_jsa_forecast, 1),
                            "Error (bu/ac)":  round(_jsa_forecast - _bty_act, 2),
                        })

                    _bt_df = pd.DataFrame(_bt_rows).sort_values("Year", ascending=False).reset_index(drop=True)

                    # ── Step 5: Summary stats ─────────────────────────────────────────
                    _jsa_errs = _bt_df["Error (bu/ac)"].dropna()

                    _stat_cols = st.columns(4)
                    for _sc, (_sv, _sl) in zip(_stat_cols, [
                        (f"{float(_jsa_errs.abs().mean()):.2f} bu/ac", f"MAE  (n={len(_jsa_errs)} yrs)"),
                        (f"{float(np.sqrt((_jsa_errs**2).mean())):.2f} bu/ac", "RMSE"),
                        (f"{float(_jsa_errs.mean()):+.2f} bu/ac",      "Avg Bias"),
                        (f"{int((_jsa_errs > 0).sum())} / {int((_jsa_errs < 0).sum())}",
                                                                        "Yrs Over / Under"),
                    ]):
                        with _sc:
                            st.markdown(
                                f'<div class="kpi-card"><div class="kpi-main">{_sv}</div>'
                                f'<div class="kpi-label">{_sl}</div></div>',
                                unsafe_allow_html=True,
                            )

                    st.markdown("<div style='margin-top:0.8rem'></div>", unsafe_allow_html=True)

                    # ── Step 6: Chart — Actual vs JSA Forecast ───────────────────────
                    _bty_sorted = _bt_df.sort_values("Year")
                    _bt_fig = go.Figure()

                    # Trend line
                    _bt_fig.add_trace(go.Scatter(
                        x=_bty_sorted["Year"], y=_bty_sorted["Trend (bu/ac)"],
                        mode="lines", name="Trend",
                        line=dict(color=DM_MUTED, width=1.5, dash="dot"),
                    ))
                    # Actual USDA
                    _bt_fig.add_trace(go.Scatter(
                        x=_bty_sorted["Year"], y=_bty_sorted["Actual (bu/ac)"],
                        mode="lines+markers", name="USDA Actual",
                        line=dict(color=JPSI_BLUE, width=2.5),
                        marker=dict(size=6, color=JPSI_BLUE),
                        hovertemplate="<b>USDA Actual</b> %{x}<br>%{y:.1f} bu/ac<extra></extra>",
                    ))
                    # JSA forecast
                    _bt_fig.add_trace(go.Scatter(
                        x=_bty_sorted["Year"], y=_bty_sorted["JSA Forecast"],
                        mode="lines+markers", name="JSA Forecast",
                        line=dict(color="#f59e0b", width=2, dash="dash"),
                        marker=dict(size=5, color="#f59e0b"),
                        hovertemplate="<b>JSA Forecast</b> %{x}<br>%{y:.1f} bu/ac<extra></extra>",
                    ))

                    _bt_fig.update_layout(
                        height=380,
                        paper_bgcolor=DM_BG,
                        plot_bgcolor=DM_SURFACE2,
                        font=dict(color=DM_TEXT, size=12),
                        legend=dict(
                            bgcolor=DM_SURFACE, bordercolor=DM_BORDER, borderwidth=1,
                            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                        ),
                        xaxis=dict(title="Harvest Year", gridcolor=DM_BORDER, zeroline=False),
                        yaxis=dict(title="Yield (bu/ac)", gridcolor=DM_BORDER, zeroline=False),
                        hovermode="x unified",
                        margin=dict(l=60, r=20, t=30, b=50),
                    )
                    _show_chart(_bt_fig, "backtest_yield")

                    # ── Step 7: Error bar chart ────────────────────────────────────────
                    _err_fig = go.Figure()
                    _err_fig.add_trace(go.Bar(
                        x=_bty_sorted["Year"],
                        y=_bty_sorted["JSA Error"],
                        name="JSA-Only Error",
                        marker_color=[
                            "rgba(245,158,11,0.6)" if e >= 0 else "rgba(245,158,11,0.9)"
                            for e in _bty_sorted["JSA Error"]
                        ],
                        hovertemplate="<b>JSA-Only Error</b> %{x}<br>%{y:+.2f} bu/ac<extra></extra>",
                    ))
                    _err_fig.add_trace(go.Bar(
                        x=_bty_sorted["Year"],
                        y=_bty_sorted["Combined Error"],
                        name="Combined Error",
                        marker_color=[
                            "rgba(74,222,128,0.6)" if e >= 0 else "rgba(74,222,128,0.9)"
                            for e in _bty_sorted["Combined Error"]
                        ],
                        hovertemplate="<b>Combined Error</b> %{x}<br>%{y:+.2f} bu/ac<extra></extra>",
                    ))
                    _err_fig.add_hline(y=0, line_color=DM_BORDER, line_width=1)
                    _err_fig.update_layout(
                        height=240,
                        barmode="group",
                        paper_bgcolor=DM_BG,
                        plot_bgcolor=DM_SURFACE2,
                        font=dict(color=DM_TEXT, size=11),
                        xaxis=dict(gridcolor=DM_BORDER, zeroline=False),
                        yaxis=dict(title="Forecast Error (bu/ac)", gridcolor=DM_BORDER, zeroline=False),
                        legend=dict(bgcolor=DM_SURFACE, bordercolor=DM_BORDER, borderwidth=1,
                                    orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        margin=dict(l=60, r=20, t=10, b=40),
                        title=dict(
                            text="Forecast Error: positive = overestimate · negative = underestimate",
                            font=dict(size=11, color=DM_MUTED), x=0,
                        ),
                    )
                    _show_chart(_err_fig, "backtest_error")

                    # ── Step 8: Year-by-year table ─────────────────────────────────────
                    with st.expander("📋 Year-by-Year Backtest Detail", expanded=False):
                        st.dataframe(
                            _bt_df,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Year":           st.column_config.NumberColumn("Year", format="%d"),
                                "Trend (bu/ac)":  st.column_config.NumberColumn("Trend", format="%.1f"),
                                "Actual (bu/ac)": st.column_config.NumberColumn("USDA Actual", format="%.1f"),
                                "JSA Index (wk)": st.column_config.NumberColumn(
                                    f"JSA Idx (wk {_bt_best_iso})", format="%.1f"),
                                "JSA Forecast":   st.column_config.NumberColumn("JSA Forecast", format="%.1f"),
                                "Error (bu/ac)":  st.column_config.NumberColumn("Error (bu/ac)", format="%+.2f"),
                            },
                        )
                        _dl_btn(_bt_df, "corn_jsa_model_backtest.xlsx", "⬇ Download Backtest")
                        st.caption(
                            f"Best-signal ISO week for JSA conditions: **week {_bt_best_iso}** "
                            f"(~{_iso_lbl(_bt_best_iso)}).  "
                            f"JSA→yield OLS: slope = {_bt_slope:.4f} %dev per JSA pt, "
                            f"intercept = {_bt_icept:.4f}.  "
                            "In-sample regression — same data used for fitting and evaluation."
                        )

                    # ── Step 9: State-level backtest summary (last 15 yrs) ───────────
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown(
                        f'<div style="font-size:0.9rem;font-weight:700;color:{JPSI_BLUE};'
                        f'margin-bottom:6px">State-Level JSA Model Performance — Last 15 Years</div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        "For each major corn state: how the JSA conditions model (at best-signal "
                        f"week) performed vs USDA final yield over the last 15 harvest years. "
                        "Uses each state's own yield trend and JSA conditions series."
                    )

                    _st_summary_rows = []
                    _min_yr_15 = sel_usda_yr - 15

                    # States in scan results that have yield data (exclude index-level keys)
                    _priority_keys = {"US", "HRW", "SRW", "White"}
                    _st_keys_bt = sorted(
                        [k for k in _scan_res if k not in _priority_keys],
                        key=lambda k: k
                    )

                    for _stk in _st_keys_bt:
                        _st_scan = _scan_res.get(_stk)
                        if _st_scan is None:
                            continue
                        _stk_best_iso = int(_st_scan["best_iso"])
                        _stk_yl = _yield_lookup.get(_stk, {})
                        if len(_stk_yl) < 8:
                            continue

                        # State JSA series
                        _stk_jsa_df = _us_series(raw_df, "JSA Index", _stk).copy()
                        if _stk_jsa_df.empty:
                            continue
                        _stk_jsa_df["week_ending"] = pd.to_datetime(_stk_jsa_df["week_ending"])
                        _stk_jsa_df["crop_year"]   = _stk_jsa_df["week_ending"].dt.year
                        _stk_jsa_df["iso_week"]    = _stk_jsa_df["week_ending"].dt.isocalendar().week.astype(int)

                        _stk_snap: dict[int, float] = {}
                        for _scy, _scg in _stk_jsa_df[_stk_jsa_df["crop_year"] < sel_usda_yr].groupby("crop_year"):
                            _sidx = int(np.argmin(np.abs(_scg["iso_week"].values - _stk_best_iso)))
                            _stk_snap[int(_scy)] = float(_scg.iloc[_sidx]["metric"])

                        # OLS for this state
                        _stk_pairs = [
                            (float(_stk_snap[yr]), float(_stk_yl[yr]["dev"]))
                            for yr in _stk_snap
                            if yr in _stk_yl and _stk_yl[yr].get("dev") is not None
                        ]
                        if len(_stk_pairs) < 8:
                            continue
                        _stk_xs = np.array([p[0] for p in _stk_pairs])
                        _stk_ys = np.array([p[1] for p in _stk_pairs])
                        _stk_c  = np.polyfit(_stk_xs, _stk_ys, 1)
                        _stk_sl, _stk_ic = float(_stk_c[0]), float(_stk_c[1])

                        # Build per-year errors for last 15 years (JSA-only)
                        _stk_errs_jsa = []
                        for yr in _stk_snap:
                            if yr < _min_yr_15 or yr not in _stk_yl:
                                continue
                            if _stk_yl[yr].get("dev") is None:
                                continue
                            _s_act   = float(_stk_yl[yr]["yield"])
                            _s_trend = float(_stk_yl[yr]["trend"])
                            _s_jval  = _stk_snap[yr]
                            _s_pred  = _stk_sl * _s_jval + _stk_ic
                            _s_jfore = _s_trend * (1.0 + _s_pred / 100.0)
                            _stk_errs_jsa.append(_s_jfore - _s_act)

                        if not _stk_errs_jsa:
                            continue

                        _ej = np.array(_stk_errs_jsa)
                        _st_summary_rows.append({
                            "State":     _stk,
                            "Best Wk":  _stk_best_iso,
                            "MAE":      round(float(np.abs(_ej).mean()), 2),
                            "Avg Bias": round(float(_ej.mean()), 2),
                            "Yrs Above": int((_ej > 0).sum()),
                            "Yrs Below": int((_ej < 0).sum()),
                            "n":         len(_ej),
                        })

                    if _st_summary_rows:
                        _st_sum_df = (pd.DataFrame(_st_summary_rows)
                                      .sort_values("State")
                                      .reset_index(drop=True))
                        st.dataframe(
                            _st_sum_df,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "State":     st.column_config.TextColumn("State", width="small"),
                                "Best Wk":   st.column_config.NumberColumn("Best Wk", format="%d", width="small",
                                                 help="ISO week with highest R² between JSA conditions and yield deviation"),
                                "MAE":       st.column_config.NumberColumn("MAE (bu/ac)", format="%.2f",
                                                 help="Mean absolute error — JSA conditions model"),
                                "Avg Bias":  st.column_config.NumberColumn("Avg Bias (bu/ac)", format="%+.2f",
                                                 help="Positive = model overestimates on average"),
                                "Yrs Above": st.column_config.NumberColumn("Yrs Above", format="%d", width="small"),
                                "Yrs Below": st.column_config.NumberColumn("Yrs Below", format="%d", width="small"),
                                "n":         st.column_config.NumberColumn("n", format="%d", width="small"),
                            },
                        )
                        _dl_btn(_st_sum_df, "state_jsa_model_backtest.xlsx",
                                "⬇ Download State Summary")
                    else:
                        st.info("Not enough state-level data to build the summary table.")

        except Exception as _bt_exc:
            st.warning(f"JSA model backtest failed: {_bt_exc}")

    # ── LOO Predicted vs Actual Scatter ───────────────────────────────────────────
    st.markdown(
        '<div class="sec-hdr">LOO Model Prediction vs USDA Benchmark — Scatter Validation</div>',
        unsafe_allow_html=True,
    )
    # Active series key: state if one is selected, otherwise the main series (US / HRW / etc.)
    _loo_sk = sel_state_alpha if sel_state_alpha else _series_key
    # Recompute analog for the active key if it differs from the main result
    if sel_state_alpha and sel_state_alpha != _series_key:
        _loo_af_src = _compute_analog_forecast(
            sel_state_alpha, raw_df, _effective_week_ts(sel_state_alpha), sel_usda_yr,
            _yield_lookup, _trend_data, _dynamic_hrw_weights,
            class_weights_map={"HRW": _dynamic_hrw_weights, "SRW": _dynamic_srw_weights,
                               "White": _dynamic_white_weights},
            crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
            cond_weights=_active_cw,
        )
    else:
        _loo_af_src = _analog_result if _analog_result else None
    _loo_iso_wk = int(pd.Timestamp(sel_week).isocalendar().week) if sel_week else None

    # If the best-signal week has already passed, lock the scatter to that week
    # so the comparison is always at the historically most informative conditions snapshot.
    _loo_locked_to_best = False
    if _loo_iso_wk and "_scan_res" in dir() and _scan_res:
        _loo_scan_entry = _scan_res.get(_loo_sk) or _scan_res.get("US")
        if _loo_scan_entry:
            _best_iso = int(_loo_scan_entry["best_iso"])
            if _best_iso <= _loo_iso_wk and _best_iso != _loo_iso_wk:
                # Find the actual week_ending date for this ISO week in the data
                _loo_target_dt = pd.Timestamp(datetime.fromisocalendar(sel_usda_yr - 1, _best_iso, 3))
                _loo_avail = pd.to_datetime(raw_df["week_ending"].drop_duplicates()).sort_values()
                _loo_diffs = (_loo_avail - _loo_target_dt).abs()
                if not _loo_diffs.empty:
                    _loo_best_wk_ts = _loo_avail.iloc[_loo_diffs.argmin()]
                    _loo_af_src = _compute_analog_forecast(
                        _loo_sk, raw_df, _loo_best_wk_ts, sel_usda_yr,
                        _yield_lookup, _trend_data, _dynamic_hrw_weights,
                        class_weights_map={"HRW": _dynamic_hrw_weights, "SRW": _dynamic_srw_weights,
                                           "White": _dynamic_white_weights},
                        crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                        cond_weights=_active_cw,
                    )
                    _loo_iso_wk = _best_iso
                    _loo_locked_to_best = True

    if _loo_af_src and _loo_iso_wk and not _yield_full.empty:
        # Benchmark selector
        _BENCH_OPTIONS = [
            ("August Forecast",   "AUG FORECAST"),
            ("September Forecast","SEP FORECAST"),
            ("October Forecast",  "OCT FORECAST"),
            ("November Forecast", "NOV FORECAST"),
            ("Final (January)",   "FINAL"),
        ]
        _bench_labels = [b[0] for b in _BENCH_OPTIONS]
        _bench_sel = st.radio(
            "USDA benchmark to compare against",
            _bench_labels,
            index=len(_bench_labels) - 1,
            horizontal=True,
            key="loo_bench_radio",
        )
        _bench_ref = dict(_BENCH_OPTIONS)[_bench_sel]

        # Fetch monthly USDA yield history (cached) — state or national
        _loo_cy_range = tuple(range(2000, sel_usda_yr))
        _loo_monthly_df = fetch_usda_monthly_yield_history(
            _c_desc,
            _cl_desc,
            _loo_cy_range,
            unit_desc=_yield_unit or "BU / ACRE",
            state_alpha=sel_state_alpha if sel_state_alpha else None,
        )
        # Build lookup: crop_year → USDA benchmark yield
        _bench_lkup: dict[int, float] = {}
        if not _loo_monthly_df.empty:
            _bdf = _loo_monthly_df[_loo_monthly_df["ref_period"] == _bench_ref]
            for _, _br in _bdf.iterrows():
                _bench_lkup[int(_br["crop_year"])] = float(_br["yield_bu_ac"])

        _loo_wk_note = (
            f"🔒 Locked to **best-signal Wk {_loo_iso_wk}** (highest historical R² for this series)."
            if _loo_locked_to_best else
            f"Using current sidebar week **Wk {_loo_iso_wk}** (best-signal week not yet reached)."
        )
        st.caption(
            f"Leave-one-out cross-validation: for each historical year the JSA model is re-trained "
            f"on **all other years** and used to predict that year's yield. "
            f"Y-axis = **USDA {_bench_sel}** for that crop year. "
            f"Points on the dashed line = perfect agreement. "
            f"{_loo_wk_note}"
        )

        _loo_snap = _loo_af_src.get("jsa_snap", {})
        _loo_lkup = _yield_lookup.get(_loo_sk, {})

        _loo_pts = []
        for _lyr in sorted(_loo_snap.keys()):
            if _lyr == sel_usda_yr:
                continue
            if _lyr not in _loo_lkup or _loo_lkup[_lyr].get("dev") is None:
                continue
            if _lyr not in _bench_lkup:
                continue
            _train = [
                (_loo_snap[cy], _loo_lkup[cy]["dev"])
                for cy in _loo_snap
                if cy != _lyr and cy != sel_usda_yr
                and cy in _loo_lkup and _loo_lkup[cy].get("dev") is not None
            ]
            if len(_train) < 3:
                continue
            _ltx = np.array([p[0] for p in _train])
            _lty = np.array([p[1] for p in _train])
            _llc = np.linalg.lstsq(
                np.vstack([_ltx, np.ones(len(_ltx))]).T, _lty, rcond=None
            )[0]
            _lpred_dev   = float(_llc[0] * float(_loo_snap[_lyr]) + _llc[1])
            _lpred_yield = _loo_lkup[_lyr]["trend"] * (1 + _lpred_dev / 100)
            _loo_pts.append({
                "year":      _lyr,
                "predicted": round(_lpred_yield, 1),
                "benchmark": _bench_lkup[_lyr],
            })

        if len(_loo_pts) >= 4:
            _loo_df   = pd.DataFrame(_loo_pts)
            _loo_err  = _loo_df["predicted"] - _loo_df["benchmark"]
            _loo_rmse = float(np.sqrt(np.mean(_loo_err ** 2)))
            _loo_mae  = float(_loo_err.abs().mean())
            _loo_bias = float(_loo_err.mean())
            _loo_corr = float(np.corrcoef(_loo_df["predicted"], _loo_df["benchmark"])[0, 1])
            _loo_r2   = round(_loo_corr ** 2 * 100, 1)
            _n_loo    = len(_loo_df)

            _lstat_cols = st.columns(4)
            for _lsc, (_lsv, _lsl) in zip(_lstat_cols, [
                (f"{_loo_r2:.1f}%",                                     f"R²  (n={_n_loo} yrs)"),
                (f"{_loo_rmse:.2f} bu/ac",                              "RMSE"),
                (f"{_loo_mae:.2f} bu/ac",                               "MAE"),
                (f"{'+'if _loo_bias>=0 else ''}{_loo_bias:.2f} bu/ac",  "Bias (model − USDA)"),
            ]):
                with _lsc:
                    st.metric(_lsl, _lsv)

            _lxy_pad = 3
            _lxy_min = min(_loo_df["predicted"].min(), _loo_df["benchmark"].min()) - _lxy_pad
            _lxy_max = max(_loo_df["predicted"].max(), _loo_df["benchmark"].max()) + _lxy_pad

            # Regression line (predicted → benchmark)
            _lreg_x = np.array(_loo_df["predicted"].tolist())
            _lreg_y = np.array(_loo_df["benchmark"].tolist())
            _lreg_c = np.linalg.lstsq(
                np.vstack([_lreg_x, np.ones(len(_lreg_x))]).T, _lreg_y, rcond=None
            )[0]
            _lreg_y0 = float(_lreg_c[0] * _lxy_min + _lreg_c[1])
            _lreg_y1 = float(_lreg_c[0] * _lxy_max + _lreg_c[1])

            _loo_fig = go.Figure()
            _loo_fig.add_trace(go.Scatter(
                x=[_lxy_min, _lxy_max], y=[_lxy_min, _lxy_max],
                mode="lines",
                line=dict(color=DM_MUTED, width=1.5, dash="dash"),
                name="Perfect Agreement",
                hoverinfo="skip",
            ))
            _loo_fig.add_trace(go.Scatter(
                x=[_lxy_min, _lxy_max], y=[_lreg_y0, _lreg_y1],
                mode="lines",
                line=dict(color="#e05c2a", width=1.5),
                name=f"Trend (slope={_lreg_c[0]:.2f})",
                hoverinfo="skip",
            ))
            _loo_fig.add_trace(go.Scatter(
                x=_loo_df["predicted"].tolist(),
                y=_loo_df["benchmark"].tolist(),
                mode="markers+text",
                text=_loo_df["year"].astype(str).tolist(),
                textposition="top right",
                textfont=dict(size=10, color=DM_TEXT),
                marker=dict(size=9, color=JPSI_BLUE, opacity=0.85,
                            line=dict(width=1, color="white")),
                name=f"Historical year (LOO vs {_bench_sel})",
                customdata=_loo_err.round(1).tolist(),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    f"Wk {_loo_iso_wk} model: %{{x:.1f}} bu/ac<br>"
                    f"USDA {_bench_sel}: %{{y:.1f}} bu/ac<br>"
                    "Difference: %{customdata:+.1f} bu/ac<extra></extra>"
                ),
            ))
            # Current-year annotation: full-fit model forecast → trendline-implied USDA
            _cur_jsa_val  = _loo_af_src.get("cur_jsa")
            _ann_text     = ""
            _cur_model_yield = None
            if _cur_jsa_val is not None:
                _full_train = [
                    (_loo_snap[cy], _loo_lkup[cy]["dev"])
                    for cy in _loo_snap
                    if cy != sel_usda_yr and cy in _loo_lkup
                    and _loo_lkup[cy].get("dev") is not None
                ]
                if len(_full_train) >= 3:
                    _ftx = np.array([p[0] for p in _full_train])
                    _fty = np.array([p[1] for p in _full_train])
                    _flc = np.linalg.lstsq(
                        np.vstack([_ftx, np.ones(len(_ftx))]).T, _fty, rcond=None
                    )[0]
                    _cur_td = _trend_data.get(_loo_sk)
                    _cur_tl = _trend_at(_cur_td, sel_usda_yr) if _cur_td else None
                    if _cur_tl:
                        _cur_pred_dev    = float(_flc[0] * float(_cur_jsa_val) + _flc[1])
                        _cur_model_yield = round(_cur_tl * (1 + _cur_pred_dev / 100), 1)
                        _implied_usda    = round(float(_lreg_c[0] * _cur_model_yield + _lreg_c[1]), 1)
                        _ann_text = (
                            f"<b>{sel_usda_yr} JSA Model (Wk {_loo_iso_wk}):</b> {_cur_model_yield} bu/ac<br>"
                            f"<b>Trendline implies USDA {_bench_sel}:</b> {_implied_usda} bu/ac"
                        )

            _loo_fig.update_layout(
                title=dict(
                    text=f"Wk {_loo_iso_wk} JSA Model vs USDA {_bench_sel} — {sel_state_name if sel_state_alpha else 'US'} {commodity_label}",
                    font=dict(size=14, color=DM_TEXT),
                    subtitle=dict(
                        text=(
                            f"US national · {int(_loo_df['year'].min())}–{int(_loo_df['year'].max())}"
                            f" · leave-one-out · dashed line = perfect agreement"
                        ),
                        font=dict(size=11, color=DM_MUTED),
                    ),
                ),
                xaxis=dict(
                    title=f"Wk {_loo_iso_wk} JSA model predicted yield (bu/ac)",
                    range=[_lxy_min, _lxy_max],
                    gridcolor=DM_BORDER, color=DM_MUTED, showgrid=True,
                ),
                yaxis=dict(
                    title=f"USDA {_bench_sel} (bu/ac)",
                    range=[_lxy_min, _lxy_max],
                    gridcolor=DM_BORDER, color=DM_MUTED, showgrid=True,
                ),
                plot_bgcolor=DM_BG, paper_bgcolor=DM_BG,
                font=dict(color=DM_TEXT),
                legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=DM_BORDER,
                            borderwidth=1, font=dict(color=DM_TEXT, size=11)),
                height=520,
                margin=dict(l=60, r=30, t=80, b=60),
                annotations=[dict(
                    text=_ann_text,
                    xref="paper", yref="paper",
                    x=0.98, y=0.04,
                    xanchor="right", yanchor="bottom",
                    showarrow=False,
                    bgcolor="rgba(248,250,251,0.88)",
                    bordercolor=DM_BORDER,
                    borderwidth=1,
                    borderpad=6,
                    font=dict(size=11, color=DM_TEXT),
                )] if _ann_text else [],
            )
            # Add vertical line and marker for current-year model forecast
            if _cur_model_yield is not None:
                _loo_fig.add_vline(
                    x=_cur_model_yield,
                    line=dict(color=JPSI_BLUE, width=1, dash="dot"),
                    annotation_text=f"{sel_usda_yr}E: {_cur_model_yield}",
                    annotation_position="top",
                    annotation_font=dict(size=10, color=JPSI_BLUE),
                )
            _show_chart(_loo_fig, "loo_scatter_model_val")
            if _bench_lkup:
                _n_missing = len([y for y in _loo_snap if y < sel_usda_yr and y not in _bench_lkup])
                if _n_missing:
                    st.caption(f"⚠️ {_n_missing} year(s) excluded — USDA {_bench_sel} not available in NASS for those years.")
        elif _bench_lkup:
            st.info("Not enough matched data points for LOO scatter (need ≥ 4 years).")
        else:
            st.warning(
                f"No USDA **{_bench_sel}** data returned from NASS for {commodity_label}. "
                "This benchmark may not be available for this commodity — try another."
            )
    else:
        st.info("Select a week in the sidebar to display the LOO scatter validation.")

with _tab_prod:
    # Pre-compute model-active flag so both the caption and _jsa_col block can use it
    _non_ww_model_active = (
        commodity_label != "Winter Wheat"
        and sel_week is not None
        and _analog_result is not None
        and _analog_result.get("cur_jsa") is not None
    )
    if commodity_label != "Winter Wheat":
        if _non_ww_model_active:
            _wk_label = (f"{pd.Timestamp(sel_week).strftime('%b %d, %Y')}  Wk {int(pd.Timestamp(sel_week).isocalendar().week)}"
                         if sel_week else "")
            st.caption(
                f"🟢 **JSA model active** — using {commodity_label} crop conditions data "
                f"through **{_wk_label}**. "
                f"Yield estimated from analog-year regression (JSA conditions index → yield deviation from trend). "
                f"Planted and % harvested use the most-recent NASS data available "
                f"(5-yr avg abandonment rate for non-WW crops)."
            )
        else:
            _ssm_name = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                         7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"
                         }.get(commodity_cfg.get("season_start_month", 5), "mid-season")
            st.caption(
                f"ℹ️ USDA has not yet begun reporting **{commodity_label}** crop conditions "
                f"(typically starts {_ssm_name}). "
                f"Showing historical NASS data with **{sel_usda_yr - 1} actuals as the current estimate** "
                f"until conditions reporting begins and the JSA model activates."
            )
    # ── Metric selector ────────────────────────────────────────────────────────────
    _pmet = st.radio(
        "Metric",
        ["Production (BU)", "Planted Acres", "Harvested Acres", "% Harvested", "Yield (bu/ac)"],
        horizontal=True, key="prod_metric_tog",
    )
    _pmet_col = {
        "Production (BU)": "production_bu",
        "Planted Acres":   "planted_ac",
        "Harvested Acres": "harvested_ac",
        "% Harvested":     "pct_harvested",
        "Yield (bu/ac)":   "yield_bu_ac",
    }[_pmet]
    _pmet_is_pct   = _pmet_col == "pct_harvested"
    _pmet_is_yield = _pmet_col == "yield_bu_ac"
    _pmet_is_bu    = _pmet_col == "production_bu"
    _pmet_is_ac    = _pmet_col in ("planted_ac", "harvested_ac")
    _pmet_sfx      = "%" if _pmet_is_pct else (" bu/ac" if _pmet_is_yield else "")
    # Table section header label — clarify units for acres and production metrics
    _pmet_hdr_label = (
        _pmet.replace("Acres", "Acres (Million)") if _pmet_is_ac
        else "Production (Million BU)"             if _pmet_is_bu
        else _pmet
    )

    # ── Build state-level panel DataFrame ──────────────────────────────────────────
    _pp = _prod_tab_prod_df.copy()   # year, state_alpha, [state_name,] production_bu
    # WW acres df uses 'state' column; generic uses 'state_alpha' already
    if commodity_label == "Winter Wheat":
        _pa = _prod_tab_acres_df.rename(columns={"state": "state_alpha"}).copy()
    else:
        _pa = _prod_tab_acres_df.copy()

    if not _pp.empty and not _pa.empty:
        _panel = _pp.merge(
            _pa[["year", "state_alpha", "planted_ac", "harvested_ac"]],
            on=["year", "state_alpha"], how="outer",
        )
    elif not _pp.empty:
        _panel = _pp.copy()
        _panel["planted_ac"] = np.nan
        _panel["harvested_ac"] = np.nan
    elif not _pa.empty:
        _panel = _pa.copy()
        _panel["production_bu"] = np.nan
    else:
        _panel = pd.DataFrame()

    if not _panel.empty:
        # Fill state_name from yield data where missing
        _yn_sname = {}
        if not _yield_raw.empty:
            _yn_sname = dict(zip(_yield_raw["state_alpha"], _yield_raw["state_name"]))
        if "state_name" not in _panel.columns:
            _panel["state_name"] = _panel["state_alpha"].map(_yn_sname)
        else:
            _panel["state_name"] = _panel["state_name"].fillna(
                _panel["state_alpha"].map(_yn_sname)
            )

        _panel["pct_harvested"] = np.where(
            _panel.get("planted_ac", pd.Series(dtype=float)).fillna(0) > 0,
            (_panel["harvested_ac"] / _panel["planted_ac"] * 100).round(1),
            np.nan,
        )

        # Merge NASS-published yield (more accurate than computed)
        if commodity_label == "Winter Wheat" and not _yield_raw.empty:
            _yr_lkup = _yield_raw[_yield_raw["state_alpha"] != "US"][["year", "state_alpha", "yield_bu_ac"]].copy()
            _panel = _panel.merge(_yr_lkup, on=["year", "state_alpha"], how="left")
        elif commodity_label != "Winter Wheat" and not _prod_tab_yield_df.empty:
            _yr_lkup = _prod_tab_yield_df[_prod_tab_yield_df["state_alpha"] != "US"][["year", "state_alpha", "yield_bu_ac"]].copy()
            _panel = _panel.merge(_yr_lkup, on=["year", "state_alpha"], how="left")
        else:
            _panel["yield_bu_ac"] = np.where(
                _panel.get("harvested_ac", pd.Series(dtype=float)).fillna(0) > 0,
                (_panel["production_bu"] / _panel["harvested_ac"]).round(1),
                np.nan,
            )

        _panel["year"] = _panel["year"].astype(int)
        _panel = _panel[_panel["state_alpha"].str.len() == 2]
        _panel = _panel[_panel["state_alpha"] != "US"]

        # Apply wheat class filter from sidebar
        _panel_class_states = _class_states  # None = all
        _panel_all = _panel.copy()           # unfiltered — needed for % harvested regression
        if _panel_class_states is not None:
            _panel = _panel[_panel["state_alpha"].isin(_panel_class_states)]
        if sel_state_alpha is not None:
            _panel = _panel[_panel["state_alpha"] == sel_state_alpha]

        _panel = _panel.sort_values(["year", "state_alpha"]).reset_index(drop=True)

    # ── Display year window (default last 10 with data) ────────────────────────────
    if not _panel.empty:
        _all_yrs = sorted(_panel["year"].dropna().unique().astype(int))
        _default_n = min(10, len(_all_yrs))
        _disp_yrs  = _all_yrs[-_default_n:]
        _panel_disp = _panel[_panel["year"].isin(_disp_yrs)].copy()

        # ── Build aggregate rows (US Total + class totals) ─────────────────────────
        def _agg_rows_for_states(states_set, label_alpha, label_name, sub_df):
            """Sum acres/production; compute derived metrics. Returns one row per year."""
            if states_set is not None:
                grp = sub_df[sub_df["state_alpha"].isin(states_set)]
            else:
                grp = sub_df
            if grp.empty:
                return pd.DataFrame()
            agg = grp.groupby("year").agg(
                production_bu  = ("production_bu",  "sum"),
                planted_ac     = ("planted_ac",     "sum"),
                harvested_ac   = ("harvested_ac",   "sum"),
            ).reset_index()
            agg["pct_harvested"] = np.where(
                agg["planted_ac"] > 0,
                (agg["harvested_ac"] / agg["planted_ac"] * 100).round(1),
                np.nan,
            )
            agg["yield_bu_ac"] = np.where(
                agg["harvested_ac"] > 0,
                (agg["production_bu"] / agg["harvested_ac"]).round(1),
                np.nan,
            )
            agg["state_alpha"] = label_alpha
            agg["state_name"]  = label_name
            return agg[["year", "state_alpha", "state_name",
                         "production_bu", "planted_ac", "harvested_ac",
                         "pct_harvested", "yield_bu_ac"]]

        _agg_rows = []
        # US Total — use official USDA national figures if available, else fall back to state sum
        _all_panel_states = _panel_class_states  # respect filter
        if commodity_label == "Winter Wheat" and not _prod_tab_national_df.empty:
            _nat_disp = _prod_tab_national_df[_prod_tab_national_df["year"].isin(_disp_yrs)].copy()
            _nat_cols = ["year", "state_alpha", "state_name"]
            for _c in ["production_bu", "planted_ac", "harvested_ac", "pct_harvested", "yield_bu_ac"]:
                if _c not in _nat_disp.columns:
                    _nat_disp[_c] = np.nan
            if "pct_harvested" not in _nat_disp.columns or _nat_disp["pct_harvested"].isna().all():
                _nat_disp["pct_harvested"] = np.where(
                    _nat_disp.get("planted_ac", pd.Series(dtype=float)).fillna(0) > 0,
                    (_nat_disp["harvested_ac"] / _nat_disp["planted_ac"] * 100).round(1),
                    np.nan,
                )
            _agg_rows.append(_nat_disp[["year", "state_alpha", "state_name",
                                         "production_bu", "planted_ac", "harvested_ac",
                                         "pct_harvested", "yield_bu_ac"]])
        else:
            _agg_rows.append(_agg_rows_for_states(None, "US", "🇺🇸 US Total", _panel_disp))

        if commodity_cfg.get("has_classes", True) and _panel_class_states is None:
            _hrw_s = WHEAT_CLASSES.get("HRW — Hard Red Winter")
            _srw_s = WHEAT_CLASSES.get("SRW — Soft Red Winter")
            _wht_s = WHEAT_CLASSES.get("White Winter")
            if _hrw_s:
                _agg_rows.append(_agg_rows_for_states(_hrw_s, "HRW", "⬡ HRW", _panel_disp))
            if _srw_s:
                _agg_rows.append(_agg_rows_for_states(_srw_s, "SRW", "⬡ SRW", _panel_disp))
            if _wht_s:
                _agg_rows.append(_agg_rows_for_states(_wht_s, "White", "⬡ White", _panel_disp))
        elif commodity_cfg.get("has_classes", True) and _panel_class_states is not None:
            # Only show the relevant class aggregate
            _cls_lbl_map = {
                frozenset(WHEAT_CLASSES.get("HRW — Hard Red Winter") or []): ("HRW", "⬡ HRW"),
                frozenset(WHEAT_CLASSES.get("SRW — Soft Red Winter") or []): ("SRW", "⬡ SRW"),
                frozenset(WHEAT_CLASSES.get("White Winter") or []):           ("White", "⬡ White"),
            }
            _cls_key = frozenset(_panel_class_states)
            if _cls_key in _cls_lbl_map:
                _ca, _cn = _cls_lbl_map[_cls_key]
                _agg_rows.append(_agg_rows_for_states(_panel_class_states, _ca, _cn, _panel_disp))

        _agg_df = pd.concat([r for r in _agg_rows if not r.empty], ignore_index=True)

        # State share lookup (for row ordering)
        _prod_share_lkup = {}
        if not _panel_disp.empty:
            _tot_by_state = (
                _panel_disp.groupby("state_alpha")["production_bu"]
                .sum().sort_values(ascending=False)
            )
            _tot_all = _tot_by_state.sum()
            _prod_share_lkup = {s: v / _tot_all * 100 for s, v in _tot_by_state.items()} if _tot_all else {}

        # ── Helper: state-level yield from regression ──────────────────────────────
        def _state_yield_reg(skey):
            """Run analog + regression for one state key. Returns bu/ac or None."""
            if sel_week is None or skey not in _trend_data:
                return None
            _s_cwm = {"HRW": _dynamic_hrw_weights, "SRW": _dynamic_srw_weights,
                      "White": _dynamic_white_weights}
            _s_af = _compute_analog_forecast(
                skey, raw_df, _effective_week_ts(skey), sel_usda_yr,
                _yield_lookup, _trend_data, _dynamic_hrw_weights,
                class_weights_map=_s_cwm,
                crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                cond_weights=_active_cw,
            )
            if not _s_af:
                return None
            _s_snap = _s_af.get("jsa_snap", {})
            _s_cur  = _s_af.get("cur_jsa")
            _s_td   = _trend_data[skey]
            _s_tl   = _trend_at(_s_td, sel_usda_yr)
            _s_lkup = _yield_lookup.get(skey, {})
            _s_pts  = [(_s_snap[cy], _s_lkup[cy]["dev"])
                       for cy in _s_snap
                       if cy != sel_usda_yr and cy in _s_lkup
                       and _s_lkup[cy].get("dev") is not None]
            if len(_s_pts) < 3 or _s_cur is None or not _s_tl:
                return None
            _s_x = np.array([p[0] for p in _s_pts])
            _s_y = np.array([p[1] for p in _s_pts])
            _s_lc = np.linalg.lstsq(np.vstack([_s_x, np.ones(len(_s_x))]).T, _s_y, rcond=None)[0]
            _s_cur_f = float(_s_cur)
            _s_dev = float(_s_lc[0] * _s_cur_f + _s_lc[1])
            return round(_s_tl * (1 + _s_dev / 100), 1)

        # ── For non-Winter Wheat: populate estimate column ────────────────────────
        # When conditions data is actively reporting (USDA has released weekly updates
        # for the current marketing year), use the JSA yield regression model.
        # Before conditions begin (e.g. Corn before mid-May), fall back to LY actuals.
        # (_non_ww_model_active is already set at the top of _tab_prod)
        _jsa_col = {}   # always init here so Winter Wheat path can overwrite below
        if commodity_label != "Winter Wheat":
            _non_ww_model_active = (
                sel_week is not None
                and _analog_result is not None
                and _analog_result.get("cur_jsa") is not None
            )

            if _non_ww_model_active:
                # ── JSA model is live: estimate yield from conditions regression ────
                # Use _panel_all so we cover all states even if a state filter is active.
                # Planted / % harvested come from the most-recent NASS data available;
                # yield comes from the state-level analog/regression (fallback: US model).
                _nat_yd, _ = _jsa_reg_forecast("US")

                for _sk in sorted(_panel_all["state_alpha"].unique()):
                    if len(_sk) != 2:
                        continue

                    # Most recent planted acres: prefer current yr data if NASS has it
                    _st_cur_yr = _panel_all[(_panel_all["state_alpha"] == _sk) &
                                            (_panel_all["year"] == sel_usda_yr)]
                    _st_ly     = _panel_all[(_panel_all["state_alpha"] == _sk) &
                                            (_panel_all["year"] == sel_usda_yr - 1)]
                    _plt_src   = _st_cur_yr if not _st_cur_yr.empty else _st_ly
                    _plt = float(_plt_src["planted_ac"].iloc[0]) if (
                        not _plt_src.empty and pd.notna(_plt_src["planted_ac"].iloc[0])
                    ) else None

                    # % Harvested: 5-year historical average (stable for non-WW;
                    # no dormancy die-off, so abandonment barely moves year-to-year)
                    _st_hist5 = _panel_all[
                        (_panel_all["state_alpha"] == _sk) &
                        (_panel_all["year"] < sel_usda_yr) &
                        (_panel_all["year"] >= sel_usda_yr - 5)
                    ]
                    _ph_hist = _st_hist5["pct_harvested"].dropna()
                    if not _ph_hist.empty:
                        _ph = round(float(_ph_hist.mean()), 1)
                    elif not _st_ly.empty and pd.notna(_st_ly["pct_harvested"].iloc[0]):
                        _ph = round(float(_st_ly["pct_harvested"].iloc[0]), 1)
                    else:
                        _ph = None

                    # Yield: state-level JSA regression → fallback national model
                    _yd = _state_yield_reg(_sk)
                    if _yd is None:
                        _yd = _nat_yd   # national yield as crude fallback

                    _harv = round(_plt * _ph / 100) if (_plt and _ph is not None) else None
                    _prod = round(_harv * _yd)       if (_harv and _yd is not None) else None
                    _jsa_col[_sk] = {
                        "production_bu": _prod,
                        "planted_ac":    _plt,
                        "harvested_ac":  _harv,
                        "pct_harvested": _ph,
                        "yield_bu_ac":   _yd,
                    }

                # US aggregate — sum state planted/harvested, apply national yield
                _us_st_rows = _panel_all[
                    (_panel_all["year"].isin([sel_usda_yr, sel_usda_yr - 1])) &
                    (_panel_all["state_alpha"].str.len() == 2)
                ]
                # Use current-year rows if NASS has them; otherwise use LY
                _us_cy = _us_st_rows[_us_st_rows["year"] == sel_usda_yr]
                _us_ref = _us_cy if not _us_cy.empty else _us_st_rows[_us_st_rows["year"] == sel_usda_yr - 1]
                if not _us_ref.empty:
                    _us_plt  = float(_us_ref["planted_ac"].sum())  if "planted_ac"  in _us_ref else None
                    _us_harv = float(_us_ref["harvested_ac"].sum()) if "harvested_ac" in _us_ref else None
                    _us_ph   = (round(_us_harv / _us_plt * 100, 1)
                                if (_us_plt and _us_harv and _us_plt > 0) else None)
                    _us_prod = round(_us_harv * _nat_yd) if (_us_harv and _nat_yd) else None
                    _jsa_col["US"] = {
                        "production_bu": _us_prod,
                        "planted_ac":    _us_plt,
                        "harvested_ac":  _us_harv,
                        "pct_harvested": _us_ph,
                        "yield_bu_ac":   _nat_yd,
                    }

            else:
                # ── Conditions not yet reporting: use LY actuals as placeholder ────
                _ly_rows = _panel[_panel["year"] == sel_usda_yr - 1]
                for _, _lr in _ly_rows.iterrows():
                    _sk = _lr["state_alpha"]
                    _jsa_col[_sk] = {
                        "production_bu": _lr.get("production_bu"),
                        "planted_ac":    _lr.get("planted_ac"),
                        "harvested_ac":  _lr.get("harvested_ac"),
                        "pct_harvested": _lr.get("pct_harvested"),
                        "yield_bu_ac":   _lr.get("yield_bu_ac"),
                    }
                # Aggregate row (US total) from panel
                _us_rows = _panel[_panel["year"] == sel_usda_yr - 1]
                if not _us_rows.empty:
                    _jsa_col["US"] = {
                        "production_bu": _us_rows["production_bu"].sum() if "production_bu" in _us_rows else None,
                        "planted_ac":    _us_rows["planted_ac"].sum()    if "planted_ac"    in _us_rows else None,
                        "harvested_ac":  _us_rows["harvested_ac"].sum()  if "harvested_ac"  in _us_rows else None,
                        "pct_harvested": None,
                        "yield_bu_ac":   None,
                    }

        # ── JSA Model estimates for current marketing year ─────────────────────────
        # {state_alpha → {production_bu, planted_ac, harvested_ac, pct_harvested, yield_bu_ac}}
        # (Winter Wheat only — non-WW _jsa_col is already populated above)

        # ── Helper: fit linear regression of pct_harvested vs JSA index ────────────
        def _ph_regression(cls_key, states_set, natl_acres_df=None):
            """Predict % harvested from JSA index for a class. Returns float or None.

            natl_acres_df (optional): national NASS class-specific planted/harvested
              DataFrame (columns: year, planted_ac, harvested_ac) from
              fetch_class_national_acres.  When provided the regression is calibrated
              on official USDA national class actuals — the correct denominator.
              The JSA regression is ONLY used to produce the current-year forecast
              point; all historical % harvested values come from NASS directly.
              Falls back to _panel_all total-WW proxy only when NASS data is absent.
            """
            _af = _class_analog_results.get(cls_key)
            if not _af or not _af.get("jsa_snap"):
                return None
            _snap = _af["jsa_snap"]
            _cur  = _af.get("cur_jsa")
            if _cur is None:
                return None

            def _pts_from_natl(harv_df):
                """Build (JSA, pct_harvested) pairs using NASS national class harvested
                (authoritative) as numerator and state-panel planted as denominator.
                NASS does not publish class planted at national level; the state-sum
                planted for the class states is the best available denominator."""
                _sub = (_panel_all[_panel_all["state_alpha"].isin(states_set)]
                        if states_set else _panel_all)
                _result = []
                for _yr, _jv in _snap.items():
                    if _yr == sel_usda_yr:
                        continue
                    # Planted from state panel (best available proxy)
                    _yr_sub = _sub[_sub["year"] == _yr]
                    _p = float(_yr_sub["planted_ac"].sum()) if not _yr_sub.empty else 0.0
                    if _p <= 0:
                        continue
                    # Harvested from NASS national class data
                    _hrow = harv_df[harv_df["year"] == _yr]
                    if _hrow.empty:
                        continue
                    _h = float(_hrow["harvested_ac"].iloc[0])
                    _h = min(_h, _p)   # physical cap
                    _result.append((_jv, _h / _p * 100))
                return _result

            def _pts_from_panel():
                """Build (JSA, pct_harvested) pairs from total-WW panel_all (fallback)."""
                _sub = (_panel_all[_panel_all["state_alpha"].isin(states_set)]
                        if states_set else _panel_all)
                _result = []
                for _yr, _jv in _snap.items():
                    if _yr == sel_usda_yr:
                        continue
                    _yr_sub = _sub[_sub["year"] == _yr]
                    _p = float(_yr_sub["planted_ac"].sum())  if not _yr_sub.empty else 0.0
                    _h = float(_yr_sub["harvested_ac"].sum()) if not _yr_sub.empty else 0.0
                    if _p > 0 and _h >= 0:
                        _result.append((_jv, _h / _p * 100))
                return _result

            # Primary: hybrid using NASS national class harvested + state planted.
            # Fallback: total-WW panel proxy (if NASS class harvested unavailable).
            _MIN_PTS = 8
            _pts = []
            if natl_acres_df is not None and not natl_acres_df.empty:
                _pts = _pts_from_natl(natl_acres_df)
                if len(_pts) < _MIN_PTS:
                    _pts = _pts_from_panel()
            else:
                _pts = _pts_from_panel()

            if len(_pts) < 3:
                return None
            _xh = np.array([p[0] for p in _pts])
            _yh = np.array([p[1] for p in _pts])
            _hc = np.linalg.lstsq(np.vstack([_xh, np.ones(len(_xh))]).T, _yh, rcond=None)[0]
            # Reject backward slope: higher JSA must → higher % harvested
            if float(_hc[0]) <= 0:
                return round(float(_yh.mean()), 1)
            # Clamp input JSA to training range — prevents regression extrapolation
            # when current conditions fall outside historical observations
            _cur_clipped = float(np.clip(float(_cur), _xh.min(), _xh.max()))
            _pred = float(_hc[0] * _cur_clipped + _hc[1])
            # Clamp output to historical observed range ± 2 pp (same logic as
            # _state_pct_harv_reg; prevents phantom record % harvested values)
            _lo = max(0.0,   float(_yh.min()) - 2.0)
            _hi = min(100.0, float(_yh.max()) + 2.0)
            return round(max(_lo, min(_hi, _pred)), 1)

        # ── USDA planted acres — most authoritative estimate available ───────────────
        # NASS releases winter wheat planted acres across multiple reports through
        # the crop year (Jan Seedings → Mar Prospective Plantings → Jun Acreage →
        # monthly Crop Production → Jan final).  fetch_planted_acres_for_year()
        # queries all reference periods in a single call and automatically selects
        # the highest-priority (most final) estimate per state, so the JSA column
        # updates whenever NASS loads a new report into QuickStats.
        #
        # Winter wheat planted in Fall Y = marketing year (Y+1)/(Y+2).
        # sel_usda_yr=2026 → planted fall 2025.  NASS keys this as year=2026.
        # Fall back to year=sel_usda_yr-1 in case NASS uses the seeding-year key.
        _planted_lkup: dict  = {}   # state_alpha (upper) → planted_ac float
        _planted_data_yr: int = 0   # actual NASS year key found (for caption)
        _planted_ref_src: str = ""  # reference_period_desc of winning estimate

        # Use data prefetched at startup (avoids spinner delay when tab first opens)
        _curr_planted_df = pd.DataFrame()
        if not _pf_planted_cur.empty:
            _curr_planted_df = _pf_planted_cur
            _planted_data_yr = sel_usda_yr
        elif not _pf_planted_ly.empty:
            _curr_planted_df = _pf_planted_ly
            _planted_data_yr = sel_usda_yr - 1

        if not _curr_planted_df.empty:
            _planted_lkup = dict(
                zip(_curr_planted_df["state_alpha"].str.upper(),
                    _curr_planted_df["planted_ac"])
            )
            # Surface the most common reference period for the caption label
            if "ref_period" in _curr_planted_df.columns:
                _ref_counts = _curr_planted_df["ref_period"].value_counts()
                _planted_ref_src = _ref_counts.index[0] if not _ref_counts.empty else ""

        # Also fetch the prior crop year's planted acres via the same API function
        # so the % change map compares apples-to-apples (same source, same method).
        # _planted_data_yr - 1 is the correct prior year regardless of whether
        # the current-year fetch fell back (e.g. 2025 crop → compare vs 2024 crop).
        _ly_planted_lkup: dict = {}
        _ly_planted_ref_src: str = ""
        if _planted_data_yr > 0:
            # Normal case: prior year = sel_usda_yr - 1 → already prefetched.
            # Rare fallback case (current fetch fell back to sel_usda_yr-1): prior
            # year would be sel_usda_yr-2, which we didn't prefetch, so call normally.
            _ly_planted_df = (
                _pf_planted_ly
                if _planted_data_yr == sel_usda_yr
                else fetch_planted_acres_for_year(_planted_data_yr - 1)
            )
            if not _ly_planted_df.empty:
                _ly_planted_lkup = dict(
                    zip(_ly_planted_df["state_alpha"].str.upper(),
                        _ly_planted_df["planted_ac"])
                )
                if "ref_period" in _ly_planted_df.columns:
                    _ly_ref_counts = _ly_planted_df["ref_period"].value_counts()
                    _ly_planted_ref_src = (
                        _ly_ref_counts.index[0] if not _ly_ref_counts.empty else ""
                    )

        def _get_planted_ac(alpha: str) -> "float | None":
            """Return most-recent USDA planted acres for a state or class aggregate."""
            if alpha in {"US", "HRW", "SRW", "White"}:
                _cls_states = (None           if alpha == "US"
                               else _HRW_STATES if alpha == "HRW"
                               else _SRW_STATES  if alpha == "SRW"
                               else _WHITE_STATES)
                _vals = ([v for v in _planted_lkup.values()] if _cls_states is None
                         else [_planted_lkup[s] for s in _cls_states if s in _planted_lkup])
                return float(sum(_vals)) if _vals else None
            return _planted_lkup.get(alpha.upper())

        # ── Helper: state-level % harvested via abandonment-floor model ─────────────
        def _state_pct_harv_reg(skey: str) -> "float | None":
            """Predict % harvested for one state using the abandonment-floor model.
            Non-SRW states: JSA regression on 10-yr abandoned_ac ÷ planted.
            SRW states: 10-yr rolling avg abandoned_ac ÷ planted (slope unreliable).
            """
            if sel_week is None or skey not in _trend_data:
                return None
            _s_cwm = {"HRW": _dynamic_hrw_weights, "SRW": _dynamic_srw_weights,
                      "White": _dynamic_white_weights}
            _s_af = _compute_analog_forecast(
                skey, raw_df, _effective_week_ts(skey), sel_usda_yr,
                _yield_lookup, _trend_data, _dynamic_hrw_weights,
                class_weights_map=_s_cwm,
                crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                cond_weights=_active_cw,
            )
            if not _s_af:
                return None
            _s_snap = _s_af.get("jsa_snap", {})
            _s_cur  = _s_af.get("cur_jsa")

            # Build state-level historical abandoned acres from the panel
            _s_panel = _panel_all[_panel_all["state_alpha"] == skey]
            _s_hist_rows = []
            for _, _sr in _s_panel[_s_panel["year"] < sel_usda_yr].iterrows():
                _p = _sr.get("planted_ac")
                _h = _sr.get("harvested_ac")
                if pd.notna(_p) and pd.notna(_h) and float(_p) > 0:
                    _s_hist_rows.append({
                        "year":         int(_sr["year"]),
                        "planted_ac":   float(_p),
                        "harvested_ac": float(_h),
                        "abandoned_ac": max(0.0, float(_p) - float(_h)),
                    })
            _s_hist_ab = pd.DataFrame(_s_hist_rows) if _s_hist_rows else pd.DataFrame()

            _is_srw   = skey in _SRW_STATES
            _s_plt    = _get_planted_ac(skey)
            return _ph_from_abandon_model(
                _s_hist_ab, _s_snap, _s_cur, _s_plt,
                use_jsa_model=not _is_srw,
            )

        # ── NASS national class-specific acres — pre-fetched at startup ──────────────
        _hrw_natl_acres = _pf_hrw_natl_ac
        _srw_natl_acres = _pf_srw_natl_ac
        _wht_natl_acres = _pf_wht_natl_ac

        # ── Abandonment-floor % harvested model (replaces direct JSA→% regression) ──
        # Matches the logic in _render_abandon_panel so production and abandonment tabs
        # use the same underlying model.
        #
        # Class level (all classes): JSA regression on 10-yr abandoned_ac ÷ planted
        # State level — non-SRW: JSA regression on 10-yr abandoned_ac ÷ planted
        # State level — SRW states: pure 10-yr rolling avg abandoned_ac ÷ planted

        def _build_hist_ab_df(cls_states, natl_harv_df=None):
            """Build [year, planted_ac, harvested_ac, abandoned_ac] for a class or state.
            cls_states: set of state_alpha codes, or None for all-WW.
            natl_harv_df: NASS national class harvested (year, harvested_ac) if available.
            """
            _sub = (_panel_all[_panel_all["state_alpha"].isin(cls_states)]
                    if cls_states else _panel_all)
            _rows = []
            for _yr in sorted(_sub["year"].unique()):
                if _yr >= sel_usda_yr:
                    continue
                _yr_sub = _sub[_sub["year"] == _yr]
                _plt = float(_yr_sub["planted_ac"].sum()) if not _yr_sub.empty else 0.0
                if _plt <= 0:
                    continue
                if natl_harv_df is not None and not natl_harv_df.empty:
                    _hrow = natl_harv_df[natl_harv_df["year"] == _yr]
                    _harv = float(_hrow["harvested_ac"].iloc[0]) if not _hrow.empty else 0.0
                else:
                    _harv = float(_yr_sub["harvested_ac"].sum()) if not _yr_sub.empty else 0.0
                _harv = min(_harv, _plt)
                _rows.append({"year": _yr, "planted_ac": _plt,
                              "harvested_ac": _harv,
                              "abandoned_ac": _plt - _harv})
            return pd.DataFrame(_rows) if _rows else pd.DataFrame()

        def _ph_from_abandon_model(hist_ab_df, jsa_snap_d, cur_jsa, cur_planted,
                                   use_jsa_model=True):
            """Forecast % harvested using the abandonment-floor model (10-yr window).
            Returns float (% harvested) or None if insufficient data.
            """
            if hist_ab_df.empty or cur_planted is None or cur_planted <= 0:
                return None
            _ab2 = (hist_ab_df.dropna(subset=["abandoned_ac", "planted_ac"])
                               .sort_values("year").tail(10))
            if len(_ab2) < 3:
                return None

            _fc_ab = None
            if use_jsa_model and cur_jsa is not None:
                _ab2j = _ab2.copy()
                _ab2j["_jsa"] = _ab2j["year"].map(jsa_snap_d)
                _ab2j = _ab2j.dropna(subset=["_jsa"])
                if len(_ab2j) >= 5:
                    _ax = _ab2j["_jsa"].values
                    _ay = _ab2j["abandoned_ac"].values
                    _ac = np.linalg.lstsq(
                        np.vstack([_ax, np.ones(len(_ax))]).T, _ay, rcond=None
                    )[0]
                    _fc_ab = float(np.clip(
                        _ac[0] * float(cur_jsa) + _ac[1], 0.0, float(_ay.max())
                    ))
            if _fc_ab is None:
                _fc_ab = float(_ab2["abandoned_ac"].mean())

            _raw_pct = (1.0 - _fc_ab / cur_planted) * 100.0
            # Clamp to historical observed % harvested range ± 2 pp
            _hist_pcts = ((_ab2["planted_ac"] - _ab2["abandoned_ac"])
                          / _ab2["planted_ac"] * 100).dropna()
            _lo = max(0.0,   float(_hist_pcts.min()) - 2.0)
            _hi = min(100.0, float(_hist_pcts.max()) + 2.0)
            return round(float(np.clip(_raw_pct, _lo, _hi)), 1)

        # ── Compute class-level % harvested via abandonment model ─────────────────────
        _cls_ab_data = {
            "US":    _build_hist_ab_df(None),
            "HRW":   _build_hist_ab_df(_HRW_STATES, _hrw_natl_acres if not _hrw_natl_acres.empty else None),
            "SRW":   _build_hist_ab_df(_SRW_STATES, _srw_natl_acres if not _srw_natl_acres.empty else None),
            "White": _build_hist_ab_df(_WHITE_STATES, _wht_natl_acres if not _wht_natl_acres.empty else None),
        }
        _ph_cls = {}
        for _cls_k in ("US", "HRW", "SRW", "White"):
            _af_c  = _class_analog_results.get(_cls_k)
            _snap_c = _af_c.get("jsa_snap", {}) if _af_c else {}
            _cur_c  = _af_c.get("cur_jsa")      if _af_c else None
            _plt_c  = _get_planted_ac(_cls_k)
            _ph_cls[_cls_k] = _ph_from_abandon_model(
                _cls_ab_data[_cls_k], _snap_c, _cur_c, _plt_c, use_jsa_model=True
            )
        # Class fallback map — used only when state-level regression lacks enough data
        _state_ph_fallback = {}
        for _cls_k, _cls_s in [("HRW", _HRW_STATES), ("SRW", _SRW_STATES), ("White", _WHITE_STATES)]:
            if _cls_s and _ph_cls.get(_cls_k) is not None:
                for _ss in _cls_s:
                    _state_ph_fallback[_ss] = _ph_cls[_cls_k]

        # ── Fetch NASS national class data via short_desc + agg_level_desc=NATIONAL ───
        # Previous attempts combining class_desc + state_name/agg_level returned 400.
        # QuickStats website queries by "Data Item" (= short_desc) at Geographic Level
        # NATIONAL.  We replicate that here: one call per class using the full
        # short_desc string (e.g. "WHEAT, HARD RED WINTER - PRODUCTION, MEASURED IN BU")
        # combined with agg_level_desc=NATIONAL — no class_desc, no state_name.
        # Patch _agg_df for sel_usda_yr so both class rows and US Total show the
        # official NASS numbers.
        if commodity_label == "Winter Wheat":
            _REF_PRI_NAT = {
                "YEAR": 100, "YEAR - AUG FORECAST": 70, "YEAR - JUL FORECAST": 60,
                "YEAR - JUN FORECAST": 50, "YEAR - MAY FORECAST": 30,
            }
            # Correct NASS short_desc strings (confirmed from QuickStats website).
            # Format is "WHEAT, WINTER, RED, HARD" — not "WHEAT, HARD RED WINTER".
            # short_desc → (field, cls_key) — class-specific entries only.
            # US all-winter is handled separately below because NASS formats its
            # short_desc differently from class-specific rows (e.g. "ACRES HARVESTED"
            # instead of "AREA HARVESTED, MEASURED IN ACRES"), so exact-match fails.
            _SD_MAP = {
                "WHEAT, WINTER, RED, HARD - PRODUCTION, MEASURED IN BU":        ("production_bu", "HRW"),
                "WHEAT, WINTER, RED, HARD - AREA PLANTED, MEASURED IN ACRES":   ("planted_ac",    "HRW"),
                "WHEAT, WINTER, RED, HARD - AREA HARVESTED, MEASURED IN ACRES": ("harvested_ac",  "HRW"),
                "WHEAT, WINTER, RED, HARD - YIELD, MEASURED IN BU / ACRE":      ("yield_bu_ac",   "HRW"),
                "WHEAT, WINTER, RED, SOFT - PRODUCTION, MEASURED IN BU":        ("production_bu", "SRW"),
                "WHEAT, WINTER, RED, SOFT - AREA PLANTED, MEASURED IN ACRES":   ("planted_ac",    "SRW"),
                "WHEAT, WINTER, RED, SOFT - AREA HARVESTED, MEASURED IN ACRES": ("harvested_ac",  "SRW"),
                "WHEAT, WINTER, RED, SOFT - YIELD, MEASURED IN BU / ACRE":      ("yield_bu_ac",   "SRW"),
                "WHEAT, WINTER, WHITE - PRODUCTION, MEASURED IN BU":            ("production_bu", "White"),
                "WHEAT, WINTER, WHITE - AREA PLANTED, MEASURED IN ACRES":       ("planted_ac",    "White"),
                "WHEAT, WINTER, WHITE - AREA HARVESTED, MEASURED IN ACRES":     ("harvested_ac",  "White"),
                "WHEAT, WINTER, WHITE - YIELD, MEASURED IN BU / ACRE":          ("yield_bu_ac",   "White"),
            }
            # _nat_patch structure: {cls_key: {year: {field: value}}}
            # Covers ALL years in _agg_df so every historical column uses NASS
            # national class actuals, not the indexed state-sum proxy.
            _nat_patch: dict = {}

            def _nat_parse_by_year(df, ref_pri):
                """Return {year(int): value} picking highest-priority reference period."""
                if df.empty or "Value" not in df.columns or "year" not in df.columns:
                    return {}
                df = df.copy()
                df["_v"]   = pd.to_numeric(df["Value"].astype(str).str.replace(",", ""), errors="coerce")
                df["_pri"] = (df.get("reference_period_desc", pd.Series([""] * len(df)))
                              .str.strip().str.upper().map(ref_pri).fillna(0).astype(int))
                df["year"] = df["year"].astype(int)
                df = df.dropna(subset=["_v"])
                result = {}
                for _yr, _grp in df.groupby("year"):
                    _grp = _grp.sort_values("_pri", ascending=False)
                    result[int(_yr)] = float(_grp["_v"].iloc[0])
                return result

            # Fetch the full year range present in _agg_df — three calls by
            # statisticcat_desc keeps each result set small and avoids API limits.
            _agg_years   = sorted(_agg_df["year"].dropna().astype(int).unique())
            _yr_min      = min(_agg_years) if _agg_years else sel_usda_yr
            _yr_max      = max(_agg_years) if _agg_years else sel_usda_yr
            _nat_frames: list = []
            for _scat in ["PRODUCTION", "AREA HARVESTED", "AREA PLANTED", "YIELD"]:
                _r = _nass_get({
                    "key":               API_KEY,
                    "source_desc":       "SURVEY",
                    "sector_desc":       "CROPS",
                    "group_desc":        "FIELD CROPS",
                    "commodity_desc":    "WHEAT",
                    "statisticcat_desc": _scat,
                    "state_name":        "US TOTAL",
                    "freq_desc":         "ANNUAL",
                    "year__GE":          str(_yr_min),
                    "year__LE":          str(_yr_max),
                    "format":            "JSON",
                })
                if "data" in _r and _r["data"]:
                    _nat_frames.append(pd.DataFrame(_r["data"]))
            _nat_df = pd.concat(_nat_frames, ignore_index=True) if _nat_frames else pd.DataFrame()

            # Post-filter by exact short_desc and build _nat_patch (class-specific rows)
            for _sd_str, (_field, _ck) in _SD_MAP.items():
                if _ck in ("HRW", "SRW", "White") and _panel_class_states is not None:
                    _active_ck = (
                        "HRW"   if _panel_class_states == set(WHEAT_CLASSES.get("HRW — Hard Red Winter") or []) else
                        "SRW"   if _panel_class_states == set(WHEAT_CLASSES.get("SRW — Soft Red Winter") or []) else
                        "White" if _panel_class_states == set(WHEAT_CLASSES.get("White Winter") or []) else None
                    )
                    if _ck != _active_ck:
                        continue
                if not _nat_df.empty and "short_desc" in _nat_df.columns:
                    _sub     = _nat_df[_nat_df["short_desc"] == _sd_str]
                    _yr_vals = _nat_parse_by_year(_sub, _REF_PRI_NAT)
                    for _yr, _v in _yr_vals.items():
                        _nat_patch.setdefault(_ck, {}).setdefault(_yr, {})[_field] = _v

            # ── US all-winter patch ───────────────────────────────────────────────────
            # NASS uses a different short_desc format for the all-class "WHEAT, WINTER"
            # rollup (e.g. "WHEAT, WINTER - ACRES HARVESTED") vs class-specific entries
            # (e.g. "WHEAT, WINTER, RED, HARD - AREA HARVESTED, MEASURED IN ACRES").
            # Rather than guessing the exact string, identify all-winter rows by the
            # pattern "WHEAT, WINTER -" (space+dash, not comma) and map via statisticcat_desc.
            if _panel_class_states is None and not _nat_df.empty and "short_desc" in _nat_df.columns:
                # Use exact short_desc matches (confirmed from NASS QuickStats screenshot).
                # The loose startswith filter was picking up wrong-unit production rows.
                _us_sd_map = {
                    "WHEAT, WINTER - PRODUCTION, MEASURED IN BU":  "production_bu",
                    "WHEAT, WINTER - ACRES HARVESTED":              "harvested_ac",
                    "WHEAT, WINTER - ACRES PLANTED":                "planted_ac",
                    "WHEAT, WINTER - YIELD, MEASURED IN BU / ACRE": "yield_bu_ac",
                }
                for _sd_str, _field_k in _us_sd_map.items():
                    if not _nat_df.empty and "short_desc" in _nat_df.columns:
                        _sub = _nat_df[_nat_df["short_desc"] == _sd_str]
                        _yr_vals = _nat_parse_by_year(_sub, _REF_PRI_NAT)
                        for _yr, _v in _yr_vals.items():
                            _nat_patch.setdefault("US", {}).setdefault(_yr, {})[_field_k] = _v

            # Apply NASS national actuals to HRW / SRW / White rows, and also
            # apply the published "WHEAT, WINTER" all-class totals directly to the
            # US row (in full-class view only — class-filtered views keep their own
            # US total unchanged).
            for _ck, _yr_data in _nat_patch.items():
                if _ck == "US" and _panel_class_states is not None:
                    continue
                for _yr, _cdata in _yr_data.items():
                    _mask = (_agg_df["state_alpha"] == _ck) & (_agg_df["year"] == _yr)
                    if not _mask.any():
                        continue
                    for _col, _val in _cdata.items():
                        if _col in _agg_df.columns:
                            _agg_df.loc[_mask, _col] = _val
                    # Use NASS planted_ac from the patch if available; fall back to
                    # whatever is already in _agg_df only as a last resort so that
                    # pct_harvested uses the official USDA denominator, not the proxy.
                    _plt_v = _cdata.get("planted_ac") or _agg_df.loc[_mask, "planted_ac"].values[0]
                    _hv_v  = _cdata.get("harvested_ac")
                    _pd_v  = _cdata.get("production_bu")
                    if _hv_v and _plt_v and _plt_v > 0:
                        _agg_df.loc[_mask, "pct_harvested"] = round(_hv_v / _plt_v * 100, 1)
                    if _pd_v and _hv_v and _hv_v > 0:
                        _agg_df.loc[_mask, "yield_bu_ac"] = round(_pd_v / _hv_v, 1)

        # ── Shared yield helper: identical computation to the Yield Model tab scatter ──
        # Uses a fresh _compute_analog_forecast call for every key so the result
        # matches the scatter star exactly — no dependency on pre-computed
        # _class_analog_results which could differ if caching creates staleness.
        def _yield_from_reg(sk: str) -> "float | None":
            _td = _trend_data.get(sk)
            if _td is None:
                return None
            _cwm = {"HRW": _dynamic_hrw_weights, "SRW": _dynamic_srw_weights,
                    "White": _dynamic_white_weights}
            _af = _compute_analog_forecast(
                sk, raw_df, _effective_week_ts(sk), sel_usda_yr,
                _yield_lookup, _trend_data, _dynamic_hrw_weights,
                class_weights_map=_cwm,
                crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                cond_weights=_active_cw,
            )
            if not _af:
                return None
            _tl = _trend_at(_td, sel_usda_yr)
            if not _tl:
                return None
            _snap2   = _af.get("jsa_snap", {})
            _cur_j   = _af.get("cur_jsa")
            _lkup2   = _yield_lookup.get(sk, {})
            if _cur_j is None:
                return None
            _pts2 = [
                (_snap2[cy], _lkup2[cy]["dev"])
                for cy in _snap2
                if cy != sel_usda_yr and cy in _lkup2
                and _lkup2[cy].get("dev") is not None
            ]
            if len(_pts2) < 3:
                return None
            _x2  = np.array([p[0] for p in _pts2])
            _y2  = np.array([p[1] for p in _pts2])
            _lc  = np.linalg.lstsq(np.vstack([_x2, np.ones(len(_x2))]).T, _y2, rcond=None)[0]
            _dev = float(_lc[0] * float(_cur_j) + _lc[1])
            _raw = _tl * (1 + _dev / 100)
            return round(_raw, 1)

        # ── Build JSA column for aggregate rows (US / HRW / SRW / White) ──────────
        # JSA model: planted = USDA NASS; yield = regression (matches scatter star);
        # % harvested = JSA regression on historical planted/harvested data.
        if commodity_label == "Winter Wheat":
            for _ak in ["US", "HRW", "SRW", "White"]:
                _ar = _agg_df[_agg_df["state_alpha"] == _ak]
                if _ar.empty:
                    continue
                _plt = _get_planted_ac(_ak)
                _ph  = _ph_cls.get(_ak)
                _yd  = _yield_from_reg(_ak)
                _harv = round(_plt * _ph / 100) if (_plt and _ph is not None) else None
                _prod = round(_harv * _yd)       if (_harv and _yd is not None) else None
                _jsa_col[_ak] = {
                    "production_bu": _prod,
                    "planted_ac":    _plt,
                    "harvested_ac":  _harv,
                    "pct_harvested": _ph,
                    "yield_bu_ac":   _yd,
                }

            # ── Build JSA column for individual states ────────────────────────────
            for _sk in sorted(_panel["state_alpha"].unique()):
                if _sk in {"US", "HRW", "SRW", "White"}:
                    continue
                _plt = _get_planted_ac(_sk)
                _ph  = _state_pct_harv_reg(_sk)
                if _ph is None:
                    _ph = _state_ph_fallback.get(_sk)
                _yd  = _yield_from_reg(_sk)
                _harv = round(_plt * _ph / 100) if (_plt and _ph is not None) else None
                _prod = round(_harv * _yd)       if (_harv and _yd is not None) else None
                _jsa_col[_sk] = {
                    "production_bu": _prod,
                    "planted_ac":    _plt,
                    "harvested_ac":  _harv,
                    "pct_harvested": _ph,
                    "yield_bu_ac":   _yd,
                }

        # ── Maps: Planted Acres / JSA estimate (left) + % Change vs LY (right) ─────────
        # For the planted-acres metric on Winter Wheat, bypass _jsa_col and build
        # the LHS map directly from _planted_lkup — the most-current NASS report
        # (Dec Seedings → Mar Prospective Plantings → Jun Acreage → Final Annual)
        # regardless of whether the JSA model is active.
        _use_planted_lkup = (
            _pmet_col == "planted_ac"
            and bool(_planted_lkup)
            and commodity_label == "Winter Wheat"
        )

        if _use_planted_lkup:
            _pm_rows = [
                {"state_alpha": k, "planted_ac": float(v)}
                for k, v in _planted_lkup.items()
                if len(k) == 2 and v is not None
            ]
            _jsa_map_df = pd.DataFrame(_pm_rows) if _pm_rows else pd.DataFrame()
        else:
            _jsa_map_rows = [
                {"state_alpha": _sk, _pmet_col: float(_est[_pmet_col])}
                for _sk, _est in _jsa_col.items()
                if len(_sk) == 2 and _pmet_col in _est and _est[_pmet_col] is not None
            ]
            _jsa_map_df = pd.DataFrame(_jsa_map_rows) if _jsa_map_rows else pd.DataFrame()

        # ── % change map: compare LHS data vs prior crop year ───────────────────────
        # For planted-acres (WW) use the same API source for both years so the
        # comparison is truly apples-to-apples (no panel dependency).
        # For all other metrics, fall back to the production panel (historical actuals).
        _jsa_chg_df = pd.DataFrame()

        def _build_chg_df(cur_df, prev_col_df, prev_col):
            """Merge current vs prior year data and compute pct_chg."""
            if cur_df.empty or prev_col_df.empty:
                return pd.DataFrame()
            merged = cur_df.merge(
                prev_col_df[["state_alpha", prev_col]].rename(columns={prev_col: "_prev"}),
                on="state_alpha", how="inner",
            )
            merged["pct_chg"] = np.where(
                merged["_prev"].abs() > 0,
                ((merged[_pmet_col] - merged["_prev"]) / merged["_prev"].abs() * 100).round(1),
                np.nan,
            )
            return merged

        if _use_planted_lkup and _ly_planted_lkup:
            # Planted acres: both years from fetch_planted_acres_for_year → true YoY comparison
            _ly_planted_rows = [
                {"state_alpha": k, "planted_ac": float(v)}
                for k, v in _ly_planted_lkup.items()
                if len(k) == 2 and v is not None
            ]
            _ly_planted_map_df = pd.DataFrame(_ly_planted_rows) if _ly_planted_rows else pd.DataFrame()
            _jsa_chg_df = _build_chg_df(_jsa_map_df, _ly_planted_map_df, "planted_ac")
        else:
            # All other metrics: use production panel for prior-year actuals
            _ly_panel_df = _panel[_panel["year"] == sel_usda_yr - 1].copy()
            if not _jsa_map_df.empty and not _ly_panel_df.empty:
                _ly_col = _pmet_col if _pmet_col in _ly_panel_df.columns else None
                if _ly_col:
                    _jsa_chg_df = _build_chg_df(_jsa_map_df, _ly_panel_df, _ly_col)

        def _build_prod_map(df_map, z_col, title, colorscale, zmin=None, zmax=None,
                            ticksfx="", label_color="white"):
            """Build a US choropleth for the production panel.

            label_color: "white"  → white text everywhere (readable on dark MAP_COLORSCALE)
                         "delta"  → per-state text: dark near 0 (light bg), white at extremes
            """
            _valid = df_map.dropna(subset=[z_col])
            if _valid.empty:
                return None
            # Dynamic range: use p10/p90 so the colorscale is sensitive to
            # state-level variation rather than being stretched by extreme values
            if zmin is None and zmax is None:
                _z_vals = _valid[z_col]
                zmin = float(_z_vals.quantile(0.10))
                zmax = float(_z_vals.quantile(0.90))
                if zmax - zmin < 1e-6:
                    zmin, zmax = float(_z_vals.min()), float(_z_vals.max())
            _fig = go.Figure(go.Choropleth(
                locations=_valid["state_alpha"],
                z=_valid[z_col],
                locationmode="USA-states",
                colorscale=colorscale,
                zmin=zmin, zmax=zmax,
                marker_line_color=DM_BORDER, marker_line_width=0.8,
                colorbar=dict(thickness=12, len=0.65, x=1.01,
                              tickfont=dict(color=DM_MUTED, size=10),
                              ticksuffix=ticksfx),
                hovertemplate="%{location}: %{z}<extra></extra>",
            ))
            # State value labels at centroids
            _lats, _lons, _txts, _tcolors = [], [], [], []
            _z_range = max(abs(zmax or 30), abs(zmin or -30))
            for _, _r in _valid.iterrows():
                _st = _r["state_alpha"]
                if _st not in STATE_CENTROIDS:
                    continue
                _lats.append(STATE_CENTROIDS[_st][0])
                _lons.append(STATE_CENTROIDS[_st][1])
                _v = _r[z_col]
                if z_col == "pct_chg":
                    _txts.append(f"{'+'if _v>=0 else ''}{_v:.1f}%")
                elif _pmet_is_pct:
                    _txts.append(f"{_v:.1f}%")
                elif _pmet_is_yield:
                    _txts.append(f"{_v:.1f}")
                elif _pmet_is_bu:
                    _txts.append(f"{_v/1_000_000:.1f}")
                else:
                    _txts.append(f"{_v/1_000_000:.2f}")
                # Per-state text colour for delta maps: dark text on near-zero (light) states,
                # white text on strongly positive/negative (dark) states.
                if label_color == "delta":
                    _near_zero = _z_range > 0 and abs(_v) < _z_range * 0.35
                    _tcolors.append("#1e293b" if _near_zero else "#ffffff")
                else:
                    _tcolors.append("#ffffff")

            if _lats:
                if label_color == "delta":
                    # Split into two Scattergeo traces (dark / white) so each has uniform colour
                    for _tc in ("#1e293b", "#ffffff"):
                        _idx = [i for i, c in enumerate(_tcolors) if c == _tc]
                        if _idx:
                            _fig.add_trace(go.Scattergeo(
                                lat=[_lats[i] for i in _idx],
                                lon=[_lons[i] for i in _idx],
                                text=[_txts[i] for i in _idx],
                                mode="text",
                                textfont=dict(size=10, color=_tc, family="Arial Black"),
                                showlegend=False, hoverinfo="skip",
                            ))
                else:
                    _fig.add_trace(go.Scattergeo(
                        lat=_lats, lon=_lons, text=_txts, mode="text",
                        textfont=dict(size=10, color="#ffffff", family="Arial Black"),
                        showlegend=False, hoverinfo="skip",
                    ))
            _fig.update_layout(
                geo=dict(scope="usa", showlakes=False, bgcolor=DM_BG,
                         landcolor=DM_LAND, subunitcolor=DM_BORDER),
                paper_bgcolor=DM_BG,
                margin=dict(l=0, r=10, t=36, b=10),
                height=380,
                dragmode=False,
                title=dict(text=title, font=dict(color=DM_TEXT, size=13), x=0.5, xanchor="center"),
            )
            _wm_map(_fig)
            return _fig

        # ── Map titles ─────────────────────────────────────────────────────────────────
        _ref_label_map = {
            "YEAR - MAR ACREAGE":  "Mar Prospective Plantings",
            "YEAR - DEC ACREAGE":  "Dec Seedings",
            "YEAR - JUN ACREAGE":  "Jun Acreage",
            "YEAR - AUG FORECAST": "Aug Forecast",
            "YEAR":                "Final Annual",
        }
        _planted_report_label = _ref_label_map.get(
            _planted_ref_src.upper(), _planted_ref_src.title() or "USDA NASS"
        )

        _ly_report_label = _ref_label_map.get(
            _ly_planted_ref_src.upper(), _ly_planted_ref_src.title() or "USDA Actual"
        ) if _ly_planted_ref_src else "USDA Actual"

        if _use_planted_lkup:
            _map_lhs_title = (
                f"{_planted_data_yr or sel_usda_yr} {_planted_report_label} — Planted Acres"
            )
            _map_rhs_title = (
                f"% Change — {_planted_data_yr or sel_usda_yr} {_planted_report_label}"
                f" vs {(_planted_data_yr or sel_usda_yr) - 1} {_ly_report_label}"
            )
        else:
            _map_lhs_title = (
                f"JSA {sel_usda_yr}E — {_pmet}"
                if (commodity_label == "Winter Wheat" or _non_ww_model_active)
                else f"{sel_usda_yr - 1} Actual — {_pmet}"
            )
            _map_rhs_title = (
                f"% Change — JSA {sel_usda_yr}E vs {sel_usda_yr - 1} USDA Actual"
                if (commodity_label == "Winter Wheat" or _non_ww_model_active)
                else f"% Change — {sel_usda_yr - 1} vs {sel_usda_yr - 2} USDA Actual"
            )

        _mc1, _mc2 = st.columns(2)
        with _mc1:
            _fig_cur = _build_prod_map(
                _jsa_map_df, _pmet_col,
                _map_lhs_title,
                MAP_COLORSCALE,
                ticksfx=_pmet_sfx,
                label_color="white",
            )
            if _fig_cur:
                _show_chart(_fig_cur, "production_map_current",
                    extra_config={"scrollZoom": False, "staticPlot": False,
                                  "modeBarButtonsToRemove": ["zoom", "pan", "select",
                                                             "lasso2d", "resetGeo",
                                                             "zoomIn", "zoomOut"]})
            else:
                _no_map_label = (
                    f"{_planted_data_yr or sel_usda_yr} {_planted_report_label}"
                    if _use_planted_lkup
                    else f"JSA {sel_usda_yr}E"
                    if (commodity_label == "Winter Wheat" or _non_ww_model_active)
                    else f"{sel_usda_yr - 1} Actual"
                )
                st.info(f"No {_no_map_label} data available for this metric.")

        with _mc2:
            _chg_valid = _jsa_chg_df.dropna(subset=["pct_chg"])
            if not _chg_valid.empty:
                # Planted-acres % change: typical inter-year variation is ±5–15%.
                # Cap at ±12% so mid-range changes render with strong colour; clip
                # extreme outliers to the edges of the scale rather than washing out
                # the majority of states.  Other metrics keep the wider ±30%.
                _rhs_zmin = -12 if _use_planted_lkup else -30
                _rhs_zmax =  12 if _use_planted_lkup else  30
                _fig_chg = _build_prod_map(
                    _chg_valid, "pct_chg",
                    _map_rhs_title,
                    DELTA_COLORSCALE, zmin=_rhs_zmin, zmax=_rhs_zmax,
                    ticksfx="%",
                    label_color="delta",
                )
                if _fig_chg:
                    _show_chart(_fig_chg, "production_map_change",
                        extra_config={"scrollZoom": False, "staticPlot": False,
                                      "modeBarButtonsToRemove": ["zoom", "pan", "select",
                                                                  "lasso2d", "resetGeo",
                                                                  "zoomIn", "zoomOut"]})
            else:
                st.info(f"No year-over-year change data available.")

        st.markdown("---")

        # Hoisted here so both the snapshot and the historical table can use them
        def _fmt_val(v, col):
            if pd.isna(v):
                return "—"
            if col == "production_bu":
                return f"{v/1_000_000:.1f}"
            elif col in ("planted_ac", "harvested_ac"):
                return f"{v/1_000_000:.2f}"
            elif col == "pct_harvested":
                return f"{v:.1f}%"
            elif col == "yield_bu_ac":
                return f"{v:.1f}"
            return str(v)

        _jsa_col_hdr = (
            f"JSA {sel_usda_yr}E"
            if commodity_label == "Winter Wheat"
            else f"JSA {sel_usda_yr}E"
            if _non_ww_model_active
            else f"{sel_usda_yr - 1} Actual"
        )

        # ══════════════════════════════════════════════════════════════════════════
        # ── Production Snapshot: all 5 metrics for the selected entity, side-by-side ──
        # ══════════════════════════════════════════════════════════════════════════
        # Priority: state filter → wheat class aggregate → US Total
        if sel_state_alpha:
            _snap_key   = sel_state_alpha
            _snap_src   = _panel_disp
            _snap_label = sel_state_name
        elif commodity_cfg.get("has_classes", True) and _panel_class_states is not None:
            # Wheat class aggregate selected
            _cls_lbl_map2 = {
                frozenset(WHEAT_CLASSES.get("HRW — Hard Red Winter") or []): ("HRW",   "⬡ HRW"),
                frozenset(WHEAT_CLASSES.get("SRW — Soft Red Winter") or []): ("SRW",   "⬡ SRW"),
                frozenset(WHEAT_CLASSES.get("White Winter") or []):          ("White", "⬡ White"),
            }
            _cls_key2 = frozenset(_panel_class_states)
            _snap_agg_key = _cls_lbl_map2.get(_cls_key2, ("US", "🇺🇸 US Total"))
            _snap_key   = _snap_agg_key[0]
            _snap_src   = None   # use _agg_df
            _snap_label = _snap_agg_key[1]
        else:
            _snap_key   = "US"
            _snap_src   = None   # use _agg_df
            _snap_label = "🇺🇸 US Total"

        # Determine the data source DataFrame for this entity
        if _snap_src is not None:
            # State-level: pull rows for this state from panel
            _snap_df = _panel[_panel["state_alpha"] == _snap_key].copy()
        else:
            # Aggregate: pull from _agg_df
            _snap_df = _agg_df[_agg_df["state_alpha"] == _snap_key].copy()

        if not _snap_df.empty:
            # ── Year-window toggle (default 5 years) ──────────────────────────────
            _snap_n_yrs = st.radio(
                "History window",
                ["5 Years", "10 Years"],
                index=0,
                horizontal=True,
                key="snap_yr_tog",
            )
            _snap_window = 5 if _snap_n_yrs == "5 Years" else 10
            _snap_yrs = _all_yrs[-min(_snap_window, len(_all_yrs)):]

            _SNAP_METRICS = [
                ("planted_ac",    "Planted Acres (M)"),
                ("harvested_ac",  "Harvested Acres (M)"),
                ("pct_harvested", "% Harvested"),
                ("yield_bu_ac",   "Yield (bu/ac)"),
                ("production_bu", "Production (M BU)"),
            ]

            st.markdown(
                f'<div class="sec-hdr">Production Snapshot'
                f' &nbsp;·&nbsp; <span style="color:{JPSI_BLUE}">{_snap_label}</span>'
                f' &nbsp;·&nbsp; <span style="color:{JPSI_BLUE}">{commodity_label}</span></div>',
                unsafe_allow_html=True,
            )
            _harvest_est_note = (
                f" · ⚠️ **Harvested acres estimated** for {sel_usda_yr}: "
                "USDA has not yet published harvested acres — "
                "5-yr olympic-avg % harvested × USDA planted acres used at state & national level."
                if _acres_harvest_estimated else ""
            )
            st.caption(
                "All five production metrics for the selected entity in a single view. "
                f"Estimate column = {_jsa_col_hdr}. "
                f"Toggle history window above.{_harvest_est_note}"
            )

            # ── Build snapshot rows ───────────────────────────────────────────────
            _snap_rows = []
            _jsa_est  = _jsa_col.get(_snap_key, {})
            _stk_vals = {}   # year → raw BU; shared with Total Supply row

            # ── Sep 1 (Carry In) — top row ───────────────────────────────────────
            # When NASS hasn't published Sep 1 yet:
            #   US Total → retention-ratio model + optional USDA/WASDE manual override
            #   States   → derive from US total using best backtested method
            _is_ww_snap  = commodity_label == "Winter Wheat"
            _sep1_has_estimate = False

            # --- Build national model estimate (US Total) ---
            _us_snap_prod_df = None
            if _is_ww_snap and "production_bu" in _snap_df.columns:
                _us_snap_prod_df = _snap_df[_snap_df["state_alpha"] == "US"][
                    ["year", "state_alpha", "production_bu"]
                ].copy() if "state_alpha" in _snap_df.columns else None
                if _us_snap_prod_df is None:
                    _tmp = _snap_df[["year", "production_bu"]].copy()
                    _tmp["state_alpha"] = "US"
                    _us_snap_prod_df = _tmp
            _disapp_us = _build_sep1_disapp_df(
                _sep1_stocks_df, _jun1_stocks_df, _us_snap_prod_df, _is_ww_snap, "US"
            )
            _ww_prod_est_us = None
            if _is_ww_snap:
                _jsa_us = _jsa_col.get("US", {})
                _ww_prod_est_us = _jsa_us.get("production_bu")
                if _ww_prod_est_us is None:
                    _cy_us = _snap_df[_snap_df["year"] == sel_usda_yr] if "state_alpha" not in _snap_df.columns else _snap_df[(_snap_df["year"] == sel_usda_yr) & (_snap_df["state_alpha"] == "US")]
                    if not _cy_us.empty and "production_bu" in _cy_us.columns:
                        _ww_prod_est_us = _cy_us["production_bu"].iloc[0]
                        _ww_prod_est_us = float(_ww_prod_est_us) if pd.notna(_ww_prod_est_us) else None
            _model_us_est_bu, _model_us_note = _estimate_sep1_stocks(
                _disapp_us, _jun1_stocks_df, sel_usda_yr,
                _is_ww_snap, _ww_prod_est_us, "US", n_avg=5,
            )

            # --- USDA/WASDE override for US Total ---
            _us_sep1_actual = _sep1_stocks_df[
                (_sep1_stocks_df["year"] == sel_usda_yr) &
                (_sep1_stocks_df["state_alpha"] == "US")
            ]
            _cur_yr_us_published = not _us_sep1_actual.empty
            _used_wasde_auto  = False
            _override_default = 0.0
            if not _cur_yr_us_published:
                if _psd_es_bu and _psd_es_bu > 0:
                    # Auto-populated from USDA FAS PSD (WASDE projected ending stocks)
                    _used_wasde_auto    = True
                    _us_total_est_bu    = _psd_es_bu
                    _usda_override_mbu  = _psd_es_bu / 1e6
                    st.info(
                        f"**WASDE projected Sep 1, {sel_usda_yr} ending stocks: "
                        f"{_usda_override_mbu:,.1f} M bu** — auto-populated from USDA FAS PSD"
                    )
                else:
                    # PSD unavailable for this commodity (e.g. wheat) — fall back to model
                    _override_default  = round(_model_us_est_bu / 1e6, 1) if _model_us_est_bu else 0.0
                    _usda_override_mbu = st.number_input(
                        f"USDA projected Sep 1, {sel_usda_yr} ending stocks (M bu) — enter WASDE estimate or leave as model default",
                        min_value=0.0, max_value=50_000.0,
                        value=_override_default, step=1.0,
                        key=f"sep1_override_{sel_usda_yr}_{commodity_label}",
                        help=(
                            "WASDE auto-fetch not available for this commodity. "
                            "Model default uses Jun 1 stocks × 5-yr avg Sep1/Jun1 retention ratio."
                        ),
                    )
                    _us_total_est_bu = _usda_override_mbu * 1e6
            else:
                _us_total_est_bu   = float(_us_sep1_actual["stocks_bu"].iloc[0])
                _usda_override_mbu = _us_total_est_bu / 1e6

            # --- Run state backtest and pick best method ---
            _bt_summary, _bt_detail = _backtest_state_sep1_methods(
                _sep1_stocks_df, _jun1_stocks_df, n_avg=5,
            )
            _best_state_method = (
                _bt_summary["method"].iloc[0]
                if not _bt_summary.empty
                else "national_ratio"
            )
            _method_map = {
                "National ratio × State Jun1":     "national_ratio",
                "Hist. state share × US total":    "state_share",
                "State retention ratio":           "state_ratio",
            }
            _best_method_key = _method_map.get(_best_state_method, "national_ratio")

            # Get US Jun1 for national ratio method
            _us_jun1_row = _jun1_stocks_df[
                (_jun1_stocks_df["year"] == sel_usda_yr) &
                (_jun1_stocks_df["state_alpha"] == "US")
            ]
            _us_jun1_bu = float(_us_jun1_row["stocks_bu"].iloc[0]) if not _us_jun1_row.empty else 0.0

            # --- Build Sep 1 estimate for the viewed entity ---
            if _snap_key == "US":
                _sep1_est_bu   = _us_total_est_bu if not _cur_yr_us_published else None
                if _used_wasde_auto:
                    _sep1_est_note = f"WASDE projected ending stocks, USDA FAS PSD ({_usda_override_mbu:,.1f} M bu)"
                elif _usda_override_mbu == _override_default:
                    _sep1_est_note = _model_us_note
                else:
                    _sep1_est_note = f"USDA/WASDE projected ending stocks ({_usda_override_mbu:,.1f} M bu)"
            else:
                # State: derive from US total using best backtested method
                _st_j1_row = _jun1_stocks_df[
                    (_jun1_stocks_df["year"] == sel_usda_yr) &
                    (_jun1_stocks_df["state_alpha"] == _snap_key)
                ]
                _st_j1_bu = float(_st_j1_row["stocks_bu"].iloc[0]) if not _st_j1_row.empty else 0.0
                _sep1_est_bu = _estimate_state_sep1(
                    _snap_key, _st_j1_bu, _us_total_est_bu, _us_jun1_bu,
                    _sep1_stocks_df, _jun1_stocks_df, _best_method_key,
                    sel_usda_yr, n_avg=5,
                ) if _st_j1_bu > 0 and _us_total_est_bu > 0 else None
                _sep1_est_note = (
                    f"{_best_state_method} (lowest MAPE in backtest: "
                    f"{_bt_summary['mape_pct'].iloc[0]:.1f}% avg)"
                    if not _bt_summary.empty else "state estimate from US total"
                )

            if not _sep1_stocks_df.empty:
                _stk_row = {"Metric": "Sep 1 (Carry In)"}
                for _yr in _snap_yrs:
                    _stk_m = _sep1_stocks_df[
                        (_sep1_stocks_df["year"] == _yr) &
                        (_sep1_stocks_df["state_alpha"] == _snap_key)
                    ]
                    if not _stk_m.empty:
                        _sv = float(_stk_m["stocks_bu"].iloc[0])
                        _stk_row[str(_yr)] = f"{_sv/1_000_000:.1f}"
                        _stk_vals[_yr] = _sv
                    elif _yr == sel_usda_yr and _sep1_est_bu is not None and _sep1_est_bu > 0:
                        _stk_row[str(_yr)] = f"{_sep1_est_bu/1_000_000:.1f}*"
                        _stk_vals[_yr] = _sep1_est_bu
                        _sep1_has_estimate = True
                    else:
                        _stk_row[str(_yr)] = "—"
                        _stk_vals[_yr] = None
                _stk_cur  = _stk_vals.get(_snap_yrs[-1])
                _stk_prev = _stk_vals.get(_snap_yrs[-2]) if len(_snap_yrs) >= 2 else None
                if _stk_cur is not None and _stk_prev is not None and _stk_prev != 0:
                    _sc2 = (_stk_cur - _stk_prev) / abs(_stk_prev) * 100
                    _stk_row["vs LY"] = f"{'+'if _sc2>=0 else ''}{_sc2:.1f}%"
                else:
                    _stk_row["vs LY"] = "—"
                _stk_row[_jsa_col_hdr]       = "—"
                _stk_row["vs LY ▸ JSA"]      = "—"
                _stk_row["vs Olympic ▸ JSA"] = "—"
                _stk_hist = (
                    _sep1_stocks_df[
                        (_sep1_stocks_df["state_alpha"] == _snap_key) &
                        (_sep1_stocks_df["year"] < sel_usda_yr)
                    ]["stocks_bu"].dropna().tolist()
                )
                _stk_row["Min"] = f"{min(_stk_hist)/1_000_000:.1f}" if _stk_hist else "—"
                _stk_row["Max"] = f"{max(_stk_hist)/1_000_000:.1f}" if _stk_hist else "—"
                _snap_rows.append(_stk_row)

            for _sc, _slbl in _SNAP_METRICS:
                _row = {"Metric": _slbl}
                _prev_v = None
                _cur_v  = None

                for _yr in _snap_yrs:
                    _yr_row = _snap_df[_snap_df["year"] == _yr]
                    _v = (float(_yr_row[_sc].iloc[0])
                          if not _yr_row.empty and pd.notna(_yr_row[_sc].iloc[0])
                          else None)
                    _row[str(_yr)] = _fmt_val(_v, _sc)
                    if _yr == _snap_yrs[-1]:
                        _cur_v = _v
                    if len(_snap_yrs) >= 2 and _yr == _snap_yrs[-2]:
                        _prev_v = _v

                # vs LY (last two displayed years)
                if _cur_v is not None and _prev_v is not None and _prev_v != 0:
                    _chg = (_cur_v - _prev_v) / abs(_prev_v) * 100
                    _row["vs LY"] = f"{'+'if _chg>=0 else ''}{_chg:.1f}%"
                else:
                    _row["vs LY"] = "—"

                # JSA / estimate column
                _jv = _jsa_est.get(_sc)
                _row[_jsa_col_hdr] = _fmt_val(_jv, _sc) if _jv is not None else "—"

                # vs LY ▸ JSA
                _ly_row = _snap_df[_snap_df["year"] == sel_usda_yr - 1]
                _ly_v = (float(_ly_row[_sc].iloc[0])
                         if not _ly_row.empty and pd.notna(_ly_row[_sc].iloc[0])
                         else None)
                if _ly_v is not None and _jv is not None and _ly_v != 0:
                    _c = (_jv - _ly_v) / abs(_ly_v) * 100
                    _row["vs LY ▸ JSA"] = f"{'+'if _c>=0 else ''}{_c:.1f}%"
                else:
                    _row["vs LY ▸ JSA"] = "—"

                # vs Olympic ▸ JSA
                _h_vals = (_snap_df[_snap_df["year"] < sel_usda_yr]
                           .dropna(subset=[_sc])
                           .sort_values("year")[_sc]
                           .astype(float).tolist())
                _last6v = _h_vals[-6:]
                if len(_last6v) >= 3:
                    _s6 = sorted(_last6v)
                    _trimmed6 = _s6[1:-1] if len(_s6) >= 4 else _s6
                    _oly_v = float(np.mean(_trimmed6))
                else:
                    _oly_v = None
                if _oly_v is not None and _jv is not None and _oly_v != 0:
                    _c = (_jv - _oly_v) / abs(_oly_v) * 100
                    _row["vs Olympic ▸ JSA"] = f"{'+'if _c>=0 else ''}{_c:.1f}%"
                else:
                    _row["vs Olympic ▸ JSA"] = "—"

                # Min / Max (across all available years < sel_usda_yr)
                if _h_vals:
                    _row["Min"] = _fmt_val(float(min(_h_vals)), _sc)
                    _row["Max"] = _fmt_val(float(max(_h_vals)), _sc)
                else:
                    _row["Min"] = "—"
                    _row["Max"] = "—"

                _snap_rows.append(_row)

                # ── Total Supply — appended directly after Production ─────────────
                if _sc == "production_bu" and _stk_vals:
                    _tsup_row  = {"Metric": "Total Supply (M BU)"}
                    _tsup_vals = {}
                    for _tyr in _snap_yrs:
                        _tp_row = _snap_df[_snap_df["year"] == _tyr]
                        _tpv    = (float(_tp_row["production_bu"].iloc[0])
                                   if not _tp_row.empty and pd.notna(_tp_row["production_bu"].iloc[0])
                                   else None)
                        _tsv    = _stk_vals.get(_tyr)
                        _tsup   = _tpv + _tsv if (_tpv is not None and _tsv is not None) else None
                        _tsup_row[str(_tyr)] = f"{_tsup/1_000_000:.1f}" if _tsup is not None else "—"
                        _tsup_vals[_tyr] = _tsup
                    _ts_cur  = _tsup_vals.get(_snap_yrs[-1])
                    _ts_prev = _tsup_vals.get(_snap_yrs[-2]) if len(_snap_yrs) >= 2 else None
                    if _ts_cur is not None and _ts_prev is not None and _ts_prev != 0:
                        _tc = (_ts_cur - _ts_prev) / abs(_ts_prev) * 100
                        _tsup_row["vs LY"] = f"{'+'if _tc>=0 else ''}{_tc:.1f}%"
                    else:
                        _tsup_row["vs LY"] = "—"
                    _tsup_row[_jsa_col_hdr]       = "—"
                    _tsup_row["vs LY ▸ JSA"]      = "—"
                    _tsup_row["vs Olympic ▸ JSA"] = "—"
                    _ts_hist = []
                    for _hyr in sorted(_snap_df["year"].unique()):
                        if _hyr >= sel_usda_yr:
                            continue
                        _hp_row = _snap_df[_snap_df["year"] == _hyr]
                        _hpv    = (float(_hp_row["production_bu"].iloc[0])
                                   if not _hp_row.empty and pd.notna(_hp_row["production_bu"].iloc[0])
                                   else None)
                        _hs_row = _sep1_stocks_df[
                            (_sep1_stocks_df["state_alpha"] == _snap_key) &
                            (_sep1_stocks_df["year"] == _hyr)
                        ]
                        _hsv = float(_hs_row["stocks_bu"].iloc[0]) if not _hs_row.empty else None
                        if _hpv is not None and _hsv is not None:
                            _ts_hist.append(_hpv + _hsv)
                    _tsup_row["Min"] = f"{min(_ts_hist)/1_000_000:.1f}" if _ts_hist else "—"
                    _tsup_row["Max"] = f"{max(_ts_hist)/1_000_000:.1f}" if _ts_hist else "—"
                    _snap_rows.append(_tsup_row)

            _snap_tbl = pd.DataFrame(_snap_rows)

            # ── Style snapshot table ──────────────────────────────────────────────
            def _style_snap_table(df):
                styles = pd.DataFrame("", index=df.index, columns=df.columns)
                for i, row in df.iterrows():
                    # Amber JSA estimate column
                    styles.loc[i, _jsa_col_hdr] = (
                        "background-color:#fef3c7; color:#b45309; font-weight:700;"
                        " border-left:2px solid #f59e0b;"
                    )
                    # Green / red on pct comparison columns
                    for _pc in ("vs LY ▸ JSA", "vs Olympic ▸ JSA", "vs LY"):
                        _pv = str(row.get(_pc, ""))
                        if _pv.startswith("+"):
                            styles.loc[i, _pc] = "color:#15803d; font-weight:600;"
                        elif _pv.startswith("-"):
                            styles.loc[i, _pc] = "color:#dc2626; font-weight:600;"
                    # Muted Min / Max
                    for _mm in ("Min", "Max"):
                        if _mm in df.columns:
                            styles.loc[i, _mm] = f"color:{DM_MUTED}; font-style:italic;"
                    # Bold metric label
                    styles.loc[i, "Metric"] = "font-weight:600;"
                return styles

            _snap_styled = (_snap_tbl.style
                            .apply(_style_snap_table, axis=None)
                            .set_properties(**{"text-align": "right"})
                            .set_properties(subset=["Metric"], **{"text-align": "left"})
                            )
            st.dataframe(
                _snap_styled,
                use_container_width=True,
                height=35 * (len(_snap_tbl) + 1) + 40,
                hide_index=True,
            )
            if _sep1_has_estimate:
                st.caption(
                    f"\\* Sep 1 {sel_usda_yr} stocks estimated — {_sep1_est_note}. "
                    f"USDA NASS Grain Stocks report publishes actual data ~Sep 30."
                )

            # Backtest expander — show how each state method performed historically
            if not _bt_summary.empty and not _cur_yr_us_published:
                with st.expander("📊 State estimation backtest — method comparison", expanded=False):
                    st.markdown(
                        "Each method is tested against actual NASS Sep 1 state stocks "
                        "for every year where Jun 1 data was available. "
                        "The lowest MAPE method is applied automatically above."
                    )
                    _bt_disp = _bt_summary.copy()
                    _bt_disp.index = _bt_disp.index + 1
                    _bt_disp.columns = ["Method", "MAPE (%)", "Median APE (%)", "Observations"]
                    _bt_disp["MAPE (%)"]       = _bt_disp["MAPE (%)"].map("{:.1f}%".format)
                    _bt_disp["Median APE (%)"] = _bt_disp["Median APE (%)"].map("{:.1f}%".format)
                    st.dataframe(_bt_disp, use_container_width=True, hide_index=False)
                    if not _bt_detail.empty:
                        st.markdown("**Error distribution by state (best method)**")
                        _best_det = (_bt_detail[_bt_detail["method"] == _best_state_method]
                                     .groupby("state")["ape_pct"]
                                     .agg(mape_pct="mean", n="count")
                                     .reset_index()
                                     .sort_values("mape_pct"))
                        _best_det.columns = ["State", "MAPE (%)", "Years"]
                        _best_det["MAPE (%)"] = _best_det["MAPE (%)"].map("{:.1f}%".format)
                        st.dataframe(_best_det, use_container_width=True, hide_index=True)

        st.markdown("---")

        # ── Summary table: rows = US/class/state, cols = years ────────────────────
        st.markdown(
            f'<div class="sec-hdr">{_pmet_hdr_label} — Historical Detail ({_disp_yrs[0]}–{_disp_yrs[-1]})</div>',
            unsafe_allow_html=True,
        )

        def _build_pivot_table(src_df, agg_src_df, col, yrs, share_lkup, jsa_estimates,
                               groups=None):
            """Build display table: aggregate rows first, then states.

            groups (optional): list of dicts {states: [...], subtotal: str|None}.
            When provided, states are rendered in group order with an optional
            subtotal row after each group.  States not in any group appear at end.
            When absent, states are sorted by production share (existing behavior).
            """
            rows = []

            def _jsa_cell(alpha):
                _est = jsa_estimates.get(alpha, {})
                _v   = _est.get(col)
                return _fmt_val(_v, col) if _v is not None else "—"

            def _vs_jsa(ly_actual_v, alpha):
                """% change from sel_usda_yr-1 actual to JSA model estimate."""
                _est = jsa_estimates.get(alpha, {})
                _jv  = _est.get(col)
                if ly_actual_v is not None and _jv is not None and ly_actual_v != 0:
                    _c = (_jv - ly_actual_v) / abs(ly_actual_v) * 100
                    return f"{'+'if _c>=0 else ''}{_c:.1f}%"
                return "—"

            def _get_ly_actual(df_subset):
                """Return col value for sel_usda_yr-1 (last completed year)."""
                _ly_row = df_subset[df_subset["year"] == sel_usda_yr - 1]
                if not _ly_row.empty and pd.notna(_ly_row[col].iloc[0]):
                    return float(_ly_row[col].iloc[0])
                return None

            def _hist_stats(df_subset):
                """Return (olympic_avg, min_v, max_v) from historical years < sel_usda_yr."""
                _h = (df_subset[df_subset["year"] < sel_usda_yr]
                      .dropna(subset=[col])
                      .sort_values("year"))
                if _h.empty:
                    return None, None, None
                _vals = _h[col].astype(float).tolist()
                _min_v = float(min(_vals))
                _max_v = float(max(_vals))
                _last6 = _vals[-6:]
                if len(_last6) < 3:
                    _oly = None
                else:
                    _s = sorted(_last6)
                    _trimmed = _s[1:-1] if len(_s) >= 4 else _s
                    _oly = float(np.mean(_trimmed))
                return _oly, _min_v, _max_v

            def _vs_olympic(alpha, oly_v):
                """% change from 6-year Olympic avg to JSA estimate."""
                _est = jsa_estimates.get(alpha, {})
                _jv  = _est.get(col)
                if oly_v is not None and _jv is not None and oly_v != 0:
                    _c = (_jv - oly_v) / abs(oly_v) * 100
                    return f"{'+'if _c>=0 else ''}{_c:.1f}%"
                return "—"

            def _make_state_row(_st, _sr):
                """Build one state data row dict."""
                _sname = (_sr["state_name"].iloc[0]
                          if not _sr.empty and pd.notna(_sr["state_name"].iloc[0])
                          else _st)
                _share_pct = share_lkup.get(_st, 0)
                _row = {"State": f"{_sname}  ({_share_pct:.1f}%)", "_row_type": "state"}
                _prev_v = None
                _cur_v  = None
                for _yr in yrs:
                    _yrow = _sr[_sr["year"] == _yr]
                    _v = (float(_yrow[col].iloc[0])
                          if not _yrow.empty and pd.notna(_yrow[col].iloc[0]) else None)
                    _row[str(_yr)] = _fmt_val(_v, col)
                    if _yr == yrs[-1]:
                        _cur_v = _v
                    if len(yrs) >= 2 and _yr == yrs[-2]:
                        _prev_v = _v
                if _cur_v is not None and _prev_v is not None and _prev_v != 0:
                    _chg = (_cur_v - _prev_v) / abs(_prev_v) * 100
                    _row["vs LY"] = f"{'+'if _chg>=0 else ''}{_chg:.1f}%"
                else:
                    _row["vs LY"] = "—"
                _ly_v               = _get_ly_actual(_sr)
                _oly_v, _min_v, _max_v = _hist_stats(_sr)
                _row[_jsa_col_hdr]         = _jsa_cell(_st)
                _row["vs LY ▸ JSA"]        = _vs_jsa(_ly_v, _st)
                _row["vs Olympic ▸ JSA"]   = _vs_olympic(_st, _oly_v)
                _row["Min"]                = _fmt_val(_min_v, col) if _min_v is not None else "—"
                _row["Max"]                = _fmt_val(_max_v, col) if _max_v is not None else "—"
                return _row

            def _derived_val(sub_df_yr, est_states=None, use_jsa=False):
                """Compute the correct aggregation for col given a year slice."""
                if use_jsa and est_states is not None:
                    # Pull from JSA estimates dict
                    if col in ("production_bu", "planted_ac", "harvested_ac"):
                        _vals = [jsa_estimates.get(s, {}).get(col) for s in est_states]
                        _vals = [v for v in _vals if v is not None]
                        return float(sum(_vals)) if _vals else None
                    elif col == "pct_harvested":
                        _jp = sum((jsa_estimates.get(s,{}).get("planted_ac") or 0) for s in est_states)
                        _jh = sum((jsa_estimates.get(s,{}).get("harvested_ac") or 0) for s in est_states)
                        return round(_jh / _jp * 100, 1) if _jp > 0 else None
                    elif col == "yield_bu_ac":
                        _jpb = sum((jsa_estimates.get(s,{}).get("production_bu") or 0) for s in est_states)
                        _jh  = sum((jsa_estimates.get(s,{}).get("harvested_ac") or 0) for s in est_states)
                        return round(_jpb / _jh, 1) if _jh > 0 else None
                    return None
                # Historical NASS data aggregation
                if sub_df_yr.empty:
                    return None
                if col in ("production_bu", "planted_ac", "harvested_ac"):
                    return float(sub_df_yr[col].sum()) if sub_df_yr[col].notna().any() else None
                elif col == "pct_harvested":
                    _p = float(sub_df_yr["planted_ac"].sum()) if sub_df_yr["planted_ac"].notna().any() else 0
                    _h = float(sub_df_yr["harvested_ac"].sum()) if sub_df_yr["harvested_ac"].notna().any() else 0
                    return round(_h / _p * 100, 1) if _p > 0 else None
                elif col == "yield_bu_ac":
                    _pb = float(sub_df_yr["production_bu"].sum()) if "production_bu" in sub_df_yr.columns and sub_df_yr["production_bu"].notna().any() else 0
                    _h  = float(sub_df_yr["harvested_ac"].sum())  if sub_df_yr["harvested_ac"].notna().any() else 0
                    return round(_pb / _h, 1) if _h > 0 else None
                return None

            def _make_subtotal_row(label, grp_states, sub_df):
                """Build a subtotal row for a group of states."""
                _row = {"State": f"  ▸ {label}", "_row_type": "subtotal"}
                _prev_v = None
                _cur_v  = None
                for _yr in yrs:
                    _yr_sub = sub_df[sub_df["year"] == _yr]
                    _v = _derived_val(_yr_sub)
                    _row[str(_yr)] = _fmt_val(_v, col) if _v is not None else "—"
                    if _yr == yrs[-1]:
                        _cur_v = _v
                    if len(yrs) >= 2 and _yr == yrs[-2]:
                        _prev_v = _v
                if _cur_v is not None and _prev_v is not None and _prev_v != 0:
                    _chg = (_cur_v - _prev_v) / abs(_prev_v) * 100
                    _row["vs LY"] = f"{'+'if _chg>=0 else ''}{_chg:.1f}%"
                else:
                    _row["vs LY"] = "—"
                # JSA estimate for the subtotal group
                _jsa_v = _derived_val(None, est_states=grp_states, use_jsa=True)
                _row[_jsa_col_hdr] = _fmt_val(_jsa_v, col) if _jsa_v is not None else "—"
                # vs LY ▸ JSA — compare subtotal LY actual to subtotal JSA estimate
                _ly_sub = sub_df[sub_df["year"] == sel_usda_yr - 1]
                _ly_sub_v = _derived_val(_ly_sub)
                if _ly_sub_v is not None and _jsa_v is not None and _ly_sub_v != 0:
                    _c = (_jsa_v - _ly_sub_v) / abs(_ly_sub_v) * 100
                    _row["vs LY ▸ JSA"] = f"{'+'if _c>=0 else ''}{_c:.1f}%"
                else:
                    _row["vs LY ▸ JSA"] = "—"
                # vs Olympic ▸ JSA
                _oly_v, _min_v, _max_v = _hist_stats(sub_df)
                if _oly_v is not None and _jsa_v is not None and _oly_v != 0:
                    _c = (_jsa_v - _oly_v) / abs(_oly_v) * 100
                    _row["vs Olympic ▸ JSA"] = f"{'+'if _c>=0 else ''}{_c:.1f}%"
                else:
                    _row["vs Olympic ▸ JSA"] = "—"
                _row["Min"] = _fmt_val(_min_v, col) if _min_v is not None else "—"
                _row["Max"] = _fmt_val(_max_v, col) if _max_v is not None else "—"
                return _row

            # ── Aggregate rows (US, HRW, SRW, White) ──────────────────────────────
            _agg_order = ["US", "HRW", "SRW", "White"]
            for _ak in _agg_order:
                _ar = agg_src_df[agg_src_df["state_alpha"] == _ak]
                if _ar.empty:
                    continue
                _row = {"State": _ar["state_name"].iloc[0], "_row_type": "agg"}
                _prev_v = None
                _cur_v  = None
                for _yr in yrs:
                    _yrow = _ar[_ar["year"] == _yr]
                    _v = float(_yrow[col].iloc[0]) if not _yrow.empty and pd.notna(_yrow[col].iloc[0]) else None
                    _row[str(_yr)] = _fmt_val(_v, col)
                    if _yr == yrs[-1]:
                        _cur_v = _v
                    if len(yrs) >= 2 and _yr == yrs[-2]:
                        _prev_v = _v
                if _cur_v is not None and _prev_v is not None and _prev_v != 0:
                    _chg = (_cur_v - _prev_v) / abs(_prev_v) * 100
                    _row["vs LY"] = f"{'+'if _chg>=0 else ''}{_chg:.1f}%"
                else:
                    _row["vs LY"] = "—"
                _ly_v               = _get_ly_actual(_ar)
                _oly_v, _min_v, _max_v = _hist_stats(_ar)
                _row[_jsa_col_hdr]         = _jsa_cell(_ak)
                _row["vs LY ▸ JSA"]        = _vs_jsa(_ly_v, _ak)
                _row["vs Olympic ▸ JSA"]   = _vs_olympic(_ak, _oly_v)
                _row["Min"]                = _fmt_val(_min_v, col) if _min_v is not None else "—"
                _row["Max"]                = _fmt_val(_max_v, col) if _max_v is not None else "—"
                rows.append(_row)

            # ── State rows ─────────────────────────────────────────────────────────
            _available_states = set(src_df["state_alpha"].unique())

            if groups:
                _placed = set()
                for _grp in groups:
                    _grp_states = [s for s in _grp["states"] if s in _available_states]
                    _grp_sub_df = src_df[src_df["state_alpha"].isin(_grp_states)]
                    _grp_rows   = []
                    for _st in _grp_states:
                        _sr = src_df[src_df["state_alpha"] == _st]
                        if _sr.empty:
                            continue
                        _grp_rows.append(_make_state_row(_st, _sr))
                        _placed.add(_st)
                    if _grp_rows:
                        rows.extend(_grp_rows)
                        if _grp.get("subtotal") and len(_grp_rows) > 1:
                            rows.append(_make_subtotal_row(
                                _grp["subtotal"], _grp_states, _grp_sub_df
                            ))
                # Leftover states not in any group — sort by share
                _remaining = sorted(
                    _available_states - _placed,
                    key=lambda s: share_lkup.get(s, 0), reverse=True,
                )
                for _st in _remaining:
                    _sr = src_df[src_df["state_alpha"] == _st]
                    if not _sr.empty:
                        rows.append(_make_state_row(_st, _sr))
            else:
                # Default: sort all states by production share
                _state_order = sorted(
                    _available_states,
                    key=lambda s: share_lkup.get(s, 0), reverse=True,
                )
                for _st in _state_order:
                    _sr = src_df[src_df["state_alpha"] == _st]
                    if not _sr.empty:
                        rows.append(_make_state_row(_st, _sr))

            # Drop internal helper column before returning
            out = pd.DataFrame(rows)
            if "_row_type" in out.columns:
                out = out.drop(columns=["_row_type"])
            return out

        # ── Choose regional/class groupings for the state rows ───────────────────
        # Winter Wheat: group by class (HRW → SRW → White)
        # Corn / Soybeans / etc.: use PROD_TABLE_GROUPS if defined, else None (share sort)
        if commodity_label == "Winter Wheat":
            def _by_share(states):
                return sorted(states or [], key=lambda s: _prod_share_lkup.get(s, 0), reverse=True)
            _tbl_groups = [
                {"states": _by_share(_HRW_STATES),   "subtotal": "HRW — Hard Red Winter"},
                {"states": _by_share(_SRW_STATES),   "subtotal": "SRW — Soft Red Winter"},
                {"states": _by_share(_WHITE_STATES), "subtotal": "White Winter"},
            ]
        else:
            _tbl_groups = PROD_TABLE_GROUPS.get(commodity_label)   # None = share-sorted

        _tbl_df = _build_pivot_table(
            _panel_disp, _agg_df, _pmet_col, _disp_yrs, _prod_share_lkup, _jsa_col,
            groups=_tbl_groups,
        )

        if not _tbl_df.empty:
            _agg_labels      = {"🇺🇸 US Total", "⬡ HRW", "⬡ SRW", "⬡ White"}
            _subtotal_labels = {r for r in _tbl_df["State"] if str(r).startswith("  ▸ ")}

            def _style_prod_table(df):
                styles = pd.DataFrame("", index=df.index, columns=df.columns)
                for i, row in df.iterrows():
                    _is_agg      = row["State"] in _agg_labels
                    _is_subtotal = row["State"] in _subtotal_labels
                    if _is_agg:
                        styles.loc[i, :] = "font-weight:bold; background-color:#e8f5e9;"
                    elif _is_subtotal:
                        # Regional / class subtotal row: light sage bg, semibold, italic label
                        styles.loc[i, :] = "font-weight:600; background-color:#f0f7f0; color:#475569;"
                        styles.loc[i, "State"] = (
                            "font-weight:600; font-style:italic; background-color:#f0f7f0; "
                            "color:#475569; border-top:1px solid #e2e8f0;"
                        )
                    # Amber highlight for JSA estimate column
                    styles.loc[i, _jsa_col_hdr] = (
                        "background-color:#fef3c7; color:#b45309; font-weight:700;"
                        + (" border-left:2px solid #f59e0b;" if not _is_agg else "")
                    )
                    # Color-code all JSA % comparison columns (green +, red -)
                    for _pct_col in ("vs LY ▸ JSA", "vs Olympic ▸ JSA"):
                        _pv = str(row.get(_pct_col, ""))
                        if _pv.startswith("+"):
                            styles.loc[i, _pct_col] = "color:#15803d; font-weight:600;"
                        elif _pv.startswith("-"):
                            styles.loc[i, _pct_col] = "color:#dc2626; font-weight:600;"
                    # Muted style for Min / Max (reference context, not signals)
                    for _mm_col in ("Min", "Max"):
                        if _mm_col in df.columns:
                            styles.loc[i, _mm_col] = (
                                f"color:{DM_MUTED}; font-style:italic;"
                                + (" background-color:#e8f5e9;" if _is_agg else
                                   " background-color:#f0f7f0;" if _is_subtotal else "")
                            )
                    # vs LY (historical) coloring
                    _v_str = str(row.get("vs LY", ""))
                    if _v_str.startswith("+"):
                        _base = "color:#15803d;"
                        styles.loc[i, "vs LY"] = (
                            f"{_base} font-weight:700; background-color:#e8f5e9;" if _is_agg
                            else f"{_base} font-weight:600; background-color:#f0f7f0;" if _is_subtotal
                            else f"{_base} font-weight:600;"
                        )
                    elif _v_str.startswith("-"):
                        _base = "color:#dc2626;"
                        styles.loc[i, "vs LY"] = (
                            f"{_base} font-weight:700; background-color:#e8f5e9;" if _is_agg
                            else f"{_base} font-weight:600; background-color:#f0f7f0;" if _is_subtotal
                            else f"{_base} font-weight:600;"
                        )
                return styles

            _styled = (_tbl_df.style
                        .apply(_style_prod_table, axis=None)
                        .set_properties(**{"text-align": "right"})
                        .set_properties(subset=["State"], **{"text-align": "left"})
            )
            _tbl_height = min(900, 35 * (len(_tbl_df) + 1) + 40)

            # Caption explaining estimate column logic
            if commodity_label == "Winter Wheat":
                _planted_src_label = (
                    f"USDA {_planted_data_yr or sel_usda_yr}"
                    + (f" ({_planted_ref_src.title()})" if _planted_ref_src else "")
                )
                _nass_nat_note = (
                    f"**{sel_usda_yr} USDA column** = NASS national class-specific actuals "
                    f"(HRW/SRW/White from May Crop Production report; auto-updates each month). "
                    if _nat_patch else
                    f"**{sel_usda_yr} USDA column** = state-level winter wheat sums (NASS has not yet published "
                    f"{sel_usda_yr} class-specific national estimates). "
                )
                st.caption(
                    f"**{_jsa_col_hdr}** — JSA proprietary model: "
                    f"Planted = {_planted_src_label} USDA reported acres · "
                    f"% Harvested = JSA regression (class conditions index → historical harvest rate) · "
                    f"Harvested = Planted × % Harvested · "
                    f"Yield = JSA best-fit regression (linear/quadratic per state) · "
                    f"Production = Harvested × Yield.  "
                    f"{_nass_nat_note}"
                    f"**vs LY ▸ JSA** = % change from {sel_usda_yr - 1} actual to JSA {sel_usda_yr}E estimate.  "
                    f"**vs Olympic ▸ JSA** = % change from 6-year Olympic average (last 6 completed years, drop high & low) to JSA estimate.  "
                    f"**Min / Max** = range of values within the displayed historical window."
                )
            elif _non_ww_model_active:
                st.caption(
                    f"**{_jsa_col_hdr}** — "
                    f"Planted = most-recent USDA NASS reported acres (current year if available, else {sel_usda_yr - 1} actuals) · "
                    f"% Harvested = 5-year historical average harvest rate (abandonment is stable for {commodity_label}) · "
                    f"Harvested = Planted × % Harvested · "
                    f"Yield = JSA conditions regression (analog-year model: JSA index → yield deviation from trend, per state) · "
                    f"Production = Harvested × Yield.  "
                    f"**vs LY ▸ JSA** = % change from {sel_usda_yr - 1} actual to JSA {sel_usda_yr}E estimate.  "
                    f"**vs Olympic ▸ JSA** = % change from 6-year Olympic average (last 6 completed years, drop high & low) to JSA estimate.  "
                    f"**Min / Max** = range of values within the displayed historical window."
                )
            else:
                st.caption(
                    f"**{_jsa_col_hdr}** — USDA NASS reported actuals for {sel_usda_yr - 1} (last completed marketing year), "
                    f"used as the current-year estimate until {commodity_label} conditions reporting begins and the JSA model activates.  "
                    f"**vs LY ▸ {sel_usda_yr - 1} Actual** = % change from {sel_usda_yr - 2} actual to {sel_usda_yr - 1} actual.  "
                    f"**vs Olympic ▸ {sel_usda_yr - 1} Actual** = % change from 6-year Olympic average (last 6 completed years, drop high & low) to {sel_usda_yr - 1} actual.  "
                    f"**Min / Max** = range of values within the displayed historical window."
                )
            st.dataframe(_styled, use_container_width=True, height=_tbl_height, hide_index=True)
            _dl_btn(_tbl_df, f"ww_production_{_pmet.replace(' ','_').replace('/','_')}.xlsx",
                    f"⬇ Download {_pmet} Table")
        else:
            st.info("No data available for the current filters.")

    else:
        st.info("Production history data not available. Check API connectivity.")

with _tab_abandon:
    # ── % Harvested Study — Winter Wheat by class ──────────────────────────────────
    if commodity_label == "Winter Wheat":
        st.markdown(
            '<div class="sec-hdr">% Harvested Study — Winter Wheat by Class</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Planted vs. harvested acres (1985\u2013present) expressed as % of planted acres harvested \u2014 "
            "the industry-standard abandonment measure. Each class tab correlates its JSA condition "
            "index against the final % harvested to assess predictive power."
        )

        _ab_years = tuple(range(1985, sel_usda_yr + 1))

        # ── Fetch data: national totals + state-level (for class derivation) ──────
        # US Total uses fetch_ww_national_totals (state_name=US TOTAL + exact short_desc)
        # rather than fetch_winter_wheat_acres (agg_level_desc=NATIONAL + loose filter +
        # asymmetric planted/harvested methodology) which produces wrong pct_harvested
        # from 2016 onward due to NASS national endpoint inconsistencies.
        with st.spinner("Loading winter wheat acres from USDA NASS (1985–present)…"):
            _ab_national_raw = fetch_ww_national_totals(_ab_years)
            _ab_state_df     = fetch_ww_state_acres(_ab_years)

        # Derive abandoned_ac and abandonment_pct for the national df
        if not _ab_national_raw.empty:
            _ab_national_df = _ab_national_raw.copy()
            _ab_national_df["abandoned_ac"] = (
                (_ab_national_df["planted_ac"] - _ab_national_df["harvested_ac"]).clip(lower=0)
            )
            _ab_national_df["abandonment_pct"] = np.where(
                _ab_national_df["planted_ac"] > 0,
                (_ab_national_df["abandoned_ac"] / _ab_national_df["planted_ac"] * 100).round(1),
                np.nan,
            )
        else:
            _ab_national_df = pd.DataFrame()

        # ── Fetch NASS national class-specific acres for HRW / SRW / White ────────────
        # Use official USDA national class-level planted and harvested acres as the
        # authoritative source for % harvested history.  The JSA index regression is
        # ONLY used to place the current-year forecast star on the scatter chart —
        # all historical data points come directly from NASS final reports.
        # Falls back to total-WW state-sum proxy only when NASS national class data
        # is unavailable (e.g. NASS hasn't yet released class actuals for a new year).
        # _ab_years == _prod_tab_years, so the prefetched startup results are reused directly
        _ab_hrw_natl = _pf_hrw_natl_ac
        _ab_srw_natl = _pf_srw_natl_ac
        _ab_wht_natl = _pf_wht_natl_ac

        def _build_class_abandon_df(natl_harv_df, state_weights, fallback_state_df):
            """Build year-level abandon metrics for one wheat class.

            NASS publishes class-specific area HARVESTED at national level — those are
            the authoritative numbers.  NASS does NOT publish class-specific area
            PLANTED at national level (seedings survey only covers all-winter totals).

            Hybrid approach:
              • harvested_ac  = NASS national class harvested (official USDA final)
              • planted_ac    = state-sum of total-WW planted for class states (best proxy)
              • % harvested   = NASS harvested / state planted

            This gives the most accurate % harvested possible from available NASS data.
            Abandoned = planted − harvested; abandonment % = abandoned / planted.

            Fallback: if NASS harvested is unavailable, use state-sum proxy entirely.
            """
            _MIN_PTS = 10
            # Build state planted proxy for this class (used as denominator)
            _state_proxy = _class_acres_from_state(fallback_state_df, state_weights)

            if (natl_harv_df is not None and not natl_harv_df.empty
                    and len(natl_harv_df) >= _MIN_PTS
                    and not _state_proxy.empty):
                # Merge NASS class harvested onto state-proxy planted
                df = _state_proxy[["year", "planted_ac"]].merge(
                    natl_harv_df[["year", "harvested_ac"]],
                    on="year", how="inner",
                )
                # Physical cap: harvested ≤ planted
                df["harvested_ac"]  = df[["planted_ac", "harvested_ac"]].min(axis=1)
                df["abandoned_ac"]  = (df["planted_ac"] - df["harvested_ac"]).clip(lower=0)
                df["abandonment_pct"] = (df["abandoned_ac"] / df["planted_ac"] * 100).round(1)
                df["pct_harvested"]   = (df["harvested_ac"] / df["planted_ac"] * 100).round(1)
                if len(df) >= _MIN_PTS:
                    return df.sort_values("year").reset_index(drop=True)

            # Fallback: total-winter-wheat proxy summed for class states
            return _state_proxy

        _ab_hrw_df   = _build_class_abandon_df(_ab_hrw_natl, _dynamic_hrw_weights, _ab_state_df)
        _ab_srw_df   = _build_class_abandon_df(_ab_srw_natl, _dynamic_srw_weights, _ab_state_df)
        _ab_white_df = _build_class_abandon_df(_ab_wht_natl, _dynamic_white_weights, _ab_state_df)


        # ── Diagnostic expander: show data source + row counts for each class ──────
        with st.expander("🔍 Data Source Diagnostics", expanded=False):
            _diag_rows = []
            for _dk, _dnatl, _ddf, _dweights in [
                ("HRW",   _ab_hrw_natl,  _ab_hrw_df,   _dynamic_hrw_weights),
                ("SRW",   _ab_srw_natl,  _ab_srw_df,   _dynamic_srw_weights),
                ("White", _ab_wht_natl,  _ab_white_df, _dynamic_white_weights),
            ]:
                _nass_rows  = len(_dnatl) if _dnatl is not None and not _dnatl.empty else 0
                _proxy_used = _nass_rows < 10
                _yr_range   = (
                    f"{int(_ddf['year'].min())}–{int(_ddf['year'].max())}"
                    if not _ddf.empty else "N/A"
                )
                _avg_ph = (
                    f"{_ddf['pct_harvested'].mean():.1f}%"
                    if not _ddf.empty and "pct_harvested" in _ddf.columns else "N/A"
                )
                _source = "State-sum proxy (NASS class harvested unavailable)" if _proxy_used else f"NASS national class harvested ({_nass_rows} yrs) + state planted"
                _diag_rows.append({
                    "Class":           _dk,
                    "NASS Harv Rows":  _nass_rows,
                    "Source":          _source,
                    "Year Range":      _yr_range,
                    "Avg % Harvested": _avg_ph,
                })
            st.dataframe(pd.DataFrame(_diag_rows), hide_index=True, use_container_width=True)
            st.caption(
                "NASS publishes class-specific area harvested at national level (confirmed). "
                "Class-specific planted acres are NOT a published NASS national series. "
                "% Harvested = NASS class harvested ÷ state-sum planted for class states."
            )

        # ── Helper: panel + data table in one call ────────────────────────────────────────────
        def _ab_render_with_table(ab_df, jsa_snap, lbl, color, key_str,
                                  use_jsa_model=False, forecast_pct_override=None):
            _render_abandon_panel(ab_df, jsa_snap, lbl, color, sel_usda_yr,
                                  use_jsa_model=use_jsa_model,
                                  forecast_pct_override=forecast_pct_override)
            if not ab_df.empty:
                _t = ab_df.copy()
                _t["jsa_index"] = _t["year"].map(jsa_snap).round(1)
                _t = _t.rename(columns={
                    "year":"Crop Year","planted_ac":"Planted (ac)",
                    "harvested_ac":"Harvested (ac)","abandoned_ac":"Abandoned (ac)",
                    "pct_harvested":"% Harvested","abandonment_pct":"Abandonment %",
                    "jsa_index":"JSA Index",
                })
                for _c in ["Planted (ac)","Harvested (ac)","Abandoned (ac)"]:
                    _t[_c] = _t[_c].apply(lambda v: f"{v/1e6:.3f}M" if pd.notna(v) else "N/A")
                _t = _t[["Crop Year","Planted (ac)","Harvested (ac)","Abandoned (ac)",
                          "% Harvested","Abandonment %","JSA Index"]].sort_values("Crop Year", ascending=False)
                with st.expander("📋 Data Table", expanded=False):
                    st.dataframe(_t, hide_index=True, use_container_width=True,
                                 height=min(46*len(_t)+56, 480))
                    _dl_btn(_t, f"ww_pct_harvested_{key_str}.xlsx", "⬇ Download Data")

        # ── Class definitions ─────────────────────────────────────────────────────────────────────────
        _AB_CLASSES = [
            ("🌾 US Total",        _ab_national_df, "US",    "#f59e0b"),
            ("🔴 Hard Red Winter", _ab_hrw_df,      "HRW",   "#ef4444"),
            ("🟡 Soft Red Winter", _ab_srw_df,      "SRW",   "#eab308"),
            ("⚪ White",           _ab_white_df,    "White", "#94a3b8"),
        ]

        # State selector — default to sidebar state filter or first available state
        _ab_state_options = sorted(
            [s for s in _ab_state_df["state"].unique() if len(s) == 2]
        ) if not _ab_state_df.empty else []
        _ab_state_default = (sel_state_alpha if sel_state_alpha in _ab_state_options
                             else (_ab_state_options[0] if _ab_state_options else None))

        _ab_subtabs = st.tabs(["📍 State"] + [c[0] for c in _AB_CLASSES])
        _ab_state_tab, *_ab_class_tabs = _ab_subtabs

        # ── State tab ─────────────────────────────────────────────────────────────────────────────
        with _ab_state_tab:
            if _ab_state_options:
                _ab_sel_st = st.selectbox(
                    "Select State",
                    options=_ab_state_options,
                    index=(_ab_state_options.index(_ab_state_default)
                           if _ab_state_default else 0),
                    key="ab_state_sel",
                )
                _ab_st_rows = _ab_state_df[_ab_state_df["state"] == _ab_sel_st].copy()
                # Compute abandonment columns (fetch_ww_state_acres returns only planted/harvested)
                if not _ab_st_rows.empty:
                    _ab_st_rows["abandoned_ac"]    = (_ab_st_rows["planted_ac"] - _ab_st_rows["harvested_ac"]).clip(lower=0)
                    _ab_st_rows["abandonment_pct"] = (_ab_st_rows["abandoned_ac"] / _ab_st_rows["planted_ac"].replace(0, float("nan")) * 100).round(1)
                    _ab_st_rows["pct_harvested"]   = (_ab_st_rows["harvested_ac"] / _ab_st_rows["planted_ac"].replace(0, float("nan")) * 100).round(1)
                _ab_st_af   = _compute_analog_forecast(
                    _ab_sel_st, raw_df, _effective_week_ts(_ab_sel_st), sel_usda_yr,
                    _yield_lookup, _trend_data, _dynamic_hrw_weights,
                    class_weights_map={"HRW": _dynamic_hrw_weights,
                                       "SRW": _dynamic_srw_weights,
                                       "White": _dynamic_white_weights},
                    crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                    cond_weights=_active_cw,
                )
                _ab_st_snap = _ab_st_af["jsa_snap"] if _ab_st_af else {}
                _ab_st_name = (
                    _ab_st_rows["state_name"].iloc[0]
                    if not _ab_st_rows.empty and "state_name" in _ab_st_rows.columns
                    else _ab_sel_st
                )
                # JSA regression for non-SRW states; rolling avg for SRW states
                # (individual SRW state slopes are unreliable — class aggregate is fine)
                _st_is_srw = _ab_sel_st in WHEAT_CLASSES["SRW — Soft Red Winter"]
                _ab_render_with_table(_ab_st_rows, _ab_st_snap, _ab_st_name,
                                      JPSI_BLUE, _ab_sel_st.lower(),
                                      use_jsa_model=not _st_is_srw)
            else:
                st.info("No state-level acres data available.")

        # ── Class tabs ────────────────────────────────────────────────────────────────────────────
        for _ab_stab, (_ab_lbl, _ab_df, _ab_key, _ab_color) in zip(_ab_class_tabs, _AB_CLASSES):
            with _ab_stab:
                _ab_analog   = _class_analog_results.get(_ab_key) or _analog_result
                _ab_jsa_snap = (
                    _ab_analog["jsa_snap"] if _ab_analog and "jsa_snap" in _ab_analog else {}
                )
                _ab_render_with_table(_ab_df, _ab_jsa_snap, _ab_lbl, _ab_color,
                                      _ab_key.lower(), use_jsa_model=True,
                                      forecast_pct_override=_ph_cls.get(_ab_key))

        # ── Look-Back R² Scan — Best Predictive Week for % Harvested ─────────────
        st.markdown("---")
        st.markdown(
            '<div class="sec-hdr">Look-Back R² Scan — Best Predictive Week for % Harvested</div>',
            unsafe_allow_html=True,
        )
        _ab_scan_iso_min, _ab_scan_iso_max = commodity_cfg.get("scan_iso_range", (5, 22))
        _ab_wk_start_lbl = datetime.fromisocalendar(2024, _ab_scan_iso_min, 3).strftime("%b %d").lstrip("0").replace(" 0", " ")
        _ab_wk_end_lbl   = datetime.fromisocalendar(2024, _ab_scan_iso_max, 3).strftime("%b %d").lstrip("0").replace(" 0", " ")
        st.caption(
            f"Scans every marketing week (ISO weeks {_ab_scan_iso_min}–{_ab_scan_iso_max}, "
            f"{_ab_wk_start_lbl}–{_ab_wk_end_lbl}) and finds which week historically "
            "produces the highest R² between the JSA condition index and final % harvested "
            "(1 − abandonment rate).  Excludes the current season.  "
            "Series with fewer than 8 years of data are omitted."
        )

        # Build % harvested history dict for each series
        import json as _ab_json
        _ab_ph_data: dict = {}

        # Class aggregates
        for _ab_cls_k, _ab_cls_df in [
            ("US",    _ab_national_df),
            ("HRW",   _ab_hrw_df),
            ("SRW",   _ab_srw_df),
            ("White", _ab_white_df),
        ]:
            if not _ab_cls_df.empty and "pct_harvested" in _ab_cls_df.columns:
                _ab_ph_data[_ab_cls_k] = {
                    str(int(r["year"])): r["pct_harvested"]
                    for _, r in _ab_cls_df.iterrows()
                    if pd.notna(r.get("pct_harvested"))
                }

        # Individual states
        if not _ab_state_df.empty:
            for _ab_st in sorted(_ab_state_df["state"].unique()):
                if len(_ab_st) != 2:
                    continue
                _ab_st_sub = _ab_state_df[_ab_state_df["state"] == _ab_st].copy()
                if _ab_st_sub.empty:
                    continue
                # Compute pct_harvested if not already present
                if "pct_harvested" not in _ab_st_sub.columns:
                    _ab_st_sub["pct_harvested"] = (
                        _ab_st_sub["harvested_ac"]
                        / _ab_st_sub["planted_ac"].replace(0, float("nan")) * 100
                    ).round(1)
                _st_ph = {
                    str(int(r["year"])): r["pct_harvested"]
                    for _, r in _ab_st_sub.iterrows()
                    if pd.notna(r.get("pct_harvested"))
                }
                if _st_ph:
                    _ab_ph_data[_ab_st] = _st_ph

        with st.spinner("Running look-back scan for % harvested…"):
            _ab_scan_res = _scan_best_week_harvest(
                raw_df, sel_usda_yr,
                _ab_json.dumps(_ab_ph_data),
                tuple(sorted(_dynamic_hrw_weights.items())),
                tuple(sorted(_dynamic_srw_weights.items())),
                tuple(sorted(_dynamic_white_weights.items())),
                _crop_yr_cutoff=commodity_cfg.get("crop_yr_cutoff", 9),
                _scan_iso_min=_ab_scan_iso_min,
                _scan_iso_max=_ab_scan_iso_max,
                commodity_key=commodity_label,
            )

        def _ab_iso_lbl(iso_w: int) -> str:
            try:
                d = datetime.fromisocalendar(2024, int(iso_w), 3)
                return f"Wk {iso_w} · {d.strftime('%b %d')}"
            except Exception:
                return f"Wk {iso_w}"

        if _ab_scan_res:
            _ab_priority_ord = {"US": 0, "HRW": 1, "SRW": 2, "White": 3}
            _ab_idx_keys = [k for k in ("US", "HRW", "SRW", "White") if k in _ab_scan_res]
            _ab_st_keys  = sorted(
                [k for k in _ab_scan_res if k not in _ab_priority_ord],
                key=lambda k: -_ab_scan_res[k]["r2"],
            )

            _ab_idx_rows = []
            for _ab_sk in _ab_idx_keys:
                _ab_sr = _ab_scan_res[_ab_sk]
                _ab_lbl_map = {
                    "US":    "🇺🇸 US Total",
                    "HRW":   "⬡ HRW Index",
                    "SRW":   "⬡ SRW Index",
                    "White": "⬡ White Index",
                }
                _ab_idx_rows.append({
                    "Series":    _ab_lbl_map.get(_ab_sk, _ab_sk),
                    "Best Week": _ab_iso_lbl(_ab_sr["best_iso"]),
                    "Peak R²":   f"{_ab_sr['r2']*100:.0f}%",
                    "Yrs":       _ab_sr["n_years"],
                })

            _ab_st_rows = []
            for _ab_sk in _ab_st_keys:
                _ab_sr = _ab_scan_res[_ab_sk]
                _ab_st_rows.append({
                    "State":     _ab_sk,
                    "Best Week": _ab_iso_lbl(_ab_sr["best_iso"]),
                    "Peak R²":   f"{_ab_sr['r2']*100:.0f}%",
                    "Yrs":       _ab_sr["n_years"],
                })

            _ab_c1, _ab_c2 = st.columns([1, 2])
            with _ab_c1:
                st.markdown(
                    f'<div style="font-size:0.78rem;font-weight:600;color:{JPSI_BLUE};'
                    f'margin-bottom:4px">Index & National</div>',
                    unsafe_allow_html=True,
                )
                _ab_idx_df = pd.DataFrame(_ab_idx_rows)
                st.dataframe(_ab_idx_df, hide_index=True, use_container_width=True,
                             height=min(46 * len(_ab_idx_rows) + 56, 260))
                _dl_btn(_ab_idx_df, "harvest_bestweek_index.xlsx", "⬇ Download")
            with _ab_c2:
                st.markdown(
                    f'<div style="font-size:0.78rem;font-weight:600;color:{JPSI_BLUE};'
                    f'margin-bottom:4px">State Level — sorted by peak R²</div>',
                    unsafe_allow_html=True,
                )
                _ab_st_df_out = pd.DataFrame(_ab_st_rows)
                st.dataframe(_ab_st_df_out, hide_index=True, use_container_width=True,
                             height=min(46 * len(_ab_st_rows) + 56, 520))
                _dl_btn(_ab_st_df_out, "harvest_bestweek_states.xlsx", "⬇ Download")

            # R² curve chart — shows how predictive power shifts across weeks
            # for each class series (mirrors the yield tab R² scan chart)
            _ab_r2_rows = []
            for _ab_sk in _ab_idx_keys:
                _ab_sr = _ab_scan_res[_ab_sk]
                for _ab_wk, _ab_wk_r2 in _ab_sr.get("all_r2", {}).items():
                    _ab_r2_rows.append({
                        "iso_week": int(_ab_wk),
                        "r2":       float(_ab_wk_r2),
                        "series":   _ab_sk,
                    })
            if _ab_r2_rows:
                _ab_r2_df = pd.DataFrame(_ab_r2_rows)
                _ab_r2_fig = go.Figure()
                _ab_cls_colors = {"US": "#f59e0b", "HRW": "#ef4444",
                                  "SRW": "#eab308", "White": "#94a3b8"}
                for _ab_sk in _ab_idx_keys:
                    _ab_sub = _ab_r2_df[_ab_r2_df["series"] == _ab_sk].sort_values("iso_week")
                    if _ab_sub.empty:
                        continue
                    _ab_r2_fig.add_trace(go.Scatter(
                        x=_ab_sub["iso_week"],
                        y=(_ab_sub["r2"] * 100).round(1),
                        mode="lines+markers",
                        name=_ab_sk,
                        line=dict(color=_ab_cls_colors.get(_ab_sk, JPSI_BLUE), width=2),
                        marker=dict(size=5),
                        hovertemplate=f"<b>{_ab_sk}</b><br>ISO Wk %{{x}}<br>R² = %{{y:.1f}}%<extra></extra>",
                    ))
                    # Mark best week
                    _ab_bw = _ab_scan_res[_ab_sk]["best_iso"]
                    _ab_bw_row = _ab_sub[_ab_sub["iso_week"] == _ab_bw]
                    if not _ab_bw_row.empty:
                        _ab_r2_fig.add_trace(go.Scatter(
                            x=_ab_bw_row["iso_week"],
                            y=(_ab_bw_row["r2"] * 100).round(1),
                            mode="markers",
                            name=f"{_ab_sk} best",
                            marker=dict(size=11, symbol="star",
                                        color=_ab_cls_colors.get(_ab_sk, JPSI_BLUE)),
                            showlegend=False,
                            hovertemplate=f"<b>{_ab_sk} best week</b><br>ISO Wk %{{x}}<br>R² = %{{y:.1f}}%<extra></extra>",
                        ))
                _ab_r2_fig.update_layout(
                    xaxis=dict(title="ISO Week", gridcolor=DM_BORDER, dtick=1,
                               tickfont=dict(size=10)),
                    yaxis=dict(title="R² (%)", gridcolor=DM_BORDER, rangemode="tozero"),
                    paper_bgcolor=DM_BG,
                    plot_bgcolor=DM_SURFACE2,
                    legend=dict(
                        orientation="h", x=0.5, xanchor="center", y=-0.18,
                        font=dict(color=DM_TEXT, size=11),
                        bgcolor="rgba(0,0,0,0)",
                    ),
                    margin=dict(l=10, r=10, t=20, b=60),
                    height=340,
                    hovermode="x unified",
                )
                _show_chart(_ab_r2_fig, "abandonment_r2")
                st.caption(
                    "Stars mark the best predictive ISO week per class.  "
                    "Weeks where conditions have the highest correlation with final % harvested "
                    "are the most useful for in-season abandonment forecasting."
                )
        else:
            st.info("Insufficient % harvested data to run look-back scan (need ≥ 8 years per series).")

    else:
        st.info("The % Harvested study is currently available for Winter Wheat only.")

with _tab_info:
    # ── Wheat Classes Reference ─────────────────────────────────────────────────
    if commodity_label == "Winter Wheat":
        st.markdown(
            '<div class="sec-hdr">U.S. Wheat Classes — Planting, Harvest &amp; Production Share</div>',
            unsafe_allow_html=True,
        )
        st.caption("Six major classes — seasonal timing, growing regions, and share of total U.S. production. "
                   "Production shares are approximate long-run averages; actual shares vary by crop year.")

        # ── Badge helpers ────────────────────────────────────────────────────────
        _BADGE = {
            "Winter":        f'<span style="background:#1e3a5f;color:#7eb8f7;padding:2px 9px;border-radius:4px;font-size:0.78rem;font-weight:600">Winter</span>',
            "Spring":        f'<span style="background:#1a3a25;color:#4ade80;padding:2px 9px;border-radius:4px;font-size:0.78rem;font-weight:600">Spring</span>',
            "Winter/Spring": f'<span style="background:#2e2050;color:#c084fc;padding:2px 9px;border-radius:4px;font-size:0.78rem;font-weight:600">Winter/Spring</span>',
        }

        def _bar_html(pct: float, color: str = "#4ade80") -> str:
            """Horizontal production-share bar + label."""
            w = int(round(pct / 40 * 180))   # scale: 40 % → 180 px
            return (
                f'<div style="display:flex;align-items:center;gap:8px">'
                f'<div style="width:180px;background:{DM_BORDER};border-radius:3px;height:14px">'
                f'<div style="width:{w}px;background:{color};border-radius:3px;height:14px"></div>'
                f'</div>'
                f'<span style="color:{DM_TEXT};font-weight:700;font-size:0.92rem">~{pct:.0f}%</span>'
                f'</div>'
            )

        # ── Table data ───────────────────────────────────────────────────────────
        _WC_ROWS = [
            {
                "class":    "Hard Red Winter<br><span style='color:{m};font-size:0.82rem'>(HRW)</span>".format(m=DM_MUTED),
                "type":     "Winter",
                "planted":  "Sept – Oct",
                "harvest":  "May – July",
                "regions":  "Great Plains (TX to MT)",
                "pct":      40,
                "bar_clr":  "#4ade80",
            },
            {
                "class":    "Hard Red Spring<br><span style='color:{m};font-size:0.82rem'>(HRS)</span>".format(m=DM_MUTED),
                "type":     "Spring",
                "planted":  "Mar – May",
                "harvest":  "July – Sept",
                "regions":  "Northern Plains (ND, SD, MT)",
                "pct":      23,
                "bar_clr":  "#4ade80",
            },
            {
                "class":    "Soft Red Winter<br><span style='color:{m};font-size:0.82rem'>(SRW)</span>".format(m=DM_MUTED),
                "type":     "Winter",
                "planted":  "Sept – Oct",
                "harvest":  "May – July",
                "regions":  "Midwest &amp; Southeast",
                "pct":      18,
                "bar_clr":  "#4ade80",
            },
            {
                "class":    "Soft White<br><span style='color:{m};font-size:0.82rem'>(SW)</span>".format(m=DM_MUTED),
                "type":     "Winter/Spring",
                "planted":  "Sept–Oct or Mar–May",
                "harvest":  "June – Aug",
                "regions":  "Pacific Northwest",
                "pct":      12,
                "bar_clr":  "#4ade80",
            },
            {
                "class":    "Durum<br><span style='color:{m};font-size:0.82rem'>(Durum)</span>".format(m=DM_MUTED),
                "type":     "Spring",
                "planted":  "Mar – May",
                "harvest":  "July – Sept",
                "regions":  "Northern Plains + AZ/CA",
                "pct":      4,
                "bar_clr":  "#4ade80",
            },
            {
                "class":    "Hard White<br><span style='color:{m};font-size:0.82rem'>(HW)</span>".format(m=DM_MUTED),
                "type":     "Winter/Spring",
                "planted":  "Sept–Oct or Mar–May",
                "harvest":  "June – Aug",
                "regions":  "Western states",
                "pct":      1,
                "bar_clr":  "#4ade80",
            },
        ]

        # Header row
        _TH = (
            f'background:{DM_SURFACE};color:{JPSI_BLUE};font-weight:700;'
            f'font-size:0.84rem;padding:10px 14px;border-bottom:2px solid {DM_BORDER};'
            f'text-align:left;white-space:nowrap'
        )
        _TD_BASE = (
            f'padding:10px 14px;border-bottom:1px solid {DM_BORDER};'
            f'font-size:0.88rem;color:{DM_TEXT};vertical-align:middle'
        )

        _rows_html = ""
        for _i, _r in enumerate(_WC_ROWS):
            _bg = DM_SURFACE if _i % 2 == 0 else DM_SURFACE2
            _rows_html += (
                f'<tr style="background:{_bg}">'
                f'<td style="{_TD_BASE};font-weight:600">{_r["class"]}</td>'
                f'<td style="{_TD_BASE}">{_BADGE[_r["type"]]}</td>'
                f'<td style="{_TD_BASE}">{_r["planted"]}</td>'
                f'<td style="{_TD_BASE}">{_r["harvest"]}</td>'
                f'<td style="{_TD_BASE};color:{DM_MUTED}">{_r["regions"]}</td>'
                f'<td style="{_TD_BASE}">{_bar_html(_r["pct"], _r["bar_clr"])}</td>'
                f'</tr>'
            )

        _info_table_html = f"""
<div style="overflow-x:auto;margin-top:1rem">
<table style="width:100%;border-collapse:collapse;border:1px solid {DM_BORDER};border-radius:8px;overflow:hidden">
  <thead>
    <tr>
      <th style="{_TH}">Wheat Class</th>
      <th style="{_TH}">Type</th>
      <th style="{_TH}">Planted</th>
      <th style="{_TH}">Harvested</th>
      <th style="{_TH}">Main Regions</th>
      <th style="{_TH}">% of U.S. Production</th>
    </tr>
  </thead>
  <tbody>
    {_rows_html}
  </tbody>
</table>
</div>
<div style="margin-top:0.6rem;font-size:0.75rem;color:{DM_MUTED}">
  Source: USDA NASS &nbsp;|&nbsp; JSA Research &nbsp;|&nbsp; AgMarket.Net — Farm Division of JSA
</div>
"""
        st.markdown(_info_table_html, unsafe_allow_html=True)

        # ── Additional class-specific notes ──────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            f'<div class="sec-hdr">Class Notes</div>',
            unsafe_allow_html=True,
        )
        _note_cols = st.columns(3)
        _NOTES = [
            ("🟡 HRW — Hard Red Winter",
             "Dominant U.S. wheat class. Used primarily for bread flour. "
             "Kansas, Oklahoma, and Texas together account for ~75% of HRW production. "
             "Most sensitive to late-winter/spring conditions."),
            ("🔴 HRS — Hard Red Spring",
             "Highest protein content of any class. Prized for bread and blending. "
             "Grown primarily in North Dakota, Montana, Minnesota, and South Dakota. "
             "Spring seeding means no dormancy period."),
            ("🟢 SRW — Soft Red Winter",
             "Lower protein, used for pastries, crackers, and cakes. "
             "Grown across the Midwest and Southeast. "
             "More tolerant of wet conditions than HRW."),
            ("⚪ Soft White",
             "Very low protein. Used for crackers, pastries, Asian noodles. "
             "Produced almost entirely in the Pacific Northwest (WA, OR, ID). "
             "Includes both winter and spring types."),
            ("🟤 Durum",
             "Hardest wheat; used exclusively for pasta and semolina. "
             "Primarily grown in North Dakota and Montana. "
             "Spring-planted with relatively concentrated production geography."),
            ("🔵 Hard White",
             "Similar protein to HRW but milder flavor. "
             "Used for whole-wheat bread and Asian noodles. "
             "Smallest class by production share (~1%)."),
        ]
        for _ni, (_ntitle, _nbody) in enumerate(_NOTES):
            with _note_cols[_ni % 3]:
                st.markdown(
                    f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};'
                    f'border-radius:8px;padding:14px 16px;margin-bottom:12px">'
                    f'<div style="font-weight:700;color:{DM_TEXT};margin-bottom:6px;font-size:0.9rem">{_ntitle}</div>'
                    f'<div style="color:{DM_MUTED};font-size:0.83rem;line-height:1.5">{_nbody}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # ── Global Wheat Reference Table ──────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            '<div class="sec-hdr">Global Wheat Reference Table — Top Exporters</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Approximate long-run production shares; actual % varies by year. "
            "Global production ~800–840 MMT."
        )

        _GBADGE = {
            "Winter":        f'<span style="background:#1e3a5f;color:#7eb8f7;padding:2px 8px;border-radius:4px;font-size:0.78rem;font-weight:600">Mostly Winter</span>',
            "Spring":        f'<span style="background:#1a3a25;color:#4ade80;padding:2px 8px;border-radius:4px;font-size:0.78rem;font-weight:600">Mostly Spring</span>',
            "WinterSpring":  f'<span style="background:#2e2050;color:#c084fc;padding:2px 8px;border-radius:4px;font-size:0.78rem;font-weight:600">Mostly Winter/Spring</span>',
            "WinterWSpring": f'<span style="background:#1e3a5f;color:#7eb8f7;padding:2px 8px;border-radius:4px;font-size:0.78rem;font-weight:600">~70% Winter / 30% Spring</span>',
        }

        _GWC_ROWS = [
            {
                "region":   "European Union",
                "type":     "Winter",
                "hardsoft": "<b>Predominantly Soft</b> wheat (majority soft white/red winter); limited hard wheat",
                "planted":  "Sept–Oct",
                "harvest":  "June–Aug",
                "regions":  "France, Germany, Poland, Romania",
                "share":    "~15–18%",
            },
            {
                "region":   "Russia",
                "type":     "WinterWSpring",
                "hardsoft": "<b>Mostly Soft</b> wheat overall; majority of winter wheat is soft",
                "planted":  "Aug–Oct (W)<br>Apr–May (S)",
                "harvest":  "July–Aug (W)<br>Aug–Sept (S)",
                "regions":  "Southern &amp; Central (Winter), Siberia/Volga (Spring)",
                "share":    "~10–12%",
            },
            {
                "region":   "Canada",
                "type":     "Spring",
                "hardsoft": "<b>Mostly Hard</b> (high-protein spring wheat); minimal winter",
                "planted":  "Apr–June",
                "harvest":  "Aug–Oct",
                "regions":  "Prairies (SK, AB, MB)",
                "share":    "~4–5%",
            },
            {
                "region":   "Australia",
                "type":     "WinterSpring",
                "hardsoft": "Mix of <b>Hard</b> (e.g. APH) and <b>Soft</b> classes; varies by region/year",
                "planted":  "Apr–June",
                "harvest":  "Oct–Jan",
                "regions":  "Western Australia, NSW, Victoria",
                "share":    "~3–5%",
            },
            {
                "region":   "Argentina",
                "type":     "Winter",
                "hardsoft": "<b>Both Hard &amp; Soft</b> characteristics; flexible milling types",
                "planted":  "Apr–June",
                "harvest":  "Nov–Jan",
                "regions":  "Buenos Aires, Córdoba, Santa Fe",
                "share":    "~2–3%",
            },
            {
                "region":   "Ukraine",
                "type":     "Winter",
                "hardsoft": "<b>Mostly Hard Red</b> winter wheat",
                "planted":  "Sept–Oct",
                "harvest":  "June–Aug",
                "regions":  "Central &amp; Southern Black Sea",
                "share":    "~2–3%",
            },
            {
                "region":   "Kazakhstan",
                "type":     "Spring",
                "hardsoft": "<b>Mostly Hard</b> spring wheat",
                "planted":  "Apr–May",
                "harvest":  "July–Sept",
                "regions":  "Northern steppes",
                "share":    "~1–2%",
            },
            {
                "region":   "Turkey",
                "type":     "Winter",
                "hardsoft": "<b>Mostly Hard</b> winter wheat",
                "planted":  "Sept–Oct",
                "harvest":  "June–July",
                "regions":  "Central Anatolia, Marmara, Aegean",
                "share":    "~2%",
            },
        ]

        _g_rows_html = ""
        for _gi, _gr in enumerate(_GWC_ROWS):
            _gbg = DM_SURFACE if _gi % 2 == 0 else DM_SURFACE2
            _g_rows_html += (
                f'<tr style="background:{_gbg}">'
                f'<td style="{_TD_BASE};font-weight:700">{_gr["region"]}</td>'
                f'<td style="{_TD_BASE}">{_GBADGE[_gr["type"]]}</td>'
                f'<td style="{_TD_BASE}">{_gr["hardsoft"]}</td>'
                f'<td style="{_TD_BASE}">{_gr["planted"]}</td>'
                f'<td style="{_TD_BASE}">{_gr["harvest"]}</td>'
                f'<td style="{_TD_BASE};color:{DM_MUTED}">{_gr["regions"]}</td>'
                f'<td style="{_TD_BASE};text-align:center;font-weight:700;color:{JPSI_BLUE}">{_gr["share"]}</td>'
                f'</tr>'
            )

        _global_table_html = f"""
<div style="overflow-x:auto;margin-top:1rem">
<table style="width:100%;border-collapse:collapse;border:1px solid {DM_BORDER};border-radius:8px;overflow:hidden">
  <thead>
    <tr>
      <th style="{_TH}">Wheat Region</th>
      <th style="{_TH}">Type</th>
      <th style="{_TH}">Hard vs Soft Notes<br>(esp. Winter)</th>
      <th style="{_TH}">Planted</th>
      <th style="{_TH}">Harvested</th>
      <th style="{_TH}">Main Regions</th>
      <th style="{_TH}">% of World<br>Production</th>
    </tr>
  </thead>
  <tbody>
    {_g_rows_html}
  </tbody>
</table>
</div>
<div style="margin-top:0.6rem;font-size:0.75rem;color:{DM_MUTED}">
  Source: USDA FAS &nbsp;|&nbsp; IGC (International Grains Council) &nbsp;|&nbsp; JSA Research
</div>
"""
        st.markdown(_global_table_html, unsafe_allow_html=True)

    else:
        st.info("The Wheat Classes Reference is available when Winter Wheat is selected as the commodity.")


# ── Footer ─────────────────────────────────────────────────────────────────────
_cur_year = datetime.now().year
st.markdown(f"""
<div style="border-top:1px solid {DM_BORDER};margin-top:2rem;padding:20px 0 4px 0">
  <div style="text-align:center;color:{DM_MUTED};font-size:0.73rem;padding-bottom:14px">
    Data: USDA NASS Quick Stats &nbsp;|&nbsp; John Stewart &amp; Associates
    &nbsp;|&nbsp; Refreshed: {datetime.now().strftime("%Y-%m-%d %H:%M")} CT
  </div>
  <div style="max-width:900px;margin:0 auto;color:{DM_MUTED};font-size:0.68rem;
              line-height:1.55;text-align:center;padding-bottom:16px">
    Trading commodity futures, options on futures, cash commodities, and over-the-counter
    derivative products involves substantial risk of loss and may not be suitable for all
    investors. This communication is provided for informational purposes only and does not
    constitute investment advice, a recommendation, or an offer or solicitation to buy or
    sell any futures, options, cash commodities, or derivative products. John Stewart &amp;
    Associates, Inc. does not accept orders to buy or sell any financial instruments via
    email. The information contained herein has been obtained from sources believed to be
    reliable; however, its accuracy and completeness are not guaranteed. Any opinions
    expressed are solely those of the author, are subject to change without notice, and
    should not be relied upon as a basis for investment decisions. Past performance is not
    indicative of future results. This message may contain confidential or proprietary
    information intended solely for the use of the designated recipient.
    &copy; John Stewart &amp; Associates, Inc. {_cur_year}
  </div>
</div>
""", unsafe_allow_html=True)
