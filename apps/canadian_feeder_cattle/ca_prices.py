"""
What a Canadian feeder is worth, and how many cattle Canada is killing.

The counterpart to `mx_prices.py` on the other border, and it is NOT the same
shape -- which is the first thing to know about it.

    JSA.CME_FEEDER_CATTLE.CA_LIVESTOCK_PRICES   AMS 3213, US$/cwt by region
    JSA.CME_FEEDER_CATTLE.CA_SLAUGHTER          AMS 3213, Canadian FI head

**THERE IS NO US-CANADA CROSSINGS REPORT. ANYWHERE.** The Mexican side of this
page is built on AMS 3486 (`Mexico to United States Feeder Cattle Import
Summary`) and AMS 3629 (`U.S. - Mexico Livestock Imports/Exports`), and neither
has a Canadian counterpart: a sweep of all 1,051 MARS reports and all 151 LMR
datamart reports on 2026-10-07 returned exactly one Canadian livestock report,
and this is it. So the Canada view CANNOT lead with a head count the way the
Mexico view does, and it must say so rather than leaving a reader to wonder
where the crossings tile went. Monthly head counts exist only in Census trade
data, at roughly a six-week lag, and are a separate job.

What 3213 does carry is the half Mexico does badly: the ORIGIN-SIDE PRICE.

**AND IT IS BETTER THAN THE MEXICAN COMPARISON, NOT WORSE.** `mx_prices.py`
carries three health warnings and two of them simply do not apply here:

* Tamaulipas is not where Mexican feeders come from. **Alberta and Saskatchewan
  are exactly where Canadian feeders come from**, so there is no wrong-state
  caveat to print.
* Tamaulipas quotes MXN/kg and needs an FX join that can restate a past sale.
  **AMS publishes 3213 already in US dollars per hundredweight** -- so there is
  no FX table, no backward-reaching join, and no `FX_USDMXN`.
* Tamaulipas bands in kg and needs midpoint matching onto the AMS lb ladder.
  **3213 bands in pounds on 401-500 / 501-600 / 601-700 / 701-800 / 801-900**,
  which is the AMS ladder already.

The two hardest pieces of `mx_prices.py` therefore have no equivalent in here.
What this module owns instead is four traps of its own, all of them measured
against the live feed on 2026-10-07 rather than assumed.

THE WEEK ENDS ON `report_end_date` AND NOWHERE ELSE.
`report_date` is the MONDAY of the week covered; `report_begin_date` is the
Sunday before it and `report_end_date` the Saturday after -- so the week ending
is **five days after the date the row calls its own**. Labelling a tile from
`report_date` produces a week-ending that is wrong by most of a week and looks
entirely plausible, which is precisely the failure CLAUDE.md records for the
hand-typed deck ("as of 8/19/26" against a week ending 9/19/26). It cannot be
derived either: 31 of 3,499 rows are holiday-shifted to Tue/Mon/Sun. Read the
field.

THE CURRENCY IS CHECKED, NOT ASSUMED.
Every one of 3,499 rows reads `US Dollar` today. A Canadian report is exactly
the one where that could change, and a CAD price read as USD is a ~1.35x error
that renders perfectly, sorts correctly and sits in the right column -- the
`parentheses are negative` class of defect. `parse_prices` refuses any row whose
currency or price unit is not the expected one and records why, so a change in
the feed shows up as rejected rows rather than as a cheap Alberta.

USDA'S OWN CHANGE FIGURES ARE REPRODUCED, NEVER RECOMPUTED.
The slaughter section publishes `week_ago_volume`, `year_ago_volume`,
`current_YTD_volume`, `prior_YTD_volume` and `percent_change`. Those are
USDA's arithmetic on USDA's revisions; recomputing them from our own stored
history would produce a table that is neither source's, the rule
`letter/sterling.py` already follows for the Sterling tracker.

NULL IS NOT ZERO. 170 of 2,590 feeder rows carry a null `current_price` -- a
band that did not trade that week. They are dropped, not zero-filled, for the
same reason a withheld cash region is not "0 head".

**IT DOES NOT IMPORT `requests`, AND THAT IS DELIBERATE** -- the standing rule
for this page, which `tests/test_ca_prices.py` asserts by AST exactly as
`tests/test_mx_prices.py` does for `mx_prices`. Two reasons, and the second is
the binding one: `border.py` has no HTTP path so the Streamlit process cannot
acquire one, and `marsapi.ams.usda.gov` rejects Streamlit Community Cloud's IPs
anyway (CLAUDE.md, confirmed 2026-10-04). A live fetch from the page would fail
in production whatever we wanted. `deploy/ca_livestock.py` does the fetching on
the droplet and calls the parsers in here, so the cron and the page can never
disagree about what a report says.

HISTORY STARTS 2024-06-01 AND THAT IS ALL AMS KEEPS -- 121 weeks as of
2026-09-26, with two 14-day gaps that are both Christmas week (2024-12-28 ->
2025-01-11 and 2025-12-27 -> 2026-01-10). Those are an annual closure, not a
feed failure, and `missing_weeks()` knows the difference.

PUBLICATION LAG IS 9-17 DAYS AFTER THE WEEK ENDS, median 10. Any staleness rule
written against a weekly cadence will cry every single week; `MAX_AGE_DAYS`
below is set from the measured distribution instead.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import socket
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
APPS = REPO / "apps"

# ── The feed ─────────────────────────────────────────────────────────────────

SLUG = "3213"
SLUG_NAME = "AMS_3213"
REPORT_TITLE = "Weekly Canadian Livestock and Poultry Summary"

#: SECTIONS ARE A PATH SEGMENT, not a query parameter -- the trap
#: `direct_reports.py` documents for MARS and `leverage.py` for the datamart.
#: The bare slug answers 200 with header rows and no data.
SECTION_PRICE = "Report Detail Price"
SECTION_SLAUGHTER = "Report Detail Slaughter"

PRICE_TABLE = "JSA.CME_FEEDER_CATTLE.CA_LIVESTOCK_PRICES"
SLAUGHTER_TABLE = "JSA.CME_FEEDER_CATTLE.CA_SLAUGHTER"

#: The only currency and unit this module will accept. See the docstring.
CURRENCY = "US Dollar"
PRICE_UNIT = "Per Cwt"
COUNTRY = "Canada"

FEEDER = "Feeder Cattle"
SLAUGHTER_CATTLE = "Slaughter Cattle"

#: Measured 2026-10-07: Alberta 1,424 rows, Ontario 1,401, Saskatchewan 674.
#: WESTERN FIRST, and not alphabetically -- Alberta and Saskatchewan are where
#: cattle bound for the US actually come from, and Ontario is an eastern market
#: that mostly does not cross. A panel that led with Ontario would be ordering
#: by nothing and burying the relevant one.
REGIONS = ("Alberta", "Saskatchewan", "Ontario")
WESTERN = ("Alberta", "Saskatchewan")

#: In POUNDS, already the AMS border ladder. No midpoint matching needed.
FEEDER_WEIGHTS = ("401-500", "501-600", "601-700", "701-800", "801-900")

#: The classes 3213 prints for feeders. Sex is kept separate for the same
#: reason mx_prices keeps it: pairing a heifer against a steer quote reads as a
#: discount that is really a sex difference.
FEEDER_CLASSES = ("Steers", "Heifers")

#: Slaughter classes worth carrying. 3213 also prints Hogs, Sheep and two Hens
#: lines; this page is a cattle page.
SLAUGHTER_CLASSES = ("Cattle", "Calves")

#: Measured lag from week-ending to publication: min 9, median 10, max 17 days
#: over 3,499 rows. 28 allows the observed worst case plus a week, so the panel
#: marks a genuinely stopped feed and stays quiet on an ordinary one. CLAUDE.md:
#: a freshness panel that fires every week is one nobody reads in the week it
#: matters.
MAX_AGE_DAYS = 28

#: The annual year-end closure, in ISO week numbers. MEASURED, not assumed:
#: the feeder ladder runs 2024-12-21 (ISO 2024-W51) straight to 2025-01-11
#: (ISO 2025-W02), and 2025-12-20 (W51) to 2026-01-10 (W02). So TWO ISO weeks
#: are lost each year-end, 52 and 1, and an earlier draft of this module had
#: only `(1,)` -- which reported the other half of every closure as missing
#: data. 53 is included because an ISO year occasionally has one.
#:
#: The closure arrives in TWO different shapes and both must be handled. In
#: 2024-12-28 and 2025-12-27 AMS DID publish a report and every price in it was
#: null, so the week vanishes once nulls are dropped; in 2025-01-04 and
#: 2026-01-03 no report exists at all. Same closure, two signatures.
HOLIDAY_ISO_WEEKS = (52, 53, 1)

#: Bumped whenever load() changes the SHAPE of what it returns. Passed into the
#: cached fetch purely as part of the key -- st.cache_data keys on the decorated
#: function's own code and never on the modules it calls, the trap CLAUDE.md
#: records for leverage.SCHEMA, am_cutout.SCHEMA and mx_prices.SCHEMA. Without
#: it a new key renders "—" and nothing raises.
#:
#: 1 (2026-10-07): first version.
SCHEMA = 1


# ── Parsing ──────────────────────────────────────────────────────────────────

def _date(value):
    """'09/21/2026' or '10/06/2026 07:06:18' -> date, or None."""
    if not value:
        return None
    try:
        return dt.datetime.strptime(str(value).split()[0], "%m/%d/%Y").date()
    except (ValueError, TypeError):
        return None


def _num(value):
    """float or None. AMS sends '' and null for a band that did not trade."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reject(rejects, reason):
    if rejects is not None:
        rejects.append(reason)


