"""
Client-facing Cattle on Feed recap — the one-page table emailed after each
USDA release.

Everything on the page except the analyst "Guesses" column comes out of a
single USDA file:

    https://www.nass.usda.gov/Publications/Todays_Reports/reports/cofd{MM}{YY}.txt

That path is stable for prior months (verified back through cofd0826.txt), needs
no API key, and is posted at the 3pm ET release. It is used in preference to the
QuickStats API the rest of this dashboard runs on because it carries three things
QuickStats does not hand back in one call: USDA's own rounded "percent of
previous year" columns, the placement weight-class breakdown, and the year-ago
basis exactly as USDA restated it.

The Year-Ago column is the same three ratios recomputed from LAST year's file for
the same month — what this report looked like a year ago, not the year-ago head
count.
"""
import base64
import functools
import re
from datetime import date
from pathlib import Path

import requests

REPORT_URL = "https://www.nass.usda.gov/Publications/Todays_Reports/reports/cofd{mm:02d}{yy:02d}.txt"

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
              "Oct", "Nov", "Dec"]
# Marketing windows are written AP-style on the client page — the long months
# abbreviate, March through July are spelled out ("Feb/March", not "Feb/Mar").
MONTH_DISPLAY = ["Jan", "Feb", "March", "April", "May", "June", "July", "Aug",
                 "Sept", "Oct", "Nov", "Dec"]

# The five states carried on the client page, in that page's order.
DEFAULT_STATES = [("IA", "Iowa"), ("NE", "Nebraska"), ("KS", "Kansas"),
                  ("TX", "Texas"), ("CO", "Colorado")]

# (label, regex, months-out low, months-out high).
# The marketing window is a fixed offset from the PLACEMENT month, not a USDA
# figure: lighter cattle sit on feed longer. Checked against the Sep 2026 page —
# August placements under 600# market June/July, 1,000+# market Dec/Jan.
WEIGHT_CLASSES = [
    ("Under 600#", r"less than 600 pounds were ([\d,]+) head", 10, 11),
    ("600-699#", r"600-699 pounds were ([\d,]+) head", 8, 9),
    ("700-799#", r"700-799 pounds were ([\d,]+) head", 7, 8),
    ("800-899#", r"800-899 pounds were ([\d,]+) head", 6, 7),
    ("900-999#", r"900-999 pounds were ([\d,]+) head", 5, 6),
    ("1,000+ #", r"1,000 pounds and greater were ([\d,]+) head", 4, 5),
]

_NUM = r"([\d,]+)"
# "Iowa .............:   690   670   670   97   100" — the two state tables share
# this shape: prior-year, prior-month, current, % of prev year, % of prev month.
_STATE_ROW = re.compile(
    r"^([A-Za-z][A-Za-z .]*?)\s*\.{2,}:\s*" + _NUM + r"\s+" + _NUM + r"\s+" + _NUM
    + r"\s+(\d+)\s+(\d+)\s*$")
# "On feed September 1 ....:   11,080   11,163   101"
_US_ROW = re.compile(r"^(.+?)\s*\.{2,}:\s*" + _NUM + r"\s+" + _NUM + r"\s+(\d+)\s*$")

_ONFEED_TABLE = "Cattle on Feed Inventory on 1,000+ Capacity Feedlots by Month"
_PLACED_TABLE = "Cattle Placed on Feed on 1,000+ Capacity Feedlots by Month"
_MKT_TABLE    = "Cattle Marketed on 1,000+ Capacity Feedlots by Month"
_OTHER_TABLE  = "Cattle Other Disappearance on 1,000+ Capacity Feedlots by Month"
_CLASS_TABLE  = "Cattle on Feed by Class on 1,000+ Capacity Feedlots by Quarter"
_US_TABLE = "1,000+ Capacity Feedlots - United States:"

