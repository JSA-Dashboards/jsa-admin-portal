"""
Read-only analytics for Mexican feeder cattle imports.

Import-safe by design -- no `requests`, no HTTP, no ingest. Same split as
herd.py: the Streamlit process should never pull the ingest's network stack in.
Ingest lives in the cme-feeder-cattle-index repo as border_reports.py (AMS
narrative + trade status) and census_imports.py (Census head counts), and the
daily job pushes both to JSA.CME_FEEDER_CATTLE.

TWO SOURCES, NEITHER SUFFICIENT ALONE.

  AMS daily      (border_receipts)  head counts by crossing point, current to
                                    yesterday. ESTIMATES, rounded to the
                                    nearest hundred head.
  AMS weekly     (border_volumes)   exact weekly volumes with AMS's own YTD and
                                    prior-year YTD. A week behind the daily.
  AMS narrative  (border_reports)   trade status, which crossings are open,
                                    market tone -- what no number carries.
  Census         (census_cattle_    the official customs count, seven years of
                 imports)           history, about six weeks late. January
                                    publishes in early March.

So AMS answers "what is crossing now" and Census answers "how does that compare
to a normal year". In September 2026 Census showed zero imports for the entire
year while AMS showed Douglas, AZ reopening on 24 August and 5,200 head crossing
since -- not a contradiction, just the six-week lag. The two tie out where they
overlap: AMS's 2024 and 2025 daily totals land within ~3% of Census.

A CORRECTION WORTH KEEPING. The first version of this module asserted AMS
"carries NO numbers ... all seven International Livestock reports return zero
structured data fields", and the page showed crossing DAYS as a proxy. That was
wrong. MARS reports are split into SECTIONS addressed as PATH segments
(/reports/3486/Report%20Volume); ask for a report without one and you get its
header -- narrative and dates, nothing numeric -- which is indistinguishable
from a report that has no data. Passing `section` as a query parameter is
accepted and silently ignored. The section list was in the response's
`reportSections` key the whole time.

WHY 320 KG MATTERS. Census's weight bands top out at "320 kg or more", and
320 kg is 705 lb -- the very bottom of the CME index's 700-899 lb window. Nearly
all Mexican cattle cross BELOW index weight and reach it only after months on US
feed, so an import cut moves the index with a lag, through supply, and never by
appearing in the index's own composition.
"""
import re
from datetime import date, timedelta

import snowflake_db as db

# ── AMS narrative parsing ────────────────────────────────────────────────────

# "No cattle crossed today." AMS began publishing on zero-crossing days in
# 2026; before that a published report always meant cattle crossed. Counting
# reports rather than crossings therefore understates the 2026 collapse (12
# reports, 7 crossings) while looking perfectly reasonable.
NO_CROSSING = re.compile(r"no cattle (crossed|were crossed|crossing)", re.I)

# Crossings are named inconsistently: case varies (DOUGLAS, AZ), several appear
# in one report ("DOUGLAS AND NOGALES, AZ"), and a preceding sentence can run
# into the name ("... OTHERWISE NOTED. NOGALES, AZ"). Matching city names from a
# known list and requiring the state nearby is what makes the counts add up.
KNOWN_PORTS = ["SANTA TERESA, NM", "ST TERESA, NM", "COLUMBUS, NM",
               "DOUGLAS, AZ", "NOGALES, AZ", "PRESIDIO, TX", "EAGLE PASS, TX",
               "LAREDO, TX", "DEL RIO, TX", "SAN LUIS, AZ", "CALEXICO, CA"]
# AMS's own typo for Santa Teresa. Without folding it, 2024 splits 136/56
# across two names for one crossing.
PORT_ALIASES = {"ST TERESA, NM": "SANTA TERESA, NM"}

REOPEN = re.compile(r"RE-?OPENED|IS NOW OPEN", re.I)
SUSPEND = re.compile(r"SUSPEND|CLOSED|REMAIN(?:S)? CLOSED", re.I)


def _clean(v) -> str:
    return " ".join(str(v or "").split())


def ports_in(text: str):
    """Every known crossing named anywhere in a narrative, normalized."""
    t = _clean(text).upper()
    found = set()
    for p in KNOWN_PORTS:
        city, state = p.split(", ")
        for m in re.finditer(r"\b" + re.escape(city) + r"\b", t):
            if state in t[m.end():m.end() + 30]:
                found.add(PORT_ALIASES.get(p, p))
                break
    return found


def title_port(p: str) -> str:
    """'DOUGLAS, AZ' -> 'Douglas, AZ'."""
    city, _, state = p.partition(", ")
    return f"{city.title()}, {state}"


# ── AMS: status and crossing activity ────────────────────────────────────────

def current_status(conn):
    """
    Latest trade-status note from AMS, with the date so the page can say how old
    it is. Absence is NOT backfilled from an older week: a week with no note is
    a week AMS did not flag anything, and showing last month's suspension notice
    as though it were current would be worse than showing nothing.
    """
    rows = conn.cursor().execute(
        "SELECT report_date, report_begin, report_end, special_notes "
        "FROM border_reports WHERE kind = 'status' "
        "ORDER BY report_date DESC").fetchall()
    if not rows:
        return None
    rd, begin, end, notes = rows[0]
    return {
        "date": db.iso(rd),
        "begin": db.iso(begin) if begin else None,
        "end": db.iso(end) if end else None,
        "notes": _clean(notes) or None,
        "weeks_with_notes": sum(1 for r in rows if r[3]),
        "weeks_total": len(rows),
    }


def crossing_days(conn):
    """
    {year: {"reports", "crossings", "zero"}}.

    "crossings" is the number to show -- see NO_CROSSING above for why it is not
    the report count.
    """
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary'").fetchall()
    out = {}
    for rd, narr in rows:
        y = str(db.iso(rd))[:4]
        d = out.setdefault(y, {"reports": 0, "crossings": 0, "zero": 0})
        d["reports"] += 1
        t = _clean(narr)
        if t and NO_CROSSING.search(t):
            d["zero"] += 1
        else:
            d["crossings"] += 1
    return dict(sorted(out.items()))


def ports_by_year(conn):
    """
    {port: {year: crossing days}}, busiest first -- which crossings are open.

    The clearest single picture of the suspension: five crossings active through
    2024, one in 2026. Zero-crossing days are excluded, so a port publishing
    "no cattle crossed" does not count as open.
    """
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary'").fetchall()
    out = {}
    for rd, narr in rows:
        t = _clean(narr)
        if not t or NO_CROSSING.search(t):
            continue
        y = str(db.iso(rd))[:4]
        for p in ports_in(t):
            out.setdefault(p, {})
            out[p][y] = out[p].get(y, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -sum(kv[1].values())))