def iso(d):
    """(iso_year, iso_week) -- the week identity this module keys everything on.

    NOT the raw `report_end_date`, and that distinction is load-bearing. AMS
    republished the week of 2025-10-06 with a SHIFTED date window: the first
    publication (2025-10-21) ended the week on Sunday 2025-10-12, the
    correction (2025-10-28) ended it on Saturday 2025-10-11. All 31
    region/class/weight keys overlap exactly, so keyed on the raw date both
    survive, `latest_week` picks the Sunday -- and the page then shows the
    SUPERSEDED figures and silently drops the correction. Keyed on the ISO week
    they collapse to one and the later publication wins, which is what a
    correction is for.

    It also makes the 118-Saturdays-and-one-Sunday series a clean weekly grid,
    so gap detection and week-on-week changes stop depending on a 7-day rhythm
    the feed does not actually keep.
    """
    cal = d.isocalendar()
    return (cal[0], cal[1])


def _iso_back(week, n: int):
    """The ISO week `n` weeks before `week`, via its own Monday."""
    monday = dt.date.fromisocalendar(week[0], week[1], 1) - dt.timedelta(days=7 * n)
    return iso(monday)


def parse_prices(results, rejects=None) -> list:
    """
    AMS 3213 `Report Detail Price` rows -> normalised records.

    Returns [{week_ending, report_date, published, commodity, region, sex,
              weight_group, grade, price, sale_type}], newest week first.

    REJECTIONS ARE COUNTED, NOT SWALLOWED. `rejects` collects a one-line reason
    per dropped row so the panel can say "12 rows rejected: unexpected currency"
    instead of quietly showing a shorter table. A row is rejected for a currency
    or unit this module does not understand; a row with a null price is DROPPED
    rather than rejected, because a band that did not trade is normal and
    reporting it as a fault would bury a real one.
    """
    out = []
    for r in results or []:
        week_ending = _date(r.get("report_end_date"))
        if week_ending is None:
            _reject(rejects, "row with no report_end_date")
            continue

        # THE CURRENCY CHECK. See the module docstring -- this is the one that
        # would otherwise render a 1.35x error perfectly.
        currency = (r.get("currency") or "").strip()
        unit = (r.get("price_unit") or "").strip()
        if currency != CURRENCY or unit != PRICE_UNIT:
            _reject(rejects,
                    f"{week_ending} {r.get('region')} {r.get('class')} "
                    f"{r.get('weight_group')}: expected {CURRENCY}/{PRICE_UNIT}, "
                    f"got {currency or '?'}/{unit or '?'}")
            continue

        price = _num(r.get("current_price"))
        if price is None:
            continue  # a band that did not trade. Not a fault.

        out.append({
            "week_ending": week_ending,
            "report_date": _date(r.get("report_date")),
            "published": _date(r.get("published_date")),
            "commodity": (r.get("commodity") or "").strip(),
            "region": (r.get("region") or "").strip(),
            "sex": (r.get("class") or "").strip(),
            "weight_group": (r.get("weight_group") or "").strip(),
            "grade": (r.get("quality_grade") or "").strip() or None,
            "sale_type": (r.get("sale_type") or "").strip() or None,
            "price": price,
        })
    # week_ending is deliberately NOT a key field: _dedupe keys on the ISO week
    # so a correction with a shifted date window collapses onto its original.
    return _dedupe(out, ("commodity", "region", "sex", "weight_group", "grade"))


