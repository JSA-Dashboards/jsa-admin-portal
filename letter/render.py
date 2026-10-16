"""
Render the letter to HTML, laid out for print.

Phrasing follows the sent letters rather than improving on them -- "Live cash-
222.85 versus 219.05 week before", "Choice cutout- Up 0.77 at 376.08- Tues PM."
Clients have been reading this wording for years and the generator is not the
place to redesign it.

MISSING VALUES ARE LOUD. Anything a source did not return renders as a marked
[[?]] instead of quietly disappearing, and build.py lists every one before it
finishes. A bullet that silently vanished between the draft and the PDF is the
exact failure this generator exists to remove, so it must not be able to happen
here either.
"""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta
from pathlib import Path

from . import chart as chart_mod
from . import config

import base64
import functools

MISSING = '<span class="missing">[[?]]</span>'

@functools.lru_cache(maxsize=8)
def _asset_uri(name: str) -> str:
    """
    An image from assets/, inlined as a data URI.

    EMBEDDED, NOT LINKED, for three reasons that all matter here. The PDF is
    produced by headless Edge and then emailed: a <img src="assets/..."> would
    resolve relative to wherever the HTML happens to sit, a jpsi.com URL would
    need the network at print time and would silently drop to a broken-image box
    if it were slow, and neither survives the file being forwarded. A data URI
    is part of the document.

    Returns "" when the file is missing, so a letter still builds -- letterhead
    is presentation, and losing it must not cost the numbers.
    """
    path = Path(__file__).resolve().parent.parent / "assets" / name
    try:
        return ("data:image/png;base64,"
                + base64.b64encode(path.read_bytes()).decode("ascii"))
    except OSError:
        return ""



# -- Formatting ---------------------------------------------------------------

def price(v, dp: int = 3) -> str:
    """
    Futures style: up to three decimals, trailing zeros trimmed, never fewer
    than two. 220.700 -> 220.70, 224.675 -> 224.675.
    """
    if v is None:
        return MISSING
    s = f"{float(v):.{dp}f}".rstrip("0")
    whole, _, frac = s.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def signed(v, dp: int = 3) -> str:
    if v is None:
        return MISSING
    return ("+" if float(v) >= 0 else "-") + price(abs(float(v)), dp)


def money(v) -> str:
    return MISSING if v is None else f"{float(v):,.2f}"


def head(v) -> str:
    return MISSING if v is None else f"{float(v):,.0f}"


def head_k(v) -> str:
    """
    Head counts rounded to the nearest thousand, which is how the letter quotes
    them. AMS estimates the current year in whole thousands already, but the
    year-ago columns are actuals -- 229,195 -- and printing that next to a
    rounded 210,000 would imply a precision the current figure does not have.
    """
    return MISSING if v is None else f"{round(float(v) / 1000) * 1000:,.0f}"


def updown(v) -> str:
    """'Up 0.77' / 'Down 0.21' -- the letter's own phrasing for cutout moves."""
    if v is None:
        return MISSING
    return f"{'Up' if float(v) >= 0 else 'Down'} {abs(float(v)):.2f}"


def pct(v) -> str:
    return MISSING if v is None else f"{float(v):.1f}"


def _esc(s) -> str:
    return html.escape(str(s))


def eighths(v) -> str:
    """
    531.25 -> "531'2". How the grain trade writes a corn quote, and how Ross
    writes it: "5'4 lower at 531'2".

    Rounded to the nearest eighth rather than truncated, and a value that rounds
    up to a full cent carries into the whole number -- 530.9999 is 531'0, never
    530'8, which is not a price anyone would recognise.
    """
    if v is None:
        return MISSING
    f = float(v)
    sign = "-" if f < 0 else ""
    f = abs(f)
    whole, frac = int(f), round((f - int(f)) * 8)
    if frac == 8:
        whole, frac = whole + 1, 0
    # A whole cent drops the eighths entirely -- "528", not "528'0", which is
    # how Ross writes it: "-8'6 at 528".
    return f"{sign}{whole}" if frac == 0 else f"{sign}{whole}'{frac}"


def trim(v) -> str:
    """
    220.0 -> "220", 222.5 -> "222.50", 350.0 -> "350".

    How the letter writes a cash price: no trailing ".00", but a real decimal
    keeps both places. "220-222.50 FOB live. 350 Dressed." is verbatim from the
    9/18 letter.
    """
    if v is None:
        return MISSING
    f = float(v)
    return f"{f:,.0f}" if abs(f - round(f)) < 1e-9 else f"{f:,.2f}"


def trim_range(lo, hi) -> str:
    """A range, collapsed to one number when both ends agree."""
    if lo is None:
        return MISSING
    return trim(lo) if hi is None or abs(float(hi) - float(lo)) < 1e-9 else f"{trim(lo)}-{trim(hi)}"


_PM_DAYS = {0: "Mon", 1: "Tues", 2: "Wed", 3: "Thurs", 4: "Fri", 5: "Sat", 6: "Sun"}


def _settle_stamp(ctx: dict) -> str:
    """
    "9/23/26" for the session the AM report's futures actually settled in.

    READ OFF THE CONTRACTS, NOT COMPUTED FROM THE ISSUE DATE. The prior session
    is not yesterday on a Monday, and it is not yesterday after a holiday
    either; subtracting a day would print a date on which nothing settled, on
    exactly the mornings a reader is most likely to be checking. The rows
    already carry settle_date, so the heading states it.

    Live Cattle and Feeders settle the same day. If a feed ever disagreed the
    newer date wins rather than the label being dropped -- which session this is
    is the whole point of the line, and a day of skew beats no date at all.
    """
    dates = []
    for key in ("live_cattle", "feeder_cattle"):
        for con in ctx.get(key) or []:
            try:
                dates.append(date.fromisoformat(str(con.get("settle_date") or "")[:10]))
            except ValueError:
                continue
    if not dates:
        return ""
    d = max(dates)
    return f"{d.month}/{d.day}/{d.strftime('%y')}"


def _pm_label(report_date) -> str:
    """' Tues PM.' from the cutout's own report date, or '' if unknown."""
    if not report_date:
        return ""
    try:
        d = date.fromisoformat(str(report_date)[:10])
    except ValueError:
        return ""
    return f" {_PM_DAYS[d.weekday()]} PM."


# -- Sections -----------------------------------------------------------------

def _bullets(items) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _commentary(items) -> str:
    """Commentary bullets are escaped -- they are typed prose, not markup."""
    return _bullets([_esc(i) for i in items])


def futures_block(title: str, contracts: list, basis: str) -> str:
    key = "change_week" if basis == "week" else "change_day"
    rows = [f"{_esc(c['month'])}: {signed(c.get(key))} at {price(c.get('settle'))}"
            for c in contracts]
    if not rows:
        rows = [MISSING]
    return f"<h2>{_esc(title)}</h2>{_bullets(rows)}"