def crossing_dates(conn):
    """Every date cattle actually crossed, ascending."""
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary' ORDER BY report_date").fetchall()
    return [str(db.iso(rd)) for rd, narr in rows
            if _clean(narr) and not NO_CROSSING.search(_clean(narr))]


def reopening(conn, gap_days=45):
    """
    The most recent reopening: first crossing after a gap of `gap_days`+.

    Derived from the DATES rather than from an announcement, so it does not
    depend on AMS having worded a notice a particular way. The matching
    announcement text is returned alongside as corroboration when one exists,
    which is how the 2026-08-24 reopening was confirmed two ways.
    """
    dates = crossing_dates(conn)
    if len(dates) < 2:
        return None
    from datetime import date as _d

    def parse(s):
        return _d.fromisoformat(str(s)[:10])

    reopen_at, prev_at = None, None
    for a, b in zip(dates, dates[1:]):
        if (parse(b) - parse(a)).days >= gap_days:
            reopen_at, prev_at = b, a
    if not reopen_at:
        return None

    note = None
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary' ORDER BY report_date").fetchall()
    for rd, narr in rows:
        if str(db.iso(rd))[:10] == reopen_at:
            t = _clean(narr)
            m = re.search(r"\*{2,}(.+?)\*{2,}", t)
            if m and REOPEN.search(m.group(1)):
                note = m.group(1).strip()
            break
    return {"date": reopen_at, "previous_crossing": prev_at,
            "gap_days": (parse(reopen_at) - parse(prev_at)).days,
            "note": note,
            "days_since": (_d.today() - parse(reopen_at)).days}


EXPORT_WORD = re.compile(r"\bEXPORT", re.I)
IMPORT_WORD = re.compile(r"\bIMPORT|\bBORDER\b|\bCROSS", re.I)
# AMS wraps each announcement in asterisks; one note can carry several.
SEGMENT = re.compile(r"\*{2,}\s*(.+?)\s*\*{2,}", re.S)


def note_segments(notes: str):
    """
    [(text, direction)] -- one entry per announcement inside a status note.

    THIS IS NOT PEDANTRY, AND ONE LABEL PER NOTE IS THE WRONG SHAPE. AMS report
    3629 covers BOTH directions and a single note routinely carries both. In
    September 2026 the standing note read

        *** EXPORTS TO MEXICO REMAIN SUSPENDED UNTIL FURTHER NOTICE. ***

    while Douglas, AZ was actively crossing cattle INTO the United States, and
    an earlier note carried the Douglas reopening and the export suspension side
    by side. A page that renders "the latest note" as "the border" would have
    declared imports closed for three weeks after they reopened -- confidently,
    and citing a genuine USDA source. So each announcement is classified
    separately and the page asks for the direction it actually means.

    Direction is decided on the plain words IMPORT / EXPORT / BORDER / CROSS.
    An earlier version required "IMPORTS FROM|INTO" and matched 2 notes out of
    26, silently leaving "IMPORTS ARE SUSPENDED UNTIL FURTHER NOTICE" as
    unknown.
    """
    t = _clean(notes)
    if not t:
        return []
    segs = [s.strip() for s in SEGMENT.findall(t) if s.strip()]
    if not segs:                       # unasterisked note, e.g. "Correction to horses"
        segs = [t]
    out = []
    for s in segs:
        has_ex, has_im = bool(EXPORT_WORD.search(s)), bool(IMPORT_WORD.search(s))
        if has_im and not has_ex:
            d = "import"
        elif has_ex and not has_im:
            d = "export"
        elif has_ex and has_im:
            d = "both"
        else:
            d = "unknown"             # holiday schedules, corrections
        out.append((s, d))
    return out


def import_notes(notes: str):
    """Only the announcements that bear on IMPORTS. See note_segments()."""
    return [s for s, d in note_segments(notes) if d in ("import", "both")]


def status_history(conn, limit=None):
    """
    [(week_end, [import-relevant announcement, ...])] newest first.

    The suspension timeline in AMS's own words, which is richer than the
    crossing dates alone: it names New World Screwworm as the cause, and records
    a reopening on 7 July 2025 that closed again shortly after -- a detail no
    volume series shows, because the reopening barely produced volume.
    """
    rows = conn.cursor().execute(
        "SELECT report_end, report_date, special_notes FROM border_reports "
        "WHERE kind = 'status' AND special_notes IS NOT NULL "
        "ORDER BY report_date DESC").fetchall()
    out = []
    for end, rd, notes in rows:
        segs = import_notes(notes)
        if segs:
            out.append((str(db.iso(end or rd)), segs))
        if limit and len(out) >= limit:
            break
    return out


def import_status(conn, stale_days=10):
    """
    Is the IMPORT border open, judged only on import-side evidence.

    Derived from crossing activity in the 3486 summary rather than from any
    announcement in 3629 -- see note_direction() for why mixing the two is a
    trap. Returns the evidence, not just a verdict, so the page can show what
    the call rests on.

    "open" means cattle have actually crossed recently. A run of published
    zero-crossing days leaves the port open but idle, which is a different
    thing and is reported as such.
    """
    from datetime import date as _d

    dates = crossing_dates(conn)
    rows = conn.cursor().execute(
        "SELECT MAX(report_date) FROM border_reports WHERE kind = 'commentary'"
    ).fetchone()
    latest_report = str(db.iso(rows[0])) if rows and rows[0] else None
    if not dates:
        return {"state": "closed", "last_crossing": None,
                "latest_report": latest_report, "reopening": reopening(conn)}

    last = dates[-1]
    days = (_d.today() - _d.fromisoformat(str(last)[:10])).days
    # Idle vs closed: the port is still publishing, just with nothing crossing.
    if days <= stale_days:
        state = "open"
    elif latest_report and (_d.today() -
                            _d.fromisoformat(str(latest_report)[:10])).days <= stale_days:
        state = "idle"
    else:
        state = "closed"
    # ports_by_year is already ordered busiest-first, so keep that order.
    current_year = str(_d.today().year)
    active = [title_port(p) for p, d in ports_by_year(conn).items()
              if d.get(current_year)]
    return {"state": state, "last_crossing": str(last),
            "days_since_crossing": days, "latest_report": latest_report,
            "active_ports": active, "reopening": reopening(conn)}


def recent_commentary(conn, limit=15):
    """Latest port-level market notes, newest first, with a crossed flag."""
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary' AND narrative IS NOT NULL "
        "ORDER BY report_date DESC").fetchall()
    out = []
    for rd, narr in rows[:limit]:
        t = _clean(narr)
        # A leading "*** ... ***" block is an AMS announcement, not market
        # commentary; split it out so the table's text column stays readable.
        note = None
        m = re.match(r"\*{2,}(.+?)\*{2,}\s*(.*)$", t)
        if m:
            note, t = m.group(1).strip(), m.group(2).strip()
        port, _, rest = t.partition(" - ")
        out.append({
            "date": str(db.iso(rd)),
            "port": title_port(port.strip().upper()) if rest else None,
            "text": rest.strip() if rest else t,
            "note": note,
            "crossed": not NO_CROSSING.search(t or ""),
        })
    return out


