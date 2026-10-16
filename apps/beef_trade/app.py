"""
US Beef Trade -- monthly exports and imports against the WASDE forecast.

THE PAGE EXISTS FOR THE COMPARISON, not for either series on its own. JSA
already publishes beef EXPORTS on jpsi.com/export-sales-dashboard, weekly, out
of FAS ESR. What nothing at JSA shows is imports -- and imports are where the
2025-26 story is -- and nothing shows either one on the basis USDA forecasts
them on, so there has been no way to ask whether the year is tracking WASDE.

TWO JSA SURFACES MUST NOT QUOTE THE SAME FIGURE AND DISAGREE. That rule has
cost two mornings already on the letter-versus-dashboard feeder index, so it
is worth being explicit about why this page and the Export Sales dashboard are
allowed to print different export numbers: THEY ARE NOT THE SAME FIGURE.

    Export Sales dashboard   FAS ESR, weekly, net sales and shipments,
                             product weight, thousand metric tons
    this page                USDA ERS, monthly, customs-cleared trade,
                             CARCASS weight, million pounds

A sale is not a shipment, a shipment is not a customs entry, and product
weight is not carcass weight. The caption under the tiles says so, in those
words, because a reader who has both open will otherwise assume one of them
is broken.
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# A Streamlit page's own directory is never on sys.path, and neither is the
# repo root from a page. `trade_flows` belongs to this page; `wasde` is shared
# and lives at the root, which is the convention apps/weekly_reports/app.py
# already uses to reach the `letter` package.
#
# ONE COPY, DELIBERATELY. Python caches modules by NAME, so a second
# `wasde.py` under another app directory would mean whichever page loaded
# first decided which copy every other page got -- the `snowflake_db`-times-
# five problem CLAUDE.md documents at length. Cash Cattle Trade imports this
# same file.
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).parent))
import trade_flows as tf          # noqa: E402
import wasde                      # noqa: E402

# -- JSA brand ---------------------------------------------------------------
JSA_GREEN    = "#5e7164"
JSA_GREEN_LT = "#8db89a"

DM_BG       = "#f6f8f7"
DM_SURFACE  = "#ffffff"
DM_BORDER   = "#d7e2dc"
DM_TEXT     = "#32373c"
DM_MUTED    = "#5f7267"
COL_POS     = "#16a34a"
COL_NEG     = "#dc2626"
COL_NEU     = "#5f7267"

EXPORT_COLOR = "#6fa8c4"
IMPORT_COLOR = "#c4785a"
NET_COLOR    = "#9b89c4"
WASDE_COLOR  = "#c4b456"
PRIOR_COLOR  = "#b8c4bc"

AXIS = dict(
    gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
    tickfont=dict(color=DM_MUTED, size=11),
    title_font=dict(color=DM_MUTED, size=11),
    zeroline=False,
)

# st.set_page_config is made once by Home.py for the whole multi-page run.
st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{
    background-color:{DM_BG}; color:{DM_TEXT};
  }}
  .tile {{
    background:{DM_SURFACE}; border:1px solid {DM_BORDER};
    border-top:3px solid {JSA_GREEN}; border-radius:10px;
    padding:16px 20px; text-align:center; height:100%;
  }}
  .tile-label {{
    color:{DM_MUTED}; font-size:0.68rem; text-transform:uppercase;
    letter-spacing:0.09em; margin-bottom:6px;
  }}
  .tile-value {{
    color:{DM_TEXT}; font-size:1.55rem; font-weight:700; line-height:1.1;
  }}
  .tile-sub {{ color:{DM_MUTED}; font-size:0.72rem; margin-top:5px; }}
  .tile-delta-pos {{ color:{COL_POS}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neg {{ color:{COL_NEG}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neu {{ color:{COL_NEU}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-wasde  {{ border-top-color:{WASDE_COLOR}; }}
  .tile-export {{ border-top-color:{EXPORT_COLOR}; }}
  .tile-import {{ border-top-color:{IMPORT_COLOR}; }}
  .tile-net    {{ border-top-color:{NET_COLOR}; }}
  .sec-header {{
    color:{DM_MUTED}; font-size:0.7rem; text-transform:uppercase;
    letter-spacing:0.1em; padding:10px 0 4px; border-bottom:1px solid {DM_BORDER};
    margin-bottom:12px;
  }}
  hr {{ border-color:{DM_BORDER}; }}
  #MainMenu, footer {{ visibility:hidden; }}
  .stDeployButton {{ display:none; }}
</style>
""", unsafe_allow_html=True)


# -- small helpers -----------------------------------------------------------

def tile(label, value, delta="", sub="", cls=""):
    sub_html = '<div class="tile-sub">%s</div>' % sub if sub else ""
    return (f'<div class="tile {cls}">'
            f'<div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>'
            f'{delta}{sub_html}</div>')


def delta_html(val, suffix="", digits=0, invert=False, neutral=False):
    """
    An arrow and a signed figure, or an em dash.

    `invert` flips only the COLOUR, for figures where up is the bad direction.
    The sign printed is always the real one.

    `neutral` suppresses the colour entirely, and exists because most of the
    deltas on this page are not good or bad. Imports running ahead of USDA's
    forecast is excellent news for a packer buying 90s and poor news for a
    cow-calf operator, and the page does not know which one is reading it.
    Green and red are kept for the two places a direction really is a
    direction -- a figure against its own year-ago.
    """
    if val is None:
        return '<div class="tile-delta-neu">&mdash;</div>'
    if val == 0:
        # "0 vs Aug" reads as a missing figure. USDA leaving a forecast alone
        # is a real and frequently interesting answer, so it is said in words.
        return f'<div class="tile-delta-neu">unchanged{suffix}</div>'
    up = val > 0
    good = (not up) if invert else up
    color = "neu" if neutral else ("pos" if good else "neg")
    arrow = "▲" if up else "▼"
    return (f'<div class="tile-delta-{color}">{arrow} '
            f'{abs(val):,.{digits}f}{suffix}</div>')


def pct(new, base):
    """
    Percentage change, or None when there is no base to divide by.

    None rather than 0.0 on a missing or zero base: "USDA is forecasting no
    change" and "there is nothing to compare against" are different answers,
    and a 0.0% would merge them. Same reason `Wasde.revision` returns None.
    """
    if new is None or base in (None, 0):
        return None
    return (new / base - 1.0) * 100.0


