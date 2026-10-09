"""
CFTC Commitments of Traders Dashboard
Positioning in every CFTC-tracked ag futures market: managed money, producers,
swap dealers, index traders, and 40 years of commercial vs speculator history.

John Stewart & Associates
Data: CFTC Commitments of Traders, loaded weekly into Snowflake JSA.CFTC_COT
by cftc-cot-etl. Reports are as of Tuesday and released Friday 2:30pm CT.
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# A page's own directory is never added to sys.path automatically.
sys.path.insert(0, str(Path(__file__).parent))
import cot_client as cc  # noqa: E402

# st.set_page_config removed -- the JSA Admin Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

JSA_DARK, JSA_BLUE = "#32373c", "#0693e3"
BORDER, MUTED, GRID = "#dde3e8", "#6b7280", "#eceff2"
POS_BG, NEG_BG = "#e8f5e9", "#ffebee"

GROUPS = {  # label -> (net column, colour)
    "Managed money": ("mm_net", JSA_BLUE),
    "Producer / merchant": ("prod_merc_net", "#f2b134"),
    "Swap dealers": ("swap_net", "#5ec48c"),
    "Other reportables": ("other_net", "#c792ea"),
    "Non-reportable": ("nonrept_net", "#84939f"),
}

LABELS = {
    "CORN": "Corn", "SOYBEANS": "Soybeans", "SOYBEAN_MEAL": "Soybean meal",
    "SOYBEAN_OIL": "Soybean oil", "WHEAT_SRW": "Wheat (SRW, CBOT)",
    "WHEAT_HRW": "Wheat (HRW, KC)", "WHEAT_HRS": "Wheat (HRS, MIAX)", "OATS": "Oats",
    "ROUGH_RICE": "Rough rice", "CANOLA": "Canola (ICE)", "LIVE_CATTLE": "Live cattle",
    "FEEDER_CATTLE": "Feeder cattle", "LEAN_HOGS": "Lean hogs",
    "LIVE_HOGS": "Live hogs (to 1996)", "MILK_CLASS_III": "Class III milk",
    "COTTON": "Cotton", "SUGAR_11": "Sugar #11", "COFFEE": "Coffee", "COCOA": "Cocoa",
}
ORDER = list(LABELS)
LOOKBACKS = {"1Y": 52, "3Y": 156, "5Y": 260, "10Y": 520, "All": None}
REPORT_TYPES = {"Futures only": "FUT", "Futures + options": "COMBINED"}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap');
html, body, h1, h2, h3, h4, h5, h6, p, span, div, label, button, td, th {{
    font-family: 'Source Sans 3', 'Source Sans Pro', sans-serif;
}}
.block-container {{ padding-top: 3.2rem; max-width: 1400px; }}
.dash-header {{ display:flex; align-items:center; gap:18px; padding-bottom:10px;
    border-bottom:3px solid {JSA_BLUE}; margin-bottom:14px; }}
.dash-header img {{ height:40px; }}
.dash-header .t {{ flex:1; text-align:center; }}
.dash-header .t b {{ font-size:1.55rem; color:{JSA_DARK}; }}
.dash-header .t div {{ font-size:.85rem; color:{MUTED}; }}
@media (max-width: 640px) {{ .dash-header img {{ display:none; }} }}
</style>
<div class="dash-header">
  <img src="https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png">
  <div class="t"><b>CFTC Commitments of Traders</b>
  <div>Positioning in ag futures &middot; John Stewart &amp; Associates</div></div>
</div>
""", unsafe_allow_html=True)


def label(s: str) -> str:
    return LABELS.get(s, s.replace("_", " ").title())


def fmt(v, signed=False) -> str:
    if pd.isna(v):
        return "–"
    return f"{v:+,.0f}" if signed else f"{v:,.0f}"


def cot_index(s: pd.Series, weeks: int) -> float:
    """0-100 position of the latest value within its last `weeks` observations."""
    w = s.dropna().tail(weeks)
    if len(w) < 20 or w.max() == w.min():
        return float("nan")
    return float((w.iloc[-1] - w.min()) / (w.max() - w.min()) * 100)