# ── Census: classification and volumes ──────────────────────────────────────

def classify_commodity(commodity: str, descr: str) -> str:
    """
    feeder / slaughter / breeding / dairy / other, from the description.

    THE EXCLUSION CLAUSE. Every commercial line reads

        CATTLE, LIVE, MALE, WEIGHING 200 KG OR MORE BUT LESS THAN 320 KG EACH,
        OTHER THAN PUREBRED BREEDING AND/OR DAIRY

    so a substring test for "breeding" labels the whole feeder volume as
    breeding stock, and switching to "dairy" labels it dairy. Either mistake
    mislabelled 115,636 of June 2024's 116,696 head and still rendered a
    plausible table. Everything after "OTHER THAN" says what the line is NOT, so
    it is split off and only the positive part is matched -- which also handles
    any exclusion Census adds later.

    Keyed on the description, not the code: HS10 numbers get renumbered, the
    wording does not. Read-time classification means a wrong call is a one-line
    fix rather than a re-pull.
    """
    positive, _, _excl = (descr or "").upper().partition("OTHER THAN")
    if "IMMEDIATE SLAUGHTER" in positive:
        return "slaughter"
    if "DAIRY" in positive:
        return "dairy"
    if "PUREBRED" in positive or "FOR BREEDING" in positive:
        return "breeding"
    if "WEIGHING" in positive and "KG" in positive:
        return "feeder"
    return "other"


# Ordered light to heavy so a composition chart stacks sensibly.
BANDS = ["<90 kg (<198 lb)", "90-200 kg (198-441 lb)",
         "200-320 kg (441-705 lb)", "320+ kg (705+ lb)", "unspecified"]


def weight_band(descr: str) -> str:
    """The HS weight band, in pounds as well as kilos. See the 320 kg note above."""
    d, _, _x = (descr or "").upper().partition("OTHER THAN")
    if "LESS THAN 90" in d:
        return BANDS[0]
    if "90 KG OR MORE" in d and "LESS THAN 200" in d:
        return BANDS[1]
    if "200 KG OR MORE" in d and "LESS THAN 320" in d:
        return BANDS[2]
    if "320 KG OR MORE" in d:
        return BANDS[3]
    return BANDS[4]


# ── AMS head counts (the timely series) ─────────────────────────────────────
#
# These come from MARS report SECTIONS, which are PATH segments
# (/reports/3486/Report%20Volume). Requesting a report without one returns only
# its header -- narrative and dates, nothing numeric -- which is why an earlier
# version of this page concluded AMS published no numbers at all and showed
# crossing DAYS as a proxy. It publishes head counts daily.
#
# Two series, different in kind, never to be mixed:
#   border_receipts  DAILY, field named receipts_current_EST, rounded to the
#                    nearest 50-100 head. Current to yesterday.
#   border_volumes   WEEKLY ACTUALS with AMS's own YTD and prior-year YTD
#                    already computed. Exact, but a week behind.
# Through 2026-09-04 the daily estimates summed to 2,600 against an actual
# 2,557 -- a 1.7% rounding gap. Small, but the page labels which it is showing.

def daily_receipts(conn, since=None):
    """
    [(date, head, week_to_date)] -- AMS's own grand-total row per day.

    NEVER sums the per-crossing rows to get this. They are hierarchical rollups
    (all-points / per-state / per-crossing), so summing triple-counts, and the
    parts do not always reconcile: over 463 days the named crossings disagreed
    with AMS's published total on 19 of them. is_total flags the authoritative
    row at ingest so no reader has to re-derive that rule.
    """
    sql = ("SELECT report_date, receipts_est, receipts_wtd_est "
           "FROM border_receipts WHERE is_total = 1")
    if since:
        sql += f" AND report_date >= '{since}'"
    sql += " ORDER BY report_date"
    return [(str(db.iso(d)), v or 0, w or 0)
            for d, v, w in conn.cursor().execute(sql).fetchall()]


def receipts_by_year(conn):
    """{year: {"head", "days"}} from the daily estimate series."""
    out = {}
    for d, v, _w in daily_receipts(conn):
        y = str(d)[:4]
        r = out.setdefault(y, {"head": 0, "days": 0})
        r["head"] += v
        r["days"] += 1
    return dict(sorted(out.items()))


def receipts_by_crossing(conn, since=None):
    """
    [(crossing, state, head)] detail, busiest first.

    Detail only: these can disagree with the published total, so the page must
    present them as a breakdown rather than as something that adds up.
    """
    sql = ("SELECT crossing_point, crossing_state, SUM(receipts_est) "
           "FROM border_receipts WHERE is_total = 0 "
           "AND crossing_point <> 'All Crossing Points'")
    if since:
        sql += f" AND report_date >= '{since}'"
    sql += " GROUP BY crossing_point, crossing_state"
    rows = conn.cursor().execute(sql).fetchall()
    return sorted([(p, s, v or 0) for p, s, v in rows], key=lambda t: -t[2])


def crossing_debuts(conn, since=None):
    """
    [(crossing, state, first_date, last_date, head, days)] -- when each
    crossing started taking cattle, busiest first. `days` counts only the
    reporting days it actually carried cattle, so head/days is its rate while
    running rather than its rate across the calendar.

    EXISTS BECAUSE THE PROJECTION'S BIGGEST CAVEAT IS A MOVING FACT. The
    year-end projection assumes the pace holds, and the thing most likely to
    break that is a crossing opening or shutting. Written into the page as
    prose it goes stale silently: the caption said "only Douglas, AZ is open"
    on 2026-10-02, nine days after Santa Teresa, NM reopened on 09-24 and
    started adding several hundred head a day. The page's own header said two
    were active, directly above it.

    Per-crossing rows are a BREAKDOWN, not an exact decomposition -- see
    receipts_by_crossing -- so these dates and head counts answer "which
    crossings are running, and since when", never "what crossed in total".
    """
    sql = ("SELECT crossing_point, crossing_state, MIN(report_date), "
           "       MAX(report_date), SUM(receipts_est), COUNT(*) "
           "FROM border_receipts WHERE is_total = 0 "
           "AND crossing_point <> 'All Crossing Points' "
           "AND receipts_est > 0")
    if since:
        sql += f" AND report_date >= '{since}'"
    sql += " GROUP BY crossing_point, crossing_state"
    rows = conn.cursor().execute(sql).fetchall()
    return sorted([(p, s, str(db.iso(a)), str(db.iso(b)), v or 0, n or 0)
                   for p, s, a, b, v, n in rows], key=lambda t: -t[4])


