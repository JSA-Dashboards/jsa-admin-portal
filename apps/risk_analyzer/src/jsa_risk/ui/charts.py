"""Scenario charts — P&L heatmap, delta-scenario strip, payoff chart, and per-contract
Greeks bars. Ported from the JSA Risk Analyzer HTML tool's hand-rolled SVG/DOM renderers,
using plotly instead — a practical substitution (like Phase 1's scipy-for-erf swap), not
a pixel-for-pixel port. The underlying numbers (portfolio_pnl_at/portfolio_delta_at) are
unchanged from the original tool.
"""
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

import plotly.graph_objects as go
import streamlit as st

from jsa_risk.pricing.commodities import CORN, CommoditySpec
from jsa_risk.pricing.portfolio import book_totals, portfolio_delta_at, portfolio_pnl_at, portfolio_reference_price
from jsa_risk.pricing.stress import Position, PositionEval, StressState, eval_position

# Price shocks are a percent of the book's reference price (see portfolio_reference_price),
# applied as one parallel cents-per-unit move to every contract -- so the same grid works for
# corn, soybeans, and cattle alike, and a delta-neutral book stays flat.
#
# The window (half-range %, step %) is user-selectable because what counts as a realistic
# stress differs a lot by product: 1% of live cattle is ~2.4¢/lb, so +/-25% (~60¢) is far
# more dramatic there than it is for corn.
SHOCK_WINDOWS = {
    "±2.5% · 0.25% steps": (2.5, 0.25),
    "±5% · 1% steps": (5, 1),
    "±10% · 2% steps": (10, 2),
    "±25% · 5% steps": (25, 5),
}
DEFAULT_SHOCK_WINDOW = "±10% · 2% steps"


def _steps(half_range: float, step: float) -> List[float]:
    """-half_range..+half_range in `step` increments (fractional steps like 0.25 included),
    built from integer multiples so 0.25 steps don't accumulate float error and 0 is exact."""
    n = round(half_range / step)
    return [round(i * step, 6) for i in range(-n, n + 1)]


# Cattle is quoted and traded in fractions of a cent, so its shocks are laddered in cents
# per pound rather than as a percent window: (half-range ¢, step ¢). Both contracts qualify:
# live cattle and feeder cattle are both $/lb, and a feeder book was on the percent ladder
# until 2026-10 for no reason anyone recorded -- it reads as an oversight from when cattle
# support landed one contract at a time, not a decision. The charts still carry
# them internally as a percent of the book's reference price (cents / price), so the pricing
# code is unchanged; only the grid and the labels are in cents.
#
# Selectable for the same reason the percent windows are: ±5¢ is the right default for a book
# sitting near the money, but a leg struck 10¢ out shows no shape at all inside it -- the
# payoff chart draws a flat expiry line because the window stops short of the strike.
CENTS_SHOCK_WINDOWS = {
    "±2¢ · 0.25¢ steps": (2.0, 0.25),
    "±5¢ · 0.5¢ steps": (5.0, 0.5),
    "±10¢ · 1¢ steps": (10.0, 1.0),
    "±20¢ · 2¢ steps": (20.0, 2.0),
}
DEFAULT_CENTS_SHOCK_WINDOW = "±5¢ · 0.5¢ steps"
# Per-contract default, because the same cents ladder is not the same window. A nickel on a
# ~$2.28 live steer is 2.2%; on a ~$3.40 feeder it is 1.5%, and feeders carry the higher
# daily vol of the two (see CommoditySpec.daily_vol). So a feeder book opens one preset
# wider -- same ladder, same labels, just a default that covers a comparable day's range.
# Anything not named here falls back to DEFAULT_CENTS_SHOCK_WINDOW.
DEFAULT_CENTS_WINDOW_BY_CODE = {"GF": "±10¢ · 1¢ steps"}
CENTS_SHOCK_COMMODITIES = {"LE", "GF"}


def shocks_in_cents(commodity: CommoditySpec) -> bool:
    return commodity.code in CENTS_SHOCK_COMMODITIES


