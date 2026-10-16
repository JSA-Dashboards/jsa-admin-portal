"""
The Sterling Beef Profit Tracker, fetched from the mailbox and parsed.

John Nalivka's weekly PDF arrives from jnalivka@fmtc.com and carries, on one
page, every figure on slide 7 of the weekly cattle deck: the feedlot and
packer margins, the weekly slaughter table with Sterling's own plant capacity
utilisation, and the annual projections. Until 2026-10-06 all of it was
retyped or pasted in as screenshots.

IT IS SOMEONE ELSE'S DATA AND THAT CHANGES THE RULES.

Sterling is a paid subscription and the PDF says so: "considered proprietary
material". Two consequences the rest of this module is built around.

  REPRODUCE, NEVER RECOMPUTE. Where USDA figures can be checked against each
  other and marked when they disagree, these are Sterling's numbers and the
  only correct behaviour is to print what they published. AMS has its own
  weekly slaughter split -- for w/e 2026-09-26 it says Steers/Heifers 382,000
  and Cows/Bulls 102,000 against Sterling's 395,428 and 82,280 -- and
  substituting it would produce a table that is neither Sterling's nor AMS's.
  Sterling's own rows do not always reconcile (see THE ZERO below) and they
  are still reproduced exactly.

  THE ATTRIBUTION IS PART OF THE SLIDE. "Margins compiled by Sterling
  Marketing, Inc." is on the hand-built slide and must stay on the generated
  one. `ATTRIBUTION` is used by the renderer; do not make it optional.

THE ZERO. Sterling's 2026-09-28 tracker reports Cows week-ago as 0 while the
Cow Plant Capacity Utilization directly beneath it reads 60.0% for the same
column -- a percentage of nothing. It is wrong in their PDF, so it is
reproduced and flagged by `anomalies()` rather than quietly repaired.
Repairing it would mean inventing a number and attributing it to Sterling.

WHAT THIS FIXES. The hand-typed slide for 2026-09-28 read "Packer Margins -
Last week- 117.37" where the tracker says 137.37: one digit, in a client
deck, in the row immediately above Sterling's own attribution line.

PARSING. Every data row ends in exactly four values -- this week, week ago,
month ago, year ago -- so the parser takes the LAST FOUR numeric tokens on
the line rather than all of them. It has to: the labels carry footnote
markers and ranges ("Beef Cutout 1 ($ / cwt)", "Cow-Calf Margin 3($ / cow)",
"Feeder Steer (Ok City 750-800 lb...)") and a leading-token rule would read a
footnote number as a price. A row that does not yield four values is returned
as None rather than padded, so a layout change shows up as a gap instead of a
silent shift of every column by one.

PARENTHESES ARE NEGATIVE. Sterling writes losses in accounting style:
($335.15) is minus 335.15. Reading it as positive turns the worst feedlot
margin in two years into a profit, which is exactly the kind of wrong number
that looks entirely plausible on a slide.
"""

from __future__ import annotations

import base64
import io
import re
from datetime import datetime

ATTRIBUTION = "Margins compiled by Sterling Marketing, Inc."
SENDER = "jnalivka@fmtc.com"
SUBJECT_HINT = "Profit Trackers"
PDF_NAME = "Sterling Beef Profit Tracker.pdf"

MISSING = "[[?]]"

# label -> the key it lands under. Matched as a prefix on the stripped line,
# so the trailing "($ / head)" and footnote markers do not have to be spelled
# out here.
ROWS = {
    "Feedlot Margin - Unhedged": "feedlot_margin",
    "Packer Margin": "packer_margin",
    "Cattle Slaughter": "cattle_slaughter",
    "Steer & Heifer": "steer_heifer",
    "Fed Plant Capacity Utilization": "fed_capacity",
    "Cows": "cows",
    "Cow Plant Capacity Utilization": "cow_capacity",
    "Beef Production": "beef_production",
    "Carcass Weight": "carcass_weight",
}

# The annual block repeats two labels from the weekly block, so it is parsed
# from its own section rather than by label alone.
ANNUAL_ROWS = {
    "Cow-Calf Margin": "cow_calf_margin",
    "Feedlot Margin": "feedlot_margin",
    "Packer Margin": "packer_margin",
}

_NUM = re.compile(r"\(?\$?-?[\d,]+\.?\d*\)?%?")


def _value(tok: str):
    """'($335.15)' -> -335.15, '74.6%' -> 74.6, '484,000' -> 484000.0."""
    t = tok.strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace("$", "").replace(",", "").replace("%", "")
    if not t or t in "-.":
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _last_four(line: str):
    """
    The four data values on a row, or None.

    None rather than a short list on purpose: a padded row would shift every
    column and still render, which is the failure this whole module is
    written to avoid.
    """
    toks = [t for t in _NUM.findall(line) if _value(t) is not None]
    if len(toks) < 4:
        return None
    return [_value(t) for t in toks[-4:]]


