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


def latest_price_date(conn):
    """The newest date carrying a price, which is NOT the newest reporting day.

    AMS quotes only when enough head sell to establish a trend, so the two
    differ by 8 days in 2026 alone -- the rule `price_grid` already follows and
    the reason it takes its own default this way.
    """
    r = conn.cursor().execute(
        "SELECT MAX(report_date) FROM border_prices "
        "WHERE avg_price IS NOT NULL").fetchone()
    return str(db.iso(r[0])) if r and r[0] else None


def reopened_on(conn):
    """The most recent reopening date, or None. Thin wrapper over
    `reopening()` so a caller wanting only the date does not carry its dict."""
    r = reopening(conn)
    return r["date"] if r else None


def receipts_on(conn, on):
    """
    One day's head, as AMS published it and broken out by crossing.

    {"head", "wtd", "by_crossing": [(crossing, state, head)], "reconciles"}
    or None when that day has no receipts row at all.

    **THE TOTAL IS AMS'S OWN ROW, NEVER THE SUM OF THE PARTS.** `border_receipts`
    is a hierarchy -- all-points, per-state, per-crossing -- so summing
    everything triple-counts, and even the named crossings alone disagree with
    the published total on 19 of 463 days measured. `is_total` flags the
    authoritative row at ingest, which is why `daily_receipts` exists in the
    shape it does; this follows the same rule.

    `reconciles` says whether the named crossings happen to add to the published
    figure on this day, so a caller can show the breakdown and still be honest
    about it. It is NOT an audit in the sense `leverage.reconciles()` is -- a
    False here is AMS's own arithmetic, not evidence of a parsing fault, and the
    page must not cry error over it.

    **THERE IS NO HEAD COUNT PER WEIGHT BRACKET, AND NONE CAN BE DERIVED.**
    AMS publishes the price grid with no volume on it at all -- `border_prices`
    carries LOW/HIGH/AVG and nothing else -- so "how many head traded at this
    price" is unanswerable, and this figure is every feeder animal that crossed
    that day whatever it weighed. A caller putting it beside a price must say
    so, or a reader takes the day's whole count for the volume behind one rung.
    """
    cur = conn.cursor()
    iso = str(db.iso(on))
    r = cur.execute(
        "SELECT receipts_est, receipts_wtd_est FROM border_receipts "
        f"WHERE is_total = 1 AND report_date = '{iso}'").fetchone()
    if not r or r[0] is None:
        return None
    head, wtd = int(r[0]), (int(r[1]) if r[1] is not None else None)

    rows = cur.execute(
        "SELECT crossing_point, crossing_state, receipts_est "
        "FROM border_receipts WHERE is_total = 0 "
        "AND crossing_point <> 'All Crossing Points' "
        f"AND report_date = '{iso}' AND receipts_est IS NOT NULL "
        "ORDER BY receipts_est DESC").fetchall()
    parts = [(p, st, int(v)) for p, st, v in rows]
    return {
        "head": head,
        "wtd": wtd,
        "by_crossing": parts,
        "reconciles": bool(parts) and sum(v for _p, _s, v in parts) == head,
    }


def priced_day_head(conn, since=None):
    """
    (head_on_priced_days, head_on_all_reporting_days) since `since`.

    The gap is head that crossed on days AMS quoted no price for -- 1,350 of
    42,600 since the 2026 reopening, 8 days of 40. Worth printing beside a
    price because the alternative reading of "32 quoted days against 40
    reporting days" is that the missing 8 were empty, and they were not.
    """
    cur = conn.cursor()
    where = f" AND report_date >= '{since}'" if since else ""
    total = cur.execute(
        "SELECT SUM(receipts_est) FROM border_receipts "
        f"WHERE is_total = 1{where}").fetchone()[0]
    priced = cur.execute(
        "SELECT SUM(receipts_est) FROM border_receipts "
        f"WHERE is_total = 1{where} AND report_date IN "
        "(SELECT DISTINCT report_date FROM border_prices "
        " WHERE avg_price IS NOT NULL)").fetchone()[0]
    return (int(priced) if priced else 0, int(total) if total else 0)


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
# AMS NEVER PRE-ANNOUNCES A REOPENING IN THIS SERIES. Every one of 2026's is a
# same-day, past-tense note on the first day cattle crossed --
# "*** COLUMBUS, NM LIVESTOCK PORT OF ENTRY RE-OPENED. ***" on 2026-10-26,
# Santa Teresa on 09-24, Douglas on 08-24 -- and the only forward schedule the
# narrative has ever carried is the 2025-07-08 notice below, which did not
# happen. So a date here always comes from Ross and never from the feed, and it
# must be maintained by hand. Point it at whichever crossing is next once this
# one reopens, or clear it to None.
#
# Nogales, AZ, expected 2026-11-30 -- Ross, 2026-10-29. It replaced Columbus,
# which reopened on 2026-10-26 and is in the daily series from that date.
#
# AND AN ANNOUNCED DATE IS NOT A REOPENING. On 2025-07-08 AMS published
# "COLUMBUS AND SANTA TERESA, NM WILL RE-OPEN JULY 14TH AND 21ST RESPECTIVELY"
# and NEITHER happened: Columbus did not appear again until 2026-10-26, Santa
# Teresa recorded nothing at all between 2025-05-12 and 2026-09-24, and that
# July 2025 reopening lasted four reporting days of Douglas alone before the
# border shut again.
#
# THE DATE MAY SIZE A WINDOW; IT MAY NEVER SIZE A FLOW. watch_window() uses it
# to say how many reporting days a reopening could still touch, which is
# arithmetic on the calendar and true whether or not the port opens. What crosses
# in those days is read off restarts that actually happened -- see
# restart_curve(). The page states the whole thing as a conditional and keeps
# the "an announced date is not a reopening" caveat beside it.
WATCH_PORT = "Nogales"
WATCH_PORT_EXPECTED = "30 November 2026"
# The same expectation as a date, for watch_window() alone. Kept separate from
# the prose because the prose has to survive a vague expectation -- "end of
# October 2026" was one -- while only a real date may size a window. None means
# "expected back, no date", and the page then prices nothing.
WATCH_PORT_EXPECTED_ON = date(2026, 11, 30)