def newest_crossing(conn, since=None):
    """
    The most recent crossing to open, as
    (crossing, state, first_date, head, days).

    None when nothing has crossed, or when every active crossing started on the
    same day -- on the latter there is no "newest" and the pace window spans
    one regime, which is the case the caller wants to distinguish.
    """
    debuts = crossing_debuts(conn, since=since)
    if len(debuts) < 2:
        return None
    latest = max(debuts, key=lambda t: t[2])
    if all(d[2] == debuts[0][2] for d in debuts):
        return None
    return (latest[0], latest[1], latest[2], latest[4], latest[5])


def normal_baseline(series, min_run=1):
    """
    Median of normal trade: everything before the first SUSTAINED closure.

    `series` is [(period_label, head)]; `min_run` is how many consecutive zero
    periods count as a closure rather than a quiet spell -- 1 for a monthly
    series, 4 for a weekly one, i.e. roughly a month of no trade either way.

    WHY NOT JUST DROP THE ZEROS. That is the obvious rule and it gives the wrong
    number, because trade did not go from normal to zero -- it went through
    months that were open but crippled. On the monthly series:

        all 83 periods              92,865
        excluding the 7 zeros       97,378
        before the first closure   102,732

    The middle figure still contains February 2025 at 21,788 head, March at
    74,409, July at 4,339 -- a border open at a handful of crossings under
    restrictions. Real months, but not what "normally crosses when the border is
    open" means, and averaging them in understates normal trade by about 5%.

    WHY min_run EXISTS, and it is not a tuning knob. The first version took the
    FIRST zero as the closure. That is right monthly -- there is no zero month
    before 2024-12 -- and wrong weekly, where the run structure is:

        2023-08-14                1 week    <- genuine, but normal trade
        2024-11-25 .. 2025-01-27  10 weeks  <- the first real closure
        2025-05-19 .. 2025-06-30   7 weeks
        2025-07-14 .. 2026-07-27  47 weeks

    so "first zero" ended the baseline in August 2023 and computed normal trade
    from 32 weeks instead of 100 -- 22,985 head against the true 25,435.

    That isolated week is NOT bad data: AMS's own running year-to-date holds
    flat at 706,029 across it and only resumes the following week, and a
    cumulative series that does not advance proves nothing crossed. Some weeks
    genuinely have no trade. Requiring a run is what distinguishes those from a
    border that has shut.
    """
    if not series:
        return None

    start = None
    run = 0
    for i, (_p, h) in enumerate(series):
        if h == 0:
            run += 1
            if run >= min_run:
                start = i - run + 1     # first zero OF THIS RUN
                break
        else:
            run = 0
    if start == 0:
        return None                     # series opens mid-closure; no baseline

    head = series[:start] if start is not None else series
    vals = sorted(h for _p, h in head)
    if not vals:
        return None
    n = len(vals)
    return {
        "median": vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2,
        "n": n,
        "from": series[0][0],
        "until": head[-1][0],
        "disruption_starts": series[start][0] if start is not None else None,
        "n_after": len(series) - n,
    }


def weekly_volumes(conn, commodity="Feeder Cattle"):
    """
    [(week_start, head)] weekly ACTUALS from 3629.

    STARTS IN 2023, and no further back is possible. AMS's series simply does
    not exist before then -- asking MARS for 2014 onward returns nothing earlier
    for either the weekly or the daily section. Census is the only source with
    2019 history and it publishes MONTHLY only, so a weekly series reaching 2019
    would have to be manufactured by splitting months into weeks. It is not
    manufactured here; the chart says where the data starts instead.

    A NULL volume is stored as 0, not dropped. 65 of 181 weeks are NULL and they
    are the suspension weeks -- checked against the daily series, which agrees:
    of the 100 overlapping weeks, only one is NULL in 3629 while daily data
    exists, and that week's daily estimates are themselves 0. Dropping them
    would draw a continuous line across the closure and hide the whole story.

    These are ACTUALS, which is why they are preferred over rolling the daily
    estimates into weeks: over 99 comparable weeks the two differ by a mean of
    1,255 head, the estimates being rounded to the nearest hundred per day.
    """
    rows = conn.cursor().execute(
        "SELECT report_begin, current_volume FROM border_volumes "
        f"WHERE category = 'Import' AND commodity = '{commodity}' "
        "AND origin = 'Mexico' ORDER BY report_begin").fetchall()
    return [(str(db.iso(b)), int(v or 0)) for b, v in rows]


def ytd_actuals(conn, commodity="Feeder Cattle"):
    """
    AMS's OWN year-to-date, not one this page computes.

    Worth using rather than summing the daily series: AMS defines the cut-off,
    so a partial current year cannot be mismeasured against a full prior one --
    the trap that had the index's 2026 YTD reading the wrong sign before the
    weekday alignment went in. Returns the latest week carrying a YTD figure.
    """
    rows = conn.cursor().execute(
        "SELECT report_begin, report_end, current_volume, current_ytd, "
        "       prior_volume, prior_ytd, current_year, prior_year "
        "FROM border_volumes WHERE category = 'Import' "
        f"AND commodity = '{commodity}' AND origin = 'Mexico' "
        "ORDER BY report_begin DESC").fetchall()
    for b, e, cv, cy, pv, py, yr, pyr in rows:
        if cy is None:
            continue          # weeks during the shutdown carry no YTD at all
        return {
            "week_begin": str(db.iso(b)), "week_end": str(db.iso(e)),
            "week": cv, "ytd": cy, "prior_week": pv, "prior_ytd": py,
            "year": yr, "prior_year": pyr,
            "pct": ((cy / py - 1) * 100) if py else None,
        }
    return None


def since_reopening(conn):
    """
    Head crossed since the border reopened, from the daily series.

    Deliberately the daily estimates rather than AMS's weekly actuals: the
    actuals lag a week, and "how many since it reopened" is a question about
    right now. The caller is told it is an estimate.
    """
    r = reopening(conn)
    if not r or not r.get("date"):
        return None
    rows = daily_receipts(conn, since=r["date"])
    if not rows:
        return None
    crossed = [(d, v) for d, v, _w in rows if v > 0]
    return {
        "from": r["date"],
        "head": sum(v for _d, v, _w in rows),
        "days": len(rows),
        "days_with_cattle": len(crossed),
        "best_day": max(crossed, key=lambda t: t[1]) if crossed else None,
        "latest": rows[-1][0],
    }


# The years the border ran without restriction, and so the only ones a
# crossing's normal rate can be read from. 2025 is excluded deliberately: it
# was three-quarters closed, and the ports that did run were running under
# restrictions at roughly half their usual rate.
NORMAL_YEARS = ("2023", "2024")

