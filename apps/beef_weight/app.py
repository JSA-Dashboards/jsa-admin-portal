import sys
import os
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
import re
from datetime import datetime
from urllib.parse import quote

# st.Page runs this file via exec(), not as a standalone script, so its own
# directory is never added to sys.path automatically -- without this, the
# local nass_cache_client import below raises ModuleNotFoundError.
# `wasde` is SHARED and lives at the repo root -- the convention
# apps/weekly_reports/app.py uses to reach `letter`. It exists ONCE in this
# repo and must stay that way: Python caches modules by NAME, so a copy
# beside this page would mean whichever page loaded first decided which one
# every other page got. US Beef Trade and Cash Cattle Trade import the same
# file.
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).parent))

import daily_slaughter
import wasde  # noqa: E402

# ── JSA Brand Colors ───────────────────────────────────────────────────────────
# Extracted from jpsi.com logo: sage green #5e7164, charcoal #333132
JSA_GREEN    = "#5e7164"   # exact logo monogram green
JSA_GREEN_LT = "#8db89a"   # lightened for dark-bg readability
JSA_CHARCOAL = "#333132"   # logo text color

DM_BG       = "#f6f8f7"    # light, faint green tint
DM_SURFACE  = "#ffffff"    # card / sidebar surface
DM_SURFACE2 = "#eef3f0"    # chart background
DM_BORDER   = "#d7e2dc"    # borders — JSA green tint
DM_TEXT     = "#32373c"    # primary text — JPSI charcoal
DM_MUTED    = "#5f7267"    # muted text — sage
COL_POS     = "#16a34a"    # positive delta — green
COL_NEG     = "#dc2626"    # negative delta — red
COL_NEU     = "#5f7267"

JPSI_GREEN  = JSA_GREEN_LT  # alias used throughout

JSA_LOGO_FULL  = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"
JSA_LOGO_WHITE = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"


CLASS_COLORS = {
    "STEERS":     "#8db89a",   # JSA light green
    "HEIFERS":    "#6fa8c4",   # steel blue
    "COWS":       "#c98a56",   # warm amber
    "BULLS":      "#9b89c4",   # muted purple
    "CALVES":     "#c4b456",   # muted gold
    "GE 500 LBS": "#c8d4ca",   # light sage — headline class
}
CLASS_ORDER = ["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS", "CALVES"]
CLASS_DISPLAY = {
    "GE 500 LBS": "Actual Carcass Weights",
    "STEERS":     "Steers",
    "HEIFERS":    "Heifers",
    "COWS":       "Cows",
    "BULLS":      "Bulls",
    "CALVES":     "Calves",
}
VOL_DISPLAY = {**CLASS_DISPLAY, "GE 500 LBS": "All Cattle"}
FILTER_DISPLAY = {**CLASS_DISPLAY, "GE 500 LBS": "All Cattle"}

def _fmt_cls(c: str) -> str:
    return FILTER_DISPLAY.get(c, c.title())

from nass_cache_client import fetch_cached

