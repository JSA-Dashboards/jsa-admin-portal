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
# `portal_view` is SHARED and lives at the repo root, the convention `wasde`
# already uses. It decides whether this run is the client deployment, and it is
# NOT named `view` because several pages bind that as a local -- see
# portal_view.py.
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).parent))

import portal_view  # noqa: E402
import cof_recap  # noqa: E402
import cold_storage  # noqa: E402
import placement_records  # noqa: E402
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
def fetch_beef_cows(schema: int) -> pd.Series:
    """Jan-1 beef cow inventory, year-indexed, SURVEY only.

    SURVEY ONLY IS LOAD-BEARING. This series also carries CENSUS rows, and the
    Census of Agriculture years 1997, 2002 and 2017 come back at 1.4M, 1.2M and
    4.0M head against a true ~30M -- a collapse and recovery that never
    happened, on a series used as a denominator.

    The params are us_cow_herd/inventory.py's BEEF_COWS verbatim, which omits
    the four keys every other fetch on this page sends. The cache key is a hash
    of the exact dict, so "tidying" it to match returns nothing at all.
    """
    try:
        payload = fetch_cached({"agg_level_desc": "NATIONAL",
                                "short_desc": "CATTLE, COWS, BEEF - INVENTORY"})
    except Exception:
        return pd.Series(dtype="float64")
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not rows:
        return pd.Series(dtype="float64")
    df = pd.DataFrame(rows)
    if "source_desc" in df:
        df = df[df["source_desc"] == "SURVEY"]
    df = df[df["reference_period_desc"] == "FIRST OF JAN"]
    df["Value"] = pd.to_numeric(df["Value"].astype(str).str.replace(",", "", regex=False),
                                errors="coerce")
    df = df.dropna(subset=["Value"])
    df["year"] = df["year"].astype(int)
    return df.groupby("year")["Value"].max()


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


# The released report text, by full state name as USDA prints it.
_STATE_BY_NAME = {v.lower(): k for k, v in STATE_NAMES.items()}


def overlay_released(df: pd.DataFrame, series: str, rows: list) -> pd.DataFrame:
    """`df` with USDA's just-released figures written over it.

    WHY THE PAGE NEEDS THIS AT ALL. Everything here reads QuickStats through a
    cache a scheduled job fills, so on release day it sat on last month while
    the COF Recap tab — which parses USDA's released text directly — already had
    the new one. Two halves of one page a month apart. This closes that: the
    history still comes from the cache, and the one or two months the release
    covers are written over the top of it.

    **THE RELEASE WINS WHERE THE TWO OVERLAP, and that is not arbitrary.**
    Checked against the cache on 2026-10-23: of 104 observations both sources
    held, 98 agreed exactly and 6 differed — South Dakota and the US total, in
    all three monthly series, for the PRIOR month. They are USDA's restatement,
    which every release makes, and the US delta equalled South Dakota's to the
    head in each one (+5,000 / +3,000 / -2,000). So the disagreements were the
    release being newer, not this being wrong. The same rule the feeder index
    runs on: the published value wins for any period it covers.

    **IT IS APPLIED OUTSIDE load_all's CACHE ON PURPOSE.** load_all holds for an
    hour because it is a Snowflake read over full series; this is a dict merge
    over ~150 rows. Keeping it out here lets the new month appear on the release
    text's own five-minute clock without making the history refetch hourly.
    """
    if df.empty or not rows:
        return df
    recs = []
    for r in rows:
        if r["series"] != series:
            continue
        st = _STATE_BY_NAME.get(r["state_name"].lower())
        if not st:
            continue
        recs.append({"year": r["year"], "month": r["month"],
                     "date": pd.Timestamp(year=r["year"], month=r["month"], day=1),
                     "agg_level_desc": "NATIONAL" if st == "US" else "STATE",
                     "state_alpha": st, "Value": float(r["value"])})
    if not recs:
        return df
    add = pd.DataFrame(recs)
    # Replace, never append: the prior month is usually already in the cache and
    # concatenating would leave TWO rows for it, which every downstream .max()
    # and groupby would silently pick between.
    marked = df.merge(add[["state_alpha", "year", "month"]].assign(_new=1),
                      on=["state_alpha", "year", "month"], how="left")
    kept = df[marked["_new"].isna().values]
    return (pd.concat([kept, add], ignore_index=True)
              .sort_values("date").reset_index(drop=True))


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