# The crossing most likely to move the year-end projection next, and the one
# the page writes a sensitivity for while it is shut.
#
# NOT DERIVABLE FROM THE FEED, which is the whole reason it is a constant.
# AMS does announce reopening schedules in the narrative -- on 2025-07-08 it
# published "COLUMBUS AND SANTA TERESA, NM WILL RE-OPEN JULY 14TH AND 21ST
# RESPECTIVELY" -- but the current narrative (2026-10-01) names only Santa
# Teresa. The Columbus expectation comes from Ross on 2026-10-02 and has no
# counterpart in the data, so it cannot be read off and must be maintained by
# hand. Clear it to None once Columbus reopens, or point it at whichever
# crossing is next.
#
# AND AN ANNOUNCED DATE IS NOT A REOPENING. That same 2025-07-08 notice named
# two ports and two dates and NEITHER happened: Columbus has not appeared in
# the series since 2024-11-25, Santa Teresa recorded nothing at all between
# 2025-05-12 and 2026-09-24, and the July 2025 reopening lasted four reporting
# days of Douglas alone before the border shut again. So this date may inform
# a reader; it must never feed a number.
WATCH_PORT = "Columbus"
WATCH_PORT_EXPECTED = "end of October 2026"


def port_profile(conn, port, years=NORMAL_YEARS, this_year=None):
    """
    What one crossing did when the border was running normally, and whether it
    is running now.

        head, days, per_day   over `years`, counting only days it carried
                              cattle, so per_day is its rate while open
        share                 its share of all named-port head in those years
        last_seen             the last date it carried cattle, ever
        running               whether it has carried cattle in `this_year`

    Returns None for a crossing that never appears, which is the honest answer
    for a port that has no history to project from.

    `share` is taken against the NAMED-PORT total rather than AMS's own
    all-points figure. The two disagree on 19 days in 463 (see
    receipts_by_crossing) and only the named rows can be attributed to a port,
    so a share mixing the two bases would be the wrong fraction of the wrong
    denominator.
    """
    yrs = ", ".join(f"'{y}'" for y in years)
    cur = conn.cursor()
    row = cur.execute(
        "SELECT SUM(receipts_est), COUNT(*) FROM border_receipts "
        "WHERE is_total = 0 AND receipts_est > 0 "
        f"AND crossing_point = '{port}' "
        f"AND TO_CHAR(report_date, 'YYYY') IN ({yrs})").fetchone()
    head, days = (row or (None, 0))
    if not head or not days:
        return None
    total = cur.execute(
        "SELECT SUM(receipts_est) FROM border_receipts "
        "WHERE is_total = 0 AND receipts_est > 0 "
        "AND crossing_point <> 'All Crossing Points' "
        f"AND TO_CHAR(report_date, 'YYYY') IN ({yrs})").fetchone()[0]
    last = cur.execute(
        "SELECT MAX(report_date) FROM border_receipts "
        f"WHERE is_total = 0 AND receipts_est > 0 "
        f"AND crossing_point = '{port}'").fetchone()[0]
    yr = str(this_year or date.today().year)
    now = cur.execute(
        "SELECT COUNT(*) FROM border_receipts "
        "WHERE is_total = 0 AND receipts_est > 0 "
        f"AND crossing_point = '{port}' "
        f"AND TO_CHAR(report_date, 'YYYY') = '{yr}'").fetchone()[0]
    return {
        "port": port,
        "head": head,
        "days": days,
        "per_day": head / days,
        "share": (head / total) if total else None,
        "last_seen": str(db.iso(last)) if last else None,
        "running": bool(now),
        "years": years,
    }


# ── Pace, and the year-end projection ───────────────────────────────────────
#
# Same question the Beef Trimmings page asks of the tariff-free quota: at the
# rate things are arriving, where does this land by the deadline? The shape of
# the answer is deliberately different in two ways, and both matter.
#
# IT USES A TRAILING WINDOW, NOT THE WHOLE SPAN. quota_tracker.pace() measures
# first observation to last, because CBP reports weekly and one holiday-shortened
# gap would read as a collapse. That reasoning does not transfer. This series is
# daily and dense, and it is RAMPING off a reopening rather than running at a
# steady rate: the first full week after the border reopened carried 2,500 head
# and the second carried 100, while the fifth carried 6,400. Averaging from the
# reopening gives 761 head/day against 1,155 over the trailing fortnight -- a
# third lower, describing a start-up that is over rather than the rate now.
#
# IT COUNTS REPORTING DAYS, NOT CALENDAR DAYS. Cattle cross on weekdays. A
# per-calendar-day rate carried across a quarter silently prices in Saturdays
# and Sundays and lands about 30% low.

# AMS publishes every weekday except holidays. Read off the series rather than
# assumed: across 2023-2026 the only weekday gaps inside a reporting span are
# holidays, and 2024 -- the one complete year -- has exactly ten, being MLK,
# Presidents, Good Friday, Memorial, Juneteenth, July 4th and the 5th, Labor,
# Columbus and Veterans. 2026 has one so far, Labor Day.
#
# Only dates that can fall inside a projection window are listed. Missing one
# costs a single reporting day out of sixty-odd, under 2% of the projection,
# against a pace that moved 25% between two adjacent fortnights. It does not
# earn a holiday library.
NON_REPORTING = frozenset({
    date(2026, 10, 12),   # Columbus Day
    date(2026, 11, 11),   # Veterans Day
    date(2026, 11, 26),   # Thanksgiving
    date(2026, 12, 25),   # Christmas
    date(2027, 1, 1),     # New Year
    date(2027, 1, 18),    # MLK Day
    date(2027, 2, 15),    # Presidents Day
    date(2027, 3, 26),    # Good Friday
    date(2027, 5, 31),    # Memorial Day
    date(2027, 6, 18),    # Juneteenth, observed (the 19th is a Saturday)
    date(2027, 7, 5),     # Independence Day, observed (the 4th is a Sunday)
    date(2027, 9, 6),     # Labor Day
    date(2027, 10, 11),   # Columbus Day
    date(2027, 11, 11),   # Veterans Day
    date(2027, 11, 25),   # Thanksgiving
    date(2027, 12, 24),   # Christmas, observed (the 25th is a Saturday)
})

# Two full reporting weeks. A week is the natural unit because AMS's own report
# is built on one -- the week-to-date column resets every Monday -- and two of
# them is the shortest window that cannot be swung by a single day.
#
# That last part is not theoretical. The week of 2026-09-28 ran 1,350 / 600 /
# 1,600 / 550 head on consecutive days, so a trailing FIVE days is 1,200 and a
# trailing ten is 1,155, but the five-day figure would have read 935 had it been
# taken one day earlier. Ten reporting days also holds the day-of-week mix
# constant, which a window that is not a multiple of five does not.
PACE_WINDOW = 10


def _as_date(v):
    """A 'YYYY-MM-DD' label as a date. The series carries strings throughout."""
    if isinstance(v, date):
        return v
    y, m, d = (int(p) for p in str(v)[:10].split("-"))
    return date(y, m, d)


