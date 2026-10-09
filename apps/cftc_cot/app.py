"""
CFTC Commitments of Traders Dashboard
Positioning in every CFTC-tracked ag futures market: managed money, producers,
swap dealers, index traders, and 40 years of commercial vs speculator history.

John Stewart & Associates
Data: CFTC Commitments of Traders, loaded weekly into Snowflake JSA.CFTC_COT
by cftc-cot-etl. Reports are as of Tuesday and released Friday 2:30pm CT.

Visual language follows the Livestock Portal's COT page (sage palette, hero and
stat tiles, uppercase section headers, green/red split net charts).
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# A page's own directory is never added to sys.path automatically.
sys.path.insert(0, str(Path(__file__).parent))
import cot_client as cc  # noqa: E402

# st.set_page_config removed -- the JSA Admin Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

# -- palette (matches livestock-portal/apps/cot_report) ------------------------
JSA_GREEN = "#5e7164"
DM_BG, DM_SURFACE, DM_BORDER = "#f6f8f7", "#ffffff", "#d7e2dc"
DM_TEXT, DM_MUTED = "#32373c", "#5f7267"
COL_POS, COL_NEG = "#16a34a", "#dc2626"
SPREAD_COLOR = "#b8c4bc"

GROUPS = {  # label -> (net column, colour)
    "Managed money": ("mm_net", "#6fa8c4"),
    "Producer / merchant": ("prod_merc_net", "#c4785a"),
    "Swap dealers": ("swap_net", "#5e7164"),
    "Other reportables": ("other_net", "#9b89c4"),
    "Non-reportable": ("nonrept_net", "#b8c4bc"),
}
MM_COLOR = GROUPS["Managed money"][1]

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
HERO_MARKETS = ["CORN", "SOYBEANS", "WHEAT_SRW"]
HERO_COLORS = {"CORN": "#6fa8c4", "SOYBEANS": "#c4785a", "WHEAT_SRW": "#9b89c4"}
LOOKBACKS = {"1Y": 52, "3Y": 156, "5Y": 260, "10Y": 520, "All": None}
REPORT_TYPES = {"Futures only": "FUT", "Futures + options": "COMBINED"}

AXIS = dict(gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
            tickfont=dict(color=DM_MUTED, size=11),
            title_font=dict(color=DM_MUTED, size=11), zeroline=False)

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
    border-radius:10px; padding:16px 20px; text-align:center; height:100%; }}
.tile-label {{ color:{DM_MUTED}; font-size:0.68rem; text-transform:uppercase; letter-spacing:0.09em; margin-bottom:6px; }}
.tile-value {{ color:{DM_TEXT}; font-size:1.55rem; font-weight:700; line-height:1.1; }}
.tile-sub {{ color:{DM_MUTED}; font-size:0.72rem; margin-top:5px; }}
.tile-delta-neu {{ color:{DM_MUTED}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
.hero {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-top:4px solid {JSA_GREEN};
    border-radius:12px; padding:20px 24px 18px; height:100%; }}
.hero-market {{ color:{DM_TEXT}; font-family:'EB Garamond',Georgia,serif; font-size:1.05rem; font-weight:600; }}
.hero-label {{ color:{DM_MUTED}; font-size:0.66rem; text-transform:uppercase; letter-spacing:0.09em; margin:2px 0 10px; }}
.hero-value {{ color:{DM_TEXT}; font-size:2.6rem; font-weight:700; line-height:1; }}
.hero-side-long {{ color:{COL_POS}; font-size:1.25rem; font-weight:700; }}
.hero-side-short {{ color:{COL_NEG}; font-size:1.25rem; font-weight:700; }}
.hero-unit {{ color:{DM_MUTED}; font-size:0.74rem; margin-top:6px; }}
.hero-delta-neu {{ color:{DM_MUTED}; font-size:0.92rem; font-weight:600; margin-top:10px; }}
.hero-legs {{ color:{DM_MUTED}; font-size:0.76rem; margin-top:8px; line-height:1.5; }}
.sec-header {{ color:{DM_MUTED}; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.1em;
    padding:10px 0 4px; border-bottom:1px solid {DM_BORDER}; margin-bottom:12px; }}
.asof {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-radius:8px; padding:10px 16px;
    color:{DM_MUTED}; font-size:0.82rem; margin-bottom:12px; }}
.asof b {{ color:{DM_TEXT}; }}
hr {{ border-color:{DM_BORDER}; }}
#MainMenu, footer {{ visibility:hidden; }}
.stDeployButton {{ display:none; }}
</style>
<div class="dash-header">
  <img src="https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png">
  <div class="t"><b>CFTC Commitments of Traders</b>
  <div>Positioning in ag futures &middot; John Stewart &amp; Associates</div></div>
</div>
""", unsafe_allow_html=True)


