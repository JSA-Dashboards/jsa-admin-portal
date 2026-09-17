"""Variable Storage Rate (VSR) observation-window tracker for SRW, HRW and HRS wheat.

Reproduces CME's own VSR calculator (cmegroup.com/reports/vsr-calculator.xls):

    carry days   = far first delivery day - near first delivery day
    full carry   = days x ((INT / 100) / 360 x near price + storage)          $/bu
    daily %      = (far price - near price) / full carry
    result       = simple average of the daily % over the observation window
                   >= 80%  storage rises 10/100 of a cent per bushel per day
                   <= 50%  storage falls 10/100 (never below the floor)
                   else    no change

INT is 3-month CME Term SOFR + 221.25bp (SER-9121). Term SOFR is CME-licensed and not
publicly downloadable, so it is approximated from the 3-Month SOFR futures (SR3) strip:
the implied rate interpolated at a settlement date 91 days out, which spans the same
forward three months. Against CME's published Term SOFR for Jul 20 - Aug 13 2026 this
tracked within 0.04pp on most days (worst 0.09pp), worth roughly 0.1pt of % full carry.

Observation window for the nearby spread whose near month is M (H/K, K/N, N/U, U/Z, Z/H):
    start   19th of the previous delivery month (next business day if it isn't one)
    end     option expiration of M: the last Friday at least two business days before
            the last business day of the month preceding M
    effect  the new rate applies from the 19th of M, after its delivery period
Validated against CME's published windows for Mar '21, Mar '23, Mar '26, Jul '26, Sep '26.

Storage in the calculation is the maximum rate in force when the window opens.
Minimums: SRW and HRW 16.5, rising to 26.5 after the December 2026 contracts expire
(SER-9809); HRS 26.5.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import holidays
import pandas as pd

import coc_storage_rates as storage_rates

DELIVERY_MONTHS = "HKNUZ"
MONTH_NUMBER = {"H": 3, "K": 5, "N": 7, "U": 9, "Z": 12}
MONTH_NAME = {"H": "Mar", "K": "May", "N": "Jul", "U": "Sep", "Z": "Dec"}

INCREASE_AT = 0.80
DECREASE_AT = 0.50
STEP = 0.00100
TERM_SOFR_SPREAD_PCT = 2.2125
TERM_DAYS = 91

MARKETS = {
    "ZW": {"label": "Chicago SRW", "exchange": "CBOT"},
    "KE": {"label": "KC HRW", "exchange": "CBOT"},
    "HRS": {"label": "MGEX HRS", "exchange": "MGEX"},
}

MIN_RAISE_DATE = date(2026, 12, 19)

# CME's published results, for the history table and for validating this module.
# (product, near month letter, near year) -> average % of financial full carry.
PUBLISHED = {
    ("ZW", "H", 2021): 11.30, ("KE", "H", 2021): 32.76,
    ("ZW", "K", 2022): -1.70, ("KE", "K", 2022): 5.47,
    ("ZW", "N", 2022): 65.14, ("KE", "N", 2022): 35.11,
    ("ZW", "U", 2022): 72.43, ("KE", "U", 2022): 17.35,
    ("ZW", "Z", 2022): 60.24, ("KE", "Z", 2022): -13.44,
    ("ZW", "H", 2023): 48.39, ("KE", "H", 2023): -33.90,
    ("ZW", "K", 2023): 58.92, ("KE", "K", 2023): -69.27,
    ("ZW", "N", 2023): 71.07, ("KE", "N", 2023): -18.52,
    ("ZW", "U", 2023): 90.29, ("KE", "U", 2023): 34.48,
    ("ZW", "Z", 2023): 78.61, ("KE", "Z", 2023): 33.10,
    ("ZW", "H", 2024): 33.05, ("KE", "H", 2024): 4.00,
    ("ZW", "K", 2024): 92.00, ("KE", "K", 2024): -13.74,
    ("ZW", "N", 2024): 76.12, ("KE", "N", 2024): 62.82,
    ("ZW", "U", 2024): 71.14, ("KE", "U", 2024): 64.09,
    ("ZW", "Z", 2024): 58.16, ("KE", "Z", 2024): 56.61,
    ("ZW", "H", 2025): 57.35, ("KE", "H", 2025): 60.33,
    ("ZW", "K", 2025): 66.40, ("KE", "K", 2025): 83.40,
    ("ZW", "N", 2025): 65.28, ("KE", "N", 2025): 61.80,
    ("ZW", "U", 2025): 64.73, ("KE", "U", 2025): 65.31, ("HRS", "U", 2025): 90.30,
    ("ZW", "Z", 2025): 50.19, ("KE", "Z", 2025): 57.34, ("HRS", "Z", 2025): 58.82,
    ("ZW", "H", 2026): 45.50, ("KE", "H", 2026): 56.00, ("HRS", "H", 2026): 56.74,
    ("ZW", "K", 2026): 62.96, ("KE", "K", 2026): 62.86, ("HRS", "K", 2026): 56.97,
    ("ZW", "N", 2026): 71.71, ("KE", "N", 2026): 41.26, ("HRS", "N", 2026): 50.05,
    ("ZW", "U", 2026): 69.85, ("KE", "U", 2026): 61.03, ("HRS", "U", 2026): 21.90,
}


# --- Exchange calendar ---------------------------------------------------------------
# NYSE's calendar matches CBOT grain closures (incl. Good Friday and Juneteenth) closely
# enough for window dates; realised sessions always come from the price data itself.

@lru_cache(maxsize=None)
def _closures(year: int) -> frozenset:
    return frozenset(holidays.financial_holidays("NYSE", years=year))


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _closures(d.year)


def next_business_day(d: date) -> date:
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def prev_business_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def first_business_day(year: int, month: int) -> date:
    return next_business_day(date(year, month, 1))


def last_business_day(year: int, month: int) -> date:
    d = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)) - timedelta(days=1)
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def option_expiration(year: int, month: int) -> date:
    """Standard grain option expiry for the futures month: the last Friday preceding by at
    least two business days the last business day of the prior month (a holiday Friday
    moves back to the business day before)."""
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    cutoff = prev_business_day(prev_business_day(last_business_day(py, pm)))
    friday = cutoff - timedelta(days=(cutoff.weekday() - 4) % 7)
    while not is_business_day(friday):
        friday -= timedelta(days=1)
    return friday


def business_days_between(start: date, end: date) -> int:
    """Business days in [start, end]."""
    n, d = 0, start
    while d <= end:
        n += is_business_day(d)
        d += timedelta(days=1)
    return n


# --- Storage rates -------------------------------------------------------------------

def floor_rate(product: str, on: date) -> float:
    if product == "HRS":
        return 0.00265
    return 0.00265 if on >= MIN_RAISE_DATE else storage_rates.VSR_FLOOR


def rate_on(product: str, on: date) -> float:
    """storage_rates' schedule, or the minimum for dates before it starts."""
    rate = storage_rates.rate_on(product, on)
    return floor_rate(product, on) if rate is None else rate