# st.set_page_config removed — the JSA Admin Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{
    background-color:{DM_BG}; color:{DM_TEXT};
  }}
  [data-testid="stSidebar"] {{
    background-color:{DM_SURFACE}; border-right:1px solid {DM_BORDER};
  }}
  [data-testid="stSidebar"] * {{ color:{DM_TEXT} !important; }}

  /* ── Snapshot card ── */
  .snap-card {{
    background:{DM_SURFACE}; border:1px solid {DM_BORDER};
    border-top:2px solid {JSA_GREEN}; border-radius:10px;
    padding:18px 16px 14px; height:100%;
  }}
  .snap-class {{
    color:{DM_MUTED}; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:.08em; margin-bottom:6px;
  }}
  .snap-value {{
    color:{DM_TEXT}; font-size:2rem; font-weight:700; line-height:1.1;
    margin-bottom:10px;
  }}
  .snap-grid {{
    display:grid; grid-template-columns:1fr 1fr; gap:6px 10px;
  }}
  .snap-item {{ display:flex; flex-direction:column; }}
  .snap-lbl {{
    color:{DM_MUTED}; font-size:0.65rem; text-transform:uppercase;
    letter-spacing:.06em;
  }}
  .snap-pos {{ color:{COL_POS}; font-size:0.88rem; font-weight:600; }}
  .snap-neg {{ color:{COL_NEG}; font-size:0.88rem; font-weight:600; }}
  .snap-neu {{ color:{COL_NEU}; font-size:0.88rem; }}

  /* ── Summary table ── */
  .sum-table {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .sum-table th {{
    color:{DM_MUTED}; font-weight:500; text-transform:uppercase;
    font-size:0.68rem; letter-spacing:.06em; padding:6px 10px;
    border-bottom:1px solid {DM_BORDER}; text-align:right;
  }}
  .sum-table th:first-child {{ text-align:left; }}
  .sum-table td {{
    padding:7px 10px; border-bottom:1px solid {DM_BORDER};
    text-align:right; color:{DM_TEXT};
  }}
  .sum-table td:first-child {{ text-align:left; font-weight:600; }}
  .sum-table tr:last-child td {{ border-bottom:none; }}
  .pos {{ color:{COL_POS}; }} .neg {{ color:{COL_NEG}; }}

  /* ── Top-level page tabs ── */
  .stTabs [data-baseweb="tab-list"] {{
    background:{DM_SURFACE};
    border-radius:10px;
    padding:6px 8px;
    gap:6px;
    border:1px solid {DM_BORDER};
  }}
  .stTabs [data-baseweb="tab"] {{
    color:{DM_MUTED};
    font-size:1rem;
    font-weight:600;
    letter-spacing:.02em;
    padding:10px 28px;
    border-radius:7px;
    border-bottom:none !important;
    transition:background .15s, color .15s;
  }}
  .stTabs [data-baseweb="tab"]:hover {{
    background:{DM_SURFACE2};
    color:{DM_TEXT};
  }}
  .stTabs [aria-selected="true"] {{
    color:#fff !important;
    background:{JSA_GREEN} !important;
  }}
  /* hide the default underline indicator */
  .stTabs [data-baseweb="tab-highlight"] {{ display:none !important; }}
  .stTabs [data-baseweb="tab-border"]    {{ display:none !important; }}
  .sec-hdr {{
    color:{DM_MUTED}; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:.1em; margin:14px 0 6px;
  }}
  div[data-testid="stDataFrame"] {{ background:{DM_SURFACE}; border-radius:8px; }}

  .sat-call {{
    background:{DM_SURFACE}; border:1px solid {DM_BORDER};
    border-left:4px solid {JSA_GREEN}; border-radius:8px;
    padding:16px 20px 14px; margin:2px 0 14px;
  }}
  .sat-call-lead {{ color:{DM_TEXT}; font-size:1.05rem; line-height:1.5; }}
  .sat-call-sub  {{ color:{DM_MUTED}; font-size:0.82rem; margin-top:8px; line-height:1.55; }}
  .sat-table {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .sat-table th {{
    text-align:left; color:{DM_MUTED}; font-weight:600; font-size:0.7rem;
    text-transform:uppercase; letter-spacing:.06em;
    padding:6px 10px; border-bottom:1px solid {DM_BORDER};
  }}
  .sat-table td {{ padding:6px 10px; border-bottom:1px solid {DM_BORDER}; color:{DM_TEXT}; }}
  .sat-table td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
</style>
""", unsafe_allow_html=True)


# ── Data fetching ──────────────────────────────────────────────────────────────

def _nass_get(params: dict) -> dict:
    # Reads the shared NASS cache (see usda-nass-etl) instead of calling
    # NASS live -- this app no longer holds a NASS API key.
    try:
        return fetch_cached(params)
    except Exception as e:
        st.error(f"NASS cache error: {e}")
        return {}




AMS_URL = "https://www.ams.usda.gov/mnreports/sj_ls712.txt"

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_ams_raw() -> dict:
    """Lightweight AMS fetch used for sidebar/header dates — reused by full render."""
    try:
        r = requests.get(AMS_URL, timeout=20)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        return {"error": str(e)}

    def _num(s):
        try: return float(str(s).replace(",","").replace("%","").strip())
        except: return float("nan")
    def _pd(s):
        s = s.strip()
        for fmt in ("%d-%b-%y", "%d-%b-%Y"):
            try: return datetime.strptime(s, fmt).date()
            except ValueError: pass
        return None

    res = {}
    m = re.search(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+\s+\d+,\s+\d{4})", text)
    if m:
        try: res["report_date"] = datetime.strptime(m.group(2).strip(), "%b %d, %Y").date()
        except: res["report_date"] = None

    slaughter = {}
    m = re.search(r"Livestock Slaughter \(head\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            parts = line.strip().split()
            if not parts: continue
            d = _pd(parts[0])
            if d and len(parts) >= 5:
                slaughter[d] = dict(zip(["Cattle","Calves","Hogs","Sheep"],[_num(p) for p in parts[1:5]]))
            elif len(parts) >= 6 and parts[1] == "YTD":
                slaughter[f"YTD_{parts[0]}"] = dict(zip(["Cattle","Calves","Hogs","Sheep"],[_num(p) for p in parts[2:6]]))
    res["slaughter"] = slaughter

    weights = {"live": {}, "dressed": {}}
    m = re.search(r"Average Weights \(lbs\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        mode = None
        for line in m.group(1).splitlines():
            line = line.strip()
            if not line: continue
            if re.search(r"Live:", line, re.IGNORECASE): mode = "live"
            elif re.search(r"Dressed:", line, re.IGNORECASE): mode = "dressed"
            if mode is None: continue
            parts = line.split()
            d = _pd(parts[0]) if parts else None
            if d:
                nums = []
                for p in parts[1:]:
                    try: nums.append(float(p.replace(",","")))
                    except: pass
                if len(nums) >= 4:
                    weights[mode][d] = {"Cattle":nums[0],"Calves":nums[1],"Hogs":nums[2],"Sheep":nums[3]}
    res["weights"] = weights

    class_mix = {}
    m = re.search(r"Percentage of Total Cattle Slaughtered by Class(.*?)(?:----|\Z)", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            parts = line.strip().split()
            d = _pd(parts[0]) if parts else None
            if d and len(parts) >= 5:
                class_mix[d] = dict(zip(["Steers","Heifers","Cows","Bulls"],[_num(p) for p in parts[1:5]]))
    res["class_mix"] = class_mix

    meat_prod = {}
    m = re.search(r"Meat Production \(millions of pounds\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            parts = line.strip().split()
            if not parts: continue
            d = _pd(parts[0])
            if d and len(parts) >= 5:
                vals = [_num(p) for p in parts[1:6]]
                meat_prod[d] = {"Beef":vals[0],"Calf/Veal":vals[1],"Pork":vals[2],"Lamb":vals[3],"Total":vals[4]}
            elif len(parts) >= 7 and parts[1] == "YTD":
                # e.g. "2026 YTD  7735.4  6.9  8950.0  37.9  16730.2"
                meat_prod[f"YTD_{parts[0]}"] = {"Beef":_num(parts[2]),"Calf/Veal":_num(parts[3]),"Pork":_num(parts[4]),"Lamb":_num(parts[5]),"Total":_num(parts[6])}
    res["meat_prod"] = meat_prod
    return res


# ── USDA AMS MARS — report 3658, Actual Slaughter Under Federal Inspection ────
# Weekly FIS dressed weights by class, published THURSDAY, covering the week
# that ended ~12 days earlier (published 09/17/2026 for w/e 09/05/2026).
# NASS publishes the SAME series, but only inside its MONTHLY Livestock
# Slaughter release -- which is why the NASS weight tiles sit ~3 weeks stale
# between releases. That staleness is the pipeline working, not failing.
# Verified equal to the pound on all 8 overlapping weeks 2026-07-11..2026-08-29
# (NASS GE 500 LBS dressed == AMS class Cattle dressed).
MARS_BASE     = "https://marsapi.ams.usda.gov/services/v1.2/reports"
FIS_REPORT_ID = 3658
# SECTION IS A PATH SEGMENT, NOT A QUERY PARAM. `?section=...` is accepted and
# silently ignored -- you get the report header, zero rows, HTTP 200, no error,
# which looks exactly like a report that publishes nothing.
FIS_SECTION   = "Report FIS Meat Production"
# AMS class -> NASS class_desc. Exact keys only: never endswith/substring, and
# never loosen it -- calves live under commodity "Slaughter Calves" and a fuzzy
# match would pull a different animal into a cattle tile.
FIS_CLASS_MAP = {"Cattle": "GE 500 LBS", "Steers": "STEERS",
                 "Heifers": "HEIFERS", "Cows": "COWS", "Bulls": "BULLS"}
FIS_UNIT_DESC = "LB / HEAD, DRESSED BASIS"   # the NASS spelling, on purpose

try:
    MARS_KEY = st.secrets.get("MARS_API_KEY", "")
except Exception:
    # No secrets.toml locally -- st.secrets raises rather than returning {}.
    MARS_KEY = ""
MARS_KEY = (MARS_KEY or os.environ.get("MARS_API_KEY", "")).strip()


def _mars_date(s):
    """MM/DD/YYYY, sometimes with a trailing clock time, -> datetime.date."""
    if not s:
        return None
    try:
        m, d, y = str(s).split()[0].split("/")   # .split()[0] drops "10:00:01"
        return datetime(int(y), int(m), int(d)).date()
    except Exception:
        return None


def _mars_num(v):
    """AMS sends numbers as strings — `volume` arrives as "973", not 973."""
    if v is None:
        return None
    t = str(v).strip().replace(",", "").replace("$", "")
    if not t or t.upper() in ("NA", "N/A", "NULL", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_fis_weights() -> dict:
    """AMS MARS report 3658 — weekly FIS dressed weights by cattle class."""
    if not MARS_KEY:
        return {"error": "MARS_API_KEY not configured"}
    # No q= date filter on purpose. Guessing a date field name on a report
    # family that has no report_date is the documented way to get zero rows and
    # no error, and the full pull is what gives WoW/YoY/4-week their history.
    try:
        r = requests.get(f"{MARS_BASE}/{FIS_REPORT_ID}/{quote(FIS_SECTION)}",
                         auth=(MARS_KEY, ""), timeout=(5, 120))
        if r.status_code in (204, 404):
            return {"error": f"AMS returned HTTP {r.status_code}"}
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

    rows, bad_unit, published = [], 0, None
    for x in results:
        if str(x.get("commodity", "")).strip()   != "Slaughter Cattle": continue
        if str(x.get("description", "")).strip() != "Dressed Weight":   continue
        cls = FIS_CLASS_MAP.get(str(x.get("class", "")).strip())
        if cls is None:
            continue
        # Unit guard: the tiles say "lb". A silent unit rename is exactly the
        # kind of layout change that has bitten these AMS feeds before, and it
        # would land as a plausible-looking wrong number, not an error.
        if str(x.get("unit", "")).strip().lower() != "lbs":
            bad_unit += 1
            continue
        # 3658 HAS NO report_date FIELD -- only report_begin_date /
        # report_end_date / published_date. Asking for report_date returns None
        # and skips every row with no error. The END date is the week ending.
        wk  = _mars_date(x.get("report_end_date") or x.get("report_begin_date"))
        val = _mars_num(x.get("volume"))
        if wk is None or val is None:
            continue
        rows.append({"year": wk.year, "week_ending": wk.isoformat(),
                     "class_desc": cls, "unit_desc": FIS_UNIT_DESC,
                     "Value": val})
        p = _mars_date(x.get("published_date"))
        if p and (published is None or p > published):
            published = p

    if bad_unit:
        return {"error": f"{bad_unit} rows carried a unit other than 'lbs' "
                         f"— report 3658 layout may have changed"}
    if not rows:
        return {"error": "no Slaughter Cattle / Dressed Weight rows in report 3658"}
    return {"rows": rows, "published": published, "n_results": len(results)}


def _build_df(frames: list) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    keep = ["year", "week_ending", "class_desc", "unit_desc", "Value"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df["Value"]       = pd.to_numeric(
        df["Value"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    df["week_ending"] = pd.to_datetime(df["week_ending"], errors="coerce")
    df["year"]        = df["year"].astype(int)
    df["class_desc"]  = df["class_desc"].str.upper().str.strip()
    df["unit_desc"]   = df["unit_desc"].str.strip()
    df["iso_week"]    = df["week_ending"].dt.isocalendar().week.astype(int)
    return df.dropna(subset=["Value", "week_ending"])


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_data(years: tuple) -> pd.DataFrame:
    frames = []
    for year in years:
        params = {
            "source_desc":       "SURVEY",
            "sector_desc":       "ANIMALS & PRODUCTS",
            "group_desc":        "LIVESTOCK",
            "commodity_desc":    "CATTLE",
            "statisticcat_desc": "SLAUGHTERED",
            "freq_desc":         "WEEKLY",
            "state_alpha":       "US",
            "year":              year,
        }
        payload = _nass_get(params)
        if "data" in payload and payload["data"]:
            frames.append(pd.DataFrame(payload["data"]))
    return _build_df(frames)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_vol_data(years: tuple) -> pd.DataFrame:
    """Separate fetch for head-count slaughter data — may update ahead of weight data."""
    frames = []
    for year in years:
        params = {
            "source_desc":       "SURVEY",
            "sector_desc":       "ANIMALS & PRODUCTS",
            "group_desc":        "LIVESTOCK",
            "commodity_desc":    "CATTLE",
            "statisticcat_desc": "SLAUGHTERED",
            "unit_desc":         "HEAD",
            "freq_desc":         "WEEKLY",
            "state_alpha":       "US",
            "year":              year,
        }
        payload = _nass_get(params)
        if "data" in payload and payload["data"]:
            frames.append(pd.DataFrame(payload["data"]))
    return _build_df(frames)


# ── Analytics helpers ──────────────────────────────────────────────────────────

def _nearest_week(df: pd.DataFrame, year: int, iso_week: int) -> float:
    """Return the value for the closest ISO week in a given year."""
    sub = df[df["year"] == year]
    if sub.empty:
        return float("nan")
    idx = (sub["iso_week"] - iso_week).abs().idxmin()
    return sub.loc[idx, "Value"]


def prior_years_avg(df: pd.DataFrame, ref_year: int, iso_week: int, n: int = 5) -> float:
    """Simple average of the n prior years for the same ISO week."""
    vals = [_nearest_week(df, ref_year - i, iso_week) for i in range(1, n + 1)]
    vals = [v for v in vals if not pd.isna(v)]
    if not vals:
        return float("nan")
    return sum(vals) / len(vals)


def prior_years_series(df: pd.DataFrame, ref_year: int, n: int = 5) -> pd.Series:
    """Plain average of the prior n years, per ISO week, indexed by iso_week."""
    weeks = sorted(df["iso_week"].unique())
    return pd.Series(
        {w: prior_years_avg(df, ref_year, w, n) for w in weeks},
        name="prior_years_avg",
    )


def trailing_4wk(df: pd.DataFrame) -> pd.DataFrame:
    """4-week rolling average per class, sorted by week_ending."""
    return (
        df.sort_values("week_ending")
        .assign(t4w=lambda d: d.groupby("class_desc")["Value"]
                .transform(lambda s: s.rolling(4, min_periods=1).mean()))
    )


def _fis_frame(raw: dict) -> pd.DataFrame:
    """AMS rows -> the exact frame shape NASS produces (schema parity by reuse)."""
    if raw.get("error") or not raw.get("rows"):
        return pd.DataFrame()
    # Routed through _build_df so week_ending is a pandas Timestamp like every
    # other frame here. datetime.date objects would compare unequal to the NASS
    # Timestamps, which would silently produce an empty overlap and duplicate
    # class/week pairs instead of a splice.
    return _build_df([pd.DataFrame(raw["rows"])])


def _ams_nass_agree(nass_df: pd.DataFrame, ams_df: pd.DataFrame,
                    tol: float = 5.0, weeks: int = 26):
    """Prove AMS and NASS are the same measure on the overlap — never assume it.

    This is the number-against-an-independently-derived-number check. On the
    latest common week the two agree to the pound (w/e 2026-08-29 reads
    891/969/877/640/930 from both feeds). If AMS ever redefines the series, or a
    week-ending convention drifts by a day, this refuses the splice rather than
    publishing two different measures under one heading.

    Scoped to the RECENT overlap, and that is the load-bearing part. AMS prints
    a preliminary figure and NASS confirms it weeks later, so individual old
    weeks get revised by a pound or three. Across the full archive -- 990
    class/week pairs back to 2022 -- the worst single gap is 3.0 lb, or 0.34%.
    That is revision noise, not a different measure. The first version of this
    check took a max over every pair ever published against a 2.0 lb tolerance,
    so one historical revision refused the splice permanently and the page went
    on quietly showing the stale NASS week this change exists to replace. A
    check that fails closed forever is no more use than one that cannot fail.
    """
    j = (nass_df[["class_desc", "week_ending", "Value"]]
         .merge(ams_df[["class_desc", "week_ending", "Value"]],
                on=["class_desc", "week_ending"], suffixes=("_nass", "_ams")))
    if j.empty:                      # also catches a week-ending convention drift
        return False, float("nan"), 0
    cutoff = j["week_ending"].max() - pd.Timedelta(weeks=weeks)
    recent = j[j["week_ending"] >= cutoff]
    if recent.empty:                 # archive shorter than the window
        recent = j
    d = (recent["Value_nass"] - recent["Value_ams"]).abs()
    return bool(d.max() <= tol), float(d.max()), int(len(recent))


def _ams_first(nass_df, ams_df, unit_filter, err):
    """Lead with AMS where it is present and provably the same series.

    Returns (frame, source, note, maxdiff, n_overlap). Every failure path
    returns the NASS frame plus a note -- the page degrades to exactly what it
    renders today, with a banner saying why.
    """
    nass_only = nass_df.assign(source="NASS")
    if unit_filter != "DRESSED":
        return (nass_only, "NASS",
                "AMS report 3658 publishes DRESSED weight by class only — "
                "live-basis tiles are NASS, which updates monthly.",
                float("nan"), 0)
    if ams_df.empty:
        return (nass_only, "NASS",
                f"AMS weekly weights unavailable ({err or 'no rows returned'}) — "
                f"showing NASS, which publishes weights only in its MONTHLY "
                f"Livestock Slaughter release.", float("nan"), 0)
    ok, maxdiff, n_ovl = _ams_nass_agree(nass_df, ams_df)
    if not ok:
        why = ("no overlapping weeks" if n_ovl == 0
               else f"they differ by up to {maxdiff:,.1f} lb over {n_ovl} weeks")
        return (nass_only, "NASS",
                f"AMS and NASS dressed weights no longer line up ({why}) — "
                f"refusing to splice, showing NASS only.", maxdiff, n_ovl)
    merged = pd.concat([ams_df.assign(source="AMS"), nass_only],
                       ignore_index=True)
    # AMS is concatenated first, so keep="first" makes AMS win every week it
    # covers and NASS supply everything older.
    merged = merged.drop_duplicates(subset=["class_desc", "week_ending"],
                                    keep="first")
    return trailing_4wk(merged), "AMS", None, maxdiff, n_ovl


def _row_source(df: pd.DataFrame, cls: str, when) -> str:
    """Which feed produced the value a card is about to show."""
    if when is None or df.empty:
        return "—"
    m = df[(df["class_desc"] == cls) & (df["week_ending"] == when)]
    return str(m["source"].iloc[0]) if not m.empty else "—"


def week_kpis(wt: pd.DataFrame, cls: str) -> dict:
    """Compute all snapshot KPIs for one class."""
    nan = dict(current=float("nan"), wow=float("nan"), wow_pct=float("nan"),
               yoy=float("nan"), yoy_pct=float("nan"), t4w=float("nan"),
               prior_avg=float("nan"), vs_prior_avg=float("nan"), vs_prior_avg_pct=float("nan"),
               latest_date=None, latest_year=None, iso_week=None)

    sub = wt[wt["class_desc"] == cls].sort_values("week_ending")
    if sub.empty:
        return nan

    latest_date = sub["week_ending"].max()
    latest_year = int(sub.loc[sub["week_ending"] == latest_date, "year"].iloc[0])
    iso_week    = int(sub.loc[sub["week_ending"] == latest_date, "iso_week"].iloc[0])
    current     = float(sub.loc[sub["week_ending"] == latest_date, "Value"].iloc[0])

    # WoW
    prev_dates = sub[sub["week_ending"] < latest_date]
    if not prev_dates.empty:
        prev_val = float(sub.loc[sub["week_ending"] == prev_dates["week_ending"].max(), "Value"].iloc[0])
        wow = current - prev_val
        wow_pct = wow / prev_val * 100 if prev_val else float("nan")
    else:
        wow = wow_pct = float("nan")

    # YoY — same ISO week, prior year
    ly_val = _nearest_week(sub, latest_year - 1, iso_week)
    yoy = current - ly_val if not pd.isna(ly_val) else float("nan")
    yoy_pct = yoy / ly_val * 100 if (not pd.isna(ly_val) and ly_val) else float("nan")

    # Trailing 4-week avg (including current week)
    recent4 = sub.tail(4)["Value"]
    t4w = float(recent4.mean()) if len(recent4) >= 1 else float("nan")

    # Plain average of the prior 5 years for this ISO week
    prior_val = prior_years_avg(sub, latest_year, iso_week)
    vs_prior_avg = current - prior_val if not pd.isna(prior_val) else float("nan")
    vs_prior_avg_pct = vs_prior_avg / prior_val * 100 if (not pd.isna(prior_val) and prior_val) else float("nan")

    return dict(current=current, wow=wow, wow_pct=wow_pct, yoy=yoy, yoy_pct=yoy_pct,
                t4w=t4w, prior_avg=prior_val, vs_prior_avg=vs_prior_avg, vs_prior_avg_pct=vs_prior_avg_pct,
                latest_date=latest_date, latest_year=latest_year, iso_week=iso_week)


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _dc(val: float, fmt: str = "+.1f", suffix: str = "") -> str:
    """Return a delta value with color class."""
    if pd.isna(val):
        return f'<span class="snap-neu">—</span>'
    cls = "snap-pos" if val >= 0 else "snap-neg"
    sign = "+" if val >= 0 else ""
    return f'<span class="{cls}">{sign}{val:{fmt[1:]}}{suffix}</span>'


def _snap_item(label: str, delta_html: str) -> str:
    return f'<div class="snap-item"><span class="snap-lbl">{label}</span>{delta_html}</div>'


def _snap_card(cls: str, kpi: dict, unit_label: str, src: str = "NASS") -> str:
    val_str = f'{kpi["current"]:,.1f}' if not pd.isna(kpi["current"]) else "—"
    t4w_str = f'{kpi["t4w"]:,.1f}' if not pd.isna(kpi["t4w"]) else "—"
    prior_str = f'{kpi["prior_avg"]:,.1f}' if not pd.isna(kpi["prior_avg"]) else "—"
    color = CLASS_COLORS.get(cls, DM_MUTED)
    # Every card names its own feed and its own week. A mixed row (four AMS
    # tiles, one NASS) has to be self-describing -- a tile quietly holding last
    # month's number under an AMS heading is the failure this change exists to
    # fix, so it must never be possible to read one without its provenance.
    wk_s    = kpi["latest_date"].strftime("%b %d, %Y") if kpi["latest_date"] is not None else "—"
    src_col = "#6fa8c4" if src == "AMS" else JSA_GREEN_LT
    src_txt = "AMS FIS weekly" if src == "AMS" else ("NASS monthly" if src == "NASS" else "no data")
    return f"""
    <div class="snap-card">
      <div class="snap-class" style="color:{color}">{CLASS_DISPLAY.get(cls, cls.title())}</div>
      <div class="snap-value">{val_str} <span style="font-size:0.9rem;color:{DM_MUTED}">lb</span></div>
      <div class="snap-grid">
        {_snap_item("WoW", _dc(kpi['wow'], '+.1f', ' lb') + ' ' + _dc(kpi['wow_pct'], '+.1f', '%'))}
        {_snap_item("YoY", _dc(kpi['yoy'], '+.1f', ' lb') + ' ' + _dc(kpi['yoy_pct'], '+.1f', '%'))}
        {_snap_item("4-Wk Avg", f'<span class="snap-neu">{t4w_str} lb</span>')}
        {_snap_item("vs 5yr Avg", _dc(kpi['vs_prior_avg'], '+.1f', ' lb') + ' ' + _dc(kpi['vs_prior_avg_pct'], '+.1f', '%'))}
      </div>
      <div style="margin-top:8px;font-size:0.7rem;color:{DM_MUTED}">
        5yr avg: {prior_str} lb &nbsp;·&nbsp; {unit_label}
      </div>
      <div style="margin-top:3px;font-size:0.68rem;color:{src_col};font-weight:600">
        {src_txt} &nbsp;·&nbsp; w/e {wk_s}
      </div>
    </div>"""


# ── Chart helpers ──────────────────────────────────────────────────────────────

AXIS_STYLE = dict(gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True)


def _base_layout(title: str = "", height: int = 420, y_title: str = "") -> dict:
    return dict(
        title=dict(text=title, font=dict(color=DM_TEXT, size=13), x=0),
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0, font=dict(size=11)),
        margin=dict(l=50, r=20, t=40, b=40),
        hovermode="x unified", height=height,
    )


def _apply(fig, title="", height=420, y_title="", y_range=None):
    fig.update_layout(**_base_layout(title, height, y_title))
    fig.update_xaxes(**AXIS_STYLE)
    if y_range:
        fig.update_yaxes(**AXIS_STYLE, title_text=y_title, range=y_range)
    else:
        fig.update_yaxes(**AXIS_STYLE, title_text=y_title, autorange=True)


def _tight_range(series, pad_pct=0.04):
    """Return [min, max] with a small padding for a tight Y axis."""
    vals = [v for v in series if v is not None and not pd.isna(v)]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * pad_pct if hi != lo else hi * pad_pct
    return [lo - pad, hi + pad]


def _to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    return buf.getvalue()


# ── Saturday slaughter view ────────────────────────────────────────────────────
# Data and arithmetic live in daily_slaughter.py; the layout is here next to the
# brand helpers it needs. Same split as cof_recap and cold_storage on the Cattle
# on Feed page.

@st.cache_data(ttl=3600, show_spinner=False)
def _sat_load() -> dict:
    return daily_slaughter.fetch(MARS_KEY)


def render_saturday_slaughter() -> None:
    with st.spinner("Loading USDA AMS daily slaughter…"):
        raw = _sat_load()

    # Header banner, in the compact in-tab style the AMS Weekly tab uses --
    # the page already has its logo masthead above the tab strip, so repeating
    # it here would print the letterhead twice.
    _pub = raw["published"].strftime("%b %d, %Y") if raw.get("published") else "N/A"
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
      background:{DM_SURFACE2};border:1px solid {DM_BORDER};
      border-left:4px solid {JSA_GREEN};border-radius:6px;padding:14px 20px;margin-bottom:18px">
      <div>
        <div style="color:{DM_TEXT};font-size:1.1rem;font-weight:700">
          Saturday Slaughter — Daily Estimates
        </div>
        <div style="color:{DM_MUTED};font-size:0.78rem;margin-top:3px">
          USDA Agricultural Marketing Service · report 3208 · Federally Inspected ·
          the only JSA source with a day-of-week breakdown
        </div>
      </div>
      <div style="text-align:right">
        <div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;letter-spacing:.06em">AMS 3208 Published</div>
        <div style="color:{JSA_GREEN_LT};font-size:1.15rem;font-weight:700">{_pub}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if raw.get("error"):
        st.error(
            f"AMS daily slaughter unavailable — {raw['error']}. This view reads "
            f"MARS report 3208 and needs MARS_API_KEY, the same secret the "
            f"carcass-weight tiles use. The published report is at "
            f"{daily_slaughter.REPORT_PDF}"
        )
        return

    df   = daily_slaughter.daily_frame(raw)
    sats = daily_slaughter.saturday_frame(df)
    if sats.empty:
        st.warning("No complete Saturday weeks in report 3208.")
        return

    # ── Controls, in the tab body rather than the sidebar ─────────────────────
    # This renderer runs on every page load now that it is a tab (a hidden tab
    # is hidden, not skipped), so a st.sidebar widget here would sit in the
    # weights sidebar permanently, whichever tab the reader was actually on.
    yrs = sorted({d.year for d in sats["day"]})
    pick = st.multiselect("Years", yrs, default=yrs, key="sat_years")
    if not pick:
        pick = yrs
    st.caption(
        f"MARS keeps this slug back to {daily_slaughter.FIRST_YEAR} and no "
        f'further, so "the last time" is always read against that window. '
        f"The newest Saturday is a projection until the next business day "
        f"restates it, and Saturdays revise up far more often than down."
    )

    shown = sats[sats["day"].map(lambda d: d.year in pick)]

    # ── Headline: the newest Saturday, and the last one that matched it ───────
    latest = sats.iloc[-1]
    prior  = daily_slaughter.at_or_above(sats, int(latest["head"]), before=latest["day"])
    when   = "Tomorrow" if latest["is_projection"] else "Latest Saturday"

    if prior.empty:
        answer = (f"No Saturday since {daily_slaughter.FIRST_YEAR} has matched it.")
    else:
        p = prior.iloc[-1]
        gap = (latest["day"] - p["day"]).days // 7
        answer = (f"Last matched on <b>{p['day'].strftime('%b %d, %Y')}</b> at "
                  f"<b>{int(p['head']):,}</b> head — {gap} weeks ago, and "
                  + ("that was a holiday week." if p["lost_day"] else "that was a full week."))

    note = ("This is a full Mon–Fri week, so the Saturday is additive rather "
            "than a holiday make-up — which is what makes it unusual."
            if not latest["lost_day"] else
            f"This week gave up a weekday ({int(latest['week_low']):,} head on its "
            f"weakest), so the Saturday is buying back a lost day rather than "
            f"adding one.")

    st.markdown(
        f'<div class="sat-call">'
        f'<div class="sat-call-lead">{when} — <b>{latest["day"].strftime("%A, %b %d, %Y")}</b>: '
        f'<b>{int(latest["head"]):,} head</b>'
        + ('  <span style="color:#b07d2b">(projection)</span>' if latest["is_projection"] else '')
        + f'. {answer}</div>'
        f'<div class="sat-call-sub">Week to date {int(latest["week_total"]):,} head · '
        f'Saturday is {latest["sat_share"]*100:.1f}% of the week. {note}</div>'
        f'</div>', unsafe_allow_html=True)

    # ── Chart ──────────────────────────────────────────────────────────────────
    # Holiday weeks are coloured apart rather than filtered out: they are most
    # of the big Saturdays, and hiding them would make the series look like it
    # trends when it mostly just reflects the calendar.
    fig = go.Figure()
    for flag, name, colour in ((False, "Full week", JSA_GREEN),
                               (True,  "Holiday / short week", "#b07d2b")):
        sub = shown[shown["lost_day"] == flag]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub["day"], y=sub["head"], name=name,
            marker_color=colour,
            customdata=sub[["week_total", "week_low"]],
            hovertemplate=("%{x|%b %-d, %Y}<br>%{y:,.0f} head"
                           "<br>week %{customdata[0]:,.0f}"
                           "<br>weakest weekday %{customdata[1]:,.0f}<extra></extra>"),
        ))
    _apply(fig, "Saturday Cattle Slaughter — Head", 430, "Head")
    fig.update_layout(barmode="overlay", legend=dict(orientation="h", y=1.02, x=0))
    st.plotly_chart(fig, use_container_width=True)

    # ── Biggest Saturdays, with the week each sat in ───────────────────────────
    st.markdown('<div class="sec-hdr">Biggest Saturdays on file</div>', unsafe_allow_html=True)
    top = shown.sort_values("head", ascending=False).head(15)
    rows_html = "".join(
        f'<tr><td>{r.day.strftime("%a %b %d, %Y")}</td>'
        f'<td class="num">{int(r.head):,}</td>'
        f'<td class="num">{int(r.week_total):,}</td>'
        f'<td class="num">{r.sat_share*100:.1f}%</td>'
        f'<td>{daily_slaughter.context_line(r._asdict())}</td></tr>'
        for r in top.itertuples()
    )
    st.markdown(
        f'<table class="sat-table"><thead><tr>'
        f'<th>Saturday</th><th style="text-align:right">Head</th>'
        f'<th style="text-align:right">Week total</th>'
        f'<th style="text-align:right">Sat share</th><th>Context</th>'
        f'</tr></thead><tbody>{rows_html}</tbody></table>',
        unsafe_allow_html=True)

    # ── Audit + provenance ─────────────────────────────────────────────────────
    bad = daily_slaughter.reconcile(df, raw)
    if bad:
        st.warning(
            f"{len(bad)} week(s) do not sum to the report's own week-to-date — "
            f"first: week of {bad[0][0]}, Mon–Sat {bad[0][1]:,} vs AMS {bad[0][2]:,}. "
            f"Treat those weeks as suspect."
        )

    st.caption(
        f"USDA AMS report 3208, *Daily Livestock and Poultry Slaughter* "
        f"([report]({daily_slaughter.REPORT_PDF}) · "
        f"[viewer]({daily_slaughter.REPORT_VIEW})), read through MARS. "
        f"Estimated federally inspected head, {daily_slaughter.FIRST_YEAR}–present — "
        f"that is the whole history MARS retains for this slug. "
        f"{len(sats)} complete weeks, all of which reconcile to the report's own "
        f"week-to-date. Cached 1 hr."
    )

    st.download_button(
        "Download Saturday series (Excel)",
        _to_excel(shown.assign(day=shown["day"].astype(str))),
        file_name="saturday_slaughter.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Sidebar ────────────────────────────────────────────────────────────────────

st.sidebar.markdown(
    f'<div style="padding:10px 0 6px">'
    f'<img src="{JSA_LOGO_WHITE}" style="width:160px;opacity:0.92" /></div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<div style="background:{JSA_GREEN};border-radius:4px;padding:5px 10px;'
    f'font-size:.7rem;color:#fff;font-weight:600;letter-spacing:.08em;'
    f'text-transform:uppercase;margin-bottom:10px">Cattle Weights Dashboard</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<span style="color:{DM_MUTED};font-size:.72rem">USDA NASS · Federally Inspected</span>',
    unsafe_allow_html=True,
)
st.sidebar.divider()

current_year = datetime.now().year
# Always load enough history for the 5-yr average + trend charts
LOAD_YEARS = tuple(range(current_year - 7, current_year + 1))

weight_unit = st.sidebar.radio("Weight basis", ["Dressed Weight", "Live Weight"])
unit_filter = "DRESSED" if weight_unit == "Dressed Weight" else "LIVE"
unit_label  = "dressed basis" if unit_filter == "DRESSED" else "live basis"

st.sidebar.divider()
st.sidebar.markdown(f'<span style="color:{DM_MUTED};font-size:.72rem;text-transform:uppercase;letter-spacing:.06em">Classes — Snapshot</span>',
                    unsafe_allow_html=True)
snap_classes = st.sidebar.multiselect(
    "Snapshot classes", CLASS_ORDER,
    default=["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS"],
    format_func=_fmt_cls,
    label_visibility="collapsed",
)
if not snap_classes:
    snap_classes = ["GE 500 LBS"]

st.sidebar.divider()
trend_weeks = st.sidebar.slider("Trend window (weeks)", 8, 52, 26)
trend_class = st.sidebar.selectbox("Trend class", CLASS_ORDER, format_func=_fmt_cls)


# ── Load data ──────────────────────────────────────────────────────────────────

# DEFINED HERE, ABOVE THE NASS GUARD THAT CALLS IT, and that placement is
# load-bearing. It was originally next to _render_beef_production, far below;
# the outage branch a few lines down then raised
# `NameError: name '_render_wasde_production' is not defined` the moment NASS
# was unavailable. py_compile passed and all 1,103 tests passed -- only
# loading the page with no Snowflake credentials showed it. Same lesson as
# AXIS in apps/beef_cutout/app.py.
# ── USDA WASDE beef production forecast ─────────────────────────────────────
#
# WHAT THIS PAGE MEASURES, FORECAST A YEAR AHEAD. The tiles above are weekly
# slaughter and carcass weight, and those two multiply into production --
# the one cattle quantity WASDE publishes. So the panel says what USDA
# thinks this page's own arithmetic comes to for the year.
#
# IT IS COMMERCIAL PRODUCTION AND THE WEEKLY TILES ARE FEDERALLY INSPECTED.
# Not the same series: commercial adds state-inspected and custom plants on
# top of FI, and WASDE's OTHER table (meats supply and use, page 32) adds
# farm slaughter on top of that again -- 24,877 against 24,945 for 2026, a
# 68 million lb gap identical in both years on file.
#
# SO THERE IS DELIBERATELY NO YEAR-TO-DATE PACE HERE, unlike the US Beef
# Trade page, where ERS and WASDE are provably the same series. Dividing an
# FI year-to-date by a commercial forecast would print a percentage that
# looks like progress and measures a definitional gap, and nothing would
# raise. tests/test_beef_trade.py pins the 68.


@st.cache_data(ttl=21600, persist="disk", show_spinner=False)
def _fetch_wasde_beef(schema: int = wasde.SCHEMA) -> dict:
    """Shared arithmetic -- see wasde.summary.

    `schema` keys the cache, and BOTH halves matter: no leading underscore (Streamlit drops underscore-prefixed arguments from the key) and the CALLER must pass it (a default is never hashed).
    """
    return wasde.summary(wasde.load_quarterly_production(), "beef")


def _wasde_delta(value, percent, suffix, digits=0, base=None, base_label=""):
    # THE LEVEL THE MOVE IS MEASURED FROM, printed under it. A tile reading
    # "▼ 90 · 0.4% vs last month" over 24,877 does not say what USDA forecast
    # last month -- the reader subtracts to find 24,967, which is the whole
    # of Ross's complaint about the beef cutout tiles on 2026-10-07 and the
    # Cash Cattle Trade WASDE tiles the day after. Same defect, same fix.
    #
    # IT GOES HERE AND NOT IN `sub` BECAUSE sub ALREADY CARRIES THE UNIT, and
    # on this page the unit is load-bearing: WASDE is COMMERCIAL production
    # while the weekly tiles above are FEDERALLY INSPECTED, and the word is
    # what stops a reader setting one against the other. The year-on-year
    # tile is the one place sub was spent on a level instead, which is why
    # that tile was never part of this defect and is left alone.
    _b = ""
    if base is not None:
        _b = ('<div style="color:%s;font-size:0.72rem;margin-top:3px">'
              '%s %s</div>' % (DM_MUTED, base_label, format(base, ",.%df" % digits)))
    if value is None and percent is None:
        return ('<div style="color:%s;font-size:0.8rem">&mdash;</div>'
                % DM_MUTED) + _b
    if value == 0 or (value is None and percent == 0):
        return ('<div style="color:%s;font-size:0.8rem">unchanged%s</div>'
                % (DM_MUTED, suffix)) + _b
    ref = value if value is not None else percent
    arrow = "▲" if ref > 0 else "▼"
    bits = []
    if value is not None:
        bits.append(format(abs(value), ",.%df" % digits))
    if percent is not None:
        bits.append(format(abs(percent), ",.1f") + "%")
    # NO PARENTHESES: in USDA's own reports they mean negative.
    return ('<div style="color:%s;font-size:0.8rem;font-weight:600;'
            'margin-top:4px">%s %s%s</div>'
            % (DM_MUTED, arrow, " · ".join(bits), suffix)) + _b


def _wasde_tile(label, value, delta="", sub=""):
    sub_html = ""
    if sub:
        sub_html = ('<div style="color:%s;font-size:0.7rem;margin-top:5px">'
                    '%s</div>' % (DM_MUTED, sub))
    return ('<div style="background:%s;border:1px solid %s;'
            'border-top:3px solid #c4b456;border-radius:10px;'
            'padding:16px 20px;text-align:center;height:100%%">'
            '<div style="color:%s;font-size:0.68rem;text-transform:uppercase;'
            'letter-spacing:0.09em;margin-bottom:6px">%s</div>'
            '<div style="color:%s;font-size:1.5rem;font-weight:700;'
            'line-height:1.1">%s</div>%s%s</div>'
            % (DM_SURFACE, DM_BORDER, DM_MUTED, label, DM_TEXT, value,
               delta, sub_html))


def _render_wasde_production():
    try:
        w = _fetch_wasde_beef(wasde.SCHEMA)
    except Exception as exc:  # noqa: BLE001
        st.caption("WASDE beef production forecast unavailable — %s" % exc)
        return
    if not w or w.get("value") is None:
        return

    year = w["year"]
    dash = "—"

    st.markdown('<div class="sec-hdr">USDA WASDE expectation — beef '
                'production</div>', unsafe_allow_html=True)
    st.caption(
        "USDA's projection of total US **commercial** beef production for "
        "the **%d calendar year**, updated every WASDE. Report: **%s**. "
        "Commercial is federally inspected plus state-inspected and custom "
        "plants, so it runs above the federally-inspected weekly figures on "
        "this page — the two are not the same series and should not be "
        "set against each other." % (year, w["report_month"]))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(_wasde_tile(
            "USDA %d production forecast" % year,
            format(w["value"], ",.0f"),
            _wasde_delta(w["revision"], w["revision_pct"], " vs last month",
                         base=w["prior"], base_label="last month"),
            "calendar year · million lb, commercial"),
            unsafe_allow_html=True)
    with c2:
        st.markdown(_wasde_tile(
            "USDA %d forecast vs %d" % (year, w["base_year"]),
            (format(w["yoy_pct"], "+,.1f") + "%"
             if w["yoy_pct"] is not None else dash),
            _wasde_delta(w["yoy_abs"], None, " million lb"),
            ("%d actual %s" % (w["base_year"], format(w["base"], ",.0f"))
             if w["base"] else "million lb, commercial")),
            unsafe_allow_html=True)
    with c3:
        qs = [q for q in w["quarters"] if q["value"] is not None]
        left = [q for q in qs if q["projected"]]
        st.markdown(_wasde_tile(
            "%d quarters still forecast" % year,
            ("%d of %d" % (len(left), len(qs))) if qs else dash,
            ('<div style="color:%s;font-size:0.8rem;margin-top:4px">%s to '
             'come</div>' % (DM_MUTED,
                             ", ".join(q["period"] for q in left) or "none"))
            if qs else ""), unsafe_allow_html=True)
    with c4:
        nxt_pct, nxt_prior = None, None
        if w["next_revision"] is not None and w["next_value"] is not None:
            nxt_prior = w["next_value"] - w["next_revision"]
            nxt_pct = ((w["next_revision"] / nxt_prior * 100.0)
                       if nxt_prior else None)
        st.markdown(_wasde_tile(
            "USDA %d production forecast" % w["next_year"],
            (format(w["next_value"], ",.0f")
             if w["next_value"] is not None else dash),
            _wasde_delta(w["next_revision"], nxt_pct, " vs last month",
                         base=nxt_prior, base_label="last month"),
            "million lb, commercial"), unsafe_allow_html=True)

    qs = [q for q in w["quarters"] if q["value"] is not None]
    if qs:
        st.markdown('<div class="sec-hdr" style="margin-top:12px">By '
                    'quarter</div>', unsafe_allow_html=True)
        cols = st.columns(len(qs))
        for col, q in zip(cols, qs):
            with col:
                name = ("Q%d" % q["number"]) if q["number"] else q["period"]
                state = "proj" if q["projected"] else "actual"
                st.markdown(_wasde_tile(
                    "%s %d · %s" % (name, year, state),
                    format(q["value"], ",.0f"), "", "million lb"),
                    unsafe_allow_html=True)

    audit = w["audit"]
    if audit.get("ok") is False:
        st.caption(
            "⚠️ WASDE's annual figure (%s) no longer equals the %s "
            "of its four quarters (%s). The table layout has probably "
            "changed and these figures should not be relied on until that is "
            "checked." % (format(audit["annual"], ",.0f"), audit["how"],
                          format(audit["expected"], ",.0f")))


with st.spinner("Loading USDA NASS data…"):
    raw     = fetch_data(LOAD_YEARS)
    raw_vol = fetch_vol_data(LOAD_YEARS)

if raw.empty:
    st.error("No data returned from the shared NASS cache (usda-nass-etl). "
             "Weight history and 5-yr averages are unavailable.")
    # Saturday Slaughter reads USDA AMS report 3208 and touches neither NASS
    # nor the cache, so it is still good. Rendering it here, before the guard
    # stops the rest of the page, is what keeps a NASS outage from taking down
    # a view that has no NASS in it -- the property the old top-level switch
    # had by sitting above this line.
    # Same argument for the WASDE forecast: it comes from ESMIS and touches
    # neither NASS nor the cache, so a NASS outage must not take it down. It
    # normally lives inside the Beef Production tab, which sits BELOW this
    # guard -- caught while rendering the page locally with no Snowflake
    # credentials, which is exactly the outage this block exists for. Without
    # these two lines the panel's own comment ("an AMS outage must not take
    # the forecast down with it") was true inside the tab and false about the
    # page.
    _sat, _wasde_tab = st.tabs(["📅  Saturday Slaughter",
                                "🥩  USDA WASDE forecast"])
    with _sat:
        render_saturday_slaughter()
    with _wasde_tab:
        _render_wasde_production()
    st.stop()

wt  = raw[raw["unit_desc"].str.contains(unit_filter, case=False, na=False)].copy()
# Use dedicated volume fetch; fall back to weight dataset if empty
vol = raw_vol if not raw_vol.empty else raw[raw["unit_desc"].str.upper() == "HEAD"].copy()
wt  = trailing_4wk(wt)

# ── AMS FIS weekly weights, spliced over NASS for the tiles only ─────────────
# `wt` stays pure NASS below this point: every chart, the 5-yr seasonal, the
# YoY overlays, all head counts, beef production and the Data tab read it and
# their provenance labels stay honest. Only `wt_tiles` leads with AMS.
with st.spinner("Loading USDA AMS weekly carcass weights…"):
    _fis_raw = _fetch_fis_weights()
_fis_df  = _fis_frame(_fis_raw)
_fis_err = _fis_raw.get("error")
_fis_pub = _fis_raw.get("published")

wt_tiles, _tile_src, _tile_note, _agree_max, _agree_n = _ams_first(
    wt, _fis_df, unit_filter, _fis_err)

_ams_rows = wt_tiles[wt_tiles["source"] == "AMS"] if "source" in wt_tiles else wt_tiles.iloc[0:0]
_fis_wk_date = _ams_rows["week_ending"].max() if not _ams_rows.empty else None
# Every mapped class must be present in the newest AMS week. A class that goes
# missing falls back to NASS and its own card says so -- it must never sit
# there holding last month's number under an AMS heading.
_fis_missing = []
if _fis_wk_date is not None:
    _have = set(_ams_rows.loc[_ams_rows["week_ending"] == _fis_wk_date, "class_desc"])
    _fis_missing = [c for c in FIS_CLASS_MAP.values() if c not in _have]

# Freshness. Report 3658 publishes on a Thursday covering the week that ended
# about twelve days earlier, so the newest AMS week is normally 12-19 days old.
# A fetch SUCCEEDING is not evidence the data moved: against a frozen report it
# returns 200 with the same rows forever, and the tiles would sit under a
# confident "USDA AMS" heading looking current. SJ_LS711 froze in exactly this
# way and stayed frozen for years. Past four weeks, say so out loud.
FIS_MAX_AGE_DAYS = 28
_fis_age_days = ((datetime.now().date() - _fis_wk_date.date()).days
                 if _fis_wk_date is not None else None)
_fis_stale = _fis_age_days is not None and _fis_age_days > FIS_MAX_AGE_DAYS

latest_date = wt["week_ending"].max()
latest_year = int(wt.loc[wt["week_ending"] == latest_date, "year"].iloc[0])
latest_iso  = int(wt.loc[wt["week_ending"] == latest_date, "iso_week"].iloc[0])

vol_latest_date = vol["week_ending"].max() if not vol.empty else None

# ── Compute weekly beef production from NASS (head × dressed wt / 1M lbs) ─────
# Always uses dressed basis regardless of sidebar toggle — production is dressed
_wt_dressed = raw[raw["unit_desc"].str.contains("DRESSED", case=False, na=False)]
_vol_ge500  = (vol[vol["class_desc"] == "GE 500 LBS"]
               [["year","iso_week","week_ending","Value"]]
               .rename(columns={"Value":"head_count"}))
_wt_ge500   = (_wt_dressed[_wt_dressed["class_desc"] == "GE 500 LBS"]
               [["year","iso_week","Value"]]
               .rename(columns={"Value":"dressed_wt"}))
beef_prod_nass = _vol_ge500.merge(_wt_ge500, on=["year","iso_week"], how="inner").copy()
beef_prod_nass["prod_mlbs"]    = beef_prod_nass["head_count"] * beef_prod_nass["dressed_wt"] / 1_000_000
beef_prod_nass["day_of_year"]  = beef_prod_nass["week_ending"].dt.dayofyear

with st.spinner("Loading USDA AMS data…"):
    _ams_meta = _fetch_ams_raw()
_ams_rpt_date   = _ams_meta.get("report_date")
_ams_slaughter  = _ams_meta.get("slaughter", {})
_ams_dated_keys = sorted([k for k in _ams_slaughter if not isinstance(k, str)], reverse=True)
_ams_wk_date    = _ams_dated_keys[0] if _ams_dated_keys else None

# ── Next Friday calculation ────────────────────────────────────────────────────
_today      = datetime.now().date()
_days_ahead = (4 - _today.weekday()) % 7   # 4 = Friday; 0 means today IS Friday
_next_friday = _today + __import__("datetime").timedelta(days=_days_ahead)
# Report 3658 publishes THURSDAY, not Friday like SJ_LS712 — three feeds on
# this page, three different cadences, and only one of them is Fridays.
_days_thu     = (3 - _today.weekday()) % 7   # 3 = Thursday
_next_thursday = _today + __import__("datetime").timedelta(days=_days_thu)

# ── Sidebar data info panel ────────────────────────────────────────────────────
st.sidebar.divider()
_ams_wk_str  = _ams_wk_date.strftime('%b %d, %Y')  if _ams_wk_date  else "N/A"
_ams_rpt_str = _ams_rpt_date.strftime('%b %d, %Y') if _ams_rpt_date else "N/A"
_vol_color   = '#fbbf24' if vol_latest_date is not None and vol_latest_date != latest_date else DM_TEXT
_vol_date_s  = vol_latest_date.strftime('%b %d, %Y') if vol_latest_date is not None else 'N/A'
_vol_iso_s   = f"Wk {int(vol_latest_date.isocalendar()[1])}, {vol_latest_date.year}" if vol_latest_date is not None else 'N/A'
_fis_wk_s    = _fis_wk_date.strftime('%b %d, %Y') if _fis_wk_date is not None else 'N/A'
_fis_pub_s   = _fis_pub.strftime('%b %d, %Y') if _fis_pub else 'N/A'
_fis_stat    = 'Live' if _tile_src == 'AMS' else ('Unavailable — ' + (_fis_err or 'not used on live basis'))
_fis_stat_c  = '#6fa8c4' if _tile_src == 'AMS' else '#fbbf24'
st.sidebar.markdown(f"""
<div style="background:{DM_SURFACE2};border:1px solid {DM_BORDER};
  border-left:3px solid {JSA_GREEN};border-radius:6px;padding:12px 14px;font-size:0.78rem">
  <div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;
    letter-spacing:.08em;margin-bottom:8px">Data Status</div>

  <div style="color:#6fa8c4;font-size:0.62rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">🗓️ AMS FIS — Carcass Weights (tiles)</div>
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="color:{DM_MUTED}">Week ending</span>
    <span style="color:{DM_TEXT};font-weight:600">{_fis_wk_s}</span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="color:{DM_MUTED}">Published</span>
    <span style="color:{DM_TEXT};font-weight:600">{_fis_pub_s}</span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:8px">
    <span style="color:{DM_MUTED}">Status</span>
    <span style="color:{_fis_stat_c};font-weight:600">{_fis_stat}</span>
  </div>

  <div style="color:{JSA_GREEN_LT};font-size:0.62rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">📊 NASS — Weights (history / 5-yr)</div>
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="color:{DM_MUTED}">Report date</span>
    <span style="color:{DM_TEXT};font-weight:600">{latest_date.strftime('%b %d, %Y')}</span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:8px">
    <span style="color:{DM_MUTED}">ISO Week</span>
    <span style="color:{DM_TEXT};font-weight:600">Wk {latest_iso}, {latest_year}</span>
  </div>

  <div style="color:{JSA_GREEN_LT};font-size:0.62rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">📊 NASS — Slaughter Volume</div>
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="color:{DM_MUTED}">Report date</span>
    <span style="color:{_vol_color};font-weight:600">{_vol_date_s}</span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:8px">
    <span style="color:{DM_MUTED}">ISO Week</span>
    <span style="color:{DM_TEXT};font-weight:600">{_vol_iso_s}</span>
  </div>

  <div style="border-top:1px solid {DM_BORDER};margin:8px 0"></div>

  <div style="color:#6fa8c4;font-size:0.62rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">🗓️ AMS — Weekly Slaughter</div>
  <div style="display:flex;justify-content:space-between;margin-bottom:2px">
    <span style="color:{DM_MUTED}">Week ending</span>
    <span style="color:{DM_TEXT};font-weight:600">{_ams_wk_str}</span>
  </div>
  <div style="display:flex;justify-content:space-between;margin-bottom:8px">
    <span style="color:{DM_MUTED}">Report date</span>
    <span style="color:{DM_TEXT};font-weight:600">{_ams_rpt_str}</span>
  </div>

  <div style="border-top:1px solid {DM_BORDER};margin:8px 0"></div>

  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">AMS FIS (weights)</span>
    <span style="color:{DM_TEXT};font-weight:600">Thursdays ({_next_thursday.strftime('%b %d')})</span>
  </div>

  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">AMS SJ_LS712 (slaughter)</span>
    <span style="color:{DM_TEXT};font-weight:600">Fridays ({_next_friday.strftime('%b %d')})</span>
  </div>

  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">NASS Livestock Slaughter</span>
    <span style="color:{DM_TEXT};font-weight:600">Monthly</span>
  </div>

  <div style="border-top:1px solid {DM_BORDER};margin:8px 0"></div>

  <div style="color:{DM_MUTED};font-size:0.68rem;line-height:1.5">
    NASS: USDA Livestock Slaughter report<br>
    AMS: MARS report 3658 (FIS carcass weights)<br>
    AMS: LPGMN report SJ_LS712<br>
    Cache refreshes every hour
  </div>
</div>
""", unsafe_allow_html=True)


# ── Header ─────────────────────────────────────────────────────────────────────

hdr_l, hdr_r = st.columns([4, 1])
with hdr_l:
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:24px;padding:10px 0 8px">
      <img src="{JSA_LOGO_FULL}" style="height:68px" />
      <div>
        <div style="font-size:2rem;font-weight:700;color:{DM_TEXT};line-height:1.1;letter-spacing:-0.01em">
          JSA - USDA Cattle Slaughter Weights
        </div>
        <div style="color:{DM_MUTED};font-size:0.88rem;margin-top:5px;letter-spacing:.02em">
          Weekly snapshot &nbsp;·&nbsp; USDA AMS FIS + NASS QuickStats &nbsp;·&nbsp; Federally Inspected &nbsp;·&nbsp; Commercial Slaughter
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
with hdr_r:
    _vol_str     = vol_latest_date.strftime('%b %d, %Y') if vol_latest_date is not None else "N/A"
    _wt_str      = latest_date.strftime('%b %d, %Y')
    _dates_match = vol_latest_date is not None and vol_latest_date == latest_date
    _ams_hdr_str = _ams_wk_date.strftime('%b %d, %Y') if _ams_wk_date else "N/A"
    _fis_hdr_s   = _fis_wk_date.strftime('%b %d, %Y') if _fis_wk_date is not None else "N/A"
    st.markdown(f"""
    <div style="text-align:right;padding-top:6px;font-size:0.75rem">
      <div style="color:#6fa8c4;font-size:0.6rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">AMS FIS — CARCASS WEIGHTS</div>
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:6px">
        <span style="color:{DM_MUTED}">Week ending</span>
        <span style="color:#6fa8c4;font-weight:700;font-size:0.9rem">{_fis_hdr_s}</span>
      </div>
      <div style="color:{DM_MUTED};font-size:0.6rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">NASS</div>
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:2px">
        <span style="color:{DM_MUTED}">Weights (history) as of</span>
        <span style="color:{DM_TEXT};font-weight:700;font-size:0.9rem">{_wt_str}</span>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:6px">
        <span style="color:{DM_MUTED}">Slaughter vol as of</span>
        <span style="color:{'#fbbf24' if not _dates_match else DM_TEXT};font-weight:700;font-size:0.9rem">{_vol_str}</span>
      </div>
      <div style="color:#6fa8c4;font-size:0.6rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">AMS</div>
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:6px">
        <span style="color:{DM_MUTED}">Week ending</span>
        <span style="color:#6fa8c4;font-weight:700;font-size:0.9rem">{_ams_hdr_str}</span>
      </div>
      <div style="display:inline-block;background:{JSA_GREEN};color:#fff;font-size:.68rem;
        font-weight:600;padding:2px 8px;border-radius:3px;letter-spacing:.06em">
        {weight_unit.upper()}
      </div>
    </div>
    """, unsafe_allow_html=True)
st.divider()

# ── Top-level page tabs ────────────────────────────────────────────────────────
_page_summary, _page_nass, _page_ams, _page_sat, _page_prod = st.tabs([
    "⭐  Summary",
    "📊  NASS Cattle Weights & Slaughter",
    "🗓️  AMS Weekly Slaughter",
    "📅  Saturday Slaughter",
    "🥩  Beef Production",
])


def _render_nass():
    """All NASS dashboard content — called inside the NASS tab."""
        # ── Weekly Snapshot cards ────────────────────────────────────────────────

    # Deliberately `wt`, not `wt_tiles` — this tab stays single-source NASS so
    # its charts and its headline can never disagree with each other.
    cols = st.columns(len(snap_classes))
    for col, cls in zip(cols, snap_classes):
        kpi = week_kpis(wt, cls)
        col.markdown(_snap_card(cls, kpi, unit_label, src="NASS"), unsafe_allow_html=True)

    st.caption(
        f"USDA NASS weekly weights, week ending {latest_date.strftime('%b %d, %Y')}. "
        f"NASS accumulates weeks into a MONTHLY Livestock Slaughter release, so this "
        f"page can sit several weeks behind. The Summary tab leads with the AMS FIS "
        f"weekly figure (report 3658) for the same measure."
    )

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)


    # ── Slaughter Volume Snapshot ──────────────────────────────────────────────────

    def vol_kpis(vol_df: pd.DataFrame, cls: str) -> dict:
        nan = dict(current=float("nan"), wow=float("nan"), wow_pct=float("nan"),
                   yoy=float("nan"), yoy_pct=float("nan"), t4w=float("nan"),
                   prior_avg=float("nan"), vs_prior_avg=float("nan"), vs_prior_avg_pct=float("nan"))
        sub = vol_df[vol_df["class_desc"] == cls].sort_values("week_ending")
        if sub.empty:
            return nan
        latest_d  = sub["week_ending"].max()
        latest_y  = int(sub.loc[sub["week_ending"] == latest_d, "year"].iloc[0])
        iso_w     = int(sub.loc[sub["week_ending"] == latest_d, "iso_week"].iloc[0])
        current   = float(sub.loc[sub["week_ending"] == latest_d, "Value"].iloc[0])

        prev_d = sub[sub["week_ending"] < latest_d]
        if not prev_d.empty:
            prev_val = float(sub.loc[sub["week_ending"] == prev_d["week_ending"].max(), "Value"].iloc[0])
            wow = current - prev_val
            wow_pct = wow / prev_val * 100 if prev_val else float("nan")
        else:
            wow = wow_pct = float("nan")

        ly_val = _nearest_week(sub, latest_y - 1, iso_w)
        yoy = current - ly_val if not pd.isna(ly_val) else float("nan")
        yoy_pct = yoy / ly_val * 100 if (not pd.isna(ly_val) and ly_val) else float("nan")

        t4w   = float(sub.tail(4)["Value"].mean())
        prior_val  = prior_years_avg(sub, latest_y, iso_w)
        vs_prior = current - prior_val if not pd.isna(prior_val) else float("nan")
        vs_prior_pct = vs_prior / prior_val * 100 if (not pd.isna(prior_val) and prior_val) else float("nan")
        return dict(current=current, wow=wow, wow_pct=wow_pct, yoy=yoy, yoy_pct=yoy_pct,
                    t4w=t4w, prior_avg=prior_val, vs_prior_avg=vs_prior, vs_prior_avg_pct=vs_prior_pct)


    def _vol_card(cls: str, kpi: dict) -> str:
        val_str  = f'{kpi["current"]:,.0f}' if not pd.isna(kpi["current"]) else "—"
        t4w_str  = f'{kpi["t4w"]:,.0f}' if not pd.isna(kpi["t4w"]) else "—"
        prior_str = f'{kpi["prior_avg"]:,.0f}' if not pd.isna(kpi["prior_avg"]) else "—"
        color = CLASS_COLORS.get(cls, DM_MUTED)
        return f"""
        <div class="snap-card">
          <div class="snap-class" style="color:{color}">{VOL_DISPLAY.get(cls, cls.title())}</div>
          <div class="snap-value">{val_str} <span style="font-size:0.9rem;color:{DM_MUTED}">head</span></div>
          <div class="snap-grid">
            {_snap_item("WoW", _dc(kpi['wow'], '+.0f', ' hd') + ' ' + _dc(kpi['wow_pct'], '+.1f', '%'))}
            {_snap_item("YoY", _dc(kpi['yoy'], '+.0f', ' hd') + ' ' + _dc(kpi['yoy_pct'], '+.1f', '%'))}
            {_snap_item("4-Wk Avg", f'<span class="snap-neu">{t4w_str} hd</span>')}
            {_snap_item("vs 5yr Avg", _dc(kpi['vs_prior_avg'], '+.0f', ' hd') + ' ' + _dc(kpi['vs_prior_avg_pct'], '+.1f', '%'))}
          </div>
          <div style="margin-top:8px;font-size:0.7rem;color:{DM_MUTED}">
            5yr avg: {prior_str} head
          </div>
        </div>"""


    st.markdown(f'<div class="sec-hdr">Slaughter Volume — Weekly Snapshot (Head)</div>', unsafe_allow_html=True)
    vol_snap_classes = ["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS"]
    vol_cols = st.columns(len(vol_snap_classes))
    for col, cls in zip(vol_cols, vol_snap_classes):
        kpi = vol_kpis(vol, cls)
        col.markdown(_vol_card(cls, kpi), unsafe_allow_html=True)

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)


    # ── Weight Summary table ───────────────────────────────────────────────────────

    def _fmt_delta(val: float, pct: float, suffix: str = " lb") -> str:
        if pd.isna(val):
            return "—"
        sign = "+" if val >= 0 else ""
        css  = "pos" if val >= 0 else "neg"
        p    = f" ({sign}{pct:.1f}%)" if not pd.isna(pct) else ""
        return f'<span class="{css}">{sign}{val:.1f}{suffix}{p}</span>'


    def _build_summary(classes: list) -> str:
        rows = ""
        for cls in classes:
            kpi = week_kpis(wt, cls)
            cur = f'{kpi["current"]:,.1f}' if not pd.isna(kpi["current"]) else "—"
            t4  = f'{kpi["t4w"]:,.1f}' if not pd.isna(kpi["t4w"]) else "—"
            rows += f"""<tr>
              <td>{CLASS_DISPLAY.get(cls, cls.title())}</td>
              <td>{cur} lb</td>
              <td>{_fmt_delta(kpi['wow'], kpi['wow_pct'])}</td>
              <td>{t4} lb</td>
              <td>{_fmt_delta(kpi['yoy'], kpi['yoy_pct'])}</td>
              <td>{_fmt_delta(kpi['vs_prior_avg'], kpi['vs_prior_avg_pct'])}</td>
            </tr>"""
        return f"""
        <table class="sum-table">
          <thead><tr>
            <th>Class</th>
            <th>This Week</th>
            <th>WoW Change</th>
            <th>4-Wk Avg</th>
            <th>vs Last Year</th>
            <th>vs 5yr Avg</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>"""


    def _build_vol_summary(classes: list) -> str:
        rows = ""
        for cls in classes:
            kpi = vol_kpis(vol, cls)
            cur = f'{kpi["current"]:,.0f}' if not pd.isna(kpi["current"]) else "—"
            t4  = f'{kpi["t4w"]:,.0f}' if not pd.isna(kpi["t4w"]) else "—"
            rows += f"""<tr>
              <td>{VOL_DISPLAY.get(cls, cls.title())}</td>
              <td>{cur} hd</td>
              <td>{_fmt_delta(kpi['wow'], kpi['wow_pct'], ' hd')}</td>
              <td>{t4} hd</td>
              <td>{_fmt_delta(kpi['yoy'], kpi['yoy_pct'], ' hd')}</td>
              <td>{_fmt_delta(kpi['vs_prior_avg'], kpi['vs_prior_avg_pct'], ' hd')}</td>
            </tr>"""
        return f"""
        <table class="sum-table">
          <thead><tr>
            <th>Class</th>
            <th>This Week</th>
            <th>WoW Change</th>
            <th>4-Wk Avg</th>
            <th>vs Last Year</th>
            <th>vs 5yr Avg</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>"""


    vol_sum_classes = ["GE 500 LBS", "STEERS", "HEIFERS", "COWS", "BULLS", "CALVES"]

    st.markdown(f'<div class="sec-hdr">Volume Summary — All Classes (Head)</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-radius:8px;padding:12px 16px">'
        + _build_vol_summary(vol_sum_classes)
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    st.markdown(f'<div class="sec-hdr">Weight Summary — All Classes</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-radius:8px;padding:12px 16px">'
        + _build_summary(CLASS_ORDER)
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


    # ── Tabs ───────────────────────────────────────────────────────────────────────

    tab_trend, tab_yoy, tab_vol, tab_data = st.tabs([
        "📈 Weekly Trend", "📊 Year-over-Year", "🔢 Slaughter Volume", "📋 Data"
    ])


    # ── Tab 1 — Weekly Trend ───────────────────────────────────────────────────────

    with tab_trend:
        cls = trend_class
        sub = wt[wt["class_desc"] == cls].sort_values("week_ending")

        if sub.empty:
            st.warning("No data for selected class.")
        else:
            # Build current year window — all weeks available for latest_year
            curr_yr = sub[sub["year"] == latest_year].sort_values("week_ending")
            # Apply trend window cutoff
            cutoff = curr_yr["week_ending"].max() - pd.Timedelta(weeks=trend_weeks)
            curr_yr = curr_yr[curr_yr["week_ending"] > cutoff]

            # Build an ISO-week → current-year date lookup for aligning all series to same X axis
            iso_to_date = curr_yr.set_index("iso_week")["week_ending"].to_dict()
            x_dates = curr_yr["week_ending"].values
            iso_weeks = curr_yr["iso_week"].values

            # Prior year — map onto current year dates by ISO week
            prev_lookup = sub[sub["year"] == latest_year - 1].set_index("iso_week")["Value"].to_dict()
            prev_y = [prev_lookup.get(w, float("nan")) for w in iso_weeks]

            # 5yr avg and range — mapped to current year dates
            prior_map = prior_years_series(sub, latest_year)
            prior_y    = [prior_map.get(w, float("nan")) for w in iso_weeks]
            prior_highs, prior_lows = [], []
            for w in iso_weeks:
                yr_vals = [_nearest_week(sub, latest_year - i, w) for i in range(1, 6)]
                yr_vals = [v for v in yr_vals if not pd.isna(v)]
                prior_highs.append(max(yr_vals) if yr_vals else float("nan"))
                prior_lows.append(min(yr_vals) if yr_vals else float("nan"))

            # 4-week rolling avg for current year
            sub_roll = sub[sub["year"] == latest_year].sort_values("week_ending").copy()
            sub_roll["t4w"] = sub_roll["Value"].rolling(4, min_periods=1).mean()
            roll_lookup = sub_roll.set_index("iso_week")["t4w"].to_dict()
            roll_y = [roll_lookup.get(w, float("nan")) for w in iso_weeks]

            fig = go.Figure()

            # 5yr range band
            fig.add_trace(go.Scatter(
                x=list(x_dates) + list(x_dates)[::-1],
                y=prior_highs + prior_lows[::-1],
                fill="toself", fillcolor="rgba(122,153,144,0.12)",
                line=dict(color="rgba(0,0,0,0)"),
                name="5yr Range", hoverinfo="skip", showlegend=True,
            ))

            # 5yr avg line
            fig.add_trace(go.Scatter(
                x=x_dates, y=prior_y,
                name="5yr Avg", mode="lines",
                line=dict(color="rgba(122,153,144,0.7)", width=1.8, dash="dash"),
                hovertemplate="5yr avg: %{y:,.1f} lb<extra></extra>",
            ))

            # Prior year — same X dates as current year
            fig.add_trace(go.Scatter(
                x=x_dates, y=prev_y,
                name=str(latest_year - 1), mode="lines",
                line=dict(color="rgba(224,232,240,0.5)", width=1.5, dash="dot"),
                hovertemplate=f"{latest_year-1}: %{{y:,.1f}} lb<extra></extra>",
            ))

            # Current year
            fig.add_trace(go.Scatter(
                x=x_dates, y=curr_yr["Value"].values,
                name=str(latest_year), mode="lines+markers",
                line=dict(color=JPSI_GREEN, width=2.5),
                marker=dict(size=5, color=JPSI_GREEN),
                hovertemplate=f"{latest_year}: %{{y:,.1f}} lb<extra></extra>",
            ))

            # 4-week rolling avg
            fig.add_trace(go.Scatter(
                x=x_dates, y=roll_y,
                name="4-Wk Rolling Avg", mode="lines",
                line=dict(color="#fbbf24", width=2, dash="dashdot"),
                hovertemplate="4-wk avg: %{y:,.1f} lb<extra></extra>",
            ))

            _wt_vals = list(curr_yr["Value"]) + [v for v in prev_y if not pd.isna(v)] + [v for v in prior_y if not pd.isna(v)]
            _apply(fig, f"{cls.title()} — {weight_unit} · Last {trend_weeks} Weeks", 440, "lb / head",
                   y_range=_tight_range(_wt_vals))
            st.plotly_chart(fig, use_container_width=True)

            # WoW delta bars
            recent = sub[sub["week_ending"] > cutoff].copy()
            recent["wow_delta"] = recent["Value"].diff()
            recent = recent.dropna(subset=["wow_delta"])

            fig2 = go.Figure(go.Bar(
                x=recent["week_ending"],
                y=recent["wow_delta"],
                marker_color=[COL_POS if v >= 0 else COL_NEG for v in recent["wow_delta"]],
                hovertemplate="WoW: %{y:+.1f} lb<extra></extra>",
            ))
            fig2.add_hline(y=0, line_color=DM_BORDER)
            _apply(fig2, "Week-over-Week Change", 240, "\u0394 lb / head")
            st.plotly_chart(fig2, use_container_width=True)


    # ── Tab 2 — Year-over-Year ─────────────────────────────────────────────────────

    with tab_yoy:
        yoy_cls = st.selectbox(
            "Class",
            [c for c in CLASS_ORDER if not wt[wt["class_desc"] == c].empty],
            format_func=_fmt_cls,
            key="yoy_cls",
        )
        n_years = st.slider("Years to compare", 3, 10, 6, key="yoy_n")

        yoy_sub = wt[wt["class_desc"] == yoy_cls].copy()
        if yoy_sub.empty:
            st.warning("No data.")
        else:
            yoy_sub["day_of_year"] = yoy_sub["week_ending"].dt.dayofyear
            ly_max  = yoy_sub["year"].max()
            yr_list = [y for y in range(ly_max - n_years + 1, ly_max + 1)
                       if y in yoy_sub["year"].unique()]

            month_ticks  = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
            month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

            # ── Multi-year overlay ────────────────────────────────────────────────
            fig3 = go.Figure()

            # 5yr average band
            prior_all = prior_years_series(yoy_sub, ly_max, n=5)
            all_doys = sorted(yoy_sub["day_of_year"].unique())
            doy_to_iso = yoy_sub.groupby("day_of_year")["iso_week"].first().to_dict()
            prior_y_all = [prior_all.get(doy_to_iso.get(d, 0), float("nan")) for d in all_doys]

            # Range band
            prior_high_all, prior_low_all = [], []
            for d in all_doys:
                iw = doy_to_iso.get(d, 0)
                yr_vals = [_nearest_week(yoy_sub, ly_max - i, iw) for i in range(1, 6)]
                yr_vals = [v for v in yr_vals if not pd.isna(v)]
                prior_high_all.append(max(yr_vals) if yr_vals else float("nan"))
                prior_low_all.append(min(yr_vals) if yr_vals else float("nan"))

            fig3.add_trace(go.Scatter(
                x=all_doys + all_doys[::-1],
                y=prior_high_all + prior_low_all[::-1],
                fill="toself", fillcolor="rgba(122,153,144,0.10)",
                line=dict(color="rgba(0,0,0,0)"),
                name="5yr Range", hoverinfo="skip",
            ))
            fig3.add_trace(go.Scatter(
                x=all_doys, y=prior_y_all,
                name="5yr Avg",
                mode="lines",
                line=dict(color="rgba(122,153,144,0.7)", width=1.8, dash="dash"),
                hovertemplate="5yr avg: %{y:,.1f} lb<extra></extra>",
            ))

            for yr in yr_list:
                yd = yoy_sub[yoy_sub["year"] == yr].sort_values("day_of_year")
                is_cur = yr == ly_max
                fig3.add_trace(go.Scatter(
                    x=yd["day_of_year"], y=yd["Value"],
                    name=str(yr), mode="lines",
                    line=dict(
                        color=JPSI_GREEN if is_cur else CLASS_COLORS.get(yoy_cls, DM_MUTED),
                        width=2.5 if is_cur else 1.2,
                        dash="solid" if is_cur else "dot",
                    ),
                    opacity=1.0 if is_cur else 0.5,
                    hovertemplate=f"{yr}: %{{y:,.1f}} lb<extra></extra>",
                ))

            _apply(fig3, f"{yoy_cls.title()} — Year-over-Year Overlay", 460, "lb / head")
            fig3.update_xaxes(tickmode="array", tickvals=month_ticks, ticktext=month_labels)
            st.plotly_chart(fig3, use_container_width=True)

            # ── Same-week YoY comparison bar chart ───────────────────────────────
            st.markdown('<div class="sec-hdr">Same Week — Value by Year</div>', unsafe_allow_html=True)
            wk_vals = []
            for yr in range(ly_max - n_years + 1, ly_max + 1):
                v = _nearest_week(yoy_sub, yr, latest_iso)
                prior_val = prior_years_avg(yoy_sub, yr, latest_iso)
                wk_vals.append({"Year": yr, "Value": v, "PriorAvg": prior_val})
            wk_df = pd.DataFrame(wk_vals).dropna(subset=["Value"])

            fig4 = go.Figure()
            fig4.add_trace(go.Bar(
                x=wk_df["Year"], y=wk_df["Value"],
                name="Actual",
                marker_color=[JPSI_GREEN if yr == ly_max else "rgba(74,222,128,0.45)"
                              for yr in wk_df["Year"]],
                hovertemplate="%{x}: %{y:,.1f} lb<extra></extra>",
            ))
            fig4.add_trace(go.Scatter(
                x=wk_df["Year"], y=wk_df["PriorAvg"],
                name="5yr Avg",
                mode="lines+markers",
                line=dict(color=DM_MUTED, dash="dash", width=1.5),
                hovertemplate="5yr avg: %{y:,.1f} lb<extra></extra>",
            ))
            _apply(fig4, f"ISO Week {latest_iso} — Historical Comparison", 300, "lb / head")
            fig4.update_xaxes(tickmode="linear", dtick=1)
            st.plotly_chart(fig4, use_container_width=True)

            # ── YoY delta vs 5yr avg ──────────────────────────────────────────────
            st.markdown('<div class="sec-hdr">Current Year vs 5yr Avg — Weekly Delta</div>', unsafe_allow_html=True)
            curr_full = yoy_sub[yoy_sub["year"] == ly_max].sort_values("iso_week")
            prior_curr = [prior_years_avg(yoy_sub, ly_max, w) for w in curr_full["iso_week"]]
            curr_full = curr_full.copy()
            curr_full["vs_prior_avg"] = curr_full["Value"].values - pd.array(prior_curr)

            fig5 = go.Figure(go.Bar(
                x=curr_full["week_ending"],
                y=curr_full["vs_prior_avg"],
                marker_color=[COL_POS if v >= 0 else COL_NEG for v in curr_full["vs_prior_avg"]],
                hovertemplate="%{x|%b %d}: %{y:+.1f} lb vs 5yr avg<extra></extra>",
            ))
            fig5.add_hline(y=0, line_color=DM_BORDER)
            _apply(fig5, f"{ly_max} vs 5yr Avg — Weekly \u0394", 260, "\u0394 lb / head")
            st.plotly_chart(fig5, use_container_width=True)


    # ── Tab 3 — Slaughter Volume ───────────────────────────────────────────────────

    with tab_vol:
        if vol.empty:
            st.warning("No slaughter volume data.")
        else:
            vol_cls = st.multiselect(
                "Classes",
                CLASS_ORDER,
                default=["GE 500 LBS", "STEERS", "HEIFERS"],
                format_func=_fmt_cls,
                key="vol_cls",
            )
            if not vol_cls:
                vol_cls = ["GE 500 LBS"]

            vol_cutoff = vol["week_ending"].max() - pd.Timedelta(weeks=trend_weeks)

            fig6 = go.Figure()
            for cls in vol_cls:
                cd = vol[(vol["class_desc"] == cls) & (vol["week_ending"] > vol_cutoff)].sort_values("week_ending")
                if cd.empty:
                    continue
                fig6.add_trace(go.Scatter(
                    x=cd["week_ending"], y=cd["Value"],
                    name=VOL_DISPLAY.get(cls, cls.title()), mode="lines",
                    line=dict(color=CLASS_COLORS.get(cls, DM_MUTED), width=2),
                    hovertemplate="%{y:,.0f} head<extra>%{fullData.name}</extra>",
                ))
            _vol_vals = [v for cls in vol_cls
                         for v in vol[(vol["class_desc"]==cls)&(vol["week_ending"]>vol_cutoff)]["Value"]]
            _apply(fig6, f"Weekly Slaughter — Head Count · Last {trend_weeks} Weeks", 420, "Head",
                   y_range=_tight_range(_vol_vals))
            st.plotly_chart(fig6, use_container_width=True)

            # Latest week pie
            latest_vol_date = vol["week_ending"].max()
            pie_data = vol[
                (vol["week_ending"] == latest_vol_date) &
                (vol["class_desc"].isin(["STEERS", "HEIFERS", "COWS", "BULLS", "CALVES"]))
            ]
            if not pie_data.empty:
                st.markdown(f'<div class="sec-hdr">Week of {latest_vol_date.strftime("%B %d, %Y")} — Class Mix</div>',
                            unsafe_allow_html=True)
                fig7 = go.Figure(go.Pie(
                    labels=pie_data["class_desc"].map(lambda c: VOL_DISPLAY.get(c, c.title())),
                    values=pie_data["Value"],
                    marker_colors=[CLASS_COLORS.get(c, DM_MUTED) for c in pie_data["class_desc"]],
                    hole=0.45, textinfo="label+percent",
                    hovertemplate="%{label}: %{value:,.0f} head<extra></extra>",
                ))
                fig7.update_layout(
                    paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
                    font=dict(color=DM_TEXT), showlegend=False,
                    height=300, margin=dict(l=20, r=20, t=10, b=10),
                )
                st.plotly_chart(fig7, use_container_width=True)


    # ── Tab 4 — Data ───────────────────────────────────────────────────────────────

    with tab_data:
        c1, c2 = st.columns([2, 1])
        with c1:
            tbl_cls = st.multiselect(
                "Classes", CLASS_ORDER,
                default=["GE 500 LBS", "STEERS", "HEIFERS"],
                format_func=_fmt_cls,
                key="tbl_cls",
            )
        with c2:
            tbl_unit = st.selectbox(
                "Unit",
                ["LB / HEAD, DRESSED BASIS", "LB / HEAD, LIVE BASIS", "HEAD"],
                key="tbl_unit",
            )

        tbl = raw[
            (raw["class_desc"].isin(tbl_cls or CLASS_ORDER)) &
            (raw["unit_desc"] == tbl_unit)
        ][["year", "week_ending", "class_desc", "unit_desc", "Value"]].copy()
        tbl = tbl.sort_values(["week_ending", "class_desc"], ascending=[False, True])
        tbl.columns = ["Year", "Week Ending", "Class", "Unit", "Value"]

        st.dataframe(
            tbl, use_container_width=True, height=440,
            column_config={
                "Value": st.column_config.NumberColumn(format="%.1f"),
                "Week Ending": st.column_config.DateColumn(format="MM/DD/YYYY"),
            },
        )
        st.download_button(
            "⬇ Download Excel",
            data=_to_excel(tbl),
            file_name=f"beef_weight_{current_year}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


    # ── Footer ──────────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(
        f'<p style="color:{DM_MUTED};font-size:.72rem;text-align:center">'
        f'<img src="{JSA_LOGO_WHITE}" style="height:18px;opacity:0.5;vertical-align:middle;margin-right:8px" />'
        f'John Stewart &amp; Associates &nbsp;·&nbsp; USDA NASS QuickStats &nbsp;·&nbsp; '
        f'Federally Inspected Commercial Slaughter &nbsp;·&nbsp; Cached 1 hr</p>',
        unsafe_allow_html=True,
    )


# ── AMS render ────────────────────────────────────────────────────────────────

def _hex_to_rgba(h, a=1.0):
    h = h.lstrip("#")
    r2, g2, b2 = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"rgba({r2},{g2},{b2},{a})"


def _render_ams_page():
    ams = _fetch_ams_raw()
    if "error" in ams:
        st.error(f"Could not load AMS report: {ams['error']}")
        return

    slaughter = ams.get("slaughter", {})
    wts_ams   = ams.get("weights", {})
    class_mix = ams.get("class_mix", {})
    meat_prod = ams.get("meat_prod", {})
    rpt_date  = ams.get("report_date")

    dated_keys = sorted([k for k in slaughter if not isinstance(k, str)], reverse=True)
    curr_d = dated_keys[0] if dated_keys else None
    prev_d = dated_keys[1] if len(dated_keys) > 1 else None
    yago_d = dated_keys[2] if len(dated_keys) > 2 else None

    wk_str  = curr_d.strftime("%b %d, %Y") if curr_d else "N/A"
    rpt_str = rpt_date.strftime("%b %d, %Y") if rpt_date else "N/A"

    # Header banner
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
      background:{DM_SURFACE2};border:1px solid {DM_BORDER};
      border-left:4px solid {JSA_GREEN};border-radius:6px;padding:14px 20px;margin-bottom:18px">
      <div>
        <div style="color:{DM_TEXT};font-size:1.1rem;font-weight:700">
          AMS Weekly — Livestock Slaughter &amp; Weights
        </div>
        <div style="color:{DM_MUTED};font-size:0.78rem;margin-top:3px">
          USDA Agricultural Marketing Service · Livestock, Poultry &amp; Grain Market News ·
          SJ_LS712 · More current than NASS (updates Fridays)
        </div>
      </div>
      <div style="text-align:right">
        <div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;letter-spacing:.06em">Week Ending</div>
        <div style="color:{JSA_GREEN_LT};font-size:1.15rem;font-weight:700">{wk_str}</div>
        <div style="color:{DM_MUTED};font-size:0.68rem">Report date: {rpt_str}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    def _fd(v, pct=False):
        if pd.isna(v): return "—"
        return f"{v:+.1f}%" if pct else f"{v:+,.0f}"
    def _fc(v): return COL_POS if (not pd.isna(v) and v >= 0) else COL_NEG

    # ── Slaughter head count tiles ────────────────────────────────────────────
    st.markdown(f'<div class="sec-hdr">Slaughter Head Count — Week Ending {wk_str}</div>',
                unsafe_allow_html=True)
    sp_colors = {"Cattle": JSA_GREEN_LT, "Calves": "#c4b456", "Hogs": "#c98a56", "Sheep": "#6fa8c4"}
    cols_sp = st.columns(4)
    for col, sp in zip(cols_sp, ["Cattle","Calves","Hogs","Sheep"]):
        cv = slaughter.get(curr_d, {}).get(sp, float("nan")) if curr_d else float("nan")
        pv = slaughter.get(prev_d, {}).get(sp, float("nan")) if prev_d else float("nan")
        yv = slaughter.get(yago_d, {}).get(sp, float("nan")) if yago_d else float("nan")
        wow = cv - pv if not (pd.isna(cv) or pd.isna(pv)) else float("nan")
        yoy = cv - yv if not (pd.isna(cv) or pd.isna(yv)) else float("nan")
        wow_p = wow/pv*100 if (not pd.isna(pv) and pv != 0) else float("nan")
        yoy_p = yoy/yv*100 if (not pd.isna(yv) and yv != 0) else float("nan")
        ytd_c = slaughter.get(f"YTD_{curr_d.year if curr_d else ''}", {}).get(sp, float("nan"))
        ytd_p = slaughter.get(f"YTD_{(curr_d.year-1) if curr_d else ''}", {}).get(sp, float("nan"))
        ytd_g = (ytd_c-ytd_p)/ytd_p*100 if (not (pd.isna(ytd_c) or pd.isna(ytd_p)) and ytd_p!=0) else float("nan")
        cv_s  = "—" if pd.isna(cv) else f"{cv:,.0f}"
        tc    = sp_colors.get(sp, JSA_GREEN)
        col.markdown(f"""
        <div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};
          border-top:3px solid {tc};border-radius:6px;padding:14px 16px">
          <div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;
            letter-spacing:.07em;margin-bottom:6px">{sp}</div>
          <div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;margin-bottom:10px">{cv_s}</div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px">
            <span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;
              font-size:0.7rem;color:{_fc(wow)}">WoW {_fd(wow_p,True)}</span>
            <span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;
              font-size:0.7rem;color:{_fc(yoy)}">YoY {_fd(yoy_p,True)}</span>
          </div>
          <div style="color:{DM_MUTED};font-size:0.7rem">
            YTD vs prior yr: <span style="color:{_fc(ytd_g)}">{_fd(ytd_g,True)}</span>
          </div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    # ── Cattle average weight tiles ───────────────────────────────────────────
    # Use actual dates as tile labels — avoids "current/prior" ambiguity since
    # the AMS report is published Friday before the week-ending Saturday.
    curr_lbl    = f"Live (Est.) · Wk Ending {curr_d.strftime('%b %d, %Y')}" if curr_d else "Live — Latest Wk"
    prev_lbl    = f"Live (Est.) · Wk Ending {prev_d.strftime('%b %d, %Y')}" if prev_d else "Live — Prior Wk"
    curr_dr_lbl = f"Dressed (Est.) · Wk Ending {curr_d.strftime('%b %d, %Y')}" if curr_d else "Dressed — Latest Wk"
    prev_dr_lbl = f"Dressed (Est.) · Wk Ending {prev_d.strftime('%b %d, %Y')}" if prev_d else "Dressed — Prior Wk"
    yago_lbl = yago_d.strftime("%b %d, %Y") if yago_d else "yr ago"

    st.markdown(f'<div class="sec-hdr">Cattle Average Weights &nbsp;·&nbsp; <span style="color:{DM_MUTED};font-size:0.65rem;font-weight:400">WoW compares the two most recent weeks · YoY vs {yago_lbl}</span></div>',
                unsafe_allow_html=True)

    wt_meta = [
        (curr_lbl,    "live",    curr_d, prev_d, yago_d, True),
        (prev_lbl,    "live",    prev_d, None,   yago_d, False),
        (curr_dr_lbl, "dressed", curr_d, prev_d, yago_d, True),
        (prev_dr_lbl, "dressed", prev_d, None,   yago_d, False),
    ]
    wt_cols = st.columns(4)
    for col, (label, basis, c_d2, p_d2, y_d2, has_wow) in zip(wt_cols, wt_meta):
        cv2 = wts_ams.get(basis,{}).get(c_d2,{}).get("Cattle", float("nan")) if c_d2 else float("nan")
        pv2 = wts_ams.get(basis,{}).get(p_d2,{}).get("Cattle", float("nan")) if p_d2 else float("nan")
        yv2 = wts_ams.get(basis,{}).get(y_d2,{}).get("Cattle", float("nan")) if y_d2 else float("nan")
        wow2 = cv2-pv2 if (has_wow and not(pd.isna(cv2) or pd.isna(pv2))) else float("nan")
        yoy2 = cv2-yv2 if not(pd.isna(cv2) or pd.isna(yv2)) else float("nan")
        cv2s  = "—" if pd.isna(cv2) else f"{cv2:,.0f} lb"
        wow2s = "—" if pd.isna(wow2) else f"{wow2:+.1f} lb"
        yoy2s = "—" if pd.isna(yoy2) else f"{yoy2:+.1f} lb"
        border_c = "#6fa8c4" if basis == "live" else "#c98a56"
        # Build badge HTML as a single string — no empty lines inside the div
        # (a blank line from an empty variable would end Streamlit's HTML block parser)
        badges = []
        if has_wow and not pd.isna(wow2):
            badges.append(f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc(wow2)}">WoW {wow2s}</span>')
        if y_d2 and not pd.isna(yoy2):
            badges.append(f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc(yoy2)}">YoY {yoy2s}</span>')
        badges_html = " ".join(badges)
        col.markdown(
            f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-top:3px solid {border_c};border-radius:6px;padding:14px 16px">'
            f'<div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">{label}</div>'
            f'<div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;margin-bottom:10px">{cv2s}</div>'
            f'<div style="display:flex;gap:6px;flex-wrap:wrap">{badges_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    # ── Beef Meat Production tile ─────────────────────────────────────────────
    st.markdown(f'<div class="sec-hdr">Beef Meat Production &nbsp;·&nbsp; <span style="color:{DM_MUTED};font-size:0.65rem;font-weight:400">million lbs · federally inspected</span></div>',
                unsafe_allow_html=True)
    mp_dated = sorted([k for k in meat_prod if not isinstance(k, str)], reverse=True)
    mp_curr = mp_dated[0] if mp_dated else None
    mp_prev = mp_dated[1] if len(mp_dated) > 1 else None
    mp_yago = mp_dated[2] if len(mp_dated) > 2 else None
    mp_yr   = mp_curr.year if mp_curr else datetime.now().year

    def _mpv(d):
        return meat_prod.get(d, {}).get("Beef", float("nan")) if d else float("nan")

    bc = _mpv(mp_curr); bp = _mpv(mp_prev); by = _mpv(mp_yago)
    ytd_c = meat_prod.get(f"YTD_{mp_yr}", {}).get("Beef", float("nan"))
    ytd_p = meat_prod.get(f"YTD_{mp_yr-1}", {}).get("Beef", float("nan"))
    ytd_g = (ytd_c-ytd_p)/ytd_p*100 if not (pd.isna(ytd_c) or pd.isna(ytd_p)) and ytd_p != 0 else float("nan")

    mp_wow = bc-bp if not (pd.isna(bc) or pd.isna(bp)) else float("nan")
    mp_yoy = bc-by if not (pd.isna(bc) or pd.isna(by)) else float("nan")
    mp_wow_p = mp_wow/bp*100 if (not pd.isna(mp_wow) and bp != 0) else float("nan")
    mp_yoy_p = mp_yoy/by*100 if (not pd.isna(mp_yoy) and by != 0) else float("nan")

    bc_s    = "—" if pd.isna(bc)    else f"{bc:,.1f}"
    ytd_c_s = "—" if pd.isna(ytd_c) else f"{ytd_c:,.1f}"
    ytd_p_s = "—" if pd.isna(ytd_p) else f"{ytd_p:,.1f}"
    _mp_wow_sp = f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc(mp_wow)}">WoW {_fd(mp_wow_p,True)}</span>' if not pd.isna(mp_wow) else ""
    _mp_yoy_sp = f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc(mp_yoy)}">YoY {_fd(mp_yoy_p,True)}</span>' if not pd.isna(mp_yoy) else ""
    _mp_badges = f"{_mp_wow_sp} {_mp_yoy_sp}".strip()
    _ytd_color = _fc(ytd_g) if not pd.isna(ytd_g) else DM_MUTED
    _ytd_g_s   = _fd(ytd_g, True) if not pd.isna(ytd_g) else "—"

    mp_col1, mp_col2, mp_col3 = st.columns([1, 1, 2])
    mp_col1.markdown(
        f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-top:3px solid #c98a56;border-radius:6px;padding:14px 16px">'
        f'<div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">Beef Production · Wk Ending {mp_curr.strftime("%b %d, %Y") if mp_curr else "N/A"}</div>'
        f'<div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;margin-bottom:10px">{bc_s} <span style="font-size:0.85rem;color:{DM_MUTED}">M lbs</span></div>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap">{_mp_badges}</div>'
        f'</div>', unsafe_allow_html=True)
    mp_col2.markdown(
        f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-top:3px solid #9b89c4;border-radius:6px;padding:14px 16px">'
        f'<div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">{mp_yr} YTD Beef Production</div>'
        f'<div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;margin-bottom:6px">{ytd_c_s} <span style="font-size:0.85rem;color:{DM_MUTED}">M lbs</span></div>'
        f'<div style="color:{DM_MUTED};font-size:0.72rem">vs {mp_yr-1} YTD: {ytd_p_s} M lbs &nbsp;<span style="color:{_ytd_color};font-weight:600">{_ytd_g_s}</span></div>'
        f'</div>', unsafe_allow_html=True)
    mp_col3.markdown(
        f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-top:3px solid {DM_BORDER};border-radius:6px;padding:14px 16px">'
        f'<div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">All Meat Production — Week Ending {mp_curr.strftime("%b %d, %Y") if mp_curr else "N/A"} (M lbs)</div>'
        + "".join([
            f'<div style="display:flex;justify-content:space-between;margin-bottom:4px">'
            f'<span style="color:{DM_MUTED};font-size:0.78rem">{k}</span>'
            f'<span style="color:{DM_TEXT};font-weight:600;font-size:0.78rem">{meat_prod.get(mp_curr,{}).get(k,float("nan")):.1f}</span>'
            f'</div>'
            for k in ["Beef","Calf/Veal","Pork","Lamb","Total"] if mp_curr and not pd.isna(meat_prod.get(mp_curr,{}).get(k,float("nan")))
        ])
        + f'</div>', unsafe_allow_html=True)

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    # ── Charts side by side ───────────────────────────────────────────────────
    c_l, c_r = st.columns(2)
    with c_l:
        if dated_keys:
            st.markdown('<div class="sec-hdr">Head Count by Species</div>', unsafe_allow_html=True)
            sp_list = ["Cattle","Calves","Hogs","Sheep"]
            fig_b = go.Figure()
            for lbl, dk, alpha in [
                (wk_str, curr_d, 1.0),
                (prev_d.strftime("%b %d, %Y") if prev_d else "Prior Wk", prev_d, 0.55),
                (yago_d.strftime("%b %d, %Y") if yago_d else "Year Ago", yago_d, 0.28),
            ]:
                vals = [slaughter.get(dk,{}).get(s,0) for s in sp_list] if dk else [0]*4
                fig_b.add_trace(go.Bar(name=lbl, x=sp_list, y=vals,
                                       marker_color=_hex_to_rgba(JSA_GREEN_LT, alpha)))
            fig_b.update_layout(barmode="group", **_base_layout("", 340),
                                xaxis=dict(**AXIS_STYLE), yaxis=dict(**AXIS_STYLE))
            st.plotly_chart(fig_b, use_container_width=True)

    with c_r:
        if class_mix:
            st.markdown('<div class="sec-hdr">Cattle Class Mix (%)</div>', unsafe_allow_html=True)
            mix_dates  = sorted(class_mix.keys(), reverse=True)
            mix_labels = ["Steers","Heifers","Cows","Bulls"]
            mix_colors = [CLASS_COLORS["STEERS"], CLASS_COLORS["HEIFERS"],
                          CLASS_COLORS["COWS"],   CLASS_COLORS["BULLS"]]
            fig_m = go.Figure()
            for i2, md in enumerate(mix_dates[:2]):
                row = class_mix[md]
                colors = mix_colors if i2==0 else [_hex_to_rgba(c, 0.45) for c in mix_colors]
                fig_m.add_trace(go.Bar(
                    name=md.strftime("Wk %b %d, %Y"), x=mix_labels,
                    y=[row.get(l,0) for l in mix_labels], marker_color=colors,
                    text=[f"{row.get(l,0):.1f}%" for l in mix_labels], textposition="outside",
                ))
            fig_m.update_layout(barmode="group", showlegend=True,
                                **_base_layout("", 340),
                                xaxis=dict(**AXIS_STYLE),
                                yaxis=dict(ticksuffix="%", **AXIS_STYLE))
            st.plotly_chart(fig_m, use_container_width=True)

    # ── Meat production table ─────────────────────────────────────────────────
    if meat_prod:
        st.markdown('<div class="sec-hdr">Weekly Meat Production (million lbs)</div>',
                    unsafe_allow_html=True)
        mp_df = pd.DataFrame([{"Week Ending": d, **v} for d,v in sorted(
            [(k,v) for k,v in meat_prod.items() if not isinstance(k, str)], reverse=True)])
        st.dataframe(mp_df, use_container_width=True, hide_index=True,
                     column_config={"Week Ending": st.column_config.DateColumn(format="MM/DD/YYYY")})

    st.markdown(f'<div style="color:{DM_MUTED};font-size:0.68rem;margin-top:12px">'
                f'Source: USDA AMS LPGMN · Report SJ_LS712 · Updated Fridays</div>',
                unsafe_allow_html=True)