def technicals_block(tech: dict, commentary: list, label: str) -> str:
    """
    The technical read, as Ross writes it. Nothing computed reaches the letter.

    THE MOVING AVERAGES USED TO PRINT HERE and stopped on 2026-09-25 at Ross's
    request: he fills the Technicals in himself. They are still fetched and
    still quoted in the draft under this heading -- see build.hints, where the
    9-day and 20-day sit beside the swing high/low and the prior session's range
    as the figures you would otherwise open a dashboard to read. Computed as a
    writing aid, printed only if he writes them.

    That also retires the int-vs-string key hazard this function carried: the
    context round-trips through JSON between the fetch and the --no-fetch
    re-render, so ma[9] came back as ma["9"] and looking up only the int made
    the averages vanish from the rendered letter with no error.

    `tech` is still read, for the month. The heading says WHICH contract the
    read is about -- "Oct Live Cattle", not "Live Cattle" -- because the front
    month rolls, and on 2026-09-25 the feeders rolled from Sep to Oct/Nov/Jan
    mid-week.
    """
    lines = [_esc(c) for c in commentary]
    if not lines:
        return ""
    month = tech.get("month", "") if tech else ""
    heading = f"{month} {label}".strip()
    return f"<h3>{_esc(heading)}</h3>{_bullets(lines)}"


def cash_trade_block(cash: dict) -> str:
    live, dressed, vol = cash.get("live", {}), cash.get("dressed", {}), cash.get("volume", {})
    rows = [
        f"Live cash- {money(live.get('this_week'))} versus {money(live.get('last_week'))} week before",
        f"Dressed cash- {money(dressed.get('this_week'))} versus {money(dressed.get('last_week'))} week before",
        f"Negotiated trade- {head(vol.get('confirmed'))} versus {head(vol.get('confirmed_last_week'))} week before",
        f"1-14-day window- {head(vol.get('d14'))} head versus {head(vol.get('d14_last_week'))} week before",
        f"15-30-day window- {head(vol.get('d30'))} head versus {head(vol.get('d30_last_week'))} week before",
    ]
    return "<h2>Last week&rsquo;s cash trade:</h2>" + _bullets(rows)


def fci_published(fci: dict) -> str:
    """
    The EVENING letter's index figure: what CME has actually printed, dated.

    NOT `fci["value"]`, which is the index CME will publish NEXT -- the first
    business day after their last file. That forward estimate is the right
    headline for the dashboard and for the morning brief, and both label it
    one. The evening rundown prints "Feeder Cattle Index: x" bare, so a
    reader takes it for the index as it stands, and an estimate of a day
    still in progress is not that.

    Reported by Ross on 2026-10-07: the afternoon report quoted 335.86 for
    index date 10/07 -- 228 locations, 17,524 head, the day still running --
    when CME had published 10/06 that morning at 337.87. Our own 10/06
    estimate was 337.869294, so the published figure was not merely
    available, it was one we already agreed with.

    BARE, WITH NO DATE AND NO LABEL. A first attempt printed
    "337.87 (10/6)" and, when the published block was missing,
    "335.86 (JSA est. 10/7)". Ross rejected both: what the line is for is
    the actual CME feeder index, most recent, and a parenthesis on it is
    either noise or an excuse.

    IT NEVER FALLS BACK TO `fci["value"]`. That fallback shipped on
    2026-10-07 and printed the exact figure Ross had reported an hour
    earlier -- the deployed app reads a different Snowflake, the CME table
    did not answer there, and the "fix" reproduced the bug with a label on
    it. `sources.fetch_feeder_index` now builds `published` from the merged
    series instead, so it degrades to OUR estimate for the same completed
    session rather than to the unfinished forward one. If even that is
    absent there is genuinely no index to print and it marks itself.
    """
    pub = (fci or {}).get("published") or {}
    return money(pub["value"]) if pub.get("value") is not None else MISSING



def rundown_block(fci: dict, slaughter: dict, cutout: dict,
                  daily: dict = None, weights: dict = None) -> str:
    rows = []
    daily = daily or {}
    weights = weights or {}

    if config.INCLUDE_FEEDER_INDEX:
        rows.append(f"Feeder cattle index- {fci_published(fci)}")

    # Daily and WTD come from AMS 3208, which is a different report from the
    # weekly SJ_LS712 the carcass weights use -- see sources.parse_3208.
    rows.append(f"Daily slaughter- {head_k(daily.get('current_day'))} head")
    rows.append(
        f"WTD slaughter- {head_k(daily.get('wtd'))} head versus "
        f"{head_k(daily.get('wtd_week_ago'))} LW and "
        f"{head_k(daily.get('wtd_year_ago'))} LY")

    # AMS 3658 actuals -- the series the Cattle Weights dashboard shows. If the
    # MARS key is missing this renders [[?]] rather than silently substituting
    # SJ_LS712's estimate, which is a different number.
    rows.append(f"Avg carcass wts- {head(weights.get('value'))}# versus "
                f"{head(weights.get('last_week'))}# LW and "
                f"{head(weights.get('year_ago'))}# LY")

    ch, se = cutout.get("choice", {}), cutout.get("select", {})
    # The "Tues PM" tag comes from the DATA's report date, not the issue date.
    # LM_XB403 PM publishes about 3pm Central, so a letter written earlier
    # carries the PREVIOUS session's cutout -- and labelling that "Tues PM" on a
    # Tuesday would be a false claim about which print it is. Deriving the day
    # from the report makes it say "Mon PM" instead, which is true.
    pm = _pm_label(cutout.get("report_date"))
    rows.append(f"Choice cutout- {updown(ch.get('change'))} at {money(ch.get('value'))}-{pm}")
    rows.append(f"Select cutout- {updown(se.get('change'))} at {money(se.get('value'))}-{pm}")
    rows.append(f"5-day averages- Choice {money(ch.get('avg5'))}. Select {money(se.get('avg5'))}.")

    g = cutout.get("grading", {})
    rows.append(f"Choice &amp; Higher Grading %- {pct(g.get('pct'))} versus {pct(g.get('pct_last_week'))} LW")

    return "<h2>Cattle market rundown:</h2>" + _bullets(rows)


# -- Friday-only sections -----------------------------------------------------
#
# Friday punctuates differently from Tuesday and the difference is kept rather
# than tidied: "Choice cutout: -0.21 at 371.94" against Tuesday's "Choice
# cutout- Down 0.21 at 371.94- Tues PM." Clients read both every week.

