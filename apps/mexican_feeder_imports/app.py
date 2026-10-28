"""
Mexican Feeder Imports -- how much Mexican cattle is reaching US feedyards.

Mexico normally supplies about 1.25 million feeder cattle a year, roughly 4% of
the US calf crop and concentrated in the southern Plains. New World Screwworm
suspensions cut that to 214,394 head in 2025 and to zero for the first seven
months of 2026. Douglas, AZ reopened on 24 August 2026 -- one crossing of five.

THE PAGE IS BUILT AROUND A LAG. AMS publishes daily head counts by crossing
point, current to yesterday, plus exact weekly totals with its own year-to-date
a week behind that. Census is the official customs count with seven years of
history but runs about six weeks late. So AMS answers "what is crossing now"
and Census answers "how does that compare to a normal year". In September 2026
a Census-only page would have shown zero imports for the whole year and said
nothing about the border reopening three weeks earlier.

A CORRECTION WORTH KEEPING. The first version of this page asserted that AMS
published no numbers at all and showed crossing DAYS as a proxy for volume.
That was wrong. MARS reports are split into SECTIONS addressed as PATH segments
(/reports/3486/Report%20Volume); requesting a report without one returns just
its header -- narrative and dates, nothing numeric -- which looks exactly like
a report with no data. The section list was in the response's `reportSections`
key all along.

DIRECTION MATTERS. AMS's status report covers both directions, and its standing
September 2026 note is about EXPORTS to Mexico being suspended while imports
were flowing. The import verdict here is computed from import-side crossing
activity only; the export note is shown separately and labelled. See
border.note_segments().

Analytics live in border.py, which is import-safe (no requests). Ingest is
border_reports.py and census_imports.py in the cme-feeder-cattle-index repo.
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Streamlit puts the MAIN script's directory on sys.path, never the page's, so a
# multipage app's own sibling modules are not importable without this.
# `portal_view` is SHARED and lives at the repo root, the convention `wasde`
# already uses. It decides whether this run is the client deployment, and it is
# NOT named `view` because several pages bind that as a local -- see
# portal_view.py.
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).parent))

import portal_view  # noqa: E402

import snowflake_db as db
import border as bd
import corn_demand as cdm
import mx_prices as mxp

# ── JSA Brand Colors (shared with the rest of the portal shell) ─────────────
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
AMBER     = "#d97706"

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
  /* Scenario tiles carry an amber rule instead of the blue one. Every other
     tile on this page is a measurement or a projection anchored to one; these
     describe a year that has not started and must not read as either. */
  .tile-scen {{ border-top-color:{AMBER}; }}
  .tile-sub {{ color:{MUTED}; font-size:0.72rem; margin-top:5px; }}
  .tile-delta-pos {{ color:{POS}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neg {{ color:{NEG}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neu {{ color:{NEU}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .sec-header {{
    color:{MUTED}; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:0.1em; padding:8px 0 4px; border-bottom:1px solid {BORDER};
    margin-bottom:10px;
  }}
  /* Status banner. Colour carries the verdict, so the text still has to say it
     in words -- a reader on a projector or with a colour deficiency gets the
     same answer. */
  .banner {{
    border-radius:10px; padding:16px 20px; margin-bottom:6px;
    border:1px solid {BORDER}; border-left:5px solid {MUTED};
    background:{CARD_BG};
  }}
  .banner-open   {{ border-left-color:{POS}; }}
  .banner-idle   {{ border-left-color:{AMBER}; }}
  .banner-closed {{ border-left-color:{NEG}; }}
  .banner-state {{ font-size:1.15rem; font-weight:700; line-height:1.2; }}
  .banner-detail {{ color:{MUTED}; font-size:0.82rem; margin-top:6px; line-height:1.5; }}
  .banner-quote {{
    color:{TEXT}; font-size:0.78rem; margin-top:9px; padding:8px 11px;
    background:{SURFACE2}; border-radius:6px; font-family:ui-monospace,monospace;
  }}
  .srcline {{ color:{MUTED}; font-size:0.72rem; line-height:1.6; }}
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


# ── Helpers ─────────────────────────────────────────────────────────────────

def tile(label, value, extra="", cls=""):
    return (f'<div class="tile {cls}"><div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>{extra}</div>')


def sub(text):
    return f'<div class="tile-sub">{text}</div>'


def pct_delta(val, suffix=""):
    if val is None or pd.isna(val):
        return '<div class="tile-delta-neu">—</div>'
    sign = "▲" if val > 0 else ("▼" if val < 0 else "")
    kind = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    return f'<div class="tile-delta-{kind}">{sign} {abs(val):.1f}%{suffix}</div>'


def fmt_date(d, fmt="%b %d, %Y"):
    if not d:
        return "—"
    return pd.Timestamp(str(d)).strftime(fmt)


def win_span(w):
    """'Feb 20 - May 12, 2025' -- ONE spelling of a window.

    The caption names two windows and the table names every one, so a span
    formatted at each site is three chances to describe the same stretch two
    ways. Same reason border.weight_spans() formats its own label.
    """
    if not w:
        return "—"
    a, b = w["start"], w["end"]
    if a[:4] == b[:4]:
        return (f"{fmt_date(a, '%b %d')} – {fmt_date(b, '%b %d')}, "
                f"{b[:4]}")
    return f"{fmt_date(a)} – {fmt_date(b)}"


def narrowing_phrase(cur, prev):
    """How the discount moved, COMPUTED rather than typed.

    "has roughly halved" was true when it was written and is printed in the
    same breath as the two figures it describes, so it has to be derived from
    them. The southeast retention caption is this page's precedent: prose
    naming a high and a low went stale against the chart directly above it,
    and the fix was to read them off the series at render time.
    """
    if not prev:
        return "has moved"
    r = cur / prev          # both negative; r < 1 means a narrower discount
    if r < 0:
        return "has flipped to a premium"
    if r < 0.40:
        return "has all but closed"
    if r <= 0.60:
        return "has roughly halved"
    if r < 0.85:
        return "has narrowed sharply"
    if r <= 1.15:
        return "is little changed"
    return "has widened"


def fmt_month(p):
    if not p:
        return "—"
    return pd.Timestamp(str(p) + "-01").strftime("%b %Y")


# ── Data ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def load_all(schema=bd.SCHEMA):
    """
    Everything the page needs, in one connection. None on any failure.

    get_conn() is INSIDE the try on purpose: connecting is the step most likely
    to fail (a missing SNOWFLAKE_ACCOUNT, an expired key, a paused warehouse),
    and with it outside, that failure escaped as a raw traceback on the page
    instead of the handled message below -- the one case the error handling
    exists for.
    """
    if not db.use_snowflake() and not DB_PATH.exists():
        return None
    conn = None
    try:
        conn = db.get_conn()
        ytd, through = bd.ytd_compare(conn)
        annual, _ = bd.annual_head(conn)
        bands, band_year = bd.band_shares(conn)
        kinds, kind_year = bd.kind_totals(conn, band_year)
        monthly, _ = bd.monthly_head(conn)
        return {
            "status": bd.import_status(conn),
            "export_note": bd.current_status(conn),
            "crossings": bd.crossing_days(conn),
            "ports": bd.ports_by_year(conn),
            "commentary": bd.recent_commentary(conn, 15),
            "timeline": bd.status_history(conn),
            "monthly": monthly,
            "annual": annual,
            "ytd": ytd,
            "census_through": through,
            "bands": bands,
            "band_year": band_year,
            # The same Census rows the annual bar reads, by month. No
            # extra fetch -- band_shares and this both walk _national().
            "band_mix": bd.band_mix_monthly(conn),
            "kinds": kinds,
            "kind_year": kind_year,
            "vph": bd.value_per_head(conn),
            "fresh": bd.data_freshness(conn),
            "daily": bd.daily_receipts(conn, since=f"{date.today().year}-01-01"),
            "daily_all": bd.daily_receipts(conn),
            "by_year": bd.receipts_by_year(conn),
            "by_crossing": bd.receipts_by_crossing(conn,
                                                   since=f"{date.today().year}-01-01"),
            "newest_port": bd.newest_crossing(conn,
                                              since=f"{date.today().year}-01-01"),
            "watch_port": (bd.port_profile(conn, bd.WATCH_PORT)
                           if bd.WATCH_PORT else None),
            "outlook": bd.year_outlook(
                conn, date.today().year + 1,
                bd.daily_receipts(conn), watch=bd.WATCH_PORT),
            "ytd_ams": bd.ytd_actuals(conn),
            "since_open": bd.since_reopening(conn),
            "weekly": bd.weekly_volumes(conn),
            "price_grid": bd.price_grid(conn),
            "price_series": bd.price_series(conn, grade=bd.INDEX_GRADE),
            "spread": bd.index_spread(conn),
            # Keyed on the border's OPEN WINDOWS, not the calendar year.
            # basis_move defaults to the two newest, so it and the tile read
            # one ordered dict and cannot pick different spans.
            "spread_win": bd.spread_by_window(conn),
            "basis_move": bd.basis_move(conn),
            # Head is published per crossing per DAY and never per weight
            # bracket, so this is the volume behind the day, not behind a rung.
            "price_head": bd.receipts_on(conn, bd.latest_price_date(conn)),
            "head_priced": bd.priced_day_head(
                conn, since=bd.reopened_on(conn)),
            # The weights AMS QUOTED per day. Not an average weight --
            # there is no published one; weight_spans() records why.
            "spans": bd.weight_spans(conn),
            "reopened": bd.reopened_on(conn),
        }
    except Exception as e:
        st.session_state["_mfi_error"] = f"{type(e).__name__}: {e}"
        return None
    finally:
        if conn is not None:
            conn.close()


with st.spinner("Loading border reports and Census trade data…"):
    # PASSED, never left to the default: st.cache_data hashes the
    # arguments it is CALLED with, so a parameter sitting at its default
    # contributes nothing to the key.
    D = load_all(bd.SCHEMA)

if not D:
    st.error("Could not load the Mexican import data.")
    st.caption(
        "This page reads the `border_reports` and `census_cattle_imports` "
        "tables, populated by `border_reports.py` and `census_imports.py` in "
        "the cme-feeder-cattle-index repo and pushed to Snowflake by that "
        "repo's daily job."
    )
    if st.session_state.get("_mfi_error"):
        st.caption(f"Detail: `{st.session_state['_mfi_error']}`")
    st.stop()

S = D["status"]
F = D["fresh"]

# ── Header ──────────────────────────────────────────────────────────────────
col_title, col_date = st.columns([6, 2])
with col_title:
    st.markdown("## JSA — Mexican Feeder Imports")
    st.caption("Daily head counts and border status from USDA AMS · historical customs counts from US Census trade data")
with col_date:
    st.markdown(
        f"<div style='text-align:right;color:{MUTED};font-size:0.75rem;padding-top:6px;'>"
        f"Latest border report<br>"
        f"<span style='color:{JPSI_BLUE};font-size:1rem;font-weight:700;'>"
        f"{fmt_date(F['ams_through'])}</span></div>",
        unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)


# Module level on purpose -- see CLAUDE.md on the letter page's tab split.
_MX_METHOD = """
**Source.** Tamaulipas auction results from `mexicoganadero.com`, recorded by
`scripts/mx_auction.py` into `JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES`. The US
side is USDA AMS report 3486 -- the same `border_prices` table the Crossings
tab quotes. Exchange rates are the ECB daily reference rate via
frankfurter.app, banked per sale date in `JSA.CME_FEEDER_CATTLE.FX_USDMXN`.

**The conversion.** MXN/kg to USD/cwt is kilos to pounds, pesos to dollars,
then per-pound to per-hundredweight. A missing rate leaves the cell empty
rather than defaulting, so no calf is ever priced at an implied 1.0 peso.

**Weight is matched on the midpoint.** The two ladders do not align --
Tamaulipas bands in kg, AMS in lb -- so each Mexican band is assigned to the
AMS bracket containing its own midpoint in pounds. Two Mexican bands can land
in one AMS bracket and are kept as separate rows rather than averaged: with no
head counts an average would weight a thin band equally with a heavy one and
print a figure no lot ever traded at.

**Sex is matched too.** BECERRO is a bull calf and pairs with AMS *Steers*;
BECERRA is a heifer calf and pairs with *Spayed Heifers*. Pairing across sexes
would read as a discount that is really a sex difference.

