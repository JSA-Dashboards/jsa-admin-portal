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


# -- EIA, CFTC, weekly staples and holidays ------------------------------------------------
from datetime import timedelta  # noqa: E402

NASS_2026_HOLIDAYS = {date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3),
                      date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 11), date(2026, 11, 26), date(2026, 12, 25)}


def test_federal_holidays_match_nass_s_own_2026_holiday_rows_and_observe_weekends():
    assert {o for o, _n, _a in rc.federal_holidays(2026)} == NASS_2026_HOLIDAYS            # read from NASS's .ics on 2026-11-12
    h27 = {n: o for o, n, _a in rc.federal_holidays(2027)}
    assert h27["Juneteenth"] == date(2027, 6, 18) and h27["Independence Day"] == date(2027, 7, 5)      # Saturday -> Friday, Sunday -> Monday
    assert h27["Christmas Day"] == date(2027, 12, 24) and h27["Thanksgiving Day"] == date(2027, 11, 25)
    assert any(o == date(2027, 12, 31) for o, n, a in rc.federal_holidays(2028) if n == "New Year's Day")    # Jan 1 2028 is a Saturday


def test_good_friday_and_the_cme_closures():
    assert rc.easter(2026) - timedelta(days=2) == date(2026, 4, 3) and rc.easter(2027) - timedelta(days=2) == date(2027, 3, 26)
    ev = {e["when"].date(): e for e in rc.holiday_events(date(2026, 11, 12))}
    assert ev[date(2026, 11, 26)]["closed"] and ev[date(2026, 12, 25)]["closed"] and ev[date(2027, 3, 26)]["closed"]
    assert not ev[date(2026, 11, 11)]["closed"] and "trade normally" in ev[date(2026, 11, 11)]["note"]      # Veterans Day: CME trades
    assert ev[date(2026, 11, 27)]["title"].startswith("CME early close") and "12:05 PM CT" in ev[date(2026, 11, 27)]["note"]
    assert all(rc.H in e["tags"] and e.get("notime") for e in ev.values())


def test_holidays_are_in_every_scope_and_have_their_own_switch():
    ev = rc.holiday_events(date(2026, 11, 12)) + rc.wasde_events()
    assert any(rc.H in e["tags"] for e in rc.for_scope(ev, "grain")) and any(rc.H in e["tags"] for e in rc.for_scope(ev, "livestock"))
    assert {e["title"] for e in rc.with_any_tag(ev, {"holiday"})} == {e["title"] for e in ev if rc.H in e["tags"]}


def test_cot_schedule_is_read_from_the_cftc_page_and_marks_holiday_delays():
    page = ("<html><body><p>2026 Release Schedule</p><table><tr><td>Month</td><td>Dates</td></tr>"
            "<tr><td>January</td><td>05* 09 16 23 30</td></tr><tr><td>June</td><td>&nbsp;</td><td>05 12 22* 26</td></tr>"
            "<tr><td>November</td><td>06 16* 20 30*</td></tr></table><p>*Delayed release date due to a federal holiday. RELATED LINKS</p></body></html>")
    ev = rc.parse_cot_schedule(page)
    days = {e["when"].date(): e for e in ev}
    assert set(days) >= {date(2026, 1, 5), date(2026, 1, 9), date(2026, 6, 22), date(2026, 11, 16), date(2026, 11, 30), date(2026, 11, 6)}
    assert "Delayed" in days[date(2026, 11, 16)]["note"] and "Delayed" not in days[date(2026, 11, 20 - 14)]["note"]
    assert days[date(2026, 1, 9)]["when"].strftime("%H:%M") == "14:30" and days[date(2026, 1, 9)]["tags"] == {"grain", "livestock"}   # 3:30 PM ET


def test_export_sales_uses_the_official_dates_then_fas_holiday_rule():
    ev = rc.export_sales_events(date(2026, 12, 20))
    days = [e["when"].date() for e in ev]
    assert date(2026, 11, 13) in days and date(2026, 11, 27) in days and date(2026, 11, 12) not in days      # Veterans Day, Thanksgiving: Friday
    assert date(2027, 1, 8) in days and date(2027, 1, 7) not in days          # Fri Jan 1 holiday the previous Friday: the Friday after
    assert date(2027, 1, 22) in days and date(2027, 1, 21) not in days        # MLK Monday
    assert date(2027, 1, 14) in days                                           # an ordinary week stays on Thursday
    assert all(e["when"].strftime("%H:%M") == "07:30" for e in ev)             # 8:30 AM ET
    assert "Usual schedule" in next(e for e in ev if e["when"].date() == date(2027, 1, 14))["note"]
    assert max(days) <= date(2026, 12, 20) + timedelta(days=121)


def test_export_inspections_are_monday_morning_and_tuesday_after_a_monday_holiday():
    days = {e["when"].date() for e in rc.export_inspections_events(date(2027, 1, 10))}
    assert date(2027, 1, 11) in days and date(2027, 1, 19) in days and date(2027, 1, 18) not in days       # MLK Monday -> Tuesday
    ev = rc.export_inspections_events(date(2027, 1, 10))
    assert all(e["when"].strftime("%H:%M") == "10:00" and e["tags"] == {"grain"} for e in ev)


def test_eia_weekly_dates_replace_the_holiday_week_and_stop_at_the_year_the_table_covers():
    ex = [(date(2026, 11, 12), (12, 0), "Veterans Day")]                       # WPSR: Wed Nov 11 moves to Thu Nov 12, noon ET
    ev = rc.eia_weekly("W", "w", "", 2, (10, 30), ex, date(2026, 11, 2), date(2026, 11, 30))
    days = [(e["when"].date(), e["when"].strftime("%H:%M")) for e in ev]
    assert days == [(date(2026, 11, 4), "09:30"), (date(2026, 11, 12), "11:00"), (date(2026, 11, 18), "09:30"), (date(2026, 11, 25), "09:30")]
    table = ("<table><tr><th>Data for the week ending</th><th>Alternate release date</th><th>Release day</th><th>Release time</th><th>Holiday</th></tr>"
             "<tr><td>November 6, 2026</td><td>November 12, 2026</td><td>Thursday</td><td>12:00 p.m.</td><td>Veterans Day</td></tr></table>")
    assert rc.parse_eia_exceptions(table) == [(date(2026, 11, 12), (12, 0), "Veterans Day")]
    gas = ("<table><tr><td>November 13, 2026</td><td>Friday</td><td>10:30 a.m.</td><td>Veterans Day</td></tr>"
           "<tr><td>January 8, 2025 - (Updated)</td><td>Wednesday</td><td>12:00 p.m.</td><td>Mourning</td></tr></table>")
    assert [d for d, _h, _n in rc.parse_eia_exceptions(gas)] == [date(2026, 11, 13), date(2025, 1, 8)]


def test_steo_and_psm_release_dates_come_from_their_page_headers():
    page = "<p><strong>Release Date:</strong> November 10, 2026 | <strong>Next Release Date:</strong> December 8, 2026 </p>"
    assert rc.parse_eia_release_dates(page) == [date(2026, 11, 10), date(2026, 12, 8)]
    ev = rc.eia_events({"steo": page}, date(2026, 11, 12))
    assert {e["when"].date() for e in ev} == {date(2026, 11, 10), date(2026, 12, 8)} and all(e["notime"] for e in ev)