def parse(text: str) -> dict:
    """Page 1 of the tracker as a dict. Never raises; missing rows are absent."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out = {"weekly": {}, "annual": {}, "week_ending": None,
           "annual_as_of": None, "annual_years": [], "annual_label": None}

    # The week-ending date is near the top but not reliably FIRST -- the
    # column header ("Week Ending  Week Ago Month Ago Year Ago") comes out
    # above it in the extracted text, so lines[0] is a header, not a date.
    for ln in lines[:4]:
        if ln.strip().startswith("Annual"):
            break
        d = _date(ln)
        if d:
            out["week_ending"] = d
            break

    # The annual block starts at its own header and the two repeated labels
    # below it belong to it, not to the weekly table.
    split = len(lines)
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Annual Projections"):
            split = i
            out["annual_as_of"] = _date(ln)
            # Sterling's OWN label text, kept verbatim. They write "Sept."
            # and strftime('%b') gives "Sep" -- reformatting their header is
            # the same class of mistake as recomputing their figures.
            out["annual_label"] = re.split(r"\s+20\d\d\*", ln, maxsplit=1)[0].strip()
            # The column years come AFTER the as-of date, and that date
            # contains a year too -- "Annual Projections - Sept. 14, 2026
            # 2026* 2025 2024 2023" yields five matches if the whole line is
            # scanned, and the duplicate silently shifts the header.
            tail = ln.split(str(out["annual_as_of"].year), 1)[-1] \
                if out["annual_as_of"] else ln
            out["annual_years"] = re.findall(r"\b(20\d\d)\*?", tail)
            break

    for i, ln in enumerate(lines):
        stripped = ln.strip()
        table = out["weekly"] if i < split else out["annual"]
        labels = ROWS if i < split else ANNUAL_ROWS
        for label, key in labels.items():
            if stripped.startswith(label) and key not in table:
                vals = _last_four(stripped)
                if vals:
                    table[key] = vals
                break
    return out


def _date(s: str):
    """
    'September 26, 2026' or 'Sept. 14, 2026' -> a date.

    Sterling abbreviates inconsistently -- "Sept." is not a strptime month
    name under any locale, so it is normalised before parsing rather than
    hoping %b takes it.
    """
    m = re.search(r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+20\d\d)", s)
    if not m:
        return None
    txt = m.group(1).replace("Sept.", "Sep").replace(".", "")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


def anomalies(data: dict) -> list:
    """
    Things wrong in Sterling's own numbers, reported rather than repaired.

    Only checks that need no outside data, because the moment this reaches
    for AMS to "verify" Sterling it stops reproducing and starts arbitrating
    between two methodologies.
    """
    out = []
    w = data.get("weekly", {})
    for key, label in (("cows", "Cows"), ("steer_heifer", "Steer & Heifer"),
                       ("cattle_slaughter", "Cattle Slaughter")):
        vals = w.get(key)
        if vals and any(v == 0 for v in vals):
            cols = [c for c, v in zip(COLUMNS, vals) if v == 0]
            out.append(f"Sterling reports {label} as 0 for {', '.join(cols)}.")
    # A capacity utilisation with no head count behind it
    if w.get("cows") and w.get("cow_capacity"):
        for c, head, pct in zip(COLUMNS, w["cows"], w["cow_capacity"]):
            if head == 0 and pct:
                out.append(f"Cow capacity utilisation reads {pct}% for {c} "
                           f"against a head count of 0 — Sterling's own rows "
                           f"disagree for that column.")
    return out


COLUMNS = ("this week", "week ago", "month ago", "year ago")


# -- fetching -----------------------------------------------------------------

def fetch(max_age_days: int = 21) -> dict:
    """
    The newest Profit Tracker PDF, parsed.

    Returns {"error": ...} rather than raising, like every other source here:
    a mailbox that will not answer must not stop the deck being built from
    whatever else is available.
    """
    try:
        import requests

        from . import mailbox
    except Exception as exc:                      # pragma: no cover
        return {"error": f"mailbox unavailable: {exc}"}

    if not mailbox.configured():
        return {"error": "Graph is not configured for this deployment."}
    token, _flow = mailbox.token(interactive=False)
    if not token:
        return {"error": "Not signed in to the mailbox — open the letter page "
                         "and complete the Microsoft sign-in."}

    h = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(f"{mailbox.GRAPH}/me/messages", headers=h, timeout=60,
                         params={"$search": f'"from:{SENDER} {SUBJECT_HINT}"',
                                 "$select": "id,subject,receivedDateTime",
                                 "$top": 10})
        r.raise_for_status()
        msgs = [m for m in r.json().get("value", [])
                if SUBJECT_HINT in m.get("subject", "")]
    except Exception as exc:
        return {"error": f"mailbox search failed: {exc}"}
    if not msgs:
        return {"error": f"No '{SUBJECT_HINT}' email from {SENDER}."}

    msgs.sort(key=lambda m: m["receivedDateTime"], reverse=True)
    msg = msgs[0]
    received = datetime.strptime(msg["receivedDateTime"][:10], "%Y-%m-%d").date()

    try:
        atts = requests.get(f"{mailbox.GRAPH}/me/messages/{msg['id']}/attachments",
                            headers=h, timeout=120).json().get("value", [])
        pdf = next(a for a in atts if a.get("name") == PDF_NAME)
        raw = base64.b64decode(pdf["contentBytes"])
    except StopIteration:
        return {"error": f"'{msg['subject']}' has no {PDF_NAME}."}
    except Exception as exc:
        return {"error": f"could not read the attachment: {exc}"}

    try:
        from pypdf import PdfReader
        text = PdfReader(io.BytesIO(raw)).pages[0].extract_text() or ""
    except Exception as exc:
        return {"error": f"could not parse the PDF: {exc}"}

    data = parse(text)
    data["received"] = received
    data["subject"] = msg["subject"]
    data["age_days"] = None
    return data
