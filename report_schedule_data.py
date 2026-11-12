"""Release dates that are typed in because the official source cannot be read by a script.

Both were read on 2026-11-12 from the agencies' own pages in a browser (their servers answer a script with 403):

  WASDE  https://www.usda.gov/oce/commodity-markets/wasde  ("2026 / 2027 WASDE Release Dates (12:00pm ET)")
         ESMIS (esmis.nal.usda.gov) lists only reports already published, so it cannot give the next one.
  CPI, PPI  https://www.bls.gov/schedule/news_release/cpi.htm and /ppi.htm  (reference month, release date, 08:30 AM ET)
         BLS lists them from the reference month October 2026 through November 2027 (one release a month).

THEY HAVE TO BE REFRESHED BY HAND: when BLS adds 2028 (late 2027) and USDA publishes its next year of WASDE dates
(usually in the autumn). `report_calendar.coverage_warning` turns the footnote amber once the last date here is
less than 60 days away, so it cannot quietly run out. The NASS calendar is NOT typed: it is read live from NASS's
own .ics file (report_calendar.fetch_nass_ics).

Everything is US Eastern; report_calendar converts to Central for display.
"""
from datetime import date

WASDE_TIME_ET = (12, 0)
BLS_TIME_ET = (8, 30)

WASDE = [
    # 2026
    date(2026, 1, 12), date(2026, 2, 10), date(2026, 3, 10), date(2026, 4, 9), date(2026, 5, 12), date(2026, 6, 11),
    date(2026, 7, 10), date(2026, 8, 12), date(2026, 9, 11), date(2026, 10, 9), date(2026, 11, 10), date(2026, 12, 10),
    # 2027
    date(2027, 1, 12), date(2027, 2, 10), date(2027, 3, 10), date(2027, 4, 9), date(2027, 5, 12), date(2027, 6, 11),
    date(2027, 7, 9), date(2027, 8, 12), date(2027, 9, 10), date(2027, 10, 8), date(2027, 11, 10), date(2027, 12, 10),
]

# (reference month label, release date)
CPI = [
    ("October 2026", date(2026, 11, 10)), ("November 2026", date(2026, 12, 10)), ("December 2026", date(2027, 1, 13)),
    ("January 2027", date(2027, 2, 11)), ("February 2027", date(2027, 3, 10)), ("March 2027", date(2027, 4, 13)),
    ("April 2027", date(2027, 5, 12)), ("May 2027", date(2027, 6, 10)), ("June 2027", date(2027, 7, 14)),
    ("July 2027", date(2027, 8, 11)), ("August 2027", date(2027, 9, 14)), ("September 2027", date(2027, 10, 14)),
    ("October 2027", date(2027, 11, 10)), ("November 2027", date(2027, 12, 10)),
]

PPI = [
    ("October 2026", date(2026, 11, 13)), ("November 2026", date(2026, 12, 15)), ("December 2026", date(2027, 1, 14)),
    ("January 2027", date(2027, 2, 12)), ("February 2027", date(2027, 3, 12)), ("March 2027", date(2027, 4, 14)),
    ("April 2027", date(2027, 5, 13)), ("May 2027", date(2027, 6, 11)), ("June 2027", date(2027, 7, 15)),
    ("July 2027", date(2027, 8, 10)), ("August 2027", date(2027, 9, 10)), ("September 2027", date(2027, 10, 15)),
    ("October 2027", date(2027, 11, 12)), ("November 2027", date(2027, 12, 15)),
]


# USDA FAS "Report Release Calendar" (https://www.fas.usda.gov/data/scheduled-reports; it answers a script with 403), read in a browser on
# 2026-11-12: every Weekly Export Sales release it lists, 8:30 AM ET. Veterans Day (Wed Nov 11) moved the report to Fri Nov 13 and
# Thanksgiving (Thu Nov 26) to Fri Nov 27. FAS lists only the next two months, so beyond the last date here report_calendar follows FAS's own
# holiday rule and marks those dates "usual schedule".
EXPORT_SALES_OFFICIAL = [
    date(2026, 11, 13), date(2026, 11, 19), date(2026, 11, 27), date(2026, 12, 3),
    date(2026, 12, 10), date(2026, 12, 17), date(2026, 12, 24), date(2026, 12, 31),
]
EXPORT_SALES_TIME_ET = (8, 30)
EXPORT_INSPECTIONS_TIME_ET = (11, 0)
COT_TIME_ET = (15, 30)

