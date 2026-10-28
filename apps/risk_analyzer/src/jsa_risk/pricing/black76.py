"""Option-on-futures pricing: Black-76 (European) and, for the book, its American-exercise
counterpart.

Black-76 was ported from the JSA Risk Analyzer HTML tool. It uses scipy's normal CDF/PDF in
place of the original's hand-rolled Abramowitz-Stegun erf approximation -- an intentional
precision improvement, not a required byte-for-byte port. Its theta is carried over exactly
as coded: a simplified formula (no discrete r*K*e^-rT*N(d2) term), identical for calls and
puts.
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

    # log(F/K) is undefined for a non-positive forward or strike (a zeroed contract mark or a
    # bad strike in the book): price it at intrinsic rather than crash the whole page.
    if T <= 0 or F <= 0 or K <= 0:
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


# --- American exercise -------------------------------------------------------------------
# Every option the book trades (CBOT corn/soybeans, CME cattle) is American-style, so the
# model prices with the Barone-Adesi & Whaley (1987) approximation for an option on a future:
# the European Black-76 value plus an early-exercise premium. It is exact at expiry, never
# below the European value or intrinsic, and accurate to a fraction of a tick for these
# maturities (checked against a 1000-step binomial tree in tests/test_american.py).

def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _european(F: float, K: float, T: float, sigma: float, is_call: bool) -> float:
    """Black-76 price with `sigma` as a decimal (0.25 = 25%)."""
    sqrt_t = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    df = math.exp(-RATE * T)
    if is_call:
        return df * (F * _cdf(d1) - K * _cdf(d2))
    return df * (K * _cdf(-d2) - F * _cdf(-d1))


def _intrinsic(F: float, K: float, is_call: bool) -> float:
    return max(F - K, 0.0) if is_call else max(K - F, 0.0)


def _american_price(F: float, K: float, T: float, sigma: float, is_call: bool) -> float:
    """Barone-Adesi-Whaley price of an American option on a future (cost of carry b = 0)."""
    if T <= 0 or F <= 0 or K <= 0:
        return _intrinsic(F, K, is_call)
    euro = _european(F, K, T, sigma, is_call)
    if RATE <= 0:
        return euro                          # no discounting -> early exercise is never optimal
    df = math.exp(-RATE * T)
    sig2 = sigma * sigma
    k = 2.0 * RATE / (sig2 * (1.0 - df))
    root = math.sqrt(1.0 + 4.0 * k)
    sqrt_t = math.sqrt(T)

    def d1(s: float) -> float:
        return (math.log(s / K) + 0.5 * sig2 * T) / (sigma * sqrt_t)

    if is_call:
        q = (1.0 + root) / 2.0

        def gap(s: float) -> float:          # exercise value - (European + premium) at s
            return s - K - _european(s, K, T, sigma, True) - (1.0 - df * _cdf(d1(s))) * s / q

        lo, hi = K, K * 2.0
        if gap(lo) >= 0:
            return euro
        while gap(hi) < 0 and hi < K * 1e4:
            hi *= 2.0
        if gap(hi) < 0:
            return euro
        s_star = _bisect(gap, lo, hi)
        if F >= s_star:
            return F - K
        a2 = (s_star / q) * (1.0 - df * _cdf(d1(s_star)))
        return euro + a2 * (F / s_star) ** q

    q = (1.0 - root) / 2.0                   # negative root

    def gap(s: float) -> float:
        return K - s - _european(s, K, T, sigma, False) + (1.0 - df * _cdf(-d1(s))) * s / q

    lo, hi = K * 1e-6, K
    if gap(hi) >= 0:
        return euro
    if gap(lo) <= 0:
        return euro
    s_star = _bisect(gap, lo, hi)
    if F <= s_star:
        return K - F
    a1 = -(s_star / q) * (1.0 - df * _cdf(-d1(s_star)))
    return euro + a1 * (F / s_star) ** q


def _bisect(f, lo: float, hi: float) -> float:
    flo = f(lo)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if (fm < 0) == (flo < 0):
            lo, flo = mid, fm
        else:
            hi = mid
        if hi - lo < 1e-6 * hi:
            break
    return 0.5 * (lo + hi)


def american(
    F: float, K: float, T: float, sigma_pct: float, is_call: bool, greeks: bool = True
) -> Black76Result:
    """Price and Greeks for an American option on a future. Same units/conventions as
    `black76` (delta per $1 of futures, gamma per $1^2, vega per 1.00 of vol, theta per year),
    but the Greeks are numerical derivatives of the American price (zeros with greeks=False)."""
    sigma = max(sigma_pct, 0.0001) / 100
    if T <= 0 or F <= 0 or K <= 0:
        return black76(F, K, T, sigma_pct, is_call)

    price = _american_price(F, K, T, sigma, is_call)
    if not greeks:                           # scenario P&L only needs the price -- ~8x cheaper
        return Black76Result(price=price, delta=0.0, gamma=0.0, vega=0.0, theta=0.0)

    h = F * 0.005
    up = _american_price(F + h, K, T, sigma, is_call)
    dn = _american_price(max(F - h, F * 1e-6), K, T, sigma, is_call)
    delta = (up - dn) / (F + h - max(F - h, F * 1e-6))
    gamma = (up - 2.0 * price + dn) / (h * h)

    dv = min(0.005, sigma / 2)
    vega = (_american_price(F, K, T, sigma + dv, is_call)
            - _american_price(F, K, T, sigma - dv, is_call)) / (2.0 * dv)

    day = 1.0 / 365.0
    t1 = max(T - day, 0.0)
    theta = (_american_price(F, K, t1, sigma, is_call) - price) / (T - t1) if T > t1 else 0.0

    return Black76Result(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta)