def reporting_days(start, end):
    """
    Weekdays in [start, end] inclusive that AMS would publish on.

    Inclusive of BOTH ends, which is why the caller passes the day after the
    last report rather than the report date -- counting from the report itself
    would project a day that is already in the actual.
    """
    start, end = _as_date(start), _as_date(end)
    n = 0
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in NON_REPORTING:
            n += 1
        day += timedelta(days=1)
    return n


def daily_pace(series, window=PACE_WINDOW):
    """
    Head per reporting day over the trailing `window` reporting days.

    `series` is [(date_label, head)], the same shape normal_baseline takes and
    what daily_receipts gives once the week-to-date column is dropped.

    DAYS AMS PUBLISHED WITH ZERO CROSSINGS COUNT IN THE DENOMINATOR. They are
    reporting days on which nothing crossed, which is a fact about the pace and
    not a hole in the data -- the week of 2026-08-31 is four such days either
    side of a single 100-head Monday. Dropping them would have that week read
    as 100 head/day, i.e. faster than the fortnight that followed it.

    Returns None under a full window rather than averaging two days and calling
    the result a rate.
    """
    pts = [(_as_date(r[0]), r[1] or 0) for r in series]
    if len(pts) < window:
        return None
    tail = sorted(pts)[-window:]
    return sum(h for _d, h in tail) / float(window)


def project_year_end(series, today=None, window=PACE_WINDOW):
    """
    Where the calendar year lands if the trailing pace holds to 31 December.

    Returns None without a full window of reporting days, and otherwise:

        crossed    head so far this year, from the daily estimates
        pace       head per reporting day over the trailing window
        days_left  reporting days from the day after the last report to 31 Dec
        projected  crossed + pace * days_left
        through    date of the last report in the series
        window     the window actually used

    NO CAP, and that is the real departure from the quota tracker.
    project_final() clamps at the tranche limit because CBP stops accepting
    entries once a quota fills. Nothing caps a border: it runs at whatever rate
    the open crossings support, and in 2024 that was 5,678 head per reporting
    day against the 1,155 behind this projection.

    WHAT IT CANNOT SEE IS WHAT DECIDES IT. The two things that move this number
    most are both step changes, and a straight line is blind to both:

      * a crossing reopening, which is not hypothetical and has already
        happened inside a pace window. Douglas, AZ carried the whole border
        from 24 August until Santa Teresa, NM joined it on 24 September and
        began adding several hundred head a day. Two of the six crossings that
        ran in 2023 are open. After the February 2025 reopening the weekly
        run-rate climbed to about 20,000 head and plateaued by week six; the
        2026 ramp was at 6,400 in week five, on a fraction of the ports.
        Use newest_crossing() to tell whether the window spans one regime or
        two -- a window that straddles an opening reads LOW, because part of
        it predates the port.
      * a new screwworm detection. That is what shut the border in the first
        place, and it takes the rate to zero in a day rather than bending it.

    So read it as "if nothing changes", exactly as the quota page's projection
    is to be read, and expect the error to arrive as a jump rather than as
    drift. The page says so in as many words.
    """
    pts = sorted((_as_date(r[0]), r[1] or 0) for r in series)
    if not pts:
        return None
    today = _as_date(today) if today else date.today()
    yr = today.year
    this_year = [(d, h) for d, h in pts if d.year == yr]
    if not this_year:
        return None
    rate = daily_pace(this_year, window=window)
    if rate is None:
        return None
    through = this_year[-1][0]
    # From the day after the LAST REPORT, not the day after today. The two
    # differ whenever the report lags, and counting from today would drop the
    # days in between out of the projection altogether -- cattle crossed on
    # them, and the daily series has merely not caught up yet.
    left = reporting_days(through + timedelta(days=1), date(yr, 12, 31))
    crossed = sum(h for _d, h in this_year)
    return {
        "crossed": crossed,
        "pace": rate,
        "days_left": left,
        "projected": crossed + rate * left,
        "through": str(through),
        "window": window,
    }


def port_shares(conn, years=NORMAL_YEARS):
    """
    {"shares": {port: fraction}, "head": total, "days": reporting days}.

    Each port's share of named-port head over the years the border ran
    normally, which is the only basis on which scenarios can be added up.

    DO NOT BUILD A SCENARIO BY SUMMING PER-PORT DAILY RATES. port_profile()
    divides a port's head by the days THAT PORT carried cattle, which is the
    right rate for "what does it do when it runs" and the wrong one for
    "what does the border do". Ports run different numbers of days, so the
    per-port rates sum to 8,750 head/day against a real border rate of 5,521
    -- 58% high. Shares sum to 1 by construction and cannot do that.
    """
    yrs = ", ".join(f"'{y}'" for y in years)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT crossing_point, SUM(receipts_est) FROM border_receipts "
        "WHERE is_total = 0 AND receipts_est > 0 "
        "AND crossing_point <> 'All Crossing Points' "
        f"AND TO_CHAR(report_date, 'YYYY') IN ({yrs}) "
        "GROUP BY crossing_point").fetchall()
    total = sum((h or 0) for _p, h in rows)
    days = cur.execute(
        "SELECT COUNT(*) FROM border_receipts WHERE is_total = 1 "
        f"AND TO_CHAR(report_date, 'YYYY') IN ({yrs})").fetchone()[0]
    if not total or not days:
        return None
    return {"shares": {p: (h or 0) / total for p, h in rows},
            "head": total, "days": days, "years": years}


def normal_rate(conn, years=NORMAL_YEARS):
    """
    Head per REPORTING day when the border ran normally, from the total row.

    A RATE, not an annual total, and that is the correction that matters.
    2024's raw 1,277,600 head looks like a full year and is not -- the border
    shut on 22 November, so it covers 225 reporting days against a full year's
    ~257. Using it as "a normal year" understates one by about 12%. The rate
    carries cleanly onto whatever reporting-day count the target year has.
    """
    yrs = ", ".join(f"'{y}'" for y in years)
    row = conn.cursor().execute(
        "SELECT SUM(receipts_est), COUNT(*) FROM border_receipts "
        f"WHERE is_total = 1 AND TO_CHAR(report_date, 'YYYY') IN ({yrs})").fetchone()
    head, days = (row or (None, 0))
    if not head or not days:
        return None
    return head / days


