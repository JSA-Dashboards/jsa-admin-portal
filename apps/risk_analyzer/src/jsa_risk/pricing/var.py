"""Delta-normal Value at Risk, ported from the JSA Risk Analyzer HTML tool.

Fixed 1.6% assumed daily corn futures move (not derived from position IVs), 1-day,
95% one-sided confidence (z=1.645).
"""

Z_95 = 1.645
CORN_DAILY_VOL = 0.016


def value_at_risk(net_delta_d: float, daily_vol: float = CORN_DAILY_VOL, z: float = Z_95) -> float:
    return z * abs(net_delta_d) * daily_vol