# ── Summary tab ───────────────────────────────────────────────────────────────

def _render_summary():
    """Summary tab — AMS-led weight tiles + AMS slaughter tiles + seasonal chart."""

    # ── Headline carcass-weight tiles — AMS first, NASS underneath ───────────
    _hdr_col = "#6fa8c4" if _tile_src == "AMS" else JSA_GREEN_LT
    _hdr_wk  = wt_tiles["week_ending"].max()
    _hdr_src = ("USDA AMS — Actual Slaughter Under Federal Inspection (report 3658)"
                if _tile_src == "AMS" else "USDA NASS — Livestock Slaughter (monthly)")
    _pub_s   = (f' &nbsp;·&nbsp; published {_fis_pub.strftime("%b %d, %Y")}'
                if (_tile_src == "AMS" and _fis_pub) else "")
    st.markdown(
        f'<div class="sec-hdr" style="font-size:0.8rem;color:{_hdr_col}">'
        f'🗓️ Cattle Carcass Weights — {_hdr_src} &nbsp;·&nbsp; '
        f'Week Ending {_hdr_wk.strftime("%b %d, %Y")}{_pub_s}</div>',
        unsafe_allow_html=True,
    )
    if _tile_note:
        st.warning(_tile_note, icon="⚠️")
    if _fis_missing:
        st.warning(
            "AMS returned no " + ", ".join(CLASS_DISPLAY.get(c, c) for c in _fis_missing)
            + f" for week ending {_fis_wk_date.strftime('%b %d, %Y')} — "
              "those tiles fall back to NASS and are labelled NASS.", icon="⚠️")
    if _tile_src == "AMS" and _fis_stale:
        st.warning(
            f"These AMS figures are {_fis_age_days} days old (week ending "
            f"{_fis_wk_date.strftime('%b %d, %Y')}). Report 3658 normally runs "
            f"12–19 days behind, so it has probably stopped updating — the fetch "
            f"still succeeds, which is why nothing else here would flag it.",
            icon="⚠️")
    wt_cols = st.columns(len(snap_classes))
    for col, cls in zip(wt_cols, snap_classes):
        kpi = week_kpis(wt_tiles, cls)
        col.markdown(
            _snap_card(cls, kpi, unit_label,
                       src=_row_source(wt_tiles, cls, kpi["latest_date"])),
            unsafe_allow_html=True,
        )
    _cap_src = ("Tiles: USDA AMS MARS report 3658, published Thursdays, ~12 days "
                "after the week it covers." if _tile_src == "AMS" else
                "Tiles: USDA NASS Livestock Slaughter — weekly figures are only "
                "released monthly, so they can run ~3 weeks behind.")
    _cap_chk = (f" AMS and NASS dressed weight are the same measure: verified equal "
                f"within {_agree_max:,.1f} lb across {_agree_n} overlapping weeks "
                f"before splicing." if _tile_src == "AMS" else "")
    st.caption(_cap_src + " WoW / YoY / 4-week come from the same spliced series; "
               "the 5-year average and every chart below come from NASS history."
               + _cap_chk)

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ── AMS Slaughter tiles ──────────────────────────────────────────────────
    ams       = _ams_meta
    slaughter = ams.get("slaughter", {})
    dk        = sorted([k for k in slaughter if not isinstance(k, str)], reverse=True)
    curr_d    = dk[0] if dk        else None
    prev_d    = dk[1] if len(dk)>1 else None
    yago_d    = dk[2] if len(dk)>2 else None
    wk_str    = curr_d.strftime("%b %d, %Y") if curr_d else "N/A"

    st.markdown(
        f'<div class="sec-hdr" style="font-size:0.8rem;color:#6fa8c4">'
        f'🗓️ AMS Weekly — Cattle Slaughter &amp; Weights &nbsp;·&nbsp; Week Ending {wk_str}</div>',
        unsafe_allow_html=True,
    )

    def _fd(v, pct=False):
        if pd.isna(v): return "—"
        return f"{v:+.1f}%" if pct else f"{v:+,.0f}"
    def _fc(v): return COL_POS if (not pd.isna(v) and v >= 0) else COL_NEG

    wts_ams = ams.get("weights", {})

    # ── 3 cattle-focused tiles: Head Count, Live Weight, Dressed Weight ──────
    # Helper: safe get from slaughter dict
    def _sl(d):
        return slaughter.get(d, {}).get("Cattle", float("nan")) if d else float("nan")
    def _wt(basis, d):
        return wts_ams.get(basis, {}).get(d, {}).get("Cattle", float("nan")) if d else float("nan")

    # Pre-compute all six values
    sl_curr = _sl(curr_d);    sl_prev = _sl(prev_d);    sl_yago = _sl(yago_d)
    lv_curr = _wt("live", curr_d); lv_prev = _wt("live", prev_d); lv_yago = _wt("live", yago_d)
    dr_curr = _wt("dressed", curr_d); dr_prev = _wt("dressed", prev_d); dr_yago = _wt("dressed", yago_d)

    ytd_c_sl = slaughter.get(f"YTD_{curr_d.year if curr_d else ''}", {}).get("Cattle", float("nan"))
    ytd_p_sl = slaughter.get(f"YTD_{(curr_d.year-1) if curr_d else ''}", {}).get("Cattle", float("nan"))
    ytd_g_sl = (ytd_c_sl-ytd_p_sl)/ytd_p_sl*100 if (not (pd.isna(ytd_c_sl) or pd.isna(ytd_p_sl)) and ytd_p_sl != 0) else float("nan")

    prev_wk_str = prev_d.strftime("%b %d") if prev_d else "prior wk"
    yago_str    = yago_d.strftime("%b %d, %Y") if yago_d else "yr ago"

    def _tile(col, label, value, unit, wow_val, wow_pct, yoy_val, yoy_pct, extra_html, border_color):
        val_s  = "—" if pd.isna(value) else f"{value:,.0f}"
        wow_sp = f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc(wow_val)}">WoW {_fd(wow_pct,True)}</span>'
        yoy_sp = f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc(yoy_val)}">YoY {_fd(yoy_pct,True)}</span>'
        # All on one string — no blank lines inside the HTML block (blank lines end Streamlit's HTML parser)
        col.markdown(
            f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-top:3px solid {border_color};border-radius:6px;padding:14px 16px">'
            f'<div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">{label}</div>'
            f'<div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;line-height:1.1;margin-bottom:10px">{val_s} <span style="font-size:0.85rem;color:{DM_MUTED}">{unit}</span></div>'
            f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px">{wow_sp} {yoy_sp}</div>'
            f'{extra_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

    def _deltas(curr, prev, yago):
        wow_v = curr-prev if not (pd.isna(curr) or pd.isna(prev)) else float("nan")
        yoy_v = curr-yago if not (pd.isna(curr) or pd.isna(yago)) else float("nan")
        wow_p = wow_v/prev*100 if (not pd.isna(wow_v) and prev != 0) else float("nan")
        yoy_p = yoy_v/yago*100 if (not pd.isna(yoy_v) and yago != 0) else float("nan")
        return wow_v, wow_p, yoy_v, yoy_p

    sl_wow, sl_wow_p, sl_yoy, sl_yoy_p = _deltas(sl_curr, sl_prev, sl_yago)
    lv_wow, lv_wow_p, lv_yoy, lv_yoy_p = _deltas(lv_curr, lv_prev, lv_yago)
    dr_wow, dr_wow_p, dr_yoy, dr_yoy_p = _deltas(dr_curr, dr_prev, dr_yago)

    ytd_html = (f'<div style="color:{DM_MUTED};font-size:0.7rem">'
                f'YTD vs prior yr: <span style="color:{_fc(ytd_g_sl)}">{_fd(ytd_g_sl,True)}</span></div>')
    ref_html = (f'<div style="color:{DM_MUTED};font-size:0.68rem;margin-top:4px">'
                f'vs {prev_wk_str} &amp; {yago_str}</div>')

    # ── Beef production values for the 4th tile ──────────────────────────────
    mp      = ams.get("meat_prod", {})
    mp_dk   = sorted([k for k in mp if not isinstance(k, str)], reverse=True)
    mp_cd   = mp_dk[0] if mp_dk           else None
    mp_pd   = mp_dk[1] if len(mp_dk) > 1  else None
    mp_yd   = mp_dk[2] if len(mp_dk) > 2  else None
    mp_yr_s = mp_cd.year if mp_cd else datetime.now().year
    bc      = mp.get(mp_cd, {}).get("Beef", float("nan")) if mp_cd else float("nan")
    bp_     = mp.get(mp_pd, {}).get("Beef", float("nan")) if mp_pd else float("nan")
    by_     = mp.get(mp_yd, {}).get("Beef", float("nan")) if mp_yd else float("nan")
    ytd_bc  = mp.get(f"YTD_{mp_yr_s}",   {}).get("Beef", float("nan"))
    ytd_bp  = mp.get(f"YTD_{mp_yr_s-1}", {}).get("Beef", float("nan"))
    ytd_bg  = (ytd_bc-ytd_bp)/ytd_bp*100 if not (pd.isna(ytd_bc) or pd.isna(ytd_bp)) and ytd_bp != 0 else float("nan")
    bc_wow  = bc-bp_ if not (pd.isna(bc) or pd.isna(bp_)) else float("nan")
    bc_yoy  = bc-by_ if not (pd.isna(bc) or pd.isna(by_)) else float("nan")
    bc_wow_p = bc_wow/bp_*100 if (not pd.isna(bc_wow) and bp_ != 0) else float("nan")
    bc_yoy_p = bc_yoy/by_*100 if (not pd.isna(bc_yoy) and by_ != 0) else float("nan")

    bc_s    = "—" if pd.isna(bc)    else f"{bc:,.1f}"
    ytd_bc_s = "—" if pd.isna(ytd_bc) else f"{ytd_bc:,.1f}"
    ytd_bp_s = "—" if pd.isna(ytd_bp) else f"{ytd_bp:,.1f}"
    prod_wow_sp = f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc(bc_wow)}">WoW {_fd(bc_wow_p,True)}</span>' if not pd.isna(bc_wow) else ""
    prod_yoy_sp = f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc(bc_yoy)}">YoY {_fd(bc_yoy_p,True)}</span>' if not pd.isna(bc_yoy) else ""
    prod_badges = f"{prod_wow_sp} {prod_yoy_sp}".strip()
    prod_extra  = (f'<div style="color:{DM_MUTED};font-size:0.7rem;margin-top:6px">'
                   f'{mp_yr_s} YTD: {ytd_bc_s} M lbs &nbsp;'
                   f'<span style="color:{_fc(ytd_bg)};font-weight:600">{_fd(ytd_bg,True)}</span>'
                   f' vs {mp_yr_s-1} ({ytd_bp_s} M lbs)</div>')

    ams_cols = st.columns(4)
    _tile(ams_cols[0], "Cattle Slaughter", sl_curr, "head",
          sl_wow, sl_wow_p, sl_yoy, sl_yoy_p, ytd_html, JSA_GREEN_LT)
    _tile(ams_cols[1], "Avg Live Weight — Cattle (Est.)", lv_curr, "lb",
          lv_wow, lv_wow_p, lv_yoy, lv_yoy_p, ref_html, "#6fa8c4")
    _tile(ams_cols[2], "Avg Dressed Weight — Cattle (Est.)", dr_curr, "lb",
          dr_wow, dr_wow_p, dr_yoy, dr_yoy_p, ref_html, "#c98a56")
    # 4th tile — beef meat production
    ams_cols[3].markdown(
        f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-top:3px solid #9b89c4;border-radius:6px;padding:14px 16px;height:100%">'
        f'<div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">Beef Production (Est.) · M lbs</div>'
        f'<div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;line-height:1.1;margin-bottom:10px">{bc_s} <span style="font-size:0.85rem;color:{DM_MUTED}">M lbs</span></div>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px">{prod_badges}</div>'
        f'{prod_extra}'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

    # ── Seasonal chart ───────────────────────────────────────────────────────
    st.markdown(
        f'<div class="sec-hdr" style="font-size:0.8rem">📈 Seasonal Overlay Chart</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        chart_src = st.radio(
            "Data",
            ["Weights (NASS)", "Slaughter Volume (NASS)"],
            horizontal=True,
            key="sum_src",
        )
    with c2:
        if chart_src == "Weights (NASS)":
            sub_cls = st.selectbox(
                "Class", CLASS_ORDER, format_func=_fmt_cls, key="sum_cls_wt",
            )
        else:
            sub_cls = st.selectbox(
                "Class", CLASS_ORDER,
                format_func=lambda c: VOL_DISPLAY.get(c, c.title()),
                key="sum_cls_vol",
            )
    with c3:
        n_yrs = st.slider("Years", 3, 10, 6, key="sum_nyrs")

    # Pick dataset and labels
    if chart_src == "Weights (NASS)":
        chart_df  = wt[wt["class_desc"] == sub_cls].copy()
        y_label   = "lb / head"
        cls_label = _fmt_cls(sub_cls)
        val_fmt   = ",.1f"
        title_sfx = weight_unit
    else:
        chart_df  = vol[vol["class_desc"] == sub_cls].copy()
        y_label   = "Head"
        cls_label = VOL_DISPLAY.get(sub_cls, sub_cls.title())
        val_fmt   = ",.0f"
        title_sfx = "Head Count"

    if chart_df.empty:
        st.warning("No data for the selected combination.")
        return

    chart_df["day_of_year"] = chart_df["week_ending"].dt.dayofyear
    ly_max   = int(chart_df["year"].max())
    yr_list  = [y for y in range(ly_max - n_yrs + 1, ly_max + 1)
                if y in chart_df["year"].unique()]

    month_ticks  = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    # 5yr range + avg
    all_doys    = sorted(chart_df["day_of_year"].unique())
    doy_to_iso  = chart_df.groupby("day_of_year")["iso_week"].first().to_dict()
    prior_map    = prior_years_series(chart_df, ly_max, n=5)

    prior_hi, prior_lo, prior_avg_vals = [], [], []
    for d in all_doys:
        iw = doy_to_iso.get(d, 0)
        yr_vals = [_nearest_week(chart_df, ly_max - i, iw) for i in range(1, 6)]
        yr_vals = [v for v in yr_vals if not pd.isna(v)]
        prior_hi.append(max(yr_vals)  if yr_vals else float("nan"))
        prior_lo.append(min(yr_vals)  if yr_vals else float("nan"))
        prior_avg_vals.append(prior_map.get(iw, float("nan")))

    # Year color palette — current year gets JSA green, others cycle through muted tones
    _yr_palette = [
        "#6fa8c4", "#c98a56", "#9b89c4", "#c4b456",
        "#e07070", "#c8d4ca", "#7a9485", "#fbbf24", "#e2a8c4",
    ]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=all_doys + all_doys[::-1],
        y=prior_hi + prior_lo[::-1],
        fill="toself", fillcolor="rgba(122,153,144,0.10)",
        line=dict(color="rgba(0,0,0,0)"),
        name="5yr Range", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=all_doys, y=prior_avg_vals,
        name="5yr Avg", mode="lines",
        line=dict(color="rgba(122,153,144,0.75)", width=1.8, dash="dash"),
        hovertemplate=f"5yr avg: %{{y:{val_fmt}}}<extra></extra>",
    ))

    # Older years first (drawn underneath), current year last (on top)
    older = [y for y in yr_list if y != ly_max]
    for i, yr in enumerate(older):
        yd    = chart_df[chart_df["year"] == yr].sort_values("day_of_year")
        color = _hex_to_rgba(_yr_palette[i % len(_yr_palette)], 0.55)
        fig.add_trace(go.Scatter(
            x=yd["day_of_year"], y=yd["Value"],
            name=str(yr), mode="lines",
            line=dict(color=color, width=1.4),
            hovertemplate=f"{yr}: %{{y:{val_fmt}}}<extra></extra>",
        ))

    # Current year — bold green on top
    cur_df = chart_df[chart_df["year"] == ly_max].sort_values("day_of_year")
    fig.add_trace(go.Scatter(
        x=cur_df["day_of_year"], y=cur_df["Value"],
        name=str(ly_max), mode="lines+markers",
        line=dict(color=JPSI_GREEN, width=2.8),
        marker=dict(size=5, color=JPSI_GREEN),
        hovertemplate=f"{ly_max}: %{{y:{val_fmt}}}<extra></extra>",
    ))

    _apply(fig, f"{cls_label} — Seasonal Overlay · {title_sfx}", 500, y_label)
    fig.update_xaxes(tickmode="array", tickvals=month_ticks, ticktext=month_labels)
    st.plotly_chart(fig, use_container_width=True)