def delta_pair(value, percent, suffix="", digits=0, base=None, base_label=""):
    """
    An absolute change and its percentage on one line: "+/- 130 . 2.1% vs Aug".

    BOTH, because on this page they answer different questions and the
    smaller one is not the less important. A 130 million lb revision to the
    import forecast sounds like a rounding error beside a 6,262 total and is
    2.1% -- and USDA has made several in a row the same way. The percentage
    is what makes a run of them legible; the absolute is what nets against
    production.

    NO PARENTHESES AROUND THE PERCENTAGE, which is what the first version
    used. **In USDA's own reports parentheses mean NEGATIVE** -- the trap
    `letter/sterling.py` and `am_cutout` both document, where (2.23) is a
    $2.23 fall -- so "+/- 130 (2.1%)" on a page of USDA figures is read by
    exactly the audience most likely to get it backwards. A middle dot
    separates them instead.

    THE ARROW CARRIES THE SIGN, so neither figure after it is signed. The
    first version printed the percentage with `:+` as well and produced
    "v -0.8%", a double negative.

    `base` PRINTS THE LEVEL THE MOVE IS MEASURED FROM, on its own line under
    it. "+/- 130 . 2.1% vs Aug" over 6,262 never said USDA forecast 6,132 in
    August -- the reader subtracts, which is Ross's complaint about the beef
    cutout tiles on 2026-10-07 and the same defect fixed on Cash Cattle Trade
    and Cattle Weights since. It is a separate line rather than more text on
    this one because `sub` here carries the UNIT, and on this page the unit is
    load-bearing: these are carcass weight, and the FAS export figures JSA
    also publishes are product weight.
    """
    _b = ""
    if base is not None:
        _b = (f'<div class="tile-sub">{base_label} '
              f'{base:,.{digits}f}</div>')
    if value is None and percent is None:
        return '<div class="tile-delta-neu">&mdash;</div>' + _b
    if value == 0 or (value is None and percent == 0):
        # NO LEVEL LINE HERE. An unchanged forecast means the base IS the
        # tile's own value, and printing it underneath is the "same number
        # twice" the beef cutout tiles were corrected for -- it fills the
        # space without adding a figure.
        return f'<div class="tile-delta-neu">unchanged{suffix}</div>' 
    ref = value if value is not None else percent
    arrow = "▲" if ref > 0 else "▼"
    bits = []
    if value is not None:
        bits.append(f"{abs(value):,.{digits}f}")
    if percent is not None:
        bits.append(f"{abs(percent):,.1f}%")
    return (f'<div class="tile-delta-neu">{arrow} '
            f'{" · ".join(bits)}{suffix}</div>' + _b)


def running_html(over_pct):
    """
    "running 12.3% above this" -- a sentence, not a signed percentage.

    The earlier version printed the arrow and "% — recent pace against
    this", which left the reader to work out which of the two numbers was
    above the other. A headline that needs decoding is not a headline, and
    on this portal every one of them has to be readable on its own.
    """
    if over_pct is None:
        return '<div class="tile-delta-neu">&mdash;</div>'
    if abs(over_pct) < 0.05:
        return '<div class="tile-delta-neu">running at this pace</div>'
    word = "above" if over_pct > 0 else "below"
    arrow = "▲" if over_pct > 0 else "▼"
    return (f'<div class="tile-delta-neu">{arrow} running '
            f'{abs(over_pct):,.1f}% {word} this</div>')


def projection_yoy_html(pct_change, base_year, base_value):
    """
    "▲ 19.1% vs 2025" -- the projection expressed as a year-on-year
    change, the same way USDA's forecast is expressed in the panel above.

    THAT PARALLEL IS THE WHOLE POINT. The WASDE tile says the 2026 import
    forecast is +16.2% on 2025; this one says the actual pace is tracking
    +19.1% on the same base. Two percentages, one basis, one from USDA and
    one from the market -- which is the comparison the page exists to make,
    and it only works if both are quoted the same way.

    It replaced a share of USDA's forecast ("102.5% of USDA's 6,262"), which
    answered a question the caption underneath already answers in absolute
    terms and did not line up with anything else on the page.
    """
    if pct_change is None or not base_value:
        return '<div class="tile-delta-neu">&mdash;</div>'
    if abs(pct_change) < 0.05:
        return (f'<div class="tile-delta-neu">level with '
                f'{base_year}</div>')
    arrow = "▲" if pct_change > 0 else "▼"
    return (f'<div class="tile-delta-neu">{arrow} '
            f'{abs(pct_change):,.1f}% vs {base_year}</div>')


def fmt(v, digits=0, suffix=""):
    return f"{v:,.{digits}f}{suffix}" if v is not None else "—"


# -- data --------------------------------------------------------------------

@st.cache_data(ttl=21600, persist="disk", show_spinner=False)
def load_trade(schema: int = tf.SCHEMA) -> pd.DataFrame:
    """
    The ERS monthly file. Six hours, because it is republished monthly and is
    4 MB. `schema` keys the cache, and BOTH halves matter: no leading underscore (Streamlit drops underscore-prefixed arguments from the key) and the CALLER must pass it (a default is never hashed).
    st.cache_data
    never notices that trade_flows.py changed. See CLAUDE.md on
    `leverage.SCHEMA`.
    """
    return tf.fetch()


@st.cache_data(ttl=21600, persist="disk", show_spinner=False)
def load_wasde(schema: int = wasde.SCHEMA) -> dict:
    """
    The newest WASDE meats table, flattened to a plain dict.

    FLATTENED ON PURPOSE: st.cache_data pickles what it stores, and a cached
    dataclass instance goes stale against its own class the moment the module
    is edited. A dict cannot.
    """
    w = wasde.load()
    return {
        "report_month": w.report_month,
        "release_date": w.release_date,
        "source_url": w.source_url,
        "series": [
            {"commodity": s.commodity, "year": s.year, "status": s.status,
             "current_month": s.current_month, "prior_month": s.prior_month,
             "current": dict(s.current), "prior": dict(s.prior)}
            for s in w.series
        ],
    }


@st.cache_data(ttl=86400, persist="disk", show_spinner=False)
def load_revisions(attribute: str, year: int, n: int,
                   schema: int = wasde.SCHEMA) -> list:
    """n releases, n requests -- only ever called from a button."""
    return wasde.history("Beef", attribute, year, n=n)


