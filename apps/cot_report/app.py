"""
Commitment of Traders -- where the funds are positioned in the cattle futures.

THE PAGE EXISTS FOR TWO NUMBERS. Managed money net futures position in Live
Cattle, and in Feeder Cattle. They are the first thing on the page, they are
above the tabs, and they are above the outage guard. Everything else here is
context for them and is arranged so it cannot push them below the fold.

WHY IT IS WORTH A PAGE WHEN THE LETTER ALREADY PRINTS THE SAME TWO FIGURES.
The Friday letter's CFTC block gives the net and the week's change, which is
the right amount for a letter. What it cannot give is the thing that makes
either number mean anything: that 53,193 Live Cattle contracts is the 47th
percentile of twenty years and the 26th of the last five; that the funds have
been net long for 338 straight weeks; that the week's rise was short covering
rather than new buying; and that producers and merchants are net short 95,274
on the other side of it. See `cot_positions.py` for the proof that the two
surfaces quote the same figure to the contract.

THE HEADLINE BAND AND THE FRESHNESS LINE RENDER ABOVE THE OUTAGE GUARD, the
same four-line shape as the Saturday Slaughter view and the morning cutout
panel. There is only one source here, so an outage takes the whole page -- but
it must take it LOUDLY, naming the reason, rather than drawing an empty chart.

A NET IS A PLAUSIBLE NUMBER WHETHER OR NOT IT IS RIGHT. Nothing on this page
fails loudly on its own, which is why `cot_positions.reconciles()` runs on
every load and the audit line under the tiles says so out loud.
"""
import os
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# A Streamlit page's own directory is never added to sys.path automatically --
# st.Page runs this file via exec() rather than as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# On Streamlit Community Cloud the secrets live in st.secrets rather than in a
# local .env, and `snowflake_db.get_conn()` reads os.environ only. Forward them.
#
# SNOWFLAKE_SCHEMA IS DELIBERATELY ABSENT FROM THIS LIST, and that is the one
# difference from the block in apps/cme_feeder_cattle/app.py that this is
# copied from. Nine bundled modules each default it to the schema THEY own, so
# forwarding one value overrides all nine and their queries miss silently --
# pages load, charts come back empty, nothing raises. CLAUDE.md is explicit
# that unset is the only working configuration, so this page declines to
# forward it even if somebody adds it to the console. `cot_positions` names
# JSA.CFTC_COT in full and would not read it anyway.
#
# THIS BLOCK IS NOT OPTIONAL AND IS NOT INHERITED. A page only gets os.environ
# populated if some page that forwards has already run in this process, and
# with st.navigation only the SELECTED page's script executes -- so a reader
# who lands straight on /commitment-of-traders as the first request a fresh
# container ever serves would otherwise find no credentials at all.
try:
    for _k in ("USE_SNOWFLAKE", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER",
               "SNOWFLAKE_PASSWORD", "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE",
               "SNOWFLAKE_DATABASE", "SNOWFLAKE_PRIVATE_KEY",
               "SNOWFLAKE_PRIVATE_KEY_PWD", "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # noqa: BLE001
    pass  # no secrets.toml locally -- the .env has already been read

import cot_positions as cot          # noqa: E402

# -- JSA brand ---------------------------------------------------------------
JSA_GREEN    = "#5e7164"

DM_BG       = "#f6f8f7"
DM_SURFACE  = "#ffffff"
DM_BORDER   = "#d7e2dc"
DM_TEXT     = "#32373c"
DM_MUTED    = "#5f7267"
COL_POS     = "#16a34a"
COL_NEG     = "#dc2626"
COL_NEU     = "#5f7267"

LIVE_COLOR   = "#6fa8c4"
FEEDER_COLOR = "#c4785a"
LONG_COLOR   = "#16a34a"
SHORT_COLOR  = "#dc2626"
SPREAD_COLOR = "#b8c4bc"
OI_COLOR     = "#9b89c4"

MARKET_COLOR = {"LIVE_CATTLE": LIVE_COLOR, "FEEDER_CATTLE": FEEDER_COLOR}
MARKET_CLS   = {"LIVE_CATTLE": "tile-live", "FEEDER_CATTLE": "tile-feeder"}

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
  .tile-live   {{ border-top-color:{LIVE_COLOR}; }}
  .tile-feeder {{ border-top-color:{FEEDER_COLOR}; }}
  .hero {{
    background:{DM_SURFACE}; border:1px solid {DM_BORDER};
    border-top:4px solid {JSA_GREEN}; border-radius:12px;
    padding:20px 24px 18px; height:100%;
  }}
  .hero-market {{
    color:{DM_TEXT}; font-family:'EB Garamond',Georgia,serif;
    font-size:1.05rem; font-weight:600; letter-spacing:0.2px;
  }}
  .hero-label {{
    color:{DM_MUTED}; font-size:0.66rem; text-transform:uppercase;
    letter-spacing:0.09em; margin:2px 0 10px;
  }}
  .hero-value {{ color:{DM_TEXT}; font-size:2.6rem; font-weight:700; line-height:1; }}
  .hero-side-long  {{ color:{COL_POS}; font-size:1.25rem; font-weight:700; }}
  .hero-side-short {{ color:{COL_NEG}; font-size:1.25rem; font-weight:700; }}
  .hero-unit {{ color:{DM_MUTED}; font-size:0.74rem; margin-top:6px; }}
  .hero-delta-neu {{ color:{COL_NEU}; font-size:0.92rem; font-weight:600; margin-top:10px; }}
  .hero-delta-pos {{ color:{COL_POS}; font-size:0.92rem; font-weight:600; margin-top:10px; }}
  .hero-delta-neg {{ color:{COL_NEG}; font-size:0.92rem; font-weight:600; margin-top:10px; }}
  .hero-legs {{ color:{DM_MUTED}; font-size:0.76rem; margin-top:8px; line-height:1.5; }}
  .sec-header {{
    color:{DM_MUTED}; font-size:0.7rem; text-transform:uppercase;
    letter-spacing:0.1em; padding:10px 0 4px; border-bottom:1px solid {DM_BORDER};
    margin-bottom:12px;
  }}
  .asof {{
    background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-radius:8px;
    padding:10px 16px; color:{DM_MUTED}; font-size:0.82rem; margin-bottom:6px;
  }}
  .asof b {{ color:{DM_TEXT}; }}
  hr {{ border-color:{DM_BORDER}; }}
  #MainMenu, footer {{ visibility:hidden; }}
  .stDeployButton {{ display:none; }}
</style>
""", unsafe_allow_html=True)


# -- small helpers -----------------------------------------------------------

def fmt(v, digits=0, suffix=""):
    return f"{v:,.{digits}f}{suffix}" if v is not None and pd.notna(v) else "—"


def signed_words(net):
    """
    "53,193 long" / "9,589 short" / "flat".

    THE DIRECTION IS A WORD. A net short written -9,589 is fine and written
    (9,589) is a disaster: in CFTC's and USDA's own reports parentheses mean
    NEGATIVE, so the audience most fluent in those reports reads it as a long.
    Managed money is net short feeder cattle in roughly one week of four, so
    this is the live case rather than the theoretical one.
    """
    if net is None or pd.isna(net):
        return "—", ""
    s = cot.side(net)
    if s == "flat":
        return "flat", ""
    return f"{abs(net):,.0f}", s


def delta_html(val, unit="contracts", suffix="", digits=0, neutral=True,
               invert=False, cls="tile-delta"):
    """
    An arrow and an unsigned figure, or words when there is nothing to show.

    NEUTRAL BY DEFAULT, and that is a decision rather than laziness. Funds
    adding length is bullish for the board, which is welcome news to a feeder
    with cattle to sell and unwelcome to a packer with cattle to buy, and the
    page does not know which of them is reading it. Green and red are spent
    only on the direction of the POSITION ITSELF -- long or short -- which is
    a state and not a judgement.

    THE ARROW CARRIES THE SIGN, so the figure after it is never signed too.
    """
    if val is None or pd.isna(val):
        return f'<div class="{cls}-neu">&mdash;</div>'
    if val == 0:
        # A bare "0" reads as a figure that failed to load. The funds not
        # moving in a week is a real and occasionally striking answer.
        return f'<div class="{cls}-neu">unchanged{suffix}</div>'
    up = val > 0
    good = (not up) if invert else up
    color = "neu" if neutral else ("pos" if good else "neg")
    arrow = "▲" if up else "▼"
    unit = f" {unit}" if unit else ""
    return (f'<div class="{cls}-{color}">{arrow} '
            f'{abs(val):,.{digits}f}{unit}{suffix}</div>')


def tile(label, value, delta="", sub="", cls=""):
    sub_html = f'<div class="tile-sub">{sub}</div>' if sub else ""
    return (f'<div class="tile {cls}">'
            f'<div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>'
            f'{delta}{sub_html}</div>')


def _us(d):
    """M/D/YY without the platform-specific strftime flags."""
    if d is None:
        return "—"
    return f"{d.month}/{d.day}/{str(d.year)[2:]}"


def movement_words(delta):
    """
    A change in NET as "4,342 bought" / "59,238 sold" / "unchanged".

    BUY AND SELL LANGUAGE WORKS AT EVERY SIGN, which is why it is used here
    instead of "more net long". A net short that becomes less short is buying;
    a net long that becomes less long is selling; and a position that crosses
    zero is both, described correctly either way. "More net long" is wrong the
    moment the position is short, and feeder cattle is net short in about one
    week of four.
    """
    if delta is None or pd.isna(delta):
        return "—"
    if delta == 0:
        return "unchanged"
    return f"{abs(delta):,.0f} {'bought' if delta > 0 else 'sold'}"


def ordinal(p):
    """43.0 -> '43rd'. Percentiles read as ranks, so they are printed as ranks."""
    if p is None or pd.isna(p):
        return "—"
    n = int(round(p))
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


# -- data --------------------------------------------------------------------

@st.cache_data(ttl=1800, persist="disk", show_spinner="Reading CFTC positions…")
def load_cot(schema: int = cot.SCHEMA, epoch=None) -> dict:
    """
    The whole page's data, in two queries.

    =====================================================================
    `epoch` IS WHAT MAKES THE PAGE PICK UP FRIDAY'S REPORT ON FRIDAY
    =====================================================================

    CFTC publishes at 2:30pm CT and the ETL loads Snowflake at 3pm, but a TTL
    knows about neither: it is a stopwatch started by whoever last opened the
    page. On an hour's TTL a reader could be served the previous Tuesday's
    positions until 4pm on a Friday the new report landed at 3 -- correctly
    computed, correctly dated, and a week old.

    `cot.data_epoch()` rolls over at 3pm Friday, so passing it here makes the
    cache expire ON THE EVENT rather than on a timer. The TTL stays as a
    backstop: if the ETL is late the epoch has already rolled, the refetch
    returns the old week, and half an hour later it tries again.

    `schema` is in the signature ONLY to key the cache. `st.cache_data` keys on
    the decorated function's own code and its arguments and never on the modules
    it calls, so without it a change to `cot_positions.load()` would leave this
    serving a dict from before the change and the tiles reading a key that is no
    longer there -- rendering an em dash with nothing raising. The identical trap
    is recorded against `leverage.SCHEMA` in CLAUDE.md.

    =====================================================================
    TWO CONDITIONS, AND THE GUARD IS INERT UNLESS BOTH HOLD
    =====================================================================

    1. NO LEADING UNDERSCORE. Streamlit deliberately excludes any parameter
       whose name begins with one from the cache key -- that is the documented
       way to pass unhashable things like a database handle into a cached
       function -- so a `_schema` argument is hashed exactly never.
    2. THE CALLER MUST PASS IT. Only arguments actually supplied are hashed;
       DEFAULTS ARE NOT PART OF THE KEY AT ALL. So `schema=mod.SCHEMA` sitting
       in the signature while every call site writes `load_x()` is just as
       inert as the underscore form, in a way that looks fixed.

    Measured rather than assumed, on the Streamlit in this venv:

        @st.cache_data
        def f(_schema=1, normal=0): ...
        f(); f(2); f(1); f(1, 9)   ->  body ran for (1,0) and (1,9) only;
                                       f(2) was served from the cache

        @st.cache_data
        def g(schema=1): ...
        g(); g(2); g(1)            ->  body ran for 1, 2, 1
        g(); g(1); g(); g(1)       ->  body ran TWICE, not once -- so f()
                                       and f(1) are different keys, which
                                       is only possible if the default is
                                       absent from the key rather than
                                       resolved into it

    THE SECOND CONDITION WAS MISSED ON THE FIRST PASS AT THIS, which is worth
    recording because the result was a fix that looked complete: the underscore
    came off, the constant got bumped, a test asserted the signature, and the
    cache went on ignoring all of it because the call site still read
    `load_cot()`. That is the shape CLAUDE.md records under the feeder index --
    a first fix that shipped the same bug with a label on it.

    THE TRAP IT IS MEANT TO CATCH FIRED ON THIS VERY PAGE while it was being
    built: `why()` gained an `agree` key, the hero tile read `.get("agree")`,
    the cached dict predated it, `.get` returned None, the tile printed the
    wrong sentence, and `persist="disk"` carried the stale dict across two full
    server restarts. Nothing raised at any point.

    The other eighteen loaders in this repo were corrected the same way; see
    the CLAUDE.md section. `apps/cash_trade/app.py::fetch_leverage` is the one
    that was right all along, and is worth reading as the model: unprefixed,
    and passed `leverage.SCHEMA` at the call site.

    FRAMES ARE RETURNED AS DATAFRAMES AND THAT IS FINE -- st.cache_data pickles
    what it stores and a DataFrame pickles cleanly. What must never go in here is
    a dataclass, which goes stale against its own class the moment its module is
    edited; `load()` returns plain dicts for exactly that reason.

    An hour, because CFTC publishes once a week. The TTL is there to pick up a
    revision landing in the ETL's eight-week re-pull, not to chase a live feed.
    """
    return cot.load()


# -- the page ----------------------------------------------------------------

st.markdown(
    f"<h3 style='margin-bottom:2px;color:{DM_TEXT};"
    f"font-family:\"EB Garamond\",Georgia,serif'>Commitment of Traders</h3>"
    f"<div style='color:{DM_MUTED};font-size:0.86rem;margin-bottom:14px'>"
    "Where the speculative funds are positioned in the cattle futures — "
    "CFTC's weekly Disaggregated report, futures only."
    "</div>",
    unsafe_allow_html=True,
)

if not cot.enabled():
    st.error(
        "**Snowflake is not configured for this app, so there are no CFTC "
        "positions to show.** This page reads `JSA.CFTC_COT` and needs "
        "`USE_SNOWFLAKE=1` plus the Snowflake connection block in the app's "
        "secrets. It needs no new API key and no new host."
    )
    st.stop()

data = load_cot(cot.SCHEMA, cot.data_epoch())

if data.get("error"):
    st.error(
        "**The CFTC positions could not be read, so nothing on this page is "
        f"current.** `{data['error']}`\n\nThe source is `{cot.VIEW}`, loaded by "
        "the droplet job in `JSA-Dashboards/cftc-cot-etl` on Fridays at 3pm CT. "
        "A failure here is a connection or a grant, never a parse — the data is "
        "already in Snowflake."
    )
    st.stop()

markets = data.get("markets") or {}
fresh = data.get("freshness") or {}
age = data.get("position_age_days")

# -- the as-of line, which has to be read before the figures ------------------
#
# THE COMMONEST WAY THIS REPORT IS MISREAD is as a current position. It is not
# one and never can be: the positions are taken at TUESDAY's close and are not
# published until FRIDAY, so the freshest possible reading is three days old
# when it appears and is nine days old by the Thursday after. The age is
# computed, printed in days, and sits above the figures rather than under them.
as_of = data.get("as_of")
released = (as_of + timedelta(days=3)) if as_of else None
age_phrase = (f"These positions are <b>{age} days old</b>."
              if age is not None else "")
st.markdown(
    f'<div class="asof">Managed money positions as they stood at the close on '
    f'<b>Tuesday {_us(as_of)}</b>, published by CFTC on Friday {_us(released)}. '
    f'{age_phrase} CFTC publishes once a week and never intraday, so this is '
    f'the most recent reading that exists — it is not a position held today.'
    f'</div>',
    unsafe_allow_html=True,
)

if not fresh.get("current"):
    weeks = fresh.get("weeks_behind")
    st.warning(
        f"**The newest CFTC report on file is {weeks} week"
        f"{'s' if weeks != 1 else ''} behind.** The latest report date here is "
        f"{_us(fresh.get('as_of'))}; by the release calendar CFTC should have "
        f"published {_us(fresh.get('expected'))} by now. Every figure below is "
        "correctly computed and describes an older week — the ETL "
        "(`JSA-Dashboards/cftc-cot-etl`, Fridays 3pm CT) has probably not run."
    )

# -- THE TWO FIGURES THE PAGE EXISTS FOR -------------------------------------

hero_cols = st.columns(2)
for col, series in zip(hero_cols, cot.CATTLE):
    m = markets.get(series)
    with col:
        if not m:
            st.markdown(
                f'<div class="hero"><div class="hero-market">'
                f'{cot.LABELS.get(series, series)}</div>'
                '<div class="hero-label">no rows returned</div></div>',
                unsafe_allow_html=True)
            continue
        L, W = m["latest"], m["why"]
        mag, word = signed_words(L["net"])
        side_cls = "hero-side-long" if word == "long" else "hero-side-short"
        side_html = f' <span class="{side_cls}">{word}</span>' if word else ""

        # The label names the figure in full. "Managed money net" alone would
        # not say whose, which market, or on what contract basis -- and a tile
        # gets screenshotted away from the header above it.
        legs = (f'Long {L["long"]:,.0f} against short {L["short"]:,.0f}'
                f' · spreading {fmt(L["spread"])}')
        # "mostly X" only parses when ONE leg carried the week. When the two
        # legs moved together the phrase is already a whole clause -- "both
        # sides added" -- and "mostly both sides added" is not English.
        if not W.get("phrase"):
            driver = ""
        elif W.get("agree"):
            driver = f'<br>The week\'s move was mostly <b>{W["phrase"]}</b>'
        else:
            driver = f'<br><b>{W["phrase"].capitalize()}</b>, so the net barely moved'
        st.markdown(
            f'<div class="hero" style="border-top-color:{MARKET_COLOR[series]}">'
            f'<div class="hero-market">{m["label"]}</div>'
            f'<div class="hero-label">Managed money net futures position</div>'
            f'<div class="hero-value">{mag}{side_html}</div>'
            f'<div class="hero-unit">contracts, as of Tuesday {_us(L["as_of"])}</div>'
            f'{delta_html(L["wow"], unit="contracts", suffix=" vs week earlier", cls="hero-delta")}'
            f'<div class="hero-legs">{legs}{driver}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.write("")

# -- the audit, said out loud ------------------------------------------------
audit = data.get("audit") or {}
if audit.get("net_ok") and audit.get("chg_ok"):
    st.caption(
        f"✓ Checked on load across all {audit.get('rows', 0):,} cattle rows: every "
        "net equals its own long less short, and every week-over-week change "
        "equals CFTC's own published change column. Both identities hold exactly "
        "on the futures-only basis."
    )
else:
    bad = []
    if not audit.get("net_ok"):
        bad.append(f"{audit.get('net_bad', 0)} rows where the net does not equal "
                   "long less short")
    if not audit.get("chg_ok"):
        bad.append(f"{audit.get('chg_bad', 0)} weeks where CFTC's published change "
                   "does not match the change in the levels")
    st.error("**The source data no longer reconciles with itself: "
             + "; ".join(bad) + ".** Treat every figure on this page as suspect "
             "until that is explained — these identities have held on every row "
             "since 2006.")
if audit.get("oi_ok") is False:
    st.error(
        f"**Open interest and the sum of the five categories differ by up to "
        f"{audit.get('oi_worst', 0):,.0f} contracts.** On the futures-only basis "
        "that identity has been exact on every row since 2006 — a residual here "
        "is a shifted column, not rounding."
    )

cross = data.get("cross_audit") or {}
if cross.get("ok") is False:
    st.error(
        f"**The disaggregated and legacy views no longer reconcile**: "
        f"non-commercial net should equal managed money plus other reportables, "
        f"and it fails on {cross.get('bad', 0)} of {cross.get('rows', 0)} weeks "
        f"(worst {cross.get('worst', 0):,.0f} contracts). That identity is CFTC's "
        "own definition, so a break means the join between the two views is wrong."
    )

# -- THE SAME WEEK, QUOTED THREE WAYS -----------------------------------------
#
# THIS SITS DIRECTLY UNDER THE HEADLINE AND NOT AT THE BOTTOM OF THE PAGE, and
# the placement is the whole point. What it exists to prevent is a client
# ringing up because this page says the funds are net LONG feeder cattle while
# his broker's screen says they are net SHORT -- which is true today, both
# figures are CFTC's, and both are futures-only. A reconciliation a reader has
# to scroll past four charts to find cannot do that job.
#
# The gap is not an estimate and is not described as one. CFTC's older Legacy
# report had a single "non-commercial" bucket; the Disaggregated report split it
# into managed money and other reportables, so
#
#     non-commercial  =  managed money  +  other reportables
#
# exactly, on all 1,060 weeks of both cattle markets. Feeder cattle's other
# reportables are 10,247 net SHORT this week, which is the entire difference and
# the entire sign flip.

recs = {s: (markets.get(s) or {}).get("reconciliation") or {} for s in cot.CATTLE}
split = [s for s in cot.CATTLE if recs.get(s, {}).get("sign_split")]

st.markdown('<div class="sec-header">The same week, quoted three ways</div>',
            unsafe_allow_html=True)

if split:
    names = " and ".join(cot.LABELS[s] for s in split)
    st.warning(
        f"**On {names} this week, managed money and the older report are on "
        "opposite sides of the market — and both are right.** This page leads "
        "with managed money, which is CFTC's Disaggregated category for the "
        "speculative funds. Many broker screens and chart services still quote "
        "the Legacy report's single *non-commercial* bucket as \"the funds\"; "
        "that bucket is managed money **plus** other reportables, and the other "
        "reportables are heavily short. Neither figure is wrong — they count "
        "different traders."
    )

recon_rows = []
LABEL_FUT = "Managed money net, futures only — this page, and the JSA Friday letter"
LABEL_COMB = "Managed money net, futures and options combined"
LABEL_LEG = "Non-commercial net, CFTC's older Legacy report"
for key, lbl in (("fut_net", LABEL_FUT), ("combined_net", LABEL_COMB),
                 ("legacy_net", LABEL_LEG)):
    row = {"What a reader may see quoted": lbl}
    for s in cot.CATTLE:
        v = recs.get(s, {}).get(key)
        row[cot.LABELS[s]] = ("—" if v is None
                              else f"{abs(v):,.0f} {cot.side(v)}")
    recon_rows.append(row)
st.dataframe(pd.DataFrame(recon_rows), use_container_width=True, hide_index=True)

_other = {s: (markets.get(s) or {}).get("latest", {}) for s in cot.CATTLE}
_on = {s: (recs.get(s, {}) or {}).get("other_net") for s in cot.CATTLE}
st.caption(
    "**Non-commercial equals managed money plus other reportables — exactly, "
    "every week since 2006**, which is why the three figures above differ and "
    "by how much. Other reportables are "
    + ", ".join(
        f"{abs(_on[s]):,.0f} net {cot.side(_on[s])} in {cot.LABELS[s]}"
        for s in cot.CATTLE if _on.get(s) is not None)
    + ". The futures-and-options figure is the same traders on a wider basis: "
    "CFTC converts their options to futures equivalents on a delta basis, which "
    "is why it never reconciles quite exactly and why this page does not lead "
    "with it. That identity is checked on every load, across all "
    f"{cross.get('rows', 0):,} market-weeks on file."
)

st.write("")

# -- charts ------------------------------------------------------------------

WINDOWS = {"1 yr": 1, "3 yr": 3, "5 yr": 5, "Since 2006": None}


def net_figure(frame: pd.DataFrame, color: str, as_share: bool = False):
    """
    Managed money net over time, filled to zero and SPLIT AT THE ZERO LINE.

    The split is not decoration. Feeder cattle has been net short in 248 of its
    1,060 weeks, and a single-colour area makes a crossing of zero -- the one
    event on this chart that changes what the position IS rather than how big
    it is -- look like any other wiggle. Green above, red below, and a zero
    line drawn darker than the rest of the grid.

    `as_share` plots the net as a percentage of open interest instead of a
    contract count. That is the honest comparison whenever the window reaches
    back more than a few years: feeder cattle open interest has roughly doubled
    since 2006-2010, so the same contract count was a far bigger bet then.
    """
    col = "net_pct_oi" if as_share else "mm_net"
    y = frame[col]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=frame["report_date"], y=y.clip(lower=0), mode="lines",
        line=dict(width=0.8, color=LONG_COLOR), fill="tozeroy",
        fillcolor="rgba(22,163,74,0.20)", name="net long",
        hovertemplate="%{x|%b %-d, %Y}<br>net %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=frame["report_date"], y=y.clip(upper=0), mode="lines",
        line=dict(width=0.8, color=SHORT_COLOR), fill="tozeroy",
        fillcolor="rgba(220,38,38,0.20)", name="net short",
        hovertemplate="%{x|%b %-d, %Y}<br>net %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=frame["report_date"], y=y, mode="lines",
        line=dict(width=1.6, color=color), name="managed money net",
        hoverinfo="skip",
    ))
    fig.add_hline(y=0, line_width=1.2, line_color=DM_MUTED)
    fig.update_layout(
        height=340, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE,
        showlegend=False, hovermode="x unified",
        xaxis=dict(**AXIS), yaxis=dict(**AXIS,
                                       title="% of open interest" if as_share
                                       else "contracts"),
    )
    return fig


def legs_figure(frame: pd.DataFrame):
    """Gross long, gross short and spreading, so the net can be taken apart."""
    fig = go.Figure()
    for col, name, color in (("mm_long", "Long", LONG_COLOR),
                             ("mm_short", "Short", SHORT_COLOR),
                             ("mm_spread", "Spreading", SPREAD_COLOR)):
        fig.add_trace(go.Scatter(
            x=frame["report_date"], y=frame[col], mode="lines", name=name,
            line=dict(width=1.5, color=color),
            hovertemplate=name + " %{y:,.0f}<extra></extra>",
        ))
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE, hovermode="x unified",
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11, color=DM_MUTED)),
        xaxis=dict(**AXIS), yaxis=dict(**AXIS, title="contracts"),
    )
    return fig


def categories_figure(rows: list):
    """
    Every category's net for the newest week, as a horizontal bar through zero.

    THE BARS MUST SUM TO ZERO and the eye should be able to see that they do.
    Managed money net long 53,193 is only half a sentence; the other half is
    that producers, merchants and processors are net short 95,274 against it.
    """
    rows = list(reversed(rows))
    fig = go.Figure(go.Bar(
        x=[r["net"] for r in rows],
        y=[r["label"] for r in rows],
        orientation="h",
        marker_color=[LONG_COLOR if r["net"] >= 0 else SHORT_COLOR for r in rows],
        hovertemplate="%{y}<br>net %{x:,.0f} contracts<extra></extra>",
    ))
    fig.add_vline(x=0, line_width=1.2, line_color=DM_MUTED)
    fig.update_layout(
        height=250, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE, showlegend=False,
        xaxis=dict(**AXIS, title="net contracts — long above zero, short below"),
        # {**AXIS, ...} and NOT dict(**AXIS, showgrid=False): AXIS already
        # carries showgrid, and the keyword form raises TypeError on the
        # duplicate rather than overriding it.
        yaxis={**AXIS, "showgrid": False},
    )
    return fig


# -- one market's detail ------------------------------------------------------

def market_panel(series: str):
    m = markets.get(series)
    if not m:
        st.info(f"No rows returned for {cot.LABELS.get(series, series)}.")
        return
    L, C, W = m["latest"], m["context"], m["why"]
    color = MARKET_COLOR.get(series, JSA_GREEN)
    label = m["label"]

    # -- where this week sits in twenty years --------------------------------
    st.markdown('<div class="sec-header">How big is this position, '
                'historically</div>', unsafe_allow_html=True)
    c = st.columns(4)
    c[0].markdown(tile(
        f"{label} net vs its own 20-year record",
        ordinal(C["net_pctile"]) + " percentile",
        sub=(f"of {C['weeks_total']:,} weekly readings since "
             f"{C['history_from'].year}"),
        cls=MARKET_CLS.get(series, "")), unsafe_allow_html=True)
    c[1].markdown(tile(
        f"{label} net vs the last {C['recent_years']} years",
        ordinal(C["net_pctile_recent"]) + " percentile",
        sub="the era the market is actually trading in",
        cls=MARKET_CLS.get(series, "")), unsafe_allow_html=True)
    hi_mag, hi_word = signed_words(C["record_high"])
    lo_mag, lo_word = signed_words(C["record_low"])
    # "IN CONTRACTS" IS NOT PADDING. Feeder Cattle open interest has grown
    # about 4% a year since 2006, so the biggest bet in contracts and the
    # biggest bet relative to the market are not the same week and a tile
    # saying merely "most net long ever" is picking one without saying which.
    c[2].markdown(tile(
        f"{label} most net long ever, in contracts",
        f"{hi_mag} {hi_word}",
        sub=f"week of {_us(C['record_high_on'])}",
        cls=MARKET_CLS.get(series, "")), unsafe_allow_html=True)
    c[3].markdown(tile(
        (f"{label} most net short ever, in contracts" if C["record_low"] < 0
         else f"{label} least net long ever, in contracts"),
        f"{lo_mag} {lo_word}",
        sub=f"week of {_us(C['record_low_on'])}",
        cls=MARKET_CLS.get(series, "")), unsafe_allow_html=True)

    st.write("")
    c = st.columns(4)
    # EACH FIGURE PRINTS ONCE. The first version of these two tiles carried the
    # change as the value AND as the delta underneath it -- "4,342" over
    # "▲ 4,342 contracts over 4 weeks" -- which is the same fault CLAUDE.md
    # records against the cash forecast tiles that printed the actual twice:
    # it reads as two findings that happen to agree. The value is the move, the
    # sub-line is the two levels it moved between, and nothing repeats.
    four_from = C["net_4wk_ago"]
    c[0].markdown(tile(
        f"{label} net — managed money's last 4 weeks",
        movement_words(C["chg_4wk"]),
        sub=(f"{abs(four_from):,.0f} {cot.side(four_from)} four weeks ago, "
             f"{abs(C['net']):,.0f} {cot.side(C['net'])} now"
             if four_from is not None else "a month of positioning, not one week of noise")),
        unsafe_allow_html=True)
    yr_from = C["net_year_ago"]
    c[1].markdown(tile(
        f"{label} net — managed money's last 12 months",
        movement_words(C["chg_year"]),
        sub=(f"{abs(yr_from):,.0f} {cot.side(yr_from)} on {_us(C['net_year_ago_on'])}, "
             f"{abs(C['net']):,.0f} {cot.side(C['net'])} now"
             if yr_from is not None else "no reading a year back")),
        unsafe_allow_html=True)
    c[2].markdown(tile(
        f"{label} — weeks running net {L['side']}",
        f"{C['weeks_on_this_side']:,}",
        sub=(f"net short in {C['weeks_net_short']:,} of "
             f"{C['weeks_total']:,} weeks on record")),
        unsafe_allow_html=True)
    # THE WINDOW IS NAMED HERE TOO. Every other percentile on this page says
    # which history it is measured against, and a bare "62nd percentile" was
    # the one left that did not -- the same headline-reads-alone rule, and the
    # easiest place to break it because the tile's own value is a percentage.
    c[3].markdown(tile(
        f"{label} net as a share of open interest",
        fmt(C["net_pct_oi"], 1, "%"),
        sub=(f"{ordinal(C['net_pct_oi_pctile'])} percentile of the full "
             f"{C['history_from'].year}–{C['as_of'].year} record — the "
             "comparison that survives open interest growing")),
        unsafe_allow_html=True)

    st.caption(
        f"The week's move of {abs(L['wow']):,.0f} contracts was "
        f"{ordinal(C['chg_pctile_abs'])} percentile by size against every weekly "
        f"move since {C['history_from'].year}; the largest ever were "
        f"{C['chg_biggest_up']:,.0f} up and {abs(C['chg_biggest_down']):,.0f} down. "
        f"Longs {'added' if W['long_chg'] >= 0 else 'cut'} "
        f"{abs(W['long_chg']):,.0f} and shorts "
        f"{'added' if W['short_chg'] >= 0 else 'cut'} {abs(W['short_chg']):,.0f}, "
        f"so the week reads as {W['phrase']}."
    )

    # -- the chart ------------------------------------------------------------
    st.write("")
    st.markdown(f'<div class="sec-header">{label} — managed money net position, '
                'week by week</div>', unsafe_allow_html=True)
    left, right = st.columns([3, 2])
    with left:
        win = st.segmented_control(
            "Window", list(WINDOWS), default="3 yr",
            key=f"win_{series}", label_visibility="collapsed")
    with right:
        # The share is OFFERED rather than forced, and the caption says when it
        # is the one to read. Open interest doubling is a fact about the market,
        # not about the funds, and a reader comparing 2008 with today on raw
        # contracts is comparing two different-sized markets.
        share = st.toggle("Show as a share of open interest",
                          key=f"share_{series}",
                          value=False,
                          help="Open interest has grown a long way since 2006, "
                               "so a contract count is not comparable across the "
                               "full history. The share is.")
    years = WINDOWS.get(win or "3 yr")
    frame = cot.series_frame(m["frame"], years)
    st.plotly_chart(net_figure(frame, color, as_share=share),
                    use_container_width=True, key=f"net_{series}")
    if years is None and not share:
        st.caption(
            "Reading the full history in contracts compares a bet made in a "
            f"market with {m['frame'].iloc[0]['open_interest']:,.0f} contracts "
            f"of open interest against one made in a market with "
            f"{L['open_interest']:,.0f}. The share toggle above removes that."
        )

    # -- the legs -------------------------------------------------------------
    st.markdown('<div class="sec-header">The net taken apart — gross long, '
                'gross short, and spreading</div>', unsafe_allow_html=True)
    st.plotly_chart(legs_figure(frame), use_container_width=True,
                    key=f"legs_{series}")
    st.caption(
        f"Spreading — {fmt(L['spread'])} contracts this week — is equal and "
        "offsetting long and short legs held by the same trader. CFTC counts it "
        "in its own column and it nets to zero by construction, so it is "
        "excluded from the net above rather than overlooked. It is worth "
        "watching anyway: when the funds' spreading is larger than their net, "
        "the directional bet is smaller than the gross figures suggest."
    )

    # -- who is on the other side --------------------------------------------
    st.markdown('<div class="sec-header">Who is on the other side of the '
                'funds, this week</div>', unsafe_allow_html=True)
    st.plotly_chart(categories_figure(m["categories"]), use_container_width=True,
                    key=f"cat_{series}")
    bal = m.get("balance")
    bal_note = ("Every long contract is somebody's short, so the five "
                "categories sum to zero")
    if bal is not None and abs(bal) > cot.OI_TOLERANCE:
        bal_note = (f"⚠️ The five categories sum to {bal:,.0f} rather than "
                    "zero, which should be impossible")
    st.caption(
        f"{bal_note}. Managed money is one of five groups CFTC splits the market "
        f"into; the report is called Disaggregated because the single "
        "'non-commercial' bucket of the older report mixed the funds in with "
        "other large speculators. "
        f"{L['long_traders'] or '—'} traders held the long side and "
        f"{L['short_traders'] or '—'} the short, out of "
        f"{L['traders_total'] or '—'} reportable traders in the market."
    )

    # -- the numbers ----------------------------------------------------------
    with st.expander(f"{label} — the last 12 weeks, and the full series to download"):
        g = m["frame"].tail(12).iloc[::-1]
        table = pd.DataFrame({
            "Week (Tuesday)": [_us(d.date()) for d in g["report_date"]],
            "Managed money net": g["mm_net"].map(lambda v: f"{abs(v):,.0f} {cot.side(v)}"),
            "Change on the week": (g["mm_long_chg"] - g["mm_short_chg"]).map(
                lambda v: "unchanged" if v == 0 else f"{'+' if v > 0 else '−'}{abs(v):,.0f}"),
            "Long": g["mm_long"].map("{:,.0f}".format),
            "Short": g["mm_short"].map("{:,.0f}".format),
            "Spreading": g["mm_spread"].map("{:,.0f}".format),
            "Open interest": g["open_interest"].map("{:,.0f}".format),
            "Net as % of OI": (100 * g["mm_net"] / g["open_interest"]).map("{:,.1f}%".format),
        })
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button(
            f"Download the full {label} series — {len(m['frame']):,} weeks, CSV",
            m["frame"].to_csv(index=False).encode("utf-8"),
            file_name=f"cftc_cot_{series.lower()}_managed_money.csv",
            mime="text/csv", key=f"dl_{series}")


# -- the tabs ----------------------------------------------------------------
#
# TABS RATHER THAN SEPARATE PAGES, AND THAT IS ALLOWED HERE. The rule further
# up CLAUDE.md is that a hidden Streamlit tab is hidden and not skipped, so its
# body runs on every rerun -- which makes a tab the wrong shape when the hidden
# body is expensive. Every tab below reads the SAME two cached queries that
# `load_cot()` already made, so the second and third cost rendering and no
# network at all. Nothing on this page fetches from inside a tab.

tab_live, tab_feeder, tab_compare = st.tabs(
    ["Live Cattle", "Feeder Cattle", "Across the markets"])

with tab_live:
    market_panel("LIVE_CATTLE")

with tab_feeder:
    market_panel("FEEDER_CATTLE")

with tab_compare:
    st.markdown('<div class="sec-header">Both cattle markets on one scale</div>',
                unsafe_allow_html=True)
    st.caption(
        "Plotted as a share of each market's own open interest, because Live "
        "Cattle runs about five times the open interest of Feeder Cattle and a "
        "contract count would simply redraw that size difference. The share "
        "asks the question worth asking: how heavily are the funds committed in "
        "each, relative to the market they are committed in."
    )
    fig = go.Figure()
    for s in cot.CATTLE:
        mm = markets.get(s)
        if not mm:
            continue
        fr = cot.series_frame(mm["frame"], 5)
        fig.add_trace(go.Scatter(
            x=fr["report_date"], y=fr["net_pct_oi"], mode="lines", name=mm["label"],
            line=dict(width=1.8, color=MARKET_COLOR[s]),
            hovertemplate=mm["label"] + " %{y:.1f}% of OI<extra></extra>"))
    fig.add_hline(y=0, line_width=1.2, line_color=DM_MUTED)
    fig.update_layout(
        height=340, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE, hovermode="x unified",
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11, color=DM_MUTED)),
        xaxis=dict(**AXIS), yaxis=dict(**AXIS, title="net as % of open interest"))
    st.plotly_chart(fig, use_container_width=True, key="compare_net")

    # -- the neighbours -------------------------------------------------------
    st.markdown('<div class="sec-header">The rest of the cattle feeder\'s '
                'board, same report, same week</div>', unsafe_allow_html=True)
    rows = []
    for s in cot.CATTLE + cot.NEIGHBOURS:
        mm = markets.get(s)
        if not mm:
            continue
        LL = mm["latest"]
        rows.append({
            "Market": mm["label"],
            "Managed money net": f"{abs(LL['net']):,.0f} {cot.side(LL['net'])}",
            "Change on the week": ("unchanged" if LL["wow"] == 0 else
                                   f"{'+' if LL['wow'] > 0 else '−'}{abs(LL['wow']):,.0f}"),
            "Gross long": f"{LL['long']:,.0f}",
            "Gross short": f"{LL['short']:,.0f}",
            "Open interest": f"{LL['open_interest']:,.0f}",
            "Net as % of OI": f"{LL['net_pct_oi']:,.1f}%",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "Lean hogs is the third livestock market; corn and soybean meal are the "
        "feeder's input cost, and a fund position in them moves a cattle feeding "
        "margin as surely as one in the cattle. They cost no extra request — "
        "the same query that fetches the cattle fetches these. Every figure is "
        "futures-only, as of the same Tuesday."
    )

    # -- why this page is futures-only ----------------------------------------
    #
    # The three-way table used to live here and has moved to the top of the
    # page, under the headline, where it can actually stop the phone call it
    # exists to stop. What is left here is the reasoning, which is reference
    # material rather than something a reader needs before the figures.
    st.markdown('<div class="sec-header">Why this page is futures-only</div>',
                unsafe_allow_html=True)
    st.markdown(
        "The figures at the top of this page are **futures only**, and that is "
        "load-bearing rather than a preference.\n\n"
        "- It is what the user of a \"net futures position\" is asking for, and "
        "it is the basis **JSA's own Friday letter** quotes — so the two agree "
        "to the contract rather than nearly.\n"
        "- It is the only one of the two bases that reconciles **exactly**. "
        "Every identity in the futures-only report holds with zero residual on "
        "all 2,120 cattle rows since 2006: each category's longs plus the "
        "spread columns equal open interest, the five nets sum to zero, and "
        "CFTC's published weekly change equals the change in its own levels.\n"
        "- On the combined basis none of that is quite true, because CFTC "
        "converts options to futures equivalents on a **delta** basis and then "
        "rounds each category separately. The residuals are small — one "
        "contract on a change column, two or three on a sum — but they mean "
        "combined figures must be read as published levels and never used as "
        "the basis for arithmetic that has to close.\n\n"
        "The combined figure is shown at the top anyway, because a reader who "
        "meets it on a wire or a broker's screen needs to know why it differs "
        "— not as an alternative headline."
    )

st.write("")
st.caption(
    f"Source: CFTC Commitments of Traders, Disaggregated report, futures only, "
    f"read from `{cot.VIEW}` — loaded weekly by `JSA-Dashboards/cftc-cot-etl`, "
    "which re-pulls the last eight weeks each run so CFTC's own revisions land. "
    "Positions are as of Tuesday's close and are published the following "
    "Friday. Managed money is CFTC's category for commodity trading advisors, "
    "commodity pool operators and unregistered funds trading for clients — the "
    "speculative money, as distinct from the producers and processors hedging "
    "physical cattle."
)
