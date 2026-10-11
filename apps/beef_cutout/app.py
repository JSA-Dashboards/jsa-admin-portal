import sys
from pathlib import Path

import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta
import time

# A Streamlit page's own directory is never added to sys.path automatically.
# Same two lines apps/beef_weight/app.py uses to reach daily_slaughter.py.
# "am_cutout" is a name that exists ONCE in this repo, so unlike snowflake_db
# it cannot join the five-copy sys.modules collision CLAUDE.md documents.
sys.path.insert(0, str(Path(__file__).parent))
import am_cutout

# ── JSA Brand Colors ────────────────────────────────────────────────────────
JSA_GREEN    = "#5e7164"
JSA_GREEN_LT = "#8db89a"

DM_BG       = "#f6f8f7"
DM_SURFACE  = "#ffffff"
DM_SURFACE2 = "#eef3f0"
DM_BORDER   = "#d7e2dc"
DM_TEXT     = "#32373c"
DM_MUTED    = "#5f7267"
COL_POS     = "#16a34a"
COL_NEG     = "#dc2626"
COL_NEU     = "#5f7267"

CHOICE_COLOR = "#8db89a"
SELECT_COLOR = "#6fa8c4"
SPREAD_COLOR = "#c4b456"
VOL_COLOR    = "#9b89c4"

# Shared Plotly axis styling. DEFINED UP HERE WITH THE OTHER STYLE CONSTANTS,
# not beside the first chart that uses it: cuts_panel() reads it too and runs
# from the view switch, which is well above where this used to sit. Module
# level means it resolved at call time and would have raised NameError only
# for the reader who clicked the new view.
AXIS = dict(
    gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
    tickfont=dict(color=DM_MUTED, size=11),
    title_font=dict(color=DM_MUTED, size=11),
    zeroline=False,
)

JSA_LOGO_WHITE = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"

# ── USDA LMR API (no key required) ──────────────────────────────────────────
LMR_BASE       = "https://mpr.datamart.ams.usda.gov/services/v1.1/reports"
REPORT_ID      = 2453   # LM_XB403 — National Daily Boxed Beef Cutout & Boxed Beef Cuts PM
REPORT_NAME    = "LM_XB403"
GRADING_ID     = 2700   # LSWFEDCC — National Weekly Fed Cattle Comprehensive (has Pct_Choice_CW)

# ── Historical annual grading averages (USDA AMS, 2000-2025) ────────────────
# Source: USDA AMS National Weekly Fed Cattle Comprehensive annual summaries
# "Choice & Higher" = Prime + Choice graded carcasses as % of total graded
ANNUAL_GRADES = {
    2000: (60.6, 39.4), 2001: (60.7, 39.3), 2002: (62.1, 37.9),
    2003: (60.0, 39.9), 2004: (60.6, 39.0), 2005: (60.3, 39.5),
    2006: (59.0, 40.9), 2007: (60.5, 39.1), 2008: (63.8, 35.8),
    2009: (67.0, 32.7), 2010: (67.8, 31.5), 2011: (68.9, 30.7),
    2012: (68.8, 30.9), 2013: (70.4, 29.5), 2014: (75.0, 22.0),
    2015: (78.0, 18.0), 2016: (82.0, 13.0), 2017: (85.0, 11.0),
    2018: (87.0, 10.0), 2019: (88.0,  9.0), 2020: (85.0, 12.0),
    2021: (85.0, 11.0), 2022: (85.0, 11.0), 2023: (87.0, 10.0),
    2024: (88.0,  9.5), 2025: (88.5,  9.0),
}