def beef_series(wd: dict, year=None):
    """The Beef row for `year`, or the earliest forecast year."""
    rows = [s for s in wd["series"] if s["commodity"] == "Beef"]
    if year is not None:
        rows = [s for s in rows if s["year"] == year]
    else:
        fc = sorted((s for s in rows if s["status"]), key=lambda s: s["year"])
        rows = fc[:1] or rows
    return rows[0] if rows else None


# -- header ------------------------------------------------------------------

st.markdown(
    f"<h2 style='margin:0;color:{DM_TEXT};"
    f"font-family:\"EB Garamond\",Georgia,serif'>US Beef Trade</h2>"
    f"<div style='color:{DM_MUTED};font-size:0.9rem;margin-bottom:4px'>"
    f"Monthly exports and imports, carcass-weight basis, against the USDA "
    f"WASDE forecast</div>",
    unsafe_allow_html=True)

_err = None
try:
    trade = load_trade(tf.SCHEMA)
except Exception as exc:                                   # noqa: BLE001
    trade, _err = pd.DataFrame(), exc

wd = None
wasde_err = None
try:
    wd = load_wasde(wasde.SCHEMA)
except Exception as exc:                                   # noqa: BLE001
    wasde_err = exc

if _err is not None:
    st.error(
        "USDA ERS did not return the beef trade file, so there are no actuals "
        f"to show. {type(_err).__name__}: {_err}")
    st.caption(f"Source: {tf.ERS_PAGE}")
    st.stop()

if trade.empty:
    st.warning("USDA ERS returned the beef trade file but it held no rows.")
    st.stop()

# THE AUDIT RUNS BEFORE ANYTHING IS DRAWN. `World total` is a row in the file,
# so a grouping mistake doubles every figure on the page and still produces
# numbers that look like beef trade. If the countries have stopped summing to
# USDA's published total, say so rather than charting it.
_rec = tf.reconciles(trade)
if not _rec["ok"]:
    st.error(
        "The ERS file no longer reconciles: the partner countries sum to "
        f"{_rec['worst']:,.1f} million lb away from USDA's own World total "
        f"(worst of {_rec['checked']} month/flow pairs, at {_rec['worst_at']}). "
        "Every figure below is built on the published total, so it is still "
        "right, but the file's shape has changed and the country tables "
        "should not be trusted until this is looked at.")

_latest = tf.latest_month(trade, "Imports") or tf.latest_month(trade, "Exports")
YEAR, THROUGH = _latest
_fc_year = None
if wd:
    _b = beef_series(wd)
    _fc_year = _b["year"] if _b else None

bits = [f"USDA ERS through **{tf.month_name(THROUGH)} {YEAR}**"]
if wd:
    bits.append(f"WASDE **{wd['report_month']}**")
st.caption(" · ".join(bits) + " · carcass weight, million pounds")

if wasde_err is not None:
    st.warning(
        "The WASDE forecast could not be read, so the expectation panels are "
        f"blank. The actuals below are unaffected. {type(wasde_err).__name__}: "
        f"{wasde_err}")


# -- WASDE panel -------------------------------------------------------------