# "Kansas .....:  1,460  1,390  1,430   950   910   950" -- the quarterly class
# table is SIX head columns, steers for three periods then heifers for the same
# three, and no percentages. It matches neither _STATE_ROW (which ends in two
# percents) nor _US_ROW, which is why _table_block has to be told the shape.
_CLASS_ROW = re.compile(
    r"^([A-Za-z][A-Za-z .]*?)\s*\.{2,}:\s*" + r"\s+".join([_NUM] * 6) + r"\s*$")

# series -> (table marker, month offset of the table's CURRENT column from the
# report month). THE OFFSET IS THE WHOLE CORRECTNESS OF THIS. The October report
# carries the OCTOBER 1 inventory but SEPTEMBER placements, marketings and other
# disappearance, and the tables say so in their own headers:
#
#   Inventory : October 1, 2025 | September 1, 2026 | October 1, 2026
#   Marketed  : During September 2025 | During August 2026 | During September 2026
#
# Give the flows offset 0 and every figure lands a month late, on a page where
# a month-late placement number is entirely plausible.
RELEASED_TABLES = {
    "inventory":  (_ONFEED_TABLE,  0),
    "placements": (_PLACED_TABLE, -1),
    "marketings": (_MKT_TABLE,    -1),
    "other":      (_OTHER_TABLE,  -1),
}


def _int(s):
    return int(s.replace(",", ""))


def report_url(year: int, month: int) -> str:
    return REPORT_URL.format(mm=month, yy=year % 100)


def fetch_report(year: int, month: int) -> str:
    """Raw report text, or "" when USDA has not posted that month."""
    try:
        r = requests.get(report_url(year, month), timeout=30)
    except requests.RequestException:
        return ""
    # NASS serves an HTML error page rather than a 404 status for some misses.
    if r.status_code != 200 or "Cattle on Feed" not in r.text[:400]:
        return ""
    return r.text


def latest_report(today: date = None):
    """(year, month, text) of the most recent posted report, searching back a year.

    The report published in month M carries the M/1 inventory and M-1 placements,
    so the filename month is the publication month.
    """
    today = today or date.today()
    y, m = today.year, today.month
    for _ in range(13):
        text = fetch_report(y, m)
        if text:
            return y, m, text
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return None, None, ""


def _table_block(text: str, marker: str, row_re=None) -> list:
    """Data rows of the first table whose header contains `marker`.

    `row_re` overrides the default state/US shapes for a table that prints
    something else -- the quarterly class table is six head columns with no
    percentages, and matches neither.
    """
    lines = text.splitlines()
    try:
        head = next(i for i, ln in enumerate(lines) if marker in ln)
    except StopIteration:
        return []
    out, seen_data = [], False
    for ln in lines[head:head + 60]:
        if (row_re.match(ln) if row_re else
                (_STATE_ROW.match(ln) or _US_ROW.match(ln))):
            out.append(ln)
            seen_data = True
        elif seen_data and ln.startswith("---"):
            break
    return out


def parse_release_date(text: str):
    m = re.search(r"Released\s+(\w+)\s+(\d{1,2}),\s+(\d{4})", text)
    if not m or m.group(1) not in MONTH_NAMES:
        return None
    return date(int(m.group(3)), MONTH_NAMES.index(m.group(1)) + 1, int(m.group(2)))


def parse_us(text: str) -> dict:
    """{key: (prior_year_head, current_head)} in 1,000 head, for the headline three.

    The first US table holds five rows; the opening "On feed <prev month> 1" and
    the closing "On feed <report month> 1" both match the same pattern, and it is
    the LAST one that is the headline inventory.
    """
    rows = _table_block(text, _US_TABLE)
    out, on_feed = {}, None
    for ln in rows:
        m = _US_ROW.match(ln)
        if not m:
            continue
        label, prev, curr = m.group(1).strip(), _int(m.group(2)), _int(m.group(3))
        if label.startswith("On feed"):
            on_feed = (prev, curr)
        elif label.startswith("Placed on feed"):
            out["placed"] = (prev, curr)
        elif label.startswith("Fed cattle marketed"):
            out["marketed"] = (prev, curr)
    if on_feed:
        out["on_feed"] = on_feed
    return out


