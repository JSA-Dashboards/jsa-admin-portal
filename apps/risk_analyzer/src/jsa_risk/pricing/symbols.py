"""CME/CBOT contract symbol decoding, generalized across commodities (see commodities.py).

The 3rd character of a futures/option symbol is the contract month code and the next two
are the 2-digit year (e.g. "ZCZ26" -> Z, 26; "LEG26" -> G, 26) -- this position convention
is the same for every CME/CBOT product. What differs per commodity is which month codes
have a real *listed* future (corn: H/K/N/U/Z; soybeans: F/H/K/N/Q/U/X; live cattle:
G/J/M/Q/V/Z; feeder cattle: F/H/J/K/Q/U/V/X) -- every other month code only ever appears
on a serial option, one that expires in its own calendar month but is priced against the
next listed contract chronologically (which may fall in the following year, e.g.
soybeans' December, itself serial, rolls to January of the next year).

A listed contract's own practical trading life ends well before its namesake calendar
month even begins (corn's last trade day is roughly two weeks earlier) -- so once the
calendar reaches the 1st of a listed contract's own month, that contract is treated as
rolled off, and anything still nominally tied to it (its own monthly option, or a serial
option one hop away) rolls forward to the next listed contract instead, exactly like a
true serial option already does. This is date-dependent, so decoding takes an optional
`today` (defaults to the real today).

Every function here takes a `commodity: CommoditySpec` (default corn, for the common case
and for existing callers/tests) -- the dashboard shows one commodity at a time (see
state.py), so callers thread through whichever spec the session has selected.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Tuple

from .commodities import CORN, CommoditySpec

MONTH_NAMES = {
    "F": "Jan", "G": "Feb", "H": "Mar", "J": "Apr", "K": "May", "M": "Jun",
    "N": "Jul", "Q": "Aug", "U": "Sep", "V": "Oct", "X": "Nov", "Z": "Dec",
}
MONTH_NUMBERS = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}


@dataclass(frozen=True)
class DecodedSymbol:
    raw: str
    expiry_month: str
    expiry_month_name: str
    year2: str                     # the option's own literal year, from the raw symbol
    is_serial: bool                # True whenever the underlying differs from the symbol's own month -- a true serial option, or a listed month that has itself rolled off
    underlying_month: str
    underlying_month_name: str
    underlying_year2: str          # the underlying contract's own year -- can differ from year2 when a roll crosses a year boundary
    underlying_key: str            # canonical key, e.g. "Z26"


def _next_listed(months_order, month: str, year: int) -> Tuple[str, int]:
    idx = months_order.index(month)
    if idx == len(months_order) - 1:
        return months_order[0], year + 1
    return months_order[idx + 1], year


def _nominal_listed_month(months_order, month: str, year: int) -> Tuple[str, int]:
    """If `month` is itself listed, it's its own nominal underlying. Otherwise, the
    nominal underlying is the next listed month chronologically after it -- within the
    same year, or the first listed month of next year if `month` falls after the last
    listed month of this one (e.g. corn's Oct/Nov, serial, roll to Dec the same year, but
    soybeans' December, also serial since soybeans list no December future, rolls to
    January of *next* year)."""
    if month in months_order:
        return month, year
    month_num = MONTH_NUMBERS[month]
    for m in months_order:
        if MONTH_NUMBERS[m] > month_num:
            return m, year
    return months_order[0], year + 1


def _contract_has_rolled(month: str, year: int, today: date, rolls_at_month_start: bool) -> bool:
    start = date(year, MONTH_NUMBERS[month], 1)
    if rolls_at_month_start:
        return today >= start
    return today >= date(year + (month == "Z"), MONTH_NUMBERS[month] % 12 + 1, 1)   # first of the NEXT month


def _roll_to_active(
    months_order, month: str, year: int, today: date, rolls_at_month_start: bool = True,
) -> Tuple[str, int]:
    """Cascades forward (not just one hop) so a long-stale reference still lands on
    whichever listed contract is actually current as of `today`. Whether a contract counts
    as rolled from the 1st of its own month or only once the month is over is a
    per-commodity choice (CommoditySpec.rolls_at_month_start)."""
    while _contract_has_rolled(month, year, today, rolls_at_month_start):
        month, year = _next_listed(months_order, month, year)
    return month, year


def decode_contract_symbol(
    raw: Optional[str], today: Optional[date] = None, commodity: CommoditySpec = CORN
) -> Optional[DecodedSymbol]:
    s = (raw or "").strip().upper()
    if len(s) < 5:
        return None
    month_char = s[2]
    year2 = s[3:5]
    if month_char not in MONTH_NAMES or not year2.isdigit():
        return None
    today = today or date.today()
    year = 2000 + int(year2)
    nominal_month, nominal_year = _nominal_listed_month(commodity.listed_months, month_char, year)
    underlying_month, underlying_year = _roll_to_active(
        commodity.listed_months, nominal_month, nominal_year, today, commodity.rolls_at_month_start)
    is_serial = underlying_month != month_char or underlying_year != year
    return DecodedSymbol(
        raw=s,
        expiry_month=month_char,
        expiry_month_name=MONTH_NAMES[month_char],
        year2=year2,
        is_serial=is_serial,
        underlying_month=underlying_month,
        underlying_month_name=MONTH_NAMES[underlying_month],
        underlying_year2=f"{underlying_year % 100:02d}",
        underlying_key=f"{underlying_month}{underlying_year % 100:02d}",
    )


def canonical_contract_key(
    raw_label: Optional[str], today: Optional[date] = None, commodity: CommoditySpec = CORN
) -> str:
    decoded = decode_contract_symbol(raw_label, today, commodity)
    return decoded.underlying_key if decoded else (raw_label or "").strip().upper()


def contract_display_name(
    raw_label: Optional[str], today: Optional[date] = None, commodity: CommoditySpec = CORN
) -> str:
    decoded = decode_contract_symbol(raw_label, today, commodity)
    if not decoded:
        return (raw_label or "").strip().upper() or "—"
    name = f"{decoded.underlying_month_name} '{decoded.underlying_year2}"
    if decoded.is_serial:
        name += f" (via {decoded.expiry_month_name} option)"
    return name


def normalize_underlying_override(raw: Optional[str], commodity: CommoditySpec = CORN) -> Optional[str]:
    """Turns whatever was typed into the override box into a canonical key (month letter +
    2-digit year, e.g. "V26"), or None if it isn't one. The full symbol shown beside it in
    the table ("LEV26", this commodity's code + key) is accepted too, since that's the
    natural thing to copy -- the commodity code is stripped, never reinterpreted."""
    s = (raw or "").strip().upper()
    if len(s) == 5 and s.startswith(commodity.code):
        s = s[len(commodity.code):]
    if len(s) == 3 and s[0].isalpha() and s[1:].isdigit():
        return s
    return None


def format_canonical_key(key: Optional[str]) -> str:
    """Formats an already-final canonical key (month letter + 2-digit year, e.g. "Z26")
    as a plain month name/year -- no serial-to-listed mapping and no date-based rolling,
    since a canonical key is by definition the underlying itself, not something that
    still needs to be resolved to one. Used for a manual underlying_override, which names
    its target directly rather than needing to be decoded from an option symbol."""
    s = (key or "").strip().upper()
    if len(s) != 3 or s[0] not in MONTH_NAMES or not s[1:].isdigit():
        return s or "—"
    return f"{MONTH_NAMES[s[0]]} '{s[1:]}"


def upcoming_contract_keys(
    commodity: CommoditySpec = CORN, today: Optional[date] = None, count: int = 4
) -> list:
    """The next `count` listed contracts that haven't yet rolled off as of `today`, as
    canonical keys in calendar order (e.g. ["Z26", "H27", ...]). Same roll rule as
    decode_contract_symbol (see CommoditySpec.rolls_at_month_start)."""
    today = today or date.today()
    keys: list = []
    for year in range(today.year, today.year + 4):
        for month in commodity.listed_months:
            if not _contract_has_rolled(month, year, today, commodity.rolls_at_month_start):
                keys.append(f"{month}{year % 100:02d}")
                if len(keys) == count:
                    return keys
    return keys


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(d: date) -> Optional[date]:
    """A fixed-date holiday's observed day: Saturday -> the Friday before, Sunday -> the
    Monday after. (New Year's Day on a Saturday isn't observed on the prior Friday.)"""
    if d.weekday() == 5:
        return None if (d.month, d.day) == (1, 1) else d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _exchange_holidays(year: int) -> set:
    """CME Group's US equity-style closures that matter for option expiries (a Friday
    holiday moves an expiry to the prior business day)."""
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 12, 25)]
    days = {_observed(d) for d in fixed}
    days |= {
        _nth_weekday(year, 1, 0, 3),                       # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),                       # Presidents Day
        _easter(year) - timedelta(days=2),                 # Good Friday
        _last_weekday(year, 5, 0),                         # Memorial Day
        _nth_weekday(year, 9, 0, 1),                       # Labor Day
        _nth_weekday(year, 11, 3, 4),                      # Thanksgiving
    }
    days.add(_observed(date(year + 1, 1, 1)))              # an observed Jan 1 can land in Dec
    return {d for d in days if d}


def _is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _exchange_holidays(d.year)


def _prior_business_day(d: date) -> date:
    while not _is_business_day(d):
        d -= timedelta(days=1)
    return d


def _last_business_day(year: int, month: int) -> date:
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    while not _is_business_day(d):
        d -= timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _cbot_grain_option_expiry(year: int, month: int) -> date:
    """The last Friday that precedes, by at least two business days, the last business day
    of the month before the option month (CBOT corn and soybean options)."""
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    last_bd = _last_business_day(prev_year, prev_month)
    d = last_bd - timedelta(days=1)
    while True:
        if d.weekday() == 4:
            after = sum(1 for i in range(1, (last_bd - d).days + 1) if _is_business_day(d + timedelta(days=i)))
            if after >= 2:
                return _prior_business_day(d)      # a Friday holiday expires the day before
        d -= timedelta(days=1)


def option_expiry_date(raw_label: Optional[str], commodity: CommoditySpec = CORN) -> Optional[date]:
    """Best-effort actual last-trade date of the monthly option the symbol names (its own
    month/year, not the underlying it prices off -- an Oct option expires in September).
    None when the symbol can't be read or the commodity's rule isn't modelled.

    Corn/soybeans/soybean meal: the CBOT rule above. Live cattle: first Friday of the contract month
    (checked against CME DataMine's Last Trade Dates). Feeder cattle: last Thursday of the
    contract month. Weekly/short-dated options aren't covered. A holiday on the expiry day moves it to the
    prior business day (Christmas, New Year's Day and Good Friday did, in 2026-27)."""
    s = (raw_label or "").strip().upper()
    if len(s) < 5 or s[2] not in MONTH_NUMBERS or not s[3:5].isdigit():
        return None
    month, year = MONTH_NUMBERS[s[2]], 2000 + int(s[3:5])
    if commodity.code in ("ZC", "ZS", "ZM"):
        return _cbot_grain_option_expiry(year, month)
    if commodity.code == "LE":
        return _prior_business_day(_nth_weekday(year, month, 4, 1))
    if commodity.code == "GF":
        return _prior_business_day(_last_weekday(year, month, 3))
    return None
