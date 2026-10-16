"""
Cattle Market Board — what is moving the market, what it means, on one page.

STAFF ONLY, AND UNLISTED. `portal_auth.require_admin()` is the first thing that
runs, and `Home.py` registers this under `TOOLS` rather than `DASHBOARDS`, the
same treatment the letter authoring tool gets: no home-grid tile, no nav entry,
no route at all for a client. Signing in reveals both staff pages together.

IT IS A RENDERER AND NOTHING ELSE. Every figure comes from the module that
already owns it — `apps/cash_trade/leverage.py`, `apps/fed_cattle_crush/
corn_cost.py`, `letter/sources.py` — fetched by `loaders.py`, picked by
`registry.py`, read by `meaning.py`. This file computes no market number. It
cannot: a summary page that re-derives a figure another page shows is the
letter-versus-dashboard disagreement CLAUDE.md records four times, multiplied
by twenty tiles.

ITS OWN PAGE, NOT A TAB ON THE LETTER. A hidden Streamlit tab still executes,
so as a third tab here the fetches below would run on every keystroke in the
letter's commentary boxes and add their cold cost to the page Ross opens under
deadline each morning. Separate pages, separate loads — and an exception here
cannot take the letter down with it.
"""

import os
import sys
from datetime import date
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import portal_auth  # noqa: E402

portal_auth.require_admin("Cattle Market Board")

