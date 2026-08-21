import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
import re
from datetime import datetime

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

try:
    API_KEY = st.secrets.get("NASS_API_KEY", "9A6D1EB8-4D94-3221-BA0C-ADD4533EA0C1")
except Exception:
    API_KEY = "9A6D1EB8-4D94-3221-BA0C-ADD4533EA0C1"

BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"

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
</style>
""", unsafe_allow_html=True)


# ── Data fetching ──────────────────────────────────────────────────────────────

def _nass_get(params: dict) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(BASE_URL, params=params, timeout=60)
            return r.json()
        except requests.exceptions.Timeout:
            if attempt < 2:
                continue
        except Exception:
            pass
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
            "key":               API_KEY,
            "source_desc":       "SURVEY",
            "sector_desc":       "ANIMALS & PRODUCTS",
            "group_desc":        "LIVESTOCK",
            "commodity_desc":    "CATTLE",
            "statisticcat_desc": "SLAUGHTERED",
            "freq_desc":         "WEEKLY",
            "state_alpha":       "US",
            "year":              year,
            "format":            "JSON",
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
            "key":               API_KEY,
            "source_desc":       "SURVEY",
            "sector_desc":       "ANIMALS & PRODUCTS",
            "group_desc":        "LIVESTOCK",
            "commodity_desc":    "CATTLE",
            "statisticcat_desc": "SLAUGHTERED",
            "unit_desc":         "HEAD",
            "freq_desc":         "WEEKLY",
            "state_alpha":       "US",
            "year":              year,
            "format":            "JSON",
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


def olympic_avg(df: pd.DataFrame, ref_year: int, iso_week: int, n: int = 5) -> float:
    """Simple average of the n prior years for the same ISO week."""
    vals = [_nearest_week(df, ref_year - i, iso_week) for i in range(1, n + 1)]
    vals = [v for v in vals if not pd.isna(v)]
    if not vals:
        return float("nan")
    return sum(vals) / len(vals)


def olympic_series(df: pd.DataFrame, ref_year: int, n: int = 5) -> pd.Series:
    """Olympic avg for every ISO week, returned as Series indexed by iso_week."""
    weeks = sorted(df["iso_week"].unique())
    return pd.Series(
        {w: olympic_avg(df, ref_year, w, n) for w in weeks},
        name="olympic_avg",
    )


def trailing_4wk(df: pd.DataFrame) -> pd.DataFrame:
    """4-week rolling average per class, sorted by week_ending."""
    return (
        df.sort_values("week_ending")
        .assign(t4w=lambda d: d.groupby("class_desc")["Value"]
                .transform(lambda s: s.rolling(4, min_periods=1).mean()))
    )


def week_kpis(wt: pd.DataFrame, cls: str) -> dict:
    """Compute all snapshot KPIs for one class."""
    nan = dict(current=float("nan"), wow=float("nan"), wow_pct=float("nan"),
               yoy=float("nan"), yoy_pct=float("nan"), t4w=float("nan"),
               olympic=float("nan"), vs_olympic=float("nan"), vs_olympic_pct=float("nan"),
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

    # Olympic avg
    olym = olympic_avg(sub, latest_year, iso_week)
    vs_olympic = current - olym if not pd.isna(olym) else float("nan")
    vs_olympic_pct = vs_olympic / olym * 100 if (not pd.isna(olym) and olym) else float("nan")

    return dict(current=current, wow=wow, wow_pct=wow_pct, yoy=yoy, yoy_pct=yoy_pct,
                t4w=t4w, olympic=olym, vs_olympic=vs_olympic, vs_olympic_pct=vs_olympic_pct,
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


def _snap_card(cls: str, kpi: dict, unit_label: str) -> str:
    val_str = f'{kpi["current"]:,.1f}' if not pd.isna(kpi["current"]) else "—"
    t4w_str = f'{kpi["t4w"]:,.1f}' if not pd.isna(kpi["t4w"]) else "—"
    olym_str = f'{kpi["olympic"]:,.1f}' if not pd.isna(kpi["olympic"]) else "—"
    color = CLASS_COLORS.get(cls, DM_MUTED)
    return f"""
    <div class="snap-card">
      <div class="snap-class" style="color:{color}">{CLASS_DISPLAY.get(cls, cls.title())}</div>
      <div class="snap-value">{val_str} <span style="font-size:0.9rem;color:{DM_MUTED}">lb</span></div>
      <div class="snap-grid">
        {_snap_item("WoW", _dc(kpi['wow'], '+.1f', ' lb') + ' ' + _dc(kpi['wow_pct'], '+.1f', '%'))}
        {_snap_item("YoY", _dc(kpi['yoy'], '+.1f', ' lb') + ' ' + _dc(kpi['yoy_pct'], '+.1f', '%'))}
        {_snap_item("4-Wk Avg", f'<span class="snap-neu">{t4w_str} lb</span>')}
        {_snap_item("vs 5yr Avg", _dc(kpi['vs_olympic'], '+.1f', ' lb') + ' ' + _dc(kpi['vs_olympic_pct'], '+.1f', '%'))}
      </div>
      <div style="margin-top:8px;font-size:0.7rem;color:{DM_MUTED}">
        5yr avg: {olym_str} lb &nbsp;·&nbsp; {unit_label}
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


