"""Value at Risk for the book: delta-normal over PER-CONTRACT risk factors, with an EWMA
covariance matrix estimated from each contract's own daily log returns.

Why per contract: a calendar spread (long one month, short another) is delta-neutral in
aggregate but still carries the risk that the two legs diverge. A single net-delta number
shows it as zero risk; a covariance matrix over the individual contracts does not -- the
VaR of a hedge shrinks with the legs' correlation and no further.

    exposure_k  = $ delta of the book to contract k  (units of delta x that contract's price,
                  i.e. the $ P&L for a 100% move; options contribute their delta)
    C           = EWMA covariance matrix of the contracts' daily log returns (RiskMetrics
                  style: zero mean, decay lambda = 0.94, so recent days dominate)
    sigma_p     = sqrt(exposure' C exposure)            # 1-day $ standard deviation
    VaR         = z x sigma_p                           # z = 1.645 for 95% one-sided

Gamma and vega are NOT in this number: it is linear in the factors. A contract with too little
history borrows the vol and correlations of the nearest contract that has enough; if nothing
has enough, the whole calculation falls back to one assumed daily vol on the net exposure.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np

Z_95 = 1.645
CORN_DAILY_VOL = 0.016
EWMA_LAMBDA = 0.94
MIN_OBSERVATIONS = 30

_MONTHS = "FGHJKMNQUVXZ"


def value_at_risk(net_delta_d: float, daily_vol: float = CORN_DAILY_VOL, z: float = Z_95) -> float:
    """Single-factor delta-normal VaR. `net_delta_d` is a DOLLAR exposure (delta in units x
    price), not bushels/pounds -- multiplying a unit delta by a fractional vol gives nothing
    meaningful until it is priced."""
    return z * abs(net_delta_d) * daily_vol


@dataclass(frozen=True)
class ContractRisk:
    key: str
    exposure: float                   # $ delta
    daily_vol: float                  # 1-day log-return vol used for this contract
    component_var: float              # its share of the book's VaR (these sum to the VaR)
    observations: int                 # daily returns behind its own vol (0 when borrowed)
    proxy: Optional[str] = None       # contract whose vol/correlations it borrowed, if any


@dataclass(frozen=True)
class VarResult:
    var: float
    method: str                       # "covariance" or "fixed"
    z: float
    contracts: List[ContractRisk] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    fixed_vol: Optional[float] = None


def key_order(key: str) -> Tuple[int, int]:
    """Calendar position of a canonical key like 'Z26' (year, month) -- for 'nearest contract'."""
    try:
        return int(key[1:]), _MONTHS.index(key[0])
    except (ValueError, IndexError):
        return 0, 0


def _ordinal(key: str) -> int:
    y, m = key_order(key)
    return y * 12 + m


def log_returns(prices: Dict[date, float]) -> Dict[date, float]:
    """Daily log returns keyed by the later date. Non-positive prices are skipped (a bad bar
    must not become a NaN that poisons the matrix)."""
    ds = sorted(d for d, p in prices.items() if p and p > 0)
    return {b: float(np.log(prices[b] / prices[a])) for a, b in zip(ds, ds[1:])}


def ewma_covariance(
    returns: Dict[str, Dict[date, float]], lam: float = EWMA_LAMBDA
) -> Tuple[List[str], np.ndarray]:
    """Zero-mean EWMA covariance over the given contracts. Weight of a day is lam^(age),
    age counted in trading days back from the most recent date any contract has. A pair uses
    only the days BOTH traded, normalised by the weight of those days, so a younger contract
    doesn't have its covariances dragged toward zero by its missing history."""
    keys = sorted(returns, key=key_order)
    all_dates = sorted({d for r in returns.values() for d in r})
    age = {d: len(all_dates) - 1 - i for i, d in enumerate(all_dates)}
    n = len(keys)
    cov = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            ri, rj = returns[keys[i]], returns[keys[j]]
            common = ri.keys() & rj.keys()
            if not common:
                continue
            w = np.array([lam ** age[d] for d in common])
            x = np.array([ri[d] * rj[d] for d in common])
            cov[i, j] = cov[j, i] = float((w * x).sum() / w.sum())
    return keys, _repair(cov)


def _repair(cov: np.ndarray) -> np.ndarray:
    """Pairwise estimation can leave the matrix very slightly non-positive-semidefinite, which
    would make exposure' C exposure negative for some books. Clip negative eigenvalues to zero
    and restore the original variances on the diagonal."""
    if cov.size == 0:
        return cov
    vals, vecs = np.linalg.eigh(cov)
    if vals.min() >= 0:
        return cov
    fixed = (vecs * np.clip(vals, 0, None)) @ vecs.T
    d_old = np.sqrt(np.clip(np.diag(cov), 0, None))
    d_new = np.sqrt(np.clip(np.diag(fixed), 1e-30, None))
    return fixed * np.outer(d_old / d_new, d_old / d_new)


def book_var(
    exposures: Dict[str, float],
    returns: Dict[str, Dict[date, float]],
    fallback_vol: float,
    z: float = Z_95,
    lam: float = EWMA_LAMBDA,
    min_obs: int = MIN_OBSERVATIONS,
) -> VarResult:
    """1-day VaR of a book given its $ exposure per contract and each contract's return
    history. `returns` may hold more contracts than the book: the extras serve as proxies."""
    live = {k: e for k, e in exposures.items() if e}
    if not live:
        return VarResult(var=0.0, method="covariance", z=z)

    # The factor universe is every contract with enough history, in the book or not: a young
    # contract in the book can then borrow from an established one that isn't held.
    usable = [k for k, r in returns.items() if len(r) >= min_obs]
    if not usable:
        net = sum(live.values())
        return VarResult(
            var=value_at_risk(net, fallback_vol, z), method="fixed", z=z, fixed_vol=fallback_vol,
            notes=[f"No contract has {min_obs} daily returns of history, so this uses an "
                   f"assumed {fallback_vol * 100:.1f}% daily move on the net exposure."],
        )

    factor_keys, cov_u = ewma_covariance({k: returns[k] for k in usable}, lam)
    idx = {k: i for i, k in enumerate(factor_keys)}
    notes: List[str] = []
    factor_of: Dict[str, str] = {}
    for k in live:
        if k in idx:
            factor_of[k] = k
        else:                                      # too little history: borrow the nearest contract
            near = min(factor_keys, key=lambda u: abs(_ordinal(u) - _ordinal(k)))
            factor_of[k] = near
            notes.append(f"{k} has under {min_obs} days of history, so it uses {near}'s volatility "
                         "and moves one-for-one with it.")

    keys = sorted(live, key=key_order)
    m = [idx[factor_of[k]] for k in keys]
    cov = cov_u[np.ix_(m, m)]
    d = np.array([live[k] for k in keys])
    sigma = float(np.sqrt(max(float(d @ cov @ d), 0.0)))
    marginal = (cov @ d) / sigma if sigma > 0 else np.zeros_like(d)

    contracts = [
        ContractRisk(
            key=k, exposure=float(d[i]), daily_vol=float(np.sqrt(cov[i, i])),
            component_var=float(z * d[i] * marginal[i]),
            observations=len(returns.get(k, {})) if k in idx else 0,
            proxy=None if k in idx else factor_of[k],
        )
        for i, k in enumerate(keys)
    ]
    return VarResult(var=z * sigma, method="covariance", z=z, contracts=contracts, notes=notes)