# ── Page Config ─────────────────────────────────────────────────────────────
# st.set_page_config removed — the JSA Admin Portal shell (Home.py) makes the
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

  .tile {{
    background:{DM_SURFACE}; border:1px solid {DM_BORDER};
    border-top:3px solid {JSA_GREEN}; border-radius:10px;
    /* 10px side padding, not 20. These rows went from four tiles to five
       when the 5-day average and the spread's year change were added, and at
       1440px a tile is 128px wide -- 20px a side left an 86px content box,
       which is narrower than "$375.62" at this font size. */
    padding:16px 10px; text-align:center; height:100%;
  }}
  .tile-label {{
    color:{DM_MUTED}; font-size:0.68rem; text-transform:uppercase;
    letter-spacing:0.09em; margin-bottom:6px;
  }}
  .tile-value {{
    /* NOWRAP IS THE IMPORTANT HALF. Without it a price too wide for its tile
       breaks between characters and renders as "$375.6" above a lone "2" --
       which does not look like a layout fault, it looks like a number. It
       shipped that way for a day because the checks read the page's TEXT,
       where "$375.62" is intact either way, and only a screenshot shows it. */
    color:{DM_TEXT}; font-size:1.45rem; font-weight:700; line-height:1.1;
    white-space:nowrap;
  }}
  .tile-delta-pos {{ color:{COL_POS}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neg {{ color:{COL_NEG}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neu {{ color:{COL_NEU}; font-size:0.82rem; font-weight:600; margin-top:4px; }}

  .tile-choice {{ border-top-color:{CHOICE_COLOR}; }}
  .tile-select {{ border-top-color:{SELECT_COLOR}; }}
  .tile-spread {{ border-top-color:{SPREAD_COLOR}; }}
  .tile-vol    {{ border-top-color:{VOL_COLOR}; }}

  .sec-header {{
    color:{DM_MUTED}; font-size:0.7rem; text-transform:uppercase;
    letter-spacing:0.1em; padding:8px 0 4px; border-bottom:1px solid {DM_BORDER};
    margin-bottom:10px;
  }}
  hr {{ border-color:{DM_BORDER}; }}
  #MainMenu, footer {{ visibility:hidden; }}
  .stDeployButton {{ display:none; }}
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def delta_html(val, suffix=""):
    if val is None:
        return '<div class="tile-delta-neu">—</div>'
    sign  = "▲" if val > 0 else ("▼" if val < 0 else "")
    color = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    return f'<div class="tile-delta-{color}">{sign} {abs(val):.2f}{suffix}</div>'


def tile(label, value, delta="", cls=""):
    return (f'<div class="tile {cls}">'
            f'<div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>'
            f'{delta}</div>')


def fmt(v, prefix="$"):
    return f"{prefix}{v:.2f}" if v is not None else "—"

def money_md(text: str) -> str:
    """
    A caption string with its dollar signs escaped for Streamlit markdown.

    TWO UNESCAPED $ IN ONE st.caption IS INLINE LaTeX, and Streamlit renders
    it as maths. Everything between the first and second dollar sign is
    swallowed: the $ themselves vanish, and **bold** inside the span comes
    out as literal asterisks because LaTeX does not do markdown. A caption
    reading "a month ago is **Sep 04, 2026** at $20.30" shipped as "a month
    ago is **Sep 04, 2026** at 20.30" with the prices stripped -- which is
    worse than a visible fault, because a spread quoted without its dollar
    sign still reads as a number.

    ONE dollar sign in a caption is safe and several already exist on this
    page ("$/cwt"): it takes a PAIR to open and close a maths span. So this
    only became a bug when captions started quoting two prices at once.
    """
    return text.replace("$", '\\$')


def fmt_loads(v):
    return f"{v:.1f}" if v is not None else "—"


# ── What moved the cutout ────────────────────────────────────────────────────
#
# THE WEIGHTS ARE SOLVED FROM THE DATA, NOT TYPED IN. The cutout is a fixed
# weighted average of the seven primals, and USDA publishes both sides of
# that equation every day -- the primal values and the resulting cutout. So
# the weights can be recovered by least squares rather than quoted from
# memory, and the residual says whether the answer is trustworthy.
#
# Solved over 260 reports on 2026-10-01:
#
#     Chuck 29.62%  Round 22.32%  Loin 21.26%  Rib 11.40%
#     Plate  7.10%  Brisket 4.95%  Flank 3.35%          -> 100.000%
#
# Summing to 100% was NOT imposed, and the maximum residual across those 260
# reports is 0.008 $/cwt. Choice and Select give the same weights to three
# decimals, which is the expected answer: they are carcass proportions, not
# prices.
#
# AND THEY ARE USDA'S PUBLISHED FIGURES, checked against the documented table
# on 2026-10-01 rather than assumed from the fit. The primal-to-carcass
# yields USDA uses are Rib 11.40, Chuck 29.62, Round 22.32, Loin 21.26,
# Brisket 4.95, Short Plate 7.10, Flank 3.35 -- all seven identical to two
# decimals, and the documented method is the same multiply-and-sum this does
# (u.osu.edu/beef/2021/01/13/boxed-beef, which walks it through: primal rib
# at 329.98 x 0.114 = 37.62 of the cutout).
#
# So why still solve them? Because the fit is then a CHECK rather than a
# guess: if USDA ever re-bases the yields, the page follows them instead of
# drifting against a hard-coded table, and the residual says loudly when the
# identity has stopped holding. A table typed in from a web page in 2026
# would go quietly wrong.

def primal_weights(sections: dict, grade: str):
    """
    (names, weights, rms) for the grade, or (None, None, None) if unsolvable.

    Returns the residual so the caller can refuse to show a decomposition it
    cannot stand behind -- a fit that has gone bad must not be presented as
    an explanation of anything.
    """
    primal = _cut_numbers(sections.get("Composite Primal Values", pd.DataFrame()))
    cutout = _cut_numbers(sections.get("Current Cutout Values", pd.DataFrame()))
    pcol, ccol = f"{grade}_600_900", f"{grade}_600_900_current"
    if primal.empty or cutout.empty or pcol not in primal.columns:
        return None, None, None
    if "primal_desc" not in primal.columns or ccol not in cutout.columns:
        return None, None, None

    P = primal.pivot_table(index="report_date", columns="primal_desc",
                           values=pcol, aggfunc="last").sort_index()
    y = cutout.set_index("report_date")[ccol].sort_index()
    df = P.join(y.rename("_cut"), how="inner").dropna()
    # A RECENT WINDOW, NOT THE WHOLE ARCHIVE -- USDA RE-BASED THE YIELDS.
    #
    # Fitting all 5,775 usable reports back to 2004 gives Brisket 5.16,
    # Chuck 29.77, Flank 3.21 and an rms of 0.0949. Fitting an era gives
    # 0.0032, thirty times better, and two different answers:
    #
    #     2004-2010   Rib 11.31  Chuck 29.56  Brisket 4.97  Flank 3.38
    #     2020-       Rib 11.40  Chuck 29.62  Brisket 4.95  Flank 3.35
    #
    # The second set is USDA's current published table. So the yields
    # changed somewhere between, and a whole-archive fit is a compromise
    # that is correct for no year at all -- it quietly appeared on the
    # primal tiles as "5.2% of carcass" the moment the fetch went deep.
    #
    # This panel always describes TODAY, so it fits today's era. The blown-up
    # residual is the design working rather than failing: it is exactly the
    # signal that said the weights had stopped being one number.
    df = df.tail(FIT_WINDOW)
    names = [c for c in df.columns if c != "_cut"]
    # Need more reports than primals for the system to be determined at all.
    if len(df) <= len(names) + 2 or not names:
        return None, None, None
    A, b = df[names].to_numpy(float), df["_cut"].to_numpy(float)
    try:
        w, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None, None, None
    rms = float(np.sqrt(((b - A @ w) ** 2).mean()))
    return names, w, rms


def cutout_attribution(sections: dict, grade: str):
    """
    Which primals moved the cutout today, and by how much of it.

    WHY A DECOMPOSITION RATHER THAN A LIST OF PRIMAL MOVES. The biggest mover
    is routinely not the biggest cause. On 2026-10-01 Choice brisket fell
    2.23 and chuck fell 9.22, but brisket is 4.95% of the carcass and chuck
    is 29.62%, so chuck did -2.73 of the cutout's -6.00 and brisket did
    -0.11 -- twenty-five times less. Reading the primal column alone gets
    that ordering wrong, which is the whole reason this panel exists.
    """
    names, w, rms = primal_weights(sections, grade)
    if names is None or rms is None or rms > 0.25:
        return None
    primal = _cut_numbers(sections.get("Composite Primal Values", pd.DataFrame()))
    P = primal.pivot_table(index="report_date", columns="primal_desc",
                           values=f"{grade}_600_900", aggfunc="last").sort_index()
    P = P[names].dropna()
    if len(P) < 2:
        return None
    d = P.iloc[-1] - P.iloc[-2]
    out = pd.DataFrame({
        "Primal": names,
        "Move": d.to_numpy(float),
        "Weight": w * 100,
        "Effect": d.to_numpy(float) * w,
    })
    return out.sort_values("Effect"), rms


def cutout_recap(sections: dict, hist: pd.DataFrame, grade: str = "choice") -> list:
    """
    Short bullets on why the cutout did what it did, as a list of strings.

    EVERY BULLET IS ARITHMETIC. This page can say that chuck accounted for
    46% of today's move, because that is a sum. It cannot say why packers
    bid chuck lower, because nothing in LM_XB403 knows -- and a line of
    invented causality in a market report is worse than no line at all. The
    recap therefore reports WHAT moved and HOW MUCH of the move it was, and
    stops where the data stops. Same rule the daily letter runs on: a figure
    is right or it is marked, and prose that is neither gets a human.

    Three things in here that a reader cannot get from the tiles:

    - WHICH primal actually did it, as a share of the move. The tiles give
      the total; the biggest primal MOVE is routinely not the biggest cause.
    - OFFSET. A quiet cutout can be two large primals cancelling, which
      reads as "nothing happened" and is not the same fact at all.
    - Whether the move came on heavier or lighter trade, which is the
      difference between a market and a thin print.
    """
    out = []
    attr = cutout_attribution(sections, grade)
    if attr is None:
        return out
    tbl, _rms = attr
    total = float(tbl["Effect"].sum())
    label = grade.capitalize()

    # 1. the move itself, with the other grade for contrast
    cur = hist[grade].dropna()
    if len(cur) >= 2:
        other = "select" if grade == "choice" else "choice"
        o = hist[other].dropna()
        bit = (f"**{label} cutout {total:+.2f} to {cur.iloc[-1]:,.2f}**")
        if len(o) >= 2:
            od = o.iloc[-1] - o.iloc[-2]
            sp_now = hist["spread"].dropna()
            if len(sp_now) >= 2:
                sp_d = sp_now.iloc[-1] - sp_now.iloc[-2]
                widened = "widened" if sp_d > 0 else ("narrowed" if sp_d < 0 else "flat")
                bit += (f", {other.capitalize()} {od:+.2f} — the Choice–Select "
                        f"spread {widened} {abs(sp_d):.2f} to {sp_now.iloc[-1]:,.2f}")
        out.append(bit + ".")

    # 2. who did it, as a share of the move
    if abs(total) > 0.005:
        lead = tbl.reindex(tbl["Effect"].abs().sort_values(ascending=False).index).iloc[0]
        share = abs(lead["Effect"] / total) * 100
        out.append(
            f"**{lead['Primal'].replace('Primal ', '')} did most of it** — "
            f"{lead['Move']:+.2f} on {lead['Weight']:.2f}% of the carcass is "
            f"{lead['Effect']:+.2f} of the {total:+.2f}, or {share:.0f}% of the move."
        )

    # 3. breadth, and the odd one out
    up = tbl[tbl["Move"] > 0]
    dn = tbl[tbl["Move"] < 0]
    if len(up) and len(dn):
        minority, direction = (up, "higher") if len(up) <= len(dn) else (dn, "lower")
        names = ", ".join(f"{r['Primal'].replace('Primal ', '')} {r['Move']:+.2f}"
                          for _, r in minority.iterrows())
        out.append(f"{len(dn)} of {len(tbl)} primals lower, {len(up)} higher — "
                   f"the {direction} side was {names}.")
    elif len(dn) == len(tbl):
        out.append(f"All {len(tbl)} primals lower — broad, not one cut.")
    elif len(up) == len(tbl):
        out.append(f"All {len(tbl)} primals higher — broad, not one cut.")

    # 4. OFFSET. A quiet cutout built from large opposing moves is a
    #    different fact from a quiet day, and the tiles cannot show it.
    gross = float(tbl["Effect"].abs().sum())
    if gross > 0 and abs(total) < gross * 0.55:
        out.append(
            f"Largely offsetting: {gross:.2f} of gross primal movement netted "
            f"to {total:+.2f}, so the quiet headline hides two sides pulling "
            f"against each other."
        )

    # 5. did it come on trade, or on nobody?
    loads = hist["total_loads"].dropna() if "total_loads" in hist.columns else pd.Series(dtype=float)
    if len(loads) >= 11:
        now, avg = loads.iloc[-1], loads.iloc[-11:-1].mean()
        if avg:
            pct = (now / avg - 1) * 100
            how = ("heavy" if pct >= 15 else "light" if pct <= -15 else "normal")
            out.append(f"Volume {how}: {now:.1f} loads against a 10-day average of "
                       f"{avg:.1f} ({pct:+.0f}%).")

    # 6. the loudest CUTS, volume-screened -- a thin print will out-move
    #    everything on percentage and mean nothing.
    cuts = _cut_numbers(sections.get(f"{label} Cuts", pd.DataFrame()))
    if not cuts.empty:
        piv = cuts.pivot_table(index="report_date", columns="item_description",
                               values="weighted_average", aggfunc="last").sort_index()
        vol = cuts.pivot_table(index="report_date", columns="item_description",
                               values="total_pounds", aggfunc="last").sort_index()
        if len(piv) >= 2:
            d = (piv.iloc[-1] - piv.iloc[-2]).dropna()
            lbs = vol.iloc[-1].reindex(d.index)
            floor = lbs.median()
            keep = d[lbs >= floor]
            if len(keep):
                hi, lo = keep.idxmax(), keep.idxmin()
                out.append(
                    f"Among cuts trading at least the day's median {floor:,.0f} lbs: "
                    f"**{hi}** {keep[hi]:+.2f}, **{lo}** {keep[lo]:+.2f}. "
                    f"Thinner cuts moved further and are left out on purpose."
                )
    return out


# ── Individual cuts ──────────────────────────────────────────────────────────
#
# THE DATA WAS ALREADY BEING DOWNLOADED AND THROWN AWAY. fetch_lmr asks for
# allSections, which is eleven sections including "Choice Cuts" (42 items),
# "Select Cuts" (42) and "Composite Primal Values" (7). The page used three of
# them. So this view costs no extra request and no extra second -- it reads
# what the existing fetch already paid for.

# EVERY numeric column across all three sections, because they do not share a
# schema: the cut sections carry weighted_average/total_pounds, and Composite
# Primal Values carries choice_600_900/select_600_900 instead. Leaving the
# primal pair out left them as STRINGS and the panel died on "str - str" the
# first time it rendered -- a column list that was right for two sections out
# of three.
CUT_NUM_COLS = ("weighted_average", "total_pounds", "number_trades",
                "price_range_low", "price_range_high",
                "choice_600_900", "select_600_900",
                # Current Cutout Values, a FOURTH schema. primal_weights()
                # read these and only worked because .to_numpy(float) parses
                # a comma-free string -- which the cutout is today at ~$376
                # and the ribeye already is not at $1,361. Coerce them here
                # rather than rely on the value staying under four figures.
                "choice_600_900_current", "select_600_900_current")


# The columns where 0.00 means "did not trade", never "cost nothing".
CUT_PRICE_COLS = ("weighted_average", "price_range_low", "price_range_high",
                  "choice_600_900", "select_600_900",
                  "choice_600_900_current", "select_600_900_current")


def _cut_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strings to numbers, with the two traps USDA sets in this feed.

    COMMAS. These arrive as "239,801" and "1,361.58". pd.to_numeric on those
    yields NaN silently, which empties the table rather than raising, so the
    separators come out first.

    AND 0.00 MEANS "NO TRADE", NOT A PRICE. When a cut did not trade in a
    grade on a report, USDA prints 0.00 rather than leaving it blank. Over
    259 reports that is 978 zeros across 18 Choice cuts and **3,612 across 38
    of the 42 Select cuts** -- not an edge case, the normal state of the
    thinner cuts.

    Left as zeros they are wrong three separate ways, all of them quiet:
    the Select column shows a cut trading at $0.00; the Choice-Select spread
    becomes the entire Choice price wearing the word "spread"; and the chart's
    y-axis is dragged to zero, which is how this was found -- a ribeye running
    $826-$1,417 was plotted on an axis from -85 to 1502 with 40% of the panel
    empty, so a $130 move read as a flat line.

    NaN is the honest value: the cut did not trade, so there is no price.
    """
    out = df.copy()
    for c in CUT_NUM_COLS:
        if c in out.columns:
            out[c] = pd.to_numeric(
                out[c].astype(str).str.replace(",", "", regex=False), errors="coerce")
    for c in CUT_PRICE_COLS:
        if c in out.columns:
            # mask(), not replace(0, pd.NA): the column is float64 from
            # to_numeric, and pd.NA will not cast back into it -- that raised
            # "float() argument must be a string or a real number, not
            # 'NAType'". mask leaves a plain NaN in a float column.
            out[c] = out[c].mask(out[c] == 0)
    return out


def cuts_panel(sections: dict, years: int = 1):
    """
    Every individual cut, its move since the prior report, and its history.

    WEIGHT IS SHOWN BESIDE EVERY PRICE, and that is the point of the table
    rather than a decoration. These are negotiated sales: a cut that traded
    4,700 lbs and one that traded 420,000 lbs both print a weighted average,
    and the first will swing several percent on a handful of loads. On
    2026-10-01 the lip-on ribeye printed 1,417.50 on 8,783 lbs and then
    1,361.58 on 239,801 lbs the next day -- a "-55.92 day" that is mostly the
    thin print correcting. Sorting by percent move without looking at the
    pounds column will mislead you about that every week.
    """
    # THE DEEP PULL HAPPENS HERE, not at page load. The Cutout view needs two
    # reports of cuts for the recap's last bullet; this view needs years of
    # them for the chart, and paying that on every visit to the other view
    # would be the one slow thing on the page.
    deep = {}
    if years:
        with st.spinner(f"Loading {years} year(s) of individual cuts…"):
            try:
                deep = fetch_cut_sections(int(years))
            except Exception:
                deep = {}
    choice = _cut_numbers(deep.get("Choice Cuts",
                                   sections.get("Choice Cuts", pd.DataFrame())))
    select = _cut_numbers(deep.get("Select Cuts",
                                   sections.get("Select Cuts", pd.DataFrame())))
    primal = _cut_numbers(sections.get("Composite Primal Values", pd.DataFrame()))

    if choice.empty:
        st.warning("USDA returned no individual-cut sections for this report.")
        return

    piv = choice.pivot_table(index="report_date", columns="item_description",
                             values="weighted_average", aggfunc="last").sort_index()
    vol = choice.pivot_table(index="report_date", columns="item_description",
                             values="total_pounds", aggfunc="last").sort_index()
    if len(piv) < 2:
        st.warning("Only one report in range — no day-over-day move to show.")
        return

    last, prev = piv.index[-1], piv.index[-2]
    st.markdown(
        f'<div class="sec-header">Individual Cuts — {last:%b %d, %Y} '
        f'vs {prev:%b %d}</div>', unsafe_allow_html=True)

    # ── primal strip ────────────────────────────────────────────────────────
    if not primal.empty and "primal_desc" in primal.columns:
        ppiv = primal.pivot_table(index="report_date", columns="primal_desc",
                                  values="choice_600_900", aggfunc="last").sort_index()             if "choice_600_900" in primal.columns else pd.DataFrame()
        if not ppiv.empty and len(ppiv) > 1:
            # The carcass share beside each primal, so the tiles say how much
            # a move there is worth. Chuck at 29.62% and brisket at 4.95%
            # move the cutout six times differently for the same $1.
            _wn, _wv, _wr = primal_weights(sections, "choice")
            share = dict(zip(_wn, _wv)) if _wn and _wr is not None and _wr <= 0.25 else {}
            names = [c for c in ppiv.columns if pd.notna(ppiv.iloc[-1][c])]
            for chunk in [names[i:i + 4] for i in range(0, len(names), 4)]:
                cols = st.columns(len(chunk))
                for col, name in zip(cols, chunk):
                    cur = ppiv.iloc[-1][name]
                    pri = ppiv.iloc[-2][name]
                    d = (cur - pri) if pd.notna(pri) else None
                    lbl = str(name)
                    if name in share:
                        lbl += f" · {share[name] * 100:.1f}% of carcass"
                    with col:
                        st.markdown(tile(lbl, fmt(cur), delta_html(d)),
                                    unsafe_allow_html=True)
            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── the movers table ────────────────────────────────────────────────────
    def _asof(when):
        """
        Each cut's last traded price on or before `when`.

        ffill WITH A LIMIT, because a cut that stopped trading must not keep
        reporting its last price forever -- several of the thin cuts go weeks
        between prints, and carrying one forward a month would invent a
        "no change" that never happened. Five reports is a trading week; past
        that the comparison is blank, which is the honest answer.
        """
        sub = piv[piv.index <= when]
        if sub.empty:
            return pd.Series(index=piv.columns, dtype=float)
        return sub.ffill(limit=5).iloc[-1]

    base = piv.loc[prev]
    wk_at, mo_at = last - pd.Timedelta(days=7), last - pd.Timedelta(days=30)
    wk, mo = _asof(wk_at), _asof(mo_at)
    now = piv.loc[last]

    chg = now - base
    tbl = pd.DataFrame({
        "Cut": piv.columns,
        "$/cwt": now.values,
        "Day $": chg.values,
        "Day %": (chg / base * 100).values,
        "Wk $": (now - wk).values,
        "Wk %": ((now - wk) / wk * 100).values,
        "Mo $": (now - mo).values,
        "Mo %": ((now - mo) / mo * 100).values,
        "Pounds": vol.loc[last].reindex(piv.columns).values,
    # ONLY $/cwt is required. A cut that traded today but not yesterday still
    # belongs in the table with a blank day change -- dropping it hid cuts
    # that had a perfectly good week-over-week move.
    }).dropna(subset=["$/cwt"]).sort_values("Day %", ascending=False)

    sel_last = (select.pivot_table(index="report_date", columns="item_description",
                                   values="weighted_average", aggfunc="last")
                .sort_index().iloc[-1] if not select.empty else pd.Series(dtype=float))
    # reindex, NOT a .get() comprehension: .get returns None for a missing cut
    # and a column of mixed None/float renders the word "None" in the table
    # rather than an empty cell. reindex gives NaN, which Streamlit leaves blank.
    tbl["Select"] = sel_last.reindex(tbl["Cut"]).to_numpy(dtype=float)
    # Choice over Select on the same cut -- the quality spread cut by cut,
    # which the composite number cannot show.
    tbl["Ch-Se"] = tbl["$/cwt"] - tbl["Select"]

    st.dataframe(
        tbl, hide_index=True, use_container_width=True, height=430,
        column_config={
            "Cut": st.column_config.TextColumn(width="large"),
            "$/cwt": st.column_config.NumberColumn(format="$%.2f"),
            "Day $": st.column_config.NumberColumn(format="%+.2f"),
            "Day %": st.column_config.NumberColumn(format="%+.2f%%"),
            "Wk $": st.column_config.NumberColumn(
                format="%+.2f", help="Against the last report on or before 7 days ago"),
            "Wk %": st.column_config.NumberColumn(format="%+.2f%%"),
            "Mo $": st.column_config.NumberColumn(
                format="%+.2f", help="Against the last report on or before 30 days ago"),
            "Mo %": st.column_config.NumberColumn(format="%+.2f%%"),
            "Pounds": st.column_config.NumberColumn(format="%,d", help="Pounds traded "
                                                    "on this report — a thin print "
                                                    "moves several percent on a few loads"),
            "Select": st.column_config.NumberColumn(format="$%.2f"),
            "Ch-Se": st.column_config.NumberColumn("Ch−Se", format="%+.2f"),
        },
    )
    st.caption(
        f"Sortable. **Read the Pounds column with the percentage** — these are "
        f"negotiated sales, and a cut that traded a few thousand pounds will "
        f"swing on a single load. **Wk** is against {wk_at:%b %d} and **Mo** "
        f"against {mo_at:%b %d} — the last report on or before those dates, "
        f"blank if the cut had not traded within a week of them. Blank Select "
        f"means that cut did not trade in the Select grade on this report."
    )

    # ── one cut's history ───────────────────────────────────────────────────
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">One cut over time</div>', unsafe_allow_html=True)

    names = sorted(piv.columns)
    # Default to the lip-on ribeye: the biggest-volume single cut on the
    # report and the one that gets asked about.
    default = next((i for i, n in enumerate(names) if "ribeye, lip-on" in n.lower()), 0)
    pick = st.selectbox("Cut", names, index=default, label_visibility="collapsed")

    line = piv[pick].dropna()
    _span = [line.min(), line.max()]
    fig_c = go.Figure()
    fig_c.add_trace(go.Scatter(
        x=line.index, y=line.values, name="Choice", mode="lines",
        line=dict(color=CHOICE_COLOR, width=2),
        hovertemplate="<b>Choice</b>: $%{y:.2f}<extra></extra>"))
    if not select.empty:
        spiv = select.pivot_table(index="report_date", columns="item_description",
                                  values="weighted_average", aggfunc="last").sort_index()
        if pick in spiv.columns:
            sl = spiv[pick].dropna()
            if not sl.empty:
                fig_c.add_trace(go.Scatter(
                    x=sl.index, y=sl.values, name="Select", mode="lines",
                    line=dict(color=SELECT_COLOR, width=2),
                    hovertemplate="<b>Select</b>: $%{y:.2f}<extra></extra>"))
                _span = [min(_span[0], sl.min()), max(_span[1], sl.max())]

    # AN EXPLICIT Y RANGE, because autorange put the floor at zero. Measured
    # on the live chart: for a ribeye running 826-1417 the axis came back
    # [-78.75, 1496.25], so about 40% of the plot was empty space under the
    # line and a $130 move looked like a flat drift. A single cut never
    # trades near zero, so there is nothing to be gained from a zero baseline
    # here -- the question is always how far it has moved, not its ratio to
    # nothing. 6% padding keeps the line off the frame.
    _pad = max(1.0, (_span[1] - _span[0]) * 0.06)
    fig_c.update_layout(
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color=DM_TEXT, size=11), bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=55, r=20, t=15, b=40),
        xaxis=dict(**AXIS, title="", type="date"),
        yaxis=dict(**AXIS, title="$/cwt", tickprefix="$",
                   range=[_span[0] - _pad, _span[1] + _pad]),
        height=340,
    )
    st.plotly_chart(fig_c, use_container_width=True)

    # ESCAPE THE DOLLAR SIGNS. Streamlit's markdown treats a $...$ pair as
    # LaTeX, so "$1,361.58 · week ago $1,346.60" rendered as mathematics --
    # the two prices vanished into an italic run reading "1,361.58 ⋅
    # weekago1,346.60". Every figure on this line is a price, so every one of
    # them needs it. The tiles above are unaffected: they go through
    # st.markdown with unsafe_allow_html, which is HTML, not markdown.
    d = "\\$"
    cur = line.iloc[-1]
    bits = [f"**{pick}** — {d}{cur:,.2f}"]
    for label, days in (("week", 7), ("month", 30)):
        past = line[line.index <= line.index[-1] - pd.Timedelta(days=days)]
        if len(past):
            v = past.iloc[-1]
            bits.append(f"{label} ago {d}{v:,.2f} "
                        f"({cur - v:+,.2f}, {(cur / v - 1) * 100:+.1f}%)")
    lo, hi = line.min(), line.max()
    bits.append(f"range over {len(line)} reports {d}{lo:,.2f}–{d}{hi:,.2f}")
    st.caption(" · ".join(bits))


# ── Data Fetching ────────────────────────────────────────────────────────────

def _lmr_session() -> requests.Session:
    """Requests session with retry + backoff for the slow USDA LMR API."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=3,           # waits 3, 9, 27 s between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


# ── Archive depth, measured 2026-10-01 ───────────────────────────────────────
#
# LM_XB403 goes back MUCH further than this page was reading, and the reason
# it was not is the fetch shape rather than the archive:
#
#   section                 rows    span                     cost
#   Current Cutout Values   6,474   2001-04-03 -> today      6.0s / 5 MB
#   Current Volume          6,474   2001-04-03 -> today      7.3s / 6.5 MB
#   Choice Cuts            ~13k/yr  2001-04-03 -> today      ~7s per year
#
# USABLE values start LATER than the rows do, and differently for each: the
# composite cutout is null until 2004-01-05, while the individual cuts carry
# prices from 2001-04-03, the very first report. So the cuts have a longer
# usable history than the cutout they add up to. 2000 does not exist in this
# report at all.
#
# TWO THINGS MADE THE OLD DEPTH LOOK LIKE THE ARCHIVE'S LIMIT:
#
# - allSections=true returns all eleven sections at once and costs 91 MB and
#   30s for a couple of years. Asking for ONE section as a path segment is
#   about fifteen times cheaper, which is what makes full history viable.
# - The API caps any single response at exactly 100,000 ROWS, silently. A
#   full Choice Cuts pull returns 100,000 rows ending 2017-05-25 and looks
#   for all the world like the series starting there. It does not; the cap
#   truncated it. Paging by calendar year (~13k rows each) walks straight
#   past it, and that is the only reason 2001-2016 is on this page.

ARCHIVE_START = 2001          # first report_date in LM_XB403
CUTOUT_FIRST_VALUE = "2004-01-05"   # composite is null before this

# Reports the primal-weight fit is run over. Long enough to be stable, short
# enough to sit entirely inside the CURRENT yield table -- see the re-basing
# note in primal_weights(). A year is both.
FIT_WINDOW = 260


def _lmr_get(section: str, params: dict) -> pd.DataFrame:
    sess = _lmr_session()
    resp = sess.get(f"{LMR_BASE}/{REPORT_ID}/{section}", params=params, timeout=300)
    resp.raise_for_status()
    rows = resp.json().get("results") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    return df.dropna(subset=["report_date"]).sort_values("report_date")


@st.cache_data(ttl=7200, persist="disk", show_spinner=False)
def fetch_thin_sections() -> dict:
    """
    The one-row-per-report sections, at FULL archive depth.

    These are small enough that there is no reason to window them: the whole
    25 years is 11.5 MB and about 13 seconds, once per cache period. Primal
    Values is seven rows a report, so ~45k -- still inside the 100k cap.
    """
    out = {}
    for name in ("Summary", "Current Cutout Values", "Current Volume",
                 "Change From Prior Day", "Composite Primal Values"):
        try:
            df = _lmr_get(name, {"lastReports": 9999})
        except Exception:
            df = pd.DataFrame()
        if not df.empty:
            out[name] = df
    return out


@st.cache_data(ttl=7200, persist="disk", show_spinner=False)
def fetch_cut_sections(years: int, _today=None) -> dict:
    """
    Choice and Select Cuts for the last `years` calendar years.

    PAGED BY YEAR BECAUSE OF THE 100,000-ROW CAP, not for politeness. A
    single request for everything comes back truncated and looks complete.
    Each year is ~13k rows and ~7s, so the cost is linear and predictable,
    and `years` is the reader's choice rather than a number baked in here.
    """
    this_year = (_today or datetime.now()).year
    # ONE MORE CALENDAR YEAR THAN ASKED FOR, because the pages are calendar
    # years and the request is a span. `years=1` starting at this January
    # would be four days of history on the 4th of January and the label would
    # be a lie; including last year guarantees at least the span named, at
    # the cost of one extra page.
    first = max(ARCHIVE_START, this_year - years)
    out = {}
    for name in ("Choice Cuts", "Select Cuts"):
        frames = []
        for yr in range(first, this_year + 1):
            try:
                frames.append(_lmr_get(name, {"q": f"report_date=01/01/{yr}:12/31/{yr}"}))
            except Exception:
                continue
        frames = [f for f in frames if not f.empty]
        if frames:
            out[name] = pd.concat(frames, ignore_index=True).sort_values("report_date")
    return out


# persist="disk" survives app sleep/wake cycles — users never hit a cold fetch
@st.cache_data(ttl=7200, persist="disk", show_spinner=False)
def fetch_lmr(last_n: int = 260):
    """
    Pull allSections for the last N reports from the USDA LMR API.
    Returns a dict keyed by section name, each value a DataFrame.
    """
    url  = f"{LMR_BASE}/{REPORT_ID}/"
    sess = _lmr_session()
    resp = sess.get(url, params={"lastReports": last_n, "allSections": "true"}, timeout=60)
    resp.raise_for_status()

    payload = resp.json()
    sections = {}
    for sec in (payload if isinstance(payload, list) else [payload]):
        name    = sec.get("reportSection", "")
        results = sec.get("results", [])
        if results:
            df = pd.DataFrame(results)
            df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
            df = df.dropna(subset=["report_date"]).sort_values("report_date")
            sections[name] = df
    return sections


@st.cache_data(ttl=7200, persist="disk", show_spinner=False)
def fetch_grading_weekly() -> pd.DataFrame:
    """Fetch weekly Pct_Choice_CW from LMR report 2700 (lastReports=200 ≈ 4 yrs)."""
    url  = f"{LMR_BASE}/{GRADING_ID}/"
    sess = _lmr_session()
    resp = sess.get(url, params={"lastReports": 200, "allSections": "true"}, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    for sec in (payload if isinstance(payload, list) else [payload]):
        if sec.get("reportSection") == "Weekly Fed Cattle Comprehensive":
            df = pd.DataFrame(sec["results"])
            df["report_date"]    = pd.to_datetime(df["report_date"], errors="coerce")
            df["pct_choice"]     = pd.to_numeric(df.get("Pct_Choice_CW"), errors="coerce")
            df["published_date"] = df.get("published_date", "")
            return df[["report_date", "pct_choice", "published_date"]].dropna(subset=["report_date"]).sort_values("report_date")
    return pd.DataFrame()


# ── The MORNING cutout ───────────────────────────────────────────────────────
# A SECOND USDA REPORT, NOT A SLICE OF THIS ONE. Everything above reads
# LM_XB403, the afternoon close. LM_XB402 is the 9:30am read, published around
# 10:55 CT, and it regularly tells a different story -- on 2026-10-06 it said
# Choice +4.20 and the day closed +0.67.
#
# It has no API and no history anywhere; see am_cutout's docstring, which
# records the probes so nobody repeats them. The fetch is a PDF from
# www.ams.usda.gov -- the host letter/sources.py already reads from the
# deployed app, and NOT marsapi, which Community Cloud cannot reach.

@st.cache_data(ttl=900, show_spinner=False)
def fetch_am_cutout(schema: int = am_cutout.SCHEMA) -> dict:
    """
    Today's morning cutout. `schema` keys the cache, and BOTH halves matter: no leading underscore (Streamlit drops underscore-prefixed arguments from the key) and the CALLER must pass it (a default is never hashed).
    The old `_schema` form keyed nothing at all. It was
    in the signature ONLY to key the
    cache -- st.cache_data never notices that am_cutout.py changed. See
    am_cutout.SCHEMA.
    """
    return am_cutout.fetch_am()


@st.cache_data(ttl=900, show_spinner=False)
def fetch_am_history(schema: int = am_cutout.SCHEMA) -> pd.DataFrame:
    """The mornings banked so far. Empty until this has run for a few days."""
    return am_cutout.history()


def am_panel(am_row: dict, pm_hist: pd.DataFrame, banked: pd.DataFrame):
    """
    The morning read, its own tiles, and what it did by the close.

    PM FIGURES ARE NEVER RECOMPUTED HERE. The close comes from `pm_hist`, the
    frame the rest of the page is built on, so the two sessions cannot
    disagree about the same day -- the failure CLAUDE.md records twice for the
    letter and the dashboard quoting the same FCI.
    """
    if am_row.get("error"):
        st.warning(f"⏳ **Morning cutout unavailable** — {am_row['error']}")
        return

    rd = am_row.get("report_date")
    st.markdown(
        '<div class="sec-header">Morning Cutout — USDA LM_XB402, values as of 9:30am</div>',
        unsafe_allow_html=True)

    cols = st.columns(4)
    with cols[0]:
        st.markdown(tile("Choice", fmt(am_row["choice"]),
                         delta_html(am_row.get("change_choice")), "tile-choice"),
                    unsafe_allow_html=True)
    with cols[1]:
        st.markdown(tile("Select", fmt(am_row["select"]),
                         delta_html(am_row.get("change_select")), "tile-select"),
                    unsafe_allow_html=True)
    with cols[2]:
        st.markdown(tile("Choice–Select Spread", fmt(am_row["spread"]), cls="tile-spread"),
                    unsafe_allow_html=True)
    with cols[3]:
        st.markdown(tile("Loads So Far", fmt_loads(am_row.get("loads")), cls="tile-vol"),
                    unsafe_allow_html=True)

    # PARENTHESISED ON PURPOSE. Written as a bare `f"..." if rd else ""`
    # followed by more string literals, the conditional takes the implicit
    # concatenation as its ELSE branch -- so the caption silently loses every
    # sentence after the first on exactly the days the date IS present.
    st.caption(money_md(
        (f"Morning report for {rd:%b %d, %Y}. " if rd else "")
        + "The change is USDA's own, against the prior afternoon close. "
        + "USDA's 5-day simple average — the five sessions **before** this one — is "
        + f"{fmt(am_row.get('avg5_choice'))} Choice, "
        + f"{fmt(am_row.get('avg5_select'))} Select."
    ))

    # ── What the morning read did by the close ──────────────────────────────
    close = None
    if rd is not None and not pm_hist.empty:
        same = pm_hist[pm_hist["report_date"].dt.date == rd]
        if not same.empty:
            close = same.iloc[-1]

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if close is not None:
        cfade = close["choice"] - am_row["choice"]
        sfade = close["select"] - am_row["select"]
        st.markdown('<div class="sec-header">Morning vs Close</div>', unsafe_allow_html=True)
        cols = st.columns(4)
        with cols[0]:
            st.markdown(tile("Choice AM", fmt(am_row["choice"]), cls="tile-choice"),
                        unsafe_allow_html=True)
        with cols[1]:
            st.markdown(tile("Choice PM", fmt(close["choice"]), delta_html(cfade), "tile-choice"),
                        unsafe_allow_html=True)
        with cols[2]:
            st.markdown(tile("Select AM", fmt(am_row["select"]), cls="tile-select"),
                        unsafe_allow_html=True)
        with cols[3]:
            st.markdown(tile("Select PM", fmt(close["select"]), delta_html(sfade), "tile-select"),
                        unsafe_allow_html=True)
        st.caption(
            f"The close moved {cfade:+.2f} on Choice and {sfade:+.2f} on Select away from "
            "the morning print. The delta on each PM tile is that move, not the day change."
        )
    else:
        st.info(
            "**The afternoon report is not out yet.** The morning read above is the "
            "newest figure USDA has published today; the close lands around 3pm CT."
        )

    # ── The look-back ───────────────────────────────────────────────────────
    # EMPTY IS THE EXPECTED STATE AT FIRST, and the caption says why rather
    # than letting an empty panel read as a broken one. USDA keeps no archive
    # of LM_XB402 at all, so this series starts the day the portal first
    # recorded one and can never be back-filled.
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Morning vs Close — History</div>',
                unsafe_allow_html=True)

    hist_fade = am_cutout.fade(banked, pm_hist)
    if hist_fade.empty:
        st.caption(
            "No banked mornings with a close yet. USDA overwrites LM_XB402 in place "
            "every morning and keeps no archive of it, so this history cannot be "
            "back-filled — it fills one day at a time, from whichever days this page "
            "is opened after the morning release."
        )
        return

    show = hist_fade.sort_values("report_date", ascending=False).head(60)
    st.dataframe(
        pd.DataFrame({
            "Date":        show["report_date"].dt.strftime("%b %d, %Y"),
            "Choice AM":   show["choice_am"],
            "Choice PM":   show["choice_pm"],
            "Choice fade": show["choice_fade"],
            "Select AM":   show["select_am"],
            "Select PM":   show["select_pm"],
            "Select fade": show["select_fade"],
        }),
        hide_index=True, use_container_width=True,
        column_config={
            c: st.column_config.NumberColumn(c, format="%.2f")
            for c in ("Choice AM", "Choice PM", "Select AM", "Select PM")
        } | {
            c: st.column_config.NumberColumn(c, format="%+.2f")
            for c in ("Choice fade", "Select fade")
        },
    )
    med = show["choice_fade"].median()
    st.caption(
        f"{len(hist_fade)} day(s) banked. Median Choice fade {med:+.2f} — "
        "the close minus the morning print, so a negative number is a morning "
        "read the day did not hold."
    )


def build_history(sections: dict) -> pd.DataFrame:
    """Merge Cutout + Volume sections into a clean daily DataFrame."""
    cutout = sections.get("Current Cutout Values", pd.DataFrame())
    volume = sections.get("Current Volume",        pd.DataFrame())

    if cutout.empty:
        raise ValueError("'Current Cutout Values' section returned no data.")

    df = cutout[["report_date"]].copy()
    df["choice"] = pd.to_numeric(cutout.get("choice_600_900_current"), errors="coerce")
    df["select"] = pd.to_numeric(cutout.get("select_600_900_current"), errors="coerce")
    # DROP THE EMPTY LEAD-IN. LM_XB403 has report_date rows from 2001-04-03 but
    # carries no composite value until 2004-01-05, so keeping them put nearly
    # three blank years on the left of every chart once the fetch went to full
    # depth. The rows are real and the values are not; a chart that starts
    # where the data starts is the honest one.
    df = df[df["choice"].notna() | df["select"].notna()]
    df["spread"] = df["choice"] - df["select"]

    if not volume.empty:
        vol = volume[["report_date"]].copy()
        for c in ["choice_volume_loads", "select_volume_loads",
                  "trimmings_volume_loads", "coarse_volume_loads"]:
            vol[c] = pd.to_numeric(volume.get(c), errors="coerce")
        vol["total_loads"] = (
            vol["choice_volume_loads"].fillna(0) +
            vol["select_volume_loads"].fillna(0) +
            vol["trimmings_volume_loads"].fillna(0) +
            vol["coarse_volume_loads"].fillna(0)
        )
        vol["choice_loads"] = vol["choice_volume_loads"]
        vol["select_loads"] = vol["select_volume_loads"]
        df = df.merge(vol[["report_date", "total_loads", "choice_loads", "select_loads"]],
                      on="report_date", how="left")
    else:
        df["total_loads"]  = None
        df["choice_loads"] = None
        df["select_loads"] = None

    return df.reset_index(drop=True)


def changes(df: pd.DataFrame, col: str):
    """Return (current, day_chg, month_chg, year_chg)."""
    valid = df[df[col].notna()]
    if valid.empty:
        return None, None, None, None
    cur  = valid.iloc[-1]
    cval = cur[col]
    cdt  = cur["report_date"]

    def prior(delta):
        sub = valid[valid["report_date"] <= cdt - delta]
        return sub.iloc[-1][col] if not sub.empty else None

    # THE PRIOR REPORT, NOT A CALENDAR OFFSET -- this is the "Day Change"
    # tile and it was wrong every day there was a report yesterday.
    #
    # It read prior(timedelta(days=2)), which takes the last row on or before
    # today minus two days. On 2026-10-01 that is <= 09/29, so it skipped
    # 09/30 completely and quoted a TWO-session move as a day change:
    #
    #     dashboard   Choice 376.79 - 382.66 (09/29) = -5.87
    #                 Select 352.89 - 364.48 (09/29) = -11.59
    #     USDA sheet  Choice 376.79 - 382.79 (09/30) =  -6.00
    #                 Select 352.89 - 360.59 (09/30) =  -7.70
    #
    # Reported by Ross on 2026-10-01 against ams_2453.pdf: the cutout values
    # matched and only the changes did not, which is exactly the shape of
    # this bug -- the level comes straight from the feed and only the
    # subtraction was reaching back too far.
    #
    # iloc[-2] is the prior PUBLISHED report, which is USDA's own basis and
    # handles weekends and holidays for free: Monday 09/28's published +1.65
    # is against Friday 09/25. A day offset cannot do that without a calendar.
    p1   = valid.iloc[-2][col] if len(valid) > 1 else None
    p30  = prior(timedelta(days=30))
    p365 = prior(timedelta(days=365))

    return (
        cval,
        cval - p1   if p1   is not None else None,
        cval - p30  if p30  is not None else None,
        cval - p365 if p365 is not None else None,
    )


def prior_level(df: pd.DataFrame, col: str, days: int):
    """
    What `col` actually WAS `days` ago, and the report it comes from.

    THE SELECTION RULE IS COPIED FROM changes() ON PURPOSE -- the last report
    on or before today minus `days`. The tiles show this level and that
    function's delta side by side, so if the two ever picked different rows
    the page would print a prior price and a change that do not subtract to
    the current one, and a reader doing the arithmetic would be the one to
    find it. tests/test_cutout_prior_level.py asserts prior + delta == current
    rather than trusting the two to stay in step.

    USDA does not publish on a fixed calendar, so "a month ago" lands on the
    nearest session at or before the date, not on the date. The tile prints
    which one.
    """
    valid = df[df[col].notna()]
    if valid.empty:
        return None, None
    cdt = valid.iloc[-1]["report_date"]
    sub = valid[valid["report_date"] <= cdt - timedelta(days=days)]
    if sub.empty:
        return None, None
    row = sub.iloc[-1]
    return row[col], row["report_date"]


def five_day(df: pd.DataFrame, col: str):
    """
    USDA's 5-day simple average: the five sessions BEFORE the one being
    reported, NOT the trailing five including it.

    THE WINDOW IS iloc[-6:-1] AND IT MUST STAY THAT. letter/sources.py prints
    the same figure in the daily letter and letter/rundown.py puts it on the
    client slide, both on that window -- and CLAUDE.md records two mornings
    lost to the letter and a dashboard quoting one number and disagreeing,
    each defensible, neither raising. `tail(5)` is the natural thing to write
    and is the one that breaks it: for 2026-10-05 it gives Choice 379.38
    where the published figure is 378.94.

    It is also USDA's own convention, which is the real argument for it.
    The morning report prints "Current 5 Day Simple Average: 378.94" on
    2026-10-06, and 378.94 is the mean of 10/05, 10/02, 10/01, 09/30 and
    09/29 -- the five sessions before it, to the cent. So this is not a house
    preference that happens to match; it reproduces what USDA publishes.

    The excluding window is also the more useful one: it is a fixed benchmark
    the new print is read AGAINST, rather than a window that chases it.
    """
    valid = df[df[col].notna()]
    if len(valid) < 6:
        return None
    return float(valid[col].iloc[-6:-1].mean())


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image(JSA_LOGO_WHITE, use_container_width=True)
    st.markdown("<hr>", unsafe_allow_html=True)

    # THE CUTOUT TREND IS NO LONGER WINDOWED. The thin sections are the whole
    # archive for 13 seconds, so there is nothing to choose -- the chart's own
    # 1M/3M/6M/YTD/1Y/All buttons do the zooming, over 2004 onward rather than
    # over whatever was fetched.
    st.markdown('<div class="sec-header">Cuts History</div>', unsafe_allow_html=True)
    cuts_years = st.selectbox(
        "Years of individual-cut history",
        [1, 3, 5, 10, 26],
        index=0,
        format_func=lambda y: {1: "1 Year", 3: "3 Years", 5: "5 Years",
                               10: "10 Years", 26: "All (2001→)"}[y],
        label_visibility="collapsed",
        help="Individual cuts are paged a year at a time, about 7 seconds each, "
             "then cached for two hours. The cutout trend always loads its full "
             "archive and is not affected by this.",
    )
    st.caption("Cutout trend always loads 2004→ in full.")

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Data Refresh</div>', unsafe_allow_html=True)
    auto_refresh = st.toggle("Auto-refresh (30 min)", value=False)
    if st.button("↺  Refresh Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="color:{DM_MUTED};font-size:0.72rem;line-height:1.6;">'
        f'Source: USDA AMS Livestock Mandatory Reporting<br><br>'
        # TWO REPORTS, NOT ONE REPORT PUBLISHED TWICE. This read
        # "Report: LM_XB403 ... Published twice daily", which conflated them:
        # XB403 goes out once, in the afternoon. The morning figures are
        # XB402, a separate report with a separate slug and no data feed.
        f'<b>LM_XB402</b> — morning, values as of 9:30am, out ~10:55 CT<br>'
        f'<b>LM_XB403</b> — afternoon close, out ~2:55 CT<br><br>'
        f'The morning report is published only as a PDF and USDA keeps no '
        f'archive of it, so its history is banked here one day at a time.'
        f'<br><br>'
        f'Cache: 30 min. Use <b>Refresh Now</b> to force reload.</div>',
        unsafe_allow_html=True,
    )


# ── Load Data ────────────────────────────────────────────────────────────────

with st.spinner("Loading USDA beef cutout data…"):
    try:
        sections = fetch_thin_sections()
        # A SHALLOW slice of the cuts rides along for the Cutout view: the
        # recap's last bullet names the day's loudest cuts, and that needs
        # two reports, not two decades. The deep pull happens only when the
        # reader actually opens Individual Cuts.
        try:
            for _k, _v in fetch_cut_sections(1).items():
                sections.setdefault(_k, _v)
        except Exception:
            pass
        hist     = build_history(sections)
        load_ok  = True
        err_msg  = ""
    except Exception as e:
        load_ok  = False
        err_msg  = str(e)
        sections = {}
        hist     = pd.DataFrame()

# ITS OWN try, AND ITS OWN HOST. The morning report is a PDF from
# www.ams.usda.gov; everything above is the LMR JSON API. Folding it into the
# block above would mean an LMR outage blanking a view that does not read LMR
# at all -- the mistake the Saturday Slaughter tab's four-line guard exists to
# prevent (CLAUDE.md, "The Saturday Slaughter view").
try:
    am_row = fetch_am_cutout(am_cutout.SCHEMA)
except Exception as e:
    am_row = {"error": str(e)}

# Record it, if it is not recorded already. OPPORTUNISTIC: Community Cloud has
# no scheduler, so the series fills on the days somebody opens this page after
# the morning release. See am_cutout.bank().
am_bank_msg = ""
if not am_row.get("error") and am_cutout.enabled():
    am_bank_msg = am_cutout.ensure_table() or am_cutout.bank(am_row)
    if am_bank_msg == "banked":
        fetch_am_history.clear()
        am_bank_msg = ""

try:
    am_banked = fetch_am_history(am_cutout.SCHEMA)
except Exception:
    am_banked = pd.DataFrame()


# ── Header ───────────────────────────────────────────────────────────────────

c1, c2 = st.columns([7, 3])
with c1:
    st.markdown(
        f"<h1 style='color:{DM_TEXT};margin:0;padding:0;font-size:1.9rem;'>"
        "JSA - Daily Beef Cutout</h1>"
        f"<div style='color:{DM_MUTED};font-size:0.8rem;margin-top:2px;'>"
        "Choice &amp; Select Composite 600–900 lbs · "
        "USDA LM_XB402 (morning) &amp; LM_XB403 (close)</div>",
        unsafe_allow_html=True,
    )
with c2:
    if load_ok and not hist.empty:
        last_date = hist["report_date"].max()
        pub_date  = sections.get("Summary", pd.DataFrame())
        pub_str   = ""
        if not pub_date.empty and "published_date" in pub_date.columns:
            pub_str = pub_date.iloc[-1].get("published_date", "")
        st.markdown(
            f"<div style='text-align:right;color:{DM_MUTED};font-size:0.75rem;padding-top:6px;'>"
            f"Most recent report<br>"
            f"<span style='color:{JSA_GREEN_LT};font-size:1rem;font-weight:700;'>"
            f"{last_date.strftime('%b %d, %Y')}</span>"
            + (f"<br><span style='font-size:0.7rem;'>{pub_str}</span>" if pub_str else "")
            + "</div>",
            unsafe_allow_html=True,
        )

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)

if not load_ok:
    st.warning(
        "⏳ **USDA data temporarily unavailable** — the USDA LMR server is not responding. "
        "This usually resolves in a few minutes. Use **Refresh Now** in the sidebar to retry."
    )
    with st.expander("Technical details"):
        st.code(err_msg)
    # NOT REDUNDANT. The morning report comes from a different USDA host over
    # a different protocol, so it is very often fine when LMR is not. Delete
    # this and an LMR hiccup blanks a panel that never touched LMR.
    if not am_row.get("error"):
        st.markdown("<hr style='margin:18px 0;'>", unsafe_allow_html=True)
        am_panel(am_row, pd.DataFrame(), am_banked)
    st.stop()

if hist.empty:
    st.warning("No data returned from USDA LMR API.")
    st.stop()


# ── View switch ──────────────────────────────────────────────────────────────
# A SWITCH, NOT AN EXTRA SECTION DOWN THE PAGE, and the same shape the Cattle
# on Feed page uses for Cold Storage. This page already runs three Plotly
# charts and a grading series; appending a 42-row table and a fourth chart
# under all of it would make a long page longer and bury both views.
#
# st.stop() below is what makes it a switch rather than a tab. A hidden
# Streamlit tab is hidden, NOT skipped -- its widgets execute on every rerun --
# so as a tab the cutout charts would rebuild on every cuts interaction and
# vice versa.
_view = st.segmented_control(
    "View", ["Cutout", "Individual Cuts"], default="Cutout",
    label_visibility="collapsed", key="bc_view")

if _view == "Individual Cuts":
    cuts_panel(sections, cuts_years)
    st.stop()


# ── Compute Changes ──────────────────────────────────────────────────────────

cn, cd1, cd30, cd365 = changes(hist, "choice")
sn, sd1, sd30, sd365 = changes(hist, "select")

# USDA's own 5-day window -- the five sessions BEFORE this one. See five_day().
c5 = five_day(hist, "choice")
s5 = five_day(hist, "select")
c5d = (cn - c5) if (cn is not None and c5 is not None) else None
s5d = (sn - s5) if (sn is not None and s5 is not None) else None
# The year change was computed and thrown away here. changes() returns it
# for any column; only the spread row never showed one.
spn, spd1, spd30, spd365 = changes(hist, "spread")

# THE LEVEL, NOT JUST THE MOVE. These two tiles used to print the change as
# their value AND as their delta -- the same number twice, with the prior
# spread nowhere on the page, so reading "a month ago" meant subtracting
# 1.11 from 21.41 in your head.
sp_p30,  sp_p30_dt  = prior_level(hist, "spread", 30)
sp_p365, sp_p365_dt = prior_level(hist, "spread", 365)
c_p30,   c_p30_dt   = prior_level(hist, "choice", 30)
c_p365,  c_p365_dt  = prior_level(hist, "choice", 365)
s_p30,   _s_p30_dt  = prior_level(hist, "select", 30)
s_p365,  _s_p365_dt = prior_level(hist, "select", 365)

vol_rows = hist[hist["total_loads"].notna()]
loads_now  = vol_rows.iloc[-1]["total_loads"]  if not vol_rows.empty else None
loads_prev = vol_rows.iloc[-2]["total_loads"]  if len(vol_rows) > 1  else None
loads_d1   = (loads_now - loads_prev) if (loads_now and loads_prev) else None


# ── Session switch: morning read or afternoon close ─────────────────────────
# USDA publishes this cutout TWICE a day and the portal only ever showed the
# close. LM_XB402 is the 9:30am read; LM_XB403 is the settle. They disagree
# often enough to matter -- see am_cutout's docstring.
#
# THE DEFAULT FOLLOWS WHAT IS PUBLISHED, NOT THE CLOCK. A rule like "after 3pm
# show the close" opens on a report that does not exist on every day USDA runs
# late. Reading the two report dates gives the same answer on a normal day and
# the right one on a slow one. am_cutout.default_session() owns that rule and
# tests/test_am_cutout.py pins its truth table.
try:
    from zoneinfo import ZoneInfo
    _today_ct = datetime.now(ZoneInfo("America/Chicago")).date()
except Exception:
    _today_ct = datetime.now().date()

_pm_date  = hist["report_date"].max().date()
_am_date  = am_row.get("report_date")
# Just the two words. The qualifiers that used to be here -- "(9:30am)" and
# "(close)" -- are provenance, and provenance belongs in the caption under
# the tiles, not in a control the reader clicks twenty times a day.
_sessions = ["Morning", "Afternoon"]
_default  = (_sessions[0]
             if am_cutout.default_session(_am_date, _pm_date, _today_ct) == "AM"
             else _sessions[1])

_session = st.segmented_control(
    "Session", _sessions, default=_default,
    label_visibility="collapsed", key="bc_session")

# segmented_control returns None when the reader clears the selection.
if _session is None:
    _session = _default

# SAY IT OUT LOUD. The look-back accrues only if the write is working, and a
# write that silently fails looks exactly like a page nobody has opened yet --
# months later there would be no history and no clue why. Same reasoning as
# the letter page's autosave banner.
if am_bank_msg:
    st.caption(f"⚠️ Morning cutout is not being recorded — {am_bank_msg}")

if _session == _sessions[0]:
    am_panel(am_row, hist, am_banked)
    st.markdown("<hr style='margin:18px 0;'>", unsafe_allow_html=True)
    st.caption(
        "Everything below this line is the **afternoon** report (LM_XB403) — "
        "the attribution, charts, grading and table are all built on the close. "
        "USDA publishes no cut-level detail in a feed for the morning report."
    )
else:
    # ── Metric Tiles — Choice ────────────────────────────────────────────────────

    st.markdown('<div class="sec-header">Choice Cutout — Composite 600–900 lbs</div>',
                unsafe_allow_html=True)
    cols = st.columns(5)
    with cols[0]:
        st.markdown(tile("Current", fmt(cn), cls="tile-choice"), unsafe_allow_html=True)
    with cols[1]:
        st.markdown(tile("Day Change", fmt(cd1), delta_html(cd1), "tile-choice"), unsafe_allow_html=True)
    with cols[2]:
        st.markdown(tile("5-Day Avg", fmt(c5), delta_html(c5d), "tile-choice"), unsafe_allow_html=True)
    with cols[3]:
        st.markdown(tile("A Month Ago", fmt(c_p30), delta_html(cd30), "tile-choice"), unsafe_allow_html=True)
    with cols[4]:
        st.markdown(tile("A Year Ago", fmt(c_p365), delta_html(cd365), "tile-choice"), unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Metric Tiles — Select ────────────────────────────────────────────────────

    st.markdown('<div class="sec-header">Select Cutout — Composite 600–900 lbs</div>',
                unsafe_allow_html=True)
    cols = st.columns(5)
    with cols[0]:
        st.markdown(tile("Current", fmt(sn), cls="tile-select"), unsafe_allow_html=True)
    with cols[1]:
        st.markdown(tile("Day Change", fmt(sd1), delta_html(sd1), "tile-select"), unsafe_allow_html=True)
    with cols[2]:
        st.markdown(tile("5-Day Avg", fmt(s5), delta_html(s5d), "tile-select"), unsafe_allow_html=True)
    with cols[3]:
        st.markdown(tile("A Month Ago", fmt(s_p30), delta_html(sd30), "tile-select"), unsafe_allow_html=True)
    with cols[4]:
        st.markdown(tile("A Year Ago", fmt(s_p365), delta_html(sd365), "tile-select"), unsafe_allow_html=True)

    _ago = ""
    if c_p30_dt is not None and c_p365_dt is not None:
        _ago = (f" **A Month Ago** and **A Year Ago** are levels, not moves — "
                f"{c_p30_dt:%b %d, %Y} and {c_p365_dt:%b %d, %Y}, the last "
                f"report on or before each date, with the move to today "
                f"beside them.")
    st.caption(money_md(
        "**5-Day Avg** is USDA's own simple average of the five sessions "
        "**before** this one, not a trailing five that includes it — the same "
        "window the daily letter and the client slide print, and the same "
        "figure USDA puts on the morning report. The delta beside it is where "
        "the current print sits against that benchmark." + _ago
    ))

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Metric Tiles — Spread & Volume ──────────────────────────────────────────

    st.markdown('<div class="sec-header">Choice–Select Spread &amp; Total Volume</div>',
                unsafe_allow_html=True)
    cols = st.columns(5)
    with cols[0]:
        st.markdown(tile("Choice–Select Spread", fmt(spn), delta_html(spd1), "tile-spread"),
                    unsafe_allow_html=True)
    with cols[1]:
        st.markdown(tile("Spread a Month Ago", fmt(sp_p30), delta_html(spd30), "tile-spread"),
                    unsafe_allow_html=True)
    with cols[2]:
        st.markdown(tile("Spread a Year Ago", fmt(sp_p365), delta_html(spd365), "tile-spread"),
                    unsafe_allow_html=True)
    with cols[3]:
        st.markdown(tile("Total Loads Today", fmt_loads(loads_now), cls="tile-vol"),
                    unsafe_allow_html=True)
    with cols[4]:
        st.markdown(tile("Loads Day Change", fmt_loads(loads_d1), delta_html(loads_d1, " lds"), "tile-vol"),
                    unsafe_allow_html=True)

    # WHICH SESSION "a month ago" IS. USDA publishes on its own calendar, not
    # every 30 days, so the comparison lands on the nearest report at or
    # before the date. Printing it means a reader can check the subtraction
    # against the chart instead of taking the tile's word for it.
    if sp_p30_dt is not None or sp_p365_dt is not None:
        _bits = []
        if sp_p30_dt is not None:
            _bits.append(f"a month ago is **{sp_p30_dt:%b %d, %Y}** at {fmt(sp_p30)}")
        if sp_p365_dt is not None:
            _bits.append(f"a year ago is **{sp_p365_dt:%b %d, %Y}** at {fmt(sp_p365)}")
        st.caption(money_md(
            "Against the current " + fmt(spn) + ", " + " and ".join(_bits) +
            " — the last report on or before each date, since USDA does not "
            "publish on a fixed calendar. The green or red figure is the move "
            "from that session to this one."
        ))


# ── What moved the cutout ────────────────────────────────────────────────────
# Directly under the tiles that state the move, because it is the answer to
# the question those tiles raise. Anything inserted between them separates
# the number from its explanation.

_attr = cutout_attribution(sections, "choice")
if _attr is not None:
    _tbl, _rms = _attr
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">What Moved the Cutout — Choice</div>',
                unsafe_allow_html=True)

    # THE RECAP IN WORDS, above the table it summarises. Every bullet is
    # arithmetic -- see cutout_recap's docstring for why there is no line in
    # here guessing at a reason.
    for _b in cutout_recap(sections, hist, "choice"):
        st.markdown(f"- {_b.replace('$', chr(92) + '$')}")
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.dataframe(
        _tbl, hide_index=True, use_container_width=True,
        height=38 + 35 * len(_tbl),
        column_config={
            "Primal": st.column_config.TextColumn(width="medium"),
            "Move": st.column_config.NumberColumn(
                "Primal move", format="%+.2f",
                help="The primal's own change since the prior report, $/cwt"),
            "Weight": st.column_config.NumberColumn(
                "Share of carcass", format="%.2f%%",
                help="Solved from USDA's own primal values and cutout, "
                     "not typed in"),
            "Effect": st.column_config.NumberColumn(
                "Effect on cutout", format="%+.2f",
                help="Primal move x share — this is what actually moved the "
                     "cutout, and it is what to read"),
        },
    )
    st.caption(
        f"**Effect on cutout** is the column that answers the question — the "
        f"biggest mover is routinely not the biggest cause. The seven effects "
        f"sum to **{_tbl['Effect'].sum():+.2f}**, against the published day "
        f"change of **{cd1:+.2f}**. Shares are recovered from USDA's own "
        f"primal values and cutout by least squares over the last "
        f"{min(FIT_WINDOW, len(hist)):,} reports (residual {_rms:.3f} $/cwt), "
        f"so they follow USDA rather than a hard-coded table. The window is "
        f"recent on purpose — USDA re-based the yields since 2004, and a fit "
        f"over the whole archive is correct for no year at all."
    )


# ── Cutout Trend Chart ───────────────────────────────────────────────────────

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Cutout Trend</div>', unsafe_allow_html=True)

fig = go.Figure()

# Spread fill (rendered first so it's behind the lines)
fig.add_trace(go.Scatter(
    x=pd.concat([hist["report_date"], hist["report_date"].iloc[::-1]]),
    y=pd.concat([hist["choice"], hist["select"].iloc[::-1]]),
    fill="toself",
    fillcolor="rgba(196,180,86,0.08)",
    line=dict(color="rgba(0,0,0,0)"),
    name="Spread",
    hoverinfo="skip",
))

fig.add_trace(go.Scatter(
    x=hist["report_date"], y=hist["choice"],
    name="Choice",
    mode="lines",
    line=dict(color=CHOICE_COLOR, width=2),
    hovertemplate="<b>Choice</b>: $%{y:.2f}<extra></extra>",
))

fig.add_trace(go.Scatter(
    x=hist["report_date"], y=hist["select"],
    name="Select",
    mode="lines",
    line=dict(color=SELECT_COLOR, width=2),
    hovertemplate="<b>Select</b>: $%{y:.2f}<extra></extra>",
))

fig.update_layout(
    paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
    font=dict(color=DM_TEXT, size=11),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(color=DM_TEXT, size=11), bgcolor="rgba(0,0,0,0)"),
    margin=dict(l=55, r=20, t=15, b=40),
    xaxis=dict(
        **AXIS, title="",
        rangeselector=dict(
            buttons=[
                dict(count=1,  label="1M",  step="month", stepmode="backward"),
                dict(count=3,  label="3M",  step="month", stepmode="backward"),
                dict(count=6,  label="6M",  step="month", stepmode="backward"),
                dict(count=1,  label="YTD", step="year",  stepmode="todate"),
                dict(count=1,  label="1Y",  step="year",  stepmode="backward"),
                dict(step="all", label="All"),
            ],
            bgcolor=DM_SURFACE, activecolor=JSA_GREEN,
            font=dict(color=DM_TEXT, size=10), bordercolor=DM_BORDER,
        ),
        rangeslider=dict(visible=False),
        type="date",
    ),
    yaxis=dict(**AXIS, title="$/cwt", tickprefix="$"),
    height=380,
)

st.plotly_chart(fig, use_container_width=True)


# ── Choice–Select Spread Chart ───────────────────────────────────────────────
# ITS OWN CHART BECAUSE IT CANNOT BE READ ON THE ONE ABOVE. The Cutout Trend
# already carries the spread, as the shaded band between the two lines, and on
# a $100-$400 axis a $20 spread is a smear at the bottom you cannot take a
# value off. Plotted alone it gets an axis scaled to itself, which is the
# whole point of repeating the series rather than a duplication to tidy away.

_sp = hist[hist["spread"].notna()]

if not _sp.empty:
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Choice–Select Spread</div>',
                unsafe_allow_html=True)

    figsp = go.Figure()
    figsp.add_trace(go.Scatter(
        x=_sp["report_date"], y=_sp["spread"],
        name="Choice–Select",
        mode="lines",
        line=dict(color=SPREAD_COLOR, width=1.6),
        fill="tozeroy",
        fillcolor="rgba(196,180,86,0.12)",
        hovertemplate="<b>Spread</b>: $%{y:.2f}<extra></extra>",
    ))

    # ZERO IS DRAWN BECAUSE THE SERIES CAN CROSS IT. Select trading above
    # Choice is rare and is exactly the thing a reader wants to see rather
    # than infer from an axis that starts wherever the data happens to.
    figsp.add_hline(y=0, line=dict(color=DM_MUTED, width=1, dash="dot"))

    figsp.update_layout(
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11),
        hovermode="x unified",
        showlegend=False,
        margin=dict(l=55, r=20, t=15, b=40),
        xaxis=dict(
            **AXIS, title="",
            rangeselector=dict(
                buttons=[
                    dict(count=1,  label="1M",  step="month", stepmode="backward"),
                    dict(count=6,  label="6M",  step="month", stepmode="backward"),
                    dict(count=1,  label="YTD", step="year",  stepmode="todate"),
                    dict(count=1,  label="1Y",  step="year",  stepmode="backward"),
                    dict(count=5,  label="5Y",  step="year",  stepmode="backward"),
                    dict(step="all", label="All"),
                ],
                bgcolor=DM_SURFACE, activecolor=JSA_GREEN,
                font=dict(color=DM_TEXT, size=10), bordercolor=DM_BORDER,
            ),
            rangeslider=dict(visible=False),
            type="date",
        ),
        yaxis=dict(**AXIS, title="$/cwt", tickprefix="$"),
        height=340,
    )

    st.plotly_chart(figsp, use_container_width=True)

    # THE START DATE IS PRINTED, NOT LEFT TO THE AXIS. LM_XB403's rows begin
    # 2001-04-03, but its composite cutout is null for the first 699 of them
    # and only becomes usable on 2004-01-05 -- so the spread cannot exist
    # before then even though the report does. A reader who knows the cuts go
    # back to 2001 would otherwise read the start of this line as a gap in
    # our fetch. Same reasoning as FIRST_YEAR on the Saturday Slaughter view.
    _lo, _hi = _sp["spread"].min(), _sp["spread"].max()
    _lo_d = _sp.loc[_sp["spread"].idxmin(), "report_date"]
    _hi_d = _sp.loc[_sp["spread"].idxmax(), "report_date"]
    st.caption(money_md(
        f"Choice minus Select, {len(_sp):,} reports from "
        f"{_sp['report_date'].min():%b %d, %Y} to {_sp['report_date'].max():%b %d, %Y}. "
        f"**It starts in 2004 because USDA's composite cutout does** — LM_XB403 "
        f"carries rows from Apr 2001, but the cutout column is empty for the "
        f"first 699 of them, so there is no spread to compute. The individual "
        f"cuts do go back to 2001; see Individual Cuts. "
        f"Range over the whole series ${_lo:,.2f} ({_lo_d:%b %Y}) to "
        f"${_hi:,.2f} ({_hi_d:%b %Y})."
    ))


