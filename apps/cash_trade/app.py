import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
import time

# ── JPSI Brand ───────────────────────────────────────────────────────────────
JPSI_DARK = "#32373c"
JPSI_BLUE = "#0693e3"
MUTED     = "#6b7280"
BORDER    = "#e2e5e9"
POS       = "#1a7f37"
NEG       = "#c62828"

FOB_COLOR  = JPSI_BLUE     # Live FOB
DEL_COLOR  = "#e8833a"     # Dressed Delivered
CONF_COLOR = JPSI_BLUE     # Total confirmed
D14_COLOR  = "#5aa469"     # 1-14 day delivery
D30_COLOR  = "#e8833a"     # 15-30 day delivery

JSA_LOGO = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"
WATERMARK_OPACITY = 0.10

# ── Data sources ─────────────────────────────────────────────────────────────
# USDA AMS LMR (old datamart system) — no API key required.
LMR_BASE = "https://mpr.datamart.ams.usda.gov/services/v1.1/reports"

# 5 Area Weekly Weighted Average Direct Slaughter Cattle (LM_CT150). "History"
# section carries USDA's own pre-computed weekly weighted averages for Live FOB
# and Dressed Delivered, by class (Steer/Heifer), for three aligned periods per
# report: "WEEKLY WEIGHTED AVERAGES" (this week), "SAME PERIOD LAST WEEK", and
# "SAME PERIOD LAST YEAR" — matches the PDF's own weekly/week-ago/year-ago panel.
CT150_ID = 2477

# National Weekly Direct Slaughter Cattle - Negotiated Purchases (LM_CT154).
# "Summary" section (the API's default) carries the confirmed / 1-14 day /
# 15-30 day negotiated cash trade head counts plus the weekly market narrative.
CT154_ID = 2481

PRICE_PERIODS = ["WEEKLY WEIGHTED AVERAGES", "SAME PERIOD LAST WEEK", "SAME PERIOD LAST YEAR"]
PERIOD_LABEL = {
    "WEEKLY WEIGHTED AVERAGES": "This Week",
    "SAME PERIOD LAST WEEK": "Week Ago",
    "SAME PERIOD LAST YEAR": "Year Ago",
}
BASIS_LABEL = {"Live": "Live FOB", "Dressed": "Dressed Delivered"}

