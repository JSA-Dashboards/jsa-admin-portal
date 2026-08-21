"""
JSA Grain Rail Shipments Dashboard
====================================
Data source: USDA AMS agtransport.usda.gov (live API, cached 1 hr)
Run: streamlit run streamlit_app.py
"""

import sys
import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

# st.set_page_config removed — the JSA Admin Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

# Import plotly AFTER set_page_config so any failure shows in the browser
try:
    import plotly.graph_objects as go
except Exception as _plotly_err:
    st.error(f"plotly import failed: {_plotly_err}")
    st.stop()

# Import local module AFTER set_page_config for the same reason
try:
    import usda_api
except Exception as _usda_err:
    st.error(f"usda_api import failed: {_usda_err}")
    st.stop()

# ─────────────────────────────────────────────
# CONSTANTS & COLORS
# ─────────────────────────────────────────────
BASE = Path(__file__).parent

# JSA brand palette
C = {
    "BG":      "#0e1614",
    "CARD":    "#162019",
    "CARD2":   "#1e2e2a",
    "BORDER":  "#243328",
    "PRIMARY": "#4a5d58",
    "TEXT":    "#d4e8e4",
    "DIM":     "#7a9990",
    "MID":     "#a8c5bf",
    "POS":     "#4ade80",
    "NEG":     "#f87171",
    "BLUE":    "#4aa3dc",
    "GOLD":    "#fbbf24",
}

# Railroad colors
RR_COLORS = {
    "BNSF":    "#4a9d8c",
    "CN":      "#a78bfa",
    "CP":      "#60a5fa",
    "CPKC":    "#34d399",
    "CP/CPKC": "#60a5fa",
    "CSX":     "#f87171",
    "KCS":     "#e879f9",
    "NS":      "#fbbf24",
    "UP":      "#fb923c",
}

MONTH_ORDER = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

WESTERN_STATES = ["IA","NE","SD","ND","MN","KS","MO"]
EASTERN_STATES = ["IL","IN","OH","MI","KY"]

