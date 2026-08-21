import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.express as px
import plotly.graph_objects as go

# st.set_page_config removed — the JSA Admin Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

# ── Constants ──────────────────────────────────────────────────────────────────
API_URL      = "https://agtransport.usda.gov/resource/27k8-utc2.json"
CARS_TO_BU   = 4_000
MIN_COMPLETE_WEEK = 48   # weeks to consider a MY "complete"

DEST_MAP = {
    "BNSF": "Western",  "UP": "Western",
    "CSX":  "Eastern",  "NS": "Eastern",
    "CN":   "Central",
    "CP":   "Central/Canada", "CPKC": "Central/Canada",
    "KCS":  "Central/Mexico",
}

RR_ORDER = ["BNSF", "UP", "CSX", "NS", "CN", "CP", "CPKC", "KCS"]
RR_COLORS = {
    "BNSF": "#f97316", "UP": "#fbbf24", "CSX": "#34d399",
    "NS":   "#60a5fa", "CN": "#a78bfa", "CP":  "#f87171",
    "CPKC": "#fb923c", "KCS": "#4ade80",
}
DEST_COLORS = {
    "Western": "#f97316", "Eastern": "#60a5fa",
    "Central": "#a78bfa", "Central/Canada": "#fb923c",
    "Central/Mexico": "#4ade80",
}

MY_MONTHS = {
    1: "Sep", 2: "Oct",  3: "Nov", 4: "Dec",
    5: "Jan", 6: "Feb",  7: "Mar", 8: "Apr",
    9: "May", 10: "Jun", 11: "Jul", 12: "Aug",
}

WESTERN_STATES = ["IA", "NE", "SD", "ND", "MN", "KS", "MO"]
EASTERN_STATES = ["IL", "IN", "OH", "MI", "KY"]

