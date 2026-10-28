"""Morning Financial Wire - hosted view.

Shows today's wire (snapshot, reading list, macro read, history) and the
headline-candidate picker. Nothing here writes into the wire on its own: ticking
items only builds a bullet list, and the "Outlook draft" download adds those
bullets to a copy of the wire for you to edit and send.

Email-sourced content arrives from Snowflake (push_wire.py on your PC). The
public news feeds are fetched live. With no Snowflake config it reads the local
files, so `streamlit run streamlit_app.py` works on your PC too.
"""
import sys as _sys  # portal-sync: sibling imports resolve to this folder
from pathlib import Path as _Path  # portal-sync
_sys.path.insert(0, str(_Path(__file__).parent))  # portal-sync
import html
from email.message import EmailMessage

import streamlit as st

import fw_build_fin_wire as build_fin_wire
import fw_explain as explain
import fw_headlines as headlines
import fw_summarize as summarize
import fw_wire_store as wire_store

pass  # portal-sync: st.set_page_config removed (Home.py makes the one call allowed per run)

# -- palette: same as the CFTC COT dashboard ------------------------------------
JSA_GREEN = "#5e7164"
DM_BG, DM_SURFACE, DM_BORDER = "#f6f8f7", "#ffffff", "#d7e2dc"
DM_TEXT, DM_MUTED = "#32373c", "#5f7267"
COL_POS, COL_NEG = "#16a34a", "#dc2626"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&family=Source+Sans+3:wght@400;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"] {{ background-color:{DM_BG}; color:{DM_TEXT}; }}
html, body, p, span, div, label, button, td, th {{ font-family:'Source Sans 3','Source Sans Pro',sans-serif; }}
.block-container {{ padding-top: 3.2rem; max-width: 1400px; }}
.dash-header {{ display:flex; align-items:center; gap:18px; padding-bottom:10px;
    border-bottom:1px solid {DM_BORDER}; margin-bottom:14px; }}
.dash-header img {{ height:40px; }}
.dash-header .t b {{ font-family:'EB Garamond',Georgia,serif; font-size:1.7rem; color:{DM_TEXT}; font-weight:600; }}
.dash-header .t div {{ font-size:.85rem; color:{DM_MUTED}; }}
@media (max-width: 640px) {{ .dash-header img {{ display:none; }} }}
.tile {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-top:3px solid {JSA_GREEN};
    border-radius:10px; padding:14px 16px; text-align:center; height:100%; }}
.tile-label {{ color:{DM_MUTED}; font-size:0.68rem; text-transform:uppercase; letter-spacing:0.09em; margin-bottom:6px; }}
.tile-value {{ color:{DM_TEXT}; font-size:1.4rem; font-weight:700; line-height:1.1; }}
.tile-delta {{ font-size:0.9rem; font-weight:700; margin-top:4px; }}
.sec-header {{ color:{DM_MUTED}; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.1em;
    padding:10px 0 4px; border-bottom:1px solid {DM_BORDER}; margin-bottom:12px; }}
.asof {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-radius:8px; padding:10px 16px;
    color:{DM_MUTED}; font-size:0.82rem; margin-bottom:12px; }}
.asof b {{ color:{DM_TEXT}; }}
hr {{ border-color:{DM_BORDER}; }}
#MainMenu, footer {{ visibility:hidden; }}
.stDeployButton {{ display:none; }}
</style>
<div class="dash-header">
  <img src="https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png">
  <div class="t"><b>Morning Financial Wire</b>
  <div>Markets and news that move grains, biofuels and livestock &middot; John Stewart &amp; Associates</div></div>
</div>
""", unsafe_allow_html=True)


def sec(text: str):
    st.markdown(f'<div class="sec-header">{html.escape(text)}</div>', unsafe_allow_html=True)


def _md(parts: tuple[str, str]) -> str:
    """Markdown with the first sentence bold; $ escaped so pairs of prices don't render as LaTeX."""
    first, rest = (p.replace("$", "\\$") for p in parts)
    return f"**{first}**" + (f" {rest}" if rest else "")


def tile(name: str, level: str, change: str) -> str:
    col = build_fin_wire.change_color(name, change)
    col = COL_POS if col == build_fin_wire.GREEN else COL_NEG
    return (f'<div class="tile"><div class="tile-label">{html.escape(build_fin_wire.title_case(name))}</div>'
            f'<div class="tile-value">{html.escape(level)}</div>'
            f'<div class="tile-delta" style="color:{col}">{html.escape(change)}</div></div>')