# ── Beef Production tab ───────────────────────────────────────────────────────

def _render_beef_production():
    """Beef Production tab — AMS weekly tile + NASS-computed seasonal chart."""

    # ABOVE THE AMS FETCH, DELIBERATELY. WASDE comes from ESMIS over a
    # different host, so an AMS outage must not take the forecast down with
    # it -- the same shape as the Saturday Slaughter view and the morning
    # cutout panel.
    _render_wasde_production()
    st.markdown("<hr style='margin:18px 0;'>", unsafe_allow_html=True)

    ams       = _fetch_ams_raw()
    meat_prod = ams.get("meat_prod", {})

    mp_dated = sorted([k for k in meat_prod if not isinstance(k, str)], reverse=True)
    mp_curr  = mp_dated[0] if mp_dated           else None
    mp_prev  = mp_dated[1] if len(mp_dated) > 1  else None
    mp_yago  = mp_dated[2] if len(mp_dated) > 2  else None
    mp_yr    = mp_curr.year if mp_curr else datetime.now().year

    def _mpv(d): return meat_prod.get(d, {}).get("Beef", float("nan")) if d else float("nan")
    def _fd2(v, pct=False):
        if pd.isna(v): return "—"
        return f"{v:+.1f}%" if pct else f"{v:+,.1f}"
    def _fc2(v): return COL_POS if (not pd.isna(v) and v >= 0) else COL_NEG

    bc = _mpv(mp_curr); bp = _mpv(mp_prev); by = _mpv(mp_yago)
    ytd_c = meat_prod.get(f"YTD_{mp_yr}",   {}).get("Beef", float("nan"))
    ytd_p = meat_prod.get(f"YTD_{mp_yr-1}", {}).get("Beef", float("nan"))
    ytd_g = (ytd_c-ytd_p)/ytd_p*100 if not (pd.isna(ytd_c) or pd.isna(ytd_p)) and ytd_p != 0 else float("nan")

    mp_wow   = bc-bp if not (pd.isna(bc) or pd.isna(bp)) else float("nan")
    mp_yoy   = bc-by if not (pd.isna(bc) or pd.isna(by)) else float("nan")
    mp_wow_p = mp_wow/bp*100 if (not pd.isna(mp_wow) and bp != 0) else float("nan")
    mp_yoy_p = mp_yoy/by*100 if (not pd.isna(mp_yoy) and by != 0) else float("nan")

    wk_str  = mp_curr.strftime("%b %d, %Y") if mp_curr else "N/A"
    rpt_str = ams.get("report_date","")
    rpt_str = rpt_str.strftime("%b %d, %Y") if hasattr(rpt_str,"strftime") else str(rpt_str)

    # ── Header banner ────────────────────────────────────────────────────────
    st.markdown(f"""
<div style="display:flex;align-items:center;justify-content:space-between;background:{DM_SURFACE2};border:1px solid {DM_BORDER};border-left:4px solid #c98a56;border-radius:6px;padding:14px 20px;margin-bottom:18px">
  <div>
    <div style="color:{DM_TEXT};font-size:1.1rem;font-weight:700">🥩 Beef Meat Production Tracker</div>
    <div style="color:{DM_MUTED};font-size:0.78rem;margin-top:3px">USDA AMS · Federally Inspected · million lbs · Chart built from NASS weekly slaughter data</div>
  </div>
  <div style="text-align:right">
    <div style="color:{DM_MUTED};font-size:0.68rem;text-transform:uppercase;letter-spacing:.06em">Week Ending</div>
    <div style="color:#c98a56;font-size:1.15rem;font-weight:700">{wk_str}</div>
    <div style="color:{DM_MUTED};font-size:0.68rem">Report: {rpt_str}</div>
  </div>
</div>""", unsafe_allow_html=True)

    # ── KPI tiles ────────────────────────────────────────────────────────────
    st.markdown(f'<div class="sec-hdr">Weekly Beef Production vs 2025</div>', unsafe_allow_html=True)

    bc_s    = "—" if pd.isna(bc)    else f"{bc:,.1f}"
    ytd_c_s = "—" if pd.isna(ytd_c) else f"{ytd_c:,.1f}"
    ytd_p_s = "—" if pd.isna(ytd_p) else f"{ytd_p:,.1f}"
    by_s    = "—" if pd.isna(by)    else f"{by:,.1f}"

    badges_wk = " ".join(filter(None, [
        (f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc2(mp_wow)}">WoW {_fd2(mp_wow_p,True)}</span>') if not pd.isna(mp_wow) else "",
        (f'<span style="background:{DM_SURFACE2};border-radius:3px;padding:2px 8px;font-size:0.7rem;color:{_fc2(mp_yoy)}">YoY {_fd2(mp_yoy_p,True)}</span>') if not pd.isna(mp_yoy) else "",
    ]))

    t1, t2, t3 = st.columns(3)
    t1.markdown(
        f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-top:3px solid #c98a56;border-radius:6px;padding:14px 16px">'
        f'<div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">Beef Production · {wk_str}</div>'
        f'<div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;margin-bottom:10px">{bc_s} <span style="font-size:0.85rem;color:{DM_MUTED}">M lbs</span></div>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap">{badges_wk}</div>'
        f'<div style="color:{DM_MUTED};font-size:0.7rem;margin-top:8px">Year ago ({mp_yago.strftime("%b %d, %Y") if mp_yago else "N/A"}): {by_s} M lbs</div>'
        f'</div>', unsafe_allow_html=True)

    ytd_color = _fc2(ytd_g)
    t2.markdown(
        f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-top:3px solid #9b89c4;border-radius:6px;padding:14px 16px">'
        f'<div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">{mp_yr} YTD Beef Production</div>'
        f'<div style="color:{DM_TEXT};font-size:1.7rem;font-weight:700;margin-bottom:8px">{ytd_c_s} <span style="font-size:0.85rem;color:{DM_MUTED}">M lbs</span></div>'
        f'<div style="color:{DM_MUTED};font-size:0.72rem">{mp_yr-1} YTD: {ytd_p_s} M lbs &nbsp;<span style="color:{ytd_color};font-weight:700;font-size:0.85rem">{_fd2(ytd_g,True)}</span></div>'
        f'</div>', unsafe_allow_html=True)

    # All meats breakdown
    all_meats = {k: meat_prod.get(mp_curr,{}).get(k,float("nan")) for k in ["Beef","Calf/Veal","Pork","Lamb","Total"]}
    rows_html  = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid {DM_BORDER}">'
        f'<span style="color:{DM_MUTED};font-size:0.78rem">{k}</span>'
        f'<span style="color:{"#c98a56" if k=="Beef" else DM_TEXT};font-weight:{"700" if k in ("Beef","Total") else "400"};font-size:0.78rem">{v:.1f} M lbs</span>'
        f'</div>'
        for k, v in all_meats.items() if not pd.isna(v)
    )
    t3.markdown(
        f'<div style="background:{DM_SURFACE};border:1px solid {DM_BORDER};border-top:3px solid {DM_BORDER};border-radius:6px;padding:14px 16px">'
        f'<div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">All Meats · Wk {wk_str}</div>'
        f'{rows_html}'
        f'</div>', unsafe_allow_html=True)

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    # ── Seasonal trend chart (NASS-computed: head × dressed wt / 1M) ─────────
    st.markdown(f'<div class="sec-hdr">Beef Production — Seasonal Trend &nbsp;·&nbsp; <span style="color:{DM_MUTED};font-size:0.65rem;font-weight:400">Computed: NASS weekly head count × avg dressed weight</span></div>',
                unsafe_allow_html=True)

    n_yrs_prod = st.slider("Years to show", 3, 10, 6, key="prod_nyrs")

    if beef_prod_nass.empty:
        st.warning("NASS production data not available.")
        return

    ly = int(beef_prod_nass["year"].max())
    yr_list = [y for y in range(ly - n_yrs_prod + 1, ly + 1) if y in beef_prod_nass["year"].unique()]

    all_doys   = sorted(beef_prod_nass["day_of_year"].unique())
    doy_to_iso = beef_prod_nass.groupby("day_of_year")["iso_week"].first().to_dict()

    # 5yr range + avg
    prior_hi, prior_lo, prior_avg_vals = [], [], []
    for d in all_doys:
        iw = doy_to_iso.get(d, 0)
        yr_vals = []
        for i in range(1, 6):
            sub = beef_prod_nass[(beef_prod_nass["year"] == ly-i) & (beef_prod_nass["iso_week"] == iw)]
            if not sub.empty:
                yr_vals.append(float(sub["prod_mlbs"].iloc[0]))
        prior_hi.append(max(yr_vals)  if yr_vals else float("nan"))
        prior_lo.append(min(yr_vals)  if yr_vals else float("nan"))
        prior_avg_vals.append(sum(yr_vals)/len(yr_vals) if yr_vals else float("nan"))

    _prod_palette = ["#6fa8c4","#c98a56","#9b89c4","#c4b456","#e07070","#c8d4ca","#7a9485","#fbbf24"]
    month_ticks   = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    month_labels  = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=all_doys + all_doys[::-1], y=prior_hi + prior_lo[::-1],
        fill="toself", fillcolor="rgba(201,138,86,0.10)",
        line=dict(color="rgba(0,0,0,0)"),
        name="5yr Range", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=all_doys, y=prior_avg_vals, name="5yr Avg", mode="lines",
        line=dict(color="rgba(201,138,86,0.75)", width=1.8, dash="dash"),
        hovertemplate="5yr avg: %{y:,.1f} M lbs<extra></extra>",
    ))

    older_yrs = [y for y in yr_list if y != ly]
    for i, yr in enumerate(older_yrs):
        yd = beef_prod_nass[beef_prod_nass["year"] == yr].sort_values("day_of_year")
        fig.add_trace(go.Scatter(
            x=yd["day_of_year"], y=yd["prod_mlbs"], name=str(yr), mode="lines",
            line=dict(color=_hex_to_rgba(_prod_palette[i % len(_prod_palette)], 0.55), width=1.4),
            hovertemplate=f"{yr}: %{{y:,.1f}} M lbs<extra></extra>",
        ))

    cur = beef_prod_nass[beef_prod_nass["year"] == ly].sort_values("day_of_year")
    fig.add_trace(go.Scatter(
        x=cur["day_of_year"], y=cur["prod_mlbs"], name=str(ly), mode="lines+markers",
        line=dict(color="#c98a56", width=2.8),
        marker=dict(size=5, color="#c98a56"),
        hovertemplate=f"{ly}: %{{y:,.1f}} M lbs<extra></extra>",
    ))

    # Drop AMS dot for the current week if data matches
    if mp_curr and not pd.isna(bc):
        fig.add_trace(go.Scatter(
            x=[mp_curr.timetuple().tm_yday], y=[bc],
            mode="markers", name=f"AMS Reported ({wk_str})",
            marker=dict(size=11, color="#c98a56", symbol="star",
                        line=dict(color="#fff", width=1.5)),
            hovertemplate=f"AMS: {bc:.1f} M lbs<extra></extra>",
        ))

    _apply(fig, f"Weekly Beef Production — {ly} vs Prior Years", 520, "Million lbs")
    fig.update_xaxes(tickmode="array", tickvals=month_ticks, ticktext=month_labels)
    st.plotly_chart(fig, use_container_width=True)

    # YTD bar comparison
    st.markdown(f'<div class="sec-hdr">YTD Beef Production — {mp_yr} vs {mp_yr-1}</div>', unsafe_allow_html=True)
    if not (pd.isna(ytd_c) or pd.isna(ytd_p)):
        fig_ytd = go.Figure()
        fig_ytd.add_trace(go.Bar(
            x=[str(mp_yr-1), str(mp_yr)],
            y=[ytd_p, ytd_c],
            marker_color=[_hex_to_rgba("#c98a56", 0.45), "#c98a56"],
            text=[f"{ytd_p:,.1f} M lbs", f"{ytd_c:,.1f} M lbs"],
            textposition="outside", textfont=dict(color=DM_TEXT, size=12),
            hovertemplate="%{x}: %{y:,.1f} M lbs<extra></extra>",
        ))
        _apply(fig_ytd, f"YTD Beef Production (thru wk ending {wk_str})", 280, "Million lbs")
        fig_ytd.update_xaxes(tickmode="linear")
        st.plotly_chart(fig_ytd, use_container_width=True)

    st.markdown(f'<div style="color:{DM_MUTED};font-size:0.68rem;margin-top:8px">AMS tile: USDA AMS LPGMN SJ_LS712 · Chart: NASS weekly head count × avg dressed weight estimate</div>',
                unsafe_allow_html=True)


# ── Render pages ──────────────────────────────────────────────────────────────

with _page_summary:
    _render_summary()

with _page_nass:
    _render_nass()

with _page_ams:
    _render_ams_page()

with _page_sat:
    render_saturday_slaughter()

with _page_prod:
    _render_beef_production()

# ── Disclaimer Footer ──────────────────────────────────────────────────────────
_yr = datetime.now().year
st.markdown(
    f'<div style="font-family:inherit;margin-top:48px;padding:16px 20px;border-top:1px solid {DM_BORDER};'
    f'color:{DM_MUTED};font-size:inherit;line-height:1.6;">'
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
    f'&copy; John Stewart &amp; Associates, Inc. {_yr}'
    f'</div>',
    unsafe_allow_html=True,
)