def wasde_panel(attribute: str, label: str, key: str):
    """
    USDA's forecast for the flow, what it was last month, and how it compares
    with the year behind it.

    ON EVERY VIEW, which is the point -- exports, imports and net trade each
    get the expectation that belongs to them rather than one shared panel at
    the top that a reader on the imports tab would have to translate.

    THE REVISION IS FREE AND THE REVISION HISTORY IS NOT. Each WASDE release
    prints last month's estimate beside this month's, so the month-over-month
    change costs nothing. A longer history is one request per release, so it
    sits behind a button -- and a hidden Streamlit tab still executes its
    widgets, so a button is also what stops the exports tab fetching twelve
    releases because somebody opened the imports one.
    """
    if not wd:
        return None, None
    s = beef_series(wd)
    if not s:
        return None, None

    # EVERY TILE LABEL NAMES ITS OWN FIGURE. A reader should never have to
    # look up at the section header to find out whether 6,262 is imports or
    # exports -- that is the standing rule for headlines on this portal.
    noun = label.lower().rstrip("s") if label.lower().endswith("s") else label.lower()
    year = s["year"]
    now = s["current"].get(attribute)
    was = s["prior"].get(attribute)
    rev = (now - was) if (now is not None and was is not None) else None

    prior_actual = beef_series(wd, year - 1)
    base = prior_actual["current"].get(attribute) if prior_actual else None
    yoy = ((now / base - 1.0) * 100.0) if (now and base) else None

    nxt = beef_series(wd, year + 1)
    nxt_val = nxt["current"].get(attribute) if nxt else None
    nxt_rev = None
    if nxt and nxt["prior"].get(attribute) is not None and nxt_val is not None:
        nxt_rev = nxt_val - nxt["prior"][attribute]

    st.markdown(f"<div class='sec-header'>USDA WASDE expectation &mdash; "
                f"{label}</div>", unsafe_allow_html=True)
    # SPELLED OUT BECAUSE WASDE IS INCONSISTENT WITH ITSELF. Its grain tables
    # are split MARKETING years -- corn is 2026/27, September to August -- so
    # a reader who knows WASDE from the grain side will reasonably assume
    # these are too. The meats table is plain calendar years, which is what
    # lets the monthly actuals below be summed Jan-Dec and compared with it
    # directly. The basis check at the foot of the page is the proof: ERS's
    # Jan-Dec 2025 total reproduces WASDE's 2025 line exactly.
    st.caption(
        f"USDA's own projection of what US beef {label.lower()} will total "
        f"over the **{year} calendar year**, updated every WASDE. Not a "
        f"marketing year — the meats table runs January to December, "
        f"unlike the grain tables in the same report.")

    # THE PERCENTAGE IS THE POINT, SO IT IS A VALUE AND NOT A FOOTNOTE.
    # "What change is USDA forecasting" is the question this panel exists to
    # answer, and it was previously answerable only by dividing two tiles in
    # your head. The year-on-year move is now the headline figure of its own
    # tile; every other change on the panel carries its percentage beside the
    # absolute rather than instead of it.
    rev_pct = pct(now, was)
    nxt_vs_now = pct(nxt_val, now)
    nxt_rev_pct = pct(nxt_val, nxt["prior"].get(attribute)) if nxt else None
    yoy_abs = (now - base) if (now is not None and base is not None) else None

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(tile(
            f"USDA {year} {noun} forecast", fmt(now),
            delta_pair(rev, rev_pct,
                       " vs " + (s["prior_month"] or "last month"),
                       base=was, base_label=(s["prior_month"] or "last month")),
            sub="calendar year · million lb, carcass weight",
            cls="tile-wasde"),
            unsafe_allow_html=True)
    with c2:
        st.markdown(tile(
            f"USDA {year} forecast vs {year - 1}",
            (f"{yoy:+,.1f}%" if yoy is not None else "—"),
            delta_pair(yoy_abs, None, " million lb"),
            sub=f"{year - 1} actual {fmt(base)}", cls="tile-wasde"),
            unsafe_allow_html=True)
    with c3:
        nxt_sub = "WASDE adds the next year in May"
        if nxt_val:
            nxt_prior = nxt["prior"].get(attribute) if nxt else None
            if nxt_prior is None:
                nxt_sub = "million lb"
            elif nxt_rev == 0:
                # A level identical to the value is noise; "unchanged" is the
                # answer, and USDA leaving a forecast alone IS an answer.
                nxt_sub = f"unchanged vs {nxt['prior_month']} · million lb"
            else:
                nxt_sub = (f"{nxt['prior_month']} {fmt(nxt_prior)}"
                           f" · million lb")
        st.markdown(tile(
            f"USDA {year + 1} {noun} forecast", fmt(nxt_val),
            delta_pair(None, nxt_vs_now, f" vs {year}", ),
            sub=nxt_sub,
            cls="tile-wasde"), unsafe_allow_html=True)
    with c4:
        st.markdown(tile(
            "WASDE report",
            wd["report_month"].split()[0] if wd["report_month"] else "—",
            sub=(wd["release_date"].isoformat() if wd["release_date"] else ""),
            cls="tile-wasde"), unsafe_allow_html=True)

    with st.expander("How USDA's forecast for this year has moved"):
        st.caption(
            "One request per WASDE release, so it is not fetched until asked "
            "for. ESMIS serves about two years of releases and **October 2025 "
            "is missing** — that WASDE was never published — so the "
            "line has a real gap in it rather than a flat month.")
        n = st.slider("Releases", 4, 24, 12, key=f"rev_n_{key}")
        if st.button("Fetch revision history", key=f"rev_go_{key}"):
            with st.spinner(f"Reading {n} WASDE releases…"):
                try:
                    hist = load_revisions(attribute, year, n, wasde.SCHEMA)
                except Exception as exc:                   # noqa: BLE001
                    hist = []
                    st.warning(f"Could not read the releases: {exc}")
            if hist:
                h = pd.DataFrame(hist)
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=h["date"], y=h["value"], mode="lines+markers",
                    name=f"WASDE {year} {label.lower()}",
                    line=dict(color=WASDE_COLOR, width=2.5),
                    marker=dict(size=7),
                    hovertemplate="%{x|%b %Y}<br>%{y:,.0f} mil lb<extra></extra>"))
                if base:
                    fig.add_hline(
                        y=base, line_dash="dot", line_color=DM_MUTED,
                        annotation_text=f"{year - 1} actual {base:,.0f}",
                        annotation_font_color=DM_MUTED)
                fig.update_layout(
                    height=300, margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE,
                    showlegend=False, xaxis=AXIS,
                    yaxis={**AXIS, "title": "million lb"})
                st.plotly_chart(fig, use_container_width=True,
                                key=f"revfig_{key}")
                first, last = h.iloc[0], h.iloc[-1]
                move = last["value"] - first["value"]
                st.caption(
                    f"Between the {first['report_month']} and "
                    f"{last['report_month']} reports USDA has "
                    f"{'raised' if move > 0 else 'cut' if move < 0 else 'held'} "
                    f"the {year} beef {label.lower()} forecast by "
                    f"{abs(move):,.0f} million lb "
                    f"({len(h)} releases on file).")
            elif hist == []:
                st.caption("No releases carried that year.")
    return year, now


# -- pace panel --------------------------------------------------------------

def pace_panel(flow: str, forecast, year: int, through: int, cls: str):
    """
    Is the year on track for USDA's number?

    TWO DIFFERENT QUESTIONS AND THE PAGE REFUSES TO MERGE THEM. "What must the
    remaining months average" is arithmetic on USDA's forecast. "What will the
    year come to" is a projection off the seasonal shape. They disagree, and
    the disagreement IS the information -- see trade_flows.pace.
    """
    p = tf.pace(trade, flow, year, through, forecast)

    # EVERY TILE NAMES ITS UNIT, and the two RATES name their period as well.
    # A reader meeting 535 beside a 6,262 forecast has no way to tell they
    # are different kinds of number -- one is a year, the other a month --
    # and the gap between them looks like a collapse rather than a cadence.
    # Flagged 2026-10-07; the WASDE row above had carried its units from the
    # start and these four had not.
    UNIT = "million lb"
    RATE = "million lb per month"

    st.markdown("<div class='sec-header'>Actual pace against the "
                "forecast</div>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(tile(
            f"{year} {flow.lower()} so far", fmt(p["ytd"]),
            delta_html(p["yoy_pct"], "%", 1),
            sub=f"{UNIT} · Jan–{tf.month_name(through)} vs {year - 1}",
            cls=cls), unsafe_allow_html=True)
    with c2:
        st.markdown(tile(
            "Recent monthly pace", fmt(p["run_rate"]),
            sub=f"{RATE} · average of the last 3 months", cls=cls),
            unsafe_allow_html=True)
    with c3:
        # THE RATIO IS PRINTED THE WAY IT IS READ. `gap_pct` is required
        # against recent pace, so a year running hot shows a NEGATIVE gap --
        # which is the right arithmetic and exactly backwards as a sentence.
        # Inverting it here makes the arrow mean "the market is running this
        # much above what USDA's number needs", which is the claim.
        over = None
        if p["required"] and p["run_rate"]:
            over = (p["run_rate"] / p["required"] - 1.0) * 100.0
        st.markdown(tile(
            "Monthly pace needed", fmt(p["required"]),
            running_html(over),
            sub=(f"{RATE} · to reach USDA's {forecast:,.0f}, "
                 f"{p['months_left']} months left" if forecast
                 else f"{RATE} · {p['months_left']} months left"), cls=cls),
            unsafe_allow_html=True)
    with c4:
        st.markdown(tile(
            f"{year} full-year projection", fmt(p["projection"]),
            projection_yoy_html(p["projection_yoy_pct"], year - 1,
                                p["prior_year_total"]),
            sub=(f"{UNIT} · {year - 1} actual {fmt(p['prior_year_total'])}"
                 if p["prior_year_total"] else
                 f"{UNIT} · full year on the seasonal shape"), cls=cls),
            unsafe_allow_html=True)

    if p["projection"] is not None and forecast:
        diff = p["implied_vs_forecast"]
        direction = "above" if diff > 0 else "below"
        # THE WORKED EXAMPLE FOLLOWS THE TAB. Explaining why the projection
        # is seasonal with a fact about imports, on the exports tab, reads as
        # a copy-paste -- and invites the reader to wonder which flow the
        # number above it actually describes.
        shape = tf.seasonal_shape(trade, flow, year)
        season_note = ""
        if not shape.empty:
            heavy = tf.month_name(int(shape.idxmax()))
            light = tf.month_name(int(shape.idxmin()))
            covered = float(shape[shape.index <= through].sum()) * 100.0
            season_note = (
                f" {flow} are heaviest in {heavy} and lightest in {light}, "
                f"and Jan–{tf.month_name(through)} normally carries "
                f"{covered:,.0f}% of the year rather than "
                f"{through / 12 * 100:,.0f}% — which is the whole "
                "difference between this and a YTD×12/n annualisation.")
        st.caption(
            f"Carrying on at a normal seasonal shape, {year} lands around "
            f"**{p['projection']:,.0f}** million lb — "
            f"**{abs(diff):,.0f} {direction}** USDA's {forecast:,.0f}. "
            "The projection scales this year's realised year-to-date by the "
            "share of the year those months normally carry." + season_note
        )
    return p