def shock_windows_for(commodity: Optional[CommoditySpec]) -> dict:
    """The window presets to offer for a commodity -- cents for cattle, percent for the
    rest. Keyed by the same label the user picks, so `shock_grid` can look one up directly."""
    if commodity is not None and shocks_in_cents(commodity):
        return CENTS_SHOCK_WINDOWS
    return SHOCK_WINDOWS


def default_shock_window(commodity: Optional[CommoditySpec]) -> str:
    if commodity is not None and shocks_in_cents(commodity):
        return DEFAULT_CENTS_WINDOW_BY_CODE.get(commodity.code, DEFAULT_CENTS_SHOCK_WINDOW)
    return DEFAULT_SHOCK_WINDOW


def cents_window(commodity: CommoditySpec, window: str) -> tuple:
    """(half-range ¢, step ¢) for a cents-shock commodity's selected window."""
    return CENTS_SHOCK_WINDOWS.get(window, CENTS_SHOCK_WINDOWS[DEFAULT_CENTS_SHOCK_WINDOW])


def shock_grid(
    window: str = DEFAULT_SHOCK_WINDOW, commodity: Optional[CommoditySpec] = None,
    ref_price: Optional[float] = None,
) -> Tuple[float, float, List[float]]:
    """(half-range %, step %, shocks in %) for a named window, e.g. (10, 2, [-10.0, ..., 10.0]).
    For a cents-shock commodity (either cattle) `window` names a CENTS_SHOCK_WINDOWS preset and
    the grid is that cents ladder expressed as a percent of `ref_price`."""
    if commodity is not None and shocks_in_cents(commodity):
        half_c, step_c = cents_window(commodity, window)
        rp = ref_price or commodity.default_price
        return half_c / rp, step_c / rp, [c / rp for c in _steps(half_c, step_c)]
    half_range, step = SHOCK_WINDOWS.get(window, SHOCK_WINDOWS[DEFAULT_SHOCK_WINDOW])
    return half_range, step, _steps(half_range, step)


VOL_SHOCKS_BOTTOM_UP = [-30, -15, 0, 15, 30]  # last item renders at the top of the heatmap
ACCENT = "#3987e5"
MUTED = "#898781"
GAIN = "#3a9d5d"
LOSS = "#c0392b"
# One solid color per distinct expiry line on the payoff chart -- avoids red/green (already
# meaning loss/gain everywhere else) and blue (Today), cycles if there are more expiries.
EXPIRY_COLORS = ["#e8a33d", "#9b6bce", "#4fb8af", "#d9779a", "#c9a227", "#6a8caf"]


def _fmt_cents(v: float, commodity: Optional[CommoditySpec] = None) -> str:
    """`v` is a price move in the commodity's own unit ($ per bu/lb/ton); shown as cents for a
    cents-quoted product, with a decimal under 10¢ so small moves (e.g. 5% of a cheap
    contract) don't all round to the same label. A dollars-quoted product (soybean meal) shows
    the move in dollars per unit instead."""
    sign = "-" if v < 0 else ("+" if v > 0 else "")
    if commodity is not None and commodity.price_divisor != 100:
        return f"{sign}${abs(v):.2f}"
    cents = abs(v) * 100
    body = f"{cents:.1f}" if 0 < cents < 10 else f"{cents:.0f}"
    return f"{sign}{body}¢"


def _fmt_pct_signed(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:g}%"


def _shock_cents(pct: float, ref_price: float) -> float:
    return pct / 100 * ref_price


def _shock_tick(pct: float, ref_price: float, commodity: Optional[CommoditySpec] = None) -> str:
    """Two-line axis tick: % over its cents equivalent -- or, for a cents-shock commodity,
    the cents move over the % it works out to."""
    cents = _fmt_cents(_shock_cents(pct, ref_price), commodity)
    if commodity is not None and shocks_in_cents(commodity):
        return f"{cents}<br>{_fmt_pct_signed(round(pct, 2))}"
    return f"{_fmt_pct_signed(pct)}<br>{cents}"