def outlook_draft(wire: dict, picked: list, recipient: str) -> bytes:
    """An .eml flagged X-Unsent: Outlook opens it as an editable draft, subject 'Financial News'."""
    data = dict(wire, headlines=picked)
    msg = EmailMessage()
    msg["Subject"] = "Financial News"
    if recipient:
        msg["To"] = recipient
    msg["X-Unsent"] = "1"
    msg.set_content("Open this message in an HTML-capable mail client.")
    msg.add_alternative(build_fin_wire.build(data), subtype="html")
    return msg.as_bytes()


@st.cache_data(ttl=300, show_spinner="Loading the wire...")
def load_payloads():
    return wire_store.read_latest()


@st.cache_data(ttl=86400, show_spinner=False, max_entries=500)
def get_summary(title: str, link: str, source: str, blurb: str) -> dict:
    r = summarize.summarize(title, link, source, blurb)
    if not r["summary"]:
        raise RuntimeError(r["error"] or "no summary")   # exceptions are not cached, so a fixed key works at once
    return r


def fut_tile(r: dict) -> str:
    dec = r.get("decimals", 2)

    def line(label, v, pct=None):
        if v is None:
            return f'<div class="tile-sub">{label} n/a</div>'
        col = COL_POS if v > 0 else COL_NEG if v < 0 else DM_MUTED
        extra = f" ({pct:+.1f}%)" if pct is not None else ""
        return f'<div class="tile-sub">{label} <b style="color:{col}">{v:+.{dec}f}{extra}</b></div>'
    return (f'<div class="tile"><div class="tile-label">{html.escape(build_fin_wire.title_case(r["name"]))} · {html.escape(r["ticker"])}</div>'
            f'<div class="tile-value">{r["last"]:.{dec}f}</div>'
            f'<div class="tile-sub">{html.escape(r["unit"])}</div>{line("Day", r.get("day"))}{line("Week", r.get("week"))}'
            f'{line("Month", r.get("month"), r.get("month_pct"))}{line("Year", r.get("year"), r.get("year_pct"))}</div>')


@st.cache_data(ttl=86400, show_spinner=False, max_entries=50)
def get_explanations(items: tuple, context: str, source: str) -> list:
    return explain.explain(list(items), context, source)   # raises on failure, so failures are not cached


@st.cache_data(ttl=900, show_spinner="Fetching news feeds...")
def load_feeds():
    return headlines.collect(include_mailbox=False)


payloads, origin = load_payloads()
wire = (payloads.get("wire") or {}).get("data")
stamp = (payloads.get("wire") or {}).get("pushed_at")
st.markdown(f'<div class="asof">Source: <b>{html.escape(origin)}</b>'
            + (f" &middot; email items pushed <b>{stamp:%a %b %d %H:%M}</b>" if stamp else "") + "</div>",
            unsafe_allow_html=True)

if not wire:
    st.warning("No wire data yet. Run push_wire.py on the PC that has Outlook.")
else:
    if wire.get("history"):
        sec("Today in Markets History")
        with st.container(border=True):
            st.markdown(_md(build_fin_wire.split_first(wire["history"])))
    snap = wire.get("snapshot") or []
    if snap:
        sec("Market Snapshot" + (f" · Bloomberg, {wire['snapshotAsOf']}" if wire.get("snapshotAsOf") else ""))
        for col, s in zip(st.columns(len(snap)), snap):
            col.markdown(tile(s["name"], s["level"], s["change"]), unsafe_allow_html=True)
    futs = build_fin_wire.order_futures((payloads.get("mkts") or {}).get("data"))
    if futs:
        sec(f"Nearby Futures · Settlements {futs[0].get('asof', '')} · Change in Contract Units")
        for i in range(0, len(futs), 5):   # five tiles a row; 9 in one row is too narrow to read
            chunk = futs[i:i + 5]
            for col, r in zip(st.columns(5), chunk):
                col.markdown(fut_tile(r), unsafe_allow_html=True)
    for g in wire.get("gaps") or []:
        st.caption(f":material/warning: {g}")


# -- ticks live in session_state, so they are known before anything below is drawn ----------
feed_items, feed_errors = load_feeds()
items = list((payloads.get("pj") or {}).get("data") or []) + \
    list((payloads.get("bbg") or {}).get("data") or []) + feed_items
