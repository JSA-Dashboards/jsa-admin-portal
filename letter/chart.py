"""
The chart of the day, drawn as inline SVG.

WHY SVG AND NOT A PLOTTING LIBRARY. plotly is installed and kaleido is pinned to
0.2.1, and that pair cannot export an image on Ross's desktop: plotly 7 requires
kaleido>=1, and requirements.txt pins 0.2.1 with a note that newer combinations
"silently break Cloud PNG export" for the dashboards. The letter is built on the
desktop, so the one machine that matters is the one where the export is broken,
and un-pinning kaleido to fix the letter would risk six dashboards.

Inline SVG has none of that: no dependency, nothing to install, the same output
on the desktop and the deployed app, and it stays sharp in the PDF at any zoom
because it is vector rather than a rasterised PNG.

NOTHING HERE FETCHES. It is handed a series and returns markup, the same
division render.py keeps -- the data comes from build.gather, which already
holds a Massive client, and a test asserts the renderer cannot reach a fetcher.

WHERE IT GOES, AND THE CONSTRAINT THAT SHAPED IT. Bottom right of the morning
brief, beside the signature block. That page was measured before any of this was
written: 8.28in of content in a 9.2in printable area, but the band to the right
of the signature is 1.89in tall and 4.97in wide and completely empty. A chart
that floats into THAT costs no vertical space at all, which is the only way this
could be added without spending the one-page budget CLAUDE.md calls the product.
Hence the size below. Make it taller than the band and the letter runs to two
pages -- there is a test.
"""
from __future__ import annotations

from datetime import date

from . import config

# Sized to the empty band beside the signature, with room to spare. 96 user
# units per inch, so the viewBox is also the size in CSS pixels.
IN = 96
WIDTH_IN, HEIGHT_IN = 3.10, 1.62

# Plot insets. Left for the y labels, bottom for the month labels, right for the
# endpoint value -- which is a label that must not be clipped, so the space is
# reserved rather than hoped for.
PAD_L, PAD_R, PAD_T, PAD_B = 30, 34, 15, 13

# One shade off the surface, hairline, solid. Never dashed -- a dashed grid
# reads as a projection or a threshold when it is just a grid.
GRID = "#d8d8d8"
AXIS_TEXT = "#5a5a5a"
# The letter is black on white and is often printed that way. The line is ink,
# not an accent colour that would come out as mid-grey mush on a mono printer.
LINE = "#1a1a1a"

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _as_date(v):
    """
    A date from either a date or its ISO string, or None.

    THE CACHE ROUND TRIP IS THE NORMAL PATH, not an edge case. build.py writes
    ctx to JSON between the fetch run and the `--no-fetch` re-render, and JSON
    has no date type -- so the second run, the one that actually produces the
    PDF, hands this module strings. Slicing those for a month label printed
    "202". Same shape of bug as the moving averages coming back under string
    keys, recorded in render.technicals_block.
    """
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _nice_bounds(lo: float, hi: float):
    """
    Axis bounds that HUG THE DATA, rounded to a readable unit.

    The obvious approach -- pick a step and floor to a multiple of it from zero
    -- is wrong for a price series that lives nowhere near zero. Feeders ranging
    318.98 to 371.38 got an axis of 300 to 400 on the first attempt: the line
    then used barely half the plot height and a 52-point slide read as a gentle
    drift. A chart that understates the move it is there to show is worse than
    no chart.

    So the bounds are the data padded a little and rounded outward to a unit
    scaled to the span, and the three ticks are placed within them. The numbers
    still read as numbers -- 310, 345, 380 -- without the axis running to a
    round hundred nobody asked for.
    """
    if hi <= lo:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    pad = span * 0.08

    # Half an order of magnitude below the span: 5 for a ~50 point range, 50 for
    # a ~500 point one. Keeps the rounding visible but never coarse.
    import math
    unit = (10 ** math.floor(math.log10(span))) / 2 if span > 0 else 1

    lo_r = math.floor((lo - pad) / unit) * unit
    hi_r = math.ceil((hi + pad) / unit) * unit
    mid = round(((lo_r + hi_r) / 2) / unit) * unit
    ticks = sorted({round(v, 4) for v in (lo_r, mid, hi_r)})
    return lo_r, hi_r, ticks


