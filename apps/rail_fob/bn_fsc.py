"""
BN's mileage-based fuel surcharge ($/car-mile) worked out from US on-highway diesel (Kolten, 2026-10-28:
"set the FSC to auto calculate").

    FSC for month M = 1 cent per mile for every 5 cents the monthly average of EIA's weekly US on-highway
                      diesel price, TWO MONTHS EARLIER, sits above a $3.25 strike (each started step counts).

Not taken from BNSF's rule text (Item 3377-Series, Rules Book 6100 — the grain price lists cite its $3.25
strike price but the rule itself isn't public). Worked out from the surcharges Kolten has actually had, and it
reproduces every one exactly: Aug .36 (Jun diesel 5.024), Sep .35 (Jul 4.955), Oct .45 (Aug 5.462),
Nov .61 (Sep 6.291) — a one-month lag does not (Oct would be .61). tests/test_bn_fsc.py keeps those four.
Check each new month BN publishes against it; if one misses, the parameters below are what to revisit.

A month whose source month is complete is "published" (BN's number is knowable); one whose source month is
still open uses the average so far; one further out holds the latest weekly price flat — the simple stand-in
for a diesel forecast. Months Kolten types an override for always win (bn_inputs.py).
"""
import math
import os
from datetime import date, timedelta

STRIKE = 3.25      # $/gal, the strike price BNSF's grain price lists cite
STEP = 0.05        # $/gal of diesel per step
PER_STEP = 0.01    # $/mile per step
LAG = 2            # months between the diesel month and the surcharge month
EIA_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"   # weekly retail: product EPD2D (No 2 diesel), NUS, process PTE

_MONTH = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fsc_from_diesel(price):
    """$/mile for a monthly average diesel price; 0 at or under the strike."""
    if price <= STRIKE:
        return 0.0
    return round(math.ceil(round((price - STRIKE) / STEP, 6)) * PER_STEP, 4)


def key():
    return os.environ.get("EIA_API_KEY", "").strip()


def available():
    return bool(key())


def fetch_weekly(start):
    """[(ISO Monday, $/gal)] from `start` (a date), oldest first. Raises if EIA can't be reached."""
    import requests
    r = requests.get(EIA_URL, timeout=20, params={
        "api_key": key(), "frequency": "weekly", "data[0]": "value", "facets[product][]": "EPD2D",
        "facets[duoarea][]": "NUS", "start": start.isoformat(), "sort[0][column]": "period",
        "sort[0][direction]": "asc", "length": "500"})
    r.raise_for_status()
    rows = r.json()["response"]["data"]
    return [(x["period"], float(x["value"])) for x in rows if x.get("process") in (None, "PTE") and x.get("value") is not None]


def crop_year_anchor(today):
    """The year of the grid's Oct (the Oct..Sep grid starts with the coming or current October)."""
    return today.year if today.month >= 9 else today.year - 1


def grid_months(today):
    """[(key, year, month)] for the Oct..Sep grid, in order."""
    a = crop_year_anchor(today)
    return [(_MONTH[m].lower(), a if m >= 10 else a + 1, m) for m in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)]


def _minus(year, month, n):
    i = year * 12 + (month - 1) - n
    return i // 12, i % 12 + 1


def auto_table(weekly, today, fn=None):
    """{month key: {fsc, kind, basis, year, month}} for the grid. `fn` maps a diesel price to $/mile (BN's formula
    unless another railroad's is passed — rail_fsc.py). kind: 'published' (source month complete), 'open' (source
    month in progress, average so far) or 'forecast' (latest weekly price held flat)."""
    if not weekly:
        return {}
    fn = fn or fsc_from_diesel
    pts = [(date.fromisoformat(d), v) for d, v in weekly]
    latest_d, latest_v = pts[-1]
    out = {}
    for k, y, m in grid_months(today):
        sy, sm = _minus(y, m, LAG)
        vals = [v for d, v in pts if (d.year, d.month) == (sy, sm)]
        nxt = latest_d + timedelta(days=7)
        complete = bool(vals) and (nxt.year, nxt.month) > (sy, sm)
        if complete:
            avg = sum(vals) / len(vals)
            out[k] = {"fsc": fn(avg), "kind": "published", "year": y, "month": m,
                      "basis": f"{_MONTH[sm]} diesel {avg:.3f}"}
        elif vals:
            avg = sum(vals) / len(vals)
            out[k] = {"fsc": fn(avg), "kind": "open", "year": y, "month": m,
                      "basis": f"{_MONTH[sm]} diesel so far {avg:.3f}"}
        else:
            out[k] = {"fsc": fn(latest_v), "kind": "forecast", "year": y, "month": m,
                      "basis": f"latest diesel {latest_v:.3f} held flat"}
    return out
