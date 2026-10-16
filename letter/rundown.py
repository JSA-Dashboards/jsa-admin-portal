"""
The Cattle Market Rundown slide.

One client-facing slide of the day's fundamentals, in the shape Ross has been
typing by hand into PowerPoint: cash trade, carcass weights, cutout, grading,
the feeder index, and the two year-to-date rates.

IT NEVER FETCHES, AND THAT IS THE WHOLE POINT.

`rows()` takes the ctx `build.gather()` has already assembled and formats it.
It has no import path to `sources`, no `requests`, and no database handle --
the same rule `render.py` follows, and a test asserts it. The reason is not
tidiness. CLAUDE.md records twice that the letter and a dashboard quoted the
same figure and disagreed, each defensible in isolation and neither raising,
and both took a morning to find. A slide built from a SECOND set of fetches
would be a third number in that argument. Built from the ctx, the slide and
the letter are the same arithmetic by construction and cannot drift.

MISSING FIGURES ARE MARKED, NEVER DROPPED.

A bullet that silently disappears reads as "nothing to report there", which on
a client slide is a statement -- and a wrong one. Anything a source did not
return prints `[[?]]`, exactly as the letter does, so a hole looks like a hole.
`missing()` counts them so the page can refuse to hand over a deck that is
quietly full of them.

THE FIGURES THIS FIXES, recorded because they were wrong on the hand-typed
slide for 2026-10-05 and the whole point of automating it is that they stop
being wrong:

    carcass weights   "as of 8/19/26" for a week ending 9/19/26 -- a typo in
                      the month, invisible because a four-week-old weight
                      looks no different from a two-week-old one. The week
                      ending is now printed from the data.
    Slaughter YTD     -7.7% against USDA's published -7.5%
    Beef Prod YTD     -5.3% against USDA's published -5.2%
                      Both are read straight off USDA's own Change rows, so
                      they are not our arithmetic -- the hand-typed pair had
                      been carried over from the previous week's slide.
    Feeder Index      337.79 against 337.22. NOT a firming-up of the same
                      row -- 337.79 is the 2026-09-25 value, carried forward
                      from the previous week's deck. fci_daily has 10/05 at
                      337.218 and 09/25 at 337.794. The row DOES firm up
                      separately (10/05 read 337.66 then 337.22 during
                      2026-10-06), and conflating the two is the mistake
                      this entry exists to stop repeating.

The 5-day average is the five sessions BEFORE the one being reported. See
`sources.fetch_cutout`, which carried the other convention until 2026-10-06.
"""

from __future__ import annotations

import pathlib
from datetime import date, datetime, timedelta

# Plain text, not render.MISSING -- that one is wrapped in a <span> for the
# letter's CSS and would print the markup inside a PowerPoint text box.
MISSING = "[[?]]"

TITLE = "Cattle Market Rundown"


# -- formatting ---------------------------------------------------------------
# Each of these mirrors how the figure reads on the slide Ross has been typing,
# down to the punctuation. They are separate from render.py's helpers because
# that module's emit HTML and escape for it.

def _f(v):
    """float or None, tolerating the strings USDA sometimes sends."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def money(v) -> str:
    v = _f(v)
    return MISSING if v is None else f"{v:,.2f}"


def head(v) -> str:
    v = _f(v)
    return MISSING if v is None else f"{v:,.0f}"


def signed_head(v) -> str:
    """'+40,881' -- a week-on-week head change, always signed."""
    v = _f(v)
    return MISSING if v is None else f"{v:+,.0f}"


def signed_money(v) -> str:
    v = _f(v)
    return MISSING if v is None else f"{v:+.2f}"


def lbs(v) -> str:
    """'891#' -- the trade's own way of writing a carcass weight."""
    v = _f(v)
    return MISSING if v is None else f"{v:,.0f}#"


def pct1(v) -> str:
    v = _f(v)
    return MISSING if v is None else f"{v:.1f}%"


def signed_pct1(v) -> str:
    """'-7.5%'. Unsigned when positive, because '+2.1% YTD' is not how it reads."""
    v = _f(v)
    return MISSING if v is None else f"{v:.1f}%"


def short_date(d) -> str:
    """
    '9/19/26'. Built by hand rather than with strftime because the no-pad
    directive is %-d on Linux and %#d on Windows, and this runs on both.
    """
    d = _as_date(d)
    return MISSING if d is None else f"{d.month}/{d.day}/{d.year % 100:02d}"


