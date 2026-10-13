"""Portfolio-level scenario aggregation — reused by the P&L heatmap, the delta-scenario
table, and the payoff chart instead of each reimplementing this inline.

Both functions layer an *additional* shock on top of the current stress-slider state
(`base_stress`), exactly as the original portfolioPnlAt()/portfolioDeltaAt() did. The
price shock is expressed as a percent of the book's reference price (see
portfolio_reference_price) but applied as ONE parallel move: every contract shifts by the
same cents per unit. That keeps a delta-neutral book flat -- a book long and short the same
number of bushels/pounds across differently-priced contracts has no P&L from a parallel
move, whatever the contracts' own prices. (An earlier version scaled the shock by each
contract's own price, which tilted a unit-neutral book by the price difference between its
legs.)
"""
from datetime import date
from typing import Callable, Iterable, Optional

from .commodities import CORN, CommoditySpec
from .stress import (
    Position,
    PositionEval,
    StressState,
    days_to_expiry,
    effective_underlying_key,
    eval_position,
    stressed_future,
    stressed_sigma,
)


def _shocked_future(
    position: Position,
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    price_shock_pct: float,
    today: Optional[date],
    commodity: CommoditySpec,
    ref_price: float,
) -> float:
    base_F = stressed_future(get_contract_price(effective_underlying_key(position, today, commodity)), base_stress)
    return base_F + price_shock_pct / 100 * ref_price


def portfolio_reference_price(
    positions: Iterable[Position],
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
) -> float:
    """One representative underlying price for the whole book, in the commodity's own unit
    ($/bu or $/lb), used to translate a % price shock into an equivalent cents-per-unit
    label. Weighted by |delta| so the contracts carrying the most exposure dominate; falls
    back to a plain average when every delta is zero, and to the commodity's default price
    for an empty book."""
    prices, weights = [], []
    for p in positions:
        prices.append(stressed_future(get_contract_price(effective_underlying_key(p, today, commodity)), base_stress))
        weights.append(abs(eval_position(p, base_stress, get_contract_price, today=today, commodity=commodity).delta_d))
    if not prices:
        return commodity.default_price
    total = sum(weights)
    if total <= 0:
        return sum(prices) / len(prices)
    return sum(f * w for f, w in zip(prices, weights)) / total


def portfolio_pnl_at(
    positions: Iterable[Position],
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    price_shock_pct: float,
    vol_shock_pct: float,
    days_fwd: float,
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
    ref_price: Optional[float] = None,
) -> float:
    positions = list(positions)
    if ref_price is None:
        ref_price = portfolio_reference_price(positions, get_contract_price, base_stress, today, commodity)
    total = 0.0
    for p in positions:
        F = _shocked_future(p, get_contract_price, base_stress, price_shock_pct, today, commodity, ref_price)
        if p.type == "future":
            sigma = 0.5
        else:
            sigma = max(stressed_sigma(p.iv, base_stress) * (1 + vol_shock_pct / 100), 0.5)
        dte = days_to_expiry(p.expiry_date, today)
        T = 0.0 if dte is None else max(dte - base_stress.days - days_fwd, 0) / 365
        r: PositionEval = eval_position(
            p, base_stress, get_contract_price, F_override=F, sigma_override=sigma, T_override=T, today=today,
            commodity=commodity,
        )
        total += r.pnl
    return total


def portfolio_delta_at(
    positions: Iterable[Position],
    get_contract_price: Callable[[str], float],
    base_stress: StressState,
    price_shock_pct: float,
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
    ref_price: Optional[float] = None,
) -> float:
    """Net delta ($, i.e. unit-equivalent exposure) at a hypothetical price, holding
    vol and time at the current stress scenario (no extra vol/time axis, unlike
    `portfolio_pnl_at`)."""
    positions = list(positions)
    if ref_price is None:
        ref_price = portfolio_reference_price(positions, get_contract_price, base_stress, today, commodity)
    total = 0.0
    for p in positions:
        F = _shocked_future(p, get_contract_price, base_stress, price_shock_pct, today, commodity, ref_price)
        r = eval_position(p, base_stress, get_contract_price, F_override=F, today=today, commodity=commodity)
        total += r.delta_d
    return total