def idx_text(v: float) -> str:
    return "–" if pd.isna(v) else f"{v:.0f}"


def trim(df: pd.DataFrame, lookback: str) -> pd.DataFrame:
    n = LOOKBACKS[lookback]
    return df if n is None else df.tail(n)


def layout(fig: go.Figure, title: str, height=420, yaxis_title="Contracts") -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=JSA_DARK)), height=height,
        margin=dict(l=10, r=10, t=50, b=10), plot_bgcolor="white", paper_bgcolor="white",
        hovermode="x unified", legend=dict(orientation="h", y=-0.12),
        yaxis=dict(title=yaxis_title, gridcolor=GRID, zerolinecolor="#b8c0c8"),
        xaxis=dict(gridcolor=GRID), font=dict(family="Source Sans 3, sans-serif"))
    return fig


def tint_change(v):
    if pd.isna(v) or v == 0:
        return ""
    return f"background-color: {POS_BG if v > 0 else NEG_BG}"


def tint_index(v):
    if pd.isna(v):
        return ""
    if v >= 80:
        return f"background-color: {POS_BG}"
    if v <= 20:
        return f"background-color: {NEG_BG}"
    return ""


def pick_market(series, key: str) -> str:
    present = set(series)
    avail = [s for s in ORDER if s in present] or sorted(present)
    return st.selectbox("Market", avail, format_func=label, key=key)


def load_disagg_or_stop(rt: str) -> pd.DataFrame:
    try:
        return cc.load_disagg(rt)
    except Exception as e:
        st.error(f"Could not read JSA.CFTC_COT: {e}")
        st.stop()


# ── Snapshot ────────────────────────────────────────────────────────────────
@st.fragment
def tab_snapshot():
    rt_label = st.segmented_control("Report", list(REPORT_TYPES), default="Futures only",
                                    key="snap_rt", label_visibility="collapsed")
    df = load_disagg_or_stop(REPORT_TYPES[rt_label or "Futures only"])
    rows = []
    for s, g in df.groupby("series"):
        g = g.sort_values("report_date")
        if len(g) < 2:
            continue
        last, prev = g.iloc[-1], g.iloc[-2]
        rows.append({
            "Market": label(s), "_s": s, "As of": last.report_date.date(),
            "MM net": last.mm_net, "Wk chg": last.mm_net - prev.mm_net,
            "MM % of OI": last.mm_net / last.open_interest * 100 if last.open_interest else float("nan"),
            "Index 1Y": cot_index(g.mm_net, 52), "Index 3Y": cot_index(g.mm_net, 156),
            "Prod/merc net": last.prod_merc_net, "Swap net": last.swap_net,
            "Open interest": last.open_interest, "OI chg": last.open_interest - prev.open_interest,
        })
    t = pd.DataFrame(rows)
    t["_o"] = t["_s"].map({s: i for i, s in enumerate(ORDER)}).fillna(99)
    t = t.sort_values("_o").drop(columns=["_s", "_o"]).set_index("Market")
    st.caption("Managed money (MM) net = long − short, in contracts. Index = where MM net sits in its "
               "1- or 3-year range (0 = most short, 100 = most long); shaded green ≥ 80, red ≤ 20.")
    sty = (t.style
           .map(tint_change, subset=["Wk chg", "OI chg"])
           .map(tint_index, subset=["Index 1Y", "Index 3Y"])
           .format({"MM net": "{:+,.0f}", "Wk chg": "{:+,.0f}", "MM % of OI": "{:+.1f}%",
                    "Index 1Y": "{:.0f}", "Index 3Y": "{:.0f}", "Prod/merc net": "{:+,.0f}",
                    "Swap net": "{:+,.0f}", "Open interest": "{:,.0f}", "OI chg": "{:+,.0f}"},
                   na_rep="–"))
    st.dataframe(sty, width="stretch", height=min(40 + 35 * len(t), 780))


