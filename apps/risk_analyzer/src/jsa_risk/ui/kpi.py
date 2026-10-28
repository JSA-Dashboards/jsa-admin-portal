"""KPI strip: Net Position, Net Gamma $, Net Vega $, Net Theta $/day, 1-Day 95% VaR —
computed over whichever positions are currently visible (all of them, until Phase 3
adds blotter filters).

Rendered as custom HTML (not st.metric) so the value text itself can be colored green/red
by sign — st.metric only colors its small delta indicator, not the main value."""
from typing import Callable, List, Tuple

import pandas as pd
import streamlit as st

from jsa_risk.pricing.commodities import CORN, CommoditySpec
from jsa_risk.pricing.portfolio import book_totals
from jsa_risk.pricing.stress import (
    Position, PositionEval, StressState, effective_underlying_key, eval_position, stressed_future,
)
from jsa_risk.pricing.symbols import upcoming_contract_keys
from jsa_risk.pricing.var import VarResult, book_var, value_at_risk

GAIN_COLOR = "#3a9d5d"
LOSS_COLOR = "#c0392b"


def _sign_color(v: float) -> str:
    return GAIN_COLOR if v >= 0 else LOSS_COLOR


def _fmt_unit_signed(v: float, unit: str) -> str:
    """Just the signed number, no LONG/SHORT wording — a minus sign for short, nothing
    (no plus) for long/flat. Comma-grouped, no decimal places, no K/M abbreviation."""
    sign = "-" if v < 0 else ""
    return f"{sign}{abs(v):,.0f} {unit}"


def _fmt_dollars(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def _stat_html(label: str, value_str: str, color: str, help_text: str) -> str:
    return (
        f"<div style='margin-bottom:4px'>"
        f"<span style='font-size:14px;color:#898781' title='{help_text}'>{label} ⓘ</span>"
        f"<div style='font-size:2rem;font-weight:600;line-height:1.3;color:{color}'>{value_str}</div>"
        f"</div>"
    )


def compute_book_var(
    positions: List[Position],
    evals: List[PositionEval],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec,
) -> Tuple[VarResult, str]:
    """1-day 95% VaR over per-contract factors (see pricing/var.py), and a note on anything that
    kept it from using real price history. Never raises: a VaR tile is not worth the page, so
    any failure drops to the assumed-vol estimate on the net exposure and says why."""
    exposures: dict = {}
    for p, e in zip(positions, evals):
        key = effective_underlying_key(p, commodity=commodity)
        price = stressed_future(get_contract_price(key), stress)
        exposures[key] = exposures.get(key, 0.0) + e.delta_d * price      # units x $/unit = $
    problem = ""
    returns: dict = {}
    if any(exposures.values()):
        try:
            from jsa_risk.data.price_history import get_return_history
            # The book's own contracts, plus the next few listed ones as stand-ins for a young
            # contract that has too little history of its own.
            keys = sorted(set(exposures) | set(upcoming_contract_keys(commodity, count=4)))
            returns, problem = get_return_history(commodity, keys)
        except Exception as e:                                           # noqa: BLE001
            problem = f"Price history is unavailable ({e})."
    return book_var(exposures, returns, commodity.daily_vol), problem


def _var_basis(result: VarResult) -> str:
    return "EWMA covariance" if result.method == "covariance" else "assumed daily move"


def render_kpi_strip(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec = CORN,
) -> None:
    evals = [eval_position(p, stress, get_contract_price, commodity=commodity) for p in positions]
    # Shared with the blotter's totals footer -- "Net Position" here and "Total Delta"
    # there are one figure, and summing them separately would let them drift silently.
    net_delta, _ = book_totals(evals)
    net_gamma = sum(e.gamma_d for e in evals)
    net_vega = sum(e.vega_d for e in evals)
    net_theta = sum(e.theta_d for e in evals)
    var_result, _ = compute_book_var(positions, evals, stress, get_contract_price, commodity)
    var_signed = -var_result.var

    contracts = abs(net_delta) / commodity.contract_size

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(
        _stat_html("Net Position", _fmt_unit_signed(net_delta, commodity.unit), _sign_color(net_delta),
                   f"≈{contracts:.1f} contracts"),
        unsafe_allow_html=True,
    )
    c2.markdown(
        _stat_html("Net Gamma $", _fmt_dollars(net_gamma), _sign_color(net_gamma), "Δdelta per $1 move"),
        unsafe_allow_html=True,
    )
    c3.markdown(
        _stat_html("Net Vega $", _fmt_dollars(net_vega), _sign_color(net_vega), "per 1 vol pt"),
        unsafe_allow_html=True,
    )
    c4.markdown(
        _stat_html("Net Theta $/day", _fmt_dollars(net_theta), _sign_color(net_theta), "time decay"),
        unsafe_allow_html=True,
    )
    c5.markdown(
        _stat_html("1-Day 95% VaR", _fmt_dollars(var_signed), _sign_color(var_signed),
                   _var_basis(var_result)),
        unsafe_allow_html=True,
    )


def render_var_panel(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec = CORN,
) -> None:
    evals = [eval_position(p, stress, get_contract_price, commodity=commodity) for p in positions]
    result, problem = compute_book_var(positions, evals, stress, get_contract_price, commodity)
    var_signed = -result.var
    st.markdown(
        _stat_html("1-Day 95% VaR", _fmt_dollars(var_signed), _sign_color(var_signed), _var_basis(result)),
        unsafe_allow_html=True,
    )
    if result.method == "covariance":
        st.caption(
            "Delta-normal over each contract's own price factor: 1.645 × the 1-day dollar standard "
            "deviation of the book, from an EWMA covariance matrix (decay 0.94, so recent days "
            "weigh most) of every contract's daily settlement log returns. Offsetting contracts "
            "net only as far as they are correlated, so a spread still carries risk. Gamma and "
            "vega are not included."
        )
        if result.contracts:
            st.dataframe(pd.DataFrame([{
                "Contract": c.key,
                "Exposure ($ delta)": round(c.exposure),
                "Daily vol": f"{c.daily_vol * 100:.2f}%" + (f" (from {c.proxy})" if c.proxy else ""),
                "VaR contribution ($)": round(c.component_var),
            } for c in result.contracts]), hide_index=True, use_container_width=True)
    else:
        st.caption(
            f"Using an assumed {commodity.daily_vol * 100:.1f}% daily move on the net dollar exposure — "
            "not enough price history to estimate volatility and correlations."
        )
    for note in [problem, *(result.notes if result.method == "covariance" else [])]:
        if note:
            st.caption(note)