# -- charts ------------------------------------------------------------------

def monthly_chart(flow: str, color: str, year: int, key: str):
    m = tf.monthly(trade, flow)
    # FIVE COMPLETE YEARS, THE SAME FIVE trade_flows.seasonal_shape FITS ON.
    # The band and the projection are two views of one claim about what a
    # normal year looks like, so a reader comparing them must not be looking
    # at different windows. It was 2020-2025 here against 2021-2025 there for
    # about an hour, which also made the legend say "5-yr" over six years.
    complete = m.groupby("year")["month"].count()
    hist = [int(y) for y in complete[complete == 12].index if y < year][-5:]
    band = m[m["year"].isin(hist)]

    fig = go.Figure()
    if not band.empty:
        g = band.groupby("month")["mil_lb"]
        lo, hi, avg = g.min(), g.max(), g.mean()
        months = list(lo.index)
        fig.add_trace(go.Scatter(
            x=months + months[::-1],
            y=list(hi.values) + list(lo.values)[::-1],
            fill="toself", fillcolor="rgba(184,196,188,0.35)",
            line=dict(width=0), hoverinfo="skip",
            name=f"{hist[0]}–{hist[-1]} range"))
        fig.add_trace(go.Scatter(
            x=months, y=avg.values, mode="lines",
            name=f"{len(hist)}-yr average",
            line=dict(color=PRIOR_COLOR, width=2, dash="dot"),
            hovertemplate="%{y:,.0f} mil lb<extra>5-yr avg</extra>"))

    prev = m[m["year"] == year - 1]
    if not prev.empty:
        fig.add_trace(go.Scatter(
            x=prev["month"], y=prev["mil_lb"], mode="lines",
            name=str(year - 1), line=dict(color=DM_MUTED, width=2),
            hovertemplate="%{y:,.0f} mil lb<extra>" + str(year - 1) + "</extra>"))

    cur = m[m["year"] == year]
    fig.add_trace(go.Scatter(
        x=cur["month"], y=cur["mil_lb"], mode="lines+markers", name=str(year),
        line=dict(color=color, width=3), marker=dict(size=7),
        hovertemplate="%{y:,.0f} mil lb<extra>" + str(year) + "</extra>"))

    fig.update_layout(
        height=380, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0, font=dict(size=11,
                                                            color=DM_MUTED)),
        xaxis={**AXIS, "tickmode": "array", "tickvals": list(range(1, 13)),
               "ticktext": tf.MONTHS},
        yaxis={**AXIS, "title": "million lb"})
    st.plotly_chart(fig, use_container_width=True, key=key)


# Start years offered on the annual chart. FIXED ANCHORS, not "last N
# years": a rolling count silently changes what the chart covers every
# January, and a label that says "Since 2000" still says it in 2030. ERS
# carries 37 complete years (1989-2025, no gaps), so the only limit here is
# how much a reader wants to look at.
ANNUAL_WINDOWS = {"Since 2010": 2010, "Since 2000": 2000, "All (1989–)": None}
# THE FULL HISTORY BY DEFAULT. Asked for 2026-10-07. The long view is the
# point of an annual chart here: imports bottomed at 2,057 million lb in
# 2011 against 5,388 in 2025, and the 2003 BSE collapse and the 2014-15
# herd-low spike are both outside any recent window. The shorter options
# stay for a closer look.
ANNUAL_DEFAULT = "All (1989–)"