# -- helpers ----------------------------------------------------------------
def label(s: str) -> str:
    return LABELS.get(s, s.replace("_", " ").title())


def fmt(v) -> str:
    return "—" if pd.isna(v) else f"{v:,.0f}"


def _us(d) -> str:
    return "—" if d is None or pd.isna(d) else f"{d.month}/{d.day}/{str(d.year)[2:]}"


def side(net) -> str:
    return "flat" if net == 0 else ("long" if net > 0 else "short")


def signed_words(net):
    """'381,220' + 'long'. The direction is a word, never a parenthesised negative."""
    if pd.isna(net):
        return "—", ""
    s = side(net)
    return ("flat", "") if s == "flat" else (f"{abs(net):,.0f}", s)


def ordinal(p) -> str:
    if pd.isna(p):
        return "—"
    n = int(round(p))
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def pctile(s: pd.Series, weeks: int | None = None) -> float:
    w = s.dropna()
    if weeks:
        w = w.tail(weeks)
    return float("nan") if len(w) < 20 else float((w <= w.iloc[-1]).mean() * 100)


def cot_index(s: pd.Series, weeks: int) -> float:
    """0-100 position of the latest value within its last `weeks` observations."""
    w = s.dropna().tail(weeks)
    if len(w) < 20 or w.max() == w.min():
        return float("nan")
    return float((w.iloc[-1] - w.min()) / (w.max() - w.min()) * 100)


def idx_text(v: float) -> str:
    return "–" if pd.isna(v) else f"{v:.0f}"


def movement(delta, unit="contracts", suffix="", cls="tile-delta") -> str:
    """Arrow plus buy/sell words. Neutral colour: funds adding length is not good or bad news."""
    if pd.isna(delta):
        return f'<div class="{cls}-neu">&mdash;</div>'
    if delta == 0:
        return f'<div class="{cls}-neu">unchanged{suffix}</div>'
    return (f'<div class="{cls}-neu">{"▲" if delta > 0 else "▼"} {abs(delta):,.0f} '
            f'{"bought" if delta > 0 else "sold"}{suffix}</div>')


def tile(label_, value, delta="", sub="", color=None) -> str:
    style = f' style="border-top-color:{color}"' if color else ""
    sub_html = f'<div class="tile-sub">{sub}</div>' if sub else ""
    return (f'<div class="tile"{style}><div class="tile-label">{label_}</div>'
            f'<div class="tile-value">{value}</div>{delta}{sub_html}</div>')


def sec(text: str):
    st.markdown(f'<div class="sec-header">{text}</div>', unsafe_allow_html=True)


def trim(df: pd.DataFrame, lookback: str) -> pd.DataFrame:
    n = LOOKBACKS[lookback]
    return df if n is None else df.tail(n)


def style_fig(fig: go.Figure, height=340, yaxis_title="contracts", legend=True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE, hovermode="x unified",
        showlegend=legend, legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11, color=DM_MUTED)),
        xaxis=dict(**AXIS), yaxis=dict(**AXIS, title=yaxis_title))
    return fig


