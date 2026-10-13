"""KPI strip: Net Position, Net Gamma $, Net Vega $, Net Theta $/day, 1-Day 95% VaR —
computed over whichever positions are currently visible (all of them, until Phase 3
adds blotter filters).

Rendered as custom HTML (not st.metric) so the value text itself can be colored green/red
by sign — st.metric only colors its small delta indicator, not the main value."""
from typing import Callable, List

import streamlit as st

from jsa_risk.pricing.commodities import CORN, CommoditySpec
from jsa_risk.pricing.stress import Position, StressState, eval_position
from jsa_risk.pricing.var import value_at_risk

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


def render_kpi_strip(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec = CORN,
) -> None:
    evals = [eval_position(p, stress, get_contract_price, commodity=commodity) for p in positions]
    net_delta = sum(e.delta_d for e in evals)
    net_gamma = sum(e.gamma_d for e in evals)
    net_vega = sum(e.vega_d for e in evals)
    net_theta = sum(e.theta_d for e in evals)
    var_95 = value_at_risk(net_delta, daily_vol=commodity.daily_vol)
    var_signed = -var_95

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
        _stat_html("1-Day 95% VaR", _fmt_dollars(var_signed), _sign_color(var_signed), "delta-normal"),
        unsafe_allow_html=True,
    )


def render_var_panel(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec = CORN,
) -> None:
    evals = [eval_position(p, stress, get_contract_price, commodity=commodity) for p in positions]
    net_delta = sum(e.delta_d for e in evals)
    var_95 = value_at_risk(net_delta, daily_vol=commodity.daily_vol)
    var_signed = -var_95
    st.markdown(
        _stat_html("1-Day 95% VaR", _fmt_dollars(var_signed), _sign_color(var_signed), "delta-normal"),
        unsafe_allow_html=True,
    )
    st.caption(
        f"Delta-normal: 1.645 × |net delta $| × an assumed {commodity.daily_vol * 100:.1f}% "
        f"daily {commodity.name.lower()} futures move (approximate, not a fitted historical vol)."
    )