def with_year_ago_pct(sub: pd.DataFrame, history: pd.DataFrame = None) -> pd.DataFrame:
    """`sub` plus a `pct_year_ago` column — USDA's percent of previous year, so
    100 is unchanged and 97.0 is three percent below.

    `history` is the longer run of the same series to reach back INTO, and the
    Data tab passes it for a rendering reason rather than an arithmetic one.
    The tables show the nine years `LOAD_YEARS` covers, so the oldest of them
    has no year-ago row inside its own frame — and `st.column_config.NumberColumn`
    has no blank: a missing number prints a greyed **"None"**, which reads as a
    fault rather than as "USDA published nothing to compare against". Measured
    on Streamlit 1.63, and it is not a dtype matter: float64 NaN, nullable
    Float64 pd.NA and an object None all render the same. Reaching into the
    full record the page already holds for the seasonality charts means those
    rows carry a real figure, and what "None" is left genuinely has none.

    THE ARITHMETIC IS `cof_recap.pct`, DELIBERATELY. The COF Recap tab on this
    same page already prints this figure for the latest month off USDA's
    released report text; a second copy of `round(curr / prev * 100, 1)` here is
    how the two tabs come to quote one number two ways and disagree in the last
    decimal. Note the convention differs from the Summary tiles on purpose —
    those show a percent CHANGE, this reproduces the column USDA's own report
    prints beside On Feed, Placed and Marketed, which is what the raw-series
    tables are for. That is also why the column header spells out "% of year
    ago" rather than carrying a sign.

    The year-ago row is matched on (year - 1, month), never a 12-row shift.
    They agree on every row of every state today — checked across all three
    series over the loaded window, zero divergence — so this is not fixing a
    live defect. It is the form that stays right if a month ever goes missing,
    which these state series do without warning: Minnesota's placements run to
    November 2024 and then stop for good. A shift bridges a hole silently and
    prices a month against whatever row happens to sit twelve places back.

    A row with no year-ago match gets None, which renders blank. The earliest
    loaded year has no prior year to reach, by construction.
    """
    out = sub.copy()
    src = sub if history is None else history
    prior = {(int(r.year) + 1, int(r.month)): float(r.Value) for r in src.itertuples()}
    vals = [
        cof_recap.pct(float(v), prior.get((int(y), int(m))))
        for y, m, v in zip(out["year"], out["month"], out["Value"])
    ]
    # float64, not object: a state whose every row is unmatched would otherwise
    # give an all-None column, and NumberColumn's "%.1f%%" cannot format that.
    out["pct_year_ago"] = pd.Series(vals, index=out.index, dtype="float64")
    return out


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

    # Cold Storage keeps Overview and Full History -- the second is the whole
    # reason this view reads QuickStats rather than the monthly PDF, since it
    # goes back to 1917 and a one-month release cannot. Seasonality and Data go
    # for the same reasons they go upstairs.
    tab_over, tab_hist, tab_season, tab_data = portal_view.tabs([
        "⭐  Overview", "📈  Full History", "📅  Seasonality", "📋  Data",
    ], hide={"📅  Seasonality", "📋  Data"}, on_change="rerun")

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
# The state picker chooses a reading and stays; the trend window is tuning and
# goes, at the 5 years the staff page opens on. See the same line drawn on
# Cattle Weights' sidebar.
trend_years = portal_view.pick(5, lambda: st.sidebar.slider("Trend window (years)", 2, 8, 5))

st.sidebar.divider()

# CLEARING load_all ALONE DOES NOTHING. It is cached, but its body calls
# fetch_series, which is cached too -- so clearing only the outer one re-runs it
# straight back into the inner cache and returns the same frames. Both, or
# neither. The button would otherwise look like it worked.
#
# Staff only, like the trend slider: a client has no use for a cache control.
if portal_view.pick(False, lambda: st.sidebar.button(
        "Check for new data", width="stretch",
        help="Clears the cached NASS pull and refetches. These tabs read the "
             "shared cache a scheduled job fills, so new USDA data appears here "
             "only once that job has run.")):
    fetch_series.clear()
    load_all.clear()
    st.rerun()

# BOOKED HERE, FILLED AFTER THE LOAD. The freshness line needs `inv`, which is
# fetched ~190 lines below this -- script order, not layout order, the rule the
# crush pages already run on. Without the slot it lands at the bottom of the
# sidebar under the publication note, away from the button it belongs to.
_freshness_slot = st.sidebar.empty()

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

# SEVEN TABS IS THE DENSEST PAGE ON THE PORTAL AND A CLIENT GETS THREE.
# Summary, On-Feed & Flows and Heifers on Feed each answer a market question
# off the report USDA just published. Seasonality overlays eight years to show
# the shape of a normal calendar, State Comparison is a fourteen-state ranking
# nobody trades off, and Data is the raw frame -- research, not a reading.
#
# COF RECAP GOES FOR A DIFFERENT REASON, and the docstring below still calls it
# "the client one-pager", which is true of the ARTEFACT and not of this tab.
# Ross builds the recap here and sends it out himself (2026-10-23: "the clients
# don't need to see the COF Recap page that I use to edit and send to
# clients"). What a client receives is the finished one-pager in their inbox;
# the live tab is the workbench it was made on, and showing both invites the
# question of why they disagree -- which they will, since this tab re-reads
# USDA's file every hour and the thing they were sent did not.
#
# Hiding it also skips `_latest_recap()`, which fetches and parses USDA's
# released report text -- the body is behind `if tab_recap.open:`, so a client
# costs that fetch nothing.
tab_summary, tab_recap, tab_flows, tab_weights, tab_prec, tab_season, tab_heifer, tab_state, tab_data = portal_view.tabs([
    "⭐  Summary", "📄  COF Recap", "📊  On-Feed & Flows", "⚖️  Placements by Weight", "📉  Placement Records", "📅  Seasonality", "🐄  Heifers on Feed", "🗺️  State Comparison", "📋  Data",
], hide={"📄  COF Recap", "📅  Seasonality", "🗺️  State Comparison", "📋  Data"},
    on_change="rerun")

# ── COF Recap ─────────────────────────────────────────────────────────────────
# The client one-pager, drawn BEFORE the QuickStats load on purpose: it reads
# USDA's released report text over plain HTTP and needs neither that API nor a
# key, so an outage there must not take it down. Tab display order is set by
# st.tabs, not by where these blocks sit, so it still shows up second.
# Deliberately NOT built off the QuickStats frames the
# rest of this page uses: it reads USDA's released report text so the state
# percentages are USDA's own rounded figures rather than ours, and so the
# weight-class breakdown (absent from the series above) comes along with them.


