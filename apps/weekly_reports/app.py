"""
JSA Daily Cattle Reports — build the client letter from live data.

The authoring surface for the daily letter. Everything it does is a thin
shell over the letter/ package, which is also driven from the command line by
`python -m letter.build`; the two share the data cache and the commentary file
in out/, so a letter started here can be finished there and the other way round.

PASSWORD. This page is gated on its own REPORTS_PASSPHRASE and the rest of the
portal is not. That is deliberate: the dashboards show published USDA data, but a
draft here is Ross's unsent market read, hours before clients pay to receive it.
See portal_auth.py -- the gate fails closed, so set the secret before deploying.

WHAT THIS PAGE CANNOT DO WHEN DEPLOYED. Streamlit Community Cloud runs Linux
containers with no browser, so letter.topdf finds nothing to drive and the
one-click PDF is unavailable there -- the page offers the HTML instead and you
print it with Ctrl+P, which uses the same print CSS and gives the same result.

DRAFTS SURVIVE A REBOOT NOW, and that is new as of 2026-09-25. The container
filesystem is still ephemeral, so out/ is still destroyed every reboot; what
changed is that the draft no longer lives only there. Every edit is autosaved
to JSA.LETTER.DRAFTS as well, append-only, and pulled back on the next load.
This docstring used to end "a draft written on the deployed app does not
survive a reboot" -- it said so accurately, and a nearly finished Friday letter
was lost to exactly that anyway, because a warning in a docstring is not a
backup. See letter/draft_store.py.

THE PRIOR-FRIDAY SETTLES GO WITH THEM, as of 2026-09-26. They are the only
other thing on this page typed in by hand, they lived in the same doomed out/,
and they cost the same six numbers off last week's letter to re-enter. Same
table, KIND = "weekbase", keyed by the Friday rather than by the letter.
"""
import io
import os
import re
import sys
from datetime import date
from pathlib import Path

import streamlit as st

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import portal_auth  # noqa: E402

# Same question the portal asks everywhere else. Signing in on the home page
# opens this too; arriving here directly offers the same box.
portal_auth.require_admin("JSA Daily Cattle Reports")

# -- Secrets -> environment ---------------------------------------------------
# The letter package is a plain library and reads os.environ; st.secrets does
# not exist for it. Copy across an EXPLICIT ALLOWLIST.
#
# SNOWFLAKE_SCHEMA IS DELIBERATELY NOT IN THIS LIST AND MUST NEVER BE. CLAUDE.md
# records that five bundled modules each default it to the schema they own, so
# setting it to any one value silently empties the other four -- pages load,
# queries miss, nothing raises.
_ALLOWED_SECRETS = (
    "MARS_API_KEY", "MASSIVE_API_KEY",
    "USE_SNOWFLAKE", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_PRIVATE_KEY_PATH", "SNOWFLAKE_PRIVATE_KEY", "SNOWFLAKE_PRIVATE_KEY_PWD",
    # Graph, for the four subscription digests in the headline panel. NOT
    # credentials -- a public client's client id and a tenant id are both public
    # identifiers, sent in plaintext on every auth request. The credential is the
    # token MSAL caches after device-code sign-in, and that never leaves the
    # machine that signed in.
    #
    # They are here rather than committed as config because this repo is public,
    # and a tenant id in a public repo names the organisation. Cheap to keep out.
    "GRAPH_CLIENT_ID", "GRAPH_TENANT_ID",
)
for _name in _ALLOWED_SECRETS:
    try:
        _value = st.secrets.get(_name, "")
    except Exception:
        _value = ""
    if _value and not os.environ.get(_name):
        os.environ[_name] = str(_value)

from letter import build as letter_build  # noqa: E402
from letter import (archive, commentary, config, draft_store, headlines,  # noqa: E402
                    mailbox, onthisday, render, rundown, settle_log,
                    sterling, topdf)

# ...then .env, for anything the secrets did not supply.
#
# WITHOUT THIS THE PAGE QUIETLY READS THE WRONG DATABASE. st.secrets is the only
# source above, and .streamlit/secrets.toml carries just the passphrase -- so
# USE_SNOWFLAKE was never set, snowflake_db fell back to the committed SQLite
# file, and the feeder index rendered 327.60 from 2026-09-04: a real-looking
# number nearly three weeks old, in a client letter, with no error anywhere.
# load_env() uses setdefault, so anything already set above still wins.
letter_build.load_env()

OUT = REPO / "out"