def state_abbr(port):
    """'Nogales' -> 'AZ', from KNOWN_PORTS. None for a crossing not listed there.

    KNOWN_PORTS already pairs each city with its state abbreviation and is what
    ports_in() matches the narrative against, so a second map would be the
    snowflake_db-times-five problem for the sake of three entries.
    """
    city = str(port or "").split(",")[0].strip().upper()
    for p in KNOWN_PORTS:
        c, _, st = p.partition(", ")
        if c.strip() == city:
            return st.strip()
    return None


def port_profile(conn, port, years=NORMAL_YEARS, this_year=None):
    """
    What one crossing did when the border was running normally, and whether it
    is running now.

        head, days, per_day   over `years`, counting only days it carried
                              cattle, so per_day is its rate while open
        share                 its share of all named-port head in those years
        per_reporting_day     share x the normal border rate -- the SAME basis
                              as daily_pace, see below
        state                 the crossing's state, from the data
        last_seen             the last date it carried cattle, ever
        running               whether it has carried cattle in `this_year`

    `per_day` AND `per_reporting_day` ARE NOT INTERCHANGEABLE AND THE SECOND IS
    THE ONE THAT MULTIPLIES BY A DAY COUNT. `days` counts only the days this
    crossing actually carried cattle -- Nogales had 234 of them across 2023-24
    against the border's 381 reporting days, 61% coverage -- so `per_day` is
    "head on a day it ran" and carries an implicit assumption of a head every
    single day. Multiplied by reporting days it reads 1,118 x N where the truth
    is 684 x N, 63% high, and the error is largest for exactly the small
    intermittent crossings a reopening note is about (Columbus 2.05x, Presidio
    1.94x, Santa Teresa only 1.07x).

    So quote `per_day` beside another while-open rate, and use
    `per_reporting_day` anywhere a figure is about to be multiplied by a span.

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
    # MAX(crossing_state) rather than a lookup table: the state is in the feed
    # (crossing_debuts already returns it) and a second copy here is the
    # snowflake_db-times-five problem in miniature. One state per crossing, so
    # MAX is just "the value" -- and it works on both backends, where ANY_VALUE
    # does not.
    last, state = cur.execute(
        "SELECT MAX(report_date), MAX(crossing_state) FROM border_receipts "
        f"WHERE is_total = 0 AND receipts_est > 0 "
        f"AND crossing_point = '{port}'").fetchone()
    yr = str(this_year or date.today().year)
    now = cur.execute(
        "SELECT COUNT(*) FROM border_receipts "
        "WHERE is_total = 0 AND receipts_est > 0 "
        f"AND crossing_point = '{port}' "
        f"AND TO_CHAR(report_date, 'YYYY') = '{yr}'").fetchone()[0]
    # The border's own reporting days over the same years -- the denominator
    # daily_pace() and project_year_end() work in. Taken from the total row, not
    # from this port's rows, which is the whole point: a port that reported on
    # 234 of 381 days contributed head on 234 and nothing on the other 147, and
    # both kinds of day are in the span a projection multiplies by.
    rdays = cur.execute(
        "SELECT COUNT(*) FROM border_receipts WHERE is_total = 1 "
        f"AND TO_CHAR(report_date, 'YYYY') IN ({yrs})").fetchone()[0]
    share = (head / total) if total else None
    return {
        "port": port,
        "head": head,
        "days": days,
        "per_day": head / days,
        "share": share,
        "per_reporting_day": (head / rdays) if rdays else None,
        "state": _clean(state) or None,
        # "AZ", not "Arizona". crossing_state is the authority for WHICH state
        # and KNOWN_PORTS is the authority for how this page SPELLS it -- every
        # other crossing on the screen reads "Douglas, AZ", so a lone
        # "Nogales, Arizona" reads as a different kind of thing.
        "state_abbr": state_abbr(port) or _clean(state) or None,
        "last_seen": str(db.iso(last)) if last else None,
        "running": bool(now),
        "years": years,
    }


# ── Restarts: what a crossing actually does when it comes back ──────────────
#
# THE QUESTION A REOPENING NOTE ASKS IS NOT "WHAT DID THIS PORT USED TO DO".
# port_profile()["per_day"] answers that, and it is the wrong answer twice: it
# is a while-open rate about to be multiplied by elapsed days (see that
# docstring), and it has a crossing restarting from nothing and hitting its own
# long-run normal immediately. The page already disowns that arithmetic in the
# 2027 scenarios block, where year_outlook() scales port CAPACITY instead and
# the caption prints a paragraph saying why. Using it as the high end of a 2026
# forecast would have one page publish a figure and refute it two screens down.
#
# WHAT THE SERIES ACTUALLY HOLDS IS SIX COMPLETED RESTARTS, and they are far
# more alike in head per day than in percentage of their own normal. Over each
# port's first 23 elapsed reporting days -- the length of a 30 November window:
#
#     Nogales      2025-02-19    515 head/day    46.1% of its own normal
#     Douglas      2025-02-06    622            51.2%
#     Douglas      2026-08-24    648            53.4%
#     Santa Teresa 2025-02-05    667            27.2%
#     Presidio     2025-02-21    698            68.9%
#     Santa Teresa 2026-09-24    730            29.8%
#
# Head per day spans 515-730, a coefficient of variation of 10.6%. The same six
# as a share of their own normal span 27.2-68.9%, CV 31.0% -- nearly three times
# wider. A restart looks to be limited by what the crossing can process on the
# way back rather than by how big it used to be: Santa Teresa normally moves
# 2,455 head a day and Nogales 1,118, and on their first 23 days back they did
# 730 and 515.
#
# So a reopening is priced from THE COHORT IN HEAD, never from a percentage of
# the port's own normal -- that route takes Santa Teresa's 27.2%, which is low
# only because Santa Teresa is huge, and lands Nogales at 304 head a day, below
# anything any crossing has ever managed coming back.

# A crossing with no row for this many days has stopped, so its next row is a
# restart rather than a quiet week. The real gaps are 410 and 534 days and the
# longest run of absences inside an open period is a fortnight, so anything from
# about 30 to 300 picks out the same six.
RESTART_GAP_DAYS = 60


def restarts(conn, port=None):
    """
    [(crossing, state, restart_date)] -- every time a crossing came back after
    being absent from the feed for more than RESTART_GAP_DAYS.

    A closed crossing has NO ROW AT ALL, which is what makes this readable: a
    zero-head row means AMS listed the port and nothing crossed, and those stay
    in. A port's first appearance in the series is not a restart and is
    excluded -- everything starts on 2023-05-05 because that is when AMS began
    publishing, not because ten crossings reopened that day.
    """
    sql = ("SELECT crossing_point, crossing_state, report_date "
           "FROM border_receipts WHERE is_total = 0 "
           "AND crossing_point <> 'All Crossing Points'")
    if port:
        sql += f" AND crossing_point = '{port}'"
    rows = conn.cursor().execute(
        sql + " ORDER BY crossing_point, report_date").fetchall()
    by_port = {}
    for p, s, d in rows:
        by_port.setdefault(p, (s, []))[1].append(_as_date(db.iso(d)))
    out = []
    for p, (s, dates) in by_port.items():
        for prev, cur in zip(dates, dates[1:]):
            if (cur - prev).days > RESTART_GAP_DAYS:
                out.append((p, _clean(s) or None, str(cur)))
    return sorted(out, key=lambda t: t[2])


# As far forward as a restart is tracked. Long enough to cover any window the
# page can ask for -- a reopening on the first business day of a year has about
# 250 reporting days left and nothing on this border has run 60 since coming
# back without the question becoming "what is its normal rate" instead.
RESTART_MAX_AGE = 60


def restart_ladder(conn, max_age=RESTART_MAX_AGE):
    """
    Every restart as a cumulative head count by elapsed reporting day.

        [{"port", "state", "from", "cum": [head after day 1, after day 2, ...]}]

    DATE-INDEPENDENT ON PURPOSE, so it can sit inside the page's 30-minute
    cache while the AGE it is read at cannot -- the window a reopening still
    has left shrinks every day whether or not Snowflake has anything new, which
    is the same reason project_year_end() is computed outside that cache. Build
    the ladder once, call curve_at() with today's window length.

    `cum` runs out early for a restart younger than `max_age`; curve_at()
    returns None past its end rather than reporting a short curve as a full one.
    """
    rows = conn.cursor().execute(
        "SELECT crossing_point, report_date, receipts_est FROM border_receipts "
        "WHERE is_total = 0 AND crossing_point <> 'All Crossing Points'"
    ).fetchall()
    head = {}
    for p, d, v in rows:
        head[(p, _as_date(db.iso(d)))] = v or 0
    # THE DAYS AMS ACTUALLY PUBLISHED, not a weekday calendar. NON_REPORTING is
    # maintained only for dates that can fall inside a projection window -- its
    # earliest entry is 2026-10-12 -- so walking the calendar counts Presidents
    # Day 2025-02-17 and Labor Day 2026-09-07 as reporting days on which
    # nothing crossed. Three of the six restarts on file sit across one of
    # those and each read about 4% low.
    #
    # It is also the denominator daily_pace() works in: that function averages
    # the trailing N ROWS of the daily series, which are published days. A rate
    # that is going to be added to that pace has to be measured the same way.
    pub = sorted({_as_date(db.iso(d)) for (d,) in conn.cursor().execute(
        "SELECT report_date FROM border_receipts WHERE is_total = 1").fetchall()})

    out = []
    for port, state, start in restarts(conn):
        d0 = _as_date(start)
        window = [d for d in pub if d >= d0][:max_age]
        cum, total = [], 0
        for d in window:
            total += head.get((port, d), 0)
            cum.append(total)
        out.append({"port": port, "state": state, "from": start, "cum": cum})
    return out


def curve_at(entry, age):
    """
    What one restart did over its first `age` ELAPSED reporting days, or None
    when it has not run that long.

    A partial curve reported as a full one is the "across its first 3" problem
    the Columbus note shipped with: three reporting days is not evidence about
    a twenty-three-day window, and a reader cannot tell the two apart once both
    are printed as "head a day".

    ELAPSED, not days-it-carried-cattle. This rate gets multiplied by a span of
    reporting days, so its denominator has to be that same span -- the unit
    error port_profile()'s docstring describes, which this exists to stop
    repeating.
    """
    if not entry or age < 1 or len(entry.get("cum") or []) < age:
        return None
    head = entry["cum"][age - 1]
    return {"port": entry["port"], "state": entry.get("state"),
            "from": entry["from"], "age": age,
            "head": head, "rate": head / age}


def cohort_at(ladder, age, exclude=None):
    """
    Every completed restart measured at the same age, slowest first.

    `exclude` drops a port from the comparison -- the page passes the watch
    port, so "what every OTHER crossing did coming back" and "what this one did
    last time" stay separate claims rather than one averaging the other in.

    Returns [] rather than None when nothing has run that long, so a caller can
    say "no restart on file has run this far" instead of rendering a dash.
    """
    out = [c for c in (curve_at(e, age) for e in (ladder or [])
                       if not (exclude and e["port"] == exclude)) if c]
    return sorted(out, key=lambda c: c["rate"])


def latest_restart(ladder, port):
    """The most recent restart of one crossing, or None if it has never had one."""
    mine = [e for e in (ladder or []) if e["port"] == port]
    return max(mine, key=lambda e: e["from"]) if mine else None


def shut_crossings(conn, this_year=None, years=NORMAL_YEARS):
    """
    [(crossing, share, last_seen)] for every crossing with history that is not
    running this year, largest share first.

    EXISTS BECAUSE "THE ONE SHUT CROSSING THAT USED TO CARRY REAL VOLUME" WAS
    NEVER TRUE. The page said it of Columbus at 11.30% while Nogales sat shut
    at 12.44% and Presidio at 9.48% -- wrong on the day it shipped and wrong in
    a way no reader could check. A superlative has to be read off the data or
    it is a claim about the day somebody wrote it.
    """
    sh = port_shares(conn, years=years)
    if not sh:
        return []
    yr = str(this_year or date.today().year)
    running = {p for (p,) in conn.cursor().execute(
        "SELECT DISTINCT crossing_point FROM border_receipts "
        "WHERE is_total = 0 AND receipts_est > 0 "
        f"AND TO_CHAR(report_date, 'YYYY') = '{yr}'").fetchall()}
    last = {p: str(db.iso(d)) for p, d in conn.cursor().execute(
        "SELECT crossing_point, MAX(report_date) FROM border_receipts "
        "WHERE is_total = 0 AND receipts_est > 0 "
        "GROUP BY crossing_point").fetchall()}
    out = [(p, s, last.get(p)) for p, s in sh["shares"].items()
           if p not in running]
    return sorted(out, key=lambda t: -t[1])


def ramp_weeks(series, since=None):
    """
    [{"week", "begin", "head", "days", "complete"}] from a reopening onward.

    Weeks are AMS's own Monday-to-Friday ones, numbered from 1 at the week the
    border came back, and `complete` says whether the week has all five
    reporting days on file yet.

    EXISTS SO THE PAGE STOPS QUOTING A WEEK NUMBER IT TYPED IN. The caption
    read "6,400 in week five this time" for nine weeks after week five, in the
    present tense, beside figures that were updating around it. A snapshot in
    prose is the failure this module keeps recording; the only fix is to read
    it at render time.
    """
    pts = sorted((_as_date(r[0]), r[1] or 0) for r in series)
    if since:
        since = _as_date(since)
        pts = [(d, h) for d, h in pts if d >= since]
    if not pts:
        return []
    first = pts[0][0] - timedelta(days=pts[0][0].weekday())
    weeks = {}
    for d, h in pts:
        mon = d - timedelta(days=d.weekday())
        w = weeks.setdefault(mon, {"begin": str(mon), "head": 0, "days": 0})
        w["head"] += h
        w["days"] += 1
    out = []
    for i, mon in enumerate(sorted(weeks), start=1):
        w = weeks[mon]
        out.append({"week": ((mon - first).days // 7) + 1, "begin": w["begin"],
                    "head": w["head"], "days": w["days"],
                    "complete": w["days"] >= reporting_days(
                        mon, mon + timedelta(days=4))})
    return out


def watch_window(through, expected=None, year=None):
    """
    Reporting days a shut crossing could still contribute to `year`.

    {"start", "end", "days", "lapsed", "overdue", "stale"}, or None when there
    is no expected date -- "expected back, no date given" prices nothing, which
    is the honest answer and the one the rule above WATCH_PORT demands.

        overdue   the date has passed and the crossing has not come back
        stale     it passed in an EARLIER YEAR, so the constant needs re-setting
                  by hand, and `days` is zero

    STALE IS NOT A TIDINESS FLAG. Without it a 30 November 2026 expectation read
    on 2027-02-01, with the port still shut, gives a window of 229 reporting
    days and a caption reading "expected back 30 November 2026 -- which leaves
    229 reporting days in 2027", pricing a hundred thousand head off a date
    fourteen months old. WATCH_PORT_EXPECTED_ON is maintained by hand and this
    is the one state in which nothing reminds anybody to.

    START IS max(expected, the day after the last report), and that is the
    whole correctness of it. Anchored on the announced date alone a window goes
    on claiming 23 reporting days deep into December while the port stays shut,
    pricing days that are already counted as actual in the projection box it is
    being added to. This is the same anchor project_year_end() uses for
    days_left, which is what keeps the window a subset of it and so legitimate
    to add.

    IT SIZES A WINDOW AND NOTHING ELSE. How many reporting days lie between a
    date and 31 December is arithmetic on the calendar, true whether or not the
    crossing opens. What crosses in them comes from restarts that actually
    happened -- restart_curve() -- and the page states the pair as a
    conditional.
    """
    if expected is None:
        return None
    through = _as_date(through)
    expected = _as_date(expected)
    yr = year or through.year
    end = date(yr, 12, 31)
    start = max(expected, through + timedelta(days=1))
    overdue = expected <= through
    if expected.year < yr:
        return {"start": str(start), "end": str(end), "days": 0,
                "lapsed": True, "overdue": True, "stale": True}
    if start > end:
        return {"start": str(start), "end": str(end), "days": 0,
                "lapsed": True, "overdue": overdue, "stale": False}
    return {"start": str(start), "end": str(end),
            "days": reporting_days(start, end), "lapsed": False,
            "overdue": overdue, "stale": False}


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
    would catch. Nogales ran 1,118 head on each day it was open in 2023-24, so
    "add Nogales back" reads as +1,118/day -- about +278,000 on a 249-day year.
    But the ports that ARE open are managing well under two thirds of what they
    normally do, and a crossing that reopened last month will not instantly
    outrun its neighbours. Scaling port capacity instead -- Nogales is 12.4% of
    a normal border against the 68.1% already open, so +18% -- gives +99,800.
    The naive figure is about 2.8x too high and arrives wearing the same units.

    THOSE TWO MULTIPLES ARE READ OFF THE DATA AT RENDER TIME, NOT FROM HERE. An
    earlier version of this paragraph said "+67,600" and "4.7x", computed when
    only Douglas and Santa Teresa were open; both drifted the moment a third
    port came back, and CLAUDE.md went on quoting the 4.7x as a standing rule.
    Treat the figures above as an illustration of the shape and never as a
    measurement.

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
    # A CROSSING THAT HAS ALREADY REOPENED IS NOT A SCENARIO, and nothing
    # stopped it being counted as one until 2026-10-26. Columbus came back that
    # morning, WATCH_PORT still said "Columbus", and the panel went on offering
    # +90,679 head for an event that had happened -- on a pace that already
    # contained its cattle, with "Columbus" twice in one tile label
    # ("Douglas/Santa Teresa/Columbus/Columbus") and `mature` double-counting
    # its 11.3% share for a 154,673-head error.
    #
    # The clincher is that `mature` describes the SAME SET OF PORTS either way,
    # so it should not have moved at all, and it jumped 16.6% on the day the
    # port opened. Nothing raised, nothing could: every figure stayed a
    # plausible head count.
    #
    # Dropped rather than raised. Every watch port eventually opens, this is
    # the ordinary end of its life, and the page has no try/except around this
    # call -- a raise would take the whole dashboard down on a good-news day.
    if watch and watch in open_ports:
        watch = None
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


def weight_spans(conn, since=None, class_desc=None):
    """
    {date: {"low", "high", "n", "classes", "label"}} -- the weight range AMS
    QUOTED that day, which is the only daily weight signal that exists.

    **IT IS A SPAN OF WHAT WAS QUOTED, NOT AN AVERAGE OF WHAT CROSSED, AND
    THERE IS NO AVERAGE TO BE HAD.** Established by probe on 2026-10-21 against
    the feeds themselves rather than inferred from the shape of our own tables:

      * AMS 3486 has four sections. `Report Volume` carries head and nothing
        else -- and `receipts_current_wtd_est` is WEEK-TO-DATE head, not a
        weighted anything, which is the one field name on this feed that
        invites exactly the wrong reading. `Report Detail Current` and
        `Report Detail WTD` carry `weight_break_low`/`weight_break_high`, which
        are quote brackets with no head against them, plus `weight_collect`,
        which is the string "Estimate" describing how the break was collected
        rather than a number.
      * AMS 3629 has three sections and 21,179 rows and NOT ONE weight field.
      * Census does publish head by HS weight class -- a real distribution, and
        what `band_shares()` already reads -- but its top class is OPEN-ENDED
        ("320 kg or more"). That class held 1.4% of head across the whole
        record and **27.8% in August 2026**, so assuming 360 against 450 kg for
        it moves a head-weighted average from 635 lb to 690 lb. An average
        resting on a 55 lb assumption nobody can check is not a figure this
        page should print, and it would be at its worst precisely in the
        reopening months anyone would want it for.

    So the span is what AMS actually says, and it earns a column because it
    MOVES: inside the current window alone it is 400-800 lb on 19 days and
    500-800 lb on 13. The light end carries the signal: the 300-400 lb bracket
    ran until 2025-02-18 and has not been quoted since, and the light end came
    back only to 400 lb on reopening, never to 300. The calves that used to
    cross are not crossing.

    AMS quotes a bracket only when enough head sell to establish a trend in it,
    the rule `price_grid` already records for the day as a whole. An absent
    bracket is therefore one that did not trade in volume rather than one
    nobody looked at -- which is the strongest inference available here, and is
    still not a head count.

    `classes` is carried because the span pools whatever classes were quoted
    and they are not interchangeable: heifers are quoted on 1 day of 2026
    against steers on 32, so a day pooling both is a different population from
    its neighbours and the caller can say so rather than guess.
    """
    sql = ("SELECT report_date, MIN(weight_low), MAX(weight_high), "
           "       COUNT(DISTINCT weight_low), "
           "       LISTAGG(DISTINCT class_desc, '|') "
           "FROM border_prices WHERE avg_price IS NOT NULL")
    if class_desc:
        sql += f" AND class_desc = '{class_desc}'"
    if since:
        sql += f" AND report_date >= '{since}'"
    sql += " GROUP BY report_date ORDER BY report_date"
    out = {}
    for d, lo, hi, n, cls in conn.cursor().execute(sql).fetchall():
        if lo is None or hi is None:
            continue
        out[str(db.iso(d))] = {
            "low": int(lo), "high": int(hi), "n": int(n),
            "classes": sorted(str(cls).split("|")) if cls else [],
            # Formatted HERE so the tile, the table and any caption cannot
            # drift into two spellings of one span -- the en dash and the unit
            # are part of the figure, not of the layout.
            "label": f"{int(lo)}–{int(hi)} lb",
        }
    return out


def index_spread(conn, limit=None, crossing=None):
    """
    [(date, border_price, index_value, spread, crossings)] for the
    index-comparable slice.

    The border quote is Mexican-origin cattle at the crossing; the index is US
    cattle sold at auction and direct across 12 states. The gap is a real market
    relationship -- origin, quality, freight and who is buying -- not a
    mispricing, and the page says so. Both are $/cwt FOB, which is what makes
    subtracting them meaningful at all.

    Reads fci_daily, which lives in the same schema. Uses the reconstruction
    rather than CME's published file because it carries the current date, and a
    spread against a value three days stale would mostly measure the staleness.

    **WITH NO `crossing`, A DAY'S PRICE IS AVERAGED OVER WHICHEVER CROSSINGS
    QUOTED, AND THE ROSTER MOVES.** That is not a detail: in 2025 four crossings
    quoted this rung (Nogales, Douglas, Santa Teresa, Presidio) and in 2026 only
    two, and they are not interchangeable -- where both quoted in 2026 they sat
    $1 to $6 apart, mean $4, and over the year Douglas averaged $4.87 under
    Santa Teresa. So a crossing joining or leaving a day moves the average with
    no buyer changing his bid, which is the failure
    `six_state.bracket_move()` exists for on the other dashboard.

    Each row therefore carries the crossings it was built from, so a caller can
    name them instead of guessing, and `crossing` restricts the series to one
    so a comparison can be made on a fixed roster.
    """
    where = (f"AND p.crossing_point = '{crossing}' " if crossing else "")
    rows = conn.cursor().execute(
        "SELECT p.report_date, AVG(p.avg_price), MAX(f.fci_value), "
        "       LISTAGG(DISTINCT p.crossing_point, '|') "
        "FROM border_prices p JOIN fci_daily f ON p.report_date = f.report_date "
        f"WHERE p.class_desc = '{INDEX_CLASS}' "
        f"AND p.muscle_grade = '{INDEX_GRADE}' "
        f"AND p.weight_low = {INDEX_WEIGHT_LOW} "
        "AND p.avg_price IS NOT NULL "
        f"{where}"
        "GROUP BY p.report_date ORDER BY p.report_date").fetchall()
    out = [(str(db.iso(d)), float(b), float(f), float(b) - float(f),
            sorted(str(c).split("|")) if c else [])
           for d, b, f, c in rows if b is not None and f is not None]
    return out[-limit:] if limit else out


# A gap this long in the QUOTED SPREAD closes a window. It is `reopening()`'s
# own default, deliberately: one definition of "shut" in this module, so if a
# window boundary and a reopening date ever differ it is because of what was
# QUOTED, never because two functions disagree about what a closure is.
#
# MEASURED, NOT CHOSEN. The spread series has 84 dates and exactly ONE gap of
# 20 days or more -- 470 days, May 2025 to Aug 2026 -- so every threshold from
# 20 to 470 yields today's two windows. 45 sits well above the longest quote
# drought inside an open border (2026 has 32 quoted days across 40 reporting
# days and its longest unquoted run is under 20) and well below every real
# closure on file (72, 56 and 410 days). Nothing here is delicate; the number
# is headroom on both sides rather than a fitted parameter.
WINDOW_GAP_DAYS = 45

# Below this a window is REPORTED and FLAGGED, never dropped and never
# headlined against another window. One reporting week.
#
# It guards a future reopening, not anything on file: both current windows are
# 52 and 32 quoted days. The case is a border that reopens, quotes three days
# and shuts -- which is not hypothetical, since crossings did exactly that over
# 2025-07-07..07-10. A 3-day mean set against a 52-day one under a sentence
# saying the discount "has roughly halved" is a plausible claim about nothing,
# and it is what this page would have printed.
MIN_WINDOW_DAYS = 5


# Bump when spread_by_window(), spread_windows() or basis_move() change the
# SHAPE of what they return. st.cache_data keys on the decorated loader's own
# code and arguments and is BLIND to the modules it calls, so a reshaped dict
# is served from a cache built before the reshape and the tile reading a new
# key renders an em dash with nothing raising -- the leverage.SCHEMA trap. The
# page now reads this module's window dicts BY KEY, which is exactly that
# shape, so it has to be passed at the call site: a default is not part of the
# key, and neither is an argument whose name starts with an underscore.
SCHEMA = 2


def _window_bounds(dates, gap_days=WINDOW_GAP_DAYS):
    """[(start, end)] -- split an ascending ISO date list wherever it jumps.

    Pure and connection-free so a test can hand it the real 84 dates, which is
    the only way to pin the boundaries without a warehouse.
    """
    if not dates:
        return []
    out, start, prev = [], dates[0], dates[0]
    for d in dates[1:]:
        if (_as_date(d) - _as_date(prev)).days >= gap_days:
            out.append((start, prev))
            start = d
        prev = d
    out.append((start, prev))
    return out


def spread_windows(conn, gap_days=WINDOW_GAP_DAYS):
    """[(start, end)] for the priced spread, oldest first.

    The enumeration `reopening()` deliberately does not provide -- it answers
    only "when did the border last reopen", and the PRIOR window's mean is a
    figure this page has always printed, so something has to list them all.
    """
    return _window_bounds([d for d, _b, _f, _s, _c in index_spread(conn)],
                          gap_days)


def spread_by_window(conn, crossing=None, gap_days=WINDOW_GAP_DAYS, today=None):
    """
    {start: {"n","mean","median","last","crossings","start","end","open"}} --
    the index spread, one entry per OPEN WINDOW, oldest first.

    **THIS REPLACED A CALENDAR-YEAR BUCKET AND THE YEAR WAS NEVER THE UNIT.**
    The border is shut for long stretches -- screwworm closed it Nov 2024, it
    ran Feb-May 2025, shut again, and reopened 2026-08-24 -- so a year splits
    one trading window and pools two others. Today the two windows coincide
    exactly with calendar 2025 and 2026, which is why the old keying looked
    right: every figure it printed was correct and would have stayed correct
    until 1 January, when the tile would have rolled to a near-empty "2027"
    while the window that began in August ran on unbroken.

    **THE BOUNDS ARE COMPUTED ON THE UNFILTERED SERIES, ALWAYS, AND THEN
    APPLIED AS A DATE FILTER.** Segmenting a single crossing's own dates would
    let that crossing invent a boundary: Santa Teresa quotes on 12 days of the
    current window against Douglas's 29, so a crossing that happens to skip
    seven weeks would split one window in two and `basis_move` would then
    compare a window to half of itself. A window is a property of the BORDER.

    Segmented on the priced spread rather than on crossings, for three reasons.
    A window is a claim about which rows belong in one average, so it has to be
    a property of the series being averaged. Crossings resumed for three days
    in July 2025 (07-07..07-10) with no index-rung price quoted at all, so a
    crossing-derived boundary produces a window holding zero priced days -- a
    row with n=0 and no mean, needing a suppression rule that exists only
    because the boundary came from the wrong series. And it is self-auditing:
    the windows' counts sum to len(index_spread(conn)), so no quoted day can
    fall between two windows.

    `open` says the newest window is still running -- no closure-length gap
    since its last quote -- so a caller can say "since" rather than asserting a
    window is current when the border has shut again.
    """
    bounds = spread_windows(conn, gap_days)
    rows = index_spread(conn, crossing=crossing)
    ref = _as_date(today) if today else date.today()
    out = {}
    for lo, hi in bounds:
        vals = [s for d, _b, _f, s, _c in rows if lo <= d <= hi]
        if not vals:
            # Only reachable with a `crossing` filter: the border was open and
            # this one crossing never quoted in it. Skipped rather than stored
            # as n=0, so a caller averaging windows cannot divide by nothing.
            continue
        seen = sorted({c for d, _b, _f, _s, cr in rows if lo <= d <= hi
                       for c in cr})
        v = sorted(vals)
        n = len(v)
        out[lo] = {
            "n": n,
            "mean": sum(v) / n,
            "median": v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2,
            "last": vals[-1],
            "crossings": seen,
            "start": lo,
            "end": hi,
            "open": (ref - _as_date(hi)).days < gap_days,
            "thin": n < MIN_WINDOW_DAYS,
        }
    return out


def basis_move(conn, window=None, prior=None):
    """
    The year-on-year change in the border basis, as REPORTED and on a FIXED
    ROSTER of crossings. Returns None if either year is missing.

    THE TWO ARE DIFFERENT NUMBERS AND THE DIFFERENCE IS THE WHOLE POINT, the
    same shape `six_state.bracket_move()` uses. 2025 carried four crossings on
    this rung and 2026 carries two, so the reported narrowing mixes a market
    move with a roster change. `same_crossing` restricts BOTH years to the
    crossings they share, which is the only comparison in which no crossing
    entering or leaving can move the answer.

    `reported` is kept beside it rather than thrown away -- it is what USDA's
    own published rows average to, and the page shows both when they differ.
    """
    allw = spread_by_window(conn)
    keys = list(allw)
    # Defaulting to the two newest windows is what keeps this function and the
    # tile on the same pair by construction. Both read one ordered dict, so a
    # caller cannot headline one window while the roster check describes
    # another -- the letter-versus-dashboard failure this file records five
    # times, which only ever needed two surfaces picking their own rows.
    if window is None:
        window = keys[-1] if keys else None
    if prior is None:
        prior = keys[-2] if len(keys) > 1 else None
    a, b = allw.get(prior), allw.get(window)
    if not a or not b:
        return None
    # A roster decomposition across a 3-day window is arithmetic on noise, and
    # it would render as confidently as any other. Refusing here rather than in
    # the page means every caller gets the refusal, and the page's existing
    # `if _bm` guard already drops the sentence.
    if a["thin"] or b["thin"]:
        return None

    panel = sorted(set(a["crossings"]) & set(b["crossings"]))
    pa = pb = None
    if panel:
        # Restricted to the shared roster, both windows, one crossing at a
        # time and then averaged -- never a single SQL AVG over the set, which
        # would weight a crossing by how often it quoted rather than equally.
        #
        # spread_by_window takes its BOUNDS from the unfiltered series even on
        # a filtered call, so `key` still names the same span for every
        # crossing. Segmenting a crossing's own dates would let Santa Teresa,
        # which quotes on 12 of the current window's 32 days, split that window
        # and have this average a sub-window against a whole one.
        def restricted(key):
            vals = []
            for cx in panel:
                w = spread_by_window(conn, crossing=cx).get(key)
                if w:
                    vals.append(w["mean"])
            return sum(vals) / len(vals) if vals else None
        pa, pb = restricted(prior), restricted(window)

    reported = b["mean"] - a["mean"]
    same = (pb - pa) if (pa is not None and pb is not None) else None
    return {
        "reported": reported,
        "same_crossing": same,
        "roster": (reported - same) if same is not None else None,
        "panel": panel,
        "prior_panel": a["crossings"],
        "year_panel": b["crossings"],
        "prior_same": pa,
        "year_same": pb,
    }


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


# Below this a month's MIX is one shipment's worth of cattle and moves on
# nothing. Measured: the two thin months on file are 2025-07 at 4,339 head and
# 2026-08 at 2,453, against a normal month of 85,000-150,000. July 2025 prints
# 52.8% in the top band off 4,339 head, which on a share chart reads as a
# regime change and is a single load.
MIN_MIX_HEAD = 20_000

# A band that never reaches this share in any month is a flat line on the axis
# and a fourth legend entry for nothing. Only `<90 kg` is affected -- 252 head
# in seven years, four months, peak share 0.15% -- and the caller is handed the
# omitted total so the page can say what was left out rather than quietly
# dropping it.
MIN_BAND_SHARE = 1.0


def band_mix_monthly(conn, kinds=("feeder",)):
    """
    The weight-class mix of crossing cattle, month by month.

    {"months", "head", "share", "bands", "omitted", "thin", "baseline",
     "latest"} -- `months` is a CONTIGUOUS run of 'YYYY-MM', `head` and each
    series in `share` carry None where no cattle crossed.

    **THIS IS THE ONLY ASSUMPTION-FREE WEIGHT STATEMENT AVAILABLE, AND IT IS A
    MIX RATHER THAN AN AVERAGE.** Census publishes head against its own HS
    weight classes, so a share is division and nothing else. An AVERAGE is not
    available from it and must not be derived here: the top class is
    OPEN-ENDED ("320 kg or more"), and it held 1.4% of head across the record
    but 27.8% in August 2026 -- so assuming 360 against 450 kg for it swings a
    head-weighted average from 635 lb to 690. The assumption would be at its
    worst in exactly the months anyone wants the figure for.
    `weight_spans()` records the four feeds checked for a published average.

    **CONTIGUOUS BY CONSTRUCTION, because the holes are the story.** Census has
    84 months on file and two of them are absent entirely (2025-01, and
    2026-01 through 2026-07) plus seven more at zero head -- the screwworm
    closures. Plotting only the months that exist would pack a 14-month closure
    into the gap between two adjacent points and hide it. The grid is filled
    and the blanks are None, never 0: a month with no cattle has no mix, and a
    zero share would read as "no light cattle crossed" rather than "nothing
    crossed". Same rule `cold_storage.monthly_frame` follows.

    **It independently corroborates the AMS quoted-bracket series**, which is
    worth knowing because the two come from different agencies by different
    routes. AMS stopped quoting its 300-400 lb bracket after 2025-02-18;
    Census's 90-200 kg class (198-441 lb) went from 24.3% of head in 2024 to
    2.8% in 2025. Same quarter, same direction, neither derived from the other.
    """
    rows = _national(conn)
    agg = {}
    for period, commodity, descr, head, _v in rows:
        if kinds and classify_commodity(commodity, descr) not in kinds:
            continue
        m = agg.setdefault(str(period), {})
        b = weight_band(descr)
        m[b] = m.get(b, 0) + (head or 0)
    if not agg:
        return None

    def nxt(p):
        y, mo = int(p[:4]), int(p[5:7])
        return f"{y + 1:04d}-01" if mo == 12 else f"{y:04d}-{mo + 1:02d}"

    lo, hi = min(agg), max(agg)
    months, p = [], lo
    while True:
        months.append(p)
        if p == hi:
            break
        p = nxt(p)

    head = [(sum(agg[m].values()) if m in agg else 0) or None for m in months]

    # Which bands are worth a line. Computed over months that HAVE cattle, so
    # the closure cannot dilute a band out of the chart.
    peak = {}
    for m, h in zip(months, head):
        if not h:
            continue
        for b in BANDS:
            peak[b] = max(peak.get(b, 0.0), agg[m].get(b, 0) / h * 100)
    bands = [b for b in BANDS if peak.get(b, 0) >= MIN_BAND_SHARE]
    omitted = {}
    for b in BANDS:
        if b in bands:
            continue
        t = sum(agg[m].get(b, 0) for m in agg)
        if t:
            omitted[b] = t

    share = {b: [] for b in bands}
    for m, h in zip(months, head):
        for b in bands:
            share[b].append(agg[m].get(b, 0) / h * 100 if h else None)

    thin = [(m, h) for m, h in zip(months, head)
            if h and h < MIN_MIX_HEAD]

    # The baseline is the twelve months before the FIRST month with no cattle
    # -- the border as it ran normally. Not a calendar year: the first closure
    # landed in December, so a year would mix two regimes and understate the
    # change the chart exists to show.
    first_dark = next((i for i, h in enumerate(head) if not h), None)
    baseline = None
    if first_dark is not None and first_dark >= 12:
        window = [(m, h) for m, h in zip(months[:first_dark],
                                         head[:first_dark])][-12:]
        tot = sum(h for _m, h in window)
        if tot:
            # Periods, never a formatted label: fmt_month lives on the page
            # and this module has no business choosing how a month is spelled.
            baseline = {
                "from": window[0][0], "to": window[-1][0], "head": tot,
                "share": {b: sum(agg[m].get(b, 0) for m, _h in window)
                          / tot * 100 for b in bands},
            }

    latest = None
    for m, h in zip(reversed(months), reversed(head)):
        if h:
            latest = {"month": m, "head": h,
                      "share": {b: agg[m].get(b, 0) / h * 100 for b in bands}}
            break

    return {"months": months, "head": head, "share": share, "bands": bands,
            "omitted": omitted, "thin": thin, "baseline": baseline,
            "latest": latest}


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