def _as_date(d):
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if not d:
        return None
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _weekday(d) -> str:
    """'Monday', for the 'Choice- 378.26. +4.07 Monday PM.' line."""
    d = _as_date(d)
    return d.strftime("%A") if d else MISSING


def _diff(a, b):
    a, b = _f(a), _f(b)
    return None if a is None or b is None else a - b


# -- the slide ----------------------------------------------------------------

def rows(ctx: dict) -> list:
    """
    The slide as (indent_level, text) pairs, in order.

    Levels mirror the hand-typed deck: 0 is a top bullet, 3 is the delivery
    split nested under the volume total. Returning structure rather than a
    rendered string is what lets the page preview it as markdown and the
    exporter lay it out as real PowerPoint bullets from the same source.
    """
    cash = ctx.get("cash") or {}
    cutout = ctx.get("cutout") or {}
    weights = ctx.get("carcass_weights") or {}
    fci = ctx.get("fci") or {}
    slaughter = ctx.get("slaughter") or {}

    live = cash.get("live") or {}
    dressed = cash.get("dressed") or {}
    vol = cash.get("volume") or {}

    out = [(0, "Last week's cash trade")]
    out.append((1, f"{money(live.get('this_week'))} live versus "
                   f"{money(live.get('last_week'))} week earlier"))
    out.append((1, f"{money(dressed.get('this_week'))} dressed versus "
                   f"{money(dressed.get('last_week'))} week earlier"))
    out.append((1, f"Volume: {signed_head(_diff(vol.get('confirmed'), vol.get('confirmed_last_week')))}/hd WoW"))
    out.append((2, f"{head(vol.get('confirmed'))} head total"))
    out.append((3, f"1-14-day: {head(vol.get('d14'))}. "
                   f"{signed_head(_diff(vol.get('d14'), vol.get('d14_last_week')))}/hd WoW"))
    out.append((3, f"15-30 day: {head(vol.get('d30'))}. "
                   f"{signed_head(_diff(vol.get('d30'), vol.get('d30_last_week')))}/hd WoW"))

    # THE WEEK ENDING IS PRINTED, NOT ASSUMED. This report runs about a
    # fortnight behind, which is long enough that a wrong date is invisible --
    # it is how "8/19/26" survived on the hand-typed slide.
    steers = weights.get("steers") or {}
    out.append((0, f"Actual carcass weights as of {short_date(weights.get('week_ending'))}- "
                   f"{lbs(weights.get('value'))} versus {lbs(weights.get('last_week'))} LW "
                   f"and {lbs(weights.get('year_ago'))} LY"))
    out.append((1, f"Steers- {lbs(steers.get('value'))} versus {lbs(steers.get('last_week'))} LW "
                   f"and {lbs(steers.get('year_ago'))} LY"))

    choice = cutout.get("choice") or {}
    select = cutout.get("select") or {}
    when = _weekday(cutout.get("report_date"))
    out.append((0, f"Choice- {money(choice.get('value'))}. "
                   f"{signed_money(choice.get('change'))} {when} PM."))
    out.append((1, f"5-day average- {money(choice.get('avg5'))}."))
    out.append((0, f"Select- {money(select.get('value'))}. "
                   f"{signed_money(select.get('change'))} {when} PM."))
    out.append((1, f"5-day average- {money(select.get('avg5'))}."))

    # Derived here rather than taken from the feed: USDA publishes the two
    # cutouts and the spread is their difference, so computing it guarantees
    # the three numbers on the slide are consistent with each other.
    grading = cutout.get("grading") or {}
    out.append((0, f"Choice/Select spread: {money(_diff(choice.get('value'), select.get('value')))}"))
    out.append((1, f"Choice & Higher- {pct1(grading.get('pct'))}"))

    # THE ACTUAL CME FEEDER INDEX, MOST RECENT. Bare -- no date, no "(est)".
    #
    # `fci["value"]` is the index CME will print NEXT, so on an afternoon
    # slide it is a part-day estimate of an unfinished day: on 2026-10-07 it
    # read 335.86 for 10/07 off 228 locations, where CME had published 10/06
    # at 337.87 and our own 10/06 estimate was 337.869294. Ross reported it
    # twice -- once for the value, once again when the first fix merely
    # labelled it "(JSA est. 10/7)" instead of replacing it.
    #
    # `published` comes from the merged series, so it is CME's print where
    # we have it and our estimate for that SAME completed session where we
    # do not. It can never be the forward day. The letter's evening rundown
    # reads the identical block, so the slide and the letter cannot drift.
    out.append((0, f"Feeder Index: {money((fci.get('published') or {}).get('value'))}"))

    weekly = slaughter.get("weekly") or {}
    beef = slaughter.get("beef_production") or {}
    out.append((0, f"Slaughter {signed_pct1(weekly.get('ytd_chg_pct'))} YTD"))
    out.append((0, f"Beef Production {signed_pct1(beef.get('ytd_chg_pct'))} YTD"))
    return out


