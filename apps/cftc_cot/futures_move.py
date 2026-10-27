"""
futures_move.py -- price change in each market's front-month futures since the COT cut-off.

The COT report is as of Tuesday's close, so the price chart answers "what has the market
done since the positions were taken": Tuesday's settle to the latest settle, on the CURRENT
front-month contract (the same contract at both ends, so a roll never shows up as a move).

FRONT MONTH ROLLS ON FIRST NOTICE DAY. A contract is the front month until the calendar date
passes its first notice day (FND); on FND itself it is still front. For CBOT corn, soybeans,
meal, oil, the wheats, and MIAX spring wheat, FND is the last business day of the month before
the delivery month (Dec corn: Nov 30; Nov soybeans: Oct 31, or the Friday before when the 31st
is a weekend). Business days use the US federal holiday calendar, which only differs from the
exchange's where a holiday lands on a month-end, and none of the delivery months here do.

Settlements come from JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS (filled daily by the droplet).
"""
from datetime import date, timedelta

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())
MONTH_NUM = dict(zip("FGHJKMNQUVXZ", range(1, 13)))

# product code in the bank -> (label, unit of the settle)
MARKETS = {
    "ZC": ("Corn", "cents/bu"),
    "ZS": ("Soybeans", "cents/bu"),
    "ZM": ("SBM", "$/ton"),
    "ZL": ("SBO", "cents/lb"),
    "ZW": ("SRW", "cents/bu"),
    "KE": ("HRW", "cents/bu"),
    "HRS": ("HRS", "cents/bu"),
    "LE": ("Live cattle", "cents/lb"),
    "GF": ("Feeder cattle", "cents/lb"),
    "HE": ("Lean hogs", "cents/lb"),
}

# Cash-settled: no notice day, so the front month runs to the last trading day instead.
CASH_SETTLED = {"LE", "GF", "HE"}


def first_notice_day(year: int, month_code: str) -> date:
    """Last business day of the month before the delivery month."""
    delivery_first = date(year, MONTH_NUM[month_code], 1)
    end = pd.Timestamp(delivery_first - timedelta(days=1))
    return (end if BDAY.is_on_offset(end) else end - BDAY).date()


def front_month(contracts: list[tuple[int, str]], today: date) -> tuple[int, str] | None:
    """Nearest contract whose first notice day has not yet passed."""
    live = [(y, m) for y, m in contracts if first_notice_day(y, m) >= today]
    return min(live, key=lambda c: (c[0], MONTH_NUM[c[1]])) if live else None


def price_moves(settles: pd.DataFrame, cot_date: date, today: date) -> pd.DataFrame:
    """One row per market: front contract, its settle on the COT Tuesday and on the latest day.

    `settles` has PRODUCT_CODE-style columns: product_code, month, year, date, settle (lower-case).
    Markets with no settle on the Tuesday or none after it come back with NaN change, never
    a guess."""
    settles = settles.copy()
    settles["date"] = pd.to_datetime(settles["date"]).dt.date
    if "expiry" not in settles:
        settles["expiry"] = None
    rows = []
    for code, (name, unit) in MARKETS.items():
        d = settles[settles.product_code == code]
        if d.empty:
            continue
        latest_day = d["date"].max()
        # Contracts that actually traded on the latest day, so a stale tail is never chosen.
        live = d[d["date"] == latest_day]
        if code in CASH_SETTLED:
            ex = {(int(r.year), r.month): pd.to_datetime(r.expiry).date() for r in live.itertuples()}
            ahead = [k for k, v in ex.items() if v >= today]
            front = min(ahead, key=lambda k: ex[k]) if ahead else None
            roll = ex.get(front)
        else:
            front = front_month(list(zip(live.year.astype(int), live.month)), today)
            roll = first_notice_day(*front) if front else None
        if front is None:
            continue
        y, m = front
        c = d[(d.year == y) & (d.month == m)].set_index("date").settle
        tue = c.get(cot_date)
        last = c.get(latest_day)
        rows.append({
            "code": code, "market": name, "unit": unit, "contract": f"{m}{str(y)[2:]}",
            "year": y, "month": m, "fnd": roll, "roll_kind": "last trade" if code in CASH_SETTLED else "first notice",
            "cot_date": cot_date, "cot_settle": tue, "latest_date": latest_day, "latest_settle": last,
            "change": (last - tue) if tue is not None and last is not None and latest_day > cot_date
            else float("nan"),
        })
    return pd.DataFrame(rows)


def continuous_front(settles: pd.DataFrame, code: str) -> pd.Series:
    """Daily front-month settle for one product, rolling as the bar chart does: a contract is the
    front month through its roll date (first notice day, or last trade for cash-settled products)
    and the next contract takes over the day after. Indexed by trading date.

    UNADJUSTED: at a roll the series steps from one contract to the next, so a carry or inverse
    shows as a step. THE FRONT CONTRACT IS CHOSEN FROM THE CALENDAR, NOT FROM WHAT HAS A PRICE that
    day: if the front contract has no settle on a date (a hole in the bank), the date is a gap, not
    a quiet switch to the next contract's price, which would look like a spike.

    `settles`: product_code, month, year, date, settle, and `expiry` for cash-settled products."""
    d = settles[settles.product_code == code].copy()
    if d.empty:
        return pd.Series(dtype=float)
    d["date"] = pd.to_datetime(d["date"]).dt.date
    cash = code in CASH_SETTLED
    rolls = {}
    for (y, m), g in d.groupby(["year", "month"]):
        y = int(y)
        if cash:
            ex = g["expiry"].dropna() if "expiry" in g else pd.Series(dtype=object)
            rolls[(y, m)] = pd.to_datetime(ex.iloc[0]).date() if len(ex) else g["date"].max()
        else:
            rolls[(y, m)] = first_notice_day(y, m)
    order = sorted(rolls, key=lambda k: rolls[k])
    roll_dates = [rolls[k] for k in order]
    px = {k: g.set_index("date")["settle"] for k, g in d.groupby(["year", "month"])}
    out = {}
    import bisect
    for day in sorted(d["date"].unique()):
        i = bisect.bisect_left(roll_dates, day)        # first contract whose roll date is on/after day
        if i >= len(order):
            continue
        v = px[order[i]].get(day)
        if v is not None:
            out[day] = float(v)
    return pd.Series(out, dtype=float).sort_index()