# ── Volume Chart ─────────────────────────────────────────────────────────────

if hist["total_loads"].notna().any():
    st.markdown('<div class="sec-header">Total Daily Loads</div>', unsafe_allow_html=True)

    vd = hist[hist["total_loads"].notna()].copy()
    ma = vd["total_loads"].rolling(10, min_periods=1).mean()

    fig_v = go.Figure()
    fig_v.add_trace(go.Bar(
        x=vd["report_date"], y=vd["total_loads"],
        name="Total Loads", marker_color=VOL_COLOR, marker_line_width=0,
        hovertemplate="<b>Total Loads</b>: %{y:.1f}<extra></extra>",
    ))
    fig_v.add_trace(go.Scatter(
        x=vd["report_date"], y=ma,
        name="10-Day Avg", mode="lines",
        line=dict(color=JSA_GREEN_LT, width=2, dash="dot"),
        hovertemplate="<b>10-Day Avg</b>: %{y:.1f}<extra></extra>",
    ))
    fig_v.update_layout(
        paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
        font=dict(color=DM_TEXT, size=11), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color=DM_TEXT, size=11), bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=55, r=20, t=15, b=40),
        xaxis=dict(**AXIS, title=""),
        yaxis=dict(**AXIS, title="Loads"),
        height=250, bargap=0.15,
    )
    st.plotly_chart(fig_v, use_container_width=True)


