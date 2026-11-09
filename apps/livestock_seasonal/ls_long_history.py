"""Nearby futures history from before Massive's floor, so the charts reach 2001.

Added 2026-11-05 on Ross's "we currently only go back 5 years for chart history --
can we add 20 years worth of data?"

MASSIVE CANNOT DO IT AND NO SPELLING WILL FIX THAT, which is the first thing to
know before anybody tries again. Re-probed the day this was written:

    LEZ1  38 bars  2021-11-08 -> 2021-12-31     the floor, and it is sharp
    LEZ0  0 bars          LEZ8  0 bars          LEZ9  0 bars

Contracts that expired before 2021-11-08 return HTTP 200 with an empty result
set -- the "200 that means nothing here" trap CLAUDE.md records for MARS slug
2452. And the symbology is DECADE-AMBIGUOUS: `LEZ7` is both Dec 2017 and Dec
2027, and /aggs always resolves to the live contract, so it answers with 2026
data. Two-digit and dotted forms (LEZ21, LEZ06, LEZ2021, LEZ16) all return zero
bars. /contracts for an as-of date in 2010 or 2016 returns zero results. So the
older contracts are not merely absent, they are UNADDRESSABLE, and a deeper
entitlement would still need a different symbology to reach them.

Yahoo's continuous front-month series does reach: LE=F to 2001-03-01, GF=F to
2001-04-03, HE=F to 2000-12-15, ~252 bars a year with no gaps.

IT IS THE SAME SERIES THE PAGE ALREADY BUILDS, which is what makes splicing it
on legitimate rather than merely convenient. Measured over the whole 1,255-day
overlap, against this page's own Massive-spliced nearby series:

    LE   1254 / 1255 identical to the thousandth
    GF   1254 / 1255
    HE   1254 / 1255

The single disagreement on each is the SAME day -- 2026-11-05, the session in
progress when the check ran, where the two sources are live quotes minutes
apart. So the roll convention, the settlement prices and the splice points all
agree; this is not a near-enough series being calibrated onto ours.

Even so the two are kept strictly apart by date (see `splice`), because "both
sources agree today" is a measurement and not a guarantee.

This is a SECOND Yahoo caller -- `letter/sources.fetch_dollar_index` is the
first -- and deliberately not a shared one: that fetches a single quote row for
the morning brief and this fetches a 25-year daily series for a chart. They
share no code worth lifting, only conventions: a null close skipped rather than
read as zero, and any failure costing the deep history alone and never the page.

ONE CONVENTION IS DELIBERATELY NOT CARRIED OVER -- that module dates its bars
off `meta.gmtoffset`, which is right there and wrong here. See `fetch_nearby`;
copying it cost 792 bars dated to a Sunday before the overlap check caught it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

# Bump whenever fetch_nearby or splice changes the SHAPE of what it returns.
# The cache serves shape, not freshness, and never notices that this module
# changed -- the leverage.SCHEMA trap, recorded in CLAUDE.md. Passed at the
# call site, because a default is not part of the key.
SCHEMA = 1

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# Yahoo's continuous front-month symbols. Verified against this page's own
# nearby series over five years -- see the docstring.
NEARBY_SYMBOLS = {"LE": "LE=F", "GF": "GF=F", "HE": "HE=F"}

# Yahoo serves this endpoint a 404 to an unidentified client often enough to be
# worth setting rather than discovering on a Monday morning -- the reason
# letter/sources.py sets one too.
USER_AGENT = "Mozilla/5.0 (compatible; JSA-portal/1.0)"

# The earliest date worth asking for. Well before any of the three series
# begins, so the floor that comes back is the feed's own rather than this
# constant's -- which is what lets the page PRINT the start date instead of
# asserting one that could quietly stop being true.
REQUEST_FROM = date(1990, 1, 1)

TIMEOUT = 30


def _epoch(when: date) -> int:
    return int(datetime(when.year, when.month, when.day, tzinfo=timezone.utc).timestamp())


def fetch_nearby(product_code: str, as_of: date) -> pd.Series:
    """Daily continuous nearby settlements for one product, oldest first.

    RANGE=MAX SILENTLY RETURNS MONTHLY BARS, and that is the trap this function
    exists to not fall into. Asking for `range=max&interval=1d` -- the obvious
    spelling -- comes back 200 with `dataGranularity: 1mo` and 264 bars spanning
    25 years, which reads as a working daily series right up until somebody
    charts it or computes a seasonal statistic off twelve points a year. An
    explicit period1/period2 pair returns the real 6,438. Measured both ways.

    The last bar is TODAY'S SESSION IN PROGRESS, not a settlement, so it is
    dropped -- the `completed_only` rule letter/sources.py already runs on, and
    the one day in the overlap check where this series and Massive's disagreed.
    It matters only when this series is standing in for a dark Massive, since
    otherwise Massive owns every recent date anyway.

    Returns an empty Series on any failure. The deep history is additive: the
    page renders exactly as it did before without it, so an outage at an
    undocumented endpoint must not be able to cost anything else.
    """
    symbol = NEARBY_SYMBOLS.get(product_code)
    if not symbol:
        return pd.Series(dtype=float)

    try:
        resp = requests.get(
            CHART_URL.format(symbol=symbol),
            headers={"User-Agent": USER_AGENT},
            params={
                "period1": _epoch(REQUEST_FROM),
                "period2": _epoch(as_of + timedelta(days=1)),
                "interval": "1d",
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        result = ((resp.json().get("chart") or {}).get("result") or [None])[0]
        if not result:
            return pd.Series(dtype=float)

        # THE UTC DATE OF THE STAMP IS THE SESSION DATE. DO NOT APPLY
        # `meta.gmtoffset` HERE -- it is in the payload, it is what
        # letter/sources.fetch_dollar_index correctly uses, and on this endpoint
        # it moves every bar onto the WRONG DAY for eight months of the year.
        #
        # The two symbols are stamped differently, which is the whole trap.
        # DX-Y.NYB is stamped at the session OPEN (13:00-14:00 UTC), so reading
        # it as UTC is only hours from the boundary and the offset is the safe
        # correction. These futures are stamped at MIDNIGHT NEW YORK: 04:00 UTC
        # on an EDT date, 05:00 UTC on an EST one. Subtracting five hours
        # therefore lands 04:00 back on 23:00 the PREVIOUS day through EDT and
        # is a no-op through EST -- so it misdates most of the year and comes
        # right in winter, which is precisely the shape of defect that survives
        # a spot check.
        #
        # Measured, rather than reasoned about, over the whole 25-year pull:
        #   with the offset   792 bars landed on a SUNDAY, and agreement with
        #                     this page's Massive series over their overlap fell
        #                     to 440 of 1081, worst case 16.38 out
        #   as plain UTC      zero weekend bars -- all 6,524 stamps are Mon-Fri
        #                     -- and 1,254 of 1,255 overlap days identical to
        #                     the thousandth
        #
        # It is robust rather than lucky: 04:00/05:00 UTC sits four hours clear
        # of the UTC midnight it would have to cross, and the 43 intraday stamps
        # in the history (11:20-14:30 UTC, the live bar) are further inside the
        # same UTC day, not nearer the edge.
        stamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []

        rows: dict[date, float] = {}
        for stamp, close in zip(stamps, closes):
            # A NULL CLOSE IS SKIPPED, not read as a number. Yahoo serves them
            # -- letter/sources.py found a Saturday carrying close: null -- and
            # `float(None)` raising here would cost the whole series, while a
            # zero would chart as a crash to nothing.
            if close is None:
                continue
            when = datetime.fromtimestamp(int(stamp), tz=timezone.utc).date()
            rows[when] = float(close)

        rows.pop(as_of, None)
        if not rows:
            return pd.Series(dtype=float)

        series = pd.Series(rows).sort_index()
        series.index = pd.to_datetime(series.index)
        return series
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return pd.Series(dtype=float)


def splice(recent: pd.Series, legacy: pd.Series) -> pd.Series:
    """One source per date, and the live feed wins every date it covers.

    Massive is the series the rest of this page is built from -- the per-contract
    overlays, the spreads, the curve -- so handing it any date it can answer
    keeps the nearby chart reconcilable with the tabs beside it, and makes this
    change provably unable to move a number that is on the page today.

    The handover is Massive's own earliest date rather than a constant, so it
    travels on its own as the vendor's retention window rolls forward. That is
    the shape `herd.CHANNEL_LEGACY_THROUGH` and the southeast retention build
    already use: one source per period, decided by where the live feed starts,
    never a date typed in here.

    Summing them instead would double-count 1,255 days. The two agree to the
    thousandth on almost all of them, so a duplicated index would not look
    wrong -- it would just quietly give those five years twice the weight in
    every mean and every high/low count computed downstream.

    With no live series at all this returns the legacy one on its own, which is
    a complete and current nearby series rather than a stale one -- Yahoo runs
    to the last completed session. That is strictly better than the warning the
    page would otherwise show, and it is why `fetch_nearby` drops the in-progress
    bar rather than leaving it for the caller to remember.
    """
    if legacy is None or not len(legacy):
        return recent if recent is not None else pd.Series(dtype=float)
    if recent is None or not len(recent):
        return legacy

    older = legacy[legacy.index < recent.index.min()]
    if not len(older):
        return recent
    return pd.concat([older, recent]).sort_index()
