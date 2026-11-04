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
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, List, Optional, Tuple

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


def book_totals(evals: Iterable[PositionEval]) -> Tuple[float, float]:
    """(net delta in the commodity's own unit, total P&L vs entry) over a book's evaluated
    positions. One function because the KPI strip's "Net Position" and the blotter's delta
    total are the SAME figure on the same page -- summed separately they would be free to
    drift apart, and nothing would raise when they did.

    EACH POSITION IS ROUNDED BEFORE SUMMING, with the same `round` the blotter applies to
    its cells, so the totals line FOOTS the columns it sits under: a reader adding the four
    P&L figures by hand gets the printed total to the dollar. Summing unrounded and
    rounding once is the more obvious choice and is wrong here -- it is off by up to half a
    unit per row, which is invisible on the delta column and is exactly the kind of
    "it doesn't add up" a client notices on a P&L."""
    evals = list(evals)
    return sum(round(e.delta_d) for e in evals), sum(round(e.pnl) for e in evals)


@dataclass(frozen=True)
class GroupTotals:
    """One underlying's legs combined. `delta_per_unit` is the figure a trader quotes for
    the structure -- long the 2.39 call against short the 2.19 put is "0.57 delta" -- and
    is None when the legs are not all the same size, because there is then no single
    structure to be one unit OF. `delta_contracts` is always defined: the legs' deltas
    added with their sizes, which is "how many deltas" the group is."""
    label: str
    delta_per_unit: Optional[float]
    delta_contracts: float
    position: float
    pnl: float


def book_totals_by_group(
    positions: Iterable[Position],
    evals: Iterable[PositionEval],
    key: Callable[[Position], str],
) -> List[GroupTotals]:
    """Per-group combined figures, in the order each group first appears in the book -- so
    the breakdown reads down the page in the same order as the blotter rows it summarises.

    Position and P&L round per position exactly as `book_totals` does, which is what makes
    the group rows foot to the book line beneath them. The deltas do NOT round per leg:
    they are quoted to four decimals, and rounding two of those before adding would show a
    combined delta that the column above it does not produce."""
    order: List[str] = []
    acc: dict = {}
    for p, e in zip(positions, evals):
        k = key(p)
        if k not in acc:
            order.append(k)
            acc[k] = {"pos": 0.0, "pnl": 0.0, "dc": 0.0, "qty": set()}
        a = acc[k]
        a["pos"] += round(e.delta_d)
        a["pnl"] += round(e.pnl)
        a["dc"] += e.delta * p.qty
        a["qty"].add(abs(p.qty))

    out: List[GroupTotals] = []
    for k in order:
        a = acc[k]
        # One size across every leg means the group is N copies of one structure, so its
        # delta per copy is meaningful. Mixed sizes have no "per unit" to report, and a
        # group of zero-qty rows has nothing to divide by.
        lots = a["qty"]
        per_unit = None
        if len(lots) == 1:
            size = next(iter(lots))
            if size:
                per_unit = a["dc"] / size
        out.append(GroupTotals(k, per_unit, a["dc"], a["pos"], a["pnl"]))
    return out


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
            commodity=commodity, greeks=False,
        )
        # Anchor to the mark the blotter shows. A position carrying a last tick is marked at
        # that tick (not the model) when no stress is applied, so the scenario is that actual
        # P&L plus the model's CHANGE -- otherwise the 0%/0% cell is repriced purely off the
        # model and disagrees with the blotter total by (tick - model).
        base = eval_position(p, base_stress, get_contract_price, today=today, commodity=commodity)
        pnl = r.pnl + (base.price - base.model_price) * p.qty * commodity.contract_size
        total += pnl
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