# ─────────────────────────────────────────────
# CSS INJECTION — JSA dark theme
# ─────────────────────────────────────────────
st.markdown(f"""
<style>
  /* Global background */
  .stApp, .main, [data-testid="stAppViewContainer"] {{
      background-color: {C['BG']} !important;
      color: {C['TEXT']} !important;
  }}
  /* Sidebar */
  [data-testid="stSidebar"] {{ background-color: {C['CARD']} !important; }}
  /* All block containers */
  .block-container {{ padding-top: 0 !important; background-color: {C['BG']}; }}
  /* Metric cards */
  [data-testid="stMetric"] {{
      background-color: {C['CARD']} !important;
      border: 1px solid {C['BORDER']} !important;
      border-radius: 8px !important;
      padding: 12px 16px !important;
  }}
  [data-testid="stMetricValue"] {{ color: {C['TEXT']} !important; font-size: 1.5rem !important; }}
  [data-testid="stMetricDelta"] {{ font-size: 0.85rem !important; }}
  [data-testid="stMetricLabel"] {{ color: {C['MID']} !important; font-size: 0.8rem !important; }}
  /* Tabs */
  .stTabs [data-baseweb="tab-list"] {{
      background-color: {C['CARD']} !important;
      border-bottom: 1px solid {C['BORDER']} !important;
      gap: 2px;
  }}
  .stTabs [data-baseweb="tab"] {{
      background-color: transparent !important;
      color: {C['DIM']} !important;
      border-radius: 6px 6px 0 0 !important;
      padding: 8px 18px !important;
      font-size: 0.85rem;
  }}
  .stTabs [aria-selected="true"] {{
      background-color: {C['CARD2']} !important;
      color: {C['TEXT']} !important;
      border-top: 2px solid {C['POS']} !important;
  }}
  .stTabs [data-baseweb="tab-panel"] {{
      background-color: {C['BG']} !important;
      padding-top: 12px !important;
  }}
  /* Selectbox / radio / multiselect */
  .stSelectbox > div > div,
  .stMultiSelect > div > div {{
      background-color: {C['CARD']} !important;
      border: 1px solid {C['BORDER']} !important;
      color: {C['TEXT']} !important;
  }}
  .stRadio > div {{ color: {C['MID']} !important; }}
  label[data-testid="stWidgetLabel"] {{ color: {C['MID']} !important; font-size: 0.8rem; }}
  /* Dataframe */
  [data-testid="stDataFrame"] {{ background-color: {C['CARD']} !important; }}
  .dvn-scroller {{ background-color: {C['CARD']} !important; }}
  /* Captions */
  .stCaption {{ color: {C['DIM']} !important; }}
  /* Dividers */
  hr {{ border-color: {C['BORDER']} !important; }}
  /* Scrollbars */
  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: {C['BG']}; }}
  ::-webkit-scrollbar-thumb {{ background: {C['PRIMARY']}; border-radius: 3px; }}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# BASE PLOTLY LAYOUT
# ─────────────────────────────────────────────
def base_layout(**kwargs):
    """Return a dict of common Plotly layout settings with JSA dark theme."""
    layout = dict(
        paper_bgcolor=C["CARD"],
        plot_bgcolor=C["CARD"],
        font=dict(color=C["MID"], family="Inter, sans-serif", size=11),
        margin=dict(l=8, r=8, t=30, b=8),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(0,0,0,0)",
            font=dict(color=C["MID"], size=10),
        ),
        xaxis=dict(
            gridcolor=C["BORDER"],
            zerolinecolor=C["BORDER"],
            tickfont=dict(color=C["DIM"]),
        ),
        yaxis=dict(
            gridcolor=C["BORDER"],
            zerolinecolor=C["BORDER"],
            tickfont=dict(color=C["DIM"]),
        ),
    )
    layout.update(kwargs)
    return layout

# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────
def oly_avg(vals):
    """Olympic average: drop highest and lowest, return mean of rest.
    Requires at least 4 values; otherwise returns simple mean (or 0 if empty).
    """
    v = [x for x in vals if x is not None and not np.isnan(x)]
    if not v:
        return 0
    if len(v) >= 4:
        v_sorted = sorted(v)
        v_trimmed = v_sorted[1:-1]
        return float(np.mean(v_trimmed))
    return float(np.mean(v))


def pct(curr, base):
    """Percent change from base to curr. Returns None if base == 0."""
    if not base:
        return None
    return round((curr / base - 1) * 100, 1)


def fbu(n):
    """Format bushel counts: >=1B → '1.23B', >=1M → '12.3M', >=1K → '123K', else int."""
    n = float(n)
    if abs(n) >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(int(n))


def fdiff(curr, base):
    """Format difference as '+12.3M' or '—' if base is 0."""
    if not base:
        return "—"
    diff = curr - base
    sign = "+" if diff >= 0 else ""
    return f"{sign}{fbu(diff)}"


def fpct(v):
    """Format percent as '+12.3%' or '—' if None."""
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def bar_color(v):
    """Return POS or NEG color based on sign of v."""
    return C["POS"] if (v is not None and v >= 0) else C["NEG"]


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────
VALID_STATES = [
    'AL','AR','AZ','CA','CO','CT','DE','FL','GA','IA','ID','IL','IN','KS',
    'KY','LA','MA','MD','ME','MI','MN','MO','MS','MT','NC','ND','NE','NH',
    'NJ','NM','NV','NY','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT',
    'VA','VT','WA','WI','WV','WY',
]

# ── Sidebar — data source controls ───────────────────────────────────────────
with st.sidebar:
    st.markdown(
        f"<div style='color:{C['TEXT']};font-size:14px;font-weight:600;"
        f"margin-bottom:8px;'>Data Source</div>",
        unsafe_allow_html=True,
    )
    app_token = st.text_input(
        "USDA App Token (optional)",
        type="password",
        help="Free token from agtransport.usda.gov — increases rate limits.",
    )
    if st.button("🔄 Refresh from Live API"):
        st.cache_data.clear()
        st.session_state["force_api"] = True
        st.rerun()
    st.caption("Dashboard loads from bundled data.\nUse button above for latest.")
    st.divider()
    st.caption("KCS reported as national total only (no state breakdown).")


PARQUET_PATH = BASE / "data" / "rail_data.parquet"


@st.cache_data(ttl=3600)
def load_from_api(token: str = ""):
    df = usda_api.load_usda_data(app_token=token or None)
    return df, datetime.now().strftime("%b %d %Y %I:%M %p")


@st.cache_data
def load_from_file():
    df = pd.read_parquet(PARQUET_PATH)
    ts = datetime.fromtimestamp(PARQUET_PATH.stat().st_mtime).strftime("%b %d %Y")
    return df, ts


# Check st.secrets for a server-side token (set in Streamlit Cloud Secrets)
_secret_token = ""
try:
    _secret_token = st.secrets.get("USDA_APP_TOKEN", "") or ""
except Exception:
    pass

_effective_token = app_token or _secret_token

if st.session_state.get("force_api"):
    with st.spinner("Fetching latest USDA data from API…"):
        try:
            _df_raw, _last_updated = load_from_api(_effective_token)
            _data_source = "LIVE API"
        except Exception as e:
            st.error(f"API fetch failed: {e}")
            st.session_state["force_api"] = False
            st.rerun()
else:
    if PARQUET_PATH.exists():
        _df_raw, _last_updated = load_from_file()
        _data_source = "Bundled"
    else:
        with st.spinner("Fetching USDA data…"):
            try:
                _df_raw, _last_updated = load_from_api(_effective_token)
                _data_source = "LIVE API"
            except Exception as e:
                st.error(f"Failed to load data: {e}")
                st.stop()

# Expose a clean df; state-level views filter to VALID_STATES naturally
# (KCS state='US' is excluded automatically from state charts/maps)
df = _df_raw

# ─────────────────────────────────────────────
# BRANDED HEADER  (needs _data_source + _last_updated from load_df)
# ─────────────────────────────────────────────
if _data_source == "LIVE API":
    _src_badge = (
        "<span style='background:#1a3530;border:1px solid " + C['POS'] + ";"
        "color:" + C['POS'] + ";border-radius:4px;padding:2px 7px;font-size:10px;"
        "font-weight:600;margin-left:8px;'>&#9679; LIVE API</span>"
    )
else:
    _src_badge = (
        "<span style='background:#1e2530;border:1px solid " + C['BLUE'] + ";"
        "color:" + C['BLUE'] + ";border-radius:4px;padding:2px 7px;font-size:10px;"
        "font-weight:600;margin-left:8px;'>&#9679; DATA AS OF " + _last_updated.upper() + "</span>"
    )

st.markdown(f"""
<div style="
    background: linear-gradient(90deg, {C['CARD']} 0%, {C['CARD2']} 100%);
    border-bottom: 1px solid {C['BORDER']};
    padding: 12px 24px;
    display: flex;
    align-items: center;
    gap: 20px;
    margin-bottom: 16px;
">
  <img src="https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"
       style="height:36px; object-fit:contain;" alt="JSA Logo"
       onerror="this.style.display='none'">
  <div style="flex:1;">
    <div style="color:{C['TEXT']}; font-size:1.1rem; font-weight:600; letter-spacing:0.03em;">
        Grain Rail Shipments Dashboard {_src_badge}
    </div>
    <div style="color:{C['DIM']}; font-size:0.75rem; margin-top:2px;">
        USDA Agricultural Marketing Service &middot; John Stewart &amp; Associates
    </div>
  </div>
  <div style="color:{C['DIM']};font-size:0.72rem;text-align:right;line-height:1.6;">
    <span style="color:{C['MID']};">Last updated</span><br>{_last_updated}
  </div>
</div>
""", unsafe_allow_html=True)


def prep_df(df, cp_mode):
    """Merge CP and CPKC into CP/CPKC when cp_mode == 'Combined'."""
    if cp_mode == "Combined":
        df = df.copy()
        df['Railroad'] = df['Railroad'].replace({'CP': 'CP/CPKC', 'CPKC': 'CP/CPKC'})
    return df


def get_cp_rrs(df, cp_mode):
    """Return sorted list of railroad names, merging CP/CPKC if combined."""
    rrs = sorted(df['Railroad'].dropna().unique().tolist())
    if cp_mode == "Combined":
        merged = []
        for r in rrs:
            if r in ('CP', 'CPKC'):
                if 'CP/CPKC' not in merged:
                    merged.append('CP/CPKC')
            else:
                merged.append(r)
        return merged
    return rrs


all_years = sorted(df['Market Year'].dropna().unique().tolist())

# ─────────────────────────────────────────────
# TAB STRUCTURE
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Progress",
    "🚂 Railroad by Month",
    "🗺️ State Map",
    "📅 Weekly by Year",
    "📈 Yearly by Railroad",
    "📋 Summary",
])

# ══════════════════════════════════════════════
# TAB 1 — PROGRESS
# ══════════════════════════════════════════════
with tab1:
    # ── Controls ──────────────────────────────
    c1, c2, c3, c4 = st.columns([1.5, 1.5, 2, 2])
    with c1:
        sel_yr = st.selectbox(
            "Market Year",
            options=list(reversed(all_years)),
            index=0,
            key="t1_year",
        )
    with c2:
        cp_mode1 = st.radio("CP/CPKC", ["Combined", "Split"], horizontal=True, key="t1_cp")
    with c3:
        dfc1 = prep_df(df, cp_mode1)
        rr_list1 = get_cp_rrs(df, cp_mode1)
        sel_rr1 = st.selectbox("Railroad", ["All"] + rr_list1, key="t1_rr")
    with c4:
        states_avail1 = sorted(df['State'].dropna().unique().tolist())
        sel_state1 = st.selectbox("State", ["All"] + states_avail1, key="t1_state")

    # ── Context caption ───────────────────────
    max_wk = int(df[df['Market Year'] == sel_yr]['MY Week'].max())

    # All years are strings like "2025/26" — look up by index, never do arithmetic
    _yr_idx = all_years.index(sel_yr)
    ly_yr   = all_years[_yr_idx - 1] if _yr_idx > 0 else None

    # Build pool: 6 most recent complete years before sel_yr
    complete_years = [y for y in all_years if y < sel_yr]
    pool_years = sorted(complete_years)[-6:]

    # Identify if we're in a split mode where CP/CPKC comparisons are ambiguous
    is_split = (cp_mode1 == "Split")

    pool_label = f"{min(pool_years)}–{max(pool_years)}" if pool_years else "—"
    st.caption(
        f"{sel_yr} — Week {max_wk} · "
        f"vs LY: {ly_yr or 'N/A'} · "
        f"6-yr avg: {pool_label} (drop hi/lo)"
    )

    # ── Inner helpers ─────────────────────────
    def _s(d, year, rr=None, state=None):
        """Sum Est Bushels for given year up to max_wk, optionally filtered."""
        mask = (d['Market Year'] == year) & (d['MY Week'] <= max_wk)
        if rr:
            mask &= (d['Railroad'] == rr)
        if state:
            mask &= (d['State'] == state)
        return float(d.loc[mask, 'Est Bushels'].sum())

    def metrics(rr=None, state=None):
        """Compute current, LY, 6-yr Olympic avg, and pct deltas."""
        curr = _s(dfc1, sel_yr, rr, state)
        ly   = _s(dfc1, ly_yr, rr, state)
        pool_vals = [_s(dfc1, y, rr, state) for y in pool_years]
        avg  = oly_avg(pool_vals)
        return dict(
            current=curr,
            ly=ly,
            avg=avg,
            pct_ly=pct(curr, ly),
            pct_avg=pct(curr, avg),
        )

    # ── Railroad Summary Table ────────────────
    st.markdown(f"<h4 style='color:{C['TEXT']}; margin:8px 0 4px 0;'>Railroad Summary</h4>", unsafe_allow_html=True)

    rr_rows = []
    all_rrs = get_cp_rrs(dfc1, cp_mode1)
    for rr in all_rrs:
        m = metrics(rr=rr)
        # In split mode, CP & CPKC won't have meaningful LY (CPKC didn't exist)
        hide_compare = is_split and rr in ("CP", "CPKC")
        rr_rows.append({
            "Railroad":       rr,
            "MYtD Bu":        fbu(m['current']),
            "vs LY":          "—" if hide_compare else fdiff(m['current'], m['ly']),
            "% vs LY":        "—" if hide_compare else fpct(m['pct_ly']),
            "vs 6-Yr Avg":    "—" if hide_compare else fdiff(m['current'], m['avg']),
            "% vs Avg":       "—" if hide_compare else fpct(m['pct_avg']),
        })

    # Totals row
    tot = metrics()
    rr_rows.append({
        "Railroad":    "TOTAL",
        "MYtD Bu":     fbu(tot['current']),
        "vs LY":       fdiff(tot['current'], tot['ly']),
        "% vs LY":     fpct(tot['pct_ly']),
        "vs 6-Yr Avg": fdiff(tot['current'], tot['avg']),
        "% vs Avg":    fpct(tot['pct_avg']),
    })

    tbl_df = pd.DataFrame(rr_rows)
    st.dataframe(
        tbl_df,
        width='stretch',
        hide_index=True,
        height=min(42 * (len(rr_rows) + 1) + 38, 500),
    )

    st.markdown("---")

    # ── Railroad Deviation Chart ──────────────
    st.markdown(f"<h4 style='color:{C['TEXT']}; margin:8px 0 4px 0;'>Railroad Deviation</h4>", unsafe_allow_html=True)

    dev_rrs, pct_ly_vals, pct_avg_vals, diff_ly_vals, diff_avg_vals = [], [], [], [], []
    for rr in all_rrs:
        m = metrics(rr=rr)
        hide = is_split and rr in ("CP", "CPKC")
        if not hide:
            dev_rrs.append(rr)
            pct_ly_vals.append(m['pct_ly'] if m['pct_ly'] is not None else 0)
            pct_avg_vals.append(m['pct_avg'] if m['pct_avg'] is not None else 0)
            diff_ly_vals.append(fdiff(m['current'], m['ly']))
            diff_avg_vals.append(fdiff(m['current'], m['avg']))

    ly_colors  = [C["POS"] if v >= 0 else C["NEG"] for v in pct_ly_vals]
    avg_colors = [C["BLUE"] if v >= 0 else C["GOLD"] for v in pct_avg_vals]

    fig_rr = go.Figure()
    fig_rr.add_trace(go.Bar(
        name="% vs Last Year",
        y=dev_rrs,
        x=pct_ly_vals,
        orientation='h',
        marker_color=ly_colors,
        text=diff_ly_vals,
        textposition='outside',
        textfont=dict(color=ly_colors, size=10),
    ))
    fig_rr.add_trace(go.Bar(
        name="% vs 6-Yr Avg",
        y=dev_rrs,
        x=pct_avg_vals,
        orientation='h',
        marker_color=avg_colors,
        text=diff_avg_vals,
        textposition='outside',
        textfont=dict(color=avg_colors, size=10),
    ))

    rr_layout = base_layout(
        barmode='group',
        height=max(300, len(dev_rrs) * 52 + 80),
        title=dict(text=f"Deviation from LY & 6-Yr Avg — Week {max_wk}", font=dict(color=C["TEXT"], size=13)),
    )
    rr_layout['xaxis'].update(tickformat='+.0f', ticksuffix='%')
    fig_rr.update_layout(**rr_layout)
    st.plotly_chart(fig_rr, width='stretch')

    st.markdown("---")

    # ── State Deviation Chart ─────────────────
    st.markdown(f"<h4 style='color:{C['TEXT']}; margin:8px 0 4px 0;'>State Deviation</h4>", unsafe_allow_html=True)

    state_group = st.radio(
        "State Group",
        ["Top 15", "All States", "Western (IA NE SD ND MN KS MO)", "Eastern (IL IN OH MI KY)"],
        horizontal=True,
        key="t1_state_group",
    )

    # Determine state universe
    if "Western" in state_group:
        state_universe = WESTERN_STATES
    elif "Eastern" in state_group:
        state_universe = EASTERN_STATES
    else:
        state_universe = states_avail1

    # Pre-filter df to relevant years for performance
    rel_years = [sel_yr, ly_yr] + pool_years
    dfc1_filt = dfc1[dfc1['Market Year'].isin(rel_years)]

    if sel_rr1 != "All":
        dfc1_filt = dfc1_filt[dfc1_filt['Railroad'] == sel_rr1]

    def _ss(d, year, state):
        """Sum bushels for state/year up to max_wk (uses pre-filtered df)."""
        mask = (d['Market Year'] == year) & (d['MY Week'] <= max_wk) & (d['State'] == state)
        return float(d.loc[mask, 'Est Bushels'].sum())

    state_data = []
    for st_code in state_universe:
        curr = _ss(dfc1_filt, sel_yr, st_code)
        ly   = _ss(dfc1_filt, ly_yr, st_code)
        pool_v = [_ss(dfc1_filt, y, st_code) for y in pool_years]
        avg  = oly_avg(pool_v)
        p_ly  = pct(curr, ly)
        p_avg = pct(curr, avg)
        state_data.append(dict(
            state=st_code,
            current=curr, ly=ly, avg=avg,
            pct_ly=p_ly, pct_avg=p_avg,
        ))

    # Sort by pct_ly descending (treat None as -999)
    state_data.sort(key=lambda x: x['pct_ly'] if x['pct_ly'] is not None else -999, reverse=True)

    if state_group == "Top 15":
        state_data = state_data[:15]

    s_names    = [x['state']   for x in state_data]
    s_pct_ly   = [x['pct_ly']  if x['pct_ly']  is not None else 0 for x in state_data]
    s_pct_avg  = [x['pct_avg'] if x['pct_avg'] is not None else 0 for x in state_data]
    s_diff_ly  = [fdiff(x['current'], x['ly'])  for x in state_data]
    s_diff_avg = [fdiff(x['current'], x['avg']) for x in state_data]

    sly_colors  = [C["POS"] if v >= 0 else C["NEG"] for v in s_pct_ly]
    savg_colors = [C["BLUE"] if v >= 0 else C["GOLD"] for v in s_pct_avg]

    fig_st = go.Figure()
    fig_st.add_trace(go.Bar(
        name="% vs Last Year",
        y=s_names,
        x=s_pct_ly,
        orientation='h',
        marker_color=sly_colors,
        text=s_diff_ly,
        textposition='outside',
        textfont=dict(color=sly_colors, size=10),
    ))
    fig_st.add_trace(go.Bar(
        name="% vs 6-Yr Avg",
        y=s_names,
        x=s_pct_avg,
        orientation='h',
        marker_color=savg_colors,
        text=s_diff_avg,
        textposition='outside',
        textfont=dict(color=savg_colors, size=10),
    ))

    st_layout = base_layout(
        barmode='group',
        height=max(500, len(s_names) * 34 + 80),
        title=dict(text=f"State Deviation — Week {max_wk}", font=dict(color=C["TEXT"], size=13)),
    )
    st_layout['xaxis'].update(tickformat='+.0f', ticksuffix='%')
    fig_st.update_layout(**st_layout)
    st.plotly_chart(fig_st, width='stretch')


# ══════════════════════════════════════════════
# TAB 2 — RAILROAD BY MONTH
# ══════════════════════════════════════════════
with tab2:
    c1, c2, c3 = st.columns([2, 1.5, 2])
    with c1:
        year_opts2 = ["All Years"] + list(reversed(all_years))
        sel_yr2 = st.selectbox("Market Year", year_opts2, key="t2_year")
    with c2:
        cp_mode2 = st.radio("CP/CPKC", ["Combined", "Split"], horizontal=True, key="t2_cp")
    with c3:
        states_avail2 = sorted(df['State'].dropna().unique().tolist())
        sel_state2 = st.selectbox("State", ["All"] + states_avail2, key="t2_state")

    dfc2 = prep_df(df, cp_mode2)
    if sel_yr2 != "All Years":
        dfc2 = dfc2[dfc2['Market Year'] == sel_yr2]
    if sel_state2 != "All":
        dfc2 = dfc2[dfc2['State'] == sel_state2]

    # Group by Calendar Month and Railroad
    dfc2['Calendar Month'] = dfc2['Calendar Month'].astype(str).str.strip()

    # Aggregate
    grp2 = dfc2.groupby(['Calendar Month', 'Railroad'], as_index=False)['Est Bushels'].sum()

    # Map month abbreviations
    month_map = {
        '1': 'Jan', '2': 'Feb',  '3': 'Mar',  '4': 'Apr',
        '5': 'May', '6': 'Jun',  '7': 'Jul',  '8': 'Aug',
        '9': 'Sep', '10': 'Oct', '11': 'Nov', '12': 'Dec',
        'January': 'Jan', 'February': 'Feb', 'March': 'Mar', 'April': 'Apr',
        'May': 'May', 'June': 'Jun', 'July': 'Jul', 'August': 'Aug',
        'September': 'Sep', 'October': 'Oct', 'November': 'Nov', 'December': 'Dec',
    }
    grp2['Month'] = grp2['Calendar Month'].map(lambda x: month_map.get(x, x))
    grp2 = grp2[grp2['Month'].isin(MONTH_ORDER)]
    grp2['Month'] = pd.Categorical(grp2['Month'], categories=MONTH_ORDER, ordered=True)
    grp2 = grp2.sort_values('Month')

    rr_list2 = get_cp_rrs(dfc2, cp_mode2)

    fig2 = go.Figure()
    for rr in rr_list2:
        sub = grp2[grp2['Railroad'] == rr]
        fig2.add_trace(go.Bar(
            name=rr,
            x=sub['Month'],
            y=sub['Est Bushels'],
            marker_color=RR_COLORS.get(rr, C["PRIMARY"]),
        ))

    title2 = f"Bushels by Month & Railroad" + (f" — {sel_yr2}" if sel_yr2 != "All Years" else " — All Years")
    lay2 = base_layout(
        barmode='stack',
        height=480,
        title=dict(text=title2, font=dict(color=C["TEXT"], size=13)),
    )
    lay2['xaxis'].update(categoryorder='array', categoryarray=MONTH_ORDER)
    lay2['yaxis'].update(tickformat='.2s')
    fig2.update_layout(**lay2)
    st.plotly_chart(fig2, width='stretch')


# ══════════════════════════════════════════════
# TAB 3 — STATE MAP
# ══════════════════════════════════════════════
with tab3:
    c1, c2, c3 = st.columns([1.5, 2, 2])
    with c1:
        sel_yr3 = st.selectbox("Market Year", list(reversed(all_years)), key="t3_year")
    with c2:
        rr_list3 = get_cp_rrs(df, "Combined")
        sel_rr3 = st.selectbox("Railroad", ["All"] + rr_list3, key="t3_rr")
    with c3:
        metric3 = st.radio(
            "Metric",
            ["Total Bu", "% vs LY", "% vs 6-Yr Avg"],
            horizontal=True,
            key="t3_metric",
        )

    dfc3 = prep_df(df, "Combined")
    if sel_rr3 != "All":
        dfc3 = dfc3[dfc3['Railroad'] == sel_rr3]

    # Compute per-state values
    _idx3  = all_years.index(sel_yr3)
    ly_yr3 = all_years[_idx3 - 1] if _idx3 > 0 else None
    comp3  = sorted([y for y in all_years if y < sel_yr3])[-6:]

    map_data = []
    for st_code in VALID_STATES:
        mask_cur = (dfc3['Market Year'] == sel_yr3) & (dfc3['State'] == st_code)
        curr3 = float(dfc3.loc[mask_cur, 'Est Bushels'].sum())
        mask_ly = (dfc3['Market Year'] == ly_yr3) & (dfc3['State'] == st_code)
        ly3 = float(dfc3.loc[mask_ly, 'Est Bushels'].sum())
        pool_v3 = [float(dfc3.loc[(dfc3['Market Year'] == y) & (dfc3['State'] == st_code), 'Est Bushels'].sum()) for y in comp3]
        avg3 = oly_avg(pool_v3)
        map_data.append(dict(state=st_code, curr=curr3, ly=ly3, avg=avg3,
                              pct_ly=pct(curr3, ly3), pct_avg=pct(curr3, avg3)))

    map_df = pd.DataFrame(map_data)

    if metric3 == "Total Bu":
        z_vals  = map_df['curr'].tolist()
        z_label = "Bushels"
        colorscale = [
            [0.0, "#0e2a22"],
            [0.3, "#1a4a38"],
            [0.6, "#2d7a5c"],
            [1.0, "#4ade80"],
        ]
        zmid = None
        colorbar_tickformat = ".2s"
    elif metric3 == "% vs LY":
        z_vals  = [x if x is not None else 0 for x in map_df['pct_ly'].tolist()]
        z_label = "% vs LY"
        colorscale = "RdYlGn"
        zmid = 0
        colorbar_tickformat = "+.0f"
    else:
        z_vals  = [x if x is not None else 0 for x in map_df['pct_avg'].tolist()]
        z_label = "% vs 6-Yr Avg"
        colorscale = "RdYlGn"
        zmid = 0
        colorbar_tickformat = "+.0f"

    hover_text = []
    for _, row in map_df.iterrows():
        ht = (
            f"<b>{row['state']}</b><br>"
            f"Current: {fbu(row['curr'])}<br>"
            f"vs LY: {fpct(row['pct_ly'])}<br>"
            f"vs 6-Yr Avg: {fpct(row['pct_avg'])}"
        )
        hover_text.append(ht)

    fig3 = go.Figure(go.Choropleth(
        locations=map_df['state'],
        z=z_vals,
        locationmode='USA-states',
        colorscale=colorscale,
        zmid=zmid,
        colorbar=dict(
            title=dict(text=z_label, font=dict(color=C["MID"])),
            tickformat=colorbar_tickformat,
            tickfont=dict(color=C["MID"]),
            bgcolor=C["CARD"],
            bordercolor=C["BORDER"],
        ),
        hoverinfo='text',
        text=hover_text,
    ))

    map_layout = base_layout(height=480)
    map_layout.update(
        geo=dict(
            scope='usa',
            bgcolor=C["CARD"],
            lakecolor=C["BG"],
            landcolor=C["CARD2"],
            subunitcolor=C["BORDER"],
        ),
        title=dict(
            text=f"State {metric3} — {sel_yr3}",
            font=dict(color=C["TEXT"], size=13),
        ),
        margin=dict(l=0, r=0, t=40, b=0),
    )
    fig3.update_layout(**map_layout)

    # Layout: map left, detail right
    map_col, detail_col = st.columns([3, 2])
    with map_col:
        st.plotly_chart(fig3, width='stretch')

    with detail_col:
        st.markdown(f"<p style='color:{C['MID']}; font-size:0.8rem; margin-bottom:4px;'>State Detail</p>", unsafe_allow_html=True)
        detail_state = st.selectbox(
            "Select State",
            ["(none)"] + VALID_STATES,
            key="t3_detail_state",
            label_visibility="collapsed",
        )
        if detail_state != "(none)":
            dfc3_state = dfc3[(dfc3['State'] == detail_state) & (dfc3['Market Year'] == sel_yr3)]
            rr_bu = dfc3_state.groupby('Railroad')['Est Bushels'].sum().reset_index()
            rr_bu = rr_bu.sort_values('Est Bushels', ascending=True)

            fig3b = go.Figure(go.Bar(
                x=rr_bu['Est Bushels'],
                y=rr_bu['Railroad'],
                orientation='h',
                marker_color=[RR_COLORS.get(r, C["PRIMARY"]) for r in rr_bu['Railroad']],
                text=[fbu(v) for v in rr_bu['Est Bushels']],
                textposition='outside',
                textfont=dict(color=C["MID"], size=10),
            ))
            lay3b = base_layout(
                height=300,
                title=dict(
                    text=f"{detail_state} by Railroad — {sel_yr3}",
                    font=dict(color=C["TEXT"], size=12),
                ),
            )
            lay3b['xaxis'].update(tickformat='.2s')
            fig3b.update_layout(**lay3b)
            st.plotly_chart(fig3b, width='stretch')


# ══════════════════════════════════════════════
# TAB 4 — WEEKLY BY YEAR
# ══════════════════════════════════════════════
with tab4:
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        default_yrs4 = list(reversed(all_years))[:4]
        sel_yrs4 = st.multiselect(
            "Years",
            options=list(reversed(all_years)),
            default=default_yrs4,
            key="t4_years",
        )
    with c2:
        rr_list4 = get_cp_rrs(df, "Combined")
        sel_rr4 = st.selectbox("Railroad", ["All"] + rr_list4, key="t4_rr")
    with c3:
        states_avail4 = sorted(df['State'].dropna().unique().tolist())
        sel_state4 = st.selectbox("State", ["All"] + states_avail4, key="t4_state")

    if not sel_yrs4:
        st.info("Select at least one year above.")
    else:
        dfc4 = df.copy()
        if sel_rr4 != "All":
            dfc4 = dfc4[dfc4['Railroad'] == sel_rr4]
        if sel_state4 != "All":
            dfc4 = dfc4[dfc4['State'] == sel_state4]

        dfc4 = dfc4[dfc4['Market Year'].isin(sel_yrs4)]
        wk_grp = dfc4.groupby(['Market Year', 'MY Week'], as_index=False)['Est Bushels'].sum()

        # Color palette for years
        YEAR_PALETTE = [
            C["POS"], C["BLUE"], C["GOLD"], C["NEG"],
            "#a78bfa", "#fb923c", "#34d399", "#4aa3dc",
        ]

        # ── Weekly bar chart ──────────────────
        fig4a = go.Figure()
        for i, yr in enumerate(sorted(sel_yrs4)):
            sub = wk_grp[wk_grp['Market Year'] == yr].sort_values('MY Week')
            fig4a.add_trace(go.Bar(
                name=str(yr),
                x=sub['MY Week'],
                y=sub['Est Bushels'],
                marker_color=YEAR_PALETTE[i % len(YEAR_PALETTE)],
            ))

        lay4a = base_layout(
            barmode='group',
            height=320,
            title=dict(text="Weekly Shipments by Year", font=dict(color=C["TEXT"], size=13)),
        )
        lay4a['yaxis'].update(tickformat='.2s')
        fig4a.update_layout(**lay4a)
        st.plotly_chart(fig4a, width='stretch')

        # ── Cumulative line chart ─────────────
        fig4b = go.Figure()
        for i, yr in enumerate(sorted(sel_yrs4)):
            sub = wk_grp[wk_grp['Market Year'] == yr].sort_values('MY Week').copy()
            sub['Cumulative'] = sub['Est Bushels'].cumsum()
            fig4b.add_trace(go.Scatter(
                name=str(yr),
                x=sub['MY Week'],
                y=sub['Cumulative'],
                mode='lines',
                line=dict(color=YEAR_PALETTE[i % len(YEAR_PALETTE)], width=2),
            ))

        lay4b = base_layout(
            height=320,
            title=dict(text="Cumulative Shipments by Year", font=dict(color=C["TEXT"], size=13)),
        )
        lay4b['yaxis'].update(tickformat='.2s')
        fig4b.update_layout(**lay4b)
        st.plotly_chart(fig4b, width='stretch')


# ══════════════════════════════════════════════
# TAB 5 — YEARLY BY RAILROAD
# ══════════════════════════════════════════════
with tab5:
    c1, c2, c3 = st.columns([1.5, 2, 2])
    with c1:
        cp_mode5 = st.radio("CP/CPKC", ["Combined", "Split"], horizontal=True, key="t5_cp")
    with c2:
        rr_list5 = get_cp_rrs(df, cp_mode5)
        focus_rr5 = st.selectbox(
            "Focus Railroad (dims others)",
            ["All"] + rr_list5,
            key="t5_focus",
        )
    with c3:
        states_avail5 = sorted(df['State'].dropna().unique().tolist())
        sel_state5 = st.selectbox("State", ["All"] + states_avail5, key="t5_state")

    dfc5 = prep_df(df, cp_mode5)
    if sel_state5 != "All":
        dfc5 = dfc5[dfc5['State'] == sel_state5]

    yr_rr_grp = dfc5.groupby(['Market Year', 'Railroad'], as_index=False)['Est Bushels'].sum()

    fig5 = go.Figure()
    for rr in rr_list5:
        sub = yr_rr_grp[yr_rr_grp['Railroad'] == rr].sort_values('Market Year')
        opacity = 1.0 if (focus_rr5 == "All" or focus_rr5 == rr) else 0.25
        fig5.add_trace(go.Bar(
            name=rr,
            x=sub['Market Year'].astype(str),
            y=sub['Est Bushels'],
            marker=dict(
                color=RR_COLORS.get(rr, C["PRIMARY"]),
                opacity=opacity,
            ),
        ))

    lay5 = base_layout(
        barmode='stack',
        height=480,
        title=dict(
            text="Annual Shipments by Railroad"
                 + (f" — Focus: {focus_rr5}" if focus_rr5 != "All" else ""),
            font=dict(color=C["TEXT"], size=13),
        ),
    )
    lay5['yaxis'].update(tickformat='.2s')
    fig5.update_layout(**lay5)
    st.plotly_chart(fig5, width='stretch')


# ══════════════════════════════════════════════
# TAB 6 — SUMMARY
# ══════════════════════════════════════════════
with tab6:
    c1, c2 = st.columns([2, 2])
    with c1:
        default_yrs6 = list(reversed(all_years))[:3]
        sel_yrs6 = st.multiselect(
            "Years",
            options=list(reversed(all_years)),
            default=default_yrs6,
            key="t6_years",
        )
    with c2:
        rr_list6 = get_cp_rrs(df, "Combined")
        sel_rr6 = st.selectbox("Railroad", ["All"] + rr_list6, key="t6_rr")

    if not sel_yrs6:
        st.info("Select at least one year above.")
    else:
        dfc6 = df.copy()
        if sel_rr6 != "All":
            dfc6 = prep_df(dfc6, "Combined")
            dfc6 = dfc6[dfc6['Railroad'] == sel_rr6]

        # Current MY is latest in selection
        cur_yr6 = max(sel_yrs6)
        _idx6   = all_years.index(cur_yr6)
        ly_yr6  = all_years[_idx6 - 1] if _idx6 > 0 else None

        cur_data6 = dfc6[dfc6['Market Year'] == cur_yr6]
        ly_data6  = dfc6[dfc6['Market Year'] == ly_yr6]

        cur_total6 = float(cur_data6['Est Bushels'].sum())
        ly_total6  = float(ly_data6['Est Bushels'].sum())
        cur_wk6    = int(cur_data6['MY Week'].max()) if not cur_data6.empty else 0
        pct_ly6    = pct(cur_total6, ly_total6)

        min_yr6 = min(sel_yrs6)
        max_yr6 = max(sel_yrs6)

        # ── KPI Row ───────────────────────────
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(f"Total Bu ({cur_yr6})", fbu(cur_total6))
        k2.metric("vs Last Year", fpct(pct_ly6), delta=fdiff(cur_total6, ly_total6))
        k3.metric("Current Week", str(cur_wk6))
        k4.metric("Data Range", f"{min_yr6}–{max_yr6}")

        st.markdown("---")

        # ── Stacked bar by year ───────────────
        dfc6_sel = dfc6[dfc6['Market Year'].isin(sel_yrs6)]
        dfc6_cp  = prep_df(dfc6_sel, "Combined")
        yr_rr6   = dfc6_cp.groupby(['Market Year', 'Railroad'], as_index=False)['Est Bushels'].sum()

        rr_list6b = sorted(dfc6_cp['Railroad'].dropna().unique().tolist())

        fig6a = go.Figure()
        for rr in rr_list6b:
            sub = yr_rr6[yr_rr6['Railroad'] == rr].sort_values('Market Year')
            fig6a.add_trace(go.Bar(
                name=rr,
                x=sub['Market Year'].astype(str),
                y=sub['Est Bushels'],
                marker_color=RR_COLORS.get(rr, C["PRIMARY"]),
            ))

        lay6a = base_layout(
            barmode='stack',
            height=360,
            title=dict(text="Annual Totals by Railroad", font=dict(color=C["TEXT"], size=13)),
        )
        lay6a['yaxis'].update(tickformat='.2s')
        fig6a.update_layout(**lay6a)
        st.plotly_chart(fig6a, width='stretch')

        # ── Cumulative weekly line ────────────
        YEAR_PAL6 = [C["POS"], C["BLUE"], C["GOLD"], C["NEG"], "#a78bfa", "#fb923c"]
        wk_grp6 = dfc6_sel.groupby(['Market Year', 'MY Week'], as_index=False)['Est Bushels'].sum()

        fig6b = go.Figure()
        for i, yr in enumerate(sorted(sel_yrs6)):
            sub = wk_grp6[wk_grp6['Market Year'] == yr].sort_values('MY Week').copy()
            sub['Cumulative'] = sub['Est Bushels'].cumsum()
            fig6b.add_trace(go.Scatter(
                name=str(yr),
                x=sub['MY Week'],
                y=sub['Cumulative'],
                mode='lines',
                line=dict(color=YEAR_PAL6[i % len(YEAR_PAL6)], width=2),
            ))

        lay6b = base_layout(
            height=320,
            title=dict(text="Cumulative Weekly Shipments", font=dict(color=C["TEXT"], size=13)),
        )
        lay6b['yaxis'].update(tickformat='.2s')
        fig6b.update_layout(**lay6b)
        st.plotly_chart(fig6b, width='stretch')