**Why Mexico has no feeder index.** Probed and recorded so it is not
re-derived: SNIIM (`economia-sniim.gob.mx`) is a slaughter-market system -- its
cattle series prices animals delivered to a rastro, and its calf series is
effectively dead. SIAP carries prices by municipality for Chihuahua and Sonora,
but annually, on a carcass basis, with 2025 published in August 2026. Neither
can answer what a feeder calf is worth this week.
"""


# ── The two views ───────────────────────────────────────────────────────────
# st.tabs, matching Cash Cattle Trade, which is the shape Ross asked for.
#
# A HIDDEN TAB IS HIDDEN, NOT SKIPPED -- its body executes on every rerun, the
# rule recorded in CLAUDE.md. So the prices tab's Snowflake read is behind
# @st.cache_data rather than running raw on every crossings load, the same deal
# the Saturday Slaughter view takes for its MARS fetch.
this_yr = date.today().year

# CORN DEMAND IS STAFF-ONLY, on Ross's instruction 2026-10-26. It is an
# internal read rather than a client one: every figure on it rests on feeding
# assumptions a client would take for measurement, and the interesting number
# is about US corn demand rather than about their cattle.
#
# HIDING THE LABEL DOES NOT STOP THE BODY -- portal_view.Hidden is a no-op
# context manager, so an unguarded `with tab_corn:` would run the PSD fetch on
# a client load and render the panel UNFRAMED into their page. The body is
# behind portal_view.shown(), which tests/test_client_view.py pins.
tab_crossings, tab_prices, tab_corn = portal_view.tabs(
    ["Mexican Feeder Crossings", "Mexican Feeder Prices", "Corn Demand"],
    hide=["Corn Demand"])

with tab_crossings:
    # ── Status banner ───────────────────────────────────────────────────────────
    # The single most important fact on the page and the one Census cannot answer.
    state = S["state"]
    reop = S.get("reopening") or {}
    words = {
        "open": ("IMPORTS FLOWING",
                 "Cattle have crossed within the last few reporting days."),
        "idle": ("PORT OPEN, NOTHING CROSSING",
                 "AMS is still publishing, but the recent reports say no cattle crossed."),
        "closed": ("IMPORTS SUSPENDED",
                   "No crossings reported, and no current border report."),
    }
    headline, explain = words.get(state, ("STATUS UNKNOWN", ""))
    ports_txt = ", ".join(S.get("active_ports") or []) or "none"

    # The comparison is against the busiest year on record, not against every port
    # that has ever appeared: Laredo reported in 2023 and never again, so "of 6
    # ever" and "5 were active in 2024" are both true and reading them together
    # looks like an inconsistency. Derive one number and use it in both places.
    _pyears = sorted({y for d in D["ports"].values() for y in d})
    _open_by_year = {y: sum(1 for d in D["ports"].values() if d.get(y))
                     for y in _pyears}
    peak_open_year = max(_open_by_year, key=_open_by_year.get) if _open_by_year else "—"
    peak_open_n = _open_by_year.get(peak_open_year, 0)

    detail = (f"{explain}<br>"
              f"<b>Active crossings:</b> {ports_txt} "
              f"({len(S.get('active_ports') or [])} of the {peak_open_n} open in "
              f"{peak_open_year}) &nbsp;·&nbsp; "
              f"<b>Last crossing:</b> {fmt_date(S.get('last_crossing'))}")
    if reop.get("date"):
        detail += (f"<br><b>Reopened:</b> {fmt_date(reop['date'])} — "
                   f"{reop['days_since']} days ago, after a "
                   f"{reop['gap_days']}-day closure "
                   f"(previous crossing {fmt_date(reop['previous_crossing'])})")

    st.markdown(
        f'<div class="banner banner-{state}">'
        f'<div class="banner-state">{headline}</div>'
        f'<div class="banner-detail">{detail}</div>'
        + (f'<div class="banner-quote">AMS, {fmt_date(reop["date"])}: '
           f'{reop["note"]}</div>' if reop.get("note") else "")
        + '</div>',
        unsafe_allow_html=True)

    # The export-direction note, kept visually separate. Merging it into the banner
    # above is the mistake this page is built to avoid.
    en = D.get("export_note") or {}
    ex_segs = [s for s, d in bd.note_segments(en.get("notes") or "") if d == "export"]
    if ex_segs:
        st.caption(
            f"Separately, on the **export** side (US cattle going *to* Mexico), AMS's "
            f"note for the week ending {fmt_date(en.get('end') or en.get('date'))} reads: "
            f"*{' '.join(ex_segs)}* — this does not describe imports."
        )

    # ── Data currency ───────────────────────────────────────────────────────────
    st.caption(
        f"**Two sources, two different lags.** AMS publishes head counts daily and "
        f"is current to {fmt_date(F['ams_through'])}, with exact weekly totals a "
        f"week behind that. Census is the official customs count with seven years "
        f"of history, but runs about six weeks late — currently through "
        f"**{fmt_month(F['census_through'])}**. So AMS answers *what is crossing "
        f"now* and Census answers *how this compares to a normal year*."
    )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    # ── Year to date ────────────────────────────────────────────────────────────
    # The question the page exists to answer once the border reopens: how much has
    # actually crossed this year, and against what.
    Y = D.get("ytd_ams")
    SO = D.get("since_open")

    st.markdown(f'<div class="sec-header">{this_yr} Year to Date</div>',
                unsafe_allow_html=True)

    # Reads left to right from most immediate to broadest context: what crossed on
    # the last reporting day, what that adds up to since the border reopened, the
    # official year to date, and the same point last year.
    daily = D.get("daily") or []
    spans = D.get("spans") or {}
    last_day = daily[-1] if daily else None

    # Deliberately NOT inside load_all(). That function is @st.cache_data with a
    # 30-minute ttl, and this is the one figure on the page whose value depends on
    # today's date as well as on the data -- the reporting days left in the year
    # tick down whether or not Snowflake has anything new. Cached, it would go on
    # quoting yesterday's remaining-day count with nothing to show it had.
    #
    # Guarded for the same reason the normal-trade baseline below is: this is one
    # tile on a page with a dozen other things on it, and a projection that cannot
    # be computed should cost the tile, not the page.
    try:
        PROJ = bd.project_year_end([(d, v) for d, v, _w in daily]) if daily else None
    except Exception as exc:
        PROJ = None
        st.caption(f":orange[Year-end projection unavailable ({type(exc).__name__}).]")

    c = st.columns(5)
    with c[0]:
        st.markdown(tile("Daily Head Crossings",
                         f"{last_day[1]:,}" if last_day else "—",
                         sub(f"est., {fmt_date(last_day[0])}" if last_day
                             else "no reporting day yet")), unsafe_allow_html=True)
    with c[1]:
        # Summed over the whole YEAR, not from the reopening date. The two are the
        # same number today because nothing crossed before 24 August -- but the
        # label says 2026, so the figure has to be 2026 by construction. Computing
        # it from the reopening and calling it the year total would quietly become
        # wrong the moment AMS backfills an earlier date.
        yr_est = sum(v for _d, v, _w in daily) if daily else None
        st.markdown(tile(f"{this_yr} Estimated Total Crossings",
                         f"~{yr_est:,}" if yr_est is not None else "—",
                         sub(f"est., {fmt_date(daily[0][0])} – "
                             f"{fmt_date(daily[-1][0])}" if daily else "")),
                    unsafe_allow_html=True)
    with c[2]:
        st.markdown(tile(f"{this_yr} YTD Head",
                         f"{Y['ytd']:,}" if Y else "—",
                         pct_delta(Y.get("pct") if Y else None,
                                   f" vs {Y['prior_year']}" if Y else "")
                         + sub(f"AMS actual, through {fmt_date(Y['week_end'])}"
                               if Y else "no YTD published")),
                    unsafe_allow_html=True)
    with c[3]:
        st.markdown(tile(f"{Y['prior_year']} YTD Head" if Y else "Prior YTD",
                         f"{Y['prior_ytd']:,}" if Y and Y.get("prior_ytd") else "—",
                         sub("same point last year")), unsafe_allow_html=True)
    with c[4]:
        # Last, and next to the prior-year box on purpose: the comparison a reader
        # wants from a projection is against the year it is being measured down
        # from, and here those two tiles sit side by side.
        st.markdown(tile(f"{this_yr} Projected Total",
                         f"~{PROJ['projected']:,.0f}" if PROJ else "—",
                         sub(f"{PROJ['pace']:,.0f} head/day · {PROJ['days_left']} "
                             f"reporting days left" if PROJ
                             else "not enough reporting days yet")),
                    unsafe_allow_html=True)

    if Y:
        # Derived, not hardcoded: the estimate-vs-actual gap moves every week, and a
        # literal here would quietly go stale while still reading as a measurement.
        est_to_date = sum(v for d, v, _w in daily if str(d) <= str(Y["week_end"]))
        gap = ((est_to_date / Y["ytd"] - 1) * 100) if Y.get("ytd") else None
        st.caption(
            f"**The first two boxes are estimates, the next two are actuals, and "
            f"the last is a projection.** The "
            f"daily figures AMS publishes are rounded to the nearest hundred head, "
            f"so the {this_yr} total is approximate and current to "
            f"{fmt_date(SO['latest']) if SO else 'the latest report'}. The YTD is "
            f"AMS's own count, exact but a week behind — and it is AMS's cut-off, "
            f"not one computed here, so a partial year cannot be measured against a "
            f"full one by accident. Over the same span the estimates sum to "
            f"{est_to_date:,} against an actual {Y['ytd']:,}"
            + (f", a {gap:+.1f}% rounding gap" if gap is not None else "")
            + ", which is why the boxes do not tie exactly."
        )

    if PROJ:
        _by = D.get("by_year") or {}
        # The BUSIEST prior year, not the most recent one. Most recent is 2025,
        # which was itself three-quarters closed at 222,600 head -- against it the
        # projection reads 41% and sounds like a shortfall rather than a collapse.
        # Against 2024 it is 7%. Scale means scale against a working border.
        _prior = {y: r["head"] for y, r in _by.items() if y < str(this_yr)}
        _ref = max(_prior, key=_prior.get, default=None)
        _ref_head = _prior.get(_ref)
        st.caption(
            f"**The last box is a projection, not a measurement.** It carries the "
            f"trailing **{PROJ['window']} reporting days** — two full AMS weeks, "
            f"**{PROJ['pace']:,.0f} head a day** — across the {PROJ['days_left']} "
            f"reporting days left in {this_yr}: {PROJ['crossed']:,} head through "
            f"{fmt_date(PROJ['through'])}, plus {PROJ['pace']:,.0f} × "
            f"{PROJ['days_left']}. Two full weeks rather than the whole span since "
            f"the border reopened, because that span still contains the restart — "
            f"over all {len(daily)} reporting days this year the rate is "
            f"{PROJ['crossed'] / len(daily):,.0f} head a day, which describes a "
            f"start-up that is over rather than the rate now."
        )
        # Every port fact here is read off the data rather than written in. The
        # first draft of this caption said "only Douglas, AZ is open" -- true when
        # the border reopened, nine days stale by the time it shipped, and
        # contradicted by the page's own header two screens up.
        _ports = (S or {}).get("active_ports") or []
        _new = D.get("newest_port")
        st.caption(
            f"**Read it as “if nothing changes”.** The two things that would change "
            f"it most are step changes, and a straight line sees neither. The first "
            f"is a crossing opening or shutting"
            + (f" — **{len(_ports)} of the six crossings that ran in 2023 are open "
               f"now** ({', '.join(_ports)})." if _ports else ".")
            + (f" **{_new[0]} only joined on {fmt_date(_new[2], '%b %d')}** "
               f"and has carried {_new[3]:,} head since, so part of the "
               f"{PROJ['window']}-day window above predates it and the pace is a "
               f"blend of a one-port border and a two-port one — which makes it "
               f"read low, not high."
               if _new else "")
            + f" After the February 2025 reopening the run-rate climbed to about "
              f"20,000 head a week and plateaued by week six, against 6,400 in week "
              f"five this time, so the next crossing to reopen moves this in a jump "
              f"rather than a drift. The second is a fresh screwworm detection, "
              f"which takes it to zero just as abruptly. For scale, "
            + (f"the projection is **{PROJ['projected'] / _ref_head * 100:.0f}% of "
               f"{_ref}’s {_ref_head:,} head**, the busiest year in this series "
               f"and the last one the border ran for before the first closure."
               if _ref_head else "a working border runs well over a million head "
                                 "a year.")
        )

        # The named step change, priced. Shown only while the crossing is shut --
        # once it opens it is in the daily series, the trailing pace picks it up on
        # its own, and the caption above names it as the newest port. Nothing here
        # needs changing on the day; this paragraph simply stops appearing.
        _w = D.get("watch_port")
        if _w and not _w["running"]:
            _nd = bd.reporting_days(date(this_yr, 11, 1), date(this_yr, 12, 31))
            # Low: the rate the port that most recently reopened is ACTUALLY
            # managing, which is the only in-regime evidence of what a restarting
            # crossing does today. High: this port's own rate when the border ran
            # normally. The gap between them is the honest width of the question.
            _lo = (_new[3] / _new[4]) if (_new and _new[4]) else None
            _hi = _w["per_day"]
            _p_lo = PROJ["projected"] + _lo * _nd if _lo else None
            _p_hi = PROJ["projected"] + _hi * _nd
            st.caption(
                f"**The step change with a date on it: {_w['port']}, NM.** It is "
                f"the one shut crossing that used to carry real volume — "
                f"**{_w['share'] * 100:.0f}% of every head** through the border in "
                f"{_w['years'][0]}–{_w['years'][-1]}, at {_w['per_day']:,.0f} a day "
                f"while open, against the {PROJ['pace']:,.0f} a day the whole "
                f"border is managing now. It has not carried a head since "
                f"{fmt_date(_w['last_seen'])}, and is expected back "
                f"**{bd.WATCH_PORT_EXPECTED}**. Over the {_nd} reporting days in "
                f"November and December that is worth "
                + (f"**+{_lo * _nd:,.0f} head** if it restarts the way "
                   f"{_new[0]} has ({_lo:,.0f} a day across its first {_new[4]}) "
                   f"and " if _lo else "")
                + f"**+{_hi * _nd:,.0f}** at its own {_w['years'][0]}–"
                  f"{_w['years'][-1]} rate — a year-end total of "
                + (f"roughly **{_p_lo:,.0f} to {_p_hi:,.0f}**" if _p_lo
                   else f"roughly **{_p_hi:,.0f}**")
                + f" rather than {PROJ['projected']:,.0f}."
            )
            st.caption(
                f":orange[**None of that is in the box**, which counts only cattle "
                f"that have crossed — and an announced reopening is not a "
                f"reopening.] On 8 July 2025 AMS published that {_w['port']} and "
                f"Santa Teresa would reopen on the 14th and 21st. Neither did: "
                f"{_w['port']} has not appeared since {fmt_date(_w['last_seen'])}, "
                f"Santa Teresa recorded nothing between May 2025 and its actual "
                f"return on Sep 24, 2026, and that July reopening ran four "
                f"reporting days of Douglas alone before the border shut again. "
                f"The projection moves when cattle cross, not when a date is "
                f"announced."
            )

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Next year, as scenarios ─────────────────────────────────────────────────
    # NOT a second projection. The box above is anchored -- most of its answer is
    # head that have already crossed -- and none of next year has happened at all.
    # So this is four scenarios rather than a number with an error bar, each one
    # answering a different question, and the header says "scenarios" in the first
    # three words.
    OUTLOOK = D.get("outlook")
    if OUTLOOK and OUTLOOK["scenarios"]:
        _o = OUTLOOK
        _s = _o["scenarios"]
        _yr = _o["year"]
        st.markdown(f'<div class="sec-header">{_yr} Outlook — scenarios, not a '
                    f'forecast</div>', unsafe_allow_html=True)

        # Joined with "and" because these read mid-sentence: "the 57% Douglas,
        # Santa Teresa carry between them" parses as three ports, not two.
        _op = _o["open_ports"]
        _ports = (" and ".join(_op) if len(_op) < 3
                  else ", ".join(_op[:-1]) + " and " + _op[-1])
        # Named from the data, never typed in. The first tile IS the open ports --
        # today's pace comes from nothing else -- so it carries their names, and
        # the third has to spell out that it includes the watch port too, which
        # "those ports" stopped conveying once the first tile was named.
        _slash = "/".join(_op)
        c = st.columns(4)
        with c[0]:
            st.markdown(tile(
                _slash or "Nothing Changes",
                f"~{_s['as_is']:,.0f}",
                sub(f"today's {_o['pace']:,.0f} head/day × {_o['reporting_days']} "
                    f"reporting days"), "tile-scen"), unsafe_allow_html=True)
        with c[1]:
            st.markdown(tile(
                f"{_o['watch']} Reopens" if _o["watch"] else "One More Crossing",
                f"~{_s['watch']:,.0f}" if _o["watch"] else "—",
                # NOT "the pace Douglas and Santa Teresa had when THEY reopened".
                # That reading is unstable: their own first 10, 15 and 20 reporting
                # days give 21%, 38% and 49% of normal, so the increment would swing
                # from +68k to +154k on an arbitrary window, and Santa Teresa has
                # only 9 days on file so it drops out of the blend entirely past 9.
                # This is the maturity they are at NOW, which is one number.
                sub(f"+{_s['watch'] - _s['as_is']:,.0f} head, at the "
                    f"{_o['maturity'] * 100:.0f}% of normal {_ports} run now"
                    if _o["watch"] else "no watch port set"),
                "tile-scen"), unsafe_allow_html=True)
        with c[2]:
            st.markdown(tile(
                "/".join(_op + ([_o["watch"]] if _o["watch"] else [])),
                f"~{_s['mature']:,.0f}",
                sub("all three at their normal rates, not today's"
                    if _o["watch"] else "at their normal rates, not today's"),
                "tile-scen"), unsafe_allow_html=True)
        with c[3]:
            st.markdown(tile(
                f"All {_o['n_crossings']} Crossings",
                f"~{_s['normal']:,.0f}",
                sub(f"the whole border at {_o['normal_rate']:,.0f} head/day"),
                "tile-scen"), unsafe_allow_html=True)

        st.caption(
            f"**None of {_yr} has happened, so every figure here is a scenario.** "
            f"They are ordered, and the gaps between them are the point. "
            f"**{_slash}** carries today's {_o['pace']:,.0f} head a day "
            f"across all {_o['reporting_days']} of {_yr}'s reporting days — those "
            f"two crossings are the only ones taking cattle, so today's pace is "
            f"theirs entirely. "
            f"**{_o['watch']} reopens** adds the one crossing expected back: it "
            f"carried **{_o['watch_share'] * 100:.0f}% of every head** when the "
            f"border ran normally, against the **{_o['open_share'] * 100:.0f}%** "
            f"{_ports} carry between them, so it is about "
            f"{_o['watch_share'] / _o['open_share'] * 100:.0f}% more port capacity "
            f"— **+{_s['watch'] - _s['as_is']:,.0f} head**."
            if _o["watch"] else
            f"**None of {_yr} has happened, so every figure here is a scenario.**"
        )
        # Like for like: the two OPEN ports at normal, with no watch port in it.
        # The "recover" tile includes the watch port, so using that figure here
        # would credit maturity with a reopening and overstate the comparison.
        _open_at_normal = _o["open_share"] * _s["normal"]
        _maturity_worth = _open_at_normal - _s["as_is"]
        _watch_worth = _s["watch"] - _s["as_is"]
        st.caption(
            f"**The reopening is not the big number, and that is worth sitting "
            f"with.** {_ports} are open now and running at "
            f"**{_o['maturity'] * 100:.0f}% of what those two crossings normally "
            f"carry**. Bringing just those two up to normal — no new crossing at "
            f"all — is worth **+{_maturity_worth:,.0f} head**, about "
            f"**{_maturity_worth / _watch_worth:.0f}×** the "
            f"+{_watch_worth:,.0f} {_o['watch'] or 'another crossing'} adds. "
            f"A reopening is a headline; maturity is the volume."
        )
        # Derived, not written in: the naive figure has to move with the data or
        # it becomes a claim about numbers the page is no longer showing.
        _wp = D.get("watch_port")
        if _wp and _o["watch"]:
            _naive = _wp["per_day"] * _o["reporting_days"]
            st.caption(
                f":orange[**Why {_o['watch']} is "
                f"+{_s['watch'] - _s['as_is']:,.0f} and not "
                f"+{_naive:,.0f}.**] Added at its own old rate it would read the "
                f"larger figure — it moved {_wp['per_day']:,.0f} head on each day "
                f"it was open in {_wp['years'][0]}–{_wp['years'][-1]}. But that "
                f"has a crossing restarting from nothing and instantly outrunning "
                f"its neighbours by more than two to one, while they sit at "
                f"{_o['maturity'] * 100:.0f}% of their own normal. Scaling port "
                f"**capacity** is the consistent way to do it. The naive figure is "
                f"{_naive / (_s['watch'] - _s['as_is']):.1f}× too high and arrives "
                f"in the same units, which is why it is worth naming."
            )

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Import volumes: one chart, monthly or weekly ────────────────────────────
    # ONE chart with a toggle rather than two stacked charts: these answer the same
    # question at two resolutions, and showing both at once invites reading a
    # monthly bar against a weekly one.
    with st.container(key="wm-volumes"):
        st.markdown('<div class="sec-header">Import Volumes</div>',
                    unsafe_allow_html=True)

        gran = st.radio("Resolution", ["Monthly", "Weekly"], horizontal=True,
                        label_visibility="collapsed", key="vol_gran")

        if gran == "Monthly":
            raw = list(D["monthly"] or [])
            pts = [(pd.Timestamp(str(pp) + "-01"), h) for pp, h in raw]
            hover = "%{x|%b %Y}<br>%{y:,.0f} head<extra></extra>"
            src_note = (
                f"**US Census**, the official customs count, monthly back to 2019 "
                f"and current to {fmt_month(F['census_through'])}."
            )
        else:
            raw = list(D.get("weekly") or [])
            pts = [(pd.Timestamp(w), h) for w, h in raw]
            hover = "week of %{x|%b %d, %Y}<br>%{y:,.0f} head<extra></extra>"
            src_note = (
                "**USDA AMS**, weekly actuals. This series **starts in 2023** — AMS "
                "does not publish it any earlier, and Census, which does reach 2019, "
                "publishes monthly only. Splitting Census months into weeks would "
                "invent data, so the weekly view simply starts where the weekly data "
                "does. Switch to Monthly for the longer history."
            )

        if pts:
            xs = [x for x, _h in pts]
            ys = [h for _x, h in pts]
            srt = sorted(ys)
            n = len(srt)
            all_med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
            zeros = sum(1 for v in ys if v == 0)

            # The line shows NORMAL trade -- the median before the first closure --
            # not the median of everything plotted. A median spanning the closure
            # answers "what was a typical month over this period", which is not the
            # question anyone asks of this chart; they want to know what crosses
            # when the border is open. Both numbers are reported underneath so the
            # closure is not airbrushed out of the statistic.
            # min_run is "about a month of no trade" at each resolution. Weekly
            # needs 4 because single zero weeks happen during normal trade; monthly
            # needs 1 because a whole zero month never did until the border shut.
            #
            # Pass the ORIGINAL labels. The first version rebuilt them with
            # `str(x.date())` off the plotted Timestamps, which is a pointless
            # round-trip -- the labels are right there in `raw` -- and it took the
            # whole page down in production with an AttributeError that never fired
            # locally. Nothing here needs a date object; the label is opaque to
            # normal_baseline.
            #
            # The guard is deliberate. This is one decorative statistic on a page
            # with a dozen other things on it, and it has now demonstrated that it
            # can replace all of them with a traceback. A missing baseline degrades
            # to the all-periods median, which is still a true number.
            try:
                base = bd.normal_baseline([(str(p), h) for p, h in raw],
                                          min_run=1 if gran == "Monthly" else 4)
            except Exception as exc:
                base = None
                st.caption(f":orange[Normal-trade baseline unavailable "
                           f"({type(exc).__name__}); showing the all-periods "
                           f"median instead.]")
            med = base["median"] if base else all_med

            fig = go.Figure()
            fig.add_bar(x=xs, y=ys, marker_color=JPSI_BLUE, name="Head",
                        hovertemplate=hover)
            # Right, not left: at "top left" the label lands on top of the y-axis
            # tick numbers and neither can be read. The right end of both charts is
            # the closure period, so it is empty space. The solid background and
            # border keep it legible if a tall bar ever does reach under it.
            fig.add_hline(
                y=med, line_width=1.6, line_dash="dash", line_color=AMBER,
                annotation_text=(f"normal {med:,.0f}" if base
                                 else f"median {med:,.0f}"),
                annotation_position="top right",
                annotation_font=dict(color=AMBER, size=11),
                annotation_bgcolor=CARD_BG,
                annotation_bordercolor=AMBER,
                annotation_borderwidth=1,
                annotation_borderpad=3)
            fig.update_layout(
                height=340, margin=dict(l=10, r=24, t=10, b=10),
                paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                font=dict(color=TEXT, size=11), showlegend=False,
                xaxis=dict(gridcolor=BORDER, title=None),
                yaxis=dict(gridcolor=BORDER, title="Head", tickformat=","),
            )
            st.plotly_chart(fig, use_container_width=True)

            unit = "month" if gran == "Monthly" else "week"
            if base:
                st.markdown(
                    f"<div style='color:{MUTED};font-size:0.8rem;margin:-4px 0 6px;'>"
                    f"Normal trade: median <b style='color:{AMBER}'>{med:,.0f} head"
                    f"</b> per {unit} over the {base['n']:,} {unit}s before the "
                    f"border first closed ({fmt_month(base['from']) if gran == 'Monthly' else fmt_date(base['from'])}"
                    f" – {fmt_month(base['until']) if gran == 'Monthly' else fmt_date(base['until'])})."
                    f" &nbsp;·&nbsp; Across all {n:,} {unit}s plotted, including the "
                    f"{zeros} at zero, the median is {all_med:,.0f}."
                    f"</div>", unsafe_allow_html=True)
            else:
                st.markdown(
                    f"<div style='color:{MUTED};font-size:0.8rem;margin:-4px 0 6px;'>"
                    f"Median <b style='color:{AMBER}'>{med:,.0f} head</b> per {unit} "
                    f"across {n:,} {unit}s."
                    f"</div>", unsafe_allow_html=True)

            st.caption(
                src_note
                + (f" **The line is normal trade, not the median of the chart.** "
                   f"Dropping only the zero {unit}s would not do it: trade did not "
                   f"go from normal to nothing, it went through {unit}s that were "
                   f"open but crippled — February 2025 at 21,788 head, July at "
                   f"4,339 — and averaging those into the baseline understates "
                   f"normal by about 5%. So the baseline is everything before the "
                   f"first closure, and the all-{unit}s median is given above for "
                   f"comparison." if base and zeros else "")
            )

            if gran == "Monthly":
                st.caption(
                    f"**Not every decline here is the border.** The 2021–22 slide — "
                    f"from 1.44m head in 2020 to 869,630 in 2022 — was drought and "
                    f"herd liquidation in northern Mexico, with the border open the "
                    f"whole time; volume then recovered to about 1.24m in 2023 and "
                    f"2024. Only the collapse from December 2024 is New World "
                    f"Screwworm, and it came in two closures: the first took "
                    f"November 2024's 102,751 head to zero that December, then a "
                    f"partial reopening ran February–May 2025 before closing again "
                    f"in June. Census is current to "
                    f"{fmt_month(F['census_through'])}, so the August 2026 "
                    f"reopening is not in this chart yet — it should first appear "
                    f"in the August 2026 release, around early October."
                )
            else:
                st.caption(
                    "The weekly view shows the reopening that the monthly Census "
                    "chart cannot yet: the week of 24 August 2026 is the first "
                    "non-zero week since July 2025."
                )
        else:
            st.info("No volume data stored for this resolution yet.")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Border prices ───────────────────────────────────────────────────────────
    # The border quote is on the SAME basis as the index -- $/cwt, F.O.B., Medium
    # and Large, #1-2 steers -- which is what makes subtracting the two legitimate.
    st.markdown('<div class="sec-header">Border Prices</div>', unsafe_allow_html=True)

    grid, grid_date = D.get("price_grid", ([], None))
    spread = D.get("spread") or []
    spread_win = D.get("spread_win") or {}

    if grid:
        latest = spread[-1] if spread else None
        # The two newest OPEN WINDOWS. The len() >= 2 guard is not
        # decoration: one window is the state this page is in after the next
        # closure plus any rebuild that drops 2025, and [-2] would take the
        # whole Border Prices block down with an IndexError.
        _wk = list(spread_win)
        cur_w = spread_win[_wk[-1]] if _wk else None
        prev_w = spread_win[_wk[-2]] if len(_wk) >= 2 else None

        c = st.columns(4)
        with c[0]:
            # THE CROSSINGS ARE NAMED FROM THE DATA, NEVER TYPED. This read
            # "Douglas" over a figure that is AVG(avg_price) across whichever
            # crossings quoted that day -- on 2026-10-20 that is $324.50, the
            # mean of Douglas $324.00 and Santa Teresa $325.00, so it was
            # neither crossing's quote under one crossing's name. Both quote on
            # 9 of 2026's 32 priced days and Santa Teresa quotes ALONE on
            # several, where the label was simply the wrong port. Same defect
            # the Mexican Feeder Prices tab was corrected for.
            _xing = latest[4] if latest else []
            st.markdown(tile("700–800 lb #1-2 Steers",
                             f"${latest[1]:,.2f}" if latest else "—",
                             sub(f"{' + '.join(_xing)}, {fmt_date(latest[0])}"
                                 if latest and _xing
                                 else (fmt_date(latest[0]) if latest
                                       else "not quoted"))),
                        unsafe_allow_html=True)
        with c[1]:
            st.markdown(tile("CME Feeder Index",
                             f"${latest[2]:,.2f}" if latest else "—",
                             sub("same day, 12-state 700–899 lb")),
                        unsafe_allow_html=True)
        with c[2]:
            st.markdown(tile("Border Basis",
                             f"${latest[3]:,.2f}" if latest else "—",
                             sub("border minus index, $/cwt")), unsafe_allow_html=True)
        with c[3]:
            # THE LABEL CARRIES THE WINDOW, NEVER THE CALENDAR YEAR.
            # "2026 Avg Basis" was right only while the window and the year
            # coincided, which they do exactly today and stop doing on 1
            # January -- when it would roll to a near-empty "2027 Avg Basis"
            # over a window that began in August and never closed. "Since"
            # only while the window is open: once the border shuts, asserting
            # the figure is current is the one thing the label must not do.
            _nx = len(cur_w["crossings"]) if cur_w else 0
            st.markdown(tile(
                (f"Avg Basis Since {fmt_date(cur_w['start'], '%b %Y')}"
                 if cur_w and cur_w["open"]
                 else (f"Avg Basis, {win_span(cur_w)}" if cur_w
                       else "Avg Basis")),
                f"${cur_w['mean']:,.2f}" if cur_w else "—",
                # The crossing count stays in the sub. This page's documented
                # failure is a roster change reading as a market move, so the
                # size of the roster behind the figure belongs beside it.
                #
                # KEPT TO ONE LINE, AND THE BUDGET IS MEASURED RATHER THAN
                # COUNTED IN CHARACTERS. A .tile-sub here has 264px. The first
                # version of this read "32 quoted days to Oct 20 · 2 crossings
                # · prior window $-42.27", which renders 287px: it wrapped, and
                # took this tile to 131px against its three neighbours' 113.
                # That is the ragged row CLAUDE.md records for the Cash Cattle
                # Trade daily tiles -- py_compile, the suite and get_page_text
                # all pass it, and only a DOM measurement shows it.
                #
                # The end date came out because the label already carries the
                # window: "Since Aug 2026" while it is open (so it runs to
                # now), and both ends once it has closed.
                sub(f"{cur_w['n']} quoted days · {_nx} "
                    f"crossing{'s' if _nx != 1 else ''}"
                    + (f" · prior ${prev_w['mean']:,.2f}" if prev_w else "")
                    if cur_w else "")),
                unsafe_allow_html=True)

        # THE DAY'S HEAD, UNDER THE PRICES RATHER THAN BESIDE THEM. Five
        # tiles in one row is what broke the beef cutout page -- 128px each
        # and $375.62 split between characters -- and this row is already
        # four across.
        #
        # IT IS THE WHOLE DAY'S FEEDER CATTLE, NOT THE HEAD BEHIND A BRACKET.
        # AMS publishes the price grid with no volume on it at all, so there
        # is no head count per weight and none can be derived. Said in the
        # sentence rather than left to a footnote, because a head figure
        # printed under a 700-800 lb price reads as that rung's volume.
        _ph = D.get("price_head")
        if _ph:
            _parts = ", ".join(f"{p} {v:,}" for p, _st, v in _ph["by_crossing"])
            # The named crossings disagree with AMS's published total on 19 of
            # 463 days -- border_receipts is a hierarchy and the parts are a
            # BREAKDOWN, not an audit. A day they differ is AMS's arithmetic,
            # so the page says which figure is theirs and does not cry error.
            _split = ""
            if _parts:
                _split = (f" — {_parts}" if _ph["reconciles"]
                          else f" — reported by crossing as {_parts}, which "
                               f"does not add to it")
            _wtd = (f" Week to date **{_ph['wtd']:,}**."
                    if _ph.get("wtd") else "")
            # THE WEIGHTS ARE THE ONES AMS QUOTED, NOT AN AVERAGE OF WHAT
            # CROSSED, and the two are different populations on the same day:
            # the head is every feeder animal over the border, the span is the
            # brackets that traded in enough volume to price. No feed anywhere
            # publishes a head count against a weight -- see
            # border.weight_spans() for the four places that were checked --
            # so no weighted average exists to print instead.
            _sp = spans.get(grid_date)
            _wspan = ""
            if _sp:
                _cls = " and ".join(c.lower() for c in _sp["classes"]) or "cattle"
                _wspan = f" AMS quoted {_cls} at **{_sp['label']}**."
            st.caption(
                f"**{_ph['head']:,} head crossed that day**{_split}."
                f"{_wtd}{_wspan} The head is every feeder animal that crossed, "
                f"whatever it weighed; the span is the weights AMS found enough "
                f"trade to quote. It publishes no head against any weight, so "
                f"there is no average weight to be had and no volume behind any "
                f"single bracket."
            )

        if cur_w and prev_w:
            # Dollar signs MUST be escaped in st.caption. Two unescaped ones in the
            # same string make Streamlit treat everything between them as LaTeX
            # math, and this caption rendered as a wall of italic variables before
            # the escapes went in. The tiles above are exempt because they are raw
            # HTML. Escape in prose, never inside a code fence.
                # THE AVERAGE IS ACROSS CROSSINGS AND IS NOT DOUGLAS'S. This said
                # "Mexican cattle at Douglas averaged -42.27" where Douglas alone
                # averaged -45.74 and -42.27 is the mean over four crossings. Both
                # figures were real and the sentence belonged to neither.
                _bm = D.get("basis_move")
                _roster = ""
                if _bm and _bm.get("same_crossing") is not None:
                    # THE ROSTER CHANGED AND IT IS WORTH SAYING IT DID NOT
                    # MATTER. Four crossings quoted this rung in 2025 and two
                    # do now, which is exactly the setup where a move is really
                    # a roster change -- the trap six_state.bracket_move()
                    # exists for. Measured rather than assumed: holding both
                    # years to the crossings they share moves the narrowing by
                    # about a third of a point.
                    _roster = (
                        f" The crossings quoting it changed between them — "
                        f"{len(_bm['prior_panel'])} reported this rung in "
                        f"the earlier window and {len(_bm['year_panel'])} "
                        f"do now — but holding both windows to the "
                        f"{' and '.join(_bm['panel'])} pair they share gives "
                        f"**{_bm['same_crossing']:+.2f}** against the "
                        f"**{_bm['reported']:+.2f}** above, so the narrowing is "
                        f"the market rather than the roster."
                    )
                # The verb is COMPUTED, and the two periods are named as
                # SPANS rather than years -- the border was shut for 470
                # days between them, so "2025" and "2026" named
                # stretches of calendar that were mostly closed.
                st.caption(
                    f"**The border discount "
                    f"{narrowing_phrase(cur_w['mean'], prev_w['mean'])}.** "
                    f"Averaged over the crossings that quoted, Mexican "
                    f"cattle came in **\\${prev_w['mean']:,.2f}/cwt** "
                    f"under the index over **{win_span(prev_w)}** and "
                    f"**\\${cur_w['mean']:,.2f}** over "
                    f"**{win_span(cur_w)}** — consistent with scarcity, "
                    f"since the few head crossing are bid much closer to "
                    f"the US market."
                    + _roster
                    + f" These are the border's two open windows, not two "
                    f"calendar years: it was shut between them. Read the "
                    f"current figure with care — it rests on "
                    f"**{cur_w['n']} quoted days** against "
                    f"{prev_w['n']} in the earlier window."
            )

        t_now, t_wt, t_sp = st.tabs(
            ["Latest quotes", "By weight bracket", "vs CME index"])

        with t_now:
            st.dataframe(
                pd.DataFrame([{
                    "Class": c_, "Weight": f"{wl}–{wh} lb" if wh else f"{wl}+ lb",
                    "Grade": g or "—", "Low": lo, "High": hi, "Mid": mid,
                    "Crossing": cp,
                } for c_, wl, wh, g, lo, hi, mid, cp in grid]),
                use_container_width=True, hide_index=True)
            # COUNTED OVER THE WINDOW, not the calendar year, so both
            # halves of this sentence measure the same span. The quoted count
            # is the window's own n -- read off the same dict as the tile
            # rather than recounted here, since two counts of one thing is
            # how a page comes to disagree with itself.
            _reop = D.get("reopened")
            _cov_q = cur_w["n"] if cur_w else 0
            _cov_r = (len([1 for _d, _v, _w in daily if _d >= _reop])
                      if _reop else len(daily))
            st.caption(
                f"AMS quotes for **{fmt_date(grid_date)}**, $/cwt F.O.B. Prices are "
                f"published only when enough head sell to establish a trend, so a "
                f"day can report cattle crossing and carry no quote at all — "
                f"since the border reopened there have been "
                f"{_cov_q} quoted days against {_cov_r} reporting days."
                # "32 against 40" reads as though the missing eight were
                # empty. They were not, and the head that crossed on them is
                # the figure that says so.
                + (f" Those unquoted days were not empty: "
                   f"**{_hp[1] - _hp[0]:,} head** of the {_hp[1]:,} crossed "
                   f"on a day carrying no price."
                   if (_hp := D.get("head_priced")) and _hp[1] > _hp[0] else "")
            )

        with t_wt:
            ser = D.get("price_series") or {}
            if ser:
                fig = go.Figure()
                for label, pts in sorted(ser.items(),
                                         key=lambda kv: int(kv[0].split("-")[0])):
                    fig.add_trace(go.Scatter(
                        x=[pd.Timestamp(d) for d, _p in pts],
                        y=[p for _d, p in pts], mode="lines", name=label,
                        hovertemplate=f"{label}<br>%{{x|%b %d, %Y}}"
                                      "<br>$%{y:,.2f}/cwt<extra></extra>"))
                fig.update_layout(
                    height=340, margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                    font=dict(color=TEXT, size=11),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                    xaxis=dict(gridcolor=BORDER, title=None),
                    yaxis=dict(gridcolor=BORDER, title="$/cwt F.O.B."))
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    "#1-2 Medium & Large steers, one line per weight bracket. "
                    "**Kept separate on purpose:** AMS's brackets moved between 2024 "
                    "and 2025 — it quoted 300–400/400–500/500–600 through 2024 and "
                    "500–600/600–700/700–800 from 2025 — so a single blended "
                    "\"border price\" line would fold that change straight into the "
                    "trend and show a jump that is pure mix. The 700–800 lb bracket "
                    "simply does not exist before February 2025."
                )

        with t_sp:
            if spread:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=[pd.Timestamp(d) for d, _b, _f, _s, _c in spread],
                    y=[b for _d, b, _f, _s, _c in spread], mode="lines+markers",
                    name="Border, 700–800 #1-2", line=dict(color=AMBER, width=2),
                    marker=dict(size=5)))
                fig.add_trace(go.Scatter(
                    x=[pd.Timestamp(d) for d, _b, _f, _s, _c in spread],
                    y=[f for _d, _b, f, _s, _c in spread], mode="lines+markers",
                    name="CME Feeder Index", line=dict(color=JPSI_BLUE, width=2),
                    marker=dict(size=5)))
                fig.update_layout(
                    height=320, margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                    font=dict(color=TEXT, size=11),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                    xaxis=dict(gridcolor=BORDER, title=None),
                    yaxis=dict(gridcolor=BORDER, title="$/cwt"))
                st.plotly_chart(fig, use_container_width=True)

                st.dataframe(
                    pd.DataFrame([{"Window": win_span(d),
                                   "Quoted days": d["n"],
                                   "Mean basis": round(d["mean"], 2),
                                   "Median basis": round(d["median"], 2)}
                                  for d in reversed(
                                      list(spread_win.values()))]),
                    use_container_width=True, hide_index=True)
                st.caption(
                    "Both series are **$/cwt F.O.B.**, which is what makes "
                    "subtracting them meaningful — verified across all 10,401 price "
                    "rows, every one of which is Per Cwt and F.O.B. The comparison "
                    "is not exact: the border quote is 700–800 lb Mexican-origin "
                    "cattle at one crossing, the index is 700–899 lb US cattle sold "
                    "at auction and direct across 12 states. The gap is a real "
                    "market relationship — origin, quality, freight and who is "
                    "buying — not a mispricing. The index value used is JSA's "
                    "same-day reconstruction rather than CME's published file, "
                    "which runs 1–3 days behind; a spread against a stale index "
                    "would mostly measure the staleness."
                )
            else:
                st.info("No overlapping days between border quotes and the index.")
    else:
        st.info("No border price quotes stored yet.")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Daily crossings ─────────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">Daily Crossings</div>',
                unsafe_allow_html=True)

    # daily was bound above, for the year-to-date boxes.
    if daily:
        t_day, t_wtd, t_port, t_hist = st.tabs(
            ["Per day", "Week to date", "By crossing", "Against prior years"])

        with t_day:
            dx = [pd.Timestamp(d) for d, _v, _w in daily]
            dy = [v for _d, v, _w in daily]
            fig = go.Figure()
            fig.add_bar(x=dx, y=dy, marker_color=JPSI_BLUE,
                        hovertemplate="%{x|%a %b %d}<br>%{y:,.0f} head<extra></extra>")
            if SO and SO.get("from"):
                fig.add_vline(x=pd.Timestamp(SO["from"]), line_width=1.5,
                              line_dash="dot", line_color=POS)
                fig.add_annotation(x=pd.Timestamp(SO["from"]), y=1, yref="paper",
                                   text="reopened", showarrow=False, yanchor="bottom",
                                   font=dict(size=10, color=POS))
            fig.update_layout(
                height=320, margin=dict(l=10, r=10, t=24, b=10),
                paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                font=dict(color=TEXT, size=11), showlegend=False,
                xaxis=dict(gridcolor=BORDER, title=None),
                yaxis=dict(gridcolor=BORDER, title="Head", tickformat=","))
            st.plotly_chart(fig, use_container_width=True)
            zero = sum(1 for _d, v, _w in daily if v == 0)
            st.caption(
                f"Every reporting day in {this_yr}: {len(daily)} days, "
                f"{len(daily) - zero} with cattle and {zero} published with none. "
                f"Head counts are AMS estimates, rounded to the nearest hundred."
            )
            st.dataframe(
                pd.DataFrame([{"Date": d, "Head": v, "Week to date": w,
                               # A reporting day with no quote gets a dash
                               # rather than a carried-forward span: the
                               # head crossed, nothing was priced, and
                               # those are different facts.
                               "Weights quoted": (spans.get(d) or {})
                               .get("label", "–")}
                              for d, v, w in reversed(daily)]),
                use_container_width=True, hide_index=True)

        with t_wtd:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(d) for d, _v, w in daily],
                y=[w for _d, _v, w in daily], mode="lines+markers",
                line=dict(color=AMBER, width=2), marker=dict(size=6),
                hovertemplate="%{x|%a %b %d}<br>%{y:,.0f} head WTD<extra></extra>"))
            fig.update_layout(
                height=320, margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                font=dict(color=TEXT, size=11), showlegend=False,
                xaxis=dict(gridcolor=BORDER, title=None),
                yaxis=dict(gridcolor=BORDER, title="Head, week to date",
                           tickformat=","))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "AMS's running week-to-date total, which **resets each Monday** — "
                "the sawtooth is the reset, not a collapse in trade. Shown because "
                "it is how the AMS report itself presents the week."
            )

        with t_port:
            bc = D.get("by_crossing") or []
            if bc:
                st.dataframe(
                    pd.DataFrame([{"Crossing": p, "State": s, f"{this_yr} head": v}
                                  for p, s, v in bc]),
                    use_container_width=True, hide_index=True)
                st.caption(
                    "Per-crossing detail. These are a **breakdown, not an exact "
                    "decomposition** — AMS's per-crossing rows disagreed with its "
                    "own published total on 19 of 463 days measured, so the "
                    "headline figures above use AMS's total row rather than a sum "
                    "of these."
                )
            else:
                st.info(f"No per-crossing detail reported yet in {this_yr}.")

        with t_hist:
            by = D.get("by_year") or {}
            if by:
                years = sorted(by)
                fig = go.Figure()
                fig.add_bar(x=years, y=[by[y]["head"] for y in years],
                            marker_color=JPSI_BLUE, name="Head",
                            hovertemplate="%{x}<br>%{y:,.0f} head<extra></extra>")
                fig.update_layout(
                    height=300, margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                    font=dict(color=TEXT, size=11), showlegend=False,
                    xaxis=dict(gridcolor=BORDER, title=None, type="category"),
                    yaxis=dict(gridcolor=BORDER, title="Head", tickformat=","))
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(
                    pd.DataFrame([{"Year": y, "Head (AMS est.)": by[y]["head"],
                                   "Reporting days": by[y]["days"],
                                   "Head per reporting day":
                                       round(by[y]["head"] / by[y]["days"])
                                       if by[y]["days"] else 0}
                                  for y in years]),
                    use_container_width=True, hide_index=True)
                st.caption(
                    "Whole-year totals from the same daily series. **2023 is "
                    "incomplete** — AMS's daily volume section only runs from part "
                    "way through that year (156 reporting days against 225 in "
                    "2024), so its total is not comparable. 2024 and 2025 tie to "
                    "Census within about 3%, which is the cross-check that the "
                    "estimates are sound."
                )
    else:
        st.info("No daily receipts stored for this year yet.")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Tiles ───────────────────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">Current Activity</div>', unsafe_allow_html=True)

    this_year = str(date.today().year)
    last_year = str(date.today().year - 1)
    cy = D["crossings"].get(this_year, {"crossings": 0, "zero": 0, "reports": 0})
    ly = D["crossings"].get(last_year, {"crossings": 0, "zero": 0, "reports": 0})

    c = st.columns(4)
    with c[0]:
        st.markdown(tile("Import Status", headline.split(",")[0].title(),
                         sub(f"as of {fmt_date(S.get('latest_report'))}")),
                    unsafe_allow_html=True)
    with c[1]:
        st.markdown(tile(f"Crossing Days {this_year}", f"{cy['crossings']:,}",
                         sub(f"{cy['zero']} published days with no cattle")),
                    unsafe_allow_html=True)
    with c[2]:
        st.markdown(tile(f"Crossing Days {last_year}", f"{ly['crossings']:,}",
                         sub("same measure, full year")), unsafe_allow_html=True)
    with c[3]:
        st.markdown(tile("Days Since Reopening",
                         f"{reop['days_since']:,}" if reop.get("days_since") is not None else "—",
                         sub(f"reopened {fmt_date(reop.get('date'))}"
                             if reop.get("date") else "no reopening on record")),
                    unsafe_allow_html=True)

    st.caption(
        "Crossing days count report days on which cattle actually crossed. AMS began "
        "publishing on zero-crossing days in 2026, so counting reports instead would "
        f"read {cy['reports']} for {this_year} and understate the closure. It is a "
        "proxy for activity, not a head count — a crossing day covers whatever "
        "crossed that day, at whatever size."
    )

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Volume tiles ────────────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">Head Counts — Census</div>', unsafe_allow_html=True)

    ann = D["annual"]
    yrs = sorted(ann)
    prev_full = [y for y in yrs if ann[y] > 0]
    c = st.columns(4)
    for i, y in enumerate(yrs[-3:]):
        d = D["ytd"].get(y, {})
        with c[i]:
            st.markdown(tile(f"{y} Feeder Head", f"{ann[y]:,}",
                             pct_delta(d.get("pct"), " vs prior YTD")
                             + sub(f"{len(d.get('months', []))} months on file")),
                        unsafe_allow_html=True)
    with c[3]:
        peak = max(ann.values()) if ann else 0
        latest = ann[yrs[-1]] if yrs else 0
        drop = (latest / peak - 1) * 100 if peak else None
        st.markdown(tile("vs Peak Year", f"{drop:+.0f}%" if drop is not None else "—",
                         sub(f"{max(ann, key=ann.get)} peak of {peak:,} head"
                             if ann else "")), unsafe_allow_html=True)

    # ── Annual + crossing days, the two sources side by side ────────────────────
    st.markdown('<div class="sec-header">Both Sources, By Year</div>',
                unsafe_allow_html=True)
    years_all = sorted(set(list(map(str, ann.keys())) + list(D["crossings"].keys())))
    fig = go.Figure()
    fig.add_bar(x=years_all, y=[ann.get(int(y), 0) for y in years_all],
                marker_color=JPSI_BLUE, name="Census head",
                hovertemplate="%{x}<br>%{y:,.0f} head<extra></extra>")
    fig.add_trace(go.Scatter(
        x=years_all,
        y=[D["crossings"].get(y, {}).get("crossings", 0) for y in years_all],
        yaxis="y2", mode="lines+markers", name="Crossing days",
        line=dict(color=AMBER, width=2.5), marker=dict(size=8),
        hovertemplate="%{x}<br>%{y:,.0f} crossing days<extra></extra>"))
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT, size=11),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(gridcolor=BORDER, title=None, type="category"),
        yaxis=dict(gridcolor=BORDER, title="Census head", tickformat=","),
        yaxis2=dict(overlaying="y", side="right", title="Crossing days",
                    showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "The two independent sources track each other, which is the point of "
        f"showing them together — where they diverge, the AMS line leads. "
        f"{this_year} has {cy['crossings']} crossing days against a Census bar of "
        "zero, because the reopening has not reached Census yet."
    )

    # ── Ports ───────────────────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">Which Crossings Are Open</div>',
                unsafe_allow_html=True)
    if D["ports"]:
        pyears = sorted({y for d in D["ports"].values() for y in d})
        prows = []
        for p, d in D["ports"].items():
            row = {"Crossing": bd.title_port(p)}
            for y in pyears:
                row[y] = d.get(y, 0)
            prows.append(row)
        st.dataframe(pd.DataFrame(prows), use_container_width=True, hide_index=True)
        st.caption(
            f"Crossing days per year, per port of entry. {peak_open_n} crossings "
            f"were active in {peak_open_year}; the reopening has restarted "
            f"{len(S.get('active_ports') or [])} of them. Zero-crossing days are "
            "excluded, so a port publishing “no cattle crossed” does not count as "
            "open here."
        )

    # ── Weight composition ──────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">What Crosses — Weight Composition</div>',
                unsafe_allow_html=True)
    if D["bands"]:
        # A SWITCH RATHER THAN A SECOND CHART ALWAYS DRAWN. Both views read
        # the same already-loaded Census rows, so this is about the length of
        # the page rather than the cost of it -- the Cold Storage shape.
        _wc = st.segmented_control(
            "View", ["By month", "Latest year"], default="By month",
            label_visibility="collapsed", key="mfi_wc_view")
        # segmented_control returns None when the reader clears the selection.
        if _wc is None:
            _wc = "By month"
        _mix = D.get("band_mix")

    if D["bands"] and _wc == "By month" and _mix:
        _x = [pd.Timestamp(m + "-01") for m in _mix["months"]]
        # Light to heavy: the amber line is the one that collapses and the
        # dark one is the one that takes its place, so the two that move are
        # the two furthest apart in the palette.
        _cols = [AMBER, JPSI_BLUE, JPSI_DARK]
        fig = go.Figure()
        for _b, _c in zip(_mix["bands"], _cols):
            fig.add_trace(go.Scatter(
                x=_x, y=_mix["share"][_b], name=_b, mode="lines",
                line=dict(color=_c, width=2),
                # EXPLICIT, AND LOAD-BEARING. The series has a 14-month hole
                # where the border was shut; a bridged line would draw a
                # smooth handover from light cattle to heavy ones across
                # months in which nothing crossed at all.
                connectgaps=False,
                customdata=_mix["head"],
                hovertemplate="%{x|%b %Y}<br>" + _b +
                              ": %{y:.1f}%<br>%{customdata:,} head that month"
                              "<extra></extra>"))
        if SO and SO.get("from"):
            fig.add_vline(x=pd.Timestamp(SO["from"]), line_width=1.5,
                          line_dash="dot", line_color=POS)
            fig.add_annotation(x=pd.Timestamp(SO["from"]), y=1, yref="paper",
                               text="reopened", showarrow=False,
                               yanchor="bottom", font=dict(size=10, color=POS))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=24, b=10),
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            font=dict(color=TEXT, size=11),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            xaxis=dict(gridcolor=BORDER, title=None),
            yaxis=dict(gridcolor=BORDER, title="% of head",
                       ticksuffix="%", rangemode="tozero"))
        st.plotly_chart(fig, use_container_width=True)

        _bl, _lt = _mix.get("baseline"), _mix.get("latest")
        if _bl and _lt:
            _lo, _hi = _mix["bands"][0], _mix["bands"][-1]
            _lab = lambda b: b.split(" (")[0]   # noqa: E731
            st.caption(
                f"**The cattle crossing got heavier, and it happened at the "
                f"closure.** Over the twelve months before the border first "
                f"shut ({fmt_month(_bl['from'])} – {fmt_month(_bl['to'])}, "
                f"{_bl['head']:,} head) **{_lab(_lo)}** was "
                f"**{_bl['share'][_lo]:.1f}%** of head and **{_lab(_hi)}** was "
                f"**{_bl['share'][_hi]:.1f}%**. In "
                f"**{fmt_month(_lt['month'])}** they are "
                f"**{_lt['share'][_lo]:.1f}%** and "
                f"**{_lt['share'][_hi]:.1f}%**. "
                f"AMS says the same by a different route — it stopped quoting "
                f"its 300–400 lb steer bracket after Feb 18, 2025 — and the "
                f"two are independent, one a customs count and the other a "
                f"price report."
            )
        _notes = []
        if _mix.get("thin"):
            # Named and dated rather than counted: a reader looking at the
            # 2025 spike needs to know THAT month is one load, and "two thin
            # months" does not tell them which.
            _notes.append(
                "One shipment moves a mix this thin — "
                + " and ".join(f"**{fmt_month(m)}** rests on {h:,} head"
                               for m, h in _mix["thin"])
                + ", against 85,000–150,000 in a normal month.")
        if _mix.get("omitted"):
            # "across the record" rather than a span in years, which would be
            # wrong the moment Census publishes another January.
            _notes.append(
                "Left off as too small to draw: "
                + ", ".join(f"{b.split(' (')[0]} at {h:,} head across the "
                            f"whole record"
                            for b, h in _mix["omitted"].items()) + ".")
        st.caption(
            "Gaps are months in which **no cattle crossed at all**, not months "
            "Census has yet to publish, and the lines are deliberately broken "
            "across them. "
            + (" ".join(_notes) + " " if _notes else "")
            + "**This is a mix, not an average weight.** Census's top class is "
            "open-ended — “320 kg or more” — so no average can be computed "
            "from it, and the one month that matters most is the one where "
            "that class is largest."
        )

    elif D["bands"]:
        bands = D["bands"]
        fig = go.Figure()
        fig.add_bar(x=[h for _, h, _ in bands], y=[b for b, _, _ in bands],
                    orientation="h", marker_color=JPSI_BLUE,
                    text=[f"{s:.1f}%" for _, _, s in bands], textposition="outside",
                    hovertemplate="%{y}<br>%{x:,.0f} head<extra></extra>")
        fig.update_layout(
            height=250, margin=dict(l=10, r=40, t=10, b=10),
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            font=dict(color=TEXT, size=11), showlegend=False,
            xaxis=dict(gridcolor=BORDER, title="Head", tickformat=","),
            yaxis=dict(gridcolor=BORDER, title=None,
                       categoryorder="array",
                       categoryarray=[b for b, _, _ in bands][::-1]),
        )
        st.plotly_chart(fig, use_container_width=True)
        # THE SAMPLE GOES BESIDE THE YEAR. band_shares picks the newest year
        # carrying any volume, and after a reopening that is a year holding
        # one shipment -- 2026 is 2,453 head against 1.24m in 2024. The
        # monthly view flags its thin months by name, so leaving this one
        # unflagged would make the same sample honest in one view and silent
        # in the other.
        _by_head = sum(h for _b, h, _s in bands)
        st.caption(
            f"Latest year with volume: **{D['band_year']}**, {_by_head:,} head."
            + (f" That is a shipment rather than a year — under "
               f"{bd.MIN_MIX_HEAD:,} head, where one load moves every share "
               f"above. The **By month** view shows how it got here."
               if _by_head < bd.MIN_MIX_HEAD else ""))

    if D["bands"]:
        # Below the branch on purpose: it describes the weight classes
        # themselves, so it is as true of the monthly view as of the annual
        # one, and stating it in only one of them would make the other read
        # as a different quantity.
        st.caption(
            "Census's top band is “320 kg or more”, and 320 kg is 705 lb — the "
            "very bottom of the CME index's 700–899 lb window. So nearly all "
            "Mexican cattle cross *below* index weight and only reach it after "
            "months on US feed. **An import cut moves the index with a lag, "
            "through supply — it never shows up in the index's own "
            "composition.** Imported cattle mostly go straight to feedyards "
            "under retained ownership and never sell through a USDA-reported "
            "auction, so they are not index-eligible."
        )

        if D["kinds"]:
            kt = D["kinds"]
            parts = " · ".join(f"{k}: {v:,}" for k, v in
                               sorted(kt.items(), key=lambda t: -t[1]))
            st.caption(
                f"{D['kind_year']} by entry type — {parts}. Only the feeder bucket "
                "is charted above: cattle entered for immediate slaughter, breeding "
                "stock and dairy cows answer different questions."
            )

    # ── Commentary log ──────────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">Border Market Commentary</div>',
                unsafe_allow_html=True)
    if D["commentary"]:
        crows = [{"Date": c["date"],
                  "Crossed": "Yes" if c["crossed"] else "No",
                  "Crossing": c["port"] or "—",
                  "Report": c["text"]}
                 for c in D["commentary"]]
        st.dataframe(pd.DataFrame(crows), use_container_width=True, hide_index=True,
                     column_config={"Report": st.column_config.TextColumn(width="large")})
        st.caption(
            "AMS's own words, newest first — trade tone, demand, and what the supply "
            "consisted of. The head counts above come from the same report's volume "
            "section; this is the colour that no number carries."
        )

    # ── Suspension timeline ─────────────────────────────────────────────────────
    with st.expander("Suspension timeline, in AMS's own words"):
        st.caption(
            "Import-relevant announcements only. AMS's status report covers both "
            "directions and its notes are classified by direction before being "
            "shown here — the September 2026 standing note is about **exports** to "
            "Mexico and is deliberately excluded from this list."
        )
        tl = D["timeline"]
        if tl:
            # Collapse consecutive identical announcements to their date range: the
            # same "IMPORTS ARE SUSPENDED" line repeats weekly for months, and 40
            # identical rows hide the handful of dates where something changed.
            collapsed, run = [], None
            for end, segs in tl:
                key = " | ".join(segs)
                if run and run["key"] == key:
                    run["from"] = end
                else:
                    if run:
                        collapsed.append(run)
                    run = {"key": key, "from": end, "to": end, "segs": segs}
            if run:
                collapsed.append(run)
            for r in collapsed:
                span = (fmt_date(r["to"]) if r["from"] == r["to"]
                        else f"{fmt_date(r['from'])} – {fmt_date(r['to'])}")
                st.markdown(f"**{span}** — {' '.join(r['segs'])}")
        else:
            st.info("No status announcements stored.")

    # ── Method ──────────────────────────────────────────────────────────────────
    for _ in portal_view.staff_expander("Sources and method"):
        st.markdown(f"""
