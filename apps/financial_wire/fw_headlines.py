"""Headline candidates for the Morning Financial Wire.

Pulls recent news that bears on grains, biofuels and (lightly) livestock from
RSS feeds and site-scoped Google News searches, dedupes, and writes a tick-box
page (headline_candidates.html). Ticking copies bullets to the clipboard; you
paste them into the wire's Headlines box and rewrite them in your own words.

Nothing here ever writes into the wire. build_fin_wire.py does not import this
module - that separation is deliberate, so a feed can't put words under JSA's name.

    python headlines.py            # -> headline_candidates.html (+ .json)
    python headlines.py --open
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).parent
MAX_AGE_H = 40          # 64 on Monday, set below
PER_FEED = 12
UA = {"User-Agent": "Mozilla/5.0 (JSA morning wire)"}


def gnews(q: str) -> str:
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q + " when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"})


# (topic, label, url) - listed in dedupe priority order: first copy of a headline wins.
FEEDS = [
    # WSJ's public section feeds: headlines + summaries only, no paywalled text.
    ("WSJ", "WSJ Markets", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain"),
    ("WSJ", "WSJ Economy", "https://feeds.content.dowjones.io/public/rss/socialeconomyfeed"),
    ("WSJ", "WSJ World News", "https://feeds.content.dowjones.io/public/rss/RSSWorldNews"),
    ("Grains", "DTN / Brownfield / Farm Progress",
     gnews('(site:dtnpf.com OR site:brownfieldagnews.com OR site:farmprogress.com OR site:agweb.com) (corn OR soybeans OR wheat)')),
    ("Grains", "Wires: grain markets",
     gnews('(site:reuters.com OR site:bloomberg.com OR site:wsj.com) (CBOT OR "corn futures" OR "soybean futures" OR "wheat futures" OR "grain exports")')),
    ("Grains", "Trade & China",
     gnews('(soybeans OR corn OR wheat) (China OR tariff OR "trade deal" OR "export sales" OR Brazil OR Argentina)')),
    ("Biofuels", "Ethanol & RFS",
     gnews('(ethanol OR RFS OR "renewable volume obligations" OR E15 OR 45Z OR "SAF")')),
    ("Biofuels", "Biodiesel / soybean oil",
     gnews('("renewable diesel" OR biodiesel OR "soybean oil" OR "crush margins" OR "biomass-based diesel")')),
    ("Macro for Ag", "Fed, dollar, energy",
     gnews('(site:reuters.com OR site:bloomberg.com OR site:wsj.com) (Fed OR "Treasury yields" OR "dollar index" OR "crude oil" OR Hormuz)')),
    ("Livestock", "Cattle & beef",
     gnews('(cattle OR "beef prices" OR "feeder cattle" OR "screwworm" OR "packer") (futures OR herd OR imports OR plant)')),
    ("Livestock", "Hogs",
     gnews('("lean hogs" OR "pork exports" OR "hog prices")')),
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()[:70]


def parse(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = (src_el.text if src_el is not None else "") or ""
        if not source and " - " in title:
            title, source = title.rsplit(" - ", 1)
        elif source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        try:
            when = parsedate_to_datetime(it.findtext("pubDate") or "")
        except Exception:
            when = None
        desc = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
        desc = re.sub(r"\s+", " ", desc).strip()
        yield title.strip(), source.strip(), link, when, desc


def collect(include_mailbox=True):
    """include_mailbox=False is the hosted app's mode: only the public feeds (the
    mailbox items reach it through Snowflake, pushed from your PC by push_wire.py)."""
    age = timedelta(hours=64 if datetime.now().weekday() == 0 else MAX_AGE_H)
    cutoff = datetime.now(timezone.utc) - age
    seen, out, errors = set(), [], []
    if include_mailbox:
        out.extend(pj_items(errors))
        out.extend(bbg_items(errors))
    for topic, label, url in FEEDS:
        try:
            n = 0
            for title, source, link, when, desc in parse(fetch(url)):
                if n >= PER_FEED:
                    break
                if when and when.astimezone(timezone.utc) < cutoff:
                    continue
                k = norm(title)
                if len(title) < 25 or k in seen:   # drops ticker-only items like "AMAN.O"
                    continue
                seen.add(k)
                n += 1
                out.append({"topic": topic, "feed": label, "title": title, "source": source or label,
                            "link": link, "when": when.astimezone().strftime("%a %H:%M") if when else "",
                            # Google News descriptions just repeat the headline; only direct feeds carry a blurb
                            "blurb": "" if "news.google.com" in url else desc})
        except Exception as e:  # one dead feed shouldn't sink the page
            errors.append(f"{label}: {e}")
    return out, errors


def pj_items(errors):
    """Prose paragraphs from every PJ Quaid email (Outlook), pinned first - like Ross's USDA items."""
    import subprocess
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(HERE / "fetch_pj.ps1")], check=True, capture_output=True, timeout=240)
        raw = (HERE / "pj_candidates.json").read_text(encoding="utf-8-sig").strip()
        rows = json.loads(raw) if raw else []
        rows = [rows] if isinstance(rows, dict) else rows
    except Exception as e:
        errors.append(f"PJ Quaid mailbox: {e}")
        return []
    return [{"topic": "PJ Quaid", "feed": r["subject"], "title": r["text"], "source": f'PJ Quaid, StoneX - "{r["subject"]}"',
             "link": "", "when": r["received"]} for r in rows]