def missing(rows_: list) -> int:
    """How many figures came back empty. The page refuses to export on this."""
    return sum(text.count(MISSING) for _, text in rows_)


def as_markdown(rows_: list) -> str:
    """The preview on the page. Four spaces per level is Streamlit's nesting."""
    return "\n".join(f"{'    ' * lvl}- {text}" for lvl, text in rows_)


# -- is the number you are about to send actually today's? --------------------

def freshness(ctx: dict, today: date = None) -> dict:
    """
    Whether the PM cutout on this slide is today's or a previous session's.

    Streamlit Community Cloud has no scheduler, so nothing can rebuild this at
    3pm on its own -- the tab is built when it is opened. That makes "which
    session am I looking at" the question the page has to answer out loud,
    because the failure it prevents is silent: the cutout for the previous
    session is a perfectly good number and looks exactly like today's. It is
    the same trap as the stale futures feed in CLAUDE.md, where every check
    asked whether data came back and it had.

    `stale` is deliberately false at a weekend and before the PM release --
    there is no session to be behind on, so saying "stale" would train the
    reader to ignore it.
    """
    today = today or date.today()
    cutout = ctx.get("cutout") or {}
    got = _as_date(cutout.get("report_date"))

    # Last weekday on or before today: Sat/Sun fall back to Friday.
    expected = today
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)

    if got is None:
        return {"stale": True, "report_date": None, "expected": expected,
                "message": "No cutout in this build — the slide has no Choice or Select."}
    if got >= expected:
        return {"stale": False, "report_date": got, "expected": expected,
                "message": f"PM cutout for {_weekday(got)} {short_date(got)} is in."}
    return {"stale": True, "report_date": got, "expected": expected,
            "message": (f"Still showing {_weekday(got)} {short_date(got)} — "
                        f"{_weekday(expected)}'s PM cutout has not landed yet. "
                        f"It is released around 3pm CT; press Fetch latest data after that.")}


# -- PowerPoint ---------------------------------------------------------------

# 16:9, which is what the deck these slides go into uses. python-pptx's default
# template is 4:3 and would letterbox the slide inside Ross's deck.
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5

# ONE FONT, ONE SIZE, ONE SPACING -- Ross's house format, specified 2026-10-06.
#
# An earlier version tapered the size by indent level (19/16/14/13) and let
# PowerPoint put extra space before a top-level bullet, which is what the deck
# does by default. Both are wrong here: the slide is read at a glance on a
# projector and an even grey block reads faster than a hierarchy of sizes.
# Every run is Aptos 16 and every paragraph carries the same space_after, so
# the gap between a sub-bullet and the next heading is identical to the gap
# between two sub-bullets.
#
# Deliberately fixed rather than autofit: a placeholder that shrinks to fit
# would give a different type size whenever the content grew by a line, and a
# slide subtly smaller than last week's is the sort of thing nobody reports
# and everybody notices.
FONT = "Aptos"
BODY_PT = 16
TITLE_PT = 36
SPACE_AFTER_PT = 4

# The one underlined row. There is exactly one heading on this slide, so
# naming it beats inferring "looks like a heading" from the text.
HEADING = "Last week's cash trade"
# Left margin per level, in inches, measured off Ross's own slide: the bullets
# sit at 0.42 / 0.92 / 1.43 / 1.93in from the sheet edge. The box starts at
# BODY_LEFT_IN and these are relative to it; the bullet hangs back into _HANG.
_MARGIN_IN = {0: 0.35, 1: 0.87, 2: 1.37, 3: 1.88}
_HANG_IN = 0.23

