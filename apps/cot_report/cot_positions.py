"""
CFTC Commitments of Traders -- Managed Money in the cattle futures.

WHAT THIS ANSWERS. Every Friday the CFTC publishes where the speculative funds
were positioned the previous Tuesday. For a cattle market the number that gets
quoted is MANAGED MONEY NET -- the funds' long contracts less their short
contracts -- in Live Cattle and in Feeder Cattle. That is the figure this
module returns and the figure the page leads with.

READ FROM SNOWFLAKE, NOT FROM CFTC. `JSA.CFTC_COT` is loaded by the droplet
job in JSA-Dashboards/cftc-cot-etl, Fridays at 3pm CT with a Monday catch-up,
and it re-pulls the last eight weeks each run so CFTC's own revisions land.
That buys three things the public API does not: history back to 2006 for the
disaggregated report and 1986 for the legacy one in a single query, no rate
limit on a page a dozen people may open at once, and the pre-1998 market codes
already joined and converted to contracts.

=============================================================================
THE LETTER ALREADY PRINTS THESE TWO NUMBERS, AND THE TWO MUST NEVER DISAGREE
=============================================================================

`letter/render.cftc_block()` renders "CFTC Report as of M/D/YY -- Managed Money
Traders (Futures Only)" on the Friday letter, with Net Long and WoW Change for
both cattle contracts. It is fed by `letter/sources.fetch_cftc()`, which hits
the LIVE CFTC Socrata dataset `publicreporting.cftc.gov/resource/72hh-3qpy`
rather than Snowflake.

So this page is the fourth JSA surface to quote a figure another surface
already publishes, and CLAUDE.md records three separate mornings lost to
exactly that -- two numbers, both defensible, neither raising. It was checked
BEFORE this module was written rather than after:

    120 rows compared (60 weeks x 2 markets, 2025-08-12 .. 2026-09-29)
    net mismatches 0 | long 0 | short 0 | week-over-week 0

To the contract, on every row. Which it has to be, because they are the same
CFTC publication arriving by two routes. What makes them agree is that this
module makes the same three choices `sources.fetch_cftc` makes, and each one
is load-bearing:

  * REPORT_TYPE = 'FUT'. Futures only, never futures-and-options COMBINED.
    `sources.py` records that the combined set gives Live Cattle 45,262 for
    the 9/18/26 letter where futures-only gives 47,696 -- both plausible
    cattle numbers, which is why a wrong choice there fails silently. Over
    the full 1,060 weeks the two bases differ by a mean 3,038 contracts in
    Live Cattle and run as far apart as 21,603.
  * The DISAGGREGATED report, never the legacy one. Legacy "Non-Commercial"
    is not Managed Money -- it also carries the other reportables, and for
    the 9/18/26 letter it flips Feeder Cattle to a NET SHORT of 3,853, which
    inverts the market read.
  * Net is LONG minus SHORT, with MM_SPREAD excluded. See SPREADING below.

If the two surfaces are ever seen to disagree, the cause is almost certainly
the release-window race described under `is_current()`, not the arithmetic.

=============================================================================
TWO FREE AUDITS, BOTH CHECKED ON EVERY LOAD
=============================================================================

A net, a share and a weekly change are all numbers between plausible bounds
whether or not they are right, so nothing here would fail loudly on its own.
Both identities below hold EXACTLY over the whole cattle history, so a
tolerance would only hide a fault:

  1. MM_NET = MM_LONG - MM_SHORT. Zero violations in 4,240 cattle rows across
     both report types.
  2. CFTC's own published change columns reproduce the week-over-week diff of
     the levels: MM_LONG_CHG equals the diff of MM_LONG across all 1,037
     adjacent-week pairs in both cattle markets, and the same for shorts.
     NOTE THAT THIS HOLDS ONLY ON 'FUT'. On 'COMBINED' the long leg alone fails
     on 198 feeder and 283 live weeks, and the NET change -- two rounded figures
     differenced, so the errors compound -- fails on 361 and 437. Every single
     one of those errors is one contract, or two on the net. One more reason the
     headline basis is futures-only.

The open-interest identity -- every category's longs plus the spread columns
summing to open interest -- is NOT exact: it runs up to 3 contracts out, on
both sides, which is CFTC's own residual in the non-reportable column. It is
therefore a tolerance check (`OI_TOLERANCE`) and a warning rather than a
refusal, because the headline figure does not depend on it balancing.

=============================================================================
THINGS THAT LOOK WRONG AND ARE NOT
=============================================================================

SPREADING IS EXCLUDED FROM NET, AND IT IS LARGE. Feeder Cattle on 2026-09-29:
17,364 long, 9,198 short, and 10,252 SPREAD -- a spread position being equal
and offsetting long and short legs held by the same trader, which CFTC counts
once in its own column rather than in both of the others. It nets to zero by
construction, so folding it into "net" would be adding zero contracts with a
label on them. It is still worth showing, because a market where the funds'
spread position is larger than their net tells a reader the directional bet is
smaller than the gross figures suggest.

THE NEWEST FIGURE IS ALWAYS AT LEAST THREE DAYS OLD, AND USUALLY MORE. The
positions are as of a TUESDAY and are not published until the FRIDAY. By the
following Thursday the newest available reading describes a market nine days
gone. A COT number read as a current position is the commonest way this report
is misused, so `as_of` is never inferred from the calendar -- it is read off
the same rows as the figures, the way `render.cftc_block` learned to after the
9/18/26 letter was headed with the wrong week's date.

THERE ARE NO MISSING WEEKS, BUT THERE ARE MONDAYS. Every step in the cattle
series is 6, 7 or 8 days: 1,037 of 1,059 are exactly 7, and the 22 others are
6/8 pairs around a federal holiday, where the Tuesday report date slips back
to the Monday. So a gap check must not demand 7 days, and `is_current()`
allows the newest report date to be one day early for that reason.

NET AS A COUNT OF CONTRACTS IS NOT COMPARABLE ACROSS TWENTY YEARS. Feeder
Cattle open interest has roughly doubled -- a 29,617 average over 2006-2010
against 59,722 over 2022-2026 -- so a 20,000 net in 2008 was a far bigger bet
on the same market than a 20,000 net now. `context()` therefore returns the
net as a share of open interest alongside the raw percentile, and the page
leads the long-history comparison with the share.

FEEDER CATTLE GOES NET SHORT AND LIVE CATTLE ESSENTIALLY DOES NOT. Managed
money has been net short feeders in 248 of 1,060 weeks (23.4%) and net short
live cattle in 15 (1.4%). Nothing here may assume the net is positive: the
sign is carried by a WORD -- "long" or "short" -- rather than by a leading
minus or, far worse, by parentheses, which in CFTC's and USDA's own reports
mean NEGATIVE. That is the trap `letter/sterling.py` and
`apps/beef_cutout/am_cutout.py` both document.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

APPS = Path(__file__).resolve().parent.parent

# PASSED INTO THE PAGE'S CACHED FETCH PURELY AS PART OF THE CACHE KEY.
# `st.cache_data` keys on the decorated function's own code and arguments and
# NEVER on the modules it calls, so adding a key to what `load()` returns
# leaves the page serving a dict from before that key existed and the tile
# that reads it renders an em dash with nothing raising. The identical trap is
# recorded against `leverage.SCHEMA` and `am_cutout.SCHEMA` in CLAUDE.md.
# BUMP THIS whenever load(), context(), why() or decompose() change the SHAPE
# of what they return.
#
# 3 -- `load()` gained `legacy`, `cross_audit` and a per-market
#      `reconciliation` block.
# 2 -- `why()` gained an `agree` key. THE TRAP FIRED DURING DEVELOPMENT, which
# is worth recording because it is the cheapest demonstration of why the
# constant exists: the page read `W.get("agree")`, the cached dict predated the
# key, `.get` returned None, and the hero tile silently took the wrong branch
# and printed the wrong sentence. The page did not raise, the server had been
# restarted, and `persist="disk"` meant the stale dict outlived the process.
SCHEMA = 3

VIEW = "JSA.CFTC_COT.COT_DISAGG"

# Read ONLY for the reconciliation panel, never for a headline and never for a
# chart. See `reconciliation()` for what it is for and `LEGACY_IS_NOT_A_HISTORY`
# for the two reasons it must not be charted.
LEGACY_VIEW = "JSA.CFTC_COT.COT_LEGACY"

# Futures only. See the module docstring: this is what the Friday letter prints
# and what the trade means by "net futures position". COMBINED is fetched too,
# but only so the page can show a reader what the other basis says rather than
# leaving them to wonder why a number they saw elsewhere differs.
FUT = "FUT"
COMBINED = "COMBINED"

# The two markets the page exists for, in the order they are shown. Live Cattle
# first: it is much the larger market and the one the fed cattle trade watches.
CATTLE = ("LIVE_CATTLE", "FEEDER_CATTLE")

LABELS = {
    "LIVE_CATTLE":   "Live Cattle",
    "FEEDER_CATTLE": "Feeder Cattle",
    "LEAN_HOGS":     "Lean Hogs",
    "CORN":          "Corn",
    "SOYBEAN_MEAL":  "Soybean Meal",
}

# Shown underneath the cattle as context rather than as subject. Lean hogs is
# the third livestock market; corn and meal are the feeder's input cost, and a
# fund position in them moves a cattle feeding margin as surely as one in the
# cattle themselves. They cost nothing extra -- same query, three more
# SERIES values.
NEIGHBOURS = ("LEAN_HOGS", "CORN", "SOYBEAN_MEAL")

# The disaggregated report's five trader categories. Their nets sum to zero by
# construction -- every long is somebody's short -- which `reconciles()` uses
# as a third audit. Order is CFTC's own, from the commercial end down to the
# smallest traders.
CATEGORIES = (
    ("prod_merc", "Producers, merchants, processors, end users"),
    ("swap",      "Swap dealers"),
    ("mm",        "Managed money"),
    ("other",     "Other reportables"),
    ("nonrept",   "Non-reportable (small traders)"),
)

# ZERO, AND THAT IS NOT AN OVERSIGHT -- it is the measurement.
#
# On the futures-only basis every identity in this report is EXACT. The five
# categories' longs plus the three spread columns equal open interest in all
# 2,120 cattle FUT rows; so do the shorts; and the five nets sum to zero. The
# residual is not small, it is 0, on every row of every week since 2006. A
# tolerance would therefore only ever hide a fault, so a FUT row that fails is
# treated as corrupt rather than as rounded.
#
# THE COMBINED BASIS IS A DIFFERENT MATTER and this constant is deliberately
# not applied to it: there the residual runs -3..+2 on about half the rows,
# spread evenly over all 21 years. That asymmetry has the same single cause as
# the change-column mismatch in the module docstring -- futures-and-options
# combined positions are options converted to futures equivalents on a delta
# basis and then ROUNDED to whole contracts, independently per category.
# Independent rounding is exactly what breaks a sum by a contract or two and
# what stops a published change column reproducing the diff of two rounded
# levels; every one of the 481 cattle change mismatches is exactly one
# contract, never more. Both anomalies are confined to COMBINED and neither
# touches FUT, which is a third reason the headline basis is futures-only.
OI_TOLERANCE = 0

# How far the newest report date may sit behind the one the release calendar
# implies before the page says so. One day covers the holiday weeks where the
# Tuesday report date slips back to a Monday; anything more is a real lag.
AS_OF_SLACK_DAYS = 1

# WHEN A READER OF *THIS PAGE* CAN EXPECT THE NEW WEEK, which is not when CFTC
# publishes it.
#
# CFTC releases at 3:30pm ET = 2:30pm Central. The ETL that fills Snowflake runs
# at 3pm CT. So this page cannot have the new report before 3pm however healthy
# everything is, and between 2:30 and 3:00 the Friday letter -- which reads the
# live CFTC API -- legitimately has a figure this page does not. That half hour
# is the one window in which the two JSA surfaces differ for a good reason, and
# it is worth knowing about before somebody reports it as a bug.
#
# 4pm rather than 3pm, to leave the ETL an hour to finish. Pinning this to the
# job's own start time would make the page cry stale for however long the run
# takes, every Friday afternoon -- a banner that fires every week is one nobody
# reads on the week it matters.
RELEASE_HOUR_CT = 16
RELEASE_MINUTE_CT = 0

# TWO THRESHOLDS, BECAUSE BEING WRONG COSTS DIFFERENT AMOUNTS EITHER SIDE.
#
#   ETL_HOUR_CT (3pm)      when to go and LOOK for the new week. The droplet
#                          job fills Snowflake at 3pm CT, so this is the first
#                          moment the new report can be there. Being early
#                          costs one SELECT that returns the same rows.
#   RELEASE_HOUR_CT (4pm)  when to SAY SO on the page. An hour of grace for the
#                          job to finish, because a banner that fires every
#                          Friday afternoon while the cron runs is one nobody
#                          reads on the Friday it matters.
#
# A single threshold has to pick one of those jobs and do the other badly.
ETL_HOUR_CT = 15

_SELECT = """
    REPORT_DATE, OPEN_INTEREST, OPEN_INTEREST_CHG,
    MM_LONG, MM_SHORT, MM_SPREAD, MM_NET, MM_LONG_CHG, MM_SHORT_CHG,
    MM_LONG_TRADERS, MM_SHORT_TRADERS, TRADERS_TOTAL,
    PROD_MERC_LONG, PROD_MERC_SHORT, PROD_MERC_NET,
    SWAP_LONG, SWAP_SHORT, SWAP_SPREAD, SWAP_NET,
    OTHER_LONG, OTHER_SHORT, OTHER_SPREAD, OTHER_NET,
    NONREPT_LONG, NONREPT_SHORT, NONREPT_NET