def _shock_hover(pct: float, ref_price: float, commodity: Optional[CommoditySpec] = None) -> str:
    cents = _fmt_cents(_shock_cents(pct, ref_price), commodity)
    if commodity is not None and shocks_in_cents(commodity):
        return f"{cents} ({_fmt_pct_signed(round(pct, 2))})"
    return f"{_fmt_pct_signed(pct)} ({cents})"


def _shock_axis_title(ref_price: float, commodity: CommoditySpec) -> str:
    if shocks_in_cents(commodity):
        return f"Price shock (¢/{commodity.unit}, same move on every contract · % of ${ref_price:.2f} avg beneath) →"
    return f"Price shock (% of avg price · ≈{commodity.move_symbol}/{commodity.unit} at ${ref_price:.2f}, all contracts) →"


def _fmt_dollars_signed(v: float) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}${abs(v):,.0f}"


def _money_md(v: float) -> str:
    r"""`_fmt_dollars_signed` with the dollar sign escaped for markdown.

    Streamlit renders `$...$` as inline LaTeX, so a caption quoting TWO dollar amounts
    opens a maths span: both signs vanish and everything between them is italicised. One
    `$` in a block is safe, which is why the axis captions get away with it -- it takes a
    pair. Caught in a browser, not by a test: the page text reads correctly either way.
    """
    return _fmt_dollars_signed(v).replace("$", r"\$")


def _fmt_unit_signed(v: float, unit: str) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}{abs(v):,.0f} {unit}"