topics = list(dict.fromkeys(i["topic"] for i in items))
groups = {t: [i for i in items if i["topic"] == t] for t in topics}
picked = [it for t in topics for n, it in enumerate(groups[t]) if st.session_state.get(f"{t}-{n}")]

# -- PJ-style explanations under the Bloomberg Five Things and the WSJ reading list ----------
five = [i["title"] for i in (payloads.get("bbg") or {}).get("data") or [] if i.get("feed") == "Five things"]
wsj_items = list((wire or {}).get("reading") or [])
five_x, wsj_x, expl_note = [], [], None
with st.spinner("Writing the explanations..."):
    for items_, ctx, src, name in ((five, (wire or {}).get("bbgBody", ""), "Bloomberg Markets Daily", "five"),
                                   (wsj_items, (wire or {}).get("wsjBody", ""), "WSJ Markets A.M.", "wsj")):
        if not items_:
            continue
        try:
            x = get_explanations(tuple(items_), ctx, src)
        except Exception as e:
            expl_note, x = str(e), []
        if name == "five":
            five_x = x
        else:
            wsj_x = x
expl_map = dict(zip(five, five_x)) | dict(zip(wsj_items, wsj_x))

entries = []   # {"title": "Headline (Source)", "summary": "...", "note": None | "..."}
for p in picked:
    entry = {"title": f"{p['title']} ({p['source']})", "summary": "", "note": None, "basis": ""}
    if p.get("link"):
        with st.spinner(f"Summarizing: {p['title'][:60]}"):
            try:
                r = get_summary(p["title"], p["link"], p["source"], p.get("blurb", ""))
                entry["summary"], entry["basis"] = r["summary"], r["basis"]
            except Exception as e:
                entry["note"] = str(e)
    elif p["title"] in expl_map:
        entry["summary"], entry["basis"] = expl_map[p["title"]], "newsletter (AI-drafted)"
    entries.append(entry)

# -- the wire, full width, with the Outlook button just under it -------------------------
sec("Today's Wire")
if wire:
    with st.container(border=True):
        st.iframe(build_fin_wire.build(dict(wire, headlines=entries, futures=futs, five=five, five_x=five_x, reading_x=wsj_x)), height=1400)
    st.download_button(
        "Create Outlook template", data=outlook_draft(dict(wire, futures=futs, five=five, five_x=five_x, reading_x=wsj_x), entries, wire.get("recipient", "")),
        file_name="Financial News.eml", mime="message/rfc822", icon=":material/mail:", type="primary",
        help="Opens in Outlook as an editable draft, subject 'Financial News', with the wire plus your ticked headlines.")
    if expl_note and (five or wsj_items):
        st.caption(f":material/warning: no explanations written: {expl_note}")
else:
    st.info("No wire yet.")

# -- headline candidates below ----------------------------------------------------------
sec("Headline Candidates")
st.caption("Tick what matters. Ticked items appear in the wire above and in the Outlook template.")
if not items:
    st.info("No candidates yet.")
for t in topics:
    group = groups[t]
    with st.expander(f"{t} ({len(group)})", expanded=t in ("PJ Quaid", "Bloomberg Markets Daily")):
        for n, it in enumerate(group):
            title = it["title"] if len(it["title"]) < 400 else it["title"][:397] + "..."
            tail = f"  \n:gray[{it['source']} \u00b7 {it['when']}]"
            link = f" [:material/open_in_new:]({it['link']})" if it.get("link") else ""
            st.checkbox(_md(build_fin_wire.split_first(title)) + link + tail, key=f"{t}-{n}")
            # a small summary behind the headline: the AI-drafted explanation for Bloomberg's Five Things,
            # the publisher's own one-line description for WSJ's feed items
            small = expl_map.get(it["title"]) or (it.get("blurb") if t == "WSJ" else "")
            if small:
                st.caption(small.replace("$", "\\$"))

if entries:
    sec(f"Ticked ({len(entries)})")
    for e in entries:
        if e["note"]:
            st.caption(f":material/warning: no summary for \"{e['title'][:60]}\": {e['note']}")
        elif e["summary"]:
            st.markdown("\n\n".join([f"**{e['title'][:90]}**", e["summary"].replace("$", "\\$"),
                                     f":gray[summary from the {e['basis']}]"]))
    st.code("\n".join(f"\u2022 {e['title']}" + ("\n  " + e["summary"] if e["summary"] else "") for e in entries),
            language=None, wrap_lines=True)
for e in feed_errors:
    st.caption(f":material/warning: feed failed: {e}")