# ── Market detail ───────────────────────────────────────────────────────────
@st.fragment
def tab_detail():
    c1, c2, c3 = st.columns([2, 2, 3])
    rt_label = c2.segmented_control("Report", list(REPORT_TYPES), default="Futures only", key="det_rt")
    lb = c3.segmented_control("Lookback", list(LOOKBACKS), default="3Y", key="det_lb")
    rt_label, lb = rt_label or "Futures only", lb or "3Y"
    df = load_disagg_or_stop(REPORT_TYPES[rt_label])
    with c1:
        s = pick_market(df.series.unique(), "det_mkt")
    g = df[df.series == s].sort_values("report_date")
    last, prev = g.iloc[-1], g.iloc[-2]

    m = st.columns(5)
    m[0].metric("MM net", fmt(last.mm_net), fmt(last.mm_net - prev.mm_net, True))
    m[1].metric("MM % of open interest", f"{last.mm_net / last.open_interest * 100:+.1f}%")
    m[2].metric("MM index (1Y / 3Y)", f"{idx_text(cot_index(g.mm_net, 52))} / {idx_text(cot_index(g.mm_net, 156))}")
    m[3].metric("Open interest", fmt(last.open_interest), fmt(last.open_interest - prev.open_interest, True))
    m[4].metric("As of", f"{last.report_date:%b %d, %Y}")

    shown = st.pills("Trader groups", list(GROUPS),
                     default=["Managed money", "Producer / merchant", "Swap dealers"],
                     selection_mode="multi", key="det_groups") or []
    w = trim(g, lb)
    fig = go.Figure()
    for name in shown:
        col, colour = GROUPS[name]
        fig.add_scatter(x=w.report_date, y=w[col], name=name, line=dict(color=colour, width=2.2),
                        hovertemplate="%{y:,.0f}")
    fig.add_hline(y=0, line_color="#b8c0c8", line_width=1)
    st.plotly_chart(layout(fig, f"{label(s)} — net positions by trader group"), width="stretch")

    fig = go.Figure()
    fig.add_bar(x=w.report_date, y=w.mm_long, name="MM long", marker_color="#5ec48c")
    fig.add_bar(x=w.report_date, y=-w.mm_short, name="MM short", marker_color="#e0716f")
    fig.add_scatter(x=w.report_date, y=w.mm_net, name="MM net", line=dict(color=JSA_DARK, width=2))
    fig.update_layout(barmode="relative")
    st.plotly_chart(layout(fig, f"{label(s)} — managed money long, short and net", 360), width="stretch")

    with st.expander("Weekly data"):
        cols = ["report_date", "mm_long", "mm_short", "mm_net", "prod_merc_net", "swap_net",
                "other_net", "nonrept_net", "open_interest", "traders_total"]
        st.dataframe(g[cols].sort_values("report_date", ascending=False).head(104)
                     .rename(columns=lambda c: c.replace("_", " ").title()),
                     width="stretch", hide_index=True)


# ── Seasonal overlay ────────────────────────────────────────────────────────
@st.fragment
def tab_seasonal():
    c1, c2, c3 = st.columns([2, 2, 2])
    rt_label = c2.segmented_control("Report", list(REPORT_TYPES), default="Futures only", key="sea_rt")
    df = load_disagg_or_stop(REPORT_TYPES[rt_label or "Futures only"])
    with c1:
        s = pick_market(df.series.unique(), "sea_mkt")
    grp = c3.selectbox("Trader group", list(GROUPS), key="sea_grp")
    col = GROUPS[grp][0]
    g = df[df.series == s].copy()
    g["year"] = g.report_date.dt.year
    g["week"] = g.report_date.dt.isocalendar().week.astype(int).clip(upper=52)
    years = sorted(g.year.unique())[-6:]
    palette = ["#c9d1d8", "#a3afba", "#7f8d99", "#5a6a78", "#f2b134", JSA_BLUE]
    fig = go.Figure()
    for i, y in enumerate(years):
        d = g[g.year == y].groupby("week")[col].last()
        cur = y == years[-1]
        fig.add_scatter(x=d.index, y=d.values, name=str(y), mode="lines",
                        line=dict(color=palette[len(palette) - len(years) + i], width=3.2 if cur else 1.8))
    fig.add_hline(y=0, line_color="#b8c0c8", line_width=1)
    fig.update_xaxes(title="Week of year")
    st.plotly_chart(layout(fig, f"{label(s)} — {grp.lower()} net by week of year, last {len(years)} years", 460),
                    width="stretch")