**AMS (USDA Market News), current to {fmt_date(F['ams_through'])}**

- Report 3486, *Mexico to United States Feeder Cattle Import Summary* —
  section **Report Volume** gives daily receipts by crossing point
  (`receipts_current_est`, rounded to the nearest hundred head) and the
  week-to-date running total; section **Report Header** gives the narrative log.
- Report 3629, *U.S. – Mexico Livestock Imports/Exports* — section **Report
  Volume** gives exact weekly volumes with AMS's own year-to-date and
  prior-year-to-date; **Report Header** gives the weekly status note.
- MARS sections are **path** segments (`/reports/3486/Report%20Volume`). Passing
  `section` as a query parameter is accepted and silently ignored, returning the
  header — which is how this source was first mistaken for having no data.
- Daily figures are AMS **estimates**; weekly and YTD figures are **actuals**.
  Through 2026-09-04 the daily estimates summed to ~2,600 against an actual
  2,557 — a 1.7% rounding gap.
- Head counts use AMS's own "All Crossing Points / All Crossing States" row.
  The per-crossing rows are hierarchical rollups that triple-count if summed,
  and they disagreed with the published total on 19 of 463 days measured.
- Crossing days exclude days AMS published but reported no cattle crossing. AMS
  only began publishing those in 2026, so the raw report count understates the
  closure.