# ── Beef Grading Trend Chart ─────────────────────────────────────────────────

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Beef Carcass Grading — Choice &amp; Higher vs Select</div>',
            unsafe_allow_html=True)

# Fetch live weekly grading data (silent fail — chart still shows historical)
try:
    grade_wk = fetch_grading_weekly()
except Exception:
    grade_wk = pd.DataFrame()

# Build annual series from hardcoded history
grade_years   = sorted(ANNUAL_GRADES.keys())
choice_annual = [ANNUAL_GRADES[y][0] for y in grade_years]
select_annual = [ANNUAL_GRADES[y][1] for y in grade_years]

# Latest weekly point
latest_choice = None
latest_week   = None
latest_pub    = ""
if not grade_wk.empty:
    last_row      = grade_wk.iloc[-1]
    latest_choice = last_row["pct_choice"]
    latest_week   = last_row["report_date"]
    latest_pub    = str(last_row.get("published_date", ""))

# Current-year YTD average from weekly API data
cur_year = datetime.now().year
ytd_df   = grade_wk[grade_wk["report_date"].dt.year == cur_year] if not grade_wk.empty else pd.DataFrame()
ytd_avg  = float(ytd_df["pct_choice"].mean()) if not ytd_df.empty else None

fig_g = go.Figure()

