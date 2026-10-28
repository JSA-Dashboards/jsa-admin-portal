"""Render fin_input.json (from fetch_fin.ps1) into an Outlook-safe HTML email.

No summarizing step: the snapshot, reading list, history and PJ's ag-read
paragraphs are all the senders' own text, laid into a fixed template.

    python build_fin_wire.py            # -> fin_output.html
    python build_fin_wire.py --open     # also open it in the browser
"""
import html
import json
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
SECTION_ORDER = ["history", "snapshot", "futures", "macro", "headlines", "five", "reading"]  # reorder freely

INK, ACCENT, MUTED, RULE = "#32373c", "#5e7164", "#5f7267", "#d7e2dc"   # JSA green, as the COT dashboard
GREEN, RED, AMBER = "#2e7d32", "#c62828", "#b26a00"
FONT = "font-family:Arial,Helvetica,sans-serif;"


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


_ABBR = {"u.s", "u.k", "inc", "corp", "co", "ltd", "jr", "sr", "st", "no", "vs", "mr", "mrs", "dr", "gov",
         "sen", "rep", "sec", "mt", "e.g", "i.e", "jan", "feb", "mar", "apr", "aug", "sept", "oct", "nov",
         "dec", "a.m", "p.m", "approx", "est"}


def split_first(text: str) -> tuple[str, str]:
    """(first sentence, the rest). Skips U.S., Inc., single initials and decimals; if there is
    no second sentence the whole text is the first."""
    for m in re.finditer(r'[.!?]["”\')]*\s+', text):
        i = m.start()
        nxt = text[m.end():m.end() + 1]
        if not nxt or nxt.islower():
            continue
        if text[i] == ".":
            tok = re.search(r"[\w.]+$", text[:i])
            tok = tok.group(0).lower() if tok else ""
            if tok in _ABBR or len(tok) == 1:
                continue
        return text[:m.end()].rstrip(), text[m.end():]
    return text, ""


def bold_first(text: str) -> str:
    """HTML-escaped text with the first sentence in <b>."""
    first, rest = split_first(text or "")
    return f"<b>{esc(first)}</b>" + (f" {esc(rest)}" if rest else "")


_SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "vs"}


def title_case(text: str) -> str:
    """Title Case for labels: small words stay lower (not first), and anything already containing a
    capital (US, SRW, McBee) is left alone. Hyphenated parts are handled one by one (10-Year)."""
    def fix(tok: str, first: bool) -> str:
        if any(c.isupper() for c in tok) or any(c.isdigit() for c in tok):
            return tok
        if not first and tok.lower() in _SMALL:
            return tok
        for i, c in enumerate(tok):
            if c.isalpha():
                return tok[:i] + c.upper() + tok[i + 1:]
        return tok
    out = []
    for i, w in enumerate((text or "").split(" ")):
        out.append("-".join(fix(p, i == 0 and j == 0) for j, p in enumerate(w.split("-"))))
    return " ".join(out)


def heading(text: str) -> str:
    return (f'<tr><td style="padding:22px 0 6px 0;{FONT}font-size:18px;font-weight:bold;'
            f'color:{INK};border-bottom:2px solid {ACCENT};">{esc(text)}</td></tr>')


def row(inner: str, pad: str = "10px 0 0 0") -> str:
    return f'<tr><td style="padding:{pad};{FONT}font-size:14px;line-height:1.5;color:{INK};">{inner}</td></tr>'


def change_color(name: str, change: str) -> str:
    up = change.strip().startswith("+")
    # Yields and the dollar going up is a headwind for grains - his own snapshot paints yield +0.01 red.
    if re.search(r"yield", name, re.I):
        return RED if up else GREEN
    return GREEN if up else RED