def _score(text: str, entry: dict) -> float:
    """
    How much a piece of text is about one market.

    WEIGHTED BY SPECIFICITY. A hit on "cost of gain" says far more than a hit on
    "corn", so a phrase scores its word count. Without this every single-word hit
    tied and the tie-break -- the rotation -- decided, which is how "Corn basis
    firms as harvest rolls" drew a Live Cattle chart.
    """
    low = (text or "").lower()
    return sum(low.count(w) * len(w.split()) for w in entry["words"])


def source_weight(source: str) -> float:
    """
    How much one outlet's headline counts. See config.CHART_SOURCE_WEIGHTS.

    Substring match, so an outlet nobody has seen before lands on the default
    instead of needing a config entry the day it first appears.
    """
    low = (source or "").lower()
    for marker, weight in config.CHART_SOURCE_WEIGHTS.items():
        if marker in low:
            return weight
    if any(m in low for m in config.CHART_TRADE_SOURCES):
        return config.CHART_TRADE_WEIGHT
    return config.CHART_DEFAULT_SOURCE_WEIGHT


def pick(issue: date, text: str = "", candidates: list = None,
         movers: dict = None, pool: list = None) -> tuple:
    """
    Which chart this morning gets, and why. Returns (entry, reason).

    FOUR TIERS, IN ORDER OF HOW MUCH EACH ONE KNOWS:

      1. What Ross wrote. If the headlines he typed talk about corn, the chart is
         corn. The human already said what the morning is about; nothing
         computed beats that.
      2. What the day's headlines are about -- the candidate list the panel
         already fetched, weighted by source so USDA's own cash-trade narrative
         outranks a general newsroom that covered cattle once. This is what
         aims the chart before a word has been typed.
      3. What actually moved. Nothing in the text either way, so the most
         applicable chart is the market that did something -- scored as a
         percentage so 8 cents of corn and 40 S&P points compare.
      4. A rotation. Nothing to go on at all: a cycle that shows every chart once
         before repeating, shuffled per cycle so it is not a fixed weekly rota.

    NOTHING HERE FETCHES ANYTHING, and tier 2 must never cause a fetch: the
    candidate list costs several HTTP calls and is only passed in when the caller
    already has it. A CLI build that never asked for headlines simply skips to
    tier 3, which is why the reason string always names the tier that fired.

    DETERMINISTIC, NEVER RANDOM AT RENDER TIME. A letter is built twice -- once
    to fetch, once with --no-fetch to make the PDF -- and an actually-random pick
    would put a different chart in the PDF than the one that was previewed.
    """
    pool = pool or config.CHART_POOL
    order, pos = _rotation(issue, len(pool))

    def _best(scores):
        ranked = [(scores[i], -order.index(i), e) for i, e in enumerate(pool)]
        return max(ranked, key=lambda t: (t[0], t[1]))

    if text:
        best = _best([_score(text, e) for e in pool])
        if best[0] > 0:
            low = text.lower()
            hits = [w for w in best[2]["words"] if w in low]
            return best[2], f"matched {', '.join(repr(w) for w in hits[:2])} in your text"

    if candidates:
        totals, top_title = [0.0] * len(pool), {}
        for item in candidates:
            title = item.get("title") or ""
            weight = source_weight(item.get("source"))
            for i, e in enumerate(pool):
                s = _score(title, e) * weight
                if s <= 0:
                    continue
                totals[i] += s
                if s > top_title.get(i, (0, "", ""))[0]:
                    top_title[i] = (s, title, item.get("source") or "")
        best = _best(totals)
        if best[0] > 0:
            i = pool.index(best[2])
            _, title, src = top_title.get(i, (0, "", ""))
            short = (title[:52] + "…") if len(title) > 53 else title
            return best[2], f"the day's headlines — {src}: “{short}”"

    if movers:
        ranked = [(abs(v), e) for e in pool
                  for v in [movers.get(e["key"])] if v is not None]
        if ranked:
            top = max(ranked, key=lambda t: t[0])
            return top[1], f"biggest mover ({top[0] * 100:.1f}%)"

    return pool[order[pos]], "rotation"


