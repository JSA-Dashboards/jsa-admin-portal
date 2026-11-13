"""
New World Screwworm confirmed cases, from APHIS's own published feeds.

WHY IT SITS ON THIS PAGE. Screwworm is the reason the southern border closed
to feeder cattle at all. Every port state recorded in `border.py` -- Douglas,
Santa Teresa, Columbus, Nogales -- shut and reopened on NWS risk, so the case
count in northern Mexico is the leading indicator for the crossings panel two
tabs over. Sonora and Chihuahua, the two states that supply the cattle moving
through Douglas and Santa Teresa, are both in the Mexican feed below.

TWO FEEDS, TWO COUNTRIES, AND "ACTIVE" DOES NOT MEAN THE SAME THING IN EACH.
That is the single most important fact in this module and the page says it out
loud, because the two numbers sit inches apart and nothing about them warns a
reader:

    Mexico   active <=> the case was confirmed within the last 15 days.
             SENASICA calls a case active at diagnosis and revisits it after
             15 days. In practice the flip is MECHANICAL -- see below.
    US       active <=> mitigation is still under way, a real case status.
             APHIS's own monthly split proves it is not a clock: on the
             2026-11 reading, 24 of October's 33 domestic cases were still
             active at 11 to 41 days old, which a 15-day rule would have
             closed.

So "active cases" is a 15-day rolling case count on one side of the border and
a genuine disease status on the other. Averaging them, summing them, or
putting them under one label would be the two-surfaces-one-name failure this
repo records five times over.

THE MEXICAN FLIP IS MECHANICAL, AND THAT IS LOAD-BEARING RATHER THAN A
CURIOSITY. Measured across all 578 rows of the 2026-11-10 file: every case at
age 0-14 days was Active (63 of 63) and every case at age 15 or more was
Inactive (515 of 515). Not one date carried both statuses. Three things fall
out of it, and the whole panel rests on them:

  - INACTIVE IS NOT INDEPENDENT INFORMATION. It is total minus active. The
    page shows it because APHIS does and Ross asked for it, and says so.
  - THE WHOLE HISTORY IS RECONSTRUCTIBLE. Status is a pure function of
    (confirmed date, as-of date), so what the dashboard said last Tuesday can
    be recomputed from today's file. **Week-over-week therefore needs no
    banked snapshots, no table and no cron** -- unlike `JSA.BOXED_BEEF.CUTOUT_AM`
    and `MX_AUCTION_PRICES`, where the source keeps no history and the series
    only accrues from the day a job starts recording. This one arrives with
    fourteen months of history on its first load.
  - IT IS AN AUDIT. `as_of()` DERIVES the file's as-of date from the
    active/inactive boundary rather than taking `max(date)` or, worse,
    today's clock. If APHIS ever changes the rule the two constraints stop
    agreeing, `as_of()` returns None, and the page says the status rule no
    longer holds instead of printing a confident wrong number.

NEVER COMPUTE "ACTIVE" AGAINST `date.today()`. The file lags its own newest
case -- the 2026-11-10 edition stopped at 2026-11-08 -- so a window anchored
on today drops cases APHIS still calls active off the back of the window while
the front has nothing to replace them with. The count comes out low, looks
entirely plausible, and nothing raises. Every function here takes the as-of
date as an argument for the same reason `index_dates` and `cof_recap` do.

NO NEW SECRET. Both feeds are keyless.

    MEXICO  www.aphis.usda.gov/sites/default/files/nws-weekly-status.csv
            Case-level: confirmed date, state, species, age, active/inactive,
            sterile-fly dispersal, and approximate miles from the US. It is
            the list the Current Status page renders as a table, and it is
            scoped to cases WITHIN 100 MILES OF THE BORDER -- the observed
            maximum is exactly 100.0, which is the tell. It is NOT all of
            Mexico and the page must not be read as a national count.

            Despite the filename it is not weekly: APHIS states it is
            rewritten each business day at 5 p.m. ET, and the Last-Modified
            header has matched that. It does go stale -- read it, do not
            assume it is current.

    US      publicdashboards.dl.usda.gov -- the `.csv` export of the Tableau
            view behind the APHIS confirmed-detections dashboard. Monthly, and
            only the most recent four months, because that is what the
            underlying worksheet draws.

THE US FEED CANNOT SUPPORT WEEK-OVER-WEEK AND MUST NOT BE MADE TO LOOK LIKE IT
CAN. It is monthly. It also cannot give the all-time total: the dashboard's
own headline counts every case since the first US detection on 2026-06-08,
while the CSV reaches back four months. What it CAN give exactly is the active
count, because an active US case is a recent one and the four-month window
covers every one of them -- 65 on the 2026-11 reading, which reconciles with
the dashboard's own 126 domestic less 61 inactive. Anything the feed cannot
answer is linked out to APHIS rather than estimated.

WHY THIS MODULE MAY FETCH WHEN `border.py` AND `mx_prices.py` MAY NOT.
`tests/test_mx_prices.py` asserts those two import no `requests`, and the rule
is recorded in CLAUDE.md as "border.py has no HTTP path so the Streamlit
process cannot acquire one". What that rule protects is CREDENTIALS -- every
USDA and Census key this page depends on belongs to an ingest running
elsewhere, and a key here would be dead config at best. Both feeds here are
public and keyless, so nothing of the sort enters the process. The two
existing modules are untouched; `corn_demand.py` set this precedent and, like
it, a test pins the exact hosts this one may reach.

THE FILE CARRIES A UTF-8 BOM. `csv.DictReader` over a plain `utf-8` handle
puts `﻿` on the front of the first column name, so every lookup of the
date column returns None and the parse yields 578 empty rows rather than an
error. The same BOM is recorded in CLAUDE.md for two of the app pages. Read
`utf-8-sig`.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

import requests

# Bump whenever a function here changes the SHAPE of what it returns. The
# cache serves shape, not freshness -- `st.cache_data` keys on the decorated
# function's own code and never on the modules it calls, so a reshaped return
# is served from a cache built before the reshape and the tile reading a new
# key renders an em dash with nothing raising. The `leverage.SCHEMA` trap.
SCHEMA = 1

SOURCE_MX = "https://www.aphis.usda.gov/sites/default/files/nws-weekly-status.csv"
SOURCE_US = ("https://publicdashboards.dl.usda.gov/t/MRP_PUB/views/"
             "NewWorldScrewwormPublicReporting_17805168329840/"
             "SummaryDashboard.csv")

# The pages a reader should be sent to rather than given an estimate of.
PAGE_MX = ("https://www.aphis.usda.gov/animals/animal-health/"
           "livestock-and-poultry-disease/stop-screwworm/current-status")
PAGE_US = PAGE_MX + "/confirmed"

# SENASICA's own rule: active at diagnosis, revisited after 15 days. Inclusive
# of both ends, so a case is active on the 15 dates from its confirmation
# through confirmation + 14 -- which is what reproduces the published split
# exactly. Do NOT "simplify" this to 14 or to a strict inequality; the boundary
# was measured off the file and `test_the_active_window_reproduces_the_feed`
# fails either way round.
ACTIVE_DAYS = 15

# Week-over-week is 7-day BLOCKS ANCHORED ON THE AS-OF DATE, never calendar
# weeks. A calendar week is partial on every day but one, so a Tuesday reading
# would compare three days against seven and print a collapse that is only the
# calendar -- the trap `annual_span()` and `YTD_CUT` already guard elsewhere in
# this repo. Anchored blocks are always seven days each.
WEEK = 7

# The scope of the Mexican feed, stated so a reader cannot take it for a
# national count. Verified against the data on every load by `in_scope()`.
MAX_MILES = 100

# Approximate geographic centre of each Mexican state that can appear in a
# feed scoped to 100 miles of the border, plus the near-border interior. The
# bubble sits at the state's MIDDLE, not at the cases -- which for a state the
# size of Chihuahua is a couple of hundred miles from the line. That is why
# the page draws the miles-from-border distribution beside the map instead of
# letting the map imply a distance. `unmapped_states()` reports anything that
# turns up without a coordinate, because a state silently missing from a map
# reads as a state with no cases.
MX_STATE_COORDS = {
    "Baja California": (30.5, -115.5),
    "Baja California Sur": (25.8, -111.8),
    "Sonora": (29.6, -110.9),
    "Chihuahua": (28.6, -106.1),
    "Coahuila": (27.3, -102.0),
    "Nuevo León": (25.6, -99.9),
    "Tamaulipas": (24.3, -98.6),
    "Durango": (24.8, -104.7),
    "Sinaloa": (25.0, -107.5),
    "Zacatecas": (23.2, -102.6),
    "San Luis Potosí": (22.6, -100.4),
    "Veracruz": (19.2, -96.4),
}

# The crossings, for orientation on the map -- the question this page exists
# to answer is how close the cases are to where cattle cross. The KEYS are
# `border.KNOWN_PORTS` spellings and `test_every_mapped_port_is_a_border_port`
# asserts it, so the two rosters cannot drift into naming one crossing two
# ways.
PORT_COORDS = {
    "NOGALES, AZ": (31.34, -110.94),
    "DOUGLAS, AZ": (31.34, -109.55),
    "SANTA TERESA, NM": (31.78, -106.69),
    "COLUMBUS, NM": (31.83, -107.64),
    "PRESIDIO, TX": (29.56, -104.37),
    "DEL RIO, TX": (29.36, -100.90),
    "EAGLE PASS, TX": (28.71, -100.50),
    "LAREDO, TX": (27.51, -99.51),
}

# The feed writes a literal "NA" where SENASICA has not released the state.
# It is NOT a missing-data bug and it is not evenly spread: on the 2026-11-10
# file all 24 of them were the newest cases, 11-01 to 11-08. So the newest
# week is systematically the least located, and a state chart that silently
# dropped them would understate exactly the period a reader is looking at.
NO_STATE = "NA"

# Likewise the dispersal column, where "**" is APHIS's own footnote marker
# rather than a value -- it carries the note that the sterile-fly area is
# adjusted on modelling and is not disclosed per case.
NO_VALUE = "**"

_DATE_COL = "Date (mm/dd/yy)"


# ── Fetching ────────────────────────────────────────────────────────────────

def _parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%m/%d/%y").date()
    except ValueError:
        return None


def _parse_miles(s):
    s = str(s if s is not None else "").strip()
    if not s or s in (NO_STATE, NO_VALUE):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_mexico(text: str) -> list[dict]:
    """Case rows from the APHIS Mexico CSV text.

    A row whose date will not parse is DROPPED rather than carried with a null
    date: every figure on the panel is a function of the date, so a row
    without one cannot be counted, aged, or placed in a week, and carrying it
    would make the total disagree with the sum of its own parts.
    """
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        d = _parse_date(raw.get(_DATE_COL, ""))
        if d is None:
            continue
        rows.append({
            "date": d,
            "state": (raw.get("State") or "").strip() or NO_STATE,
            "species": (raw.get("Species") or "").strip() or "Unknown",
            "age": (raw.get("Age") or "").strip(),
            "status": (raw.get("Active/Inactive*") or "").strip(),
            "dispersal": (raw.get("USDA Sterile Insect Dispersal") or "").strip(),
            "miles": _parse_miles(raw.get("Approximate Miles From US")),
        })
    rows.sort(key=lambda r: r["date"])
    return rows


def fetch_mexico(url: str = SOURCE_MX, timeout: int = 30) -> dict:
    """The Mexican case list, with the server's own Last-Modified.

    `last_modified` is kept because it answers a different question from the
    newest case date and the page prints both: one says when APHIS last
    rewrote the file, the other how far the cases in it reach. On the
    2026-11-10 edition they were two days apart, which is the publication lag
    and is the reason the newest week always reads light.
    """
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    # The BOM is why this is utf-8-sig rather than r.text, which honours the
    # header charset and leaves ﻿ on the first column name.
    rows = parse_mexico(r.content.decode("utf-8-sig"))
    stamp = None
    lm = r.headers.get("Last-Modified")
    if lm:
        try:
            stamp = datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S %Z")
        except ValueError:
            stamp = None
    return {"rows": rows, "last_modified": stamp, "url": url}


# ── The as-of date, derived rather than assumed ─────────────────────────────

def as_of(rows: list[dict]):
    """The date the published active/inactive split describes.

    DERIVED FROM THE SPLIT ITSELF, which makes it a free audit of the rule the
    whole panel rests on. Active means `as_of - date <= ACTIVE_DAYS - 1`, so
    the oldest Active case caps the as-of date and the newest Inactive one
    floors it. A third bound is free and worth stating: nothing can be
    published before it was confirmed, so the newest case floors it too.

        as_of <= oldest_active   + (ACTIVE_DAYS - 1)
        as_of >= newest_inactive + ACTIVE_DAYS
        as_of >= newest_case

    On the 2026-11-10 file all three collapse onto 2026-11-08 -- a single day,
    which is as tight as the data can be. Returns None when they cross, which
    means APHIS has changed the rule; the page then says so rather than
    computing a window it can no longer justify.

    WHERE THE BOUNDS LEAVE A RANGE, THE EARLIEST IS TAKEN. A gap in case dates
    either side of the boundary loosens them, and the two errors are not
    symmetric: reading the as-of later than it is claims a freshness the file
    does not have and quietly ages real cases out of the active window, while
    reading it early only understates. Understating is the recoverable one.

    Returning the newest case date outright would look identical today and
    would keep looking identical for as long as the rule held, which is
    precisely why it is not done that way: the point is to notice when it
    stops.
    """
    act = [r["date"] for r in rows if r["status"] == "Active"]
    ina = [r["date"] for r in rows if r["status"] == "Inactive"]
    newest = max((r["date"] for r in rows), default=None)
    if newest is None:
        return None
    if not act:
        # No active case at all is a real state -- an outbreak that has gone
        # quiet -- and the boundary cannot be read from it. The newest case is
        # the best available bound and is never later than the truth.
        return newest
    hi = min(act) + timedelta(days=ACTIVE_DAYS - 1)
    lo = newest
    if ina:
        lo = max(lo, max(ina) + timedelta(days=ACTIVE_DAYS))
    return None if lo > hi else lo


def rule_holds(rows: list[dict], d: date) -> bool:
    """Does every row's published status match the 15-day window at `d`?

    The audit in its blunt form, run on every load. `as_of()` only checks the
    two extremes; this checks all 578 rows, so a single restated case in the
    middle of the series shows up.
    """
    for r in rows:
        if r["status"] not in ("Active", "Inactive"):
            continue
        want = "Active" if _is_active(r["date"], d) else "Inactive"
        if r["status"] != want:
            return False
    return True


def in_scope(rows: list[dict]) -> bool:
    """Does the feed still look like the within-100-miles list?

    Printed rather than assumed: the caption tells a reader this is not a
    national count, and that claim has to keep being true. A file that started
    carrying the whole country would make every figure here describe something
    much larger under an unchanged heading.
    """
    miles = [r["miles"] for r in rows if r["miles"] is not None]
    return bool(miles) and max(miles) <= MAX_MILES


def _is_active(case: date, d: date) -> bool:
    return 0 <= (d - case).days <= ACTIVE_DAYS - 1


# ── Counts at a date ────────────────────────────────────────────────────────

def total_on(rows: list[dict], d: date) -> int:
    """Cases confirmed on or before `d`, as the file now stands."""
    return sum(1 for r in rows if r["date"] <= d)


def active_on(rows: list[dict], d: date) -> int:
    return sum(1 for r in rows if _is_active(r["date"], d))


def new_between(rows: list[dict], start: date, end: date) -> int:
    """Cases confirmed in [start, end], both ends inclusive."""
    return sum(1 for r in rows if start <= r["date"] <= end)


def snapshot(rows: list[dict], d: date) -> dict:
    """What APHIS's own headline said on `d`.

    `inactive` is total less active and the page labels it as such. It is
    shown because the dashboard shows it and Ross asked for it, not because it
    is a second measurement -- on this feed it carries no information the
    other two do not.
    """
    tot = total_on(rows, d)
    act = active_on(rows, d)
    return {
        "as_of": d,
        "total": tot,
        "active": act,
        "inactive": tot - act,
        "newest": max((r["date"] for r in rows if r["date"] <= d), default=None),
        "oldest": min((r["date"] for r in rows), default=None),
    }


# ── Week over week ──────────────────────────────────────────────────────────

def wow(rows: list[dict], d: date) -> dict:
    """This 7-day block against the one before it, anchored on `d`.

    THE TWO LEGS OF THE ACTIVE CHANGE ARE NOT EQUALLY SETTLED, and the panel
    says so. Active moves by what came in less what aged out:

        active(d) - active(d-7)  ==  new_7  -  aged_out

    `aged_out` is the block that ended 15 days ago. It is weeks old, fully
    reported, and will not move again. `new_7` is the last seven days, which
    are still filling in -- APHIS's own file reached only to two days before
    it was written. So the change is biased DOWNWARD, by an amount nobody can
    measure from one snapshot, and a week that reads flat may well have risen.
    That is a caveat to print, not a correction to apply: inventing a
    completion factor would be the plausible-wrong-cause failure this repo
    keeps recording.

    `total_change` is identically `new_7` -- a total only moves by new cases.
    Both are returned because the page labels them differently and a reader
    adding them would otherwise double-count.
    """
    prev = d - timedelta(days=WEEK)
    now, before = snapshot(rows, d), snapshot(rows, prev)
    new_7 = new_between(rows, d - timedelta(days=WEEK - 1), d)
    prev_7 = new_between(rows, prev - timedelta(days=WEEK - 1), prev)
    # Cases that were active a week ago and are not now: the block ending
    # ACTIVE_DAYS before `d`.
    out_end = d - timedelta(days=ACTIVE_DAYS)
    aged_out = new_between(rows, out_end - timedelta(days=WEEK - 1), out_end)
    return {
        "as_of": d,
        "prev_as_of": prev,
        "total": now["total"], "total_prev": before["total"],
        "total_change": now["total"] - before["total"],
        "active": now["active"], "active_prev": before["active"],
        "active_change": now["active"] - before["active"],
        "inactive": now["inactive"], "inactive_prev": before["inactive"],
        "inactive_change": now["inactive"] - before["inactive"],
        "new_7": new_7, "new_prev_7": prev_7,
        "new_change": new_7 - prev_7,
        "aged_out": aged_out,
    }


def weekly_new(rows: list[dict], d: date, blocks: int = 12) -> list[dict]:
    """New cases per anchored 7-day block, oldest first.

    Blocks that begin before the first case are dropped rather than drawn as
    zeros: the series starts when the outbreak does, and a run of empty bars
    in front of it reads as a quiet period rather than as no data.

    THE LAST BLOCK IS FLAGGED `provisional` AND THE CHART MUST SHOW IT AS
    SUCH. It ends on the as-of date, which is the newest case APHIS has
    published -- and the file is written some days after that, so the most
    recent days are still collecting late reports. A full-height bar there
    invites a reader to compare a settling week against seven finished ones
    and conclude the outbreak has turned, which is the part-period failure
    `annual_span()` exists to stop on the retention chart.

    ONLY THE LAST ONE IS FLAGGED, and that is a measurement rather than a
    guess: the observed gap between the file's newest case and its own
    Last-Modified was two days, well inside one block, so the block before it
    is complete. If that lag ever grows past a week this is wrong and the
    flag has to follow it.
    """
    first = min((r["date"] for r in rows), default=None)
    if first is None:
        return []
    out = []
    for i in range(blocks - 1, -1, -1):
        end = d - timedelta(days=WEEK * i)
        start = end - timedelta(days=WEEK - 1)
        if end < first:
            continue
        out.append({"start": start, "end": end,
                    "count": new_between(rows, start, end),
                    "provisional": i == 0})
    return out


# ── Breakdowns ──────────────────────────────────────────────────────────────

def by_state(rows: list[dict], d: date) -> list[dict]:
    """Cases by Mexican state, biggest first, with the unlocated bucket last.

    `NO_STATE` is kept in the list rather than dropped. On the 2026-11-10 file
    it was 24 cases and every one of them was from the newest eight days, so
    hiding it would quietly remove the most recent week from a chart a reader
    is consulting for exactly that week.
    """
    agg: dict[str, dict] = {}
    for r in rows:
        if r["date"] > d:
            continue
        a = agg.setdefault(r["state"], {"state": r["state"], "total": 0,
                                        "active": 0, "nearest": None})
        a["total"] += 1
        if _is_active(r["date"], d):
            a["active"] += 1
        if r["miles"] is not None:
            a["nearest"] = (r["miles"] if a["nearest"] is None
                            else min(a["nearest"], r["miles"]))
    out = sorted(agg.values(), key=lambda a: -a["total"])
    return ([a for a in out if a["state"] != NO_STATE]
            + [a for a in out if a["state"] == NO_STATE])


def by_species(rows: list[dict], d: date) -> list[dict]:
    agg: dict[str, int] = {}
    n = 0
    for r in rows:
        if r["date"] > d:
            continue
        agg[r["species"]] = agg.get(r["species"], 0) + 1
        n += 1
    return [{"species": k, "count": v, "share": (v / n if n else 0.0)}
            for k, v in sorted(agg.items(), key=lambda kv: -kv[1])]


def cattle_share(rows: list[dict], d: date) -> float | None:
    """The bovine share of cases, which is the figure this page is about.

    Named rather than left to a reader to pick off a species chart: on a
    feeder-cattle dashboard the question is how much of this is cattle, and
    the answer -- a clear majority -- is the reason the panel is here.
    """
    sp = by_species(rows, d)
    if not sp:
        return None
    return sum(s["share"] for s in sp if s["species"] == "Bovine")


DISTANCE_BANDS = ((0, 25), (26, 50), (51, 75), (76, 100))


def by_distance(rows: list[dict], d: date) -> list[dict]:
    """Cases by how far from the US line they were found.

    The precise geography the centroid map cannot show. Bands rather than a
    raw histogram because the column is APHIS's own APPROXIMATE mileage -- it
    is rounded to the mile and should not be read to a finer resolution than
    it is published at.
    """
    out = []
    for lo, hi in DISTANCE_BANDS:
        n = sum(1 for r in rows
                if r["date"] <= d and r["miles"] is not None
                and lo <= r["miles"] <= hi)
        act = sum(1 for r in rows
                  if r["miles"] is not None and lo <= r["miles"] <= hi
                  and _is_active(r["date"], d))
        out.append({"low": lo, "high": hi, "count": n, "active": act})
    return out


def nearest(rows: list[dict], d: date, active_only: bool = True):
    """The closest case to the border, and when it was confirmed."""
    pool = [r for r in rows
            if r["miles"] is not None and r["date"] <= d
            and (not active_only or _is_active(r["date"], d))]
    if not pool:
        return None
    r = min(pool, key=lambda r: (r["miles"], -r["date"].toordinal()))
    return {"miles": r["miles"], "date": r["date"], "state": r["state"],
            "species": r["species"]}


def unmapped_states(rows: list[dict]) -> list[str]:
    """States in the feed that the map has no coordinate for.

    Reported on the page rather than swallowed. A state missing from a bubble
    map is indistinguishable from a state with no cases, which is the worst
    way for this to fail -- it would read as good news.
    """
    return sorted({r["state"] for r in rows
                   if r["state"] not in MX_STATE_COORDS
                   and r["state"] != NO_STATE})


# ── The US side ─────────────────────────────────────────────────────────────

_US_TOTAL_DOM = "Total Cases - Domestic"
_US_TOTAL_ALL = "Total Cases"


def parse_us(text: str) -> dict:
    """Monthly US counts out of the Tableau view's CSV export.

    The export is a crosstab of one worksheet, so each month appears on
    several rows: one carrying the two totals and one per measure carrying a
    value under `Measure Values`. They are folded back into a month record
    here.

    ONLY THE MOST RECENT FOUR MONTHS ARE IN IT, because that is what the
    worksheet draws -- the dashboard's own note says so. `months` is therefore
    a window, never the series, and `all_time` is deliberately absent rather
    than summed from it. The one all-time figure that IS exact is `active`:
    an active US case is a recent one, so the window contains every one.
    """
    months: dict[str, dict] = {}
    order: list[str] = []
    for raw in csv.DictReader(io.StringIO(text)):
        label = (raw.get("Month of Confirmed Date") or "").strip()
        if not label:
            continue
        if label not in months:
            months[label] = {"label": label, "month": _us_month(label),
                             "domestic": None, "total": None,
                             "active": None, "inactive": None}
            order.append(label)
        m = months[label]
        measure = (raw.get("Measure Names") or "").strip()
        if not measure:
            m["domestic"] = _int(raw.get(_US_TOTAL_DOM))
            m["total"] = _int(raw.get(_US_TOTAL_ALL))
        elif measure.startswith("Active"):
            m["active"] = _int(raw.get("Measure Values"))
        elif measure.startswith("Inactive"):
            m["inactive"] = _int(raw.get("Measure Values"))
    out = [months[k] for k in order]
    out.sort(key=lambda m: (m["month"] or ""))
    act = [m["active"] for m in out if m["active"] is not None]
    return {
        "months": out,
        # Exact all-time, for the reason in the docstring.
        "active": sum(act) if act else None,
        "window_domestic": sum(m["domestic"] or 0 for m in out) or None,
        "window_total": sum(m["total"] or 0 for m in out) or None,
    }


def _us_month(label: str):
    """'August 2026' -> '2026-08'. None if it will not parse."""
    try:
        return datetime.strptime(label.strip(), "%B %Y").strftime("%Y-%m")
    except ValueError:
        return None


def _int(v):
    s = str(v if v is not None else "").strip().replace(",", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def fetch_us(url: str = SOURCE_US, timeout: int = 30) -> dict:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return parse_us(r.content.decode("utf-8-sig"))


# ── One call for the page ───────────────────────────────────────────────────

def load_all(schema: int = SCHEMA) -> dict:
    """Both feeds, with the US half allowed to fail on its own.

    THE US HALF IS ON A HOST NOTHING ELSE IN THIS REPO READS.
    `www.aphis.usda.gov` is already fetched from the deployed app by
    `letter/sources.AMS_3208_PDF` and `apps/beef_cutout/am_cutout.py`, so the
    Mexican feed is on proven ground; `publicdashboards.dl.usda.gov` is not,
    and `marsapi.ams.usda.gov` is the standing proof that a USDA host can be
    unreachable from Streamlit Community Cloud. So it fails soft and alone:
    `us` comes back None, the US panel says the feed is unavailable and links
    out, and the Mexican half -- which is the substance of the tab and the
    half that can do week-over-week -- is untouched.

    `schema` is in the signature so a caller can pass it into a cache key. It
    is unused by design, and it carries NO leading underscore: Streamlit drops
    an underscore-prefixed argument from the key, which is the half of that
    trap that looks fixed and is not.
    """
    mx, mx_err = None, None
    try:
        mx = fetch_mexico()
    except Exception as exc:                      # noqa: BLE001
        mx_err = str(exc)
    us, us_err = None, None
    try:
        us = fetch_us()
    except Exception as exc:                      # noqa: BLE001
        us_err = str(exc)
    return {"mx": mx, "mx_error": mx_err, "us": us, "us_error": us_err}
