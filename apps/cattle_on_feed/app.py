"""
Cattle on Feed Dashboard — USDA NASS QuickStats
On-feed inventory, placements, marketings, and the quarterly heifers-on-feed
share (herd-cycle signal) for the 13 major feedlot states + US total.

John Stewart & Associates
Data source: USDA NASS QuickStats API (https://quickstats.nass.usda.gov)
"""

import io
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ── JSA brand ────────────────────────────────────────────────────────────────
JSA_GREEN    = "#5e7164"
JSA_GREEN_LT = "#8db89a"
DM_BG        = "#f6f8f7"
DM_SURFACE   = "#ffffff"
DM_SURFACE2  = "#eef3f0"
DM_BORDER    = "#d7e2dc"
DM_TEXT      = "#32373c"
DM_MUTED     = "#5f7267"
COL_POS      = "#16a34a"
COL_NEG      = "#dc2626"
COL_NEU      = "#5f7267"
STEER_COLOR  = "#8db89a"
HEIFER_COLOR = "#6fa8c4"

JSA_LOGO_FULL  = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"
JSA_LOGO_WHITE = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"

try:
    API_KEY = st.secrets.get("NASS_API_KEY", "9A6D1EB8-4D94-3221-BA0C-ADD4533EA0C1")
except Exception:
    API_KEY = "9A6D1EB8-4D94-3221-BA0C-ADD4533EA0C1"

BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"

# The 13 states NASS publishes individually in the Cattle on Feed report
# (1,000+ head feedlots); "OT" is NASS's "Other States" catch-all.
STATE_ORDER = ["US", "TX", "NE", "KS", "CO", "IA", "OK", "SD", "AZ", "CA", "ID", "MN", "WA", "OT"]
STATE_NAMES = {
    "US": "United States", "TX": "Texas", "NE": "Nebraska", "KS": "Kansas",
    "CO": "Colorado", "IA": "Iowa", "OK": "Oklahoma", "SD": "South Dakota",
    "AZ": "Arizona", "CA": "California", "ID": "Idaho", "MN": "Minnesota",
    "WA": "Washington", "OT": "Other states",
}
MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
          "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
MONTH_ABBR = {v: k.title() for k, v in MONTHS.items()}

