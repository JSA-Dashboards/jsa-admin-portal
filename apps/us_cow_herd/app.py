"""
US Cow Herd -- is the breeding herd expanding or liquidating?

The definitive answer is NASS January 1 inventory: beef cows and beef
replacement heifers, published once a year. For ten months of the year this
page therefore runs on a proxy, and the proxy is chosen to be a good one rather
than merely available: AMS replacement-cattle auction reports, weekly, priced
by the people actually buying and selling breeding females.

The headline is a RATIO, not a price. A bred female is worth either what a
neighbour will pay for her bred or what the packer will pay for her by the
pound, and the relationship between those two IS the retention decision. Both
sides roughly tripled from 2020 to 2026, so the dollar premium mostly tracks
the market level; the ratio controls for that and still rose from 1.21 to 1.44.

Analytics live in herd.py, which is import-safe (no requests) so this page
never pulls the ingest's HTTP stack into the Streamlit process. Ingest is
replacement_reports.py in the cme-feeder-cattle-index repo.
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Streamlit puts the MAIN script's directory on sys.path, never the page's, so
# a multipage app's own sibling modules are not importable without this. Same
# line the cme_feeder_cattle page carries, for the same reason.
sys.path.insert(0, str(Path(__file__).parent))

import snowflake_db as db
from herd import (BASELINE_YEARS, LEGACY_LAST_GOOD_WEEK, YTD_CUT, annual_ratio,
                  annual_span, MAX_PAIR_GAP_DAYS, SCHEMA as HERD_SCHEMA,
                  class_prices, decompose, heifer_share_annual,
                  heifer_share_rolling, heifer_share_summary, heifer_share_thin,
                  receipts_volume_annual,
                  latest_date,
                  receipts_yoy)
import expansion
import southeast
from dairy_mix import (ASSUMED_DAIRY_NOW, ASSUMED_DAIRY_THEN,
                       ASSUMED_HEIFER_FRAC)
from dairy_mix import adjust as dm_adjust
from dairy_mix import implied_dairy_share as dm_implied
from inventory import inventory_summary
from on_feed import on_feed_summary

# ── JSA Brand Colors (shared with the rest of the portal shell) ──────────────
JPSI_DARK = "#32373c"
JPSI_BLUE = "#0693e3"
BG        = "#f6f8f7"
CARD_BG   = "#ffffff"
SURFACE2  = "#eef3f0"
BORDER    = "#d7e2dc"
MUTED     = "#5f7267"
TEXT      = "#32373c"
POS       = "#16a34a"
NEG       = "#dc2626"
NEU       = "#5f7267"

JSA_LOGO = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"
DB_PATH = Path(__file__).parent / "data" / "mars_history.db"

st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{
    background-color:{BG}; color:{TEXT};
  }}
  [data-testid="stSidebar"] {{
    background-color:{SURFACE2}; border-right:1px solid {BORDER};
  }}
  .tile {{
    background:{CARD_BG}; border:1px solid {BORDER};
    border-top:3px solid {JPSI_BLUE}; border-radius:10px;
    padding:16px 20px; text-align:center; height:100%;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .tile-label {{
    color:{MUTED}; font-size:0.68rem; text-transform:uppercase;
    letter-spacing:0.09em; margin-bottom:6px;
  }}
  .tile-value {{
    color:{TEXT}; font-size:1.7rem; font-weight:700; line-height:1.1;
  }}
  .tile-delta-pos {{ color:{POS}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neg {{ color:{NEG}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neu {{ color:{NEU}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .sec-header {{
    color:{MUTED}; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:0.1em; padding:8px 0 4px; border-bottom:1px solid {BORDER};
    margin-bottom:10px;
  }}
  hr {{ border-color:{BORDER}; }}
  #MainMenu, footer {{ visibility:hidden; }}
  .stDeployButton {{ display:none; }}
  div[class*="st-key-wm-"] {{ position:relative; }}
  div[class*="st-key-wm-"]::after {{
    content:"";
    position:absolute; inset:0; margin:auto;
    width:50%; height:110px; max-width:320px;
    background-image:url('{JSA_LOGO}');
    background-size:contain; background-repeat:no-repeat; background-position:center;
    opacity:0.05; pointer-events:none; z-index:3;
  }}
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def tile(label, value, delta=""):
    return (f'<div class="tile"><div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>{delta}</div>')


def pct_delta(val, suffix=""):
    if val is None or pd.isna(val):
        return '<div class="tile-delta-neu">—</div>'
    sign = "▲" if val > 0 else ("▼" if val < 0 else "")
    kind = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    return f'<div class="tile-delta-{kind}">{sign} {abs(val):.1f}%{suffix}</div>'


def pt_delta(val, suffix=""):
    """Points, not percent -- the ratio moves in points and calling that a
    percentage change would overstate it by a factor of about four."""
    if val is None or pd.isna(val):
        return '<div class="tile-delta-neu">—</div>'
    sign = "▲" if val > 0 else ("▼" if val < 0 else "")
    kind = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    return f'<div class="tile-delta-{kind}">{sign} {abs(val):.2f}{suffix}</div>'


# ── Data ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_all(schema=HERD_SCHEMA):
    """
    Everything the page needs, in one connection. Returns None on any failure
    so the page can say so plainly rather than half-rendering.

    `schema` is never read. It is herd.SCHEMA, passed in purely so that a change
    to herd.py lands in this function's cache key -- st.cache_data keys on this
    function's own code and arguments and is blind to the module it calls, so
    without it a reshaped return value is served from a cache built before the
    reshape, and the page renders the old numbers with nothing raising.

    IT HAS TO BE PASSED AT THE CALL SITE, which it was not until 2026-10-07.
    Only arguments the caller actually supplies are hashed; a DEFAULT is not
    part of the key at all, so `load_all()` against `schema=HERD_SCHEMA` keyed
    nothing and bumping herd.SCHEMA did nothing. The name was right here from
    the start -- it is the call that was missing, which is the harder half to
    notice.
    """
    if not db.use_snowflake() and not DB_PATH.exists():
        return None
    conn = db.get_conn()
    try:
        return {
            "latest": latest_date(conn),
            "current": decompose(conn),
            "annual": annual_ratio(conn),
            "span": annual_span(conn, (latest_date(conn) or "0")[:4]),
            # Read on the page's one connection and cached with everything
            # else, rather than re-queried on every widget interaction.
            "southeast": southeast.load(conn),
            # Computed here rather than in the view branch so it shares the
            # page's one connection and the same hour-long cache. It adds two
            # NASS calls that the sections further down this page already make.
            "expansion": expansion.load(conn),
            "classes": class_prices(conn),
            "receipts": receipts_yoy(conn),
        }
    except Exception:
        return None
    finally:
        conn.close()


@st.cache_data(ttl=3600, show_spinner=False)
def load_inventory():
    """The head counts. Same contract as load_on_feed: reason up, never a bare None."""
    try:
        return {"ok": inventory_summary()}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@st.cache_data(ttl=3600, show_spinner=False)
def load_on_feed():
    """
    The feedlot-side read, from the shared NASS cache rather than Snowflake's
    CME_FEEDER_CATTLE schema. Loaded on its own for the same reason the receipts
    section is: a different backend, and a failure here should cost one panel
    rather than the page.

    Returns {"ok": summary} or {"error": reason}. The reason is carried up rather
    than swallowed: nass_cache_client raises on a genuine backend failure
    precisely so a misconfigured secret is loud, and catching that to a bare None
    would delete this panel with no explanation. That is not hypothetical -- it
    is how the SNOWFLAKE_PRIVATE_KEY_PWD name mismatch hid itself the first time.
    An empty cache is different, and stays quiet.
    """
    try:
        return {"ok": on_feed_summary()}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@st.cache_data(ttl=3600, show_spinner=False)
def load_heifer_share():
    """
    The receipts-mix section, loaded SEPARATELY from load_all() on purpose.

    It reads a different table (`feeder_receipts`, from feeder_sex_mix.py), and
    folding it into load_all's try/except would mean a missing or empty table
    there takes down the retention-incentive half of the page too -- which is
    fed by a different ingest and would be perfectly healthy. Returning None
    here costs one section instead.
    """
    if not db.use_snowflake() and not DB_PATH.exists():
        return None
    conn = db.get_conn()
    try:
        summary = heifer_share_summary(conn)
        if not summary:
            return None
        return {"summary": summary, "annual": heifer_share_annual(conn),
                "rolling": heifer_share_rolling(conn),
                # Kept apart from "annual" all the way to the chart. Nothing
                # that computes a benchmark, a peak or a distance ever sees it.
                "thin": heifer_share_thin(conn),
                # Whole years and every week, unlike "annual" -- see the
                # function's docstring for why a level needs different rules
                # from a ratio.
                "volume": receipts_volume_annual(conn)}
    except Exception:
        return None
    finally:
        conn.close()


with st.spinner("Loading replacement-cattle reports…"):
    D = load_all(HERD_SCHEMA)

if not D or not D.get("current"):
    st.error("Could not load the replacement-cattle data.")
    st.caption(
        "This page reads the `replacement_sales` table, populated by "
        "`replacement_reports.py` in the cme-feeder-cattle-index repo and "
        "pushed to Snowflake by that repo's daily job."
    )
    st.stop()

cur = D["current"]

# ── Header ───────────────────────────────────────────────────────────────────
col_title, col_date = st.columns([6, 2])
with col_title:
    st.markdown("## JSA — US Cow Herd")
    st.caption("Herd expansion vs liquidation · AMS replacement-cattle auction reports")
with col_date:
    st.markdown(
        f"<div style='text-align:right;color:{MUTED};font-size:0.75rem;padding-top:6px;'>"
        f"Latest sale date<br>"
        f"<span style='color:{JPSI_BLUE};font-size:1rem;font-weight:700;'>"
        f"{pd.Timestamp(D['latest']).strftime('%b %d, %Y')}</span></div>",
        unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)


# ── Retention Incentive ──────────────────────────────────────────────────────
st.markdown('<div class="sec-header">Retention Incentive</div>', unsafe_allow_html=True)
st.caption(
    f"What a bred female is worth against what the packer would pay for the same "
    f"animal **at the same market**. Trailing **{cur['weeks']} weeks** "
    f"({cur['n_dates']} sale dates across {cur['n_barns']} markets, "
    f"{cur['bred_head']:,} bred head) — a single sale can swing the ratio 25 points "
    f"on quality mix alone, so the headline is a window rather than the latest print."
)

c = st.columns(4)
with c[0]:
    st.markdown(tile("Bred Female", f"${cur['bred']:,.0f}/hd",
                     pct_delta(cur.get("bred_yoy_pct"), " YoY")), unsafe_allow_html=True)
with c[1]:
    st.markdown(tile("Salvage Value", f"${cur['salvage']:,.0f}/hd",
                     pct_delta(cur.get("salvage_yoy_pct"), " YoY")), unsafe_allow_html=True)
with c[2]:
    st.markdown(tile("Premium", f"${cur['premium']:,.0f}/hd"), unsafe_allow_html=True)
with c[3]:
    st.markdown(tile("Ratio", f"{cur['ratio']:.2f}",
                     pt_delta(cur["ratio_vs_base"], " vs normal")), unsafe_allow_html=True)

st.caption(
    f"Normal for {BASELINE_YEARS[0]}–{BASELINE_YEARS[1]} is **{cur['base_ratio']:.2f}** "
    f"(n={cur['n_base']} sale dates). Salvage is converted to a per-head basis — bred "
    f"females trade per head, slaughter cows per hundredweight."
)

if cur.get("driver"):
    # A rising ratio means opposite things depending on which side moved, so
    # say which rather than leaving a reader to assume the flattering one.
    _up = cur["ratio_vs_base"] > 0
    st.info(
        f"**{'Retention pays more than normal' if _up else 'Retention pays less than normal'}** — "
        f"and it is {cur['driver']}: bred values {cur['bred_yoy_pct']:+.1f}% against "
        f"{cur['prior_year']} while salvage moved {cur['salvage_yoy_pct']:+.1f}%. "
        f"That distinction matters: the ratio rises either because producers are "
        f"bidding up breeding females or because packers stopped paying for cull cows, "
        f"and only the first is expansion."
    )


# ── Ratio Trend ──────────────────────────────────────────────────────────────
st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Retention Incentive by Year</div>',
            unsafe_allow_html=True)

_ann = D["annual"]

# A SWITCH, NOT ELEVEN MORE BARS ON THE SAME CHART. The twelve plains markets
# above did not report a bred cow to USDA before 2019 -- the legacy auction
# archive holds zero Oklahoma, zero Missouri and zero Texas bred-cow rows across
# 2000-2019 -- so their 2019 floor is permanent. Five southeastern barns did
# report throughout, and carry the measure back to 2008.
#
# They are kept on separate axes deliberately. The southeast-to-plains offset is
# tight over the overlap (about +0.25, sd 0.013) and looks subtractable; the one
# pre-2019 test of it has it wandering +0.085 to +0.312, wider than the plains
# series' whole modern range. Shifting one onto the other would be invented
# precision, and two ratio lines 0.25 apart on one axis is the
# letter-versus-dashboard failure this file records three times. The switch is
# the Cold Storage shape, and it is cheap here because the southeastern series
# is a 2KB precomputed file rather than a fetch.
_SE = D.get("southeast")
_PLAINS_VIEW = "Southern plains · 2019–2026"
_SE_VIEW = "Southeastern · 2008–2026"
_EXP_VIEW = "Did the herd expand? · 2008–2026"
_view = _PLAINS_VIEW
if _SE:
    _opts = [_PLAINS_VIEW, _SE_VIEW, _EXP_VIEW]
    _view = st.segmented_control(
        "Panel", _opts, default=_PLAINS_VIEW,
        label_visibility="collapsed", key="herd_ratio_panel") or _PLAINS_VIEW

_EXP = D.get("expansion")
if _view == _EXP_VIEW and not _EXP:
    _view = _PLAINS_VIEW          # the data did not come; do not show an empty frame

if _view == _SE_VIEW:
    _rows = [{"year": r["year"], "ratio": r["ratio"], "months": r["months"],
              "barns": r["barns"], "n": r["n"]} for r in _SE["series"]]
    _base_ratio = southeast.baseline(_SE["series"])
    _span = southeast.span(_SE["series"])
else:
    _rows = [{"year": int(a[0]), "ratio": a[1], "months": a[5], "barns": a[6],
              "n": a[4]} for a in _ann]
    _base_ratio = cur["base_ratio"]
    _span = D.get("span")

_last = _rows[-1]["year"] if _rows else None

# A TEN-MONTH BAR BESIDE TWELVE-MONTH BARS is a true number telling a false
# story. This ratio has close to a full point of swing inside a single year, so
# the part year is labelled with the months it actually covers rather than with
# its number alone -- the same reason YTD_CUT exists for the heifer-share chart
# further down this page.
_SHOW_BARS = _view != _EXP_VIEW
_labels = [(f"{r['year']}<br><span style='font-size:0.72em'>{_span[0]}–{_span[1]}</span>"
            if (_span and r["year"] == _last) else str(r["year"])) for r in _rows]

_fig = go.Figure()
_fig.add_trace(go.Bar(
    x=_labels, y=[r["ratio"] for r in _rows],
    marker_color=[JPSI_BLUE if r["year"] == _last else "#9fb8c8" for r in _rows],
    # INSIDE, not outside. Every year within a few points of normal puts its
    # value label at exactly the height of the dotted normal line, and the two
    # are then unreadable -- 1.22 read as 1.77 in a screenshot of this chart.
    # Drawing the labels inside the bars moves them off the line entirely
    # instead of fighting it with z-order, which does not help when the
    # collision is positional. Text colour is per bar because the highlighted
    # year is dark and the rest are light; one colour is illegible on one of them.
    text=[f"{r['ratio']:.2f}" for r in _rows], textposition="inside",
    insidetextanchor="end",
    textfont=dict(color=["#ffffff" if r["year"] == _last else TEXT for r in _rows],
                  size=12),
    customdata=[(r["months"], r["barns"], r["n"]) for r in _rows],
    hovertemplate="%{x}<br>ratio %{y:.2f}<br>"
                  "%{customdata[0]} months · %{customdata[1]} markets · "
                  "%{customdata[2]} barn sales<extra></extra>", name="ratio"))
# layer="below" so the dotted line passes BEHIND the bar labels. Any year
# sitting within a few points of normal puts its value label right on this
# line, and with the line drawn on top the digits are unreadable -- 1.22 read
# as 1.77 in a screenshot of this very chart. The years nearest normal are the
# ones a reader most wants to read.
_fig.add_hline(y=_base_ratio, line_dash="dot", line_color=MUTED, layer="below",
               annotation_text=f"{BASELINE_YEARS[0]}–{BASELINE_YEARS[1]} normal "
                               f"{_base_ratio:.2f}",
               annotation_position="bottom left")
# type="category" IS LOAD-BEARING -- the same trap beef_trade.annual_figure
# documents. Plotly type-sniffs the axis, and "2019".."2025" are all numeric
# strings, so it builds a LINEAR axis and the part-year label ("2026" plus a
# month span) has no numeric position: its bar is simply never drawn. It is not
# dropped either, which is what makes it nasty -- the trace still stretches the
# y-axis, so the chart reserves headroom for a bar nobody can see. Caught by
# loading the page; the data check and py_compile both passed.
_fig.update_layout(height=300, margin=dict(l=0, r=0, t=24, b=0),
                   plot_bgcolor="white", paper_bgcolor="white",
                   xaxis=dict(type="category"),
                   yaxis_title="bred value ÷ salvage value", showlegend=False)
# The floor was a hard 1.0. The ratio has no rule keeping it above parity -- a
# year where a bred female is worth less than her own salvage is exactly the
# signal this chart exists to show, and it would have been drawn as a zero-height
# bar. It adapts now.
_fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9",
                  range=[min(1.0, min(r["ratio"] for r in _rows) - 0.05),
                         max(r["ratio"] for r in _rows) * 1.12])
if _SHOW_BARS:
    # SHADE THE YEARS THE HERD ACTUALLY GREW, behind the bars. USDA's January 1
    # beef cow count, not a signal -- see expansion.py. Drawn by finding runs of
    # consecutive expansion years and shading each run, so a future expansion
    # appears here on its own without anyone editing a date in.
    #
    # ON THE PLAINS VIEW THIS IS CURRENTLY EMPTY, and that is the finding rather
    # than a bug: the last expansion ran 2014-2018 and this panel starts in
    # 2019, so every year it shows is a liquidation year. The caption says so.
    # The moment a year in range turns, the band draws itself.
    _grew = {r["year"] for r in (_EXP or []) if r["expanded"]}
    _idx = {r["year"]: i for i, r in enumerate(_rows)}
    _run = []
    for _y in sorted(_grew & set(_idx)):
        if _run and _y == _run[-1][-1] + 1:
            _run[-1].append(_y)
        else:
            _run.append([_y])
    for _k, _block in enumerate(_run):
        _fig.add_vrect(
            x0=_idx[_block[0]] - 0.5, x1=_idx[_block[-1]] + 0.5,
            fillcolor=POS, opacity=0.08, line_width=0, layer="below",
            annotation_text="herd expanded" if _k == 0 else None,
            annotation_position="top left",
            annotation_font=dict(size=11, color=MUTED))
    st.plotly_chart(_fig, use_container_width=True)
_lo_sal = min(_ann, key=lambda a: a[3])
_part = (f"**{_last} covers {_span[0]}–{_span[1]} only** and is not a whole-year "
         f"figure. " if _span else "")

# Shaded years are the ones USDA's count later showed the herd grew. Saying so
# only when there are none would leave the shading unexplained when there are;
# saying it only when there are some would leave an all-liquidation chart
# looking like the band had been forgotten. Both cases get a sentence.
_shaded = sorted({r["year"] for r in (_EXP or []) if r["expanded"]}
                 & {r["year"] for r in _rows})
if _shaded:
    _herd_note = (f" Shaded years are the ones the herd actually grew, on USDA's "
                  f"January 1 beef cow count: **{_shaded[0]}–{_shaded[-1]}**.")
elif _EXP:
    _herd_note = (
        " **No year on this chart was a national herd expansion.** USDA's "
        "January 1 beef cow count fell every year from 2019, so there is nothing "
        "to shade — the last national expansion ran 2014–2018, before this panel "
        "begins, and the southeastern view reaches it. "
        "Note this is the NATIONAL count. The four states these barns sit in "
        "(OK, MO, KS, MT) do not move with it — their herd grew 1.2% in 2024 "
        "while the national one fell — but the page cannot show that: state-level "
        "beef cow inventory is not in the NASS cache this page reads, and nothing "
        "here fetches NASS live by design.")
else:
    _herd_note = ""
if _view == _EXP_VIEW:
    # TWO FRAMES, NOT ONE, AND DELIBERATELY NOT A DUAL AXIS. The retention
    # incentive is a ratio near 1.0; the other two are percentages near 40. On
    # a shared axis one of them flattens to nothing, and a secondary axis lets
    # whoever picks the scales draw whatever relationship they like. Same x,
    # two frames, each honest about its own units.
    _er = [r for r in _EXP if r["ret"] is not None]
    _yrs = [r["year"] for r in _er]
    _col = {True: JPSI_BLUE, False: "#9fb8c8", None: "#e0a33a"}

    _f1 = go.Figure()
    _f1.add_trace(go.Bar(
        x=_yrs, y=[r["ret"] for r in _er],
        marker_color=[_col[r["expanded"]] for r in _er],
        text=[f"{r['ret']:.2f}" for r in _er], textposition="inside",
        insidetextanchor="end",
        textfont=dict(color=["#ffffff" if r["expanded"] is not False else TEXT
                             for r in _er], size=11),
        customdata=[[("expanded" if r["expanded"] else "contracted")
                     if r["expanded"] is not None else "not yet counted"]
                    for r in _er],
        hovertemplate="%{x}<br>retention %{y:.3f}"
                      "<br>herd %{customdata[0]}<extra></extra>", name="ratio"))
    # A BAND, NOT A LINE. The cut is fitted on these same 18 years with one free
    # parameter; refitting it without each year in turn moves it between 1.064
    # and 1.102. A hairline would claim a precision the fit has not got -- the
    # same reason the southeastern panel is never shifted onto the plains axis.
    _f1.add_hrect(y0=expansion.CUT_BAND[0], y1=expansion.CUT_BAND[1],
                  fillcolor=MUTED, opacity=0.13, line_width=0, layer="below",
                  annotation_text="above this band the herd has usually grown",
                  annotation_position="top left",
                  annotation_font=dict(size=11, color=MUTED))
    _f1.update_layout(height=280, margin=dict(l=0, r=0, t=24, b=0),
                      plot_bgcolor="white", paper_bgcolor="white",
                      xaxis=dict(type="category"), showlegend=False,
                      yaxis_title="bred value \u00f7 salvage value")
    _f1.update_yaxes(showgrid=True, gridcolor="#f1f5f9",
                     range=[min(r["ret"] for r in _er) - 0.06,
                            max(r["ret"] for r in _er) * 1.10])
    st.plotly_chart(_f1, use_container_width=True)

    _f2 = go.Figure()
    _f2.add_trace(go.Scatter(
        x=_yrs, y=[r["hs"] for r in _er], mode="lines+markers",
        name="heifer share of feeder receipts",
        line=dict(color=JPSI_BLUE, width=2), connectgaps=False,
        hovertemplate="%{x}<br>heifer share of receipts %{y:.1f}%<extra></extra>"))
    _f2.add_trace(go.Scatter(
        x=_yrs, y=[r["of"] for r in _er], mode="lines+markers",
        name="heifers on feed",
        line=dict(color=MUTED, width=2, dash="dot"),
        hovertemplate="%{x}<br>heifers on feed %{y:.1f}%<extra></extra>"))
    _f2.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0),
                      plot_bgcolor="white", paper_bgcolor="white",
                      xaxis=dict(type="category"),
                      yaxis_title="per cent \u2014 falling means heifers kept back",
                      legend=dict(orientation="h", y=1.2, x=0, font=dict(size=11)))
    _f2.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
    st.plotly_chart(_f2, use_container_width=True)

    _open = [r for r in _er if r["expanded"] is None]
    _s = expansion.SCORE
    st.caption(
        f"**Blue years are ones the herd actually grew** \u2014 USDA's January 1 "
        f"beef cow count, which is not a signal but the thing the signals are "
        f"guessing at. A year is scored against the NEXT January's count, "
        f"because decisions taken in a year show up in the following one's "
        f"inventory. The retention incentive moves with that change at "
        f"**r = +0.87** across {_s['n']} years, which needs no threshold and is "
        f"the honest headline. "
        f"**The band is fitted and is reported as fitted.** One cut gets "
        f"{_s['in_sample']} of {_s['n']} years right in-sample \u2014 but "
        f"refitting it without each year and then predicting that year gives "
        f"**{_s['out_of_sample']} of {_s['n']}**, against {_s['null']} for simply "
        f"saying the herd shrinks every year. Two years of edge is real and is "
        f"not a rule to trade on by itself. Heifer share and heifers on feed "
        f"have cuts of the same kind near 40.8% and 35.9%, and all three "
        f"together score no better than retention alone \u2014 so what the other "
        f"two add is their disagreement, not a vote."
        + (f" **{_open[0]['year']} reads {_open[0]['ret']:.2f}**, above the band, "
           f"while both volume lines are still on the contraction side. That "
           f"split has happened twice, in 2018 and 2019, and the herd went a "
           f"different way each time. The January {_open[0]['year'] + 1} count "
           f"settles it." if _open else "")
    )

elif _view == _SE_VIEW:
    # Computed, never asserted. The first version of this caption said
    # "2010-2012 is the trough of the whole record", which was true of an
    # earlier five-barn panel and false of this one -- 2023 and 2022 are both
    # lower than 2011. A sentence about where the high and low sit has to be
    # read off the series it sits under, or it goes stale the moment the panel
    # changes and nothing raises.
    _se_lo = min(_rows, key=lambda r: r["ratio"])
    _se_hi = max(_rows, key=lambda r: r["ratio"])
    _se_now = _rows[-1]
    _vs_now = ("above" if _se_hi["ratio"] > _se_now["ratio"] else "below")
    st.caption(
        f"**{len(_SE['panel'])} southeastern barns — {', '.join(_SE['panel'])} — "
        f"not the twelve markets above.** Median of every barn sale in the year, "
        f"bred and salvage from the same market, and every one of these barns "
        f"reports in every year shown. {_part}"
        f"These are different cattle in a different region, so **read the shape, "
        f"not the level**: do not compare a number here with a number on the "
        f"southern-plains view. The gap between the two panels is not a constant — "
        f"measured before 2019 it runs anywhere from 0.09 to 0.31 — so no single "
        f"offset puts them on one axis. What this view is for is the years the "
        f"plains feed cannot reach: the record high is **{_se_hi['year']}** at "
        f"{_se_hi['ratio']:.2f}, {_vs_now} today's {_se_now['ratio']:.2f}, and the "
        f"low is **{_se_lo['year']}** at {_se_lo['ratio']:.2f}. "
        f"2008–2018 is USDA's legacy auction archive and 2019 onward is the live "
        f"feed; where a barn is carried by both, the live feed wins from its first "
        f"sale, so no week is counted twice."
        + _herd_note
    )
else:
    st.caption(
        f"Median of every barn sale in the year, with the bred and the salvage side "
        f"taken from the **same market**. Coverage begins {_rows[0]['year']} — these "
        f"twelve markets reported no bred cows to USDA before then, so there is "
        f"nothing earlier to show. {_part}"
        f"The lowest salvage year is **{_lo_sal[0]}**, at ${_lo_sal[3]:,.0f} a head: "
        f"a high ratio in a year like that says what packers were paying, not what "
        f"producers wanted, which is why the banner above always names the side that "
        f"moved."
        + _herd_note
    )

with st.expander("ℹ️  How to read the retention incentive"):
    # THE BACKSLASHES BEFORE EACH $ ARE LOAD-BEARING. Streamlit renders $...$ as
    # inline LaTeX, so two unescaped dollar amounts in one markdown block open a
    # math span: the dollar signs vanish and the ** bold markers between them are
    # left stranded in the text. It read "a bred female brings 2,430** while the
    # same animal's salvage value is **1,603" on the live page. A single dollar
    # sign in a block is safe, which is why the captions elsewhere get away with
    # it -- but do not rely on that when adding a second.
    st.markdown(f"""