_CLASS_MONTH = re.compile(r"([A-Z][a-z]{2})\s+1,")


def _class_periods(text: str):
    """The six (year, month) the class table's OWN HEADER names, or None.

    **USDA DATES THIS TABLE BY THE CALENDAR QUARTER, NOT BY THE REPORT**, and
    the two come apart whenever a quarterly report slips. It has happened: the
    October 2025 report was never published, so the **November 2025** report
    carried the Oct 1 class split — its class header reads
    `Oct 1, 2024 | Jul 1, 2025 | Oct 1, 2025` while the monthly tables in the
    SAME FILE read November. Deriving these from the report month filed all
    seventy-eight class figures a month late, on quarters the series has never
    held a value for, and the Heifers tile would have shown 37.2% dated Nov
    2025 against a true 38.1% dated Oct 1.

    So the header is read rather than the dates computed. It is what USDA
    actually says, and it cannot drift from the rows beneath it.

    Returns None when the header cannot be read, and `released_rows` then skips
    the class block entirely — **keeping the cached figures is the conservative
    failure**, where guessing the periods is the one that puts a real number on
    a date USDA never published.
    """
    lines = text.splitlines()
    try:
        head = next(i for i, ln in enumerate(lines) if _CLASS_TABLE in ln)
    except StopIteration:
        return None
    for i in range(head, min(head + 20, len(lines) - 1)):
        months = _CLASS_MONTH.findall(lines[i])
        if len(months) < 6:
            continue
        years = re.findall(r"\b((?:19|20)\d{2})\b", lines[i + 1])
        if len(years) < 6:
            continue
        out = []
        for mon, yr in zip(months[:6], years[:6]):
            if mon not in MONTH_ABBR:
                return None
            out.append((int(yr), MONTH_ABBR.index(mon) + 1))
        return out
    return None


def _shift(year: int, month: int, delta: int) -> tuple:
    """(year, month) `delta` months from (year, month)."""
    i = year * 12 + (month - 1) + delta
    return i // 12, i % 12 + 1


def released_rows(text: str, year: int, month: int) -> list:
    """[{series, state_name, year, month, value}] of HEAD, from the release text.

    This is what lets the dashboard move at the release rather than waiting on
    QuickStats and then on the cache job behind it. Each state row carries three
    periods — a year before the current one, the month before it, and the
    current one — so one parse covers the new month AND the restatement of the
    month before it, which USDA makes in every release.

    **STATE NAMES ARE RETURNED AS PRINTED, not as abbreviations.** app.py owns
    STATE_NAMES and maps them; a second copy of that map here is the
    snowflake_db-times-five problem in miniature, and this module already
    carries a PARTIAL one in DEFAULT_STATES that covers five states of thirteen.

    **Values are multiplied to HEAD.** The tables print "1,000 head" and
    QuickStats serves head, so an un-multiplied overlay is out by a factor of a
    thousand — on a page where every figure is already in the millions, that
    renders as a collapse rather than as an obvious unit error.

    A row USDA suppressed as "(D)" simply fails _STATE_ROW and is skipped, which
    leaves the cached figure in place rather than blanking it.
    """
    out = []
    for series, (marker, offset) in RELEASED_TABLES.items():
        cy, cm = _shift(year, month, offset)
        periods = [(_shift(cy, cm, -12), 0), (_shift(cy, cm, -1), 1), ((cy, cm), 2)]
        for ln in _table_block(text, marker):
            m = _STATE_ROW.match(ln)
            if not m:
                continue
            name = m.group(1).strip()
            for (py, pm), col in periods:
                out.append({"series": series, "state_name": name,
                            "year": py, "month": pm,
                            "value": _int(m.group(2 + col)) * 1000})

    # The quarterly steer/heifer split. Its periods are READ FROM ITS OWN
    # HEADER, never derived from the report month — see _class_periods for the
    # November 2025 report that proves why. `year` and `month` are deliberately
    # unused here, and that is the fix rather than an oversight.
    #
    # No month test either: the eight non-quarterly reports carry no such table,
    # _class_periods returns None, and this block does not run.
    periods = _class_periods(text)
    if periods:
        for ln in _table_block(text, _CLASS_TABLE, _CLASS_ROW):
            m = _CLASS_ROW.match(ln)
            if not m:
                continue
            name = m.group(1).strip()
            for series, base in (("steers", 0), ("heifers", 3)):
                for col in (0, 1, 2):
                    py, pm = periods[base + col]
                    out.append({"series": series, "state_name": name,
                                "year": py, "month": pm,
                                "value": _int(m.group(2 + base + col)) * 1000})
    return out