"""


# -- reaching Snowflake ------------------------------------------------------

def enabled() -> bool:
    """Snowflake is configured. The same flag the rest of the portal uses."""
    return os.getenv("USE_SNOWFLAKE", "").strip().lower() in ("1", "true", "yes", "on")


def _load_db():
    """
    apps/cme_feeder_cattle/snowflake_db.py, under a PRIVATE module name.

    The trick `draft_store._load_db()`, `sources._load_fci_db()` and
    `am_cutout._load_db()` all use, for the same reason: snowflake_db.py exists
    five times in this repo and Python caches modules by NAME, so a plain
    `import snowflake_db` binds whichever page happened to load first. "_cot_db"
    can never join that collision.

    NOTE WHAT IS *NOT* HERE: this module never reads SNOWFLAKE_SCHEMA. Every
    statement names JSA.CFTC_COT in full, so it takes no part in the nine-module
    collision CLAUDE.md documents, and the connection's own default schema --
    whatever page set it -- cannot affect what these queries return.
    """
    path = APPS / "cme_feeder_cattle" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_cot_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cot_db"] = mod
    spec.loader.exec_module(mod)
    return mod


_CONN = None


def _conn():
    global _CONN
    if _CONN is None:
        _CONN = _load_db().get_conn()
    return _CONN


def _drop_conn():
    global _CONN
    try:
        if _CONN is not None:
            _CONN.close()
    except Exception:  # noqa: BLE001
        pass
    _CONN = None


def _read(sql: str) -> pd.DataFrame:
    """
    One query, retried once on a dropped connection.

    Streamlit keeps a process alive for hours between visitors and Snowflake
    will have closed the session long before the next one arrives, so the first
    query of the morning fails on a connection that looked perfectly healthy.
    """
    db = _load_db()
    try:
        return db.read_sql_lower(sql, _conn())
    except Exception:  # noqa: BLE001
        _drop_conn()
        return db.read_sql_lower(sql, _conn())


def _quoted(names) -> str:
    return ", ".join("'" + str(n).replace("'", "''") + "'" for n in names)


# -- fetching ----------------------------------------------------------------

def fetch(series=CATTLE, report_type: str = FUT) -> pd.DataFrame:
    """
    Full weekly history for `series`, oldest first.

    NO DATE WINDOW, DELIBERATELY. The whole disaggregated cattle history is
    1,060 rows per market -- five markets is a few hundred kilobytes and one
    round trip, and the page's percentile and record tiles need all of it.
    Windowing would buy nothing measurable and would quietly change what
    "record high" means, which is the silent narrowing CLAUDE.md records
    against the cash forecast's analogue pool.
    """
    sql = (f"SELECT SERIES AS series, {_SELECT} FROM {VIEW} "
           f"WHERE REPORT_TYPE = '{report_type}' "
           f"AND SERIES IN ({_quoted(series)}) "
           f"ORDER BY SERIES, REPORT_DATE")
    df = _read(sql)
    if df.empty:
        return df
    df["report_date"] = pd.to_datetime(df["report_date"])
    num = [c for c in df.columns if c not in ("series", "report_date")]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    return df.reset_index(drop=True)


def market(df: pd.DataFrame, series: str) -> pd.DataFrame:
    """One market's rows, oldest first, index reset."""
    if df is None or df.empty or "series" not in df:
        return pd.DataFrame()
    return (df[df["series"] == series]
            .sort_values("report_date")
            .reset_index(drop=True))


