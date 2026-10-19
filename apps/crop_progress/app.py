"""
Crop Progress Dashboard -- USDA NASS weekly Crop Progress for the major grains.

Reads the shared NASS cache (usda-nass-etl, jobs/crop_progress.py) through the
vendored nass_cache_client.py; never calls NASS live.

Layout follows the JPSI crop-progress benchmark: selectors on the left, a state
map + TW / LW / LY / 5YA comparison table, and a seasonal line chart by calendar
week with an optional 5-year average.
"""
import sys as _sys  # portal-sync: sibling imports resolve to this folder
from pathlib import Path as _Path  # portal-sync
_sys.path.insert(0, str(_Path(__file__).parent))  # portal-sync
import base64
import datetime as dt
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import json

import nass_cache_client as ncc
from nass_cache_client import cache_freshness, fetch_cached

HERE = Path(__file__).parent
# -- palette (matches cftc-cot-dashboard / livestock-portal cot_report) --------
JSA_GREEN = "#5e7164"
DM_BG, DM_SURFACE, DM_BORDER = "#f6f8f7", "#ffffff", "#d7e2dc"
DM_TEXT, DM_MUTED = "#32373c", "#5f7267"
COL_POS, COL_NEG = "#16a34a", "#dc2626"
DARK, GREY = DM_TEXT, DM_MUTED
LINE_COLORS = ["#6fa8c4", "#c4785a", "#5e7164", "#9b89c4", "#b8c4bc", "#d4a84b", "#4c7c9a"]
WATERMARK = HERE / "assets" / "logo-50yr.png"
WATERMARK_OPACITY = 0.10

pass  # portal-sync: st.set_page_config removed (Home.py makes the one call allowed per run)


@st.cache_data(show_spinner=False)
def watermark_uri() -> str | None:
    try:
        return "data:image/png;base64," + base64.b64encode(WATERMARK.read_bytes()).decode()
    except OSError:
        return None


_wm = watermark_uri()
_wm_url = _wm or ""
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&family=Source+Sans+3:wght@400;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"] {{ background-color:{DM_BG}; color:{DM_TEXT}; }}
html, body, p, span, div, label, button, td, th {{ font-family:'Source Sans 3','Source Sans Pro',sans-serif; }}
.block-container {{ padding-top: 3.2rem; max-width: 1400px; }}
.dash-header {{ display:flex; align-items:center; gap:18px; padding-bottom:10px;
    border-bottom:1px solid {DM_BORDER}; margin-bottom:14px; }}
.dash-header img {{ height:40px; }}
.dash-header .t b {{ font-family:'EB Garamond',Georgia,serif; font-size:1.7rem; color:{DM_TEXT}; font-weight:600; }}
.dash-header .t div {{ font-size:.85rem; color:{DM_MUTED}; }}
@media (max-width: 640px) {{ .dash-header img {{ display:none; }} }}
.tile {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-top:3px solid {JSA_GREEN};
    border-radius:10px; padding:16px 20px; text-align:center; height:100%; min-height:150px; }}
