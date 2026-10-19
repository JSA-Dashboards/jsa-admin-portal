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
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import json

import nass_cache_client as ncc
from nass_cache_client import cache_freshness, fetch_cached

HERE = Path(__file__).parent
BLUE, DARK, GREY = "#0693e3", "#32373c", "#8a9199"
LINE_COLORS = ["#0693e3", "#f59e0b", "#10b981", "#8b5cf6", "#ef4444", "#14b8a6", "#64748b"]

pass  # portal-sync: st.set_page_config removed (Home.py makes the one call allowed per run)

# ---------------------------------------------------------------------------
# Catalog: UI commodity -> NASS commodity_desc, class filter, stage order
# ---------------------------------------------------------------------------
COMMODITIES = {
    "Corn": dict(desc="CORN", cls=None,
                 stages=["PLANTED", "EMERGED", "SILKING", "DOUGH", "DENTED", "MATURE", "HARVESTED"]),
    "Soybeans": dict(desc="SOYBEANS", cls=None,
                     stages=["PLANTED", "EMERGED", "BLOOMING", "SETTING PODS",
                             "DROPPING LEAVES", "HARVESTED"]),
    "Winter wheat": dict(desc="WHEAT", cls="WINTER",
                         stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"], fall=("PLANTED", "EMERGED")),
    "Spring wheat": dict(desc="WHEAT", cls="SPRING, (EXCL",
                         stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"]),
    "Sorghum": dict(desc="SORGHUM", cls=None,
                    stages=["PLANTED", "HEADED", "COLORING", "MATURE", "HARVESTED"]),
    "Oats": dict(desc="OATS", cls=None, stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"]),
    "Barley": dict(desc="BARLEY", cls=None, stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"]),
    "Rice": dict(desc="RICE", cls=None, stages=["PLANTED", "EMERGED", "HEADED", "HARVESTED"]),
    "Cotton": dict(desc="COTTON", cls="UPLAND",
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


def select(df: pd.DataFrame, meta: dict, stage: str) -> pd.DataFrame:
    """One commodity/class/stage with a crop-year column (fall-planted winter wheat -> next year)."""
    d = df[df["stage"] == stage]
    if meta["cls"]:
        d = d[d["class_desc"].str.startswith(meta["cls"], na=False)] if meta["cls"] != "WINTER" \
            else d[d["class_desc"] == "WINTER"]
    d = d.copy()
    d["crop_year"] = d["year"] + (1 if stage in meta.get("fall", ()) else 0)
    return d


def weekly_matrix(d: pd.DataFrame) -> pd.DataFrame:
    """(state, crop_year) x week, interpolated between reports and carried forward after the last."""
    p = d.pivot_table(index=["state", "crop_year"], columns="week", values="value", aggfunc="last")
    p = p.reindex(columns=range(1, 54))
    p = p.interpolate(axis=1, limit_area="inside")
    return p.ffill(axis=1)


def five_year_avg(p: pd.DataFrame, year: int, week: int) -> pd.Series:
    prior = p[p.index.get_level_values("crop_year").isin(range(year - 5, year))][week].dropna()
    g = prior.groupby(level="state")
    return g.mean().where(g.count() >= 3)


def comparison_table(p: pd.DataFrame, year: int, week: int) -> pd.DataFrame:
    def col(y, w):
        try:
            return p.xs(y, level="crop_year")[w]
        except KeyError:
            return pd.Series(dtype=float)
    out = pd.DataFrame({"TW": col(year, week), "LW": col(year, week - 1),
                        "LY": col(year - 1, week), "5YA": five_year_avg(p, year, week)})
    out = out.dropna(subset=["TW"])
    out["ΔLW"], out["ΔLY"], out["Δ5YA"] = out.TW - out.LW, out.TW - out.LY, out.TW - out["5YA"]
    return out


# ---------------------------------------------------------------------------
# Header + selectors
# ---------------------------------------------------------------------------
logo = HERE / "JSA Logo.png"
c_logo, c_title = st.columns([1, 6], vertical_alignment="center")
if logo.exists():
    c_logo.image(str(logo), width=150)
c_title.title("Crop Progress Dashboard")

commodity = st.session_state.get("commodity", "Corn")
left, right = st.columns([1, 4], gap="large")

with left:
    commodity = st.selectbox("Commodity", list(COMMODITIES), key="commodity")
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
    newest = max(reversed(stages), key=lambda x: select(raw, meta, x)["week_ending"].max())
    stage = st.selectbox("Crop stage", stages, index=stages.index(newest),
                         format_func=str.title, key=f"stage_{commodity}")
    d = select(raw, meta, stage)
    P = weekly_matrix(d)

    years = sorted(d["crop_year"].unique(), reverse=True)
    map_year = st.selectbox("Marketing year for map", years, format_func=year_label,
                            key=f"myear_{commodity}_{stage}")
    wk_opts = sorted(d.loc[d["crop_year"] == map_year, "week"].unique())
    # Week labels: the week-ending date from the US row when we have it
    we = d[(d["crop_year"] == map_year)].groupby("week")["week_ending"].max()
    week = st.selectbox("Calendar week", wk_opts, index=len(wk_opts) - 1,
                        format_func=lambda w: f"Week #{w}" + (
                            f" (w/e {we[w]:%b %d})" if w in we.index and pd.notna(we[w]) else ""),
                        key=f"week_{commodity}_{stage}_{map_year}")
    metric = st.selectbox("Map selection", ["TW (this week)", "LW (last week)", "LY (last year)",
                                            "5YA (5-year avg)", "ΔLW", "ΔLY", "Δ5YA"],
                          key="map_metric")
    chart_years = st.multiselect("Marketing year(s) for line chart", years,
                                 default=years[:2], format_func=year_label,
                                 key=f"cyears_{commodity}_{stage}")
    state_opts = ["US"] + sorted(s for s in d["state"].unique() if s != "US")
    chart_state = st.selectbox("State for line chart", state_opts,
                               format_func=lambda s: "US total" if s == "US" else STATES.get(s, s),
                               key=f"cstate_{commodity}_{stage}")
    show_5ya = st.toggle("Show 5-year average", value=True)

table = comparison_table(P, map_year, week)

with right:
    latest = d["week_ending"].max()
    st.caption(f"Updated {latest:%B %d, %Y}  ·  USDA NASS Crop Progress, "
               f"{commodity.lower()} {stage.lower()} (% of acreage)")

    # KPI cards for the US row
    if "US" in table.index:
        u = table.loc["US"]
        k = st.columns(4)

        def delta(v):
            return None if pd.isna(v) else f"{v:+.0f} pts"
        k[0].metric(f"{commodity} {stage.lower()} — week #{week}", f"{u.TW:.0f}%", delta(u.ΔLW))
        k[1].metric("vs last year", "—" if pd.isna(u.LY) else f"{u.LY:.0f}%", delta(u.ΔLY),
                    help="Last year's value for the same calendar week; delta is this week minus it.")
        k[2].metric("vs 5-year avg", "—" if pd.isna(u["5YA"]) else f"{u['5YA']:.0f}%",
                    delta(u.Δ5YA))
        k[3].metric("Last week", "—" if pd.isna(u.LW) else f"{u.LW:.0f}%")
    else:
        st.info("No US total reported for this week.")

    mcol, tcol = st.columns([5, 4], gap="medium")

    # ---- map ----
    key = metric.split(" ")[0]
    is_delta = key.startswith("Δ")
    st_rows = table.drop(index="US", errors="ignore")
    with mcol, st.container(border=True):
        fig = go.Figure(go.Choropleth(
            locations=st_rows.index, z=st_rows[key], locationmode="USA-states",
            text=[STATES.get(s, s) for s in st_rows.index],
            colorscale=[[0, "#ef4444"], [0.5, "#f5f5f5"], [1, BLUE]] if is_delta
            else [[0, "#eef6fd"], [1, BLUE]],
            zmid=0 if is_delta else None,
            zmin=None if is_delta else 0, zmax=None if is_delta else 100,
            marker_line_color="white", colorbar=dict(title="pts" if is_delta else "%", thickness=12),
            hovertemplate="%{text}: %{z:.0f}<extra></extra>"))
        fig.update_geos(scope="usa", showlakes=False, bgcolor="rgba(0,0,0,0)")
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=28, b=0),
                          title=dict(text=f"{commodity} {stage.lower()} — {metric}, week #{week}",
                                     font=dict(size=14)))
        st.plotly_chart(fig, width="stretch")

    # ---- table ----
    with tcol:
        disp = table.copy()
        disp.index = ["US TOTAL" if s == "US" else s for s in disp.index]
        disp = disp.sort_index(key=lambda ix: ix.map(lambda s: (s != "US TOTAL", s)))
        disp.index.name = "STATE"
        def _blend(v, vmin, vmax, lo, hi):
            if pd.isna(v):
                return ""
            t = min(max((v - vmin) / (vmax - vmin), 0), 1)
            r, g, b = (int(lo[i] + (hi[i] - lo[i]) * t) for i in range(3))
            return f"background-color: rgb({r},{g},{b}); color: {DARK}"

        def _delta_css(v):  # red (behind) -> white -> blue (ahead)
            if pd.isna(v):
                return ""
            return (_blend(v, -30, 0, (239, 120, 120), (255, 255, 255)) if v < 0
                    else _blend(v, 0, 30, (255, 255, 255), (110, 180, 235)))

        styled = (disp.style.format("{:.0f}", na_rep="–")
                  .format("{:+.0f}", subset=["ΔLW", "ΔLY", "Δ5YA"], na_rep="–")
                  .map(_delta_css, subset=["ΔLW", "ΔLY", "Δ5YA"])
                  .map(lambda v: _blend(v, 0, 100, (255, 255, 255), (190, 224, 247)),
                       subset=["TW", "LW", "LY", "5YA"]))
        st.dataframe(styled, height=420, width="stretch")

# ---------------------------------------------------------------------------
# Seasonal line chart
# ---------------------------------------------------------------------------
st.subheader(f"{commodity} {stage.lower()} seasonal chart — {'US total' if chart_state == 'US' else STATES.get(chart_state, chart_state)}")
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
    pm = P.xs(chart_state, level="state") if chart_state in P.index.get_level_values("state") else None
    if pm is not None:
        prior = pm[pm.index.isin(range(ref - 5, ref))]
        avg = prior.mean().where(prior.count() >= 3).dropna()
        avg = avg[(avg.index >= sub["week"].min()) & (avg.index <= sub["week"].max())]
        fig.add_trace(go.Scatter(x=avg.index, y=avg.values, mode="lines", name="5-year average",
                                 line=dict(color=GREY, width=2, dash="dash"),
                                 hovertemplate="Week %{x}: %{y:.0f}%<extra>5-yr avg</extra>"))
fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), template="plotly_white",
                  xaxis_title="Calendar week", yaxis_title="Percent complete",
                  yaxis=dict(range=[0, 100]), legend=dict(orientation="h", y=1.1),
                  hovermode="x unified")
with st.container(border=True):
    st.plotly_chart(fig, width="stretch")

st.caption("Source: USDA NASS Crop Progress (weekly, Mondays 4 pm ET) via the JSA NASS cache. "
           "LY and 5YA compare the same calendar week; the 5-year average needs at least 3 prior "
           f"years. Cache last refreshed: {cache_freshness() or 'unknown'}.")