def parse_slaughter(results, rejects=None) -> list:
    """
    AMS 3213 `Report Detail Slaughter` rows -> normalised records.

    USDA'S OWN CHANGE FIGURES ARE CARRIED THROUGH UNTOUCHED -- `pct_change`,
    `ytd` and `ytd_prior` are read, never recomputed. They are USDA's arithmetic
    over USDA's revisions, and substituting ours would produce a table that is
    neither source's. `letter/sterling.py` follows the same rule for the same
    reason.
    """
    out = []
    for r in results or []:
        week_ending = _date(r.get("report_end_date"))
        if week_ending is None:
            _reject(rejects, "row with no report_end_date")
            continue
        unit = (r.get("volume_unit") or "").strip()
        if unit and unit != "Head":
            _reject(rejects, f"{week_ending} {r.get('class')}: volume in {unit}, not Head")
            continue
        head = _num(r.get("current_volume"))
        if head is None:
            continue
        out.append({
            "week_ending": week_ending,
            "report_date": _date(r.get("report_date")),
            "published": _date(r.get("published_date")),
            "species": (r.get("class") or "").strip(),
            "head": head,
            "head_week_ago": _num(r.get("week_ago_volume")),
            "head_year_ago": _num(r.get("year_ago_volume")),
            "ytd": _num(r.get("current_YTD_volume")),
            "ytd_prior": _num(r.get("prior_YTD_volume")),
            "pct_change": _num(r.get("percent_change")),
        })
    return _dedupe(out, ("species",))


