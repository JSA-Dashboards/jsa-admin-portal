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

G, L, E = "grain", "livestock", "economic"
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


def sort_events(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: (e["when"], e["title"]))


def for_scope(events: list[dict], scope: str) -> list[dict]:
    """scope: 'grain' | 'livestock' | 'all'. Economic reports are in every scope."""
    if scope == "all":
        return list(events)
    return [e for e in events if scope in e["tags"] or E in e["tags"]]


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
.jsa-rc-month .more { color:#8a9a90; margin-top:2px; display:block; }
@media (max-width: 700px) { .jsa-rc-day { flex-direction:column; gap:0.15rem; } .jsa-rc-month td { height:4rem; } }
</style>
"""


def _clock(when: datetime) -> str:
    h = when.hour % 12 or 12
    return f"{h}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}"


def chip_html(e: dict) -> str:
    eco = E in e["tags"]
    tip = html.escape((e["note"] + " · " if e["note"] else "") + e["source"])
    return (f'<span class="jsa-rc-chip{" eco" if eco else ""}" title="{tip}"><i>{_clock(e["when"])}</i><b>{html.escape(e["title"])}</b>'
            + (f'<em>ECON</em>' if eco else "") + "</span>")


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
    foot = ('<div class="jsa-rc-foot">Times are Central. USDA dates from NASS and the WASDE schedule; economic reports (CPI, PPI) from BLS. '
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
            items = "".join(f'<span class="e{" eco" if E in e["tags"] else ""}" title="{html.escape(_clock(e["when"]) + " " + e["title"])}">'
                            f'{html.escape(e["title"].split(":")[0])}</span>' for e in day[:max_per_day])
            more = f'<span class="more">+{len(day) - max_per_day} more</span>' if len(day) > max_per_day else ""
            cells.append(f'<td class="{cls.strip()}"><span class="n">{d.day}</span>{items}{more}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="jsa-rc-month">{"".join(rows)}</table>'


def list_rows(events: list[dict]) -> list[dict]:
    """Rows for a table: Date, Time (CT), Report, Source, Notes."""
    return [{"Date": e["when"].strftime("%a %b ") + str(e["when"].day), "Time (CT)": _clock(e["when"]), "Report": e["title"],
             "Type": "Economic" if E in e["tags"] else ("Grain + livestock" if e["tags"] >= BOTH else
                                                         ("Grain" if G in e["tags"] else "Livestock")),
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

    note = "USDA NASS's release calendar could not be read just now, so NASS reports are missing."
    if _time.time() < _fail_until:
        return sort_events(wasde_events() + bls_events()), [note]
    try:
        return _good(today.isoformat()), []
    except Exception:  # noqa: BLE001
        _fail_until = _time.time() + _FAIL_BACKOFF_SECONDS
        return sort_events(wasde_events() + bls_events()), [note]


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
        shown = st.pills("Show", ["Grain", "Livestock", "Economic"], selection_mode="multi",
                         default=["Grain", "Livestock", "Economic"], key="rc_types", label_visibility="collapsed",
                         help="Turn grain, livestock and economic (CPI, PPI) reports on or off.")
    scoped = with_any_tag(events, {{"Grain": G, "Livestock": L, "Economic": E}[x] for x in (shown or [])})
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
        st.caption("Switch at least one of Grain, Livestock or Economic on to see reports.")
    elif month_events:
        st.dataframe(pd.DataFrame(list_rows(month_events)), hide_index=True, width="stretch")
    else:
        st.caption("No reports on the calendar for this month yet.")
    warn = " ".join(notes) or coverage_warning(today)
    st.caption("Times are Central. USDA NASS dates are read live from NASS's release calendar; WASDE dates are USDA's published schedule; "
               "CPI and PPI come from the Bureau of Labor Statistics. Dates can change: check the agency before you rely on one."
               + (f" ⚠ {warn}" if warn else ""))