# st.set_page_config removed — the Livestock Portal shell (Home.py) makes the
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
  .snap-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:6px 10px; }}
  .snap-item {{ display:flex; flex-direction:column; }}
  .snap-lbl {{
    color:{DM_MUTED}; font-size:0.65rem; text-transform:uppercase; letter-spacing:.06em;
  }}
  .snap-pos {{ color:{COL_POS}; font-size:0.88rem; font-weight:600; }}
  .snap-neg {{ color:{COL_NEG}; font-size:0.88rem; font-weight:600; }}
  .snap-neu {{ color:{COL_NEU}; font-size:0.88rem; }}

  .sum-table {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .sum-table th {{
    color:{DM_MUTED}; font-weight:500; text-transform:uppercase; font-size:0.68rem;
    letter-spacing:.06em; padding:6px 10px; border-bottom:1px solid {DM_BORDER}; text-align:right;
  }}
  .sum-table th:first-child {{ text-align:left; }}
  .sum-table td {{
    padding:7px 10px; border-bottom:1px solid {DM_BORDER}; text-align:right; color:{DM_TEXT};
  }}
  .sum-table td:first-child {{ text-align:left; font-weight:600; }}
  .sum-table tr:last-child td {{ border-bottom:none; }}
  .pos {{ color:{COL_POS}; }} .neg {{ color:{COL_NEG}; }}

  .stTabs [data-baseweb="tab-list"] {{
    background:{DM_SURFACE}; border-radius:10px; padding:6px 8px; gap:6px; border:1px solid {DM_BORDER};
  }}
  .stTabs [data-baseweb="tab"] {{
    color:{DM_MUTED}; font-size:1rem; font-weight:600; letter-spacing:.02em;
    padding:10px 28px; border-radius:7px; border-bottom:none !important;
    transition:background .15s, color .15s;
  }}
  .stTabs [data-baseweb="tab"]:hover {{ background:{DM_SURFACE2}; color:{DM_TEXT}; }}
  .stTabs [aria-selected="true"] {{ color:#fff !important; background:{JSA_GREEN} !important; }}
  .stTabs [data-baseweb="tab-highlight"] {{ display:none !important; }}
  .stTabs [data-baseweb="tab-border"]    {{ display:none !important; }}
  .sec-hdr {{
    color:{DM_MUTED}; font-size:0.72rem; text-transform:uppercase; letter-spacing:.1em; margin:14px 0 6px;
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


def _month_num(reference_period_desc: str):
    if not reference_period_desc:
        return None
    token = reference_period_desc.strip().split()[-1].upper()
    return MONTHS.get(token)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_series(short_desc: str, years: tuple, domaincat_filter: str = None) -> pd.DataFrame:
    # Single ranged request (year__GE/year__LE) instead of one call per year —
    # NASS API supports range suffixes and this stays well under its 50k-row cap.
    params = {
        "key":               API_KEY,
        "source_desc":       "SURVEY",
        "sector_desc":       "ANIMALS & PRODUCTS",
        "group_desc":        "LIVESTOCK",
        "commodity_desc":    "CATTLE",
        "short_desc":        short_desc,
        "year__GE":          min(years),
        "year__LE":          max(years),
        "format":            "JSON",
    }
    payload = _nass_get(params)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        return pd.DataFrame(columns=["year", "month", "date", "agg_level_desc", "state_alpha", "Value"])

    df = pd.DataFrame(data)
    if domaincat_filter:
        df = df[df["domaincat_desc"] == domaincat_filter]

    df["Value"] = pd.to_numeric(df["Value"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df["month"] = df["reference_period_desc"].apply(_month_num)
    df = df.dropna(subset=["Value", "month"]).copy()
    df["month"] = df["month"].astype(int)
    df["year"] = df["year"].astype(int)
    df["date"] = pd.to_datetime(dict(year=df["year"], month=df["month"], day=1))
    df["state_alpha"] = df["state_alpha"].where(df["agg_level_desc"] != "NATIONAL", "US")
    keep = ["year", "month", "date", "agg_level_desc", "state_alpha", "Value"]
    return df[keep].sort_values("date").reset_index(drop=True)


CAP_1000 = "CAPACITY: (1,000 OR MORE HEAD)"


@st.cache_data(ttl=3600, show_spinner=False)
def load_all(years: tuple, qyears: tuple):
    inv      = fetch_series("CATTLE, ON FEED - INVENTORY", years, CAP_1000)
    place    = fetch_series("CATTLE, ON FEED - PLACEMENTS, MEASURED IN HEAD", years, CAP_1000)
    sales    = fetch_series("CATTLE, ON FEED - SALES FOR SLAUGHTER, MEASURED IN HEAD", years, CAP_1000)
    other    = fetch_series("CATTLE, ON FEED - DISAPPEARANCE, OTHER, MEASURED IN HEAD", years, CAP_1000)
    heifer   = fetch_series("CATTLE, HEIFERS & HEIFER CALVES, ON FEED - INVENTORY", qyears)
    steer    = fetch_series("CATTLE, STEERS & STEER CALVES, ON FEED - INVENTORY", qyears)
    # Heifer/steer share needs the on-feed total over the SAME full history as
    # the quarterly heifer/steer series, not just the shorter monthly window
    # used for the flows tabs — fetched separately to keep that window fast.
    inv_full = fetch_series("CATTLE, ON FEED - INVENTORY", qyears, CAP_1000)
    return inv, place, sales, other, heifer, steer, inv_full


# ── Analytics helpers ────────────────────────────────────────────────────────

def series_for(df: pd.DataFrame, state: str) -> pd.DataFrame:
    return df[df["state_alpha"] == state].sort_values("date").reset_index(drop=True)


def latest_kpi(df: pd.DataFrame, state: str) -> dict:
    nan = dict(current=float("nan"), mom=float("nan"), mom_pct=float("nan"),
               yoy=float("nan"), yoy_pct=float("nan"), date=None)
    sub = series_for(df, state)
    if sub.empty:
        return nan
    latest = sub.iloc[-1]
    current, date = float(latest["Value"]), latest["date"]

    prior = sub[sub["date"] < date]
    if not prior.empty:
        prev_val = float(prior.iloc[-1]["Value"])
        mom = current - prev_val
        mom_pct = mom / prev_val * 100 if prev_val else float("nan")
    else:
        mom = mom_pct = float("nan")

    ly = sub[(sub["year"] == latest["year"] - 1) & (sub["month"] == latest["month"])]
    if not ly.empty:
        ly_val = float(ly.iloc[0]["Value"])
        yoy = current - ly_val
        yoy_pct = yoy / ly_val * 100 if ly_val else float("nan")
    else:
        yoy = yoy_pct = float("nan")

    return dict(current=current, mom=mom, mom_pct=mom_pct, yoy=yoy, yoy_pct=yoy_pct, date=date)


def heifer_pct_frame(heifer: pd.DataFrame, steer: pd.DataFrame, inv: pd.DataFrame, state: str) -> pd.DataFrame:
    """Heifer/steer share of total on-feed inventory for the shared quarterly months."""
    h = series_for(heifer, state)[["date", "Value"]].rename(columns={"Value": "heifers"})
    s = series_for(steer, state)[["date", "Value"]].rename(columns={"Value": "steers"})
    t = series_for(inv, state)[["date", "Value"]].rename(columns={"Value": "total"})
    m = h.merge(s, on="date", how="outer").merge(t, on="date", how="inner").sort_values("date")
    m["heifer_pct"] = m["heifers"] / m["total"] * 100
    m["steer_pct"]  = m["steers"] / m["total"] * 100
    return m.reset_index(drop=True)


def _dc(val: float, fmt: str = "+.1f", suffix: str = "") -> str:
    if pd.isna(val):
        return '<span class="snap-neu">—</span>'
    cls = "snap-pos" if val >= 0 else "snap-neg"
    sign = "+" if val >= 0 else ""
    return f'<span class="{cls}">{sign}{val:{fmt[1:]}}{suffix}</span>'


def _snap_item(label: str, delta_html: str) -> str:
    return f'<div class="snap-item"><span class="snap-lbl">{label}</span>{delta_html}</div>'


def _snap_card(title: str, value_str: str, unit: str, mom_html: str, yoy_html: str,
               mom_lbl: str = "MoM", yoy_lbl: str = "YoY", accent: str = JSA_GREEN,
               foot: str = "") -> str:
    return f"""
    <div class="snap-card">
      <div class="snap-class" style="color:{accent}">{title}</div>
      <div class="snap-value">{value_str} <span style="font-size:0.9rem;color:{DM_MUTED}">{unit}</span></div>
      <div class="snap-grid">
        {_snap_item(mom_lbl, mom_html)}
        {_snap_item(yoy_lbl, yoy_html)}
      </div>
      {f'<div style="margin-top:8px;font-size:0.7rem;color:{DM_MUTED}">{foot}</div>' if foot else ''}
    </div>"""


def _base_layout(title: str = "", height: int = 420, y_title: str = "") -> dict:
    return dict(
        title=dict(text=title, font=dict(color=DM_TEXT, size=13), x=0),
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0, font=dict(size=11)),
        margin=dict(l=50, r=20, t=40, b=40),
        hovermode="x unified", height=height,
    )


AXIS_STYLE = dict(gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True)


def _apply(fig, title="", height=420, y_title=""):
    fig.update_layout(**_base_layout(title, height, y_title))
    fig.update_xaxes(**AXIS_STYLE)
    fig.update_yaxes(**AXIS_STYLE, title_text=y_title, autorange=True)


def heifer_share_bar_chart(hp: pd.DataFrame, avg_years: int = 15, height: int = 420) -> go.Figure:
    """Quarterly heifer-share-of-on-feed bar chart, JSA house style:
    steel-blue bars, latest quarter highlighted red, dashed avg reference
    line over the trailing `avg_years`, and a callout box on the latest bar.
    """
    d = hp.dropna(subset=["heifer_pct"]).sort_values("date").reset_index(drop=True)
    if d.empty:
        return go.Figure()

    latest_date = d["date"].iloc[-1]
    avg_start = pd.Timestamp(year=max(d["date"].dt.year.min(), latest_date.year - avg_years + 1), month=1, day=1)
    avg_window = d[d["date"] >= avg_start]
    avg_val = float(avg_window["heifer_pct"].mean())

    colors = [COL_NEG if i == len(d) - 1 else HEIFER_COLOR for i in range(len(d))]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["date"], y=d["heifer_pct"], marker_color=colors, name="Heifer share",
                          hovertemplate="%{x|%b %Y}: %{y:.1f}%<extra></extra>"))
    fig.add_hline(y=avg_val, line=dict(color="#c98a56", width=1.6, dash="dash"),
                  annotation_text=f"Avg ({avg_window['date'].dt.year.min()}–{latest_date.year}) = {avg_val:.1f}%",
                  annotation_position="top left",
                  annotation_font=dict(color="#c98a56", size=11))

    latest_val = float(d["heifer_pct"].iloc[-1])
    fig.add_annotation(
        x=latest_date, y=latest_val, text=f"<b>{latest_val:.1f}%</b>",
        showarrow=False, xanchor="left", yanchor="middle", xshift=36,
        font=dict(color=COL_NEG, size=13),
        bordercolor=COL_NEG, borderwidth=1.4, borderpad=5, bgcolor=DM_SURFACE,
    )

    _apply(fig, height=height, y_title="Share of total on-feed inventory")
    fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(dtick="M24", tickformat="%Y")
    fig.update_layout(showlegend=False, margin=dict(l=50, r=70, t=40, b=40))
    return fig


def _to_excel(sheets: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, index=False, sheet_name=name[:31])
    return buf.getvalue()


# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.markdown(
    f'<div style="padding:10px 0 6px"><img src="{JSA_LOGO_WHITE}" style="width:160px;opacity:0.92" /></div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<div style="background:{JSA_GREEN};border-radius:4px;padding:5px 10px;'
    f'font-size:.7rem;color:#fff;font-weight:600;letter-spacing:.08em;'
    f'text-transform:uppercase;margin-bottom:10px">Cattle on Feed</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<span style="color:{DM_MUTED};font-size:.72rem">USDA NASS · Feedlots, 1,000+ head</span>',
    unsafe_allow_html=True,
)
st.sidebar.divider()

current_year = datetime.now().year
LOAD_YEARS  = tuple(range(current_year - 8, current_year + 1))
Q_YEARS     = tuple(range(1996, current_year + 1))  # full history — NASS series starts 1996

state = st.sidebar.selectbox(
    "State", STATE_ORDER, format_func=lambda s: STATE_NAMES.get(s, s),
)
trend_years = st.sidebar.slider("Trend window (years)", 2, 8, 5)

st.sidebar.divider()
st.sidebar.markdown(
    f'<div style="color:{DM_MUTED};font-size:.68rem;line-height:1.6">'
    f'On-feed inventory, placements, and marketings are published monthly '
    f'(mid-month release). The heifer/steer split is published quarterly, in the '
    f'Jan, Apr, Jul, and Oct reports.</div>',
    unsafe_allow_html=True,
)

# ── Load data ────────────────────────────────────────────────────────────────

with st.spinner("Loading USDA NASS data…"):
    inv, place, sales, other, heifer, steer, inv_full = load_all(LOAD_YEARS, Q_YEARS)

if inv.empty:
    st.error("No data returned from USDA NASS. Check your API key in st.secrets.")
    st.stop()

inv_s    = series_for(inv, state)
place_s  = series_for(place, state)
sales_s  = series_for(sales, state)
other_s  = series_for(other, state)
hpct     = heifer_pct_frame(heifer, steer, inv_full, state)

inv_kpi   = latest_kpi(inv, state)
place_kpi = latest_kpi(place, state)
sales_kpi = latest_kpi(sales, state)

latest_date   = inv_kpi["date"]
latest_h_row  = hpct.dropna(subset=["heifer_pct"]).iloc[-1] if not hpct.dropna(subset=["heifer_pct"]).empty else None
prior_h_rows  = hpct.dropna(subset=["heifer_pct"])
prior_h_row   = prior_h_rows.iloc[-2] if len(prior_h_rows) >= 2 else None
yoy_h_row     = None
if latest_h_row is not None:
    yoy_match = prior_h_rows[
        (prior_h_rows["date"].dt.year == latest_h_row["date"].year - 1) &
        (prior_h_rows["date"].dt.month == latest_h_row["date"].month)
    ]
    if not yoy_match.empty:
        yoy_h_row = yoy_match.iloc[0]

# ── Header ───────────────────────────────────────────────────────────────────

hdr_l, hdr_r = st.columns([4, 1])
with hdr_l:
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:24px;padding:10px 0 8px">
      <img src="{JSA_LOGO_FULL}" style="height:68px" />
      <div>
        <div style="font-size:2rem;font-weight:700;color:{DM_TEXT};line-height:1.1;letter-spacing:-0.01em">
          JSA - USDA Cattle on Feed
        </div>
        <div style="color:{DM_MUTED};font-size:0.88rem;margin-top:5px;letter-spacing:.02em">
          {STATE_NAMES.get(state, state)} &nbsp;·&nbsp; USDA NASS QuickStats &nbsp;·&nbsp; Feedlots with 1,000+ head capacity
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
with hdr_r:
    _inv_str = latest_date.strftime('%b %d, %Y') if latest_date is not None else "N/A"
    _h_str   = latest_h_row["date"].strftime('%b %Y') if latest_h_row is not None else "N/A"
    st.markdown(f"""
    <div style="text-align:right;padding-top:6px;font-size:0.75rem">
      <div style="color:{DM_MUTED};font-size:0.6rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">On-feed data</div>
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:6px">
        <span style="color:{DM_MUTED}">As of</span>
        <span style="color:{DM_TEXT};font-weight:700;font-size:0.9rem">{_inv_str}</span>
      </div>
      <div style="color:{HEIFER_COLOR};font-size:0.6rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">Heifer/steer split</div>
      <div style="display:flex;justify-content:flex-end;gap:8px;align-items:baseline;margin-bottom:6px">
        <span style="color:{DM_MUTED}">As of</span>
        <span style="color:{HEIFER_COLOR};font-weight:700;font-size:0.9rem">{_h_str}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)
st.divider()

# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_summary, tab_flows, tab_heifer, tab_state, tab_data = st.tabs([
    "⭐  Summary", "📊  On-Feed & Flows", "🐄  Heifers on Feed", "🗺️  State Comparison", "📋  Data",
])

# ── Summary ────────────────────────────────────────────────────────────────────
with tab_summary:
    cols = st.columns(4)

    with cols[0]:
        st.markdown(_snap_card(
            "On-Feed Inventory", f'{inv_kpi["current"]:,.0f}', "head",
            _dc(inv_kpi["mom"], "+,.0f", " hd") + " " + _dc(inv_kpi["mom_pct"], "+.1f", "%"),
            _dc(inv_kpi["yoy"], "+,.0f", " hd") + " " + _dc(inv_kpi["yoy_pct"], "+.1f", "%"),
            foot=inv_kpi["date"].strftime("%b %Y") if inv_kpi["date"] is not None else "",
        ), unsafe_allow_html=True)

    with cols[1]:
        st.markdown(_snap_card(
            "Placements", f'{place_kpi["current"]:,.0f}', "head",
            _dc(place_kpi["mom"], "+,.0f", " hd") + " " + _dc(place_kpi["mom_pct"], "+.1f", "%"),
            _dc(place_kpi["yoy"], "+,.0f", " hd") + " " + _dc(place_kpi["yoy_pct"], "+.1f", "%"),
            accent="#c98a56",
            foot=place_kpi["date"].strftime("%b %Y") if place_kpi["date"] is not None else "",
        ), unsafe_allow_html=True)

    with cols[2]:
        st.markdown(_snap_card(
            "Marketings", f'{sales_kpi["current"]:,.0f}', "head",
            _dc(sales_kpi["mom"], "+,.0f", " hd") + " " + _dc(sales_kpi["mom_pct"], "+.1f", "%"),
            _dc(sales_kpi["yoy"], "+,.0f", " hd") + " " + _dc(sales_kpi["yoy_pct"], "+.1f", "%"),
            accent="#9b89c4",
            foot=sales_kpi["date"].strftime("%b %Y") if sales_kpi["date"] is not None else "",
        ), unsafe_allow_html=True)

    with cols[3]:
        if latest_h_row is not None:
            hp = float(latest_h_row["heifer_pct"])
            qoq = hp - float(prior_h_row["heifer_pct"]) if prior_h_row is not None else float("nan")
            yoy = hp - float(yoy_h_row["heifer_pct"]) if yoy_h_row is not None else float("nan")
            st.markdown(_snap_card(
                "Heifers on Feed", f'{hp:,.1f}', "% of on-feed",
                _dc(qoq, "+.1f", " pts"), _dc(yoy, "+.1f", " pts"),
                mom_lbl="QoQ", yoy_lbl="YoY", accent=HEIFER_COLOR,
                foot=latest_h_row["date"].strftime("%b %Y"),
            ), unsafe_allow_html=True)
        else:
            st.markdown(_snap_card("Heifers on Feed", "—", "% of on-feed", "—", "—",
                                    accent=HEIFER_COLOR), unsafe_allow_html=True)

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    st.markdown(f'<div class="sec-hdr">On-feed inventory — trend</div>', unsafe_allow_html=True)
    cutoff = pd.Timestamp(latest_date) - pd.DateOffset(years=trend_years) if latest_date is not None else None
    plot_df = inv_s[inv_s["date"] >= cutoff] if cutoff is not None else inv_s
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=plot_df["date"], y=plot_df["Value"], mode="lines",
                              line=dict(color=JSA_GREEN, width=2.2), name="On-feed inventory"))
    _apply(fig, height=340, y_title="Head")
    st.plotly_chart(fig, width="stretch")

    st.markdown(f'<div class="sec-hdr">Heifer share of on-feed inventory — the herd-cycle signal</div>', unsafe_allow_html=True)
    st.caption("A rising heifer share means fewer heifers are being held back for breeding — a sign herd liquidation is "
               "continuing. A falling share signals more heifers being retained, i.e. herd rebuilding. "
               f"Heifers & heifer calves ÷ total on-feed inventory, both from feedlots with 1,000+ head capacity, "
               f"quarterly (Jan/Apr/Jul/Oct) since 1996. State: {STATE_NAMES.get(state, state)}.")
    st.plotly_chart(heifer_share_bar_chart(hpct), width="stretch")

# ── On-Feed & Flows ───────────────────────────────────────────────────────────
with tab_flows:
    st.markdown(f'<div class="sec-hdr">On-feed inventory</div>', unsafe_allow_html=True)
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=inv_s["date"], y=inv_s["Value"], mode="lines",
                               line=dict(color=JSA_GREEN, width=2.2), name="Inventory"))
    _apply(fig1, height=380, y_title="Head")
    st.plotly_chart(fig1, width="stretch")

    st.markdown(f'<div class="sec-hdr">Placements vs marketings vs other disappearance</div>', unsafe_allow_html=True)
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=place_s["date"], y=place_s["Value"], name="Placements", marker_color="#c98a56"))
    fig2.add_trace(go.Bar(x=sales_s["date"], y=sales_s["Value"], name="Marketings", marker_color="#9b89c4"))
    fig2.add_trace(go.Bar(x=other_s["date"], y=other_s["Value"], name="Other disappearance", marker_color="#c4b456"))
    fig2.update_layout(barmode="group")
    _apply(fig2, height=380, y_title="Head")
    st.plotly_chart(fig2, width="stretch")

    st.markdown(f'<div class="sec-hdr">Monthly detail — last 18 months</div>', unsafe_allow_html=True)
    merged = (inv_s[["date", "Value"]].rename(columns={"Value": "On-feed inventory"})
              .merge(place_s[["date", "Value"]].rename(columns={"Value": "Placements"}), on="date", how="outer")
              .merge(sales_s[["date", "Value"]].rename(columns={"Value": "Marketings"}), on="date", how="outer")
              .merge(other_s[["date", "Value"]].rename(columns={"Value": "Other disappearance"}), on="date", how="outer")
              .sort_values("date"))
    merged = merged.tail(18).iloc[::-1].copy()
    merged["date"] = merged["date"].dt.strftime("%b %Y")
    st.dataframe(merged, hide_index=True, width="stretch")

# ── Heifers on Feed ───────────────────────────────────────────────────────────
with tab_heifer:
    st.markdown(f'<div class="sec-hdr">Heifer share of cattle on feed — {STATE_NAMES.get(state, state)}</div>',
                unsafe_allow_html=True)
    st.caption("Heifers & Heifer Calves ÷ Total Cattle On Feed (Inventory), both filtered to feedlots with "
               "1,000+ head capacity, quarterly since 1996 (USDA NASS QuickStats, SURVEY program).")
    st.plotly_chart(heifer_share_bar_chart(hpct, height=440), width="stretch")

    st.markdown(f'<div class="sec-hdr">Heifer & steer counts on feed — {STATE_NAMES.get(state, state)}</div>',
                unsafe_allow_html=True)
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=hpct["date"], y=hpct["heifers"], mode="lines+markers", name="Heifers & heifer calves",
                               line=dict(color=HEIFER_COLOR, width=2.2)))
    fig3.add_trace(go.Scatter(x=hpct["date"], y=hpct["steers"], mode="lines+markers", name="Steers & steer calves",
                               line=dict(color=STEER_COLOR, width=2.2)))
    _apply(fig3, height=380, y_title="Head")
    st.plotly_chart(fig3, width="stretch")

    st.markdown(f'<div class="sec-hdr">Heifer vs steer share of on-feed inventory</div>', unsafe_allow_html=True)
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=hpct["date"], y=hpct["heifer_pct"], mode="lines+markers", name="Heifers %",
                               line=dict(color=HEIFER_COLOR, width=2.2)))
    fig4.add_trace(go.Scatter(x=hpct["date"], y=hpct["steer_pct"], mode="lines+markers", name="Steers %",
                               line=dict(color=STEER_COLOR, width=2.2)))
    _apply(fig4, height=340, y_title="% of on-feed inventory")
    st.plotly_chart(fig4, width="stretch")

    st.markdown(f'<div class="sec-hdr">Latest quarter by state</div>', unsafe_allow_html=True)
    if latest_h_row is not None:
        latest_q_date = latest_h_row["date"]
        rows = []
        for s in STATE_ORDER:
            r = heifer_pct_frame(heifer, steer, inv_full, s)
            match = r[r["date"] == latest_q_date]
            if not match.empty:
                m = match.iloc[0]
                rows.append({
                    "State": STATE_NAMES.get(s, s),
                    "Heifers (head)": m["heifers"],
                    "Steers (head)": m["steers"],
                    "Total on feed": m["total"],
                    "Heifer %": m["heifer_pct"],
                })
        state_tbl = pd.DataFrame(rows).sort_values("Heifers (head)", ascending=False)
        st.dataframe(
            state_tbl, hide_index=True, width="stretch",
            column_config={
                "Heifers (head)": st.column_config.NumberColumn(format="%,.0f"),
                "Steers (head)": st.column_config.NumberColumn(format="%,.0f"),
                "Total on feed": st.column_config.NumberColumn(format="%,.0f"),
                "Heifer %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
    else:
        st.info("No quarterly heifer/steer data available yet for this window.")

# ── State Comparison ──────────────────────────────────────────────────────────
with tab_state:
    st.markdown(f'<div class="sec-hdr">On-feed inventory by state — latest month</div>', unsafe_allow_html=True)
    comp_rows = []
    for s in STATE_ORDER:
        if s == "US":
            continue
        k = latest_kpi(inv, s)
        comp_rows.append({"State": STATE_NAMES.get(s, s), "state_alpha": s,
                           "Inventory": k["current"], "YoY %": k["yoy_pct"]})
    comp_df = pd.DataFrame(comp_rows).dropna(subset=["Inventory"]).sort_values("Inventory", ascending=False)

    fig5 = go.Figure()
    fig5.add_trace(go.Bar(x=comp_df["State"], y=comp_df["Inventory"], marker_color=JSA_GREEN))
    _apply(fig5, height=380, y_title="Head")
    st.plotly_chart(fig5, width="stretch")

    st.markdown(f'<div class="sec-hdr">Year-over-year change by state</div>', unsafe_allow_html=True)
    fig6 = go.Figure()
    colors = [COL_POS if v >= 0 else COL_NEG for v in comp_df["YoY %"].fillna(0)]
    fig6.add_trace(go.Bar(x=comp_df["State"], y=comp_df["YoY %"], marker_color=colors))
    _apply(fig6, height=320, y_title="% change vs year ago")
    st.plotly_chart(fig6, width="stretch")

    st.dataframe(
        comp_df[["State", "Inventory", "YoY %"]], hide_index=True, width="stretch",
        column_config={
            "Inventory": st.column_config.NumberColumn(format="%,.0f"),
            "YoY %": st.column_config.NumberColumn(format="%+.1f%%"),
        },
    )

# ── Data ───────────────────────────────────────────────────────────────────────
with tab_data:
    st.markdown(f'<div class="sec-hdr">Raw series — {STATE_NAMES.get(state, state)}</div>', unsafe_allow_html=True)

    dl_col1, dl_col2 = st.columns([1, 5])
    with dl_col1:
        excel_bytes = _to_excel({
            "On-feed inventory": inv_s, "Placements": place_s, "Marketings": sales_s,
            "Other disappearance": other_s, "Heifer-steer split": hpct,
        })
        st.download_button("Download Excel", excel_bytes, file_name=f"cattle_on_feed_{state}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    _date_col = st.column_config.DateColumn("date", format="MMM YYYY")
    _head_col = st.column_config.NumberColumn(format="%,.0f")
    _pct_col  = st.column_config.NumberColumn(format="%.1f%%")

    st.markdown("**On-feed inventory (monthly)**")
    st.dataframe(inv_s[["date", "Value"]].sort_values("date", ascending=False), hide_index=True, width="stretch",
                 column_config={"date": _date_col, "Value": _head_col})

    st.markdown("**Placements (monthly)**")
    st.dataframe(place_s[["date", "Value"]].sort_values("date", ascending=False), hide_index=True, width="stretch",
                 column_config={"date": _date_col, "Value": _head_col})

    st.markdown("**Marketings (monthly)**")
    st.dataframe(sales_s[["date", "Value"]].sort_values("date", ascending=False), hide_index=True, width="stretch",
                 column_config={"date": _date_col, "Value": _head_col})

    st.markdown("**Heifer / steer split (quarterly)**")
    st.dataframe(hpct.sort_values("date", ascending=False), hide_index=True, width="stretch",
                 column_config={"date": _date_col, "heifers": _head_col, "steers": _head_col,
                                 "total": _head_col, "heifer_pct": _pct_col, "steer_pct": _pct_col})