def _dedupe(rows: list, key_fields: tuple) -> list:
    """
    Newest `published` wins per (ISO week, key), then newest week first.

    KEYED ON THE ISO WEEK, NEVER ON `week_ending`. A correction can arrive with
    a shifted date window -- see `iso()`, which documents the live example this
    rule was written from. Keyed on the raw date, the original and its
    correction are two different weeks, both survive, and the page shows the
    one AMS withdrew. There is no error, no duplicate-looking row and no clue.

    It also normalises away the one Sunday `week_ending` in 119 weeks, so
    everything downstream can assume a clean weekly grid.
    """
    best = {}
    for row in rows:
        key = (iso(row["week_ending"]),) + tuple(row.get(f) for f in key_fields)
        prior = best.get(key)
        if prior is None or (row.get("published") or dt.date.min) >= (prior.get("published") or dt.date.min):
            best[key] = row
    return sorted(best.values(),
                  key=lambda r: (r["week_ending"], str(r.get("region") or ""),
                                 str(r.get("species") or r.get("sex") or ""),
                                 str(r.get("weight_group") or "")),
                  reverse=True)


# ── Arithmetic ───────────────────────────────────────────────────────────────

def latest_week(rows: list):
    """The newest week_ending present, or None."""
    return max((r["week_ending"] for r in rows), default=None)