def level_of(rate: float) -> int:
    """VSR level numbered by absolute rate: 16.5 = 1, 26.5 = 2, 36.5 = 3 ..."""
    return int(round((rate - storage_rates.VSR_FLOOR) / STEP)) + 1


# --- Windows -------------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    product: str
    near_letter: str
    near_year: int
    far_letter: str
    far_year: int
    start: date
    end: date
    effective: date
    near_fdd: date
    far_fdd: date
    storage_rate: float

    @property
    def carry_days(self) -> int:
        return (self.far_fdd - self.near_fdd).days

    @property
    def near_ticker(self) -> str:
        return f"{self.product}{self.near_letter}{self.near_year % 10}"

    @property
    def far_ticker(self) -> str:
        return f"{self.product}{self.far_letter}{self.far_year % 10}"

    @property
    def label(self) -> str:
        return (f"{MONTH_NAME[self.near_letter]} '{self.near_year % 100:02d} / "
                f"{MONTH_NAME[self.far_letter]} '{self.far_year % 100:02d}")

    @property
    def sessions(self) -> int:
        return business_days_between(self.start, self.end)

    def status(self, today: date) -> str:
        if today < self.start:
            return "upcoming"
        return "closed" if today > self.end else "open"


def build_window(product: str, near_letter: str, near_year: int) -> Window:
    i = DELIVERY_MONTHS.index(near_letter)
    far_letter = DELIVERY_MONTHS[(i + 1) % 5]
    far_year = near_year + (1 if near_letter == "Z" else 0)
    prev_letter = DELIVERY_MONTHS[(i - 1) % 5]
    prev_year = near_year - (1 if near_letter == "H" else 0)
    start = next_business_day(date(prev_year, MONTH_NUMBER[prev_letter], 19))
    near_month = MONTH_NUMBER[near_letter]
    return Window(
        product=product,
        near_letter=near_letter, near_year=near_year,
        far_letter=far_letter, far_year=far_year,
        start=start,
        end=option_expiration(near_year, near_month),
        effective=date(near_year, near_month, 19),
        near_fdd=first_business_day(near_year, near_month),
        far_fdd=first_business_day(far_year, MONTH_NUMBER[far_letter]),
        storage_rate=rate_on(product, start),
    )


def windows_between(product: str, first: date, last: date) -> list[Window]:
    """Every window whose observation period overlaps [first, last], in order."""
    out = []
    for year in range(first.year - 1, last.year + 2):
        for letter in DELIVERY_MONTHS:
            w = build_window(product, letter, year)
            if w.end >= first and w.start <= last:
                out.append(w)
    return sorted(out, key=lambda w: w.start)


def current_window(product: str, today: date) -> Window:
    """The open window, or the next one to open if today falls between windows."""
    for w in windows_between(product, today - timedelta(days=100), today + timedelta(days=100)):
        if w.end >= today:
            return w
    raise ValueError("no window found")  # unreachable: windows tile the calendar


# --- Interest ------------------------------------------------------------------------

SR3_LETTERS = "FGHJKMNQUVXZ"

# Used only when the SR3 strip has no settlement for a session: effective fed funds ran
# about 0.15pp under CME 3M Term SOFR through Jul-Aug 2026, so that gap is added back.
DFF_TO_TERM_SOFR_PCT = 0.15