# Choice & Higher line (annual)
fig_g.add_trace(go.Scatter(
    x=grade_years, y=choice_annual,
    name="Choice & Higher (Prime + Choice)",
    mode="lines+markers+text",
    line=dict(color=CHOICE_COLOR, width=2.5),
    marker=dict(size=7, color=CHOICE_COLOR),
    text=[f"{v:.1f}%" for v in choice_annual],
    textposition="top center",
    textfont=dict(size=9, color=CHOICE_COLOR),
    hovertemplate="<b>Choice & Higher</b>: %{y:.1f}%<extra></extra>",
))

# Select line (annual)
fig_g.add_trace(go.Scatter(
    x=grade_years, y=select_annual,
    name="Select",
    mode="lines+markers+text",
    line=dict(color=SELECT_COLOR, width=2.5),
    marker=dict(size=7, color=SELECT_COLOR),
    text=[f"{v:.1f}%" for v in select_annual],
    textposition="bottom center",
    textfont=dict(size=9, color=SELECT_COLOR),
    hovertemplate="<b>Select</b>: %{y:.1f}%<extra></extra>",
))

# YTD average diamond for current year
if ytd_avg is not None:
    fig_g.add_trace(go.Scatter(
        x=[cur_year], y=[ytd_avg],
        name=f"{cur_year} YTD Avg",
        mode="markers",
        marker=dict(size=14, symbol="diamond", color=CHOICE_COLOR,
                    line=dict(width=2, color=DM_TEXT)),
        hovertemplate=f"<b>{cur_year} YTD Avg</b>: %{{y:.1f}}%<extra></extra>",
    ))

