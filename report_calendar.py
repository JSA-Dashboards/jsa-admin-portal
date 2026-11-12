"""
report_calendar.py -- the portal's report calendar: a "This Week's Reports" panel for the Grain and Livestock home pages and a
Reports Calendar tab (month grid + list).

Kolten 2026-11-12: a USDA reports calendar tab, "This Weeks Reports" on the home page for grain and for livestock, and the
economic reports (monthly CPI and PPI) co-mingled into both. Official dates only (no "usual schedule" guesses).

WHERE THE DATES COME FROM
  USDA NASS   the agency's own .ics release calendar, read live (https://www.nass.usda.gov/Publications/Calendar/<year>/
              NassReleases<year>.ics: every NASS report with its day and time; the next year appears when NASS publishes it).
              Only the reports a grain or livestock desk watches are kept (GRAIN_NASS / LIVESTOCK_NASS below); the rest of the ~90
              titles (hops, mushrooms, floriculture ...) and the HOLIDAY rows are dropped on purpose.
  WASDE       typed in report_schedule_data.py (USDA's own list; ESMIS only lists reports already published).
  CPI, PPI    typed in report_schedule_data.py (BLS's schedule; BLS answers a script with 403).
  EIA         read live from EIA's own schedule pages (they answer a script), all tagged "economic": the Weekly Petroleum Status Report
              (ethanol production and stocks are in it), the Weekly Natural Gas Storage Report, the Short-Term Energy Outlook and the
              Petroleum Supply Monthly. See the EIA section below for how the weekly ones are built from their holiday-exception tables.
  CFTC        the Commitments of Traders release schedule page (it answers a script), 3:30 PM ET, holiday delays marked there.
  Export Sales  FAS's calendar, typed (EXPORT_SALES_OFFICIAL: it answers a script with 403) for the dates FAS has published; after those,
              FAS's own holiday rule ("usual schedule" in the notes), looking ahead 120 days at most.
  Export Inspections  Mondays 11:00 AM ET, Tuesday after a Monday holiday: the usual schedule (no calendar is published), 120 days at most.
  Holidays    US federal holidays from the statute (observed dates: Saturday -> Friday, Sunday -> Monday) and the days CME's grain and
              livestock futures are closed (the federal list less Columbus Day and Veterans Day, plus Good Friday). The extra hours detail
              (early closes) is typed only where CME has published it; CME confirms holiday hours about two weeks ahead.
  Canada      Statistics Canada's own release-schedule JSON (the "key indicators" feed behind its calendar page: it answers a script and looks
              ahead to about March 2027): the crop reports (areas, production, stocks, model-based estimates), Farm income and the Canadian CPI.
              The Daily is published at 8:30 AM ET. Crop reports are tagged grain AND international, so they also show on the Grain card.
  Brazil      CONAB's own calendar PDF, typed (CONAB_*): the monthly grain surveys, the crop-monitoring bulletins and the Monday 7 PM Brasilia
              crop-progress release. Tagged grain AND international.
  Argentina   NOT included: the Buenos Aires Grain Exchange sits behind a Cloudflare challenge and Rosario's site shows no release calendar,
              so there is no official date to show. (The tab says so.)
Times are shown in Central.

TAGS. Every event carries a set of tags: "grain", "livestock", "economic". A scope shows the events tagged with it PLUS every
"economic" one, which is how CPI / PPI end up on both pages. WASDE and Agricultural Prices are tagged for both.
"""
from __future__ import annotations

import calendar
import html
import re
import shutil
import subprocess
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import report_schedule_data as D

CT = ZoneInfo("America/Chicago")
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
NASS_ICS_URL = "https://www.nass.usda.gov/Publications/Calendar/{year}/NassReleases{year}.ics"
UA = "jsa-report-calendar"

G, L, E, H, I = "grain", "livestock", "economic", "holiday", "international"
BOTH = frozenset({G, L})

# NASS .ics SUMMARY (spaces collapsed, "\," unescaped) -> (tags, title shown)
GRAIN_NASS: dict[str, tuple[frozenset, str]] = {n: (frozenset({G}), t) for n, t in {
    "Crop Progress": "Crop Progress",
    "Crop Production": "Crop Production",
    "Crop Production Annual Summary": "Crop Production Annual Summary",
    "Grain Stocks": "Grain Stocks",
    "Acreage": "Acreage",
    "Prospective Plantings": "Prospective Plantings",
    "Small Grains Summary": "Small Grains Summary",
    "Winter Wheat and Canola Seedings": "Winter Wheat and Canola Seedings",
    "Grain Crushings": "Grain Crushings",
    "Fats & Oils": "Fats & Oils: Oilseed Crushings",
    "North American Grain and Oilseed Crushings": "North American Grain and Oilseed Crushings",
    "Rice Stocks": "Rice Stocks",
    "Flour Milling": "Flour Milling Products",
    "Crop Values": "Crop Values",
    "Land Values": "Land Values",
    "Cash Rents- State": "Cash Rents (state)",
    "County Estimates Corn, Soybeans, Sorghum": "County Estimates: Corn, Soybeans, Sorghum",
    "County Estimates Barley, Oats, Winter Wheat, Durum": "County Estimates: Barley, Oats, Winter Wheat, Durum",
}.items()}