def yoy(v) -> str:
    """-7.5 -> '7.5% lower YoY'. USDA gives a signed change; the letter words it."""
    if v is None:
        return MISSING
    f = float(v)
    if f == 0:
        return "unchanged YoY"
    return f"{abs(f):.1f}% {'lower' if f < 0 else 'higher'} YoY"


def signed2(v) -> str:
    return MISSING if v is None else f"{float(v):+.2f}"


def friday_rundown_block(fci: dict, slaughter: dict, cutout: dict,
                         daily: dict = None, weights: dict = None) -> str:
    """Friday's rundown: Tuesday's, plus the completed week and both YTD rates."""
    daily, weights = daily or {}, weights or {}
    wk = (slaughter or {}).get("weekly") or {}
    bp = (slaughter or {}).get("beef_production") or {}
    rows = []

    if config.INCLUDE_FEEDER_INDEX:
        rows.append(f"Feeder Cattle Index: {fci_published(fci)}")

    rows.append(f"Daily slaughter: {head_k(daily.get('current_day'))}")
    # NO "(est., w/e 10/3)" TAG HERE, and it is not an oversight.
    #
    # One was added on 2026-09-29 and removed at Ross's request on 2026-10-02.
    # The reasoning for it still stands on the facts -- SJ_LS712 publishes on
    # the Friday for the week ending the SATURDAY AFTER, so the headline has
    # two days still projected in it, and USDA marks the three figures on this
    # line Estimate / Estimate / Actual. What it does not account for is that
    # Ross writes this letter and knows which week he is quoting; the tag was
    # six characters of hedging on a line his readers have read bare for
    # years. His letter, his call. Do not reinstate it without asking him.
    rows.append(
        f"Weekly slaughter: {head_k(wk.get('value'))} compared to "
        f"{head_k(wk.get('last_week'))} head LW and {head_k(wk.get('year_ago'))} LY")
    rows.append(f"YTD slaughter: {yoy(wk.get('ytd_chg_pct'))}")
    rows.append(f"Beef production: {yoy(bp.get('ytd_chg_pct'))}")
    rows.append(f"Avg carcass wts: {head(weights.get('value'))}# versus "
                f"{head(weights.get('last_week'))}# LW and {head(weights.get('year_ago'))}# LY")

    g = (cutout or {}).get("grading", {})
    rows.append(f"Choice grading: {pct(g.get('pct'))}% versus {pct(g.get('pct_last_week'))}% LW")

    ch, se = (cutout or {}).get("choice", {}), (cutout or {}).get("select", {})
    rows.append(f"Choice cutout: {signed2(ch.get('change'))} at {money(ch.get('value'))}")
    rows.append(f"Select cutout: {signed2(se.get('change'))} at {money(se.get('value'))}")
    rows.append(f"5-day averages: Choice {money(ch.get('avg5'))}. Select {money(se.get('avg5'))}")

    return "<h2>Cattle market rundown:</h2>" + _bullets(rows)


def wtd_cash_rows(ctx: dict) -> list:
    """
    This week's cash by state, in the letter's own shorthand:
    "NE: 221.00-222.50 live &middot; 350 dressed".

    Only states that actually traded are listed -- naming four every day so
    three can say "Undefined" is three wasted lines.

    EXCEPT ON FRIDAY, where the absence is the news. A state that never
    established a test all week is a fact about the market, and the weekly
    letter said nothing at all about it. Mid-week it means "not yet" and is
    noise; on Friday the week is closed and it means "not at all". That is
    the whole reason this is keyed on `kind` rather than applied everywhere.

    "Undefined" is USDA's own term for too little confirmed trade to publish
    a market test -- a real answer, not a gap, so it is never marked [[?]].
    The wording is carried over from the old two-region cash_cattle_block,
    which printed "South: Undefined" and was deleted when this took over; it
    was the one thing that block knew that this one did not.

    SHARED BY THE MORNING BRIEF AND THE RECAP. It was the morning brief's alone
    until 2026-09-24, when Ross asked for the same treatment Tue-Thu evening;
    extracted rather than copied, because two implementations of "how this
    letter writes a cash range" is exactly the kind of pair that drifts.
    """
    regions = (ctx.get("regional_cash") or {}).get("regions") or {}
    rows = []
    for name, r in ((n, r) for n, r in regions.items() if not r.get("undefined")):
        bits = []
        if r.get("live_low") is not None:
            bits.append(f"{trim_range(r['live_low'], r['live_high'])} live")
        if r.get("dressed_low") is not None:
            bits.append(f"{trim_range(r['dressed_low'], r['dressed_high'])} dressed")
        rows.append(f"{_esc(name)}: {' &middot; '.join(bits)}")

    # NOTHING TRADED ANYWHERE is one line, not four identical ones -- and an
    # EMPTY regions dict is a different thing entirely. fetch_regional_cash_wtd
    # always returns every state in CASH_STATES, marking the quiet ones
    # undefined, so empty means the fetch did not run. Saying "no test" then
    # would be reporting a market fact we never actually looked up.
    if not rows:
        return ["No established test this week"] if regions else []

    if ctx.get("kind") == "friday":
        rows.extend(f"{_esc(n)}: Undefined"
                    for n, r in regions.items() if r.get("undefined"))
    return rows


def wtd_cash_block(ctx: dict) -> str:
    """
    The recap's Cash Trade: this week's state ranges and nothing else.

    NO CUTOUT AND NO SLAUGHTER, unlike the morning brief's version of this
    block. Ross's point: on the evening letter both already appear a few inches
    below in the cattle market rundown, so repeating them here is the same
    figure twice on one page. The brief has no rundown, which is why it carries
    them there.

    NOT last week's weighted average either -- that is Monday's block, and it
    says "Last week's cash trade" because on a Monday that is the week worth
    reporting. Tuesday onward, the week in progress is the news.
    """
    rows = wtd_cash_rows(ctx)
    return "<h2>Cash Trade</h2>" + _bullets(rows) if rows else ""