def term_rate_from_fed_funds(fed_funds: pd.Series, on: date) -> float | None:
    if fed_funds is None or not len(fed_funds):
        return None
    prior = fed_funds[fed_funds.index <= on]
    return None if prior.empty else float(prior.iloc[-1]) + DFF_TO_TERM_SOFR_PCT


def third_wednesday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(2 - first.weekday()) % 7 + 14)


def sr3_contracts_for(window: Window) -> dict[str, date]:
    """SR3 tickers -> final settlement date covering every rate the window needs.

    Built from the contract rule rather than Massive's /contracts listing, which buries
    the outrights under thousands of strategy rows. A contract month M references the
    quarter from M's third Wednesday to the third Wednesday three months later, and
    settles on that later date."""
    out = {}
    y, m = window.start.year, window.start.month - 1
    last = (window.end.year, window.end.month + 2)
    while (y, m) <= last:
        if m < 1:
            y, m = y - 1, m + 12
        if m > 12:
            y, m = y + 1, m - 12
            continue
        sy, sm = (y + 1, m - 9) if m > 9 else (y, m + 3)
        out[f"SR3{SR3_LETTERS[m - 1]}{y % 10}"] = third_wednesday(sy, sm)
        m += 1
    return out

def term_rate_from_sr3(sr3_histories: dict[str, pd.Series], sr3_settlements: dict[str, date],
                       on: date) -> float | None:
    """3-month forward rate (percent) implied by the SR3 strip on `on`, interpolated at a
    settlement date TERM_DAYS ahead. None if the strip doesn't bracket that date."""
    target = on + timedelta(days=TERM_DAYS)
    points = sorted(
        (sr3_settlements[t], 100.0 - float(h[on]))
        for t, h in sr3_histories.items()
        if t in sr3_settlements and len(h) and on in h.index
    )
    below = [p for p in points if p[0] <= target]
    above = [p for p in points if p[0] >= target]
    if not below or not above:
        return None
    (d0, r0), (d1, r1) = below[-1], above[0]
    if d0 == d1:
        return r0
    return r0 + (r1 - r0) * (target - d0).days / (d1 - d0).days


# --- Daily calculation ----------------------------------------------------------------

def daily_table(window: Window, near_cents: pd.Series, far_cents: pd.Series,
                term_rate_pct) -> pd.DataFrame:
    """One row per session inside the window with prices for both legs.

    `term_rate_pct(date)` returns the base rate in percent (before the 221.25bp spread)
    and a source tag, or (None, None) when no rate is available for that date."""
    both = pd.concat({"near": near_cents, "far": far_cents}, axis=1).dropna()
    both = both[(both.index >= window.start) & (both.index <= window.end)]
    rows = []
    for day, (near_c, far_c) in both.iterrows():
        base, source = term_rate_pct(day)
        if base is None:
            continue
        near, far = near_c / 100.0, far_c / 100.0
        int_pct = base + TERM_SOFR_SPREAD_PCT
        ffc = window.carry_days * ((int_pct / 100) / 360 * near + window.storage_rate)
        spread = far - near
        rows.append({
            "date": day, "near": near, "far": far, "int_pct": int_pct, "rate_source": source,
            "full_carry": ffc, "spread": spread, "pct": spread / ffc,
        })
    frame = pd.DataFrame(rows)
    if len(frame):
        frame["running_avg"] = frame["pct"].expanding().mean()
    return frame


def zone(avg: float) -> str:
    if avg >= INCREASE_AT:
        return "increase"
    if avg <= DECREASE_AT:
        return "decrease"
    return "no change"


def projected_rate(window: Window, avg: float) -> float:
    rate = window.storage_rate
    if avg >= INCREASE_AT:
        rate += STEP
    elif avg <= DECREASE_AT:
        rate -= STEP
    return round(max(rate, floor_rate(window.product, window.effective)), 5)


def summarize(window: Window, table: pd.DataFrame, today: date) -> dict:
    """Headline numbers for one window."""
    total = window.sessions
    observed = len(table)
    out = {
        "window": window, "status": window.status(today), "sessions_total": total,
        "sessions_observed": observed, "sessions_left": None, "avg": None, "zone": None,
        "projected_rate": None, "latest_pct": None, "needed_for_increase": None,
        "needed_for_decrease": None,
    }
    if not observed:
        return out
    avg = float(table["pct"].mean())
    left = max(total - observed, 0) if out["status"] == "open" else 0
    total_sum = float(table["pct"].sum())
    out.update(avg=avg, zone=zone(avg), projected_rate=projected_rate(window, avg),
               latest_pct=float(table["pct"].iloc[-1]), sessions_left=left)
    if left:
        n = observed + left
        # Average the remaining sessions must print to finish exactly on each threshold.
        out["needed_for_increase"] = (INCREASE_AT * n - total_sum) / left
        out["needed_for_decrease"] = (DECREASE_AT * n - total_sum) / left
    return out


def cents_per_month(rate: float) -> int:
    return storage_rates.cents_per_month(rate)