# Where things sit. MEASURED OFF THE REAL DECK (slide 3 of JSA Weekly Cattle
# Slides 9.28.26.pptx) rather than chosen, so a generated slide drops into the
# deck without nudging. Module constants so the test can do the collision
# arithmetic without rendering anything -- see
# test_the_text_cannot_print_through_the_logo, which exists because it once did.
TITLE_LEFT_IN = 0.18
TITLE_TOP_IN = -0.05        # the deck really does hang the title box off the top
BODY_LEFT_IN = 0.32
BODY_TOP_IN = 0.59
# Both marks are 2.67in wide in the deck; heights differ because the artwork
# does. Positioned by their own left edges, not mirrored, for the same reason.
LOGO_LEFT_IN, LOGO_TOP_IN, LOGO_W_IN = 0.07, 6.72, 2.67
AGMARKET_LEFT_IN, AGMARKET_TOP_IN, AGMARKET_W_IN = 10.49, 6.89, 2.67
LOGO_H_IN = 0.73            # kept for the clearance test; the deck's own height


def text_height_in(rows_: list) -> float:
    """
    Estimated rendered height of the body, in inches.

    An ESTIMATE on purpose -- the real height depends on font metrics
    PowerPoint resolves at open time, which nothing here can see. 1.22x the
    point size is the usual single-line spacing and is close enough to catch
    the failure that actually happened (text running 0.05in into the logo).
    The test uses it; the layout does not, so a slightly wrong constant costs
    a margin of safety rather than a wrong slide.
    """
    if not rows_:
        return 0.0
    # (n-1) gaps, not n -- the last paragraph's space_after hangs off the
    # bottom of the text and is not part of its height. Counting it
    # overstated the block by a row's worth of gap and made the clearance
    # test stricter than the slide.
    line = BODY_PT * 1.22
    return ((len(rows_) - 1) * (line + SPACE_AFTER_PT) + line) / 72.0


def _bullet(para, lvl: int):
    """
    Put a real bullet glyph and a hanging indent on the paragraph.

    SETTING para.level IS NOT ENOUGH ON A PLAIN TEXT BOX. A level only selects
    a style from the layout's list styles, and a blank-layout text box has
    none -- so the first build came out as flat, unindented, bullet-less text
    that still reported the right `level` through python-pptx. It inspected
    fine and looked wrong, which is the failure mode worth guarding.

    Writing buChar and the margins explicitly also makes the slide render the
    same in Google Slides and LibreOffice, which read a missing bullet
    definition differently from PowerPoint.
    """
    from pptx.util import Inches
    from pptx.oxml.ns import qn

    pPr = para._p.get_or_add_pPr()
    pPr.set("marL", str(Inches(_MARGIN_IN.get(lvl, 1.88)).emu))
    pPr.set("indent", str(-Inches(_HANG_IN).emu))
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    buFont = pPr.makeelement(qn("a:buFont"), {"typeface": "Arial"})
    buChar = pPr.makeelement(qn("a:buChar"), {"char": "•"})
    pPr.append(buFont)
    pPr.append(buChar)


# -- slide chrome, shared by both builders ------------------------------------

def _deck():
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W_IN)
    prs.slide_height = Inches(SLIDE_H_IN)
    return prs


def _titled_slide(prs, title: str):
    """A blank slide with the deck's title box on it.

    A BLANK LAYOUT, not a title+content placeholder. The placeholder layout
    autofits by shrinking text, so a week with one extra line would come out
    in a different size from last week's -- the sort of difference nobody
    reports and everybody notices.
    """
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    slide = prs.slides.add_slide(prs.slide_layouts[6])   # 6 == blank
    tb = slide.shapes.add_textbox(Inches(TITLE_LEFT_IN), Inches(TITLE_TOP_IN),
                                  Inches(SLIDE_W_IN - 1.2), Inches(0.83))
    run = tb.text_frame.paragraphs[0].add_run()
    run.text = title
    run.font.name = FONT
    run.font.size = Pt(TITLE_PT)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    return slide


def _marks(slide, logo=None, agmarket=None):
    """Both wordmarks at the deck's own coordinates. A missing file is skipped
    rather than allowed to cost the whole deck."""
    from pptx.util import Inches
    for art, left, top, width in (
            (logo, LOGO_LEFT_IN, LOGO_TOP_IN, LOGO_W_IN),
            (agmarket, AGMARKET_LEFT_IN, AGMARKET_TOP_IN, AGMARKET_W_IN)):
        if art is None:
            continue
        try:
            slide.shapes.add_picture(str(art), Inches(left), Inches(top),
                                     width=Inches(width))
        except Exception:
            pass


