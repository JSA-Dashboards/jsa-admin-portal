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
# The one holiday whose hours CME had published for both groups when this was read: Thanksgiving 2026. Wed Nov 25 normal,
# Thu Nov 26 closed, Fri Nov 27 opens 8:30 AM and closes 12:05 PM CT (grains and livestock alike).
CME_THANKSGIVING_2026_EARLY_CLOSE = (date(2026, 11, 27), "8:30 AM - 12:05 PM CT")
