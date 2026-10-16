"""
USDA AMS daily slaughter estimates -- the only place a SATURDAY kill exists.

Nothing else on this dashboard can answer a day-of-week question. The NASS tab
and the SJ_LS712 feed behind the AMS tab are both WEEKLY (week-ending Saturday)
totals, so a Saturday figure is not a slice of them -- it is a different report.
That report is AMS 3208, "Daily Livestock and Poultry Slaughter", published
every business day: PDF at `ams.usda.gov/mnreports/ams_3208.pdf`, viewer at
`mymarketnews.ams.usda.gov/viewReport/3208`.

No new secret. It reuses the MARS_API_KEY this page already holds for report
3658.

THE SLUG IS SECTIONED, which is the trap the cme-feeder-cattle-index repo's
`direct_reports.py` documents at length for the direct/video slugs:

    GET /reports/3208                           -> HTTP 200, narrative rows,
                                                   NO head counts at all
    GET /reports/3208/Report Livestock Commodity -> per-day head, all species
    GET /reports/3208/Report Livestock Class     -> Steers/Heifers vs Cows/Bulls

The bare call does not fail. It answers 200 with plausible-looking rows that
simply have no `slaughter` key, which reads exactly like a report that has
stopped publishing. The section name is a PATH SEGMENT, not a query param --
`?section=...` is accepted and ignored.

Three things about the data that will produce a wrong number if assumed:

- **HISTORY STARTS 2024-01-01.** One unfiltered call returns the whole series
  (~6,900 commodity rows) and that is all MARS keeps. Any question about 2023
  or earlier is unanswerable here, so `FIRST_YEAR` is surfaced on the page
  rather than left for a reader to infer from an axis.

- **One slaughter_date appears in several reports.** Friday's report carries
  Friday as `period="Current"` AND Saturday as a PROJECTION, then Monday's
  report restates Saturday as `period="Previous"`. Dedupe by taking the row
  with the latest `report_date`; `_latest_by_day` does this.

- **Saturdays revise UP far more often than down.** 14 of the first 145
  Saturdays on file were ever revised, and the moves are not small: 2024-11-30
  went 39,000 -> 47,000 and 2024-07-06 went 42,000 -> 47,000. So today's
  Saturday number is a forecast and tomorrow's comparison is against settled
  history -- `is_projection` marks it and the page says so.

WHY A BIG SATURDAY IS USUALLY NOT NEWS, which is the whole reason this module
computes week context instead of just plotting a series. Every Saturday at or
above 38,000 head between 2024-01-01 and 2026-10-02 fell in a week that had
lost a weekday to a holiday -- New Year's, Memorial Day, July 4th, Labor Day,
Thanksgiving. The 2026-09-12 Saturday of 70,000, the largest on file, sat in a
Labor Day week whose Monday killed 2,000; the week still totalled only 505,000
against a 2026 median full week of 527,500, so the sixth day recovered most of
the lost Monday and not all of it. A Saturday number quoted without its week is
therefore close to meaningless, and `saturday_frame` never returns one.

`week_to_date` is the report's own running total and is the free audit: Mon-Sat
summed must equal the Saturday row's WTD. `reconcile()` checks it so a silent
dedupe mistake shows up as a number rather than a plausible chart.

VENDORED TWICE -- here and at the root of the beef-weight-dashboard repo,
which runs this same page standalone. The two must stay byte-identical;
`tests/test_no_drift.py` in cme-feeder-cattle-index compares them and lists
this name in SHARED.

The in-process `sys.modules` collision CLAUDE.md describes for
`snowflake_db.py` does NOT apply: those five copies live in one Streamlit
process, where whichever page imports first wins. These two live in separate
deployments and never meet. The risk here is the quieter one -- a fix landing
in one repo and not the other, invisible until someone compares the two live
pages -- which is exactly what the drift test is for.
"""
from datetime import date, datetime, timedelta
from urllib.parse import quote