def cftc_block(cftc: dict) -> str:
    """
    Managed money net long for both contracts.

    The as-of date is PRINTED FROM THE DATA, never typed. The 9/18/26 letter
    was headed "as of 9/8/26" while carrying the 9/15 report's figures; taking
    the date from the same rows as the numbers makes that impossible.
    """
    if not cftc or not cftc.get("markets"):
        return f"<h2>CFTC Report</h2>{_bullets([MISSING])}"
    as_of = cftc.get("as_of", "")
    try:
        y, m, d = as_of.split("-")
        stamp = f"{int(m)}/{int(d)}/{y[2:]}"
    except (ValueError, AttributeError):
        stamp = as_of

    # NESTED, NOT FLAT. These were six bullets at one level, so "Live Cattle:"
    # and its two figures sat at the same indent as "Feeder Cattle:" and its
    # two -- nothing but reading order said which pair belonged to which
    # contract. The product is the bullet; its figures are a list inside it.
    rows = []
    for name in ("Live Cattle", "Feeder Cattle"):
        mk = cftc["markets"].get(name)
        if not mk:
            rows.append(f"{name}: {MISSING}")
            continue
        # THE LABEL FOLLOWS THE SIGN, and that is not cosmetic. This line read
        # `f"Net Long: {head(...)}"` until 2026-10-07 and printed the words
        # "Net Long" above a NEGATIVE number every week managed money was net
        # short -- "Net Long: -870 contracts" on 2024-09-17, and on the six
        # Fridays before it.
        #
        # It is not a rare case. Managed money has been net short FEEDER cattle
        # in 248 of 1,060 weeks since 2006 (23.4%), and it comes in runs rather
        # than odd weeks: seven straight letters in Aug-Sep 2024, nine over the
        # 2023 turn, and two separate runs of 24 weeks in 2022. Live cattle has
        # done it 15 times, most recently 2020-04-07.
        #
        # It matters for this readership in particular. These are readers
        # fluent in USDA and CFTC notation, where a leading minus is easy to
        # skim past and a bracket means negative -- the trap `sterling.py` and
        # `apps/beef_cutout/am_cutout.py` both document. "Net Long: 870" read
        # quickly is the exact opposite of the truth, and inverting the fund
        # position inverts the market read.
        #
        # The Commitment of Traders dashboard carries the direction in a WORD
        # for the same reason (`cot_positions.side()`), so this also keeps the
        # letter and that page saying the same thing about the same figure --
        # the disagreement CLAUDE.md records three mornings lost to.
        #
        # WoW Change keeps its sign rather than a word, because a CHANGE has a
        # natural direction where a level does not -- but it now carries the
        # sign EXPLICITLY IN BOTH DIRECTIONS.
        #
        # `head()` formats a plain number, so a week of buying printed as a
        # bare "1,738" while a week of selling printed "-3,100". The reader
        # could tell a sale from a purchase only by the ABSENCE of a mark,
        # which is not something you notice on a line you are skimming -- and
        # the two happen about equally often: 551 up weeks against 507 down in
        # feeder cattle, 553 against 506 in live. "+1,738" and "-3,100" say
        # which it was without being read carefully.
        #
        # The one week in 2,120 where the change was exactly zero prints
        # "unchanged" rather than "+0" or a bare "0" -- the portal's standing
        # rule, because a bare zero reads as a figure that failed to load, and
        # the funds not moving in a week is a real answer.
        net = mk.get("net_long")
        side = "Net Short" if (net is not None and net < 0) else "Net Long"
        wow = mk.get("wow")
        if wow is None:
            wow_row = f"WoW Change: {MISSING} contracts"
        elif wow == 0:
            wow_row = "WoW Change: unchanged"
        else:
            wow_row = f"WoW Change: {wow:+,.0f} contracts"
        inner = _bullets([f"{side}: {head(net if net is None else abs(net))} contracts",
                          wow_row])
        rows.append(f"{name}:{inner}")
    return (f"<h2>CFTC Report as of {_esc(stamp)}:</h2>"
            "<div>Managed Money Traders (Futures Only)</div>" + _bullets(rows))


def cof_block(cof: dict) -> str:
    """
    The monthly Cattle on Feed table, or nothing at all.

    Actual and Year-Ago come from cof_recap's computation, so On-Feed reads
    100.7 and the Year-Ago basis 98.9 where the old Excel sheet read 100.8 and
    99. Guesses are typed in -- USDA does not publish them and nothing derives
    them -- so a missing guess prints an em dash rather than a marked gap.
    """
    if not cof or not cof.get("include"):
        return ""
    actual, year_ago, guesses = cof.get("actual", {}), cof.get("year_ago", {}), cof.get("guesses", {})

    def cell(v):
        return "&mdash;" if v is None else f"{float(v):.1f}"

    # Labels and headers punctuated as the letter punctuates them: a trailing
    # hyphen on each row label, colons on the first two column heads but not on
    # Year-Ago. Copied from the 9/18/26 letter rather than tidied.
    rows = "".join(
        f"<tr><td>{label}-</td><td>{cell(actual.get(key))}</td>"
        f"<td>{cell(guesses.get(key))}</td><td>{cell(year_ago.get(key))}</td></tr>"
        for key, label in (("on_feed", "On-Feed"), ("placed", "Placed"), ("marketed", "Marketed"))
    )
    return (
        f"<h2>{_esc(cof.get('title') or 'COF Report')}</h2>"
        "<table class='cof'><thead><tr><th></th><th>Actual:</th><th>Guesses:</th>"
        "<th>Year-Ago</th></tr></thead><tbody>" + rows + "</tbody></table>"
    )


# -- Page ---------------------------------------------------------------------