**Census (International Trade API), current to {fmt_month(F['census_through'])}**

- Live bovine animals, HS 0102, from Mexico (country code 2010), monthly,
  general imports, at the ten-digit commodity level.
- Quantity is Census's `UNIT_QY1`, checked on ingest to be “NO.” (number of
  head) rather than assumed.
- The HS10 code list is **discovered, not hardcoded** — the ten-digit breakouts
  get renumbered, and a code carrying all the volume one year can be empty the
  next. Entry types are classified at read time from the description, splitting
  off the “OTHER THAN PUREBRED BREEDING AND/OR DAIRY” exclusion clause first.
- Census publishes about six weeks after month end, so this series cannot
  answer what crossed last week. That is what the AMS status above is for.

**Not shown, and why**

- No price series **yet**. Report 3486's *Report Detail Current* section does
  carry structured prices, weight breaks, frame and muscle grade — it is simply
  not ingested here, and is the obvious next addition. Census value-per-head is
  a declared customs value that moves with both the market and the weight mix,
  so it is a level check rather than a quote.
""")

    st.markdown("<hr style='margin:18px 0 8px;'>", unsafe_allow_html=True)
    st.markdown(
        f'<div class="srcline">JSA · John Stewart &amp; Associates &nbsp;·&nbsp; '
        f'Border status USDA AMS Market News · Head counts US Census Bureau '
        f'International Trade &nbsp;·&nbsp; AMS through {fmt_date(F["ams_through"])} · '
        f'Census through {fmt_month(F["census_through"])}</div>',
        unsafe_allow_html=True)


# ── Mexican Feeder Prices ───────────────────────────────────────────────────
# The other half of the border: what the calf is worth BEFORE it crosses.
# Arithmetic and every read live in mx_prices.py, the same split as the
# Cold Storage view and the Packer Leverage tab.

@st.cache_data(ttl=1800, show_spinner=False)
def load_mx_prices(schema=mxp.SCHEMA):
    """One connection, everything the prices tab draws. None on any failure.

    `schema` keys the cache, and BOTH halves matter: no leading underscore (Streamlit drops underscore-prefixed arguments from the key) and the CALLER must pass it (a default is never hashed). st.cache_data keys
    on the decorated function's own code and arguments and NEVER on the modules
    it calls, so without it a change to mx_prices.compare()'s shape would keep
    serving a dict from before the new key existed and the tiles would render
    "—" with nothing raising. The trap is recorded in CLAUDE.md for
    leverage.SCHEMA and am_cutout.SCHEMA; bump mxp.SCHEMA, not this line.
    """
    conn = None
    try:
        conn = db.get_conn()
        cmp_ = mxp.compare(conn)
        if not cmp_:
            return None
        series = mxp.ratio_series(conn, "M")
        return {"cmp": cmp_,
                "history": [(r["date"], r["pct"], r["usd"], r["us"])
                            for r in series],
                "series": series,
                # Every step, plus first->last, so the panel can say WHICH
                # driver moved the ratio rather than leaving it to be read off
                # a line that is mostly a currency chart.
                "steps": [(series[i], series[i + 1],
                           mxp.decompose(series[i], series[i + 1]))
                          for i in range(len(series) - 1)],
                "overall": (mxp.decompose(series[0], series[-1])
                            if len(series) > 1 else None),
                "steer": mxp.headline(cmp_, "M"),
                "heifer": mxp.headline(cmp_, "F")}
    except Exception as e:
        st.session_state["_mxp_error"] = f"{type(e).__name__}: {e}"
        return None
    finally:
        if conn is not None:
            conn.close()


with tab_prices:
    st.markdown('<div class="sec-header">Mexican Feeder Prices</div>',
                unsafe_allow_html=True)

    MX = load_mx_prices(mxp.SCHEMA)

    if not MX:
        st.info(
            "**No Mexican auction prices recorded yet.** This view reads "
            "`JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES`, written by the "
            "`mx_auction.py` job. The source keeps only the current sale and "
            "one previous, with no archive and no date parameter, so the "
            "history accrues from the first run and cannot be back-filled."
        )
        if st.session_state.get("_mxp_error"):
            st.caption(f"Detail: `{st.session_state['_mxp_error']}`")
    else:
        C = MX["cmp"]
        steer = MX["steer"]

        # THE CAVEAT GOES FIRST, NOT IN A FOOTNOTE. The figures below are
        # correctly computed and describe a different state's cattle from the
        # ones crossing at Douglas; a reader who meets the number before the
        # caveat has already drawn the wrong conclusion.
        st.warning(
            "**Tamaulipas is not where these cattle come from.** Douglas and "
            "Santa Teresa take **Sonora** and **Chihuahua** cattle, and neither "
            "state runs a published feeder auction — the only figures for them "
            "anywhere are association spokesmen quoted in the Mexican press. "
            "Tamaulipas is a northern border state that publishes real feeder "
            "bands by weight, which makes it the closest honest comparator and "
            "not the right one. Read the gap below as *what a Mexican feeder "
            "market pays*, never as the export premium at Douglas."
        )

        c = st.columns(4)
        with c[0]:
            st.markdown(tile(
                "Tamaulipas Steer Calf",
                f"${steer['usd']:,.2f}" if steer else "—",
                sub(f"{steer['low_lb']:.0f}–{steer['high_lb']:.0f} lb · $/cwt"
                    if steer else "no matched band")), unsafe_allow_html=True)
        # THE CROSSING IS NAMED FROM THE DATA, NOT TYPED. Douglas and Santa
        # Teresa both quote on the same day and disagree -- $310 against $315
        # at 700-800 lb on 2026-09-30 -- so a hard-coded "Douglas" is wrong on
        # any day only the other one quoted.
        _cross = (C.get("us_crossings") or {}).get("M")
        with c[1]:
            st.markdown(tile(
                f"Same Weight at {_cross}" if _cross else "Same Weight at Border",
                f"${steer['us_price']:,.2f}" if steer else "—",
                sub(f"AMS #1-2 steers, read at {steer['us_at_lb']:.0f} lb"
                    if steer else "not quoted")),
                unsafe_allow_html=True)
        with c[2]:
            st.markdown(tile(
                "Mexico as % of Border",
                f"{steer['pct']:.0f}%" if steer else "—",
                sub("auction price ÷ border quote")), unsafe_allow_html=True)
        # THE FOURTH TILE IS THE CHANGE, NOT THE LEVEL, which is the point of
        # the panel: the level carries Tamaulipas' geography, the export
        # selection and the certification premium, none of which move week to
        # week. But a change tile that does not say WHAT moved is worse than
        # none -- the first three sales fell 3.55 points while the Mexican
        # market in pesos ROSE 0.24%, the whole move being the peso.
        _ov = MX.get("overall")
        _dom = mxp.dominant(_ov)
        with c[3]:
            st.markdown(tile(
                (f"Change since {fmt_date(MX['series'][0]['date'], '%b %d')}"
                 if _ov else "Change"),
                (f"{_ov['pts']:+.1f} pts" if _ov else "—"),
                sub(f"mostly {_dom[1]}" if _dom else
                    "one sale on file — no change yet")),
                unsafe_allow_html=True)

        _gap = C["gaps"].get("M")
        _gapwords = (f" — **{_gap} day{'s' if _gap != 1 else ''} apart**. "
                     if _gap else ". ")
        _fxwords = (
            f"Converted at **{C['fx']:,.4f} MXN/USD**, the ECB reference rate "
            f"for {fmt_date(C['fx_date'])} — the rate that stood when the sale "
            f"traded, not today's, so a past sale is never restated by a later "
            f"move in the peso." if C["fx"]
            else "No exchange rate is recorded for this sale.")
        st.caption(
            f"Sale of **{fmt_date(C['sale_date'])}** at "
            f"{C['auction'].title()}, against the AMS "
            f"**{_cross or 'border'}** quote for "
            f"**{fmt_date(C['us_dates'].get('M'))}**" + _gapwords + _fxwords)

        # DERIVED, NOT TYPED. This sentence carried a hard-coded "60%" and the
        # headline moved to 59% the moment the AMS price started being read off
        # the slide instead of a bracket -- so the tile and the sentence six
        # inches below it disagreed about the same figure. That is the
        # letter-vs-dashboard failure CLAUDE.md records twice, in miniature:
        # both numbers defensible, neither raising. The Packer Leverage tab's
        # honesty check is computed live for the same reason.
        _pct = steer["pct"] if steer else None
        st.caption(
            "This is a **level, not a margin**. Nothing here nets out freight, "
            "the test, the crossing fee, shrink or the buyer's margin"
            + (f", so a calf worth {_pct:.0f}% of the border price is not "
               f"{100 - _pct:.0f}% of profit." if _pct else ".")
        )

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        # "How this is built" is provenance -- which AMS report, which rows
        # are excluded, how a week is defined. It keeps a reader of this code
        # honest and it is not what a client opened the page for.
        t_bands, t_hist, t_method = portal_view.tabs(
            ["By weight band", "What moved it", "How this is built"],
            hide={"How this is built"})

        with t_bands:
            _rows = []
            for r in C["rows"]:
                _rows.append({
                    "Class": r["clasificacion"],
                    "Sex": "Steer" if r["sex"] == "M" else "Heifer",
                    "Weight (kg)": (f"{r['low_kg']:.0f}–{r['high_kg']:.0f}"
                                    if r["low_kg"] and r["high_kg"]
                                    else (f"<{r['high_kg']:.0f}"
                                          if r["high_kg"] else "—")),
                    "Weight (lb)": (f"{r['low_lb']:.0f}–{r['high_lb']:.0f}"
                                    if r["low_lb"] and r["high_lb"]
                                    else (f"<{r['high_lb']:.0f}"
                                          if r["high_lb"] else "—")),
                    "MXN/kg": (f"{r['price_avg']:,.2f}"
                               if r["price_avg"] is not None else "—"),
                    "USD/cwt": f"${r['usd']:,.2f}" if r["usd"] else "—",
                    "AMS read at": (f"{r['us_at_lb']:.0f} lb"
                                    if r["us_price"] else "—"),
                    "AMS $/cwt": (f"${r['us_price']:,.2f}"
                                  if r["us_price"] else "—"),
                    "% of AMS": f"{r['pct']:.0f}%" if r["pct"] else "—",
                })
            st.dataframe(pd.DataFrame(_rows), use_container_width=True,
                         hide_index=True)

            # A whole sex with no counterpart is a fact about the US feed, not
            # a failed join, and a column of dashes cannot tell the reader
            # which. AMS stopped quoting Spayed Heifers in May 2025.
            for _sex, _lastq in (C.get("us_last") or {}).items():
                _which = "steer" if _sex == "M" else "heifer"
                _cls = mxp.US_CLASS_BY_SEX[_sex]
                if _lastq:
                    st.info(
                        f"**No border quote for {_which} calves.** AMS last "
                        f"priced *{_cls}* at the border on "
                        f"**{fmt_date(_lastq)}** — every 2026 quoted day is "
                        f"Steers. The {_which} bands above are still converted "
                        f"to $/cwt; they simply have nothing on the US side to "
                        f"sit beside, which is the feed's state and not a "
                        f"failed match."
                    )
                else:
                    st.info(
                        f"**No border quote for {_which} calves.** AMS has "
                        f"never priced *{_cls}* at grade "
                        f"{mxp.US_GRADE} in this record."
                    )

            _slide = (C.get("us_slide") or {}).get("M") or []
            st.caption(
                "**The AMS column is read off the quote slide at each band's "
                "own weight, not taken from a bracket.** AMS quotes brackets — "
                + (" · ".join(f"\\${p:,.0f} at {w:.0f} lb" for w, p in _slide)
                   if _slide else "none quoted")
                + " — and feeder prices slide with weight, so a 443–507 lb lot "
                "is priced at what a 475 lb calf is worth rather than being "
                "forced into 400–500 or 500–600. Those two choices gave 55% "
                "and 60% for the same animal, which is why neither was kept. "
                "Inside the lightest and heaviest brackets the slide is flat, "
                "because there USDA's own quote is the answer."
            )
            st.caption(
                "A band shows no AMS figure when its weight falls outside "
                "everything AMS quoted — the 351–400 kg lot is 774–882 lb and "
                "AMS stops at 800, so the slide is not run past the end of its "
                "own data — or when it is one of the wide **CNH** lots. Those "
                "are priced in dollars and left uncompared."
            )

        with t_hist:
            _ser = MX["series"]
            if len(_ser) > 1:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=[pd.Timestamp(str(r["date"])) for r in _ser],
                    y=[r["pct"] for r in _ser],
                    mode="lines+markers", name="Mexico as % of border",
                    line=dict(color=JPSI_BLUE, width=2.5)))
                # THE PESO PRICE RIDES ALONGSIDE ON ITS OWN AXIS, because the
                # two lines diverging IS the finding. The ratio fell 3.55
                # points over the first three sales while this line was flat.
                fig.add_trace(go.Scatter(
                    x=[pd.Timestamp(str(r["date"])) for r in _ser],
                    y=[r["mxn_kg"] for r in _ser],
                    mode="lines+markers", name="Tamaulipas, MXN/kg",
                    yaxis="y2",
                    line=dict(color="#B07A2A", width=2, dash="dot")))
                fig.update_layout(
                    height=330, margin=dict(l=10, r=10, t=30, b=10),
                    yaxis=dict(title="% of AMS border quote"),
                    yaxis2=dict(title="MXN/kg", overlaying="y", side="right",
                                showgrid=False),
                    xaxis_title=None, plot_bgcolor="white",
                    legend=dict(orientation="h", y=1.15, x=0))
                st.plotly_chart(fig, use_container_width=True)

                st.markdown(
                    "**Read the two lines against each other.** When they "
                    "move apart, the ratio is telling you about the peso "
                    "rather than about cattle."
                )

                _rows = []
                for _a, _b, _d in MX["steps"]:
                    if not _d:
                        continue
                    _rows.append({
                        "From": fmt_date(_a["date"], "%b %d"),
                        "To": fmt_date(_b["date"], "%b %d"),
                        "Ratio": f"{_a['pct']:.1f}% → {_b['pct']:.1f}%",
                        "Move": f"{_d['pts']:+.2f} pts",
                        "Mexican mkt (pesos)": f"{_d['mxn']:+.2f}%",
                        "Peso vs USD": f"{_d['fx']:+.2f}%",
                        "US border": f"{_d['us']:+.2f}%",
                    })
                if _rows:
                    st.dataframe(pd.DataFrame(_rows),
                                 use_container_width=True, hide_index=True)

                _o = MX.get("overall")
                _dm = mxp.dominant(_o)
                if _o and _dm:
                    st.info(
                        f"**Over the whole record the ratio moved "
                        f"{_o['pts']:+.2f} points, and most of that was "
                        f"{_dm[1]} ({_dm[2]:+.2f}%).** The three parts are a "
                        f"log decomposition and sum to the total exactly "
                        f"(residual {_o['residual']:+.4f}%), so this is "
                        f"arithmetic rather than an attribution model."
                    )
                    st.caption(
                        "**Which number you want depends on the question.** "
                        "*Are Mexican cattle cheapening?* — read the "
                        "**Mexican market (pesos)** column alone; currency is "
                        "no part of that. *Is exporting more attractive?* — "
                        "read the whole ratio, because a weaker peso genuinely "
                        "does make a US sale worth more at home. The two can "
                        "point opposite ways in the same week, and over this "
                        "record they do."
                    )
            st.caption(
                f"**{len(_ser)} sale{'s' if len(_ser) != 1 else ''} on file.** "
                f"mexicoganadero.com keeps the current sale and one previous, "
                f"with no archive and no date parameter, so this cannot be "
                f"back-filled — it accrues from the first run of the recording "
                f"job, the same shape as the morning cutout table. A short "
                f"record is the age of the series, not a broken feed, and "
                f"three sales is far too few to call a trend."
            )

        if portal_view.shown(t_method):
            with t_method:
                st.markdown(_MX_METHOD)

        st.markdown("<hr style='margin:18px 0 8px;'>", unsafe_allow_html=True)
        st.markdown(
            f'<div class="srcline">JSA · John Stewart &amp; Associates '
            f'&nbsp;·&nbsp; Mexican auction prices mexicoganadero.com '
            f'({C["auction"].title()}) · Border quotes USDA AMS 3486 · '
            f'FX European Central Bank &nbsp;·&nbsp; sale '
            f'{fmt_date(C["sale_date"])}</div>',
            unsafe_allow_html=True)


# ── Corn demand ─────────────────────────────────────────────────────────────
# STAFF ONLY. See the note at the tab construction above.
if portal_view.shown(tab_corn):
    with tab_corn:

        @st.cache_data(ttl=21600, show_spinner=False)
        def load_corn(schema=cdm.SCHEMA):
            """Two keyless PSD bulk files, about 4 seconds. No secret, no
            host, no cron -- which is why this is a page fetch rather than a
            droplet job."""
            try:
                return cdm.load()
            except Exception as e:                    # noqa: BLE001
                st.session_state["_corn_err"] = f"{type(e).__name__}: {e}"
                return None

        # PASSED, never left to the default: st.cache_data hashes the
        # arguments it is CALLED with, so a parameter sitting at its default
        # contributes nothing to the key.
        CD = load_corn(cdm.SCHEMA)

        st.markdown('<div class="sec-header">Corn Demand That Moves With '
                    'These Cattle</div>', unsafe_allow_html=True)

        if not CD:
            st.warning(
                f"USDA PSD is not answering — {st.session_state.get('_corn_err', 'no detail')}"
            )
        else:
            _sf, _base, _ly, _lh = cdm.crossing_shortfall(CD["cattle"])

            st.caption(
                f"While the border was shut, cattle that would have crossed "
                f"were kept and fed in **Mexico**, on corn Mexico buys from "
                f"the **United States**. Mexican exports ran **{_base:,.0f} "
                f"head** a year over 2022–24 and **{_lh:,.0f}** in MY{_ly}, a "
                f"shortfall of **{_sf:,.0f} head**. What that is worth in "
                f"corn, and where the demand goes when they cross again, is "
                f"below — every figure rests on the feeding assumptions in "
                f"the controls, which are **assumptions and not measurements**."
            )

            # THE FULL SHORTFALL IS A SCENARIO, NOT WHAT IS HAPPENING.
            # Reopening is phased -- Douglas 2026-08-24, Santa Teresa 09-24
            # capped at 750 head a day, Columbus 10-26, Nogales planned for
            # 11-30 -- and the flow is running near a third of normal. USDA's
            # own MY2027 forecast is 625,000 head, half of 2024. Headlining
            # the full return without a control would size something nobody
            # expects soon.
            _psd_next = (CD["cattle"].get(_ly + 1, {}).get("Exports", 0.0)
                         * 1000)
            # CAPPED ON THE RECORD, NOT ON A RECENT MEAN. This was capped
            # at the 2022-24 average of about 1.17m, which is not a ceiling:
            # that window spans two weak years, and Mexico has shipped
            # 1.49-1.66m three times. Typing an ordinary 1.3m recovery turned
            # the box red with nothing saying why.
            _peak, _peak_yr = cdm.peak_exports(CD["cattle"])
            _head = st.number_input(
                "Head a year that stop being fed in Mexico", 0,
                int(max(_peak, _base)), int(_sf), 25_000, key="cd_head",
                format="%d",
                help=f"Defaults to the full shortfall against a normal year "
                     f"({_sf:,.0f} head). USDA's MY{_ly+1} forecast implies "
                     f"about {max(0.0, _base - _psd_next):,.0f}; the crossing "
                     f"pace so far since August is nearer a third of normal "
                     f"again. The Crossings tab has the live count. The box "
                     f"accepts up to {_peak:,.0f}, the most Mexico has "
                     f"shipped in a year on USDA's record ({_peak_yr}) — the "
                     f"herd grew about a million head during the closure, so "
                     f"that is a generous bound rather than a hard limit.")

            # THESE ARE YARD WEIGHTS, NOT BORDER WEIGHTS. The pounds between
            # the crossing and the bunk are grass on both sides -- in Mexico
            # the first 100-150 kg carries no grain at all -- and charging
            # them as corn inflates every figure below by about 40%.
            st.caption(
                "Feedlot **entry** weight, not crossing weight: the pounds "
                "between the border and the bunk are put on at grass on both "
                "sides, and cost no corn. **The two sides are measured on "
                "different bases** — K-State publishes US feed:gain on dry "
                "matter, UNAM's Mexican programme is as fed — so each box "
                "says which it wants, and only the US side carries the "
                "corn-moisture step."
            )
            c2, c3 = st.columns(2)
            with c2:
                st.markdown("**Fed in Mexico**")
                _mxi = st.number_input("On feed at, lb", 400.0, 1000.0,
                                       float(cdm.MX_FEEDLOT_IN_LB), 25.0,
                                       key="cd_mxi")
                _mxf = st.number_input("Finish weight, lb", 800.0, 1500.0,
                                       float(cdm.MX_FINISH_LB), 25.0,
                                       key="cd_mxf")
                _mxc = st.number_input(
                    "Feed conversion, lb feed per lb gain — AS FED",
                    4.0, 12.0, float(cdm.MX_CONVERSION), 0.1, key="cd_mxc",
                    help="UNAM's conventional Mexican finishing programme: "
                         "6.0–6.5 as fed. As-fed figures already carry the "
                         "water, so no moisture step is applied to this side.")
                # WHOLE PERCENTS. On a 0-1 slider Streamlit applies
                # `format` to the raw value, so 0.65 printed as "1%" while
                # the arithmetic below was correct -- a label that lies
                # about a control nobody would doubt.
                _mxs = st.slider("Corn share of ration", 0, 100,
                                 int(round(cdm.MX_CORN_SHARE * 100)), 1,
                                 key="cd_mxs", format="%d%%",
                                 help="Corn as a share of the AS-FED ration. "
                                      "UNAM: ration 85% concentrate, of which "
                                      "60–70% grain, and corn 75–90% of that "
                                      "grain — so 38–54% of the ration. "
                                      "Mexican yards lean on sorghum and "
                                      "byproduct.")
            with c3:
                st.markdown("**Fed in the US**")
                _usi = st.number_input("On feed at, lb ", 500.0, 1100.0,
                                       float(cdm.US_FEEDLOT_IN_LB), 25.0,
                                       key="cd_usi")
                _usf = st.number_input("Finish weight, lb ", 1000.0, 1700.0,
                                       float(cdm.US_FINISH_LB), 25.0,
                                       key="cd_usf")
                _usc = st.number_input(
                    "Feed conversion, lb feed per lb gain — DRY MATTER",
                    4.0, 12.0, float(cdm.US_CONVERSION), 0.1, key="cd_usc",
                    help="K-State Focus on Feedlots, August 2026 closeouts: "
                         "6.47 on a dry-matter basis. Corn is marketed at "
                         "about 15.5% moisture, so this side carries a "
                         "moisture step the Mexican one does not.")
                _uss = st.slider("Corn share of ration ", 0, 100,
                                 int(round(cdm.US_CORN_SHARE * 100)), 1,
                                 key="cd_uss", format="%d%%",
                                 help="Corn as a share of ration DRY MATTER. "
                                      "The Samuelson nutritionist survey puts "
                                      "finishing grain at 50–90% of DM; 65% "
                                      "is mid-range for a steam-flaked yard. "
                                      "corn_cost.py's own 80% is an AS-FED "
                                      "rule of thumb and is not this number.")

            # /100 HERE, not in the widget: the sliders carry whole
            # percents so their labels read correctly.
            R = cdm.displaced(_head, mx_in=_mxi, mx_finish=_mxf, mx_conv=_mxc,
                              mx_share=_mxs / 100.0, us_in=_usi,
                              us_finish=_usf, us_conv=_usc,
                              us_share_corn=_uss / 100.0)

            # WHERE EVERY NUMBER COMES FROM, under the controls that set
            # them. Ross asked twice; the answer was in a docstring and a
            # tooltip, neither of which is where a reader of the tiles looks.
            # Built from cdm.SOURCES so a default that moves without its
            # citation shows up rather than going quiet.
            with st.expander("Where these figures come from"):
                st.caption(
                    "**The two sides are not equally sourced.** The US "
                    "programme is measured and has two independent "
                    "cross-checks. The Mexican one rests on a single "
                    "extension source, a ration share derived from three "
                    "published parts, and a feedlot entry weight that is "
                    "**ours** — nothing publishes it. That difference is "
                    "worth knowing before trading on the gap between the "
                    "two tiles."
                )
                _GRADE = {
                    "measured": "measured — a published figure, used as published",
                    "judgement": "judgement — a published RANGE, point chosen here",
                    "derived": "derived — arithmetic on published parts",
                    "ours": "OURS — an inference with no published counterpart",
                }
                st.dataframe(
                    pd.DataFrame([{
                        "Side": r["side"],
                        "Input": r["input"],
                        "Published": r["sourced"],
                        "Grade": _GRADE[r["strength"]].split(" — ")[0],
                        "Source": r["cite"],
                        "Note": r["note"],
                    } for r in cdm.SOURCES]),
                    use_container_width=True, hide_index=True)

                st.caption("  ·  ".join(_GRADE.values()))

                st.markdown("**Independent cross-checks**")
                for _cc in cdm.CROSS_CHECKS:
                    _line = (f"- **{_cc['side']}** — {_cc['says']} "
                             f"({_cc['cite']})")
                    if _cc.get("agrees"):
                        st.markdown(_line + " — agrees.")
                    else:
                        st.markdown(_line + f" — **{_cc.get('caveat','')}**")

                st.caption(
                    "Neither per-head figure is itself published. Each is "
                    "three inputs multiplied together, which is why they are "
                    "controls rather than constants, and why the cross-checks "
                    "above matter more than any single one of them."
                )

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            t = st.columns(3)
            with t[0]:
                st.markdown(tile(
                    "US corn EXPORT demand lost",
                    f"{R['export_bu']/1e6:,.0f} mil bu",
                    sub(f"corn Mexico stops feeding · "
                        f"{R['per_head_mx_bu']:.0f} bu a head")),
                    unsafe_allow_html=True)
            with t[1]:
                st.markdown(tile(
                    "US corn DOMESTIC demand gained",
                    f"{R['domestic_bu']/1e6:,.0f} mil bu",
                    sub(f"corn US yards feed instead · "
                        f"{R['per_head_us_bu']:.0f} bu a head")),
                    unsafe_allow_html=True)
            with t[2]:
                # THE NET IS NOT OPTIONAL. The export tile on its own is
                # arithmetically right and tells a reader the opposite of what
                # happens to US corn demand, which is the standing failure
                # this repo records. The two are never shown without it.
                _net = R["net_bu"] / 1e6
                st.markdown(tile(
                    "NET US corn demand",
                    f"{_net:+,.0f} mil bu",
                    sub("domestic gain less export loss, a year"),
                    cls="" if _net >= 0 else "tile-scen"),
                    unsafe_allow_html=True)

            st.caption(
                f"**The demand does not disappear — it moves, and it grows.** "
                f"The same calf eats **{R['per_head_mx_bu']:.0f} bushels** "
                f"finished in Mexico and **{R['per_head_us_bu']:.0f}** "
                f"finished in a US yard, because it goes to a heavier finish "
                f"on a more corn-dense ration north of the border. So "
                f"reopening costs the **export** line and adds more than that "
                f"back to **domestic feed**. Where it lands matters for basis: "
                f"export demand loads the Gulf and rail, feedyard demand loads "
                f"the Southern Plains."
            )

            # ── the substitution caveat ──────────────────────────────────────
            st.markdown("<div style='height:10px'></div>",
                        unsafe_allow_html=True)
            st.markdown('<div class="sec-header">What Mexico Actually Fed'
                        '</div>', unsafe_allow_html=True)

            fg = cdm.feed_grain_total(CD["grains"])
            fg = [row for row in fg if row[0] >= 2016]
            fig = go.Figure()
            for g, col in (("Corn", JPSI_BLUE), ("Sorghum", AMBER),
                           ("Wheat", JPSI_DARK)):
                fig.add_trace(go.Scatter(
                    x=[f"MY{y}" for y, _p, _t in fg],
                    y=[p.get(g, 0) for _y, p, _t in fg],
                    name=g, mode="lines+markers",
                    line=dict(color=col, width=2)))
            fig.add_trace(go.Scatter(
                x=[f"MY{y}" for y, _p, _t in fg],
                y=[t for _y, _p, t in fg], name="All feed grain",
                mode="lines", line=dict(color=MUTED, width=2, dash="dot")))
            fig.update_layout(
                height=300, margin=dict(l=10, r=10, t=24, b=10),
                paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                font=dict(color=TEXT, size=11),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                # CATEGORY, not a sniffed axis: "MY2016".."MY2026" would be
                # read as numeric strings on a linear axis -- the trap
                # beef_trade.annual_figure documents.
                xaxis=dict(gridcolor=BORDER, title=None, type="category"),
                yaxis=dict(gridcolor=BORDER, title="1000 MT"))
            st.plotly_chart(fig, use_container_width=True)

            _by = {y: (p, t) for y, p, t in fg}
            _yrs = sorted(_by)
            if len(_yrs) >= 2:
                _a, _b = _yrs[-2], _yrs[-1]
                def _d(y, g):
                    return _by[y][0].get(g, 0) - _by[y - 1][0].get(g, 0)
                st.caption(
                    f"**Read the corn line with the others beside it.** Corn "
                    f"feed use rose **{_d(_a,'Corn'):+,.0f}** thousand MT in "
                    f"MY{_a}, which reads as a cattle story — but **all feed "
                    f"grain together rose "
                    f"{_by[_a][1]-_by[_a-1][1]:+,.0f}**, because sorghum fell "
                    f"{_d(_a,'Sorghum'):+,.0f} and feed wheat "
                    f"{_d(_a,'Wheat'):+,.0f} as Mexico's own crops failed. "
                    f"Most of that corn replaced other grain rather than "
                    f"feeding extra animals. The tiles above are a "
                    f"bottom-up estimate from head and rations; this is what "
                    f"Mexico's balance sheet actually shows, and the two do "
                    f"not have to agree."
                )

            # USDA'S OWN BOOKS DISAGREE WITH THE PREMISE, and the panel
            # says so rather than letting three tiles imply otherwise.
            _ly2 = max(CD["corn"])
            _dimp = (CD["corn"][_ly2].get("Imports", 0)
                     - CD["corn"].get(_ly2 - 1, {}).get("Imports", 0))
            if _dimp:
                st.info(
                    f"**USDA is not forecasting Mexico to buy less corn.** "
                    f"The PSD vintage that postdates the reopening still has "
                    f"MY{_ly2} imports **{_dimp:+,.0f}** thousand MT on the "
                    f"year, on poultry and feed-sector growth — poultry is "
                    f"about 47% of Mexican feed demand. What is sized above "
                    f"is one component moving the other way inside a total "
                    f"that is still rising, not a forecast that Mexico's "
                    f"imports fall."
                )

            _sh, _rep = cdm.us_share(CD["corn"], max(CD["corn"]))
            st.caption(
                f"The US supplies **{_sh:.0%}** of Mexico's corn imports"
                + ("" if _rep else
                   " — a five-year average, because PSD zero-fills its "
                   "US-share field for trade years that have not closed and "
                   "the raw figure reads as nil")
                + ". Mexico's own crop is mostly white corn for food; the "
                  "imports are yellow dent for feed, which is the line these "
                  "cattle sit on."
            )

        st.markdown("<hr style='margin:18px 0 8px;'>", unsafe_allow_html=True)
        st.markdown(
            '<div class="srcline">JSA · John Stewart &amp; Associates '
            '&nbsp;·&nbsp; USDA FAS PSD (keyless bulk) · head cross-checked '
            'against US Census imports &nbsp;·&nbsp; feeding assumptions are '
            'JSA\'s, not USDA\'s</div>',
            unsafe_allow_html=True)