def _rotation(issue: date, n: int):
    """
    A deterministic cycle that shows every chart once before repeating.

    A plain `ordinal % n` is a fixed rota -- with five charts, every Monday gets
    the same one. Shuffling the order per cycle keeps the no-repeat property and
    loses the pattern, and seeding on the cycle number keeps it reproducible.
    """
    import random
    cycle, pos = divmod(issue.toordinal(), n)
    order = list(range(n))
    random.Random(cycle).shuffle(order)
    # A chart landing last in one cycle and first in the next is the only way
    # this repeats two days running. Cheap to avoid.
    #
    # NOT GATED ON pos, AND THAT WAS A BUG. The swap used to fire only when
    # pos == 0, so day 0 of a cycle got a different permutation from days 1..n
    # of the same cycle -- the order stopped being a function of the cycle
    # alone, and the day-0 chart could duplicate the day-1 chart. Five entries
    # never happened to trigger it; adding a sixth did, on the first cycle
    # tested. The order must depend on `cycle` and nothing else.
    prev = list(range(n))
    random.Random(cycle - 1).shuffle(prev)
    if n > 1 and order[0] == prev[-1]:
        order[0], order[1] = order[1], order[0]
    return order, pos


def _fmt(v: float, style: str = "decimal") -> str:
    """
    The endpoint value, written the way the letter writes that market.

    Corn is quoted in eighths in the bullets above -- 529'4 -- so a chart of the
    same contract labelled 529.25 on the same page would look like a different
    number. render.eighths is imported lazily because render imports this module
    at load time, and duplicating the formatter would be one more copy to drift.
    """
    if style == "eighths":
        from . import render
        return render.eighths(v)
    return f"{v:,.2f}"


COMPARE_LINE = "#9aa3a8"      # the average, behind and quieter than this year