def feeder_ladder(rows: list, region: str, week_ending=None) -> list:
    """
    One region's feeder ladder for a week: [{weight_group, Steers, Heifers}].

    Ordered by FEEDER_WEIGHTS, light to heavy, and a weight that did not trade
    is returned with None rather than omitted -- a missing rung reads as a
    ladder that stops, which is a different statement from one that has a hole.
    """
    week = week_ending or latest_week([r for r in rows if r["region"] == region])
    if week is None:
        return []
    by = {}
    for r in rows:
        if r["commodity"] != FEEDER or r["region"] != region or r["week_ending"] != week:
            continue
        by.setdefault(r["weight_group"], {})[r["sex"]] = r["price"]
    out = []
    for wt in FEEDER_WEIGHTS:
        prices = by.get(wt, {})
        out.append({"weight_group": wt,
                    "Steers": prices.get("Steers"),
                    "Heifers": prices.get("Heifers")})
    return out


def price_change(rows: list, region: str, sex: str, weight_group: str,
                 weeks: int = 1):
    """
    (latest, prior, change) for one rung, or (None, None, None).

    NEVER SUBTRACTS ACROSS A HOLE. `weeks` back means exactly that many ISO
    weeks earlier, not "the previous row we happen to have" -- the rule
    `letter/sources.fetch_futures` follows. Across the year-end closure the
    previous row is three weeks old and the difference is three weeks of market
    dressed as one, which looks like an ordinary move and is not.

    COUNTED IN ISO WEEKS, NOT IN DAYS. A `-7 days` step is right 118 times out
    of 119 and wrong across the one Sunday `week_ending` the feed contains,
    where it would silently find nothing and report no change on a week that
    has one. See `iso()`.
    """
    series = {iso(r["week_ending"]): r["price"] for r in rows
              if r["region"] == region and r["sex"] == sex
              and r["weight_group"] == weight_group}
    if not series:
        return None, None, None
    newest = max(series)
    latest, prior = series.get(newest), series.get(_iso_back(newest, weeks))
    if latest is None or prior is None:
        return latest, None, None
    return latest, prior, round(latest - prior, 2)


def slaughter_summary(rows: list, species: str = "Cattle", week_ending=None):
    """
    The week's Canadian FI kill for one species, with USDA's own YTD figures.

    `pct_change` is USDA's number for the YTD comparison and is passed straight
    through. It is NOT `head` against `head_year_ago`, which is a weekly
    comparison -- two different questions that both look like "percent change",
    and conflating them is the two-clocks error in miniature.
    """
    week = week_ending or latest_week([r for r in rows if r["species"] == species])
    if week is None:
        return {}
    for r in rows:
        if r["species"] == species and r["week_ending"] == week:
            return dict(r)
    return {}


def missing_weeks(rows: list) -> list:
    """
    ISO weeks absent from an otherwise weekly series, EXCLUDING the annual
    year-end closure. Returns [(iso_year, iso_week)].

    Every gap in 119 weeks on file is the year-end closure, which costs TWO ISO
    weeks (52 and 1) and not one. Flagging an annual closure as missing data
    trains a reader to ignore the one that is not -- and an earlier draft of
    this function did exactly that, reporting 2024-12-28 and 2025-12-27 as
    holes because it excluded only week 1.

    Walked in ISO weeks rather than 7-day steps so the one Sunday `week_ending`
    in the series does not shift the grid and manufacture a gap every week
    after it.
    """
    weeks = sorted({iso(r["week_ending"]) for r in rows})
    out = []
    for a, b in zip(weeks, weeks[1:]):
        step = _iso_back(b, 1)
        run = []
        while step != a and step > a:
            if step[1] not in HOLIDAY_ISO_WEEKS:
                run.append(step)
            step = _iso_back(step, 1)
        out.extend(reversed(run))
    return out