def snapshot(d: dict) -> str:
    rows = d.get("snapshot") or []
    if not rows:
        return ""
    body = ""
    for r in rows:
        col = change_color(r["name"], r["change"])
        body += (f'<tr><td style="padding:9px 4px;border-bottom:1px solid {RULE};{FONT}font-size:14px;'
                 f'font-weight:bold;color:{INK};">{esc(title_case(r["name"]))}</td>'
                 f'<td align="right" style="padding:9px 4px;border-bottom:1px solid {RULE};{FONT}font-size:14px;'
                 f'color:{INK};">{esc(r["level"])}</td>'
                 f'<td align="right" style="padding:9px 4px;border-bottom:1px solid {RULE};{FONT}font-size:14px;'
                 f'font-weight:bold;color:{col};width:70px;">{esc(r["change"])}</td></tr>')
    asof = d.get("snapshotAsOf")
    note = f'<div style="{FONT}font-size:11px;color:{MUTED};padding-top:4px;">Bloomberg, as of {esc(asof)}</div>' if asof else ""
    return heading("Market Snapshot") + row(f'<table width="100%" cellpadding="0" cellspacing="0">{body}</table>{note}', "6px 0 0 0")


def _explained(title: str, items: list, expl: list, note: str) -> str:
    """Bold headline with a PJ-style explanation paragraph under each (when we have one)."""
    if not items:
        return ""
    if not expl or len(expl) != len(items):
        lis = "".join(f'<li style="padding:3px 0;">{esc(i)}</li>' for i in items)
        return heading(title) + row(f'<ul style="margin:0;padding-left:20px;">{lis}</ul>')
    ps = "".join(f'<p style="margin:0 0 12px 0;"><b>{esc(i)}</b><br>{esc(x)}</p>' for i, x in zip(items, expl))
    return heading(title) + row(ps) +         f'<tr><td style="{FONT}font-size:11px;color:{MUTED};">{esc(note)}</td></tr>'


def reading(d: dict) -> str:
    return _explained("What We're Reading", d.get("reading") or [], d.get("reading_x") or [],
                      "WSJ Markets A.M. headlines; explanations are AI-drafted from the newsletter, verify before relying")


def five_things(d: dict) -> str:
    return _explained("Bloomberg Five Things", d.get("five") or [], d.get("five_x") or [],
                      "Bloomberg Markets Daily; explanations are AI-drafted from the newsletter, verify before relying")


def macro(d: dict) -> str:
    paras = d.get("macro") or []
    if not paras:
        return ""
    ps = "".join(f'<p style="margin:0 0 12px 0;">{bold_first(p)}</p>' for p in paras)
    return heading("Macro & Ag Read") + row(ps) + \
        f'<tr><td style="{FONT}font-size:11px;color:{MUTED};">PJ Quaid, StoneX</td></tr>'


FUT_ORDER = ["Corn", "Chicago ethanol (Platts fut)", "Soybeans", "Board crush", "Soybean meal",
             "Soybean oil", "SRW wheat", "HRW wheat", "Live cattle"]


def order_futures(rows: list) -> list:
    """Display order for the nearby table; anything not listed goes last, in its original order."""
    rank = {n: i for i, n in enumerate(FUT_ORDER)}
    return sorted(rows or [], key=lambda r: rank.get(r.get("name"), len(FUT_ORDER)))


def futures(d: dict) -> str:
    """Nearby futures: last settle; day/week change nominal; month/year change nominal with % in ( )."""
    rows = order_futures(d.get("futures"))
    if not rows:
        return ""
    base = f"padding:8px 4px;border-bottom:1px solid {RULE};{FONT}font-size:14px;"
    th = (f'style="padding:6px 4px;border-bottom:2px solid {RULE};{FONT}font-size:11px;color:{MUTED};'
          f'text-transform:uppercase;letter-spacing:.06em;"')
    head = (f'<tr><td {th}>Nearby</td>' +
            "".join(f'<td align="right" {th}>{h}</td>' for h in ("Last", "Day", "Week", "Month (%)", "Year (%)")) + '</tr>')

    def cell(v, dec, pct=None):
        if v is None:
            return f'<td align="right" style="{base}color:{MUTED};">n/a</td>'
        col = GREEN if v > 0 else RED if v < 0 else INK
        txt = f"{v:+.{dec}f}" + (f" ({pct:+.1f}%)" if pct is not None else "")
        return f'<td align="right" style="{base}font-weight:bold;color:{col};">{txt}</td>'

    body = ""
    for r in rows:
        dec = r.get("decimals", 2)
        body += (f'<tr><td style="{base}font-weight:bold;color:{INK};">{esc(title_case(r["name"]))} '
                 f'<span style="font-weight:normal;color:{MUTED};font-size:11px;">{esc(r["ticker"])}</span></td>'
                 f'<td align="right" style="{base}color:{INK};">{r["last"]:.{dec}f} '
                 f'<span style="color:{MUTED};font-size:11px;">{esc(r["unit"])}</span></td>'
                 f'{cell(r.get("day"), dec)}{cell(r.get("week"), dec)}'
                 f'{cell(r.get("month"), dec, r.get("month_pct"))}{cell(r.get("year"), dec, r.get("year_pct"))}</tr>')
    asof = esc(rows[0].get("asof", ""))
    note = (f'<div style="{FONT}font-size:11px;color:{MUTED};padding-top:4px;">Settlements as of {asof}. '
            f'Change in each contract\'s own units (&cent;/bu, $/st, &cent;/lb); all on the same contract, '
            f'so a roll is never a move. Week = 5 sessions, month = 30 days, year = 365 days. '
            f'Ethanol is the CME Chicago (Platts) futures, a proxy for the assessment.</div>')
    return heading("Nearby Futures") + row(
        f'<table width="100%" cellpadding="0" cellspacing="0">{head}{body}</table>{note}', "6px 0 0 0")