# Forward Streamlit Cloud secrets into os.environ so the Snowflake readers see
# them the same way they do locally.
#
# SNOWFLAKE_SCHEMA IS DELIBERATELY NOT IN THIS LIST, and that is the one
# difference from the block this is copied from. Nine bundled modules each
# default it to the schema THEY own; forwarding one value overrides all nine and
# their queries miss silently — pages load, charts come back empty, nothing
# raises. CLAUDE.md is explicit that unset is the only working configuration, so
# this page declines to forward it even if somebody adds it to the console.
try:
    for _k in ("USE_SNOWFLAKE", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER",
               "SNOWFLAKE_PASSWORD", "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE",
               "SNOWFLAKE_DATABASE"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # noqa: BLE001
    pass

import mb_loaders as loaders
import mb_meaning as meaning
import mb_registry as registry

JSA_GREEN = "#5e7164"
INK = "#32373c"
MUTED = "#8b9490"

st.markdown(f"""<style>
.mb-card {{ background:{INK}; border-radius:6px; padding:16px 18px 14px;
            margin-bottom:18px; }}
.mb-q {{ color:#fff; font-family:'EB Garamond',Georgia,serif; font-size:20px;
         font-weight:600; margin:0 0 2px; }}
.mb-tile {{ border-left:3px solid {JSA_GREEN}; padding:2px 0 2px 12px;
            margin:14px 0 0; }}
.mb-label {{ color:#cfe8fb; font-size:13px; font-weight:600; letter-spacing:.2px; }}
.mb-value {{ color:#fff; font-size:26px; font-weight:600; line-height:1.15; }}
.mb-basis {{ color:{MUTED}; font-size:11px; font-style:italic; margin-top:2px; }}
.mb-text {{ color:#dfe5e1; font-size:13px; line-height:1.5; margin-top:6px; }}
.mb-stale .mb-value {{ color:#e0b050; }}
.mb-gone .mb-value {{ color:{MUTED}; }}
.mb-strip {{ background:#eef1ef; border-left:4px solid {JSA_GREEN};
             padding:8px 12px; font-size:12px; color:#333; margin-bottom:14px; }}
.mb-bad {{ background:#fdecea; border-left-color:#b3261e; }}
.mb-cross {{ background:#f4f6f4; border:1px solid #dde2de; border-radius:6px;
             padding:12px 14px; margin-bottom:12px; }}
.mb-cross h4 {{ margin:0 0 6px; font-size:15px; color:{INK}; }}
</style>""", unsafe_allow_html=True)

st.markdown(f"<div class='mb-q' style='font-size:26px'>Cattle Market Board</div>",
            unsafe_allow_html=True)

TODAY = date.today()

with st.spinner("Reading USDA, CME and Snowflake…"):
    B = loaders.bundle(TODAY)

READINGS = {s.key: meaning.read(s, B, TODAY) for s in registry.SIGNALS}

# ── the freshness strip ──────────────────────────────────────────────────────
#
# THREE STATES KEPT DISTINCT. "Old figure" and "dead fetch" are different
# sentences and a reader needs to know which. Every figure renders identically
# whether its pipeline ran twenty minutes ago or failed on Friday.
_ok = [r for r in READINGS.values() if r.state == meaning.OK]
_stale = [r for r in READINGS.values() if r.state == meaning.STALE]
_gone = [r for r in READINGS.values() if r.state == meaning.GONE]

bits = [f"{len(_ok)} of {len(READINGS)} current"]
if _stale:
    oldest = max(_stale, key=lambda r: r.days_behind or 0)
    bits.append(f"{len(_stale)} stale (oldest: {oldest.signal.label}, "
                f"{meaning.short(oldest.as_of)})")
if _gone:
    bits.append(f"{len(_gone)} with no reading")
if B["errors"]:
    bits.append(f"{len(B['errors'])} source(s) failed")

st.markdown(
    f"<div class='mb-strip {'mb-bad' if B['errors'] else ''}'>"
    + " · ".join(bits) + "</div>", unsafe_allow_html=True)

if B["errors"]:
    with st.expander(f"{len(B['errors'])} source(s) failed", expanded=False):
        for name, why in B["errors"].items():
            st.markdown(f"- **{name}** — {why}")

# A loud banner rather than a quiet note: without the Snowflake block the
# readers fall through to a committed SQLite file and render plausible
# months-old numbers with nothing raising. "It works locally proves nothing" is
# this project's own rule and this is where it gets enforced.
if os.environ.get("USE_SNOWFLAKE", "").strip().lower() not in ("1", "true", "yes", "on"):
    st.error("Reading the local SQLite file, not Snowflake. Every Snowflake-"
             "sourced figure below may be months old.")

# ── the cross-signal panels, above the tiles ─────────────────────────────────
#
# ABOVE, because they are the only sentences on this page that no existing
# dashboard produces. A reader who gets no further than the fold should have
# read these.
st.markdown("### What it means")
for cross, body, live in meaning.crosses(READINGS, B):
    st.markdown(
        f"<div class='mb-cross'><h4>{cross.title}</h4>{body}</div>",
        unsafe_allow_html=True)

# ── the cards ────────────────────────────────────────────────────────────────

def tile(r: meaning.Reading) -> str:
    cls = {meaning.OK: "", meaning.STALE: "mb-stale", meaning.GONE: "mb-gone"}[r.state]
    age = (f" · as of {meaning.short(r.as_of)}" if r.as_of else "")
    return (
        f"<div class='mb-tile {cls}'>"
        f"<div class='mb-label'>{r.signal.label}</div>"
        f"<div class='mb-value'>{r.shown}</div>"
        f"<div class='mb-basis'>{r.signal.basis}{age}</div>"
        f"<div class='mb-text'>{meaning.clause(r, B)}</div>"
        f"</div>")


st.markdown("### The numbers")
cols = st.columns(2)
for i, question in enumerate(registry.QUESTIONS):
    with cols[i % 2]:
        body = "".join(tile(READINGS[s.key]) for s in registry.for_question(question))
        st.markdown(f"<div class='mb-card'><div class='mb-q'>{question}</div>"
                    f"{body}</div>", unsafe_allow_html=True)

# ── what we cannot say today ─────────────────────────────────────────────────
#
# A board that only shows what it knows reads as a board that knows everything.
gaps = [r for r in READINGS.values() if r.state != meaning.OK]
with st.expander(f"What this page cannot say today ({len(gaps)})", expanded=False):
    if not gaps:
        st.markdown("Every signal is current.")
    for r in gaps:
        st.markdown(f"- **{r.signal.label}** — {meaning.clause(r, B)}")

# ── provenance, and the honest depth statement ───────────────────────────────
with st.expander("Where every figure comes from, and how far back it goes"):
    st.markdown(
        "**History is uneven and the differences are large.** Measured by live "
        "probe on 2026-10-07, not inferred from how old a report looks. Cash "
        "runs 22 years and the feeder index 11.75; CME cattle **futures reach "
        "back only to 2021-10-08** — five years, a hard floor, with no "
        "continuous series available at any depth. So a study of what a reading "
        "has meant can speak to cash and the index over two decades and to "
        "futures only over five, and this page will label which."
    )
    rows = ["| Signal | Source | Backtest depth |", "|---|---|---|"]
    for s in registry.SIGNALS:
        rows.append(f"| {s.label} | {s.source} | **{s.depth}** — {s.depth_note} |")
    st.markdown("\n".join(rows))
    if B.get("book_reconciles") is False:
        st.warning("The forward book's sixteen monthly totals no longer sum to "
                   "USDA's published figure. The delivery-month rows may have "
                   "shifted; treat the book tile as unverified.")