# Latest weekly annotation marker
if latest_choice is not None:
    week_label = latest_week.strftime("%b %d, %Y") if latest_week else ""
    fig_g.add_trace(go.Scatter(
        x=[cur_year + 0.15], y=[latest_choice],
        name=f"Latest Weekly",
        mode="markers+text",
        marker=dict(size=12, symbol="diamond", color=COL_NEG,
                    line=dict(width=2, color=DM_TEXT)),
        text=[f"Latest Weekly: {latest_choice:.1f}%"],
        textposition="top right",
        textfont=dict(size=10, color=COL_NEG, family="Arial Black"),
        hovertemplate=f"<b>Latest Weekly ({week_label})</b>: %{{y:.1f}}%<extra></extra>",
    ))

fig_g.update_layout(
    paper_bgcolor=DM_SURFACE2, plot_bgcolor=DM_SURFACE2,
    font=dict(color=DM_TEXT, size=11),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                font=dict(color=DM_TEXT, size=11), bgcolor="rgba(0,0,0,0)"),
    margin=dict(l=55, r=30, t=30, b=40),
    xaxis=dict(
        gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
        tickfont=dict(color=DM_MUTED, size=11), title_font=dict(color=DM_MUTED),
        zeroline=False, title="Year", dtick=2,
    ),
    yaxis=dict(
        gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
        tickfont=dict(color=DM_MUTED, size=11), title_font=dict(color=DM_MUTED),
        zeroline=False, title="% of Graded Carcasses", ticksuffix="%",
        range=[0, 100],
    ),
    height=440,
)

