from datetime import date, datetime

import pytest

import report_calendar as rc
import report_schedule_data as D

ICS = r"""BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20261120T200000Z
SUMMARY:Cattle on Feed
END:VEVENT
BEGIN:VEVENT
DTSTART:20261110T170000Z
SUMMARY:Crop Production
END:VEVENT
BEGIN:VEVENT
DTSTART:20261111T050000Z
SUMMARY:HOLIDAY
END:VEVENT
BEGIN:VEVENT
DTSTART:20261113T190000Z
SUMMARY:Honey
END:VEVENT
BEGIN:VEVENT
DTSTART:20260501T190000Z
SUMMARY:County Estimates  Corn, Soybeans, Sorghum
END:VEVENT
BEGIN:VEVENT
DTSTART:20261130T190000Z
SUMMARY:Agricultural Prices
END:VEVENT
BEGIN:VEVENT
DTSTART:20260406T200000Z
SUMMARY:Crop Progress
END:VEVENT
END:VCALENDAR
"""


def by_title(events):
    return {e["title"]: e for e in events}


def test_only_grain_and_livestock_reports_are_kept_and_times_are_central():
    ev = by_title(rc.parse_nass_ics(ICS))
    assert set(ev) == {"Cattle on Feed", "Crop Production", "County Estimates: Corn, Soybeans, Sorghum", "Agricultural Prices", "Crop Progress"}
    assert ev["Cattle on Feed"]["when"].strftime("%Y-%m-%d %H:%M") == "2026-11-20 14:00"      # 20:00Z = 2 PM CST
    assert ev["Crop Production"]["when"].strftime("%H:%M") == "11:00"                         # 12:00 ET
    assert ev["Crop Progress"]["when"].strftime("%H:%M") == "15:00"                           # April: 4 PM EDT = 3 PM CDT
    assert ev["Cattle on Feed"]["tags"] == {"livestock"} and ev["Crop Production"]["tags"] == {"grain"}
    assert ev["Agricultural Prices"]["tags"] == {"grain", "livestock"}


def test_the_two_nass_lists_do_not_overlap():
    assert not (set(rc.GRAIN_NASS) & set(rc.LIVESTOCK_NASS))
    assert set(rc.NASS_BOTH) <= set(rc.NASS_KEEP)


def test_economic_reports_are_in_every_scope_and_wasde_in_both():
    ev = rc.parse_nass_ics(ICS) + rc.wasde_events() + rc.bls_events()
    grain = {e["title"] for e in rc.for_scope(ev, "grain")}
    live = {e["title"] for e in rc.for_scope(ev, "livestock")}
    assert "Crop Production" in grain and "Cattle on Feed" not in grain
    assert "Cattle on Feed" in live and "Crop Production" not in live
    assert "WASDE" in grain & live and "CPI: Consumer Price Index" in grain & live and "PPI: Producer Price Index" in grain & live
    assert len(rc.for_scope(ev, "all")) == len(ev)


def test_the_typed_dates_are_complete_and_in_central_time():
    for year in (2026, 2027):
        assert sum(d.year == year for d in D.WASDE) == 12 and len({d.month for d in D.WASDE if d.year == year}) == 12
    assert len(D.CPI) == len(D.PPI) == 14
    assert [m for m, _ in D.CPI] == [m for m, _ in D.PPI]                       # same reference months
    assert all(d.weekday() < 5 for _, d in D.CPI + D.PPI) and all(d.weekday() < 5 for d in D.WASDE)
    ev = {e["title"][:3]: e for e in rc.bls_events()}
    cpi = next(e for e in rc.bls_events() if e["title"].startswith("CPI") and e["when"].date() == date(2026, 11, 10))
    assert cpi["when"].strftime("%H:%M") == "07:30" and cpi["note"] == "October 2026 data"      # 08:30 ET
    w = next(e for e in rc.wasde_events() if e["when"].date() == date(2026, 11, 10))
    assert w["when"].strftime("%H:%M") == "11:00"                                               # 12:00 ET


def test_week_runs_monday_to_sunday_and_looks_ahead_on_the_weekend():
    assert rc.week_of(date(2026, 11, 12)) == (date(2026, 11, 9), date(2026, 11, 15), False)
    assert rc.week_of(date(2026, 11, 14)) == (date(2026, 11, 16), date(2026, 11, 22), True)    # Saturday
    assert rc.week_of(date(2026, 11, 15))[2] is True


def test_the_week_card_lists_the_days_and_marks_economic_reports_and_today():
    ev = rc.sort_events(rc.parse_nass_ics(ICS) + rc.wasde_events() + rc.bls_events())
    card = rc.week_html(rc.for_scope(ev, "grain"), date(2026, 11, 10), "Grain")
    assert "This week" in card and "Nov 9" in card
    assert "Crop Production" in card and "WASDE" in card and "CPI: Consumer Price Index" in card and "ECON" in card
    assert "Today" in card and "Cattle on Feed" not in card
    assert "PPI: Producer Price Index" in card                                                  # Fri Nov 13, same week
    empty = rc.week_html([], date(2026, 11, 10), "Livestock")
    assert "No reports are scheduled" in empty


def test_month_grid_has_every_day_and_caps_a_busy_day():
    ev = [{"when": datetime(2026, 11, 10, 9 + i % 6, 0, tzinfo=rc.CT), "title": f"R{i}", "source": "x", "tags": frozenset({"grain"}), "note": ""} for i in range(7)]
    grid = rc.month_html(ev, 2026, 11, date(2026, 11, 12))
    assert grid.count("<td") >= 30 and "+3 more" in grid and 'class="today"' in grid


def test_the_typed_dates_warn_before_they_run_out():
    end = rc.coverage_end()
    assert rc.coverage_warning(end.replace(year=end.year - 1)) is None
    assert "run out" in rc.coverage_warning(date(end.year, end.month, 1))
    assert "end" in rc.coverage_warning(date(end.year + 1, 1, 5))


def test_the_calendar_switches_filter_by_tag():
    ev = rc.parse_nass_ics(ICS) + rc.wasde_events() + rc.bls_events()
    titles = lambda tags: {e["title"] for e in rc.with_any_tag(ev, tags)}        # noqa: E731
    assert titles({"economic"}) == {"CPI: Consumer Price Index", "PPI: Producer Price Index"}
    g = titles({"grain"})
    assert "Crop Production" in g and "WASDE" in g and "Cattle on Feed" not in g and "CPI: Consumer Price Index" not in g
    lv = titles({"livestock"})
    assert "Cattle on Feed" in lv and "WASDE" in lv and "Crop Production" not in lv
    assert titles({"grain", "livestock", "economic"}) == {e["title"] for e in ev}
    assert rc.with_any_tag(ev, set()) == []