def render_pnl_heatmap(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
    shock_window: str = DEFAULT_SHOCK_WINDOW,
    centre_on_today: bool = False,
) -> None:
    """`centre_on_today` re-centres the grid on the current scenario: every cell becomes the
    CHANGE from where the book stands, so the outlined cell reads 0 and a cell answers "what
    does this move do to me from here" directly rather than by subtracting two cells.

    Two things fall out, and they are the point of offering it. The vol axis becomes legible
    -- vol is worth a few thousand dollars where cumulative P&L is worth hundreds of
    thousands, so it is swamped on the uncentred grid. And the gap between a tick-marked book
    and a model-priced one cancels exactly -- it is the same constant in every cell -- so a
    re-centred grid reads the same on either basis, and the tick/model question that the
    uncentred grid's caption has to explain simply does not arise here.
    """
    ref_price = portfolio_reference_price(positions, get_contract_price, stress, today, commodity)
    _, _, price_shocks = shock_grid(shock_window, commodity, ref_price)
    # Purely numeric x/y (0,1,2,...) with cosmetic tick labels via update_xaxes/yaxes,
    # rather than handing the Heatmap trace the label strings directly. Plotly's implicit
    # category-axis positioning turned out unreliable for a second overlaid trace: both a
    # go.Shape rect and a numeric-coordinate scatter line, tried in turn to outline the
    # current-scenario cell, landed off-axis (Plotly silently extended the axis with new
    # tick positions instead of aligning to the heatmap's categories). Numeric coordinates
    # end that ambiguity -- the heatmap and the highlight now share one unambiguous grid.
    price_ticks = [_shock_tick(p, ref_price, commodity) for p in price_shocks]
    price_hover = [_shock_hover(p, ref_price, commodity) for p in price_shocks]
    vol_labels = [_fmt_pct_signed(v) for v in VOL_SHOCKS_BOTTOM_UP]
    x_idx = list(range(len(price_shocks)))
    y_idx = list(range(len(VOL_SHOCKS_BOTTOM_UP)))
    # Every cell is the blotter's own mark plus the model's change for that shock (see
    # portfolio_pnl_at), so the current-scenario cell IS the blotter's P&L. The blotter totals
    # each position rounded to the dollar; the cell takes that exact total so the two agree
    # to the dollar rather than to within rounding.
    raw = [
        [portfolio_pnl_at(positions, get_contract_price, stress, ps, vs, 0, today, commodity, ref_price)
         for ps in price_shocks]
        for vs in VOL_SHOCKS_BOTTOM_UP
    ]
    base_price_idx = price_shocks.index(0.0)
    base_vol_idx = VOL_SHOCKS_BOTTOM_UP.index(0)
    blotter = book_totals(
        eval_position(p, stress, get_contract_price, today=today, commodity=commodity) for p in positions
    )[1]
    centre = raw[base_vol_idx][base_price_idx]
    if abs(centre - blotter) <= len(positions):      # only rounding apart; anything wider is left visible
        raw[base_vol_idx][base_price_idx] = centre = float(blotter)
    z = [[v - centre for v in row] for row in raw] if centre_on_today else raw
    max_abs = max(1.0, max(abs(v) for row in z for v in row))
    text = [[_fmt_dollars_signed(v) for v in row] for row in z]
    customdata = [[[price_hover[j], vol_labels[i]] for j in x_idx] for i in y_idx]

    fig = go.Figure(
        go.Heatmap(
            x=x_idx,
            y=y_idx,
            z=z,
            colorscale="RdYlGn",
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 11},
            customdata=customdata,
            hovertemplate="Price %{customdata[0]} · Vol %{customdata[1]}<br>Book P&L: %{text}<extra></extra>",
            showscale=False,
        )
    )
    # Outline the current-scenario (0 price, 0 vol) cell -- a closed line path at
    # +/-0.5 index either side of its center, tracing exactly the cell's own boundary.
    px0, px1 = base_price_idx - 0.5, base_price_idx + 0.5
    py0, py1 = base_vol_idx - 0.5, base_vol_idx + 0.5
    fig.add_trace(
        go.Scatter(
            x=[px0, px1, px1, px0, px0],
            y=[py0, py0, py1, py1, py0],
            mode="lines",
            line=dict(color=ACCENT, width=3),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=340,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(title=_shock_axis_title(ref_price, commodity), tickvals=x_idx, ticktext=price_ticks,
                   automargin=True),
        yaxis=dict(title="Vol shock ↑", tickvals=y_idx, ticktext=vol_labels, automargin=True),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True)
    _caption_basis(centre, positions, stress, get_contract_price, today, commodity,
                   centre_on_today)



def _caption_basis(
    centre: float,
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    today: Optional[date],
    commodity: CommoditySpec,
    centred: bool = False,
) -> None:
    """Name the basis, and reconcile the uncentred grid against the blotter.

    The grid is Black-76 throughout; the blotter at zero stress prefers an imported
    `last_tick`. So the uncentred grid's zero cell and the P&L column above it are two
    valuations of one book, and they can be far apart -- on a live cattle book, -$52,320
    against -$200,500. Both are defensible, which is why the disagreement is printed rather
    than left for someone to meet on their own.

    The centred grid needs none of this: the difference is the same constant in every cell
    and vanishes in the subtraction, so that view is identical on either basis.
    """
    zero = "0¢" if shocks_in_cents(commodity) else "0%"
    if centred:
        st.caption(
            f"Every cell is the CHANGE from where the book stands now, so the outlined "
            f"{zero} / 0% cell reads zero. Read a cell as what that move is worth to you from "
            "here. This view is unaffected by whether a leg is marked to a traded price or to "
            "the model — that difference is the same in every cell and cancels out."
        )
        return
    st.caption(
        f"The outlined {zero} / 0% cell is the book's P&L against your entry prices — the same "
        "total as the position blotter, marks and all. Every other cell adds what the model "
        "(Black-76 with American early exercise) says that move is worth on top of it."
    )


def render_delta_scenario(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
    shock_window: str = DEFAULT_SHOCK_WINDOW,
) -> None:
    unit = commodity.unit
    ref_price = portfolio_reference_price(positions, get_contract_price, stress, today, commodity)
    _, _, price_shocks = shock_grid(shock_window, commodity, ref_price)
    price_ticks = [_shock_tick(p, ref_price, commodity) for p in price_shocks]
    price_hover = [_shock_hover(p, ref_price, commodity) for p in price_shocks]
    x_idx = list(range(len(price_shocks)))
    row = [portfolio_delta_at(positions, get_contract_price, stress, ps, today, commodity, ref_price) for ps in price_shocks]
    max_abs = max(1.0, max(abs(v) for v in row))
    base = row[price_shocks.index(0.0)]
    text = [[f"{v:,.0f}" for v in row]]

    fig = go.Figure(
        go.Heatmap(
            x=x_idx,
            y=[f"Net delta ({unit})"],
            z=[row],
            colorscale="RdYlGn",
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 11},
            customdata=[price_hover],
            hovertemplate=f"Price %{{customdata}}<br>Net delta: %{{text}} {unit}<extra></extra>",
            showscale=False,
        )
    )
    fig.update_layout(
        height=150,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(title=_shock_axis_title(ref_price, commodity), tickvals=x_idx, ticktext=price_ticks,
                   automargin=True),
        yaxis=dict(automargin=True),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True)

    lo, hi = row[0], row[-1]
    st.caption(
        f"Cell = net position delta ({unit}) under that price shock, sign colored long (green) vs short (red). "
        f"At {_shock_hover(price_shocks[0], ref_price, commodity)}: {lo:,.0f} {unit} (Δ {lo - base:+,.0f} {unit}) · "
        f"At {_shock_hover(price_shocks[-1], ref_price, commodity)}: {hi:,.0f} {unit} (Δ {hi - base:+,.0f} {unit}) "
        f"vs current {base:,.0f} {unit}."
    )