def bbg_items(errors):
    """Five Things + On the move bullets from your Bloomberg Markets Daily email."""
    import subprocess
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(HERE / "fetch_bbg.ps1")], check=True, capture_output=True, timeout=240)
        raw = (HERE / "bbg_candidates.json").read_text(encoding="utf-8-sig").strip()
        rows = json.loads(raw) if raw else []
        rows = [rows] if isinstance(rows, dict) else rows
    except Exception as e:
        errors.append(f"Bloomberg mailbox: {e}")
        return []
    return [{"topic": "Bloomberg Markets Daily", "feed": r["section"], "title": r["text"],
             "source": f'Bloomberg - {r["section"]}', "link": "", "when": r["received"]} for r in rows]


def render(items, errors) -> str:
    esc = lambda s: html.escape(s or "", quote=True)
    topics = []
    for it in items:
        if it["topic"] not in topics:
            topics.append(it["topic"])
    body = ""
    for t in topics:
        body += f"<h2>{esc(t)}</h2>"
        for i, it in enumerate(x for x in items if x["topic"] == t):
            cid = f"{t}-{i}".replace(" ", "_")
            text = (f'<a href="{esc(it["link"])}" target="_blank" rel="noopener">{esc(it["title"])}</a>'
                    if it["link"] else esc(it["title"]))
            body += (f'<label class="row"><input type="checkbox" data-t="{esc(it["title"])}" data-s="{esc(it["source"])}" id="{cid}">'
                     f'<span>{text}'
                     f'<small> {esc(it["source"])} · {esc(it["when"])}</small></span></label>')
    err = "".join(f"<li>{esc(e)}</li>" for e in errors)
    err = f'<div class="warn"><b>Feeds that failed</b><ul>{err}</ul></div>' if err else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Headline Candidates</title>
<style>body{{font:14px/1.45 Arial,sans-serif;color:#32373c;max-width:760px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px}}h2{{font-size:16px;border-bottom:2px solid #0693e3;padding-bottom:4px;margin-top:24px}}
.row{{display:flex;gap:8px;padding:5px 0}}small{{color:#6b7280}}a{{color:#32373c;text-decoration:none}}a:hover{{text-decoration:underline}}
.bar{{position:sticky;top:0;background:#fff;padding:10px 0;border-bottom:1px solid #d9dde1}}
button{{background:#0693e3;color:#fff;border:0;padding:8px 14px;border-radius:4px;cursor:pointer}}
.warn{{background:#fff4e0;border-left:4px solid #b26a00;padding:8px 12px;margin-top:16px}}</style></head><body>
<h1>Headline Candidates</h1>
<p>Tick what matters, copy, paste into the wire's Headlines box and rewrite in your own words. Nothing here goes into the wire on its own.</p>
<div class="bar"><button onclick="cp()">Copy ticked (<span id="n">0</span>)</button> <span id="m"></span></div>
{body}{err}
<script>
const boxes=[...document.querySelectorAll('input[type=checkbox]')];
boxes.forEach(b=>b.onchange=()=>n.textContent=boxes.filter(x=>x.checked).length);
function cp(){{const t=boxes.filter(x=>x.checked).map(x=>'\\u2022 '+x.dataset.t+(x.dataset.s?' ('+x.dataset.s+')':'')).join('\\n');
navigator.clipboard.writeText(t).then(()=>m.textContent='Copied');}}
</script></body></html>"""


if __name__ == "__main__":
    items, errors = collect()
    (HERE / "headline_candidates.json").write_text(json.dumps(items, indent=1), encoding="utf-8")
    out = HERE / "headline_candidates.html"
    out.write_text(render(items, errors), encoding="utf-8")
    print(f"{len(items)} candidates, {len(errors)} feed errors -> {out}")
    for e in errors:
        print("  FEED ERROR:", e)
    if "--open" in sys.argv:
        webbrowser.open(out.as_uri())