CSS = """
/* THE PAGE MARGIN IS WHERE THE FRAME GOES, and the text is inset the rest of
   the way with padding. The obvious construct -- keep a 0.9in margin and push a
   fixed frame outward with NEGATIVE offsets -- renders in headless
   --print-to-pdf and is clipped when the same letter prints from inside the
   preview iframe, because a negative-offset fixed box is only safe in a root
   context. Printed from the app it simply vanished, with nothing to say why.
   No negative offsets anywhere now: the frame sits at inset 0, which is the
   page box, and the text is moved in from it. */
/* A FIXED SIZE IS WHAT HIDES THE PRINT DIALOG'S ORIENTATION CONTROL, and
   "letter" on its own already does it.

   DO NOT ADD "portrait". Blink DISCARDS an orientation keyword that is
   redundant with an already-portrait named size -- Size::ParseSingleValue in
   longhands_custom.cc appends the orientation only when there is no page size
   or the keyword is not `portrait`. So `size: letter portrait` parses to
   exactly `size: letter`; read back through the CSSOM it serialises without
   the keyword. A commit added it on 2026-09-30 to fix a dialog stuck on
   landscape, changed literally nothing, and was reverted to this.

   What does the work: GetPageSizeAndOrientationInfo marks every page kFixed
   when @page names a size, which sets all_pages_have_custom_orientation, and
   the preview then REMOVES the Layout control rather than pre-selecting
   Portrait -- the ticket falls back to the setting's unavailableValue, which
   is portrait. `size: auto` would hand the control back, along with whatever
   orientation that reader last used, because Chromium persists `layout` as a
   sticky setting per profile.

   IT ONLY HOLDS FOR CHROMIUM'S OWN "Save as PDF" DESTINATION. Choose a system
   printer instead -- "Microsoft Print to PDF" is the trap, it reads as the
   same thing -- and the Layout control comes back with the sticky value. The
   page box stays portrait because the CSS still wins, so a tall sheet sits in
   a preview pane sized for a wide one and the letter has to be scrolled to
   read. That is exactly what Ross saw on 2026-09-30. */
@page { size: letter; margin: 0.52in; }
* { box-sizing: border-box; }
body {
  font-family: Calibri, Carlito, "Segoe UI", system-ui, sans-serif;
  font-size: 11.5pt; line-height: 1.32; color: #000; margin: 0;
  /* TOP 0.20, SIDES 0.33, BOTTOM 0.38. The sides and the foot still restore
     the original text block -- 0.52 + 0.33 = 0.85 across, 0.52 + 0.38 = 0.90
     up from the bottom -- but the HEAD is tighter than the 0.90in it used to
     be, by Ross's ask on 2026-09-29: "too much of a gap for the title".
     0.52 + 0.20 = 0.72in of white above the masthead, which still clears the
     frame comfortably.
     It also bought back the two lines of disclaimer that were tipping the
     morning brief onto a second page. The foot deliberately did NOT move: the
     disclaimer is the last thing on the page and crowding it against the
     frame is the problem this was fixing. */
  padding: 0.20in 0.33in 0.38in;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
/* Masthead is a row now: title left, logo hard right. baseline rather than
   center so the wordmark sits on the same line as the title rather than
   floating above it. */
.masthead { font-weight: 700; font-size: 13pt; margin: 0 0 14px;
            display: flex; align-items: baseline; justify-content: space-between;
            gap: 18px; }
.masthead img { height: 0.34in; width: auto; align-self: center; }
/* THE WATERMARK SITS BEHIND THE TEXT, not over it. z-index -1 puts it under
   the content, which only works because the page background lives on <html>
   -- put a background on <body> and this disappears underneath it.
   position:fixed so it is placed against the PAGE box in print, and it does
   not participate in layout at all, which is why letterhead costs the
   one-page brief nothing. */
html { background: #fff; }
/* THE FRAME COSTS NO LAYOUT, same trick as the watermark. position:fixed keeps
   it out of flow, so it cannot push the morning brief onto a second page, and
   in print Chrome positions it against the PAGE box -- hence the NEGATIVE
   offsets, which walk it out of the text area and into the margin. A frame
   drawn with a border on <body> would be in flow and would repaginate. */
.frame { position: fixed; z-index: -1; pointer-events: none; }
.wm { position: fixed; left: 50%; top: 46%; transform: translate(-50%, -50%);
      width: 4.4in; opacity: 0.07; z-index: -1; pointer-events: none; }
table.band { width: 100%; border-collapse: collapse; margin: 0 0 -10px; }
/* The two blocks sit TOGETHER on the left, not at opposite edges of the page.
   A 50/50 split put Cattle Futures at the horizontal midpoint and opened a
   lane of white space between two short lists. The first cell now shrinks to
   its own widest line -- width:1% with nowrap is the usual idiom for a
   shrink-to-fit table cell -- and the second takes the remainder, so the
   gutter is a deliberate 42px instead of whatever the page had left over. */
table.band > tr > td, table.band td { vertical-align: top; padding: 0; }
table.band td:first-child { width: 1%; white-space: nowrap; padding-right: 42px; }
table.band h2:first-child { margin-top: 0; }
table.band ul { margin-bottom: 0; }
.intro { margin: 0 0 14px; }
h2 { font-size: 11.5pt; font-weight: 700; margin: 16px 0 4px; }
/* A qualifier on a heading, not part of it: lighter and smaller so the
   heading still reads as one word at a glance. */
h2 .asof { font-weight: 400; font-size: 9.5pt; color: #444; }
h3 { font-size: 11.5pt; font-weight: 400; margin: 10px 0 3px; }
ul { margin: 0 0 4px; padding-left: 22px; }
li { margin: 1px 0; }
.missing {
  background: #ffe8a3; border: 1px solid #c79b12; color: #7a5c00;
  padding: 0 4px; border-radius: 3px; font-weight: 700;
}
table.cof { border-collapse: collapse; margin: 6px 0 4px; font-size: 11pt; }
table.cof th, table.cof td { padding: 1px 16px 1px 0; text-align: left; }
table.cof th { font-weight: 700; }
table.cof td:first-child { font-weight: 600; }
.signoff { margin: 18px 0 26px; }
/* THE CHART COSTS NO VERTICAL SPACE, and that is the only reason it is allowed
   on a one-page brief. Floated right before the sign-off, it drops into the
   band beside the signature block -- measured empty at 1.89in tall by 4.97in
   wide -- so the text flows up its left and the page does not grow. Make it
   taller than that band and the letter runs to two pages; a test checks. */
.dayplot-wrap { float: right; margin: 2px 0 6px 18px; }
.dayplot { display: block; }
/* A LINE INSTEAD OF A CHART, in the same float and the same width, so the
   page geometry does not change with the choice. Sized to the chart's 3.1in
   and kept well inside the 1.89in band -- three lines of 8.5pt is about
   0.55in, so this can never be the thing that costs a second page.
   Hairline rule in the frame's sage rather than a box: it should read as a
   footnote on stationery, not as a callout competing with the market. */
.dayfact { width: 3.1in; border-top: 0.75pt solid #5e7164; padding-top: 5px; }
.dayfact-label { font-size: 7pt; letter-spacing: 0.06em; text-transform: uppercase;
                 color: #5e7164; font-weight: 700; margin-bottom: 2px; }
.dayfact-text { font-size: 8.5pt; line-height: 1.34; color: #222; }
/* Space between facts when there is more than one, and none after the last,
   so a single line is spaced exactly as it was before this became a list. */
.dayfact-text + .dayfact-text { margin-top: 4px; }
/* One page is the product: a three-minute brief that spills its
   disclaimer onto a second sheet has stopped being one. Tightened for
   the morning only -- the evening letter keeps its roomier spacing. */
body.am h2 { margin: 12px 0 3px; }
body.am .intro { margin: 0 0 10px; }
body.am .signoff { margin: 14px 0 18px; }
/* 22px on a page that was overflowing by two lines. The gap is there so the
   risk text does not sit hard against the phone number; 12px still reads as a
   separate block and is worth an eighth of an inch on a one-page budget. The
   evening letter, which has the whole page, keeps the roomier 30px below. */
body.am .sig .disclaimer { margin-top: 12px; }
/* The evening letter keeps its own page for the signature and the
   disclaimer, matching the printed letter clients already receive. The
   morning brief does not: it is one page, and pushing six lines of
   signature onto a second doubles a three-minute read. */
.sig { margin-top: 4px; }
.sig.own-page { page-break-before: always; }
.sig div { margin: 0; }
/* .sig .disclaimer, not .disclaimer: ".sig div" above is the more specific
   selector, so a bare .disclaimer rule loses to it and the margin-top is
   silently dropped -- which is why the risk text sat hard against the cell
   number with no gap at all. */
.sig .disclaimer {
  margin-top: 30px; font-size: 8pt; line-height: 1.35; color: #222; text-align: justify;
}
"""