def _bullets(slide, rows_, left=None, top=None, underline=None):
    """The bulleted body, one font and one gap throughout."""
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    body = slide.shapes.add_textbox(
        Inches(BODY_LEFT_IN if left is None else left),
        Inches(BODY_TOP_IN if top is None else top),
        Inches(SLIDE_W_IN - 0.6), Inches(5.9))
    tf = body.text_frame
    tf.word_wrap = True
    first = True
    for lvl, text in rows_:
        para = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        para.level = lvl
        # SAME GAP EVERYWHERE. space_before is pinned as well as space_after:
        # the deck default puts extra space ahead of a top-level bullet, which
        # made the gap before "Choice-" larger than before "5-day average-".
        para.space_after = Pt(SPACE_AFTER_PT)
        para.space_before = Pt(0)
        _bullet(para, lvl)
        r = para.add_run()
        r.text = text
        r.font.name = FONT
        r.font.size = Pt(BODY_PT)
        r.font.underline = (text == (HEADING if underline is None else underline))
        r.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    return body


def _save(prs, out):
    # A str/Path goes to disk; anything else is a file-like (BytesIO on the
    # page, which never touches the container's filesystem).
    prs.save(str(out) if isinstance(out, (str, pathlib.Path)) else out)
    return out


def build_pptx(rows_: list, out, title: str = TITLE, logo=None, agmarket=None):
    """
    The bulleted rundown (deck slide 3), written to `out`.

    Takes ROWS, not ctx, so the writer knows nothing about where the figures
    came from and the page can memoise on the rows alone. A hidden Streamlit
    tab still executes every rerun, so without that the letter page would
    rebuild a PowerPoint file on every keystroke in the commentary boxes.

    python-pptx is imported lazily so a missing wheel breaks the download
    button and nothing else on the page.
    """
    prs = _deck()
    slide = _titled_slide(prs, title)
    _bullets(slide, rows_)
    # LOGO_TOP must clear the bottom of the text. At 0.62in high and 0.95in
    # off the floor the logo sat at 6.55in while the rows ran to 6.60in, so
    # the last line printed straight through the wordmark. It rendered
    # without complaint and only a picture showed it; tests/test_rundown.py
    # now does that arithmetic instead.
    _marks(slide, logo, agmarket)
    return _save(prs, out)


# -- slide 7: the Sterling Profit Tracker -------------------------------------
#
# Same title as the bulleted rundown -- "Cattle Market Rundown" is the section
# name in the weekly deck and sits on five of its thirteen slides, not one.
# This is the one carrying the margins and the two Sterling tables.
#
# THE TABLES ARE NATIVE, NOT PASTED IMAGES. The hand-built slide carries them
# as screenshots: ppt/media/image9.png is 603x102 stretched to 6.28in, which
# is why it looks soft on a projector. Real table shapes stay sharp at any
# size, and the numbers stay selectable so a reader can check one.

STERLING_TABLE_1 = (0.32, 3.92, 6.28, 1.06)     # left, top, width, height (in)
STERLING_TABLE_2 = (0.32, 5.19, 6.26, 0.96)
ATTRIB_POS = (0.24, 6.41, 6.27, 0.30)
TABLE_PT = 9
ATTRIB_PT = 12


def _money_acct(v) -> str:
    """Sterling's own convention: a loss is (335.15), never -335.15."""
    v = _f(v)
    if v is None:
        return MISSING
    return f"({abs(v):,.2f})" if v < 0 else f"{v:,.2f}"


def sterling_rows(data: dict) -> list:
    """
    The margins block, as (level, text) pairs.

    Mirrors the hand-built slide, with one deliberate difference: that slide
    writes "Last year-" under Feedlot and "Last Year-" under Packer. The
    capital is a slip, not a distinction, so both read "Last year-" here.
    """
    w = (data or {}).get("weekly", {})
    out = []
    for key, label, suffix in (("feedlot_margin", "Feedlot Margins-", " (Unhedged)"),
                               ("packer_margin", "Packer Margins-", "")):
        vals = w.get(key) or [None] * 4
        out.append((0, label))
        for col, v in zip(("Current", "Last week", "Last month", "Last year"), vals):
            tail = suffix if col == "Current" else ""
            out.append((1, f"{col}- {_money_acct(v)}{tail}"))
    return out