import pandas as pd
import requests

MARS_BASE   = "https://marsapi.ams.usda.gov/services/v1.2/reports"
REPORT_ID   = 3208
SEC_COMMODITY = "Report Livestock Commodity"
SEC_CLASS     = "Report Livestock Class"

REPORT_PDF  = "https://www.ams.usda.gov/mnreports/ams_3208.pdf"
REPORT_VIEW = "https://mymarketnews.ams.usda.gov/viewReport/3208"

# MARS keeps roughly three years of this slug and no more. Surfaced on the page
# so "the last time" is always read against a stated window.
FIRST_YEAR = 2024

# A weekday under this fraction of the week's own weekday median is treated as
# a lost day -- a holiday or a plant disruption. It is a ratio rather than a
# fixed head count so it keeps working as the herd contracts and the whole
# level drifts down: a 2024 holiday Monday and a 2026 one are both ~2,000 head
# against very different normal weeks.
LOST_DAY_FRAC = 0.50


def _num(v):
    """AMS sends counts as strings -- "489000", not 489000. Blank/NA -> None."""
    if v is None:
        return None
    t = str(v).strip().replace(",", "")
    if not t or t.upper() in ("NA", "N/A", "NULL", "-"):
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def _mdy(s):
    """MM/DD/YYYY, sometimes with a trailing clock time -> date."""
    if not s:
        return None
    try:
        m, d, y = str(s).split()[0].split("/")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def fetch(key: str, commodity: str = "Cattle") -> dict:
    """
    Pull the whole daily series for one commodity.

    Returns {"rows": [...], "published": date} or {"error": "..."}. Never
    raises -- the caller is a dashboard view and a dead feed should say so in
    the page, not blank it.
    """
    if not key:
        return {"error": "MARS_API_KEY not configured"}

    # No q= date filter on purpose. The full series is one request and well
    # under the 100,000-row allowance (~6,900 rows), and guessing a date field
    # name on a MARS slug is the documented way to get zero rows and no error.
    try:
        r = requests.get(f"{MARS_BASE}/{REPORT_ID}/{quote(SEC_COMMODITY)}",
                         auth=(key, ""), timeout=(5, 180))
        if r.status_code in (204, 404):
            return {"error": f"AMS returned HTTP {r.status_code}"}
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

    results = payload.get("results", payload) if isinstance(payload, dict) else payload
    if not results:
        return {"error": "report 3208 returned no rows"}

    rows, published = [], None
    for x in results:
        if str(x.get("commodity", "")).strip() != commodity:
            continue
        sd = x.get("slaughter_date")
        hd = _num(x.get("slaughter"))
        rd = _mdy(x.get("report_date"))
        if not sd or hd is None or rd is None:
            continue
        try:
            day = date.fromisoformat(str(sd)[:10])
        except ValueError:
            continue
        rows.append({
            "day": day, "head": hd, "report_date": rd,
            "period": str(x.get("period", "")).strip(),
            "revision": str(x.get("revision", "")).strip(),
            "week_to_date": _num(x.get("week_to_date")),
            "year_ago": _num(x.get("year_ago")),
        })
        p = _mdy(str(x.get("published_date") or ""))
        if p and (published is None or p > published):
            published = p

    if not rows:
        return {"error": f"no {commodity} rows in report 3208"}
    return {"rows": rows, "published": published}


def _latest_by_day(rows: list) -> dict:
    """
    One row per slaughter day, taking the latest `report_date`.

    This is what turns Friday's Saturday PROJECTION into Monday's restated
    figure. Picking the first row instead -- or trusting `period` -- would
    silently freeze every Saturday at its forecast.
    """
    best = {}
    for r in rows:
        cur = best.get(r["day"])
        if cur is None or r["report_date"] > cur["report_date"]:
            best[r["day"]] = r
    return best