LIVESTOCK_NASS: dict[str, tuple[frozenset, str]] = {n: (frozenset({L}), t) for n, t in {
    "Cattle on Feed": "Cattle on Feed",
    "Cattle": "Cattle (inventory)",
    "Hogs and Pigs": "Quarterly Hogs and Pigs",
    "Cold Storage": "Cold Storage",
    "Livestock Slaughter": "Livestock Slaughter",
    "Slaughter Weekly": "Slaughter Weekly",
    "Milk Production": "Milk Production",
    "Dairy Products": "Dairy Products",
    "Chickens and Eggs": "Chickens and Eggs",
    "Egg Products": "Egg Products",
    "Poultry Slaughter": "Poultry Slaughter",
    "Broiler Hatchery": "Broiler Hatchery",
    "Turkey Hatchery": "Turkey Hatchery",
    "Sheep and Goats": "Sheep and Goats",
    "Meat Animals Production, Disposition and Income": "Meat Animals Production, Disposition and Income",
    "Milk Production, Disposition, and Income": "Milk Production, Disposition and Income",
    "Cold Storage Annual Summary": "Cold Storage Annual Summary",
    "Livestock Slaughter Annual Summary": "Livestock Slaughter Annual Summary",
    "Chickens and Eggs Annual Summary": "Chickens and Eggs Annual Summary",
    "Poultry Slaughter Annual Summary": "Poultry Slaughter Annual Summary",
    "Dairy Products Annual Summary": "Dairy Products Annual Summary",
    "Poultry - Production and Value": "Poultry Production and Value",
    "Hatchery Production Annual Summary": "Hatchery Production Annual Summary",
    "Turkeys Raised": "Turkeys Raised",
    "U.S. and Canadian Cattle and Sheep": "U.S. and Canadian Cattle and Sheep",
    "U.S. and Canadian Hogs": "U.S. and Canadian Hogs",
    "United States and Canadian Cattle": "United States and Canadian Cattle",
    "United States and Canadian Hogs": "United States and Canadian Hogs",
    "Capacity of Refrigerated Warehouses": "Capacity of Refrigerated Warehouses",
    "County Estimates Cattle & Sheep": "County Estimates: Cattle and Sheep",
}.items()}

NASS_BOTH = {"Agricultural Prices": (BOTH, "Agricultural Prices")}
NASS_KEEP: dict[str, tuple[frozenset, str]] = {**GRAIN_NASS, **LIVESTOCK_NASS, **NASS_BOTH}


EIA_WPSR_URL = "https://www.eia.gov/petroleum/supply/weekly/schedule.php"
EIA_NGS_URL = "https://ir.eia.gov/ngs/schedule.html"
EIA_STEO_URL = "https://www.eia.gov/outlooks/steo/release_schedule.php"
EIA_PSM_URL = "https://www.eia.gov/petroleum/supply/monthly/"


# -- parsing -----------------------------------------------------------------------------
_EVENT = re.compile(r"BEGIN:VEVENT(.*?)END:VEVENT", re.S)
_SUMMARY = re.compile(r"^SUMMARY:(.*)$", re.M)
_START = re.compile(r"^DTSTART[^:]*:(\d{8})(?:T(\d{6})Z?)?", re.M)


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\\,", ",").replace("\\;", ";")).strip()


def parse_nass_ics(text: str) -> list[dict]:
    """The kept NASS reports of one .ics file as events. A date-only start is taken as 12:00 ET."""
    out = []
    for ev in _EVENT.findall(text.replace("\r", "")):
        sm, st = _SUMMARY.search(ev), _START.search(ev)
        if not sm or not st:
            continue
        keep = NASS_KEEP.get(norm_name(sm.group(1)))
        if not keep:
            continue
        d, hms = st.group(1), st.group(2)
        if hms:
            when = datetime(int(d[:4]), int(d[4:6]), int(d[6:]), int(hms[:2]), int(hms[2:4]), tzinfo=UTC).astimezone(CT)
        else:
            when = datetime(int(d[:4]), int(d[4:6]), int(d[6:]), 12, 0, tzinfo=ET).astimezone(CT)
        out.append({"when": when, "title": keep[1], "source": "USDA NASS", "tags": keep[0], "note": ""})
    return out


def _et(d: date, hm: tuple[int, int]) -> datetime:
    return datetime.combine(d, time(*hm), tzinfo=ET).astimezone(CT)


def wasde_events() -> list[dict]:
    return [{"when": _et(d, D.WASDE_TIME_ET), "title": "WASDE", "source": "USDA WAOB", "tags": BOTH,
             "note": "World Agricultural Supply and Demand Estimates"} for d in D.WASDE]


def bls_events() -> list[dict]:
    out = []
    for title, rows in (("CPI", D.CPI), ("PPI", D.PPI)):
        full = "Consumer Price Index" if title == "CPI" else "Producer Price Index"
        for ref, d in rows:
            out.append({"when": _et(d, D.BLS_TIME_ET), "title": f"{title}: {full}", "source": "BLS",
                        "tags": frozenset({E}), "note": f"{ref} data"})
    return out


# -- EIA ---------------------------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September",
                                       "October", "November", "December"], 1)}
_DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4})")
_TIME = re.compile(r"(\d{1,2}):(\d{2}) ?([ap])\.?m", re.I)


def _plain(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)))


def _hm(txt: str) -> tuple[int, int] | None:
    m = _TIME.search(txt)
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return h, int(m.group(2))


