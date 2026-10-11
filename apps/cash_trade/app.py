import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import html
import sys
import time
from pathlib import Path

# `scorecard` is a unique module name across every bundled app and both repos
# (checked 2026-10-02), so the bare-name import is safe here in a way that
# `snowflake_db` is not -- see CLAUDE.md on the five identical copies of that
# one and why whichever page loads first wins.
# `wasde` is SHARED and lives at the repo root -- the same convention
# apps/weekly_reports/app.py uses to reach the `letter` package. It is
# deliberately not copied in beside leverage.py: Python caches modules by
# NAME, so a second copy would mean whichever page loaded first decided which
# one every other page got. That is the `snowflake_db`-times-five problem
# CLAUDE.md documents, and US Beef Trade imports this same file.
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).parent))
import leverage  # noqa: E402
import scorecard  # noqa: E402
import wasde  # noqa: E402

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

# Daily negotiated purchases by region. USDA publishes each region TWICE a day,
# and THE TWO FILES DO NOT DESCRIBE THE SAME TRADING DAY:
#
#   "Afternoon" (median 15:08 CT) is dated the trading day and carries that
#   day's trade as of the 1:30 pm cut -- a PARTIAL count, still moving.
#   "Summary" (median 11:17 CT) is dated the day it is PUBLISHED and carries
#   the PREVIOUS business day's COMPLETE trade.
#
# So the morning file dated D finalises trading day D-1. Taking its report_date
# as the trading day prints yesterday's average under today's date, and nothing
# looks wrong when it does -- the head count is plausible and the price is off
# by cents. Verified on Nebraska across 08/25-09/22/2026: every Summary row is
# the prior business day's Afternoon row plus the late trade, nine pairs in a
# row (Aftn 08/27 195 hd @ 220.00 -> Summary 08/28 584 hd @ 220.00).
# fetch_daily_cash() shifts the morning file back a business day to correct it.
#
# COLORADO IS ABSENT ON PURPOSE. USDA discontinued the CO daily reports -- the
# afternoon file (LM_CT133) last published 06/27/2023 and the summary
# (LM_CT134) 07/05/2024, and the API returns nothing for either on any date
# since. Colorado is still inside the 5-Area WEEKLY average on the other tab;
# there is no daily Colorado series left to show. Do not "fix" this by adding
# slugs 2669/2670 back -- they return zero rows, not an error.
DAILY_REGIONS = {
    "TX/OK/NM":       {"morning": 2664, "afternoon": 2663},   # LM_CT118 / LM_CT117
    "Kansas":         {"morning": 2666, "afternoon": 2665},   # LM_CT121 / LM_CT120
    "Nebraska":       {"morning": 2668, "afternoon": 2667},   # LM_CT124 / LM_CT123
    "Iowa/Minnesota": {"morning": 2672, "afternoon": 2671},   # LM_CT137 / LM_CT136
}

# Only NEGOTIATED CASH, only Steer and Heifer, only the roll-up grade row.
# Widening any of the three changes the number: the graded rows double-count
# against "Total all grades", and ALL BEEF TYPE folds in dairybred and mixed
# lots -- the same filter the letter's fetch_regional_cash() documents.
DAILY_PURCHASE_TYPE = "NEGOTIATED CASH"
DAILY_CLASSES = ("STEER", "HEIFER")
DAILY_GRADE_TOTAL = "Total all grades"
DAILY_BASES = {"LIVE FOB": "Live FOB", "DRESSED DELIVERED": "Dressed Delivered"}
DAILY_CUT_LABEL = {"morning": "Final", "afternoon": "1:30 pm cut"}

# /Summary rows carry both the day total and the running week total, tagged in
# current_period. "Confirmed" is that trading day; "Week to Date" is cumulative
# from Monday and resets on the trading Monday, not the file Monday.
DAILY_VOLUME_PERIODS = {"Confirmed": "day", "Week to Date": "wtd"}

# Consecutive trading days of NULL week-to-date volume after which a region is
# reported as WITHHELD rather than quiet. See _null_run_days() for the measured
# gap this sits in the middle of.
SUPPRESSION_RUN_DAYS = 10

# The window drives the FETCH, not just the view, so the default is the cheap
# one. A hidden tab still executes (see the Tabs block), which means every load
# of the WEEKLY tab pays for whatever this defaults to: 1M is about 12 s across
# the eight reports on a cold cache and instant for the next hour, where 1Y is
# nearer 40 s. Anyone who wants the longer series can ask for it and wait once.
DAILY_WINDOWS = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
DAILY_WINDOW_DEFAULT = "1M"
DAILY_REGION_COLORS = {
    "TX/OK/NM": JPSI_BLUE, "Kansas": D14_COLOR,
    "Nebraska": DEL_COLOR, "Iowa/Minnesota": "#7e57c2",
}

# ── Monday-print forecast ────────────────────────────────────────────────────
# How much daily history the forecast calibrates on. A FULL YEAR, ASKED FOR
# OUTRIGHT, and that is safe for a reason that is easy to get wrong: the cost
# of a /Summary request is FLAT in the window length. Measured 2026-10-02, the
# eight Summary reports take 4.8 s for 30 days and 5.6 s for 365 -- 675 KB
# against 8.0 MB, server-bound either way. It is fetch_daily_cash's /Detail
# section that is expensive (11 MB for one region-year), and DAILY_WINDOW_DEFAULT
# exists to hold THAT down under the hidden-tab rule. Do not "fix" this by
# shrinking it to match the Daily tab: a year buys ~50 calibration weeks for
# under a second, and a month buys four.
FORECAST_CAL_DAYS = 365

# Trailing weeks used to carry the 5-Area number across to the national one.
# FOUR, AND THE SHORTNESS IS THE POINT. Backtested on 175 weekly pairs since
# 2023: in normal times every window from 4 to 26 weeks and all three methods
# (additive gap, ratio, OLS) land inside 2.4-3.4% median absolute error, so the
# choice barely matters -- until the relationship steps, when it is the only
# thing that matters. Since Kansas and TX/OK/NM stopped publishing daily
# volumes the gap roughly doubled and every method under-predicts; measured
# over those weeks the bias is -3.5% at 4 weeks, -12.4% at 8, -16.0% at 13 and
# -15.1% at 26. The short window is the one that notices a regime change.
# How many past weeks the late-trade estimate may draw on. TWENTY, AND THE
# REASON IS REPRODUCIBILITY RATHER THAN ACCURACY.
#
# Without a cap the pool is "every qualifying week in the fetch window", and
# that window is a rolling 365 days ending TODAY — so it loses its oldest week
# roughly every seven days and the estimate silently moves with it. Replaying
# the 2026-09-28 call from windows starting a few weeks apart gave 61,167 /
# 60,897 / 60,627: a 540-head spread on a call whose median miss is about 1.5%.
# The scorecard and the settled tiles both replay past calls, so a call that
# depends on when you ask cannot be scored honestly — the number we are judged
# on would decay quietly after the fact.
#
# Anchoring the pool to the N most recent weeks BEFORE the week being forecast
# makes the answer identical from any window that reaches back far enough.
# Measured 2026-10-05 over 47 Friday checkpoints: a cap of 20 is free —
# 6.31% median absolute error and 57% within 10%, the same to two decimals as
# no cap at all — while 16 costs 0.5 points and 12 costs 2.3. So 20 buys
# determinism for nothing, which is why it is not tuned any tighter.
FORECAST_MAX_ANALOGUES = 20

# The "weak" line: below this share of a typical week, the week has not traded
# enough for anything measured off it to mean much. It does two jobs, and they
# are the same judgement -- it labels the call's confidence, and it GATES the
# front-loading narrowing below.
FORECAST_WEAK_MATURITY = 0.50

# A pool thinner than this cannot be forecast from, whatever the week has done.
# Measured over 115 at-or-above-0.50 checkpoints, by how many analogue weeks
# the pool held:
#
#     pool  <=3   +81.2% median signed error, actual at or below the call 0/11
#     pool  4-6   +56.7%,                     actual at or below the call 0/13
#     pool 7-10    +5.7%
#     pool 16-21   +3.0%, median absolute 9.1%
#
# A two-week pool is not a weak forecast, it is a different number entirely --
# and it printed with "Firm" confidence and no warning, because nothing checked.
# Every one of those thin-pool calls is from Oct-Dec 2025, the start of the
# daily history, which is also why the headline accuracy quoted for this tab
# used to read 13.6%: it averaged the cold start in. On pools of 10 or more it
# is 9.2% with a +1.4% bias.
#
# IT IS MEASURED ON `hist` AND NOT ON `pool`, AND THOSE ARE TWO DIFFERENT
# POPULATIONS. Every figure above comes from Oct-Dec 2025, when a small pool
# meant a SHORT HISTORY -- there was nothing else behind the checkpoint. A
# small pool today means something else entirely: deep history, narrowed hard
# because the week's front-loading is a shape few past weeks share.
#
# Measured over the 31 checkpoints since where narrowing left fewer than ten
# analogues WITH ten or more available, the small narrowed pool is the best
# estimate on the page by a factor of two:
#
#     the narrowed call      median |err| 12.3%, signed  +7.7%, within 10% 45%
#     the unnarrowed pool                 24.7%,         +24.2%,           19%
#     the recent-weeks median             26.7%,         -12.7%,           19%
#
# So gating on `pool` refused the most accurate number available and showed
# the worst of the three instead. It is biased high -- the actual landed at or
# below the call on 23 of 31 -- but nothing like the cold start's 0 of 11 and
# 0 of 13, which is the signature this guard was built to catch.
#
# Falling back to the unnarrowed pool was tried and is WORSE than the call it
# would replace: closer than the recent-weeks median on 39% of those 31, which
# is below a coin flip. The narrowing earns its keep precisely where it looks
# thinnest.
#
# Gating on `hist` keeps the guard pointed at what the evidence describes: a
# checkpoint with nothing behind it, from the history being rebuilt, the
# window shortened, or a new weekday/cut appearing. A pool of two still cannot
# arise there, because narrowing only fires at five or more.
FORECAST_MIN_ANALOGUES = 10

FORECAST_GAP_WEEKS = 4
# Band is drawn from a slightly longer window so it spans a real range of
# outcomes rather than the four points the centre is built from.
FORECAST_BAND_WEEKS = 6

# Checkpoint ordering within a trading week. The afternoon file for day D is
# published about 15:08 CT on D; the morning file that FINALISES D lands about
# 11:17 CT on D+1. So for one trade_date the 1:30 pm cut comes first and the
# final second, and Monday's final precedes Tuesday's cut. Sorting on
# (weekday, CUT_ORDER[cut]) therefore puts a week's publications in the order
# they actually appeared, which is what "the latest thing USDA has told us"
# has to mean.
CUT_ORDER = {"afternoon": 0, "morning": 1}

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
  /* Same reasoning as .tile-value: a label that breaks as "IOWA/MI/NNESOT/A"
     is worse than a small one. The letter-spacing shrinks with the font,
     because at 0.08em it is what pushes the longest label over the edge. */
  .tile-label {{ color:{MUTED}; font-size:clamp(0.5rem, 0.85vw, 0.66rem);
                 text-transform:uppercase; letter-spacing:clamp(0.02em, 0.1vw, 0.08em);
                 margin-bottom:6px; white-space:nowrap; }}
  /* Tile values must never break mid-token. Streamlit's default overflow-wrap
     splits them once four tiles share a narrow row -- "Undefined" rendered as
     "Undefin/ed" and "$222.00" as "$222./00". nowrap stops the break and the
     clamp shrinks the text to fit rather than letting it overflow the tile.
     At desktop width the clamp resolves to 1.55rem, so nothing changes there
     and the weekly tiles, which use the same class, are untouched in practice. */
  .tile-value {{ color:{JPSI_DARK}; font-size:clamp(1rem, 2vw, 1.55rem);
                 font-weight:700; line-height:1.1; white-space:nowrap; }}
  .tile-delta-pos {{ color:{POS}; font-size:clamp(0.62rem, 1.05vw, 0.8rem); font-weight:600; margin-top:4px; white-space:nowrap; }}
  .tile-delta-neg {{ color:{NEG}; font-size:clamp(0.62rem, 1.05vw, 0.8rem); font-weight:600; margin-top:4px; white-space:nowrap; }}
  .tile-delta-neu {{ color:{MUTED}; font-size:clamp(0.62rem, 1.05vw, 0.8rem); font-weight:600; margin-top:4px; white-space:nowrap; }}
  /* The level a delta is measured FROM. Its own line rather than more text on
     the delta's, because .tile-delta-* is nowrap and four tiles share a row:
     appending to it overflows the tile at any width below desktop. */
  .tile-sub {{ color:{MUTED}; font-size:clamp(0.54rem, 0.9vw, 0.7rem); font-weight:400; margin-top:3px; white-space:nowrap; }}

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


def and_list(items) -> str:
    """["a"] -> "a"; ["a","b"] -> "a and b"; ["a","b","c"] -> "a, b and c"."""
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


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


def _probe_session() -> requests.Session:
    """
    A deliberately impatient session, used ONLY by publication_stamps().

    _session() retries three times with a backoff_factor of 3, so against an
    unresponsive USDA it blocks for roughly a minute and a half before giving
    up. That is the right trade for the data fetches, which have nothing to
    show without it. It is the wrong trade here: the probe runs at module scope
    above st.tabs, so during an outage EVERY visitor would pay that wait on
    every rerun, on whichever tab they are looking at, to learn something the
    page already has a fallback for. One attempt, split connect/read timeout,
    worst case about eleven seconds.
    """
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=0, status_forcelist=[], allowed_methods=["GET"])))
    return s


# `stamps` is unused in the body and must stay: it is USDA's published_date for
# LM_CT150, taken as an argument so st.cache_data keys on it. This used to read
# ttl=3600, persist="disk", which NEVER EXPIRED -- Streamlit ignores ttl when
# persist is set, so the sidebar's "Cache: 1 hr" was not true and a weekly
# release was only picked up by "Refresh now" or a restart. See publication_stamps.
@st.cache_data(persist="disk", max_entries=8, show_spinner=False)
def fetch_price_history(stamps: str) -> pd.DataFrame:
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
    # previous_week_head_count rides along for the forecast tab. It is a
    # HEADER-LEVEL field repeated on every row of the report, not a per-class
    # one -- de-duplicate by report_date before using it, which
    # weekly_5area_head() does. Carrying it here costs nothing: this request
    # already pulls the whole History section for the price panel.
    for c in ["head_count", "weight_range_avg", "weighted_avg_price",
              "previous_week_head_count"]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce")

    df = df.dropna(subset=["report_date"])
    keep = ["report_date", "current_period", "selling_basis_desc", "class_description",
            "head_count", "weight_range_avg", "weighted_avg_price",
            "previous_week_head_count"]
    return df[keep].sort_values("report_date").reset_index(drop=True)


# `stamps` as above, for LM_CT154. Same never-expiring ttl bug, same fix.
@st.cache_data(persist="disk", max_entries=8, show_spinner=False)
def fetch_volume_history(stamps: str) -> pd.DataFrame:
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


@st.cache_data(persist="disk", max_entries=8, show_spinner=False)
def fetch_leverage(stamps: str, schema: int) -> dict:
    """
    The four purchase-mix and committed-inventory series, full history.

    `stamps` is unused in the body and is the cache key, exactly as in
    fetch_price_history -- see there. About 3 s and 6 MB for all four
    concurrently, which is the same order as the weekly fetches this page
    already makes, so the hidden-tab rule costs roughly what the other tabs
    do rather than multiplying it.
    """
    del schema          # cache key only, exactly like `stamps` above
    return leverage.load(_session)


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