# -- the audits --------------------------------------------------------------

def reconciles(df: pd.DataFrame) -> dict:
    """
    The three identities, as a dict the page can print.

    `net_ok` is the one that matters and it is EXACT -- MM_NET must equal
    MM_LONG - MM_SHORT on every row, with no tolerance, because it holds with
    no tolerance across the whole history. Slack here would only hide a fault.

    `chg_ok` checks CFTC's own published change columns against the diff of the
    levels, on adjacent weeks only. It is what lets the page say that the
    week-over-week figure on the headline tile is CFTC's own arithmetic rather
    than something this module invented.

    `oi_ok` is the open-interest identity, and it is the one that needs slack:
    CFTC's non-reportable residual leaves it up to 3 contracts out. Reported so
    the page can warn, never so it can refuse.
    """
    out = {"rows": 0, "net_ok": None, "chg_ok": None, "oi_ok": None,
           "net_bad": 0, "chg_bad": 0, "oi_worst": 0.0}
    if df is None or df.empty:
        return out
    out["rows"] = int(len(df))

    bad_net = int((df["mm_net"] != df["mm_long"] - df["mm_short"]).sum())
    out["net_bad"] = bad_net
    out["net_ok"] = bad_net == 0

    bad_chg, worst = 0, 0.0
    for _, g in df.groupby("series"):
        g = g.sort_values("report_date")
        adjacent = g["report_date"].diff().dt.days.between(6, 8)
        for level, published in (("mm_long", "mm_long_chg"),
                                 ("mm_short", "mm_short_chg")):
            bad_chg += int(((g[level].diff() != g[published]) & adjacent).sum())
        longs = (g["prod_merc_long"] + g["swap_long"] + g["swap_spread"]
                 + g["mm_long"] + g["mm_spread"] + g["other_long"]
                 + g["other_spread"] + g["nonrept_long"])
        worst = max(worst, float((longs - g["open_interest"]).abs().max()))
    out["chg_bad"] = bad_chg
    out["chg_ok"] = bad_chg == 0
    out["oi_worst"] = worst
    out["oi_ok"] = worst <= OI_TOLERANCE
    return out