# ── Sidebar ────────────────────────────────────────────────────────────────────

st.sidebar.markdown(
    f'<div style="padding:10px 0 6px">'
    f'<img src="{JSA_LOGO_WHITE}" style="width:160px;opacity:0.92" /></div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<div style="background:{JSA_GREEN};border-radius:4px;padding:5px 10px;'
    f'font-size:.7rem;color:#fff;font-weight:600;letter-spacing:.08em;'
    f'text-transform:uppercase;margin-bottom:10px">Beef Weight Dashboard</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<span style="color:{DM_MUTED};font-size:.72rem">USDA NASS · Federally Inspected</span>',
    unsafe_allow_html=True,
)
st.sidebar.divider()

current_year = datetime.now().year
# Always load enough history for 5-yr olympic avg + trend charts
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

with st.spinner("Loading USDA NASS data…"):
    raw     = fetch_data(LOAD_YEARS)
    raw_vol = fetch_vol_data(LOAD_YEARS)

if raw.empty:
    st.error("No data returned from USDA NASS. Check your API key in st.secrets.")
    st.stop()

wt  = raw[raw["unit_desc"].str.contains(unit_filter, case=False, na=False)].copy()
# Use dedicated volume fetch; fall back to weight dataset if empty
vol = raw_vol if not raw_vol.empty else raw[raw["unit_desc"].str.upper() == "HEAD"].copy()
wt  = trailing_4wk(wt)

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