def parse_eia_exceptions(html_text: str) -> list[tuple[date, tuple[int, int], str]]:
    """The holiday-exception rows of an EIA weekly schedule page: (alternate release date, (hour, minute) ET, holiday). The
    petroleum page also carries the data week's end date first; the alternate release date is the LAST date of a row."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S):
        cells = [_plain(c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        dates = [d for c in cells for d in _DATE.findall(c)]
        times = [t for t in (_hm(c) for c in cells) if t]
        if not dates or not times:
            continue
        mon, day, yr = dates[-1] if len(cells) < 5 else _DATE.findall(cells[1])[-1]
        out.append((date(int(yr), _MONTHS[mon], int(day)), times[0], cells[-1]))
    return out


def eia_weekly(title: str, short: str, note: str, std_weekday: int, std_hm: tuple[int, int],
               exceptions: list[tuple[date, tuple[int, int], str]], start: date, end: date) -> list[dict]:
    """A weekly EIA report from start to end: every `std_weekday` at `std_hm` ET, except that each holiday exception REPLACES the
    standard day nearest to its alternate date (within 4 days). EIA publishes the exceptions only for the year ahead, so the
    caller stops `end` at the end of the last year its table covers: past that, holiday weeks would be guessed."""
    std_days = {start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() == std_weekday}
    moved: list[tuple[date, tuple[int, int]]] = []
    for alt, hm, _holiday in sorted(exceptions):
        near = sorted((abs(k), k) for k in range(-4, 5) if (alt + timedelta(days=k)) in std_days)
        if near:
            std_days.discard(alt + timedelta(days=near[0][1]))
        if start <= alt <= end:
            moved.append((alt, hm))
    days = [(d, std_hm) for d in sorted(std_days)] + moved
    return [{"when": _et(d, hm), "title": title, "short": short, "source": "EIA", "tags": frozenset({E}), "note": note}
            for d, hm in sorted(days)]


def parse_eia_release_dates(html_text: str) -> list[date]:
    """'Release Date: Nov 10, 2026 | Next Release Date: Dec 8, 2026' style headers: every date after those labels."""
    t = _plain(html_text)
    out = []
    for label in ("Release Date", "Next Release Date", "Next Release"):
        for m in re.finditer(label + r":?\s*(?:&nbsp;)?\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, \d{4})", t):
            raw = m.group(1).replace(".", "")
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    out.append(datetime.strptime(raw, fmt).date())
                    break
                except ValueError:
                    pass
    return sorted(set(out))


def eia_events(pages: dict[str, str], today: date) -> list[dict]:
    """EIA's four reports from the text of its pages (keys 'wpsr', 'ngs', 'steo', 'psm'; a missing key is skipped)."""
    out: list[dict] = []
    start = today - timedelta(days=45)
    if pages.get("wpsr"):
        ex = parse_eia_exceptions(pages["wpsr"])
        end = date(max((d.year for d, _, _ in ex), default=today.year), 12, 31)
        out += eia_weekly("EIA: Weekly Petroleum Status Report", "EIA petroleum", "Includes ethanol production and stocks",
                          2, (10, 30), [x for x in ex if x[0] >= start - timedelta(days=7)], start, end)
    if pages.get("ngs"):
        ex = parse_eia_exceptions(pages["ngs"])
        end = date(max((d.year for d, _, _ in ex), default=today.year), 12, 31)
        out += eia_weekly("EIA: Natural Gas Storage Report", "EIA gas storage", "Working gas in underground storage",
                          3, (10, 30), [x for x in ex if x[0] >= start - timedelta(days=7)], start, end)
    for key, title, short, note, hm in (("steo", "EIA: Short-Term Energy Outlook", "EIA STEO", "Monthly energy forecast", (12, 0)),
                                        ("psm", "EIA: Petroleum Supply Monthly", "EIA PSM", "Monthly petroleum supply and disposition", (11, 30))):
        if pages.get(key):
            for d in parse_eia_release_dates(pages[key]):
                if d >= start:
                    out.append({"when": _et(d, hm), "title": title, "short": short, "source": "EIA", "tags": frozenset({E}), "note": note,
                            "notime": True})          # EIA's page gives the day, not the hour
    return out