def annual_figure(df: pd.DataFrame, flow: str, color: str, forecast, fc_year,
                  since: int | None = 2010) -> go.Figure:
    """
    Complete calendar years, with the WASDE forecast drawn as its own bar.

    THE FORECAST BAR IS A DIFFERENT COLOUR AND IS LABELLED, because a forecast
    sitting in a row of actuals at the same saturation is read as an actual.
    The part-year in progress is left OUT entirely rather than drawn short --
    a bar covering eight months beside twelve-month bars is a chart that tells
    a true story wrongly.

    THE X-AXIS IS FORCED CATEGORICAL AND THAT LINE IS LOAD-BEARING. Plotly
    type-sniffs an axis, and "2014".."2025" are all numeric strings, so it
    builds a LINEAR axis from 2013.5 to 2025.5 -- at which point "2026F" has
    no numeric position and its bar is never drawn. It is not dropped either:
    the trace exists, the legend entry renders, and the value still stretches
    the y-axis, so the chart reserves headroom to 6,592 for a bar nobody can
    see. Caught on 2026-10-07 by reading _fullLayout out of the live page
    after the bar failed to appear in a screenshot; nothing raised, and the
    only visible symptom was a suspiciously tall empty top.

    Split out of the renderer so a test can assert the axis type without
    rendering anything.
    """
    m = tf.monthly(df, flow)
    complete = m.groupby("year")["month"].count()
    full_years = [int(y) for y in complete[complete == 12].index
                  if since is None or y >= since]
    tot = m[m["year"].isin(full_years)].groupby("year")["mil_lb"].sum()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[str(y) for y in tot.index], y=list(tot.values), name="Actual",
        marker_color=color,
        hovertemplate="%{x}<br>%{y:,.0f} mil lb<extra></extra>"))
    if forecast and fc_year:
        fig.add_trace(go.Bar(
            x=[f"{fc_year}F"], y=[forecast], name="WASDE forecast",
            marker_color=WASDE_COLOR,
            hovertemplate="%{x}<br>%{y:,.0f} mil lb<extra>WASDE</extra>"))
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=10, b=10), bargap=0.25,
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE,
        legend=dict(orientation="h", y=1.1, x=0,
                    font=dict(size=11, color=DM_MUTED)),
        xaxis={**AXIS, "type": "category"},
        yaxis={**AXIS, "title": "million lb"})
    return fig


# What moved the series, for the years the data itself picks out.
#
# KEYED BY (FLOW, YEAR) BECAUSE THE EVENTS ARE NOT SHARED. The December 2003
# BSE case is an EXPORTS story and nothing else: exports fell 82% in 2004 and
# imports ROSE 22% the same year, because the bans ran outward. Writing "the
# 2003 BSE collapse" under an imports chart would describe a dip that is not
# there -- I did exactly that in a note to Ross before checking the series,
# which is why this is keyed rather than shared.
#
# The YEARS are not written here, only the causes. Which year is the record,
# the trough or the biggest move is computed from the data every load, so a
# new record cannot leave the caption describing the old one.
EVENT_NOTES = {
    ("Exports", 2004):
        "the BSE case confirmed that December closed Japan, South Korea and "
        "most other markets almost overnight — monthly exports went from "
        "163.5 million lb in December 2003 to 5.6 that January",
    ("Imports", 2014):
        "the US cow herd bottomed after the 2011–12 drought, and lean "
        "grinding beef had to come from somewhere",
}
# ("Imports", 2011) HAD A NOTE HERE AND IT WAS WRONG. It read "the tightest
# year of the herd rebuild, before the drought broke it" -- but 2011 was
# DURING the 2011-12 drought, not before it, and the rebuild did not start
# until around 2014. I do not actually know why imports bottomed that year,
# so the figure now stands on its own. A caption with no cause is worth more
# than a caption with a plausible wrong one, which is the standard the rest
# of this file is written to.


def landmark_caption(flow: str) -> str:
    """
    One line naming the extremes the chart shows, with the reason where
    there is one.

    A thirty-seven-year bar chart has obvious features a reader can see and
    cannot name. The chart already says "there is a hole in 2004"; what it
    cannot say is that exports fell 82% and took until 2011 to recover.
    """
    lm = tf.landmarks(trade, flow)
    if not lm:
        return ""
    noun = flow.lower()
    bits = []

    # ONE EXPLANATION PER YEAR. 2004 is both the steepest fall and the record
    # low for exports, so an unguarded caption printed the whole BSE sentence
    # twice in one paragraph. A reader meeting the same clause again assumes
    # they have misread the first one.
    explained = set()

    def _note(year):
        if year in explained:
            return ""
        text = EVENT_NOTES.get((flow, year))
        if not text:
            return ""
        explained.add(year)
        return f" — {text}"

    fall = lm.get("biggest_fall")
    if fall:
        line = (f"**{fall['year']}** was the steepest fall on record, "
                f"{abs(fall['pct']):,.0f}% to {fall['value']:,.0f}"
                + _note(fall["year"]))
        back = tf.recovered_year(trade, flow, fall["year"] - 1)
        if back:
            line += (f". {noun.capitalize()} did not regain their "
                     f"{fall['year'] - 1} level until **{back}**")
        bits.append(line)

    rise = lm.get("biggest_rise")
    if rise and (not fall or rise["year"] != fall["year"]):
        bits.append(f"**{rise['year']}** was the sharpest rise, "
                    f"{rise['pct']:,.0f}% to {rise['value']:,.0f}"
                    + _note(rise["year"]))

    low, high = lm.get("low"), lm.get("high")
    if low and high:
        # TWO SENTENCES, not one joined by a comma. With a note spliced into
        # the first half, ", the high ..." trails off the end of a clause
        # that already has commas in it and stops parsing as a list.
        bits.append(f"The low is **{low['year']}** at {low['value']:,.0f}"
                    + _note(low["year"]))
        bits.append(f"The high is **{high['year']}** at {high['value']:,.0f}"
                    + _note(high["year"]))

    if not bits:
        return ""
    return (". ".join(bits) + f". Million lb, carcass weight, "
            f"{lm['first_year']}–{lm['last_year']}.")


def annual_chart(flow: str, color: str, forecast, fc_year, key: str):
    """
    THE WINDOW IS THE READER'S CHOICE, because the right one depends on the
    question. A twelve-year chart starting in 2014 was the original default
    and it hides the thing that makes today remarkable: beef imports
    bottomed at 2,057 million lb in 2011 and are 5,388 now. You cannot see
    that a series has more than doubled if the chart starts after the
    trough.
    """
    choice = st.segmented_control(
        "Years shown", list(ANNUAL_WINDOWS), default=ANNUAL_DEFAULT,
        label_visibility="collapsed", key=f"{key}_window")
    # segmented_control returns None when the reader clears the selection.
    since = ANNUAL_WINDOWS.get(choice or ANNUAL_DEFAULT, ANNUAL_WINDOWS[ANNUAL_DEFAULT])

    st.plotly_chart(
        annual_figure(trade, flow, color, forecast, fc_year, since),
        use_container_width=True, key=key)
    note = landmark_caption(flow)
    if note:
        st.caption(note)
    if forecast and fc_year:
        st.caption(f"{fc_year}F is USDA's forecast, not an actual. The part "
                   "year in progress is left out rather than drawn as a short "
                   "bar beside full ones.")