**The question it answers.** A producer holding a cow can sell her bred to a
neighbour, or ship her to the packer. Whichever pays more is what tends to
happen, in aggregate, and that decision is what grows or shrinks the national
herd. This ratio prices that choice every week.

**Today:** a bred female brings **\\${cur['bred']:,.0f}** while the same animal's
salvage value is **\\${cur['salvage']:,.0f}** — a ratio of **{cur['ratio']:.2f}**
against a {BASELINE_YEARS[0]}–{BASELINE_YEARS[1]} normal of
**{cur['base_ratio']:.2f}**.

**Why the ratio and not the premium.** Bred values are {_ann[-1][2] / _ann[0][2]:.1f}×
their {_ann[0][0]} level and salvage {_ann[-1][3] / _ann[0][3]:.1f}×, so the dollar
premium mostly measures the bull market. The ratio controls for that level, and it
still ran from {min(a[1] for a in _ann):.2f} to {max(a[1] for a in _ann):.2f} across
the same span — a real change in the incentive rather than in the price of cattle.

**Why the driver matters.** The ratio rises when bred values climb *or* when
salvage falls, and those are opposite stories. The weakest salvage year here is
{_lo_sal[0]} at \\${_lo_sal[3]:,.0f} a head, and its ratio of {_lo_sal[1]:.2f} is
mostly packers retreating rather than producers expanding. The banner above always
names which side moved.

