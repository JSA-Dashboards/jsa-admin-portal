"""Moore Research-style seasonal pattern for a spread.

A pattern answers "where in its range does this spread usually sit at this point in the
season?", independent of how wide or where that range was in any one year:

1. Each prior year's spread is put on a daily grid of days-to-near-expiration.
2. Within the window, each year is rescaled to 0-100 (its own low = 0, high = 100), so
   a 30-cent year and a 5-cent year count equally.
3. The yearly indexes are averaged at each day (only where most years have data), and
   the average is rescaled to 0-100 again.

The current year is excluded — the pattern is built only from completed prior years
(Moore's "15 Year Seasonal (11-25)" for a Nov '26 spread uses 2011-2025).

To draw the pattern over the live market it's mapped onto price with a least-squares
fit of the current year's observed spread against the pattern index (price = a + b x
index). The fit is only used when the current market tracks the pattern (b > 0);
otherwise the index is stretched across the current year's own low-high range.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_FIT_POINTS = 10


def year_grid(by_dte: dict[str, pd.Series], window_days: int) -> pd.DataFrame:
    """Every year on one daily grid of days to expiration (-window_days..0), filling
    only gaps between sessions (not before the first or after the last)."""
    grid = pd.RangeIndex(-window_days, 1, name="dte")
    aligned = {}
    for name, s in by_dte.items():
        clean = s[~s.index.duplicated(keep="last")].sort_index()
        clean = clean[(clean.index >= -window_days) & (clean.index <= 0)]
        if len(clean) < 2:
            continue
        aligned[name] = clean.reindex(clean.index.union(grid)).interpolate(
            limit_area="inside").reindex(grid)
    return pd.DataFrame(aligned, index=grid)


def _to_index(values: pd.Series) -> pd.Series:
    lo, hi = values.min(), values.max()
    if pd.isna(lo) or hi == lo:
        return values * np.nan
    return (values - lo) / (hi - lo) * 100


def pattern(by_dte: dict[str, pd.Series], window_days: int) -> pd.Series:
    """0-100 seasonal pattern indexed by days to expiration. Empty if < 2 usable years."""
    frame = year_grid(by_dte, window_days)
    if frame.shape[1] < 2:
        return pd.Series(dtype=float)
    indexed = frame.apply(_to_index)
    required = max(2, (indexed.shape[1] + 1) // 2)
    avg = indexed.mean(axis=1, skipna=True)[indexed.count(axis=1) >= required]
    if len(avg) < 2:
        return pd.Series(dtype=float)
    return _to_index(avg)


def scale_to_market(pattern_index: pd.Series, current: pd.Series) -> tuple[pd.Series, str]:
    """Pattern (0-100) expressed in the current market's units, plus how it was scaled."""
    if not len(pattern_index) or current is None or not len(current):
        return pd.Series(dtype=float), "none"
    clean = current[~current.index.duplicated(keep="last")]
    overlap = pd.concat({"idx": pattern_index, "px": clean}, axis=1).dropna()
    if len(overlap) >= MIN_FIT_POINTS and overlap["idx"].std() > 0:
        slope, intercept = np.polyfit(overlap["idx"], overlap["px"], 1)
        if slope > 0:
            return intercept + slope * pattern_index, "fit"
    lo, hi = clean.min(), clean.max()
    if hi == lo:
        return pd.Series(dtype=float), "none"
    return lo + pattern_index / 100 * (hi - lo), "range"


def year_span_label(years: list[int]) -> str:
    """[2011, ..., 2025] -> '11-25', as Moore labels its patterns."""
    if not years:
        return ""
    return f"{min(years) % 100:02d}-{max(years) % 100:02d}"