.tile-label {{ color:{DM_MUTED}; font-size:0.68rem; text-transform:uppercase; letter-spacing:0.09em; margin-bottom:6px; }}
.tile-value {{ color:{DM_TEXT}; font-size:1.55rem; font-weight:700; line-height:1.1; }}
.tile-sub {{ color:{DM_MUTED}; font-size:0.72rem; margin-top:5px; }}
.tile-delta-neu {{ color:{DM_MUTED}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
.sec-header {{ color:{DM_MUTED}; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.1em;
    padding:10px 0 4px; border-bottom:1px solid {DM_BORDER}; margin-bottom:12px; }}
.asof {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-radius:8px; padding:10px 16px;
    color:{DM_MUTED}; font-size:0.82rem; margin-bottom:12px; }}
.asof b {{ color:{DM_TEXT}; }}
hr {{ border-color:{DM_BORDER}; }}
.snap-wrap {{ position: relative; background:{DM_SURFACE}; border:1px solid {DM_BORDER};
    border-radius:10px; padding:6px 10px 10px; }}
.snap-wrap::after {{ content:""; position:absolute; inset:0; pointer-events:none;
    background:url('{_wm_url}') center center / min(34%, 260px) no-repeat; opacity:{WATERMARK_OPACITY}; }}
.snap-grid {{ border-collapse:collapse; width:100%; font-size:0.86rem; color:{DM_TEXT}; }}
.snap-grid th {{ text-align:right; color:{DM_MUTED}; font-weight:600; font-size:0.72rem;
    text-transform:uppercase; letter-spacing:0.05em; padding:8px 12px; border-bottom:2px solid {DM_BORDER}; }}
.snap-grid th:first-child, .snap-grid td:first-child {{ text-align:left; }}
.snap-grid td {{ text-align:right; padding:6px 12px; border-bottom:1px solid {DM_BORDER}; }}
.snap-grid tbody th {{ text-align:left; text-transform:none; letter-spacing:0; font-size:0.86rem; font-weight:600;
    color:{DM_TEXT}; padding:6px 12px; border-bottom:1px solid {DM_BORDER}; }}
#MainMenu, footer {{ visibility:hidden; }}
.stDeployButton {{ display:none; }}
</style>
<div class="dash-header">
  <img src="https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png">
  <div class="t"><b>Crop Progress Dashboard</b>
  <div>USDA weekly crop progress &middot; John Stewart &amp; Associates</div></div>
</div>
""", unsafe_allow_html=True)


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', " ", str(name)).strip() or "chart"


def _snap_anchor(snap_id: str):
    """Zero-height marker so the snapshot tool can find the Plotly chart that follows it."""
    st.markdown(f'<div id="{snap_id}" style="height:0"></div>', unsafe_allow_html=True)


_SNAP_JS = """
<div style="display:flex;gap:6px;align-items:center;margin:2px 0 14px 0">
  <button id="dl__ID__" style="font:600 13px system-ui,sans-serif;color:#fff;
    background:__ACCENT__;border:none;border-radius:6px;padding:6px 12px;cursor:pointer">\U0001F4E5 PNG</button>
  <button id="cp__ID__" style="font:600 13px system-ui,sans-serif;color:__ACCENT__;
    background:transparent;border:1.5px solid __ACCENT__;border-radius:6px;padding:6px 12px;
    cursor:pointer">\U0001F4CB Copy</button>
  <span id="msg__ID__" style="font:12px system-ui,sans-serif;color:__MUTED__"></span>
</div>
<script>
(function(){
  const ANCHOR="__ID__", FN="__FN__";
  function ensureH2C(){
    if(window.html2canvas) return Promise.resolve();
    if(window.__h2c) return window.__h2c;
    window.__h2c=new Promise((res,rej)=>{
      const s=document.createElement("script");
      s.src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js";
      s.onload=()=>res(); s.onerror=()=>rej(new Error("load failed"));
      document.head.appendChild(s); setTimeout(()=>rej(new Error("timeout")),10000);
    });
    return window.__h2c;
  }
  // The tagged wrapper itself if it holds content (tables), else the first Plotly chart
  // after the anchor in document order (a chart can't carry an id of its own).
  function target(){
    const el=document.getElementById(ANCHOR); if(!el) return null;
    if(el.querySelector("table,canvas,svg")) return el;
    const charts=[...document.querySelectorAll('[data-testid="stPlotlyChart"]')];
    for(const c of charts){
      if(el.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING) return c;
    }
    return charts[0]||el;
  }
  async function shoot(){
    await ensureH2C();
    const el=target(); if(!el) throw new Error("nothing to capture");
    return await window.html2canvas(el,{scale:2,backgroundColor:"__BG__",logging:false,useCORS:true});
  }
  const msgEl=document.getElementById("msg__ID__");
  const msg=t=>{ if(msgEl){ msgEl.textContent=t; if(t) setTimeout(()=>{msgEl.textContent="";},2500);} };
  document.getElementById("dl__ID__").onclick=async()=>{
    msg("…"); try{ const c=await shoot(); const a=document.createElement("a");
      a.download=FN+".png"; a.href=c.toDataURL("image/png"); a.click(); msg("✓ saved"); }
    catch(e){ msg("⚠ "+e.message); }
  };
  // Promise-based ClipboardItem keeps the click's user gesture through html2canvas's async work.
  document.getElementById("cp__ID__").onclick=async()=>{
    msg("…");
    try{
      await navigator.clipboard.write([new ClipboardItem({"image/png":(async()=>{
        const c=await shoot();
        return await new Promise(r=>c.toBlob(r,"image/png"));
      })()})]);
      msg("✓ copied");
    }catch(e){ msg("⚠ "+(e.name||e.message)); }
  };
})();
</script>
"""


def _snap_toolbar(snap_id: str, filename: str):
    """PNG download + clipboard copy of the actual on-screen chart/map/table."""
    st.html(_SNAP_JS.replace("__ID__", snap_id).replace("__FN__", _safe_filename(filename))
            .replace("__ACCENT__", JSA_GREEN).replace("__MUTED__", DM_MUTED)
            .replace("__BG__", DM_SURFACE), unsafe_allow_javascript=True)


def sec(text: str):
    st.markdown(f'<div class="sec-header">{text}</div>', unsafe_allow_html=True)


def tile(label_: str, value: str, delta_: str | None = None, sub: str = "") -> str:
    d_ = f'<div class="tile-delta-neu">{delta_}</div>' if delta_ else ""
    s_ = f'<div class="tile-sub">{sub}</div>' if sub else ""
    return (f'<div class="tile"><div class="tile-label">{label_}</div>'
            f'<div class="tile-value">{value}</div>{d_}{s_}</div>')


AXIS = dict(gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
            tickfont=dict(color=DM_MUTED, size=11),
            title_font=dict(color=DM_MUTED, size=11), zeroline=False)


def add_watermark(fig: go.Figure, above: bool = False) -> None:
    """Corner-to-corner logo mark. Choropleth fills cover anything drawn below them,
    so the map passes above=True."""
    if _wm:
        fig.add_layout_image(dict(
            source=_wm, xref="paper", yref="paper", x=0.5, y=0.5, sizex=0.5, sizey=0.5,
            xanchor="center", yanchor="middle", sizing="contain",
            opacity=WATERMARK_OPACITY, layer="above" if above else "below"))

# ---------------------------------------------------------------------------
# Catalog: UI commodity -> NASS commodity_desc, class filter, stage order
# ---------------------------------------------------------------------------
COMMODITIES = {
    "Corn": dict(desc="CORN", cls=None, area_cls="ALL CLASSES",
                 stages=["PLANTED", "EMERGED", "SILKING", "DOUGH", "DENTED", "MATURE", "HARVESTED"]),
    "Soybeans": dict(desc="SOYBEANS", cls=None, area_cls="ALL CLASSES",
                     stages=["PLANTED", "EMERGED", "BLOOMING", "SETTING PODS",
                             "DROPPING LEAVES", "HARVESTED"]),
    "Winter wheat": dict(desc="WHEAT", cls="WINTER", area_cls="WINTER",
                         stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"], fall=("PLANTED", "EMERGED")),
    "Spring wheat": dict(desc="WHEAT", cls="SPRING, (EXCL", area_cls="SPRING, (EXCL DURUM)",
                         stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"]),
    "Sorghum": dict(desc="SORGHUM", cls=None, area_cls="ALL CLASSES",
                    stages=["PLANTED", "HEADED", "COLORING", "MATURE", "HARVESTED"]),
    "Oats": dict(desc="OATS", cls=None, area_cls="ALL CLASSES", stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"]),
    "Barley": dict(desc="BARLEY", cls=None, area_cls="ALL CLASSES", stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"]),
    "Rice": dict(desc="RICE", cls=None, area_cls="ALL CLASSES", stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"]),
    "Cotton": dict(desc="COTTON", cls="UPLAND", area_cls="UPLAND",
                   stages=["PLANTED", "SQUARING", "SETTING BOLLS", "BOLLS OPENING", "HARVESTED"]),
}

STATES = {
    "AL": "Alabama", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# Must match usda-nass-etl/jobs/crop_progress.py exactly (cache keys are hashes of params).
PROGRESS_BASE = {
    "source_desc": "SURVEY", "sector_desc": "CROPS", "group_desc": "FIELD CROPS",
    "statisticcat_desc": "PROGRESS", "freq_desc": "WEEKLY",
}
MIN_YEAR = "2000"
CURRENT_SEASON_YEAR = str(dt.datetime.now().year)

# State universe per commodity_desc: ask the ETL's own list so the two cannot drift.
try:
    from jobs.crop_progress import COMMODITY_STATES  # dev checkout only
except Exception:
    COMMODITY_STATES = None


def _states_for(desc: str) -> tuple:
    if COMMODITY_STATES:
        return COMMODITY_STATES[desc]
    return tuple(STATES)  # unknown states simply return an empty cache row


def year_label(y: int) -> str:
    return f"{y}/{(y + 1) % 100:02d}"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def _read_many(param_sets: list) -> list:
    """All cache rows for many param dicts. One Snowflake connection + one IN query
    (a connection per key made a commodity load take ~40 s); other backends fall
    back to the client's per-key read."""
    if not ncc._use_sf():
        return [r for p in param_sets for r in (fetch_cached(p).get("data", []) or [])]
    keys = [ncc._cache_key("api_GET", p) for p in param_sets]
    conn = ncc._sf_connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT data FROM nass_cache WHERE cache_key IN (%s)" % ",".join(["%s"] * len(keys)),
                    keys)
        fetched = cur.fetchall()
    finally:
        conn.close()
    rows = []
    for (data,) in fetched:
        data = data if isinstance(data, (dict, list)) else json.loads(data)
        rows.extend(data.get("data", []) or [])
    return rows