# ── Long history (legacy) ───────────────────────────────────────────────────
@st.fragment
def tab_history():
    c1, c2, c3 = st.columns([2, 2, 3])
    probe = load_disagg_or_stop("FUT")
    with c1:
        s = pick_market(probe.series.unique(), "his_mkt")
    rt_label = c2.segmented_control("Report", list(REPORT_TYPES), default="Futures only", key="his_rt")
    lb = c3.segmented_control("Lookback", list(LOOKBACKS), default="All", key="his_lb") or "All"
    g = cc.load_legacy(REPORT_TYPES[rt_label or "Futures only"], s)
    if g.empty:
        st.info("No legacy history for this market.")
        return
    w = trim(g, lb)
    fig = go.Figure()
    fig.add_scatter(x=w.report_date, y=w.comm_net, name="Commercial", line=dict(color="#f2b134", width=2))
    fig.add_scatter(x=w.report_date, y=w.noncomm_net, name="Non-commercial (speculators)",
                    line=dict(color=JSA_BLUE, width=2))
    fig.add_scatter(x=w.report_date, y=w.nonrept_net, name="Non-reportable",
                    line=dict(color="#84939f", width=1.4))
    fig.add_hline(y=0, line_color="#b8c0c8", line_width=1)
    st.plotly_chart(layout(fig, f"{label(s)} — commercial vs non-commercial net, legacy report", 460),
                    width="stretch")
    st.caption(f"History from {g.report_date.min():%Y} (futures from 1986, combined from 1995). "
               "Pre-1998 grain figures were published in thousand bushels and are converted to contracts.")


# ── Index traders ───────────────────────────────────────────────────────────
@st.fragment
def tab_cit():
    try:
        df = cc.load_cit()
    except Exception as e:
        st.error(f"Could not read JSA.CFTC_COT: {e}")
        st.stop()
    c1, c2 = st.columns([2, 3])
    with c1:
        s = pick_market(df.series.unique(), "cit_mkt")
    lb = c2.segmented_control("Lookback", list(LOOKBACKS), default="5Y", key="cit_lb") or "5Y"
    g = df[df.series == s].sort_values("report_date")
    last, prev = g.iloc[-1], g.iloc[-2]
    m = st.columns(4)
    m[0].metric("Index net", fmt(last.cit_net), fmt(last.cit_net - prev.cit_net, True))
    m[1].metric("Index long % of OI", f"{last.cit_long_pct_oi:.1f}%")
    m[2].metric("Index short % of OI", f"{last.cit_short_pct_oi:.1f}%")
    m[3].metric("As of", f"{last.report_date:%b %d, %Y}")
    w = trim(g, lb)
    fig = go.Figure()
    fig.add_bar(x=w.report_date, y=w.cit_long, name="Index long", marker_color="#5ec48c")
    fig.add_bar(x=w.report_date, y=-w.cit_short, name="Index short", marker_color="#e0716f")
    fig.add_scatter(x=w.report_date, y=w.cit_net, name="Index net", line=dict(color=JSA_DARK, width=2))
    fig.update_layout(barmode="relative")
    st.plotly_chart(layout(fig, f"{label(s)} — commodity index trader positions (futures + options)", 420),
                    width="stretch")
    st.caption("Supplemental report: index traders are carved out of the commercial and non-commercial "
               "groups. Covers 13 ag markets, futures and options combined.")


t1, t2, t3, t4, t5 = st.tabs(["Snapshot", "Market detail", "Seasonal", "Long history", "Index traders"])
with t1:
    tab_snapshot()
with t2:
    tab_detail()
with t3:
    tab_seasonal()
with t4:
    tab_history()
with t5:
    tab_cit()