# FIVE MINUTES, NOT AN HOUR. This is the one page whose whole job is to show a
# USDA report the moment it lands, and on 2026-10-23 it sat on the September
# recap while October was live on nass.usda.gov -- a cache entry created before
# the 2pm CT release, held for the full hour. The fetch is two small text GETs
# behind `if tab_recap.open:`, so the hour was buying almost nothing and cost
# exactly the morning it mattered. The button below clears it outright.
@st.cache_data(ttl=300, show_spinner=False)
def _latest_recap():
    """(recap dict, overlay rows, error string) from ONE fetch of the release.

    The recap and the overlay must describe the SAME report, so they are built
    together rather than from two cached fetches. Two entries expiring
    independently is how the Recap tab and the Summary tiles come to show
    different months — which is the exact complaint this whole change answers,
    reintroduced one level down.
    """
    year, month, text = cof_recap.latest_report()
    if not text:
        return None, [], "Could not reach the USDA report file at nass.usda.gov."
    prior = cof_recap.fetch_report(year - 1, month)
    return (cof_recap.build_recap(year, month, text, prior),
            cof_recap.released_rows(text, year, month), "")


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
        recap, _release_rows, err = _latest_recap()
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
                if st.button("Prepare client page", width="stretch",
                             help="Renders the page above as one image and as a PDF."):
                    st.session_state["recap_export_ready"] = True
                if st.session_state.get("recap_export_ready"):
                    fig_json = fig.to_json()
                    with st.spinner("Rendering…"):
                        png, pdf = _recap_image(fig_json, "png"), _recap_image(fig_json, "pdf")
                    # Named for the job, in the daily letter's own words: HubSpot's
                    # editor takes ONE asset, so "one image" is the thing to promise.
                    # Unlike the letter there is no paged/texting twin to confuse it
                    # with -- the figure is a single page by construction, so there
                    # is nothing here to split and no capture height to get wrong.
                    if png:
                        st.download_button("Save one image (HubSpot)", png,
                                           file_name=f"{stem}.png", mime="image/png",
                                           width="stretch")
                    if pdf:
                        st.download_button("Download PDF (print)", pdf,
                                           file_name=f"{stem}.pdf",
                                           mime="application/pdf", width="stretch")
                    if png or pdf:
                        st.caption("The image is the whole page — letterhead, watermark "
                                   "and frame — ready to drop into a HubSpot email.")
                    if not png and not pdf:
                        st.warning("Image export failed on the host. The table above still "
                                   "renders — use the camera icon on its toolbar.")
                st.caption(f"Source: {cof_recap.report_url(recap['year'], recap['month'])}")
                # RELEASE DAY NEEDS A WAY THROUGH THE CACHE. _latest_recap is cached
                # so the tab does not refetch per rerun, and on release afternoon that
                # is exactly the wrong behaviour: the entry predates the 2pm CT post
                # and the page shows last month until it expires. Shortening the TTL
                # narrows the window; this closes it.
                if st.button("Check for a new release", width="stretch",
                             help="Clears the cached recap and refetches from USDA."):
                    _latest_recap.clear()
                    st.rerun()


# ── Placements by weight ─────────────────────────────────────────────────────
# Asked for 2026-10-23: the weight classes placed, the head in each, and when
# those cattle come to market.
#
# EVERY FIGURE HERE ALREADY EXISTED. build_recap returns `weight_classes` as
# (label, head, window) and `placed_total`, and until now both went only into
# the PNG one-pager Ross emails. This RENDERS that object; it does not
# recompute any of it, so the tab and the sheet cannot drift -- the failure
# this file records five times over.
#
# ABOVE THE QUICKSTATS GUARD, like COF Recap and for the same reason: it reads
# USDA's released report text over plain HTTP and needs neither that API nor a
# key, so an outage there must not take it down.
#
# BOTH VIEWS, unlike COF Recap directly above. The one-pager is Ross's to
# author and send; which weights went on feed and when they market is a market
# reading, and clients get it. It costs them nothing extra -- same cached
# _latest_recap() the Recap tab uses, so on the client app, where that tab is
# hidden, this is the only thing that calls it.
with tab_weights:
    if tab_weights.open:
        _wr, _, _werr = _latest_recap()
        if _werr:
            st.error(_werr)
        elif not _wr or not _wr.get("weight_classes"):
            st.info("USDA's latest release carries no weight-class breakdown.")
        else:
            _wc = _wr["weight_classes"]
            _wsum = sum(h for _lbl, h, _win in _wc if h)
            _wtot = _wr.get("placed_total")

            st.markdown(
                f'<div class="sec-hdr">Placed on feed by weight &mdash; '
                f'{_wr["placement_month"]}</div>', unsafe_allow_html=True)

            _wrows = []
            for _lbl, _head, _win in _wc:
                _h = f"{_head:,}" if _head else "&mdash;"
                _s = f"{_head / _wsum * 100:.1f}%" if _head and _wsum else "&mdash;"
                _wrows.append(f"<tr><td>{_lbl}</td><td>{_h}</td>"
                              f"<td>{_s}</td><td>{_win}</td></tr>")
            _wrows.append(
                f'<tr style="font-weight:700"><td>All weights</td>'
                f'<td>{_wsum:,}</td><td>100.0%</td><td>&mdash;</td></tr>')

            # st.html, not st.markdown: the six-state table on the index page
            # shipped as an unstyled grid because a literal tag inside a style
            # comment ended the style element, and markdown has eaten tables on
            # this portal before. st.html does not run the markdown parser.
            st.html(
                '<table class="sum-table">'
                '<thead><tr>'
                '<th>Weight placed</th>'
                '<th>Head placed</th>'
                '<th>Share of placements</th>'
                '<th>Expected marketing window</th>'
                '</tr></thead><tbody>' + "".join(_wrows) + '</tbody></table>'
            )

            # A FREE AUDIT, checked live rather than asserted. USDA publishes
            # the six classes and the placement total independently, so they
            # must agree -- they do, exactly, on the September 2026 report
            # (1,777,000 both ways). A shifted or missed class is the failure
            # that does not look wrong on a table of plausible head counts.
            if _wtot and _wsum == _wtot:
                st.caption(
                    f"The six classes sum to **{_wsum:,} head** — exactly the placement "
                    f"total USDA publishes in the same report, which is the check that "
                    f"no class has been missed or misread.")
            elif _wtot:
                st.warning(
                    f"These classes sum to {_wsum:,} head against USDA's published "
                    f"placement total of {_wtot:,} — a difference of "
                    f"{_wsum - _wtot:+,}. One of the two is being read wrongly; "
                    f"treat the breakdown as unreliable until that is resolved.")

            # THE WINDOW IS JSA'S, NOT USDA'S, and saying so is not optional.
            # USDA publishes the head in each class and nothing about when
            # those cattle market; the months are a fixed per-class offset in
            # cof_recap.WEIGHT_CLASSES, derived from one example sheet. A
            # reader who takes it for a USDA forecast has been misled by us.
            st.caption(
                "**USDA publishes the head; the marketing window is JSA's.** It is a "
                "fixed offset from the placement month — ten to eleven months out for "
                "cattle under 600 lb, down to four to five months for 1,000 lb and "
                "over — so read it as a planning guide rather than a USDA forecast. "
                "Placements are for the month USDA reports, which is the month before "
                "the report's own title.")