def _table(slide, pos, header, body_rows):
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    left, top, width, height = pos
    shape = slide.shapes.add_table(len(body_rows) + 1, len(header),
                                   Inches(left), Inches(top),
                                   Inches(width), Inches(height))
    tbl = shape.table
    # First column carries the labels and needs most of the width.
    tbl.columns[0].width = Inches(width * 0.40)
    for i in range(1, len(header)):
        tbl.columns[i].width = Inches(width * 0.60 / (len(header) - 1))

    def put(cell, text, bold=False, right=False):
        from pptx.enum.text import PP_ALIGN
        cell.margin_left = cell.margin_right = Inches(0.03)
        cell.margin_top = cell.margin_bottom = 0
        p = cell.text_frame.paragraphs[0]
        if right:
            p.alignment = PP_ALIGN.RIGHT
        r = p.add_run()
        r.text = text
        r.font.name = FONT
        r.font.size = Pt(TABLE_PT)
        r.font.bold = bold
        r.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    for c, text in enumerate(header):
        put(tbl.cell(0, c), text, bold=True, right=c > 0)
    for r_i, row in enumerate(body_rows, start=1):
        for c, (text, bold) in enumerate(row):
            put(tbl.cell(r_i, c), text, bold=bold, right=c > 0)
    return shape


def _col_header(data: dict) -> list:
    """
    ['September 26, 2026', 'Week Ago', 'Month Ago', 'Year Ago'].

    Built by hand rather than with strftime: the no-pad day directive is %-d
    on Linux and %#d on Windows, and this runs on both.
    """
    we = (data or {}).get("week_ending")
    first = f"{we.strftime('%B')} {we.day}, {we.year}" if we is not None else MISSING
    # Leading blank: column 0 carries the row labels, as it does in Sterling's
    # own table, so the header has FIVE cells for four columns of figures.
    return ["", first, "Week Ago", "Month Ago", "Year Ago"]


def build_sterling_pptx(data: dict, out, title: str = TITLE,
                        logo=None, agmarket=None):
    """
    Slide 7 of the weekly deck, from one parsed Profit Tracker.

    Every figure is Sterling's and is reproduced, not recomputed -- see
    letter/sterling.py for why that rule is absolute here. The attribution
    line is written unconditionally for the same reason.
    """
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    from . import sterling

    prs = _deck()
    slide = _titled_slide(prs, title)
    _bullets(slide, sterling_rows(data), underline="\x00")   # nothing underlined

    w = (data or {}).get("weekly", {})
    a = (data or {}).get("annual", {})

    def cells(key, fmt):
        vals = w.get(key) or [None] * 4
        return [(fmt(v), False) for v in vals]

    head = lambda v: MISSING if _f(v) is None else f"{_f(v):,.0f}"
    pct = lambda v: MISSING if _f(v) is None else f"{_f(v):.1f}%"

    _table(slide, STERLING_TABLE_1, _col_header(data), [
        [("Cattle Slaughter", True)] + cells("cattle_slaughter", head),
        [("     Steer & Heifer", False)] + cells("steer_heifer", head),
        [("          Fed Plant Capacity Utilization", False)] + cells("fed_capacity", pct),
        [("     Cows", False)] + cells("cows", head),
        [("          Cow Plant Capacity Utilization", False)] + cells("cow_capacity", pct),
    ])

    years = (data or {}).get("annual_years") or []
    as_of = (data or {}).get("annual_as_of")
    # Sterling's own header string where we have it -- they write "Sept."
    label = (data or {}).get("annual_label") or "Annual Projections"
    ahead = [label] + ([f"{years[0]}*"] + years[1:] if years else [MISSING] * 4)
    arow = lambda key, name: [(name, False)] + [
        (_money_acct(v), False) for v in (a.get(key) or [None] * 4)]
    _table(slide, STERLING_TABLE_2, ahead, [
        arow("cow_calf_margin", "   Cow-Calf Margin ($ / cow)"),
        arow("feedlot_margin", "   Feedlot Margin ($ / head)"),
        arow("packer_margin", "   Packer Margin ($ / head)"),
    ])

    left, top, width, height = ATTRIB_POS
    tb = slide.shapes.add_textbox(Inches(left), Inches(top),
                                  Inches(width), Inches(height))
    r = tb.text_frame.paragraphs[0].add_run()
    r.text = sterling.ATTRIBUTION
    r.font.name = FONT
    r.font.size = Pt(ATTRIB_PT)
    r.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    _marks(slide, logo, agmarket)
    return _save(prs, out)
