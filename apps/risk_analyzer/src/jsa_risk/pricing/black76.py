"""Black-76 option-on-futures pricing, ported from the JSA Risk Analyzer HTML tool.

Uses scipy's normal CDF/PDF in place of the original's hand-rolled Abramowitz-Stegun
erf approximation — an intentional precision improvement, not a required byte-for-byte
port. Theta is carried over exactly as coded: a simplified formula (no discrete
r*K*e^-rT*N(d2) term), identical for calls and puts.
"""
from dataclasses import dataclass
import math

from scipy.stats import norm

RATE = 0.045  # flat risk-free/discount rate, matches the original tool


@dataclass(frozen=True)
class Black76Result:
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float


def black76(F: float, K: float, T: float, sigma_pct: float, is_call: bool) -> Black76Result:
    sigma = max(sigma_pct, 0.0001) / 100

    if T <= 0:
        intrinsic = max(F - K, 0.0) if is_call else max(K - F, 0.0)
        if is_call:
            delta = 1.0 if F > K else 0.0
        else:
            delta = -1.0 if F < K else 0.0
        return Black76Result(price=intrinsic, delta=delta, gamma=0.0, vega=0.0, theta=0.0)

    sqrt_t = math.sqrt(T)
    d1 = (math.log(F / K) + (sigma * sigma / 2) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    df = math.exp(-RATE * T)
    pdf1 = norm.pdf(d1)

    if is_call:
        price = df * (F * norm.cdf(d1) - K * norm.cdf(d2))
        delta = df * norm.cdf(d1)
    else:
        price = df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))
        delta = -df * norm.cdf(-d1)

    gamma = df * pdf1 / (F * sigma * sqrt_t)
    vega = F * df * pdf1 * sqrt_t
    theta = RATE * price - (F * df * pdf1 * sigma) / (2 * sqrt_t)

    return Black76Result(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta)


@dataclass(frozen=True)
class ScaledGreeks:
    delta_d: float
    gamma_d: float
    vega_d: float
    theta_d: float


def scale_greeks(result: Black76Result, qty: int, mult: int = 5000) -> ScaledGreeks:
    """$-scale an option's per-unit Greeks by position size (qty * bu-per-contract)."""
    pos_mult = qty * mult
    return ScaledGreeks(
        delta_d=result.delta * pos_mult,
        gamma_d=result.gamma * pos_mult,
        vega_d=(result.vega / 100) * pos_mult,
        theta_d=(result.theta / 365) * pos_mult,
    )