# st.set_page_config removed — the Livestock Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600;700&display=swap');
  html, body, [class*="css"], .stApp, button, input, select, textarea, table, td, th, .stMarkdown,
  h1, h2, h3, h4, h5, h6, p, span, div {{
    font-family: 'Source Sans Pro', system-ui, -apple-system, sans-serif !important;
  }}

  #MainMenu, footer {{ visibility:hidden !important; }}
  .stDeployButton {{ display:none; }}

  .stApp {{ background-color:#ffffff; }}
  .block-container {{ padding-top:0.75rem !important; max-width:1250px; }}

  [data-testid="stSidebar"] {{ background-color:#f6f8fa; border-right:1px solid {BORDER}; }}

  .dash-header {{
    background:#ffffff; border-bottom:3px solid {JPSI_BLUE};
    padding:16px 8px 14px 8px; margin:-0.75rem 0 22px 0;
    display:flex; align-items:center; gap:20px;
  }}
  .dash-header-logo img {{ height:48px; display:block; }}
  .dash-header-text {{ flex:1; text-align:center; }}
  .dash-header-text h1 {{
    margin:0; color:{JPSI_DARK} !important; font-size:1.65rem; font-weight:700; letter-spacing:-0.01em;
  }}
  .dash-header-text .subtitle {{ color:{MUTED}; font-size:0.83rem; margin:3px 0 0 0; }}
  .dash-header-meta {{ text-align:right; color:{MUTED}; font-size:0.75rem; min-width:150px; }}
  .dash-header-meta b {{ color:{JPSI_DARK}; font-size:1rem; }}

  .sec-header {{
    color:{JPSI_DARK}; font-size:0.78rem; font-weight:700; text-transform:uppercase;
    letter-spacing:0.08em; padding:6px 0 6px 10px; border-left:4px solid {JPSI_BLUE};
    margin:22px 0 12px;
  }}

  .tile {{
    background:#ffffff; border:1px solid {BORDER}; border-top:3px solid {JPSI_BLUE};
    border-radius:10px; padding:14px 16px; text-align:center; height:100%;
    box-shadow:0 1px 4px rgba(50,55,60,0.06);
  }}
  .tile-fob   {{ border-top-color:{FOB_COLOR}; }}
  .tile-del   {{ border-top-color:{DEL_COLOR}; }}
  .tile-conf  {{ border-top-color:{CONF_COLOR}; }}
  .tile-d14   {{ border-top-color:{D14_COLOR}; }}
  .tile-d30   {{ border-top-color:{D30_COLOR}; }}
  .tile-neu   {{ border-top-color:{MUTED}; }}
  .tile-label {{ color:{MUTED}; font-size:0.66rem; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:6px; }}
  .tile-value {{ color:{JPSI_DARK}; font-size:1.55rem; font-weight:700; line-height:1.1; }}
  .tile-delta-pos {{ color:{POS}; font-size:0.8rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neg {{ color:{NEG}; font-size:0.8rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neu {{ color:{MUTED}; font-size:0.8rem; font-weight:600; margin-top:4px; }}

  .narrative {{
    background:#f6f8fa; border:1px solid {BORDER}; border-left:4px solid {JPSI_BLUE};
    border-radius:8px; padding:14px 18px; color:{JPSI_DARK}; font-size:0.85rem; line-height:1.55;
  }}

  .note {{ color:{MUTED}; font-size:0.72rem; line-height:1.5; }}
  hr {{ border-color:{BORDER}; }}
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_price(v):
    return f"${v:.2f}" if v is not None and pd.notna(v) else "—"


def fmt_hd(v):
    return f"{v:,.0f} hd" if v is not None and pd.notna(v) else "—"


def price_delta_html(cur, prior):
    if cur is None or prior is None or pd.isna(cur) or pd.isna(prior):
        return '<div class="tile-delta-neu">—</div>'
    diff = cur - prior
    sign = "▲" if diff > 0 else ("▼" if diff < 0 else "")
    color = "pos" if diff > 0 else ("neg" if diff < 0 else "neu")
    return f'<div class="tile-delta-{color}">{sign} ${abs(diff):.2f}</div>'


def hd_delta_html(cur, prior):
    if cur is None or prior is None or pd.isna(cur) or pd.isna(prior):
        return '<div class="tile-delta-neu">—</div>'
    diff = cur - prior
    pct = (diff / prior * 100) if prior else None
    sign = "▲" if diff > 0 else ("▼" if diff < 0 else "")
    color = "pos" if diff > 0 else ("neg" if diff < 0 else "neu")
    pct_str = f" ({pct:+.1f}%)" if pct is not None else ""
    return f'<div class="tile-delta-{color}">{sign} {abs(diff):,.0f} hd{pct_str}</div>'


def tile(label, value, delta="", cls=""):
    return (f'<div class="tile {cls}">'
            f'<div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>'
            f'{delta}</div>')


# ── Data Fetching ────────────────────────────────────────────────────────────

def _session(backoff=3) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=backoff,
                   status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


@st.cache_data(ttl=3600, persist="disk", show_spinner=False)
def fetch_price_history() -> pd.DataFrame:
    """Full-history weekly Live FOB / Dressed Delivered weighted averages by
    class (Steer/Heifer), for all three USDA-aligned periods, from LM_CT150."""
    url = f"{LMR_BASE}/{CT150_ID}/History"
    sess = _session()
    resp = sess.get(url, timeout=120)
    resp.raise_for_status()
    rows = resp.json().get("results", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["report_date"] = pd.to_datetime(df["report_date"], format="%m/%d/%Y", errors="coerce")
    for c in ["head_count", "weight_range_avg", "weighted_avg_price"]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce")

    df = df.dropna(subset=["report_date"])
    keep = ["report_date", "current_period", "selling_basis_desc", "class_description",
            "head_count", "weight_range_avg", "weighted_avg_price"]
    return df[keep].sort_values("report_date").reset_index(drop=True)


@st.cache_data(ttl=3600, persist="disk", show_spinner=False)
def fetch_volume_history() -> pd.DataFrame:
    """Full-history weekly negotiated cash trade volumes (confirmed, 1-14 day,
    15-30 day) plus the weekly market narrative, from LM_CT154."""
    url = f"{LMR_BASE}/{CT154_ID}"
    sess = _session()
    resp = sess.get(url, timeout=60)
    resp.raise_for_status()
    rows = resp.json().get("results", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["report_date"] = pd.to_datetime(df["report_date"], format="%m/%d/%Y", errors="coerce")
    num_cols = ["total_head_count", "head_count_week_ago", "head_count_year_ago",
                "total_head_count_1", "head_count_week_ago_1",
                "total_head_count_2", "head_count_week_ago_2"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce")

    df = df.dropna(subset=["report_date"]).sort_values("report_date").reset_index(drop=True)
    return df[["report_date", "trend"] + num_cols]


def combine_steer_heifer(df: pd.DataFrame) -> pd.DataFrame:
    """Head-count-weighted combine of Steer + Heifer rows, per report_date /
    period / selling basis — a simple weighted average, no double-counting."""
    d = df.copy()
    d["wp"] = d["head_count"] * d["weighted_avg_price"]
    g = d.groupby(["report_date", "current_period", "selling_basis_desc"], as_index=False).agg(
        head_count=("head_count", "sum"), wp_sum=("wp", "sum"),
    )
    g["combo_price"] = g["wp_sum"] / g["head_count"]
    return g.drop(columns="wp_sum")


def period_value(g: pd.DataFrame, report_date, period, basis):
    row = g[(g["report_date"] == report_date) & (g["current_period"] == period) &
            (g["selling_basis_desc"] == basis)]
    if row.empty:
        return None, None
    r = row.iloc[0]
    return r["combo_price"], r["head_count"]


# ── Load Data ────────────────────────────────────────────────────────────────

with st.spinner("Loading full USDA cash cattle trade history…"):
    try:
        price_df = fetch_price_history()
        vol_df = fetch_volume_history()
        load_ok, err_msg = True, ""
    except Exception as e:
        load_ok, err_msg = False, str(e)
        price_df, vol_df = pd.DataFrame(), pd.DataFrame()


# ── Header ───────────────────────────────────────────────────────────────────

c1, c2 = st.columns([7, 3])
with c1:
    st.markdown(
        '<div class="dash-header">'
        f'<div class="dash-header-logo"><img src="{JSA_LOGO}"></div>'
        '<div class="dash-header-text">'
        '<h1>Cash Cattle Trade Dashboard</h1>'
        '<div class="subtitle">5-Area weighted-average FOB/Delivered prices and national negotiated cash trade volume</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

if not load_ok:
    st.warning(
        "⏳ **USDA data temporarily unavailable** — the USDA server is not responding. "
        "This usually resolves in a few minutes. Use **Refresh now** in the sidebar to retry."
    )
    with st.expander("Technical details"):
        st.code(err_msg)
    st.stop()

if price_df.empty and vol_df.empty:
    st.warning("No data returned from USDA APIs.")
    st.stop()

last_price_date = price_df["report_date"].max() if not price_df.empty else None
last_vol_date = vol_df["report_date"].max() if not vol_df.empty else None

with c2:
    meta = []
    if last_price_date is not None:
        meta.append(f"LM_CT150: <b>{last_price_date.strftime('%b %d, %Y')}</b>")
    if last_vol_date is not None:
        meta.append(f"LM_CT154: <b>{last_vol_date.strftime('%b %d, %Y')}</b>")
    st.markdown('<div class="dash-header-meta">' + "<br>".join(meta) + '</div>', unsafe_allow_html=True)


# ── Section 1: Combined Steer & Heifer prices ───────────────────────────────

st.markdown(
    '<div class="sec-header">Cash Cattle Prices — Combined Steer &amp; Heifer, Head-Count Weighted (LM_CT150, 5-Area)</div>',
    unsafe_allow_html=True,
)

combo = combine_steer_heifer(price_df) if not price_df.empty else pd.DataFrame()

if combo.empty:
    st.info("No price data available.")
    fob_now = fob_wk = fob_yr = del_now = del_wk = del_yr = None
    fob_now_hd = del_now_hd = None
else:
    fob_now, fob_now_hd = period_value(combo, last_price_date, "WEEKLY WEIGHTED AVERAGES", "Live")
    fob_wk, _ = period_value(combo, last_price_date, "SAME PERIOD LAST WEEK", "Live")
    fob_yr, _ = period_value(combo, last_price_date, "SAME PERIOD LAST YEAR", "Live")
    del_now, del_now_hd = period_value(combo, last_price_date, "WEEKLY WEIGHTED AVERAGES", "Dressed")
    del_wk, _ = period_value(combo, last_price_date, "SAME PERIOD LAST WEEK", "Dressed")
    del_yr, _ = period_value(combo, last_price_date, "SAME PERIOD LAST YEAR", "Dressed")

st.markdown(f'<div class="sec-header" style="border-left-color:{FOB_COLOR};margin-top:6px;">Live FOB ($/cwt) — {fmt_hd(fob_now_hd)}</div>', unsafe_allow_html=True)
cols = st.columns(3)
with cols[0]:
    st.markdown(tile("This Week", fmt_price(fob_now), cls="tile-fob"), unsafe_allow_html=True)
with cols[1]:
    st.markdown(tile("vs Week Ago", fmt_price(fob_wk), price_delta_html(fob_now, fob_wk), "tile-fob"), unsafe_allow_html=True)
with cols[2]:
    st.markdown(tile("vs Year Ago", fmt_price(fob_yr), price_delta_html(fob_now, fob_yr), "tile-fob"), unsafe_allow_html=True)

st.markdown(f'<div class="sec-header" style="border-left-color:{DEL_COLOR};">Dressed Delivered ($/cwt) — {fmt_hd(del_now_hd)}</div>', unsafe_allow_html=True)
cols = st.columns(3)
with cols[0]:
    st.markdown(tile("This Week", fmt_price(del_now), cls="tile-del"), unsafe_allow_html=True)
with cols[1]:
    st.markdown(tile("vs Week Ago", fmt_price(del_wk), price_delta_html(del_now, del_wk), "tile-del"), unsafe_allow_html=True)
with cols[2]:
    st.markdown(tile("vs Year Ago", fmt_price(del_yr), price_delta_html(del_now, del_yr), "tile-del"), unsafe_allow_html=True)

st.markdown(
    '<div class="note" style="margin-top:6px;">Combined price = (Steer head count × Steer price + Heifer head count × '
    'Heifer price) ÷ total head count — a simple head-count-weighted average of USDA\'s own published Steer and Heifer '
    'weekly weighted averages. "This Week", "Week Ago" and "Year Ago" are the exact aligned periods USDA publishes '
    'alongside the current report.</div>',
    unsafe_allow_html=True,
)


# ── Price Trend Chart ────────────────────────────────────────────────────────

st.markdown('<div class="sec-header">Weekly combined price trend</div>', unsafe_allow_html=True)

AXIS = dict(gridcolor=BORDER, linecolor=BORDER, showgrid=True,
            tickfont=dict(color=MUTED, size=11), title_font=dict(color=MUTED, size=11),
            zeroline=False)

if not combo.empty:
    trend = combo[combo["current_period"] == "WEEKLY WEIGHTED AVERAGES"].sort_values("report_date")
    fob_trend = trend[trend["selling_basis_desc"] == "Live"]
    del_trend = trend[trend["selling_basis_desc"] == "Dressed"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=fob_trend["report_date"], y=fob_trend["combo_price"],
        name="Live FOB (combined)", mode="lines", line=dict(color=FOB_COLOR, width=2),
        hovertemplate="<b>Live FOB</b>: $%{y:.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=del_trend["report_date"], y=del_trend["combo_price"],
        name="Dressed Delivered (combined)", mode="lines", line=dict(color=DEL_COLOR, width=2),
        hovertemplate="<b>Dressed Delivered</b>: $%{y:.2f}<extra></extra>",
    ))

    _end = trend["report_date"].max()
    _start = _end - pd.Timedelta(days=3 * 365) if pd.notna(_end) else None

    fig.add_layout_image(dict(
        source=JSA_LOGO, xref="paper", yref="paper",
        x=0.5, y=0.5, sizex=0.5, sizey=0.5,
        xanchor="center", yanchor="middle", sizing="contain",
        opacity=WATERMARK_OPACITY, layer="below",
    ))
    fig.update_layout(
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color=JPSI_DARK, size=11), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color=JPSI_DARK, size=11), bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=55, r=20, t=15, b=40),
        xaxis=dict(
            **AXIS, title="",
            range=[_start, _end] if _start is not None else None,
            rangeselector=dict(
                buttons=[
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(count=1, label="YTD", step="year", stepmode="todate"),
                    dict(count=1, label="1Y", step="year", stepmode="backward"),
                    dict(count=3, label="3Y", step="year", stepmode="backward"),
                    dict(count=10, label="10Y", step="year", stepmode="backward"),
                    dict(step="all", label="All"),
                ],
                bgcolor="#f6f8fa", activecolor=JPSI_BLUE,
                font=dict(color=JPSI_DARK, size=10), bordercolor=BORDER,
            ),
            rangeslider=dict(visible=False), type="date",
        ),
        yaxis=dict(**AXIS, title="$/cwt", tickprefix="$"),
        height=400,
    )
    st.plotly_chart(fig, width="stretch")
else:
    st.info("No price trend data available.")


# ── Steer / Heifer detail table ─────────────────────────────────────────────

with st.expander("📋  Steer / Heifer / Combined detail — this week, week ago, year ago"):
    if price_df.empty:
        st.info("No data.")
    else:
        detail = price_df[price_df["report_date"] == last_price_date].copy()
        detail["Class"] = detail["class_description"]
        detail["Period"] = detail["current_period"].map(PERIOD_LABEL)
        detail["Basis"] = detail["selling_basis_desc"].map(BASIS_LABEL)
        detail = detail.rename(columns={"head_count": "Head Count", "weight_range_avg": "Avg Weight",
                                         "weighted_avg_price": "Wtd Avg Price"})

        combo_detail = combo[combo["report_date"] == last_price_date].copy()
        combo_detail["Class"] = "Combined (Steer+Heifer)"
        combo_detail["Period"] = combo_detail["current_period"].map(PERIOD_LABEL)
        combo_detail["Basis"] = combo_detail["selling_basis_desc"].map(BASIS_LABEL)
        combo_detail = combo_detail.rename(columns={"head_count": "Head Count", "combo_price": "Wtd Avg Price"})
        combo_detail["Avg Weight"] = float("nan")

        full = pd.concat([
            detail[["Period", "Basis", "Class", "Head Count", "Avg Weight", "Wtd Avg Price"]],
            combo_detail[["Period", "Basis", "Class", "Head Count", "Avg Weight", "Wtd Avg Price"]],
        ], ignore_index=True)

        period_order = {"This Week": 0, "Week Ago": 1, "Year Ago": 2}
        class_order = {"Steer": 0, "Heifer": 1, "Combined (Steer+Heifer)": 2}
        full["_p"] = full["Period"].map(period_order)
        full["_c"] = full["Class"].map(class_order)
        full = full.sort_values(["_p", "Basis", "_c"]).drop(columns=["_p", "_c"]).reset_index(drop=True)

        full["Head Count"] = full["Head Count"].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "—")
        full["Avg Weight"] = full["Avg Weight"].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "—")
        full["Wtd Avg Price"] = full["Wtd Avg Price"].apply(lambda v: f"${v:.2f}" if pd.notna(v) else "—")

        st.dataframe(full, width="stretch", height=380, hide_index=True)


# ── Section 2: Negotiated cash trade volume ─────────────────────────────────

st.markdown(
    '<div class="sec-header">Negotiated Cash Trade Volume — National (LM_CT154)</div>',
    unsafe_allow_html=True,
)

if vol_df.empty:
    st.info("No volume data available.")
    conf_now = conf_wk = conf_yr = d14_now = d14_wk = d30_now = d30_wk = None
    narrative = None
else:
    latest_vol = vol_df.iloc[-1]
    conf_now, conf_wk, conf_yr = latest_vol["total_head_count"], latest_vol["head_count_week_ago"], latest_vol["head_count_year_ago"]
    d14_now, d14_wk = latest_vol["total_head_count_1"], latest_vol["head_count_week_ago_1"]
    d30_now, d30_wk = latest_vol["total_head_count_2"], latest_vol["head_count_week_ago_2"]
    narrative = latest_vol["trend"]

cols = st.columns(3)
with cols[0]:
    st.markdown(tile("Total Confirmed — This Week", fmt_hd(conf_now), cls="tile-conf"), unsafe_allow_html=True)
with cols[1]:
    st.markdown(tile("vs Week Ago", fmt_hd(conf_wk), hd_delta_html(conf_now, conf_wk), "tile-conf"), unsafe_allow_html=True)
with cols[2]:
    st.markdown(tile("vs Year Ago", fmt_hd(conf_yr), hd_delta_html(conf_now, conf_yr), "tile-conf"), unsafe_allow_html=True)

cols = st.columns(4)
with cols[0]:
    st.markdown(tile("1-14 Day Delivery — This Week", fmt_hd(d14_now), cls="tile-d14"), unsafe_allow_html=True)
with cols[1]:
    st.markdown(tile("1-14 Day vs Week Ago", fmt_hd(d14_wk), hd_delta_html(d14_now, d14_wk), "tile-d14"), unsafe_allow_html=True)
with cols[2]:
    st.markdown(tile("15-30 Day Delivery — This Week", fmt_hd(d30_now), cls="tile-d30"), unsafe_allow_html=True)
with cols[3]:
    st.markdown(tile("15-30 Day vs Week Ago", fmt_hd(d30_wk), hd_delta_html(d30_now, d30_wk), "tile-d30"), unsafe_allow_html=True)

st.markdown(
    '<div class="note" style="margin-top:6px;">USDA does not publish a year-ago figure for the 1-14 day / 15-30 day '
    'delivery windows — only for total confirmed trade — so those two rows compare to week-ago only, matching the source report.</div>',
    unsafe_allow_html=True,
)

if narrative:
    st.markdown('<div class="sec-header">This week\'s market narrative</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="narrative">{narrative}</div>', unsafe_allow_html=True)


# ── Volume Trend Chart ───────────────────────────────────────────────────────

st.markdown('<div class="sec-header">Weekly negotiated cash trade volume trend</div>', unsafe_allow_html=True)

if not vol_df.empty:
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=vol_df["report_date"], y=vol_df["total_head_count"],
        name="Total Confirmed", mode="lines", line=dict(color=CONF_COLOR, width=2),
        hovertemplate="<b>Total Confirmed</b>: %{y:,.0f} hd<extra></extra>",
    ))
    fig2.add_trace(go.Scatter(
        x=vol_df["report_date"], y=vol_df["total_head_count_1"],
        name="1-14 Day Delivery", mode="lines", line=dict(color=D14_COLOR, width=2),
        hovertemplate="<b>1-14 Day</b>: %{y:,.0f} hd<extra></extra>",
    ))
    fig2.add_trace(go.Scatter(
        x=vol_df["report_date"], y=vol_df["total_head_count_2"],
        name="15-30 Day Delivery", mode="lines", line=dict(color=D30_COLOR, width=2),
        hovertemplate="<b>15-30 Day</b>: %{y:,.0f} hd<extra></extra>",
    ))

    _vend = vol_df["report_date"].max()
    _vstart = _vend - pd.Timedelta(days=2 * 365) if pd.notna(_vend) else None

    fig2.add_layout_image(dict(
        source=JSA_LOGO, xref="paper", yref="paper",
        x=0.5, y=0.5, sizex=0.5, sizey=0.5,
        xanchor="center", yanchor="middle", sizing="contain",
        opacity=WATERMARK_OPACITY, layer="below",
    ))
    fig2.update_layout(
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color=JPSI_DARK, size=11), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color=JPSI_DARK, size=11), bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=55, r=20, t=15, b=40),
        xaxis=dict(
            **AXIS, title="",
            range=[_vstart, _vend] if _vstart is not None else None,
            rangeselector=dict(
                buttons=[
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(count=1, label="YTD", step="year", stepmode="todate"),
                    dict(count=1, label="1Y", step="year", stepmode="backward"),
                    dict(count=5, label="5Y", step="year", stepmode="backward"),
                    dict(step="all", label="All"),
                ],
                bgcolor="#f6f8fa", activecolor=JPSI_BLUE,
                font=dict(color=JPSI_DARK, size=10), bordercolor=BORDER,
            ),
            rangeslider=dict(visible=False), type="date",
        ),
        yaxis=dict(**AXIS, title="Head Count"),
        height=380,
    )
    st.plotly_chart(fig2, width="stretch")
else:
    st.info("No volume trend data available.")


# ── Data Tables ────────────────────────────────────────────────────────────

with st.expander("📋  Weekly combined price history"):
    if combo.empty:
        st.info("No data.")
    else:
        trend = combo[combo["current_period"] == "WEEKLY WEIGHTED AVERAGES"].sort_values("report_date")
        piv = trend.pivot_table(index="report_date", columns="selling_basis_desc", values="combo_price").reset_index()
        piv = piv.rename(columns={"report_date": "Week Of", "Live": "Live FOB", "Dressed": "Dressed Delivered"})
        piv["Week Of"] = piv["Week Of"].dt.strftime("%Y-%m-%d")
        piv = piv.sort_values("Week Of", ascending=False).reset_index(drop=True)
        st.dataframe(piv.style.format({"Live FOB": "${:.2f}", "Dressed Delivered": "${:.2f}"}, na_rep="—"),
                     width="stretch", height=320)

with st.expander("📋  Weekly negotiated cash trade volume history"):
    if vol_df.empty:
        st.info("No data.")
    else:
        disp = vol_df.drop(columns="trend").copy()
        disp["report_date"] = disp["report_date"].dt.strftime("%Y-%m-%d")
        disp = disp.rename(columns={
            "report_date": "Week Of", "total_head_count": "Confirmed", "head_count_week_ago": "Confirmed (Wk Ago)",
            "head_count_year_ago": "Confirmed (Yr Ago)", "total_head_count_1": "1-14 Day",
            "head_count_week_ago_1": "1-14 Day (Wk Ago)", "total_head_count_2": "15-30 Day",
            "head_count_week_ago_2": "15-30 Day (Wk Ago)",
        }).sort_values("Week Of", ascending=False).reset_index(drop=True)
        st.dataframe(disp.style.format({c: "{:,.0f}" for c in disp.columns if c != "Week Of"}, na_rep="—"),
                     width="stretch", height=320)


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image(JSA_LOGO, width="stretch")
    st.markdown("<hr>", unsafe_allow_html=True)

    st.markdown('<div class="sec-header" style="margin-top:0;">Data refresh</div>', unsafe_allow_html=True)
    auto_refresh = st.toggle("Auto-refresh (30 min)", value=False)
    if st.button("↺  Refresh now", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(
        '<div class="note">'
        '<b>Cash Cattle Prices</b> — USDA AMS LMR, 5 Area Weekly Weighted Average Direct Slaughter Cattle '
        '(<b>LM_CT150</b>), Texas/Oklahoma/New Mexico, Kansas, Nebraska, Colorado, Iowa/Minnesota. '
        'Combined Live FOB and Dressed Delivered figures are a simple head-count-weighted average of USDA\'s '
        'own published Steer and Heifer weekly weighted averages. Published weekly (Mondays).<br><br>'
        '<b>Negotiated Cash Trade Volume</b> — USDA AMS LMR, National Weekly Direct Slaughter Cattle - '
        'Negotiated Purchases (<b>LM_CT154</b>). USDA does not publish a year-ago figure for the 1-14 day '
        'or 15-30 day delivery windows, only for total confirmed trade.<br><br>'
        'Full available history is always loaded — LM_CT150 back to 2004, LM_CT154 back to 2001. Cache: 1 hr.'
        '</div>',
        unsafe_allow_html=True,
    )


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

# ── Debug Expander ──────────────────────────────────────────────────────────

with st.expander("🔧  Raw API debug"):
    st.write("**Price endpoint:**", f"{LMR_BASE}/{CT150_ID}/History")
    st.write("**Volume endpoint:**", f"{LMR_BASE}/{CT154_ID}")
    st.write("**Price rows:**", len(price_df), "| **Volume rows:**", len(vol_df))
    if not price_df.empty:
        st.dataframe(price_df.tail(12))
    if not vol_df.empty:
        st.dataframe(vol_df.tail(6))

# ── Auto-refresh ─────────────────────────────────────────────────────────────

if auto_refresh:
    time.sleep(1800)
    st.cache_data.clear()
    st.rerun()