@st.cache_data(ttl=1800, max_entries=12, show_spinner="Loading USDA crop progress…")
def load_progress(desc: str) -> pd.DataFrame:
    """Every cached PROGRESS row for one commodity (all states, all classes)."""
    param_sets = []
    for yr_ge in (MIN_YEAR, CURRENT_SEASON_YEAR):
        for s in _states_for(desc):
            param_sets.append({**PROGRESS_BASE, "commodity_desc": desc,
                               "agg_level_desc": "STATE", "state_alpha": s, "year__GE": yr_ge})
        param_sets.append({**PROGRESS_BASE, "commodity_desc": desc,
                           "state_name": "US TOTAL", "year__GE": yr_ge})
    rows = _read_many(param_sets)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df[df["unit_desc"].str.startswith("PCT ", na=False)].copy()
    df["value"] = pd.to_numeric(df["Value"].astype(str).str.replace(",", ""), errors="coerce")
    df = df.dropna(subset=["value"])
    df["week"] = pd.to_numeric(df["reference_period_desc"].str.extract(r"WEEK #(\d+)")[0],
                               errors="coerce")
    df = df.dropna(subset=["week"])
    df["week"] = df["week"].astype(int)
    df["year"] = df["year"].astype(int)
    df["stage"] = df["unit_desc"].str[4:]
    df["state"] = np.where(df["state_name"] == "US TOTAL", "US", df["state_alpha"])
    df["week_ending"] = pd.to_datetime(df["week_ending"], errors="coerce")
    return df[["year", "week", "week_ending", "state", "class_desc", "stage", "value"]] \
        .drop_duplicates(["year", "week", "state", "class_desc", "stage"], keep="last")


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False)
def load_area(desc: str, cls: str, stat: str) -> pd.DataFrame:
    """Annual state acreage estimates (same cache keys as jobs/crop_progress.area_jobs)."""
    rows = _read_many([{
        "source_desc": "SURVEY", "sector_desc": "CROPS", "group_desc": "FIELD CROPS",
        "commodity_desc": desc, "class_desc": cls, "statisticcat_desc": stat,
        "unit_desc": "ACRES", "agg_level_desc": "STATE", "year__GE": "1985",
    }])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df[(df["domain_desc"] == "TOTAL")
            & (df["prodn_practice_desc"] == "ALL PRODUCTION PRACTICES")].copy()
    df["value"] = pd.to_numeric(df["Value"].astype(str).str.replace(",", ""), errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["value", "year"])
    df["year"] = df["year"].astype(int)
    df["grain"] = df["util_practice_desc"].eq("GRAIN")  # grain rows beat silage/all-use rows
    df["load_time"] = pd.to_datetime(df["load_time"], errors="coerce")
    return df.rename(columns={"state_alpha": "state"})[
        ["state", "year", "value", "grain", "load_time", "reference_period_desc"]]