# -- The morning brief --------------------------------------------------------
#
# Built to be read in under three minutes, which is the whole product. Every
# block earns its place or it comes out: a section that says the same thing for
# three weeks stops being read, and takes the ones around it with it.

def am_cattle_rows(ctx: dict, per_product: int = 2) -> list:
    """
    The two nearby Live Cattle and Feeder Cattle contracts.

    YESTERDAY'S SETTLE AND ITS MOVE, not a week-to-date change: CME livestock
    does not open until 08:30 Central, so at the hour this goes out there is no
    session of its own to report and the prior close is the number the day is
    measured from. The evening letter quotes the week instead, which is why this
    reads change_day where that reads change_week.
    """
    rows = []
    for key, tag in (("live_cattle", "LC"), ("feeder_cattle", "FC")):
        for con in (ctx.get(key) or [])[:per_product]:
            rows.append(f"{_esc(con['month'])} {tag}: "
                        f"{signed(con.get('change_day'))} at {price(con.get('settle'))}")
    return rows


def am_blocks(ctx: dict, c: dict) -> list:
    """The AM report's sections, in reading order."""
    out = []

    # 1. The index first -- it is JSA's own number and the reason to open this.
    fci = ctx.get("fci") or {}
    if config.INCLUDE_FEEDER_INDEX and fci.get("value") is not None:
        # Same shape as the overnight quotes -- change first, then "at", then
        # the price. One reading pattern for every number on the page.
        #
        # No date on the line: the heading says Estimate, the brief is dated at
        # the top, and a second date here is one more thing to read past.
        rows = [("Estimate: " + (f"{signed(fci['change'], 2)} at {money(fci['value'])}"
                                 if fci.get("change") is not None else money(fci["value"])))]
        # Basis against the front feeder contract: one number that frames the
        # whole feeder complex before the open. Cash minus futures, the usual
        # convention, so a negative basis means the board is over the index.
        front = (ctx.get("feeder_cattle") or [None])[0]
        if front and front.get("settle") is not None:
            basis = float(fci["value"]) - float(front["settle"])
            rows.append(f"{_esc(front['month'])} feeders: {price(front['settle'])}")
            rows.append(f"Basis: {signed(basis, 2)}")
        cattle = am_cattle_rows(ctx)
        left = "<h2>JSA FCI Estimate</h2>" + _bullets(rows)
        if cattle:
            # The heading says WHICH SESSION these settled in. The rows are
            # yesterday's close and yesterday's move -- see am_cattle_rows --
            # and on a page dated today that is worth saying once, next to the
            # numbers, rather than leaving the reader to assume.
            settled = _settle_stamp(ctx)
            head = "Cattle Futures"
            if settled:
                head += f' <span class="asof">Settlement on {settled}</span>'
            out.append(
                '<table class="band"><tr>'
                f'<td>{left}</td>'
                f'<td><h2>{head}</h2>{_bullets(cattle)}</td>'
                "</tr></table>")
        else:
            out.append(left)

    # 2. Headlines -- written, and where border status lives.
    if c.get("headlines"):
        out.append("<h2>Headlines</h2>" + _commentary(c["headlines"]))

    # 3. Overnight. Cattle do not trade overnight, so this is grain and macro.
    #    Month BEFORE the commodity: "Dec Corn", not "Corn Dec".
    markets = [m for m in (ctx.get("outside") or []) if m.get("price") is not None]
    if markets:
        rows = []
        for m in markets:
            fmt = eighths if m.get("style") == "eighths" else money
            chg = m.get("change")
            chg_txt = (("+" if chg >= 0 else "") + fmt(chg)) if chg is not None else MISSING
            # Change BEFORE the price, joined by "at" -- the same shape the
            # evening letter uses for cattle ("Oct: +1.025 at 220.70") and the
            # shape Ross asked for: "Dec Corn -8'6 at 528".
            rows.append(f"{_esc(m.get('month') or '')} {_esc(m['label'])}: "
                        f"{chg_txt} at {fmt(m['price'])}")
        out.append("<h2>Overnight Markets</h2>" + _bullets(rows))

    # 4. Yesterday, for anyone who did not read the evening letter. One line
    #    each, no LW/LY triples -- that density belongs in the PM report.
    rows = []
    # Week to date by state, in the letter's own shorthand:
    #   "Cash  NE 221.00-222.50 live, 350 dressed"
    # Only states that actually traded are listed -- naming four every morning
    # so three can say "Undefined" is three wasted lines.
    rows.extend(wtd_cash_rows(ctx))

    # NO WEEKLY WEIGHTED AVERAGE HERE. LM_CT150's "this week" is the last
    # COMPLETED week, published after it ends -- so on a Wednesday morning it is
    # the previous week's average sitting next to this week's daily trade, which
    # is two different weeks on adjacent lines. The state ranges above are the
    # current week. The weighted average still leads the evening letter, where
    # "Last week's cash trade" says plainly which week it means.

    cut = ctx.get("cutout") or {}
    ch, se = cut.get("choice", {}), cut.get("select", {})
    if ch.get("value") is not None:
        rows.append(f"Cutout: Choice {money(ch['value'])} {signed(ch.get('change'), 2)} "
                    f"&middot; Select {money(se.get('value'))} {signed(se.get('change'), 2)}")
    dsl = ctx.get("daily_slaughter") or {}
    if dsl.get("current_day") is not None:
        rows.append(f"Slaughter: Daily {head_k(dsl['current_day'])} &middot; "
                    f"WTD {head_k(dsl.get('wtd'))} "
                    f"({head_k(dsl.get('wtd_week_ago'))} LW, {head_k(dsl.get('wtd_year_ago'))} LY)")
    if rows:
        out.append("<h2>Cash Trade</h2>" + _bullets(rows))

    # 5. The week's releases as ONE list, each with its date -- rather than a
    #    "Today" block and a "This Week" block. A reader scanning for whether
    #    anything prints today finds it in the same place either way, and one
    #    list is a shorter read than two headings.
    # THIS WEEK ONLY, though the fetch reaches six weeks out. sources
    # .fetch_report_calendar argues, correctly, that a WASDE a fortnight away
    # changes how the month is traded -- so the horizon stays wide and the
    # trimming happens HERE, at the display. The full list is still in the ctx
    # for anything else that wants it.
    #
    # Five rows of October on a one-page brief is most of a section spent on
    # things three weeks out. Ross asked for the current week on 2026-09-29;
    # the comment above this block always claimed it was "the week's releases"
    # and only now is that true.
    items = (ctx.get("calendar") or {}).get("items") or []
    issue = ctx.get("issue_date")
    if isinstance(issue, str):
        try:
            issue = date.fromisoformat(issue[:10])
        except ValueError:
            issue = None
    if isinstance(issue, date):
        # Through Sunday, so "this week" means the calendar week the letter is
        # written in rather than the next seven days -- on a Thursday those are
        # very different lists.
        week_end = (issue + timedelta(days=6 - issue.weekday())).isoformat()
        # BOTH ENDS. The fetch already drops anything before as_of, but a
        # --no-fetch re-render reads a ctx captured days earlier, and an
        # "upcoming" report that has already printed is worse than a long list.
        shown = [i for i in items
                 if issue.isoformat() <= str(i.get("date") or "")[:10] <= week_end]
    else:
        shown = items

    rows = [f"{_esc(i['label'])}: {_esc(i['when'])}"
            + (" <strong>(today)</strong>" if i.get("is_today") else "")
            for i in shown]

    # A QUIET WEEK STILL NAMES WHAT IS NEXT, in one line. The section exists so
    # a reader is not hearing about a Cattle on Feed on the morning it prints,
    # and a bare "None scheduled" on a Thursday would hide one landing Monday.
    # One line is not the five this change removed.
    if not rows:
        after = issue.isoformat() if isinstance(issue, date) else ""
        nxt = next((i for i in items if str(i.get("date") or "")[:10] >= after), None)
        rows = [f"None this week &mdash; next is {_esc(nxt['label'])}: {_esc(nxt['when'])}"] \
            if nxt else ["None scheduled"]

    out.append("<h2>Upcoming USDA Reports</h2>" + _bullets(rows))
    return out