def render_payoff_chart(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
    shock_window: str = DEFAULT_SHOCK_WINDOW,
) -> None:
    # Compute well past the default view so zooming/panning out reveals a real, continuing
    # curve instead of hitting blank space at the edge of what used to be the only data.
    ref_price = portfolio_reference_price(positions, get_contract_price, stress, today, commodity)
    default_view, step, _ = shock_grid(shock_window, commodity, ref_price)
    compute_range = default_view * 3
    xs = _steps(compute_range, step)  # % of the average price
    # Tick at every step inside the default window, then only at multiples of the window
    # beyond it, so a zoomed-out view doesn't turn the axis into a wall of two-line labels.
    tick_vals = [x for x in xs
                 if abs(x) <= default_view + 1e-6 or abs(x / default_view - round(x / default_view)) < 1e-9]
    tick_text = [_shock_tick(x, ref_price, commodity) for x in tick_vals]

    # One expiry date per distinct expiration among current option positions -- not just
    # the nearest -- so a book with staggered expiries shows every real decay cliff.
    expiry_dates = sorted({p.expiry_date for p in positions if p.expiry_date is not None})
    today_ = today or date.today()
    expiry_dtes = [(d, (d - today_).days) for d in expiry_dates]
    expiry_dtes = [(d, dte) for d, dte in expiry_dtes if dte > 0]

    horizons = [
        {"label": "Today", "days": 0, "dash": None, "width": 2.5, "opacity": 1.0, "color": ACCENT},
    ]
    for i, (expiry_date, dte) in enumerate(expiry_dtes):
        horizons.append({
            "label": f"{expiry_date.strftime('%b')} {expiry_date.day} ({dte}d)",
            "days": dte,
            "dash": None,
            "width": 2.0,
            "opacity": 1.0,
            "color": EXPIRY_COLORS[i % len(EXPIRY_COLORS)],
        })
    for h in horizons:
        h["ys"] = [portfolio_pnl_at(positions, get_contract_price, stress, s, 0, h["days"], today, commodity, ref_price) for s in xs]

    cur_val = portfolio_pnl_at(positions, get_contract_price, stress, 0, 0, 0, today, commodity, ref_price)

    # Fit the initial Y-range to just the default-visible window's values, not the whole
    # (much wider) computed dataset -- otherwise the visible curve gets squashed into a
    # sliver by extremes that only occur far outside the default zoom.
    visible_ys = [
        y for h in horizons for x, y in zip(xs, h["ys"]) if abs(x) <= default_view + 1e-6
    ]
    y_lo, y_hi = min(visible_ys), max(visible_ys)
    y_pad = max((y_hi - y_lo) * 0.1, 1.0)

    fig = go.Figure()
    today_h = horizons[0]
    fig.add_trace(
        go.Scatter(
            x=xs, y=today_h["ys"], mode="lines", name=today_h["label"],
            line=dict(width=today_h["width"], color=today_h["color"]),
            fill="tozeroy", fillcolor="rgba(57,135,229,0.12)",
            customdata=[_shock_hover(x, ref_price, commodity) for x in xs],
            hovertemplate="%{y:$,.0f} · shock %{customdata}<extra>" + today_h["label"] + "</extra>",
        )
    )
    for h in horizons[1:]:
        fig.add_trace(
            go.Scatter(
                x=xs, y=h["ys"], mode="lines", name=h["label"],
                line=dict(width=h["width"], color=h["color"], dash=h["dash"]),
                opacity=h["opacity"],
                hovertemplate="%{y:$,.0f}<extra>" + h["label"] + "</extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[0], y=[cur_val], mode="markers", name="Current",
            marker=dict(size=9, color=ACCENT, line=dict(color="white", width=1)),
            showlegend=False,
        )
    )
    fig.add_vline(x=0, line_dash="dot", line_color=MUTED)
    fig.update_layout(
        hovermode="x unified",
        xaxis=dict(
            title=_shock_axis_title(ref_price, commodity),
            range=[-default_view - 1e-6, default_view + 1e-6],
            tickvals=tick_vals, ticktext=tick_text,
            ticksuffix="" if shocks_in_cents(commodity) else "%", automargin=True,
        ),
        yaxis_title="Book P&L ($)",
        yaxis=dict(tickprefix="$", separatethousands=True, range=[y_lo - y_pad, y_hi + y_pad]),
        height=520,
        margin=dict(l=10, r=30, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    if shocks_in_cents(commodity):
        half_c = cents_window(commodity, shock_window)[0]
        view_text, range_text = f"{half_c:g}¢", f"{half_c * 3:g}¢"
    else:
        view_text, range_text = f"{default_view:g}% of the average price", f"{compute_range:g}%"
    st.caption(
        f"Current mark: **{_fmt_dollars_signed(cur_val)}** at a 0% shock (blue dot). Default view is "
        f"±{view_text}; drag or zoom out to see up to ±{range_text}. "
        f"Other lines hold vol at the current scenario and roll time forward — theta & gamma "
        f"reshape the curve as they decay."
    )


def _contract_group_key(p: Position) -> str:
    if p.is_cash:
        return f"Futures cash {p.underlying_override}"
    return p.expiry_date.isoformat() if p.expiry_date else f"Futures {p.label}"


def _contract_group_label(key: str) -> str:
    if key.startswith("Futures"):
        return key
    d = date.fromisoformat(key)
    return f"{d.strftime('%b')} {d.day}, '{d.strftime('%y')}"


def _group_by_contract(
    positions: List[Position],
    evals: Dict[int, PositionEval],
    value_fn: Callable[[PositionEval], float],
) -> Tuple[List[str], Dict[str, float]]:
    data: Dict[str, float] = {}
    order: List[str] = []
    for p in positions:
        k = _contract_group_key(p)
        if k not in data:
            data[k] = 0.0
            order.append(k)
        data[k] += value_fn(evals[id(p)])
    order.sort(key=lambda k: (k.startswith("Futures"), k))
    return order, data


# Width of one character of the 11px font these bars label their bars with, measured in
# the browser rather than guessed: "+3,645,343 lb" renders 60.3px over 13 characters.
_LABEL_CHAR_PX = 4.7
_LABEL_MIN_PX = 10
_LABEL_MAX_PX = 70


def _label_margin_px(texts: List[str]) -> int:
    """Side margin wide enough for the longest value label to draw outside its bar, in
    pixels, capped so three charts in a row still leave a plot to draw in.

    Both sides, because a negative bar labels to the LEFT -- vega and theta go negative
    routinely, and a net short book does it on the position bar too."""
    if not texts:
        return _LABEL_MIN_PX
    want = int(max(len(t) for t in texts) * _LABEL_CHAR_PX) + 8
    return max(_LABEL_MIN_PX, min(want, _LABEL_MAX_PX))


def _render_mini_bar(
    col,
    title: str,
    unit: str,
    order: List[str],
    data: Dict[str, float],
    fmt: Callable[[float], str],
) -> None:
    with col:
        st.markdown(f"**{title}** <span style='font-size:11px;color:{MUTED}'>{unit}</span>", unsafe_allow_html=True)
        if not order:
            st.caption("No positions.")
            return
        labels = [_contract_group_label(k) for k in order]
        values = [data[k] for k in order]
        max_abs = max(1.0, max(abs(v) for v in values))
        colors = [GAIN if v >= 0 else LOSS for v in values]
        text = [fmt(v) for v in values]
        fig = go.Figure(
            go.Bar(
                x=values, y=labels, orientation="h",
                marker_color=colors, text=text, textposition="auto",
                # "auto" rather than "outside", with clipping off. An outside label is
                # clipped at the axis when it does not fit, so a long value loses its last
                # characters SILENTLY and still reads as a number -- "+7,391,811 lb"
                # rendering as "+7,391,81". The full string stays in the DOM either way,
                # which is why that survived a text-based check and showed up only in a
                # picture. "auto" moves the label inside the bar instead.
                #
                # The margin below is NOT enough on its own: these sit three to a row, and
                # the width is decided in the browser, so on a narrow window the space a
                # label needs exceeds the whole column. Reserving pixels cannot fix a case
                # where the pixels do not exist -- "auto" is what covers it.
                cliponaxis=False,
                hovertemplate=f"%{{y}}<br>{title}: %{{text}}<extra></extra>",
            )
        )
        # Room for the label beyond the longest bar. A fixed multiplier cannot do this:
        # the headroom is a fraction of the PLOT, the label is a fixed number of PIXELS,
        # so whatever constant works at one pane width fails at a narrower one -- 1.3
        # needs a plot about 400px wide to fit a 13-character value, and these sit three
        # to a row. Hence room reserved in the MARGIN, which is in pixels like the text,
        # and scaled to the longest label actually being drawn.
        side = _label_margin_px(text)
        fig.update_layout(
            height=34 * len(order) + 50,
            margin=dict(l=side, r=side, t=10, b=10),
            xaxis=dict(range=[-max_abs * 1.12, max_abs * 1.12], zeroline=True, zerolinewidth=1, showgrid=False,
                       showticklabels=False),
            yaxis=dict(autorange="reversed"),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        )
        st.plotly_chart(fig, use_container_width=True)


def render_greeks_bars(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec = CORN,
) -> None:
    evals = {id(p): eval_position(p, stress, get_contract_price, commodity=commodity) for p in positions}
    cols = st.columns(3)
    # round() per position, matching the blotter's Position column and the group rows
    # that foot it. Summing the raw floats instead leaves this bar a pound or two from the
    # same figure printed a few inches above it -- which is nothing as a quantity and is
    # still one number appearing twice with two values.
    order, delta_data = _group_by_contract(positions, evals, lambda r: round(r.delta_d))
    # "Net Position", not "Delta": this is the blotter's Position (lb) column summed per
    # expiry, and the page now reserves the word Delta for the option's own greek. Net,
    # because a group really is several legs added together -- unlike a blotter row.
    _render_mini_bar(cols[0], f"Net Position ({commodity.unit})", "by expiry", order, delta_data,
                      lambda v: _fmt_unit_signed(v, commodity.unit))
    order, vega_data = _group_by_contract(positions, evals, lambda r: r.vega_d)
    _render_mini_bar(cols[1], "Vega $", "per vol pt", order, vega_data, _fmt_dollars_signed)
    order, theta_data = _group_by_contract(positions, evals, lambda r: r.theta_d)
    _render_mini_bar(cols[2], "Theta $", "per day", order, theta_data, _fmt_dollars_signed)