**Both sides come from one market.** A bred female is priced against the cull
cows sold at the same barn, within {MAX_PAIR_GAP_DAYS} days — 96% of the time on
the same day. Until October 2026 this page divided one barn's bred females by
whatever other barn reported a cull price that day, because five of these markets
sell their breeding stock at a Replacement Special that carries no slaughter side.
{", ".join(cur["unpairable"])} reports bred females and no cull cows at all, and
has no companion sale, so it is not in the ratio.

**What it is not.** It is a price signal, not a head count. It tells you what
the incentive to retain looks like, not how many females were actually kept.
The NASS January 1 inventory is the only thing that measures that, and it
arrives once a year.
""")


# ── Breeding Female Prices ───────────────────────────────────────────────────
st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Breeding Female Prices</div>',
            unsafe_allow_html=True)
st.caption(
    f"Trailing {cur['weeks']} weeks against the same weeks a year earlier (52 weeks "
    f"back, so the comparison lands on the same point in the sale calendar). "
    f"**Per-pair prices include the calf** and are shown on their own basis — "
    f"averaging them with single females would overstate the market."
)

_rows = []
for r in D["classes"]:
    if r["head"] < 5:
        continue           # a one-head lot is an anecdote, not a price
    _rows.append({
        "Class": r["class"],
        "Basis": r["basis"],
        "Price": f"${r['price']:,.0f}",
        "Head": f"{r['head']:,}",
        "Year Ago": f"${r['year_ago']:,.0f}" if r["year_ago"] else "—",
        "YoY": f"{r['yoy_pct']:+.1f}%" if r["yoy_pct"] is not None else "—",
    })
if _rows:
    with st.container(key="wm-classes"):
        st.dataframe(pd.DataFrame(_rows), use_container_width=True,
                     hide_index=True, height=min(300, 60 + 35 * len(_rows)))

# Bred heifers over bred cows is the sharper expansion signal: it is money paid
# specifically for a young female entering the herd rather than for one already
# in it.
_bh = next((r for r in D["classes"] if r["class"] == "Bred Heifers"), None)
_bc = next((r for r in D["classes"] if r["class"] == "Bred Cows"), None)
if _bh and _bc and _bh["head"] >= 5 and _bc["head"] >= 5:
    _gap = _bh["price"] - _bc["price"]
    st.caption(
        f"**Bred heifers are {'above' if _gap > 0 else 'below'} bred cows by "
        f"\\${abs(_gap):,.0f}/hd** (\\${_bh['price']:,.0f} against "
        f"\\${_bc['price']:,.0f}). Heifers are the sharper expansion signal — that is "
        f"money paid for a female *entering* the herd rather than one already in it."
    )


# ── Receipts ─────────────────────────────────────────────────────────────────
_rc = D.get("receipts")
if _rc:
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Replacement Auction Receipts</div>',
                unsafe_allow_html=True)
    r1, r2, r3 = st.columns(3)
    with r1:
        st.markdown(tile(f"Receipts, {_rc['weeks']} Wks", f"{_rc['receipts']:,}"),
                    unsafe_allow_html=True)
    with r2:
        st.markdown(tile("Year Ago", f"{_rc['year_ago']:,}",
                         pct_delta(_rc["pct"])), unsafe_allow_html=True)
    with r3:
        st.markdown(tile("Reports", f"{_rc['n_reports']:,}"), unsafe_allow_html=True)
    st.caption(
        "Total head through these auctions, using each report's OWN year-ago "
        "receipts figure rather than our stored history — so the comparison is "
        "AMS's like-for-like and holds even where our archive has a gap. Falling "
        "receipts alongside rising bred prices is the classic tight-supply "
        "signature: fewer females offered, bid harder."
    )


# ── Heifer Share of Feeder Receipts ──────────────────────────────────────────
# The volume-side read, and the counterpart to everything above it: the ratio
# section prices the retention DECISION, this shows what producers did about it.
HS = load_heifer_share()
if HS:
    _sum = HS["summary"]
    _cur, _lo, _hi = _sum["current"], _sum["low"], _sum["high"]

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Heifer Share of Feeder Receipts</div>',
                unsafe_allow_html=True)
    st.caption(
        f"Heifers as a share of steer + heifer feeder cattle sold, across **all "
        f"three channels** — sale barn, direct country trade and video/internet "
        f"auction — year-to-date through week {YTD_CUT} of every year. When "
        f"producers keep heifers back to breed, those heifers stop being sold "
        f"at all, so a **falling** share is retention. Unlike the ratio above, "
        f"this measures what was done rather than what it paid to do."
    )

    h = st.columns(4)
    with h[0]:
        _since = (f'<div class="tile-delta-pos">▼ lowest since {_sum["since"]}</div>'
                  if _sum["since"] else '<div class="tile-delta-neu">—</div>')
        st.markdown(tile(f"Heifer Share, {_cur['year']}", f"{_cur['share']:.1f}%", _since),
                    unsafe_allow_html=True)
    with h[1]:
        st.markdown(tile("Cycle Peak", f"{_hi['share']:.1f}%",
                         f'<div class="tile-delta-neu">{_hi["year"]}</div>'),
                    unsafe_allow_html=True)
    with h[2]:
        st.markdown(tile("Last Rebuild Low", f"{_lo['share']:.1f}%",
                         f'<div class="tile-delta-neu">{_lo["year"]}</div>'),
                    unsafe_allow_html=True)
    with h[3]:
        # The basis travels with the figure rather than sitting in a footnote,
        # because a footnote is separated from it the moment someone screenshots
        # the tiles.
        #
        # The subtitle used to read "feedlot survey reads further", which was
        # true while this was auction-only and read 0.64 points. On all three
        # channels it reads about 3, which is close to the feedlot figure -- so
        # the old line would now assert a disagreement that has largely closed.
        # It says what it measures instead, and the prose below does the
        # comparing where it can be qualified.
        st.markdown(tile(f"Distance To {_lo['year']} — Receipts Basis",
                         f"{_sum['gap_to_low']:.2f} pts",
                         '<div class="tile-delta-neu">all three sale '
                         'channels</div>'), unsafe_allow_html=True)

    _ann = HS["annual"]
    _yrs = [r["year"] for r in _ann]
    _shs = [r["share"] for r in _ann]
    # The spliced year is drawn in a muted colour rather than hidden: it is a
    # real reading, but it is the one point built from two archives.
    _colors = [POS if r["year"] == _cur["year"]
               else ("#9fb8c8" if r["src"] == "spliced" else JPSI_BLUE) for r in _ann]
    _sizes = [14 if r["year"] == _cur["year"]
              else (11 if r["year"] in (_hi["year"], _lo["year"]) else 7) for r in _ann]

    # The under-covered early years, drawn DETACHED -- no segment joins 2004 to
    # 2005, because the break is the message. They are the same measurement on a
    # smaller and shifting set of states (12 in 2000, 16 by 2004), so the level
    # is not comparable even though each year is internally sound. Dashed, grey,
    # hollow markers, no fill: every cue says "read these apart".
    _thin = HS.get("thin") or []
    _tyrs = [r["year"] for r in _thin]
    _tshs = [r["share"] for r in _thin]

    _f1 = go.Figure()
    if _thin:
        _f1.add_trace(go.Scatter(
            x=_tyrs, y=_tshs, mode="lines+markers",
            name=f"{_tyrs[0]}–{_tyrs[-1]} · {min(r['states'] for r in _thin)}–"
                 f"{max(r['states'] for r in _thin)} states",
            line=dict(color="#94a3b8", width=1.8, dash="dot"),
            marker=dict(size=7, color="#ffffff",
                        line=dict(color="#94a3b8", width=1.8)),
            hovertemplate="%{x}<br>heifer share %{y:.2f}%"
                          "<br><i>fewer reporting states</i><extra></extra>"))
    _f1.add_trace(go.Scatter(x=_yrs, y=_shs, mode="lines", fill="tozeroy",
                             fillcolor="rgba(6,147,227,0.08)",
                             name=f"{_yrs[0]}–{_yrs[-1]} · full panel",
                             line=dict(color=JPSI_BLUE, width=2.5),
                             hovertemplate="%{x}<br>heifer share %{y:.2f}%<extra></extra>"))
    _f1.add_trace(go.Scatter(x=_yrs, y=_shs, mode="markers", hoverinfo="skip",
                             showlegend=False,
                             marker=dict(size=_sizes, color=_colors,
                                         line=dict(color="#ffffff", width=2))))
    _f1.add_hline(y=_lo["share"], line_dash="dot", line_color=POS)
    # The basis is named on both charts' peaks and axes. Without it the two
    # sections read as disagreeing about the same number: this one peaks at
    # 47.5% and the rolling one at 46.6%, because heifer share runs about three
    # points lighter in the autumn run and a trailing-year window always
    # contains one while a January-September window never does.
    _f1.add_annotation(x=_hi["year"], y=_hi["share"], xanchor="left", ax=6, ay=-32,
                       text=f"<b>{_hi['share']:.1f}%</b> peak liquidation (Jan–Sep)",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f1.add_annotation(x=_lo["year"], y=_lo["share"], ax=0, ay=40,
                       text=f"<b>{_lo['share']:.1f}%</b> last rebuild",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f1.add_annotation(x=_cur["year"], y=_cur["share"], ax=-14, ay=34,
                       text=f"<b>{_cur['share']:.1f}%</b>", showarrow=True,
                       arrowhead=0, arrowcolor=POS, font=dict(size=13, color=TEXT))
    # A legend only once there are two series to tell apart, and never as the
    # sole cue: the early years are also dashed, grey and detached.
    _f1.update_layout(height=380, margin=dict(l=0, r=10, t=44 if _thin else 30, b=0),
                      plot_bgcolor="white", paper_bgcolor="white",
                      showlegend=bool(_thin),
                      legend=dict(orientation="h", yanchor="bottom", y=1.04,
                                  xanchor="left", x=0, font=dict(size=11),
                                  bgcolor="rgba(0,0,0,0)"),
                      yaxis_title=f"heifer share, Jan–mid-Sep (weeks 1–{YTD_CUT})")
    # Ranges span BOTH series, so adding the early years cannot clip them.
    _allsh = _shs + _tshs
    _allyr = _tyrs + _yrs
    _f1.update_yaxes(showgrid=True, gridcolor="#f1f5f9", ticksuffix="%",
                     range=[min(_allsh) - 1.2, max(_allsh) + 1.1])
    _f1.update_xaxes(showgrid=False, tickvals=[y for i, y in enumerate(_allyr)
                                               if i % 2 == 0 or y == _cur["year"]])
    with st.container(key="wm-heifer-annual"):
        st.plotly_chart(_f1, use_container_width=True)

    _chg = ""
    if _sum["heifer_chg"] is not None and _sum["steer_chg"] is not None:
        _dir = "up" if _sum["steer_chg"] > 0 else "down"
        # The reading DEPENDS ON THE SIGN and must not be written down as if it
        # did not. This sentence used to end "the decline is females only",
        # which was true on auction receipts, where steers rose while heifers
        # fell. On all three channels both fall, and the claim became false the
        # moment the basis changed -- so the conclusion is derived from the
        # numbers rather than asserted alongside them.
        #
        # Both falling is not the same finding: it is consistent with retention
        # AND with a smaller calf crop, and only the ratio separates them.
        _both_down = _sum["steer_chg"] < 0
        _tail = ("both are falling, so this says the mix shifted rather than "
                 "that supply did — heifers are leaving the sale faster than "
                 "steers, which is retention on top of a smaller calf crop"
                 if _both_down else
                 "the decline is females only, which is what retention looks "
                 "like and what a general contraction in cattle numbers "
                 "would not")
        _chg = (f" Against {_sum['chg_base_year']}, heifer receipts are down "
                f"**{abs(_sum['heifer_chg']):,}** head while steer receipts are "
                f"*{_dir}* **{abs(_sum['steer_chg']):,}** — {_tail}.")
    # Derived, not hard-coded: a deployment without the legacy archive loaded
    # has no spliced year at all, and the caption should not claim one.
    _spl = [r["year"] for r in _ann if r["src"] == "spliced"]
    _spl_txt = ""
    if _spl:
        _spl_txt = (
            f" **{_spl[0]} is spliced** — USDA retired the archive behind the early "
            f"years mid-year and stood up its replacement in the same weeks, so that "
            f"point takes the weeks through {LEGACY_LAST_GOOD_WEEK} from one and the "
            f"rest from the other; the two halves agree to within 0.26 points.")
    st.caption(
        f"Each point covers the same weeks of its year, across all three sale "
        f"channels and the {min(r['states'] for r in _ann)}–"
        f"{max(r['states'] for r in _ann)} auction panel states reporting in it. "
        f"2020 is absent rather than missing: the direct channel changed archive "
        f"in September of that year, past this window, so no honest point exists."
        + (f" The grey {_tyrs[0]}–{_tyrs[-1]} segment is drawn apart because only "
           f"{min(r['states'] for r in _thin)}–{max(r['states'] for r in _thin)} "
           f"states reported then, and the video channel covered as few as "
           f"{min(r['weeks'] for r in _thin)} of the {YTD_CUT} weeks: each year is "
           f"sound on its own — the gaps are scattered, not seasonal, worth under "
           f"a third of a point — but the level is not comparable with the rest, "
           f"so no line joins them." if _thin else "")
        + f"{_spl_txt}{_chg}"
    )

    # ---- receipts VOLUME: whole-year head, the share's own numerator ----
    #
    # ANNUAL TOTALS, NOT HEAD PER WEEK. The first version of this normalised by
    # reporting week so the Jan-Sep window's 30-37 weeks stayed comparable. That
    # was a defensible statistic and the wrong chart: a cattleman wants to know
    # how many head sold, and the short window amputates the autumn run, which is
    # when a third of the year's cattle move. On full years the retention
    # signature reads more clearly too -- 2015 shows steers RISING 1.1% while
    # heifers fell 7.4%, which the Jan-Sep window had shown as steers -2.2%.
    #
    # The current year is partial and is drawn as such rather than rescaled:
    # annualising it would mean assuming the seasonal pattern it has not reached.
    _vol = HS.get("volume") or []
    if len(_vol) > 4:
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        st.markdown('<div class="sec-header">Receipts Volume</div>',
                    unsafe_allow_html=True)


        _part = [r for r in _vol if not r["complete"]]
        _fv = go.Figure()
        for _era in ("legacy", "mars"):
            _seg = [r for r in _vol
                    if r["era"] == _era and r["complete"] and not r["thin"]]
            if not _seg:
                continue
            for _k, _col, _nm in (("steers", JPSI_BLUE, "steers"),
                                  ("heifers", POS, "heifers")):
                _fv.add_trace(go.Scatter(
                    x=[r["year"] for r in _seg],
                    y=[r[_k] / 1e6 for r in _seg],
                    mode="lines+markers", name=_nm, legendgroup=_nm,
                    showlegend=(_era == "legacy"),
                    line=dict(color=_col, width=2.5),
                    marker=dict(size=6, color=_col),
                    hovertemplate="%{x}<br>" + _nm + " %{y:.2f}M head<extra></extra>"))
        # The under-covered early years drawn APART, as on the share chart above.
        # Excluding them would be wrong -- a count from twelve states is a real
        # count -- but joining them to the rest asserts a comparability the
        # panel does not have: it fills from 12 states to 18 between 2000 and
        # 2005, and most of the "rise" across those years is that.
        _tv = [r for r in _vol if r["thin"] and r["complete"]]
        if _tv:
            for _k, _col, _nm in (("steers", JPSI_BLUE, "steers"),
                                  ("heifers", POS, "heifers")):
                _fv.add_trace(go.Scatter(
                    x=[r["year"] for r in _tv], y=[r[_k] / 1e6 for r in _tv],
                    mode="lines+markers", showlegend=False, legendgroup=_nm,
                    line=dict(color="#94a3b8", width=1.6, dash="dot"),
                    marker=dict(size=6, color="#ffffff",
                                line=dict(color="#94a3b8", width=1.6)),
                    hovertemplate="%{x}<br>" + _nm + " %{y:.2f}M head"
                                  "<br><i>fewer reporting states</i><extra></extra>"))

        # The partial year as hollow markers, joined to nothing.
        for _r in _part:
            for _k, _col in (("steers", JPSI_BLUE), ("heifers", POS)):
                _fv.add_trace(go.Scatter(
                    x=[_r["year"]], y=[_r[_k] / 1e6], mode="markers",
                    showlegend=False,
                    marker=dict(size=9, color="#ffffff",
                                line=dict(color=_col, width=2)),
                    hovertemplate="%{x} (partial, " + str(_r["weeks"])
                                  + " wks)<br>%{y:.2f}M head<extra></extra>"))
        _fv.update_layout(height=320, margin=dict(l=0, r=10, t=40, b=0),
                          plot_bgcolor="white", paper_bgcolor="white",
                          legend=dict(orientation="h", yanchor="bottom", y=1.04,
                                      xanchor="left", x=0, font=dict(size=11),
                                      bgcolor="rgba(0,0,0,0)"),
                          yaxis_title="million head sold, whole year")
        _fv.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
        _fv.update_xaxes(showgrid=False,
                         tickvals=[r["year"] for i, r in enumerate(_vol)
                                   if i % 3 == 0 or r["year"] == _vol[-1]["year"]])
        with st.container(key="wm-heifer-vol"):
            st.plotly_chart(_fv, use_container_width=True)

        # Year-over-year only WITHIN an era and only between complete years.
        _yy = []
        for _i in range(1, len(_vol)):
            _a, _b = _vol[_i - 1], _vol[_i]
            if (_a["era"] != _b["era"] or _b["year"] - _a["year"] != 1
                    or not (_a["complete"] and _b["complete"])
                    or _a["thin"] or _b["thin"]):
                continue
            _yy.append((_b["year"], 100 * (_b["steers"] / _a["steers"] - 1),
                        100 * (_b["heifers"] / _a["heifers"] - 1)))
        if _yy:
            _ly, _ls, _lh = _yy[-1]
            _pt = (f" {_part[0]['year']} is drawn hollow and joined to nothing: "
                   f"{_part[0]['weeks']} of 52 weeks are in, so it is a part-year "
                   f"total, not a small one." if _part else "")
            st.caption(
                f"Whole-year head, both sexes. Last complete year, **{_ly}: steers "
                f"{_ls:+.1f}%, heifers {_lh:+.1f}%** — heifers "
                + ("leaving the sale faster than steers, which is retention in "
                   "volume rather than in mix." if _lh < _ls else
                   "falling no faster than steers, so the mix is not shifting "
                   "toward retention on this measure.")
                + _pt
                + (f" {_tv[0]['year']}–{_tv[-1]['year']} are grey and set apart: "
                   f"the auction panel reported from {min(r['states'] for r in _tv)}"
                   f"–{max(r['states'] for r in _tv)} states then against "
                   f"{max(r['states'] for r in _vol)} now, so most of the rise "
                   f"across them is the panel filling in rather than more cattle."
                   if _tv else "")
                + " The eras are drawn apart and no year-over-year spans them: "
                "head does not cross the 2020 archive handover cleanly even "
                "though share does, because both the auction and video rosters "
                "widened there, by 16% and 30%. 2020 itself is absent — legacy "
                "direct decays before its replacement starts, leaving that year "
                "at 74% of 2019."
            )

        # BELOW THE CHART AND FOLDED AWAY. The table was the lead for a while,
        # and it is the better way to read a single year-over-year -- but 26
        # rows is most of a screen, and it pushed the shape of the series, and
        # everything after it, out of view. The chart answers 'what is
        # happening' and the table answers 'by how much, in which year', so
        # the chart goes first and the numbers are one click away.
        with st.expander("📋  Receipts volume by year, with year-over-year"):
            # st.dataframe rather than hand-rolled HTML, for two affordances it
            # brings and a markup table cannot: a FULLSCREEN toggle, which is how
            # you snip this, and a download, which is how you print it or take it
            # into a spreadsheet. Both live in the toolbar that appears on hover;
            # the explicit button below repeats the download because a toolbar
            # that only exists on hover is not a thing most readers find.
            _rowsv = []
            _pv = None
            for _r in _vol:
                _ok = (_pv is not None and _r["year"] - _pv["year"] == 1
                       and _r["era"] == _pv["era"] and _r["complete"]
                       and _pv["complete"])
                _rowsv.append({
                    "Year": (str(_r["year"]) if _r["complete"]
                             else f"{_r['year']} ({_r['weeks']} of 52 wks)"),
                    "States": _r["states"],
                    "Steers": _r["steers"],
                    "Heifers": _r["heifers"],
                    "Total": _r["steers"] + _r["heifers"],
                    "Steer YoY %": (round(100 * (_r["steers"] / _pv["steers"] - 1), 1)
                                    if _ok else None),
                    "Heifer YoY %": (round(100 * (_r["heifers"] / _pv["heifers"] - 1), 1)
                                     if _ok else None),
                })
                _pv = _r
            _dfv = pd.DataFrame(_rowsv)
            _thin_years = {str(r["year"]) for r in _vol if r["thin"]}

            def _shade(_row):
                # Grey the under-covered years, the same signal the chart gives
                # them, so a reader who prints this still sees which rows are
                # drawn from a smaller panel.
                _d = str(_row["Year"]).split(" ")[0] in _thin_years
                return [f"color:{MUTED};" if _d else "" for _ in _row]

            def _yoy_colour(_v):
                if _v is None or pd.isna(_v):
                    return f"color:{MUTED};"
                return f"color:{POS};" if _v < 0 else f"color:{NEG};"

            _sty = (_dfv.style
                    .apply(_shade, axis=1)
                    .map(_yoy_colour, subset=["Steer YoY %", "Heifer YoY %"])
                    .format({"Steers": "{:,.0f}", "Heifers": "{:,.0f}",
                             "Total": "{:,.0f}",
                             "Steer YoY %": lambda v: "—" if pd.isna(v) else f"{v:+.1f}%",
                             "Heifer YoY %": lambda v: "—" if pd.isna(v) else f"{v:+.1f}%"}))
            st.dataframe(_sty, use_container_width=True, hide_index=True,
                         height=min(38 * (len(_dfv) + 1) + 3, 900))
            st.download_button(
                "⬇  Download as CSV",
                _dfv.to_csv(index=False).encode("utf-8"),
                file_name=f"jsa_feeder_receipts_volume_{_vol[-1]['year']}.csv",
                mime="text/csv", key="dl_vol")
            st.caption(
                "Every year in the archive. A dash means the two ends are not the "
                "same kind of number — the row above is a part year, sits in the "
                "other archive era, or is not the preceding year. Grey rows report "
                "from fewer states than the panel reaches today, so their totals "
                "are smaller for that reason as well as for the market's. "
                "Hover the table for a fullscreen toggle."
            )


    _roll = HS["rolling"]
    if len(_roll) > 8:
        _pk = max(_roll, key=lambda r: r["share"])
        _rc = _roll[-1]
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        st.markdown('<div class="sec-header">The Current Turn, Week By Week</div>',
                    unsafe_allow_html=True)
        _f2 = go.Figure()
        _f2.add_trace(go.Scatter(x=[r["week"] for r in _roll],
                                 y=[r["share"] for r in _roll], mode="lines",
                                 fill="tozeroy", fillcolor="rgba(6,147,227,0.09)",
                                 line=dict(color=JPSI_BLUE, width=2.5),
                                 hovertemplate="%{x|%b %Y}<br>%{y:.2f}%<extra></extra>"))
        _f2.add_trace(go.Scatter(x=[_pk["week"]], y=[_pk["share"]], mode="markers",
                                 hoverinfo="skip",
                                 marker=dict(size=11, color=MUTED,
                                             line=dict(color="#ffffff", width=2))))
        _f2.add_trace(go.Scatter(x=[_rc["week"]], y=[_rc["share"]], mode="markers",
                                 hoverinfo="skip",
                                 marker=dict(size=14, color=POS,
                                             line=dict(color="#ffffff", width=2))))
        _f2.add_annotation(x=_pk["week"], y=_pk["share"], ax=-2, ay=-32,
                           text=f"<b>peak {_pk['share']:.1f}%</b> (12-month)",
                           showarrow=True, arrowhead=0, arrowcolor=MUTED,
                           font=dict(size=12, color=TEXT))
        _f2.add_annotation(x=_rc["week"], y=_rc["share"], ax=0, ay=34,
                           text=f"<b>{_rc['share']:.1f}%</b>", showarrow=True,
                           arrowhead=0, arrowcolor=POS, font=dict(size=13, color=TEXT))
        _f2.update_layout(height=320, margin=dict(l=0, r=10, t=26, b=0),
                          plot_bgcolor="white", paper_bgcolor="white",
                          showlegend=False,
                          yaxis_title="heifer share, trailing 52 weeks")
        # An explicit range, because fill="tozeroy" otherwise drags the axis down
        # to 0% and squeezes a four-point move into a sliver at the top of the
        # chart. The fill is there to weight the area, not to imply a zero base.
        _rs = [r["share"] for r in _roll]
        _f2.update_yaxes(showgrid=True, gridcolor="#f1f5f9", ticksuffix="%",
                         range=[min(_rs) - 0.7, max(_rs) + 0.7])
        _f2.update_xaxes(showgrid=False)
        st.plotly_chart(_f2, use_container_width=True)
        st.caption(
            "A rolling 52-week window, which is seasonally neutral and so puts the "
            "turn on its actual date rather than in whichever annual bucket the "
            "calendar assigns it. It begins later than the annual series above "
            "because it stays clear of every handover: each channel switched "
            "archives on its own date, the last in September 2020, and a window "
            "spanning one would mix two archives mid-window."
        )

    with st.expander("ℹ️  How to read the heifer share"):
        st.markdown(f"""
