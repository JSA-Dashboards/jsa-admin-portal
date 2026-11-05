"""Strategy payoffs on a spread: the position you hold plus the options laid over it.

A strategy is a list of ``Leg``s. Every number here is P&L in dollars against what the legs cost: a spread
future against its entry level, an option against the premium paid (or received). Payoffs are piecewise
linear in the spread level, so break-evens, floors and caps come out exactly instead of from a sampled grid.
Adding a strategy later means adding legs, not changing any of this.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from . import pricing

FUTURE, CALL, PUT = "Spread future", "Call", "Put"
_EPS = 1e-9


@dataclass(frozen=True)
class Leg:
    kind: str                     # FUTURE | CALL | PUT
    qty: float                    # signed contracts: + long, - short
    strike: float                 # option strike, or the entry level of a spread future
    premium: float = 0.0          # points paid per unit when long (received when short); unused for futures
    expiry: date | None = None
    vol: float | None = None      # spread vol for this leg; None = the vol passed to value_on


def _intrinsic(leg: Leg, S):
    return np.maximum(S - leg.strike, 0.0) if leg.kind == CALL else np.maximum(leg.strike - S, 0.0)


def at_expiry(legs, S, mult: float) -> np.ndarray:
    """P&L ($) if the spread finishes at ``S``: futures vs entry, options at intrinsic value less premium."""
    S = np.asarray(S, dtype=float)
    total = np.zeros_like(S)
    for leg in legs:
        if leg.kind == FUTURE:
            total = total + leg.qty * mult * (S - leg.strike)
        else:
            total = total + leg.qty * mult * (_intrinsic(leg, S) - leg.premium)
    return total


def value_on(legs, S, mult: float, vol: float, rate: float, eval_date: date) -> np.ndarray:
    """P&L ($) if the spread is at ``S`` on ``eval_date``, options marked with the model (time value included)."""
    S = np.asarray(S, dtype=float)
    total = np.zeros_like(S)
    for leg in legs:
        if leg.kind == FUTURE:
            total = total + leg.qty * mult * (S - leg.strike)
            continue
        T = 0.0 if leg.expiry is None else max((leg.expiry - eval_date).days, 0) / 365.0
        sigma = leg.vol if leg.vol else vol
        price = pricing.price(leg.kind == CALL, S, leg.strike, sigma, T, rate)
        total = total + leg.qty * mult * (price - leg.premium)
    return total


def kinks(legs) -> list[float]:
    return sorted({leg.strike for leg in legs if leg.kind != FUTURE})


def tail_slopes(legs, mult: float) -> tuple[float, float]:
    """$ per point of spread as the spread heads to minus infinity and to plus infinity."""
    left = right = 0.0
    for leg in legs:
        q = leg.qty * mult
        if leg.kind == FUTURE:
            left += q
            right += q
        elif leg.kind == CALL:
            right += q
        else:
            left -= q
    return left, right


def breakevens(legs, mult: float) -> list[float]:
    """Spread levels where the payoff at expiry is zero, found exactly from the kinks."""
    ks = kinks(legs)
    left, right = tail_slopes(legs, mult)
    if not ks:
        f0 = float(at_expiry(legs, 0.0, mult))
        return [] if abs(right) < _EPS else [-f0 / right]
    vals = [float(at_expiry(legs, k, mult)) for k in ks]
    roots: list[float] = []
    if abs(left) > _EPS:
        r = ks[0] - vals[0] / left
        if r < ks[0] - _EPS:
            roots.append(r)
    for (a, b), (fa, fb) in zip(zip(ks, ks[1:]), zip(vals, vals[1:])):
        if fa * fb < 0:
            roots.append(a + (-fa) * (b - a) / (fb - fa))
    roots += [k for k, v in zip(ks, vals) if abs(v) < 1e-7]
    if abs(right) > _EPS:
        r = ks[-1] - vals[-1] / right
        if r > ks[-1] + _EPS:
            roots.append(r)
    out: list[float] = []
    for r in sorted(roots):
        if not out or abs(r - out[-1]) > 1e-7:
            out.append(r)
    return out


def summary(legs, mult: float) -> dict:
    """Premium paid, max loss and max gain at expiry (None = unlimited) and the break-evens."""
    ks = kinks(legs)
    left, right = tail_slopes(legs, mult)
    vals = [float(at_expiry(legs, k, mult)) for k in ks]
    unlimited_loss = left > _EPS or right < -_EPS
    unlimited_gain = left < -_EPS or right > _EPS
    if not vals:                      # futures only: linear, so unbounded one way or both
        vals = [0.0] if not (unlimited_loss or unlimited_gain) else []
    premium_paid = sum(leg.qty * mult * leg.premium for leg in legs if leg.kind != FUTURE)
    return {
        "premium_paid": premium_paid,
        "max_loss": None if unlimited_loss else (min(vals) if vals else 0.0),
        "max_gain": None if unlimited_gain else (max(vals) if vals else 0.0),
        "breakevens": breakevens(legs, mult),
    }


def grid(legs, mult: float, lo: float, hi: float, n: int = 401) -> np.ndarray:
    """An even grid over [lo, hi] that also contains every kink and break-even, so shading meets zero exactly."""
    xs = set(np.linspace(lo, hi, n).tolist())
    xs |= {k for k in kinks(legs) if lo <= k <= hi}
    xs |= {b for b in breakevens(legs, mult) if lo <= b <= hi}
    return np.array(sorted(xs))


def _opposite(pair) -> bool:
    """Two legs, one bought and one sold."""
    return len(pair) == 2 and (pair[0].qty > 0) != (pair[1].qty > 0)


def _credit(pair) -> bool:
    """A put or call spread that takes in premium: the bought option is the further from the money."""
    a, b = pair
    bought, sold = (a, b) if a.qty > 0 else (b, a)
    return bought.strike < sold.strike if a.kind == PUT else bought.strike > sold.strike


def _vertical_name(pair) -> str:
    """Put spread / Call spread (credit) / Ratio put spread, for two options of one kind on opposite sides."""
    a, b = pair
    if a.strike == b.strike:
        return "Offsetting options"
    name = f"{'Ratio ' if abs(a.qty) != abs(b.qty) else ''}{a.kind.lower()} spread"
    name = name[0].upper() + name[1:]
    return f"{name} (credit)" if _credit(pair) else name


def name_of(legs) -> str:
    """A trader's name for what the legs add up to: Put spread, Collar, Call spread vs short put, Iron condor ...

    Two options of one kind on opposite sides are a put or call spread (a credit spread when the bought one is the
    further from the money). A put and a call are a straddle or strangle when both are bought, a short straddle or
    strangle when both are sold, and otherwise a collar when the bought one works against the position (a put over a
    long spread, a call over a short one) and a risk reversal when it does not. A spread plus one option of the other
    kind reads "Call spread vs short put"; a put spread and a call spread together are an iron condor.
    """
    opts = [leg for leg in legs if leg.kind != FUTURE]
    held = sum(leg.qty for leg in legs if leg.kind == FUTURE)
    if not opts:
        return "Spread position" if held else "Nothing"
    if len(opts) == 1:
        return f"{'Long' if opts[0].qty > 0 else 'Short'} {opts[0].kind.lower()}"
    calls, puts = [o for o in opts if o.kind == CALL], [o for o in opts if o.kind == PUT]
    if len(opts) == 2:
        if len(calls) == 2 or len(puts) == 2:
            return _vertical_name(opts) if _opposite(opts) else f"Two {opts[0].kind.lower()}s"
        put, call = puts[0], calls[0]
        if put.qty > 0 and call.qty > 0:
            return "Straddle" if put.strike == call.strike else "Strangle"
        if put.qty < 0 and call.qty < 0:
            return "Short straddle" if put.strike == call.strike else "Short strangle"
        return "Collar" if held != 0 and (put.qty > 0) == (held > 0) else "Risk reversal"
    if len(opts) == 3:
        for pair, single in ((calls, puts), (puts, calls)):
            if len(pair) == 2 and len(single) == 1 and _opposite(pair):
                return f"{_vertical_name(pair)} vs {'long' if single[0].qty > 0 else 'short'} {single[0].kind.lower()}"
    if len(opts) == 4 and _opposite(calls) and _opposite(puts):
        both = (_credit(calls), _credit(puts))
        return "Iron condor" if all(both) else "Reverse iron condor" if not any(both) else "Put spread + call spread"
    return "Custom"


def describe(legs) -> str:
    """The option legs in words: "buy 10 -20 put, sell 10 -10 call"."""
    return ", ".join(f"{'buy' if leg.qty > 0 else 'sell'} {abs(leg.qty):g} {leg.strike:+g} {leg.kind.lower()}"
                     for leg in legs if leg.kind != FUTURE)


# ---- where the strategy protects the position and where it keeps its gain
PROTECTED, GAINED, CAPPED, EXPOSED, PARTIAL = "protected", "gained", "capped", "exposed", "partial"


@dataclass(frozen=True)
class Zone:
    lo: float                     # -inf for a zone that runs off the bottom
    hi: float                     # +inf for one that runs off the top
    kind: str                     # PROTECTED | GAINED | CAPPED | EXPOSED | PARTIAL
    label: str


def zones(legs, mult: float) -> list[Zone]:
    """Split the spread level into zones, by what the strategy does with the position there (nothing without one).

    Between two strikes the payoff is a straight line, so each stretch is judged by its slope against the slope of
    the position alone. Where the position is losing: a flat payoff means the options have PROTECTED it (the loss
    stops growing), the position's own slope means it is EXPOSED, anything between is PARTIAL protection. Where the
    position is gaining: the position's own slope means the move is GAINED, a flat payoff means the gain is CAPPED
    (no additional move pays), anything between is a reduced gain. The loss side is whichever side of the entry the
    position loses on.
    """
    futures = [leg for leg in legs if leg.kind == FUTURE]
    lots = sum(leg.qty for leg in futures)
    if not futures or abs(lots) < _EPS:
        return []
    m_pos = lots * mult
    entry = sum(leg.qty * leg.strike for leg in futures) / lots
    points = sorted({entry, *kinks(legs)})
    left, right = tail_slopes(legs, mult)
    way = "downside" if m_pos < 0 else "upside"               # the way the spread has to move for the position to pay
    out: list[Zone] = []
    for a, b in zip([-math.inf, *points], [*points, math.inf]):
        if a == -math.inf:
            slope, probe = left, b - 1.0
        elif b == math.inf:
            slope, probe = right, a + 1.0
        else:
            slope, probe = (float(at_expiry(legs, b, mult)) - float(at_expiry(legs, a, mult))) / (b - a), (a + b) / 2
        loss = m_pos * (probe - entry) < 0
        ratio = slope / m_pos
        if abs(ratio) < 0.02:
            kind, label = (PROTECTED, "Protected") if loss else (CAPPED, f"No additional {way}")
        elif abs(ratio - 1.0) < 0.02:
            kind, label = (EXPOSED, "Unprotected") if loss else (GAINED, f"{way.capitalize()} gained")
        else:
            kind, label = (PARTIAL, "Partly protected" if loss else "Gain reduced")
        if out and out[-1].kind == kind and out[-1].label == label:
            out[-1] = Zone(out[-1].lo, b, kind, label)
        else:
            out.append(Zone(a, b, kind, label))
    return out


def _span(zone: Zone) -> str:
    if zone.lo == -math.inf:
        return f"below {zone.hi:+g}"
    if zone.hi == math.inf:
        return f"above {zone.lo:+g}"
    return f"{zone.lo:+g} to {zone.hi:+g}"


def zone_summary(zone_list) -> str:
    """The zones in one line, protection first: "**Protected** -20 to -5 · **Downside gained** -30 to -21 ..."."""
    parts = []
    for kind in (PROTECTED, PARTIAL, GAINED, CAPPED, EXPOSED):
        spans: dict[str, list[str]] = {}
        for z in zone_list:
            if z.kind == kind:
                spans.setdefault(z.label, []).append(_span(z))
        parts += [f"**{label}** {' and '.join(found)}" for label, found in spans.items()]
    return " · ".join(parts)


# ---- the structure as a broker writes it
def ticket(legs, code: str, ref: float, net: float, unit: str = "c") -> str:
    """``SFK -20/-5cs vs -30p 2.40c over ref -21 x10``: the spread, the structure, its net price and the level it is over.

    A bought and a sold option of one kind and size pair up into a spread (``cs`` call spread, ``ps`` put spread, the
    bought strike first). Bought options read ``-20p`` / ``-20c`` and what is sold comes after ``vs``. ``net`` is the net
    premium paid for one lot in points (a credit prints as such); ``ref`` is the spread level the quote is over.
    """
    pool = [leg for leg in legs if leg.kind != FUTURE]
    spreads, bought, sold = [], [], []
    for kind in (CALL, PUT):
        buys = [leg for leg in pool if leg.kind == kind and leg.qty > 0]
        sells = [leg for leg in pool if leg.kind == kind and leg.qty < 0]
        for b in list(buys):
            match = next((x for x in sells if abs(x.qty) == b.qty), None)
            if match is not None:
                spreads.append(f"{b.strike:+g}/{match.strike:+g}{'cs' if kind == CALL else 'ps'}")
                buys.remove(b)
                sells.remove(match)
        bought += buys
        sold += sells

    def single(leg) -> str:
        return f"{leg.strike:+g}{'c' if leg.kind == CALL else 'p'}"

    body = " + ".join(spreads + [single(leg) for leg in bought])
    if sold:
        body = f"{body} vs {' + '.join(single(leg) for leg in sold)}" if body else f"sell {' + '.join(single(leg) for leg in sold)}"
    sizes = {abs(leg.qty) for leg in pool}
    lots = f" x{sizes.pop():g}" if len(sizes) == 1 else ""
    price = f"{abs(net):.2f}{unit}{' credit' if net < -0.005 else ''}"
    return f"{code} {body} {price} over ref {ref:+g}{lots}"