def dayfact_block(text: str) -> str:
    """
    One line in the chart's slot, for a morning when a fact beats a chart.

    SAME FLOAT, SAME WIDTH, so choosing one over the other cannot change the
    page. The chart occupies a band beside the signature that is empty
    anyway; this occupies the same band and less of it.

    It takes whatever Ross typed. The On This Day panel seeds the box from
    history.com, but the words that reach a client are his -- the events are
    facts and free to use, the phrasing is theirs and is not, and the panel
    says so. Escaped, like every other line he writes: it is prose, not
    markup.
    """
    if not (text or "").strip():
        return ""
    # ONE LINE PER LINE. Newlines collapse in HTML, so several facts pasted
    # into the box would have run together into one paragraph -- readable as
    # nothing. Each becomes its own block, and the label goes plural when it
    # should.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    body = "".join(f'<div class="dayfact-text">{_esc(ln)}</div>' for ln in lines)
    return ('<div class="dayplot-wrap dayfact">'
            '<div class="dayfact-label">On this day</div>'
            f'{body}</div>')


def _signature_html(issue, own_page: bool = True, disclaimer: bool = True) -> str:
    """
    The signature, and the risk disclaimer unless it is being left off.

    WHY THE DISCLAIMER IS EVER OMITTED, and why the default is never to.
    Ross sends the letter in an email that already carries the firm's risk
    disclaimer, and the attached copy then prints it twice. So one variant
    drops it -- for the PDF and the image that go INSIDE that email, and for
    nothing else.

    DEFAULT TRUE EVERYWHERE, and no caller gets it by accident:
    `letter.build` never passes it, so the CLI, `--no-fetch` re-renders and
    `--archive` all keep the full letter. Only the authoring page can turn it
    off, per render, with the state shown on screen and reset every run. A
    disclaimer that goes missing quietly is the failure that matters here,
    so the switch is deliberate, visible, and does not persist.
    """
    s = config.SIGNATURE
    body = (
        f'<div>{_esc(s["name"])}</div>'
        f'<div>{_esc(s["company"])}</div>'
        f'<div>{_esc(s["city"])}</div>'
        f'<div>{_esc(s["web"])}</div>'
        f'<div>Office: {_esc(s["office"])}</div>'
        f'<div>Cell: {_esc(s["cell"])}</div>'
    )
    if disclaimer:
        body += (f'<div class="disclaimer">'
                 f'{_esc(config.DISCLAIMER.format(year=issue.year))}</div>')
    return f'<div class="sig{" own-page" if own_page else ""}">{body}</div>'



def _page(title: str, stamp: str, body: list, body_class: str = "") -> str:
    cls = f' class="{body_class}"' if body_class else ""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(title)} {stamp}</title>"
        f"<style>{CSS}</style></head><body{cls}>" + "".join(body) + "</body></html>"
    )