**What it measures.** Every feeder animal sold is a steer or a heifer. Steers
have one destination — the feedlot. A heifer can go to the feedlot too, or she
can stay home and be bred. So the heifer share of feeder receipts is a direct
count of which choice was made, aggregated over {len(_ann)} years.

**All three sale channels.** The sale barn is roughly 60% of the head here;
direct country trade and video/internet auctions are the rest, and they do not
move together — direct's heifer share climbed about twelve points since 2015
while the barn's moved half a point. A barn-only reading of today would put the
herd within a point of the 2015 rebuild; all three channels put it about three
points above. The coverage guard still counts the {min(r["states"] for r in _ann)}–{max(r["states"] for r in _ann)}
auction states, because it exists for the auction archive's own thin early years.

**Falling is rebuilding.** A share of **{_cur['share']:.1f}%** in {_cur['year']}
against a peak of **{_hi['share']:.1f}%** in {_hi['year']} means heifers are being
withheld. The benchmark is **{_lo['share']:.1f}%** in {_lo['year']}, the last time
the national herd genuinely expanded — today sits **{_sum['gap_to_low']:.2f} points**
above it *on this measure*.

**This is the all-channel view, and it used to be the sale barn's alone.** That
change is worth knowing about, because the two do not say the same thing: barn
receipts put today about a point above {_lo['year']}, all three channels put it
around three. The barn's heifer share barely moved since {_lo['year']} while
direct country trade's climbed about twelve points, so a barn-only reading
understates how far today sits from a genuine rebuild.