# -- the release calendar ----------------------------------------------------

def _now_ct() -> datetime:
    """
    Central time, because that is the clock both CFTC's release and the ETL run
    are most naturally read on. Falls back to naive local time where the tz
    database is missing rather than failing -- the only consequence is a few
    hours' error in the staleness message, on one day of the week.
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return datetime.now()


def expected_as_of(now: datetime | None = None, hour: int = RELEASE_HOUR_CT) -> date:
    """
    The Tuesday of the newest report that should be on file by `now`.

    The cycle: positions are taken at Tuesday's close and published the FRIDAY
    of the same week. So the newest report that exists is the Tuesday of the
    most recent week whose release has passed.

    WORKED THROUGH, because an off-by-one here gives a page that cries stale
    every Friday lunchtime or one that never cries stale at all:

        Wed 10/07 14:00  -> last release Fri 10/02  -> expect Tue 09/29
        Fri 10/09 13:00  -> release not yet made    -> expect Tue 09/29
        Fri 10/09 16:00  -> release made at 15:00   -> expect Tue 10/06
        Sat 10/10 09:00  -> last release Fri 10/09  -> expect Tue 10/06

    `hour` defaults to the ALARM threshold. Pass ETL_HOUR_CT to get the fetch
    threshold instead -- see `data_epoch()` and the note on the two constants.

    Holiday weeks shift the REPORT date back to the Monday rather than forward,
    which is why `is_current()` compares with a day of slack instead of
    demanding equality.
    """
    now = now or _now_ct()
    today = now.date()
    # Most recent Friday on or before today. weekday(): Mon=0 .. Fri=4 .. Sun=6.
    friday = today - timedelta(days=(today.weekday() - 4) % 7)
    if friday == today and (now.hour, now.minute) < (hour, RELEASE_MINUTE_CT):
        friday -= timedelta(days=7)
    return friday - timedelta(days=3)      # that week's Tuesday


def data_epoch(now: datetime | None = None) -> date:
    """
    A value that changes exactly when new data should exist, for use as a CACHE
    KEY -- not as a claim about what is on file.

    WHY THE PAGE NEEDS THIS AT ALL. CFTC publishes at 2:30pm CT on a Friday and
    the ETL loads Snowflake at 3pm, but a cached page does not notice either
    event: `st.cache_data` re-runs when its TTL expires, which is a stopwatch
    started by whoever happened to open the page last. With an hour's TTL a
    reader could be served Tuesday-before-last's positions until 4pm on a Friday
    the new report landed at 3 -- correct-looking, correctly dated, and a week
    old. That is the staleness this file keeps warning about, arriving through
    the cache rather than through the feed.

    Keying on this instead makes the cache expire ON THE EVENT: the value rolls
    over at 3pm Friday and every viewer's next load goes back to Snowflake. The
    TTL stays on as a backstop for the case the ETL is late, where this value
    has already rolled and the data has not.
    """
    return expected_as_of(now, hour=ETL_HOUR_CT)


def _as_date(v):
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.date()
    return v


def is_current(as_of, now: datetime | None = None) -> dict:
    """
    Whether the newest row on file is the newest CFTC has published.

    "THE NEWEST BAR OF A STALE SERIES IS A PERFECTLY GOOD BAR" -- the lesson
    CLAUDE.md draws from the morning the letter printed a fortnight-old settle
    and `gather()` returned an empty error list throughout. Nothing about a COT
    row says which week it came from except its own date, so a page that simply
    shows MAX(REPORT_DATE) will go on showing a three-week-old position,
    formatted beautifully, if the ETL stops.

    Returns `current`, the `expected` Tuesday and `weeks_behind`, so the page
    can say how far behind rather than merely that it is.
    """
    expected = expected_as_of(now)
    as_of = _as_date(as_of)
    if as_of is None:
        return {"current": False, "expected": expected, "as_of": None,
                "days_behind": None, "weeks_behind": None}
    days = (expected - as_of).days
    return {
        "current": days <= AS_OF_SLACK_DAYS,
        "expected": expected,
        "as_of": as_of,
        "days_behind": days,
        "weeks_behind": max(0, int(round(days / 7.0))),
    }


def position_age_days(as_of, now: datetime | None = None) -> int | None:
    """
    How old the POSITIONS are, in days -- which is a different question from
    `is_current()` and the one a reader actually needs.

    A perfectly up-to-date COT reading still describes a Tuesday that is nine
    days gone by the time somebody opens the page on the following Thursday.
    The page prints this beside the figure so the number is never mistaken for
    a position held today.
    """
    as_of = _as_date(as_of)
    if as_of is None:
        return None
    return ((now or _now_ct()).date() - as_of).days


# -- reading one week --------------------------------------------------------

def side(net) -> str:
    """
    "long", "short" or "flat" for a net position.

    THE SIGN IS CARRIED BY THIS WORD AND NOT BY PUNCTUATION. A net short
    rendered as -9,589 is readable; rendered as (9,589) it is a POSITIVE
    number to anyone fluent in CFTC's and USDA's own reports, where
    parentheses mean negative. Managed money is net short feeder cattle in
    roughly one week in four, so this is a live case and not a theoretical one.
    """
    if net is None or pd.isna(net):
        return ""
    if net > 0:
        return "long"
    if net < 0:
        return "short"
    return "flat"


def latest(df: pd.DataFrame) -> dict:
    """
    The headline figures for one market's history: the newest week, its
    week-over-week change, and the gross legs behind the net.

    `wow` IS CFTC'S OWN ARITHMETIC, not a diff this module computed:
    MM_LONG_CHG - MM_SHORT_CHG, which is exactly what
    `letter/sources.fetch_cftc` does. The two agree with a plain diff of the
    levels on every one of the 1,037 adjacent-week pairs on the futures-only
    basis, so the choice costs nothing -- but it is the published figure, it
    survives a revision to an older week correctly, and taking it means the
    letter and this page cannot drift apart by taking different routes to the
    same number.
    """
    if df is None or df.empty:
        return {}
    r = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None

    wow = None
    if pd.notna(r.get("mm_long_chg")) and pd.notna(r.get("mm_short_chg")):
        wow = float(r["mm_long_chg"] - r["mm_short_chg"])

    oi = float(r["open_interest"]) if pd.notna(r["open_interest"]) else None
    return {
        "as_of": r["report_date"].date(),
        "net": float(r["mm_net"]),
        "side": side(r["mm_net"]),
        "long": float(r["mm_long"]),
        "short": float(r["mm_short"]),
        "spread": float(r["mm_spread"]) if pd.notna(r["mm_spread"]) else None,
        "wow": wow,
        "long_chg": float(r["mm_long_chg"]) if pd.notna(r["mm_long_chg"]) else None,
        "short_chg": float(r["mm_short_chg"]) if pd.notna(r["mm_short_chg"]) else None,
        "open_interest": oi,
        "oi_chg": float(r["open_interest_chg"]) if pd.notna(r["open_interest_chg"]) else None,
        "net_pct_oi": (100.0 * float(r["mm_net"]) / oi) if oi else None,
        "long_traders": _int_or_none(r.get("mm_long_traders")),
        "short_traders": _int_or_none(r.get("mm_short_traders")),
        "traders_total": _int_or_none(r.get("traders_total")),
        "prev_net": float(prev["mm_net"]) if prev is not None else None,
        "prev_as_of": prev["report_date"].date() if prev is not None else None,
    }


def _int_or_none(v):
    return int(v) if v is not None and pd.notna(v) else None


def why(latest_row: dict) -> dict:
    """
    Whether the week's move in NET was longs or shorts, and in which direction.

    NET HIDES THE MECHANISM AND THE MECHANISM IS THE STORY. A net that rises
    4,103 because funds bought 4,103 new longs is a market being chased; the
    same 4,103 because shorts covered is a market squeezing people out. Live
    Cattle on 2026-09-29 is the second kind -- longs added 1,452 and shorts
    covered 2,651, so most of the move was short covering -- and a page showing
    only "+4,103" cannot tell those apart.

    THE TWO LEGS CAN ALSO MOVE TOGETHER, AND THAT IS A THIRD STORY THE
    DOMINANT LEG ALONE WOULD MISREPRESENT. Feeder Cattle in the same week added
    1,122 longs AND 961 shorts: the net barely moved, by 161, but the funds put
    on more than two thousand contracts of gross exposure on both sides of the
    market. Reporting that as "new buying" because the long leg was marginally
    the larger would be true and misleading in one phrase. `agree` is False
    whenever the two legs point the same way, and the page says "both sides
    added" instead.

    Returns the dominant leg, its share of the gross movement, whether the legs
    agree, and a phrase the page can print. `driver` is None when nothing moved.
    """
    dl = latest_row.get("long_chg")
    ds = latest_row.get("short_chg")
    if dl is None or ds is None:
        return {"driver": None, "share": None, "phrase": "", "agree": None,
                "long_chg": None, "short_chg": None}
    gross = abs(dl) + abs(ds)
    if gross == 0:
        return {"driver": None, "share": None, "agree": None,
                "phrase": "neither leg moved", "long_chg": dl, "short_chg": ds}

    # Each leg's contribution to the NET move: a long added is +1 to net, a
    # short added is -1. The legs AGREE when both push net the same way, which
    # is when one phrase can honestly describe the week.
    long_part, short_part = dl, -ds
    agree = (long_part == 0 or short_part == 0
             or (long_part > 0) == (short_part > 0))

    if abs(long_part) >= abs(short_part):
        driver, part = "long", long_part
        phrase = "new buying" if dl > 0 else "long liquidation"
    else:
        driver, part = "short", short_part
        phrase = "short covering" if ds < 0 else "new selling"

    if not agree:
        # A WHOLE CLAUSE, not a noun phrase, because the caller cannot prefix
        # it with "mostly": no single leg carried a week in which both moved
        # the same way, and "mostly both sides added" is not English.
        phrase = ("longs and shorts both added" if dl > 0 and ds > 0
                  else "longs and shorts both liquidated")

    return {
        "driver": driver,
        "share": 100.0 * abs(part) / gross,
        "agree": agree,
        "phrase": phrase,
        "long_chg": dl,
        "short_chg": ds,
    }


def decompose(df: pd.DataFrame) -> list:
    """
    Every category's net for the newest week, so the page can show who is on
    the other side of the funds.

    THE WHOLE POINT OF THE DISAGGREGATED REPORT is that the five nets sum to
    zero -- every long contract is somebody's short. Managed money being net
    long 53,193 Live Cattle is only half a sentence; the other half is that
    producers, merchants and processors are net short 95,274 against it. The
    page shows both, because "funds are long" without "hedgers are short"
    invites the reader to imagine the position is held against nobody.
    """
    if df is None or df.empty:
        return []
    r = df.iloc[-1]
    rows = []
    for key, label in CATEGORIES:
        net = r.get(f"{key}_net")
        if net is None or pd.isna(net):
            continue
        rows.append({
            "key": key,
            "label": label,
            "net": float(net),
            "side": side(net),
            "long": _float_or_none(r.get(f"{key}_long")),
            "short": _float_or_none(r.get(f"{key}_short")),
            "spread": _float_or_none(r.get(f"{key}_spread")),
        })
    return rows


def _float_or_none(v):
    return float(v) if v is not None and pd.notna(v) else None


def categories_balance(rows: list) -> float | None:
    """
    The five nets summed. Zero by construction; CFTC's non-reportable residual
    leaves it a contract or two out in practice. The page prints it only when
    it exceeds OI_TOLERANCE, which would mean a category had gone missing.
    """
    if not rows:
        return None
    return float(sum(r["net"] for r in rows))


# -- putting one week in twenty years of context -----------------------------

RECENT_YEARS = 5

# Below this many observations a percentile is decoration rather than a
# measurement. The cattle history carries 1,060 weeks, so this only ever bites
# on a market whose history is short, or on a test fixture.
MIN_FOR_PERCENTILE = 52


def percentile(series: pd.Series, value) -> float | None:
    """
    Where `value` sits in `series`, 0-100. None rather than 50.0 when there is
    not enough history to mean anything: "the sample is too short to say" and
    "it is bang in the middle" are different answers, and a page that merges
    them is lying quietly. The same rule `leverage` follows for its own
    percentile helper.
    """
    s = pd.Series(series).dropna()
    if value is None or pd.isna(value) or len(s) < MIN_FOR_PERCENTILE:
        return None
    return float(100.0 * (s < value).mean())


def context(df: pd.DataFrame) -> dict:
    """
    What the newest net means against the history -- the half of the page that
    turns a number into information.

    TWO PERCENTILES, NOT ONE, BECAUSE THEY DISAGREE AND THE DISAGREEMENT IS THE
    POINT. Live Cattle on 2026-09-29 sits at the 47th percentile of the whole
    2006-2026 record and the 26th of the last five years: an ordinary position
    by the standards of two decades, a low one by the standards of the era the
    market is actually in. Either alone is a defensible number answering a
    question the reader did not ask.

    AND THE SHARE OF OPEN INTEREST, BECAUSE CONTRACTS ARE NOT COMPARABLE ACROSS
    THAT SPAN. Feeder Cattle open interest has roughly doubled since 2006-2010,
    so the same contract count is a materially smaller bet now than it was
    then. `net_pct_oi_pctile` is the honest long-run comparison and
    `net_pctile` is the familiar one; the page leads with the share wherever it
    reaches back past about five years.
    """
    out = {}
    if df is None or df.empty:
        return out
    g = df.sort_values("report_date").reset_index(drop=True)
    cur = g.iloc[-1]
    net = float(cur["mm_net"])
    out["as_of"] = cur["report_date"].date()
    out["net"] = net

    out["net_pctile"] = percentile(g["mm_net"], net)
    cutoff = cur["report_date"] - pd.Timedelta(365 * RECENT_YEARS, "D")
    recent = g[g["report_date"] >= cutoff]
    out["recent_years"] = RECENT_YEARS
    out["net_pctile_recent"] = percentile(recent["mm_net"], net)

    hi, lo = g["mm_net"].idxmax(), g["mm_net"].idxmin()
    out["record_high"] = float(g.loc[hi, "mm_net"])
    out["record_high_on"] = g.loc[hi, "report_date"].date()
    out["record_low"] = float(g.loc[lo, "mm_net"])
    out["record_low_on"] = g.loc[lo, "report_date"].date()

    pct_oi = 100.0 * g["mm_net"] / g["open_interest"]
    out["net_pct_oi"] = float(pct_oi.iloc[-1]) if pd.notna(pct_oi.iloc[-1]) else None
    out["net_pct_oi_pctile"] = percentile(pct_oi, out["net_pct_oi"])

    # Four weeks back BY DATE, not four rows back: a holiday week shifts a
    # report date but never drops one, so today the two agree -- taking it by
    # position anyway would silently become wrong if CFTC ever did skip a week.
    four = g[g["report_date"] <= cur["report_date"] - pd.Timedelta(27, "D")]
    out["net_4wk_ago"] = float(four.iloc[-1]["mm_net"]) if len(four) else None
    out["chg_4wk"] = (net - out["net_4wk_ago"]) if out["net_4wk_ago"] is not None else None

    # A YEAR AGO MEANS THE NEAREST REPORT TO THIS DATE LAST YEAR, not 52 rows
    # back. Fifty-two weeks is 364 days and the drift compounds: over twenty
    # years it walks the comparison a fortnight out of season, which on a market
    # with a real seasonal pattern is a different question.
    target = cur["report_date"] - pd.Timedelta(365, "D")
    if (g["report_date"] <= target).any():
        near = (g["report_date"] - target).abs().idxmin()
        out["net_year_ago"] = float(g.loc[near, "mm_net"])
        out["net_year_ago_on"] = g.loc[near, "report_date"].date()
        out["chg_year"] = net - out["net_year_ago"]
    else:
        out["net_year_ago"] = out["net_year_ago_on"] = out["chg_year"] = None

    # How long the funds have been on this side of the market. The run is
    # counted on the CURRENT sign, so a market that has just flipped reports 1
    # rather than carrying a stale long streak.
    sign = 0 if net == 0 else (1 if net > 0 else -1)
    run = 0
    for v in reversed(g["mm_net"].tolist()):
        if (0 if v == 0 else (1 if v > 0 else -1)) != sign:
            break
        run += 1
    out["weeks_on_this_side"] = run
    out["weeks_net_short"] = int((g["mm_net"] < 0).sum())
    out["weeks_total"] = int(len(g))
    out["history_from"] = g.iloc[0]["report_date"].date()

    # The week's move against every weekly move on file, so a bare "4,103" can
    # be placed as an ordinary week or a violent one.
    chg = g["mm_net"].diff()
    out["chg_wow_observed"] = float(chg.iloc[-1]) if pd.notna(chg.iloc[-1]) else None
    if out["chg_wow_observed"] is not None:
        out["chg_pctile_abs"] = percentile(chg.abs(), abs(out["chg_wow_observed"]))
    else:
        out["chg_pctile_abs"] = None
    out["chg_biggest_up"] = float(chg.max()) if chg.notna().any() else None
    out["chg_biggest_down"] = float(chg.min()) if chg.notna().any() else None
    return out


def series_frame(df: pd.DataFrame, years: int | None = None) -> pd.DataFrame:
    """
    The columns a chart needs, optionally trimmed to the last `years`.

    Trimming is on the DATE and not on a row count, for the reason `context()`
    takes four weeks by date: the step is 6, 7 or 8 days, and only a date
    window means the same thing in every era.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    g = df.sort_values("report_date").reset_index(drop=True)
    if years:
        cutoff = g["report_date"].max() - pd.Timedelta(365 * years, "D")
        g = g[g["report_date"] >= cutoff].reset_index(drop=True)
    out = g[["report_date", "mm_net", "mm_long", "mm_short", "mm_spread",
             "open_interest"]].copy()
    out["net_pct_oi"] = 100.0 * out["mm_net"] / out["open_interest"]
    return out