# CME Globex regular day-session hours (Central) for the two product groups, read from CME's "Holiday and Trading Hours" page
# (https://www.cmegroup.com/trading-hours.html, 403 to a script) on 2026-11-12 from an ordinary Wednesday:
CME_NORMAL_HOURS = {"grains": "8:30 AM - 1:20 PM CT day session", "livestock": "8:30 AM - 1:05 PM CT"}
# CME holiday hours for the GRAINS and LIVESTOCK groups on Globex (Central time), read from CME's "Holiday and Trading Hours" page on
# 2026-11-12 holiday by holiday (the page takes the date in its address, e.g. .../trading-hours.html#tradeDate=2027-01-18, and needs a reload to
# read it; it answers a script with 403). CME says holiday hours are finalized about two weeks ahead and subject to change.
# (date, name, kind, what happens).  kind: "closed" = no trading that trade date; "early" = trades but closes early.
_EVENING = "Grains: no day session; the evening session opens 7:00 PM CT for the next trade date. Livestock: closed, reopens the next day 8:30 AM CT."
CME_HOLIDAY_HOURS = [
    (date(2026, 11, 26), "Thanksgiving Day", "closed", "Grain and livestock futures are closed. (Wed Nov 25 trades normal hours.)"),
    (date(2026, 11, 27), "Day after Thanksgiving", "early", "Grains and livestock trade 8:30 AM - 12:05 PM CT, then close."),
    (date(2026, 12, 24), "Christmas Eve", "early", "Grains and livestock trade 8:30 AM - 12:05 PM CT, then close (no afternoon session)."),
    (date(2026, 12, 25), "Christmas Day", "closed", "Grain and livestock futures are closed."),
    (date(2027, 1, 1), "New Year's Day", "closed", "Grain and livestock futures are closed. (Thu Dec 31 trades normal hours.)"),
    (date(2027, 1, 18), "Martin Luther King Jr. Day", "closed", _EVENING),
    (date(2027, 2, 15), "Presidents Day", "closed", _EVENING),
    (date(2027, 3, 26), "Good Friday", "closed", "Grain and livestock futures are closed. (Thu Mar 25 trades normal hours.)"),
    (date(2027, 5, 31), "Memorial Day", "closed", _EVENING),
    (date(2027, 6, 18), "Juneteenth (observed)", "closed", "Grain and livestock futures are closed. (Thu Jun 17 trades normal hours.)"),
    (date(2027, 7, 5), "Independence Day (observed)", "closed",
     "Grains: closed with NO evening session, so trading resumes Tue Jul 6 at 8:30 AM CT. Livestock: closed, reopens Tue 8:30 AM CT."),
    (date(2027, 9, 6), "Labor Day", "closed", _EVENING),
    (date(2027, 11, 25), "Thanksgiving Day", "closed", "Grain and livestock futures are closed. (Wed Nov 24 trades normal hours.)"),
    (date(2027, 11, 26), "Day after Thanksgiving", "early", "Grains and livestock trade 8:30 AM - 12:05 PM CT, then close."),
    (date(2027, 12, 24), "Christmas Day (observed)", "closed", "Grain and livestock futures are closed. (Thu Dec 23 trades normal hours.)"),
]
# New Year's Day 2028 falls on a Saturday: CME grains and livestock trade a normal day on Fri Dec 31 2027 and the grain evening session reopens
# Sunday 7:00 PM CT, so there is no closure to show.


# CONAB (Brazil), "Acompanhamento da Safra Brasileira: calendario de divulgacao", the agency's own 1-page PDF
# https://www.gov.br/conab/pt-br/assuntos/imagens/calendario-de-safras-e-prohort-2026.pdf (read 2026-11-12). It lists the dates of the whole
# 2025/26 and 2026/27 grain surveys, the monthly crop monitoring ("Monitoramento Agricola", which "may change with the availability of spectral
# data"), and says CONAB publishes crop progress every Monday at 19:00 (Brasilia time). It carries no time for the surveys themselves.
# CONAB issues a new calendar each year: refresh this when the 2027 one appears.
CONAB_GRAIN_SURVEYS = [
    (date(2026, 10, 15), "1st survey, 2026/27 crop"), (date(2026, 11, 13), "2nd survey, 2026/27 crop"),
    (date(2026, 12, 15), "3rd survey, 2026/27 crop"), (date(2027, 1, 14), "4th survey, 2026/27 crop"),
]
CONAB_MONITORING = [date(2026, 11, 26), date(2026, 12, 17)]
CONAB_PROGRESS_WEEKDAY = 0                 # Monday
CONAB_PROGRESS_TIME_BRT = (19, 0)
CONAB_LAST_DATE = date(2027, 1, 14)        # the last date the calendar above reaches (for the "needs refreshing" warning)


# CHINA public holidays, from the State Council General Office's notices ("Guo Ban Fa Ming Dian": 2026 on 2025-11-04, 2027 on 2026-11-05), read from
# the full texts Xinhua carries (news.cn/politics/20251104/... and /20261105/...) on 2026-11-12. (name, first day, last day). The make-up working
# days (a weekend day worked in exchange for the holiday) follow. A 2028 notice normally appears in November 2027: refresh this then.
CHINA_HOLIDAYS = [
    ("New Year's Day", date(2026, 1, 1), date(2026, 1, 3)),
    ("Spring Festival", date(2026, 2, 15), date(2026, 2, 23)),
    ("Qingming Festival", date(2026, 4, 4), date(2026, 4, 6)),
    ("Labour Day", date(2026, 5, 1), date(2026, 5, 5)),
    ("Dragon Boat Festival", date(2026, 6, 19), date(2026, 6, 21)),
    ("Mid-Autumn Festival", date(2026, 9, 25), date(2026, 9, 27)),
    ("National Day", date(2026, 10, 1), date(2026, 10, 7)),
    ("New Year's Day", date(2027, 1, 1), date(2027, 1, 3)),
    ("Spring Festival", date(2027, 2, 5), date(2027, 2, 13)),
    ("Qingming Festival", date(2027, 4, 3), date(2027, 4, 5)),
    ("Labour Day", date(2027, 5, 1), date(2027, 5, 5)),
    ("Dragon Boat Festival", date(2027, 6, 9), date(2027, 6, 9)),
    ("Mid-Autumn Festival", date(2027, 9, 15), date(2027, 9, 15)),
    ("National Day", date(2027, 10, 1), date(2027, 10, 7)),
]
CHINA_MAKEUP_WORKDAYS = [      # (date, the holiday it makes up for)
    (date(2026, 1, 4), "New Year's Day"), (date(2026, 2, 14), "Spring Festival"), (date(2026, 2, 28), "Spring Festival"),
    (date(2026, 5, 9), "Labour Day"), (date(2026, 9, 20), "National Day"), (date(2026, 10, 10), "National Day"),
    (date(2027, 1, 31), "Spring Festival"), (date(2027, 2, 14), "Spring Festival"), (date(2027, 5, 8), "Labour Day"),
    (date(2027, 9, 26), "National Day"), (date(2027, 10, 9), "National Day"),
]