def net_figure(w: pd.DataFrame, col: str, color: str, as_share=False) -> go.Figure:
    """Net over time, filled to zero and split at the zero line (green long, red short)."""
    y = (w[col] / w["open_interest"] * 100) if as_share else w[col]
    fig = go.Figure()
    for clip, c, rgba, nm in ((dict(lower=0), COL_POS, "rgba(22,163,74,0.20)", "net long"),
                              (dict(upper=0), COL_NEG, "rgba(220,38,38,0.20)", "net short")):
        fig.add_trace(go.Scatter(x=w.report_date, y=y.clip(**clip), mode="lines",
                                 line=dict(width=0.8, color=c), fill="tozeroy", fillcolor=rgba,
                                 name=nm, hovertemplate="%{x|%b %d, %Y}<br>net %{y:,.1f}<extra></extra>"
                                 if as_share else "%{x|%b %d, %Y}<br>net %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=w.report_date, y=y, mode="lines", line=dict(width=1.6, color=color),
                             name="net", hoverinfo="skip"))
    fig.add_hline(y=0, line_width=1.2, line_color=DM_MUTED)
    return style_fig(fig, 340, "% of open interest" if as_share else "contracts", legend=False)


def load_disagg_or_stop(rt: str) -> pd.DataFrame:
    try:
        return cc.load_disagg(rt)
    except Exception as e:
        st.error(f"**The CFTC positions could not be read.** `{e}`")
        st.stop()


def pick_market(series, key: str) -> str:
    present = set(series)
    avail = [s for s in ORDER if s in present] or sorted(present)
    return st.selectbox("Market", avail, format_func=label, key=key)


# -- as-of band and hero tiles (futures only, above the tabs) -------------------
fut = load_disagg_or_stop("FUT")
latest_date = fut[fut.series == "CORN"].report_date.max()
age = (date.today() - latest_date.date()).days
st.markdown(
    f'<div class="asof">Positions as they stood at the close on <b>Tuesday {_us(latest_date)}</b>, '
    f'published by CFTC on Friday {_us(latest_date + pd.Timedelta(days=3))}. These positions are '
    f'<b>{age} days old</b>. CFTC publishes once a week and never intraday, so this is the most '
    f'recent reading that exists &mdash; it is not a position held today.</div>', unsafe_allow_html=True)

hero_cols = st.columns(len(HERO_MARKETS))
for col, s in zip(hero_cols, HERO_MARKETS):
    g = fut[fut.series == s].sort_values("report_date")
    if len(g) < 2:
        continue
    L, P = g.iloc[-1], g.iloc[-2]
    mag, word = signed_words(L.mm_net)
    side_html = f' <span class="hero-side-{word}">{word}</span>' if word else ""
    legs = (f"Long {L.mm_long:,.0f} against short {L.mm_short:,.0f} · spreading {fmt(L.mm_spread)}"
            f"<br>Producers / merchants net {side(L.prod_merc_net)} {abs(L.prod_merc_net):,.0f}")
    with col:
        st.markdown(
            f'<div class="hero" style="border-top-color:{HERO_COLORS[s]}">'
            f'<div class="hero-market">{label(s)}</div>'
            f'<div class="hero-label">Managed money net futures position</div>'
            f'<div class="hero-value">{mag}{side_html}</div>'
            f'<div class="hero-unit">contracts, as of Tuesday {_us(L.report_date)}</div>'
            f'{movement(L.mm_net - P.mm_net, suffix=" vs week earlier", cls="hero-delta")}'
            f'<div class="hero-legs">{legs}</div></div>', unsafe_allow_html=True)
st.write("")


# -- Snapshot ------------------------------------------------------------------
def tint_change(v):
    if pd.isna(v) or v == 0:
        return ""
    return f"background-color: {'#e8f5e9' if v > 0 else '#ffebee'}"