def parse_state_pct(text: str) -> dict:
    """{'on_feed': {state: pct}, 'placed': {state: pct}} — USDA's own % of prev year."""
    out = {}
    for key, marker in (("on_feed", _ONFEED_TABLE), ("placed", _PLACED_TABLE)):
        vals = {}
        for ln in _table_block(text, marker):
            m = _STATE_ROW.match(ln)
            if m:
                vals[m.group(1).strip()] = int(m.group(5))
        out[key] = vals
    return out


def parse_weight_classes(text: str) -> list:
    """[(label, head, lo, hi)] from the narrative paragraph, which wraps lines."""
    flat = " ".join(text.split())
    out = []
    for label, pattern, lo, hi in WEIGHT_CLASSES:
        m = re.search(pattern, flat)
        out.append((label, _int(m.group(1)) if m else None, lo, hi))
    return out


def pct(curr, prev):
    """Percent of previous year, to the nearest tenth of the head counts.

    Deliberately NOT USDA's rounded whole-number percent column, and
    deliberately not matched to the legacy Excel sheet. For September 2026 that
    sheet read On-Feed 100.8 and 99 where 11,163/11,080 and 11,080/11,198 give
    100.7 and 98.9; its Placed and Marketed cells agree with this calculation to
    the decimal, so only the two On-Feed cells ever differed. Confirmed
    2026-09-22 that the computed figure is the one to show. Do not round these
    back to match the old sheet.

    The state block is a different matter — those percentages are read straight
    from USDA's published whole-number column and are not recomputed here.
    """
    return round(curr / prev * 100, 1) if prev else None


def marketing_window(place_month: int, lo: int, hi: int) -> str:
    """'June/July' — the months lo and hi out from the placement month."""
    a = (place_month - 1 + lo) % 12
    b = (place_month - 1 + hi) % 12
    return f"{MONTH_DISPLAY[a]}/{MONTH_DISPLAY[b]}"


def build_recap(year: int, month: int, text: str, prior_text: str = None,
                states=None) -> dict:
    """Everything the page renders, except the analyst guesses."""
    states = states or DEFAULT_STATES
    us = parse_us(text)
    # Placements and marketings are for the month BEFORE the report month.
    pm_year, pm_month = (year, month - 1) if month > 1 else (year - 1, 12)

    actual = {k: pct(v[1], v[0]) for k, v in us.items()}

    year_ago = {}
    if prior_text:
        year_ago = {k: pct(v[1], v[0]) for k, v in parse_us(prior_text).items()}

    sp = parse_state_pct(text)
    state_rows = [(abbr, sp["on_feed"].get(full), sp["placed"].get(full))
                  for abbr, full in states]

    wc = [(label, head, marketing_window(pm_month, lo, hi))
          for label, head, lo, hi in parse_weight_classes(text)]
    total = us.get("placed", (None, None))[1]

    return {
        "year": year,
        "month": month,
        "title": f"{MONTH_ABBR[month - 1]} COF Report",
        "release_date": parse_release_date(text),
        "placement_month": f"{MONTH_NAMES[pm_month - 1]} {pm_year}",
        "us_head": us,
        "actual": actual,
        "year_ago": year_ago,
        "states": state_rows,
        "weight_classes": wc,
        "placed_total": total * 1000 if total else None,
    }