def acre_basis(meta: dict, stage: str, target_year: int):
    """(acres by state, year used, estimate label, stat) -- latest NASS estimate at or before
    target_year. Harvest uses area harvested; every other stage uses area planted."""
    stat = "AREA HARVESTED" if stage == "HARVESTED" else "AREA PLANTED"
    df = load_area(meta["desc"], meta["area_cls"], stat)
    if df.empty and stat == "AREA HARVESTED":
        stat = "AREA PLANTED"
        df = load_area(meta["desc"], meta["area_cls"], stat)
    if df.empty:
        return pd.Series(dtype=float), None, "", stat
    df = df[(df["year"] <= target_year) & (df["year"] >= target_year - 2)]
    if df.empty:
        return pd.Series(dtype=float), None, "", stat
    df = df.sort_values(["state", "year", "grain", "load_time"]).groupby("state").tail(1)
    latest = df.sort_values(["year", "load_time"]).iloc[-1]
    ref = str(latest["reference_period_desc"]).title().replace("Year - ", "")
    return df.set_index("state")["value"], int(latest["year"]), ref, stat


def select(df: pd.DataFrame, meta: dict, stage: str) -> pd.DataFrame:
    """One commodity/class/stage with a crop-year column (fall-planted winter wheat -> next year)."""
    d = df[df["stage"] == stage]
    if meta["cls"]:
        d = d[d["class_desc"].str.startswith(meta["cls"], na=False)] if meta["cls"] != "WINTER" \
            else d[d["class_desc"] == "WINTER"]
    d = d.copy()
    d["crop_year"] = d["year"] + (1 if stage in meta.get("fall", ()) else 0)
    return d


def _back(ts: pd.Timestamp, years: int) -> pd.Timestamp:
    """Same month/day `years` earlier (Feb 29 -> Feb 28)."""
    try:
        return ts.replace(year=ts.year - years)
    except ValueError:
        return ts.replace(year=ts.year - years, day=28)


