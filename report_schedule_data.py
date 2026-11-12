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