def country_table(flow: str, year: int, through: int, key: str, noun: str):
    rows = tf.countries(trade, flow, year, through, top=12)
    if rows.empty:
        st.caption("No partner detail for that period.")
        return
    disp = pd.DataFrame({
        noun: rows["country"],
        f"{year} YTD": rows["ytd"].round(1),
        f"{year - 1} YTD": rows["prior"].round(1),
        "Change": rows["change"].round(1),
        "%": rows["pct"].round(1),
        "Share %": rows["share"].round(1),
    })
    st.dataframe(disp, use_container_width=True, hide_index=True, key=key)
    st.caption(
        f"Million lb, carcass weight, January–{tf.month_name(through)}. "
        "Share is against USDA's published world total, so it is the share of "
        "all trade rather than of the twelve shown.")


# -- views -------------------------------------------------------------------
#
# TABS, NOT A SWITCH. The rule in CLAUDE.md is that a hidden Streamlit tab is
# hidden and not skipped, so a tab is right only when the hidden body is
# cheap. Here all three views read the SAME two cached fetches -- one ERS file
# and one WASDE release -- so the second and third tabs cost rendering and no
# network at all. The one expensive thing on the page, the WASDE revision
# history, is behind a button for exactly this reason.

tab_exp, tab_imp, tab_net = st.tabs(
    ["Exports", "Imports", "Net trade"])

with tab_exp:
    fc_year, fc = wasde_panel("exports", "Exports", "exp")
    st.write("")
    pace_panel("Exports", fc, YEAR, THROUGH, "tile-export")
    st.markdown("<div class='sec-header'>Monthly exports</div>",
                unsafe_allow_html=True)
    monthly_chart("Exports", EXPORT_COLOR, YEAR, "exp_monthly")
    st.markdown("<div class='sec-header'>Annual exports</div>",
                unsafe_allow_html=True)
    annual_chart("Exports", EXPORT_COLOR, fc, fc_year, "exp_annual")
    st.markdown("<div class='sec-header'>Top destinations</div>",
                unsafe_allow_html=True)
    country_table("Exports", YEAR, THROUGH, "exp_countries", "Destination")
    st.caption(
        "JSA's Export Sales dashboard reads **FAS ESR** — weekly net "
        "sales and shipments in thousand metric tons, product weight. This "
        "page reads **USDA ERS** — monthly customs-cleared trade in "
        "million pounds, carcass weight. They are different measurements of "
        "different things and will not agree; the ERS basis is the one WASDE "
        "forecasts, which is why it is the one here.")

with tab_imp:
    fc_year_i, fc_i = wasde_panel("imports", "Imports", "imp")
    st.write("")
    pace_panel("Imports", fc_i, YEAR, THROUGH, "tile-import")
    st.markdown("<div class='sec-header'>Monthly imports</div>",
                unsafe_allow_html=True)
    monthly_chart("Imports", IMPORT_COLOR, YEAR, "imp_monthly")
    st.markdown("<div class='sec-header'>Annual imports</div>",
                unsafe_allow_html=True)
    annual_chart("Imports", IMPORT_COLOR, fc_i, fc_year_i, "imp_annual")
    st.markdown("<div class='sec-header'>Top sources</div>",
                unsafe_allow_html=True)
    country_table("Imports", YEAR, THROUGH, "imp_countries", "Source")
    st.caption(
        "Lean imported trimmings and domestic fed beef are not substitutes "
        "— they meet in the grinder. An import figure is a read on the "
        "lean side of the blend, which is why it moves with the cow herd and "
        "90s trimmings rather than with the cutout.")