def line_chart(dates: list, values: list, title: str = "", style: str = "decimal",
               width_in: float = WIDTH_IN, height_in: float = HEIGHT_IN,
               compare: list = None, compare_label: str = "5-yr avg") -> str:
    """
    One series over time, as an <svg> string, optionally against a second.
    Returns "" if there is nothing worth drawing -- two points is not a chart.

    ONE SERIES, NO LEGEND: the title says what is plotted, and a one-swatch
    legend box would only restate it and cost space that is not available here.
    Only the endpoint is labelled; a number on every point is unreadable at this
    size and goes unread at any size.

    TWO SERIES, STILL NO LEGEND BOX, because 3.1 x 1.75 inches does not have
    room for one. Identity is carried three ways instead, none of them colour
    alone -- which matters on a letter that is printed, photocopied and read by
    people who do not all see colour the same way:

        this year    solid, full weight, endpoint dot, the value spelled out
        comparison   dashed, thinner, muted, labelled at its own end

    `compare` must be index-aligned with `values` -- same length, same x
    positions, Nones allowed where a year has no observation. Aligning by
    position rather than by date is deliberate: a seasonal chart puts this
    year's week 14 against the average of week 14, and the calendar dates
    differ by definition.
    """
    pts = [(d, float(v)) for d, v in zip(dates or [], values or []) if v is not None]
    if len(pts) < 5:
        return ""

    # Kept as an index-aligned list against the ORIGINAL values, then filtered
    # the same way, so a None in either series cannot shift the two apart.
    cmp_pts = []
    if compare:
        padded = list(compare) + [None] * len(values or [])
        i = 0
        for v, c in zip(values or [], padded):
            if v is None:
                continue          # dropped from pts, so it takes no x position
            if c is not None:
                cmp_pts.append((i, float(c)))
            i += 1

    w, h = width_in * IN, height_in * IN
    x0, x1 = PAD_L, w - PAD_R
    y0, y1 = PAD_T, h - PAD_B
    # BOTH SERIES SET THE SCALE. Bounding on this year alone would push the
    # average off the top or bottom of the box, which is the one thing a
    # comparison chart must not do.
    seen = [v for _, v in pts] + [c for _, c in cmp_pts]
    lo, hi, ticks = _nice_bounds(min(seen), max(seen))

    def sx(i):
        return x0 + (x1 - x0) * (i / (len(pts) - 1))

    def sy(v):
        return y1 - (y1 - y0) * ((v - lo) / (hi - lo or 1))

    parts = [f'<svg class="dayplot" xmlns="http://www.w3.org/2000/svg" '
             f'viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" '
             f'role="img" aria-label="{_esc(title)}">']

    if title:
        parts.append(f'<text x="0" y="9" font-size="8" fill="#333" '
                     f'font-weight="600">{_esc(title)}</text>')

    for t in ticks:
        y = sy(t)
        parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{x0 - 4}" y="{y + 2.6:.1f}" font-size="7" '
                     f'fill="{AXIS_TEXT}" text-anchor="end" '
                     f'style="font-variant-numeric:tabular-nums">{t:g}</text>')

    # THE COMPARISON GOES DOWN FIRST, so this year draws over it rather than
    # under. Dashed and a weight thinner: the reading is "where are we against
    # normal", and normal is the backdrop, not the subject.
    if len(cmp_pts) >= 5:
        cd = " ".join(("M" if n == 0 else "L") + f"{sx(i):.1f} {sy(c):.1f}"
                      for n, (i, c) in enumerate(cmp_pts))
        parts.append(f'<path d="{cd}" fill="none" stroke="{COMPARE_LINE}" '
                     f'stroke-width="1.25" stroke-dasharray="3 2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')

    d = " ".join(("M" if i == 0 else "L") + f"{sx(i):.1f} {sy(v):.1f}"
                 for i, (_, v) in enumerate(pts))
    parts.append(f'<path d="{d}" fill="none" stroke="{LINE}" stroke-width="2" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')

    # First and last month, not every tick: at three inches wide there is room
    # for two labels and no more.
    for i, anchor in ((0, "start"), (len(pts) - 1, "end")):
        d = _as_date(pts[i][0])
        if not d:
            continue
        parts.append(f'<text x="{sx(i):.1f}" y="{h - 3:.0f}" font-size="7" '
                     f'fill="{AXIS_TEXT}" text-anchor="{anchor}">'
                     f'{_MONTHS[d.month - 1]}</text>')

    # The endpoint: an 8px dot with a 2px surface ring so it stays legible where
    # it sits on the line, and the one value worth reading without the axis.
    ex, ey, ev = sx(len(pts) - 1), sy(pts[-1][1]), pts[-1][1]
    parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="{LINE}" '
                 f'stroke="#fff" stroke-width="2"/>')
    parts.append(f'<text x="{ex + 6:.1f}" y="{ey + 2.8:.1f}" font-size="8" '
                 f'fill="#111" font-weight="600" '
                 f'style="font-variant-numeric:tabular-nums">{_fmt(ev, style)}</text>')

    # DIRECT-LABEL THE COMPARISON at its own end, and push it clear of this
    # year's endpoint rather than trusting them not to collide -- on a
    # seasonal chart the two lines converge exactly where both labels sit.
    if len(cmp_pts) >= 5 and compare_label:
        ci, cv = cmp_pts[-1]
        cy = sy(cv)
        cy += 9 if cv < pts[-1][1] else -6
        cy = min(max(cy, PAD_T + 6), h - PAD_B - 1)
        parts.append(f'<text x="{sx(ci) + 6:.1f}" y="{cy:.1f}" font-size="6.5" '
                     f'fill="{COMPARE_LINE}" font-weight="600">'
                     f'{_esc(compare_label)}</text>')

    parts.append("</svg>")
    return "".join(parts)


def chart_block(chart: dict) -> str:
    """
    The floated figure the morning brief drops into the bottom right.

    Float, not a table cell: the sign-off and the signature flow up its left
    side, so the chart occupies whitespace that already existed instead of
    pushing the page down.
    """
    if not chart:
        return ""
    svg = line_chart(chart.get("dates"), chart.get("values"),
                     chart.get("title", ""), chart.get("style", "decimal"),
                     compare=chart.get("compare"),
                     compare_label=chart.get("compare_label", "5-yr avg"))
    if not svg:
        return ""
    return f'<div class="dayplot-wrap">{svg}</div>'