def build_series(d: pd.DataFrame) -> dict:
    """(state, crop_year) -> (week-ending ordinals, values), for date-aligned lookups."""
    out = {}
    for key, g in d.dropna(subset=["week_ending"]).sort_values("week_ending").groupby(["state", "crop_year"]):
        out[key] = (g["week_ending"].map(pd.Timestamp.toordinal).to_numpy(),
                    g["value"].to_numpy(float))
    return out


def aligned(series: dict, state: str, crop_year: int, ts: pd.Timestamp) -> float:
    """One season's value on calendar date ts, interpolated between its weekly reports.

    NASS "week numbers" land on different dates each year (week 42 ended Oct 18 in 2026 but
    Oct 24 in 2021), so comparing by week number overstates progress. NASS's own prior-year and
    5-year-average columns line up by date, and so does this. Before a season's first report
    there is no value; after its last report the finished value is held (only if it got to 90%+).
    """
    s_ = series.get((state, crop_year))
    if s_ is None:
        return np.nan
    x, y = s_
    o = ts.toordinal()
    if o < x[0]:
        return np.nan
    if o > x[-1]:
        return float(y[-1]) if y[-1] >= 90 else np.nan
    return float(np.interp(o, x, y))


def default_stage(raw: pd.DataFrame, meta: dict, stages: list) -> str:
    """The stage a trader wants to see first: the one the latest report is about.

    Looks only at the newest report week for the US. Planting is the headline until it is
    ~90% done; once harvest has started it is the headline; in between it is the furthest
    stage still under way (silking, dough, setting pods ...). Falls back to the last stage.
    """
    latest = {}
    for stg in stages:
        r = select(raw, meta, stg)
        r = r[r["state"] == "US"].sort_values("week_ending")
        if not r.empty:
            latest[stg] = (r.iloc[-1]["week_ending"], r.iloc[-1]["value"])
    if not latest:
        return stages[-1]
    newest = max(w for w, _ in latest.values())
    live = {k: v for k, (w, v) in latest.items() if (newest - w).days <= 7}  # still being reported
    if "PLANTED" in live and live["PLANTED"] < 90:
        return "PLANTED"
    if live.get("HARVESTED", 0) > 0:
        return "HARVESTED"
    under_way = [stg for stg in stages if stg in live and live[stg] < 97]
    return under_way[-1] if under_way else [stg for stg in stages if stg in live][-1]


def comparison_table(d: pd.DataFrame, series: dict, year: int, week: int, ts: pd.Timestamp) -> pd.DataFrame:
    cur = d[(d["crop_year"] == year) & (d["week"] == week)].set_index("state")["value"]
    rows = {}
    for st_, tw in cur.items():
        five = [aligned(series, st_, y, _back(ts, year - y)) for y in range(year - 5, year)]
        five = [v for v in five if not np.isnan(v)]
        rows[st_] = dict(TW=tw,
                         LW=aligned(series, st_, year, ts - pd.Timedelta(days=7)),
                         LY=aligned(series, st_, year - 1, _back(ts, 1)),
                         **{"5YA": float(np.mean(five)) if len(five) >= 3 else np.nan})
    out = pd.DataFrame.from_dict(rows, orient="index", columns=["TW", "LW", "LY", "5YA"])
    out["ΔLW"], out["ΔLY"], out["Δ5YA"] = out.TW - out.LW, out.TW - out.LY, out.TW - out["5YA"]
    return out


# Approximate state label positions (lon, lat) for the map's data labels.
STATE_XY = {
    "AL": (-86.8, 32.8), "AZ": (-111.7, 34.2), "AR": (-92.4, 34.9), "CA": (-119.6, 37.2),
    "CO": (-105.5, 39.0), "CT": (-72.7, 41.6), "DE": (-75.5, 39.0), "FL": (-81.7, 28.6),
    "GA": (-83.4, 32.7), "ID": (-114.6, 44.4), "IL": (-89.2, 40.0), "IN": (-86.3, 39.9),
    "IA": (-93.5, 42.0), "KS": (-98.4, 38.5), "KY": (-85.3, 37.5), "LA": (-92.0, 31.0),
    "ME": (-69.2, 45.3), "MD": (-76.8, 39.0), "MA": (-72.1, 42.3), "MI": (-84.6, 43.9),
    "MN": (-94.3, 46.3), "MS": (-89.7, 32.7), "MO": (-92.5, 38.4), "MT": (-109.6, 47.0),
    "NE": (-99.8, 41.5), "NH": (-71.6, 43.7), "NJ": (-74.5, 40.1), "NM": (-106.1, 34.4),
    "NY": (-75.5, 42.9), "NC": (-79.4, 35.5), "ND": (-100.5, 47.5), "OH": (-82.8, 40.3),
    "OK": (-97.5, 35.6), "OR": (-120.6, 44.0), "PA": (-77.8, 40.9), "RI": (-71.5, 41.7),
    "SC": (-80.9, 33.9), "SD": (-100.2, 44.4), "TN": (-86.3, 35.8), "TX": (-99.3, 31.5),
    "UT": (-111.7, 39.3), "VT": (-72.7, 44.0), "VA": (-78.8, 37.5), "WA": (-120.5, 47.4),
    "WV": (-80.6, 38.6), "WI": (-89.9, 44.6), "WY": (-107.5, 43.0),
}
SMALL_STATES = {"CT", "DE", "MA", "MD", "NH", "NJ", "RI", "VT"}


