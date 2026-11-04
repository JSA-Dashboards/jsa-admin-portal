"""
Backgrounding Crush -- buy calves, put weight on them, sell feeders.

Same shape as the Fed Cattle Crush, different trade. There the question is
"what can I bid for feeders against the fed cattle board". Here it is "what can
I bid for CALVES against the feeder board", and the answer turns on one number
the fed version does not have:

    VALUE OF GAIN = (revenue - calf cost) / gain

What each hundredweight you put on is actually worth when you sell. Beat it
with your cost of gain and you make money; that is the entire trade. Profit per
head follows from it, but value of gain is the number a backgrounder decides
on, because it is directly comparable to a forage or grower-ration cost.

DEATH LOSS IS ITS OWN SLIDER AND THE COST OF GAIN BOX EXCLUDES IT. The two are
a pair: the $101.35 default is Iowa State's all-in $110 with the death loss
taken back out, so the slider can charge it without counting it twice. Charged on an
all-in figure it would be, and nothing on the page could report that -- a
plausible cost over a plausible calf is a plausible margin either way.

Only death loss came out of the cost of gain; interest, trucking, commission
and any charge for risk stay in it. The reason is that death loss is the one
line that scales with the CALF rather than with the ration -- a percentage of
the purchase price, so the same 1% cost about $3.44/cwt of gain at $180 calves
and $8.65 at $453. That is how a cost of gain carried over from a cheaper year
ends up understated, and the slider is what saves doing the correction by hand.

The charge reaches total cost, profit, the break-even bid and the all-in cost
of gain the value-of-gain comparison uses, so profit per head stays exactly
(value of gain - all-in cost of gain) x gain. The break-even is NOT a
subtraction: death loss is charged on what you pay, so it rises with the bid
and has to be solved for rather than taken off the top.

WHY THE TWO LEGS COME FROM DIFFERENT PLACES.

  BUY  calves, 400-650 lb. There is no futures contract for a 500 lb calf --
       CME's feeder index starts at 700 lb -- so the buy side can only come
       from cash auction data. That is calf_sales, ingested from the same AMS
       barn reports behind the index, over the weight brackets the index
       discards.

  SELL feeders, 700-899 lb, months out. That IS the CME Feeder Cattle contract,
       so the sell leg prices off GF at the sale date plus a feeder basis --
       forward-looking and hedgeable, exactly as the fed cattle version prices
       its sale off Live Cattle.

Pricing the sale off today's cash feeder market instead would answer a question
nobody asked: a backgrounder selling in February cares what February feeders
are worth, not what they fetched this week.

THE CALF PRICE DEFAULT comes from the bracket that matches the entered start
weight, so changing start weight re-prices the calf. It is a starting point:
cash calf markets vary enormously by quality, fill, lot size and barn, and the
number to trust is the one the buyer knows for their own cattle.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

import bgc_cash_calves as cash_calves
from bgc_massive_api import MassiveApiError, get_futures_curve

JPSI_DARK = "#32373c"
JPSI_BLUE = "#0693e3"
BG        = "#f6f8f7"
CARD_BG   = "#ffffff"
SURFACE2  = "#eef3f0"
BORDER    = "#d7e2dc"
MUTED     = "#5f7267"
TEXT      = "#32373c"
POS       = "#16a34a"
NEG       = "#dc2626"
AMBER     = "#d97706"

MONTH_LETTERS = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
                 "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
MONTH_NAME = dict(zip(range(1, 13),
                      ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]))

# Backgrounding, not finishing: forage or a grower ration, lower daily gain,
# shorter than a feedyard. Starting points, all editable.
#
# COST OF GAIN IS NOT CHEAPER THAN FINISHING, which this page asserted at $95
# until it was checked. Iowa State's Livestock Enterprise Budgets for Iowa-2026
# (FM 1815 / B1-21) put all six of their beef systems within $4.43/cwt of each
# other -- backgrounding winter drylot $111.37, backgrounding summer pasture
# $109.40, and the four finishing systems $106.94 to $110.52. $95 sat below
# every one of them.
#
# The reason backgrounding is not cheaper is arithmetic, not agronomy: every
# per-head and per-day cost is spread over half as many pounds. At 2.0 ADG a
# $0.50/hd/day yardage is $25.00/cwt of gain against $15.38 at 3.25, and feed
# conversion does not rescue it -- a medium-frame steer runs 6.6:1 DM at 500 lb
# and 8.4:1 at 700 lb (UNL G2064), WORSE than a finishing closeout's 6.0-6.5:1.
#
# Backgrounding gain is cheap when it is cheap because the feed costs $114-134
# a ton of dry matter instead of $217 -- not because of conversion, and not
# because of corn.
#
# The one honest exception is worth knowing: strip out interest on the purchased
# calf and summer pasture backgrounding IS the cheapest gain in the book at
# $75.40/cwt. At today's calf values that interest line is enormous, so whether
# backgrounding looks cheap depends almost entirely on whether you charge it --
# which is exactly why the build-up shows it as its own line.
#
# THAT $109-111 IS ALL-IN AND INCLUDES DEATH LOSS, WHICH IS WHY THE DEFAULT
# BELOW IS $101.35 AND NOT $110. Death loss has its own slider and charges
# separately, so the box it is charged on top of must be ISU's figure with the
# death loss taken back out. Three versions shipped on 2026-10-16 before that
# pairing was right, and the history is worth one paragraph because each one
# rendered perfectly:
#
#   1. A cost line on top of $110 -- double counted, moved every figure on the
#      page, nothing raised.
#   2. No charge at all, an input that merely split the $110 -- arithmetically
#      harmless and still wrong, because a control that changes no figure on
#      the page misleads about what it does.
#   3. No input, a worked note at a fixed 1% -- correct, but it left the user
#      adjusting the cost of gain by hand for a high-risk set, which is the
#      arithmetic a calculator should be doing.
#
# The lesson that outlived all three: THE DEFAULT AND THE CHARGE ARE A PAIR.
# Changing whether death loss is charged without moving DEFAULTS["cog"] in the
# same edit is the double count, and no label or help text catches it.
#
# THE $101.35 IS ISU'S $110 WITH THE DEATH LOSS TAKEN OUT, AND THAT
# SUBTRACTION IS THE WHOLE REASON THE SLIDER IS SAFE. Their $109-111 is all-in
# and carries death loss; the slider charges death loss itself, so leaving the
# default at $110 would charge it twice -- the defect that shipped on
# 2026-10-16 and the one nothing on the page can report, because a plausible
# cost over a plausible calf gives a plausible margin whichever way it was
# built.
#
# The figure is chosen so the page OPENS ON $110.00/cwt ALL-IN -- Ross's call,
# 2026-10-16, having seen the alternative. At the 1% default and a $453 calf
# death loss is $8.65/cwt of gain, so $110.00 - $8.65 = $101.35.
#
# IT IS EXACT TODAY AND DRIFTS WITH THE CALF, WHICH IS CORRECT RATHER THAN A
# DEFECT. Death loss is a percentage of the purchase price, so dearer calves
# genuinely cost more to lose: at a $500 calf the same 1% is $9.55 and the
# page opens at $110.90 all-in. Pinning the all-in total at $110 forever would
# mean quietly shrinking the feed-and-yardage figure every time calves rallied,
# which is the opposite of true. ISU's own $110 was computed at some calf
# value too.
DEFAULTS = {
    "start_wt": 525.0,
    "sell_wt": 800.0,
    "adg": 2.00,       # grower/forage, against ~3.25 in a feedyard
    "cog": 101.35,     # $/cwt of gain, EXCLUDING death loss -- see above
    "death": 1,        # %, charged by the slider on top of the line above
    "basis": -2.00,    # feeder cash typically under the board
}

# The slider's range. 10% is a ceiling rather than a plausible figure -- good
# cattle run about 1%, high-risk sale-barn calves 3-5%, and a wreck is what the
# top of the range is for. Whole points because that is the granularity anyone
# actually budgets at.
DEATH_PCT_MIN, DEATH_PCT_MAX = 0, 10

st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{ background-color:{BG}; color:{TEXT}; }}
  [data-testid="stSidebar"] {{ background-color:{SURFACE2}; border-right:1px solid {BORDER}; }}
  .tile {{
    background:{CARD_BG}; border:1px solid {BORDER}; border-top:3px solid {JPSI_BLUE};
    border-radius:10px; padding:16px 20px; text-align:center; height:100%;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .tile-pos {{ border-top-color:{POS}; }}
  .tile-neg {{ border-top-color:{NEG}; }}
  .tile-label {{
    color:{MUTED}; font-size:0.68rem; text-transform:uppercase;
    letter-spacing:0.09em; margin-bottom:6px;
  }}
  .tile-value {{ color:{TEXT}; font-size:1.7rem; font-weight:700; line-height:1.1; }}
  .tile-value-pos {{ color:{POS}; }}
  .tile-value-neg {{ color:{NEG}; }}
  .tile-sub {{ color:{MUTED}; font-size:0.72rem; margin-top:5px; }}
  .sec-header {{
    color:{MUTED}; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.1em;
    padding:8px 0 4px; border-bottom:1px solid {BORDER}; margin-bottom:10px;
  }}
  .fld-label {{
    text-align:right; color:{TEXT}; font-size:0.86rem; font-weight:600;
    padding-top:0.55rem; line-height:1.2;
  }}
  .fld-row {{
    display:flex; align-items:baseline; gap:12px; padding:5px 0;
    border-top:1px solid {BORDER};
  }}
  .fld-row .fld-label {{ flex:0 0 46%; padding-top:0; }}
  .fld-derived {{ color:{TEXT}; font-size:1.0rem; font-weight:700; }}
  .fld-note {{
    display:block; color:{MUTED}; font-size:0.68rem; font-weight:400; margin-top:1px;
  }}
  .be-line {{ color:{MUTED}; font-size:0.82rem; margin:0 0 4px 2px; }}
  .be-line b {{ color:{TEXT}; font-size:0.95rem; }}
  .profit-box {{ border-radius:12px; padding:14px 18px; margin-top:10px; text-align:center; }}
  .profit-pos {{ background:{POS}; }}
  .profit-neg {{ background:{NEG}; }}
  .profit-label {{
    color:rgba(255,255,255,0.92); font-size:0.72rem; font-weight:700;
    text-transform:uppercase; letter-spacing:0.12em;
  }}
  .profit-value {{ color:#ffffff; font-size:2.1rem; font-weight:800; line-height:1.15; }}
  .profit-unit {{ font-size:1.0rem; font-weight:600; opacity:0.9; }}
  .vog {{
    border-radius:10px; padding:12px 16px; margin-top:10px;
    border:1px solid {BORDER}; background:{CARD_BG};
  }}
  .vog-lab {{ color:{MUTED}; font-size:0.68rem; text-transform:uppercase;
              letter-spacing:0.09em; }}
  .vog-val {{ font-size:1.5rem; font-weight:800; }}
  .srcline {{ color:{MUTED}; font-size:0.72rem; line-height:1.6; }}
  hr {{ border-color:{BORDER}; }}
  #MainMenu, footer {{ visibility:hidden; }}
  .stDeployButton {{ display:none; }}
</style>
""", unsafe_allow_html=True)