# -- the one entry point the page calls --------------------------------------

def load(series=CATTLE, neighbours=NEIGHBOURS) -> dict:
    """
    Everything the page needs, in two round trips total.

    TWO QUERIES, NOT ONE PER MARKET. Each is a single SELECT over the view with
    an IN list, so adding lean hogs, corn and meal to the cattle costs three
    more SERIES values rather than three more round trips -- which is what
    makes it reasonable to show them at all.

    The COMBINED basis is fetched because the page offers it as a comparison,
    never because anything leads with it. Every headline figure in the returned
    dict comes from `fut`.

    IT RETURNS AN ERROR STRING RATHER THAN RAISING. A Snowflake outage must
    leave the page able to say what is wrong, the way `draft_store` returns a
    status instead of taking the letter down with it.
    """
    wanted = tuple(series) + tuple(n for n in neighbours if n not in series)
    out = {"schema": SCHEMA, "series": tuple(series),
           "neighbours": tuple(neighbours), "error": None}
    try:
        fut = fetch(wanted, FUT)
        comb = fetch(series, COMBINED)
        leg = fetch_legacy(series, FUT)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    out["fut"] = fut
    out["combined"] = comb
    out["legacy"] = leg
    if fut.empty:
        out["error"] = "No rows returned from " + VIEW
        return out

    out["as_of"] = fut["report_date"].max().date()
    out["freshness"] = is_current(out["as_of"])
    out["position_age_days"] = position_age_days(out["as_of"])
    cattle_fut = fut[fut["series"].isin(series)]
    out["audit"] = reconciles(cattle_fut)
    out["cross_audit"] = reconciles_across_views(cattle_fut, leg)

    markets = {}
    for s in wanted:
        one = market(fut, s)
        if one.empty:
            continue
        head = latest(one)
        entry = {"series": s,
                 "label": LABELS.get(s, s.replace("_", " ").title()),
                 "latest": head, "frame": one}
        if s in series:
            entry["context"] = context(one)
            entry["why"] = why(head)
            entry["categories"] = decompose(one)
            entry["balance"] = categories_balance(entry["categories"])
            cm = market(comb, s)
            entry["combined"] = latest(cm) if not cm.empty else {}
            other = one.iloc[-1].get("other_net")
            entry["reconciliation"] = reconciliation(
                head, entry["combined"], leg, s,
                other_net=float(other) if pd.notna(other) else None)
        markets[s] = entry
    out["markets"] = markets
    return out