# ── Rendering ────────────────────────────────────────────────────────────────
# Drawn as one Plotly figure of positioned annotations rather than HTML so that
# what the tab shows and what the PNG/PDF button hands over are the same object.
# kaleido is already pinned at 0.2.1 in requirements.txt for exactly this.

# 740, not 690: at 690 the page had no bottom margin at all. The weight-class
# block ends on its Total row around y=644 and the source line sat 12px under
# it, reading as a fourth column entry rather than a footer -- Ross, 2026-10-23,
# looking at the HubSpot image: "should sit further down in the left hand corner
# so it's not right next to the numbers". The extra 50px is bottom margin only;
# every annotation is positioned in pixels FROM THE TOP, so nothing above moves.
FIG_W, FIG_H = 520, 740
INK = "#000000"    # title, column headers
DATA = "#000000"   # Ross, 2026-10-23: black. Was #963634, the maroon this
                   # page carried from the hand-built Excel original.
MUTED = "#9a9a9a"
FONT = "Calibri, Carlito, Arial, sans-serif"

# ── Letterhead ───────────────────────────────────────────────────────────────
# The daily emails carry a wordmark top-right, the 50-years roundel faint behind
# the text, and a hairline sage frame. This page is the same company writing and
# Ross sends it to the same clients, so it carries the same three.
#
# letter/render.py IS THE AUTHORITY, and these numbers are its CSS restated
# rather than imported — that module builds an 8.5x11in HTML document and this
# is a 520x690 Plotly figure, so there is nothing to share but the geometry.
# Each value below is a FRACTION OF THE PAGE, multiplied back out at draw time,
# which is what makes the two look alike at different sizes:
#
#   .wm            width 4.4in of an 8.5in page = 0.52; top 46%; opacity 0.07
#   .masthead img  height 0.34in of an 11in page = 0.031, right-aligned
#   .frame         config.FRAME #5e7164 at config.FRAME_WIDTH 0.75pt
#
# FRAME_INSET IS NOT THE LETTER'S 0.52in, and copying that literally is the
# mistake to avoid. There the frame sits 0.33in OUTSIDE a text block beginning
# at 0.85in; here the text begins at 34px, which is 6.5% of 520 and already
# tighter than 0.52in would be — so the frame is placed the equivalent 0.33in
# outside THIS page's text instead. Taken literally it lands 2px off the first
# column and reads as a box drawn round the table.
BRAND_SAGE    = "#5e7164"   # letter/config.FRAME
FRAME_PT      = 0.75        # letter/config.FRAME_WIDTH
FRAME_INSET   = 14          # figure px from the paper edge, every side
WM_WIDTH_FRAC = 0.52        # .wm width, as a fraction of page width
WM_CENTRE_Y   = 0.46        # .wm top
WM_OPACITY    = 0.07        # .wm opacity
LOGO_H_FRAC   = 0.031       # .masthead img height, as a fraction of page height


def _png_size(data: bytes) -> tuple:
    """(width, height) from a PNG's IHDR, which is always the first chunk.

    Read from the FILE rather than written down here on purpose: the aspect
    ratio is the one number that must track the asset, and a constant that
    silently stops matching stretches the wordmark instead of failing. Doing it
    from the header costs eight bytes of slicing and adds no dependency —
    Pillow is not in requirements.txt and this module must not be the thing
    that puts it there.
    """
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


@functools.lru_cache(maxsize=4)
def _asset(name: str):
    """(data-uri, aspect) for assets/<name>, or ("", 0) when it is missing.

    EMBEDDED, NOT LINKED, for the reason letter/render._asset_uri gives: the
    figure is serialised to JSON, cached, and handed to kaleido in a separate
    process, so a relative path would resolve against whatever directory that
    process happens to be in. A data URI is part of the figure.

    Missing returns empty and the page draws unbranded rather than raising —
    letterhead is presentation, and losing it must not cost the numbers.
    """
    path = Path(__file__).resolve().parents[2] / "assets" / name
    try:
        raw = path.read_bytes()
    except OSError:
        return "", 0.0
    w, h = _png_size(raw)
    if not h:
        return "", 0.0
    return ("data:image/png;base64," + base64.b64encode(raw).decode("ascii"), w / h)