PLOT_BASE = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font_color="#32373c",
    xaxis=dict(gridcolor="#e2e8e4", linecolor="#d7e2dc"),
    yaxis=dict(gridcolor="#e2e8e4", linecolor="#d7e2dc"),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#d7e2dc"),
    margin=dict(t=50, b=40, l=40, r=20),
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #f6f8f7; }
[data-testid="stHeader"]            { background: transparent; }
.block-container                    { padding-top: 1.2rem; }
div[data-testid="stTabs"] button[aria-selected="true"] {
    border-bottom: 2px solid #4a5d58; color: #32373c;
}
div[data-testid="metric-container"] {
    background: #ffffff; border: 1px solid #d7e2dc;
    border-radius: 10px; padding: 14px;
}
</style>
""", unsafe_allow_html=True)

# ── Data fetch & transform ─────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="Fetching USDA rail data…")
def load_data() -> pd.DataFrame:
    rows, limit, offset = [], 50_000, 0
    while True:
        r = requests.get(
            API_URL,
            params={"$limit": limit, "$offset": offset, "$order": "date ASC"},
            timeout=60,
        )
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    for col in ["all", "dedicated_or_shuttle", "other"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df = df.drop(
        columns=["submission_date", "week", "month", "year", "state_point"],
        errors="ignore",
    ).rename(columns={"all": "carloads"})

    # Marketing year fields (vectorised)
    m = df["date"].dt.month
    y = df["date"].dt.year
    is_sep_plus = m >= 9
    sy = np.where(is_sep_plus, y, y - 1)                        # MY start year

    df["marketing_year"] = [f"{s}/{str(s+1)[2:]}" for s in sy]

    my_starts = pd.to_datetime(
        {"year": sy, "month": np.full(len(df), 9), "day": np.full(len(df), 1)}
    )
    df["my_week"]  = ((df["date"] - my_starts).dt.days // 7 + 1).astype(int)
    df["my_month"] = np.where(is_sep_plus, m - 8, m + 4).astype(int)

    df["est_bushels"] = df["carloads"] * CARS_TO_BU
    df["destination"] = df["railroad"].map(DEST_MAP).fillna("Other")

    return (
        df[["date", "marketing_year", "my_week", "my_month",
            "railroad", "state", "destination",
            "carloads", "dedicated_or_shuttle", "other", "est_bushels"]]
        .sort_values(["date", "railroad", "state"])
        .reset_index(drop=True)
    )

# ── Helpers ────────────────────────────────────────────────────────────────────
def fmt_bu(n: float) -> str:
    n = int(n) if pd.notna(n) else 0
    if n >= 1_000_000_000: return f"{n/1_000_000_000:.2f}B bu"
    if n >= 1_000_000:     return f"{n/1_000_000:.1f}M bu"
    return f"{n:,.0f} bu"

def fmt_cars(n: float) -> str:
    return f"{int(n):,}" if pd.notna(n) else "—"

def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

def oly_avg(vals: list) -> int:
    v = sorted(x for x in vals if x > 0)
    if len(v) >= 4:
        v = v[1:-1]
    return int(np.mean(v)) if v else 0

def pct_diff(curr: int, base: int):
    if not base:
        return None
    return (curr - base) / base * 100

def complete_years(df: pd.DataFrame) -> list:
    wk_max = df.groupby("marketing_year")["my_week"].max()
    return sorted(y for y, w in wk_max.items() if w >= MIN_COMPLETE_WEEK)

def mytd_sum(df: pd.DataFrame, year: str, max_wk: int,
             rr=None, state=None) -> int:
    mask = (df["marketing_year"] == year) & (df["my_week"] <= max_wk)
    if rr == "CP/CPKC":
        mask &= df["railroad"].isin(["CP", "CPKC"])
    elif rr and rr != "All":
        mask &= df["railroad"] == rr
    if state and state != "All":
        mask &= df["state"] == state
    return int(df.loc[mask, "est_bushels"].sum())

# ── Load ───────────────────────────────────────────────────────────────────────
df = load_data()

all_years   = sorted(df["marketing_year"].unique(), reverse=True)
all_rrs     = [r for r in RR_ORDER if r in df["railroad"].unique()]
all_states  = sorted(df["state"].unique())
comp_yrs    = complete_years(df)
current_my  = all_years[0]

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("## 🚂 JSA Grain Rail Shipment Dashboard")
st.caption(
    f"Source: USDA AMS Agricultural Transportation Hub  ·  "
    f"Latest data: {df['date'].max().strftime('%b %d, %Y')}  ·  "
    f"Refreshes hourly"
)
st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────
(tab_prog, tab_monthly, tab_map,
 tab_weekly, tab_yearly, tab_summary) = st.tabs([
    "📈 Progress", "📊 Railroad by Month", "🗺️ State Map",
    "📉 Weekly by Year", "🔥 Yearly by Railroad", "⚙️ Summary",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — PROGRESS
# ══════════════════════════════════════════════════════════════════════════════
with tab_prog:
    f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
    with f1: sel_year  = st.selectbox("Marketing Year", all_years, key="p_year")
    with f2: sel_rr    = st.selectbox("Railroad", ["All"] + all_rrs, key="p_rr")
    with f3: sel_state = st.selectbox("State", ["All"] + all_states, key="p_state")
    with f4: cp_mode   = st.radio("CP/CPKC History", ["Combined", "Split"],
                                  horizontal=True, key="cp_mode")

    state_grp = st.radio(
        "State Group",
        ["🏆 Top 15", "All States", "🌾 Western  (IA · NE · SD · ND · MN · KS · MO)",
         "🏭 Eastern  (IL · IN · OH · MI · KY)"],
        horizontal=True, key="state_grp", label_visibility="collapsed",
    )

    # Context for selected year
    yr_df   = df[df["marketing_year"] == sel_year]
    max_wk  = int(yr_df["my_week"].max()) if len(yr_df) else 0
    prior   = [y for y in comp_yrs if y < sel_year]
    oly_pool = prior[-6:]
    ly       = prior[-1] if prior else None

    # Railroad list based on CP mode
    if cp_mode == "Combined":
        rr_list = [r for r in RR_ORDER if r not in ("CP", "CPKC")]
        cp_idx  = RR_ORDER.index("CP")
        rr_list.insert(cp_idx, "CP/CPKC")
    else:
        rr_list = list(RR_ORDER)

    # Apply single-RR filter
    if sel_rr != "All":
        if cp_mode == "Combined" and sel_rr in ("CP", "CPKC"):
            rr_list = ["CP/CPKC"]
        else:
            rr_list = [sel_rr]

    # ── Progress table ─────────────────────────────────────────────────────────
    oly_label = (f"{oly_pool[0]}–{oly_pool[-1]} (drop hi/lo)"
                 if oly_pool else "N/A")
    st.markdown(f"#### MYtD Shipments — {sel_year}  ·  Week {max_wk}")
    st.caption(f"vs LY: {ly or 'N/A'}  ·  6-yr avg pool: {oly_label}")

    state_arg = sel_state if sel_state != "All" else None
    rows = []
    for rr in rr_list:
        curr_v = mytd_sum(df, sel_year, max_wk, rr, state_arg)
        ly_v   = mytd_sum(df, ly, max_wk, rr, state_arg) if ly else 0
        oly_v  = oly_avg([mytd_sum(df, y, max_wk, rr, state_arg) for y in oly_pool])

        incomplete = cp_mode == "Split" and rr in ("CP", "CPKC")
        p_ly  = pct_diff(curr_v, ly_v)  if not incomplete else None
        p_avg = pct_diff(curr_v, oly_v) if not incomplete else None

        rows.append({
            "Railroad":            rr,
            "MYtD Est. Bushels":   fmt_bu(curr_v),
            "vs LY":               ("—" if incomplete else fmt_bu(curr_v - ly_v)),
            "% vs LY":             fmt_pct(p_ly),
            "vs 6-yr Avg":         ("—" if incomplete else fmt_bu(curr_v - oly_v)),
            "% vs Avg":            fmt_pct(p_avg),
            "_curr": curr_v, "_p_ly": p_ly, "_p_avg": p_avg,
            "_incomplete": incomplete,
        })

    # Total row (complete railroads only)
    total_curr = sum(r["_curr"] for r in rows if not r["_incomplete"])
    rows.append({
        "Railroad": "TOTAL",
        "MYtD Est. Bushels": fmt_bu(total_curr),
        "vs LY": "—", "% vs LY": "—", "vs 6-yr Avg": "—", "% vs Avg": "—",
        "_curr": total_curr, "_p_ly": None, "_p_avg": None, "_incomplete": False,
    })

    display_cols = ["Railroad", "MYtD Est. Bushels", "vs LY", "% vs LY", "vs 6-yr Avg", "% vs Avg"]
    tbl = pd.DataFrame(rows)[display_cols]
    st.dataframe(tbl, use_container_width=True, hide_index=True)

    st.divider()

    # ── RR Deviation chart ─────────────────────────────────────────────────────
    chart_rows = [r for r in rows
                  if r["Railroad"] != "TOTAL"
                  and not r["_incomplete"]
                  and r["_p_ly"] is not None]

    if chart_rows:
        rr_names  = [r["Railroad"] for r in chart_rows]
        rr_pcts   = [r["_p_ly"] for r in chart_rows]
        rr_colors = ["#34d399" if v >= 0 else "#f87171" for v in rr_pcts]
        rr_texts  = [fmt_pct(v) for v in rr_pcts]

        fig_rr = go.Figure(go.Bar(
            x=rr_names, y=rr_pcts,
            marker_color=rr_colors,
            text=rr_texts, textposition="outside",
        ))
        fig_rr.update_layout(
            title=f"Railroad % vs Last Year — {sel_year} MYtD (Week {max_wk})",
            yaxis_title="% vs LY",
            height=380,
            **{**PLOT_BASE, "yaxis": {**PLOT_BASE["yaxis"], "zeroline": True,
                                       "zerolinecolor": "#4a5d58"}},
        )
        st.plotly_chart(fig_rr, use_container_width=True)

    st.divider()

    # ── State deviation chart ──────────────────────────────────────────────────
    st.markdown("#### State Progress — MYtD % vs Last Year")

    if "Top 15" in state_grp:
        prior_comp = [y for y in comp_yrs if y != current_my][-6:]
        avgs = {
            s: oly_avg([
                int(df[(df["marketing_year"] == y) & (df["state"] == s)]["est_bushels"].sum())
                for y in prior_comp
            ])
            for s in all_states
        }
        state_list = sorted(avgs, key=avgs.get, reverse=True)[:15]
    elif "Western" in state_grp:
        state_list = WESTERN_STATES
    elif "Eastern" in state_grp:
        state_list = EASTERN_STATES
    else:
        state_list = all_states

    rr_arg = sel_rr if sel_rr != "All" else None
    state_rows = []
    for s in state_list:
        curr_s = mytd_sum(df, sel_year, max_wk, rr_arg, s)
        ly_s   = mytd_sum(df, ly, max_wk, rr_arg, s) if ly else 0
        if curr_s == 0:
            continue
        pct = pct_diff(curr_s, ly_s)
        state_rows.append({"state": s, "curr": curr_s, "pct_ly": pct})

    state_rows.sort(key=lambda x: (x["pct_ly"] or 0))

    if state_rows:
        s_df = pd.DataFrame(state_rows)
        fig_st = go.Figure(go.Bar(
            x=s_df["pct_ly"],
            y=s_df["state"],
            orientation="h",
            marker_color=["#34d399" if (v or 0) >= 0 else "#f87171"
                          for v in s_df["pct_ly"]],
            text=[fmt_pct(v) for v in s_df["pct_ly"]],
            textposition="outside",
        ))
        fig_st.update_layout(
            title=f"State % vs Last Year — {sel_year} MYtD (Week {max_wk})",
            xaxis_title="% vs LY",
            height=max(400, len(state_rows) * 30),
            **{**PLOT_BASE, "xaxis": {**PLOT_BASE["xaxis"], "zeroline": True,
                                       "zerolinecolor": "#4a5d58"}},
        )
        st.plotly_chart(fig_st, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — RAILROAD BY MONTH
# ══════════════════════════════════════════════════════════════════════════════
with tab_monthly:
    mc1, mc2, mc3 = st.columns(3)
    with mc1: m_year  = st.selectbox("Marketing Year", all_years, key="m_year")
    with mc2: m_rr    = st.selectbox("Railroad", ["All"] + all_rrs, key="m_rr")
    with mc3: m_state = st.selectbox("State", ["All"] + all_states, key="m_state")

    m_df = df[df["marketing_year"] == m_year].copy()
    if m_rr    != "All": m_df = m_df[m_df["railroad"] == m_rr]
    if m_state != "All": m_df = m_df[m_df["state"]    == m_state]

    monthly = (
        m_df.groupby(["my_month", "railroad"])["est_bushels"]
        .sum().reset_index()
    )
    monthly["month_name"] = monthly["my_month"].map(MY_MONTHS)
    monthly = monthly.sort_values("my_month")

    fig_m = px.bar(
        monthly, x="month_name", y="est_bushels", color="railroad",
        color_discrete_map=RR_COLORS, barmode="stack",
        labels={"est_bushels": "Est. Bushels", "month_name": "Month",
                "railroad": "Railroad"},
        title=f"Monthly Grain Rail Shipments — {m_year}",
        category_orders={"month_name": list(MY_MONTHS.values())},
    )
    fig_m.update_layout(height=450, **PLOT_BASE)
    st.plotly_chart(fig_m, use_container_width=True)

    # Pivot table
    pivot_m = (
        m_df.groupby(["railroad", "my_month"])["est_bushels"]
        .sum().unstack(fill_value=0)
    )
    pivot_m.columns = [MY_MONTHS[c] for c in pivot_m.columns]
    pivot_m["Total"] = pivot_m.sum(axis=1)
    pivot_m = pivot_m.reset_index().rename(columns={"railroad": "Railroad"})

    fmt_df = pivot_m.copy()
    for col in fmt_df.columns:
        if col != "Railroad":
            fmt_df[col] = fmt_df[col].apply(fmt_bu)

    st.dataframe(fmt_df, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — STATE MAP
# ══════════════════════════════════════════════════════════════════════════════
with tab_map:
    mapc1, mapc2, mapc3, mapc4 = st.columns(4)
    with mapc1: map_year   = st.selectbox("Marketing Year", all_years, key="map_year")
    with mapc2: map_rr     = st.selectbox("Railroad", ["All"] + all_rrs, key="map_rr")
    with mapc3: map_metric = st.radio("Metric", ["Est. Bushels", "Carloads"],
                                      horizontal=True, key="map_metric")
    with mapc4: map_wk_mode = st.radio("Period", ["Full Year", "MYtD"],
                                       horizontal=True, key="map_wk_mode")

    map_df = df[df["marketing_year"] == map_year].copy()
    if map_rr != "All":
        map_df = map_df[map_df["railroad"] == map_rr]

    if map_wk_mode == "MYtD":
        cur_wk = int(df[df["marketing_year"] == current_my]["my_week"].max()) \
                 if map_year == current_my else \
                 int(df[df["marketing_year"] == map_year]["my_week"].max())
        map_df = map_df[map_df["my_week"] <= cur_wk]

    metric_col = "est_bushels" if map_metric == "Est. Bushels" else "carloads"
    state_totals = map_df.groupby("state")[metric_col].sum().reset_index()

    fig_map = px.choropleth(
        state_totals, locations="state", locationmode="USA-states",
        color=metric_col, scope="usa",
        color_continuous_scale=[[0, "#162019"], [0.3, "#2d6a4f"],
                                 [0.7, "#4a5d58"], [1, "#95d5b2"]],
        labels={metric_col: map_metric},
        title=f"{map_metric} by State — {map_year}  ({map_wk_mode})",
    )
    fig_map.update_layout(
        geo_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="#d4e8e4",
        margin=dict(t=40, b=0, l=0, r=0),
    )
    st.plotly_chart(fig_map, use_container_width=True)

    # State breakdown table
    state_totals_sorted = state_totals.sort_values(metric_col, ascending=False)
    state_totals_sorted = state_totals_sorted.rename(columns={
        "state": "State",
        metric_col: map_metric,
    })
    if map_metric == "Est. Bushels":
        state_totals_sorted[map_metric] = state_totals_sorted[map_metric].apply(fmt_bu)
    else:
        state_totals_sorted[map_metric] = state_totals_sorted[map_metric].apply(fmt_cars)

    with st.expander("📋 State detail table"):
        st.dataframe(state_totals_sorted, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — WEEKLY BY YEAR
# ══════════════════════════════════════════════════════════════════════════════
with tab_weekly:
    wc1, wc2, wc3 = st.columns(3)
    with wc1: w_rr    = st.selectbox("Railroad", ["All"] + all_rrs, key="w_rr")
    with wc2: w_state = st.selectbox("State", ["All"] + all_states, key="w_state")
    with wc3: w_years = st.multiselect(
        "Marketing Years", all_years,
        default=all_years[:min(6, len(all_years))],
        key="w_years",
    )

    w_df = df.copy()
    if w_rr    != "All": w_df = w_df[w_df["railroad"] == w_rr]
    if w_state != "All": w_df = w_df[w_df["state"]    == w_state]

    sel_years_w = w_years if w_years else all_years[:6]
    weekly = (
        w_df[w_df["marketing_year"].isin(sel_years_w)]
        .groupby(["marketing_year", "my_week"])["est_bushels"]
        .sum().reset_index()
    )

    fig_wk = px.line(
        weekly, x="my_week", y="est_bushels", color="marketing_year",
        labels={"est_bushels": "Est. Bushels", "my_week": "MY Week",
                "marketing_year": "Marketing Year"},
        title="Weekly Grain Rail Shipments by Marketing Year",
    )
    fig_wk.update_layout(height=420, **PLOT_BASE)
    st.plotly_chart(fig_wk, use_container_width=True)

    # Cumulative
    weekly_cum = weekly.copy().sort_values(["marketing_year", "my_week"])
    weekly_cum["cumulative"] = weekly_cum.groupby("marketing_year")["est_bushels"].cumsum()

    fig_cum = px.line(
        weekly_cum, x="my_week", y="cumulative", color="marketing_year",
        labels={"cumulative": "Cumulative Est. Bushels", "my_week": "MY Week",
                "marketing_year": "Marketing Year"},
        title="Cumulative Shipments by Marketing Year",
    )
    fig_cum.update_layout(height=420, **PLOT_BASE)
    st.plotly_chart(fig_cum, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — YEARLY BY RAILROAD
# ══════════════════════════════════════════════════════════════════════════════
with tab_yearly:
    yc1, yc2, yc3 = st.columns(3)
    with yc1: y_state = st.selectbox("State", ["All"] + all_states, key="y_state")
    with yc2: y_dest  = st.selectbox(
        "Destination", ["All"] + sorted(df["destination"].unique()), key="y_dest"
    )
    with yc3: y_view  = st.radio("View", ["Stacked", "Grouped"],
                                 horizontal=True, key="y_view")

    y_df = df.copy()
    if y_state != "All": y_df = y_df[y_df["state"]       == y_state]
    if y_dest  != "All": y_df = y_df[y_df["destination"]  == y_dest]

    yearly = (
        y_df.groupby(["marketing_year", "railroad"])["est_bushels"]
        .sum().reset_index()
        .sort_values("marketing_year")
    )

    fig_y = px.bar(
        yearly, x="marketing_year", y="est_bushels", color="railroad",
        color_discrete_map=RR_COLORS,
        barmode="stack" if y_view == "Stacked" else "group",
        labels={"est_bushels": "Est. Bushels", "marketing_year": "Marketing Year",
                "railroad": "Railroad"},
        title="Annual Grain Rail Shipments by Railroad",
    )
    fig_y.update_layout(height=450, **PLOT_BASE)
    st.plotly_chart(fig_y, use_container_width=True)

    # Pivot table
    pivot_y = (
        yearly.pivot_table(index="railroad", columns="marketing_year",
                           values="est_bushels", fill_value=0)
        .reset_index()
        .rename(columns={"railroad": "Railroad"})
    )
    pivot_y.columns.name = None

    fmt_y = pivot_y.copy()
    for col in fmt_y.columns:
        if col != "Railroad":
            fmt_y[col] = fmt_y[col].apply(fmt_bu)

    st.dataframe(fmt_y, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
with tab_summary:
    cur_df  = df[df["marketing_year"] == current_my]
    max_wk_s = int(cur_df["my_week"].max()) if len(cur_df) else 0
    cur_wk_df = cur_df[cur_df["my_week"] <= max_wk_s]

    total_bu_s   = int(cur_wk_df["est_bushels"].sum())
    total_cars_s = int(cur_wk_df["carloads"].sum())

    ly_s   = comp_yrs[-1] if comp_yrs else None
    ly_bu_s = int(
        df[(df["marketing_year"] == ly_s) & (df["my_week"] <= max_wk_s)]["est_bushels"].sum()
    ) if ly_s else 0

    delta_str = (
        f"{fmt_bu(total_bu_s - ly_bu_s)} vs {ly_s}" if ly_bu_s else None
    )

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Current Marketing Year", current_my)
    sm2.metric("MYtD Est. Bushels", fmt_bu(total_bu_s), delta=delta_str)
    sm3.metric("MYtD Carloads",     fmt_cars(total_cars_s))
    sm4.metric("Weeks Reported",    str(max_wk_s))

    st.divider()

    col_dest, col_rr = st.columns(2)

    with col_dest:
        dest_tot = (
            cur_wk_df.groupby("destination")["est_bushels"]
            .sum().reset_index()
            .sort_values("est_bushels", ascending=False)
        )
        fig_dest = px.pie(
            dest_tot, names="destination", values="est_bushels",
            color="destination", color_discrete_map=DEST_COLORS,
            title=f"MYtD by Destination — {current_my}",
        )
        fig_dest.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", font_color="#d4e8e4",
            legend=dict(bgcolor="rgba(0,0,0,0)"),
        )
        st.plotly_chart(fig_dest, use_container_width=True)

    with col_rr:
        rr_tot = (
            cur_wk_df.groupby("railroad")["est_bushels"]
            .sum().reset_index()
            .sort_values("est_bushels", ascending=False)
        )
        fig_rr_s = px.bar(
            rr_tot, x="railroad", y="est_bushels",
            color="railroad", color_discrete_map=RR_COLORS,
            labels={"est_bushels": "Est. Bushels", "railroad": "Railroad"},
            title=f"MYtD by Railroad — {current_my}",
        )
        fig_rr_s.update_layout(showlegend=False, height=380, **PLOT_BASE)
        st.plotly_chart(fig_rr_s, use_container_width=True)

    st.divider()

    # Year-over-year total
    yoy = (
        df[df["marketing_year"].isin(comp_yrs + [current_my])]
        .groupby("marketing_year")["est_bushels"]
        .sum().reset_index()
        .sort_values("marketing_year")
    )
    fig_yoy = px.bar(
        yoy, x="marketing_year", y="est_bushels",
        labels={"est_bushels": "Est. Bushels", "marketing_year": "Marketing Year"},
        title="Full-Year Grain Rail Shipments — All Railroads",
    )
    fig_yoy.update_traces(marker_color="#4a5d58")
    fig_yoy.update_layout(height=380, **PLOT_BASE)
    st.plotly_chart(fig_yoy, use_container_width=True)

st.markdown(
    f'<div style="margin-top:40px;padding:14px 20px;border-top:1px solid #d7e2dc;'
    f'color:#6b7280;font-size:0.70rem;line-height:1.6;">'
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
    f'&copy; John Stewart &amp; Associates, Inc. {pd.Timestamp.now().year}'
    f'</div>',
    unsafe_allow_html=True,
)