def tint_index(v):
    if pd.isna(v):
        return ""
    return "background-color: #e8f5e9" if v >= 80 else ("background-color: #ffebee" if v <= 20 else "")


@st.fragment
def tab_snapshot():
    sec("Every market, managed money")
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


# -- Market detail -------------------------------------------------------------
@st.fragment
def tab_detail():
    c1, c2 = st.columns([2, 2])
    rt_label = c2.segmented_control("Report", list(REPORT_TYPES), default="Futures only", key="det_rt") \
        or "Futures only"
    df = load_disagg_or_stop(REPORT_TYPES[rt_label])
    with c1:
        s = pick_market(df.series.unique(), "det_mkt")
    g = df[df.series == s].sort_values("report_date")
    L, P = g.iloc[-1], g.iloc[-2]
    color = HERO_COLORS.get(s, MM_COLOR)
    n = len(g)

    sec("How big is this position, historically")
    c = st.columns(4)
    c[0].markdown(tile(f"{label(s)} net vs its own record", ordinal(pctile(g.mm_net)) + " percentile",
                       sub=f"of {n:,} weekly readings since {g.report_date.min().year}", color=color),
                  unsafe_allow_html=True)
    c[1].markdown(tile(f"{label(s)} net vs the last 5 years", ordinal(pctile(g.mm_net, 260)) + " percentile",
                       sub="the era the market is actually trading in", color=color), unsafe_allow_html=True)
    hi, lo = g.loc[g.mm_net.idxmax()], g.loc[g.mm_net.idxmin()]
    hm, hw = signed_words(hi.mm_net)
    lm, lw = signed_words(lo.mm_net)
    c[2].markdown(tile("Most net long ever, in contracts", f"{hm} {hw}",
                       sub=f"week of {_us(hi.report_date)}", color=color), unsafe_allow_html=True)
    c[3].markdown(tile("Most net short ever, in contracts" if lo.mm_net < 0 else "Least net long ever, in contracts",
                       f"{lm} {lw}", sub=f"week of {_us(lo.report_date)}", color=color), unsafe_allow_html=True)
    st.write("")
    c = st.columns(4)
    c[0].markdown(tile("MM net, this week", " ".join(signed_words(L.mm_net)),
                       delta=movement(L.mm_net - P.mm_net), sub=f"as of {_us(L.report_date)}", color=color),
                  unsafe_allow_html=True)
    c[1].markdown(tile("MM net as a share of open interest", f"{L.mm_net / L.open_interest * 100:+.1f}%",
                       sub=f"1Y index {idx_text(cot_index(g.mm_net, 52))} · 3Y index "
                           f"{idx_text(cot_index(g.mm_net, 156))}", color=color), unsafe_allow_html=True)
    oi_chg = L.open_interest - P.open_interest
    c[2].markdown(tile("Open interest", fmt(L.open_interest),
                       delta=f'<div class="tile-delta-neu">{"▲" if oi_chg >= 0 else "▼"} '
                             f'{abs(oi_chg):,.0f} vs week earlier</div>', color=color),
                  unsafe_allow_html=True)
    c[3].markdown(tile("Traders reporting", fmt(L.traders_total), sub="all categories", color=color),
                  unsafe_allow_html=True)

    st.write("")
    sec(f"{label(s)} — managed money net position, week by week")
    l, r = st.columns([3, 2])
    with l:
        lb = st.segmented_control("Window", list(LOOKBACKS), default="3Y", key="det_lb",
                                  label_visibility="collapsed") or "3Y"
    with r:
        share = st.toggle("Show as a share of open interest", key="det_share",
                          help="Open interest changes a lot over time, so a contract count is not "
                               "comparable across the full history. The share is.")
    w = trim(g, lb)
    st.plotly_chart(net_figure(w, "mm_net", color, share), width="stretch", key="det_net")

    sec("The net taken apart — gross long, gross short and spreading")
    fig = go.Figure()
    for col_, nm, c_ in (("mm_long", "Long", COL_POS), ("mm_short", "Short", COL_NEG),
                         ("mm_spread", "Spreading", SPREAD_COLOR)):
        fig.add_scatter(x=w.report_date, y=w[col_], name=nm, mode="lines", line=dict(width=1.5, color=c_),
                        hovertemplate=nm + " %{y:,.0f}<extra></extra>")
    st.plotly_chart(style_fig(fig, 300), width="stretch", key="det_legs")

    sec("Who is on the other side of the funds, this week")
    cats = [(nm, float(L[col_])) for nm, (col_, _) in GROUPS.items()][::-1]
    fig = go.Figure(go.Bar(x=[v for _, v in cats], y=[n_ for n_, _ in cats], orientation="h",
                           marker_color=[COL_POS if v >= 0 else COL_NEG for _, v in cats],
                           hovertemplate="%{y}<br>net %{x:,.0f} contracts<extra></extra>"))
    fig.add_vline(x=0, line_width=1.2, line_color=DM_MUTED)
    style_fig(fig, 250, "", legend=False)
    fig.update_layout(xaxis=dict(**AXIS, title="net contracts — long above zero, short below"),
                      yaxis={**AXIS, "showgrid": False}, hovermode="closest")
    st.plotly_chart(fig, width="stretch", key="det_cats")
    bal = sum(v for _, v in cats)
    st.caption(f"Every long contract is somebody's short, so the five categories sum to about zero "
               f"(this week: {bal:+,.0f}). Managed money is one of five groups the Disaggregated report splits "
               "the market into.")

    sec("Trader groups over time")
    shown = st.pills("Trader groups", list(GROUPS), default=["Managed money", "Producer / merchant", "Swap dealers"],
                     selection_mode="multi", key="det_groups", label_visibility="collapsed") or []
    fig = go.Figure()
    for name in shown:
        col_, c_ = GROUPS[name]
        fig.add_scatter(x=w.report_date, y=w[col_], name=name, line=dict(color=c_, width=2),
                        hovertemplate="%{y:,.0f}")
    fig.add_hline(y=0, line_width=1.2, line_color=DM_MUTED)
    st.plotly_chart(style_fig(fig, 340), width="stretch", key="det_groups_fig")

    with st.expander("Weekly data"):
        cols = ["report_date", "mm_long", "mm_short", "mm_net", "prod_merc_net", "swap_net",
                "other_net", "nonrept_net", "open_interest", "traders_total"]
        st.dataframe(g[cols].sort_values("report_date", ascending=False).head(104)
                     .rename(columns=lambda c_: c_.replace("_", " ").title()),
                     width="stretch", hide_index=True)