# ---------------------------------------------------------------------------
# Header + selectors
# ---------------------------------------------------------------------------
# ---- filters: one row along the top ----
f = st.columns([1.1, 1.1, 1, 1.3, 1.2])
commodity = f[0].selectbox("Commodity", list(COMMODITIES), key="commodity")
meta = COMMODITIES[commodity]
try:
    raw = load_progress(meta["desc"])
except Exception as e:  # noqa: BLE001
    st.error(f"Could not read the NASS cache: {e}")
    st.stop()
if raw.empty:
    st.warning("No cached crop progress rows for this commodity yet.")
    st.stop()

stages = [s for s in meta["stages"] if not select(raw, meta, s).empty]
latest_rep = f"{raw['week_ending'].max():%Y%m%d}"  # new NASS release -> new widget keys -> defaults reset
stage = f[1].selectbox("Crop stage", stages, index=stages.index(default_stage(raw, meta, stages)),
                       format_func=str.title, key=f"stage_{commodity}_{latest_rep}")
d = select(raw, meta, stage)
series = build_series(d)

years = sorted(d["crop_year"].unique(), reverse=True)
map_year = f[2].selectbox("Marketing year", years, format_func=year_label,
                          key=f"myear_{commodity}_{stage}_{latest_rep}")
wk_opts = sorted(d.loc[d["crop_year"] == map_year, "week"].unique())
we = d[(d["crop_year"] == map_year)].groupby("week")["week_ending"].max()
week = f[3].selectbox("Calendar week", wk_opts, index=len(wk_opts) - 1,
                      format_func=lambda w: f"Week #{w}" + (
                          f" (w/e {we[w]:%b %d})" if w in we.index and pd.notna(we[w]) else ""),
                      key=f"week_{commodity}_{stage}_{map_year}_{latest_rep}")
metric = f[4].selectbox("Map selection", ["TW (this week)", "LW (last week)", "LY (last year)",
                                          "5YA (5-year avg)", "ΔLW", "ΔLY", "Δ5YA"],
                        key="map_metric")

g = st.columns([2, 1.2, 1], vertical_alignment="bottom")
chart_years = g[0].multiselect("Marketing year(s) for line chart", years,
                               default=years[:2], format_func=year_label,
                               key=f"cyears_{commodity}_{stage}")
state_opts = ["US"] + sorted(s for s in d["state"].unique() if s != "US")
chart_state = g[1].selectbox("State for line chart", state_opts,
                             format_func=lambda s: "US total" if s == "US" else STATES.get(s, s),
                             key=f"cstate_{commodity}_{stage}")
show_5ya = g[2].toggle("Show 5-year average", value=True)

ref_ts = we[week]
table = comparison_table(d, series, map_year, week, ref_ts)

latest = d["week_ending"].max()
st.markdown(f'<div class="asof">Updated <b>{latest:%B %d, %Y}</b> &middot; USDA NASS Crop Progress, '
            f'{commodity.lower()} {stage.lower()} (% of acreage)</div>', unsafe_allow_html=True)

# ---- KPI cards for the US row ----
if "US" in table.index:
    u = table.loc["US"]
    k = st.columns(4)

    def delta(v):
        return None if pd.isna(v) else f"{v:+.0f} pts"

    def pct(v):
        return "—" if pd.isna(v) else f"{v:.0f}%"
    k[0].markdown(tile(f"{commodity} {stage.lower()} — week #{week}", pct(u.TW), delta(u.ΔLW),
                       "change vs last week"), unsafe_allow_html=True)
    k[1].markdown(tile("Last year (same date)", pct(u.LY), delta(u.ΔLY), "this week minus last year"),
                  unsafe_allow_html=True)
    k[2].markdown(tile("5-year average", pct(u["5YA"]), delta(u.Δ5YA), "this week minus 5-yr avg"),
                  unsafe_allow_html=True)
    k[3].markdown(tile("Last week", pct(u.LW), None, "prior weekly report"), unsafe_allow_html=True)
