"""CME maximum storage (premium) charges over time, for historical % of full carry.

Using today's storage rate for every spread misstates history wherever the exchange rate
has since changed. The storage that matters to a spread is the rate it is actually carried
under: the rate(s) in force across its carry window, from the 19th of the near delivery
month to the 19th of the far one. For VSR wheat that rate is set by the spread's own
observation window and takes effect after the near delivery period, so it belongs to the
spread pair — not to whichever date the spread happens to be viewed on. See
`carry_window`, `carry_rate` and `vsr_profile`.

Rates are dollars per bushel per day, matching the app's `default_storage` convention
(x100 gives cents on the bushel-quoted markets): 0.00165 = 16.5/100 of a cent per bushel
per day, roughly 5 cents per bushel per month.

Sources
-------
Corn and soybeans — CME SER-8198RRR (Oct 23, 2018): 16.5/100 -> 26.5/100.
    Corn:     16.5 through 12/18/2019, 26.5 commencing 12/19/2019
              (after expiration of the December 2019 contract)
    Soybeans: 16.5 through 11/18/2019, 26.5 commencing 11/19/2019
              (after expiration of the November 2019 contract)

Chicago SRW (ZW) and KC HRW (KE) wheat — Variable Storage Rate. A nearby spread
averaging >= 80% of financial full carry raises the rate 10/100 of a cent following the
nearby delivery period; <= 50% lowers it; the floor is 16.5/100. Every step below is from
a CME VSR results Special Executive Report, and each report's starting rate matches the
previous report's outcome without a break:
    SER-8727  Mar  1 2021  ZW 16.5 floor, KE 16.5 floor   (earliest verified anchor)
    SER-8983  Apr 26 2022  ZW 16.5, KE 16.5 — no change through SER-9211 (Jun 2023)
    SER-9246  Aug 29 2023  ZW 16.5 -> 26.5 on Sep 19 2023  (90.29% FFC)
    SER-9341  Feb 26 2024  ZW 26.5 -> 16.5 on Mar 19 2024  (33.05%)
    SER-9368  Apr 29 2024  ZW 16.5 -> 26.5 on May 19 2024  (92.00%)
    SER-9560  Apr 29 2025  KE 16.5 -> 26.5 on May 19 2025  (83.40%)
    SER-9694  Feb 24 2026  ZW 26.5 -> 16.5 on Mar 19 2026  (45.50%)
    SER-9973  Jun 29 2026  KE 26.5 -> 16.5 on Jul 19 2026  (41.26%)
    SER-9809  Aug 24 2026  both unchanged at 16.5; minimum rises to 26.5 following
                           expiration of the December 2026 contracts

MGEX spring wheat (HRS) — Variable Storage Rate with a 26.5/100 floor:
    SER-9605  Aug 2025     HRS 26.5 -> 36.5 on Sep 19 2025  (90.30%); 26.5 was the
                           rate in force through that Jul-Aug 2025 observation window
    SER-9809  Aug 24 2026  HRS 36.5 -> 26.5 on Sep 19 2026  (21.90%)

Known gaps — stated rather than papered over
--------------------------------------------
* Wheat, Mar 2021 -> Apr 2022: CME's notice index does not surface the five
  determinations in between. Both ends sit at the 16.5 floor, so the rate could only
  have differed through a rise and a fall inside that year; treated as 16.5.
* HRS before its Jul 2025 anchor is not on record here.
* Dates before a product's first entry return None, and callers fall back to the rate
  entered in the app.

Corn and soybeans before 2019: the rate was unchanged at 16.5/100 for the whole archive
window (confirmed by JSA), so the 2019 steps are the only ones needed back to 2006.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date

# product_code -> [(effective_date, dollars_per_bushel_per_day), ...], ascending.
# A rate applies from its effective date until the next entry.
SCHEDULE: dict[str, list[tuple[date, float]]] = {
    "ZC": [
        (date(2006, 1, 1), 0.00165),    # unchanged before 2019, back to the archive start
        (date(2019, 12, 19), 0.00265),  # SER-8198RRR
    ],
    "ZS": [
        (date(2006, 1, 1), 0.00165),
        (date(2019, 11, 19), 0.00265),  # SER-8198RRR
    ],
    "ZW": [
        (date(2021, 3, 1), 0.00165),    # SER-8727, VSR floor
        (date(2023, 9, 19), 0.00265),   # SER-9246
        (date(2024, 3, 19), 0.00165),   # SER-9341
        (date(2024, 5, 19), 0.00265),   # SER-9368
        (date(2026, 3, 19), 0.00165),   # SER-9694
        (date(2026, 12, 19), 0.00265),  # SER-9809, minimum raised after Dec 2026 expiry
    ],
    "KE": [
        (date(2021, 3, 1), 0.00165),    # SER-8727, VSR floor
        (date(2025, 5, 19), 0.00265),   # SER-9560
        (date(2026, 7, 19), 0.00165),   # SER-9973
        (date(2026, 12, 19), 0.00265),  # SER-9809, minimum raised after Dec 2026 expiry
    ],
    "HRS": [
        (date(2025, 7, 21), 0.00265),   # starting rate of the SER-9605 window, VSR floor
        (date(2025, 9, 19), 0.00365),   # SER-9605
        (date(2026, 9, 19), 0.00265),   # SER-9809
    ],
}

_DATES = {code: [d for d, _ in steps] for code, steps in SCHEDULE.items()}


def has_schedule(product_code: str) -> bool:
    return product_code in SCHEDULE


def rate_on(product_code: str, on: date) -> float | None:
    """The maximum storage rate in effect on `on`, or None if unknown for that date."""
    steps = SCHEDULE.get(product_code)
    if not steps:
        return None
    i = bisect_right(_DATES[product_code], on) - 1
    return steps[i][1] if i >= 0 else None


# Markets whose storage rate moves under the Variable Storage Rate mechanism. Corn and
# soybeans have fixed maximums, so they have no VSR level.
VSR_PRODUCTS = ("ZW", "KE", "HRS")
VSR_FLOOR = 0.00165   # VSR 1: 16.5/100 of a cent per bushel per day, ~5 cents/month
VSR_STEP = 0.00100    # each level adds 10/100 of a cent per day, ~3 cents/month

# Rates are published up to, but not including, the next undetermined adjustment date.
# SER-9809 fixed the Sep 19 2026 rate and forced Dec 19 2026 to 26.5, so the next open
# question is the Mar-May 2027 observation, adjusting Mar 19 2027. Advance this date as
# each VSR results notice is added to SCHEDULE.
# HRS has no forced change in December, so its next open determination is the Dec '26
# window, adjusting Dec 19 2026.
KNOWN_UNTIL: dict[str, date] = {"ZW": date(2027, 3, 19), "KE": date(2027, 3, 19),
                                "HRS": date(2026, 12, 19)}

# CME storage changes take effect on the 19th of the delivery month, following the
# delivery period — both the VSR adjustments and the 2019 corn/soybean increase.
EFFECTIVE_DAY = 19


# How VSR works (CME "VSR Timeline and Calculation", SER-9121):
#   Each NEARBY calendar spread (H/K, K/N, N/U, U/Z, Z/H) is observed from the 19th of the
#   previous delivery month through nearby option expiration. Its average % of financial
#   full carry (>= 80% up, <= 50% down) sets the maximum storage rate that takes effect on
#   the 19th of the nearby delivery month, after its delivery period — the rate charged on
#   certificates carried from that delivery month into the next.
# So the storage a spread actually carries under is the rate in force across its CARRY
# WINDOW, from the 19th of its near delivery month to the 19th of its far one. An adjacent
# spread sits inside one VSR period, set by its own observation window; a wider spread
# (e.g. Dec/May) spans several periods and can straddle a change.


def carry_window(near_expiry: date, far_expiry: date) -> tuple[date, date]:
    """[start, end) over which storage is paid when carrying the near leg into the far
    leg: the 19th of the near delivery month to the 19th of the far delivery month."""
    return (date(near_expiry.year, near_expiry.month, EFFECTIVE_DAY),
            date(far_expiry.year, far_expiry.month, EFFECTIVE_DAY))


def _segments(product_code: str, start: date, end: date, fallback: float):
    """Yield (segment_start, segment_end, rate) covering [start, end) in schedule order."""
    if end <= start:
        return
    steps = SCHEDULE.get(product_code, ())
    cuts = sorted({start, end} | {d for d, _ in steps if start < d < end})
    for a, b in zip(cuts, cuts[1:]):
        rate = rate_on(product_code, a)
        yield a, b, (fallback if rate is None else rate)


def average_rate(product_code: str, start: date, end: date, fallback: float) -> float:
    """Day-weighted average maximum storage rate across [start, end)."""
    total_days = (end - start).days
    if total_days <= 0 or product_code not in SCHEDULE:
        return fallback
    weighted = sum((b - a).days * r for a, b, r in _segments(product_code, start, end, fallback))
    return weighted / total_days


def carry_rate(product_code: str, near_expiry: date, far_expiry: date, fallback: float) -> float:
    """The storage rate a spread is actually carried under: the average across its carry
    window. Constant for the whole life of the spread — it belongs to the pair, not to the
    date the spread is observed."""
    start, end = carry_window(near_expiry, far_expiry)
    return average_rate(product_code, start, end, fallback)


def vsr_profile(product_code: str, near_expiry: date, far_expiry: date) -> dict | None:
    """VSR level(s) governing a spread's carry window, for labelling.

    Returns {"levels": [1, 2] in chronological order with repeats collapsed,
             "dominant": the level covering the most days,
             "pending": True if part of the window falls after KNOWN_UNTIL}.
    None for non-VSR markets."""
    if product_code not in VSR_PRODUCTS:
        return None
    start, end = carry_window(near_expiry, far_expiry)
    if rate_on(product_code, start) is None:
        return None  # no rate on record (e.g. HRS before Jul 2025) — don't guess a level
    days_by_level: dict[int, int] = {}
    sequence: list[int] = []
    for a, b, rate in _segments(product_code, start, end, fallback=VSR_FLOOR):
        level = int(round((rate - VSR_FLOOR) / VSR_STEP)) + 1
        days_by_level[level] = days_by_level.get(level, 0) + (b - a).days
        if not sequence or sequence[-1] != level:
            sequence.append(level)
    if not sequence:
        return None
    known_until = KNOWN_UNTIL.get(product_code)
    return {
        "levels": sequence,
        "dominant": max(days_by_level, key=days_by_level.get),
        "pending": bool(known_until and end > known_until),
    }




def cents_per_month(rate: float) -> int:
    """16.5/100 of a cent per day -> 5 cents per bushel per month, as CME quotes it."""
    return int(round(rate * 100 * 30))


def changes_between(product_code: str, start: date, end: date) -> list[tuple[date, float]]:
    """Rate steps that take effect inside [start, end] — for marking them on charts."""
    return [(d, r) for d, r in SCHEDULE.get(product_code, ()) if start <= d <= end]
