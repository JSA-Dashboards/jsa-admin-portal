"""
Build the Tuesday or Friday letter.

    python -m letter.build                      # today's Tuesday letter
    python -m letter.build --friday             # the Friday letter
    python -m letter.build --date 2026-09-22
    python -m letter.build --no-fetch           # re-render after editing commentary
    python -m letter.build --html-only          # skip the PDF step
    python -m letter.build --friday --cof-guess on_feed=101.8,placed=96.8,marketed=96.1

The two letters share the futures opening, the technicals and most of the
rundown. Friday drops the five-bullet weekly cash block, expands the rundown
with the completed week and both YTD rates, and adds regional cash, CFTC, and --
on the one Friday a month that follows a USDA release -- Cattle on Feed.

The normal cycle is two runs. The first fetches the data and writes
out/commentary_<date>.md with the figures quoted underneath each heading; you
write your read into that file; the second run picks it up and produces the PDF.
--no-fetch makes the second run instant and, more to the point, guarantees the
numbers in the PDF are the ones you were looking at while writing.

EVERY SOURCE IS ISOLATED. One agency being down degrades that section to a
marked [[?]] and the letter still builds -- there is no run in which a USDA
outage leaves you with nothing at 4pm. The exit code is non-zero when anything
is missing, so a scheduled run can tell "built, needs attention" from "clean".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

from . import (archive, chart, cof, commentary, config, draft_store, render,
               settle_log, sources, technicals, topdf)

# snowflake_db passes a raw DBAPI connection to pd.read_sql, which pandas
# warns about on every query. That is the shared module's choice, not this
# one's; silenced for this process rather than edited there.
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "out"


# -- Secrets ------------------------------------------------------------------

def load_env() -> None:
    """
    Environment first, then .env, then .streamlit/secrets.toml.

    The dashboards read secrets through st.secrets, which does not exist here,
    so the same values are picked up from the file directly. Nothing is printed:
    these are credentials.
    """
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    secrets = REPO / ".streamlit" / "secrets.toml"
    if secrets.exists():
        try:
            import tomllib
            data = tomllib.loads(secrets.read_text(encoding="utf-8-sig"))
        except Exception:
            return
        for k, v in data.items():
            if isinstance(v, (str, int, float)):
                os.environ.setdefault(k, str(v))

    # THE PASSPHRASE NAMING TRAP, bridged here rather than duplicated.
    #
    # CLAUDE.md records that the key passphrase lives ONLY in
    # SNOWFLAKE_PRIVATE_KEY_PASSPHRASE, and that the Python connector does not
    # read it -- snowflake_db._load_private_key() looks for
    # SNOWFLAKE_PRIVATE_KEY_PWD. Without this line the connection falls through
    # to password auth and dies on KeyError: 'SNOWFLAKE_PASSWORD', which names
    # neither the real cause nor the fix.
    #
    # Mapped in memory, never written to .env: the passphrase stays in the one
    # place it already lives.
    if not os.environ.get("SNOWFLAKE_PRIVATE_KEY_PWD"):
        phrase = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        if phrase:
            os.environ["SNOWFLAKE_PRIVATE_KEY_PWD"] = phrase


def _try(label: str, fn, errors: list):
    """Run one fetch; record the failure and carry on rather than aborting."""
    try:
        return fn()
    except Exception as e:
        errors.append(f"{label}: {type(e).__name__}: {e}")
        if os.environ.get("LETTER_DEBUG"):
            traceback.print_exc()
        return None


# -- Assembly -----------------------------------------------------------------

def report_futures_health(ctx: dict, issue: date, errors: list) -> None:
    """
    Say so when the futures are not what they look like.

    WHY THIS IS NOT PART OF _try(). _try reports a source that RAISED. Every
    check in the build asked whether data came back, and on 2026-09-28 the
    answer was yes: the Monday brief printed 2026-09-11 settles as that
    morning's futures -- Oct feeders at 332.50 against a Friday settle of
    335.00 -- and gather() returned an empty error list, because the newest bar
    in a stale series is still a perfectly good bar. Staleness is not an
    exception, so nothing raised, so nothing was said.

    The three things worth saying are separate on purpose: a stale settle must
    stop the letter going out, a recovered one is usable but should be known
    about, and a missing move is already marked in the text and only needs
    explaining.
    """
    cons = (ctx.get("live_cattle") or []) + (ctx.get("feeder_cattle") or [])
    if not cons:
        return

    stale = sorted({c.get("settle_date") for c in cons if c.get("settle_stale")})
    if stale:
        errors.append(
            f"FUTURES ARE STALE. The newest cattle settlement available is {stale[0]}, "
            f"more than {sources.MAX_SETTLE_AGE_DAYS} days before {issue}. The prices in "
            "the futures block are NOT current -- do not send this letter without "
            "replacing them.")

    recovered = [c for c in cons if c.get("settle_recovered")]
    if recovered:
        srcs = ", ".join(sorted({c.get("settle_source") or "?" for c in recovered}))
        errors.append(
            f"{len(recovered)} cattle contract(s) recovered from {srcs}: the daily "
            "settlement series has a hole and the hourly bars were used to fill it. An "
            "hourly close is the last trade, not the official settlement -- usually "
            "identical, occasionally a few ticks out.")

    # A GAPPED HISTORY CORRUPTS THE WEEKLY CHANGE AND THE MOVING AVERAGES
    # TOGETHER, and both look plausible while being wrong. Moved here from a
    # console print so it reaches the page with the rest.
    gaps, no_base = set(), []
    for key, label in (("live_cattle", "Live Cattle"), ("feeder_cattle", "Feeders")):
        for c in ctx.get(key) or []:
            gaps.update(c.get("gaps") or [])
            if c.get("week_base_missing"):
                no_base.append(f"{label} {c.get('month')}")
    for tech in (ctx.get("tech_lc"), ctx.get("tech_fc")):
        if tech:
            gaps.update(tech.get("gaps") or [])
    if no_base:
        errors.append(
            f"No settle on the prior Friday for: {', '.join(no_base)}. The week-over-week "
            "change is marked rather than measured from an earlier session, which would "
            "print a plausible wrong number.")
    if gaps:
        errors.append(
            f"Futures history is missing sessions: {', '.join(sorted(gaps)[:8])}. Moving "
            "averages over a gapped series are wrong rather than approximate, so they are "
            "marked too. This is upstream data, not a fetch failure.")

    missing = [c.get("month") for c in cons if c.get("change_missing")]
    if missing:
        errors.append(
            f"No daily change for {', '.join(str(m) for m in missing)}. The previous "
            "session is absent from the feed, so the move would be measured across the "
            "gap; it is marked in the letter instead of computed across it.")


# How far behind the issue date each report may legitimately be. They differ
# because the SERIES differ, not because some are trusted more. Boxed beef and
# daily slaughter are same-day prints, so three days covers a weekend and
# anything past it means a back-dated rebuild picked up the newest report
# instead of that day's. The 5-area weekly weighted average always describes
# the PRIOR week, so it is seven days behind on a Monday BY DESIGN -- warning
# about that every morning would make this panel noise, and a warning nobody
# reads is how the futures outage went unnoticed for a whole letter.
MAX_REPORT_LAG_DAYS = {"boxed beef": 3, "daily slaughter": 3, "cash trade": 10,
                       # SJ_LS712 posts Friday for the week ending Saturday, so
                       # the longest honest lag is Thursday's six days. Seven
                       # catches a feed frozen for more than a week on any day;
                       # the Friday-only equality check below catches the case
                       # seven days cannot, which is a Friday letter built on
                       # last Friday's file.
                       "weekly slaughter": 7}


def report_source_health(ctx: dict, issue: date, kind: str, errors: list) -> None:
    """
    The USDA sources' freshness problems, on the page rather than the console.

    WHY THIS FUNCTION EXISTS. Every one of these checks was already written and
    already correct -- as a print() in build.main. Ross writes the letter on the
    deployed Streamlit page, which shows the `errors` list and nothing else, so
    he had never seen one of them. "Boxed beef is the 9/25 print" was being
    explained to an empty terminal. Same gap, same fix, as
    report_futures_health: a source's problems belong where the letter is
    written.

    ONLY CONDITIONAL, ACTIONABLE THINGS GO IN THE LIST. The always-true notes --
    that carcass weights run twelve days in arrears, that the feeder index is
    JSA's own estimate -- stay as console prints. They are context, not
    problems, and a panel that cries every morning stops being read on the one
    morning it matters.
    """
    # THE 3PM CENTRAL TRAP, AND WHY IT IS PM-ONLY. LM_XB403 PM publishes around
    # 3pm Central. The evening letter is written after that and wants today's
    # print, so an older one means the release has not landed. The MORNING
    # brief legitimately quotes the previous session's cutout -- that is what a
    # 07:30 letter is -- so firing there would warn every single day about the
    # letter working correctly.
    cut_date = (ctx.get("cutout") or {}).get("report_date")
    if kind != "am" and cut_date and date.fromisoformat(cut_date) < issue:
        errors.append(
            f"Boxed beef is the {cut_date} print, not {issue}'s. LM_XB403 PM releases "
            f"about 3pm Central -- re-run after that for today's cutout. Until then the "
            f"letter correctly labels it as the {cut_date} PM print.")

    ds = ctx.get("daily_slaughter") or {}
    if ds.get("status") and ds["status"].lower() != "final":
        errors.append(
            f"AMS 3208 is a {ds['status'].upper()} print for {ds.get('report_date')}. The "
            "daily and week-to-date slaughter figures will be revised -- re-run for the "
            "final before sending.")

    # SEVERAL AMS ENDPOINTS SERVE THE NEWEST REPORT AND TAKE NO DATE FILTER, so
    # a back-dated rebuild quietly reports today's numbers under an earlier
    # date. Harmless on the day, wrong afterwards, and silent either way.
    stale = []
    for label, rd in (("boxed beef", cut_date),
                      ("daily slaughter", ds.get("report_date")),
                      ("cash trade", (ctx.get("cash") or {}).get("report_date")),
                      ("weekly slaughter", (ctx.get("slaughter") or {}).get("report_date"))):
        if rd and abs((date.fromisoformat(rd) - issue).days) > MAX_REPORT_LAG_DAYS[label]:
            stale.append(f"{label} is from {rd}")
    if stale:
        errors.append(
            f"Built for {issue}, but " + "; ".join(stale) + ". These AMS endpoints always "
            "serve the newest report and take no date filter, so a back-dated build does "
            "not reconstruct that day.")

    if kind == "friday":
        # THE WEEK-IN-REVIEW'S HEADLINE KILL, AND THE ONE DAY IT CAN BE PINNED
        # EXACTLY. sj_ls712.txt is a static "newest report" URL with no date
        # filter, and fetch_slaughter takes the top week row of whatever it is
        # served without ever comparing it to the issue. On any other weekday
        # the newest file IS last Friday's and that is correct, so only Friday
        # can demand equality.
        #
        # What it costs when it is wrong: on 2026-09-25 an unrefreshed file
        # would have printed "Weekly slaughter: 529,000 compared to 505,000
        # head LW" against a true 484,000 -- a 45,000 head error that flips the
        # week from -8.5% to +4.8%, with nothing on the page to suggest it.
        wk_rd = (ctx.get("slaughter") or {}).get("report_date")
        if wk_rd and issue.weekday() == 4 and date.fromisoformat(wk_rd) != issue:
            errors.append(
                f"Weekly slaughter is the {wk_rd} report, not {issue}'s. SJ_LS712 posts "
                "Friday and the URL always serves the newest file, so the week-in-review "
                "would quote LAST week's kill as this week's. Re-run once it lands.")

        cftc = ctx.get("cftc") or {}
        if cftc.get("as_of") and not sources.cftc_is_current(cftc, issue):
            errors.append(
                f"CFTC data is as of {cftc['as_of']}, which is NOT this week's Tuesday. It "
                "releases Friday 3:30pm ET, so a letter built before then carries last "
                "week's positions with no error. Re-run after 3:30pm ET.")

    if not os.environ.get("USE_SNOWFLAKE"):
        errors.append(
            "USE_SNOWFLAKE is not set, so the feeder index and Douglas imports came from "
            "the committed SQLite file, which is stale. Set USE_SNOWFLAKE=1 and the "
            "Snowflake credentials for the live values.")


TECH_KEYS = ("tech_lc", "tech_fc")


def technical_months(ctx: dict, key: str) -> list:
    """The months offered for one product, front first."""
    rows = ctx.get("live_cattle" if key == "tech_lc" else "feeder_cattle") or []
    ordered = [c.get("month") for c in rows if c.get("month")]
    built = ctx.get(key + "_all") or {}
    # Contract order, then anything built that the futures list no longer
    # carries -- a month can survive in the cached technicals across a roll.
    return ordered + [m for m in built if m not in ordered]


def select_technicals(ctx: dict) -> None:
    """
    Resolve ctx['tech_lc'] and ['tech_fc'] from the chosen month.

    ONE PLACE, CALLED FROM THREE. The fetch sets it, the page sets it when
    the dropdown moves, and `main --no-fetch` sets it before rendering --
    so a letter, its PDF and the figures Ross writes against can never be
    about different months. `render.technicals_block` prints the heading
    off `tech["month"]` and `hints()` quotes the averages off the same
    dict, which is exactly the pairing that goes wrong when two callers
    each resolve it their own way.

    Falls back to the front contract when the stored choice is absent or
    has rolled off, rather than to nothing: an unavailable month must not
    cost the section its figures.
    """
    for key in TECH_KEYS:
        built = ctx.get(key + "_all") or {}
        if not built:
            continue
        months = technical_months(ctx, key)
        chosen = ctx.get(key + "_month")
        if chosen not in built:
            chosen = next((m for m in months if m in built), None)
        if chosen is None:
            continue
        ctx[key + "_month"] = chosen
        ctx[key] = built[chosen]


def gather(issue: date, errors: list, kind: str = "tuesday", cof_guesses: dict = None) -> dict:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not api_key:
        errors.append("MASSIVE_API_KEY not set -- futures and technicals unavailable")

    ctx: dict = {
        "issue_date": issue,
        "kind": kind,
        "change_basis": config.change_basis_for(kind),
        "live_cattle": [],
        "feeder_cattle": [],
        "tech_lc": None,
        "tech_fc": None,
        "cash": {},
        "cutout": {},
        "slaughter": {},
        "daily_slaughter": {},
        "carcass_weights": {},
        "fci": {},
        "douglas": {},
        "cftc": {},
        "regional_cash": {},
        "cof": {},
        "outside": [],
        "chart": {},
        "calendar": [],
        "regional_cash": {},
    }

    # SYNC BEFORE ANYTHING READS THE LOG, which is the whole reason this line
    # is here and not left to backfill_week_base().
    #
    # sources.fetch_futures now reads letter/data/settle_log.json as a recovery
    # tier, and letter/data/ is gitignored -- so on Streamlit Cloud, where every
    # reboot rebuilds the container from a fresh clone, that file starts EMPTY.
    # backfill_week_base() does call sync(), but it runs after gather(), so the
    # first fetch of the day would miss every banked settle and fall back to an
    # hourly close: 335.00 on the Oct feeder where 334.925 was sitting in
    # Snowflake the whole time. Only a second fetch would have been right, and
    # nothing would have said why.
    synced = settle_log.sync()
    if synced and not synced.startswith("Settle log:"):
        errors.append(f"settle log: {synced}")

    if api_key:
        # The morning brief must not read today's in-progress bar as a settle:
        # it goes out at 07:30, before CME livestock opens, and quotes the prior
        # session. The evening letter is written after the close and wants
        # today's. See sources.fetch_futures(completed_only=...).
        settled_only = (kind == "am")
        ctx["live_cattle"] = _try("live cattle futures", lambda: sources.fetch_futures(
            config.LIVE_CATTLE_CODE, api_key, issue, config.N_CONTRACTS,
            completed_only=settled_only), errors) or []
        ctx["feeder_cattle"] = _try("feeder cattle futures", lambda: sources.fetch_futures(
            config.FEEDER_CATTLE_CODE, api_key, issue, config.N_CONTRACTS,
            completed_only=settled_only), errors) or []

        # BEFORE ANYTHING ELSE READS THEM. The FCI basis line divides the index
        # by the front feeder settle, so a stale future silently becomes a
        # wrong basis printed beside a correct index -- on 2026-09-28 that was
        # a basis of +5.29 where the real figure was +2.79.
        # HERE, INSIDE gather(), because the Streamlit page calls gather()
        # directly and never goes through build.main -- hanging this off main
        # alone silently left the authoring page with no staleness warning at
        # all, which is where the letter is actually written.
        #
        # The FCI basis line divides the index by the front feeder settle, so a
        # stale future quietly becomes a wrong basis printed beside a correct
        # index: on 2026-09-28 that was +5.29 where the real figure was +2.87.
        report_futures_health(ctx, issue, errors)

        # The chart of the day, morning brief only. Which market it shows is
        # decided further down, once the commentary and the day's moves are
        # known -- see build_chart().

        # EVERY CONTRACT, NOT JUST THE FRONT ONE. Ross picks which month the
        # technical read is about -- it is not always the nearby, and on a
        # roll week it is routinely not. Asked for 2026-10-12.
        #
        # All three are fetched up front rather than on demand, which costs
        # four extra /aggs calls per build and buys two things: the dropdown
        # is instant, and `build.main --no-fetch` -- the run that makes the
        # emailed PDF -- can render any month without a network at all. A
        # fetch-on-change design would have broken the second quietly, which
        # is the half nobody would notice until a PDF came out on the wrong
        # month.
        #
        # A month whose fetch fails is still RECORDED, with its error, so it
        # stays in the dropdown and says why. Dropping it would make a failed
        # feed look like a contract that does not exist.
        for key, label, rows in (("tech_lc", "live cattle", ctx["live_cattle"]),
                                 ("tech_fc", "feeder", ctx["feeder_cattle"])):
            built = {}
            for c in rows:
                month = c.get("month")
                if not month:
                    continue
                built[month] = _try(
                    f"{label} technicals {month}",
                    lambda c=c: technicals.build(c["ticker"], api_key,
                                                 config.MA_WINDOWS),
                    errors) or {"ticker": c.get("ticker"), "month": month,
                                "error": "no bars returned"}
            ctx[key + "_all"] = built
        select_technicals(ctx)

    ctx["cash"] = _try("cash trade (LM_CT150/CT154)", sources.fetch_cash_trade, errors) or {}
    ctx["cutout"] = _try("boxed beef (LM_XB403/LSWFEDCC)", sources.fetch_cutout, errors) or {}
    ctx["slaughter"] = _try("weekly slaughter (SJ_LS712)", sources.fetch_slaughter, errors) or {}
    ctx["daily_slaughter"] = _try("daily slaughter (AMS 3208)",
                                  sources.fetch_daily_slaughter, errors) or {}
    ctx["carcass_weights"] = _try("carcass weights (AMS 3658)",
                                  sources.fetch_carcass_weights, errors) or {}
    if ctx["carcass_weights"].get("error"):
        errors.append(f"carcass weights (AMS 3658): {ctx['carcass_weights']['error']}")

    if config.INCLUDE_FEEDER_INDEX:
        ctx["fci"] = _try("feeder cattle index (Snowflake)", sources.fetch_feeder_index, errors) or {}
    ctx["douglas"] = _try("Douglas imports (Snowflake)",
                          lambda: sources.fetch_douglas_ytd(issue.year), errors) or {}

    if kind == "am":
        # The morning brief's own sources. Cattle futures do not open until
        # 08:30 CT, so grain and equities are the only real overnight signal.
        if api_key:
            ctx["outside"] = _try("outside markets", lambda: sources.fetch_outside_markets(
                api_key, issue), errors) or []
        ctx["calendar"] = _try("USDA release calendar",
                               lambda: sources.fetch_report_calendar(issue), errors) or []
        # WEEK TO DATE, not yesterday. AMS publishes its daily summary around
        # 11am so today's has not printed, and Monday is routinely untested --
        # a Tuesday brief built from Monday alone reads "no established test"
        # while the week has in fact traded.
        ctx["regional_cash"] = _try("cash week-to-date (AMS daily)",
                                    lambda: sources.fetch_regional_cash_wtd(issue), errors) or {}

    if kind == "recap":
        # THE SAME WEEK-TO-DATE SOURCE THE MORNING BRIEF USES, not the single-day
        # one Friday reads. Tue-Thu evening the news is how the week has traded
        # so far, and Monday is routinely untested -- a Tuesday letter built from
        # Monday alone reads "no established test" while the week has in fact
        # traded. Monday's letter does not need this: it reports last week's
        # completed average instead.
        ctx["regional_cash"] = _try("cash week-to-date (AMS daily)",
                                    lambda: sources.fetch_regional_cash_wtd(issue), errors) or {}

    if kind == "friday":
        ctx["cftc"] = _try("CFTC managed money", sources.fetch_cftc, errors) or {}
        # WEEK TO DATE, same as the recap and the morning brief. This read a
        # SINGLE DAY until 2026-09-24 -- the Friday itself, "the week's last
        # established test" -- which is a defensible number and the wrong one
        # for a week-in-review: it reported Friday's trade under a letter about
        # the week. Ross asked for the recap's block here, and week-to-date on a
        # Friday is the whole week, which is what this letter is for.
        ctx["regional_cash"] = _try("cash week-to-date (AMS daily)",
                                    lambda: sources.fetch_regional_cash_wtd(issue), errors) or {}
        ctx["cof"] = _try("Cattle on Feed", lambda: cof.fetch(issue, cof_guesses), errors) or {}

    # LAST, once every source is in, and inside gather() so the Streamlit page
    # gets it too -- the page calls gather() directly and never goes through
    # build.main, which is exactly how these warnings stayed invisible.
    report_source_health(ctx, issue, kind, errors)
    return ctx


def backfill_week_base(ctx: dict, out_dir: Path, issue: date) -> list:
    """
    Recover the week-over-week change from the PREVIOUS letter when the futures
    history has no bar for the prior Friday.

    This is how Ross computes it by hand: the prior Friday's settles are printed
    in the Friday letter, and every build already stores them in
    out/data_<kind>_<date>.json. Chaining to that is exact -- it is the same
    number the client read last time -- where reaching back to an earlier
    session in a gapped series is merely plausible.

    Verified against 2026-09-22: the 9/18 file carries Oct Live Cattle at
    215.925, and 218.775 - 215.925 = +2.85, which is what the letter printed.

    Returns the contracts it fixed, for reporting.
    """
    prior_friday = issue - timedelta(days=(issue.weekday() - 4) % 7 or 7)

    # PULL THE LOG DOWN FIRST. letter/data/ is gitignored, so a fresh container
    # starts with nothing and every previous build's record is in Snowflake
    # rather than on this disk. Placed here, before the read below, so both
    # callers get it -- the CLI and the authoring page -- rather than only
    # whichever one remembered to ask.
    synced = settle_log.sync()
    if synced:
        print(f"  {synced}")

    # OUR OWN LOG FIRST. Every previous build recorded what it fetched, so once
    # a letter has been built on a Friday this needs nothing from Massive's
    # history -- which is the whole point, that history having had a week-long
    # hole since 2026-09-14.
    fixed = []
    logged = settle_log.settles_on(prior_friday)
    for key in ("live_cattle", "feeder_cattle"):
        for c in ctx.get(key) or []:
            if not c.get("week_base_missing"):
                continue
            base = logged.get(c.get("ticker"))
            if base is None:
                continue
            c["change_week"] = round(float(c["settle"]) - float(base), 4)
            c["week_base_missing"] = False
            c["week_base_source"] = f"settle log ({base})"
            fixed.append(f"{c.get('month')} {base}")

    prior_ctx = None
    for kind in ("friday", "tuesday"):
        p = out_dir / f"data_{kind}_{prior_friday}.json"
        if p.exists():
            try:
                prior_ctx = json.loads(p.read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                continue
    if not prior_ctx:
        return fixed

    for key in ("live_cattle", "feeder_cattle"):
        # ONLY trust a stored settle that really is the prior Friday's. A letter
        # rebuilt later, or built when the history already had the gap, carries a
        # settle_date from some other session -- using it would compute a change
        # against the wrong day and look perfectly reasonable doing it.
        was = {c.get("month"): c.get("settle") for c in (prior_ctx.get(key) or [])
               if str(c.get("settle_date", ""))[:10] == prior_friday.isoformat()}
        for c in ctx.get(key) or []:
            if not c.get("week_base_missing"):
                continue
            base = was.get(c.get("month"))
            if base is None:
                continue
            c["change_week"] = round(float(c["settle"]) - float(base), 4)
            c["week_base_missing"] = False
            c["week_base_source"] = f"data_{prior_friday} ({base})"
            fixed.append(f"{c.get('month')} {base}")
    return fixed


# -- Prior-Friday settles, entered by hand ------------------------------------
#
# The week-over-week change needs one number per contract: the prior Friday's
# settle. Normally that comes from the futures history, or failing that from the
# previous letter's stored settles (backfill_week_base above). When neither is
# available -- Massive's history has had no bars for 2026-09-14..09-18 for over
# a week -- these let you type the six numbers off your own last letter rather
# than lose the whole block.
#
# KEYED BY TICKER, NOT MONTH. "Oct" is both LEV6 and GFV6; keying by month would
# quietly apply the Live Cattle base to the Feeder contract.


def prior_friday_of(issue: date) -> date:
    """The Friday the week-over-week change measures from."""
    return issue - timedelta(days=(issue.weekday() - 4) % 7 or 7)


def week_base_path(out_dir, issue, day: str = None) -> Path:
    """
    Keyed by the PRIOR FRIDAY, not by the letter.

    That Friday's settle is a property of the week: Monday's letter and
    Thursday's letter both measure from it. Keying by day meant typing the same
    six numbers again on every letter of the week. `day` is accepted and ignored
    so existing callers keep working.
    """
    return Path(out_dir) / f"weekbase_{prior_friday_of(issue)}.json"


def load_week_base(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: float(v) for k, v in data.items() if v} if isinstance(data, dict) else {}


def save_week_base(path: Path, bases: dict) -> None:
    """
    sort_keys because this file is mirrored to Snowflake and compared as TEXT.
    draft_store.store() skips a body identical to the newest row, and dict
    order alone would make an unchanged set of settles look like a new version
    and fill the history with rows that differ only in line order.
    """
    clean = {k: float(v) for k, v in (bases or {}).items() if v}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(clean, indent=2, sort_keys=True), encoding="utf-8")


def apply_week_base(ctx: dict, bases: dict) -> list:
    """
    Fill missing weekly changes from hand-entered prior-Friday settles.

    Only touches contracts that are actually missing a base, so a real bar or a
    chained value always wins over a typed one. Returns what it filled.
    """
    if not bases:
        return []
    fixed = []
    for key in ("live_cattle", "feeder_cattle"):
        for c in ctx.get(key) or []:
            if not c.get("week_base_missing"):
                continue
            base = bases.get(c.get("ticker"))
            if not base:
                continue
            c["change_week"] = round(float(c["settle"]) - float(base), 4)
            c["week_base_missing"] = False
            c["week_base_source"] = f"entered by hand ({base})"
            fixed.append(f"{c.get('month')} {base}")
    return fixed


def hand_entered_bases(ctx: dict) -> list:
    """
    (ticker, label) for every contract whose week base was TYPED, not fetched.

    Needed because a typo is invisible otherwise. missing_week_bases() empties
    as soon as the six settles are entered, and the page hung its whole entry
    form off that -- so the moment Ross finished typing, the form vanished and
    a wrong figure could not be corrected from the page at all. Reported
    2026-09-25 with a wrong October already saved.

    A base that came from the futures history or from a previous letter is NOT
    in this list. Those are real data and offering to overwrite them invites
    exactly the mistake the [[?]] marking exists to prevent.
    """
    out = []
    for key, product in (("live_cattle", "Live Cattle"), ("feeder_cattle", "Feeder Cattle")):
        for c in ctx.get(key) or []:
            if str(c.get("week_base_source", "")).startswith("entered by hand"):
                out.append((c["ticker"], f"{product} {c.get('month')}"))
    return out


def missing_week_bases(ctx: dict) -> list:
    """(ticker, label) for every contract still without a prior-Friday settle."""
    out = []
    for key, product in (("live_cattle", "Live Cattle"), ("feeder_cattle", "Feeder Cattle")):
        for c in ctx.get(key) or []:
            if c.get("week_base_missing"):
                out.append((c["ticker"], f"{product} {c.get('month')}"))
    return out


def hints(ctx: dict, kind: str = "tuesday") -> dict:
    """
    What to quote under each commentary heading in the editable file.

    These are the figures you would otherwise be flipping between dashboards to
    read while writing the market read.
    """
    out: dict = {key: [] for key, _ in commentary.sections_for(kind)}
    keys = set(out)

    # Derived from the format's OWN sections rather than hardcoded, so a format
    # that lacks them cannot KeyError. The AM report has only a Morning Note,
    # and assuming "market_action" existed killed the build before it wrote
    # anything -- after a full fetch, which is the expensive half.
    #
    # "headlines" IS LAST FOR A REASON. Every evening format has a headlines
    # section too, and their figures belong under Market Action; only the AM
    # brief, whose sole written section IS Headlines, falls through to it.
    #
    # Leaving it out of this tuple is why the morning draft has never carried a
    # figure block. The AM key shipped as "headlines" in the same commit that
    # wrote these tuples (786546e), so `lead` resolved to None every time and
    # add() discarded all six contract settles, the slaughter, the cash and the
    # YTD -- silently, because add() skips a slot the format lacks. The guard
    # that stopped a KeyError turned the crash into silence, and no test ever
    # called hints() with kind="am". Found 2026-09-28, the morning the futures
    # were wrong and the draft said nothing about it.
    lead = next((k for k in ("morning_note", "key_headlines", "market_action",
                             "headlines") if k in keys), None)
    tail = next((k for k in ("cash_recap", "fundamental", "morning_note") if k in keys), None)
    if tail is None and len(keys) == 1:
        # Only the AM brief has a single written section, so only it sends the
        # tail figures to the same place. Every other format keeps its current
        # behaviour exactly -- a busy Monday is no time to move the evening
        # letter's furniture.
        tail = lead

    def add(slot, text):
        """Append only to a slot this format actually has."""
        if slot in keys:
            out[slot].append(text)

    basis = "week to date" if ctx["change_basis"] == "week" else "session"
    key = "change_week" if ctx["change_basis"] == "week" else "change_day"
    for label, rows in (("Live Cattle", ctx["live_cattle"]), ("Feeders", ctx["feeder_cattle"])):
        for r in rows:
            add(lead, f"{label} {r['month']}: {r.get(key)} ({basis}) at {r.get('settle')}")

    # Through add() as well: the AM format has no technicals sections at all.
    for slot, tech, label in (("technicals_lc", ctx.get("tech_lc"), "Live Cattle"),
                              ("technicals_fc", ctx.get("tech_fc"), "Feeders")):
        if not tech or tech.get("error"):
            add(slot, f"{label}: no bars available")
            continue
        ma = tech.get("ma", {})
        # "unavailable", never a bare None. These are the figures Ross writes
        # from, and "close None on None" in a draft invites a guess where the
        # printed letter would have shown a [[?]].
        def _fig(v):
            return "unavailable" if v is None else v

        add(slot, f"{tech.get('month','')} {label} close {_fig(tech.get('last_close'))}"
                  f" on {_fig(tech.get('last_date'))}")
        # A MEAN OVER A GAPPED SERIES IS WRONG, NOT APPROXIMATE. On 2026-09-22 a
        # "9-day" average was really nine of the last fourteen sessions and read
        # 216.392 where the true figure was 218.90. The letter used to mark that
        # [[?]] when it printed the averages; it no longer prints them, so the
        # warning has to live HERE -- Ross writes his read from these figures,
        # and a wrong number restated in his own prose carries no [[?]] at all.
        trustworthy = tech.get("complete", True)
        for w in config.MA_WINDOWS:
            # BOTH KEY TYPES. technicals.build returns int keys, but the context
            # is cached to JSON between the fetch run and the --no-fetch
            # re-render, and JSON has no integer keys -- 9 comes back as "9".
            # render.technicals_block carried this same guard until the averages
            # stopped printing, and removing it there left the hazard here: the
            # draft quoted "9-day MA None" as the figure to write against.
            v = ma.get(w)
            if v is None:
                v = ma.get(str(w))
            if v is None:
                add(slot, f"{w}-day MA unavailable")
            elif trustworthy:
                add(slot, f"{w}-day MA {v}")
            else:
                add(slot, f"{w}-day MA {v} -- DO NOT QUOTE, the series has a hole "
                          f"({', '.join(tech.get('gaps') or []) or 'missing sessions'})")
        add(slot, f"prior session high/low {_fig(tech.get('prior_high'))} / "
                  f"{_fig(tech.get('prior_low'))}")
        add(slot, f"{_fig(tech.get('swing_days'))}-day swing high/low "
                  f"{_fig(tech.get('swing_high'))} / {_fig(tech.get('swing_low'))}")
        add(slot, "support/resistance below are YOUR call -- nothing is printed unless you write it")

    # Figures SJ_LS712 does publish but the Tuesday letter does not print. They
    # are quoted here because they are the completed-week context you would
    # otherwise open the Cattle Weights dashboard to read.
    sl = ctx.get("slaughter") or {}
    wk = sl.get("weekly") or {}
    if wk.get("value") is not None:
        add(tail, 
            f"week ending {wk.get('week_ending')}: {wk['value']:,.0f} head "
            f"vs {wk.get('last_week'):,.0f} LW and {wk.get('year_ago'):,.0f} LY"
            if wk.get("last_week") and wk.get("year_ago")
            else f"week ending {wk.get('week_ending')}: {wk['value']:,.0f} head")
    if wk.get("ytd_chg_pct") is not None:
        add(tail, f"YTD slaughter {wk['ytd_chg_pct']}% YoY")
    bp = sl.get("beef_production") or {}
    if bp.get("ytd_chg_pct") is not None:
        add(tail, f"YTD beef production {bp['ytd_chg_pct']}% YoY")

    if kind == "friday":
        rc = (ctx.get("regional_cash") or {}).get("regions") or {}
        for name, r in rc.items():
            if r.get("undefined"):
                add(tail, f"{name}: no adequate market test (prints as Undefined)")
            else:
                add(tail, 
                    f"{name}: live {r.get('live_low')}-{r.get('live_high')}, "
                    f"dressed {r.get('dressed_low')}-{r.get('dressed_high')}, {r.get('head')} hd")
        cf = ctx.get("cof") or {}
        if cf.get("include"):
            add("cof_note", 
                f"actual {cf.get('actual')} | guesses {cf.get('guesses') or 'none entered'} "
                f"| year-ago {cf.get('year_ago')}")

    d = ctx.get("douglas") or {}
    if d.get("head") is not None:
        add(tail, f"YTD Douglas feeder imports {d['head']:,} head ({d.get('year')})")
    cash = (ctx.get("cash") or {}).get("live", {})
    if cash.get("this_week") is not None and cash.get("last_week") is not None:
        add(tail, 
            f"live cash {cash['this_week']} vs {cash['last_week']} "
            f"({cash['this_week'] - cash['last_week']:+.2f} week on week)")
    return out


def chart_movers(ctx: dict) -> dict:
    """
    {pool key: fractional move} for the day, so the picker can ask what actually
    moved when the commentary is not steering.

    AS A FRACTION OF PRICE, not in points. Corn moving 8 cents and the S&P
    moving 40 are not comparable in points and are perfectly comparable as
    percentages -- which is the only reason one number can rank five markets.
    """
    out = {}
    for key, rows in (("live", ctx.get("live_cattle")), ("feeders", ctx.get("feeder_cattle"))):
        for c in (rows or [])[:1]:
            chg, px = c.get("change_day"), c.get("settle")
            if chg is not None and px:
                out[key] = float(chg) / float(px)
    by_code = {"ZC": "corn", "ES": "sp", "CL": "crude"}
    for m in ctx.get("outside") or []:
        key = by_code.get(m.get("code"))
        chg, px = m.get("change"), m.get("price")
        if key and chg is not None and px:
            out[key] = float(chg) / float(px)
    return out


def build_chart(ctx: dict, issue: date, api_key: str, errors: list,
                forced: str = "", candidates: list = None) -> dict:
    """
    Choose the morning's chart and fetch its series.

    Falls forward, not over: if the chosen market's history does not come back,
    the next one in the rotation is tried rather than leaving a hole where a
    chart was meant to be. A letter with the second-choice chart is better than
    a letter with a gap, and neither is worth failing the build over.
    """
    if not api_key:
        return {}
    text = " ".join(" ".join(v) for v in (ctx.get("commentary") or {}).values()
                    if isinstance(v, list))
    # candidates are passed in ONLY when the caller already has them -- the panel
    # on the authoring page. Fetching them here would put several HTTP calls
    # behind every build for a chart choice. See chart.pick.
    entry, why = chart.pick(issue, text, candidates, chart_movers(ctx))
    if forced:
        entry = next((e for e in config.CHART_POOL if e["key"] == forced), entry)
        why = "chosen by hand"

    order = [entry] + [e for e in config.CHART_POOL if e["key"] != entry["key"]]
    for candidate in order:
        # TWO KINDS OF ENTRY NOW. A futures entry carries a CME product code
        # and goes through fetch_front_history as it always has. A `series`
        # entry names a sources function that returns a finished chart dict --
        # its own dates, values and title -- because a cutout premium is not a
        # front-month curve and pretending otherwise would put the framing in
        # here rather than beside the data it describes.
        #
        # The fall-forward is deliberately unchanged and covers both: a series
        # that does not come back is skipped exactly like a futures one, and a
        # letter with the second-choice chart still beats a letter with a hole.
        try:
            if candidate.get("series"):
                got = getattr(sources, candidate["series"])()
                title = got.get("title") if got else None
            else:
                got = sources.fetch_front_history(candidate["code"], api_key, issue,
                                                  config.CHART_SESSIONS,
                                                  completed_only=True)
                title = (f"{got['month']} {candidate['label']} "
                         f"— {got['sessions']} sessions") if got else None
        except Exception as e:                      # noqa: BLE001
            errors.append(f"chart ({candidate['key']}): {type(e).__name__}: {e}")
            continue
        if got:
            if candidate is not entry:
                why += f" (fell back from {entry['key']}: no series)"
            return {"key": candidate["key"],
                    "title": title,
                    "style": got.get("style", candidate["style"]),
                    "reason": why,
                    "dates": got["dates"], "values": got["values"]}
    errors.append("chart: no series available for any market in the pool")
    return {}


def _jsonable(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the Tuesday or Friday cattle letter.")
    ap.add_argument("--date", help="issue date, YYYY-MM-DD (default: today)")
    ap.add_argument("--no-fetch", action="store_true",
                    help="re-render from the last fetch -- use after editing commentary")
    ap.add_argument("--html-only", action="store_true", help="skip the PDF step")
    ap.add_argument("--chart", default="",
                    help="force the morning chart: feeders, live, corn, sp or crude. "
                         "Default picks from what you wrote, then what moved.")
    ap.add_argument("--archive", action="store_true",
                    help="copy this letter into the private archive repo, commit and "
                         "push. Use it for the letter you actually sent, not a draft.")
    ap.add_argument("--out", default=str(OUT), help="output directory")
    ap.add_argument("--session", choices=[x.lower() for x in config.SESSIONS],
                    default=config.DEFAULT_SESSION.lower(),
                    help="which of the day's two reports (default: pm)")
    ap.add_argument("--day", choices=[d.lower() for d in config.DAYS], default=None,
                    help="which weekday's letter (default: today, or Monday at a weekend). "
                         "Friday uses the week-in-review format; every other day uses "
                         "the standard one.")
    ap.add_argument("--kind", choices=["tuesday", "recap", "friday"], default=None,
                    help=argparse.SUPPRESS)   # kept so older commands still run
    ap.add_argument("--friday", action="store_true", help="shorthand for --day friday")
    ap.add_argument("--week-base", default="",
                    help="prior-Friday settles when the futures history has a hole, "
                         "e.g. LEV6=215.925,GFV6=323.50. Keyed by ticker; persists "
                         "to out/weekbase_<kind>_<date>.json for later re-renders.")
    ap.add_argument("--settle", default="",
                    help="official settles for a session the feed cannot supply, e.g. "
                         "GFV6=334.925,LEV6=218.875 or GFV6=334.925@2026-09-25. Banked "
                         "to the settle log, so they persist, reach the deployed app "
                         "and restore the daily change. Defaults to the last weekday "
                         "before the issue date. Cannot override a real settlement.")
    ap.add_argument("--cof-guess", default="",
                    help="analyst pre-report estimates for the Cattle on Feed table, "
                         "e.g. on_feed=101.8,placed=96.8,marketed=96.1. USDA does not "
                         "publish these and nothing can derive them.")
    args = ap.parse_args(argv)

    # The issue date has to be resolved FIRST: with no --day, the weekday is
    # derived from it.
    issue = date.fromisoformat(args.date) if args.date else date.today()

    # day = what you picked; fmt = which of the two layouts it produces.
    if args.friday:
        day = "friday"
    elif args.day:
        day = args.day
    elif args.kind:
        day = args.kind          # legacy --kind tuesday|friday
    else:
        day = config.day_for_date(issue)
    fmt = config.format_for(day, args.session)
    kind = fmt                   # render/commentary still switch on the format
    session = args.session
    # AM and PM are separate letters on the same day, so every artefact is
    # keyed by both -- a shared name would have the morning letter overwrite
    # the evening one and neither would say so.
    slug = f"{session}_{day}"

    week_base_cli = {}
    for pair in args.week_base.split(","):
        if "=" in pair:
            k, _, v = pair.partition("=")
            try:
                week_base_cli[k.strip().upper()] = float(v)
            except ValueError:
                pass

    cof_guesses = {}
    for pair in args.cof_guess.split(","):
        if "=" in pair:
            k, _, v = pair.partition("=")
            try:
                cof_guesses[k.strip()] = float(v)
            except ValueError:
                pass

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / f"data_{slug}_{issue}.json"

    load_env()
    errors: list = []

    # BEFORE gather(), deliberately. A banked settle is read by
    # sources.fetch_futures as a recovery tier, so entering it first means the
    # normal fetch does the work -- including recomputing the daily change off
    # two settlements instead of leaving it marked. Applying it afterwards
    # would mean reimplementing that arithmetic here, badly.
    if args.settle:
        default_day = issue - timedelta(days=1)
        while default_day.weekday() >= 5:
            default_day -= timedelta(days=1)
        banked: dict = {}
        for pair in args.settle.split(","):
            if "=" not in pair:
                continue
            k, _, v = pair.partition("=")
            when = default_day
            if "@" in v:
                v, _, stamp = v.partition("@")
                try:
                    when = date.fromisoformat(stamp.strip())
                except ValueError:
                    print(f"  ignoring {pair}: '{stamp.strip()}' is not a date")
                    continue
            try:
                banked.setdefault(when, {})[k.strip().upper()] = float(v)
            except ValueError:
                print(f"  ignoring {pair}: '{v}' is not a number")
        for when, values in sorted(banked.items()):
            n = settle_log.bank(values, when, source="cli")
            print(f"banked {n} settle(s) for {when}: "
                  + ", ".join(f"{t}={x}" for t, x in sorted(values.items())))

    if args.no_fetch:
        if not data_path.exists():
            print(f"no saved data at {data_path} -- run once without --no-fetch first")
            return 2
        ctx = json.loads(data_path.read_text(encoding="utf-8"))
        ctx["issue_date"] = issue
        ctx["kind"] = kind
        ctx["session"] = session
        print(f"reusing {data_path.name}")
        # THE RE-RENDER IS THE RUN THAT MAKES THE PDF THAT GETS EMAILED, and
        # it never calls gather(), so the warning raised on the fetching run
        # would be absent from the one that actually produces the letter.
        # report_futures_health only reads the ctx, so a cached ctx answers it
        # just as well.
        report_futures_health(ctx, issue, errors)
        report_source_health(ctx, issue, kind, errors)
    else:
        print(f"fetching {session.upper()} {day} letter for {issue} ({fmt} format) ...")
        ctx = gather(issue, errors, kind, cof_guesses)
        ctx["session"] = session
        # Chain to the previous letter before caching, so the recovered change
        # is what --no-fetch re-renders from too.
        settle_log.record(ctx)
        recovered = backfill_week_base(ctx, out_dir, issue)
        if recovered:
            print(f"  recovered the weekly change from the previous letter: {', '.join(recovered)}")
        data_path.write_text(json.dumps(ctx, indent=2, default=_jsonable), encoding="utf-8")
        print(f"wrote {data_path.name}")

    # Hand-entered prior-Friday settles: merge anything new from the CLI into
    # the saved file, then apply. Applied on BOTH paths so a --no-fetch
    # re-render keeps the correction.
    wb_path = week_base_path(out_dir, issue, day)
    # Same trip the commentary makes below, and for the same reason: these are
    # typed by hand and out/ does not survive a reboot. Restoring cannot
    # overwrite real data -- apply_week_base only fills a contract that has no
    # base at all -- so it is safe to do unconditionally.
    wb_restored = draft_store.restore(wb_path, prior_friday_of(issue),
                                      draft_store.WEEK_BASE_KIND,
                                      label="Prior-Friday settles")
    if wb_restored:
        print(f"  {wb_restored}")
    week_base = load_week_base(wb_path)
    if week_base_cli:
        week_base.update(week_base_cli)
        save_week_base(wb_path, week_base)
        wb_err = draft_store.backup(wb_path, prior_friday_of(issue),
                                    draft_store.WEEK_BASE_KIND, "cli")
        if wb_err:
            print(f"  {wb_err}")
    filled = apply_week_base(ctx, week_base)
    if filled:
        print(f"  weekly change from entered prior-Friday settles: {', '.join(filled)}")

    # The commentary file is created once and never overwritten -- it holds your draft.
    cpath = commentary.path_for(out_dir, issue, slug)
    # Pull down anything typed on the deployed page before deciding the file is
    # empty. Without this the CLI and the page each kept their own draft and
    # whichever you were not looking at was invisible.
    restored = draft_store.restore(
        cpath, issue, slug,
        has_content=lambda b: commentary.has_content(b, kind))
    if restored:
        print(f"  {restored}")
    existed = cpath.exists()
    commentary.write_template(cpath, hints(ctx, kind), kind)
    ctx["commentary"] = commentary.read(cpath, kind)

    # FROM THE FORMAT, NOT THE CACHE. data_<slug>_<date>.json stores whatever
    # basis was in force when it was fetched, so a file written before
    # 2026-09-24 says "week" for every letter. A --no-fetch re-render would
    # quote week-over-week on a Monday and print [[?]] for it.
    ctx["change_basis"] = config.change_basis_for(kind)

    # FROM THE CACHE, unlike the basis above, because this one IS a choice --
    # which month Ross decided to write about. A --no-fetch re-render must
    # reproduce the letter he just previewed, so the stored month is honoured
    # and only falls back to the front contract when it is missing.
    select_technicals(ctx)

    # AFTER the commentary is read, because the commentary is the best evidence
    # of what the morning is about -- see chart.pick. Re-picked on a --no-fetch
    # re-render too, so editing the headlines re-aims the chart.
    if kind == "am":
        ctx["chart"] = build_chart(ctx, issue, os.environ.get("MASSIVE_API_KEY", "").strip(),
                                   errors, forced=getattr(args, "chart", "") or "")

    html = render.build_html(ctx)
    html_path = out_dir / f"{config.title_for(session)} {day.title()} {issue}.html"
    html_path.write_text(html, encoding="utf-8")

    pdf_msg = ""
    pdf_path = None
    if not args.html_only:
        pdf_path = out_dir / f"{config.title_for(session)} {day.title()} {issue}.pdf"
        ok, msg = topdf.html_to_pdf(html_path, pdf_path)
        pdf_msg = f"PDF: {msg}" if ok else f"PDF NOT written -- {msg}"
        if not ok:
            pdf_path = None

    # -- Archive, only when asked ------------------------------------------
    # OPT-IN, because "published" means Ross sent it and only he knows when.
    # Archiving every build would commit a dozen drafts a day and bury the one
    # that went out. See letter/archive.py.
    archive_msg = ""
    if getattr(args, "archive", False):
        result = archive.publish(issue, session, html_path, pdf_path,
                                 kind=kind, title=config.title_for(session))
        if not result["ok"]:
            archive_msg = f"ARCHIVE FAILED -- {result['reason']}"
        elif not result["changed"]:
            archive_msg = "Archive: already held this letter, unchanged."
        else:
            where = "pushed" if result["pushed"] else "committed locally"
            archive_msg = f"Archive: {len(result['files'])} file(s) {where}."
            if result["reason"]:
                archive_msg += f" {result['reason']}"

    # -- Report -------------------------------------------------------------
    missing = html.count(render.MISSING)
    print()
    print(f"HTML: {html_path}")
    if pdf_msg:
        print(pdf_msg)
    if archive_msg:
        print(archive_msg)
    if not existed:
        print(f"\nCommentary file created: {cpath}")
        titles = " / ".join(t for _, t in commentary.sections_for(kind))
        print(f"  Write your {titles} into it,")
        print("  then re-run with --no-fetch to render the final letter.")
    elif commentary.is_empty(ctx["commentary"]):
        print(f"\nCommentary file is still empty: {cpath}")

    if missing:
        print(f"\n{missing} value(s) could not be filled and are marked [[?]] in the letter.")
    for e in errors:
        print(f"  ! {e}")

    inferred = (ctx.get("calendar") or {}).get("inferred") or []
    if inferred:
        print(f"\n  ! WASDE dates are INFERRED from Crop Production's release slot: "
              f"{', '.join(inferred)}.")
        print("    ESMIS returns no upcoming_releases for WASDE. The paired date is right")
        print("    when it appears, but WASDE months with no Crop Production (roughly")
        print("    Dec-Apr) will not show at all.")

    # THE CONDITIONAL FRESHNESS CHECKS MOVED OUT OF HERE on 2026-09-28, into
    # build.report_source_health, so they reach the Streamlit authoring page
    # through the errors list rather than a terminal Ross never looks at. What
    # is left below is context that is ALWAYS true -- the carcass-weight lag,
    # the feeder index being JSA's own estimate, the COF block's composition.
    # Those are not problems and must not be warnings, or the panel becomes
    # noise and stops being read on the morning it matters.
    cw = ctx.get("carcass_weights") or {}
    if cw.get("week_ending"):
        print(f"\n  Carcass weights are for the week ending {cw['week_ending']} "
              "(AMS 3658, published Thursdays, ~12 days in arrears).")

    if kind == "friday":
        cf = ctx.get("cof") or {}
        if cf.get("include"):
            print(f"\n  COF block INCLUDED ({cf.get('title')}, "
                  f"released {cf.get('release_date')}).")
            if not cf.get("guesses"):
                print("    No analyst guesses given -- that column prints as dashes.")
                print("    Pass --cof-guess on_feed=...,placed=...,marketed=... to fill it.")
            print("    NOTE On-Feed and Year-Ago are COMPUTED (100.7 / 98.9 for Sept 2026),")
            print("    not the old Excel sheet's 100.8 / 99. See letter/cof.py.")
        elif cf.get("reason"):
            print(f"\n  COF block omitted: {cf['reason']}")

    fci = ctx.get("fci") or {}
    if config.INCLUDE_FEEDER_INDEX and fci.get("value") is not None:
        print(f"\n  Feeder index {fci['value']} is JSA's own estimate for {fci.get('date')} "
              "(fci_daily), not CME's published value.")
        if fci.get("cme_last_published"):
            print(f"    Headline date follows CME's publication clock; their last file is "
                  f"{fci['cme_last_published']}. If that stops advancing, suspect the CME")
            print("    ingest rather than this letter.")

    return 1 if (missing or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