def _box(px_w: float, aspect: float) -> tuple:
    """(sizex, sizey) in PAPER units for an image px_w figure-pixels wide.

    Paper units are fractions of the figure's own width and height, which are
    different lengths — so passing one fraction for both is what stretches an
    image, and the asset's aspect has to be divided back out through FIG_W/FIG_H.
    """
    return px_w / FIG_W, (px_w / aspect) / FIG_H


def _letterhead() -> tuple:
    """(images, shapes) for the wordmark, the watermark and the frame."""
    images, shapes = [], []

    mark, mark_aspect = _asset("jsa-50-years.png")
    if mark:
        sx, sy = _box(WM_WIDTH_FRAC * FIG_W, mark_aspect)
        images.append(dict(
            source=mark, xref="paper", yref="paper",
            x=0.5, y=1 - WM_CENTRE_Y, sizex=sx, sizey=sy,
            xanchor="center", yanchor="middle",
            opacity=WM_OPACITY, layer="below",
        ))

    logo, logo_aspect = _asset("logo-full.png")
    if logo:
        sx, sy = _box(LOGO_H_FRAC * FIG_H * logo_aspect, logo_aspect)
        images.append(dict(
            source=logo, xref="paper", yref="paper",
            # Right edge on the last column rule, baseline-centred on the title
            # row — the masthead's flex row, which puts the title left and the
            # wordmark right, expressed in the only terms a figure has.
            x=C3 / FIG_W, y=1 - 30 / FIG_H, sizex=sx, sizey=sy,
            xanchor="right", yanchor="middle",
            opacity=1, layer="above",
        ))

    shapes.append(dict(
        type="rect", xref="paper", yref="paper",
        x0=FRAME_INSET / FIG_W, x1=1 - FRAME_INSET / FIG_W,
        y0=FRAME_INSET / FIG_H, y1=1 - FRAME_INSET / FIG_H,
        line=dict(color=BRAND_SAGE, width=FRAME_PT), fillcolor="rgba(0,0,0,0)",
        layer="below",
    ))
    return images, shapes

# Column rules, in figure pixels. Labels right-align into LBL; the three value
# columns right-align on their own rule so the decimal points line up.
LBL, C1, C2, C3 = 150, 252, 354, 464


def _ann(x, y, text, color=INK, size=12, align="right", bold=False):
    return dict(
        x=x / FIG_W, y=1 - y / FIG_H, xref="paper", yref="paper",
        text=f"<b>{text}</b>" if bold else str(text),
        showarrow=False, xanchor=align, yanchor="middle",
        font=dict(family=FONT, size=size, color=color),
    )


def _num(v, dec=1):
    if v is None:
        return "—"
    return f"{v:.1f}" if dec else f"{v:g}"