def staleness(rows: list, today):
    """
    (week_ending, days_behind, is_stale) for the newest week on file.

    `is_stale` is measured against MAX_AGE_DAYS, which comes from the feed's
    MEASURED publication lag (9-17 days) rather than from its weekly cadence.
    A rule written against "weekly" marks this feed stale every single week on
    perfectly current data -- the defect CLAUDE.md records for the board's
    leverage tension suppressing itself every Thursday.
    """
    week = latest_week(rows)
    if week is None:
        return None, None, True
    behind = (today - week).days
    return week, behind, behind > MAX_AGE_DAYS


# ── Snowflake ────────────────────────────────────────────────────────────────

#: ATTEMPTED SEPARATELY, AND ITS FAILURE IGNORED. The schema already exists,
#: and the identity that runs this may not hold CREATE SCHEMA on the database:
#: Ross's CME_INGEST_ROLE does not, and `CREATE SCHEMA IF NOT EXISTS` still
#: needs the grant even when it would do nothing. Inside DDL below it aborted
#: the whole run with "Insufficient privileges to operate on database 'JSA'"
#: against a schema sitting right in front of it.
#:
#: The comment this replaces argued the grant was proven, because the portal
#: created JSA.BOXED_BEEF on its first run. That is the DEPLOYED identity --
#: KOLTENPOSTIN as ACCOUNTADMIN -- and this job runs as neither. A capability
#: demonstrated by one role says nothing about another, which is the same
#: mistake CLAUDE.md records as "a read test does not clear an ETL".
#:
#: If the schema really is absent, the CREATE TABLE below says so.
SCHEMA_DDL = "CREATE SCHEMA IF NOT EXISTS JSA.CME_FEEDER_CATTLE"

DDL = [
    f"""CREATE TABLE IF NOT EXISTS {PRICE_TABLE} (
            WEEK_ENDING   DATE          NOT NULL,
            REPORT_DATE   DATE,
            PUBLISHED     DATE,
            COMMODITY     VARCHAR(40)   NOT NULL,
            REGION        VARCHAR(40)   NOT NULL,
            SEX           VARCHAR(20)   NOT NULL,
            WEIGHT_GROUP  VARCHAR(20)   NOT NULL,
            GRADE         VARCHAR(60),
            SALE_TYPE     VARCHAR(40),
            PRICE_USD_CWT NUMBER(9,2)   NOT NULL,
            RECORDED_AT   TIMESTAMP_NTZ NOT NULL,
            RECORDED_BY   VARCHAR(128)
        )""",
    f"""CREATE TABLE IF NOT EXISTS {SLAUGHTER_TABLE} (
            WEEK_ENDING    DATE          NOT NULL,
            REPORT_DATE    DATE,
            PUBLISHED      DATE,
            SPECIES        VARCHAR(40)   NOT NULL,
            HEAD           NUMBER(12,0)  NOT NULL,
            HEAD_WEEK_AGO  NUMBER(12,0),
            HEAD_YEAR_AGO  NUMBER(12,0),
            YTD            NUMBER(14,0),
            YTD_PRIOR      NUMBER(14,0),
            PCT_CHANGE     NUMBER(9,2),
            RECORDED_AT    TIMESTAMP_NTZ NOT NULL,
            RECORDED_BY    VARCHAR(128)
        )""",
]


def enabled() -> bool:
    """Snowflake is configured. The same flag the rest of the portal uses."""
    return os.getenv("USE_SNOWFLAKE", "").strip().lower() in ("1", "true", "yes", "on")