# ── Sidebar data info panel ────────────────────────────────────────────────────
st.sidebar.divider()
_ams_wk_str  = _ams_wk_date.strftime('%b %d, %Y')  if _ams_wk_date  else "N/A"
_ams_rpt_str = _ams_rpt_date.strftime('%b %d, %Y') if _ams_rpt_date else "N/A"
_vol_color   = '#fbbf24' if vol_latest_date is not None and vol_latest_date != latest_date else DM_TEXT
_vol_date_s  = vol_latest_date.strftime('%b %d, %Y') if vol_latest_date is not None else 'N/A'
_vol_iso_s   = f"Wk {int(vol_latest_date.isocalendar()[1])}, {vol_latest_date.year}" if vol_latest_date is not None else 'N/A'
st.sidebar.markdown(f"""
<div style="background:{DM_SURFACE2};border:1px solid {DM_BORDER};
  border-left:3px solid {JSA_GREEN};border-radius:6px;padding:12px 14px;font-size:0.78rem">
  <div style="color:{DM_MUTED};font-size:0.65rem;text-transform:uppercase;
    letter-spacing:.08em;margin-bottom:8px">Data Status</div>

  <div style="color:{JSA_GREEN_LT};font-size:0.62rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">📊 NASS — Weights</div>
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
    <span style="color:{DM_MUTED}">Next update</span>
    <span style="color:{DM_TEXT};font-weight:600">{_next_friday.strftime('%b %d, %Y')}</span>
  </div>

  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="color:{DM_MUTED}">Update day</span>
    <span style="color:{DM_TEXT};font-weight:600">Fridays</span>
  </div>

  <div style="border-top:1px solid {DM_BORDER};margin:8px 0"></div>

  <div style="color:{DM_MUTED};font-size:0.68rem;line-height:1.5">
    NASS: USDA Livestock Slaughter report<br>
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
          USDA Beef Slaughter Weights
        </div>
        <div style="color:{DM_MUTED};font-size:0.88rem;margin-top:5px;letter-spacing:.02em">
          Weekly snapshot &nbsp;·&nbsp; USDA NASS QuickStats &nbsp;·&nbsp; Federally Inspected &nbsp;·&nbsp; Commercial Slaughter
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
with hdr_r:
    _vol_str     = vol_latest_date.strftime('%b %d, %Y') if vol_latest_date is not None else "N/A"
    _wt_str      = latest_date.strftime('%b %d, %Y')
    _dates_match = vol_latest_date is not None and vol_latest_date == latest_date
    _ams_hdr_str = _ams_wk_date.strftime('%b %d, %Y') if _ams_wk_date else "N/A"
    st.markdown(f"""
    <div style="text-align:right;padding-top:6px;font-size:0.75rem">
      <div style="color:{DM_MUTED};font-size:0.6rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">NASS</div>
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:2px">
        <span style="color:{DM_MUTED}">Weights as of</span>
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
_page_summary, _page_nass, _page_ams, _page_prod = st.tabs([
    "⭐  Summary",
    "📊  NASS Beef Weights & Slaughter",
    "🗓️  AMS Weekly Slaughter",
    "🥩  Beef Production",
])


def _render_nass():
    """All NASS dashboard content — called inside the NASS tab."""
        # ── Weekly Snapshot cards ────────────────────────────────────────────────

    cols = st.columns(len(snap_classes))
    for col, cls in zip(cols, snap_classes):
        kpi = week_kpis(wt, cls)
        col.markdown(_snap_card(cls, kpi, unit_label), unsafe_allow_html=True)

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)


    # ── Slaughter Volume Snapshot ──────────────────────────────────────────────────

    def vol_kpis(vol_df: pd.DataFrame, cls: str) -> dict:
        nan = dict(current=float("nan"), wow=float("nan"), wow_pct=float("nan"),
                   yoy=float("nan"), yoy_pct=float("nan"), t4w=float("nan"),
                   olympic=float("nan"), vs_olympic=float("nan"), vs_olympic_pct=float("nan"))
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
        olym  = olympic_avg(sub, latest_y, iso_w)
        vs_ol = current - olym if not pd.isna(olym) else float("nan")
        vs_ol_pct = vs_ol / olym * 100 if (not pd.isna(olym) and olym) else float("nan")
        return dict(current=current, wow=wow, wow_pct=wow_pct, yoy=yoy, yoy_pct=yoy_pct,
                    t4w=t4w, olympic=olym, vs_olympic=vs_ol, vs_olympic_pct=vs_ol_pct)


    def _vol_card(cls: str, kpi: dict) -> str:
        val_str  = f'{kpi["current"]:,.0f}' if not pd.isna(kpi["current"]) else "—"
        t4w_str  = f'{kpi["t4w"]:,.0f}' if not pd.isna(kpi["t4w"]) else "—"
        olym_str = f'{kpi["olympic"]:,.0f}' if not pd.isna(kpi["olympic"]) else "—"
        color = CLASS_COLORS.get(cls, DM_MUTED)
        return f"""
        <div class="snap-card">
          <div class="snap-class" style="color:{color}">{VOL_DISPLAY.get(cls, cls.title())}</div>
          <div class="snap-value">{val_str} <span style="font-size:0.9rem;color:{DM_MUTED}">head</span></div>
          <div class="snap-grid">
            {_snap_item("WoW", _dc(kpi['wow'], '+.0f', ' hd') + ' ' + _dc(kpi['wow_pct'], '+.1f', '%'))}
            {_snap_item("YoY", _dc(kpi['yoy'], '+.0f', ' hd') + ' ' + _dc(kpi['yoy_pct'], '+.1f', '%'))}
            {_snap_item("4-Wk Avg", f'<span class="snap-neu">{t4w_str} hd</span>')}
            {_snap_item("vs 5yr Avg", _dc(kpi['vs_olympic'], '+.0f', ' hd') + ' ' + _dc(kpi['vs_olympic_pct'], '+.1f', '%'))}
          </div>
          <div style="margin-top:8px;font-size:0.7rem;color:{DM_MUTED}">
            5yr avg: {olym_str} head
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
              <td>{_fmt_delta(kpi['vs_olympic'], kpi['vs_olympic_pct'])}</td>
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
              <td>{_fmt_delta(kpi['vs_olympic'], kpi['vs_olympic_pct'], ' hd')}</td>
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
            olym_map = olympic_series(sub, latest_year)
            olym_y    = [olym_map.get(w, float("nan")) for w in iso_weeks]
            olym_highs, olym_lows = [], []
            for w in iso_weeks:
                yr_vals = [_nearest_week(sub, latest_year - i, w) for i in range(1, 6)]
                yr_vals = [v for v in yr_vals if not pd.isna(v)]
                olym_highs.append(max(yr_vals) if yr_vals else float("nan"))
                olym_lows.append(min(yr_vals) if yr_vals else float("nan"))

            # 4-week rolling avg for current year
            sub_roll = sub[sub["year"] == latest_year].sort_values("week_ending").copy()
            sub_roll["t4w"] = sub_roll["Value"].rolling(4, min_periods=1).mean()
            roll_lookup = sub_roll.set_index("iso_week")["t4w"].to_dict()
            roll_y = [roll_lookup.get(w, float("nan")) for w in iso_weeks]

            fig = go.Figure()

            # 5yr range band
            fig.add_trace(go.Scatter(
                x=list(x_dates) + list(x_dates)[::-1],
                y=olym_highs + olym_lows[::-1],
                fill="toself", fillcolor="rgba(122,153,144,0.12)",
                line=dict(color="rgba(0,0,0,0)"),
                name="5yr Range", hoverinfo="skip", showlegend=True,
            ))

            # 5yr avg line
            fig.add_trace(go.Scatter(
                x=x_dates, y=olym_y,
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

            _wt_vals = list(curr_yr["Value"]) + [v for v in prev_y if not pd.isna(v)] + [v for v in olym_y if not pd.isna(v)]
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

            # Olympic avg band
            olym_all = olympic_series(yoy_sub, ly_max, n=5)
            all_doys = sorted(yoy_sub["day_of_year"].unique())
            doy_to_iso = yoy_sub.groupby("day_of_year")["iso_week"].first().to_dict()
            olym_y_all = [olym_all.get(doy_to_iso.get(d, 0), float("nan")) for d in all_doys]

            # Range band
            olym_high_all, olym_low_all = [], []
            for d in all_doys:
                iw = doy_to_iso.get(d, 0)
                yr_vals = [_nearest_week(yoy_sub, ly_max - i, iw) for i in range(1, 6)]
                yr_vals = [v for v in yr_vals if not pd.isna(v)]
                olym_high_all.append(max(yr_vals) if yr_vals else float("nan"))
                olym_low_all.append(min(yr_vals) if yr_vals else float("nan"))

            fig3.add_trace(go.Scatter(
                x=all_doys + all_doys[::-1],
                y=olym_high_all + olym_low_all[::-1],
                fill="toself", fillcolor="rgba(122,153,144,0.10)",
                line=dict(color="rgba(0,0,0,0)"),
                name="5yr Range", hoverinfo="skip",
            ))
            fig3.add_trace(go.Scatter(
                x=all_doys, y=olym_y_all,
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
                olym = olympic_avg(yoy_sub, yr, latest_iso)
                wk_vals.append({"Year": yr, "Value": v, "Olympic": olym})
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
                x=wk_df["Year"], y=wk_df["Olympic"],
                name="5yr Avg",
                mode="lines+markers",
                line=dict(color=DM_MUTED, dash="dash", width=1.5),
                hovertemplate="5yr avg: %{y:,.1f} lb<extra></extra>",
            ))
            _apply(fig4, f"ISO Week {latest_iso} — Historical Comparison", 300, "lb / head")
            fig4.update_xaxes(tickmode="linear", dtick=1)
            st.plotly_chart(fig4, use_container_width=True)

            # ── YoY delta vs Olympic avg ──────────────────────────────────────────
            st.markdown('<div class="sec-hdr">Current Year vs 5yr Avg — Weekly Delta</div>', unsafe_allow_html=True)
            curr_full = yoy_sub[yoy_sub["year"] == ly_max].sort_values("iso_week")
            olym_curr = [olympic_avg(yoy_sub, ly_max, w) for w in curr_full["iso_week"]]
            curr_full = curr_full.copy()
            curr_full["vs_olympic"] = curr_full["Value"].values - pd.array(olym_curr)

            fig5 = go.Figure(go.Bar(
                x=curr_full["week_ending"],
                y=curr_full["vs_olympic"],
                marker_color=[COL_POS if v >= 0 else COL_NEG for v in curr_full["vs_olympic"]],
                hovertemplate="%{x|%b %d}: %{y:+.1f} lb vs Olympic avg<extra></extra>",
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
          More current than NASS (updates Fridays)
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
    """Summary tab — NASS weight tiles + AMS slaughter tiles + seasonal chart."""

    # ── NASS Weight tiles ────────────────────────────────────────────────────
    st.markdown(
        f'<div class="sec-hdr" style="font-size:0.8rem;color:{JSA_GREEN_LT}">'
        f'📊 NASS Beef Weights — Week Ending {latest_date.strftime("%b %d, %Y")}</div>',
        unsafe_allow_html=True,
    )
    wt_cols = st.columns(len(snap_classes))
    for col, cls in zip(wt_cols, snap_classes):
        kpi = week_kpis(wt, cls)
        col.markdown(_snap_card(cls, kpi, unit_label), unsafe_allow_html=True)

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
    olym_map    = olympic_series(chart_df, ly_max, n=5)

    olym_hi, olym_lo, olym_avg = [], [], []
    for d in all_doys:
        iw = doy_to_iso.get(d, 0)
        yr_vals = [_nearest_week(chart_df, ly_max - i, iw) for i in range(1, 6)]
        yr_vals = [v for v in yr_vals if not pd.isna(v)]
        olym_hi.append(max(yr_vals)  if yr_vals else float("nan"))
        olym_lo.append(min(yr_vals)  if yr_vals else float("nan"))
        olym_avg.append(olym_map.get(iw, float("nan")))

    # Year color palette — current year gets JSA green, others cycle through muted tones
    _yr_palette = [
        "#6fa8c4", "#c98a56", "#9b89c4", "#c4b456",
        "#e07070", "#c8d4ca", "#7a9485", "#fbbf24", "#e2a8c4",
    ]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=all_doys + all_doys[::-1],
        y=olym_hi + olym_lo[::-1],
        fill="toself", fillcolor="rgba(122,153,144,0.10)",
        line=dict(color="rgba(0,0,0,0)"),
        name="5yr Range", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=all_doys, y=olym_avg,
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
    olym_hi, olym_lo, olym_avg = [], [], []
    for d in all_doys:
        iw = doy_to_iso.get(d, 0)
        yr_vals = []
        for i in range(1, 6):
            sub = beef_prod_nass[(beef_prod_nass["year"] == ly-i) & (beef_prod_nass["iso_week"] == iw)]
            if not sub.empty:
                yr_vals.append(float(sub["prod_mlbs"].iloc[0]))
        olym_hi.append(max(yr_vals)  if yr_vals else float("nan"))
        olym_lo.append(min(yr_vals)  if yr_vals else float("nan"))
        olym_avg.append(sum(yr_vals)/len(yr_vals) if yr_vals else float("nan"))

    _prod_palette = ["#6fa8c4","#c98a56","#9b89c4","#c4b456","#e07070","#c8d4ca","#7a9485","#fbbf24"]
    month_ticks   = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    month_labels  = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=all_doys + all_doys[::-1], y=olym_hi + olym_lo[::-1],
        fill="toself", fillcolor="rgba(201,138,86,0.10)",
        line=dict(color="rgba(0,0,0,0)"),
        name="5yr Range", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=all_doys, y=olym_avg, name="5yr Avg", mode="lines",
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

with _page_prod:
    _render_beef_production()

# ── Disclaimer Footer ──────────────────────────────────────────────────────────
_yr = datetime.now().year
st.markdown(
    f'<div style="margin-top:48px;padding:16px 20px;border-top:1px solid {DM_BORDER};'
    f'color:{DM_MUTED};font-size:0.72rem;line-height:1.6;">'
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