def _dnum(x):
    """USDA ships numbers as comma-grouped strings and blanks as None or ''."""
    if x is None:
        return None
    s = str(x).replace(",", "").strip()
    if not s or s in {"-", "--"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _daily_rows(payload) -> list:
    """
    AMS ANSWERS 200 WITH A BARE JSON STRING when a window has no report -- not
    an error status, not an empty list, not an object with zero results.
    Iterating that as sections walks its CHARACTERS and dies on str.get. Every
    shape but the documented one is treated as no rows.
    """
    if isinstance(payload, dict):
        r = payload.get("results")
        return r if isinstance(r, list) else []
    if isinstance(payload, list):
        out = []
        for sec in payload:
            if isinstance(sec, dict) and isinstance(sec.get("results"), list):
                out.extend(sec["results"])
        return out
    return []


PROBE_FAILED = "probe-unavailable"
# NO persist="disk" HERE, AND THAT IS THE WHOLE POINT. Streamlit documents that
# "ttl will be ignored if persist='disk' or persist=True" -- so a probe written
# @st.cache_data(ttl=300, persist="disk") never expires and the freshness check
# freezes at whatever it first saw. Verified against streamlit 1.63's own source.
# This cache is process-wide and in-memory, which is what a 5-minute freshness
# probe wants anyway.
@st.cache_data(ttl=300, show_spinner=False)
def publication_stamps() -> str:
    """
    When USDA last published each of our eight reports, as one opaque string.
    It is passed to fetch_daily_cash() purely as a cache key, so the expensive
    fetch re-runs exactly when USDA publishes and not on a timer.

    WHY NOT REFRESH ON A SCHEDULE, which is the obvious thing to do: AMS DOES
    NOT PUBLISH ONE. Its 30 Apr 2020 LMR notice says that from 4 May 2020 report
    data is released "in real time", replacing the old top-of-the-hour release,
    and there is no livestock equivalent of the dairy release-times page. The
    measured spread says the same -- over 180 days (n=506 AM, 497 PM):

        AM  min 10:52  median 11:17  p90 11:39  p95 11:55  p99 13:17  max 16:18
        PM  min 14:49  median 15:08  p90 15:23  p95 15:28  p99 16:14  max 16:49

    4.9% of AM files land after noon and the tail runs past 16:00, so a refresh
    pinned to the median would miss them outright. The only clock AMS commits to
    is a 5:00 pm Central cutoff, past which a delayed report is held to the next
    business day. Keying on the stamp USDA itself publishes needs no schedule.

    The stamps are US CENTRAL with daylight saving -- AMS LMPR API User Guide
    V3.3 (Nov 2024) section 2.2: "The LMPR API is set to Central Standard Time
    (CST) time zone. Standard and daylight time rules apply." Confirmed live on
    2026-09-23: the Nebraska AM stamp read 11:10:32 and appeared at 11:11:22
    CDT. Nothing here depends on that -- this compares stamps to stamps, never
    to our own clock -- but it is what the displayed time means.

    The reports LIST endpoint carries published_date for every slug in a single
    request (~67KB, ~3.7s measured), which is far cheaper than the eight Detail
    calls it guards, and it matters that it is cheap: this page is behind a tab,
    and a hidden Streamlit tab still executes on every rerun.

    On failure this returns a STABLE sentinel rather than "" or a timestamp. A
    key that varies on failure would turn every probe outage into a full
    eight-request refetch -- the opposite of the point. A constant means the
    first failure refetches once and every failure after it is a cache hit.
    """
    try:
        resp = _probe_session().get(LMR_BASE, timeout=(3, 8))
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        return PROBE_FAILED
    if not isinstance(rows, list):
        return PROBE_FAILED
    wanted = {CT150_ID, CT154_ID}
    wanted |= {slug for cuts in DAILY_REGIONS.values() for slug in cuts.values()}
    # THE PACKER LEVERAGE SLUGS BELONG HERE AND WERE MISSING UNTIL 2026-10-07.
    # fetch_leverage keys on stamps_for(_probe, [CT142_ID, CT153_ID]); with
    # neither slug in this set that call finds nothing to keep and returns the
    # CONSTANT sentinel. A constant key plus @st.cache_data(persist="disk") --
    # which voids a ttl, the trap documented directly above this function -- is
    # a cache that never expires. The whole tab (purchase mix, packer-owned,
    # forward book, committed, delivery schedule) therefore froze at whatever it
    # first fetched and only moved on "Refresh now", a SCHEMA bump or a reboot,
    # rendering perfectly throughout. Same symptom as the fix at line 338.
    wanted |= {leverage.CT142_ID, leverage.CT153_ID}
    stamps = {x.get("slug_id"): x.get("published_date") for x in rows
              if isinstance(x, dict) and x.get("slug_id") in wanted}
    if not stamps:
        return PROBE_FAILED
    return "|".join(f"{k}={stamps[k]}" for k in sorted(stamps))


def stamps_for(stamps: str, slugs) -> str:
    """
    The publication stamps for just `slugs`, as a cache key.

    One probe covers every report on the page, but each consumer must key on
    only its OWN reports -- otherwise the weekly fetch, whose data changes on
    Mondays, would re-run every time a daily file published.
    """
    if not stamps or stamps == PROBE_FAILED:
        return PROBE_FAILED
    want = {str(s) for s in slugs}
    keep = [p for p in stamps.split("|")
            if "=" in p and p.split("=", 1)[0] in want]
    return "|".join(keep) if keep else PROBE_FAILED


def daily_last_published(stamps: str) -> str:
    """The newest publication stamp in the probe string, for display."""
    if not stamps or stamps == PROBE_FAILED:
        return ""
    seen = [s.split("=", 1)[1] for s in stamps.split("|") if "=" in s]
    seen = [s for s in seen if s]
    if not seen:
        return ""
    # Stamps are "MM/DD/YYYY HH:MM:SS"; sort on a comparable key, not the string.
    def _key(s):
        try:
            d, t = s.split(" ", 1)
            m, dd, y = d.split("/")
            return (y, m, dd, t)
        except Exception:
            return ("", "", "", "")
    return max(seen, key=_key)


# NO ttl, deliberately: persist="disk" would ignore it anyway (see
# publication_stamps), and stating one would only mislead the next reader into
# thinking time drives this. The `stamps` argument drives it. max_entries bounds
# what disk collects, since the key changes roughly twice a day.
def _fetch_many(jobs: list, timeout: int = 90) -> dict:
    """
    Run independent datamart GETs concurrently, returning {key: rows}.

    Latency here is server-bound, not payload-bound: a 30-day window costs
    about 2.2 s whether it returns 108 KB of Summary or 1 MB of Detail. Run
    sequentially, the sixteen requests this page needs are over half a minute
    of wall clock on a cold cache -- and because a hidden Streamlit tab still
    executes, everyone pays it, including someone who only opens the Weekly
    tab. They are independent GETs, so they overlap cleanly.

    Each worker builds its OWN session via _session(): requests.Session is not
    safe to share across threads. Nothing in here touches st.*, so it is safe
    inside a cached function.

    A job that fails yields [] rather than raising: these are independent
    reports and one being down is not a reason to blank the others.
    """
    def run(job):
        key, slug, section, params = job
        try:
            resp = _session().get(f"{LMR_BASE}/{slug}/{section}",
                                  params=params, timeout=timeout)
            if resp.status_code in (204, 404):
                return key, []
            resp.raise_for_status()
            return key, _daily_rows(resp.json())
        except Exception:
            return key, []

    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as ex:
        return dict(ex.map(run, jobs))


@st.cache_data(persist="disk", max_entries=64, show_spinner=False)
def fetch_daily_cash(start: str, end: str, stamps: str) -> pd.DataFrame:
    """
    Daily negotiated Steer/Heifer prices for the four regions USDA still
    publishes daily, both cuts, keyed on the TRADING day rather than the file
    date.

    `stamps` IS DELIBERATELY UNUSED IN THIS BODY. It is USDA's own publication
    timestamps from publication_stamps(), taken as an argument solely so
    that st.cache_data includes it in the cache key: when USDA publishes, the
    string changes, the key changes, and this re-runs. Deleting it as a dead
    parameter would silently restore pure time-based expiry and put the page
    back to serving data up to six hours stale.

    Eight requests in all -- one per region per cut -- because the datamart
    accepts a report_date RANGE (report_date=MM/DD/YYYY:MM/DD/YYYY). A day at a
    time would be some 600 requests for a year of history.

    THE grade_desc FILTER IS WHAT MAKES THIS AFFORDABLE, and it matters because
    of the hidden-tab rule: this runs on every rerun, including for someone who
    only ever looks at the Weekly tab. Unfiltered, a year of Nebraska is 43,176
    rows and 48 MB in 12 s; asking the server for "Total all grades" alone cuts
    it to 10,280 rows and 11 MB in 4.5 s, and those are exactly the rows kept
    below. Measured 2026-09-23.

    Only ONE extra filter can be passed: chaining a second (grade_desc AND
    purchase_type_code) makes AMS return its bare-string no-results sentinel
    rather than an intersection. The class and purchase-type filters therefore
    stay client-side, and the grade check below stays too -- the server filter
    is an optimisation, not a guarantee.

    A region that fails is SKIPPED, not raised: these are eight independent
    reports and one being down is not a reason to blank the other three.
    """
    jobs = [((region, cut), slug, "Detail",
             {"q": f"report_date={start}:{end};grade_desc={DAILY_GRADE_TOTAL}"})
            for region, cuts in DAILY_REGIONS.items() for cut, slug in cuts.items()]
    fetched = _fetch_many(jobs)

    out = []
    for (region, cut), rows in fetched.items():
        for x in rows:
            if str(x.get("purchase_type_code", "")).strip() != DAILY_PURCHASE_TYPE:
                continue
            if str(x.get("class_desc", "")).strip() not in DAILY_CLASSES:
                continue
            if str(x.get("grade_desc", "")).strip() != DAILY_GRADE_TOTAL:
                continue
            basis = str(x.get("selling_basis_desc", "")).strip()
            if basis not in DAILY_BASES:
                continue
            # UNPRICED ROWS ARE KEPT, and that is load-bearing. USDA
            # publishes a file for a day with no confirmed trade, every
            # price null -- that is its "Undefined" market test, a real
            # answer. Dropping those rows made a published no-trade day
            # indistinguishable from a day USDA never published, so the
            # headline silently fell back to an older day: measured over the
            # last year the headline was behind the newest published day for
            # 15% of wall-clock. daily_combined() still drops them, so no
            # unpriced row reaches an average; they exist only so the page
            # can tell "nothing traded" from "nothing published".
            price = _dnum(x.get("wtd_avg_price"))
            out.append({
                "region": region, "cut": cut,
                "file_date": x.get("report_date"),
                "class": str(x.get("class_desc", "")).strip(),
                "basis": DAILY_BASES[basis],
                "head": _dnum(x.get("head_count")),
                "weight": _dnum(x.get("wtd_avg_weight")),
                "price": price,
            })

    df = pd.DataFrame(out)
    if df.empty:
        return df

    df["file_date"] = pd.to_datetime(df["file_date"], format="%m/%d/%Y", errors="coerce")
    df = df.dropna(subset=["file_date"])
    if df.empty:
        return df

    # THE ONE-BUSINESS-DAY SHIFT -- see DAILY_REGIONS for the evidence. Only the
    # morning file moves; the afternoon file is already dated its trading day.
    #
    # BDay steps over weekends but NOT holidays, so a morning file published the
    # day after a holiday resolves to the holiday rather than the last session
    # that actually traded. It is off by one session on those few dates a year,
    # and the tell is a holiday carrying a full day of trade.
    df["trade_date"] = df["file_date"]
    morning = df["cut"] == "morning"
    df.loc[morning, "trade_date"] = (
        df.loc[morning, "file_date"] - pd.tseries.offsets.BDay(1))

    return df.sort_values(["trade_date", "region", "cut"]).reset_index(drop=True)


@st.cache_data(persist="disk", max_entries=64, show_spinner=False)
def fetch_daily_volume(start: str, end: str, stamps: str) -> pd.DataFrame:
    """
    Negotiated cash HEAD COUNT per region -- the day's confirmed total and the
    running week-to-date -- from each report's /Summary section, which the
    price fetch never asks for.

    `stamps` is the cache key, exactly as in fetch_daily_cash(); see there.

    THIS IS A BROADER UNIVERSE THAN THE PRICES, and must never be shown as the
    head count behind them. fetch_daily_cash() filters to Steer and Heifer,
    Live FOB and Dressed Delivered, "Total all grades", because that is what a
    quoted average has to be built from. USDA's Confirmed and Week-to-Date
    volumes count every class and all four selling bases -- mixed lots,
    dairybred, the FOB/delivered variants the price section leaves out. On
    09/18/2026 Nebraska that is 3,690 head confirmed against 1,547 in the live
    FOB steer row. Same market, different question.

    A NULL VOLUME IS ZERO IN THE 5-AREA SUM, AND NOT A ZERO ANYWHERE ELSE.
    USDA leaves the field empty for a region it is not giving a number for, and
    its own aggregate adds that in as nothing: summing these four regions with
    nulls as zero reproduces LM_CT100's current_week_head_count EXACTLY on 118
    of 118 file dates (verified 2026-09-23), and LM_CT150's published
    previous_week_head_count on 23 of 23 weeks back to April 2026 (re-verified
    2026-10-02). That is why the 5-Area figure on the page is a sum of these
    four and not a fifth request.

    THE RULE DOES NOT CARRY TO A PER-REGION FIGURE, and reading it as though it
    did is what put "0 head" on the Kansas and TX/OK/NM tiles while USDA was
    withholding both for confidentiality. USDA NEVER PUBLISHES A LITERAL 0 --
    zero occurrences in 2,877 region-trading-days over 2024-01-01..2026-10-02 --
    so a 0 on a region tile is always this page's own invention, and it reads
    as "nobody traded". The trade is real: as TX/OK/NM (last number 2026-06-26)
    and Kansas (2026-08-14) went dark, the gap between LM_CT154 national
    confirmed negotiated and the LM_CT150 5-Area doubled from a median 11,567
    hd/wk to 23,172 hd/wk, with 4 of 6 weeks above the entire pre-period max.
    Roughly 11,600 hd/wk of real negotiated trade is counted nationally and
    absent from the 5-Area -- absent from USDA's figure as well as ours, which
    is why the sum above still reconciles. weekly_to_date() carries the raw
    null out for the tiles and zeroes it only for the total; see there and
    _null_run_days() for telling a withheld region from a quiet one.

    Coverage over the last 180 days, morning files: IA/MN 88%, Nebraska 78%,
    Kansas 57%, TX/OK/NM 38%.
    """
    jobs = [((region, cut), slug, "Summary",
             {"q": f"report_date={start}:{end}"})
            for region, cuts in DAILY_REGIONS.items() for cut, slug in cuts.items()]
    fetched = _fetch_many(jobs)

    out = []
    for (region, cut), rows in fetched.items():
        for x in rows:
            if str(x.get("purchase_type_desc", "")).strip() != DAILY_PURCHASE_TYPE:
                continue
            period = str(x.get("current_period", "")).strip()
            if period not in DAILY_VOLUME_PERIODS:
                continue
            out.append({
                "region": region, "cut": cut,
                "file_date": x.get("report_date"),
                "period": DAILY_VOLUME_PERIODS[period],
                "head": _dnum(x.get("current_date_volume")),
                # On the Week-to-Date row this is the RUNNING TOTAL AT THE SAME
                # POINT LAST WEEK, not last week's finished total: measured,
                # week_ago_volume(D) equals current_date_volume(D-7). It is the
                # like-for-like comparison, which is the useful one midweek.
                "head_week_ago": _dnum(x.get("week_ago_volume")),
            })

    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["file_date"] = pd.to_datetime(df["file_date"], format="%m/%d/%Y", errors="coerce")
    df = df.dropna(subset=["file_date"])
    if df.empty:
        return df

    # Same one-business-day shift as the prices -- the morning file's volumes
    # describe the previous business day too, so the week-to-date must be keyed
    # on the TRADING day or it lands a day late and the Monday reset moves.
    df["trade_date"] = df["file_date"]
    morning = df["cut"] == "morning"
    df.loc[morning, "trade_date"] = (
        df.loc[morning, "file_date"] - pd.tseries.offsets.BDay(1))
    return df.sort_values(["trade_date", "region", "cut"]).reset_index(drop=True)


def _null_run_days(vol: pd.DataFrame, region: str, trade_date) -> int:
    """
    Consecutive trading days up to `trade_date` on which USDA published this
    region's week-to-date volume BLANK.

    THE FIELD ALONE CANNOT SAY WHY IT IS BLANK, which is the whole reason this
    exists. USDA never publishes a literal 0 -- zero occurrences in 2,877
    region-trading-days over 2024-01-01..2026-10-02 -- so "no confirmed trade"
    and "withheld for confidentiality" are the SAME empty field on the day, and
    the obvious discriminators do not work. The full-skeleton signature in
    particular does not: on days where NEGOTIATED CASH is blank, NEGOTIATED
    GRID BASE still carries a number 90% of the time for Iowa/Minnesota.

    The RUN separates them cleanly. Over those same three years:

        Iowa/Minnesota   longest blank run  3
        Nebraska         longest blank run  4
        Kansas           runs of 1-4, then one run now 35 days and open
        TX/OK/NM         runs of 1-4, then two runs reaching 36 and 67

    Every ordinary quiet stretch ended by day 4; every run that reached day 5
    went on to at least 35. SUPPRESSION_RUN_DAYS sits in that empty middle, so
    a quiet week is never called withheld and a region that goes dark is named
    within two trading weeks. The measurement needs the fetched window to be
    longer than the threshold: the shortest DAILY_WINDOWS option is 30 calendar
    days, about 21 trading days, so it is.
    """
    d = vol[(vol["period"] == "wtd") & (vol["region"] == region)
            & (vol["trade_date"] <= trade_date)]
    if d.empty:
        return 0
    # Morning is the final figure and wins where both cuts exist -- the same
    # precedence the tiles use, so the run describes the number on screen.
    seen = {}
    for cut in ("afternoon", "morning"):
        hit = d[d["cut"] == cut]
        seen.update(dict(zip(hit["trade_date"], hit["head"])))
    return _trailing_blank_run({td: pd.isna(v) for td, v in seen.items()},
                               trade_date)


def _price_blank_run_days(df: pd.DataFrame, region: str, trade_date) -> int:
    """
    The same run, measured on the PRICE frame instead of the volume one.

    This exists so a volume outage cannot blind the price tiles. The two feeds
    are different requests -- /Summary and /Detail -- and _fetch_many returns
    [] for a failed job, so one can go dark while the other is healthy. The
    volume flag is still preferred where it exists, because reusing it is what
    keeps the two panels agreeing by construction; this is the fallback for
    when it does not exist at all.

    "Usable" is head and price both present, which is exactly what
    daily_combined() keeps and therefore what decides whether a quote is found
    -- so this counts the days the tile actually rendered blank, not some
    neighbouring definition of it.

    IT READS daily_df, NOT dcombo. The unpriced rows fetch_daily_cash
    deliberately keeps are the entire evidence: without them a withheld day
    and a day USDA never published are the same absence, which is the
    distinction being drawn. See the unpriced-rows note in fetch_daily_cash,
    which made the same point for the headline date.

    The threshold transfers -- blank-PRICE runs end at 6 for an ordinary quiet
    stretch (TX/OK/NM; 4 elsewhere) against 33, 36 and 63 where a region went
    dark, so SUPPRESSION_RUN_DAYS sits in the gap on this series too. The
    PRICE floor of 6 is the binding one, not the volume series' 4.
    """
    reg = df[(df["region"] == region) & (df["trade_date"] <= trade_date)]
    if reg.empty:
        return 0
    usable = reg["head"].notna() & reg["price"].notna()
    by_day = usable.groupby(reg["trade_date"]).any()
    return _trailing_blank_run({td: not ok for td, ok in by_day.items()},
                               trade_date)


def _trailing_blank_run(blank_by_day: dict, upto) -> int:
    """
    Consecutive OBSERVED days up to `upto` that were blank, newest first.

    One definition of "run" for both series, rather than two near-identical
    loops -- this file already carries the cost of a module that exists five
    times, and two copies of a rule is how they start.

    A day USDA never published is simply not in the map, so it neither counts
    toward the run nor breaks it: the run is about what USDA said on the days
    it spoke, not about the calendar.

    The measurement needs the fetched window to be longer than the threshold it
    feeds. The shortest DAILY_WINDOWS option is 30 calendar days, about 21
    trading days, against a SUPPRESSION_RUN_DAYS of 10. A window too short to
    reach the threshold simply yields a short run, so the caller reports a
    blank rather than a withholding it cannot see.
    """
    run = 0
    for td in sorted((d for d in blank_by_day if d <= upto), reverse=True):
        if not blank_by_day[td]:
            break
        run += 1
    return run


def weekly_to_date(vol: pd.DataFrame, trade_date) -> dict:
    """
    Week-to-date head per region for one trading day, plus the 5-Area sum.

    Prefers the final (morning) figure and falls back to the 1:30 pm cut, the
    same precedence the price tiles use, so a region reports as far through the
    day as USDA has taken it.

    A BLANK VOLUME MEANS DIFFERENT THINGS IN THE TWO HALVES OF THIS RETURN, and
    that is not an inconsistency. The 5-Area total adds it in as zero because
    USDA's own aggregate does -- see fetch_daily_volume, and the 2026-10-02
    re-verification in the footnote this feeds. The per-region entry carries the
    raw None, because on a tile a 0 is a number this page invented and reads as
    "nobody traded" for a region whose trade USDA is withholding.
    """
    if vol.empty:
        return {}
    day = vol[(vol["trade_date"] == trade_date) & (vol["period"] == "wtd")]
    if day.empty:
        return {}
    out = {}
    for region in DAILY_REGIONS:
        reg = day[day["region"] == region]
        row = None
        for cut in ("morning", "afternoon"):
            hit = reg[reg["cut"] == cut]
            if not hit.empty:
                row = hit.iloc[0]
                break
        if row is None:
            continue
        blank = bool(pd.isna(row["head"]))
        out[region] = {
            "head": None if blank else float(row["head"]),
            "week_ago": (None if pd.isna(row["head_week_ago"])
                         else float(row["head_week_ago"])),
            "cut": row["cut"],
            # A blank that has lasted -- USDA is publishing the file and
            # holding the number back. Short blanks stay unflagged: they are
            # indistinguishable from a quiet day and must not be asserted.
            "suppressed": (blank and _null_run_days(vol, region, trade_date)
                           >= SUPPRESSION_RUN_DAYS),
        }
    if not out:
        return {}
    # Bound before the assignment rather than read out of `out` inside the
    # literal, so nobody has to reason about whether _total is in its own sum.
    withheld = [r for r, v in out.items() if v["suppressed"]]
    counted = [r for r, v in out.items() if not v["suppressed"]]
    out["_total"] = {
        # NULLS SUM AS ZERO HERE AND MUST KEEP DOING SO. USDA's published
        # 5-Area total drops a withheld region exactly this way: summing these
        # four with blanks as zero reproduces LM_CT150's own
        # previous_week_head_count on 23 of 23 weeks back to April 2026
        # (verified 2026-10-02), a span covering both TX/OK/NM and Kansas going
        # dark. The identity breaks if a blank is ever treated as missing here.
        "head": sum(0.0 if v["head"] is None else v["head"] for v in out.values()),
        "week_ago": (sum(v["week_ago"] for v in out.values()
                         if v["week_ago"] is not None)
                     if any(v["week_ago"] is not None for v in out.values()) else None),
        "cut": None,
        "withheld": withheld,
        "counted": counted,
    }
    return out


def _week_start(dates: pd.Series) -> pd.Series:
    """
    The Monday of the week a weekly report DESCRIBES, from its report_date.

    Both weekly reports print on the Monday after the week they cover, so the
    week is report_date minus seven days -- but only normalising to Monday
    afterwards is safe. A holiday pushes the release to Tuesday, and Tuesday
    minus seven is the PREVIOUS Tuesday, which would key that week one day off
    and silently fail to join against everything else.
    """
    shifted = dates - pd.to_timedelta(7, unit="D")
    return shifted - pd.to_timedelta(shifted.dt.weekday, unit="D")


def weekly_5area_head(price_df: pd.DataFrame) -> pd.Series:
    """
    USDA's own published 5-Area weekly negotiated head, keyed to the week it
    describes. Indexed by the Monday of that week.

    THIS IS THE NUMBER THE FORECAST IS AIMING AT, and it is also what makes the
    forecast arithmetic rather than a guess. Verified 2026-10-02 on every one
    of the 23 weeks back to April 2026: this equals the four daily regions'
    Friday-FINAL week-to-date, summed with nulls as zero -- exactly, not
    approximately, including the weeks where two of the four regions published
    nothing at all. So the only unknown left in Monday's 5-Area print is the
    trade that lands after USDA's last published cut.
    """
    if price_df.empty or "previous_week_head_count" not in price_df:
        return pd.Series(dtype=float)
    d = price_df.dropna(subset=["report_date"]).drop_duplicates("report_date")
    d = d.dropna(subset=["previous_week_head_count"])
    if d.empty:
        return pd.Series(dtype=float)
    out = pd.Series(d["previous_week_head_count"].values,
                    index=_week_start(d["report_date"]))
    return out[~out.index.duplicated(keep="last")].sort_index()


def weekly_national_head(vol_df: pd.DataFrame) -> pd.Series:
    """National weekly confirmed negotiated head (LM_CT154), keyed the same way."""
    if vol_df.empty or "total_head_count" not in vol_df:
        return pd.Series(dtype=float)
    d = vol_df.dropna(subset=["report_date", "total_head_count"]).drop_duplicates("report_date")
    if d.empty:
        return pd.Series(dtype=float)
    out = pd.Series(d["total_head_count"].values, index=_week_start(d["report_date"]))
    return out[~out.index.duplicated(keep="last")].sort_index()


def wtd_checkpoints(vol: pd.DataFrame) -> pd.DataFrame:
    """
    The 5-Area week-to-date head at every publication USDA has made, one row
    per (week, weekday, cut).

    Regions are summed with nulls as zero, the same rule weekly_to_date() and
    USDA's own aggregate follow -- see fetch_daily_volume. A region missing from
    the frame entirely contributes nothing, which is what makes a suppressed
    Kansas drop out here exactly as it drops out of USDA's published figure.
    """
    cols = ["week", "weekday", "cut", "order", "wtd"]
    if vol.empty:
        return pd.DataFrame(columns=cols)
    d = vol[vol["period"] == "wtd"].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    d["week"] = d["trade_date"] - pd.to_timedelta(d["trade_date"].dt.weekday, unit="D")
    d["weekday"] = d["trade_date"].dt.weekday
    # One row per region per checkpoint first, so a region USDA happens to
    # repeat cannot be counted twice into the sum.
    g = d.groupby(["week", "weekday", "cut", "region"], as_index=False)["head"].first()
    # to_numeric first: a checkpoint where every region is withheld arrives as
    # an all-None object column, and .fillna on one of those downcasts with a
    # FutureWarning today and changes behaviour later.
    cp = (g.assign(head=pd.to_numeric(g["head"], errors="coerce").fillna(0.0))
            .groupby(["week", "weekday", "cut"], as_index=False)["head"].sum()
            .rename(columns={"head": "wtd"}))
    cp["order"] = cp["cut"].map(CUT_ORDER)
    return cp.sort_values(["week", "weekday", "order"]).reset_index(drop=True)


def _front_of(cps: pd.DataFrame, week, weekday, order, wtd_now) -> float:
    """The previous checkpoint's share of this one, within one past week."""
    if not wtd_now:
        return float("nan")
    w = cps[cps["week"] == week].sort_values(["weekday", "order"])
    before = w[(w["weekday"] < weekday) |
               ((w["weekday"] == weekday) & (w["order"] < order))]
    if before.empty:
        return float("nan")
    return float(before.iloc[-1]["wtd"]) / float(wtd_now)


def forecast_5area(vol: pd.DataFrame, published5: pd.Series) -> dict:
    """
    Where Monday's 5-Area negotiated head is likely to land, given the
    week-to-date USDA has published so far.

    The week's final is known exactly once Friday's morning file lands; until
    then the gap is whatever trades after the last cut. That is estimated from
    the SAME CHECKPOINT in past weeks -- a Friday 1:30 pm cut is compared only
    against other Friday 1:30 pm cuts, because how much of a week is still to
    come depends entirely on how far into it you are standing.

    Past weeks' finals come from published5, not from the daily frame. The two
    are identical (see weekly_5area_head), but the published series exists for
    every week whether or not the daily window reaches back that far.

    THE ANALOGUES ARE NARROWED BY HOW FRONT-LOADED THE WEEK IS, which is the
    difference between a usable estimate and a useless one. Late-Friday trade
    ran a median 2,860 head across weeks already ~90% done by Thursday, against
    a median 7,330 over all weeks and 50,330 in the worst back-loaded one. The
    observable proxy is the previous checkpoint's share of the current one:
    high means the market has gone quiet, low means it is trading right now.

    Narrowing on WEEK MATURITY instead -- week-to-date against a typical recent
    week -- is the obvious alternative and is WORSE, 12.2% median absolute
    error against front-loading's 7.8% over the same 52 weeks, with band
    coverage falling from 65% to 50%. Tried 2026-10-02; do not swap them. A
    low maturity says the week is quiet but not whether it has finished being
    quiet, and those are different questions. It earns its keep as the
    reliability label below, where it beats front-loading outright.
    """
    cps = wtd_checkpoints(vol)
    if cps.empty or published5.empty:
        return {}
    cur_week = cps["week"].max()
    this = cps[cps["week"] == cur_week].sort_values(["weekday", "order"])
    if this.empty:
        return {}
    cp = this.iloc[-1]
    wtd_now = float(cp["wtd"])

    # Friday's final IS the week -- there is nothing left to estimate, and the
    # tab says so rather than printing a forecast of a number already known.
    done = bool(cp["weekday"] == 4 and cp["cut"] == "morning")

    prior = this.iloc[-2] if len(this) > 1 else None
    front = (float(prior["wtd"]) / wtd_now) if (prior is not None and wtd_now > 0) else None

    hist = cps[(cps["week"] < cur_week) & (cps["weekday"] == cp["weekday"]) &
               (cps["cut"] == cp["cut"])].copy()
    hist["final"] = hist["week"].map(published5)
    hist = hist.dropna(subset=["final"])
    hist = hist[hist["wtd"] > 0].copy()
    hist["late"] = hist["final"] - hist["wtd"]
    # A negative "late" is USDA revising the week down, which happens rarely and
    # is not a shape to project forward onto a cumulative count.
    hist = hist[hist["late"] >= 0]

    # MATURITY IS COMPUTED HERE RATHER THAN BELOW because the narrowing now
    # depends on it. It reads only published5 and cur_week, so moving it up
    # changes nothing it sees.
    prior_weeks = published5[published5.index < cur_week]
    recent = prior_weeks.tail(13)
    typical = float(recent.median()) if len(recent) else float("nan")
    maturity = (wtd_now / typical) if typical and typical == typical else float("nan")
    # WHAT RECENT WEEKS ACTUALLY DID, which is what the page shows instead of a
    # forecast while the week is too green to make one. Same 13 weeks the
    # typical comes from, so the range and the median describe one sample.
    recent_lo = float(recent.quantile(0.10)) if len(recent) else float("nan")
    recent_hi = float(recent.quantile(0.90)) if len(recent) else float("nan")

    # THE NARROWING IS GATED ON MATURITY, AND THAT IS NOT THE SAME AS SELECTING
    # ON IT. Picking analogues BY maturity was tried on 2026-10-02 and is worse
    # than picking by front-loading (12.2% against 7.8%); that stands, and the
    # pool below is still chosen on `front`. What changed on 2026-10-09 is WHEN
    # `front` is allowed to choose at all.
    #
    # `front` is the previous checkpoint's share of the current one. Early in
    # the week both terms are a few hundred head, so the ratio is noise -- and
    # selecting on noise cuts the pool from 20 analogue weeks to about 7.
    # Measured over 455 (week, checkpoint) pairs, on the rows the narrowing
    # actually fired below this line: 28.8% median absolute error narrowed
    # against 23.7% unnarrowed. Above it the narrowing is what makes the
    # forecast work at all -- 6.7% against 14.2% once the week is fully traded.
    #
    # Gating at the weak line costs nothing where the forecast earns its keep
    # and recovers about a point where it does not: overall 23.8% -> 22.9%,
    # below the line 26.1% -> 24.9%, at or above it unchanged at 13.6%, and
    # the p10-p90 band below the line holds 70% -> 75% of the time.
    pool, narrowed = hist, False
    if front is not None and not hist.empty and maturity >= FORECAST_WEAK_MATURITY:
        hist["front"] = [
            _front_of(cps, r.week, r.weekday, r.order, r.wtd)
            for r in hist.itertuples()
        ]
        near = hist[hist["front"].notna() & ((hist["front"] - front).abs() <= 0.10)]
        if len(near) >= 5:
            pool, narrowed = near, True

    # Newest first, then truncate: the cap must drop the OLDEST weeks, so the
    # surviving set is the same one any later replay would choose. Sorting the
    # other way would make the pool depend on the fetch window again, which is
    # the whole thing FORECAST_MAX_ANALOGUES exists to stop.
    if len(pool) > FORECAST_MAX_ANALOGUES:
        pool = pool.sort_values("week").tail(FORECAST_MAX_ANALOGUES)

    # HOW FAR INTO THE WEEK WE ARE STANDING IS THE ACCURACY, and it is worth
    # saying out loud rather than printing one number with one error bar.
    # Backtested over 52 Friday-1:30 checkpoints, split into quartiles by how
    # much had already traded: the busiest quartile lands within a median 3%
    # and its p10-p90 band holds the answer 92% of the time; the quietest
    # quartile is a median 36% out and its band holds 38%. Same method, same
    # band, utterly different thing to hand someone.
    #
    # Maturity, not raw head, because a 45,000-head week in March is a full
    # week and in August is half of one. It is computed above, where the
    # narrowing needs it; this is only where it becomes a label.
    # A checkpoint with too little history behind it is its own state, not a
    # weak forecast. It outranks the maturity grades: a mature week read off
    # three analogue weeks is still not a call.
    #
    # ON `hist`, NOT ON `pool` -- see FORECAST_MIN_ANALOGUES. `pool` is `hist`
    # after the front-loading narrowing, so gating on it conflates "there is
    # no history here" with "this week has an unusual shape", and only the
    # first is what the evidence for the threshold describes. The second
    # backtests at 12.3% median absolute error, twice as good as anything the
    # page shows in its place, and refusing it cost a call on 2026-10-09.
    thin_pool = (not done) and len(hist) < FORECAST_MIN_ANALOGUES
    if done:
        grade = "final"
    elif thin_pool:
        grade = "thin"
    elif maturity != maturity:
        grade = "unknown"
    elif maturity >= 0.85:
        grade = "firm"
    elif maturity >= FORECAST_WEAK_MATURITY:
        grade = "provisional"
    else:
        grade = "weak"

    # TOO GREEN TO FORECAST, AND THE PAGE STOPS PRINTING ONE. Measured over
    # 338 sub-0.50 (week, checkpoint) pairs on the live feed:
    #
    #   * the central is NOT a floor. The actual lands at or above it on 50%
    #     of checkpoints -- 50% / 50% / 48% across 0-5%, 5-20% and 20-50%
    #     maturity, a coin flip at every level of greenness. The page used to
    #     say "treat the number as a floor, not a forecast"; that was false.
    #   * it does not beat ignoring the week. Closer than the recent-weeks
    #     median on 153 of 340, 45% against a coin flip's 50%.
    #   * and the band does not rescue it. p10-p90 covers 75% at a median
    #     width of 86% OF THE WEEK, against the recent-weeks band's 67% at
    #     64% -- wider, and less coverage per unit of width.
    #
    # So below the weak line there is no honest sentence to put under a
    # number, and the page prints the confirmed count and what recent weeks
    # did instead. It costs little: 77% of weeks clear 0.50 before Friday's
    # final, and the ones that do not are the ones a forecast could not have
    # helped with. Above the line nothing changes -- 13.6% median absolute
    # error, beating the naive alternative on 56% of checkpoints.
    too_green = (not done) and (maturity != maturity
                                or maturity < FORECAST_WEAK_MATURITY)
    # The page asks ONE question -- is there a call to print? -- and the two
    # reasons answer it the same way while needing different words.
    no_call = too_green or thin_pool

    base = {"wtd": wtd_now, "checkpoint": cp, "done": done, "front": front,
            "narrowed": narrowed, "week": cur_week, "maturity": maturity,
            "typical": typical, "grade": grade, "too_green": too_green,
            "thin_pool": thin_pool, "no_call": no_call,
            # The DEPTH BEHIND THE CHECKPOINT, which is what thin_pool now
            # tests and what the no-call sentence has always claimed to be
            # quoting. `n` below is the pool the call was actually built from
            # and is a different number whenever narrowing fires.
            "n_hist": int(len(hist)),
            "recent_lo": recent_lo, "recent_hi": recent_hi}
    if pool.empty or done:
        return {**base, "n": int(len(pool)), "central": wtd_now,
                "low": wtd_now, "high": wtd_now, "late_median": 0.0}

    late = pool["late"]
    return {**base, "n": int(len(pool)),
            "central": wtd_now + float(late.median()),
            "low": wtd_now + float(late.quantile(0.10)),
            "high": wtd_now + float(late.quantile(0.90)),
            "late_median": float(late.median())}


def forecast_national(f5: dict, published5: pd.Series, national: pd.Series) -> dict:
    """
    Carry a 5-Area figure across to the national print USDA publishes the same
    morning, using the recent gap between the two.

    THE GAP IS TAKEN ADDITIVELY, NOT AS A RATIO, and over a short trailing
    window -- see FORECAST_GAP_WEEKS for the backtest behind both choices. The
    gap is negotiated trade in states outside the five areas, plus (right now)
    the Kansas and TX/OK/NM trade USDA is withholding regionally while still
    counting it nationally. Neither part scales with the 5-Area number, which
    is why a ratio drifts whenever the 5-Area total is unusually high or low.
    """
    if not f5 or published5.empty or national.empty:
        return {}
    pair = pd.DataFrame({"h5": published5, "nat": national}).dropna().sort_index()
    if pair.empty:
        return {}
    pair["gap"] = pair["nat"] - pair["h5"]
    recent = pair.tail(FORECAST_GAP_WEEKS)["gap"]
    band = pair.tail(FORECAST_BAND_WEEKS)["gap"]
    if recent.empty:
        return {}
    gap = float(recent.median())
    # What recent national weeks actually printed, for the state where the
    # 5-Area half is too green to forecast and this half therefore has nothing
    # to carry across. Same 13-week window the 5-Area recent range uses.
    nat_recent = pair.tail(13)["nat"]
    return {"central": f5["central"] + gap,
            "low": f5["low"] + float(band.min()),
            "high": f5["high"] + float(band.max()),
            "gap": gap, "gap_lo": float(band.min()), "gap_hi": float(band.max()),
            "recent_lo": float(nat_recent.quantile(0.10)),
            "recent_hi": float(nat_recent.quantile(0.90)),
            "recent_mid": float(nat_recent.median()),
            "n": int(len(recent)), "pair": pair}


def daily_combined(df: pd.DataFrame) -> pd.DataFrame:
    """
    Head-count-weighted Steer+Heifer combine per trading day / region / cut /
    basis -- the same combine the weekly tab does, for the same reason: USDA
    publishes two classes and the page quotes one number.

    A row with a price but no head count cannot be weighted, so it is dropped
    rather than counted as zero head, which would silently delete a real print.
    """
    if df.empty:
        return df
    d = df.dropna(subset=["head", "price"]).copy()
    if d.empty:
        return pd.DataFrame()

    key = ["trade_date", "region", "cut", "basis"]
    d["wp"] = d["head"] * d["price"]
    g = d.groupby(key, as_index=False).agg(head=("head", "sum"), wp=("wp", "sum"))
    g = g[g["head"] > 0].copy()
    if g.empty:
        return pd.DataFrame()
    g["price"] = g["wp"] / g["head"]
    g = g.drop(columns="wp")

    # Average weight is head-weighted as well, over only the rows that carry
    # one. A plain mean of the Steer and Heifer figures would weigh a 50-head
    # heifer lot the same as a 3,000-head steer lot, and USDA does not always
    # publish a weight alongside a price -- those rows must drop out of the
    # divisor too, not be counted as head with no weight.
    w = d.dropna(subset=["weight"]).copy()
    if w.empty:
        g["weight"] = float("nan")
        return g
    w["ww"] = w["head"] * w["weight"]
    wg = w.groupby(key, as_index=False).agg(hw=("head", "sum"), ww=("ww", "sum"))
    wg = wg[wg["hw"] > 0].copy()
    wg["weight"] = wg["ww"] / wg["hw"]
    return g.merge(wg[key + ["weight"]], on=key, how="left")


def daily_price_state(priced_rows, published_rows, suppressed=None,
                      blank_run=0):
    """
    Which of five things a region's price tile is saying on one trading day.

    Returns (state, row): "priced" and the print to headline, or one of
    "withheld", "undefined", "unpublished", "unknown" and None.

    `priced_rows` is the region's daily_combined() rows for the day -- averages
    only, the unpriced ones already dropped. `published_rows` is its raw
    fetch_daily_cash() rows, which KEEP the unpriced ones, and asking both is
    the only way to tell a file USDA never published from one it published
    blank. Reading the combined frame alone collapses those two into a single
    "Undefined", which is what this exists to stop.

    THE PRINT TO HEADLINE IS LIVE FOB IF IT TRADED, ELSE DRESSED; final cut
    preferred over the 1:30 pm cut.

    IT MUST FALL BACK TO DRESSED. Some days trade dressed only -- Tuesday
    09/22/2026 was one, its entire national print being Nebraska 2,349 steers
    and 550 heifers at 350.00 dressed with no live FOB anywhere. Headlining
    Live FOB alone put "Undefined" on all four tiles under that day's own
    heading, which reads as "nothing traded" when nearly 2,900 head did. The
    tile names the basis for that reason: on a mixed day the four tiles are not
    all the same quote.

    "UNDEFINED" IS USDA'S OWN MARKET TEST AND STAYS. On a genuine quiet day it
    is the right word and the 09/22/2026 day above is the case it was written
    for. It is simply not what a WITHHELD region is doing: USDA has the trade,
    is publishing the file, and is holding the number back under LMR
    confidentiality. Calling that "no confirmed trade" says nobody traded in
    Texas since June, which is false.

    THE DISCRIMINATOR IS THE VOLUME FLAG, NOT A SECOND RUN DETECTOR ON PRICES.
    `suppressed` comes from weekly_to_date(); the two panels headline the same
    `last_trade`, so they line up by construction. Measured over
    2024-01-01..2026-10-02, a blank week-to-date volume NEVER coincides with a
    published price: 0 counterexamples in 2,833 region-trading-days, every
    region. So the flag can only ever fire on a day whose price is blank
    anyway, which makes reusing it strictly conservative -- it cannot overwrite
    a real print. The converse is common and must stay "undefined": 316 days
    carry a week-to-date volume with no price that day, because the region
    traded earlier in the week and was quiet on it.

    The threshold behind the flag transfers. Blank-PRICE runs over the same
    window end at 6 for an ordinary quiet stretch (TX/OK/NM; 4 elsewhere) and
    run 33, 36 and 63 where the region went dark, so SUPPRESSION_RUN_DAYS sits
    in that gap on this series as well as on the volume one.

    `suppressed` IS THREE-VALUED AND THE THIRD VALUE IS THE POINT. True is
    "the volume panel says this region is withheld", False is "it says it is
    not", and None is "there is no volume evidence either way" -- which is NOT
    the same as evidence of no withholding, and gets its own state.

    IT DEFAULTED TO FALSE AND THAT WAS WRONG. The reasoning was that falling
    back to USDA's own word is safe, because it cannot assert a withholding
    nothing established. Half of that holds: it does avoid a false WITHHELD.
    But "no confirmed trade" is itself a claim, and a false one about a market
    that traded -- the exact defect this function exists to remove. Falling
    back to the bug is not a safe fallback.

    It is reachable without an exception, which is the worst part.
    fetch_daily_volume reads each report's /Summary section and
    fetch_daily_cash its /Detail, two separate requests; _fetch_many's worker
    catches every exception per job and returns [], so a Summary outage with
    Detail healthy yields an empty volume frame, an empty `wtd`, `daily_err`
    still "" and no warning anywhere. Reproduced 2026-10-02 against this file:
    TX/OK/NM went from ("--", "withheld by USDA") to ("Undefined", "no
    confirmed trade") while the page reported itself healthy.

    The two sections do not otherwise disagree -- over 263 trading days to
    2026-10-02, weekly_to_date() returned {} on exactly none of the days that
    carried a price -- so an empty volume frame beside published prices is a
    feed failure rather than ordinary skew, and the page says so out loud.

    `blank_run` IS THE WAY OUT OF BEING BLIND, and it is a fallback rather
    than a replacement. When the volume flag exists it decides, because
    reusing it is what keeps this panel and the week-to-date panel agreeing by
    construction. When it does not exist -- and only then -- the price frame
    answers for itself: _price_blank_run_days() counts the same kind of run on
    the data this panel already has, so a /Summary outage no longer costs the
    page the distinction. The feeds are independent requests and one failing
    should not change what the other reports.

    The fallback stays conservative in the same direction as everything else
    here. A run short of SUPPRESSION_RUN_DAYS is not evidence of no
    withholding any more than a missing flag was, so it yields "unknown" and
    the tile says it does not know. Nothing reaches "withheld" without a run
    long enough to have earned it on one series or the other.
    """
    for basis in ("Live FOB", "Dressed Delivered"):
        b = priced_rows[priced_rows["basis"] == basis]
        for cut in ("morning", "afternoon"):
            hit = b[b["cut"] == cut]
            if not hit.empty:
                return "priced", hit.iloc[0]
    if published_rows is None or published_rows.empty:
        return "unpublished", None
    if suppressed is None:
        # No volume flag: let the price frame speak for itself, and fall back
        # to "unknown" when its own run is too short to settle it either.
        if blank_run >= SUPPRESSION_RUN_DAYS:
            return "withheld", None
        return "unknown", None
    return ("withheld" if suppressed else "undefined"), None


# ── Load Data ────────────────────────────────────────────────────────────────

with st.spinner("Loading full USDA cash cattle trade history…"):
    try:
        # One probe for the whole page; each fetch keys on only its own reports.
        _probe = publication_stamps()
        price_df = fetch_price_history(stamps_for(_probe, [CT150_ID]))
        vol_df = fetch_volume_history(stamps_for(_probe, [CT154_ID]))
        load_ok, err_msg = True, ""
    except Exception as e:
        _probe = PROBE_FAILED
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

last_price_date = price_df["report_date"].max() if not price_df.empty else None
last_vol_date = vol_df["report_date"].max() if not vol_df.empty else None

with c2:
    meta = []
    if last_price_date is not None:
        meta.append(f"LM_CT150: <b>{last_price_date.strftime('%b %d, %Y')}</b>")
    if last_vol_date is not None:
        meta.append(f"LM_CT154: <b>{last_vol_date.strftime('%b %d, %Y')}</b>")
    st.markdown('<div class="dash-header-meta">' + "<br>".join(meta) + '</div>', unsafe_allow_html=True)


# ── Tabs ─────────────────────────────────────────────────────────────────────────
# Weekly is the main page and displays first; Daily is the second view.
#
# NEITHER BRANCH CALLS st.stop(). st.stop() halts the WHOLE script, so a weekly
# LM_CT150 outage would blank the Daily tab too -- different reports, published
# on a different clock, perfectly healthy. Commit 19d2ee0 fixed this same trap
# on the COF Recap tab and CLAUDE.md records it. Dropping st.stop() also means
# the sidebar renders during an outage, so the "use Refresh now in the sidebar"
# that the warning offers is actually reachable -- it was not before.
#
# And the hidden-tab rule: a hidden tab is hidden, NOT skipped. The Daily block
# runs on every rerun whether or not anyone opens it, which is why its fetch is
# one cached range request per region rather than one per day.
# ── USDA WASDE steer price forecast ─────────────────────────────────────────
#
# THE ONE WASDE LINE THAT IS THIS PAGE'S OWN SERIES. WASDE's footnote defines
# its "Streers" price (USDA's spelling, left alone) as
# "5-Area, Direct, Total all grades" -- which is what LM_CT150 reports and
# what the tiles above chart. So this is not a related indicator placed
# nearby; it is USDA's forecast of the number the page already shows.
#
# It is also the only cattle figure WASDE carries. Searched the whole report
# on 2026-10-07: ZERO occurrences of feeder, cutout, cow, heifer, on feed or
# placement. Anyone asking why the feeder index page has no WASDE panel can
# stop looking -- there is nothing to put on it.
#
# QUARTERLY, AND CALENDAR YEARS. WASDE's grain tables are split marketing
# years; the animal-products tables are January to December, like the meats
# supply-and-use table the US Beef Trade page reads.

@st.cache_data(ttl=21600, persist="disk", show_spinner=False)
def fetch_wasde_steer(schema: int = wasde.SCHEMA) -> dict:
    """
    USDA's quarterly 5-Area steer price forecast, as a plain dict.

    THE ARITHMETIC IS wasde.summary(), SHARED. Three pages now show a WASDE
    figure, and each computing its own revision and year-on-year is how two
    of them end up a decimal apart with both defensible -- the
    letter-versus-dashboard failure CLAUDE.md records twice.

    Flattened because st.cache_data pickles what it stores and a cached
    dataclass goes stale against its own class the moment the module is
    edited. `schema` keys the cache, and BOTH halves matter: no leading underscore (Streamlit drops underscore-prefixed arguments from the key) and the CALLER must pass it (a default is never hashed). See `leverage.SCHEMA`.
    """
    return wasde.summary(wasde.load_quarterly_prices(), "steer")


def wasde_steer_panel():
    """USDA's forecast for the very series this tab charts."""
    try:
        w = fetch_wasde_steer(wasde.SCHEMA)
    except Exception as exc:  # noqa: BLE001
        st.caption(f"WASDE steer price forecast unavailable — {exc}")
        return
    if not w or w.get("value") is None:
        return

    year = w["year"]

    def _d(value, percent, suffix, base=None, base_label="",
           digits=2, money=True):
        # THE LEVEL THE MOVE IS MEASURED FROM, printed under it. A tile reading
        # "▼ $8.00 · 3.3% vs last month" over $237.35 does not say what USDA
        # forecast last month -- the reader adds 8.00 back in their head, and
        # on the year-on-year tile adds 12.98 to a figure that is not even on
        # the tile, since its value is a percentage. Same defect the beef
        # cutout's Month/Year tiles were corrected for on 2026-10-07: a move
        # without its base is half a number.
        _s = ""
        if base is not None:
            _s = (f'<div class="tile-sub">{base_label} '
                  + ("$" if money else "") + f'{base:,.{digits}f}</div>')
        if value is None and percent is None:
            return '<div class="tile-delta-neu">&mdash;</div>' + _s
        if value == 0 or (value is None and percent == 0):
            return f'<div class="tile-delta-neu">unchanged{suffix}</div>' + _s
        ref = value if value is not None else percent
        arrow = "▲" if ref > 0 else "▼"
        bits = []
        if value is not None:
            bits.append(("$" if money else "") + f"{abs(value):,.{digits}f}")
        if percent is not None:
            bits.append(f"{abs(percent):,.1f}%")
        # NO PARENTHESES: in USDA's own reports they mean negative. See the
        # headline rule in CLAUDE.md and letter/sterling.py.
        return (f'<div class="tile-delta-neu">{arrow} '
                f'{" · ".join(bits)}{suffix}</div>' + _s)

    st.markdown(
        '<div class="sec-header">USDA WASDE expectation &mdash; '
        '5-Area steer price</div>', unsafe_allow_html=True)
    st.caption(
        f"USDA's projection of what the 5-Area Direct steer price will "
        f"average over the **{year} calendar year**, updated every WASDE. "
        f"WASDE's own footnote defines this series as "
        f"*“{wasde.STEER_PRICE_BASIS}”* — the same thing "
        f"LM_CT150 reports, so it is directly comparable with the weekly "
        f"averages on the first tab. Report: **{w['report_month']}**.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(tile(
            f"USDA {year} steer price forecast",
            f"${w['value']:,.2f}",
            _d(w["revision"], w["revision_pct"], " vs last month",
               base=w["prior"], base_label="last month")),
            unsafe_allow_html=True)
    with c2:
        st.markdown(tile(
            f"USDA {year} forecast vs {w['base_year']}",
            f"{w['yoy_pct']:+,.1f}%" if w["yoy_pct"] is not None else "—",
            _d(w["yoy_abs"], None, "/cwt",
               base=w["base"], base_label=f"{w['base_year']} averaged")),
            unsafe_allow_html=True)
    with c3:
        qs = [q for q in w["quarters"] if q["value"] is not None]
        left = [q for q in qs if q["projected"]]
        st.markdown(tile(
            f"{year} quarters still forecast",
            f"{len(left)} of {len(qs)}" if qs else "—",
            f'<div class="tile-delta-neu">'
            f'{", ".join(q["period"] for q in left) or "none"} to come'
            f'</div>' if qs else ""), unsafe_allow_html=True)
    with c4:
        nxt_pct, nxt_prior = None, None
        if w["next_revision"] is not None and w["next_value"] is not None:
            nxt_prior = w["next_value"] - w["next_revision"]
            nxt_pct = ((w["next_revision"] / nxt_prior * 100.0)
                       if nxt_prior else None)
        st.markdown(tile(
            f"USDA {w['next_year']} steer price forecast",
            f"${w['next_value']:,.2f}" if w["next_value"] is not None else "—",
            _d(w["next_revision"], nxt_pct, " vs last month",
               base=nxt_prior, base_label="last month")),
            unsafe_allow_html=True)

    qs = [q for q in w["quarters"] if q["value"] is not None]
    if qs:
        st.markdown(
            '<div class="sec-header" style="margin-top:10px;">'
            'By quarter</div>', unsafe_allow_html=True)
        cols = st.columns(len(qs))
        for col, q in zip(cols, qs):
            with col:
                name = f"Q{q['number']}" if q["number"] else q["period"]
                state = "proj" if q["projected"] else "actual"
                st.markdown(tile(f"{name} {year} · {state}",
                                 f"${q['value']:,.2f}"), unsafe_allow_html=True)

    audit = w["audit"]
    if audit.get("ok") is False:
        st.caption(
            f"⚠️ WASDE's annual figure ({audit['annual']:,.2f}) no "
            f"longer equals the {audit['how']} of its four quarters "
            f"({audit['expected']:,.2f}). The table layout has probably "
            f"changed and these figures should not be relied on until that "
            f"is checked.")


