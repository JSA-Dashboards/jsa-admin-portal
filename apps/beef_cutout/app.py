import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta
import time

# ── JSA Brand Colors ────────────────────────────────────────────────────────
JSA_GREEN    = "#5e7164"
JSA_GREEN_LT = "#8db89a"

DM_BG       = "#f6f8f7"
DM_SURFACE  = "#ffffff"
DM_SURFACE2 = "#eef3f0"
DM_BORDER   = "#d7e2dc"
DM_TEXT     = "#32373c"
DM_MUTED    = "#5f7267"
COL_POS     = "#16a34a"
COL_NEG     = "#dc2626"
COL_NEU     = "#5f7267"

CHOICE_COLOR = "#8db89a"
SELECT_COLOR = "#6fa8c4"
SPREAD_COLOR = "#c4b456"
VOL_COLOR    = "#9b89c4"

JSA_LOGO_WHITE = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"

# ── USDA LMR API (no key required) ──────────────────────────────────────────
LMR_BASE       = "https://mpr.datamart.ams.usda.gov/services/v1.1/reports"
REPORT_ID      = 2453   # LM_XB403 — National Daily Boxed Beef Cutout & Boxed Beef Cuts PM
REPORT_NAME    = "LM_XB403"
GRADING_ID     = 2700   # LSWFEDCC — National Weekly Fed Cattle Comprehensive (has Pct_Choice_CW)

# ── Historical annual grading averages (USDA AMS, 2000-2025) ────────────────
# Source: USDA AMS National Weekly Fed Cattle Comprehensive annual summaries
# "Choice & Higher" = Prime + Choice graded carcasses as % of total graded
ANNUAL_GRADES = {
    2000: (60.6, 39.4), 2001: (60.7, 39.3), 2002: (62.1, 37.9),
    2003: (60.0, 39.9), 2004: (60.6, 39.0), 2005: (60.3, 39.5),
    2006: (59.0, 40.9), 2007: (60.5, 39.1), 2008: (63.8, 35.8),
    2009: (67.0, 32.7), 2010: (67.8, 31.5), 2011: (68.9, 30.7),
    2012: (68.8, 30.9), 2013: (70.4, 29.5), 2014: (75.0, 22.0),
    2015: (78.0, 18.0), 2016: (82.0, 13.0), 2017: (85.0, 11.0),
    2018: (87.0, 10.0), 2019: (88.0,  9.0), 2020: (85.0, 12.0),
    2021: (85.0, 11.0), 2022: (85.0, 11.0), 2023: (87.0, 10.0),
    2024: (88.0,  9.5), 2025: (88.5,  9.0),
}

