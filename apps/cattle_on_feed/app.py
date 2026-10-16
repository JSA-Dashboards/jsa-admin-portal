"""
Cattle on Feed Dashboard — USDA NASS QuickStats
On-feed inventory, placements, marketings, and the quarterly heifers-on-feed
share (herd-cycle signal) for the 13 major feedlot states + US total.

Carries a second USDA report behind the switch at the top of the page: Cold
Storage end-of-month warehouse stocks, back to 1917. See cold_storage.py.

John Stewart & Associates
Data source: USDA NASS QuickStats API (https://quickstats.nass.usda.gov)
"""

import io
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Sibling modules for the COF Recap tab and the Cold Storage view. Safe under
# the portal's shared sys.modules despite the usual by-name collision trap —
# "cof_recap" and "cold_storage" each exist exactly once in the repo, unlike
# snowflake_db.py and friends.
sys.path.insert(0, str(Path(__file__).parent))
import cof_recap  # noqa: E402
import cold_storage  # noqa: E402
from nass_cache_client import fetch_cached  # noqa: E402

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

# Cattle on Feed and Cold Storage read NASS through the shared, scheduled-pull
# cache (usda-nass-etl: jobs/cattle_on_feed.py and jobs/cold_storage.py), so this
# page needs no NASS API key. nass_cache_client.py is vendored; keep it
# byte-identical to that repo's copy.

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

  /* The report switch, dressed as a tab bar so it reads as one with the tabs
     below it. It stays an st.segmented_control rather than becoming an
     st.tabs entry because a hidden Streamlit tab is hidden, not skipped: its
     body runs every rerun, so Cold Storage would pay for the nine-request
     Cattle on Feed load and vice versa. Same reason the Beef Trimmings page
     switches its two views this way. */
  [data-testid="stButtonGroup"] {{
    margin:0 0 14px 0; border-bottom:1px solid {DM_BORDER}; gap:0 !important;
  }}
  [data-testid="stButtonGroup"] > div {{ gap:0 !important; }}
  [data-testid="stButtonGroup"] button[data-variant="segmented_control"] {{
    background:transparent !important; border:none !important;
    border-bottom:2px solid transparent !important; border-radius:0 !important;
    box-shadow:none !important; color:{DM_MUTED} !important;
    font-size:0.95rem !important; font-weight:500 !important;
    padding:6px 20px 9px 20px !important; margin:0 !important;
  }}
  [data-testid="stButtonGroup"] button[data-variant="segmented_control"]:hover {{
    color:{DM_TEXT} !important;
  }}
  [data-testid="stButtonGroup"] button[aria-checked="true"] {{
    color:{JSA_GREEN} !important; border-bottom-color:{JSA_GREEN} !important;
    font-weight:700 !important;
  }}

  .cs-call {{
    background:{DM_SURFACE}; border:1px solid {DM_BORDER};
    border-left:4px solid {JSA_GREEN}; border-radius:8px;
    padding:16px 20px 14px; margin:2px 0 14px;
  }}
  .cs-call-lead {{ color:{DM_TEXT}; font-size:1.05rem; line-height:1.5; }}
  .cs-call-sub  {{ color:{DM_MUTED}; font-size:0.82rem; margin-top:8px; line-height:1.55; }}
  .run-table {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  .run-table th {{
    color:{DM_MUTED}; font-weight:500; text-transform:uppercase; font-size:0.66rem;
    letter-spacing:.06em; padding:6px 10px; border-bottom:1px solid {DM_BORDER}; text-align:right;
  }}
  .run-table th:first-child {{ text-align:left; }}
  .run-table td {{
    padding:6px 10px; border-bottom:1px solid {DM_BORDER}; text-align:right; color:{DM_TEXT};
  }}
  .run-table td:first-child {{ text-align:left; font-weight:600; }}
  .run-table tr:last-child td {{ border-bottom:none; }}
  .run-now td {{ background:{DM_SURFACE2}; }}
</style>
""", unsafe_allow_html=True)


# ── Data fetching ──────────────────────────────────────────────────────────────

def _month_num(reference_period_desc: str):
    if not reference_period_desc:
        return None
    token = reference_period_desc.strip().split()[-1].upper()
    return MONTHS.get(token)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_series(short_desc: str, years: tuple, domaincat_filter: str = None) -> pd.DataFrame:
    # Reads the shared NASS cache (usda-nass-etl jobs/cattle_on_feed.py), not NASS
    # live. The ETL caches ONE broad, unfiltered pull per series -- no year bounds,
    # no domaincat_desc -- because a key built from year__GE/year__LE (which shift
    # every January) would go stale annually and silently miss. The year range and
    # the 1,000+-head domaincat filter are applied locally below instead.
    params = {
        "source_desc":       "SURVEY",
        "sector_desc":       "ANIMALS & PRODUCTS",
        "group_desc":        "LIVESTOCK",
        "commodity_desc":    "CATTLE",
        "short_desc":        short_desc,
    }
    try:
        payload = fetch_cached(params)
    except Exception as e:
        st.error(f"NASS cache error: {e}")
        return pd.DataFrame(columns=["year", "month", "date", "agg_level_desc", "state_alpha", "Value"])
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
    df = df[(df["year"] >= min(years)) & (df["year"] <= max(years))]
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
    # The seasonality tab (year-over-year lines, YoY% bars, annual snapshots)
    # needs the same full-history depth for placements and marketings too.
    inv_full   = fetch_series("CATTLE, ON FEED - INVENTORY", qyears, CAP_1000)
    place_full = fetch_series("CATTLE, ON FEED - PLACEMENTS, MEASURED IN HEAD", qyears, CAP_1000)
    sales_full = fetch_series("CATTLE, ON FEED - SALES FOR SLAUGHTER, MEASURED IN HEAD", qyears, CAP_1000)
    return inv, place, sales, other, heifer, steer, inv_full, place_full, sales_full


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


YEAR_PALETTE = ["#e2e8e4", "#c8d4ca", "#a8bfae", "#8db89a", "#6fa8c4", "#9b89c4", "#c98a56", COL_NEG]


def seasonal_by_year_chart(df_full: pd.DataFrame, state: str, n_years: int = 7, y_title: str = "Head",
                            height: int = 420) -> go.Figure:
    """One line per year, Jan-Dec on the x-axis — classic seasonal overlay.
    Latest year drawn last (on top) in red so it stands out against the
    muted-to-bold palette used for prior years.
    """
    sub = series_for(df_full, state)
    if sub.empty:
        return go.Figure()
    years = sorted(sub["year"].unique())[-min(n_years, len(YEAR_PALETTE)):]
    colors = YEAR_PALETTE[-len(years):]

    fig = go.Figure()
    for yr, color in zip(years, colors):
        yr_df = sub[sub["year"] == yr].sort_values("month")
        fig.add_trace(go.Scatter(
            x=yr_df["month"], y=yr_df["Value"], mode="lines+markers", name=str(yr),
            line=dict(color=color, width=2.6 if yr == years[-1] else 1.8),
            marker=dict(size=5 if yr == years[-1] else 4),
        ))
    _apply(fig, height=height, y_title=y_title)
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)),
                      ticktext=[MONTH_ABBR[m] for m in range(1, 13)])
    return fig


def yoy_pct_frame(df_full: pd.DataFrame, state: str) -> pd.DataFrame:
    sub = series_for(df_full, state)[["year", "month", "date", "Value"]].copy()
    prior = sub.rename(columns={"Value": "prior_value", "year": "prior_year"})
    prior["year"] = prior["prior_year"] + 1
    m = sub.merge(prior[["year", "month", "prior_value"]], on=["year", "month"], how="left")
    m["yoy_pct"] = (m["Value"] - m["prior_value"]) / m["prior_value"] * 100
    return m.dropna(subset=["yoy_pct"]).sort_values("date").reset_index(drop=True)


def yoy_bar_chart(df_full: pd.DataFrame, state: str, height: int = 380) -> go.Figure:
    d = yoy_pct_frame(df_full, state)
    if d.empty:
        return go.Figure()
    colors = [COL_POS if v >= 0 else COL_NEG for v in d["yoy_pct"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["date"], y=d["yoy_pct"], marker_color=colors,
                          hovertemplate="%{x|%b %Y}: %{y:+.1f}%<extra></extra>"))
    _apply(fig, height=height, y_title="% change vs. year-ago")
    fig.update_yaxes(ticksuffix="%")
    fig.update_layout(showlegend=False)
    return fig


def annual_snapshot_chart(df_full: pd.DataFrame, state: str, month: int, height: int = 380) -> go.Figure:
    """One bar per year for a single calendar month — e.g. 'on-feed as of Aug 1'
    or 'placed on feed in April', going back across the full data history.
    """
    sub = series_for(df_full, state)
    d = sub[sub["month"] == month].sort_values("year")
    if d.empty:
        return go.Figure()
    colors = [COL_NEG if yr == d["year"].iloc[-1] else JSA_GREEN for yr in d["year"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["year"].astype(str), y=d["Value"], marker_color=colors,
                          hovertemplate="%{x}: %{y:,.0f}<extra></extra>"))
    _apply(fig, height=height, y_title="Head")
    fig.update_layout(showlegend=False)
    return fig


def _to_excel(sheets: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, index=False, sheet_name=name[:31])
    return buf.getvalue()


# ── Cold Storage ─────────────────────────────────────────────────────────────
# The second report on this page. Fetching and the MoM/YoY arithmetic live in
# cold_storage.py; everything below is this page's brand and layout, which is
# why it is here rather than there — same split as cof_recap.

CS_HEADLINE = ["Beef, total", "Pork, total", cold_storage.TOTAL_RED_MEAT]


@st.cache_data(ttl=3600, show_spinner=False)
def _cs_fetch(label: str) -> pd.DataFrame:
    return cold_storage.fetch_series(cold_storage.SERIES[label], _month_num)


@st.cache_data(ttl=3600, show_spinner=False)
def _cs_load(label: str) -> pd.DataFrame:
    if label == cold_storage.TOTAL_RED_MEAT:
        return cold_storage.combine({k: _cs_fetch(k) for k in cold_storage.RED_MEAT_PARTS})
    return _cs_fetch(label)


def _cs_mlb(lb) -> str:
    """Pounds in as million pounds out. USDA prints thousand pounds, which runs
    to six digits on every red-meat line and reads worse at a glance."""
    return "—" if lb is None or pd.isna(lb) else f"{lb / 1e6:,.1f}"


def _cs_card(label: str, frame: pd.DataFrame, accent: str = JSA_GREEN) -> str:
    kpi = cold_storage.latest(frame)
    if not kpi:
        return _snap_card(label, "—", "", _dc(None), _dc(None), accent=accent)
    return _snap_card(
        label, _cs_mlb(kpi["value"]), "million lb",
        _dc(kpi["mom"], "+.1f", "%") + " " + _dc(kpi["mom_abs"] / 1e6 if kpi["mom_abs"] is not None else None, "+,.1f", "M"),
        _dc(kpi["yoy"], "+.1f", "%") + " " + _dc(kpi["yoy_abs"] / 1e6 if kpi["yoy_abs"] is not None else None, "+,.1f", "M"),
        accent=accent, foot=kpi["date"].strftime("%b %Y"),
    )


def _cs_span(run: dict) -> str:
    if run["start"] == run["end"]:
        return run["start"].strftime("%b %Y")
    return f'{run["start"]:%b %Y} – {run["end"]:%b %Y}'


def _cs_callout(label: str, frame: pd.DataFrame) -> str:
    """The question this view exists to answer: when was this last building?

    Written against YEAR-OVER-YEAR, not month-over-month. Cold storage beef
    fills from September into December and empties through the summer every
    single year, so an MoM rise in October says nothing about the market. The
    streaks below are months above year-ago.
    """
    kpi = cold_storage.latest(frame)
    if not kpi or kpi["yoy"] is None:
        return ""

    rising    = cold_storage.yoy_runs(frame, rising=True)
    falling   = cold_storage.yoy_runs(frame, rising=False)
    building  = kpi["yoy"] > 0
    current   = (rising if building else falling)
    current   = current[-1] if current and current[-1]["end"] == kpi["date"] else None
    n         = current["months"] if current else 0
    streak    = "month" if n == 1 else "months"

    lead = (
        f'<b>{label}</b> stocks are <b style="color:{COL_POS if building else COL_NEG}">'
        f'{"building" if building else "drawing down"}</b>. '
        f'{kpi["date"]:%B %Y} came in at {_cs_mlb(kpi["value"])} million lb, '
        f'{kpi["yoy"]:+.1f}% on the year and {kpi["mom"]:+.1f}% on the month — '
        f'{n} straight {streak} {"above" if building else "below"} year-ago.'
    )

    # When stocks are building, the useful comparison is the run before this
    # one; when they are not, it is the last run of any length that was.
    prior = [r for r in rising if current is None or r["end"] < current["start"]]
    if prior:
        p = prior[-1]
        gap = (f'{"Before this, the" if building else "The"} last run above year-ago was '
               f'<b>{_cs_span(p)}</b> — {p["months"]} {"month" if p["months"] == 1 else "months"}, '
               f'averaging {p["avg"]:+.1f}%.')
    else:
        gap = "No earlier run above year-ago in the published history."

    longest = max(rising, key=lambda r: r["months"]) if rising else None
    best = (f' Longest on record: <b>{_cs_span(longest)}</b>, {longest["months"]} months.'
            if longest else "")

    return (f'<div class="cs-call"><div class="cs-call-lead">{lead}</div>'
            f'<div class="cs-call-sub">{gap}{best}</div></div>')


def _cs_runs_table(frame: pd.DataFrame, n: int = 12) -> str:
    runs = cold_storage.yoy_runs(frame, rising=True)
    if not runs:
        return '<div class="cs-call-sub">No months above year-ago in the published history.</div>'
    kpi = cold_storage.latest(frame)
    tag = (f'&nbsp;<span style="font-weight:400;color:{JSA_GREEN}">current</span>')
    rows = []
    for r in runs[-n:][::-1]:
        live = bool(kpi) and r["end"] == kpi["date"]
        rows.append(
            f'<tr class="{"run-now" if live else ""}">'
            f'<td>{_cs_span(r)}{tag if live else ""}</td>'
            f'<td>{r["months"]}</td>'
            f'<td class="pos">{r["avg"]:+.1f}%</td>'
            f'<td class="pos">{r["peak"]:+.1f}%</td></tr>'
        )
    return ('<table class="run-table"><thead><tr><th>Months above year-ago</th>'
            '<th>Length</th><th>Avg YoY</th><th>Peak YoY</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def _cs_history_chart(frame: pd.DataFrame, label: str, height: int = 420) -> go.Figure:
    d = frame.dropna(subset=["value"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=d["date"], y=d["value"] / 1e6, mode="lines", name=label,
        line=dict(color=JSA_GREEN, width=1.8),
        hovertemplate="%{x|%b %Y}: %{y:,.1f}M lb<extra></extra>",
    ))
    _apply(fig, height=height, y_title="Million lb")
    fig.update_layout(showlegend=False)
    return fig


def _cs_yoy_chart(frame: pd.DataFrame, height: int = 380) -> go.Figure:
    d = frame.dropna(subset=["yoy"])
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=d["date"], y=d["yoy"],
        marker_color=[COL_POS if v >= 0 else COL_NEG for v in d["yoy"]],
        hovertemplate="%{x|%b %Y}: %{y:+.1f}%<extra></extra>",
    ))
    _apply(fig, height=height, y_title="% change vs. year-ago")
    fig.update_yaxes(ticksuffix="%")
    fig.update_layout(showlegend=False, bargap=0)
    return fig


def _cs_season_chart(frame: pd.DataFrame, n_years: int = 7, height: int = 420) -> go.Figure:
    d = frame.dropna(subset=["value"]).copy()
    if d.empty:
        return go.Figure()
    d["year"], d["month"] = d["date"].dt.year, d["date"].dt.month
    years  = sorted(d["year"].unique())[-min(n_years, len(YEAR_PALETTE)):]
    colors = YEAR_PALETTE[-len(years):]
    fig = go.Figure()
    for yr, color in zip(years, colors):
        yd = d[d["year"] == yr].sort_values("month")
        fig.add_trace(go.Scatter(
            x=yd["month"], y=yd["value"] / 1e6, mode="lines+markers", name=str(yr),
            line=dict(color=color, width=2.6 if yr == years[-1] else 1.8),
            marker=dict(size=5 if yr == years[-1] else 4),
        ))
    _apply(fig, height=height, y_title="Million lb")
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)),
                      ticktext=[MONTH_ABBR[m] for m in range(1, 13)])
    return fig


def render_cold_storage() -> None:
    labels = list(cold_storage.SERIES) + [cold_storage.TOTAL_RED_MEAT]
    label = st.sidebar.selectbox("Commodity", labels, index=0)

    st.sidebar.divider()
    st.sidebar.markdown(
        f'<div style="color:{DM_MUTED};font-size:.68rem;line-height:1.6">'
        f'Stocks are end-of-month, released about three weeks later — the '
        f'{cold_storage.FIRST_YEAR.get(label, "")} start is the whole published '
        f'history for this series, national only. Each release also restates '
        f'the month before it, so a prior figure here can move.</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Loading USDA Cold Storage history…"):
        raw = _cs_load(label)
        heads = {k: cold_storage.monthly_frame(_cs_load(k)) for k in CS_HEADLINE}

    frame = cold_storage.monthly_frame(raw)
    kpi   = cold_storage.latest(frame)

    hdr_l, hdr_r = st.columns([4, 1])
    with hdr_l:
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:24px;padding:10px 0 8px">
          <img src="{JSA_LOGO_FULL}" style="height:68px" />
          <div>
            <div style="font-size:2rem;font-weight:700;color:{DM_TEXT};line-height:1.1;letter-spacing:-0.01em">
              JSA - USDA Cold Storage
            </div>
            <div style="color:{DM_MUTED};font-size:0.88rem;margin-top:5px;letter-spacing:.02em">
              {label} &nbsp;·&nbsp; USDA NASS QuickStats &nbsp;·&nbsp; End-of-month stocks, all warehouses, United States
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)
    with hdr_r:
        # Stocks are AS OF the last calendar day of the month. The frame keys
        # months on the 1st, so the header has to roll to month-end or it
        # reads "Aug 01" for a figure USDA labels "August 31".
        _first = frame["date"].min().strftime("%b %Y") if not frame.empty else "N/A"
        _last  = (kpi["date"] + pd.offsets.MonthEnd(0)).strftime("%b %d, %Y") if kpi else "N/A"
        st.markdown(f"""
        <div style="text-align:right;padding-top:6px;font-size:0.75rem">
          <div style="color:{DM_MUTED};font-size:0.6rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">Stocks as of</div>
          <div style="color:{DM_TEXT};font-weight:700;font-size:0.9rem;margin-bottom:8px">{_last}</div>
          <div style="color:{DM_MUTED};font-size:0.6rem;text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px">History from</div>
          <div style="color:{DM_TEXT};font-weight:700;font-size:0.9rem">{_first}</div>
        </div>
        """, unsafe_allow_html=True)
    st.divider()

    if not kpi:
        st.error("No data returned from USDA NASS QuickStats for this series — "
                 "the shared NASS cache has no rows for it (usda-nass-etl jobs/cold_storage.py).")
        return

    tab_over, tab_hist, tab_season, tab_data = st.tabs([
        "⭐  Overview", "📈  Full History", "📅  Seasonality", "📋  Data",
    ], on_change="rerun")

    with tab_over:
        if tab_over.open:
            cards = [label] + [k for k in CS_HEADLINE if k != label]
            cols = st.columns(len(cards))
            for col, name in zip(cols, cards):
                with col:
                    f = frame if name == label else heads[name]
                    st.markdown(_cs_card(name, f, JSA_GREEN if name == label else JSA_GREEN_LT),
                                unsafe_allow_html=True)

            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
            st.markdown(_cs_callout(label, frame), unsafe_allow_html=True)

            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown('<div class="sec-hdr">Year-over-year change, last 10 years</div>',
                            unsafe_allow_html=True)
                recent = frame[frame["date"] >= kpi["date"] - pd.DateOffset(years=10)]
                st.plotly_chart(_cs_yoy_chart(recent), width="stretch")
            with c2:
                st.markdown('<div class="sec-hdr">Runs above year-ago</div>', unsafe_allow_html=True)
                st.markdown(_cs_runs_table(frame), unsafe_allow_html=True)

    with tab_hist:
        if tab_hist.open:
            span = st.radio("Window", ["10 years", "25 years", "50 years", "All"],
                            index=1, horizontal=True, key="cs_span")
            cut = {"10 years": 10, "25 years": 25, "50 years": 50}.get(span)
            d = frame if cut is None else frame[frame["date"] >= kpi["date"] - pd.DateOffset(years=cut)]
            st.plotly_chart(_cs_history_chart(d, label), width="stretch")
            st.markdown('<div class="sec-hdr">Year-over-year change, same window</div>',
                        unsafe_allow_html=True)
            st.plotly_chart(_cs_yoy_chart(d, height=320), width="stretch")
            st.caption(
                f"{label} · {frame['date'].min():%b %Y} – {kpi['date']:%b %Y} · "
                f"{int(frame['value'].notna().sum()):,} months published"
                + (f", {int(frame['value'].isna().sum())} not reported"
                   if frame["value"].isna().any() else "")
            )

    with tab_season:
        if tab_season.open:
            n_years = st.slider("Years overlaid", 3, 8, 7, key="cs_years")
            st.plotly_chart(_cs_season_chart(frame, n_years), width="stretch")
            st.caption("Each line is one calendar year of end-of-month stocks. The build "
                       "from late summer into winter is the seasonal pattern that makes "
                       "month-over-month a poor read on its own.")

    with tab_data:
        if tab_data.open:
            out = frame.dropna(subset=["value"]).copy()
            out = out.sort_values("date", ascending=False)
            # Thousand pounds, which is the unit USDA's own tables print, so a row
            # here can be checked against the PDF without arithmetic.
            table = pd.DataFrame({
                "Month":         out["date"].dt.strftime("%Y-%m"),
                "Stocks (1,000 lb)": (out["value"] / 1e3).round(0),
                "MoM (1,000 lb)":    (out["mom_abs"] / 1e3).round(0),
                "MoM %":             out["mom"].round(2),
                "YoY (1,000 lb)":    (out["yoy_abs"] / 1e3).round(0),
                "YoY %":             out["yoy"].round(2),
            })
            _lb_col  = st.column_config.NumberColumn(format="%,.0f")
            _pct_col = st.column_config.NumberColumn(format="%.2f%%")
            st.dataframe(
                table, width="stretch", hide_index=True, height=520,
                column_config={
                    "Stocks (1,000 lb)": _lb_col, "MoM (1,000 lb)": _lb_col,
                    "YoY (1,000 lb)": _lb_col, "MoM %": _pct_col, "YoY %": _pct_col,
                },
            )
            d1, d2 = st.columns(2)
            stem = label.lower().replace(", ", "_").replace(" ", "_").replace("(", "").replace(")", "")
            with d1:
                st.download_button("⬇  CSV", table.to_csv(index=False).encode(),
                                   f"cold_storage_{stem}.csv", "text/csv",
                                   width="stretch")
            with d2:
                st.download_button("⬇  Excel", _to_excel({"Cold Storage": table}),
                                   f"cold_storage_{stem}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   width="stretch")
            # The report that carries a month's stocks is published the FOLLOWING
            # month, so August stocks live in cost0926.pdf — hence the roll, and
            # the year roll with it for a December figure.
            _rep = kpi["date"] + pd.DateOffset(months=1)
            st.caption(
                "Source: USDA NASS QuickStats — "
                f"`{cold_storage.SERIES.get(label, 'sum of ' + ', '.join(cold_storage.RED_MEAT_PARTS))}`. "
                f"Released report: {cold_storage.report_url(_rep.year, _rep.month)}"
            )


# ── Report switch ────────────────────────────────────────────────────────────
# Two different USDA reports, not two views of one. Cold Storage asks what is
# in the freezer rather than what is in the yard, and it reads its own series,
# so it sits behind a switch: on the Cold Storage view the Cattle on Feed
# QuickStats load never runs, and on the Cattle on Feed view the cold storage
# one never does.
#
# It is placed ABOVE the load and above the st.stop() that guards it, which is
# the other half of the point: a QuickStats outage on the six Cattle on Feed
# series cannot take Cold Storage down with it.

VIEW_COF = "Cattle on Feed"
VIEW_CS  = "Cold Storage"

view = st.segmented_control(
    "Report", (VIEW_COF, VIEW_CS), default=VIEW_COF,
    label_visibility="collapsed", key="cof_view",
) or VIEW_COF          # deselecting the active segment returns None


# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.markdown(
    f'<div style="padding:10px 0 6px"><img src="{JSA_LOGO_WHITE}" style="width:160px;opacity:0.92" /></div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<div style="background:{JSA_GREEN};border-radius:4px;padding:5px 10px;'
    f'font-size:.7rem;color:#fff;font-weight:600;letter-spacing:.08em;'
    f'text-transform:uppercase;margin-bottom:10px">{view}</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<span style="color:{DM_MUTED};font-size:.72rem">'
    + ("USDA NASS · End-of-month warehouse stocks"
       if view == VIEW_CS else "USDA NASS · Feedlots, 1,000+ head")
    + '</span>',
    unsafe_allow_html=True,
)
st.sidebar.divider()

if view == VIEW_CS:
    render_cold_storage()
    st.stop()

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

# ── Header slot ────────────────────────────────────────────────────
# The header is written into this container further down, once the QuickStats
# data is in hand. Reserving its position here lets the tab bar and the COF
# Recap tab render BEFORE the load, so a QuickStats failure cannot take down a
# tab that never needed QuickStats. On a failure the container carries the
# error message instead of the header.
header_slot = st.container()

# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_summary, tab_recap, tab_flows, tab_season, tab_heifer, tab_state, tab_data = st.tabs([
    "⭐  Summary", "📄  COF Recap", "📊  On-Feed & Flows", "📅  Seasonality", "🐄  Heifers on Feed", "🗺️  State Comparison", "📋  Data",
], on_change="rerun")

# ── COF Recap ─────────────────────────────────────────────────────────────────
# The client one-pager, drawn BEFORE the QuickStats load on purpose: it reads
# USDA's released report text over plain HTTP and needs neither that API nor a
# key, so an outage there must not take it down. Tab display order is set by
# st.tabs, not by where these blocks sit, so it still shows up second.
# Deliberately NOT built off the QuickStats frames the
# rest of this page uses: it reads USDA's released report text so the state
# percentages are USDA's own rounded figures rather than ours, and so the
# weight-class breakdown (absent from the series above) comes along with them.


@st.cache_data(ttl=3600, show_spinner=False)
def _latest_recap():
    """(recap dict, error string). Cached so the tab does not refetch per rerun."""
    year, month, text = cof_recap.latest_report()
    if not text:
        return None, "Could not reach the USDA report file at nass.usda.gov."
    prior = cof_recap.fetch_report(year - 1, month)
    return cof_recap.build_recap(year, month, text, prior), ""


# The guesses are the one thing on the recap that cannot be re-derived, so they
# live in the URL rather than in widget state alone: a reload, a session
# timeout or an app reboot would otherwise mean retyping them, and the filled-in
# link can be bookmarked or handed to someone else.
_QP_GUESS = {"on_feed": "g_onfeed", "placed": "g_placed", "marketed": "g_mkt"}


def _qp_float(key: str):
    try:
        return float(st.query_params[key])
    except (KeyError, TypeError, ValueError):
        return None


def _qp_write(key: str, text: str):
    """Set or clear one query param, only when it actually changes."""
    current = st.query_params.get(key)
    if not text:
        if current is not None:
            del st.query_params[key]
    elif current != text:
        st.query_params[key] = text


@st.cache_data(show_spinner=False, max_entries=8)
def _recap_image(fig_json: str, fmt: str) -> bytes | None:
    try:
        import plotly.io as pio
        kw = {"scale": 2} if fmt == "png" else {}
        return pio.from_json(fig_json).to_image(format=fmt, **kw)
    except Exception:
        return None


with tab_recap:
    if tab_recap.open:
        recap, err = _latest_recap()
        if err:
            st.error(err)
        else:
            st.markdown('<div class="sec-hdr">Pre-report analyst estimates</div>',
                        unsafe_allow_html=True)
            st.caption("The only figures USDA does not publish — type in whatever survey "
                       "you quote to clients. Everything else is read from the release.")
            g1, g2, g3, g4 = st.columns([1, 1, 1, 2])
            # value= seeds the widget from the URL on first render only; after that
            # the explicit key owns the state and the write-back below keeps the URL
            # in step.
            guesses = {
                "on_feed":  g1.number_input("On-Feed guess",  value=_qp_float("g_onfeed"),
                                            step=0.1, format="%.1f", placeholder="101.8",
                                            key="cof_g_onfeed"),
                "placed":   g2.number_input("Placed guess",   value=_qp_float("g_placed"),
                                            step=0.1, format="%.1f", placeholder="96.8",
                                            key="cof_g_placed"),
                "marketed": g3.number_input("Marketed guess", value=_qp_float("g_mkt"),
                                            step=0.1, format="%.1f", placeholder="96.1",
                                            key="cof_g_mkt"),
            }
            guess_source = g4.text_input("Source label (footer)",
                                         value=st.query_params.get("g_src", ""),
                                         key="cof_g_src")
            show_footer = st.checkbox("Show source footer on the page", value=True)

            for _key, _param in _QP_GUESS.items():
                _val = guesses[_key]
                _qp_write(_param, "" if _val is None else f"{_val:.1f}")
            _qp_write("g_src", guess_source.strip())
            if any(v is not None for v in guesses.values()):
                st.caption("Your guesses are in the page URL — bookmark it, or send it on, "
                           "and it reopens filled in.")

            st.divider()
            fig = cof_recap.build_figure(recap, guesses=guesses, footer=show_footer,
                                         guess_source=guess_source)
            left, right = st.columns([3, 2])
            with left:
                st.plotly_chart(fig, config={"displayModeBar": False})
            with right:
                released = recap["release_date"]
                st.markdown(
                    f'<div class="sec-hdr">{recap["title"]}</div>'
                    f'<p style="color:{DM_MUTED};font-size:.82rem;line-height:1.5">'
                    f'Released {released:%B %d, %Y}.<br>'
                    f'On-feed as of the 1st; placements and marketings for '
                    f'{recap["placement_month"]}.</p>', unsafe_allow_html=True)
                stem = f"{cof_recap.MONTH_ABBR[recap['month'] - 1]}_{recap['year']}_COF_Report"
                # Gated behind a button, like livestock_seasonal's export_row: a
                # hidden tab still runs every rerun, and to_image spins up Chromium,
                # so rendering eagerly would tax every widget on the whole page.
                if st.button("Prepare download", width="stretch",
                             help="Renders the page above as PNG and PDF."):
                    st.session_state["recap_export_ready"] = True
                if st.session_state.get("recap_export_ready"):
                    fig_json = fig.to_json()
                    with st.spinner("Rendering…"):
                        png, pdf = _recap_image(fig_json, "png"), _recap_image(fig_json, "pdf")
                    if png:
                        st.download_button("Download PNG", png, file_name=f"{stem}.png",
                                           mime="image/png", width="stretch")
                    if pdf:
                        st.download_button("Download PDF", pdf, file_name=f"{stem}.pdf",
                                           mime="application/pdf", width="stretch")
                    if not png and not pdf:
                        st.warning("Image export failed on the host. The table above still "
                                   "renders — use the camera icon on its toolbar.")
                st.caption(f"Source: {cof_recap.report_url(recap['year'], recap['month'])}")


# ── Load data ────────────────────────────────────────────────────────────────

# Spinner goes in the reserved header slot, not here: this block now runs after
# the tab bar has been drawn, so an un-slotted spinner would appear underneath
# the tab content instead of at the top of the page where the header is landing.
with header_slot:
    with st.spinner("Loading USDA NASS data…"):
        inv, place, sales, other, heifer, steer, inv_full, place_full, sales_full = load_all(LOAD_YEARS, Q_YEARS)

if inv.empty:
    with header_slot:
        st.error("No data returned from USDA NASS QuickStats — check the API key "
                 "in st.secrets. The COF Recap tab reads USDA's released report "
                 "file directly and is unaffected; the tabs that need this data "
                 "will be empty.")
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

hdr_l, hdr_r = header_slot.columns([4, 1])
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
header_slot.divider()

# ── Summary ────────────────────────────────────────────────────────────────────
with tab_summary:
    if tab_summary.open:
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
    if tab_flows.open:
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

# ── Seasonality ────────────────────────────────────────────────────────────────
with tab_season:
    if tab_season.open:
        SEASON_METRICS = {
            "On-feed inventory": {"df": inv_full, "verb": "on feed as of"},
            "Placements":        {"df": place_full, "verb": "placed on feed in"},
            "Marketings":        {"df": sales_full, "verb": "marketed in"},
        }
        season_metric = st.radio("Metric", list(SEASON_METRICS.keys()), horizontal=True, label_visibility="collapsed")
        m = SEASON_METRICS[season_metric]
        m_df = m["df"]
        m_sub = series_for(m_df, state)

        if m_sub.empty:
            st.info("No data available for this metric/state.")
        else:
            latest_month = int(m_sub["month"].iloc[-1])
            month_label  = MONTH_ABBR[latest_month]

            st.markdown(f'<div class="sec-hdr">{season_metric} by year — seasonal pattern</div>', unsafe_allow_html=True)
            st.caption(f"Each line is one year, Jan–Dec. Latest year ({int(m_sub['year'].iloc[-1])}) highlighted in red.")
            st.plotly_chart(seasonal_by_year_chart(m_df, state, n_years=trend_years), width="stretch")

            st.markdown(f'<div class="sec-hdr">{season_metric} — year-over-year % change</div>', unsafe_allow_html=True)
            st.plotly_chart(yoy_bar_chart(m_df, state), width="stretch")

            st.markdown(f'<div class="sec-hdr">{STATE_NAMES.get(state, state)} cattle {m["verb"]} {month_label} — by year</div>',
                        unsafe_allow_html=True)
            st.caption("Same calendar month, every year back to 1996 — isolates the year-over-year trend from seasonality.")
            st.plotly_chart(annual_snapshot_chart(m_df, state, latest_month), width="stretch")

# ── Heifers on Feed ───────────────────────────────────────────────────────────
with tab_heifer:
    if tab_heifer.open:
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
    if tab_state.open:
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
    if tab_data.open:
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