def headlines_section(d: dict) -> str:
    """Ticked headline candidates, passed in by the app (never read from a feed here).
    Each item is a string, or {"title", "summary"} for a headline with a written summary."""
    items = d.get("headlines") or []
    if not items:
        return ""
    lis = ""
    for i in items:
        title, summ = (i.get("title", ""), i.get("summary", "")) if isinstance(i, dict) else (i, "")
        sub = (f'<div style="margin-top:3px;font-weight:normal;">{esc(summ)}</div>' if summ else "")
        lis += f'<li style="padding:5px 0;">{bold_first(title)}{sub}</li>'
    return heading("Headlines") + row(f'<ul style="margin:0;padding-left:20px;">{lis}</ul>')


def history(d: dict) -> str:
    h = d.get("history")
    if not h:
        return ""
    return heading("Today in Markets History") + row(esc(h))


SECTIONS = {"snapshot": snapshot, "futures": futures, "reading": reading, "five": five_things, "macro": macro,
            "headlines": headlines_section, "history": history}


def build(d: dict) -> str:
    today = datetime.now().strftime("%A, %B %d, %Y").replace(" 0", " ")
    parts = "".join(SECTIONS[k](d) for k in SECTION_ORDER)

    gaps = d.get("gaps") or []
    if gaps:
        li = "".join(f"<li>{esc(g)}</li>" for g in gaps)
        parts += (f'<tr><td style="padding:22px 0 0 0;"><table width="100%" cellpadding="10" cellspacing="0" '
                  f'style="background:#fff4e0;border-left:4px solid {AMBER};"><tr><td style="{FONT}font-size:13px;'
                  f'color:{INK};"><b>Did not make this wire</b><ul style="margin:6px 0 0 0;padding-left:18px;">{li}</ul>'
                  f'</td></tr></table></td></tr>')

    srcs = esc("; ".join(d.get("sources") or []))
    foot = (f'<tr><td style="padding:24px 0 0 0;{FONT}font-size:11px;color:{MUTED};border-top:1px solid {RULE};">'
            f'Sources: {srcs}. For internal reading only; do not forward.</td></tr>')

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{esc(d.get('subject',''))}</title></head>
<body style="margin:0;padding:0;background:#ffffff;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="left">
<table width="100%" cellpadding="0" cellspacing="0" style="width:100%;">
<tr><td style="padding:20px 0 4px 0;{FONT}font-size:24px;font-weight:bold;color:{INK};">Morning Financial Wire</td></tr>
<tr><td style="{FONT}font-size:13px;color:{MUTED};">{esc(today)}</td></tr>
{parts}
{foot}
</table></td></tr></table></body></html>"""


if __name__ == "__main__":
    data = json.loads((HERE / "fin_input.json").read_text(encoding="utf-8-sig"))
    out = HERE / "fin_output.html"
    out.write_text(build(data), encoding="utf-8")
    print(f"Wrote {out}")
    if "--open" in sys.argv:
        webbrowser.open(out.as_uri())
