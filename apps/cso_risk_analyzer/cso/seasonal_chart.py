"""The seasonal overlay chart: this contract's spread against the same pair in earlier years, on one calendar.

Every earlier year is shifted so its near leg's last trading day lands on the live contract's, which puts the same
point of the season in the same place on the x-axis. The strategy's own levels (strike, break-evens, entry, full
carry) run across it, so it shows at a glance where earlier years traded relative to them. When the strategy has a
position to protect, its zones are shaded behind the lines (Protected, Downside gained ...) and an arrow marks where an
additional move stops paying; the strike lines then become the bands' unlabelled edges, and the break-even and entry
levels are left to the payoff chart, because their labels would pile up on the zone labels at the left edge.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import altair as alt
import pandas as pd

from . import strategy
from .payoff_chart import BLUE, CARRY, INK, MUTED, ORANGE

PRIOR_COLORS = ["#08519c", "#3182bd", "#6baed6", "#8fb8d9", "#aec7dc"]      # most recent year darkest
CURRENT, AVERAGE = "Current", "Average"
ZONE_FILL = {strategy.PROTECTED: "#f2c744", strategy.GAINED: "#f2c744", strategy.PARTIAL: "#f4b183"}
ZONE_INK = "#6b5300"


def _long(series: pd.Series, name: str) -> pd.DataFrame:
    return pd.DataFrame({"Date": pd.to_datetime(list(series.index)), "Spread": series.values.astype(float), "Series": name})


def _hmarks(values, labels, color, dash, y_scale, below=False):
    """Horizontal rules with the label at the left edge, just above the line (or just below it); the rule alone when
    ``labels`` is None."""
    df = pd.DataFrame({"y": list(values), "label": [""] * len(list(values)) if labels is None else list(labels)})
    rule = alt.Chart(df).mark_rule(color=color, strokeWidth=1.4, strokeDash=dash).encode(y=alt.Y("y:Q", scale=y_scale))
    if labels is None:
        return [rule]
    text = alt.Chart(df).mark_text(align="left", baseline="top" if below else "bottom", dx=4, dy=3 if below else -3,
                                   fontSize=11, color=color).encode(x=alt.value(4), y=alt.Y("y:Q", scale=y_scale), text="label:N")
    return [rule, text]


def _vmarks(days, labels, color, dash, x_scale, dy=2, left_of_line=False):
    """Vertical rules with the label at the top, to the right of the line (or to its left)."""
    df = pd.DataFrame({"x": pd.to_datetime(list(days)), "label": list(labels)})
    rule = alt.Chart(df).mark_rule(color=color, strokeWidth=1.4, strokeDash=dash).encode(x=alt.X("x:T", scale=x_scale))
    text = alt.Chart(df).mark_text(align="right" if left_of_line else "left", baseline="top", dx=-4 if left_of_line else 4,
                                   dy=dy, fontSize=11, color=color).encode(
        x=alt.X("x:T", scale=x_scale), y=alt.value(0), text="label:N")
    return [rule, text]


def _shaded(zone_list, y_lo, y_hi):
    """The zones that get a band: those that protect or keep a gain, and are on the chart (a zone that runs off the
    chart is clipped to it). Each comes back as (low edge, high edge, zone)."""
    return [(max(z.lo, y_lo), min(z.hi, y_hi), z) for z in zone_list
            if z.kind in ZONE_FILL and min(z.hi, y_hi) > max(z.lo, y_lo)]


def _zone_layers(zone_list, y_scale, x_scale, start, end, y_lo, y_hi):
    """Bands across the whole chart, labelled at the left, for the zones that protect or keep a gain; and an arrow note
    where an additional move stops paying."""
    bands, below, above = [], [], []
    for a, b, z in _shaded(zone_list, y_lo, y_hi):
        bands.append({"x0": pd.Timestamp(start), "x1": pd.Timestamp(end), "y0": a, "y1": b, "mid": (a + b) / 2,
                      "label": z.label, "fill": ZONE_FILL[z.kind]})
    for z in zone_list:
        if z.kind in ZONE_FILL or min(z.hi, y_hi) <= max(z.lo, y_lo):
            continue
        if z.kind == strategy.CAPPED and z.lo == -math.inf and y_lo < z.hi < y_hi:
            below.append({"y": z.hi, "label": f"↓ {z.label}"})
        elif z.kind == strategy.CAPPED and z.hi == math.inf and y_lo < z.lo < y_hi:
            above.append({"y": z.lo, "label": f"↑ {z.label}"})
    layers = []
    if bands:
        df = pd.DataFrame(bands)
        layers.append(alt.Chart(df).mark_rect(opacity=0.30).encode(
            x=alt.X("x0:T", scale=x_scale), x2="x1:T", y=alt.Y("y0:Q", scale=y_scale), y2="y1:Q",
            color=alt.Color("fill:N", scale=None, legend=None)))
        layers.append(alt.Chart(df).mark_text(align="left", baseline="middle", dx=10, fontSize=15, fontWeight="bold",
                                              color=ZONE_INK).encode(x=alt.value(0), y=alt.Y("mid:Q", scale=y_scale), text="label:N"))
    for rows, baseline, dy in ((below, "top", 6), (above, "bottom", -6)):
        if rows:
            layers.append(alt.Chart(pd.DataFrame(rows)).mark_text(
                align="left", baseline=baseline, dx=10, dy=dy, fontSize=13, fontWeight="bold", color=INK).encode(
                x=alt.value(0), y=alt.Y("y:Q", scale=y_scale), text="label:N"))
    return layers


def seasonal_chart(current: pd.Series | None, priors: dict, average: pd.Series | None, *,
                   near_expiry: date, window: int, today: date, option_expiry: date | None = None,
                   strike: float | list[float] | None = None, breakevens=(), entry: float | None = None,
                   carry_limit: float | None = None, y_title: str = "Spread level (near − far, points)",
                   height: int = 420, zones=None, title: str | None = None, current_label: str = CURRENT):
    """Layered Altair chart. ``priors`` maps a series name (a year, or the pair's name that year) to its spread on the
    live contract's calendar dates, most recent year first; ``current`` is the live contract and ``average`` the mean
    across the years, both on calendar dates too. ``zones`` are shaded behind the lines. Returns None when there is
    nothing to draw."""
    frames, style = [], {}                  # drawn in this order, so the live contract ends up on top
    for rank, (year, s) in enumerate(priors.items()):
        if len(s):
            frames.append(_long(s, str(year)))
            style[str(year)] = (PRIOR_COLORS[min(rank, len(PRIOR_COLORS) - 1)], 1.8, [1, 0])
    if average is not None and len(average):
        frames.append(_long(average, AVERAGE))
        style[AVERAGE] = (MUTED, 2.4, [2, 3])
    if current is not None and len(current):
        frames.append(_long(current, current_label))
        style[current_label] = (INK, 3.2, [1, 0])
    if not frames:
        return None
    lines = pd.concat(frames, ignore_index=True)
    # the legend reads: the live contract, the years newest first, then the average
    names = [n for n in (current_label, *[str(y) for y in priors], AVERAGE) if n in style]
    colors, widths, dashes = ([style[n][i] for n in names] for i in range(3))

    strikes = [] if strike is None else ([float(strike)] if isinstance(strike, (int, float)) else [float(k) for k in strike])
    levels = [v for v in (*strikes, entry, *breakevens) if v is not None]
    levels += [v for z in (zones or []) for v in (z.lo, z.hi) if math.isfinite(v)]      # the bands' edges stay on the chart
    data_lo, data_hi = float(lines["Spread"].min()), float(lines["Spread"].max())
    if carry_limit is not None and data_lo - 1.5 * (data_hi - data_lo) <= carry_limit <= data_hi + 1.5 * (data_hi - data_lo):
        levels.append(carry_limit)                       # a far-off full carry would only flatten the chart
    lo, hi = min([data_lo, *levels]), max([data_hi, *levels])
    pad = max((hi - lo) * 0.06, 0.5)
    y_scale = alt.Scale(domain=[lo - pad, hi + pad], nice=False)
    x_scale = alt.Scale(domain=[pd.Timestamp(near_expiry - timedelta(days=window)), pd.Timestamp(near_expiry)], nice=False)
    x = alt.X("Date:T", scale=x_scale, axis=alt.Axis(format="%b", tickCount="month", title=None))

    start, end = near_expiry - timedelta(days=window), near_expiry
    layers = _zone_layers(zones or [], y_scale, x_scale, start, end, lo - pad, hi + pad)       # behind everything else
    shaded = bool(_shaded(zones or [], lo - pad, hi + pad))      # then the band labels carry the story: keep the rest quiet
    layers += [alt.Chart(lines).mark_line().encode(
        x=x, y=alt.Y("Spread:Q", scale=y_scale, axis=alt.Axis(title=y_title, format=".1f")),
        color=alt.Color("Series:N", scale=alt.Scale(domain=names, range=colors), legend=alt.Legend(title=None, orient="top")),
        strokeWidth=alt.StrokeWidth("Series:N", scale=alt.Scale(domain=names, range=widths), legend=None),
        strokeDash=alt.StrokeDash("Series:N", scale=alt.Scale(domain=names, range=dashes), legend=None),
        tooltip=[alt.Tooltip("Series:N"), alt.Tooltip("Date:T", format="%b %d"), alt.Tooltip("Spread:Q", format=".2f")])]

    if strikes:
        layers += _hmarks(strikes, None if shaded else [f"strike {k:+g}" for k in strikes], ORANGE, [5, 4], y_scale)
    if len(breakevens) and not shaded:
        layers += _hmarks(list(breakevens), [f"break-even {b:+.2f}" for b in breakevens], MUTED, [2, 3], y_scale)
    if entry is not None and not shaded:
        layers += _hmarks([entry], [f"entry {entry:+.2f}"], BLUE, [1, 0], y_scale, below=True)
    if carry_limit is not None and carry_limit in levels:
        layers += _hmarks([carry_limit], ["full carry"], CARRY, [2, 2], y_scale)

    if pd.Timestamp(near_expiry - timedelta(days=window)) <= pd.Timestamp(today) <= pd.Timestamp(near_expiry):
        layers += _vmarks([today], ["today"], BLUE, [1, 0], x_scale)
    if option_expiry is not None and pd.Timestamp(near_expiry - timedelta(days=window)) <= pd.Timestamp(option_expiry) <= pd.Timestamp(near_expiry):
        layers += _vmarks([option_expiry], ["option expiry"], ORANGE, [5, 4], x_scale, dy=16, left_of_line=True)
    chart = alt.layer(*layers).properties(height=height)
    if title:
        chart = chart.properties(title=alt.TitleParams(title, anchor="middle", fontSize=15, color=INK))
    return chart