def tile(label, value, sub_="", kind=""):
    vc = {"pos": " tile-value-pos", "neg": " tile-value-neg"}.get(kind, "")
    tc = {"pos": " tile-pos", "neg": " tile-neg"}.get(kind, "")
    s = f'<div class="tile-sub">{sub_}</div>' if sub_ else ""
    return (f'<div class="tile{tc}"><div class="tile-label">{label}</div>'
            f'<div class="tile-value{vc}">{value}</div>{s}</div>')


def get_api_key() -> str:
    import os
    try:
        k = st.secrets.get("MASSIVE_API_KEY", "")
    except Exception:
        k = ""
    return k or os.environ.get("MASSIVE_API_KEY", "")


def contract_month(ticker, code):
    suffix = ticker[len(code):]
    if len(suffix) < 2 or suffix[0] not in MONTH_LETTERS:
        return None
    m = MONTH_LETTERS[suffix[0]]
    try:
        d = int(suffix[1:])
    except ValueError:
        return None
    base = date.today().year
    y = (base // 10) * 10 + d if d < 10 else 2000 + d
    while y < base - 1:
        y += 10
    return y, m


def label_contract(ticker, code):
    cm = contract_month(ticker, code)
    return f"{ticker} ({MONTH_NAME[cm[1]]} {cm[0]})" if cm else ticker


def pick_contract(curve, target):
    """First contract expiring ON OR AFTER the date -- you cannot sell into an
    expired contract, so nearest-by-distance is the wrong rule."""
    if curve is None or curve.empty:
        return None
    fwd = curve[pd.to_datetime(curve["expiration"]).dt.date >= target]
    row = fwd.iloc[0] if not fwd.empty else curve.iloc[-1]
    return {"ticker": row["ticker"], "price": float(row["price"]),
            "beyond_curve": fwd.empty}


@st.cache_data(ttl=900, show_spinner=False)
def load_gf(as_of: str):
    key = get_api_key()
    if not key:
        return None, "no MASSIVE_API_KEY"
    try:
        c = get_futures_curve("GF", key, date.fromisoformat(as_of), n_contracts=12)
        if c is None or c.empty:
            c = get_futures_curve("GF", key,
                                  date.fromisoformat(as_of) - timedelta(days=1),
                                  n_contracts=12)
        return c, None
    except MassiveApiError as e:
        return None, f"Massive API error: {e}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


ALL_STATES = "All states"
CASH_BRACKETS = [400, 450, 500, 550, 600, 650, 700, 750, 800, 850, 900]


@st.cache_data(ttl=3600, show_spinner=False)
def load_calf_prices():
    """
    {weight_low: $/cwt} head-weighted, trailing 21 days, from calf_sales.

    Returns empty rather than raising if the table is absent -- a missing cash
    feed should leave the user typing their own calf price, not staring at a
    broken page.
    """
    try:
        import bgc_snowflake_db as _db
        conn = _db.get_conn()
    except Exception:
        return {}, None
    try:
        since = ("DATEADD(day, -21, CURRENT_DATE())" if _db.use_snowflake()
                 else "date('now','-21 day')")
        rows = conn.cursor().execute(
            "SELECT weight_low, "
            "       SUM(head_count*avg_price)/NULLIF(SUM(head_count),0), "
            "       MAX(report_date) "
            f"FROM calf_sales WHERE report_date >= {since} "
            "GROUP BY weight_low").fetchall()
        out = {int(w): float(p) for w, p, _d in rows if p}
        asof = max((str(_db.iso(d)) for _w, _p, d in rows if d), default=None)
        return out, asof
    except Exception:
        return {}, None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _fmt_date(iso: str) -> str:
    """ISO to 'Sep 14' -- %-d is glibc-only and raises on Windows."""
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%b %d")
    except Exception:
        return str(iso)


def bracket_for(wt: float) -> int:
    """The 50 lb bracket a weight falls in, floored to AMS's grid."""
    return int(wt // 50 * 50)


def death_cost_per_head(calf_cost: float, death_pct: float) -> float:
    """
    $/head of death loss, valued at WHAT YOU PAID for the calf.

    THIS IS A REAL CHARGE on this page, added to the cost of gain rather than
    carried inside it -- which is only safe because DEFAULTS["cog"] is ISU's
    all-in figure with its death loss already subtracted out. Read the comment
    above DEFAULTS before changing either one; they are a pair, and separating
    them double counts with nothing raising.

    The loss is valued at the PURCHASE price, not the sale price, which is the
    convention the Fed Cattle Crush's build-up uses (`death_c` there is feeder
    value x death %, spread over the gain) and the one this page's explainer
    has always quoted: a $2,165 calf, 1% to 5%, is $86.60 over 275 lb of gain
    = $31.50/cwt. It understates slightly -- a calf that dies has eaten
    something first -- and valuing it at the sale price would overstate, by
    charging the dead calf for gain it never put on. Purchase value is the
    conservative middle and it keeps the two crush pages agreeing.

    It is taken off the BID rather than off the futures-implied value. The fed
    page uses futures there to break a circularity -- its death loss feeds cost
    of gain, which feeds the break-even, which feeds the bid. That circularity
    does not arise here because `calf_breakeven` solves for the bid in closed
    form instead.
    """
    return calf_cost * death_pct / 100.0


def calf_breakeven(revenue: float, cog_cost: float, start_wt: float,
                   death_pct: float) -> float:
    """
    The most you can pay for the calves, $/cwt, and still come out level.

    DEATH LOSS SCALES WITH THE BID, so it cannot be subtracted the way cost of
    gain is -- raising the bid raises the death loss charge with it. Setting
    profit to zero and solving:

        revenue = (in/100)B + cog_cost + (in/100)B x d
                => B = (revenue - cog_cost) / ((in/100) x (1 + d))

    Dropping the (1 + d) is the silent failure: it returns a bid about a point
    too high, the page prints it as a break-even, and a pen bought at it loses
    the whole death loss line. Pinned by feeding the answer back through the
    crush and asserting the profit is zero.
    """
    if start_wt <= 0:
        return 0.0
    return (revenue - cog_cost) / ((start_wt / 100.0) * (1.0 + death_pct / 100.0))


# ── Header ──────────────────────────────────────────────────────────────────
c_t, c_d = st.columns([6, 2])
with c_t:
    st.markdown("## JSA — Backgrounding Crush")
    st.caption("Buy calves, sell feeders · cash feeder market against the CME Feeder board")

gf, err = load_gf(date.today().isoformat())
calf_px, calf_asof = load_calf_prices()

with c_d:
    st.markdown(
        f"<div style='text-align:right;color:{MUTED};font-size:0.75rem;padding-top:6px;'>"
        f"Futures as of<br><span style='color:{JPSI_BLUE};font-size:1rem;font-weight:700;'>"
        f"{date.today().strftime('%b %d, %Y')}</span></div>", unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)

if err or gf is None or gf.empty:
    st.error("Could not load the Feeder Cattle futures curve.")
    st.caption(f"Reads CME Feeder Cattle (GF) from the Massive futures API. "
               + (f"Detail: `{err}`" if err else ""))
    st.stop()

# Two tabs. The crush is a calculator; the cash lookup is a reference for what
# cattle are actually bringing, and they are read at different moments -- one
# when you are pricing a pen, the other when you are deciding what to go look
# at. Same pattern as the Fed Cattle Crush's build-up tab: a hidden tab still
# executes, so nothing here is conditional on which one is showing.
tab_crush, tab_cash = st.tabs(["Crush", "Cash Feeder Prices"])

with tab_crush:
    in_col, out_col = st.columns([1.05, 1])

    with in_col:
        st.markdown('<div class="sec-header">Your Cattle</div>', unsafe_allow_html=True)

        def field(label, fn):
            lc, fc = st.columns([0.92, 1.08])
            with lc:
                st.markdown(f'<div class="fld-label">{label}</div>', unsafe_allow_html=True)
            with fc:
                return fn()

        start_wt = field("Calf in-weight", lambda: st.number_input(
            "start_wt", 300.0, 750.0, DEFAULTS["start_wt"], 25.0,
            label_visibility="collapsed"))
        sell_wt = field("Sell weight", lambda: st.number_input(
            "sell_wt", 500.0, 1000.0, DEFAULTS["sell_wt"], 25.0,
            label_visibility="collapsed"))
        adg = field("Rate of gain", lambda: st.number_input(
            "adg", 0.25, 5.0, DEFAULTS["adg"], 0.05, label_visibility="collapsed",
            help="lb/head/day. Backgrounding on forage or a grower ration runs well "
                 "below a feedyard's 3.0-3.5."))
        cog = field("Cost of gain", lambda: st.number_input(
            "cog", 0.0, 300.0, DEFAULTS["cog"], 1.0, label_visibility="collapsed",
            help="$/cwt of gain, ALL-IN -- feed, yardage, health, interest on "
                 "the calf and interest on it — but NOT DEATH LOSS, which the "
                 "slider below charges separately. Iowa State's 2026 budgets "
                 "put backgrounding at $109-111/cwt ALL-IN, about the same as "
                 "finishing because every per-day cost is spread over half as "
                 "many pounds; the $101.35 default is that figure with its death "
                 "loss taken out, so the slider can put it back without "
                 "counting it twice."))
        death = field("Death loss", lambda: st.slider(
            "death", DEATH_PCT_MIN, DEATH_PCT_MAX, DEFAULTS["death"], 1,
            format="%d%%", label_visibility="collapsed",
            help="% of the calves placed, charged at what you paid for them. "
                 "This is what the cost of gain above leaves out, so raising it "
                 "raises your all-in cost and lowers what you can bid — no need "
                 "to adjust the cost of gain by hand. 1% is fair on cattle you "
                 "know; high-risk sale-barn calves run 3-5%."))
        # THE RESULT SITS DIRECTLY UNDER THE SLIDER, which is the point of the
        # placeholder: the dollar figure cannot be computed yet because it
        # scales with the calf, and the bid is a widget in the other column
        # that Streamlit has not reached. `st.empty()` books the position now
        # and `.markdown()` fills it after the bid is known. Without it the
        # figure lands below the sell date and cash calf rows, four rows away
        # from the control that drives it.
        death_slot = st.empty()
        # NO PLANT SHRINK LINE HERE, deliberately -- asked and answered 2026-09-14.
        #
        # The Fed Cattle Crush has one, because a packer buying fat cattle live pays
        # against a shrunk scale ticket and the full finish weight overstates
        # revenue. The sell side of THIS page is different: it prices against CME
        # Feeder Cattle futures, and that index is already quoted "FOB, 3% standing
        # shrink" -- the shrink is inside the price being used as the reference.
        # Applying it again to the weight would count it twice and understate the
        # calf bid, which is the number this page exists to produce.
        #
        # A backgrounder selling into a cash market on different terms should put
        # the difference in the basis below, where it belongs.
        basis = field("Feeder basis", lambda: st.number_input(
            "basis", -40.0, 40.0, DEFAULTS["basis"], 0.25,
            label_visibility="collapsed",
            help="$/cwt, cash minus futures at sale. Usually negative."))
        start_date = field("Start date", lambda: st.date_input(
            "start_date", date.today(), label_visibility="collapsed"))

    gain = sell_wt - start_wt
    warn = None
    if gain <= 0:
        warn = "Sell weight must be greater than the calf in-weight."
        days = 0
    elif adg <= 0:
        warn = "Rate of gain must be positive."
        days = 0
    else:
        days = int(round(gain / adg))
    finish_date = start_date + timedelta(days=days)

    if warn:
        with in_col:
            st.warning(warn)
        st.stop()

    auto = pick_contract(gf, finish_date)
    with st.expander("Override the contract", expanded=False):
        tickers = list(gf["ticker"])
        pick = st.selectbox("Feeder Cattle (sell)", tickers,
                            index=tickers.index(auto["ticker"]) if auto else 0,
                            format_func=lambda t: label_contract(t, "GF"))
        st.caption(
            "Feeder Cattle trades Jan, Mar, Apr, May, Aug, Sep, Oct and Nov. The "
            "page takes the first contract expiring **on or after** your sale date."
        )
    gf_price = float(gf[gf["ticker"] == pick]["price"].iloc[0])

    if auto and auto.get("beyond_curve"):
        st.warning(f"Your sale date is past the last listed contract "
                   f"({label_contract(auto['ticker'], 'GF')}), so that one is used.")

    # Calf price default tracks the START WEIGHT's bracket, so moving the in-weight
    # re-prices the calf -- the slide from 400 to 650 lb is steep and a fixed
    # default would be wrong the moment the weight changed.
    brk = bracket_for(start_wt)
    calf_seed = calf_px.get(brk)

    sale_price = gf_price + basis
    revenue = sell_wt / 100.0 * sale_price
    cog_cost = gain / 100.0 * cog
    calf_be = calf_breakeven(revenue, cog_cost, start_wt, death)

    with in_col:
        st.markdown(
            f'<div class="fld-row"><span class="fld-label">Sell date</span>'
            f'<span class="fld-derived">{finish_date.strftime("%b %d, %Y")}'
            f'<span class="fld-note">{days} days · {gain:,.0f} lb gain</span>'
            f'</span></div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="fld-row"><span class="fld-label">Feeder at sale</span>'
            f'<span class="fld-derived">${gf_price:,.3f}'
            f'<span class="fld-note">{label_contract(pick, "GF")} '
            f'{basis:+.2f} basis = ${sale_price:,.2f}</span></span></div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="fld-row"><span class="fld-label">Cash calf, {brk}-{brk+49} lb</span>'
            f'<span class="fld-derived">'
            f'{"$%.2f" % calf_seed if calf_seed else "—"}'
            f'<span class="fld-note">'
            f'{"AMS barns, 21-day avg through " + str(calf_asof) if calf_seed else "no cash data yet"}'
            f'</span></span></div>', unsafe_allow_html=True)

    with out_col:
        st.markdown('<div class="sec-header">Bid Price — Calves</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="be-line">Calf break even <b>${calf_be:,.2f}</b> /cwt'
                    f'</div>', unsafe_allow_html=True)
        bid = st.number_input("Bid ($/cwt)", 0.0, 1000.0,
                              float(round(calf_seed if calf_seed else calf_be, 2)), 0.25,
                              label_visibility="collapsed",
                              help="What you would pay for the calves, $/cwt. "
                                   "Seeded from the cash market where available.")

    calf_cost = start_wt / 100.0 * bid
    death_cost = death_cost_per_head(calf_cost, death)
    total_cost = calf_cost + cog_cost + death_cost
    profit = revenue - total_cost
    # The number a backgrounder actually decides on: what each cwt of gain is worth
    # once the calves are bought. Beat it with cost of gain and the trade works.
    vog = (revenue - calf_cost) / (gain / 100.0) if gain else 0.0
    breakeven = total_cost / (sell_wt / 100.0) if sell_wt else 0.0

    # DEATH LOSS IS CHARGED BY THE SLIDER, ON TOP OF A COST OF GAIN THAT
    # EXCLUDES IT. The pairing with DEFAULTS["cog"] = 101.35 is what makes that
    # safe -- see the comment above DEFAULTS. Charged on $110 it would be
    # counted twice, which is the version that shipped on 2026-10-16.
    #
    # `cost_c` is the all-in cost of gain and is what the value-of-gain box,
    # the Value of Gain tile and the caption all read. That is forced by the
    # identity
    #
    #     profit == (vog - cost_c) x gain/100      exactly
    #
    # Put death loss into total_cost alone and it breaks: the caption goes on
    # reporting "$X a head on 275 lb" off the margin on gain while the Profit
    # tile six inches above reports a figure one death loss line different.
    # Both honestly computed, neither raising -- the letter-versus-dashboard
    # failure this repo has paid for three times.
    death_c = death_cost / (gain / 100.0) if gain else 0.0
    cost_c = cog + death_c
    death_share = (death_c / cost_c * 100.0) if cost_c else 0.0

    # THE RESULT OF THE SLIDER, rendered into the slot booked directly beneath
    # it. The arithmetic is spelled out rather than just its answer because
    # "$8.65" alone does not say what it is a percentage OF -- the headline
    # rule. It names the all-in total explicitly so nobody has to add the two
    # cost-of-gain figures in their head.
    death_slot.markdown(
        f'<div class="fld-row">'
        f'<span class="fld-label">Death loss adds</span>'
        f'<span class="fld-derived">${death_c:,.2f}<span class="fld-note">'
        f'{death:,.0f}% &times; ${calf_cost:,.2f} calf = ${death_cost:,.2f}/head, '
        f'over {gain / 100:,.2f} cwt of gain &nbsp;·&nbsp; '
        f'${cog:,.2f} + ${death_c:,.2f} = <b>${cost_c:,.2f}/cwt all-in</b>'
        f'</span></span></div>', unsafe_allow_html=True)

    with out_col:
        pk = "pos" if profit >= 0 else "neg"
        st.markdown(
            f'<div class="profit-box profit-{pk}">'
            f'<div class="profit-label">Profit</div>'
            f'<div class="profit-value">{"+" if profit >= 0 else "-"}'
            f'${abs(profit):,.2f}<span class="profit-unit">/head</span></div></div>',
            unsafe_allow_html=True)
        vk = POS if vog >= cost_c else NEG
        st.markdown(
            f'<div class="vog"><span class="vog-lab">Value of gain</span><br>'
            f'<span class="vog-val" style="color:{vk}">${vog:,.2f}</span>'
            f'<span style="color:{MUTED};font-size:0.8rem"> /cwt vs '
            f'<b>${cost_c:,.2f}</b> to put it on '
            f'(${cog:,.2f} gain + ${death_c:,.2f} death loss) &nbsp;→&nbsp; '
            f'<b style="color:{vk}">${vog - cost_c:+,.2f}</b> margin on gain</span></div>',
            unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">The Crush</div>', unsafe_allow_html=True)

    # NINE TILES, SO THREE ROWS OF THREE. Death loss is a real cost line now,
    # so it gets a tile -- and at four across a ninth strands one on a row of
    # its own, the arithmetic the home grid already had to solve at thirteen.
    # Nothing was dropped to make room: the rows regroup as the cost build-up,
    # the totals, then the per-unit reads.
    #
    # A tile naming a cost beside other costs gets added on by a reader. Here
    # that is CORRECT -- Calf Cost + Cost of Gain + Death Loss is exactly Total
    # Cost. It was not correct in the version where death loss sat inside the
    # cost of gain, which is why there was no tile then.
    k = "pos" if profit >= 0 else "neg"
    m = st.columns(3)
    with m[0]:
        st.markdown(tile("Calf Cost", f"${calf_cost:,.2f}",
                         f"{start_wt:,.0f} lb @ ${bid:,.2f}"), unsafe_allow_html=True)
    with m[1]:
        st.markdown(tile("Cost of Gain", f"${cog_cost:,.2f}",
                         f"{gain:,.0f} lb @ ${cog:,.2f}/cwt, before death loss"),
                    unsafe_allow_html=True)
    with m[2]:
        st.markdown(tile("Death Loss", f"${death_cost:,.2f}",
                         f"{death:,.0f}% of the calf cost · "
                         f"${death_c:,.2f}/cwt of gain"), unsafe_allow_html=True)

    n = st.columns(3)
    with n[0]:
        st.markdown(tile("Total Cost", f"${total_cost:,.2f}",
                         f"breakeven ${breakeven:,.2f}/cwt"), unsafe_allow_html=True)
    with n[1]:
        st.markdown(tile("Revenue", f"${revenue:,.2f}",
                         f"{sell_wt:,.0f} lb @ ${sale_price:,.2f}"), unsafe_allow_html=True)
    with n[2]:
        st.markdown(tile("Profit / Loss", f"${profit:,.2f}",
                         f"per head, {days} days", k), unsafe_allow_html=True)

    p = st.columns(3)
    with p[0]:
        st.markdown(tile("Sale Price", f"${sale_price:,.2f}",
                         f"{pick} ${gf_price:,.2f} {basis:+.2f}"), unsafe_allow_html=True)
    with p[1]:
        st.markdown(tile("Value of Gain", f"${vog:,.2f}",
                         f"per cwt vs ${cost_c:,.2f} to put it on",
                         "pos" if vog >= cost_c else "neg"), unsafe_allow_html=True)
    with p[2]:
        per_day = profit / days if days else 0.0
        st.markdown(tile("Per Head Per Day", f"${per_day:,.2f}",
                         f"over {days} days", k), unsafe_allow_html=True)

    # Every `$` escaped as `\\$`: two unescaped ones in a markdown block open an
    # inline LaTeX span, the dollar signs vanish and the `**` between them come
    # out as literal asterisks. This block has six.
    st.caption(
        f"**Value of gain \\${vog:,.2f}/cwt against a \\${cost_c:,.2f} all-in cost** "
        f"is the backgrounding decision in one line — you are buying gain at "
        f"\\${cog:,.2f} plus \\${death_c:,.2f}/cwt of death loss, and selling it at "
        f"\\${vog:,.2f}. "
        + (f"That is **\\${vog - cost_c:,.2f}/cwt to the good**, "
           f"\\${(vog - cost_c) * gain / 100:,.2f} a head on {gain:,.0f} lb."
           if vog >= cost_c else
           f"That is **\\${cost_c - vog:,.2f}/cwt underwater** — the gain costs more "
           f"than it is worth at this bid.")
        + f" Death loss at {death:,.0f}% is {death_share:,.0f}% of that all-in "
          f"cost, and it moves with the calf rather than with your ration."
    )

    with st.expander("How this is calculated"):
        st.markdown(f"""
    ```
    calf cost/hd  = in-weight/100 x bid
    cost of gain  = (sell - in)/100 x cost of gain      (before death loss)
    death loss/hd = calf cost x death loss %
    sale price    = feeder futures ({pick}) + basis
    revenue/hd    = sell weight/100 x sale price
    value of gain = (revenue - calf cost) / (gain/100)
    all-in cost   = cost of gain + death loss/hd / (gain/100)
    profit/hd     = revenue - calf cost - cost of gain - death loss

    and the break-even bid, which cannot just subtract death loss because
    death loss rises with the bid:

    calf break even = (revenue - cost of gain) / ((in-weight/100) x (1 + d))
    ```

    **The buy and sell legs come from different places, necessarily.** There is no
    futures contract for a 500 lb calf — CME's feeder index starts at 700 lb — so
    the calf price can only come from cash auction data. That is `calf_sales`,
    pulled from the same AMS barn reports behind the feeder cattle index, over the
    weight brackets the index discards. The sale leg *is* a listed contract, so it
    prices off **{label_contract(pick, 'GF')}** plus your basis.

    **The calf default follows your in-weight.** The cash slide from 400 to 650 lb
    is steep — roughly \\$475/cwt down to \\$350 — so a fixed default would be wrong
    the moment you changed the weight. It re-prices to the matching 50 lb bracket.

    **Value of gain is the number to watch**, not profit per head. It is directly
    comparable to what your forage or grower ration costs, and it is what tells you
    whether to buy lighter or heavier cattle. Profit per head follows from it but
    mixes in how many pounds you put on.

    **THE COST OF GAIN BOX EXCLUDES DEATH LOSS — the slider charges it.** That
    pairing is the one thing to get right here. Iowa State's \\$109-111/cwt is an
    ALL-IN figure with death loss already inside it, so the \\${DEFAULTS["cog"]:,.0f}
    default is their number with it taken back out. Type an all-in figure in that
    box and the slider charges death loss a second time, and nothing on the page
    will tell you — a plausible cost over a plausible calf gives a plausible margin
    either way.

    Interest, trucking, commission and any charge for risk all stay in that box.
    Only death loss came out, because only death loss scales with the calf.

    **Move the slider and everything follows** — all-in cost of gain, total cost,
    profit, and the most you can bid. At {death:,.0f}% on these cattle death loss is
    \\${death_cost:,.2f} a head, \\${death_c:,.2f}/cwt of gain, taking your cost of
    gain from \\${cog:,.2f} to \\${cost_c:,.2f} all-in and your break-even bid to
    \\${calf_be:,.2f}/cwt.

    **The break-even is not a subtraction**, which is why it moves more than you
    might expect. Death loss is charged on what you pay, so raising the bid raises
    the death loss with it; the page solves `(revenue - cost of gain) / ((in-weight
    /100) x (1 + d))` rather than taking the charge off the top.

    **It is valued at what you PAID for the calf**, not at what it would have sold
    for. A calf that dies has eaten something first, so this understates a little;
    valuing it at the sale price would overstate, by charging the dead calf for gain
    it never put on. Purchase value is the conservative middle, and the Fed Cattle
    Crush charges its own death loss the same way.

    **The lever is large, and it is a CALF lever.** On a \\$2,165 calf, going from 1%
    to 5% is \\$31.50/cwt of gain; a full \\$1.00/bu move in corn is about \\$9. The
    same 1% cost about \\$3.44/cwt of gain when calves were \\$180 and is
    \\${death_c:,.2f} now — so a cost of gain carried over from a cheaper year is
    understated for that reason alone, which is exactly what the slider exists to
    stop you having to do in your head.
    """)


# ── Cash Feeder Prices ──────────────────────────────────────────────
# The same lookup appears on the CME Feeder Cattle Index page, so it lives in
# cash_calves.py rather than here. Different question, same data: a
# backgrounder asks what a calf is worth before bidding, an index reader asks
# what the cattle behind today's print actually brought.
with tab_cash:
    st.markdown('<div class="sec-header">Cash Feeder Prices</div>',
                unsafe_allow_html=True)
    cash_calves.render(tile, MUTED, key_prefix="bg")

st.markdown("<hr style='margin:18px 0 8px;'>", unsafe_allow_html=True)
st.markdown(
    f'<div class="srcline">JSA · John Stewart &amp; Associates &nbsp;·&nbsp; '
    f'Feeder prices from USDA AMS barn reports · CME Feeder Cattle (GF) via '
    f'Massive &nbsp;·&nbsp; {date.today().strftime("%b %d, %Y")}</div>',
    unsafe_allow_html=True)