tab_weekly, tab_daily, tab_fcst, tab_lev, tab_wasde = st.tabs(
    ["Weekly Cash Trade Averages", "Daily Cash Trade", "Monday Print Forecast",
     "Packer Leverage", "WASDE Steer Price"])

with tab_weekly:
    if not load_ok:
        st.warning(
            "⏳ **USDA data temporarily unavailable** — the USDA server is not responding. "
            "This usually resolves in a few minutes. Use **Refresh now** in the sidebar to retry."
        )
        with st.expander("Technical details"):
            st.code(err_msg)
    elif price_df.empty and vol_df.empty:
        st.warning("No data returned from USDA APIs.")
    else:
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
                name="Live FOB (combined)", mode="lines+markers",
                line=dict(color=FOB_COLOR, width=2), marker=dict(size=4),
                hovertemplate="<b>Live FOB</b>: $%{y:.2f}<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=del_trend["report_date"], y=del_trend["combo_price"],
                name="Dressed Delivered (combined)", mode="lines+markers",
                line=dict(color=DEL_COLOR, width=2), marker=dict(size=4),
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
                name="Total Confirmed", mode="lines+markers",
                line=dict(color=CONF_COLOR, width=2), marker=dict(size=4),
                hovertemplate="<b>Total Confirmed</b>: %{y:,.0f} hd<extra></extra>",
            ))
            fig2.add_trace(go.Scatter(
                x=vol_df["report_date"], y=vol_df["total_head_count_1"],
                name="1-14 Day Delivery", mode="lines+markers",
                line=dict(color=D14_COLOR, width=2), marker=dict(size=4),
                hovertemplate="<b>1-14 Day</b>: %{y:,.0f} hd<extra></extra>",
            ))
            fig2.add_trace(go.Scatter(
                x=vol_df["report_date"], y=vol_df["total_head_count_2"],
                name="15-30 Day Delivery", mode="lines+markers",
                line=dict(color=D30_COLOR, width=2), marker=dict(size=4),
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


with tab_daily:
    st.markdown(
        '<div class="sec-header">Daily Negotiated Cash Trade &mdash; by region, Steer &amp; Heifer combined</div>',
        unsafe_allow_html=True,
    )

    _win = st.segmented_control(
        "History window", list(DAILY_WINDOWS), default=DAILY_WINDOW_DEFAULT,
        key="daily_window", label_visibility="collapsed")
    _days = DAILY_WINDOWS.get(_win or DAILY_WINDOW_DEFAULT,
                              DAILY_WINDOWS[DAILY_WINDOW_DEFAULT])

    _end_d = datetime.now().date()
    _start_d = _end_d - timedelta(days=_days)

    with st.spinner("Loading USDA daily regional cash trade…"):
        try:
            _daily_slugs = [s for cuts in DAILY_REGIONS.values() for s in cuts.values()]
            _stamps = stamps_for(_probe, _daily_slugs)
            daily_df = fetch_daily_cash(_start_d.strftime("%m/%d/%Y"),
                                        _end_d.strftime("%m/%d/%Y"), _stamps)
            daily_vol = fetch_daily_volume(_start_d.strftime("%m/%d/%Y"),
                                           _end_d.strftime("%m/%d/%Y"), _stamps)
            daily_err = ""
        except Exception as e:
            _stamps = PROBE_FAILED
            daily_df, daily_vol, daily_err = pd.DataFrame(), pd.DataFrame(), str(e)

    # Show the publication stamp rather than a "last refreshed" clock. Our
    # refresh time says nothing useful -- USDA's does, and it is the number that
    # tells you whether a quiet page is quiet because nothing traded or because
    # the feed stopped.
    _pub = daily_last_published(_stamps)
    if _pub:
        st.markdown(
            f'<div class="note" style="margin:-4px 0 10px;">USDA last published '
            f'these reports <b>{html.escape(_pub)}</b>. This page follows that stamp, '
            f'so it picks up a release as soon as one lands rather than on a timer.'
            f'</div>', unsafe_allow_html=True)
    elif _stamps == PROBE_FAILED:
        st.markdown(
            '<div class="note" style="margin:-4px 0 10px;">Could not reach USDA\'s '
            'report index, so the figures below are whatever was last cached and '
            'may be behind a release.</div>', unsafe_allow_html=True)

    dcombo = daily_combined(daily_df)

    if daily_err:
        st.warning(
            "⏳ **USDA daily data unavailable** — the USDA server is not responding. "
            "Use **Refresh now** in the sidebar to retry."
        )
        with st.expander("Technical details"):
            st.code(daily_err)
    elif daily_df.empty:
        st.info("USDA published no daily reports for these regions in this window.")
    else:
        # The newest day USDA PUBLISHED, which is not the same as the newest day
        # that PRICED -- see the unpriced-rows note in fetch_daily_cash. Taking
        # it from dcombo instead would skip every no-trade day and head this
        # section with an older date, which is what made a Wednesday page read
        # "Monday" with nothing saying Tuesday had been published and was quiet.
        last_trade = daily_df["trade_date"].max()
        day = (dcombo[dcombo["trade_date"] == last_trade] if not dcombo.empty
               else pd.DataFrame(columns=["region", "basis", "cut", "head", "price"]))

        _priced = dcombo["trade_date"].max() if not dcombo.empty else None
        _quiet = _priced is not None and _priced < last_trade

        # COMPUTED HERE, DISPLAYED TWICE, AND THE ORDER IS THE POINT. The price
        # tiles below need the per-region `suppressed` flag, and the week-to-date
        # panel further down needs the whole dict. Script order decides what is
        # available, not the order things appear on screen (see the tabs rule in
        # CLAUDE.md), so this has to sit above the first of the two. Calling
        # weekly_to_date() twice would work and is worse: the two panels would
        # be free to disagree about which regions are withheld, which is exactly
        # the class of bug where both numbers are defensible and nothing raises.
        wtd = weekly_to_date(daily_vol, last_trade)

        # THE VOLUME FEED CAN FAIL ON ITS OWN AND NOTHING ELSE NOTICES. Prices
        # come from each report's /Detail section and head counts from its
        # /Summary, two separate requests, and _fetch_many's worker swallows
        # every exception per job and returns []. So a Summary outage leaves
        # daily_err == "", passes the `elif daily_df.empty` gate because the
        # PRICE frame is fine, and silently drops the week-to-date panel at the
        # `if wtd:` below. The page looks healthy and is not, so it says so.
        #
        # THE TILES NO LONGER DEPEND ON THIS BEING READ. _price_blank_run_days
        # gives daily_price_state a fallback, so a region withheld through a
        # Summary outage is still named rather than reverting to USDA's
        # "Undefined". The warning survives that because the week-to-date
        # panel really is gone and the remaining evidence really is weaker --
        # a reader comparing head counts needs to know which, and the wording
        # below says so rather than claiming the distinction was lost.
        #
        # It does not cry wolf: over 263 trading days to 2026-10-02,
        # weekly_to_date() returned {} on none of the days that carried a
        # price, so the two sections move together and an empty one here is a
        # real failure rather than the feeds being a few hours apart.
        #
        # "Refresh now" is the right advice and was checked rather than
        # assumed: both fetches are @st.cache_data(persist="disk") keyed on
        # the publication stamps, so the empty frame a failed fetch returns is
        # CACHED and re-served on every rerun until USDA republishes. The
        # sidebar button calls st.cache_data.clear(), which drops persisted
        # entries too, so it genuinely retries rather than redrawing the same
        # cached failure.
        if not wtd:
            st.warning(
                "⚠️ **USDA's volume reports did not load.** Head counts and prices "
                "come from different sections of the same reports and only the price "
                "half returned, so the week-to-date panel is missing below. Which "
                "regions USDA is **withholding** is being read from each region's price "
                "history instead — less direct than the head counts, and a tile reading "
                "*no volume data* is one the price history could not settle either. "
                "Use **Refresh now** in the sidebar to retry."
            )

        st.markdown(
            f'<div class="sec-header" style="border-left-color:{FOB_COLOR};margin-top:6px;">'
            f'Latest trading day &mdash; {last_trade.strftime("%A, %b %d, %Y")} '
            f'($/cwt)</div>',
            unsafe_allow_html=True)

        if _quiet:
            # "No trade in any region" is a claim about EVERY region, so it has
            # to exclude the ones USDA is withholding. On a day where the
            # reporting regions are quiet and the others are suppressed, the old
            # wording asserted a silent Texas that is in fact trading.
            #
            # All four withheld gets its own sentence rather than a subtraction:
            # the region list would be empty and the sentence would read "no
            # confirmed negotiated trade in ." It is reachable -- _quiet means
            # nothing priced, which is exactly what four withheld regions look
            # like -- so it is written out rather than guarded against.
            _held_q = [r for r in DAILY_REGIONS
                       if (wtd.get(r) or {}).get("suppressed")] if wtd else []
            _open_q = [r for r in DAILY_REGIONS if r not in _held_q]
            _last_p = f'The last day that priced was <b>{_priced.strftime("%A, %b %d, %Y")}</b>.'
            if not _held_q:
                _msg = f'USDA published this day with no confirmed negotiated trade in any region. {_last_p}'
            elif not _open_q:
                _msg = (f'USDA is withholding every region for confidentiality on this day, so '
                        f'there is no published price anywhere. {_last_p}')
            else:
                _msg = (f'USDA published this day with no confirmed negotiated trade in '
                        f'{and_list(_open_q)}. It is withholding {and_list(_held_q)} for '
                        f'confidentiality, so '
                        f'{"those regions are" if len(_held_q) > 1 else "that region is"} '
                        f'not part of that statement. {_last_p}')
            st.markdown(
                f'<div class="note" style="margin:-6px 0 12px;">{_msg}</div>',
                unsafe_allow_html=True)

        # One tile per region: the final print where USDA has closed the day
        # out, otherwise the 1:30 pm cut, labelled so the two are never
        # confused. The decision is daily_price_state() at module level, where
        # a test can reach it -- this block only renders what it returns.
        #
        # THREE WAYS TO HAVE NO PRICE, AND THEY ARE DIFFERENT NEWS. "Undefined"
        # is USDA's own market test and is right on a quiet day; it is wrong for
        # a region whose trade USDA is withholding, which is what Kansas and
        # TX/OK/NM have been doing since 08/14 and 06/26/2026. The captions stay
        # short because .tile-delta-neu is nowrap and four tiles share the row;
        # the reason goes in the footnote, which has space for it.
        _PRICE_BLANK = {
            "withheld":    ("—", "withheld by USDA"),
            "undefined":   ("Undefined", "no confirmed trade"),
            "unpublished": ("—", "not published"),
            # "not published" is USDA having published nothing for the region;
            # this is us having lost the feed that would say WHY the price is
            # blank. Different causes, and the reader can act on this one by
            # coming back later, so it does not fold into the one above --
            # folding them would collapse two states into one, which is the
            # error being fixed here one line up.
            "unknown":     ("—", "no volume data"),
        }
        # RESOLVED ONCE, READ BY THE TILES AND BY THE TABLE UNDER THEM. Same
        # reason weekly_to_date() is hoisted above both: two callers deciding
        # separately are two callers free to disagree, and a table that said
        # "no confirmed trade" beside a tile saying "withheld by USDA" would be
        # the exact defect this page is being fixed for, one row lower.
        _states = {}
        for region in DAILY_REGIONS:
            _entry = wtd.get(region) if wtd else None
            _states[region] = daily_price_state(
                day[day["region"] == region],
                daily_df[(daily_df["trade_date"] == last_trade)
                         & (daily_df["region"] == region)],
                # None, not False: no volume row for this region is no
                # evidence either way, and False would assert the opposite.
                suppressed=(_entry["suppressed"] if _entry else None),
                # Computed here and passed in, so daily_price_state keeps its
                # single call site and stays a pure decision a test can reach.
                # It costs nothing when the flag exists -- the state resolves
                # on `suppressed` before `blank_run` is ever consulted.
                blank_run=_price_blank_run_days(daily_df, region, last_trade),
            )

        cols = st.columns(len(DAILY_REGIONS))
        for col, region in zip(cols, DAILY_REGIONS):
            state, row = _states[region]
            with col:
                if row is None:
                    _val, _why = _PRICE_BLANK[state]
                    st.markdown(
                        tile(region, _val,
                             f'<div class="tile-delta-neu">{_why}</div>',
                             "tile-neu"),
                        unsafe_allow_html=True)
                else:
                    basis_short = "Live FOB" if row["basis"] == "Live FOB" else "Dressed"
                    st.markdown(
                        tile(region, fmt_price(row["price"]),
                             f'<div class="tile-delta-neu">{fmt_hd(row["head"])} '
                             f'&middot; {basis_short}, {DAILY_CUT_LABEL[row["cut"]]}</div>',
                             "tile-fob" if row["basis"] == "Live FOB" else "tile-del"),
                        unsafe_allow_html=True)

        # ── Both cuts, side by side ──────────────────────────────────────────
        st.markdown(
            '<div class="sec-header">Both cuts of the same trading day</div>',
            unsafe_allow_html=True)

        # EVERY CELL IN A WITHHELD ROW IS A DASH, AND A DASH SAYS NOTHING. The
        # tiles above distinguish a quiet region from one USDA is withholding;
        # six identical dashes across this row put the reader straight back to
        # not knowing which. The reason goes in a column of its own rather than
        # into the price cells, which would repeat it four times and widen the
        # table for a sentence that is about the ROW.
        #
        # The column is always present, including on a day when no region is
        # blank. A table that changes shape day to day is harder to read at a
        # glance than one with an empty column, and this is a page people check
        # every morning.
        grid = []
        for region in DAILY_REGIONS:
            reg = day[day["region"] == region]
            entry = {"Region": region}
            for basis, short in (("Live FOB", "Live FOB"),
                                 ("Dressed Delivered", "Dressed")):
                for cut in ("afternoon", "morning"):
                    m = reg[(reg["basis"] == basis) & (reg["cut"] == cut)]
                    entry[f"{short} {DAILY_CUT_LABEL[cut]}"] = (
                        fmt_price(m.iloc[0]["price"]) if not m.empty else "—")
            # Head across BOTH bases, not Live FOB alone -- on a dressed-only
            # day (see daily_price_state) a live-only count reads "—" for a
            # region that actually traded thousands of head.
            fin = reg[reg["cut"] == "morning"]
            entry["Head (final)"] = (
                fmt_hd(fin["head"].sum()) if not fin.empty else "—")
            # Blank for a region that priced: the row speaks for itself, and
            # filling it with "published" would bury the two rows that matter.
            _state = _states[region][0]
            entry["USDA status"] = ("" if _state == "priced"
                                    else _PRICE_BLANK[_state][1])
            grid.append(entry)
        st.dataframe(pd.DataFrame(grid), width="stretch", hide_index=True)

        # ── Week to date ─────────────────────────────────────────────────────
        # `wtd` is built above the price tiles, which share its suppressed flag.
        if wtd:
            st.markdown(
                f'<div class="sec-header" style="border-left-color:{CONF_COLOR};">'
                f'Negotiated cash volume, week to date &mdash; through '
                f'{last_trade.strftime("%A, %b %d")}</div>',
                unsafe_allow_html=True)

            # The 5-Area total leads as a line rather than a fifth tile. Five
            # tiles across is one too many: at a narrow window each is about
            # 80px, which is where the region labels start breaking mid-word.
            # Four also keeps this row the same shape as the price row above.
            _tot = wtd.get("_total")
            if _tot is not None:
                _cmp = ""
                if _tot["week_ago"] is not None:
                    _d = _tot["head"] - _tot["week_ago"]
                    _arrow = "▲" if _d > 0 else ("▼" if _d < 0 else "")
                    _col = POS if _d > 0 else (NEG if _d < 0 else MUTED)
                    _cmp = (f' <span style="color:{_col};font-weight:600;">{_arrow} '
                            f'{abs(_d):,.0f} hd</span> against {_tot["week_ago"]:,.0f} hd '
                            f'at the same point last week')
                # Name what the total is actually made of while a region is
                # withheld. The figure is still USDA's -- their 5-Area drops a
                # withheld region too -- but "5-Area" invites the reader to
                # assume five regions are in it, and right now two are not.
                _held = ""
                if _tot["withheld"]:
                    _held = (f' USDA is withholding {and_list(_tot["withheld"])} for '
                             f'confidentiality and leaves '
                             f'{"them" if len(_tot["withheld"]) > 1 else "it"} out of its '
                             f'own 5-Area figure as well, so this is '
                             f'{and_list(_tot["counted"])}.')
                st.markdown(
                    f'<div style="font-size:0.95rem;color:{JPSI_DARK};margin:-4px 0 12px;">'
                    f'<b>5-Area total {_tot["head"]:,.0f} head</b>{_cmp}.{_held}</div>',
                    unsafe_allow_html=True)

            cols = st.columns(len(DAILY_REGIONS))
            for col, region in zip(cols, DAILY_REGIONS):
                entry = wtd.get(region)
                with col:
                    if entry is None:
                        st.markdown(
                            tile(region, "—",
                                 '<div class="tile-delta-neu">not published</div>',
                                 "tile-neu"),
                            unsafe_allow_html=True)
                    elif entry["head"] is None:
                        # USDA published the file and left the volume blank.
                        # "0 head" here is a number USDA never prints and reads
                        # as "nobody traded" -- see weekly_to_date. Only a
                        # sustained blank is called withheld; a short one is
                        # indistinguishable from a quiet day and says so.
                        #
                        # Both captions are kept short enough not to overflow
                        # the tile at a narrow window, which the nowrap in
                        # .tile-delta-neu makes a real constraint. The reason a
                        # region is withheld goes on the 5-Area line above and
                        # in the footnote below, which have room for it.
                        _why = ("withheld by USDA"
                                if entry["suppressed"] else "no volume published")
                        st.markdown(
                            tile(region, "—",
                                 f'<div class="tile-delta-neu">{_why}</div>',
                                 "tile-neu"),
                            unsafe_allow_html=True)
                    else:
                        st.markdown(
                            tile(region, fmt_hd(entry["head"]),
                                 hd_delta_html(entry["head"], entry["week_ago"]),
                                 "tile-d14"),
                            unsafe_allow_html=True)

            st.markdown(
                '<div class="note" style="margin-top:6px;">Cumulative negotiated cash head '
                'from Monday through the trading day above, against the running total at the '
                'same point last week &mdash; USDA&rsquo;s own week-to-date line, not a sum computed '
                'here. <b>This counts more cattle than the prices above.</b> The averages are '
                'Steer and Heifer on Live FOB and Dressed Delivered only; this is every class '
                'and all four selling bases, so it is the size of the week&rsquo;s trade rather than '
                'the head behind those quotes. The 5-Area figure is the four regions added up, '
                'which reproduces USDA&rsquo;s own 5-Area total exactly. '
                '<b>A region shown as withheld is absent from that total</b> &mdash; USDA '
                'publishes the report with the head count blank when too few buyers reported '
                'to disclose it, and drops it from its own 5-Area figure the same way, so the '
                'total is the regions named above it and not the whole 5-Area trade. That '
                'cattle is still counted in the national confirmed negotiated figure on the '
                'Weekly tab, which is why the two have diverged.</div>',
                unsafe_allow_html=True)

        # ── Daily trend ──────────────────────────────────────────────────────
        st.markdown(
            '<div class="sec-header">Daily Live FOB by region &mdash; final prints</div>',
            unsafe_allow_html=True)

        # A local axis dict rather than the weekly tab's AXIS: that one is built
        # inside the weekly branch, which does not run when LM_CT150 is down.
        DAXIS = dict(gridcolor=BORDER, linecolor=BORDER, showgrid=True,
                     tickfont=dict(color=MUTED, size=11),
                     title_font=dict(color=MUTED, size=11), zeroline=False)

        line = (dcombo[(dcombo["basis"] == "Live FOB") & (dcombo["cut"] == "morning")]
                if not dcombo.empty else dcombo)
        if line.empty:
            st.info("No final Live FOB prints in this window.")
        else:
            fig_d = go.Figure()
            for region in DAILY_REGIONS:
                s = line[line["region"] == region].sort_values("trade_date")
                if s.empty:
                    continue
                fig_d.add_trace(go.Scatter(
                    x=s["trade_date"], y=s["price"], name=region,
                    mode="lines+markers",
                    line=dict(color=DAILY_REGION_COLORS.get(region, MUTED), width=2),
                    marker=dict(size=4),
                    hovertemplate=f"<b>{region}</b>: $%{{y:.2f}}<extra></extra>"))
            fig_d.add_layout_image(dict(
                source=JSA_LOGO, xref="paper", yref="paper", x=0.5, y=0.5,
                sizex=0.5, sizey=0.5, xanchor="center", yanchor="middle",
                sizing="contain", opacity=WATERMARK_OPACITY, layer="below"))
            fig_d.update_layout(
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                font=dict(color=JPSI_DARK, size=11), hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1,
                            font=dict(color=JPSI_DARK, size=11),
                            bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=55, r=20, t=15, b=40),
                xaxis=dict(**DAXIS, title="", type="date"),
                yaxis=dict(**DAXIS, title="$/cwt", tickprefix="$"),
                height=400)
            st.plotly_chart(fig_d, width="stretch")

        # ── Detail ───────────────────────────────────────────────────────────
        with st.expander("\U0001f4cb  Daily detail — every print in the window, both cuts"):
            if dcombo.empty:
                st.info("USDA published in this window but nothing priced.")
            else:
                det = dcombo.copy()
                det["Trading Day"] = det["trade_date"].dt.strftime("%Y-%m-%d")
                det["Cut"] = det["cut"].map(DAILY_CUT_LABEL)
                det = det.rename(columns={"region": "Region", "basis": "Basis",
                                          "head": "Head", "weight": "Avg Weight",
                                          "price": "Wtd Avg Price"})
                det = det[["Trading Day", "Region", "Basis", "Cut",
                           "Head", "Avg Weight", "Wtd Avg Price"]]
                st.dataframe(
                    det.sort_values(["Trading Day", "Region"], ascending=[False, True]),
                    width="stretch", hide_index=True)

    st.markdown(
        '<div class="note" style="margin-top:10px;">'
        '<b>Two files a day, one trading day apart.</b> USDA publishes each region twice: an '
        'afternoon file (~2:55 pm CT) carrying that day\'s trade as of the 1:30 pm cut, and a '
        'morning file (median 11:17 CT) that finalises the <i>previous</i> business day. The morning '
        'file is dated the day it is published, so this page shifts it back one business day &mdash; '
        '&ldquo;Final&rdquo; and &ldquo;1:30 pm cut&rdquo; above are the same trading day, not the '
        'same file.<br><br>'
        '<b>Colorado is not shown.</b> USDA discontinued the Colorado daily reports &mdash; the '
        'afternoon file (LM_CT133) last published 27 Jun 2023 and the summary (LM_CT134) 5 Jul 2024, '
        'and the API has returned nothing for either since. Colorado is still inside the 5-Area '
        'weekly average on the Weekly tab.<br><br>'
        '<b>Week to date</b> is USDA&rsquo;s own cumulative negotiated cash head from Monday, read from each report&rsquo;s Summary section. It counts every class and all four selling bases, so it is a wider count than the Steer/Heifer Live-FOB-and-Dressed averages above and will not tie to them. The 5-Area figure is the four regions summed, which reproduces USDA&rsquo;s own 5-Area week-to-date exactly.<br><br>'
        '<b>&ldquo;Undefined&rdquo;</b> is USDA\'s own state when a region has too little confirmed '
        'trade to publish a market test &mdash; a real answer, not a failed fetch. Regions are '
        'routinely undefined early in the week.<br><br>'
        '<b>&ldquo;Withheld by USDA&rdquo; is not the same thing</b>, and the difference is the '
        'whole market. A withheld region traded; USDA is publishing the report with the price '
        'and the head count left blank because too few buyers reported to disclose them under '
        'LMR confidentiality. An undefined region is one USDA is telling you was quiet. The '
        'report itself cannot say which &mdash; the field is empty either way and USDA never '
        'prints a literal zero &mdash; so this page reads the length of the blank run. A '
        'few quiet days in a row is an ordinary stretch; a run reaching '
        f'{SUPPRESSION_RUN_DAYS} trading days is a region that has gone dark. '
        '<b>TX/OK/NM has published no daily price since 26 Jun 2026 and Kansas '
        'none since 14 Aug 2026.</b> That cattle is still counted in the national confirmed '
        'negotiated figure on the Weekly tab, which is why the two have diverged.<br><br>'
        'Negotiated cash only, Steer and Heifer combined head-count-weighted, &ldquo;Total all '
        'grades&rdquo;. Sources: <b>LM_CT117/118</b> (TX/OK/NM), <b>LM_CT120/121</b> (Kansas), '
        '<b>LM_CT123/124</b> (Nebraska), <b>LM_CT136/137</b> (Iowa/Minnesota) — prices from each report&rsquo;s Detail section, week-to-date head from its Summary. Cached until USDA republishes, checked every 5 minutes.'
        '</div>',
        unsafe_allow_html=True)


# ── Monday Print Forecast ────────────────────────────────────────────────────
# The third tab answers one question: what will USDA print on Monday for last
# week's negotiated volume? It gets there in two steps, and keeping them
# visibly separate is the point -- they fail differently and a reader needs to
# know which half is shaky.
#
#   week-to-date now  ->  5-Area weekly (LM_CT150)  ->  national (LM_CT154)
#
# THIS TAB ADDS NO WEEKLY REQUESTS. Both weekly series ride on fetches the page
# already makes: the 5-Area head count is a header field on the LM_CT150
# History call behind the price panel, and the national count is vol_df. Its
# one request set is the daily /Summary year below, which is cheap for the
# reason FORECAST_CAL_DAYS documents.
with tab_fcst:
    st.markdown(
        '<div class="sec-header">Monday Print Forecast &mdash; negotiated cash volume</div>',
        unsafe_allow_html=True)

    with st.spinner("Loading USDA daily history for the forecast…"):
        try:
            _f_slugs = [sl for cuts in DAILY_REGIONS.values() for sl in cuts.values()]
            _f_stamps = stamps_for(_probe, _f_slugs)
            _f_end = datetime.now().date()
            _f_start = _f_end - timedelta(days=FORECAST_CAL_DAYS)
            fcst_vol = fetch_daily_volume(_f_start.strftime("%m/%d/%Y"),
                                          _f_end.strftime("%m/%d/%Y"), _f_stamps)
            fcst_err = ""
        except Exception as e:
            fcst_vol, fcst_err = pd.DataFrame(), str(e)

    head5 = weekly_5area_head(price_df)
    headn = weekly_national_head(vol_df)
    f5 = forecast_5area(fcst_vol, head5) if not fcst_vol.empty else {}
    fn = forecast_national(f5, head5, headn) if f5 else {}

    if fcst_err:
        st.warning("⏳ **USDA daily data unavailable** — the forecast needs the daily "
                   "regional reports. Use **Refresh now** in the sidebar to retry.")
        with st.expander("Technical details"):
            st.code(fcst_err)
    elif not f5 or not fn:
        st.info("Not enough published history yet to build a forecast.")
    else:
        _cp = f5["checkpoint"]
        _dow = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][int(_cp["weekday"])]
        _cut = DAILY_CUT_LABEL[_cp["cut"]]
        _wk = pd.Timestamp(f5["week"])
        _print_day = (_wk + pd.Timedelta(days=7)).strftime("%A, %b %d")

        _last_wk_hdr = _wk - pd.Timedelta(days=7)
        _settled_hdr = (_wk in head5.index) and (_wk in headn.index)
        _wow5 = _wown = ""
        if _settled_hdr:
            _p5h, _pnh = head5.get(_last_wk_hdr), headn.get(_last_wk_hdr)
            _wow5 = (f'<b>{head5[_wk] - _p5h:+,.0f} hd</b> on the 5-Area '
                     if _p5h is not None and pd.notna(_p5h) else "")
            _wown = (f'<b>{headn[_wk] - _pnh:+,.0f} hd</b> nationally '
                     if _pnh is not None and pd.notna(_pnh) else "")
        st.markdown(
            f'<div class="note" style="margin:-4px 0 12px;">Trading week of '
            f'<b>{_wk.strftime("%b %d")}&ndash;{(_wk + pd.Timedelta(days=4)).strftime("%b %d, %Y")}</b>. '
            + (f'Both weekly reports are in. Against the '
               f'{_last_wk_hdr.strftime("%b %d")} week they are '
               f'{(_wow5 + "and " + _wown).strip()}.'
               if _settled_hdr else
               f'USDA last published the <b>{_dow} {_cut}</b> figure; the weekly reports '
               f'print <b>{_print_day}</b>.')
            + '</div>', unsafe_allow_html=True)

        # The board is built here rather than down beside the table because the
        # tiles need its newest row: once USDA prints, they stop forecasting
        # and start reporting. Same object feeds both, so they cannot disagree.
        board = scorecard.build_scorecard(
            fcst_vol, head5, headn, forecast_5area, forecast_national,
            CUT_ORDER, weeks=10)

        # ── headline numbers ────────────────────────────────────────────────
        # TWO STATES, AND THE SECOND ONE EXISTS BECAUSE THE FIRST LIED.
        #
        # Until USDA prints, these are a forecast and its inputs. AFTER it
        # prints they must become a scoreboard, because forecast_5area reports
        # done=True once Friday's final lands and returns the week-to-date
        # unchanged -- so a "forecast print" tile in that state shows the
        # ACTUAL, twice, and the call we actually made is gone from the page.
        # On 2026-10-05 that read "5-Area week to date 60,063 / 5-Area forecast
        # print 60,063" while the scorecard table six inches below reported we
        # had called 61,167. Both were true; together they were a bug. Same
        # class as the letter-vs-dashboard FCI disagreement in CLAUDE.md, and
        # it is caught the same way -- by putting one number in front of
        # another and seeing them differ.
        _scored = None
        if not board.empty and pd.Timestamp(board.iloc[0]["week"]) == _wk \
                and not board.iloc[0].get("pending", False):
            _scored = board.iloc[0]

        c1, c2, c3, c4 = st.columns(4)
        _last_wk = _wk - pd.Timedelta(days=7)
        _prev5 = head5.get(_last_wk)
        _prevn = headn.get(_last_wk)

        if _scored is not None:
            # The call is the REPLAYED one from the last checkpoint that still
            # had something to predict, which is what the scorecard scores and
            # what we actually said. Verified 2026-10-05: replaying the 9/28
            # week three days later reproduced 61,167 and 81,723 to the head.
            _s_dow = ["Monday", "Tuesday", "Wednesday", "Thursday",
                      "Friday"][int(_scored["cp_weekday"])] \
                if "cp_weekday" in _scored else _dow
            with c1:
                st.markdown(tile("5-Area &mdash; we called",
                                 fmt_hd(_scored["f5"]),
                                 f'<div class="tile-delta-neu">before the print</div>',
                                 "tile-d14"), unsafe_allow_html=True)
            with c2:
                st.markdown(tile("5-Area &mdash; USDA printed",
                                 fmt_hd(_scored["a5"]),
                                 hd_delta_html(_scored["a5"], _scored["f5"]),
                                 "tile-conf"), unsafe_allow_html=True)
            with c3:
                st.markdown(tile("National &mdash; we called",
                                 fmt_hd(_scored["fn"]),
                                 f'<div class="tile-delta-neu">before the print</div>',
                                 "tile-del"), unsafe_allow_html=True)
            with c4:
                st.markdown(tile("National &mdash; USDA printed",
                                 fmt_hd(_scored["an"]),
                                 hd_delta_html(_scored["an"], _scored["fn"]),
                                 "tile-neu"), unsafe_allow_html=True)
        else:
            with c1:
                st.markdown(tile("5-Area &mdash; week to date",
                                 fmt_hd(f5["wtd"]),
                                 f'<div class="tile-delta-neu">{_dow} {_cut}, published</div>',
                                 "tile-conf"), unsafe_allow_html=True)
            # TOO GREEN: WHAT RECENT WEEKS DID, NOT WHAT THIS ONE WILL DO.
            # See forecast_5area's `too_green` for the measurement. The range
            # is labelled as history because that is what it is -- the page
            # is not allowed to imply it is a call on this week.
            with c2:
                if f5["no_call"]:
                    st.markdown(tile("5-Area &mdash; recent weeks",
                                     f'{f5["recent_lo"]:,.0f}&ndash;'
                                     f'{f5["recent_hi"]:,.0f}',
                                     f'<div class="tile-delta-neu">hd, last 13 weeks '
                                     f'&middot; median {f5["typical"]:,.0f}</div>',
                                     "tile-neu"), unsafe_allow_html=True)
                else:
                    st.markdown(tile("5-Area &mdash; forecast print",
                                     fmt_hd(f5["central"]),
                                     hd_delta_html(f5["central"], _prev5),
                                     "tile-d14"), unsafe_allow_html=True)
            with c3:
                if f5["no_call"]:
                    st.markdown(tile("National &mdash; recent weeks",
                                     f'{fn["recent_lo"]:,.0f}&ndash;'
                                     f'{fn["recent_hi"]:,.0f}',
                                     f'<div class="tile-delta-neu">hd, last 13 weeks '
                                     f'&middot; median {fn["recent_mid"]:,.0f}</div>',
                                     "tile-neu"), unsafe_allow_html=True)
                else:
                    st.markdown(tile("National &mdash; forecast print",
                                     fmt_hd(fn["central"]),
                                     hd_delta_html(fn["central"], _prevn),
                                     "tile-del"), unsafe_allow_html=True)
            with c4:
                st.markdown(tile("National &mdash; last week printed",
                                 fmt_hd(_prevn),
                                 f'<div class="tile-delta-neu">'
                                 f'{_last_wk.strftime("%b %d")} week, actual</div>',
                                 "tile-neu"), unsafe_allow_html=True)

        _GRADE = {
            "final": (POS, "The week is closed", "Friday&rsquo;s final file has landed, so the "
                      "5-Area figure below is not an estimate &mdash; it is the number."),
            "firm": (POS, "Firm", "The week has traded about as much as a normal week already, "
                     "which is the state this method is most reliable in: backtested over 52 "
                     "weeks, the busiest quarter of them land within a median 3% and the band "
                     "holds the answer 92% of the time."),
            "provisional": (D30_COLOR, "Provisional", "Roughly half to four-fifths of a normal "
                            "week is in. Comparable weeks land within a median 7&ndash;11%."),
            # NO FORECAST IS PRINTED IN THIS STATE, so this text says why
            # rather than hedging a number. It used to end "treat the number
            # as a floor, not a forecast" -- measured over 338 sub-0.50
            # checkpoints the actual lands at or above the central on 50% of
            # them, so it was never a floor.
            "weak": (NEG, "Too early to forecast", "Only a small fraction of a normal week "
                     "is on the board and most of the trade is still to come. At this point "
                     "an estimate is no closer than simply quoting recent weeks, and lands "
                     "above the eventual print as often as below it &mdash; so the tiles show "
                     "what recent weeks actually did instead of a call on this one."),
            "thin": (NEG, "Not enough history to forecast from", "This weekday and cut has "
                     "too few past weeks behind it to estimate the rest of the week. "
                     "Backtested, calls built on three analogue weeks or fewer ran a median "
                     "81% high and never once landed at or below the eventual print, so no "
                     "call is shown &mdash; the tiles give what recent weeks did instead."),
            "unknown": (MUTED, "Unrated", "Not enough published weekly history to judge how far "
                        "through the week this is."),
        }
        _gc, _gl, _gt = _GRADE[f5["grade"]]
        _mat = f5.get("maturity")
        _mat_s = (f"{_mat:.0%} of a typical recent week ({fmt_hd(f5['typical'])})"
                  if _mat == _mat else "&mdash;")
        st.markdown(
            f'<div style="border-left:3px solid {_gc};background:#fafbfc;padding:8px 12px;'
            f'margin:4px 0 14px;font-size:0.8rem;line-height:1.55;color:{JPSI_DARK};">'
            f'<b style="color:{_gc};">Confidence: {_gl}.</b> {_gt}<br>'
            f'<span style="color:{MUTED};">Week to date is {_mat_s}.</span></div>',
            unsafe_allow_html=True)

        # ── step 1 ──────────────────────────────────────────────────────────
        st.markdown(
            f'<div class="sec-header" style="border-left-color:{CONF_COLOR};">'
            f'Step 1 &mdash; finishing the 5-Area week (LM_CT150)</div>',
            unsafe_allow_html=True)
        _front_s = f"{f5['front']:.0%}" if f5.get("front") is not None else "&mdash;"
        if _scored is not None:
            _m5 = _scored["a5"] - _scored["f5"]
            _in5 = bool(_scored["in5"])
            st.markdown(
                f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
                f'From <b>{_scored["wtd"]:,.0f} hd</b> on the board we called '
                f'<b>{_scored["f5"]:,.0f} hd</b>. USDA printed '
                f'<b>{_scored["a5"]:,.0f} hd</b> &mdash; '
                f'<b style="color:{POS if _in5 else NEG};">{abs(_m5):,.0f} hd '
                f'{"below" if _m5 < 0 else "above"} the call '
                f'({abs(_m5) / _scored["a5"]:.1%})</b>, '
                f'{"inside" if _in5 else "<b>outside</b>"} the '
                f'{_scored["f5_lo"]:,.0f}&ndash;{_scored["f5_hi"]:,.0f} hd range we gave.'
                f'</div>', unsafe_allow_html=True)
        elif f5["no_call"]:
            # TWO REASONS, ONE OUTCOME. Too green is about this week; a thin
            # pool is about the history behind this checkpoint. Printing the
            # maturity sentence for a thin pool would name the wrong cause.
            _why = (f'<b>{f5["maturity"]:.0%}</b> of a typical recent week, too little to '
                    f'estimate the rest from'
                    if f5["too_green"] else
                    f'but only <b>{f5["n_hist"]}</b> past weeks stand at this same point '
                    f'in the week, too few to estimate the rest from')
            st.markdown(
                f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
                f'<b>{f5["wtd"]:,.0f} hd</b> confirmed through the {_dow} {_cut.lower()} '
                f'&mdash; {_why}. The last 13 weeks printed '
                f'<b>{f5["recent_lo"]:,.0f}&ndash;{f5["recent_hi"]:,.0f} hd</b>, median '
                f'<b>{f5["typical"]:,.0f} hd</b>.</div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
                f'<b>{f5["wtd"]:,.0f} hd</b> confirmed through the {_dow} {_cut.lower()}, '
                f'plus an estimated <b>{f5["late_median"]:,.0f} hd</b> still to be reported '
                f'&rarr; <b>{f5["central"]:,.0f} hd</b>, with a likely range of '
                f'<b>{f5["low"]:,.0f}&ndash;{f5["high"]:,.0f} hd</b>.</div>',
                unsafe_allow_html=True)
        st.markdown(
            f'<div class="note" style="margin-bottom:14px;">The week-to-date is USDA&rsquo;s '
            f'own cumulative count, and the four daily regions summed at Friday&rsquo;s final '
            f'reproduce USDA&rsquo;s published 5-Area weekly figure <b>exactly</b> &mdash; checked '
            f'on every week the daily window covers. '
            + ('So the call above was the week-to-date plus the late trade seen in '
               'comparable past weeks at the same point.'
               if _scored is not None else
               'So the only unknown is the trade still to come &mdash; which this early is '
               'most of the week, and is why no estimate of it is shown.'
               if f5["no_call"] else
               f'So the only unknown is trade reported after the last cut, estimated from '
               f'the <b>{f5["n"]}</b> past weeks standing at the same point'
               + (f' with similar front-loading (the previous cut held {_front_s} of the '
                  f'current one)' if f5.get("narrowed") else ' in the week')
               + '.')
            + '</div>', unsafe_allow_html=True)

        # ── step 2 ──────────────────────────────────────────────────────────
        st.markdown(
            f'<div class="sec-header" style="border-left-color:{DEL_COLOR};">'
            f'Step 2 &mdash; 5-Area across to national (LM_CT154)</div>',
            unsafe_allow_html=True)
        if _scored is not None:
            # THE REALISED GAP IS THE WHOLE STORY OF STEP 2 and is worth
            # printing rather than leaving the reader to subtract. It is the
            # only part of the chain with no running total to watch, so when
            # the national call misses this is always why.
            _gap_used = _scored["fn"] - _scored["f5"]
            _gap_real = _scored["an"] - _scored["a5"]
            _mn = _scored["an"] - _scored["fn"]
            _inn = bool(_scored["inn"])
            st.markdown(
                f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
                f'We added a gap of <b>{_gap_used:,.0f} hd</b> to get '
                f'<b>{_scored["fn"]:,.0f} hd</b>. USDA printed '
                f'<b>{_scored["an"]:,.0f} hd</b> &mdash; '
                f'<b style="color:{POS if _inn else NEG};">{abs(_mn):,.0f} hd '
                f'{"below" if _mn < 0 else "above"} the call '
                f'({abs(_mn) / _scored["an"]:.1%})</b>, '
                f'{"inside" if _inn else "<b>outside</b>"} the range we gave. '
                f'The gap actually came in at <b>{_gap_real:,.0f} hd</b>.</div>',
                unsafe_allow_html=True)
        elif f5["no_call"]:
            # Nothing to carry across: this step starts from the 5-Area call,
            # and there isn't one. The gap is still worth printing because it
            # is what separates the two figures whenever they are quoted.
            st.markdown(
                f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
                f'No 5-Area call to carry across yet. The recent gap between the two is '
                f'<b>{fn["gap"]:,.0f} hd</b>, and the last 13 national weeks printed '
                f'<b>{fn["recent_lo"]:,.0f}&ndash;{fn["recent_hi"]:,.0f} hd</b>, median '
                f'<b>{fn["recent_mid"]:,.0f} hd</b>.</div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
                f'<b>{f5["central"]:,.0f} hd</b> plus the recent 5-Area-to-national gap of '
                f'<b>{fn["gap"]:,.0f} hd</b> &rarr; <b>{fn["central"]:,.0f} hd</b>, '
                f'range <b>{fn["low"]:,.0f}&ndash;{fn["high"]:,.0f} hd</b>.</div>',
                unsafe_allow_html=True)
        st.markdown(
            f'<div class="note" style="margin-bottom:14px;">The gap is negotiated trade outside '
            f'the five areas, plus any region USDA is currently withholding. It is taken as a '
            f'median over the last <b>{fn["n"]}</b> weeks and added, not scaled &mdash; neither '
            f'part of it grows with the 5-Area total, so a ratio drifts whenever the 5-Area '
            f'number is unusually high or low. Over the last {FORECAST_BAND_WEEKS} weeks the gap '
            f'ran {fn["gap_lo"]:,.0f}&ndash;{fn["gap_hi"]:,.0f} hd, which is what sets the range '
            f'above.</div>', unsafe_allow_html=True)

        # ── the two series, with the forecast on the end ────────────────────
        pair = fn["pair"].tail(52)
        if not pair.empty:
            st.markdown('<div class="sec-header">5-Area and national weekly negotiated volume</div>',
                        unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=pair.index, y=pair["nat"], name="National (LM_CT154)",
                mode="lines", line=dict(color=DEL_COLOR, width=2),
                hovertemplate="%{x|%b %d, %Y}<br>National %{y:,.0f} hd<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=pair.index, y=pair["h5"], name="5-Area (LM_CT150)",
                mode="lines", line=dict(color=CONF_COLOR, width=2),
                hovertemplate="%{x|%b %d, %Y}<br>5-Area %{y:,.0f} hd<extra></extra>"))
            # The forecast as its own marked points, never joined to the line --
            # a dotted continuation reads as data at a glance.
            fig.add_trace(go.Scatter(
                x=[_wk], y=[fn["central"]], name="National forecast",
                mode="markers", marker=dict(color=DEL_COLOR, size=11, symbol="diamond",
                                            line=dict(color="#ffffff", width=1.5)),
                error_y=dict(type="data", symmetric=False,
                             array=[fn["high"] - fn["central"]],
                             arrayminus=[fn["central"] - fn["low"]],
                             color=DEL_COLOR, thickness=1.5, width=6),
                hovertemplate="%{x|%b %d, %Y}<br>National forecast %{y:,.0f} hd<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=[_wk], y=[f5["central"]], name="5-Area forecast",
                mode="markers", marker=dict(color=CONF_COLOR, size=11, symbol="diamond",
                                            line=dict(color="#ffffff", width=1.5)),
                error_y=dict(type="data", symmetric=False,
                             array=[f5["high"] - f5["central"]],
                             arrayminus=[f5["central"] - f5["low"]],
                             color=CONF_COLOR, thickness=1.5, width=6),
                hovertemplate="%{x|%b %d, %Y}<br>5-Area forecast %{y:,.0f} hd<extra></extra>"))
            fig.update_layout(
                height=330, margin=dict(l=10, r=10, t=10, b=10),
                plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
                font=dict(family="Source Sans Pro, sans-serif", color=JPSI_DARK, size=12),
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
                xaxis=dict(showgrid=False, linecolor=BORDER),
                yaxis=dict(title="head", gridcolor="#f0f2f4", linecolor=BORDER,
                           zeroline=False, tickformat=","))
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False})

            recent = pair.tail(10).copy()
            recent.index = [d.strftime("%b %d") for d in recent.index]
            recent = recent.rename(columns={"h5": "5-Area", "nat": "National", "gap": "Gap"})
            st.dataframe(
                recent[["5-Area", "National", "Gap"]].iloc[::-1]
                      .style.format("{:,.0f}"),
                use_container_width=True)

        # ── how the last ten calls landed ───────────────────────────────────
        # Scored at the SAME checkpoint the live forecast above is standing at,
        # not at a fixed Friday -- accuracy depends far more on how far into the
        # week you are than on anything else, so a fixed-Friday scorecard would
        # flatter a Wednesday reading of this page roughly tenfold. See
        # scorecard.py, which also records why replaying past calls is honest
        # here when it is not for the sibling FCI scorecard.
        stats = scorecard.summarise(board)
        # Deliberately after summarise(). The accuracy line above the table
        # describes CALLS THAT HAVE BEEN SETTLED; this week has not been, so it
        # is appended for display only and never reaches the median or the band
        # count. scorecard.summarise() also drops it defensively.
        pending = scorecard.pending_row(
            fcst_vol, head5, headn, forecast_5area, forecast_national)
        if not board.empty and stats:
            # NAME THE CHECKPOINT THESE WERE SCORED AT, because it is not
            # always the live one. build_scorecard steps back when the live
            # week is too green to forecast from (see its GREEN_MATURITY note),
            # and "at this point in the week" then describes a checkpoint the
            # rows were not scored at -- borrowing a Friday call's accuracy for
            # a Monday one, which flatters rather than merely misleads.
            #
            # IT HAS TO BE BUILT BEFORE THE HEADER THAT PRINTS IT. Writing it
            # underneath read fine and raised NameError on the live page --
            # script order again, the rule this file keeps relearning.
            _sc_cp = scorecard.checkpoint_of(board)
            _live_cp = ((int(f5["checkpoint"]["weekday"]), int(f5["checkpoint"]["order"]))
                        if f5 else None)
            _sc_dow_lbl, _sc_cut_lbl = _dow, _cut
            if _sc_cp is not None:
                _sc_dow_lbl = ["Monday", "Tuesday", "Wednesday", "Thursday",
                               "Friday"][_sc_cp[0]]
                _sc_cut_lbl = DAILY_CUT_LABEL["morning" if _sc_cp[1] else "afternoon"]
            if _sc_cp is None or _sc_cp == _live_cp:
                _cp_label = "at this point in the week"
            else:
                # DAILY_CUT_LABEL already ends in "cut" for the afternoon
                # file ("1:30 pm cut") and reads "Final" for the morning one,
                # so neither wants the word appended.
                _cp_label = (
                    f'at the {_sc_dow_lbl} {_sc_cut_lbl.lower()} &mdash; this week '
                    f'has barely traded, so there is nothing yet to score a call from')

            st.markdown(
                f'<div class="sec-header" style="border-left-color:{D14_COLOR};">'
                f'Forecast accuracy &mdash; the last {stats["n"]} calls '
                f'{_cp_label}</div>', unsafe_allow_html=True)

            _f, _n = stats["five"], stats["nat"]
            st.markdown(
                f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 8px;">'
                f'<b>5-Area</b> missed by a median <b>{_f["median_abs_head"]:,.0f} hd '
                f'({_f["median_abs_pct"]:.1%})</b>, inside the stated range '
                f'<b>{_f["in_band"] * stats["n"]:.0f} of {stats["n"]}</b> times. '
                f'<b>National</b> missed by a median <b>{_n["median_abs_head"]:,.0f} hd '
                f'({_n["median_abs_pct"]:.1%})</b>, inside <b>'
                f'{_n["in_band"] * stats["n"]:.0f} of {stats["n"]}</b>.</div>',
                unsafe_allow_html=True)

            # The live week rides on top, newest first like the rest.
            _b = (board.copy() if pending.empty
                  else pd.concat([pending, board], ignore_index=True))
            _live = _b["pending"].fillna(False).astype(bool)

            # Every actual and every miss on the pending row is NaN. Formatted
            # with the scored rows' f-strings those print "nan", which reads as
            # a broken number rather than an unanswered one.
            def _hd(v):
                return "\u2014" if pd.isna(v) else f"{v:,.0f}"

            def _ms(m, q):
                return ("\u2014" if pd.isna(m) or pd.isna(q)
                        else f"{m:+,.0f} ({q:+.1%})")

            _b["Week of"] = [d.strftime("%b %d") + (" \u00b7 live" if lv else "")
                             for d, lv in zip(_b["week"], _live)]
            _b["Week to date"] = _b["wtd"].map(_hd)
            _b["Confidence"] = _b["grade"].fillna("").str.title()
            _b["5-Area est."] = _b["f5"].map(_hd)
            _b["5-Area actual"] = _b["a5"].map(_hd)
            _b["5-Area miss"] = [_ms(m, q) for m, q in zip(_b["miss5"], _b["pct5"])]
            _b["National est."] = _b["fn"].map(_hd)
            _b["National actual"] = _b["an"].map(_hd)
            _b["National miss"] = [_ms(m, q) for m, q in zip(_b["missn"], _b["pctn"])]
            st.dataframe(
                _b[["Week of", "Week to date", "Confidence", "5-Area est.",
                    "5-Area actual", "5-Area miss", "National est.",
                    "National actual", "National miss"]],
                use_container_width=True, hide_index=True)

            if not pending.empty:
                _pw = pending["week"].iloc[0]
                _prints = (_pw + pd.Timedelta(days=7)).strftime("%a %b %d")
                st.markdown(
                    f'<div class="note" style="margin-top:6px;">'
                    f'<b>The top row is this week, still open.</b> '
                    + ('It carries no estimate because the week is too green for '
                       'one &mdash; the same reason the tiles above show recent weeks '
                       'instead of a call. '
                       if f5.get("no_call") else
                       'It is the same call as the tiles above &mdash; estimates and '
                       'confidence only. ')
                    + f'There is no actual to score against until USDA prints the week '
                    f'of {_pw.strftime("%b %d")} on <b>{_prints}</b>. '
                    f'It is <b>not</b> in the accuracy figures above, which cover the '
                    f'{stats["n"]} settled calls; when the print lands this row is '
                    f'scored like any other and the averages take it in.</div>',
                    unsafe_allow_html=True)

            st.markdown(
                f'<div class="note" style="margin-top:6px;">Each past week is replayed '
                f'through the same code the forecast above runs, standing at the same '
                # _dow/_cut are the LIVE checkpoint; these rows may have been
                # scored at an earlier one when the live week is too green to
                # forecast from. Naming the wrong checkpoint here is the same
                # defect as naming it wrong in the header above.
                f'<b>{_sc_dow_lbl} {_sc_cut_lbl.lower()}</b> and seeing only what had been '
                f'published by then &mdash; the analogue pool, the typical-week baseline '
                f'and the national gap are all cut to weeks USDA had already printed. '
                f'<b>The 5-Area column is the one to trust.</b> It is close to arithmetic, '
                f'and the national column carries the gap to states with no daily report '
                f'at all, which is why its miss is the larger of the two. Replaying is '
                f'sound here because the weekly figure being scored against has never been '
                f'revised &mdash; zero corrections in twelve months &mdash; and only 0.5% of '
                f'the daily rows it replays from ever are.</div>',
                unsafe_allow_html=True)

        st.markdown(
            '<div class="note" style="margin-top:10px;">'
            '<b>What this is.</b> Both weekly reports print the Monday after the week they '
            'cover. The 5-Area step is close to arithmetic &mdash; USDA&rsquo;s own daily '
            'week-to-date already carries most of the answer, and only late-reported trade is '
            'estimated. The national step is the looser of the two, because the gap between '
            'the two reports moves with trade in states that have no daily report at all.<br><br>'
            '<b>The one thing that can move it a long way.</b> When USDA withholds a region&rsquo;s '
            'daily volume for confidentiality, that region drops out of the 5-Area figure but '
            '<b>stays in the national count</b>, so the gap widens and the national forecast is '
            'the half that suffers. Check the week-to-date tiles on the Daily tab: a region '
            'sitting at zero across a whole week is the signal.<br><br>'
            '<b>Neither number is USDA&rsquo;s.</b> They are estimates built from USDA&rsquo;s '
            'published daily reports, and they carry no official standing until the Monday '
            'release.</div>', unsafe_allow_html=True)