# ── Load data ────────────────────────────────────────────────────────────────

# Spinner goes in the reserved header slot, not here: this block now runs after
# the tab bar has been drawn, so an un-slotted spinner would appear underneath
# the tab content instead of at the top of the page where the header is landing.
with header_slot:
    with st.spinner("Loading USDA NASS data…"):
        inv, place, sales, other, heifer, steer, inv_full, place_full, sales_full = load_all(LOAD_YEARS, Q_YEARS)

    # USDA's released text written over the cached history -- see
    # overlay_released. Outside load_all's hour-long cache on purpose, and
    # wrapped because letterhead-grade presentation must never cost the
    # numbers: if the release is unreachable the page is exactly what it was.
    try:
        _rows = _latest_recap()[1]
    except Exception:
        _rows = []
    if _rows:
        inv        = overlay_released(inv,        "inventory",  _rows)
        place      = overlay_released(place,      "placements", _rows)
        sales      = overlay_released(sales,      "marketings", _rows)
        other      = overlay_released(other,      "other",      _rows)
        inv_full   = overlay_released(inv_full,   "inventory",  _rows)
        place_full = overlay_released(place_full, "placements", _rows)
        sales_full = overlay_released(sales_full, "marketings", _rows)
        # The quarterly class split, carried only by the Jan/Apr/Jul/Oct
        # reports. heifer_pct_frame divides these by inv_full, which is
        # overlaid above, so all three sides of that ratio come from the same
        # release rather than two of them moving and one lagging a quarter.
        heifer     = overlay_released(heifer,     "heifers",    _rows)
        steer      = overlay_released(steer,      "steers",     _rows)

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

# WHAT MONTH IS ACTUALLY ON THE PAGE, in the slot booked beside the button.
# These tabs and the COF Recap run on different clocks -- the Recap reads USDA's
# released text the moment it posts, while everything else waits on QuickStats
# and then on the scheduled job that fills the cache. On release day that gap is
# a day or more, and nothing on the page said so: it simply looked like the
# dashboard had not noticed. On-feed and the two flow series are named
# separately because they are a month apart by USDA's own design -- the report
# carrying the Oct 1 inventory carries SEPTEMBER placements and marketings.
_inv_latest = inv[inv["state_alpha"] == "US"]["date"].max() if not inv.empty else None
_flow_latest = place[place["state_alpha"] == "US"]["date"].max() if not place.empty else None
if _inv_latest is not None and pd.notna(_inv_latest):
    _bits = [f"on-feed to <b>{_inv_latest:%b %Y}</b>"]
    if _flow_latest is not None and pd.notna(_flow_latest):
        _bits.append(f"flows to <b>{_flow_latest:%b %Y}</b>")
    _freshness_slot.markdown(
        f'<div style="color:{DM_MUTED};font-size:.68rem;line-height:1.5">'
        f'Cached NASS data: {" · ".join(_bits)}.</div>',
        unsafe_allow_html=True,
    )

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
# ── Placement Records ────────────────────────────────────────────────────────
# Asked for by Ross, 2026-10-27, after he noticed placements had been the lowest
# on record for their calendar month three reports running.
#
# IT REPORTS WHAT MOVED AND REFUSES TO SAY WHY. Whether a run of record lows is
# heifer retention or simply a smaller herd is the question it exists to let a
# reader judge, and this page has a standing rule against a caption that
# supplies a plausible wrong cause. The three framings are shown together
# because they disagree.

def _prec_spread_line(rows: list, heifer: dict) -> str:
    """The contrast between the heifer shares in a ranking, in words.

    BOTH ENDS ARE READ AT RENDER TIME. Ross asked for the 4th-against-54th
    contrast to be called out, and writing those two numbers into the sentence
    is how a caption comes to disagree with the table printed directly above
    it -- the mistake recorded for the southeast retention panel, where "the
    trough of the whole record" was true of one panel and false of the next.
    Nothing here names a year or a percentile.

    It states WHAT the two ends are. It does not say why they differ.
    """
    sp = placement_records.heifer_spread(rows, heifer)
    if not sp or not sp.get("material"):
        return ""
    lo, hi = sp["low"], sp["high"]
    return (f" Across these ten the heifer share runs from the "
            f"**{lo['percentile']:.0f}th percentile ({lo['year']}, "
            f"{lo['pct']:.1f}%)** to the **{hi['percentile']:.0f}th "
            f"({hi['year']}, {hi['pct']:.1f}%)** — a comparable placement "
            f"level reached with very different shares of heifers on feed.")


def _prec_stretch(n: int) -> str:
    """"1 stretch" / "3 separate stretches" -- the on-feed any-window ranking
    really does come from a single stretch, so the plural cannot be assumed."""
    return "1 stretch" if n == 1 else f"{n} separate stretches"


