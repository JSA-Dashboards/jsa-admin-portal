"""Stress-scenario transforms and the core per-position pricing/P&L function.

Ported from the JSA Risk Analyzer HTML tool's evalPosition(). The critical rule: the
moment any stress slider is non-zero, or a hypothetical F/sigma/T is supplied (used by
the heatmap/delta-scenario/payoff panels to ask "what if"), the last tick is ignored in
favor of the theoretical model price — a tick only stands in for Mark on the live,
unshocked book.
"""
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from .black76 import black76
from .commodities import CORN, CommoditySpec


@dataclass(frozen=True)
class Position:
    """A single book entry. `type` is 'call' | 'put' | 'future'; strike/expiry_date/iv
    are None for futures. `qty` is signed (positive = long, negative = short).
    `underlying_override`, when set (a canonical key like "Z26"), takes precedence over
    the underlying auto-derived from `label` -- a manual escape hatch for the cases the
    date-based roll rule in symbols.py doesn't (or shouldn't) cover on its own.
    `is_cash` marks a physical/cash position: priced and risked exactly like a future on
    the contract in `underlying_override`, but it has no expiry, and `qty` may be
    fractional (cash is held in bushels/pounds, which needn't be a whole contract)."""
    id: int
    label: str
    type: str
    qty: float
    entry: float
    strike: Optional[float] = None
    expiry_date: Optional[date] = None
    iv: Optional[float] = None
    iv_estimated: bool = False
    last_tick: Optional[float] = None
    import_mark: Optional[float] = None
    underlying_override: Optional[str] = None
    is_cash: bool = False


def effective_underlying_key(
    position: Position, today: Optional[date] = None, commodity: CommoditySpec = CORN
) -> str:
    if position.underlying_override:
        return position.underlying_override.strip().upper()
    from .symbols import canonical_contract_key  # local import avoids a circular dependency
    return canonical_contract_key(position.label, today, commodity)


def effective_underlying_display(
    position: Position, today: Optional[date] = None, commodity: CommoditySpec = CORN
) -> str:
    """Same display convention as contract_display_name, but reflects a manual
    underlying_override when set, tagged "(override)". The override names its target
    contract directly (it's already a canonical key, not an option symbol to decode), so
    it's formatted as-is via format_canonical_key rather than re-run through the
    date-based roll logic -- otherwise a stale-looking override (e.g. "U26" set after
    Sep 1) would display as if it had rolled forward again, contradicting the literal
    contract it's actually being priced against."""
    from .symbols import contract_display_name, format_canonical_key
    if position.underlying_override:
        tag = "cash" if position.is_cash else "override"
        return f"{format_canonical_key(position.underlying_override)} ({tag})"
    return contract_display_name(position.label, today, commodity)


@dataclass
class StressState:
    price_pct: float = 0.0
    vol_pct: float = 0.0
    days: float = 0.0

    @property
    def is_neutral(self) -> bool:
        return self.price_pct == 0 and self.vol_pct == 0 and self.days == 0


def days_to_expiry(expiry_date: Optional[date], today: Optional[date] = None) -> Optional[int]:
    if expiry_date is None:
        return None
    today = today or date.today()
    return (expiry_date - today).days


def stressed_future(contract_price: float, stress: StressState) -> float:
    return contract_price * (1 + stress.price_pct / 100)


def stressed_sigma(iv: float, stress: StressState) -> float:
    return max(iv * (1 + stress.vol_pct / 100), 0.5)


def stressed_T(expiry_date: Optional[date], stress: StressState, today: Optional[date] = None) -> float:
    dte = days_to_expiry(expiry_date, today)
    if dte is None:
        return 0.0
    return max(dte - stress.days, 0.0) / 365


@dataclass(frozen=True)
class PositionEval:
    price: float           # Mark actually used for pnl/import_gain (tick or model)
    model_price: float      # theoretical price, always model-based, for reference/hints
    delta_d: float
    gamma_d: float
    vega_d: float
    theta_d: float
    pnl: float              # vs. entry/cost basis
    import_gain: float      # vs. import_mark (falls back to entry if never set)


def eval_position(
    position: Position,
    stress: StressState,
    get_contract_price: Callable[[str], float],
    F_override: Optional[float] = None,
    sigma_override: Optional[float] = None,
    T_override: Optional[float] = None,
    today: Optional[date] = None,
    commodity: CommoditySpec = CORN,
) -> PositionEval:
    no_stress = stress.is_neutral
    has_tick = position.last_tick is not None
    use_last_tick = (F_override is None) and no_stress and has_tick

    canonical_key = effective_underlying_key(position, today, commodity)
    F = F_override if F_override is not None else stressed_future(get_contract_price(canonical_key), stress)
    pos_mult = position.qty * commodity.contract_size
    import_basis = position.import_mark if position.import_mark is not None else position.entry

    if position.type == "future":
        fut_mark = position.last_tick if use_last_tick else F
        return PositionEval(
            price=fut_mark,
            model_price=F,
            delta_d=pos_mult,
            gamma_d=0.0,
            vega_d=0.0,
            theta_d=0.0,
            pnl=(fut_mark - position.entry) * pos_mult,
            import_gain=(fut_mark - import_basis) * pos_mult,
        )

    sigma = sigma_override if sigma_override is not None else stressed_sigma(position.iv, stress)
    T = T_override if T_override is not None else stressed_T(position.expiry_date, stress, today)
    result = black76(F, position.strike, T, sigma, position.type == "call")
    mark = position.last_tick if use_last_tick else result.price

    return PositionEval(
        price=mark,
        model_price=result.price,
        delta_d=result.delta * pos_mult,
        gamma_d=result.gamma * pos_mult,
        vega_d=(result.vega / 100) * pos_mult,
        theta_d=(result.theta / 365) * pos_mult,
        pnl=(mark - position.entry) * pos_mult,
        import_gain=(mark - import_basis) * pos_mult,
    )