def _load_db():
    """
    apps/cme_feeder_cattle/snowflake_db.py under a PRIVATE module name.

    The trick draft_store._load_db(), sources._load_fci_db() and
    am_cutout._load_db() all use, for the same reason: snowflake_db.py exists
    five times in this repo and Python caches modules by NAME, so a plain
    `import snowflake_db` gets whichever page loaded first. "_ca_prices_db" can
    never join that collision.
    """
    path = APPS / "cme_feeder_cattle" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_ca_prices_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ca_prices_db"] = mod
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
    except Exception:
        pass
    _CONN = None


def _run(fn):
    """fn(cursor), reconnecting once -- a cached connection outlives its token."""
    for attempt in (1, 2):
        try:
            cur = _conn().cursor()
            try:
                return fn(cur)
            finally:
                cur.close()
        except Exception:
            _drop_conn()
            if attempt == 2:
                raise
    return None


def _who() -> str:
    try:
        host = socket.gethostname()
    except Exception:
        host = "?"
    return f"ca_livestock@{host}"[:128]


def ensure_table() -> str:
    """Create the schema and tables if missing. "" on success, else the reason."""
    if not enabled():
        return "Snowflake is not configured (USE_SNOWFLAKE is unset)."
    try:
        def go(cur):
            try:
                cur.execute(SCHEMA_DDL)
            except Exception:
                pass          # see SCHEMA_DDL — the grant is not required here
            for stmt in DDL:
                cur.execute(stmt)
        _run(go)
        return ""
    except Exception as e:
        return f"Could not reach Snowflake: {e}"


def bank_prices(rows: list) -> str:
    """
    Record price rows that are absent or whose price has changed.

    IDEMPOTENT, which is what makes a blunt cron schedule safe -- the same rule
    `am_cutout.bank()` follows. A re-run on an unchanged report writes nothing,
    so a catch-up costs one fetch and a run on a week AMS has not published yet
    is a no-op. There is no holiday calendar to maintain and none to get wrong.

    APPEND-ONLY. No UPDATE and no DELETE, so no write can bury the figure that
    was actually published and a correction is visible as a later row rather
    than as a value that silently moved. Same shape as JSA.LETTER.DRAFTS and
    JSA.BOXED_BEEF.CUTOUT_AM, for the same reasons.
    """
    if not rows:
        return ""
    if not enabled():
        return "Snowflake is not configured (USE_SNOWFLAKE is unset)."
    try:
        def go(cur):
            cur.execute(
                f"SELECT WEEK_ENDING, COMMODITY, REGION, SEX, WEIGHT_GROUP, PRICE_USD_CWT "
                f"FROM {PRICE_TABLE} QUALIFY ROW_NUMBER() OVER ("
                f"  PARTITION BY WEEK_ENDING, COMMODITY, REGION, SEX, WEIGHT_GROUP "
                f"  ORDER BY RECORDED_AT DESC) = 1")
            have = {(r[0], r[1], r[2], r[3], r[4]): (float(r[5]) if r[5] is not None else None)
                    for r in cur.fetchall()}
            who, new = _who(), []
            for row in rows:
                key = (row["week_ending"], row["commodity"], row["region"],
                       row["sex"], row["weight_group"])
                price = round(float(row["price"]), 2)
                if have.get(key) == price:
                    continue
                new.append((row["week_ending"], row["report_date"], row["published"],
                            row["commodity"], row["region"], row["sex"],
                            row["weight_group"], row["grade"], row["sale_type"],
                            price, who))
            if not new:
                return 0
            cur.executemany(
                f"INSERT INTO {PRICE_TABLE} (WEEK_ENDING, REPORT_DATE, PUBLISHED, "
                f"COMMODITY, REGION, SEX, WEIGHT_GROUP, GRADE, SALE_TYPE, "
                f"PRICE_USD_CWT, RECORDED_AT, RECORDED_BY) "
                f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP(),%s)", new)
            return len(new)
        n = _run(go)
        return "" if n is None else f"{n} price row(s) recorded"
    except Exception as e:
        return f"Could not write prices: {e}"