def prec_basis_chart(values: dict, heifer: dict, y_title: str, hover: str,
                     height: int = 400) -> go.Figure:
    """Placements by year on either basis, with the heifer share beside it.

    TWO AXES, AND THE CAPTION CARRIES THE MEASURED r FOR THAT REASON. Two
    series on independently scaled axes will look related whatever they do,
    which is the classic way to manufacture a correlation in a picture. The
    number under the chart is what disciplines it: these two move together at
    about +0.35, which is weak, and the page says so rather than leaving the
    impression to the drawing.
    """
    if not values:
        return go.Figure()
    years = sorted(values)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=years, y=[values[y] for y in years], marker_color=HEIFER_COLOR,
        name=y_title,
        hovertemplate="%{x}: " + hover + "<extra></extra>"))
    hy = [y for y in years if y in heifer]
    if hy:
        fig.add_trace(go.Scatter(
            x=hy, y=[heifer[y]["pct"] for y in hy], yaxis="y2",
            mode="lines+markers", name="Heifers on feed",
            line=dict(color=COL_NEG, width=2), marker=dict(size=5),
            customdata=[[heifer[y]["percentile"]] for y in hy],
            hovertemplate="%{x}: %{y:.1f}% heifers on feed · "
                          "%{customdata[0]:.0f}th percentile<extra></extra>"))
    _apply(fig, height=height, y_title=y_title)
    fig.update_layout(
        yaxis2=dict(title="Heifers, % of cattle on feed", overlaying="y",
                    side="right", showgrid=False, ticksuffix="%"),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=55, r=70, t=50, b=40))
    fig.update_xaxes(dtick=2)
    return fig


def _prec_times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def _prec_standing(st: dict, first: int) -> str:
    """Where the run in progress sits against every earlier run, in words.

    EVERY BRANCH NAMES THE SPAN. "the longest on record" ranks a figure
    against a period it does not state, which is the defect Ross reported on
    the other three tiles -- so this helper interpolates `first` on every
    path, and a test fails any branch that returns a bare string.
    """
    longest, ties = st.get("longest", 0), st.get("ties", 0)
    if not st.get("current"):
        return f"the longest since {first} is {longest} months"
    if not st.get("is_longest"):
        return f"short of the longest since {first}, {longest} months"
    if not ties:
        return f"the longest since {first}"
    return f"the longest since {first}, matched {_prec_times(ties)} before"


def _prec_ord(n: int) -> str:
    """1 -> 'the lowest', 2 -> '2nd lowest', 122 -> '122nd lowest'.

    A bare "122 lowest of 358 windows" is not a sentence, and rank 1 reads
    worst of all -- "1 lowest", when the point is that nothing is below it.
    The standing rule on this page is that a figure reads on its own.
    """
    if n == 1:
        return "the lowest"
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} lowest"