# -- Seasonal overlay ----------------------------------------------------------
@st.fragment
def tab_seasonal():
    c1, c2, c3 = st.columns([2, 2, 2])
    rt_label = c2.segmented_control("Report", list(REPORT_TYPES), default="Futures only", key="sea_rt")
    df = load_disagg_or_stop(REPORT_TYPES[rt_label or "Futures only"])
    with c1:
        s = pick_market(df.series.unique(), "sea_mkt")
    grp = c3.selectbox("Trader group", list(GROUPS), key="sea_grp")
    col_ = GROUPS[grp][0]
    g = df[df.series == s].copy()
    g["year"] = g.report_date.dt.year
    g["week"] = g.report_date.dt.isocalendar().week.astype(int).clip(upper=52)
    years = sorted(g.year.unique())[-6:]
    palette = ["#d7e2dc", "#b8c4bc", "#8fa398", "#5f7267", "#c4785a", "#6fa8c4"]
    sec(f"{label(s)} — {grp.lower()} net by week of year, last {len(years)} years")
    fig = go.Figure()
    for i, y in enumerate(years):
        d = g[g.year == y].groupby("week")[col_].last()
        fig.add_scatter(x=d.index, y=d.values, name=str(y), mode="lines",
                        line=dict(color=palette[len(palette) - len(years) + i],
                                  width=3.2 if y == years[-1] else 1.8))
    fig.add_hline(y=0, line_width=1.2, line_color=DM_MUTED)
    style_fig(fig, 460)
    fig.update_xaxes(title="week of year")
    st.plotly_chart(fig, width="stretch")