def year_outlook(conn, year, series, watch=WATCH_PORT, window=PACE_WINDOW,
                 today=None):
    """
    Scenarios for a calendar year that has not started yet.

    THIS IS NOT project_year_end(). That one is anchored: it adds a pace to
    head that have actually crossed, and by December most of its answer is
    measured rather than projected. A full forward year has NO actuals at all,
    so every figure here is a scenario and the page has to say so. Four of
    them, each meaning something different:

        as_is    today's pace carried across the year, nothing changes
        watch    the watch port reopens and restarts the way its neighbours
                 did -- the increment the page is really being asked for
        mature   those same ports recover to their normal rates
        normal   the whole border back to normal

    THE WATCH SCENARIO SCALES BY SHARE, NOT BY THE PORT'S OWN OLD RATE, and
    that is the one thing in here that is easy to get wrong in a way nobody
    would catch. Columbus ran 1,271 head on each day it was open in 2023-24,
    so "add Columbus back" reads as +1,271/day -- about +316,000 on the year.
    But the two ports that ARE open are managing 44% of what they normally do,
    and a crossing that reopened last month will not instantly outrun its
    neighbours by a factor of two. Scaling port capacity instead -- Columbus
    is 11.3% of a normal border against the 56.8% already open, so +20% --
    gives +67,600. The naive figure is 4.7x too high and arrives wearing the
    same units.

    Returns None when the normal-year basis cannot be formed, which is correct
    rather than exceptional: without it there is nothing to be a share OF.
    """
    sh = port_shares(conn)
    rate = normal_rate(conn)
    if not sh or not rate:
        return None
    pts = sorted((_as_date(r[0]), r[1] or 0) for r in series)
    if not pts:
        return None
    this_year = (_as_date(today).year if today else date.today().year)
    cur_series = [(d, h) for d, h in pts if d.year == this_year]
    pace = daily_pace(cur_series, window=window)
    if pace is None:
        return None

    rd = reporting_days(date(year, 1, 1), date(year, 12, 31))
    open_ports = [p for p, _s, _a, _b, _h, _n
                  in crossing_debuts(conn, since=f"{this_year}-01-01")]
    open_share = sum(sh["shares"].get(p, 0.0) for p in open_ports)
    watch_share = sh["shares"].get(watch, 0.0) if watch else 0.0
    if not open_share:
        return None

    normal_head = rate * rd
    as_is = pace * rd
    with_watch = pace * ((open_share + watch_share) / open_share) * rd
    mature = (open_share + watch_share) * normal_head
    return {
        "year": year,
        "reporting_days": rd,
        "pace": pace,
        "open_ports": open_ports,
        "open_share": open_share,
        "watch": watch if watch_share else None,
        "watch_share": watch_share,
        # How far along the open ports are. Measured against what those SAME
        # ports would normally carry, not against the whole border, or a
        # two-port border would read as permanently broken.
        "maturity": as_is / (open_share * normal_head),
        "normal_rate": rate,
        # How many crossings a normal border actually has, so the page can name
        # the count rather than say "every crossing" and leave it to be asked.
        "n_crossings": len(sh["shares"]),
        "scenarios": {
            "as_is": as_is,
            "watch": with_watch,
            "mature": mature,
            "normal": normal_head,
        },
    }


# ── Border prices ───────────────────────────────────────────────────────────
#
# From 3486 "Report Detail Current". Uniform where it matters, checked over all
# 10,401 rows 2023-2026: price_unit is "Per Cwt" and freight is "F.O.B." on
# every single row -- the same basis as the CME index, which is what makes a
# comparison legitimate rather than approximate.
#
# THE WEIGHT BRACKETS MOVED, and this is the trap on this table. AMS quoted
# 300-400 / 400-500 / 500-600 through 2024 and 500-600 / 600-700 / 700-800 from
# 2025:
#
#     bracket    2023   2024   2025   2026
#     300-400     922   1877     10      0
#     400-500     922   1880     10      6
#     500-600     917   1881    545     12
#     600-700       6    343    543     12
#     700-800       0      0    503     12
#
# So an average border price by year, taken without holding weight constant,
# measures the bracket change and not the market -- it would show a large jump
# into 2025 that is pure mix. Every function here holds the bracket fixed.

# The slice comparable to the CME index: the index is #1 & #1-2 Medium & Large
# steers, 700-899 lb, FOB with 3% shrink, over 12 states. 700-800 #1-2 Medium
# and Large steers FOB is as close as the border report gets. It exists only
# from February 2025, because of the bracket shift above.
INDEX_CLASS = "Steers"
INDEX_GRADE = "1-2"
INDEX_WEIGHT_LOW = 700


def price_grid(conn, on=None):
    """
    [(class, weight_low, weight_high, grade, low, high, mid)] for one date.

    Defaults to the latest date that actually carries prices, which is NOT the
    latest reporting day: AMS quotes prices only when enough head sell to
    establish a trend, so a day can report cattle crossing and no price at all
    ("Not enough head sold on the current market to establish trend or quote
    prices"). In 2026 there were 13 reporting days and 6 with prices.
    """
    cur = conn.cursor()
    if on is None:
        r = cur.execute("SELECT MAX(report_date) FROM border_prices").fetchone()
        on = r[0] if r else None
    if not on:
        return [], None
    rows = cur.execute(
        "SELECT class_desc, weight_low, weight_high, muscle_grade, "
        "       low_price, high_price, avg_price, crossing_point "
        "FROM border_prices WHERE report_date = "
        f"'{str(db.iso(on))}' ORDER BY class_desc, weight_low, muscle_grade"
    ).fetchall()
    return ([(c, wl, wh, g, lo, hi, mid, cp)
             for c, wl, wh, g, lo, hi, mid, cp in rows], str(db.iso(on)))


def price_series(conn, class_desc=INDEX_CLASS, grade=None, since=None):
    """
    {bracket_label: [(date, mid_price)]} -- one series per weight bracket.

    Keyed by bracket ON PURPOSE. Collapsing brackets into a single "border
    price" line would fold the 2024/2025 bracket shift straight into the trend.
    """
    sql = ("SELECT report_date, weight_low, weight_high, AVG(avg_price) "
           "FROM border_prices WHERE avg_price IS NOT NULL "
           f"AND class_desc = '{class_desc}'")
    if grade:
        sql += f" AND muscle_grade = '{grade}'"
    if since:
        sql += f" AND report_date >= '{since}'"
    sql += (" GROUP BY report_date, weight_low, weight_high "
            "ORDER BY weight_low, report_date")
    out = {}
    for d, wl, wh, px in conn.cursor().execute(sql).fetchall():
        label = f"{wl}-{wh} lb" if wh else f"{wl}+ lb"
        out.setdefault(label, []).append((str(db.iso(d)), float(px)))
    return out