with tab_prec:
    if tab_prec.open:
        _pc_cows = fetch_beef_cows(placement_records.SCHEMA)
        _pc_share = placement_records.heifer_share(
            series_for(heifer, "US")[["year", "month", "Value"]],
            series_for(steer, "US")[["year", "month", "Value"]])
        _pc = placement_records.compare(
            series_for(place_full, "US")[["year", "month", "Value"]],
            _pc_cows, _pc_share,
            inventory=series_for(inv_full, "US")[["year", "month", "Value"]])

        st.markdown('<div class="sec-hdr">Placement records — United States</div>',
                    unsafe_allow_html=True)

        _r12, _roll, _percow = _pc["last12"], _pc["rolling"], _pc["per_cow"]
        # HOISTED ABOVE BOTH TABLES AND THE CHART. Streamlit runs this top to
        # bottom, so a name used by the placements table cannot be bound down
        # in the chart section -- that is a NameError on the live page which
        # every source-text test passes, the trap this page has hit twice.
        _heif = _pc.get("heifer_by_year", {})
        _newest = _pc["flagged"].iloc[-1]
        # ONE GRID, NOT FOUR STREAMLIT COLUMNS. The four feet wrap to
        # different line counts and left the row ragged at 192/206/233/233px --
        # invisible to get_page_text and to the suite, exactly as the daily
        # cash tile row was.
        #
        # Streamlit columns cannot fix it from the outside: five wrappers sit
        # between the column and the card, and `height: 100%` on the column is
        # WORSE THAN NOTHING -- an explicit height defeats the flex row's own
        # `align-items: stretch`, and then resolves against an auto-height
        # parent, so the column ends up SHORTER than the row. Measured.
        #
        # Grid items stretch to their row by default, so equal height is the
        # behaviour rather than something layered on top, and it holds at any
        # width and through a Streamlit upgrade. st.html also skips the
        # markdown parser, which is what renders a pair of dollar signs as
        # LaTeX elsewhere on this portal.
        _run = _pc["current_run"]
        # EVERY RANKING NAMES ITS OWN PERIOD. Ross, 2026-10-27, on the shipped
        # version: *"does 'a series high' mean the most since the cattle on
        # feed series began in 1996?"* It did, and three of the four tiles
        # ranked against a span they never named -- "a series high", "most on
        # file", "of 358 windows". The standing rule on this portal is that a
        # tile is read on its own and screenshotted away from its caption, so
        # the span cannot live in the paragraph underneath.
        _first = int(_pc["first_year"])
        _cards = [
            _snap_card(
                "Record-Low Months in a Row", f"{_run}",
                "months" if _run != 1 else "month",
                '<span class="snap-neu">lowest for that calendar month</span>',
                f'<span class="snap-neu">'
                f'{_prec_standing(_pc["standing"], _first)}</span>',
                mom_lbl="BASIS", yoy_lbl="WHERE THIS SITS", accent="#c98a56",
                foot=(f'must beat {_pc["min_prior"]}+ earlier years · newest '
                      f'month on file: {MONTH_ABBR[int(_newest.month)]} '
                      f'{int(_newest.year)}'),
            ),
            _snap_card(
                "Record-Low Months, Last 12 Reports", f'{_r12.get("now", 0)}', "of 12",
                f'<span class="snap-neu">{_r12.get("best", 0)} in any 12 '
                f'months</span>',
                '<span class="snap-neu">'
                + (f"a series high — the most since {_first}"
                   if _r12.get("is_best")
                   else f'below the series high of {_r12.get("best", 0)}')
                + "</span>",
                mom_lbl="SERIES BEST", yoy_lbl="WHERE THIS SITS", accent="#c98a56",
                foot=", ".join(f"{MONTH_ABBR[m]} {y}"
                               for y, m in _r12.get("months", [])[-6:]),
            ),
            _snap_card(
                "Placements, Last 12 Months", f'{_roll.get("total", 0):,.0f}', "head",
                f'<span class="snap-neu">{_prec_ord(_roll.get("rank", 0))} of '
                f'{_roll.get("of", 0)} rolling 12-month windows since '
                f'{_first}</span>',
                '<span class="snap-neu">no seasonal adjustment needed</span>',
                mom_lbl="RANK", yoy_lbl="BASIS",
                foot="one window ends on every month, and each holds "
                     "every calendar month once",
            ),
            _snap_card(
                "Placements per 100 Beef Cows", f'{_percow.get("value", 0):.1f}',
                "per 100 cows",
                f'<span class="snap-neu">{_prec_ord(_percow.get("rank", 0))} of '
                f'{_percow.get("of", 0)} rolling 12-month windows since '
                f'{_first}</span>',
                '<span class="snap-neu">head placed per 100 Jan-1 beef '
                'cows</span>',
                mom_lbl="RANK", yoy_lbl="BASIS",
                foot="separates fewer cattle placed from fewer cattle existing",
            ),
        ]
        st.html(
            "<style>"
            ".prec-grid{display:grid;grid-template-columns:repeat(4,1fr);"
            "gap:12px;align-items:stretch;}"
            ".prec-grid>.snap-card{height:100%;box-sizing:border-box;}"
            "@media (max-width:900px){.prec-grid{grid-template-columns:repeat(2,1fr);}}"
            "</style>"
            '<div class="prec-grid">' + "".join(_cards) + "</div>"
        )

        st.caption(
            f"A **record low** here means placements came in below every prior year at "
            f"the **same calendar month**. Placements are seasonal — October is always "
            f"large and July always small — so a bare \"lowest ever\" would only ever "
            f"name a summer month. A month also needs **{_pc['min_prior']}+ prior years** "
            f"to beat before it can set one: the series begins {_pc['first_year']}, and "
            f"on a shorter requirement its early years manufacture records they never "
            f"earned."
        )

        if _pc["runs"]:
            st.markdown('<div class="sec-hdr">Every run of three or more, and what '
                        'the herd did next</div>', unsafe_allow_html=True)
            _rows = []
            for _row in _pc["runs"]:
                _rn, _sh = _row["run"], _row["share"]
                _rows.append({
                    "Run": (f'{MONTH_ABBR[_rn["start"][1]]}–{MONTH_ABBR[_rn["end"][1]]} '
                            f'{_rn["end"][0]}'),
                    "Months": _rn["months"],
                    "Lowest month": min(_rn["values"]),
                    "Heifers on feed": (f'{_sh["pct"]:.1f}%' if _sh else "—"),
                    "Heifer share percentile": (f'{_sh["percentile"]:.0f}th' if _sh else "—"),
                    "Beef cows, next year": ("—" if _row["cows_next"] is None
                                             else f'{_row["cows_next"]:+.1f}%'),
                    "Beef cows, year after": ("—" if _row["cows_then"] is None
                                              else f'{_row["cows_then"]:+.1f}%'),
                })
            st.dataframe(pd.DataFrame(_rows), hide_index=True, width="stretch",
                         column_config={"Lowest month":
                                        st.column_config.NumberColumn(format="%,.0f")})
            st.caption(
                "Heifers on feed is heifers as a percent of heifers plus steers, averaged "
                "over that year, with its percentile across the whole series. **Imported "
                "feeders are overwhelmingly steers and sit in that denominator**, so a year "
                "when imports are blocked carries a mechanically higher heifer share than "
                "the same herd would otherwise show — worth knowing before reading one run "
                "against another. Beef cow changes are USDA's Jan-1 inventory."
            )

        # THE TEN LOWEST 12-MONTH TOTALS. Asked for by Ross, 2026-10-27:
        # *"a list of the top 10 rolling 12 month placements ranking from #1
        # being the lowest"*, in the shape of the runs table above.
        #
        # WINDOWS OVERLAP AND THE CAPTION HAS TO SAY SO. The 12 months ending
        # August and the 12 months ending September share eleven of their
        # months, so one quiet stretch fills several rows -- these ten touch
        # three calendar years, not ten. Ten rows read as ten episodes unless
        # the page says otherwise, which would overstate how often this has
        # happened on exactly the figure the panel leads with.
        # TWO RANKINGS, BECAUSE A LITERAL TOP TEN IS NEARLY DEGENERATE.
        # "Any window" is what Ross asked for and is the honest answer to the
        # question -- but six of its ten rows are one 2026 stretch read from
        # six month-ends. "One per year" takes each calendar year's quietest
        # 12 months, which reads as a league table of years instead.
        #
        # A SWITCH RATHER THAN TWO STACKED TABLES: twenty rows of near
        # identical shape invite a reader to confuse them, and both rankings
        # are already computed in compare(), so neither costs a fetch. This is
        # the Cold Storage shape. The variable is `_low_mode` and never `view`
        # -- this page binds `view` to a segmented control at module level,
        # the collision that cost a rename once already.
        _low_mode = st.segmented_control(
            "Ranking", ["Any window", "One per year"], default="Any window",
            key="prec_low_mode",
            help="Any window ranks every rolling 12-month window. One per "
                 "year takes each calendar year's quietest 12 months, so ten "
                 "rows are ten years.",
        )
        _per_year = _low_mode == "One per year"
        _low = _pc["lowest_per_year"] if _per_year else _pc["lowest_windows"]
        if _low["rows"]:
            st.markdown('<div class="sec-hdr">The ten lowest 12-month placement '
                        'totals</div>', unsafe_allow_html=True)
            _lrows = [{
                "Rank": _r["rank"],
                "12 months ending": f'{MONTH_ABBR[_r["month"]]} {_r["year"]}',
                "Placements": _r["total"],
                "Per 100 beef cows": ("—" if _r["per100"] is None
                                      else f'{_r["per100"]:.1f}'),
                "Heifers on feed": (f'{(_heif.get(_r["year"]) or {})["pct"]:.1f}%'
                                    if _heif.get(_r["year"]) else "—"),
                "Heifer share percentile": (
                    f'{(_heif.get(_r["year"]) or {})["percentile"]:.0f}th'
                    if _heif.get(_r["year"]) else "—"),
            } for _r in _low["rows"]]
            st.dataframe(pd.DataFrame(_lrows), hide_index=True, width="stretch",
                         column_config={
                             "Placements":
                                 st.column_config.NumberColumn(format="%,.0f"),
                             "Per 100 beef cows": st.column_config.TextColumn(
                                 help="Head placed on feed over this window, "
                                      "for every 100 beef cows in the US "
                                      "breeding herd on January 1 of that "
                                      "year."),
                             "Heifers on feed": st.column_config.TextColumn(
                                 help="Heifers as a percent of the cattle on "
                                      "feed, averaged over the calendar year "
                                      "the window ends in."),
                         })
            _lead = (f"Each row is the quietest 12 months *ending* in that "
                     f"calendar year, one year per row, out of {_low['of']} "
                     f"years since {_first}."
                     if _per_year else
                     f"Each row is the 12 months *ending* that month, out of "
                     f"{_low['of']} such windows since {_first}.")
            _ovl = (f"Adjacent years can still **overlap** — a December window "
                    f"and the following January window share eleven months — so "
                    f"these ten come from **{_prec_stretch(_low['stretches'])}**."
                    if _per_year else
                    f"Those windows **overlap** — the 12 months to August and "
                    f"the 12 months to September share eleven of their months — "
                    f"so a single quiet stretch fills several rows: these ten "
                    f"come from **{_prec_stretch(_low['stretches'])}**, not ten.")
            st.caption(
                f"**#1 is the lowest.** {_lead} {_ovl} **Per 100 beef cows** "
                f"is how many head went on feed for every 100 beef cows in the "
                f"US breeding herd on January 1 of that year. It scales the "
                f"total to the size of the herd that produced it, which is why "
                f"a window can be among the lowest on head and ordinary per "
                f"cow. **Heifers on feed** is that calendar year's average "
                f"share with its percentile across the whole series — the same "
                f"figures the runs table and the on-feed table quote."
                + _prec_spread_line(_low["rows"], _heif)
            )

        # ── per beef cow, by year, with the heifer share beside it ──────────
        # Ross, 2026-10-27: a chart of the per-cow figures, what they mean,
        # "and how they might correlate to retention".
        #
        # THE ANSWER IS MEASURED AND IT IS MOSTLY NO. Per-cow placements
        # against the FOLLOWING year's beef cow change run about r = -0.19
        # over 30 years, which is close to no relationship; the heifer share
        # manages about -0.63 on the same question. So the chart carries the
        # heifer share too and the caption reports both numbers. Asserting a
        # retention story off the per-cow line would be supplying a plausible
        # wrong cause, which is the one thing this panel refuses to do.
        _pc_by_year = _pc["per_cow"].get("by_year", {})
        _tot_by_year = _pc.get("total_by_year", {})
        if _pc_by_year:
            st.markdown('<div class="sec-hdr">Placements by year, against '
                        'heifers on feed</div>', unsafe_allow_html=True)
            # TWO BASES, ONE CHART. The tab led with a 12-month placement
            # total that appeared in no chart at all -- only in tables -- so
            # the headline figure had no shape over time. Per-cow and total
            # cover the SAME windows (each year's December), so the switch
            # changes the normalisation and nothing else, and the heifer line
            # lines up with both.
            _basis = st.segmented_control(
                "Basis", ["Per 100 beef cows", "12-month total"],
                default="Per 100 beef cows", key="prec_basis",
                help="The same windows either way — each year's 12 months "
                     "ending December. Per cow divides by that January 1 herd.",
            )
            _is_total = _basis == "12-month total"
            st.plotly_chart(
                prec_basis_chart(
                    _tot_by_year if _is_total else _pc_by_year, _heif,
                    "Head placed, 12 months" if _is_total
                    else "Head placed per 100 beef cows",
                    "%{y:,.0f} head placed" if _is_total
                    else "%{y:.1f} head per 100 beef cows"),
                use_container_width=True)
            st.caption(
                ("Bars are the total head placed on feed in the 12 months "
                 "ending each December. This is the figure the tables above "
                 "rank, drawn over time."
                 if _is_total else
                 "Bars are the 12 months ending each December — how many head "
                 "went on feed for every 100 beef cows in the US breeding herd "
                 "that January 1. A high bar means more cattle placed per cow "
                 "in the herd, a low one fewer.")
                + " The red line is heifers as a percent of the cattle on "
                  "feed, on its own axis; hover for that year's percentile."
            )
            _rs = _pc.get("retention_signal") or {}
            if _rs.get("per_cow_vs_herd") is not None:
                st.caption(
                    f"**Does the per-cow figure track heifer retention? Measured, "
                    f"not assumed — and mostly it does not.** Against the "
                    f"*following* year's change in beef cow numbers it runs "
                    f"**r = {_rs['per_cow_vs_herd']:+.2f}** over "
                    f"{_rs['n_herd']} years, which is close to no relationship "
                    f"at all. The heifer share on the same test runs "
                    f"**r = {_rs['share_vs_herd']:+.2f}** — far closer — so the "
                    f"red line, not the bars, is the one to read for that "
                    f"question, and the Heifers on Feed tab is where it lives. "
                    f"The two series here move together at "
                    f"**r = {_rs['per_cow_vs_share']:+.2f}**, and even that is "
                    f"partly definitional: heifers are counted in placements, "
                    f"so the two cannot be independent. **These are "
                    f"associations measured over {_rs['n_herd']} years, not "
                    f"causes**, and two series on separate axes will look "
                    f"related whatever they do."
                )

        # ── the same ranking for on-feed inventory ───────────────────────────
        # Ross: "an on-feed top 10 like we have for placements, and add the
        # heifers on feed to that".
        #
        # AVERAGE, NOT SUM, BECAUSE ON FEED IS A STOCK. Placements are a flow
        # and twelve months of them add up; inventory is a standing count, so
        # summing it bills the same animal for every month it stands in the
        # yard. It is wired through the same `agg` switch rather than a second
        # function, and the caption names the basis.
        _onf = (_pc.get("lowest_onfeed_per_year") if _per_year
                else _pc.get("lowest_onfeed")) or {}
        if _onf.get("rows"):
            st.markdown('<div class="sec-hdr">The ten lowest 12-month average '
                        'on-feed inventories</div>', unsafe_allow_html=True)
            _orows = []
            for _r in _onf["rows"]:
                _h = _heif.get(_r["year"]) or {}
                _orows.append({
                    "Rank": _r["rank"],
                    "12 months ending": f'{MONTH_ABBR[_r["month"]]} {_r["year"]}',
                    "Avg on feed": _r["total"],
                    "Heifers on feed": (f'{_h["pct"]:.1f}%' if _h else "—"),
                    "Heifer share percentile": (f'{_h["percentile"]:.0f}th'
                                                if _h else "—"),
                })
            st.dataframe(pd.DataFrame(_orows), hide_index=True, width="stretch",
                         column_config={
                             "Avg on feed":
                                 st.column_config.NumberColumn(format="%,.0f"),
                             "Heifers on feed": st.column_config.TextColumn(
                                 help="Heifers as a percent of the cattle on "
                                      "feed, averaged over that calendar year."),
                         })
            st.caption(
                f"**#1 is the lowest**, and it is an **average**, not a total: "
                f"cattle on feed is a standing count, so twelve months of it do "
                f"not add up the way placements do. Out of {_onf['of']} windows "
                f"since {_first}, and these ten come from "
                f"**{_prec_stretch(_onf['stretches'])}** — the same overlap as "
                f"the table above. Heifers on feed is that calendar year's "
                f"average share with its percentile across the whole series, "
                f"the same figures the runs table quotes. The Ranking switch "
                f"above governs both tables."
            )

        st.caption(
            "**The three figures above can disagree, which is why all three are here.** "
            "The calendar-month record is what a monthly report invites and is the most "
            "fragile — a margin of a few thousand head sits inside USDA's revision range. "
            "The 12-month total is seasonality-free and revision-proof. Placements per "
            "beef cow is the only one that separates *fewer cattle being placed* from "
            "*fewer cattle existing*. This panel attributes no cause."
        )


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

        # The percent of year-ago is computed once per series and carried into
        # BOTH the table and the Excel sheet, so a downloaded workbook cannot
        # disagree with the page it came off.
        #
        # Each reaches back into the full-history frame rather than its own
        # nine-year window, so the oldest displayed year has a figure instead
        # of a "None" -- see with_year_ago_pct. Other disappearance has no
        # full-history twin and does not need one: it is Excel-only, and a
        # missing value writes an EMPTY cell there rather than the word.
        inv_y   = with_year_ago_pct(inv_s,   series_for(inv_full, state))
        place_y = with_year_ago_pct(place_s, series_for(place_full, state))
        sales_y = with_year_ago_pct(sales_s, series_for(sales_full, state))
        other_y = with_year_ago_pct(other_s)

        dl_col1, dl_col2 = st.columns([1, 5])
        with dl_col1:
            excel_bytes = _to_excel({
                "On-feed inventory": inv_y, "Placements": place_y, "Marketings": sales_y,
                "Other disappearance": other_y, "Heifer-steer split": hpct,
            })
            st.download_button("Download Excel", excel_bytes, file_name=f"cattle_on_feed_{state}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        _date_col = st.column_config.DateColumn("date", format="MMM YYYY")
        _head_col = st.column_config.NumberColumn(format="%,.0f")
        _pct_col  = st.column_config.NumberColumn(format="%.1f%%")
        # Named so the number reads on its own: 97.0% under "% of year ago" is
        # three percent BELOW last year, where the same figure under a header
        # saying "YoY" would read as a near-doubling. This is USDA's own column
        # and it is not signed.
        _ya_col = st.column_config.NumberColumn(
            "% of year ago", format="%.1f%%",
            help="USDA's percent of previous year: 100 is unchanged from the "
                 "same month a year earlier, 97.0 is 3% below, 104.0 is 4% above. "
                 "A row reading None is one where USDA published no figure for "
                 "that month a year earlier.",
        )
        _cols = ["date", "Value", "pct_year_ago"]
        _cfg = {"date": _date_col, "Value": _head_col, "pct_year_ago": _ya_col}

        st.caption(
            "**% of year ago** is USDA's own convention, the column their report prints "
            "beside On Feed, Placed and Marketed — **100 means unchanged** from the same "
            "month a year earlier, 97.0 means 3% below."
        )

        st.markdown("**On-feed inventory (monthly)**")
        st.dataframe(inv_y[_cols].sort_values("date", ascending=False), hide_index=True, width="stretch",
                     column_config=_cfg)

        st.markdown("**Placements (monthly)**")
        st.dataframe(place_y[_cols].sort_values("date", ascending=False), hide_index=True, width="stretch",
                     column_config=_cfg)

        st.markdown("**Marketings (monthly)**")
        st.dataframe(sales_y[_cols].sort_values("date", ascending=False), hide_index=True, width="stretch",
                     column_config=_cfg)

        st.markdown("**Heifer / steer split (quarterly)**")
        st.dataframe(hpct.sort_values("date", ascending=False), hide_index=True, width="stretch",
                     column_config={"date": _date_col, "heifers": _head_col, "steers": _head_col,
                                     "total": _head_col, "heifer_pct": _pct_col, "steer_pct": _pct_col})