st.markdown("""
<style>
  .wcr-head { font-family:'EB Garamond',Georgia,serif; color:#32373c;
              font-size:1.8rem; margin:0 0 2px; }
  .wcr-sub  { color:#64748b; font-size:0.9rem; margin-bottom:18px; }
  .wcr-fig  { font-size:0.84rem; color:#32373c; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="wcr-head">JSA Daily Cattle Reports</div>'
            '<div class="wcr-sub">Pull the numbers, write the read, print the letter.</div>',
            unsafe_allow_html=True)

# Say so loudly rather than letting a stale number look current. The SQLite
# fallback is a committed file that stopped moving weeks ago.
if not os.environ.get("USE_SNOWFLAKE", "").strip().lower() in ("1", "true", "yes", "on"):
    st.error(
        "**Not connected to Snowflake.** The feeder cattle index and Douglas imports "
        "will come from the committed SQLite file, which is weeks out of date. "
        "Set `USE_SNOWFLAKE=1` and the Snowflake settings in `.env` before using "
        "anything from this page in a client letter."
    )


# -- Controls -----------------------------------------------------------------

c0, c1, c2 = st.columns([1.4, 1.8, 4])
with c0:
    # Two reports a day, each with its own five weekdays. Independent of the
    # day: AM Monday and PM Monday are different letters.
    # Opens on the report you are most likely writing: AM before noon Central,
    # PM after. Only the DEFAULT moves -- Streamlit keeps a widget's value
    # across reruns, so picking the other one sticks, including across noon.
    session = st.radio("Report", config.SESSIONS,
                       index=config.SESSIONS.index(config.session_for_now()),
                       horizontal=True,
                       help="Defaults to the morning brief before noon Central "
                            "and the evening letter after it.").lower()
with c1:
    issue = st.date_input("Issue date", value=date.today(), format="YYYY-MM-DD")
with c2:
    # `day` is what you pick; `kind` is which of the THREE evening layouts it
    # produces -- Tuesday the full letter, Friday the week-in-review, and
    # Mon/Wed/Thu the recap. The AM ignores the day entirely.
    # See config.FORMAT_FOR_DAY.
    default_day = config.day_for_date(issue)
    day = st.radio(
        "Letter", config.DAYS, horizontal=True,
        index=config.DAYS.index(default_day.title()),
        # GENERATED FROM THE MAPPING, never written out. This sentence was a
        # hardcoded string and went stale the moment Monday and Tuesday swapped
        # formats -- the caption below had already followed, because it reads
        # `kind`, so the page stated two different arrangements at once.
        help="Defaults to the weekday of the issue date. "
             + config.pm_format_summary(),
    ).lower()
kind = config.format_for(day, session)

if kind == "friday":
    st.caption("**Week-in-review format** — adds regional cash, CFTC, and a Cattle on "
               "Feed block on release weeks. CFTC lands 3:30pm ET, boxed beef about "
               "3pm Central; build after both.")
elif kind == "recap":
    # THREE PM FORMATS, THREE CAPTIONS. This branch was missing when the recap
    # landed, so Mon/Wed/Thu fell through to "Standard format" -- the page
    # naming a letter you are not writing, while the boxes below it showed the
    # recap's sections. Wrong labels on an authoring page are worse than none.
    #
    # THE SECTION COUNT IS DERIVED, for the reason spelled out in the AM
    # branch below: this caption read "one technicals read covering both
    # products" and was still saying so on the live page on 2026-10-15, after
    # that section had become two. A typed claim about which sections a format
    # has goes stale the first time one moves, and nothing makes it fail.
    st.caption("**Recap format** — the session in brief: no Fundamental "
               f"Rundown, {commentary.sections_summary('recap')} to write. "
               "Boxed beef publishes about 3pm Central; build after that.")
elif kind == "am":
    # FOUR FORMATS, FOUR CAPTIONS. The AM brief fell through to "Standard
    # format" -- the same miss the recap branch above was added to fix, one
    # radio further up: the page named the Monday evening letter while the box
    # below it offered the morning brief's single section.
    #
    # The two facts a reader could get wrong are DERIVED, not typed: how many
    # sections there are to write, and which change the figures quote. Both
    # have already moved once.
    st.caption("**Morning brief** — one page, under three minutes, "
               f"{commentary.sections_summary('am')} to write. Quotes "
               f"{config.change_basis_label(kind)}, and reads the last "
               "COMPLETED session rather than the newest bar — at 07:30 "
               "today's row is the session opening, not a settle — so "
               "rebuilding after the open is safe.")
else:
    # Monday's full evening letter, and the fallback for a format with no
    # caption of its own. Check this reads true before adding a fifth.
    st.caption("**Standard format** — leads with last week's cash trade. Boxed beef "
               "publishes about 3pm Central; build after that or the cutout is "
               "yesterday's (the letter labels it honestly either way).")

# Analyst pre-report estimates. USDA does not publish these and nothing derives
# them, so the column is blank unless they are typed in.
cof_guesses = {}
if kind == "friday":
    with st.expander("Cattle on Feed guesses (only used on release weeks)"):
        g1, g2, g3 = st.columns(3)
        for col, key, label in ((g1, "on_feed", "On-Feed"), (g2, "placed", "Placed"),
                                (g3, "marketed", "Marketed")):
            with col:
                v = st.number_input(label, min_value=0.0, max_value=200.0,
                                    value=0.0, step=0.1, format="%.1f", key=f"cof_{key}")
                if v:
                    cof_guesses[key] = v

slug = f"{session}_{day}"
data_path = OUT / f"data_{slug}_{issue}.json"
cpath = commentary.path_for(OUT, issue, slug)

b1, b2 = st.columns([1, 3])
with b1:
    fetch = st.button("Fetch latest data", type="primary", use_container_width=True)
with b2:
    if data_path.exists():
        st.caption(f"Using saved data from `{data_path.name}`. Fetch again to refresh.")
    else:
        st.caption("No data pulled for this date yet.")


# -- Data ---------------------------------------------------------------------

def _load_ctx():
    """Fetched context for this issue, from the cache unless asked to refresh."""
    import json
    if data_path.exists():
        ctx = json.loads(data_path.read_text(encoding="utf-8"))
        ctx["issue_date"] = issue
        ctx["kind"] = kind
        ctx["session"] = session
        # RE-DERIVED, NOT REMEMBERED. The fetch run put its errors in
        # st.session_state, which does not survive a page reload or a second
        # browser session -- so the page showed a completely clean bill of
        # health over stale numbers to anyone who refreshed. These warnings are
        # a property of the data, so they can simply be asked of the cached ctx
        # again; every check is a pure read of the saved context plus the
        # environment, with no network.
        #
        # BOTH REPORTERS, and the second one was missed when the source
        # warnings were routed to the page earlier the same day. For a few
        # hours a reload showed the three futures warnings and silently dropped
        # the boxed-beef 3pm trap, the AMS 3208 PRELIMINARY note, the
        # back-dated-build check and Friday's CFTC staleness -- which is the
        # very bug the paragraph above describes, reintroduced one function
        # over while fixing it.
        errs = []
        letter_build.report_futures_health(ctx, issue, errs)
        letter_build.report_source_health(ctx, issue, kind, errs)
        return ctx, errs
    return None, []


# `or` a requested refetch: banking a settle changes what fetch_futures would
# return, and the arithmetic that turns it into a daily change lives there.
# Re-running the fetch is how the page gets the corrected figures without this
# file growing a second, drifting copy of that logic.
if fetch or st.session_state.pop("wcr_force_fetch", False):
    with st.spinner("Fetching USDA, futures and Snowflake…"):
        import json
        errors = []
        ctx = letter_build.gather(issue, errors, kind, cof_guesses)
        ctx["session"] = session
        # Log today's settles and chain the weekly change, same as the CLI.
        settle_log.record(ctx)
        letter_build.backfill_week_base(ctx, OUT, issue)
        OUT.mkdir(parents=True, exist_ok=True)
        data_path.write_text(json.dumps(ctx, indent=2, default=letter_build._jsonable),
                             encoding="utf-8")
        st.session_state["wcr_errors"] = errors
    st.rerun()

ctx, _cached_warnings = _load_ctx()
# The fetch run's errors when there was one this session, otherwise the ones
# re-derived from the saved data. Never nothing.
errors = st.session_state.get("wcr_errors") or _cached_warnings

# ONE DEFINITION, TWO RENDER PATHS. The labels appear here and again at the
# real tab call far below; spelled out twice they would drift, and the whole
# point of the empty pair is that it looks like the loaded one.
TAB_LABELS = ["Letter", "Cattle Market Rundown Slide"]

if ctx is None:
    st.info("Press **Fetch latest data** to pull this issue's numbers.")
    # THE TABS STILL DRAW, EMPTY, AND THEN THE PAGE STOPS.
    #
    # They used to be a thousand lines below this st.stop(), so before a
    # fetch the page simply ended and the slide tab did not exist. Ross went
    # looking for it on 2026-10-13 and asked where it had gone -- nothing had
    # moved, he had just not fetched that date yet, and on the deployed app
    # `out/` is gitignored so EVERY reboot wipes every saved context and puts
    # everyone back in this state. A feature you cannot see until you perform
    # an unrelated step reads as a feature that has been removed.
    _t_letter, _t_slide = st.tabs(TAB_LABELS)
    with _t_letter:
        st.caption("The rendered letter, the print and image buttons and the "
                   "PDF appear here once the numbers are pulled.")
    with _t_slide:
        st.caption("The **Cattle Market Rundown** slide (deck slide 3) and the "
                   "**Sterling** margins slide (deck slide 7) appear here once "
                   "the numbers are pulled, each with a PowerPoint download.")
    st.stop()

if errors:
    with st.expander(f"{len(errors)} source(s) reported a problem", expanded=True):
        for e in errors:
            st.warning(e)

# -- Prior-Friday settles -----------------------------------------------------
# Only appears when the futures history has no bar for the prior Friday, which
# is when the week-over-week change cannot be computed. The numbers are on your
# own last letter. Saved to out/weekbase_<friday>.json so the CLI and a later
# re-render use the same ones -- and mirrored to JSA.LETTER.DRAFTS, because
# out/ is gitignored and a reboot rebuilds the container from a fresh clone.
# Six settles typed off last week's letter are exactly as expensive to lose as
# an hour's writing, and were lost the same way.

wb_path = letter_build.week_base_path(OUT, issue, day)
_wb_friday = letter_build.prior_friday_of(issue)

# BEFORE load_week_base, for the reason the commentary restore sits before
# write_template: read the reconciled file, not the one this container happens
# to have. Restoring can never overwrite a real number -- apply_week_base only
# fills a contract with no base at all -- so it runs unconditionally.
_wb_restored = draft_store.restore(wb_path, _wb_friday,
                                   draft_store.WEEK_BASE_KIND,
                                   label="Prior-Friday settles")

saved_bases = letter_build.load_week_base(wb_path)
letter_build.apply_week_base(ctx, saved_bases)

if _wb_restored:
    st.info(_wb_restored)

still_missing = letter_build.missing_week_bases(ctx)
already_typed = letter_build.hand_entered_bases(ctx)

# THE FORM STAYS AFTER THE LAST BOX IS FILLED. It used to hang entirely off
# `still_missing`, which empties the moment the six settles are entered -- so
# finishing the entry made the form disappear and a typo could not be corrected
# from the page at all. Reported 2026-09-25 with a wrong October already saved.
#
# Contracts whose base came from the futures history or a previous letter are
# deliberately NOT offered: those are real data, and inviting an overwrite is
# the mistake the [[?]] marking exists to prevent.
editable = still_missing + [e for e in already_typed if e not in still_missing]

if editable:
    if still_missing:
        st.warning(
            f"**No prior-Friday settle for {len(still_missing)} contract(s).** The futures "
            "history has a hole, so the week-over-week change cannot be computed. Enter "
            "the settles from your previous letter below and they will be used."
        )
    with st.expander(
        f"Prior-Friday settles — {len(already_typed)} entered by hand"
        if already_typed and not still_missing else "Enter the prior-Friday settles",
        expanded=bool(still_missing),
    ):
        st.caption("Labelled by product as well as month: **Oct** is both a Live Cattle "
                   "and a Feeder contract, and they are stored separately. Type over a "
                   "value to correct it.")
        with st.form("week_base"):
            entered = {}
            cols = st.columns(min(3, len(editable)))
            for i, (ticker, label) in enumerate(editable):
                with cols[i % len(cols)]:
                    v = st.number_input(f"{label}  ({ticker})", min_value=0.0, max_value=1000.0,
                                        value=float(saved_bases.get(ticker, 0.0)),
                                        step=0.025, format="%.3f", key=f"wb_{ticker}")
                    if v:
                        entered[ticker] = v
            if st.form_submit_button("Use these settles", use_container_width=True):
                merged = dict(saved_bases)
                merged.update(entered)
                letter_build.save_week_base(wb_path, merged)
                # Only when there is something to save. An empty form writes
                # "{}", which store() would happily keep as a version.
                if merged:
                    _wb_err = draft_store.backup(wb_path, _wb_friday,
                                                 draft_store.WEEK_BASE_KIND)
                    if _wb_err:
                        st.warning(f"Saved locally. {_wb_err}")
                st.rerun()


# -- Settles the feed could not supply ----------------------------------------
# Offered ONLY for contracts whose settle did not come from the real settlement
# history. The same rule the week-base form follows, and for the same reason:
# a typed number must never be invited to beat a fetched one.
#
# Why it exists at all: on 2026-09-28 Massive had no settlement for Friday
# 09-25 at any resolution and no prospect of one -- /trades carries zero ticks
# for the whole of 09-14..09-24, so nothing can be aggregated out of it. The
# brief could recover the session from the hourly bars, but only as a LAST
# TRADE: 335.00 on the Oct feeder, which settled 334.925. CME settles on a
# weighted average of the closing range, so the two differ routinely, and the
# letter quotes settlements.
#
# It writes to the settle log rather than a file of its own, because
# fetch_futures already reads that as a recovery tier ranked above an hourly
# close. Nothing new has to be applied -- and because both ends of the move
# become settlements, the daily change comes back too instead of staying [[?]].

_PRODUCTS = {"LE": "Live Cattle", "GF": "Feeder"}

_recovered = [c for c in (ctx.get("live_cattle") or []) + (ctx.get("feeder_cattle") or [])
              if c.get("settle_recovered")]

if _recovered:
    # COUNT THE CLOSES, NOT EVERYTHING RECOVERED. A banked settle IS an official
    # settlement -- it just did not come from the feed -- and calling all six
    # "not official" told Ross four correct numbers were suspect.
    _closes = [c for c in _recovered if c.get("settle_source") == "hourly close"]
    _typed_already = [c for c in _recovered if c not in _closes]

    if _closes:
        st.warning(
            f"**{len(_closes)} contract(s) are priced off a last trade, not a "
            "settlement.** The hourly bars carry the closing trade, and CME settles on "
            "a weighted average of the closing range — usually identical, occasionally "
            "a few ticks out. Their daily move is left marked rather than measured from "
            "one kind of number to the other. Type the settles in below and both come "
            "right."
        )
    if _typed_already:
        st.caption(f"{len(_typed_already)} contract(s) are on settles entered by hand. "
                   "They are real settlements and the letter treats them as such — "
                   "correct one here if it was mistyped.")

    with st.expander("Enter the official settles", expanded=bool(_closes)):
        st.caption("From your broker, the CME settlements page or the evening market "
                   "report. Leave a box at zero to keep what was fetched. These are "
                   "saved per SESSION DATE, so they carry to every letter that quotes "
                   "that session and are not re-typed tomorrow.")
        with st.form("manual_settles"):
            _typed = {}
            _cols = st.columns(min(3, len(_recovered)))
            for _i, _c in enumerate(_recovered):
                _tk = _c.get("ticker") or ""
                _prod = _PRODUCTS.get(_tk[:2], _tk[:2])
                with _cols[_i % len(_cols)]:
                    _v = st.number_input(
                        f"{_c.get('month')} {_prod}  ({_tk})",
                        min_value=0.0, max_value=1000.0,
                        value=float(_c.get("settle") or 0.0),
                        step=0.025, format="%.3f", key=f"ms_{_tk}",
                        help=f"session of {_c.get('settle_date')} — currently "
                             f"{_c.get('settle_source')}")
                    if _v:
                        _typed[(str(_c.get("settle_date"))[:10], _tk)] = _v
            if st.form_submit_button("Use these settles", use_container_width=True):
                _by_date = {}
                for (_when, _tk), _v in _typed.items():
                    # Unchanged boxes are not re-banked: every bank is a
                    # Snowflake row, and a history of identical rows is a
                    # history of nothing. Same lesson as the draft autosave.
                    _cur = next((c for c in _recovered if c.get("ticker") == _tk), {})
                    if abs(float(_cur.get("settle") or 0) - _v) < 1e-9:
                        continue
                    _by_date.setdefault(_when, {})[_tk] = _v
                _n = sum(settle_log.bank(_vals, _when, source="page")
                         for _when, _vals in _by_date.items())
                if _n:
                    st.session_state["wcr_force_fetch"] = True
                    st.rerun()
                else:
                    st.info("Nothing changed, so nothing was saved.")


# -- What came back -----------------------------------------------------------

with st.expander("Figures pulled", expanded=False):
    fig_cols = st.columns(3)
    cash = ctx.get("cash") or {}
    cut = ctx.get("cutout") or {}
    dsl = ctx.get("daily_slaughter") or {}
    cw = ctx.get("carcass_weights") or {}
    fci = ctx.get("fci") or {}

    with fig_cols[0]:
        st.markdown("**Cash trade**")
        st.markdown(
            f"<div class='wcr-fig'>Live {cash.get('live', {}).get('this_week')} "
            f"(was {cash.get('live', {}).get('last_week')})<br>"
            f"Dressed {cash.get('dressed', {}).get('this_week')} "
            f"(was {cash.get('dressed', {}).get('last_week')})</div>",
            unsafe_allow_html=True)
    with fig_cols[1]:
        st.markdown("**Slaughter & weights**")
        st.markdown(
            f"<div class='wcr-fig'>Daily {dsl.get('current_day')}<br>"
            f"WTD {dsl.get('wtd')}<br>"
            f"Carcass {cw.get('value')}# (w/e {cw.get('week_ending')})</div>",
            unsafe_allow_html=True)
    with fig_cols[2]:
        st.markdown("**Cutout & index**")
        st.markdown(
            f"<div class='wcr-fig'>Choice {cut.get('choice', {}).get('value')}<br>"
            f"Select {cut.get('select', {}).get('value')}<br>"
            f"Feeder index {fci.get('value')}</div>",
            unsafe_allow_html=True)

# -- Commentary ---------------------------------------------------------------

# -- Headline candidates (AM only) --------------------------------------------
# Rendered BEFORE the text areas below, because adding a headline writes into
# the Headlines box's session_state -- and Streamlit refuses that once the
# widget has been instantiated.
#
# NOTHING HERE IS AUTO-INSERTED. It is a pick list. Every other figure in the
# brief is a USDA or CME number that is either right or marked [[?]]; a headline
# is editorial, and there is no [[?]] for a feed surfacing something misleading
# under JSA's name.
#
# WHICH FORMATS GET IT IS DERIVED, NOT HARDCODED. This was `kind == "am"` until
# 2026-09-23, when the evening letter gained a Headlines section and the pick
# list silently did not follow -- a box to type headlines into and no list to
# pick them from. Asking the format which section it has means adding one to a
# third format is a one-line change in commentary.py and nothing here.
#
# Friday picks up the panel for its Key Headlines as a side effect, which it
# should have had all along: same editorial job, same pick-then-rewrite rule.
# HOW OLD THE LIST IS, BECAUSE IT NEVER REFRESHES ITSELF. The candidates live
# in session_state from the moment the button is pressed until it is pressed
# again -- a rerun does not re-fetch, which is right (it is a dozen HTTP calls)
# and invisible, which is not. A list pulled at breakfast looks exactly like
# one pulled a minute ago.
#
# Sterling's Profit Tracker landed at 2:15pm on 2026-10-13 and was missing from
# Ross's panel all afternoon for precisely that reason: the fetch had happened
# earlier, everything downstream was working, and the mail was sitting at
# position 4 of 39 the moment anyone pressed the button again. Nothing was
# broken and nothing said so.
_HEADS_STALE_MIN = 30


def _fetch_heads(when_for):
    """Pull the candidates and stamp when, so the panel can date itself."""
    st.session_state["wcr_heads"] = headlines.candidates(when_for)
    st.session_state["wcr_heads_at"] = config.now_central()


def _age_minutes(then, now=None):
    """Whole minutes since `then`, or None if we never stamped it."""
    if then is None:
        return None
    try:
        return max(0, int(((now or config.now_central()) - then).total_seconds() // 60))
    except TypeError:                     # aware vs naive, if the host has no tz
        return None


def _age_phrase(mins):
    """'just now', '4m ago', '1h 23m ago'.

    Takes the MINUTES, not the timestamp, so the sentence and the decision to
    warn cannot disagree -- the first draft of this read the number back out
    of its own formatted string.
    """
    if mins is None:
        return None
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    return f"{mins // 60}h {mins % 60:02d}m ago"


_head_key, _head_title = next(
    ((k, t) for k, t in commentary.sections_for(kind)
     if k in ("headlines", "key_headlines")), (None, None))

if _head_key:
    with st.expander("Headline candidates", expanded=False):
        if st.button("Fetch headlines", use_container_width=False):
            with st.spinner("Reading Beef Magazine, the USDA narratives and packer news…"):
                _fetch_heads(issue)

        # Mailbox sign-in, only when it is actually needed. Device-code flow:
        # no password is typed here or stored anywhere by this app.
        if not mailbox.configured():
            # NAMED FROM mailbox.DIGESTS, not typed out here. The hardcoded
            # version said "the Meatingplace and eMeat digests" and had done
            # since before Global AgriTrends and Sterling were added, so the
            # page understated what connecting the mailbox actually brings in
            # -- Sterling being the one that carries the packer margin the
            # evening letter quotes by hand.
            _digests = [d["label"] for d in mailbox.DIGESTS]
            _named = ", ".join(_digests[:-1]) + f" and {_digests[-1]}" \
                if len(_digests) > 1 else _digests[0]
            st.caption(f"To include the {_named} digests from your inbox, set "
                       "`GRAPH_CLIENT_ID` and `GRAPH_TENANT_ID` in `.env`.")
        elif (st.session_state.get("wcr_heads") or {}).get("needs_sign_in"):
            flow = st.session_state.get("wcr_graph_flow")
            if not flow:
                if st.button("Connect mailbox"):
                    _, f = mailbox.token(interactive=True)
                    st.session_state["wcr_graph_flow"] = f
                    st.rerun()
            elif flow.get("error"):
                st.warning(flow["error"])
            else:
                st.info(flow.get("message", "Sign in with the code shown."))
                if st.button("I've signed in"):
                    with st.spinner("Completing sign-in…"):
                        ok = mailbox.complete_sign_in(flow)
                    st.session_state.pop("wcr_graph_flow", None)
                    if ok:
                        _fetch_heads(issue)
                    st.rerun()

        found = st.session_state.get("wcr_heads")
        if not found:
            st.caption("Beef Magazine, USDA's own cash-trade and border narratives, and a "
                       "news search for Tyson/JBS/Cargill/National Beef and plant "
                       "disruption — last 48 hours. Pick what matters and rewrite it in "
                       "your words — nothing here goes into the letter on its own.")
        else:
            # The age goes ABOVE the errors and above the list, because it is
            # the thing that decides whether anything below it is worth
            # reading. A stale list is not a wrong list -- every row in it was
            # true when it was pulled -- so this is a prompt, not an alarm.
            _mins = _age_minutes(st.session_state.get("wcr_heads_at"))
            _age = _age_phrase(_mins)
            if _age and _mins >= _HEADS_STALE_MIN:
                st.warning(
                    f"These {len(found.get('items', []))} candidates were pulled "
                    f"**{_age}** and have not moved since. Press **Fetch headlines** "
                    "again for anything that has landed — Sterling's Profit Tracker "
                    "and Meatingplace's afternoon update both arrive mid-afternoon.")
            elif _age:
                st.caption(f"{len(found.get('items', []))} candidates, pulled {_age}.")
            for err in found.get("errors", []):
                st.caption(f"⚠ {err}")
            # A GENERATION NUMBER IN THE CHECKBOX KEY, so clearing the ticks
            # never writes to a widget that already exists. Assigning
            # st.session_state["head_<n>"] = False after the loop is the obvious
            # way to reset them and it raises StreamlitWidgetAlreadyInstantiated-
            # Error every time -- the checkboxes were built moments earlier in
            # this same run, and Streamlit refuses to have their state written
            # behind their back. It crashed the page on the first real use of
            # the Add button, 2026-09-24, mid-letter.
            #
            # Bumping the generation asks for a DIFFERENT set of widgets on the
            # next run instead. They have never been instantiated, so they start
            # unchecked with nothing assigned to them.
            gen = st.session_state.get("wcr_head_gen", 0)
            picked = []
            for n, item in enumerate(found.get("items", [])):
                age = (f"{item['age_h']}h ago" if item.get("age_h") is not None
                       else str(item.get("when") or "")[:16])
                label = item["title"]
                if len(label) > 150:
                    label = label[:150] + "…"
                if st.checkbox(label, key=f"head_{gen}_{n}"):
                    picked.append(item["title"])
                st.caption(f"{item['source']} · {age}"
                           + (f" · [open]({item['link']})" if item.get("link") else ""))
            if picked and st.button(f"Add {len(picked)} to {_head_title}", type="primary"):
                # The target box is the one THIS format calls its headline
                # section -- wcr_headlines on AM and PM, wcr_key_headlines on
                # Friday. Hardcoding it wrote Friday's picks into a widget that
                # does not exist on Friday.
                _box = f"wcr_{_head_key}"
                existing = st.session_state.get(_box, "")
                lines = [ln for ln in existing.splitlines() if ln.strip()]
                lines.extend(picked)
                # Writing to the TEXT AREA's key is fine and is why this whole
                # panel is rendered above them: wcr_<section> has not been
                # instantiated yet at this point in the script. The checkboxes
                # have been, which is why they get a new generation instead.
                st.session_state[_box] = "\n".join(lines)
                st.session_state["wcr_head_gen"] = gen + 1
                st.rerun()


# -- On this day --------------------------------------------------------------
# A PROMPT, NOT A PASTE, and deliberately not wired to any box. The headline
# panel writes its picks into a text area because a headline IS the letter's
# content; a fun fact is someone else's editorial writing. The events are
# facts and free to use, the wording is history.com's and is not, so this
# shows the year and the headline as a reminder and links out. Ross writes the
# line himself, which is also the only reason the filter below is safe enough
# to ship -- see letter/onthisday.py on the morning it offered a mass shooting
# as an agriculture fact.
with st.expander("On this day — for a closing line", expanded=False):
    if st.button("Find today's facts", use_container_width=False):
        with st.spinner("Reading This Day in History…"):
            st.session_state["wcr_otd"] = onthisday.candidates(issue)

    _otd = st.session_state.get("wcr_otd")
    if _otd:
        for _e in _otd.get("errors", []):
            st.warning(_e)
        # CHECKBOXES AND ONE BUTTON, like the headline panel, so several can go
        # over at once. The per-item "Use this" button replaced the box with a
        # single line and there was no way to take two.
        #
        # THE GENERATION COUNTER IS NOT DECORATION. Ticking a box instantiates
        # that widget, and Streamlit refuses a write to an instantiated
        # widget's key -- so the boxes cannot be cleared after a rerun, they
        # have to be replaced by NEW widgets with new keys. Exactly what
        # wcr_head_gen does above, and for the same crash.
        _gen = st.session_state.get("wcr_otd_gen", 0)
        _picked = []
        for _n, _i in enumerate(_otd.get("items", [])):
            _line = f"{_i['year']} — {_i['text']}"
            if st.checkbox(_line, key=f"otd_{_gen}_{_n}"):
                _picked.append(_line)
            st.caption(" · ".join(_i["tags"]) + f" · {_i['source']}")

        if _picked and st.button(f"Add {len(_picked)} to the line box",
                                 type="primary", key="otd_add"):
            # APPENDS, never replaces -- anything already typed survives.
            # Writing wcr_dayfact is safe from HERE and only here: this panel
            # renders above the chart section, so that text area has not been
            # instantiated yet on this run.
            _have = [ln for ln in st.session_state.get("wcr_dayfact", "").splitlines()
                     if ln.strip()]
            _have.extend(ln for ln in _picked if ln not in _have)
            st.session_state["wcr_dayfact"] = "\n".join(_have)
            st.session_state["wcr_otd_gen"] = _gen + 1
            st.rerun()
        if not _otd.get("items"):
            st.caption("Nothing worth offering for today — some days are quiet, "
                       "and the filter drops anything grim rather than padding "
                       "the list.")
        st.caption(f"Source: [{_otd.get('source_url','')}]({_otd.get('source_url','')}) "
                   "— write it in your own words; nothing here goes into the "
                   "letter on its own.")
    else:
        st.caption("Sporting firsts, US milestones and the odd agricultural one, "
                   "for the bottom of the letter. Nothing is inserted for you.")


st.subheader("Your read")
st.caption("One bullet per line. Blank sections are left out of the letter entirely.")

# Pull the draft back from Snowflake BEFORE the template is written, because
# write_template() creates the file when it is missing and a created file would
# then look like a legitimately empty local draft. On a fresh container -- every
# reboot is one -- this is the step that makes yesterday's writing reappear.
_restored = draft_store.restore(cpath, issue, slug,
                                has_content=lambda b: commentary.has_content(b, kind))

# Seed the boxes with whatever is on disk so the CLI and this page stay in sync.
commentary.write_template(cpath, letter_build.hints(ctx, kind), kind)
saved = commentary.read(cpath, kind)

if _restored:
    st.info(_restored)

# -- Version history ----------------------------------------------------------
# The reason JSA.LETTER.DRAFTS is append-only: any earlier version can be put
# back. Nobody could do that on 2026-09-25, which is what this is for.
#
# ABOVE THE TEXT AREAS, for the same reason the headline panel is: restoring
# writes wcr_<section> in session_state, and Streamlit refuses that once the
# widget with that key has been instantiated. Below the boxes this raised
# rather than restoring -- which would have been a poor thing to discover
# while trying to recover a letter.

_versions = draft_store.history(issue, slug) if draft_store.enabled() else []
if len(_versions) > 1:
    with st.expander(f"Version history — {len(_versions)} saved"):
        st.caption("Newest first. Restoring loads that version into the boxes below; "
                   "nothing is deleted, so restoring is itself undoable.")
        for _n, (_at, _by, _body) in enumerate(_versions):
            v1, v2, v3 = st.columns([2, 3, 1])
            v1.markdown(f"**{_at:%b %d, %H:%M} UTC**" if _at else "—")
            _lines = len([ln for ln in _body.splitlines() if ln.strip().startswith("- ")])
            v2.caption(f"{_lines} bullet{'' if _lines == 1 else 's'} · {_by or ''}")
            if _n == 0:
                v3.caption("current")
            elif v3.button("Restore", key=f"wcr_restore_{_n}", use_container_width=True):
                cpath.write_text(_body, encoding="utf-8")
                _back = commentary.read(cpath, kind)
                for _key, _ in commentary.sections_for(kind):
                    st.session_state[f"wcr_{_key}"] = "\n".join(_back.get(_key, []))
                st.rerun()

# -- which contract month the technical read is about --------------------------
#
# BEFORE hints(), and that ordering is the whole of it. `hints()` quotes the
# 9-day, 20-day, swing high/low and prior range off ctx["tech_lc"], and
# `render.technicals_block` prints the heading off the same dict. Applying the
# dropdown after hints() had been computed would show Dec in the heading over
# October's figures for one rerun -- a letter and its own reference numbers
# disagreeing, which is the failure this repo keeps recording.
#
# Seeded from the saved ctx rather than left to default, so a month chosen
# before a reboot survives. Written back to the ctx file so `build.main
# --no-fetch`, the run that makes the emailed PDF, renders the month that was
# previewed rather than the nearby one.
# Every evening format now has one technicals section per product, so each
# picker governs exactly one. The recap carried a combined "technicals" key
# with BOTH pickers on it until 2026-10-15; that entry is gone rather than
# left harmless, because a key no format has is config that reads as live.
#
# The comment it carried was also wrong on its own terms -- it said hints()
# quoted both products there, and hints() reached that section with nothing
# at all. See commentary.SECTIONS_BY_KIND.
_TECH_PICKERS = {
    "technicals_lc": (("tech_lc", "Live cattle"),),
    "technicals_fc": (("tech_fc", "Feeders"),),
}

for _tk in letter_build.TECH_KEYS:
    _state = f"wcr_{_tk}_month"
    if _state not in st.session_state and ctx.get(f"{_tk}_month"):
        st.session_state[_state] = ctx[f"{_tk}_month"]
    if st.session_state.get(_state):
        ctx[f"{_tk}_month"] = st.session_state[_state]
letter_build.select_technicals(ctx)

# Persist only on an actual change -- this script reruns on every keystroke in
# the commentary boxes, and rewriting the ctx each time would be a disk write
# per character.
if data_path.exists():
    import json as _json
    _saved = _json.loads(data_path.read_text(encoding="utf-8"))
    if any(_saved.get(f"{k}_month") != ctx.get(f"{k}_month")
           for k in letter_build.TECH_KEYS):
        for _k in letter_build.TECH_KEYS:
            _saved[f"{_k}_month"] = ctx.get(f"{_k}_month")
        data_path.write_text(
            _json.dumps(_saved, indent=2, default=letter_build._jsonable),
            encoding="utf-8")

hints = letter_build.hints(ctx, kind)
edited = {}
for key, title in commentary.sections_for(kind):
    with st.container(border=True):
        st.markdown(f"**{title}**")
        for _tk, _plabel in _TECH_PICKERS.get(key, ()):
            _opts = [m for m in letter_build.technical_months(ctx, _tk)
                     if m in (ctx.get(f"{_tk}_all") or {})]
            if len(_opts) > 1:
                st.selectbox(
                    f"{_plabel} month", _opts, key=f"wcr_{_tk}_month",
                    help="Which contract this read is about. The heading and "
                         "the figures below follow it.")
        if hints.get(key):
            with st.expander("Figures for reference", expanded=False):
                for line in hints[key]:
                    st.caption(line)
        edited[key] = st.text_area(
            title, value="\n".join(saved.get(key, [])), height=140,
            label_visibility="collapsed", key=f"wcr_{key}",
            placeholder="One bullet per line…",
        )

sections = {k: [ln.strip() for ln in v.splitlines() if ln.strip()]
            for k, v in edited.items()}

# AUTOSAVE. Streamlit reruns this script whenever a text area loses focus, so
# every box you tab out of lands on disk and in Snowflake without anyone
# pressing anything. "Save draft" used to be the ONLY thing that wrote, which
# meant an unsaved hour was one reboot, one idle timeout or one closed laptop
# away from nothing -- and on 2026-09-25 it was.
#
# write_sections() is cheap and idempotent, so it runs unconditionally; the
# Snowflake write is the one worth guarding, and draft_store.store() already
# skips a body identical to the newest row, so a rerun that changed nothing
# costs one SELECT and no history noise.
if not commentary.is_empty(sections):
    commentary.write_sections(cpath, sections, kind)
    _autosave_err = draft_store.backup(cpath, issue, slug)
else:
    _autosave_err = ""

s1, s2 = st.columns([1, 3])
with s1:
    if st.button("Save draft", use_container_width=True):
        commentary.write_sections(cpath, sections, kind)
        err = draft_store.backup(cpath, issue, slug)
        if err:
            st.warning(f"Saved locally. {err}")
        else:
            st.success("Saved — on disk and in Snowflake.")
with s2:
    if _autosave_err:
        # Loud, because the whole point of this block is that the person stops
        # having to think about whether their writing is safe.
        st.warning(f"**Autosave to Snowflake is failing.** {_autosave_err}")
    elif draft_store.enabled():
        st.caption(f"Autosaves to `JSA.LETTER.DRAFTS` and `{cpath.name}` — "
                   "every version is kept, nothing overwrites.")
    else:
        st.caption(f"Draft file: `{cpath.name}` — shared with `python -m letter.build`. "
                   "**Snowflake is not configured, so this draft is local only.**")

# -- Build --------------------------------------------------------------------

_PRINT_STYLE = """<style>
  #jsa-bar { position: sticky; top: 0; z-index: 99; display: flex; gap: 8px;
    margin: 0 0 10px; }
  #jsa-bar button { flex: 1; padding: 7px 0;
    font: 600 14px/1.2 "Segoe UI", system-ui, sans-serif;
    color: #fff; background: #5e7164; border: 0; border-radius: 4px;
    cursor: pointer; }
  #jsa-bar button:hover { background: #4d5d52; }
  #jsa-bar button[disabled] { opacity: 0.65; cursor: progress; }
  @media print { #jsa-bar, #jsa-print, #jsa-png { display: none !important; } }
</style>"""

# Both buttons act on THIS document from the reader's own browser, which is why
# they sit together and why both work on the deployed app where Build PDF
# cannot. Build PDF stays where it is: it writes the file on the host that
# `--archive` publishes, and no browser-side button can do that.
_PRINT_BUTTON = """<div id="jsa-bar">
<button id="jsa-print" onclick="window.focus();window.print();">
  Print / Save as PDF
</button>
<button id="jsa-png">Save pages (texting)</button>
<button id="jsa-png-one">Save one image (HubSpot)</button>
</div>"""

# html2canvas, and the failure mode is handled rather than hoped away: a CDN
# that does not load leaves a button that silently does nothing, which is the
# class of quiet failure this whole file is written against. The handler says
# so on the button itself.
_IMAGE_SCRIPT = """<script
  src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"
  crossorigin="anonymous"></script>
<script>
(function () {
  // TWO DESTINATIONS, ONE CAPTURE, AND THEY WANT OPPOSITE THINGS.
  //
  //   texting   one image per page. A phone fits an image to the bubble
  //             width, so a 1632x6336 letter is squeezed until 8.5pt body
  //             text is about one pixel tall. Splitting is what made it
  //             readable -- see the per-page comment below.
  //   HubSpot   ONE image. Dragging a set of page images into the email
  //             editor does not work; it takes a single asset.
  //
  // Everything up to the finished canvas is identical, so `split` branches
  // only at the point of saving. Keeping one capture path means the two
  // exports cannot drift into producing different-looking letters.
  function wire(btn, split) {
  if (!btn) return;
  btn.addEventListener('click', function () {
    if (typeof html2canvas !== 'function') {
      btn.textContent = 'Image library did not load — use Print instead';
      return;
    }
    var bar = document.getElementById('jsa-bar');
    var label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Rendering…';
    // DISPLAY:NONE, NOT VISIBILITY:HIDDEN. The toolbar is in the flow, so
    // merely hiding it would leave its 31px band at the top of the image.
    bar.style.display = 'none';
    // PAGE MODE: lay the letter out as a PRINTED SHEET before capturing it.
    // The screen layout is NOT the print layout, and the first version of
    // this button shipped the screen one.
    //
    // render.py has no @media print rules at all, so the ONLY difference
    // between the two is page geometry -- and it is not merely cosmetic:
    //
    //   print   8.5in sheet, @page margin 0.52in, so a 7.46in page area and
    //           a 6.80in text block; the frame sits AT the page margin with
    //           white outside it.
    //   screen  the iframe's own width, about 7.42in, and no page margin --
    //           a 6.76in text block and the frame flush to the very edge.
    //
    // A text block 0.04in narrower RE-WRAPS LINES, so the image was not even
    // breaking its text where the PDF does. Forcing the sheet's geometry
    // fixes the wrapping, the margin and the frame together.
    //
    // CSS inches are always 96px, so this arithmetic is exact rather than
    // display-dependent.
    var PX = 96, PAGE_W = 8.5 * PX, PAGE_H = 11 * PX;
    var mode = document.createElement('style');
    mode.textContent =
      'html, body { width: 8.5in !important; }' +
      // 0.52 page margin plus the body's own 0.20/0.33/0.38 -- exactly the
      // figures render.py's comment works the printed block out to.
      'body { padding: 0.72in 0.85in 0.90in !important; margin: 0 !important; }' +
      // The frame is fixed at inset 0, which in PRINT means the page area,
      // i.e. 0.52in in from the sheet. On screen inset 0 is the viewport.
      '.frame { top: 0.52in !important; right: 0.52in !important;' +
      ' bottom: 0.52in !important; left: 0.52in !important; }' +
      '#jsa-bar { display: none !important; }';
    document.head.appendChild(mode);

    var el = document.documentElement;
    // WHOLE SHEETS FOR THE PAGED EXPORT, CONTENT HEIGHT FOR THE SINGLE ONE,
    // and the difference fixes two things at once.
    //
    // Paged: rounding up is what makes each page read as a letter rather
    // than a screenshot, and the splitter needs whole sheets to cut on.
    //
    // Single: rounding up is a bug. Measured on the 2026-10-07 afternoon
    // report, scrollHeight was 1161px against a 1056px sheet -- 105px over
    // -- so it rounded to 2112 and HALF THE IMAGE WAS EMPTY WHITE. It goes
    // into a HubSpot email at that size, trailing band and all.
    //
    // The watermark is the same bug wearing a different hat. `.wm` is
    // position:fixed at top:46%, and html2canvas lays fixed elements out
    // against the windowHeight it is given -- so 46% of 2112 put the
    // 50-years mark down by the signature instead of centred on the page.
    // Capturing at the real height centres it by construction, with no
    // special case for it anywhere. Reported together by Ross, and they
    // were one cause.
    //
    // scrollHeight already includes the body's 0.90in bottom padding, so
    // the letter does not come out cropped to its last line.
    var h = split ? Math.max(1, Math.ceil(el.scrollHeight / PAGE_H)) * PAGE_H
                  : el.scrollHeight;

    // THE SHEET AS THE VIEWPORT. The frame and watermark are position:fixed,
    // so they lay out against whatever window html2canvas is told about; at
    // the iframe's real size they would hug a ~712px box and the page margin
    // would collapse again.
    html2canvas(el, {
      scale: 2, backgroundColor: '#ffffff', useCORS: true,
      width: PAGE_W, height: h, windowWidth: PAGE_W, windowHeight: h,
      scrollX: 0, scrollY: 0
    }).then(function (canvas) {
      var base = (document.title || 'letter').replace(/[\\\\/:*?"<>|]/g, '-');

      if (!split) {
        // THE WHOLE LETTER AS ONE IMAGE. No page splitting, no "Page N of M"
        // stamp, no cut-finding: HubSpot takes a single asset and the height
        // does not matter there the way it does in a message bubble.
        var one = document.createElement('a');
        one.download = base + '.png';
        one.href = canvas.toDataURL('image/png');
        one.click();
        btn.textContent = 'Saved';
        setTimeout(function () { btn.textContent = label; }, 3000);
        return;
      }

      // ONE IMAGE PER PAGE, because a tall one is unreadable in a text.
      //
      // Ross texts these to clients through RingCentral. A one-page brief is
      // about 1:1.3 and survives; the 2026-10-02 afternoon letter was
      // 1632x6336, roughly 1:3.9. A phone fits an image to the bubble width,
      // so 6336px of height is squeezed to around 1400 and 8.5pt body text
      // lands at about ONE PIXEL tall. MMS re-compresses on top of that, so
      // zooming magnifies pixels that no longer contain the letter.
      //
      // Splitting into N portrait sheets gives every page the same shape as
      // the morning brief that already reads fine. Nothing else fixes it:
      // more resolution does not survive the downscale, and a wide
      // side-by-side layout is worse.
      var pageH = PAGE_H * 2;                       // scale: 2
      var pages = Math.max(1, Math.round(canvas.height / pageH));

      // CUT THROUGH WHITESPACE, NOT THROUGH A LINE OF TEXT.
      //
      // The canvas is ONE continuous render, so it has no idea where the
      // PDF's @page breaks fell -- slicing at an exact multiple of 11in can
      // land mid-sentence, and on the 2026-10-02 letter it did: the first
      // nominal cut had 75 ink pixels across it.
      //
      // Two details, both found by measuring rather than reasoning:
      //
      // MEASURE THE TEXT COLUMN ONLY. The sage frame runs down both edges of
      // every page, so a full-width scan never reads zero and "emptiest row"
      // becomes meaningless -- a blank row scored 2 and a line of text
      // scored 40, which is not the signal it looks like. Scanning inside
      // the 0.95in margin makes a clean row read exactly 0.
      //
      // SEARCH OUTWARD FROM THE NOMINAL. A top-down scan returns the FIRST
      // blank row in the window, which dragged a cut 200px up even when the
      // nominal position was already perfectly clean. Walking outwards takes
      // the NEAREST clean row, so a page that needs no adjustment gets none.
      var src = canvas.getContext('2d');
      var X0 = Math.round(0.95 * PX * 2), X1 = canvas.width - X0;
      function ink(y) {
        var d = src.getImageData(X0, y, X1 - X0, 1).data, n = 0;
        for (var x = 0; x < X1 - X0; x += 2) {
          var i = x * 4;
          if (d[i] < 245 || d[i + 1] < 245 || d[i + 2] < 245) n++;
        }
        return n;
      }
      // CENTRE THE CUT IN THE GAP, not at its first clean row. Taking the
      // first one put the slice immediately under a line of text: nothing
      // was sliced, but page 1 came out with its last line flush against
      // the bottom edge and no margin at all, which looks broken on a
      // client letter. Splitting the blank run down the middle gives the
      // page above a bottom margin and the page below a top one.
      function midOfRun(y) {
        var up = y, down = y;
        while (up > 1 && ink(up - 1) === 0) up--;
        while (down < canvas.height - 1 && ink(down + 1) === 0) down++;
        return Math.round((up + down) / 2);
      }
      function cutNear(nominal) {
        if (ink(nominal) === 0) return midOfRun(nominal);
        var bestY = nominal, bestInk = ink(nominal);
        for (var d = 1; d <= 200; d++) {
          var cand = [nominal - d, nominal + d];
          for (var j = 0; j < 2; j++) {
            var y = cand[j];
            if (y < 1 || y >= canvas.height) continue;
            var k = ink(y);
            if (k === 0) return midOfRun(y);
            if (k < bestInk) { bestInk = k; bestY = y; }
          }
        }
        return bestY;   // nothing clean within 200px: least bad wins
      }

      var cuts = [0];
      for (var i = 1; i < pages; i++) { cuts.push(cutNear(Math.round(i * pageH))); }
      cuts.push(canvas.height);

      // "Page 2 of 3" BURNED INTO THE IMAGE, not just into the filename.
      //
      // A client sees pixels in a message bubble and never sees the
      // filename, so without this there is no way to tell that a page
      // arrived out of order or did not arrive at all. MMS does not
      // guarantee ordering, and three separate texts certainly do not.
      //
      // IT GETS ITS OWN STRIP RATHER THAN SHARING THE PAGE'S BOTTOM MARGIN.
      // Measured on the 2026-10-02 letter, the white below the last line of
      // text was 23px on page 1 against 83 and 99 on pages 2 and 3 -- the
      // cuts land wherever the blank run happens to be, so there is no
      // offset that is clear of the text on every page. Adding a strip
      // makes the space exist instead of hoping for it. A single-page
      // letter gets no strip and no label, matching the filename rule.
      var LABEL_H = pages > 1 ? 52 : 0;

      function save(idx) {
        if (idx >= pages) return;
        var top = cuts[idx], bot = cuts[idx + 1];
        var slice = document.createElement('canvas');
        slice.width = canvas.width;
        // Every sheet is a FULL page tall even when its cut fell short, so
        // the images are a consistent size in the message thread rather than
        // one tall and one stubby.
        slice.height = Math.max(bot - top, pageH) + LABEL_H;
        var c = slice.getContext('2d');
        c.fillStyle = '#ffffff';
        c.fillRect(0, 0, slice.width, slice.height);
        c.drawImage(canvas, 0, top, canvas.width, bot - top,
                            0, 0, canvas.width, bot - top);
        if (LABEL_H) {
          // The frame's own sage, so it reads as the letter's furniture
          // rather than as something the browser stamped on afterwards.
          c.fillStyle = '#5e7164';
          c.font = '600 22px Calibri, Carlito, "Segoe UI", system-ui, sans-serif';
          c.textAlign = 'center';
          c.fillText('Page ' + (idx + 1) + ' of ' + pages,
                     slice.width / 2, slice.height - 18);
        }
        var a = document.createElement('a');
        a.download = pages > 1 ? base + ' (page ' + (idx + 1) + ' of ' + pages + ').png'
                               : base + '.png';
        a.href = slice.toDataURL('image/png');
        a.click();
        // Chrome serialises multiple downloads from one gesture poorly and
        // drops some when they are fired in a tight loop; a short gap makes
        // all of them land. It also lets the browser raise its own
        // "allow multiple downloads" prompt once rather than per file.
        if (idx + 1 < pages) setTimeout(function () { save(idx + 1); }, 600);
      }
      save(0);
      if (pages > 1) {
        btn.textContent = 'Saved ' + pages + ' pages';
        setTimeout(function () { btn.textContent = label; }, 4000);
      }
    }).catch(function (e) {
      btn.textContent = 'Could not render: ' + (e && e.message ? e.message : e);
      return null;
    }).then(function () {
      // Page mode comes off whatever happened -- leaving an 8.5in !important
      // width behind would reflow the preview the reader is looking at.
      mode.remove();
      bar.style.display = '';
      if (btn.textContent === 'Rendering…') { btn.textContent = label; }
      btn.disabled = false;
    });
  });
  }
  wire(document.getElementById('jsa-png'), true);
  wire(document.getElementById('jsa-png-one'), false);
})();
</script>"""


def _with_print_button(doc: str) -> str:
    """
    Put the button INSIDE the letter's document, not in front of it.

    THE OBVIOUS VERSION IS `_print_ui + html` AND IT BREAKS THE DOCUMENT.
    `render.build_html` returns a complete page beginning `<!DOCTYPE html>`.
    Concatenating anything ahead of that doctype means the doctype is no longer
    first, so the parser DISCARDS it and the whole letter renders in QUIRKS
    MODE. Measured 2026-09-30 on the real preview, in a real browser:

        document.compatMode   "BackCompat"   (standards: "CSS1Compat")
        document.doctype      null
        <meta>, <title> and the letter's ENTIRE stylesheet -> inside <body>
        first cash band       102px tall, against 108px in standards mode

    Quirks mode changes table row heights and margin collapsing, so the letter
    the reader prints from this preview was NOT laying out the same as the one
    `Build PDF` produces -- two print paths that are supposed to be identical,
    silently diverging in the one direction nobody checks. Nothing raised, and
    the page count happened to stay at one, which is why it survived.

    So: the style goes in <head> and the button just inside <body>, leaving the
    doctype where the parser needs it. Both halves fall back to prepending if
    the letter ever stops having a head or a body -- a preview with the button
    in the wrong place beats a preview with no button at all.
    """
    head_end = doc.lower().find("</head>")
    if head_end != -1:
        doc = doc[:head_end] + _PRINT_STYLE + doc[head_end:]
        # LOOK FOR <body> ONLY AFTER </head>, and this is not defensive
        # programming -- a plain search finds the wrong one. render.py's
        # stylesheet carries the comment "put a background on <body> and this
        # disappears underneath it", so the FIRST "<body" in the letter is
        # prose inside a CSS comment. Inserting there puts the button inside a
        # comment, where it is inert: the preview lost its print button
        # entirely and nothing raised. Caught 2026-09-30 by checking the live
        # DOM rather than the string.
        after_head = head_end + len(_PRINT_STYLE) + len("</head>")
    else:
        doc = _PRINT_STYLE + doc
        after_head = 0
    m = re.compile(r"<body\b[^>]*>", re.I).search(doc, after_head)
    if m:
        return doc[:m.end()] + _PRINT_BUTTON + _IMAGE_SCRIPT + doc[m.end():]
    return _PRINT_BUTTON + _IMAGE_SCRIPT + doc



# -- Output -------------------------------------------------------------------
#
# TWO TABS, and the hidden one still runs. Streamlit executes a hidden tab's
# body on every rerun, so the rundown is built from `ctx` -- which is already
# in memory -- and never fetches. The only real cost is writing the .pptx, and
# that is memoised on the slide's own rows below.


@st.cache_data(show_spinner=False)
def _rundown_pptx(rows_tuple) -> bytes:
    """
    The slide as bytes, memoised on its content.

    Without the cache this writes a PowerPoint file on every rerun of the
    page, including every keystroke in the commentary boxes, because the tab
    it lives in executes whether or not it is the one on screen.
    """
    buf = io.BytesIO()
    rundown.build_pptx(list(rows_tuple), buf,
                       logo=REPO / "assets" / "logo-full.png",
                       agmarket=REPO / "assets" / "agmarket-net.png")
    return buf.getvalue()


tab_letter, tab_slide = st.tabs(TAB_LABELS)

with tab_letter:

    ctx_for_render = dict(ctx)
    ctx_for_render["issue_date"] = issue
    ctx_for_render["kind"] = kind
    ctx_for_render["session"] = session
    # Follows the FORMAT, so switching the Letter radio re-bases the change column
    # without a refetch -- and a cache written before 2026-09-24 cannot impose the
    # old week-over-week basis on a Monday letter.
    ctx_for_render["change_basis"] = config.change_basis_for(kind)
    ctx_for_render["commentary"] = sections

    # -- Chart of the day (morning brief only) ------------------------------------
    # Picked from what you just typed, then from what moved, then a rotation. Chosen
    # HERE rather than in the fetch, because `sections` is the live text in the
    # boxes -- edit a headline and the chart re-aims on the next rerun.
    if kind == "am":
        _choices = ["Auto"] + [e["key"] for e in config.CHART_POOL]
        k1, k2 = st.columns([1, 3])
        with k1:
            _forced = st.selectbox("Chart of the day", _choices, index=0,
                                   help="Auto reads your headlines first, then the "
                                        "biggest mover, then a rotation.")
        # Whatever "Fetch headlines" already pulled, if anything. Never fetched for
        # the chart's sake -- press the button and the chart aims itself at the
        # day's news; do not and it falls through to the biggest mover.
        _cands = (st.session_state.get("wcr_heads") or {}).get("items") or None
        ctx_for_render["chart"] = letter_build.build_chart(
            ctx_for_render, issue, os.environ.get("MASSIVE_API_KEY", "").strip(), [],
            forced="" if _forced == "Auto" else _forced, candidates=_cands)
        with k2:
            _c = ctx_for_render.get("chart") or {}
            st.caption(f"**{_c.get('title', 'no chart')}** — {_c.get('reason', 'unavailable')}"
                       if _c else "No chart: no series came back for any market in the pool.")

        # A LINE INSTEAD, IF YOU WANT ONE. Anything in this box takes the chart's
        # place in the letter; clear it and the chart comes back. One slot, one
        # rule, nothing to toggle. "Use this" in the On This Day panel above
        # seeds it -- edit it into your own words before sending.
        _fact = st.text_area(
            "Or a line instead of the chart", key="wcr_dayfact", height=110,
            placeholder="1962 — Cesar Chavez and Dolores Huerta establish the "
                        "National Farm Workers Association",
            help="Takes the chart's place in the bottom right. Leave empty for the chart.")
        ctx_for_render["dayfact"] = _fact
        if _fact.strip():
            _lines = len([ln for ln in _fact.splitlines() if ln.strip()])
            st.caption(f"The letter will print {_lines} line(s) instead of the chart.")
            # THE BAND IS 1.89in AND THE BRIEF IS ONE PAGE. Each wrapped line is
            # roughly 0.16in at 8.5pt across 3.1in, so about eleven fit before the
            # float outgrows the whitespace it was chosen to sit in and the letter
            # runs to two. Warned rather than truncated -- silently dropping a
            # line he picked would be worse than a long letter he can see.
            if _lines > 6:
                st.warning(f"{_lines} lines is a lot for the corner slot. Over about "
                           "eight the float outgrows the band beside the signature "
                           "and the brief runs to a second page — check the preview.")

    # ── Which copy: with the disclaimer, or without ──────────────────────────────
    # TWO COPIES GO OUT AND ONLY ONE NEEDS THE DISCLAIMER. Ross emails the letter
    # in a message that already carries the firm's risk disclaimer, so the PDF and
    # the image attached to that message print it a second time. This drops it
    # from the attachment and nothing else.
    #
    # IT RESETS TO ON EVERY RUN and is never remembered. A disclaimer that goes
    # missing quietly is the only failure mode here that matters, so the switch
    # has to be deliberate each time rather than a setting that can be left off
    # and forgotten. `letter.build` does not pass the flag at all, so the CLI,
    # a --no-fetch re-render and --archive always keep the full letter.
    _no_disc = st.checkbox(
        "Leave the risk disclaimer off this copy",
        value=False, key="wcr_no_disclaimer",
        help="For the PDF or image you attach to an email that already carries "
             "the disclaimer. Resets to off on every run; the archived copy and "
             "the command line always keep it.")

    html = render.build_html(ctx_for_render, disclaimer=not _no_disc)

    if _no_disc:
        st.warning(
            "**This copy has no risk disclaimer.** The preview, Print / Save as "
            "PDF, Save as image and Download HTML below all now omit it — send it "
            "only inside an email that carries the disclaimer itself. Untick to "
            "get the full letter back.")

    missing = html.count(render.MISSING)
    if missing:
        st.warning(f"{missing} value(s) could not be filled. They are marked in the letter "
                   "so they cannot be missed — fill them in or fix the source before sending.")

    # PRINT FROM THE READER'S OWN BROWSER, which is the one machine in this picture
    # that definitely has one. letter.topdf drives headless Edge on the HOST, so on
    # Streamlit Cloud -- a bare Linux container -- there is nothing to drive and the
    # Build PDF button is disabled. This sidesteps that entirely: the preview below
    # is already an iframe holding the complete letter with its own @page rules, so
    # window.print() inside it prints exactly that document. Same print CSS, same
    # result as Build PDF, and it works on the deployed app.
    #
    # The button hides itself in the print output -- it is chrome, not letter.
    st.components.v1.html(_with_print_button(html), height=720, scrolling=True)
    st.caption("**Print / Save as PDF** prints the preview above from your own browser — "
               "same print CSS as Build PDF, and it works on the deployed app where "
               "Build PDF cannot. Choose *Save as PDF* as the destination. "
               "**Save as image** downloads the letter as PNGs laid out as printed "
               "8.5×11 sheets — same margins, same frame, same line breaks as the "
               "PDF — at twice print size. A multi-page letter saves as **one file "
               "per page**, each stamped *Page N of M* along the bottom, because a "
               "single tall image is unreadable once a phone fits it to a message "
               "bubble and a client never sees the filename. Cuts land in "
               "whitespace, not through a line. Your browser may ask once to "
               "allow several downloads.")

    # THE FILENAME SAYS WHICH COPY IT IS. Two near-identical PDFs of the same
    # letter land in the same folder every day, and the only difference is six
    # lines of small print at the foot. Naming them apart is the cheap half of
    # not attaching the wrong one.
    #
    # The IMAGE filename is not marked, deliberately: it comes from the document's
    # <title>, and appending to that would put "(no disclaimer)" in the browser's
    # print header on a client letter. The on-screen warning covers that case.
    _stem = f"{config.title_for(session)} {day.title()} {issue}"
    if _no_disc:
        _stem += " (no disclaimer)"

    d1, d2 = st.columns(2)
    with d1:
        st.download_button("Download HTML", data=html.encode("utf-8"),
                           file_name=f"{_stem}.html",
                           mime="text/html", use_container_width=True)
    with d2:
        browser = topdf.find_browser()
        if browser:
            if st.button("Build PDF", type="primary", use_container_width=True):
                OUT.mkdir(parents=True, exist_ok=True)
                html_path = OUT / f"{_stem}.html"
                pdf_path = OUT / f"{_stem}.pdf"
                html_path.write_text(html, encoding="utf-8")
                ok, msg = topdf.html_to_pdf(html_path, pdf_path)
                if ok:
                    st.session_state["wcr_pdf"] = pdf_path.read_bytes()
                    st.success(f"Built {pdf_path.name}")
                else:
                    st.error(f"PDF failed — {msg}")
        else:
            # THE REASON IS VISIBLE, NOT A TOOLTIP. This was help= only, and a greyed
            # button with a hover explanation reads as broken -- it got reported as a
            # bug on 2026-09-24 by the person who wrote the docstring explaining it.
            # Someone looking at a disabled control is asking why, and a hover they
            # have to guess at is not an answer.
            st.button("Build PDF", disabled=True, use_container_width=True)
            st.caption("No browser on this host. Use **Print / Save as PDF** or "
                       "**Save as image** above the preview — both run in your own "
                       "browser and give the same layout. Build PDF only earns its "
                       "place locally, where it writes the file `--archive` publishes.")

    if st.session_state.get("wcr_pdf"):
        st.download_button("Download PDF", data=st.session_state["wcr_pdf"],
                           file_name=f"{_stem}.pdf",
                           mime="application/pdf", use_container_width=True)

    # -- Archive ------------------------------------------------------------------
    # AFTER SENDING, NOT INSTEAD OF IT. This copies the rendered letter into the
    # private jsa-letter-archive repo and pushes. It is a separate button on purpose:
    # "published" means Ross emailed it, which nothing here can detect, and archiving
    # every build would bury the one that went out under a day of drafts.
    #
    # Unavailable on the deployed app -- no clone, no push credentials -- so it says
    # so rather than offering a button that cannot work.
    _arch_ok, _arch_why = archive.available()
    st.divider()
    if not _arch_ok:
        st.caption(f"Archive unavailable — {_arch_why}. Run locally to archive a sent letter.")
    else:
        a1, a2 = st.columns([1, 3])
        with a1:
            if st.button("Archive as sent", use_container_width=True):
                OUT.mkdir(parents=True, exist_ok=True)
                _hp = OUT / f"{config.title_for(session)} {day.title()} {issue}.html"
                _hp.write_text(html, encoding="utf-8")
                _pp = OUT / f"{config.title_for(session)} {day.title()} {issue}.pdf"
                res = archive.publish(issue, session, _hp, _pp if _pp.exists() else None,
                                      kind=kind, title=config.title_for(session))
                if not res["ok"]:
                    st.error(f"Not archived — {res['reason']}")
                elif not res["changed"]:
                    st.info("Already archived, unchanged.")
                else:
                    st.success("Archived and pushed." if res["pushed"]
                               else f"Committed locally. {res['reason']}")
        with a2:
            st.caption("Press this for the letter you actually sent. It copies the HTML "
                       "and PDF into the private archive repo and pushes — re-sending a "
                       "corrected letter keeps the earlier one in git history.")


with tab_slide:
    # Built from the SAME ctx the letter above was rendered from, so the two
    # cannot quote the same figure differently -- the bug CLAUDE.md records
    # twice between the letter and a dashboard, each defensible and neither
    # raising. See letter/rundown.py.
    _rd_rows = rundown.rows(ctx)
    _rd_fresh = rundown.freshness(ctx)

    # WHICH SESSION IS THIS? Community Cloud has no scheduler, so nothing
    # rebuilds the slide at 3pm -- it is built when the tab is opened. A
    # previous session's cutout is a perfectly good number and looks exactly
    # like today's, so the page says out loud which one it has.
    (st.warning if _rd_fresh["stale"] else st.success)(_rd_fresh["message"])

    _rd_gaps = rundown.missing(_rd_rows)
    if _rd_gaps:
        st.error(
            f"{_rd_gaps} figure(s) came back empty and print as "
            f"`{rundown.MISSING}` on the slide. Press **Fetch latest data** at "
            "the top of the page, or chase the source, before sending this.")

    st.markdown(rundown.as_markdown(_rd_rows))

    st.caption(
        "Every figure is live. Four that differ from the hand-typed deck and "
        "are not errors: the carcass weight line prints the week AMS actually "
        "published (that report runs about a fortnight behind), the 5-day "
        "averages are the five sessions **before** this print, both YTD rates "
        "are USDA's own published Change rows rather than ours, and the "
        "**Feeder Index firms up through the day** — its row is the first "
        "business day after CME's last file, so it is the least complete one "
        "and keeps moving as auctions report: on 2026-10-06 the 10/5 row went "
        "337.66 to 337.22 between morning and afternoon. Rebuild late for the "
        "steadier number; it is the same figure the index dashboard shows at "
        "any given moment.")

    _rd_stamp = rundown.short_date(issue).replace("/", "-")
    st.download_button(
        "Download PowerPoint slide",
        data=_rundown_pptx(tuple(_rd_rows)),
        file_name=f"Cattle Market Rundown {_rd_stamp}.pptx",
        mime=("application/vnd.openxmlformats-officedocument"
              ".presentationml.presentation"),
        type="primary",
    )
    st.caption(
        "One 16:9 slide, black text on white, both marks along the bottom — "
        "drop it straight into the weekly deck as slide 3.")

    # -- slide 7: Sterling ----------------------------------------------------
    #
    # A NETWORK CALL IN A TAB THAT RUNS WHETHER OR NOT IT IS ON SCREEN, so it
    # is cached for an hour. Sterling publishes roughly weekly; an hour is the
    # same deal the Saturday Slaughter view already takes for its MARS fetch.
    st.divider()
    st.markdown("#### Sterling slide (deck slide 7)")

    @st.cache_data(ttl=3600, show_spinner=False)
    def _sterling_data():
        return sterling.fetch()

    @st.cache_data(show_spinner=False)
    def _sterling_pptx(payload) -> bytes:
        buf = io.BytesIO()
        rundown.build_sterling_pptx(payload, buf,
                                    logo=REPO / "assets" / "logo-full.png",
                                    agmarket=REPO / "assets" / "agmarket-net.png")
        return buf.getvalue()

    _st_data = _sterling_data()
    if _st_data.get("error"):
        st.warning(f"Sterling tracker unavailable — {_st_data['error']}")
    else:
        _we = _st_data.get("week_ending")
        st.caption(
            f"From **{_st_data.get('subject', 'the Profit Tracker')}**, received "
            f"{_st_data.get('received')}. Week ending "
            f"{rundown.short_date(_we) if _we else rundown.MISSING}.")

        # Sterling's figures are REPRODUCED, never recomputed or reconciled
        # against AMS -- see letter/sterling.py. Where their own rows
        # disagree, say so rather than quietly repairing their data.
        for _note in sterling.anomalies(_st_data):
            st.warning(f"Sterling's own figures: {_note}")

        _mrows = rundown.sterling_rows(_st_data)
        st.markdown(rundown.as_markdown(_mrows))

        _w = _st_data.get("weekly", {})
        if _w:
            _hdr = rundown._col_header(_st_data)
            st.table({
                "": ["Cattle Slaughter", "Steer & Heifer",
                     "Fed Plant Capacity Utilization", "Cows",
                     "Cow Plant Capacity Utilization"],
                **{_hdr[i + 1]: [
                    f"{_w.get(k, [None]*4)[i]:,.0f}" if _w.get(k) and k in
                    ("cattle_slaughter", "steer_heifer", "cows")
                    else (f"{_w.get(k, [None]*4)[i]:.1f}%" if _w.get(k) else "—")
                    for k in ("cattle_slaughter", "steer_heifer", "fed_capacity",
                              "cows", "cow_capacity")]
                   for i in range(4)},
            })

        st.download_button(
            "Download Sterling slide",
            data=_sterling_pptx(_st_data),
            file_name=f"Cattle Market Rundown — Sterling {_rd_stamp}.pptx",
            mime=("application/vnd.openxmlformats-officedocument"
                  ".presentationml.presentation"),
        )
        st.caption(
            f"Margins, both tables and the *{sterling.ATTRIBUTION}* line, at "
            "the deck's own coordinates. The tables are **real PowerPoint "
            "tables**, not the pasted screenshots the hand-built slide uses, "
            "so they stay sharp and the figures stay selectable.")