def bank_slaughter(rows: list) -> str:
    """Record slaughter rows that are absent or whose head count has changed."""
    if not rows:
        return ""
    if not enabled():
        return "Snowflake is not configured (USE_SNOWFLAKE is unset)."
    try:
        def go(cur):
            cur.execute(
                f"SELECT WEEK_ENDING, SPECIES, HEAD FROM {SLAUGHTER_TABLE} "
                f"QUALIFY ROW_NUMBER() OVER (PARTITION BY WEEK_ENDING, SPECIES "
                f"ORDER BY RECORDED_AT DESC) = 1")
            have = {(r[0], r[1]): (float(r[2]) if r[2] is not None else None)
                    for r in cur.fetchall()}
            who, new = _who(), []
            for row in rows:
                key = (row["week_ending"], row["species"])
                if have.get(key) == float(row["head"]):
                    continue
                new.append((row["week_ending"], row["report_date"], row["published"],
                            row["species"], row["head"], row["head_week_ago"],
                            row["head_year_ago"], row["ytd"], row["ytd_prior"],
                            row["pct_change"], who))
            if not new:
                return 0
            cur.executemany(
                f"INSERT INTO {SLAUGHTER_TABLE} (WEEK_ENDING, REPORT_DATE, PUBLISHED, "
                f"SPECIES, HEAD, HEAD_WEEK_AGO, HEAD_YEAR_AGO, YTD, YTD_PRIOR, "
                f"PCT_CHANGE, RECORDED_AT, RECORDED_BY) "
                f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP(),%s)", new)
            return len(new)
        n = _run(go)
        return "" if n is None else f"{n} slaughter row(s) recorded"
    except Exception as e:
        return f"Could not write slaughter: {e}"


def read_prices(limit_weeks: int = 120) -> list:
    """Newest-wins price rows from Snowflake, in `parse_prices` shape."""
    if not enabled():
        return []
    def go(cur):
        cur.execute(
            f"SELECT WEEK_ENDING, REPORT_DATE, PUBLISHED, COMMODITY, REGION, SEX, "
            f"WEIGHT_GROUP, GRADE, SALE_TYPE, PRICE_USD_CWT FROM {PRICE_TABLE} "
            f"QUALIFY ROW_NUMBER() OVER ("
            f"  PARTITION BY WEEK_ENDING, COMMODITY, REGION, SEX, WEIGHT_GROUP "
            f"  ORDER BY RECORDED_AT DESC) = 1 "
            f"ORDER BY WEEK_ENDING DESC LIMIT %s", (limit_weeks * 60,))
        return [{"week_ending": r[0], "report_date": r[1], "published": r[2],
                 "commodity": r[3], "region": r[4], "sex": r[5],
                 "weight_group": r[6], "grade": r[7], "sale_type": r[8],
                 "price": float(r[9])} for r in cur.fetchall()]
    return _run(go) or []


def read_slaughter(limit_weeks: int = 120) -> list:
    """Newest-wins slaughter rows from Snowflake, in `parse_slaughter` shape."""
    if not enabled():
        return []
    def go(cur):
        cur.execute(
            f"SELECT WEEK_ENDING, REPORT_DATE, PUBLISHED, SPECIES, HEAD, "
            f"HEAD_WEEK_AGO, HEAD_YEAR_AGO, YTD, YTD_PRIOR, PCT_CHANGE "
            f"FROM {SLAUGHTER_TABLE} QUALIFY ROW_NUMBER() OVER ("
            f"  PARTITION BY WEEK_ENDING, SPECIES ORDER BY RECORDED_AT DESC) = 1 "
            f"ORDER BY WEEK_ENDING DESC LIMIT %s", (limit_weeks * 8,))
        return [{"week_ending": r[0], "report_date": r[1], "published": r[2],
                 "species": r[3], "head": float(r[4]),
                 "head_week_ago": _num(r[5]), "head_year_ago": _num(r[6]),
                 "ytd": _num(r[7]), "ytd_prior": _num(r[8]),
                 "pct_change": _num(r[9])} for r in cur.fetchall()]
    return _run(go) or []
