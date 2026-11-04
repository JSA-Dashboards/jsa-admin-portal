"""Cattle Equivalent -- what the carcass-weight gain is worth in head.

The question this answers: carcass weights are at record highs while the cattle
herd is at a 75-year low, so how many cattle is the weight gain standing in for?

    head-equivalents = fed head x (carcass weight / baseline carcass weight - 1)

That is "today's kill carries the beef of this many more head at the old
weight". Nothing else on the portal says it, and the arithmetic is one line --
what takes care is choosing what goes on each side of it.

THE DENOMINATOR IS FED MARKETINGS, AND ON-FEED INVENTORY IS NOT AN OPTION.
Marketings is a FLOW -- head leaving feedlots -- so each animal is counted once.
On-feed inventory is a STOCK, and it is inflated by the very thing that makes a
carcass heavy: an animal standing an extra three weeks is counted in the
inventory for three more weeks AND comes out heavier. The identity makes it
plain:

    beef / on-feed inventory  =  (marketings / on-feed)  x  (beef / marketings)
                                  turnover                   weight

Measured on this data, 2015 -> 2025: turnover -6.5%, weight +5.2%, net -1.6%.
Dividing beef by the inventory subtracts the effect the page exists to measure,
and prints a flat line over a decade in which the fed carcass gained 54 lb.
`turnover()` exists to SHOW that, in the panel that explains why days on feed
are doing the work -- never to put an inventory under a division line.
`tests/test_fed_equivalent.py` asserts the cancellation and asserts this module
never divides beef by an inventory.

CARCASS BASIS THROUGHOUT, AND THAT IS NOT THE SIDEBAR'S CHOICE TO MAKE. A
head-equivalent is a statement about beef produced, so it has to be a carcass
figure; and NASS settles it anyway -- it publishes no live-weight series for
steers or heifers at all, only for `GE 500 LBS` and `CALVES`. The page's
Live/Dressed toggle therefore does not reach this tab, which the caption says
out loud because it otherwise reads as a bug.

FED MEANS STEERS AND HEIFERS, NEVER `GE 500 LBS`. The all-cattle class folds in
cows at ~658 lb and bulls, so its average runs ~45 lb under the fed carcass and
moves with the cull mix rather than with the feeding. Using it would put a
number that is partly a cow-slaughter story into a tile labelled as a feeding
one. The classes are head-weighted together, never averaged unweighted: steers
outnumber heifers about 3:2 and carry an 80-plus pound heavier carcass, so a
simple mean runs ~15 lb light.

TWO SOURCES, ONE PER YEAR, NO OVERLAP. The shared NASS cache holds this page's
weekly slaughter for the last eight years only, so years before that come from
`data/fed_equivalent.json`, frozen by `scripts/build_fed_equivalent.py` from
the keyless QuickStats bulk dump. `annual_history()` refuses to let the two
meet: frozen years stop where the live window starts, and a year present in
both raises rather than resolving silently.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

# Bump whenever load()/compare() change the SHAPE of what they return. The
# cache serves shape, not freshness -- st.cache_data keys on the decorated
# function's own code and never on the modules it calls, so without this a
# reshaped return value is served from a cache built before the reshape and the
# new keys render an em dash with nothing raising. Must be passed AT THE CALL
# SITE: a default is never hashed.
SCHEMA = 1

DATA = Path(__file__).parent / "data" / "fed_equivalent.json"

FED_CLASSES = ("STEERS", "HEIFERS")
DRESSED_UNIT = "LB / HEAD, DRESSED BASIS"
HEAD_UNIT = "HEAD"

# A year needs this many reported weeks to count as complete. USDA publishes 52
# or 53 ISO weeks; anything less is a part year and must not sit beside full
# ones -- the trap `beef_trade.annual_figure` and the US Cow Herd retention
# chart both record.
FULL_YEAR_WEEKS = 52

# How the baseline years are described on the page. A baseline is a judgement,
# so the page names it rather than letting a bare year imply one is canonical.
BASELINE_NOTES = {
    2025: "last year",
    2022: "the last big kill",
    2019: "before the herd contraction",
}


def load_history(path: Path | None = None) -> tuple[dict[int, dict], int]:
    """Frozen complete years, and the first year the live window covers."""
    raw = json.loads(Path(path or DATA).read_text(encoding="utf-8"))
    years = {int(y): v for y, v in raw["years"].items()}
    return years, int(raw["live_from"])


def fed_weekly(raw: pd.DataFrame) -> pd.DataFrame:
    """Weekly fed head and head-weighted fed carcass weight.

    `raw` is the page's own NASS frame (year, week_ending, class_desc,
    unit_desc, Value). A week is kept only when all four figures are present --
    both classes, head and weight. A week missing heifers would otherwise
    report the steer carcass as the fed carcass, about 35 lb high, on a chart
    where that is entirely plausible.
    """
    cols = {"class_desc", "unit_desc", "Value", "week_ending"}
    if raw.empty or not cols.issubset(raw.columns):
        return pd.DataFrame(columns=["week_ending", "year", "fed_head", "fed_carcass_lb"])

    df = raw[raw["class_desc"].isin(FED_CLASSES)].copy()
    df = df[df["unit_desc"].isin((DRESSED_UNIT, HEAD_UNIT))]
    if df.empty:
        return pd.DataFrame(columns=["week_ending", "year", "fed_head", "fed_carcass_lb"])

    df["kind"] = df["unit_desc"].map({HEAD_UNIT: "head", DRESSED_UNIT: "wt"})
    wide = (df.pivot_table(index="week_ending", columns=["class_desc", "kind"],
                           values="Value", aggfunc="max"))
    need = [(c, k) for c in FED_CLASSES for k in ("head", "wt")]
    if any(c not in wide.columns for c in need):
        return pd.DataFrame(columns=["week_ending", "year", "fed_head", "fed_carcass_lb"])
    wide = wide[need].dropna()

    head = sum(wide[(c, "head")] for c in FED_CLASSES)
    beef = sum(wide[(c, "head")] * wide[(c, "wt")] for c in FED_CLASSES)
    out = pd.DataFrame({
        "week_ending": wide.index,
        "fed_head": head.values,
        "fed_beef_lb": beef.values,
        "fed_carcass_lb": (beef / head).values,
    })
    out["week_ending"] = pd.to_datetime(out["week_ending"])
    out["year"] = out["week_ending"].dt.year
    return out.sort_values("week_ending").reset_index(drop=True)


def _roll(frame: pd.DataFrame) -> dict:
    head = float(frame["fed_head"].sum())
    beef = float(frame["fed_beef_lb"].sum())
    return {"weeks": int(len(frame)), "fed_head": head, "fed_beef_lb": beef,
            "fed_carcass_lb": beef / head}


def ytd(weekly: pd.DataFrame, year: int, weeks: int | None = None) -> dict | None:
    """The first `weeks` reported weeks of `year`, head-weighted.

    LIKE FOR LIKE IS THE WHOLE POINT OF `weeks`. Carcasses are seasonal --
    heavier through winter -- so 42 weeks of this year against 52 of last is a
    comparison of calendars, not of cattle. On this series the gap between a
    42-week average and the full year runs about 6 lb, which is ~7% of a
    headline head-equivalent: wrong, and far too small to look wrong.
    """
    sub = weekly[weekly["year"] == year].sort_values("week_ending")
    if sub.empty:
        return None
    if weeks is not None:
        sub = sub.head(weeks)
        if len(sub) < weeks:
            return None  # the baseline year is shorter than the window asked for
    out = _roll(sub)
    out["year"] = year
    out["through"] = sub["week_ending"].iloc[-1].date()
    return out


def annual_from_weekly(weekly: pd.DataFrame) -> dict[int, dict]:
    """Complete calendar years only, head-weighted. Part years are dropped."""
    out = {}
    for year, sub in weekly.groupby("year"):
        if len(sub) < FULL_YEAR_WEEKS:
            continue
        out[int(year)] = _roll(sub)
    return out


def annual_history(weekly: pd.DataFrame, frozen: dict[int, dict],
                   live_from: int) -> dict[int, dict]:
    """Frozen years then live years, with the seam asserted rather than assumed.

    One source per year. A year in both would let the chart's shape depend on
    which dict happened to be written second -- the same reason
    `herd.CHANNEL_LEGACY_THROUGH` and the southeast retention build decide an
    owner per barn instead of concatenating and hoping.

    THE CHECK IS ON THE INPUTS, NOT ON THE TWO FILTERED HALVES. Slicing each
    side at `live_from` first and then testing for an intersection is a guard
    that can never fire -- the slices are disjoint by construction, so it would
    sit there looking like protection while the real misconfigurations went
    through: a JSON rebuilt with a different `LIVE_FROM` than the page thinks,
    or the ETL's window widening backwards under a frozen file nobody
    regenerated. Both show up here as a frozen year at or past `live_from`, or
    a complete live year before it, and both are caught.
    """
    live_all = annual_from_weekly(weekly)
    stale = sorted(y for y in frozen if y >= live_from)
    if stale:
        raise ValueError(
            f"frozen history carries {stale}, at or past the live window start "
            f"{live_from}; rebuild with scripts/build_fed_equivalent.py")
    early = sorted(y for y in live_all if y < live_from)
    if early:
        raise ValueError(
            f"live weekly data carries complete year(s) {early} before the "
            f"declared live window {live_from}; the frozen file is out of date")

    old = {y: {"fed_head": float(v["fed_head"]),
               "fed_carcass_lb": float(v["fed_carcass_lb"]),
               "fed_beef_lb": float(v["fed_head"]) * float(v["fed_carcass_lb"]),
               "weeks": None}
           for y, v in frozen.items()}
    return {**old, **live_all}


def head_equivalent(head: float, carcass_lb: float, base_carcass_lb: float) -> float | None:
    """Head the weight gain stands in for. Negative when weights have fallen."""
    if not head or not base_carcass_lb or carcass_lb is None:
        return None
    return head * (carcass_lb / base_carcass_lb - 1.0)


def offset_share(equivalent: float, head_now: float, head_base: float) -> float | None:
    """Share of the lost head the weight gain gives back, in beef.

    HEAD-EQUIVALENTS OVER HEAD LOST, NEVER ONE PERCENTAGE OVER THE OTHER.
    Dividing "+11.4% a head" by "-15.3% head" reads like the same question and
    gives 75% where the answer is 63%, because the two percentages have
    different bases -- one is per head, one is of the kill. Both land in the
    sixties-to-seventies and neither looks wrong.

    This form is exact: multiply numerator and denominator by the baseline
    carcass weight and it is (beef the weight added) / (beef the missing head
    would have carried), in pounds, off one weight.

    NOT CAPPED AT 100%. Over 100 means the weight more than covered the
    shortfall and beef is HIGHER than the baseline on fewer cattle -- which is
    the whole question this tab exists to answer, so clipping it would hide the
    headline result on exactly the years that have one.
    """
    lost = head_base - head_now
    if equivalent is None or lost <= 0:
        return None  # the kill did not shrink; there is nothing to give back
    return equivalent / lost * 100.0


def per_marketed_head(fed_beef_lb: float, marketings: float) -> float | None:
    """Pounds of fed beef per head marketed from 1,000-plus-head feedlots.

    NOT A CARCASS WEIGHT, and it must never be labelled as one. The numerator
    is every federally inspected steer and heifer; the denominator counts only
    feedlots of 1,000 head or more, so cattle fed in smaller lots and imported
    fed cattle are in the beef and not in the marketings. The level therefore
    runs ~150 lb above the fed carcass weight (1,073 against 922 in 2025) and a
    reader who takes it for a carcass weight will think the page contradicts
    the tile beside it. Read it as a ratio over time, which is how it earns its
    place: it rises when each head marketed carries more beef.
    """
    if not marketings or fed_beef_lb is None:
        return None
    return fed_beef_lb / marketings


def turnover(marketings: float, on_feed_jan1: float) -> float | None:
    """Times the feedlot emptied in a year. The explanation, never a denominator.

    Falling turnover and rising carcass weight are one fact seen twice: cattle
    standing longer. The panel prints both so the weight gain is legible as
    days on feed rather than as magic.
    """
    if not on_feed_jan1 or marketings is None:
        return None
    return marketings / on_feed_jan1


def baseline_years(history: dict[int, dict], live_from: int, current: int) -> list[int]:
    """Years offerable as a like-for-like baseline for a part-year headline.

    LIVE WINDOW ONLY. A frozen year has no weekly detail, so it can only be
    compared whole-year to whole-year; setting 42 weeks of this year against a
    full year of 2015 reintroduces exactly the seasonal error `ytd` documents.
    The frozen years are not wasted -- they carry the annual chart, where both
    sides are complete years.
    """
    return sorted(y for y in history if live_from <= y < current)


def compare(weekly: pd.DataFrame, frozen: dict[int, dict], live_from: int,
            baseline: int, marketings: dict[int, float],
            on_feed: dict[int, float], current: int | None = None) -> dict:
    """Everything the tab renders. Returns None-valued keys rather than guesses."""
    history = annual_history(weekly, frozen, live_from)
    years = sorted(weekly["year"].unique()) if not weekly.empty else []
    current = int(current if current is not None else (years[-1] if years else 0))

    now = ytd(weekly, current)
    base_like = ytd(weekly, baseline, weeks=now["weeks"]) if now else None

    equiv = None
    if now and base_like:
        equiv = head_equivalent(now["fed_head"], now["fed_carcass_lb"],
                                base_like["fed_carcass_lb"])

    # The annual series is complete year against complete year, so the frozen
    # history is usable here even though it cannot serve the part-year headline.
    base_annual = history.get(baseline, {}).get("fed_carcass_lb")
    by_year = {}
    for y, v in sorted(history.items()):
        by_year[y] = {
            "fed_head": v["fed_head"],
            "fed_carcass_lb": v["fed_carcass_lb"],
            "equivalent": head_equivalent(v["fed_head"], v["fed_carcass_lb"], base_annual),
            "per_marketed_head": per_marketed_head(v.get("fed_beef_lb"), marketings.get(y)),
            "turnover": turnover(marketings.get(y), on_feed.get(y)),
        }

    return {
        "current": now,
        "baseline": baseline,
        "baseline_like": base_like,
        "baseline_note": BASELINE_NOTES.get(baseline),
        "equivalent": equiv,
        "equivalent_pct": (equiv / now["fed_head"] * 100) if (equiv and now) else None,
        "by_year": by_year,
        "span": (min(by_year), max(by_year)) if by_year else None,
        "live_from": live_from,
    }
