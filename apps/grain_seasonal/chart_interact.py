"""Controls shared by the seasonal charts: Y-axis zoom, and click-a-line-to-bold.

Both are ported from the Cost of Carry spread builder. The zoom is the same quantile clip with
an 8% pad. Click-to-bold is wired differently, because Streamlit refuses to change a widget's
state once the widget exists in the run: a click on the chart reruns the script, and the click
is read at the top of that run, before the Highlight years widget is built, so the year can be
toggled in that widget's own state. (Cost of Carry sets it after the widget is built.)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

# Y-axis "central %" zoom: clip to the middle 90/80/70% of the values so one outlier year
# doesn't flatten the rest of the chart.
Y_SCALE_CHOICES = ["Full", "90%", "80%", "70%"]
Y_SCALE_TAILS = {"90%": 0.05, "80%": 0.10, "70%": 0.15}
Y_SCALE_PAD_FRAC = 0.08
MIN_YFIT_POINTS = 8


def yfit_range(values, level: str) -> list[float] | None:
    """[lo, hi] to clip a Y-axis to the central `level` (e.g. "90%") of `values`, padded 8%
    each side. None for "Full" or too few points: the caller leaves the axis on auto."""
    tail = Y_SCALE_TAILS.get(level)
    if tail is None:
        return None
    vals = [v for v in values if v is not None and pd.notna(v)]
    if len(vals) < MIN_YFIT_POINTS:
        return None
    s = pd.Series(vals, dtype=float)
    lo, hi = float(s.quantile(tail)), float(s.quantile(1 - tail))
    if hi <= lo:
        return None
    pad = (hi - lo) * Y_SCALE_PAD_FRAC
    return [lo - pad, hi + pad]


def _years_key(chart_key: str) -> str:
    return f"{chart_key}__trace_years"


def remember_traces(chart_key: str, trace_years: list[int | None]) -> None:
    """Record which year each trace of the chart just drawn stands for (None for an average,
    a band or any other line), so the next run can tell which line a click landed on."""
    st.session_state[_years_key(chart_key)] = list(trace_years)


def apply_chart_click(chart_key: str, highlight_key: str) -> None:
    """Turn a click on a line of the chart drawn last run into a toggle of that year in the
    Highlight years widget (`highlight_key`). Call it BEFORE that widget is created.

    The chart is drawn with on_select="rerun", and its selection survives later reruns, so the
    click is fingerprinted and acted on only when it changes. A click on the very point that is
    already selected clears the selection; that resets the fingerprint, so the next click there
    counts again."""
    selection = (st.session_state.get(chart_key) or {}).get("selection") or {}
    points = selection.get("points") or []
    seen = f"{chart_key}__lastclick"
    if not points:
        st.session_state.pop(seen, None)
        return
    trace_years = st.session_state.get(_years_key(chart_key)) or []
    # Under a unified hover a click can return one point per line; prefer one that maps to a
    # year and ignore the rest.
    point = next((pt for pt in points
                  if isinstance(pt.get("curve_number"), int)
                  and pt["curve_number"] < len(trace_years)
                  and trace_years[pt["curve_number"]] is not None), points[0])
    fingerprint = str((point.get("curve_number"), point.get("point_index"),
                       point.get("point_number"), point.get("x")))
    if st.session_state.get(seen) == fingerprint:
        return
    st.session_state[seen] = fingerprint

    curve = point.get("curve_number")
    year = trace_years[curve] if isinstance(curve, int) and curve < len(trace_years) else None
    if year is None:
        return  # an average, band or pattern line: nothing to bold
    picked = list(st.session_state.get(highlight_key) or [])
    st.session_state[highlight_key] = (
        [y for y in picked if y != year] if year in picked else picked + [year]
    )