# ── Page Config ─────────────────────────────────────────────────────────────
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

  .tile {{
    background:{DM_SURFACE}; border:1px solid {DM_BORDER};
    border-top:3px solid {JSA_GREEN}; border-radius:10px;
    padding:16px 20px; text-align:center; height:100%;
  }}
  .tile-label {{
    color:{DM_MUTED}; font-size:0.68rem; text-transform:uppercase;
    letter-spacing:0.09em; margin-bottom:6px;
  }}
  .tile-value {{
    color:{DM_TEXT}; font-size:1.65rem; font-weight:700; line-height:1.1;
  }}
  .tile-delta-pos {{ color:{COL_POS}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neg {{ color:{COL_NEG}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neu {{ color:{COL_NEU}; font-size:0.82rem; font-weight:600; margin-top:4px; }}

  .tile-choice {{ border-top-color:{CHOICE_COLOR}; }}
  .tile-select {{ border-top-color:{SELECT_COLOR}; }}
  .tile-spread {{ border-top-color:{SPREAD_COLOR}; }}
  .tile-vol    {{ border-top-color:{VOL_COLOR}; }}

  .sec-header {{
    color:{DM_MUTED}; font-size:0.7rem; text-transform:uppercase;
    letter-spacing:0.1em; padding:8px 0 4px; border-bottom:1px solid {DM_BORDER};
    margin-bottom:10px;
  }}
  hr {{ border-color:{DM_BORDER}; }}
  #MainMenu, footer {{ visibility:hidden; }}
  .stDeployButton {{ display:none; }}
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def delta_html(val, suffix=""):
    if val is None:
        return '<div class="tile-delta-neu">—</div>'
    sign  = "▲" if val > 0 else ("▼" if val < 0 else "")
    color = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    return f'<div class="tile-delta-{color}">{sign} {abs(val):.2f}{suffix}</div>'


def tile(label, value, delta="", cls=""):
    return (f'<div class="tile {cls}">'
            f'<div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>'
            f'{delta}</div>')


def fmt(v, prefix="$"):
    return f"{prefix}{v:.2f}" if v is not None else "—"

def fmt_loads(v):
    return f"{v:.1f}" if v is not None else "—"


# ── Data Fetching ────────────────────────────────────────────────────────────

def _lmr_session() -> requests.Session:
    """Requests session with retry + backoff for the slow USDA LMR API."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=3,           # waits 3, 9, 27 s between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


# persist="disk" survives app sleep/wake cycles — users never hit a cold fetch
@st.cache_data(ttl=7200, persist="disk", show_spinner=False)
def fetch_lmr(last_n: int = 260):
    """
    Pull allSections for the last N reports from the USDA LMR API.
    Returns a dict keyed by section name, each value a DataFrame.
    """
    url  = f"{LMR_BASE}/{REPORT_ID}/"
    sess = _lmr_session()
    resp = sess.get(url, params={"lastReports": last_n, "allSections": "true"}, timeout=60)
    resp.raise_for_status()

    payload = resp.json()
    sections = {}
    for sec in (payload if isinstance(payload, list) else [payload]):
        name    = sec.get("reportSection", "")
        results = sec.get("results", [])
        if results:
            df = pd.DataFrame(results)
            df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
            df = df.dropna(subset=["report_date"]).sort_values("report_date")
            sections[name] = df
    return sections


@st.cache_data(ttl=7200, persist="disk", show_spinner=False)
def fetch_grading_weekly() -> pd.DataFrame:
    """Fetch weekly Pct_Choice_CW from LMR report 2700 (lastReports=200 ≈ 4 yrs)."""
    url  = f"{LMR_BASE}/{GRADING_ID}/"
    sess = _lmr_session()
    resp = sess.get(url, params={"lastReports": 200, "allSections": "true"}, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    for sec in (payload if isinstance(payload, list) else [payload]):
        if sec.get("reportSection") == "Weekly Fed Cattle Comprehensive":
            df = pd.DataFrame(sec["results"])
            df["report_date"]    = pd.to_datetime(df["report_date"], errors="coerce")
            df["pct_choice"]     = pd.to_numeric(df.get("Pct_Choice_CW"), errors="coerce")
            df["published_date"] = df.get("published_date", "")
            return df[["report_date", "pct_choice", "published_date"]].dropna(subset=["report_date"]).sort_values("report_date")
    return pd.DataFrame()


def build_history(sections: dict) -> pd.DataFrame:
    """Merge Cutout + Volume sections into a clean daily DataFrame."""
    cutout = sections.get("Current Cutout Values", pd.DataFrame())
    volume = sections.get("Current Volume",        pd.DataFrame())

    if cutout.empty:
        raise ValueError("'Current Cutout Values' section returned no data.")

    df = cutout[["report_date"]].copy()
    df["choice"] = pd.to_numeric(cutout.get("choice_600_900_current"), errors="coerce")
    df["select"] = pd.to_numeric(cutout.get("select_600_900_current"), errors="coerce")
    df["spread"] = df["choice"] - df["select"]

    if not volume.empty:
        vol = volume[["report_date"]].copy()
        for c in ["choice_volume_loads", "select_volume_loads",
                  "trimmings_volume_loads", "coarse_volume_loads"]:
            vol[c] = pd.to_numeric(volume.get(c), errors="coerce")
        vol["total_loads"] = (
            vol["choice_volume_loads"].fillna(0) +
            vol["select_volume_loads"].fillna(0) +
            vol["trimmings_volume_loads"].fillna(0) +
            vol["coarse_volume_loads"].fillna(0)
        )
        vol["choice_loads"] = vol["choice_volume_loads"]
        vol["select_loads"] = vol["select_volume_loads"]
        df = df.merge(vol[["report_date", "total_loads", "choice_loads", "select_loads"]],
                      on="report_date", how="left")
    else:
        df["total_loads"]  = None
        df["choice_loads"] = None
        df["select_loads"] = None

    return df.reset_index(drop=True)


def changes(df: pd.DataFrame, col: str):
    """Return (current, day_chg, month_chg, year_chg)."""
    valid = df[df[col].notna()]
    if valid.empty:
        return None, None, None, None
    cur  = valid.iloc[-1]
    cval = cur[col]
    cdt  = cur["report_date"]

    def prior(delta):
        sub = valid[valid["report_date"] <= cdt - delta]
        return sub.iloc[-1][col] if not sub.empty else None

    p1   = prior(timedelta(days=2))
    p30  = prior(timedelta(days=30))
    p365 = prior(timedelta(days=365))

    return (
        cval,
        cval - p1   if p1   is not None else None,
        cval - p30  if p30  is not None else None,
        cval - p365 if p365 is not None else None,
    )


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image(JSA_LOGO_WHITE, use_container_width=True)
    st.markdown("<hr>", unsafe_allow_html=True)

    st.markdown('<div class="sec-header">History Window</div>', unsafe_allow_html=True)
    history_n = st.selectbox(
        "Reports to load",
        [130, 260, 400],
        index=1,
        format_func=lambda x: {130: "~6 Months", 260: "~1 Year", 400: "~18 Months"}[x],
        label_visibility="collapsed",
    )

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Data Refresh</div>', unsafe_allow_html=True)
    auto_refresh = st.toggle("Auto-refresh (30 min)", value=False)
    if st.button("↺  Refresh Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="color:{DM_MUTED};font-size:0.72rem;line-height:1.6;">'
        f'Source: USDA AMS Livestock Mandatory Reporting<br>'
        f'Report: <b>LM_XB403</b> (National Daily Boxed Beef Cutout &amp; Boxed Beef Cuts — PM)<br><br>'
        f'Published twice daily:<br>'
        f'&nbsp;&nbsp;AM ~10:30 CT &nbsp;·&nbsp; PM ~2:30 CT<br><br>'
        f'Cache: 30 min. Use <b>Refresh Now</b> to force reload.</div>',
        unsafe_allow_html=True,
    )


# ── Load Data ────────────────────────────────────────────────────────────────

with st.spinner("Loading USDA beef cutout data…"):
    try:
        sections = fetch_lmr(last_n=history_n)
        hist     = build_history(sections)
        load_ok  = True
        err_msg  = ""
    except Exception as e:
        load_ok  = False
        err_msg  = str(e)
        sections = {}
        hist     = pd.DataFrame()


# ── Header ───────────────────────────────────────────────────────────────────

c1, c2 = st.columns([7, 3])
with c1:
    st.markdown(
        f"<h1 style='color:{DM_TEXT};margin:0;padding:0;font-size:1.9rem;'>"
        "JSA - Daily Beef Cutout</h1>"
        f"<div style='color:{DM_MUTED};font-size:0.8rem;margin-top:2px;'>"
        "Choice &amp; Select Composite 600–900 lbs · USDA LMR LM_XB403</div>",
        unsafe_allow_html=True,
    )
with c2:
    if load_ok and not hist.empty:
        last_date = hist["report_date"].max()
        pub_date  = sections.get("Summary", pd.DataFrame())
        pub_str   = ""
        if not pub_date.empty and "published_date" in pub_date.columns:
            pub_str = pub_date.iloc[-1].get("published_date", "")
        st.markdown(
            f"<div style='text-align:right;color:{DM_MUTED};font-size:0.75rem;padding-top:6px;'>"
            f"Most recent report<br>"
            f"<span style='color:{JSA_GREEN_LT};font-size:1rem;font-weight:700;'>"
            f"{last_date.strftime('%b %d, %Y')}</span>"
            + (f"<br><span style='font-size:0.7rem;'>{pub_str}</span>" if pub_str else "")
            + "</div>",
            unsafe_allow_html=True,
        )

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)

if not load_ok:
    st.warning(
        "⏳ **USDA data temporarily unavailable** — the USDA LMR server is not responding. "
        "This usually resolves in a few minutes. Use **Refresh Now** in the sidebar to retry."
    )
    with st.expander("Technical details"):
        st.code(err_msg)
    st.stop()

if hist.empty:
    st.warning("No data returned from USDA LMR API.")
    st.stop()


# ── Compute Changes ──────────────────────────────────────────────────────────

cn, cd1, cd30, cd365 = changes(hist, "choice")
sn, sd1, sd30, sd365 = changes(hist, "select")
spn, spd1, spd30, _  = changes(hist, "spread")

vol_rows = hist[hist["total_loads"].notna()]
loads_now  = vol_rows.iloc[-1]["total_loads"]  if not vol_rows.empty else None
loads_prev = vol_rows.iloc[-2]["total_loads"]  if len(vol_rows) > 1  else None
loads_d1   = (loads_now - loads_prev) if (loads_now and loads_prev) else None


# ── Metric Tiles — Choice ────────────────────────────────────────────────────

st.markdown('<div class="sec-header">Choice Cutout — Composite 600–900 lbs</div>',
            unsafe_allow_html=True)
cols = st.columns(4)
with cols[0]:
    st.markdown(tile("Current", fmt(cn), cls="tile-choice"), unsafe_allow_html=True)
with cols[1]:
    st.markdown(tile("Day Change", fmt(cd1), delta_html(cd1), "tile-choice"), unsafe_allow_html=True)
with cols[2]:
    st.markdown(tile("Month Change", fmt(cd30), delta_html(cd30), "tile-choice"), unsafe_allow_html=True)
with cols[3]:
    st.markdown(tile("Year Change", fmt(cd365), delta_html(cd365), "tile-choice"), unsafe_allow_html=True)

st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# ── Metric Tiles — Select ────────────────────────────────────────────────────

st.markdown('<div class="sec-header">Select Cutout — Composite 600–900 lbs</div>',
            unsafe_allow_html=True)
cols = st.columns(4)
with cols[0]:
    st.markdown(tile("Current", fmt(sn), cls="tile-select"), unsafe_allow_html=True)
with cols[1]:
    st.markdown(tile("Day Change", fmt(sd1), delta_html(sd1), "tile-select"), unsafe_allow_html=True)
with cols[2]:
    st.markdown(tile("Month Change", fmt(sd30), delta_html(sd30), "tile-select"), unsafe_allow_html=True)
with cols[3]:
    st.markdown(tile("Year Change", fmt(sd365), delta_html(sd365), "tile-select"), unsafe_allow_html=True)

st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# ── Metric Tiles — Spread & Volume ──────────────────────────────────────────

st.markdown('<div class="sec-header">Choice–Select Spread &amp; Total Volume</div>',
            unsafe_allow_html=True)
cols = st.columns(4)
with cols[0]:
    st.markdown(tile("Choice–Select Spread", fmt(spn), delta_html(spd1), "tile-spread"),
                unsafe_allow_html=True)
with cols[1]:
    st.markdown(tile("Spread Month Change", fmt(spd30), delta_html(spd30), "tile-spread"),
                unsafe_allow_html=True)
with cols[2]:
    st.markdown(tile("Total Loads Today", fmt_loads(loads_now), cls="tile-vol"),
                unsafe_allow_html=True)
with cols[3]:
    st.markdown(tile("Loads Day Change", fmt_loads(loads_d1), delta_html(loads_d1, " lds"), "tile-vol"),
                unsafe_allow_html=True)


# ── Cutout Trend Chart ───────────────────────────────────────────────────────

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Cutout Trend</div>', unsafe_allow_html=True)

AXIS = dict(
    gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
    tickfont=dict(color=DM_MUTED, size=11),
    title_font=dict(color=DM_MUTED, size=11),
    zeroline=False,
)

fig = go.Figure()

# Spread fill (rendered first so it's behind the lines)
fig.add_trace(go.Scatter(
    x=pd.concat([hist["report_date"], hist["report_date"].iloc[::-1]]),
    y=pd.concat([hist["choice"], hist["select"].iloc[::-1]]),
    fill="toself",
    fillcolor="rgba(196,180,86,0.08)",
    line=dict(color="rgba(0,0,0,0)"),
    name="Spread",
    hoverinfo="skip",
))

fig.add_trace(go.Scatter(
    x=hist["report_date"], y=hist["choice"],
    name="Choice",
    mode="lines",
    line=dict(color=CHOICE_COLOR, width=2),
    hovertemplate="<b>Choice</b>: $%{y:.2f}<extra></extra>",
))

fig.add_trace(go.Scatter(
    x=hist["report_date"], y=hist["select"],
    name="Select",
    mode="lines",
    line=dict(color=SELECT_COLOR, width=2),
    hovertemplate="<b>Select</b>: $%{y:.2f}<extra></extra>",
))

fig.update_layout(
    paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
    font=dict(color=DM_TEXT, size=11),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(color=DM_TEXT, size=11), bgcolor="rgba(0,0,0,0)"),
    margin=dict(l=55, r=20, t=15, b=40),
    xaxis=dict(
        **AXIS, title="",
        rangeselector=dict(
            buttons=[
                dict(count=1,  label="1M",  step="month", stepmode="backward"),
                dict(count=3,  label="3M",  step="month", stepmode="backward"),
                dict(count=6,  label="6M",  step="month", stepmode="backward"),
                dict(count=1,  label="YTD", step="year",  stepmode="todate"),
                dict(count=1,  label="1Y",  step="year",  stepmode="backward"),
                dict(step="all", label="All"),
            ],
            bgcolor=DM_SURFACE, activecolor=JSA_GREEN,
            font=dict(color=DM_TEXT, size=10), bordercolor=DM_BORDER,
        ),
        rangeslider=dict(visible=False),
        type="date",
    ),
    yaxis=dict(**AXIS, title="$/cwt", tickprefix="$"),
    height=380,
)

st.plotly_chart(fig, use_container_width=True)


# ── Volume Chart ─────────────────────────────────────────────────────────────

if hist["total_loads"].notna().any():
    st.markdown('<div class="sec-header">Total Daily Loads</div>', unsafe_allow_html=True)

    vd = hist[hist["total_loads"].notna()].copy()
    ma = vd["total_loads"].rolling(10, min_periods=1).mean()

    fig_v = go.Figure()
    fig_v.add_trace(go.Bar(
        x=vd["report_date"], y=vd["total_loads"],
        name="Total Loads", marker_color=VOL_COLOR, marker_line_width=0,
        hovertemplate="<b>Total Loads</b>: %{y:.1f}<extra></extra>",
    ))
    fig_v.add_trace(go.Scatter(
        x=vd["report_date"], y=ma,
        name="10-Day Avg", mode="lines",
        line=dict(color=JSA_GREEN_LT, width=2, dash="dot"),
        hovertemplate="<b>10-Day Avg</b>: %{y:.1f}<extra></extra>",
    ))
    fig_v.update_layout(
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color=DM_TEXT, size=11), bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=55, r=20, t=15, b=40),
        xaxis=dict(**AXIS, title=""),
        yaxis=dict(**AXIS, title="Loads"),
        height=250, bargap=0.15,
    )
    st.plotly_chart(fig_v, use_container_width=True)


# ── Beef Grading Trend Chart ─────────────────────────────────────────────────

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Beef Carcass Grading — Choice &amp; Higher vs Select</div>',
            unsafe_allow_html=True)

# Fetch live weekly grading data (silent fail — chart still shows historical)
try:
    grade_wk = fetch_grading_weekly()
except Exception:
    grade_wk = pd.DataFrame()

# Build annual series from hardcoded history
grade_years   = sorted(ANNUAL_GRADES.keys())
choice_annual = [ANNUAL_GRADES[y][0] for y in grade_years]
select_annual = [ANNUAL_GRADES[y][1] for y in grade_years]

# Latest weekly point
latest_choice = None
latest_week   = None
latest_pub    = ""
if not grade_wk.empty:
    last_row      = grade_wk.iloc[-1]
    latest_choice = last_row["pct_choice"]
    latest_week   = last_row["report_date"]
    latest_pub    = str(last_row.get("published_date", ""))

# Current-year YTD average from weekly API data
cur_year = datetime.now().year
ytd_df   = grade_wk[grade_wk["report_date"].dt.year == cur_year] if not grade_wk.empty else pd.DataFrame()
ytd_avg  = float(ytd_df["pct_choice"].mean()) if not ytd_df.empty else None

fig_g = go.Figure()

# Choice & Higher line (annual)
fig_g.add_trace(go.Scatter(
    x=grade_years, y=choice_annual,
    name="Choice & Higher (Prime + Choice)",
    mode="lines+markers+text",
    line=dict(color=CHOICE_COLOR, width=2.5),
    marker=dict(size=7, color=CHOICE_COLOR),
    text=[f"{v:.1f}%" for v in choice_annual],
    textposition="top center",
    textfont=dict(size=9, color=CHOICE_COLOR),
    hovertemplate="<b>Choice & Higher</b>: %{y:.1f}%<extra></extra>",
))

# Select line (annual)
fig_g.add_trace(go.Scatter(
    x=grade_years, y=select_annual,
    name="Select",
    mode="lines+markers+text",
    line=dict(color=SELECT_COLOR, width=2.5),
    marker=dict(size=7, color=SELECT_COLOR),
    text=[f"{v:.1f}%" for v in select_annual],
    textposition="bottom center",
    textfont=dict(size=9, color=SELECT_COLOR),
    hovertemplate="<b>Select</b>: %{y:.1f}%<extra></extra>",
))

# YTD average diamond for current year
if ytd_avg is not None:
    fig_g.add_trace(go.Scatter(
        x=[cur_year], y=[ytd_avg],
        name=f"{cur_year} YTD Avg",
        mode="markers",
        marker=dict(size=14, symbol="diamond", color=CHOICE_COLOR,
                    line=dict(width=2, color=DM_TEXT)),
        hovertemplate=f"<b>{cur_year} YTD Avg</b>: %{{y:.1f}}%<extra></extra>",
    ))

# Latest weekly annotation marker
if latest_choice is not None:
    week_label = latest_week.strftime("%b %d, %Y") if latest_week else ""
    fig_g.add_trace(go.Scatter(
        x=[cur_year + 0.15], y=[latest_choice],
        name=f"Latest Weekly",
        mode="markers+text",
        marker=dict(size=12, symbol="diamond", color=COL_NEG,
                    line=dict(width=2, color=DM_TEXT)),
        text=[f"Latest Weekly: {latest_choice:.1f}%"],
        textposition="top right",
        textfont=dict(size=10, color=COL_NEG, family="Arial Black"),
        hovertemplate=f"<b>Latest Weekly ({week_label})</b>: %{{y:.1f}}%<extra></extra>",
    ))

fig_g.update_layout(
    paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
    font=dict(color=DM_TEXT, size=11),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                font=dict(color=DM_TEXT, size=11), bgcolor="rgba(0,0,0,0)"),
    margin=dict(l=55, r=30, t=30, b=40),
    xaxis=dict(
        gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
        tickfont=dict(color=DM_MUTED, size=11), title_font=dict(color=DM_MUTED),
        zeroline=False, title="Year", dtick=2,
    ),
    yaxis=dict(
        gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
        tickfont=dict(color=DM_MUTED, size=11), title_font=dict(color=DM_MUTED),
        zeroline=False, title="% of Graded Carcasses", ticksuffix="%",
        range=[0, 100],
    ),
    height=440,
)

st.plotly_chart(fig_g, use_container_width=True)

# Small caption
st.markdown(
    f'<div style="color:{DM_MUTED};font-size:0.7rem;margin-top:-10px;">'
    f'Annual averages 2000–2025 from USDA AMS. '
    f'Current-year YTD &amp; latest weekly from LMR LSWFEDCC (report 2700). '
    + (f'Latest weekly report: {latest_pub[:10]}.' if latest_pub else '')
    + '</div>',
    unsafe_allow_html=True,
)

# ── Data Table ───────────────────────────────────────────────────────────────

with st.expander("📋  Data Table"):
    display = hist.copy()
    display["report_date"] = display["report_date"].dt.strftime("%Y-%m-%d")
    display = display.rename(columns={
        "report_date":   "Date",
        "choice":        "Choice ($/cwt)",
        "select":        "Select ($/cwt)",
        "spread":        "Spread ($/cwt)",
        "total_loads":   "Total Loads",
        "choice_loads":  "Choice Loads",
        "select_loads":  "Select Loads",
    }).sort_values("Date", ascending=False).reset_index(drop=True)

    num_cols = {c: "${:.2f}" for c in ["Choice ($/cwt)", "Select ($/cwt)", "Spread ($/cwt)"]}
    num_cols.update({c: "{:.1f}" for c in ["Total Loads", "Choice Loads", "Select Loads"]
                     if c in display.columns})
    st.dataframe(display.style.format(num_cols, na_rep="—"),
                 use_container_width=True, height=320)

# ── Legal Disclaimer Footer ───────────────────────────────────────────────────

_disclaimer_year = datetime.now().year
st.markdown("<hr style='border-color:#3a3a3a;margin-top:32px;margin-bottom:16px'>", unsafe_allow_html=True)
st.markdown(
    f'<div style="color:#888;font-size:0.68rem;line-height:1.6;text-align:center;padding:0 24px 24px;">'
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

# ── Auto-refresh ─────────────────────────────────────────────────────────────

if auto_refresh:
    time.sleep(1800)
    st.cache_data.clear()
    st.rerun()