# -- holidays -----------------------------------------------------------------------------
def _nth_weekday(y: int, m: int, wd: int, n: int) -> date:
    first = date(y, m, 1)
    return first + timedelta(days=(wd - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(y: int, m: int, wd: int) -> date:
    d = date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() != wd:
        d -= timedelta(days=1)
    return d


def _observed(d: date) -> date:
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def easter(y: int) -> date:
    """Western Easter (the anonymous Gregorian computus)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(y, month, day + 1)


def federal_holidays(year: int) -> list[tuple[date, str, date]]:
    """[(observed date, name, actual date)] of the US federal holidays whose ACTUAL date is in `year` (Jan 1 of the next year can be
    observed on Dec 31 of this one)."""
    rows = [
        (date(year, 1, 1), "New Year's Day"), (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
        (_nth_weekday(year, 2, 0, 3), "Presidents Day"), (_last_weekday(year, 5, 0), "Memorial Day"),
        (date(year, 6, 19), "Juneteenth"), (date(year, 7, 4), "Independence Day"), (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (_nth_weekday(year, 10, 0, 2), "Columbus Day"), (date(year, 11, 11), "Veterans Day"),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving Day"), (date(year, 12, 25), "Christmas Day"),
    ]
    return [(_observed(d), n, d) for d, n in rows]


CME_OPEN_FEDERAL = {"Columbus Day", "Veterans Day"}      # US federal holidays on which CME grains and livestock trade as usual


def _noon(d: date) -> datetime:
    return datetime.combine(d, time(12, 0), tzinfo=CT)


def holiday_events(today: date) -> list[dict]:
    """Federal holidays and CME grain / livestock closures and early closes from last month to the end of next year, all-day events tagged
    'holiday'. CME's own holiday hours (report_schedule_data.CME_HOLIDAY_HOURS) are used wherever CME has published them; a closure
    that is not in that table yet falls back to "closed" with a note that the hours are not published."""
    start, end = today - timedelta(days=45), date(today.year + 1, 12, 31)
    cme = {d: (name, kind, text) for d, name, kind, text in D.CME_HOLIDAY_HOURS}
    out: list[dict] = []
    closed_dates: set[date] = set()

    def closed_note(d: date) -> str:
        return cme[d][2] if d in cme else "Grain and livestock futures are CLOSED (CME has not published the hours around this holiday yet)."

    gf = [easter(y) - timedelta(days=2) for y in (today.year - 1, today.year, today.year + 1)]
    for y in range(today.year - 1, today.year + 3):
        for obs, name, actual in federal_holidays(y):
            if not (start <= obs <= end):
                continue
            tag = f" (observed {obs:%a %b} {obs.day})" if obs != actual else ""
            sat_new_year = name == "New Year's Day" and actual.weekday() == 5
            if name in CME_OPEN_FEDERAL:
                cme_text, closed = "CME grain and livestock futures trade normally.", False
            elif sat_new_year:
                cme_text, closed = "CME grain and livestock futures trade normally on the observed Friday (New Year's Day falls on a Saturday).", False
            else:
                cme_text, closed = closed_note(obs), True
            if closed:
                closed_dates.add(obs)
            out.append({"when": _noon(obs), "title": f"{name}{tag}", "short": name, "source": "US federal holiday", "tags": frozenset({H}),
                        "note": "Federal agencies (USDA, BLS, EIA, CFTC) are closed and may move releases. CME: " + cme_text,
                        "notime": True, "closed": closed})
    for d in gf:
        if start <= d <= end:
            out.append({"when": _noon(d), "title": "Good Friday", "short": "Good Friday", "source": "CME", "tags": frozenset({H}),
                        "note": "Not a federal holiday. CME: " + closed_note(d), "notime": True, "closed": True})
            closed_dates.add(d)
    for d, name, kind, text in D.CME_HOLIDAY_HOURS:
        if kind == "early" and start <= d <= end:
            out.append({"when": _noon(d), "title": f"CME early close: {name}", "short": "CME early close", "source": "CME", "tags": frozenset({H}),
                        "note": text, "notime": True, "closed": False})
    return out


# -- weekly staples --------------------------------------------------------------------------
def _holiday_dates(today: date) -> set[date]:
    return {obs for y in range(today.year - 1, today.year + 3) for obs, _n, _a in federal_holidays(y)}


def export_sales_events(today: date) -> list[dict]:
    """FAS Weekly Export Sales, 8:30 AM ET: the dates FAS has published, then (120 days at most) its holiday rule: Thursday, but Friday when a
    federal holiday falls the previous Friday or Monday-Thursday of that week."""
    hol = _holiday_dates(today)
    out = [{"when": _et(d, D.EXPORT_SALES_TIME_ET), "title": "Weekly Export Sales", "short": "Export Sales", "source": "USDA FAS",
            "tags": BOTH, "note": "Sales through the prior Thursday"} for d in D.EXPORT_SALES_OFFICIAL]
    last = max(D.EXPORT_SALES_OFFICIAL)
    d = last + timedelta(days=1)
    while d <= today + timedelta(days=120):
        if d.weekday() == 3:
            week = [d - timedelta(days=6)] + [d - timedelta(days=k) for k in (3, 2, 1, 0)]       # previous Friday, Mon-Thu
            rel = d + timedelta(days=1) if any(w in hol for w in week) else d
            out.append({"when": _et(rel, D.EXPORT_SALES_TIME_ET), "title": "Weekly Export Sales", "short": "Export Sales",
                        "source": "USDA FAS", "tags": BOTH, "note": "Usual schedule: FAS has not published this date yet"})
        d += timedelta(days=1)
    return out


def export_inspections_events(today: date) -> list[dict]:
    """USDA Export Inspections, Mondays 11:00 AM ET (Tuesday after a Monday holiday): the usual schedule, 120 days at most."""
    hol = _holiday_dates(today)
    out, d = [], today - timedelta(days=45)
    while d <= today + timedelta(days=120):
        if d.weekday() == 0:
            rel = d + timedelta(days=1) if d in hol else d
            out.append({"when": _et(rel, D.EXPORT_INSPECTIONS_TIME_ET), "title": "Export Inspections", "short": "Export Inspections",
                        "source": "USDA AMS", "tags": frozenset({G}), "note": "Usual schedule (no calendar is published)"})
        d += timedelta(days=1)
    return out


_COT_MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December)"


def parse_cot_schedule(html_text: str) -> list[dict]:
    """The CFTC Commitments of Traders release dates from its schedule page ('2026 Release Schedule  Month Dates  January 05* 09 16 ...';
    a * marks a date delayed by a federal holiday), 3:30 PM ET."""
    t = _plain(html_text).replace("&nbsp;", " ")
    out = []
    for hm in re.finditer(r"(20\d\d) Release Schedule", t):
        year = int(hm.group(1))
        seg = t[hm.end():]
        stop = re.search(r"\*Delayed|RELATED LINKS|\d{4} Release Schedule", seg)
        seg = seg[:stop.start()] if stop else seg[:2000]
        parts = re.split(_COT_MONTH, seg)
        for i in range(1, len(parts) - 1, 2):
            month = _MONTHS[parts[i]]
            for day, star in re.findall(r"\b(\d{1,2})(\*?)", parts[i + 1]):
                try:
                    d = date(year, month, int(day))
                except ValueError:
                    continue
                out.append({"when": _et(d, D.COT_TIME_ET), "title": "CFTC: Commitments of Traders", "short": "CFTC COT", "source": "CFTC",
                            "tags": BOTH, "note": ("Delayed by a federal holiday. " if star else "") + "Positions as of the prior Tuesday"})
    return out


# -- international ---------------------------------------------------------------------------
STATCAN_URL = "https://www150.statcan.gc.ca/n1/dai-quo/ssi/homepage/schedule-key_indicators-eng.json"
STATCAN_ET = (8, 30)
_STATCAN_CROP = {"Principal field crop areas", "Production of principal field crops", "Stocks of principal field crops",
                 "Model-based principal field crop estimates"}
_STATCAN_LIVESTOCK = re.compile(r"cattle|hog|livestock|poultry|dairy|red meat|milk|egg", re.I)


def parse_statcan(items: list[dict], today: date) -> list[dict]:
    """Statistics Canada release rows ({date, title, description}) -> the agriculture-relevant events from last month on: the crop reports
    (grain + international), any livestock report (livestock + international), Farm income and the Canadian CPI (international only: it is
    not mixed into the US economic list)."""
    out = []
    for r in items or []:
        try:
            d = date.fromisoformat(str(r["date"])[:10])
            title = r["title"].strip()
        except (KeyError, ValueError):
            continue
        if d < today - timedelta(days=45):
            continue
        if title in _STATCAN_CROP:
            tags, short = frozenset({G, I}), "StatCan " + title.split(" ")[0].lower()
        elif _STATCAN_LIVESTOCK.search(title):
            tags, short = frozenset({L, I}), "StatCan " + title.lower()[:18]
        elif title in ("Farm income", "Consumer Price Index"):
            tags, short = frozenset({I}), "StatCan " + ("farm income" if title == "Farm income" else "CPI")
        else:
            continue
        label = "Canada CPI" if title == "Consumer Price Index" else title
        out.append({"when": _et(d, STATCAN_ET), "title": f"StatCan: {label}", "short": short, "source": "Statistics Canada", "tags": tags,
                    "note": (r.get("description") or "").strip()})
    return out


def conab_events(today: date) -> list[dict]:
    """CONAB's grain surveys and crop-monitoring bulletins (typed from its calendar PDF) and its Monday crop-progress release (the PDF's own
    statement: every Monday 19:00 Brasilia time), 120 days ahead at most. The surveys have no time in the PDF, so they show the day only."""
    out = []
    for d, label in D.CONAB_GRAIN_SURVEYS:
        out.append({"when": _noon(d), "title": "CONAB: Grain crop survey", "short": "CONAB survey", "source": "CONAB (Brazil)",
                    "tags": frozenset({G, I}), "note": label, "notime": True})
    for d in D.CONAB_MONITORING:
        out.append({"when": _noon(d), "title": "CONAB: Crop monitoring bulletin", "short": "CONAB monitoring", "source": "CONAB (Brazil)",
                    "tags": frozenset({G, I}), "note": "Monitoramento Agricola (may change with spectral data availability)", "notime": True})
    brt = ZoneInfo("America/Sao_Paulo")
    d = today - timedelta(days=45)
    while d <= today + timedelta(days=120):
        if d.weekday() == D.CONAB_PROGRESS_WEEKDAY:
            when = datetime.combine(d, time(*D.CONAB_PROGRESS_TIME_BRT), tzinfo=brt).astimezone(CT)
            out.append({"when": when, "title": "CONAB: Crop progress", "short": "CONAB progress", "source": "CONAB (Brazil)",
                        "tags": frozenset({G, I}), "note": "Weekly, Mondays 7 PM Brasilia time (CONAB's calendar)"})
        d += timedelta(days=1)
    return out


def sort_events(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: (e["when"], e["title"]))


def for_scope(events: list[dict], scope: str) -> list[dict]:
    """scope: 'grain' | 'livestock' | 'all'. Economic reports and holidays are in every scope."""
    if scope == "all":
        return list(events)
    return [e for e in events if scope in e["tags"] or E in e["tags"] or H in e["tags"]]


def with_any_tag(events: list[dict], tags: set | frozenset) -> list[dict]:
    """Events carrying at least one of `tags`: the Reports Calendar tab's on / off switches. WASDE (grain + livestock)
    stays while either of those is on; CPI / PPI go with 'economic' alone."""
    return [e for e in events if e["tags"] & set(tags)]


def between(events: list[dict], start: date, end: date) -> list[dict]:
    """Events dated start..end inclusive (Central dates)."""
    return [e for e in events if start <= e["when"].date() <= end]


def week_of(today: date) -> tuple[date, date, bool]:
    """(Monday, Sunday, is_next_week): the working week of `today`; on a Saturday or Sunday the week ahead."""
    monday = today - timedelta(days=today.weekday())
    nxt = today.weekday() >= 5
    if nxt:
        monday += timedelta(days=7)
    return monday, monday + timedelta(days=6), nxt


def coverage_end() -> date:
    return min(max(D.WASDE), max(d for _, d in D.CPI), max(d for _, d in D.PPI))


def coverage_warning(today: date) -> str | None:
    """Words for the footnote once the typed dates are about to run out (they are refreshed by hand, see report_schedule_data)."""
    left = (coverage_end() - today).days
    if left < 0:
        return f"The typed WASDE / CPI / PPI dates end {coverage_end():%b %d, %Y}: later ones are missing until they are refreshed."
    if left < 60:
        return f"The typed WASDE / CPI / PPI dates run out on {coverage_end():%b %d, %Y}; they need refreshing."
    return None


# -- fetching (the only network part) -------------------------------------------------------
def fetch_nass_ics(year: int, timeout: int = 12) -> str | None:
    """One year's NASS .ics, or None when NASS has not published that year (404) or cannot be reached."""
    import requests
    url = NASS_ICS_URL.format(year=year)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code == 200 and "BEGIN:VCALENDAR" in r.text:
            return r.text
        if r.status_code == 404:
            return None
    except requests.RequestException:
        pass
    curl = shutil.which("curl")      # nass.usda.gov's firewall has refused Python's TLS handshake before; curl gets through
    if curl:
        try:
            out = subprocess.run([curl, "-s", "-L", "--max-time", str(timeout), "-A", UA, url],
                                 capture_output=True, timeout=timeout + 5)
            txt = out.stdout.decode("utf-8", "replace")
            if "BEGIN:VCALENDAR" in txt:
                return txt
        except (subprocess.SubprocessError, OSError):
            pass
    return None


def fetch_eia_pages(timeout: int = 25) -> dict[str, str]:
    """The text of EIA's schedule pages, by key; a page that cannot be read is simply absent. The four are asked side by side
    (the petroleum one alone can take 8 seconds)."""
    import requests
    from concurrent.futures import ThreadPoolExecutor

    def one(item):
        key, url = item
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            return key, (r.text if r.status_code == 200 and len(r.text) > 2000 else None)
        except requests.RequestException:
            return key, None

    with ThreadPoolExecutor(max_workers=4) as ex:
        got = list(ex.map(one, (("wpsr", EIA_WPSR_URL), ("ngs", EIA_NGS_URL), ("steo", EIA_STEO_URL), ("psm", EIA_PSM_URL))))
    return {k: v for k, v in got if v}


def fetch_statcan(timeout: int = 40) -> list[dict] | None:
    import requests
    try:
        r = requests.get(STATCAN_URL, headers={"User-Agent": UA}, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


CFTC_URL = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm"


def fetch_cftc_page(timeout: int = 25) -> str | None:
    import requests
    try:
        r = requests.get(CFTC_URL, headers={"User-Agent": UA}, timeout=timeout)
        return r.text if r.status_code == 200 and len(r.text) > 2000 else None
    except requests.RequestException:
        return None


def load_all(today: date) -> tuple[list[dict], list[str]]:
    """(every event, notes about what could not be read)."""
    notes: list[str] = []
    events = wasde_events() + bls_events()
    got = 0
    for year in (today.year, today.year + 1):
        txt = fetch_nass_ics(year)
        if txt:
            events += parse_nass_ics(txt)
            got += 1
        elif year == today.year:
            notes.append("USDA NASS's release calendar could not be read just now, so NASS reports are missing.")
    if not got and not notes:
        notes.append("USDA NASS's release calendar could not be read just now, so NASS reports are missing.")
    pages = fetch_eia_pages()
    events += eia_events(pages, today)
    if len(pages) < 4:
        notes.append("Some of EIA's schedule pages could not be read just now, so some EIA reports are missing.")
    cot = fetch_cftc_page()
    if cot:
        events += [e for e in parse_cot_schedule(cot) if e["when"].date() >= today - timedelta(days=45)]
    else:
        notes.append("The CFTC release schedule could not be read just now, so Commitments of Traders dates are missing.")
    sc = fetch_statcan()
    if sc is not None:
        events += parse_statcan(sc, today)
    else:
        notes.append("Statistics Canada's release schedule could not be read just now, so its dates are missing.")
    events += export_sales_events(today) + export_inspections_events(today) + holiday_events(today) + conab_events(today)
    return sort_events(events), notes


# -- drawing: HTML (classes only: Streamlit's markdown rewrites inline styles) ----------------------
CSS = """
<style>
.jsa-rc { background:#ffffff; border:1px solid #d7e2dc; border-top:3px solid #5e7164; border-radius:10px; padding:0.7rem 1rem 0.6rem; margin:0.2rem 0 0.9rem; }
.jsa-rc-head { font-size:0.7rem; text-transform:uppercase; letter-spacing:0.09em; color:#5f7267; font-weight:700; margin-bottom:0.4rem; }
.jsa-rc-head span { color:#8a9a90; font-weight:600; letter-spacing:0.04em; margin-left:0.4rem; }
.jsa-rc-day { display:flex; gap:0.9rem; padding:0.28rem 0; border-top:1px solid #eef2ef; align-items:flex-start; }
.jsa-rc-day:first-of-type { border-top:none; }
.jsa-rc-day.today { background:#f3f8f5; margin:0 -0.5rem; padding-left:0.5rem; padding-right:0.5rem; border-radius:6px; }
.jsa-rc-date { flex:0 0 5.2rem; font-weight:700; color:#32373c; font-size:0.86rem; padding-top:0.12rem; }
.jsa-rc-date small { display:block; font-weight:600; color:#2f7d54; font-size:0.62rem; letter-spacing:0.06em; text-transform:uppercase; }
.jsa-rc-items { display:flex; flex-wrap:wrap; gap:0.35rem 0.5rem; }
.jsa-rc-chip { border:1px solid #d7e2dc; background:#fafcfb; border-radius:6px; padding:0.12rem 0.5rem; font-size:0.82rem; color:#32373c; line-height:1.35; }
.jsa-rc-chip b { font-weight:600; }
.jsa-rc-chip i { font-style:normal; color:#8a9a90; margin-right:0.35rem; font-size:0.74rem; font-variant-numeric:tabular-nums; }
.jsa-rc-chip.eco { border-color:#e3c27b; background:#fff8e8; }
.jsa-rc-chip.eco em { font-style:normal; font-size:0.6rem; font-weight:700; letter-spacing:0.07em; color:#9a6a12; margin-left:0.4rem; }
.jsa-rc-chip.hol { border-color:#c9d3e0; background:#f1f5fa; }
.jsa-rc-chip.closed { border-color:#e6b5b5; background:#fdf0f0; }
.jsa-rc-chip.hol em, .jsa-rc-chip.closed em { font-style:normal; font-size:0.6rem; font-weight:700; letter-spacing:0.07em; color:#8a4b4b; margin-left:0.4rem; }
.jsa-rc-chip.intl { border-color:#b9d3e3; background:#eef6fb; }
.jsa-rc-chip.intl em { font-style:normal; font-size:0.6rem; font-weight:700; letter-spacing:0.07em; color:#2d6a8f; margin-left:0.4rem; }
.jsa-rc-none { color:#8a9a90; font-size:0.84rem; padding:0.2rem 0; }
.jsa-rc-foot { font-size:0.7rem; color:#8a9a90; margin-top:0.35rem; }
.jsa-rc-warn { color:#9a6a12; }
.jsa-rc-month { width:100%; border-collapse:collapse; table-layout:fixed; font-size:0.74rem; }
.jsa-rc-month th { text-align:left; padding:0.25rem 0.4rem; color:#5f7267; font-size:0.66rem; text-transform:uppercase; letter-spacing:0.08em; border-bottom:2px solid #d7e2dc; }
.jsa-rc-month td { vertical-align:top; border:1px solid #e3ebe6; padding:0.2rem 0.3rem; height:5.4rem; background:#fff; }
.jsa-rc-month td.out { background:#f6f8f7; }
.jsa-rc-month td.today { background:#f3f8f5; box-shadow:inset 0 0 0 2px #5e7164; }
.jsa-rc-month .n { font-weight:700; color:#32373c; font-size:0.78rem; }
.jsa-rc-month .e { display:block; margin-top:2px; padding:1px 4px; border-radius:4px; background:#eef3f0; color:#32373c; line-height:1.25; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.jsa-rc-month .e.eco { background:#fff1cf; }
.jsa-rc-month .e.hol { background:#e6edf6; }
.jsa-rc-month .e.intl { background:#dcecf6; }
.jsa-rc-month .e.closed { background:#fbe3e3; }
.jsa-rc-month .more { color:#8a9a90; margin-top:2px; display:block; }
@media (max-width: 700px) { .jsa-rc-day { flex-direction:column; gap:0.15rem; } .jsa-rc-month td { height:4rem; } }
</style>
"""


def _clock(when: datetime) -> str:
    h = when.hour % 12 or 12
    return f"{h}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}"


def chip_html(e: dict) -> str:
    eco, hol, intl = E in e["tags"], H in e["tags"], I in e["tags"]
    tip = html.escape((e["note"] + " · " if e["note"] else "") + e["source"])
    when = "" if e.get("notime") else f'<i>{_clock(e["when"])}</i>'
    kind = " eco" if eco else (" closed" if e.get("closed") else " hol") if hol else " intl" if intl else ""
    return (f'<span class="jsa-rc-chip{kind}" title="{tip}">{when}<b>{html.escape(e["title"])}</b>'
            + ('<em>ECON</em>' if eco else '<em>HOLIDAY</em>' if hol else '<em>INTL</em>' if intl else "") + "</span>")


def week_html(events: list[dict], today: date, label: str, warn: str | None = None) -> str:
    """The "This Week's Reports" card. `events` is already scoped."""
    start, end, nxt = week_of(today)
    wk = between(events, start, end)
    head = f"{'Next week' if nxt else 'This week'}'s reports<span>{start:%b} {start.day} – {end.day if end.month == start.month else end.strftime('%b ') + str(end.day)}</span>"
    head = f'<div class="jsa-rc-head">{html.escape(label)} · {head}</div>'
    if not wk:
        body = '<div class="jsa-rc-none">No reports are scheduled this week.</div>'
    else:
        rows = []
        for i in range(7):
            d = start + timedelta(days=i)
            day = [e for e in wk if e["when"].date() == d]
            if not day:
                continue
            is_today = d == today
            rows.append(f'<div class="jsa-rc-day{" today" if is_today else ""}"><div class="jsa-rc-date">{d:%a} {d:%b} {d.day}'
                        + ("<small>Today</small>" if is_today else "") + "</div>"
                        f'<div class="jsa-rc-items">{"".join(chip_html(e) for e in day)}</div></div>')
        body = "".join(rows)
    foot = ('<div class="jsa-rc-foot">Times are Central. USDA dates from NASS and the WASDE schedule; economic reports from BLS (CPI, PPI) and EIA. '
            "Dates can change: check the agency before you rely on one."
            + (f' <span class="jsa-rc-warn">{html.escape(warn)}</span>' if warn else "") + "</div>")
    return f'<div class="jsa-rc">{head}{body}{foot}</div>'


def month_html(events: list[dict], year: int, month: int, today: date, max_per_day: int = 4) -> str:
    cal = calendar.Calendar(firstweekday=6)
    rows = ["<tr>" + "".join(f"<th>{n}</th>" for n in ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")) + "</tr>"]
    for wk in cal.monthdatescalendar(year, month):
        cells = []
        for d in wk:
            day = [e for e in events if e["when"].date() == d]
            cls = ("out " if d.month != month else "") + ("today" if d == today else "")
            items = "".join(f'<span class="e{" eco" if E in e["tags"] else (" closed" if e.get("closed") else " hol") if H in e["tags"] else " intl" if I in e["tags"] else ""}" title="{html.escape(("" if e.get("notime") else _clock(e["when"]) + " ") + e["title"])}">'
                            f'{html.escape(e.get("short") or e["title"].split(":")[0])}</span>' for e in day[:max_per_day])
            more = f'<span class="more">+{len(day) - max_per_day} more</span>' if len(day) > max_per_day else ""
            cells.append(f'<td class="{cls.strip()}"><span class="n">{d.day}</span>{items}{more}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="jsa-rc-month">{"".join(rows)}</table>'


def list_rows(events: list[dict]) -> list[dict]:
    """Rows for a table: Date, Time (CT), Report, Source, Notes."""
    return [{"Date": e["when"].strftime("%a %b ") + str(e["when"].day), "Time (CT)": "all day" if e.get("notime") else _clock(e["when"]),
             "Report": e["title"],
             "Type": "Holiday" if H in e["tags"] else "Economic" if E in e["tags"] else
             "International" + (" grain" if G in e["tags"] else " livestock" if L in e["tags"] else "") if I in e["tags"] else
             ("Grain + livestock" if e["tags"] >= BOTH else ("Grain" if G in e["tags"] else "Livestock")),
             "Source": e["source"], "Notes": e["note"]} for e in events]


# -- Streamlit glue ----------------------------------------------------------------------
_FAIL_BACKOFF_SECONDS = 300
_fail_until = 0.0


def _events(today: date):
    """(events, notes). A good read is cached for 6 hours for every visitor. A read where NASS could not be reached is NOT cached:
    the typed dates are returned at once and NASS is not asked again for 5 minutes, so a hiccup neither sticks for hours nor makes
    every page load wait on a dead connection."""
    import time as _time
    import streamlit as st
    global _fail_until

    @st.cache_data(ttl=6 * 3600, show_spinner=False)
    def _good(day_iso: str):
        events, notes = load_all(date.fromisoformat(day_iso))
        if notes:
            raise RuntimeError("; ".join(notes))          # an exception is never cached
        return events

    note = "Some live release calendars (NASS, EIA, CFTC, Statistics Canada) could not be read just now, so those reports are missing."
    def offline():
        return sort_events(wasde_events() + bls_events() + export_sales_events(today) + export_inspections_events(today)
                           + holiday_events(today) + conab_events(today))

    if _time.time() < _fail_until:
        return offline(), [note]
    try:
        return _good(today.isoformat()), []
    except Exception:  # noqa: BLE001
        _fail_until = _time.time() + _FAIL_BACKOFF_SECONDS
        return offline(), [note]


def today_ct() -> date:
    return datetime.now(CT).date()


def render_week(scope: str, label: str) -> None:
    """The "This Week's Reports" card for the Grain or Livestock home page. Never raises: a failure draws nothing."""
    import streamlit as st
    try:
        today = today_ct()
        events, notes = _events(today)
        warn = " ".join(notes) or coverage_warning(today)
        st.markdown(CSS + week_html(for_scope(events, scope), today, label, warn), unsafe_allow_html=True)
    except Exception as exc:  # noqa: BLE001 -- the tiles below matter more than this card
        import logging
        logging.getLogger("report_calendar").warning("week panel failed: %s", exc)


def render_tab() -> None:
    """The Reports Calendar tab: on / off switches for grain, livestock and economic reports, a month grid and the month's list."""
    import pandas as pd
    import streamlit as st
    try:
        today = today_ct()
        events, notes = _events(today)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"The report calendar could not be loaded just now ({str(exc)[:120]}).")
        return
    st.markdown(CSS, unsafe_allow_html=True)
    c1, c2 = st.columns([3, 2])
    with c1:
        shown = st.pills("Show", ["Grain", "Livestock", "Economic", "Holidays", "International"], selection_mode="multi",
                         default=["Grain", "Livestock", "Economic", "Holidays", "International"], key="rc_types", label_visibility="collapsed",
                         help="Turn grain, livestock, economic (CPI, PPI, EIA), holidays (federal and CME) and international (Canada, Brazil) entries on or off.")
    scoped = with_any_tag(events, {{"Grain": G, "Livestock": L, "Economic": E, "Holidays": H, "International": I}[x] for x in (shown or [])})
    months = []
    y, m = today.year, today.month
    for _ in range(18):                       # last month through a year and a bit ahead
        months.append((y, m))
        m += 1
        y, m = (y + 1, 1) if m == 13 else (y, m)
    start = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    months = [start] + months
    with c2:
        picked = st.selectbox("Month", months, index=1, format_func=lambda ym: f"{calendar.month_name[ym[1]]} {ym[0]}",
                              key="rc_month", label_visibility="collapsed")
    st.markdown(month_html(scoped, picked[0], picked[1], today), unsafe_allow_html=True)
    month_events = [e for e in scoped if (e["when"].year, e["when"].month) == picked]
    st.markdown(f"##### {calendar.month_name[picked[1]]} {picked[0]}: {len(month_events)} reports")
    if not shown:
        st.caption("Switch at least one of Grain, Livestock, Economic, Holidays or International on to see entries.")
    elif month_events:
        st.dataframe(pd.DataFrame(list_rows(month_events)), hide_index=True, width="stretch")
    else:
        st.caption("No reports on the calendar for this month yet.")
    warn = " ".join(notes) or coverage_warning(today)
    st.caption("CME Globex normal day-session hours: grains " + D.CME_NORMAL_HOURS["grains"] + ", livestock " + D.CME_NORMAL_HOURS["livestock"] + ". "
               "Holiday closures and early closes are CME's published holiday hours (grains and livestock groups); CME can change them and finalizes "
               "them about two weeks ahead, so check cmegroup.com/trading-hours.html before a holiday.")
    st.caption("International: Statistics Canada (crop reports, farm income, CPI) and CONAB, Brazil (grain surveys, crop progress). "
               "Argentina is not shown: the Buenos Aires Grain Exchange and Rosario publish no release calendar we can read. The Canadian and "
               "Brazilian crop reports also appear on the Grain card.")
    st.caption("Times are Central. USDA NASS dates are read live from NASS's release calendar; WASDE dates are USDA's published schedule; "
               "CPI and PPI come from the Bureau of Labor Statistics and the energy reports from EIA (its weekly dates run to the end of the year it has published holiday changes for). Dates can change: check the agency before you rely on one."
               + (f" ⚠ {warn}" if warn else ""))