**Compare it with the feedlot survey below.** That is an independent measurement
with its own basis, and the year selector in that panel set to {_lo['year']} shows
the size of any disagreement. Where they diverge, the divergence is the finding —
neither is the correction to the other.

**Why it is not the same as the ratio above.** The retention incentive prices the
decision; this counts the outcome. They can disagree, and when they do the
disagreement is the story: an incentive nobody acts on is not a rebuild, and
retention in the face of a poor incentive says something about expectations.

**Why the two charts peak at different numbers.** The first reads January to
mid-September; the second reads a trailing twelve months. Heifer share runs about
three points lighter in the autumn run, so any twelve-month window sits below a
January–September one. Both peak in 2023 — it is the same market through two
windows, not a disagreement. The annual basis is the only one comparable across
the 2019 source handover; the trailing one is the only one free of seasonality.

**What it is not.** Auction receipts only — direct, video and internet sales are
not included, and roughly half the feeder cattle in the country change hands that
way. It is a large consistent sample, not a census, and the *level* matters less
than the direction and where it sits against {_lo['year']}.
""")


# ── Heifers On Feed ──────────────────────────────────────────────────────────
# The same decision measured from the opposite end, by someone else. Receipts
# count heifers arriving at auction (AMS, barn-level); this counts heifers
# standing in feedlots (NASS, a survey of feedyards). Two datasets with
# different failure modes agreeing is worth more than either on its own.
_OF = load_on_feed() or {}
if _OF.get("error"):
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Heifers On Feed — The Feedlot Side</div>',
                unsafe_allow_html=True)
    st.warning(
        f"**The feedlot panel could not read the NASS cache.** Everything above is "
        f"unaffected — it comes from a different backend. `{_OF['error']}`"
    )
OF = _OF.get("ok")
if OF:
    _ocur, _ohi, _olo = OF["current"], OF["high"], OF["low"]
    _orows = [r for r in OF["rows"] if r["trailing"] is not None]

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Heifers On Feed — The Feedlot Side</div>',
                unsafe_allow_html=True)
    st.caption(
        "Heifers as a share of the steers and heifers standing in US feedlots — "
        "USDA NASS's quarterly survey of feedyards, an entirely separate "
        "measurement from the auction receipts above. A heifer on feed is a heifer "
        "that was **not** kept back to breed, so this falls when producers retain, "
        "the same direction as the receipts share. Plotted as a trailing "
        "four-quarter mean, because April runs about 1.3 points below the other "
        "quarters every year."
    )

    o = st.columns(4)
    with o[0]:
        _yoy = (f'<div class="tile-delta-{"pos" if OF["yoy_pts"] < 0 else "neg"}">'
                f'{"▼" if OF["yoy_pts"] < 0 else "▲"} {abs(OF["yoy_pts"]):.2f} pts YoY</div>'
                if OF["yoy_pts"] is not None else '<div class="tile-delta-neu">—</div>')
        st.markdown(tile(f"On Feed, {_ocur['label']}", f"{_ocur['share']:.1f}%", _yoy),
                    unsafe_allow_html=True)
    with o[1]:
        st.markdown(tile("Trailing 4-Qtr", f"{_ocur['trailing']:.1f}%",
                         f'<div class="tile-delta-neu">seasonally neutral</div>'),
                    unsafe_allow_html=True)
    with o[2]:
        st.markdown(tile("Series Peak", f"{_ohi['trailing']:.1f}%",
                         f'<div class="tile-delta-neu">{_ohi["label"]}</div>'),
                    unsafe_allow_html=True)
    with o[3]:
        st.markdown(tile("Rebuild Low", f"{_olo['trailing']:.1f}%",
                         f'<div class="tile-delta-neu">{_olo["label"]}</div>'),
                    unsafe_allow_html=True)

    _ox = [f"{r['year']}-Q{r['quarter']}" for r in _orows]
    _oy = [r["trailing"] for r in _orows]
    _f3 = go.Figure()
    _f3.add_trace(go.Scatter(x=_ox, y=_oy, mode="lines", fill="tozeroy",
                             fillcolor="rgba(217,119,6,0.09)",
                             line=dict(color="#d97706", width=2.5),
                             hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>"))
    for _r, _c, _sz in ((_ohi, MUTED, 11), (_olo, MUTED, 11), (_orows[-1], POS, 14)):
        _f3.add_trace(go.Scatter(x=[f"{_r['year']}-Q{_r['quarter']}"],
                                 y=[_r["trailing"]], mode="markers", hoverinfo="skip",
                                 marker=dict(size=_sz, color=_c,
                                             line=dict(color="#ffffff", width=2))))
    _f3.add_hline(y=_olo["trailing"], line_dash="dot", line_color=POS)
    _f3.add_annotation(x=f"{_ohi['year']}-Q{_ohi['quarter']}", y=_ohi["trailing"],
                       ax=0, ay=-30, text=f"<b>{_ohi['trailing']:.1f}%</b> {_ohi['year']}",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f3.add_annotation(x=f"{_olo['year']}-Q{_olo['quarter']}", y=_olo["trailing"],
                       ax=0, ay=36, text=f"<b>{_olo['trailing']:.1f}%</b> last rebuild",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f3.add_annotation(x=_ox[-1], y=_oy[-1], ax=-18, ay=-30,
                       text=f"<b>{_oy[-1]:.1f}%</b>", showarrow=True, arrowhead=0,
                       arrowcolor=POS, font=dict(size=13, color=TEXT))
    _f3.update_layout(height=340, margin=dict(l=0, r=10, t=30, b=0),
                      plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
                      yaxis_title="heifer share on feed, trailing 4 quarters")
    _f3.update_yaxes(showgrid=True, gridcolor="#f1f5f9", ticksuffix="%",
                     range=[min(_oy) - 1.0, max(_oy) + 1.2])
    _f3.update_xaxes(showgrid=False,
                     tickvals=[f"{y}-Q1" for y in range(1998, _ocur["year"] + 1, 4)])
    with st.container(key="wm-on-feed"):
        st.plotly_chart(_f3, use_container_width=True)

    # Guarded: this caption renders even when the receipts section above did
    # not, and the old text asserted a receipts distance regardless -- it read
    # "within a point of its rebuild low", true at +0.64 on auction receipts
    # and wrong at +2.98 on all three channels.
    _rec_gap_txt = (f", against **{HS['summary']['gap_to_low']:.1f} points** "
                    f"for the receipts share above" if HS else "")
    st.caption(
        f"**The two measures agree on direction and differ on distance, and there "
        f"are two reasons for that, not one.** Both peaked in 2023 and both are "
        f"falling. This one sits **{_ocur['trailing'] - _olo['trailing']:.1f} "
        f"points** above {_olo['year']}'s low{_rec_gap_txt}. The panel below "
        f"shows that gap is close to what dairy-origin cattle alone account "
        f"for.\n\n"
        f"**Timing.** Receipts are a *flow* — what is being sold this week. Cattle "
        f"on feed are a *stock*, and heifers already placed stay on feed for months, "
        f"so the feedlot number lags the sale barn by roughly a feeding period.\n\n"
        f"**Mix.** This series counts every heifer in a feedlot, including "
        f"dairy-origin ones that were never a beef-herd retention decision. The "
        f"receipts series excludes them by construction — AMS reports Dairy and "
        f"Beef/Dairy as their own classes — but NASS publishes no breed split for "
        f"cattle on feed, so they cannot be removed here. That composition has "
        f"changed since {_olo['year']} in both directions, which is why the *level* "
        f"is less comparable across a decade than the direction is within recent "
        f"years. The panel below puts numbers on how much it would take to matter."
    )

    # Not a correction -- there is no breed split to correct WITH. The inverse
    # question: the receipts series IS breed-clean, so ask how much dairy there
    # would have to be for the two measures to be telling the same story.
    # OUT OF THE EXPANDER on purpose. This is the most load-bearing thing on
    # the page -- two independently collected surveys agreeing on how far today
    # sits from a benchmark once a third, independently estimated number is
    # applied -- and it spent its first hours hidden behind a disclosure
    # triangle that most readers never open.
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Reconciling The Two Measures</div>',
                unsafe_allow_html=True)
    # The benchmark year is the reader's to choose. It defaults to the receipts
    # peak so the panel opens on the comparison the caption above just made,
    # but 2015-16 is the more interesting one -- that is the last genuine
    # rebuild, and whether today has matched it is the actual question.
    # Derived from the receipts series rather than written down, because
    # this bound has already gone stale once: it read 2010 when receipts
    # began in 2011, and the wtd_1 backfill moved the start to 2005.
    #
    # Read off HS rather than _ann: _ann is bound to the RETENTION series
    # at the top of the page and only rebound to the heifer-share one
    # inside the section above, so when that section is skipped it still
    # holds the other frame -- same years, entirely different measure.
    _rec_from = min((r["year"] for r in HS["annual"]), default=2011) if HS else 2011
    _years = sorted({r["year"] for r in _orows
                     if _rec_from <= r["year"] < _ocur["year"]})
    _bench = None
    _rdrop = None
    _rec_then = None
    if _years:
        _def = HS["summary"]["high"]["year"] if HS else _years[-1]
        if _def not in _years:
            _def = _years[-1]
        _by = st.selectbox("Compare against", _years, index=_years.index(_def),
                           key="dm_year",
                           help=f"On-feed data runs to 1996; receipts only to "
                                f"{_rec_from}, so the receipts row drops out "
                                f"below that.")
        # Same quarter as the current reading -- this series is seasonal, and
        # April sits about 1.3 points under the rest every year.
        _same_q = [r for r in _orows
                   if r["year"] == _by and r["quarter"] == _ocur["quarter"]]
        _bench = (_same_q or [r for r in _orows if r["year"] == _by])[-1]
        if HS:
            _rec_then = next((r for r in HS["annual"] if r["year"] == _by), None)
            if _rec_then:
                _rdrop = HS["summary"]["current"]["share"] - _rec_then["share"]

    st.caption(
        "The feedlot series counts **every** heifer on feed, including dairy-origin "
        "ones that were never a retention decision; the receipts series excludes "
        "them by construction. Taking an assumed dairy stream out of both years "
        "puts the two on the same terms. The assumption is stated, not adjustable."
    )

    _gap_rep = _ocur["trailing"] - _bench["trailing"]
    _adj_then = dm_adjust(_bench["trailing"], ASSUMED_DAIRY_THEN, ASSUMED_HEIFER_FRAC)
    _adj_now = dm_adjust(_ocur["trailing"], ASSUMED_DAIRY_NOW, ASSUMED_HEIFER_FRAC)
    _gap_adj = (_adj_now - _adj_then) if (_adj_then is not None
                                         and _adj_now is not None) else None

    _rows = [("On feed, as reported", "every heifer in a feedlot",
              _bench["trailing"], _ocur["trailing"], _gap_rep, False)]
    if _gap_adj is not None:
        _rows.append(
            ("On feed, beef-only",
             f"assumes {ASSUMED_DAIRY_NOW:.0f}% dairy today, none in "
             f"{_bench['year']}, that stream {ASSUMED_HEIFER_FRAC:.0f}% heifers",
             _adj_then, _adj_now, _gap_adj, True))
    if _rec_then and _rdrop is not None:
        _rows.append(("At the sale barn", "receipts — excludes dairy already",
                      _rec_then["share"], HS["summary"]["current"]["share"],
                      _rdrop, False))

    _t = ['<table style="width:100%;border-collapse:collapse;font-size:0.9rem;">',
          f'<tr style="color:{MUTED};font-size:0.7rem;text-transform:uppercase;'
          f'letter-spacing:0.08em;text-align:right;">'
          f'<th style="text-align:left;padding:6px 8px;">Heifer share</th>'
          f'<th style="padding:6px 8px;">{_bench["year"]}</th>'
          f'<th style="padding:6px 8px;">{_ocur["year"]}</th>'
          f'<th style="padding:6px 8px;">Change</th></tr>']
    for _lbl, _sub, _a, _b, _c, _hi in _rows:
        _bg = f"background:{SURFACE2};" if _hi else ""
        _w = "700" if _hi else "400"
        _t.append(
            f'<tr style="{_bg}border-top:1px solid {BORDER};text-align:right;">'
            f'<td style="text-align:left;padding:8px;font-weight:{_w};">{_lbl}'
            f'<div style="color:{MUTED};font-size:0.72rem;font-weight:400;">{_sub}</div></td>'
            f'<td style="padding:8px;">{_a:.1f}%</td>'
            f'<td style="padding:8px;font-weight:{_w};">{_b:.1f}%</td>'
            f'<td style="padding:8px;font-weight:700;color:{POS if _c < 0 else NEG};">'
            f'{_c:+.1f} pts</td></tr>')
    _t.append("</table>")
    st.markdown("".join(_t), unsafe_allow_html=True)

    # One plain sentence. Earlier versions of this panel showed the dairy share
    # that WOULD BE needed to reconcile the two series -- true, and unreadable:
    # a column of percentages whose meaning depended on holding a gap in your
    # head from a caption above it. The question a reader has is whether today
    # resembles the benchmark year, so answer that.
    if _gap_adj is None or _rdrop is None:
        st.caption("The sale-barn series does not reach "
                   f"{_bench['year']}, so there is nothing breed-clean to set "
                   "the feedlot reading against.")
    else:
        _closed = abs(_gap_adj - _rdrop) < abs(_gap_rep - _rdrop)
        _verdict = (
            f"That takes most of the disagreement out — what is left "
            f"({abs(_gap_adj - _rdrop):.1f} pts) is the feeding-period lag, or "
            f"something neither series shows."
            if _closed else
            f"That does not close the disagreement, so dairy mix is not what "
            f"is driving it.")
        st.info(
            f"**Same measure, dairy taken out of both ends.** Against "
            f"{_bench['year']}, the feedlot reading goes from **{_gap_rep:+.1f} "
            f"pts** as reported to **{_gap_adj:+.1f} pts** beef-only. The sale "
            f"barn, which never counted dairy cattle, moved **{_rdrop:+.1f} pts** "
            f"over the same span. {_verdict}"
        )

        # THE INVERSE QUESTION, which is what this panel was built for and
        # which the table above only implies: instead of assuming a dairy
        # share, solve for the one that would make the two measures move
        # identically, then ask whether that number is believable.
        #
        # REPORTED AS A RANGE, NOT A POINT, AND THAT IS NOT HEDGING. The
        # answer is sensitive to how the two windows are aligned, because the
        # benchmark year is usually moving fast. Receipts cover Jan-mid-Sep;
        # the feedlot series is quarterly and compared same-quarter here, so
        # its trailing mean reaches back into the PRIOR year. For 2015 that
        # is the difference between 33.4% (trailing at Q3) and 32.6%
        # (trailing at Q4, i.e. the calendar-year mean) -- 0.8 points of
        # benchmark, which moves the implied dairy share by about five.
        # Quoting one figure to a decimal would imply a precision the
        # alignment does not support.
        _need = dm_implied(_ocur["trailing"], _bench["trailing"] + _rdrop,
                           ASSUMED_HEIFER_FRAC)
        _alt = None
        _cal = [r for r in _orows if r["year"] == _bench["year"]]
        if _cal:
            _alt = dm_implied(_ocur["trailing"], _cal[-1]["trailing"] + _rdrop,
                              ASSUMED_HEIFER_FRAC)
        if _need is not None:
            _lo, _hi_ = sorted([v for v in (_need, _alt) if v is not None])[0],                             sorted([v for v in (_need, _alt) if v is not None])[-1]
            _span = (f"between **{_lo:.0f}% and {_hi_:.0f}%**"
                     if abs(_hi_ - _lo) >= 1 else f"about **{_need:.0f}%**")
            _overlaps = _hi_ >= 15.0 and _lo <= 20.0
            st.markdown(
                f"**And the strongest version of it.** Instead of assuming a "
                f"dairy share, solve for one: cattle on feed would need to be "
                f"{_span} dairy-origin for this series to have moved exactly as "
                f"the sale barn did since {_bench['year']}. The span is the "
                f"alignment, not the uncertainty in the data: which quarter "
                f"anchors {_bench['year']} moves it by {abs(_hi_ - _lo):.1f} "
                f"points.\n\n"
                + (f"Credible industry estimates put dairy-influenced fed cattle "
                   f"at **15–20%**, and this page assumed "
                   f"{ASSUMED_DAIRY_NOW:.0f}% before the comparison was made. "
                   f"The reconciling value overlaps that range, which is worth "
                   f"something — two surveys run by different agencies over "
                   f"different populations, needing a third independently "
                   f"estimated number to agree, and getting one in the right "
                   f"neighbourhood.\n\nIt is not a confirmation to a decimal "
                   f"place, and benchmark years disagree: the implied share runs "
                   f"from the low teens to the low twenties depending which year "
                   f"anchors it, because the two series trough a year apart and a "
                   f"common calendar year pairs them at different points in the "
                   f"cycle. This year is among the closer agreements, not a "
                   f"typical one."
                   if _overlaps else
                   f"Credible industry estimates put dairy-influenced fed cattle "
                   f"at **15-20%**, and this lands " + ("above" if _lo > 20.0
                   else "below") + f" it on every alignment, so dairy mix is "
                   f"the wrong SIZE to explain the gap rather than the wrong idea.\n\n"
                   f"Benchmark years disagree here: the implied share runs from "
                   f"the low teens to the low twenties depending which year "
                   f"anchors it, because the two series trough a year apart and "
                   f"a common calendar year pairs them at different points in "
                   f"the cycle.")
            )

    with st.expander("ℹ️  Why the direction across a decade is genuinely unknown"):
        st.markdown(
        "Straight "
        "Holstein heifers used to be scarce in feedlots — the legacy AMS archive "
        "carries Feeder Holstein *steers* and no Holstein heifer class at all, "
        "because those heifers became dairy replacements. Sexed semen then "
        "produced a surplus that did go on feed, peaking around the same years "
        "this page uses as its rebuild benchmark, before beef-on-dairy displaced "
        "it. Our own auction data shows that changeover: straight-Holstein "
        "heifers were 100% of dairy-class heifers through 2023 and are 69% now. "
        "So the benchmark year may carry its own dairy inflation. The two "
        "effects partly offset, neither is measurable, and anyone who tells you "
        "the net sign with confidence is guessing."
    )


# ── Herd Inventory ───────────────────────────────────────────────────────────
# The head counts. Everything above measures the retention decision or what
# producers did about it at the sale barn; this measures the herd itself.
_IV = load_inventory() or {}
if _IV.get("error"):
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Herd Inventory</div>', unsafe_allow_html=True)
    st.warning(
        f"**The inventory panel could not read the NASS cache.** Everything above is "
        f"unaffected — different backend. `{_IV['error']}`"
    )
IV = _IV.get("ok")
if IV:
    _ic, _ip = IV["current"], IV["prev"]
    _ihi, _ilo = IV["recent_high"], IV["recent_low"]
    _sl, _ypk = IV["slaughter"], IV["slaughter_peak"]
    _yc, _yp = IV["ytd_current"], IV["ytd_prev"]
    _sla = IV["slaughter_annual_latest"]

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Herd Inventory — The Head Count</div>',
                unsafe_allow_html=True)
    st.caption(
        "USDA NASS January 1 inventory and monthly commercial slaughter. "
        "**Replacement heifers ÷ beef cows** is the standard expansion measure — "
        "females entering the herd against females already in it — and beef cow "
        "slaughter is the culling side of the same ledger. These are counts of the "
        "herd, not prices or receipts, and they are the only thing here that "
        "measures the rebuild directly."
    )

    i = st.columns(4)
    with i[0]:
        _arrow = ("▲" if IV["turned_up"] else "▼")
        _kind = "pos" if IV["turned_up"] else "neg"
        st.markdown(tile(f"Replacement Ratio, {_ic['year']}", f"{_ic['ratio']:.1f}%",
                         f'<div class="tile-delta-{_kind}">{_arrow} '
                         f'{abs(_ic["ratio"] - _ip["ratio"]):.2f} pts vs {_ip["year"]}</div>'),
                    unsafe_allow_html=True)
    with i[1]:
        st.markdown(tile(f"Beef Cows, {_ic['year']}", f"{_ic['cows'] / 1e6:.2f}M",
                         f'<div class="tile-delta-neu">{_ic["heifers"] / 1e6:.2f}M '
                         f'replacements</div>'), unsafe_allow_html=True)
    with i[2]:
        _spct = 100.0 * (_sla["head"] - _ypk["head"]) / _ypk["head"]
        st.markdown(tile(f"Cow Slaughter, {_sla['year']}", f"{_sla['head'] / 1e6:.2f}M",
                         f'<div class="tile-delta-pos">▼ {abs(_spct):.0f}% vs '
                         f'{_ypk["year"]} peak</div>'), unsafe_allow_html=True)
    with i[3]:
        _ypct = 100.0 * (_yc["head"] - _yp["head"]) / _yp["head"]
        st.markdown(tile(f"Slaughter YTD thru {_yc['through'].title()}",
                         f"{_yc['head'] / 1e6:.2f}M",
                         f'<div class="tile-delta-{"pos" if _ypct < 0 else "neg"}">'
                         f'{"▼" if _ypct < 0 else "▲"} {abs(_ypct):.1f}% vs '
                         f'{_yp["year"]}</div>'), unsafe_allow_html=True)

    # Five decades rather than the full 107 years the series carries: enough to
    # show four cattle cycles without compressing the current turn to nothing.
    _rr = [r for r in IV["ratio"] if r["year"] >= _ic["year"] - 55]
    _f4 = go.Figure()
    _f4.add_trace(go.Scatter(x=[r["year"] for r in _rr], y=[r["ratio"] for r in _rr],
                             mode="lines", fill="tozeroy",
                             fillcolor="rgba(6,147,227,0.09)",
                             line=dict(color=JPSI_BLUE, width=2.5),
                             hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>"))
    _f4.add_trace(go.Scatter(x=[_ic["year"]], y=[_ic["ratio"]], mode="markers",
                             hoverinfo="skip",
                             marker=dict(size=14, color=POS,
                                         line=dict(color="#ffffff", width=2))))
    _f4.add_annotation(x=_ihi["year"], y=_ihi["ratio"], ax=0, ay=-30,
                       text=f"<b>{_ihi['ratio']:.1f}%</b> {_ihi['year']} rebuild",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f4.add_annotation(x=_ic["year"], y=_ic["ratio"], ax=-20, ay=34,
                       text=f"<b>{_ic['ratio']:.1f}%</b>", showarrow=True, arrowhead=0,
                       arrowcolor=POS, font=dict(size=13, color=TEXT))
    _f4.update_layout(height=330, margin=dict(l=0, r=10, t=30, b=0),
                      plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
                      yaxis_title="replacement heifers ÷ beef cows")
    # Explicit range: fill="tozeroy" otherwise drags the axis to 0% and squashes
    # a four-point spread into the top quarter of the chart. The fill weights the
    # area; it is not a claim that zero is meaningful here. (The slaughter bars
    # below DO baseline at zero, correctly -- bar length encodes magnitude.)
    _rv = [r["ratio"] for r in _rr]
    _f4.update_yaxes(showgrid=True, gridcolor="#f1f5f9", ticksuffix="%",
                     range=[min(_rv) - 0.8, max(_rv) + 1.0])
    _f4.update_xaxes(showgrid=False)
    with st.container(key="wm-repl-ratio"):
        st.plotly_chart(_f4, use_container_width=True)

    _sa = [r for r in _sl["annual"] if r["year"] >= _ic["year"] - 26]
    _f5 = go.Figure()
    _f5.add_trace(go.Bar(x=[r["year"] for r in _sa], y=[r["head"] / 1e6 for r in _sa],
                         marker_color=[NEG if r["year"] == _ypk["year"]
                                       else ("#9fb8c8" if r["year"] != _sla["year"]
                                             else POS) for r in _sa],
                         hovertemplate="%{x}<br>%{y:.2f}M head<extra></extra>"))
    _f5.update_layout(height=270, margin=dict(l=0, r=10, t=24, b=0),
                      plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
                      yaxis_title="beef cow slaughter, million head")
    _f5.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
    _f5.update_xaxes(showgrid=False)
    st.plotly_chart(_f5, use_container_width=True)

    _turn = ("**turned up in "
             f"{_ic['year']} — the first rise since {_ihi['year']}**"
             if IV["turned_up"] else "has not yet turned up")
    st.info(
        f"**The flows have turned; the herd has not — which is the order a rebuild "
        f"happens in.** Beef cow slaughter is down **{abs(_spct):.0f}%** from its "
        f"{_ypk['year']} peak and still falling this year, and the replacement ratio "
        f"{_turn}. But beef cows themselves are **{_ic['cows'] / 1e6:.2f}M**, still "
        f"the smallest in decades. That is not a contradiction: culling stops and "
        f"heifers start being held while the herd is still shrinking, because those "
        f"heifers do not add a calf for the better part of two years. Slaughter "
        f"falls first, the ratio turns second, and beef cow inventory bottoms last."
    )

st.markdown(
    f"<div style='margin-top:22px;color:{MUTED};font-size:0.72rem;"
    f"border-top:1px solid {BORDER};padding-top:10px;'>"
    f"Sources: USDA AMS replacement- and slaughter-cattle auction reports via the "
    f"MARS API ({len(D['annual'])} years); for the receipts mix, AMS auction, "
    f"direct and video/internet reports via MARS from 2020-21 and USDA's legacy "
    f"archives before that; and USDA NASS via the shared "
    f"cache for cattle on feed and the January 1 head counts. Provided for informational "
    f"purposes only; not investment advice. © John Stewart &amp; Associates "
    f"{datetime.now().year}.</div>",
    unsafe_allow_html=True)