st.plotly_chart(fig_g, use_container_width=True)

# Small caption
st.markdown(
    f'<div style="color:{DM_MUTED};font-size:0.7rem;margin-top:-10px;">'
    f'Annual averages 2000–2025 from USDA AMS. '
    f'Current-year YTD &amp; latest weekly from LMR LSWFEDCC (report 2700). '
    + (f'Latest weekly report: {latest_pub[:10]}.' if latest_pub else '')
    + '</div>',
    unsafe_allow_html=True,
)

# ── Data Table ───────────────────────────────────────────────────────────────

with st.expander("📋  Data Table"):
    display = hist.copy()
    display["report_date"] = display["report_date"].dt.strftime("%Y-%m-%d")
    display = display.rename(columns={
        "report_date":   "Date",
        "choice":        "Choice ($/cwt)",
        "select":        "Select ($/cwt)",
        "spread":        "Spread ($/cwt)",
        "total_loads":   "Total Loads",
        "choice_loads":  "Choice Loads",
        "select_loads":  "Select Loads",
    }).sort_values("Date", ascending=False).reset_index(drop=True)

    num_cols = {c: "${:.2f}" for c in ["Choice ($/cwt)", "Select ($/cwt)", "Spread ($/cwt)"]}
    num_cols.update({c: "{:.1f}" for c in ["Total Loads", "Choice Loads", "Select Loads"]
                     if c in display.columns})
    st.dataframe(display.style.format(num_cols, na_rep="—"),
                 use_container_width=True, height=320)

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