# ── Packer Leverage ──────────────────────────────────────────────────────────
# What share of the kill packers did NOT have to bid for this week, from AMS's
# own breakdown of slaughter by purchase type. See leverage.py for why every
# share is computed inside LM_CT153 alone -- the negotiated PURCHASES series on
# the other tabs is a different population on a different clock, and dividing
# one by the other yields a number that looks like a share and is not one.
with tab_lev:
    st.markdown(
        '<div class="sec-header">Packer Leverage &mdash; how much of the kill was '
        'already bought</div>', unsafe_allow_html=True)

    with st.spinner("Loading USDA purchase-mix and committed inventory…"):
        try:
            _lev_stamps = stamps_for(_probe, [leverage.CT142_ID, leverage.CT153_ID])
            lev_f = fetch_leverage(_lev_stamps, leverage.SCHEMA)
            lev_err = ""
        except Exception as e:
            lev_f, lev_err = {}, str(e)

    _mix = lev_f.get("mix", pd.DataFrame())
    _L = leverage.latest(lev_f) if lev_f else {}

    if lev_err:
        st.warning("⏳ **USDA data unavailable** — the purchase-mix reports are not "
                   "responding. Use **Refresh now** in the sidebar to retry.")
        with st.expander("Technical details"):
            st.code(lev_err)
    elif _mix.empty or "mix" not in _L:
        st.info("USDA has published no purchase-mix data for this period.")
    else:
        _r = _L["mix"]
        _wk = pd.Timestamp(_r["week"])
        _pr = _L.get("mix_prior")
        _yr = _L.get("mix_year")
        _pct = leverage.percentile(_mix, "negotiated_pct", _r["negotiated_pct"])

        st.markdown(
            f'<div class="note" style="margin:-4px 0 12px;">Slaughter week ending '
            f'<b>{_wk.strftime("%b %d, %Y")}</b>, from USDA&rsquo;s own split of the kill '
            f'by how each animal was bought (LM_CT153). This is the SLAUGHTER side &mdash; '
            f'cattle killed that week, bought whenever they were bought. The negotiated '
            f'volume on the other tabs is the PURCHASE side and runs on a different '
            f'clock.</div>', unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(tile("Negotiated share of kill",
                             f"{_r['negotiated_pct']:.1%}",
                             (f'<div class="tile-delta-{"neg" if _r["negotiated_pct"] < _pr["negotiated_pct"] else "pos"}">'
                              f'{"▼" if _r["negotiated_pct"] < _pr["negotiated_pct"] else "▲"} '
                              f'{abs(_r["negotiated_pct"] - _pr["negotiated_pct"]) * 100:.1f} pt vs week ago</div>')
                             if _pr is not None else "",
                             "tile-conf"), unsafe_allow_html=True)
        with c2:
            st.markdown(tile("Already committed",
                             f"{_r['committed_pct']:.1%}",
                             f'<div class="tile-delta-neu">formula + forward</div>',
                             "tile-d14"), unsafe_allow_html=True)
        # c3/c4 ARE THE STANDING BOOK, not the weekly flow that used to sit
        # here. "Committed inventory" and "weeks of coverage" both read
        # LM_CT142, whose Committed column is head committed DURING the week —
        # a flow — so the first was not an inventory and the second was not
        # weeks of anything. The real inventory is LM_CT153's forward book:
        # "Cumulative Total for Listed Months" on ams_2480.pdf, cattle bought
        # and not yet delivered.
        _sch = _L.get("schedule")
        _fw = _L.get("forward")
        _near = leverage.near_months(_sch, 3) if _sch is not None else {}
        with c3:
            st.markdown(tile("Forward book, undelivered",
                             fmt_hd(_fw["fwd_book"]) if _fw is not None else "—",
                             (hd_delta_html(_fw["fwd_book"], _L["forward_prior"]["fwd_book"])
                              if _fw is not None and _L.get("forward_prior") is not None else ""),
                             "tile-del"), unsafe_allow_html=True)
        with c4:
            _nc = _near.get("change")
            st.markdown(tile("Next 3 months vs year ago",
                             f"{_nc:+.0%}" if _nc is not None else "—",
                             (f'<div class="tile-delta-{"neg" if _nc < 0 else "pos"}">'
                              f'{_near["committed"]:,.0f} vs {_near["last_year"]:,.0f} hd</div>')
                             if _nc is not None else "",
                             "tile-neu"), unsafe_allow_html=True)

        # ── what it means, in the market's own recent terms ─────────────────
        if _pct == _pct:
            _tight = _pct >= 0.67
            _loose = _pct <= 0.33
            _col = POS if _tight else (NEG if _loose else D30_COLOR)
            _verdict = ("Packers are leaning on the cash market MORE than usual"
                        if _tight else
                        "Packers are leaning on the cash market LESS than usual"
                        if _loose else
                        "Packers are about as covered as usual")
            _side = ("so a larger share of the week's needs has to be bid for, which "
                     "is the feedlot-friendly end of this measure"
                     if _tight else
                     "so more of the week arrives on commitments already made and the "
                     "cash market decides less of it"
                     if _loose else
                     "so neither side gets much help from the mix this week")
            st.markdown(
                f'<div style="border-left:3px solid {_col};background:#fafbfc;padding:8px 12px;'
                f'margin:4px 0 14px;font-size:0.8rem;line-height:1.55;color:{JPSI_DARK};">'
                f'<b style="color:{_col};">{_verdict}.</b> At '
                f'<b>{_r["negotiated_pct"]:.1%}</b> the negotiated share sits in the '
                f'<b>{_pct * 100:.0f}th percentile</b> of the last three years &mdash; {_side}.'
                + (f'<br><span style="color:{MUTED};">A year ago it was '
                   f'{_yr["negotiated_pct"]:.1%}.</span>' if _yr is not None else "")
                + '</div>', unsafe_allow_html=True)

        # ── what the ratio costs them in head ───────────────────────────────
        # A RUN RATE, NOT A FORECAST, and the wording has to carry that. There
        # is no published "cattle still to buy this week": the week's purchases
        # and the week's slaughter are different populations on different
        # clocks, so subtracting one from the other would manufacture a figure
        # rather than measure one. What can be said honestly is how many head
        # recent weeks each required, how much that varied, and how close the
        # average has landed to the week that followed.
        _need = leverage.cash_need(_mix)
        _acc = leverage.need_accuracy(_mix)
        if _need:
            st.markdown(
                f'<div class="sec-header" style="border-left-color:{NEG};">'
                f'Cash need &mdash; head they have to transact for in a week</div>',
                unsafe_allow_html=True)

            n1, n2 = st.columns(2)
            with n1:
                st.markdown(tile("Negotiated cash, per week",
                                 fmt_hd(_need["cash"]),
                                 f'<div class="tile-delta-neu">'
                                 f'{_need["cash_lo"]:,.0f}&ndash;{_need["cash_hi"]:,.0f} hd '
                                 f'over {_need["weeks"]} wks</div>',
                                 "tile-conf"), unsafe_allow_html=True)
            with n2:
                st.markdown(tile("Including negotiated grid",
                                 fmt_hd(_need["must"]),
                                 f'<div class="tile-delta-neu">'
                                 f'{_need["must_lo"]:,.0f}&ndash;{_need["must_hi"]:,.0f} hd '
                                 f'over {_need["weeks"]} wks</div>',
                                 "tile-del"), unsafe_allow_html=True)

            _acc_s = ""
            if _acc.get("cash") and _acc.get("must"):
                _acc_s = (
                    f' Over the last {_acc["cash"]["n"]} weeks a '
                    f'{_need["weeks"]}-week average has landed within a median '
                    f'<b>{_acc["cash"]["median"]:.1%}</b> of the week that followed '
                    f'({_acc["cash"]["p90"]:.0%} at the 90th percentile), and '
                    f'<b>{_acc["must"]["median"]:.1%}</b> including grid &mdash; '
                    f'grid and cash partly offset each other week to week, so the '
                    f'wider measure is the steadier one.')
            st.markdown(
                f'<div class="note" style="margin-bottom:14px;">'
                f'<b>This is a run rate, not a forecast of the week in front of you.</b> '
                f'USDA publishes no &ldquo;still to buy&rdquo; figure, and the week&rsquo;s '
                f'purchases and the week&rsquo;s slaughter are different populations on '
                f'different clocks &mdash; subtracting one from the other would invent a '
                f'number rather than measure one. What this says is how many head the '
                f'{_need["weeks"]} weeks to '
                f'<b>{_need["to"].strftime("%b %d")}</b> each required, against an average '
                f'kill of <b>{_need["kill"]:,.0f} hd</b>.{_acc_s}</div>',
                unsafe_allow_html=True)

        # ── the mix itself ──────────────────────────────────────────────────
        st.markdown(
            f'<div class="sec-header" style="border-left-color:{CONF_COLOR};">'
            f'How the kill was bought</div>', unsafe_allow_html=True)
        _bits = " &middot; ".join(
            f'<b>{leverage.MIX_LABEL[k]}</b> {_r[k]:,.0f} hd ({_r[k + "_pct"]:.1%})'
            for k in ("formula", "forward", "negotiated", "neg_grid"))
        st.markdown(
            f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
            f'{_bits} &mdash; <b>{_r["total"]:,.0f} hd</b> in all.</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="note" style="margin-bottom:12px;"><b>Negotiated grid is kept '
            f'separate and is not folded into the headline.</b> Its base price is '
            f'negotiated in the week, so for &ldquo;did the packer have to transact&rdquo; it '
            f'belongs with cash &mdash; on that reading they must buy '
            f'<b>{_r["must_buy_pct"]:.1%}</b> of the week rather than '
            f'{_r["negotiated_pct"]:.1%}. For &ldquo;what share of the kill discovered a cash '
            f'price&rdquo;, the convention is cash alone. Both are defensible and they '
            f'differ by a third, so the page shows both and picks neither for you.'
            f'</div>', unsafe_allow_html=True)

        _hist = _mix[_mix["week"] >= _mix["week"].max() - pd.Timedelta(weeks=156)]
        if not _hist.empty:
            fig = go.Figure()
            for key, colr in (("formula", JPSI_BLUE), ("forward", D14_COLOR),
                              ("neg_grid", D30_COLOR), ("negotiated", NEG)):
                fig.add_trace(go.Scatter(
                    x=_hist["week"], y=_hist[f"{key}_pct"], name=leverage.MIX_LABEL[key],
                    mode="lines", stackgroup="one", line=dict(width=0.5, color=colr),
                    hovertemplate="%{x|%b %d, %Y}<br>" + leverage.MIX_LABEL[key]
                                  + " %{y:.1%}<extra></extra>"))
            fig.update_layout(
                height=320, margin=dict(l=10, r=10, t=10, b=10),
                plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
                font=dict(family="Source Sans Pro, sans-serif", color=JPSI_DARK, size=12),
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
                xaxis=dict(showgrid=False, linecolor=BORDER),
                yaxis=dict(title="share of kill", gridcolor="#f0f2f4", linecolor=BORDER,
                           zeroline=False, tickformat=".0%", range=[0, 1]))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.markdown(
                '<div class="note" style="margin-top:-6px;">Three years. The red band at '
                'the top is the only part of the week that has to find a price in the '
                'cash market.</div>', unsafe_allow_html=True)

        # ── the forward book and what else is captive ───────────────────────
        st.markdown(
            f'<div class="sec-header" style="border-left-color:{DEL_COLOR};">'
            f'The standing book &mdash; cattle bought and not yet delivered</div>',
            unsafe_allow_html=True)
        if _sch is not None and not _sch.empty and _fw is not None:
            _ok = leverage.reconciles(_sch, _fw["fwd_book"])
            st.markdown(
                f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
                f'<b>{_fw["fwd_book"]:,.0f} hd</b> on forward contract and not yet '
                f'delivered, <b>{_fw["fwd_week"]:,.0f} hd</b> newly signed last week'
                + (f'. Over the next {_near["n"]} delivery months they hold '
                   f'<b>{_near["committed"]:,.0f} hd</b> against '
                   f'<b>{_near["last_year"]:,.0f} hd</b> a year ago, '
                   f'<b style="color:{NEG if _near["change"] < 0 else POS};">'
                   f'{_near["change"]:+.1%}</b>.' if _near else ".")
                + '</div>', unsafe_allow_html=True)

            # WHICH CATTLE THESE ARE is the first thing anyone asks of the
            # figure, and both wrong answers misread the market. Read it as
            # all committed supply and the packer looks far shorter than he
            # is, because formula is the bigger share by a wide margin; read
            # it as "contracts, so basis contracts are somewhere else" and you
            # go looking for a number that does not exist separately.
            #
            # LM_CT153's own section names settle it. Section B is
            # "Prior Week Formula & Contract Slaughter" -- it names both and
            # counts them apart. Section C, where this figure comes from, is
            # "Forward Contract Purchases", and the word formula does not
            # appear anywhere in it.
            st.markdown(
                f'<div style="border-left:3px solid {DEL_COLOR};'
                f'background:#fbfbfa;padding:9px 13px;margin:2px 0 14px;'
                f'font-size:0.78rem;line-height:1.6;color:{JPSI_DARK};">'
                f'<b>What is in this book.</b> Forward-contract cattle only '
                f'&mdash; head signed for delivery in a named month at a price '
                f'struck as a <b>basis to a CME futures month</b>. USDA keys '
                f'the table &ldquo;Delivery Mo./Basis Mo.&rdquo;, so a row '
                f'reading <i>Oct&nbsp;&rsquo;26/Oct</i> is October delivery '
                f'priced off October futures. <b>Basis contracts are not a '
                f'separate category from these &mdash; they are these</b>, '
                f'which is why the only prices in the table are basis levels '
                f'rather than dollars per hundredweight.<br>'
                f'<b>Formula cattle are not in it</b>, and could not be. A '
                f'formula animal has no contracted delivery month and no '
                f'agreed price &mdash; it is priced when it ships, off a '
                f'published average &mdash; so there is nothing to inventory '
                f'by month. USDA splits them for the same reason: section B '
                f'of this report is &ldquo;Formula <i>&amp;</i> Contract&rdquo;, '
                f'section C is forward contract alone.<br>'
                f'<b>So the book understates committed supply on purpose.</b> '
                f'Formula was <b>{_r["formula_pct"]:.1%}</b> of last '
                f'week&rsquo;s reported kill against forward contract&rsquo;s '
                f'<b>{_r["forward_pct"]:.1%}</b>. What is counted here is the '
                f'part of the packer&rsquo;s cover that carries a date and a '
                f'price; the formula share is cover of a different kind and '
                f'sits in the purchase mix above, not here.</div>',
                unsafe_allow_html=True)

            _s = _sch.head(12).copy()
            _lbl = [f"{m} '{str(y)[2:]}" for m, y in zip(_s["month"], _s["year"])]
            fig2 = go.Figure()
            # THE YEAR-AGO BARS WERE DRAWN IN `BORDER` AND WERE EFFECTIVELY
            # INVISIBLE — the same near-white used for table rules and axis
            # lines. The series was plotted and nobody could see it, which is
            # the same thing as not plotting it: Ross asked for a year-ago
            # comparison on a chart that already had one. A data series needs
            # a data colour; chrome colours are for chrome.
            fig2.add_trace(go.Bar(
                x=_lbl, y=_s["last_year"], name="A year ago",
                marker=dict(color="#aeb6c0",
                            line=dict(color="#8d95a0", width=1)),
                hovertemplate="a year ago %{y:,.0f} hd<extra></extra>"))
            fig2.add_trace(go.Bar(
                x=_lbl, y=_s["committed"], name="Committed now",
                marker_color=DEL_COLOR,
                customdata=_s["vs_last_year"],
                hovertemplate="committed %{y:,.0f} hd"
                              "<br>%{customdata:+.1%} vs a year ago<extra></extra>"))
            # The shortfall is the story, so it gets its own readable row under
            # the axis rather than being left for the reader to subtract.
            # Above the taller (year-ago) bar, not at y=0 — at the zero line
            # they sit on top of the month labels and neither can be read.
            fig2.add_trace(go.Scatter(
                x=_lbl, y=_s["last_year"], mode="text",
                text=[f"{v:+.0%}" if v == v else "" for v in _s["vs_last_year"]],
                textposition="top center",
                textfont=dict(size=10, color=NEG),
                showlegend=False, hoverinfo="skip"))
            fig2.update_layout(
                height=330, margin=dict(l=10, r=10, t=26, b=10), barmode="overlay",
                plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
                font=dict(family="Source Sans Pro, sans-serif", color=JPSI_DARK, size=12),
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
                xaxis=dict(title="delivery month", showgrid=False, linecolor=BORDER),
                yaxis=dict(title="head", gridcolor="#f0f2f4", linecolor=BORDER,
                           zeroline=False, tickformat=",",
                           rangemode="tozero"))
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

            st.markdown(
                f'<div class="note" style="margin-top:-6px;margin-bottom:14px;">'
                f'USDA&rsquo;s own heading is &ldquo;Cumulative Total for Listed Months&rdquo; '
                f'&mdash; cattle contracted and still to be delivered, by the month they are '
                f'due. <b>The near months are the ones that bear on this week&rsquo;s '
                f'bidding</b>: cattle contracted for next spring do nothing for a packer '
                f'filling a kill on Thursday. The sixteen monthly totals add back to the '
                f'published book figure '
                + ('<b>exactly</b>' if _ok else '<b style="color:%s;">— and currently do '
                   'NOT, so the row layout has moved and these figures should not be '
                   'trusted</b>' % NEG)
                + f', which is the audit on this table.</div>', unsafe_allow_html=True)

        _ow, _cm = _L.get("owned"), _L.get("committed")
        _bits = []
        if _ow is not None and pd.notna(_ow["packer_owned"]):
            _bits.append(f'<b>{_ow["packer_owned"]:,.0f} hd</b> were packer-owned and fed')
        if _cm is not None and pd.notna(_cm.get("signings_vs_pace")):
            _bits.append(f'and new commitments ran at <b>{_cm["signings_vs_pace"]:.2f}&times;</b> '
                         f'the four-week shipping pace, so the book '
                         f'{"grew" if _cm["signings_vs_pace"] > 1 else "drained"} over the week')
        if _bits:
            st.markdown(
                f'<div class="note" style="margin-bottom:14px;">In the reported kill, '
                + " ".join(_bits) + '. That last ratio is a comparison of two weekly '
                'FLOWS &mdash; head committed during the week against head shipped &mdash; '
                'and is not a measure of supply on hand; the standing inventory is the '
                'forward book above.</div>', unsafe_allow_html=True)

        # ── how current the cattle are ──────────────────────────────────────
        # The third leg of leverage, and the one with no published series
        # behind it. NASS carries on-feed inventory, placements and
        # marketings but NOTHING by days fed — the "120+ days" figure analysts
        # quote is derived, not published. The weekly tell is carcass weight:
        # cattle held past their window get heavier, so weights running above
        # trend mean feedyards are not current and showlists are bigger than
        # the head count alone suggests.
        #
        # NO NEW REQUEST. price_df is already fetched for the Weekly tab and
        # `weight_range_avg` rides along on it, back to 2004.
        _wts = leverage.weight_frame(price_df)
        _wl = leverage.weight_context(_wts, "Live")
        _wd = leverage.weight_context(_wts, "Dressed")
        if _wl.get("vs_trend") is not None:
            st.markdown(
                f'<div class="sec-header" style="border-left-color:{D14_COLOR};">'
                f'How current the cattle are &mdash; weight against its own trend</div>',
                unsafe_allow_html=True)

            w1, w2, w3 = st.columns(3)
            with w1:
                st.markdown(tile("Live weight",
                                 f"{_wl['weight']:,.0f} lb",
                                 hd_delta_html(_wl["weight"], _wl["year_ago"]).replace(" hd", " lb"),
                                 "tile-d14"), unsafe_allow_html=True)
            with w2:
                _d = _wl["vs_trend"]
                st.markdown(tile("Live vs trend",
                                 f"{_d:+,.0f} lb",
                                 f'<div class="tile-delta-neu">trend says '
                                 f'{_wl["expected"]:,.0f} lb</div>',
                                 "tile-conf"), unsafe_allow_html=True)
            with w3:
                st.markdown(tile("Dressed vs trend",
                                 f"{_wd['vs_trend']:+,.0f} lb" if _wd.get("vs_trend") is not None else "—",
                                 (f'<div class="tile-delta-neu">{_wd["weight"]:,.0f} lb, trend '
                                  f'{_wd["expected"]:,.0f}</div>') if _wd.get("expected") else "",
                                 "tile-del"), unsafe_allow_html=True)

            _heavy = _wl["vs_trend"] > 0
            _col = NEG if _heavy else POS
            st.markdown(
                f'<div style="border-left:3px solid {_col};background:#fafbfc;padding:8px 12px;'
                f'margin:4px 0 12px;font-size:0.8rem;line-height:1.55;color:{JPSI_DARK};">'
                f'<b style="color:{_col};">Cattle are '
                f'{"heavier" if _heavy else "lighter"} than trend by '
                f'{abs(_wl["vs_trend"]):,.0f} lb.</b> '
                + ('Cattle held past their window put on weight, so this is feedyards '
                   'running behind — the showlist is bigger than a head count says and '
                   'the packer can afford to wait.'
                   if _heavy else
                   'Feedyards are current, so there is less standing inventory behind the '
                   'showlist than usual and the packer has less room to wait.')
                + f'<br><span style="color:{MUTED};">Up {_wl["vs_year_ago"]:+,.0f} lb on the '
                f'year, of which about {_wl["slope"]:+,.0f} lb is the ordinary drift that '
                f'happens every year &mdash; fitted on the same week of the last '
                f'{_wl["n"]} years, so the season is not in it.</span></div>',
                unsafe_allow_html=True)

            _hist = _wts[_wts["report_date"] >= _wts["report_date"].max()
                         - pd.Timedelta(weeks=156)]
            if not _hist.empty and "Live" in _hist:
                fig3 = go.Figure()
                fig3.add_trace(go.Scatter(
                    x=_hist["report_date"], y=_hist["Live"], name="Live weight",
                    mode="lines", line=dict(color=JPSI_BLUE, width=2),
                    hovertemplate="%{x|%b %d, %Y}<br>%{y:,.0f} lb<extra></extra>"))
                fig3.update_layout(
                    height=280, margin=dict(l=10, r=10, t=10, b=10),
                    plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
                    font=dict(family="Source Sans Pro, sans-serif", color=JPSI_DARK, size=12),
                    hovermode="x unified", showlegend=False,
                    xaxis=dict(showgrid=False, linecolor=BORDER),
                    yaxis=dict(title="lb, live", gridcolor="#f0f2f4", linecolor=BORDER,
                               zeroline=False, tickformat=","))
                fig3.add_hline(y=_wl["expected"], line_dash="dot", line_color=MUTED,
                               annotation_text="trend for this week",
                               annotation_position="top left")
                st.plotly_chart(fig3, use_container_width=True,
                                config={"displayModeBar": False})

            st.markdown(
                '<div class="note" style="margin-top:-6px;margin-bottom:14px;">'
                '<b>There is no published days-on-feed series.</b> NASS carries on-feed '
                'inventory, placements and marketings, and nothing by days fed — the '
                '"120+ days" figure analysts quote is derived from the placement flow, '
                'not reported. Weight is the weekly stand-in and it has the advantage of '
                'arriving every Monday rather than once a month.<br><br>'
                '<b>Against trend, not against last year.</b> Fed cattle have got heavier '
                'for two decades, so a raw year-ago comparison counts ordinary drift as '
                'market signal. The trend here is fitted on the same ISO week of prior '
                'years, which removes the season as well.</div>',
                unsafe_allow_html=True)

        _tbl = _mix.tail(12).sort_values("week", ascending=False).copy()
        _tbl["Week ending"] = _tbl["week"].dt.strftime("%b %d")
        _tbl["Negotiated %"] = _tbl["negotiated_pct"].map(lambda v: f"{v:.1%}")
        _tbl["Neg grid %"] = _tbl["neg_grid_pct"].map(lambda v: f"{v:.1%}")
        _tbl["Committed %"] = _tbl["committed_pct"].map(lambda v: f"{v:.1%}")
        for k in ("formula", "forward", "negotiated", "neg_grid"):
            _tbl[leverage.MIX_LABEL[k]] = _tbl[k].map(lambda v: f"{v:,.0f}")
        _tbl["Total kill"] = _tbl["total"].map(lambda v: f"{v:,.0f}")
        st.dataframe(
            _tbl[["Week ending", "Negotiated %", "Neg grid %", "Committed %",
                  "Negotiated cash", "Negotiated grid", "Formula", "Forward contract",
                  "Total kill"]],
            use_container_width=True, hide_index=True)

        st.markdown(
            '<div class="note" style="margin-top:10px;">'
            '<b>What this is.</b> USDA breaks the slaughter it reports down by how each '
            'animal was bought. Formula and forward cattle were priced before the week '
            'began, so they are supply the packer never has to bid for; only the '
            'negotiated share has to find a price now. A low negotiated share means the '
            'packer can stand back from the cash market, and a high one means they '
            'cannot.<br><br>'
            '<b>The number this does NOT give you.</b> It is the share of the '
            '<i>reported</i> kill, not of total US fed slaughter — plants outside the '
            'mandatory reporting universe are not in the denominator. Use it as a ratio '
            'over time, which is how it is published, rather than as a head count of the '
            'national market.<br><br>'
            '<b>It also lags.</b> LM_CT153 reports the PRIOR week\'s slaughter, so the '
            'newest row here is a week behind the daily cash prices on the other tabs. '
            'That is USDA\'s publication schedule, not a staleness bug.</div>',
            unsafe_allow_html=True)


# ── WASDE steer price ────────────────────────────────────────────────────────
# Moved out of the Weekly tab 2026-10-07. It had sat above that tab's LMR guard
# deliberately, because WASDE comes from ESMIS over a different host and an LMR
# outage must not blank a forecast that never touched LMR.
#
# ITS OWN TAB KEEPS THAT PROPERTY RATHER THAN LOSING IT, which is the only
# reason the move is safe: a tab body is outside the weekly tab's `if not
# load_ok` entirely, so the panel still renders on exactly the days an LMR
# outage would have hidden it. Putting it anywhere INSIDE the weekly tab's
# else-branch would have quietly undone that.
#
# No new fetch either. fetch_wasde_steer is cached and the hidden-tab rule
# means it already ran on every load from the weekly tab; it now runs from
# here instead.
with tab_wasde:
    wasde_steer_panel()


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
        '<b>Daily Cash Trade</b> — USDA AMS LMR daily negotiated purchases by region: <b>LM_CT117/118</b> (TX/OK/NM), <b>LM_CT120/121</b> (Kansas), <b>LM_CT123/124</b> (Nebraska), <b>LM_CT136/137</b> (Iowa/Minnesota). Each region publishes twice daily; the morning file finalises the PREVIOUS business day and is shifted back one day so both cuts line up on the trading day. Colorado no longer publishes a daily report (ended 2023/2024) and is weekly-only. The daily figures refresh on USDA\'s own <i>published_date</i> stamp rather than on a timer, because AMS publishes no release schedule — it has released LMR data in real time since May 2020. Over 180 days the morning file has landed between 10:52 and 16:18 Central (median 11:17) and the afternoon between 14:49 and 16:49 (median 15:08), so no fixed refresh time would do.<br><br>'
        'Full available history is always loaded — LM_CT150 back to 2004, LM_CT154 back to 2001. Weekly cache: 1 hr.'
        '</div>',
        unsafe_allow_html=True,
    )


# ── Legal Disclaimer Footer ───────────────────────────────────────────────────

_disclaimer_year = datetime.now().year
st.markdown("<hr style='border-color:#3a3a3a;margin-top:32px;margin-bottom:16px'>", unsafe_allow_html=True)
st.markdown(
    f'<div style="font-family:inherit;color:#888;font-size:inherit;line-height:1.6;text-align:center;padding:0 24px 24px;">'
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