# -- the three figures a reader may meet, and why they differ ----------------
#
# THE SAME WEEK, THE SAME CFTC REPORT FAMILY, THE SAME FUTURES-ONLY BASIS, AND
# THREE DIFFERENT ANSWERS TO "WHAT IS THE FUND POSITION IN CATTLE". On
# 2026-09-29 feeder cattle they do not merely differ in size, THEY DIFFER IN
# SIGN:
#
#     managed money net, disaggregated, futures only     8,166 LONG   <- this page
#     managed money net, futures and options combined    7,638 long
#     non-commercial net, the older Legacy report        2,081 SHORT
#
# All three are CFTC, all three are correct, and a reader who meets the third
# one anywhere else -- most broker screens, chart services and press wires
# still quote legacy non-commercial as "the funds" or "large speculators" --
# will read this page as broken. CLAUDE.md records three mornings lost to two
# JSA surfaces quoting the same figure and disagreeing; this is the same
# failure with the OUTSIDE WORLD as the second surface, and it is live today
# rather than hypothetical.
#
# SO THE PAGE SHOWS ALL THREE AND EXPLAINS THE GAP WITH AN IDENTITY, which is
# the only honest way to do it, because the gap is not an estimate:
#
#     NONCOMM_NET = MM_NET + OTHER_NET        exactly, 1,060/1,060 weeks,
#                                             both cattle markets, max error 0
#
# The older report had one "non-commercial" bucket; the disaggregated report
# split it into managed money and "other reportables". Feeder cattle's other
# reportables are net short 10,247, which is the whole of the difference and
# the whole of the sign flip. That is a sentence a reader can check, and it is
# asserted on every load rather than written in a comment.
#
# LEGACY_IS_NOT_A_HISTORY. The same view reaches back to 1986 and it is
# tempting to chart it as "twenty more years of fund positioning". It must not
# be, for two independent reasons, either of which is fatal:
#
#   * The gap between the two is not a constant offset. It drifts and changes
#     sign -- the annual mean gap runs from -2,837 in 2019 to +10,805 in 2026
#     -- so a spliced line would show moves that are a reclassification rather
#     than a market.
#   * Before October 1992 the legacy report was SEMI-MONTHLY, not weekly: 24
#     reports a year through 1991, 31 in 1992, 52 from 1993. A chart "back to
#     1986" silently changes its own sampling rate mid-axis.
#
# (The feeder contract was also 44,000 lb rather than 50,000 before mid-1992,
# which kills any constant-multiplier conversion of that era as well.)

