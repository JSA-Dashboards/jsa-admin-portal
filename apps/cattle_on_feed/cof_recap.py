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
import re
from datetime import date

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
_US_TABLE = "1,000+ Capacity Feedlots - United States:"


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


def _table_block(text: str, marker: str) -> list:
    """Data rows of the first table whose header contains `marker`."""
    lines = text.splitlines()
    try:
        head = next(i for i, ln in enumerate(lines) if marker in ln)
    except StopIteration:
        return []
    out, seen_data = [], False
    for ln in lines[head:head + 60]:
        if _STATE_ROW.match(ln) or _US_ROW.match(ln):
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

FIG_W, FIG_H = 520, 690
INK = "#000000"    # title, column headers
DATA = "#963634"   # the maroon the client page has always used
MUTED = "#9a9a9a"
FONT = "Calibri, Carlito, Arial, sans-serif"

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
            bits.append(f"released {released:%b %d, %Y}")
        if guess_source:
            bits.append(f"guesses: {guess_source}")
        ann.append(_ann(34, FIG_H - 20, "  ·  ".join(bits), color=MUTED,
                        size=8, align="left"))

    fig = go.Figure()
    fig.update_layout(
        width=FIG_W, height=FIG_H, annotations=ann,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(visible=False, range=[0, 1], fixedrange=True),
        yaxis=dict(visible=False, range=[0, 1], fixedrange=True),
    )
    return fig