with tab_net:
    st.markdown("<div class='sec-header'>USDA WASDE expectation &mdash; "
                "net trade</div>", unsafe_allow_html=True)
    nb = beef_series(wd) if wd else None
    if nb:
        n_year = nb["year"]
        n_imp = nb["current"].get("imports")
        n_exp = nb["current"].get("exports")
        p_imp = nb["prior"].get("imports")
        p_exp = nb["prior"].get("exports")
        n_net = (n_imp - n_exp) if (n_imp is not None and n_exp is not None) else None
        p_net = (p_imp - p_exp) if (p_imp is not None and p_exp is not None) else None
        prev = beef_series(wd, n_year - 1)
        base_net = None
        if prev:
            bi, be = prev["current"].get("imports"), prev["current"].get("exports")
            base_net = (bi - be) if (bi is not None and be is not None) else None
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            net_rev = ((n_net - p_net)
                       if (n_net is not None and p_net is not None) else None)
            # p_net IS THE LEVEL AND IT IS ALREADY IN HAND. The two sides of
            # it are on the tiles either side, but a reader should not have to
            # subtract last month's imports from last month's exports -- and
            # last month's figures are not on the row at all, only this
            # month's. So the net tile carries its own base.
            st.markdown(tile(f"WASDE {n_year} net imports", fmt(n_net),
                             delta_pair(net_rev, pct(n_net, p_net),
                                        " vs " + (nb["prior_month"] or "last month"),
                                        base=p_net,
                                        base_label=(nb["prior_month"] or "last month")),
                             sub="imports less exports · calendar year",
                             cls="tile-wasde"),
                        unsafe_allow_html=True)
        with c2:
            st.markdown(tile(f"WASDE {n_year} imports", fmt(n_imp),
                             sub="million lb", cls="tile-wasde"),
                        unsafe_allow_html=True)
        with c3:
            st.markdown(tile(f"WASDE {n_year} exports", fmt(n_exp),
                             sub="million lb", cls="tile-wasde"),
                        unsafe_allow_html=True)
        with c4:
            net_yoy = pct(n_net, base_net)
            st.markdown(tile(
                f"USDA {n_year} forecast vs {n_year - 1}",
                (f"{net_yoy:+,.1f}%" if net_yoy is not None else "—"),
                delta_pair((n_net - base_net)
                           if (n_net is not None and base_net is not None)
                           else None, None, " million lb"),
                sub=f"{n_year - 1} actual net {fmt(base_net)}",
                cls="tile-wasde"), unsafe_allow_html=True)
        st.caption(
            "Net is computed from the two WASDE lines rather than taken from "
            "a published one — WASDE prints no net trade figure. Both "
            "legs come from the same report and the same month, so the "
            "subtraction is of two numbers USDA published together.")
    else:
        st.caption("No WASDE forecast available.")

    nt = tf.net_trade(trade)
    cur = nt[nt["year"] == YEAR]
    prev_y = nt[nt["year"] == YEAR - 1]
    st.markdown("<div class='sec-header'>Net imports by month</div>",
                unsafe_allow_html=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=nt["date"], y=nt["net"], mode="lines", name="Net imports",
        line=dict(color=NET_COLOR, width=2),
        hovertemplate="%{x|%b %Y}<br>%{y:,.0f} mil lb<extra></extra>"))
    fig.add_hline(y=0, line_color=DM_MUTED, line_width=1)
    fig.update_layout(
        height=360, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE, showlegend=False,
        xaxis={**AXIS, "rangeslider": dict(visible=False)},
        yaxis={**AXIS, "title": "million lb (imports − exports)"})
    st.plotly_chart(fig, use_container_width=True, key="net_monthly")
    # COMPUTED, AND IT CORRECTED ME. This caption asserted "the US crossed
    # over durably in 2024" until the series was checked: the run starts in
    # 2023, and the US was a net EXPORTER as recently as 2021 and 2022. The
    # sign is not the news -- the scale is. See trade_flows.net_run.
    run = tf.net_run(trade)
    if run["start"]:
        st.caption(
            f"Positive is a net import. The US has been a net importer for "
            f"**{run['years']} straight years** now, since {run['start']} "
            f"— but the sign is not the news. It has crossed back and "
            f"forth {run['flipped']} times over the complete years on file "
            f"and was a net EXPORTER as recently as 2022. What is new is the "
            f"scale: {run['first']:,.0f} million lb net in {run['start']} "
            f"against {run['latest']:,.0f} in "
            f"{run['start'] + run['years'] - 1}.")
    else:
        st.caption("Positive is a net import.")

    if not cur.empty:
        c1, c2, c3 = st.columns(3)
        ytd_net = float(cur["net"].sum())
        ytd_prev = float(prev_y[prev_y["month"] <= THROUGH]["net"].sum()) if not prev_y.empty else None
        with c1:
            # NOT A WASDE TILE, SAME DEFECT. "▲ 774 · 38.5% vs 2025" over
            # 2,784 never said last year's Jan-Aug was 2,010, and unlike the
            # forecast rows there is no neighbouring tile carrying it -- the
            # other two on this row are THIS year's exports and imports. The
            # label names the window, so the base says the year.
            st.markdown(tile(f"{YEAR} YTD net imports", fmt(ytd_net),
                             delta_pair((ytd_net - ytd_prev) if ytd_prev else None,
                                        pct(ytd_net, ytd_prev),
                                        f" vs {YEAR - 1}",
                                        base=ytd_prev,
                                        base_label=f"{YEAR - 1} same months"),
                             sub=f"Jan–{tf.month_name(THROUGH)}",
                             cls="tile-net"), unsafe_allow_html=True)
        with c2:
            st.markdown(tile(f"{YEAR} YTD exports",
                             fmt(float(cur["exports"].sum())),
                             sub="million lb", cls="tile-export"),
                        unsafe_allow_html=True)
        with c3:
            st.markdown(tile(f"{YEAR} YTD imports",
                             fmt(float(cur["imports"].sum())),
                             sub="million lb", cls="tile-import"),
                        unsafe_allow_html=True)


# -- provenance and the basis check -----------------------------------------

st.markdown("<hr style='margin:22px 0 14px;'>", unsafe_allow_html=True)

with st.expander("Sources, basis, and the check that licenses this page"):
    chk = None
    if wd:
        last_full = YEAR - 1
        prev_row = beef_series(wd, last_full)
        if prev_row:
            chk = tf.basis_agrees(
                trade, last_full,
                prev_row["current"].get("imports"),
                prev_row["current"].get("exports"))
    if chk and chk["ok"] is True:
        st.success(
            f"**Same series, verified live.** For {chk['year']} this ERS file "
            f"totals {chk['ers_imports']:,.1f} million lb of imports and "
            f"{chk['ers_exports']:,.1f} of exports; WASDE prints "
            f"{chk['wasde_imports']:,.0f} and {chk['wasde_exports']:,.0f}. "
            "The actual-versus-forecast panels compare the same number, not "
            "two similar ones.")
    elif chk and chk["ok"] is False:
        st.error(
            f"**ERS and WASDE have diverged for {chk['year']}**: ERS "
            f"{chk['ers_imports']:,.1f} imports / {chk['ers_exports']:,.1f} "
            f"exports against WASDE {chk['wasde_imports']:,.0f} / "
            f"{chk['wasde_exports']:,.0f}. Until that is understood the "
            "pace-against-forecast figures are comparing different series "
            "and should not be acted on.")
    else:
        st.caption("Basis check unavailable — no complete prior year in "
                   "both sources yet.")

    st.markdown(f"""
**Actuals** &mdash; USDA Economic Research Service, *Livestock and Meat
International Trade Data*, beef & veal monthly, carcass-weight basis,
1,000 lb (converted to million lb here). Monthly back to 1989, by partner
country. Currently through **{tf.month_name(THROUGH)} {YEAR}**.
[{tf.ERS_PAGE}]({tf.ERS_PAGE})

**Forecast** &mdash; USDA WASDE, *U.S. Meats Supply and Use*, via USDA ESMIS.
{('Report ' + wd['report_month']) if wd else ''}
{('[release](' + wd['source_url'] + ')') if wd and wd.get('source_url') else ''}

**Reconciliation** &mdash; the partner countries sum to USDA's published World
total across all {_rec['checked']} month/flow pairs on file
(worst gap {_rec['worst']:,.3f} million lb). Every headline figure reads
USDA's own total rather than a sum, and the check runs on every load.

**What this page is not.** It is customs-cleared trade, not export *sales*:
JSA's [Export Sales dashboard](https://www.jpsi.com/export-sales-dashboard/)
reads FAS ESR weekly in product-weight metric tons and answers a different
question. Neither is more correct; they are different measurements.
""")

    csv = trade.copy()
    csv["flow_month"] = csv["year"].astype(str) + "-" + csv["month"].astype(str).str.zfill(2)
    st.download_button(
        "Download the full ERS series (CSV)",
        csv.to_csv(index=False).encode("utf-8"),
        file_name=f"us_beef_trade_ers_through_{YEAR}_{THROUGH:02d}.csv",
        mime="text/csv", key="dl_trade")

if st.button("Refresh data", key="refresh"):
    st.cache_data.clear()
    st.rerun()