else:
    st.info("No US total reported for this week.")

# ---- full-width map with data labels ----
key = metric.split(" ")[0]
is_delta = key.startswith("Δ")
st_rows = table.drop(index="US", errors="ignore")
vals = st_rows[key]
if is_delta:
    lim = float(min(40, max(15, np.nanmax(np.abs(vals.values)) if len(vals) else 15)))
    zmin, zmax = -lim, lim
    scale = [[0, COL_NEG], [0.5, "#f6f8f7"], [1, COL_POS]]
else:
    zmin, zmax = 0, 100
    scale = [[0, "#eef3f0"], [1, "#3f5246"]]


def _dark_fill(v):
    return (abs(v) > 0.5 * zmax) if is_delta else (v >= 55)


lab = st_rows[st_rows.index.isin(STATE_XY)].dropna(subset=[key])


def fmt(v):
    return f"{v:+.0f}" if is_delta else f"{v:.0f}"


sec(f"State map — {metric}")
with st.container(border=True):
    fig = go.Figure(go.Choropleth(
        locations=vals.index, z=vals, locationmode="USA-states",
        text=[STATES.get(s, s) for s in vals.index],
        colorscale=scale, zmin=zmin, zmax=zmax,
        marker_line_color=DM_SURFACE, marker_line_width=1.2,
        colorbar=dict(title="pts" if is_delta else "%", thickness=16, len=0.8),
        hovertemplate="%{text}: %{z:.0f}<extra></extra>"))
    fig.add_trace(go.Scattergeo(
        lon=[STATE_XY[s][0] for s in lab.index], lat=[STATE_XY[s][1] for s in lab.index],
        mode="text", hoverinfo="skip", showlegend=False,
        text=[f"<b>{s}</b><br>{fmt(v)}" if s not in SMALL_STATES else f"<b>{fmt(v)}</b>"
              for s, v in lab[key].items()],
        textfont=dict(size=[9 if s in SMALL_STATES else 12 for s in lab.index],
                      color=["white" if _dark_fill(v) else DARK for v in lab[key]])))
    fig.update_geos(scope="usa", showlakes=False, bgcolor="rgba(0,0,0,0)")
    add_watermark(fig, above=True)
    fig.update_layout(dragmode=False, height=620, margin=dict(l=0, r=0, t=36, b=0),
                      paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE,
                      title=dict(text=f"{commodity} {stage.lower()} — {metric}, week #{week}",
                                 font=dict(size=16, color=DM_TEXT)))
    _snap_anchor("snap_map")
    st.plotly_chart(fig, width="stretch", config={"scrollZoom": False, "displayModeBar": False})
    _snap_toolbar("snap_map", f"Crop Progress {commodity} {stage} {metric.split(' ')[0]} week {week}")

# ---------------------------------------------------------------------------
# Seasonal line chart
# ---------------------------------------------------------------------------
sec(f"{commodity} {stage.lower()} seasonal chart — {'US total' if chart_state == 'US' else STATES.get(chart_state, chart_state)}")
fig = go.Figure()
sub = d[d["state"] == chart_state]
for i, y in enumerate(sorted(chart_years)):
    s = sub[sub["crop_year"] == y].sort_values("week")
    if s.empty:
        continue
    fig.add_trace(go.Scatter(x=s["week"], y=s["value"], mode="lines+markers", name=year_label(y),
                             line=dict(color=LINE_COLORS[i % len(LINE_COLORS)], width=2.5),
                             marker=dict(size=5),
                             hovertemplate="Week %{x}: %{y:.0f}%<extra>" + year_label(y) + "</extra>"))