# -- Long history (legacy) -----------------------------------------------------
@st.fragment
def tab_history():
    c1, c2, c3 = st.columns([2, 2, 3])
    with c1:
        s = pick_market(fut.series.unique(), "his_mkt")
    rt_label = c2.segmented_control("Report", list(REPORT_TYPES), default="Futures only", key="his_rt")
    lb = c3.segmented_control("Window", list(LOOKBACKS), default="All", key="his_lb") or "All"
    g = cc.load_legacy(REPORT_TYPES[rt_label or "Futures only"], s)
    if g.empty:
        st.info("No legacy history for this market.")
        return
    w = trim(g, lb)
    sec(f"{label(s)} — commercial vs non-commercial net, legacy report")
    fig = go.Figure()
    fig.add_scatter(x=w.report_date, y=w.comm_net, name="Commercial", line=dict(color="#c4785a", width=1.8))
    fig.add_scatter(x=w.report_date, y=w.noncomm_net, name="Non-commercial (speculators)",
                    line=dict(color="#6fa8c4", width=1.8))
    fig.add_scatter(x=w.report_date, y=w.nonrept_net, name="Non-reportable", line=dict(color="#b8c4bc", width=1.4))
    fig.add_hline(y=0, line_width=1.2, line_color=DM_MUTED)
    st.plotly_chart(style_fig(fig, 460), width="stretch")
    st.caption(f"History from {g.report_date.min():%Y} (futures from 1986, combined from 1995). "
               "Pre-1998 grain figures were published in thousand bushels and are converted to contracts.")


# -- Index traders -------------------------------------------------------------
@st.fragment
def tab_cit():
    try:
        df = cc.load_cit()
    except Exception as e:
        st.error(f"**The index-trader positions could not be read.** `{e}`")
        st.stop()
    c1, c2 = st.columns([2, 3])
    with c1:
        s = pick_market(df.series.unique(), "cit_mkt")
    lb = c2.segmented_control("Window", list(LOOKBACKS), default="5Y", key="cit_lb") or "5Y"
    g = df[df.series == s].sort_values("report_date")
    L, P = g.iloc[-1], g.iloc[-2]
    mag, word = signed_words(L.cit_net)
    c = st.columns(4)
    c[0].markdown(tile("Index traders net", f"{mag} {word}", delta=movement(L.cit_net - P.cit_net),
                       sub=f"as of {_us(L.report_date)}"), unsafe_allow_html=True)
    c[1].markdown(tile("Index long, % of open interest", f"{L.cit_long_pct_oi:.1f}%"), unsafe_allow_html=True)
    c[2].markdown(tile("Index short, % of open interest", f"{L.cit_short_pct_oi:.1f}%"), unsafe_allow_html=True)
    c[3].markdown(tile("Open interest", fmt(L.open_interest), sub="futures + options"), unsafe_allow_html=True)
    st.write("")
    w = trim(g, lb)
    sec(f"{label(s)} — commodity index trader positions")
    fig = go.Figure()
    fig.add_bar(x=w.report_date, y=w.cit_long, name="Index long", marker_color=COL_POS)
    fig.add_bar(x=w.report_date, y=-w.cit_short, name="Index short", marker_color=COL_NEG)
    fig.add_scatter(x=w.report_date, y=w.cit_net, name="Index net", line=dict(color=DM_TEXT, width=1.6))
    fig.update_layout(barmode="relative")
    st.plotly_chart(style_fig(fig, 420), width="stretch")
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