def build_figure(recap: dict, guesses: dict = None, footer: bool = True,
                 guess_source: str = ""):
    """The client page as a single figure. `guesses` is {key: float} or None."""
    import plotly.graph_objects as go

    guesses = guesses or {}
    actual, year_ago = recap["actual"], recap["year_ago"]
    ann = [_ann(34, 30, recap["title"], size=14, bold=True, align="left")]

    for x, lab in ((C1, "Actual"), (C2, "Guesses"), (C3, "Year-Ago")):
        ann.append(_ann(x, 80, lab, size=11))
    y = 110
    for key, lab in (("on_feed", "On-Feed"), ("placed", "Placed"),
                     ("marketed", "Marketed")):
        ann.append(_ann(LBL, y, lab, color=DATA))
        ann.append(_ann(C1, y, _num(actual.get(key)), color=DATA))
        ann.append(_ann(C2, y, _num(guesses.get(key)), color=DATA))
        ann.append(_ann(C3, y, _num(year_ago.get(key)), color=DATA))
        y += 26

    # AN EMPTY YEAR-AGO COLUMN IS AN ANSWER, NOT A HOLE, and three bare em-dashes
    # on a client page read as a broken fetch. It happens when USDA published no
    # report that month: October 2025 is absent from BOTH the Todays_Reports
    # archive (cofd1025.txt 404s while cofd0925 and cofd1125 serve) and from
    # ESMIS, whose own date filter steps straight from Sep 2025 to Nov 2025.
    # The line says what is missing and does NOT say why -- a cause nobody
    # verified is worth less than none.
    if not any(year_ago.get(k) is not None
               for k in ("on_feed", "placed", "marketed")):
        # CENTRED ON THE YEAR-AGO COLUMN, not right-aligned on its rule. Right
        # aligned at C3 the line is far wider than the column it explains, so it
        # hangs left and sits under Guesses -- Ross, 2026-10-23: "needs moved
        # over and centered better. looks weird where it's at". C3-14 is about
        # the optical centre of the column: its values right-align at C3 and its
        # header runs ~45px left of it. Shortened to suit -- "published" put the
        # line back over Guesses, and the em-dashes beside it already say the
        # figures are absent rather than zero.
        ann.append(_ann(C3 - 14, y - 8,
                        f"No {MONTH_ABBR[recap['month'] - 1]} {recap['year'] - 1} report",
                        color=MUTED, size=8, align="center"))

    ann.append(_ann(34, 222, "Percent of Last Year", align="left"))
    for x, lab in ((C1, "On-Feed"), (C2, "Placed")):
        ann.append(_ann(x, 258, lab, size=11))
    y = 288
    for abbr, on_feed, placed in recap["states"]:
        ann.append(_ann(LBL, y, abbr, color=DATA))
        ann.append(_ann(C1, y, _num(on_feed, 0), color=DATA))
        ann.append(_ann(C2, y, _num(placed, 0), color=DATA))
        y += 26

    ann.append(_ann(34, 456, "Weight Classes Placed", align="left"))
    # Ross, 2026-10-23: the head column had no heading at all, so the only thing
    # naming it was the "Total" row at the foot of it. Right-aligned on 270 like
    # the figures beneath it -- the two headings either side are left-aligned on
    # their own text, and matching THEM would hang this one off the wrong edge
    # of the column it labels.
    ann.append(_ann(270, 456, "Total Head", align="right"))
    ann.append(_ann(300, 456, "Marketing Window", align="left"))
    y = 488
    for lab, head, window in recap["weight_classes"]:
        ann.append(_ann(LBL, y, lab, color=DATA))
        ann.append(_ann(270, y, f"{head:,}" if head else "—", color=DATA))
        ann.append(_ann(300, y, window, color=DATA, align="left"))
        y += 26
    ann.append(_ann(LBL, y, "Total", color=DATA))
    total = recap["placed_total"]
    ann.append(_ann(270, y, f"{total:,}" if total else "—", color=DATA))

    if footer:
        released = recap["release_date"]
        bits = ["USDA NASS Cattle on Feed"]
        if released:
            bits.append(f"Released {released:%b %d, %Y}")
        if guess_source:
            bits.append(f"Guesses: {guess_source}")
        # Bottom-left corner: 14px above the frame line and ~68px below the
        # Total row, so it reads as provenance on stationery rather than as
        # another figure in the table. At FIG_H-20 it sat INSIDE the frame.
        ann.append(_ann(34, FIG_H - 28, "  ·  ".join(bits), color=MUTED,
                        size=8, align="left"))

    brand_images, brand_shapes = _letterhead()

    fig = go.Figure()
    fig.update_layout(
        width=FIG_W, height=FIG_H, annotations=ann,
        images=brand_images, shapes=brand_shapes,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(visible=False, range=[0, 1], fixedrange=True),
        yaxis=dict(visible=False, range=[0, 1], fixedrange=True),
    )
    return fig