def build_html(ctx: dict, *, disclaimer: bool = True) -> str:
    """
    ctx carries the fetched data plus the commentary sections.

    `disclaimer` is KEYWORD-ONLY and defaults to True so that every existing
    caller -- the CLI, the archive, thirty-odd tests -- keeps producing the
    full letter without being touched. See _signature_html for why the only
    place that may set it False is the authoring page.
    """
    issue: date = ctx["issue_date"]
    c = ctx["commentary"]
    # Built by hand rather than with strftime: the letter uses unpadded 9/18/26,
    # and the "%-m" that produces on Linux raises ValueError on Windows, which is
    # where this actually runs.
    stamp = f"{issue.month}/{issue.day}/{issue.strftime('%y')}"

    # The two letters open differently: Tuesday reports the week so far, Friday
    # the week just closed.
    kind = ctx.get("kind", "tuesday")
    # The masthead names the SESSION -- "JSA Morning Cattle Report" against
    # "JSA Afternoon Cattle Report". Two reports a day, two names.
    title = config.title_for(ctx.get("session", config.DEFAULT_SESSION))
    # There is no close to report at 07:30, so the AM letter cannot use either
    # evening opening.
    if kind == "am":
        intro = config.INTRO_AM.format(stamp=stamp)
        sign_off = config.SIGN_OFF_AM
    elif kind == "recap":
        # A session, not a period -- see config.INTRO_RECAP for why it is blank.
        intro, sign_off = config.INTRO_RECAP, config.SIGN_OFF_TUESDAY
    elif kind == "friday":
        intro, sign_off = f"For the week of {stamp}:", config.SIGN_OFF_FRIDAY
    else:
        intro = f"For the week through the close on {stamp}:"
        sign_off = config.SIGN_OFF_TUESDAY

    # An empty intro renders nothing rather than an empty paragraph -- see
    # config.INTRO_AM, which is blank because the masthead already said it.
    # Letterhead on every letter, AM and PM alike -- it is the same company
    # writing. Both images are embedded; see _asset_uri.
    _logo, _mark = _asset_uri("logo-full.png"), _asset_uri("jsa-50-years.png")
    head = []
    if getattr(config, "FRAME", ""):

        head.append(
            f'<div class="frame" style="top:0;right:0;bottom:0;left:0;'
            f'border:{config.FRAME_WIDTH} solid {config.FRAME};"></div>')
    if _mark:
        head.append(f'<img class="wm" src="{_mark}" alt="">')
    head.append(
        f'<div class="masthead"><span>{_esc(title)} {stamp}</span>'
        + (f'<img src="{_logo}" alt="John Stewart and Associates">' if _logo else "")
        + '</div>')
    if intro:
        head.append(f'<p class="intro">{_esc(intro)}</p>')

    body = head + [
        futures_block("Live Cattle", ctx["live_cattle"], ctx["change_basis"]),
        futures_block("Feeder Cattle", ctx["feeder_cattle"], ctx["change_basis"]),
    ]

    # THE MORNING REPORT ENDS HERE. It is described as much simpler and shorter
    # than any evening letter, and most of what follows does not exist at 07:30
    # anyway -- no completed session to recap, no PM cutout, no settle for today.
    # Returning early rather than opting out section by section means a section
    # added to the PM letter later cannot silently appear in the AM one.
    #
    # SETTLED 2026-09-23, after Ross reviewed it section by section: the index
    # and its basis, the cattle board, his Headlines, the overnight grain and
    # macro quotes, week-to-date cash by state, and the month's USDA reports.
    # One page, under three minutes, and that budget is the product -- a section
    # added here has to earn its place against the reading time, not just fit.
    if kind == "am":
        body = list(head)                  # masthead, and the intro if there is one
        body.extend(am_blocks(ctx, c))
        # BEFORE the sign-off in source order, which is what puts a float in the
        # bottom-right corner: everything after it flows up its left side.
        # A TYPED LINE WINS OVER THE CHART. One slot, and the rule is simply
        # whether anything is in the box -- no mode to set and get wrong, and
        # emptying it puts the chart straight back.
        body.append(dayfact_block(ctx.get("dayfact"))
                    or chart_mod.chart_block(ctx.get("chart")))
        body.append(f'<p class="signoff">{_esc(sign_off)}</p>')
        body.append(_signature_html(issue, own_page=False,
                                    disclaimer=disclaimer))
        return _page(title, stamp, body, body_class="am")

    # HEADLINES LEAD, then the session recap. Friday has led with Key Headlines
    # since it was written and the morning brief leads with Headlines; as of
    # 2026-09-23 the standard evening letter does too, so all three open on what
    # happened before they explain it.
    #
    # Friday is still EITHER/OR rather than both: its Key Headlines section
    # replaced Market Action, and that format has no market_action key to render.
    if kind == "friday":
        if c.get("key_headlines"):
            body.append("<h2>Key Headlines</h2>" + _commentary(c["key_headlines"]))
    else:
        if c.get("headlines"):
            body.append("<h2>Headlines</h2>" + _commentary(c["headlines"]))
        if c.get("market_action"):
            body.append("<h2>Market Action</h2>" + _commentary(c["market_action"]))

    # EVERY EVENING FORMAT, the same shape. The recap was a special case
    # printing one combined read under a bare "Technicals" until 2026-10-15 --
    # see commentary.SECTIONS_BY_KIND for why that went, and note that
    # technicals_block returns "" for a product with no written bullets, so a
    # letter where only one side is written still prints only one heading.
    tech_lc = technicals_block(ctx.get("tech_lc"), c.get("technicals_lc", []), "Live Cattle")
    tech_fc = technicals_block(ctx.get("tech_fc"), c.get("technicals_fc", []), "Feeders")
    if tech_lc or tech_fc:
        body.append("<h2>Technicals</h2>" + tech_lc + tech_fc)

    if kind == "friday":
        # Friday drops the five-bullet weekly cash block and carries the
        # current-week regional ranges instead, further down.
        body.append(friday_rundown_block(ctx.get("fci"), ctx["slaughter"], ctx["cutout"],
                                         ctx.get("daily_slaughter"), ctx.get("carcass_weights")))
        # The same block as the recap. Friday used to print North/South for one
        # day here; it now prints the week by state, which is the week the
        # letter is reviewing. See wtd_cash_block.
        body.append(wtd_cash_block(ctx))
        if c.get("cash_recap"):
            body.append("<h2>Cash Trade Recap:</h2>" + _commentary(c["cash_recap"]))
        body.append(cftc_block(ctx.get("cftc")))
        cof_html = cof_block(ctx.get("cof"))
        if cof_html:
            body.append(cof_html)
            if c.get("cof_note"):
                body.append(_commentary(c["cof_note"]))
    else:
        # WHICH CASH BLOCK DEPENDS ON THE DAY, and that is the whole point.
        # Monday reports the week that just closed, so it leads with the
        # weighted average under "Last week's cash trade". Tuesday onward the
        # week in progress is the news, so the recap carries this week's state
        # ranges instead -- the same block the morning brief runs, minus the
        # cutout and slaughter lines, which are a few inches below in the
        # rundown on this letter and would be the same figure twice.
        if kind == "recap":
            body.append(wtd_cash_block(ctx))
        else:
            body.append(cash_trade_block(ctx["cash"]))

        body.append(rundown_block(ctx.get("fci"), ctx["slaughter"], ctx["cutout"],
                                  ctx.get("daily_slaughter"), ctx.get("carcass_weights")))
        # The Fundamental Rundown is what makes Monday the heavy letter, so the
        # recap stops here. `recap` has no "fundamental" key at all, so this is
        # belt and braces rather than the only guard.
        if kind != "recap" and c.get("fundamental"):
            body.append("<h2>Fundamental Rundown</h2>" + _commentary(c["fundamental"]))

    # COMMENTS, LAST. The catch-all for anything the named sections do not
    # cover, on every evening letter. The morning brief never reaches this line
    # -- it returned above -- which is deliberate: see commentary.py.
    if c.get("comments"):
        body.append("<h2>Comments</h2>" + _commentary(c["comments"]))

    body.append(f'<p class="signoff">{_esc(sign_off)}</p>')
    # THE RECAP'S SIGNATURE DOES NOT TAKE ITS OWN PAGE. Tuesday and Friday put
    # it on a sheet of its own and keep doing so -- they are the long letters and
    # a clean signature page suits them. On the recap that one page break was
    # the difference between two sheets and three, which is most of what
    # "lighter" was supposed to buy.
    # The recap never takes a page for this; the others follow the setting.
    # See config.SIGNATURE_OWN_PAGE -- it is False, so nothing does today.
    body.append(_signature_html(
        issue, own_page=(kind != "recap") and config.SIGNATURE_OWN_PAGE,
        disclaimer=disclaimer))
    return _page(title, stamp, body)