if show_5ya and chart_years:
    ref = max(chart_years)
    ref_rows = d[(d["crop_year"] == ref) & d["week_ending"].notna()]
    hist_rows = sub[sub["crop_year"].isin(range(ref - 10, ref))]
    if not ref_rows.empty and not hist_rows.empty:
        anchor = ref_rows.iloc[0]                      # week number -> that week's date this season
        date_of = lambda w: anchor["week_ending"] + pd.Timedelta(days=7 * (int(w) - int(anchor["week"])))
        wks = list(range(int(hist_rows["week"].min()), int(hist_rows["week"].max()) + 1))
        m10, sd10, wk10, a5, wk5 = [], [], [], [], []
        for w in wks:
            ts_w = date_of(w)
            v10 = [aligned(series, chart_state, y, _back(ts_w, ref - y)) for y in range(ref - 10, ref)]
            v10 = [v for v in v10 if not np.isnan(v)]
            if len(v10) >= 5:
                wk10.append(w); m10.append(np.mean(v10)); sd10.append(np.std(v10, ddof=1))
                v5 = [aligned(series, chart_state, y, _back(ts_w, ref - y)) for y in range(ref - 5, ref)]
                v5 = [v for v in v5 if not np.isnan(v)]
                if len(v5) >= 3:
                    wk5.append(w); a5.append(np.mean(v5))
        mean10, sd10 = np.array(m10), np.array(sd10)
        for k, name, fill in ((2, "±2 SD", "rgba(94,113,100,0.14)"), (1, "±1 SD", "rgba(94,113,100,0.28)")):
            hi, lo = np.clip(mean10 + k * sd10, 0, 100), np.clip(mean10 - k * sd10, 0, 100)
            fig.add_trace(go.Scatter(x=wk10 + wk10[::-1], y=list(hi) + list(lo)[::-1], fill="toself",
                                     fillcolor=fill, line=dict(width=0), name=f"{name} (10-yr)",
                                     hoverinfo="skip", legendgroup=name))
        fig.add_trace(go.Scatter(x=wk5, y=a5, mode="lines", name="5-year average",
                                 line=dict(color=DM_TEXT, width=2, dash="dash"),
                                 hovertemplate="Week %{x}: %{y:.0f}%<extra>5-yr avg</extra>"))
add_watermark(fig)
fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                  paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE, hovermode="x unified",
                  legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11, color=DM_MUTED)),
                  xaxis=dict(**AXIS, title="Calendar week"),
                  yaxis=dict(**AXIS, title="Percent complete", range=[0, 100]))
with st.container(border=True):
    _snap_anchor("snap_chart")
    st.plotly_chart(fig, width="stretch")
    _snap_toolbar("snap_chart", f"Crop Progress {commodity} {stage} seasonal {chart_state}")

# ---------------------------------------------------------------------------
# State table
# ---------------------------------------------------------------------------
sec(f"State detail — % {stage.lower()}, week #{week}")
basis, basis_year, basis_ref, basis_stat = acre_basis(meta, stage, map_year)
disp = table[["TW", "ΔLW", "Δ5YA"]].copy()
us_total_acres = float(basis.sum()) if len(basis) else np.nan
acres = basis.reindex(disp.index)
if "US" in disp.index:
    acres.loc["US"] = us_total_acres
disp["share"] = acres / us_total_acres * 100 if us_total_acres else np.nan
disp["left"] = acres * (1 - disp["TW"] / 100) / 1000
disp.columns = ["This wk", "WoW", "Δ5Y-avg",
                "% of US harvested acres" if stage == "HARVESTED" else "% of US planted acres",
                "Acres left (000)"]
disp["_k"] = [(s != "US", -(v if pd.notna(v) else -1)) for s, v in zip(disp.index, disp.iloc[:, 3])]
disp = disp.sort_values("_k").drop(columns="_k")
disp.index = ["US TOTAL" if s == "US" else STATES.get(s, s).upper() for s in disp.index]
disp.index.name = None


def _chg(v):
    return "" if pd.isna(v) else f"color: {COL_POS if v >= 0 else COL_NEG}; font-weight: 600"


styled = (disp.style
          .format({"This wk": "{:.0f}", "WoW": "{:+.0f}", "Δ5Y-avg": "{:+.1f}",
                   disp.columns[3]: "{:.1f}%", "Acres left (000)": "{:,.0f}"}, na_rep="–")
          .map(_chg, subset=["Δ5Y-avg"])
          .map(lambda v: "font-weight: 700", subset=["WoW"])
          .apply(lambda r: ["font-weight: 700; background-color: #eef3f0"] * len(r)
                 if r.name == "US TOTAL" else [""] * len(r), axis=1))
styled = styled.set_table_attributes('class="snap-grid"').hide(names=True)
st.html(f'<div class="snap-wrap" id="snap_table">{styled.to_html()}</div>')
_snap_toolbar("snap_table", f"Crop Progress {commodity} {stage} state table week {week}")
if basis_year:
    st.caption(f"Acres left = latest NASS {basis_stat.lower()} estimate ({basis_year}, {basis_ref}) "
               f"× (1 − % {stage.lower()}); share = state's slice of the US total of that estimate. "
               "Fall-planted winter wheat uses the most recent seeded-acre estimate.")
else:
    st.caption("No NASS acreage estimate is cached for this commodity yet, so share and acres left are blank.")

st.caption("Source: USDA NASS Crop Progress (weekly, Mondays 4 pm ET) via the JSA NASS cache. "
           "LY and 5YA are lined up by calendar date (interpolated between weekly reports), not week number; the 5-year average needs at least 3 prior "
           f"years. Cache last refreshed: {cache_freshness() or 'unknown'}.")