def fetch_legacy(series=CATTLE, report_type: str = FUT) -> pd.DataFrame:
    """
    The legacy Commercial / Non-Commercial split, for the reconciliation only.

    One row per market is all the panel needs, but the whole series costs the
    same single round trip and lets `reconciles_across_views()` check the
    identity on every week rather than on the newest one.
    """
    sql = (f"SELECT SERIES AS series, REPORT_DATE, OPEN_INTEREST, "
           f"NONCOMM_LONG, NONCOMM_SHORT, NONCOMM_SPREAD, NONCOMM_NET, "
           f"COMM_LONG, COMM_SHORT, COMM_NET, NONREPT_NET "
           f"FROM {LEGACY_VIEW} "
           f"WHERE REPORT_TYPE = '{report_type}' "
           f"AND SERIES IN ({_quoted(series)}) "
           f"ORDER BY SERIES, REPORT_DATE")
    df = _read(sql)
    if df.empty:
        return df
    df["report_date"] = pd.to_datetime(df["report_date"])
    num = [c for c in df.columns if c not in ("series", "report_date")]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    return df.reset_index(drop=True)


def reconciles_across_views(disagg: pd.DataFrame, legacy: pd.DataFrame) -> dict:
    """
    NONCOMM_NET = MM_NET + OTHER_NET, on every week the two views share.

    A CROSS-VIEW AUDIT IS WORTH MORE THAN A WITHIN-VIEW ONE HERE, because it is
    the only check that would catch the join itself going wrong -- a SERIES
    remapped, a report type crossed, a view redefined upstream. It is free: the
    legacy rows are already fetched for the panel.

    Exact, with no tolerance, because it is exact: 1,060 of 1,060 weeks in both
    cattle markets, maximum error zero.
    """
    out = {"rows": 0, "ok": None, "bad": 0, "worst": 0.0}
    if disagg is None or legacy is None or disagg.empty or legacy.empty:
        return out
    j = disagg[["series", "report_date", "mm_net", "other_net"]].merge(
        legacy[["series", "report_date", "noncomm_net"]],
        on=["series", "report_date"], how="inner")
    if j.empty:
        return out
    resid = j["noncomm_net"] - (j["mm_net"] + j["other_net"])
    out["rows"] = int(len(j))
    out["bad"] = int((resid != 0).sum())
    out["worst"] = float(resid.abs().max())
    out["ok"] = out["bad"] == 0
    return out


def reconciliation(disagg_row: dict, combined_row: dict, legacy: pd.DataFrame,
                   series: str, other_net=None) -> dict:
    """
    The three figures for one market's newest week, plus the identity that
    explains the gap between the first and the third.

    Returns `sign_split` True when the managed-money net and the legacy
    non-commercial net are on OPPOSITE SIDES of the market -- the case the
    panel exists for, live on feeder cattle this week and true in 133 of its
    1,060 weeks.
    """
    out = {
        "fut_net": disagg_row.get("net") if disagg_row else None,
        "combined_net": combined_row.get("net") if combined_row else None,
        "legacy_net": None, "other_net": other_net,
        "sign_split": False, "identity_ok": None,
    }
    if legacy is not None and not legacy.empty:
        g = legacy[legacy["series"] == series].sort_values("report_date")
        if not g.empty:
            out["legacy_net"] = float(g.iloc[-1]["noncomm_net"])
            out["legacy_as_of"] = g.iloc[-1]["report_date"].date()

    f, l = out["fut_net"], out["legacy_net"]
    if f is not None and l is not None:
        out["sign_split"] = (f > 0) != (l > 0) and f != 0 and l != 0
        if other_net is not None:
            out["identity_ok"] = (l == f + other_net)
    return out