def index_spread(conn, limit=None):
    """
    [(date, border_price, index_value, spread)] for the index-comparable slice.

    The border quote is Mexican-origin cattle at the crossing; the index is US
    cattle sold at auction and direct across 12 states. The gap is a real market
    relationship -- origin, quality, freight and who is buying -- not a
    mispricing, and the page says so. Both are $/cwt FOB, which is what makes
    subtracting them meaningful at all.

    Reads fci_daily, which lives in the same schema. Uses the reconstruction
    rather than CME's published file because it carries the current date, and a
    spread against a value three days stale would mostly measure the staleness.
    """
    rows = conn.cursor().execute(
        "SELECT p.report_date, AVG(p.avg_price), MAX(f.fci_value) "
        "FROM border_prices p JOIN fci_daily f ON p.report_date = f.report_date "
        f"WHERE p.class_desc = '{INDEX_CLASS}' "
        f"AND p.muscle_grade = '{INDEX_GRADE}' "
        f"AND p.weight_low = {INDEX_WEIGHT_LOW} "
        "AND p.avg_price IS NOT NULL "
        "GROUP BY p.report_date ORDER BY p.report_date").fetchall()
    out = [(str(db.iso(d)), float(b), float(f), float(b) - float(f))
           for d, b, f in rows if b is not None and f is not None]
    return out[-limit:] if limit else out


def spread_by_year(conn):
    """{year: {"n", "mean", "median", "last"}} for the index spread."""
    rows = index_spread(conn)
    by = {}
    for d, _b, _f, s in rows:
        by.setdefault(str(d)[:4], []).append(s)
    out = {}
    for y, vals in sorted(by.items()):
        v = sorted(vals)
        n = len(v)
        out[y] = {
            "n": n,
            "mean": sum(v) / n,
            "median": v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2,
            "last": vals[-1],
        }
    return out


def price_coverage(conn):
    """{year: {"price_days", "brackets"}} -- how thin the series is, per year."""
    rows = conn.cursor().execute(
        "SELECT report_date, weight_low FROM border_prices").fetchall()
    out = {}
    for d, wl in rows:
        y = str(db.iso(d))[:4]
        r = out.setdefault(y, {"days": set(), "brackets": set()})
        r["days"].add(str(db.iso(d)))
        r["brackets"].add(wl)
    return {y: {"price_days": len(r["days"]),
                "brackets": sorted(r["brackets"])}
            for y, r in sorted(out.items())}


def _national(conn):
    return conn.cursor().execute(
        "SELECT period, commodity, descr, head, value_usd "
        "FROM census_cattle_imports WHERE port_code = '' "
        "ORDER BY period").fetchall()


def monthly_head(conn, kinds=("feeder",)):
    """([(period, head)], data_through_period)."""
    agg = {}
    for period, commodity, descr, head, _v in _national(conn):
        if kinds and classify_commodity(commodity, descr) not in kinds:
            continue
        agg[str(period)] = agg.get(str(period), 0) + (head or 0)
    series = sorted(agg.items())
    return series, (series[-1][0] if series else None)


def annual_head(conn, kinds=("feeder",)):
    """{year: head} full-year totals, plus the data-through period."""
    series, through = monthly_head(conn, kinds)
    out = {}
    for period, head in series:
        y = int(str(period)[:4])
        out[y] = out.get(y, 0) + head
    return out, through


def ytd_compare(conn, kinds=("feeder",)):
    """
    {year: {...}} year-to-date on MONTHS PRESENT IN BOTH YEARS only.

    A partial current year must never be measured against a full prior year --
    the same trap that had the index's 2026 YTD reading the wrong sign before
    the weekday alignment went in.
    """
    series, through = monthly_head(conn, kinds)
    by = {}
    for period, head in series:
        y, m = str(period).split("-")
        by.setdefault(int(y), {})[int(m)] = head
    out = {}
    for y in sorted(by):
        prev = by.get(y - 1, {})
        shared = sorted(set(by[y]) & set(prev))
        cur = sum(by[y][m] for m in shared)
        prv = sum(prev[m] for m in shared)
        out[y] = {"total": sum(by[y].values()), "months": sorted(by[y]),
                  "shared_months": shared, "ytd": cur, "prior_ytd": prv,
                  "pct": (cur / prv - 1) * 100 if prv else None}
    return out, through


def band_shares(conn, year=None, kinds=("feeder",)):
    """[(band, head, share_pct)] for one year, light to heavy."""
    rows = _national(conn)
    years = sorted({int(str(p)[:4]) for p, *_ in rows})
    if not years:
        return [], None
    if year is None:
        # The newest year that actually carried volume -- the newest year on
        # file is all zeros during a suspension, which would render an empty
        # chart rather than the last real composition.
        for y in reversed(years):
            if any((h or 0) for p, c, d, h, _v in rows if str(p)[:4] == str(y)):
                year = y
                break
        else:
            year = years[-1]
    agg = {}
    for period, commodity, descr, head, _v in rows:
        if str(period)[:4] != str(year):
            continue
        if kinds and classify_commodity(commodity, descr) not in kinds:
            continue
        b = weight_band(descr)
        agg[b] = agg.get(b, 0) + (head or 0)
    total = sum(agg.values())
    out = [(b, agg.get(b, 0), (agg.get(b, 0) / total * 100) if total else 0)
           for b in BANDS if agg.get(b)]
    return out, year


def kind_totals(conn, year=None):
    """{kind: head} for one year -- the audit view behind the feeder headline."""
    rows = _national(conn)
    years = sorted({int(str(p)[:4]) for p, *_ in rows})
    if not years:
        return {}, None
    year = year if year is not None else years[-1]
    agg = {}
    for period, commodity, descr, head, _v in rows:
        if str(period)[:4] != str(year):
            continue
        k = classify_commodity(commodity, descr)
        agg[k] = agg.get(k, 0) + (head or 0)
    return agg, year


def value_per_head(conn, kinds=("feeder",)):
    """
    [(period, $/head)] -- the customs value per animal.

    Not a market price: it is the declared entry value, and it moves with both
    the cattle market and the mix of weights crossing. Useful as a level check
    on the head counts, not as a quote.
    """
    agg = {}
    for period, commodity, descr, head, value in _national(conn):
        if kinds and classify_commodity(commodity, descr) not in kinds:
            continue
        d = agg.setdefault(str(period), [0, 0])
        d[0] += (head or 0)
        d[1] += (value or 0)
    return [(p, v / h) for p, (h, v) in sorted(agg.items()) if h]


def data_freshness(conn):
    """What each source is current to -- shown so the lag is never implicit."""
    cur = conn.cursor()
    ams = cur.execute("SELECT MAX(report_date) FROM border_reports "
                      "WHERE kind = 'commentary'").fetchone()
    census_rows = cur.execute(
        "SELECT period, SUM(head) FROM census_cattle_imports "
        "WHERE port_code = '' GROUP BY period ORDER BY period").fetchall()
    last_nonzero = None
    for p, h in census_rows:
        if (h or 0) > 0:
            last_nonzero = str(p)
    return {
        "ams_through": str(db.iso(ams[0])) if ams and ams[0] else None,
        "census_through": str(census_rows[-1][0]) if census_rows else None,
        "census_last_volume": last_nonzero,
    }