def daily_frame(raw: dict) -> pd.DataFrame:
    """Tidy one-row-per-day frame, oldest first. Empty frame on a failed fetch."""
    if raw.get("error") or not raw.get("rows"):
        return pd.DataFrame()
    best = _latest_by_day(raw["rows"])
    df = pd.DataFrame(sorted(best.values(), key=lambda r: r["day"]))
    df["dow"]        = df["day"].map(lambda d: d.weekday())
    df["week_start"] = df["day"].map(lambda d: d - timedelta(days=d.weekday()))
    # Any day at or after the newest report's own date is still unsettled: the
    # Saturday because it has not happened, the current day because the next
    # report routinely restates it (2026-09-14 went 106,000 -> 103,000
    # overnight). Both are forecasts against settled history, so both are
    # marked -- see the module docstring on revisions.
    newest_report    = max(r["report_date"] for r in raw["rows"])
    df["is_projection"] = df["day"] >= newest_report
    return df


def saturday_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Every Saturday with the week it belongs to.

    Columns: day, head, week_total, week_low (weakest Mon-Fri), sat_share,
    lost_day (the week gave up a weekday), is_projection.

    The week context is not decoration. A Saturday head count on its own
    cannot distinguish "packers bought a sixth day because margins are good"
    from "packers are buying back a holiday Monday", and historically it has
    almost always been the second.
    """
    if df.empty:
        return pd.DataFrame()

    wk = {}
    for r in df.itertuples():
        wk.setdefault(r.week_start, {})[r.dow] = r.head

    out = []
    for r in df[df["dow"] == 5].itertuples():
        days = wk.get(r.week_start, {})
        weekdays = [days[i] for i in range(5) if i in days]
        if len(weekdays) < 5:
            continue                      # partial week at the edges of the feed
        total = sum(days.get(i, 0) for i in range(6))
        med   = sorted(weekdays)[len(weekdays) // 2]
        low   = min(weekdays)
        out.append({
            "day": r.day, "head": r.head,
            "week_start": r.week_start, "week_total": total,
            "week_low": low, "week_median_wkday": med,
            "sat_share": (r.head / total) if total else float("nan"),
            "lost_day": bool(med) and low < med * LOST_DAY_FRAC,
            "is_projection": r.is_projection,
        })
    return pd.DataFrame(out)


def at_or_above(sats: pd.DataFrame, head: int, before: date = None) -> pd.DataFrame:
    """
    Saturdays that matched or beat `head`, oldest first.

    This is the "when did we last do this" question. `before` excludes the day
    being asked about so a Saturday never counts as its own precedent.
    """
    if sats.empty:
        return sats
    m = sats["head"] >= head
    if before is not None:
        m &= sats["day"] < before
    return sats[m].sort_values("day")


def reconcile(df: pd.DataFrame, raw: dict) -> list:
    """
    Audit Mon-Sat against the report's own week_to_date.

    A dedupe error does not raise and does not look wrong on a chart -- it
    looks like a slightly different market. This is the cheap check that turns
    it back into a number. Returns a list of (week_start, summed, reported).
    """
    if df.empty or raw.get("error"):
        return []
    wtd = {}
    for r in _latest_by_day(raw["rows"]).values():
        if r["day"].weekday() == 5 and r["week_to_date"]:
            wtd[r["day"]] = r["week_to_date"]

    bad = []
    for sat, reported in wtd.items():
        wkstart = sat - timedelta(days=5)
        days = df[(df["week_start"] == wkstart) & (df["dow"] <= 5)]
        if len(days) < 6:
            continue
        summed = int(days["head"].sum())
        if summed != reported:
            bad.append((wkstart, summed, reported))
    return bad


def context_line(row) -> str:
    """One plain sentence explaining a Saturday, for the table's Note column."""
    if row["lost_day"]:
        return (f"holiday week — weakest weekday {row['week_low']:,} head; "
                f"week totalled {row['week_total']:,}")
    return f"full week — week totalled {row['week_total']:,}"
