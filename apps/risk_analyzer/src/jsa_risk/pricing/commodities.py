"""Per-commodity contract specs. The dashboard prices exactly one commodity per session
(see state.py's commodity_code) -- everything that differs by product (contract size,
quoting unit, which months are actually listed futures vs. serial-option-only, a rough
daily-vol estimate for VaR) funnels through the CommoditySpec for that selection instead
of being hardcoded to corn.

`code` is also the raw symbol prefix (e.g. "ZCZ26"'s "ZC") and the prefix used to keep
each commodity's reference data (contract marks, IV snapshot, prior settles) from
colliding in Snowflake, since those tables are keyed by canonical key alone -- see
`reference_key()`. All codes here are exactly 2 characters; that invariant is relied on
wherever a stored key is de-prefixed back to its bare canonical key (state.py).
"""
from dataclasses import dataclass
from datetime import time
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class CommoditySpec:
    code: str                 # 2-letter CME/Globex root, e.g. "ZC"
    name: str                  # "Corn"
    unit: str                  # "bu", "lb" or "ton" -- the pricing/quoting unit
    contract_size: int         # units per contract, e.g. 5000 bu, 40000 lb
    listed_months: List[str]   # month letters with a real listed future, in calendar order
    daily_vol: float           # assumed 1-day price-move fraction, for the delta-normal VaR estimate
    default_price: float       # fallback mark when no real one has been entered/seeded yet --
                               # a rough, round starting point in this commodity's own unit,
                               # NOT a live quote. Using corn's $/bu number for a $/lb commodity
                               # (or vice versa) silently makes every option look absurdly deep
                               # in- or out-of-the-money, which is exactly what happened before
                               # this field existed: a live cattle book priced off corn's $4.62
                               # default showed near-zero delta on puts struck near real cattle
                               # levels (~$2/lb) because they looked wildly out-of-the-money
                               # against that phantom ~$4.62/lb "future".
    icon: str = "📈"
    # Grains stop being the contract to price off once their own month begins (corn's last
    # trade day is ~2 weeks before the month starts), so options tied to it roll to the next
    # listed contract on the 1st. Cattle trade through their own contract month, so for them
    # a contract stays current until the month is over.
    rolls_at_month_start: bool = True
    # When the market is open, in US Central time. The day session runs to 2:00 pm -- a little
    # past the actual close (1:20 pm grains, 1:05 pm cattle) so the exchange has posted its
    # settlement before we start asking for it. Grains also trade an overnight session that
    # begins the evening before (Sun-Thu) and runs to the next morning; cattle has none.
    day_session: Tuple[time, time] = (time(8, 30), time(14, 0))
    overnight_session: Optional[Tuple[time, time]] = (time(19, 0), time(7, 45))
    # How many of the exchange's / broker's quoted price units make one of `unit`: corn,
    # soybeans and cattle quote in cents (100 -> dollars), soybean meal quotes in dollars per
    # short ton already (1). Applies to Massive prices and to QST strike/entry/last-tick columns.
    price_divisor: float = 100.0

    @property
    def quote_unit(self) -> str:
        """The unit prices are QUOTED in, e.g. "cents/bu" or "$/ton"."""
        return f"cents/{self.unit}" if self.price_divisor == 100 else f"$/{self.unit}"

    @property
    def move_symbol(self) -> str:
        """Symbol for a price move in the quoting unit: "¢" for cents-quoted products, "$"."""
        return "¢" if self.price_divisor == 100 else "$"


CORN = CommoditySpec(
    code="ZC", name="Corn", unit="bu", contract_size=5000,
    listed_months=["H", "K", "N", "U", "Z"], daily_vol=0.016, default_price=4.62, icon="🌽",
)
SOYBEANS = CommoditySpec(
    code="ZS", name="Soybeans", unit="bu", contract_size=5000,
    listed_months=["F", "H", "K", "N", "Q", "U", "X"], daily_vol=0.017, default_price=10.50, icon="🫘",
)
LIVE_CATTLE = CommoditySpec(
    code="LE", name="Live Cattle", unit="lb", contract_size=40000,
    listed_months=["G", "J", "M", "Q", "V", "Z"], daily_vol=0.011, default_price=2.20, icon="🐄",
    rolls_at_month_start=False, overnight_session=None,
)
SOYBEAN_MEAL = CommoditySpec(
    code="ZM", name="Soybean Meal", unit="ton", contract_size=100,
    listed_months=["F", "H", "K", "N", "Q", "U", "V", "Z"], daily_vol=0.015, default_price=300.0,
    icon="🥜", price_divisor=1.0,
)
FEEDER_CATTLE = CommoditySpec(
    code="GF", name="Feeder Cattle", unit="lb", contract_size=50000,
    listed_months=["F", "H", "J", "K", "Q", "U", "V", "X"], daily_vol=0.012, default_price=2.60, icon="🐂",
    rolls_at_month_start=False, overnight_session=None,
)

COMMODITIES: Dict[str, CommoditySpec] = {
    c.code: c for c in [CORN, SOYBEANS, SOYBEAN_MEAL, LIVE_CATTLE, FEEDER_CATTLE]
}


def get_commodity(code: str) -> CommoditySpec:
    return COMMODITIES.get(code, CORN)


def reference_key(commodity: CommoditySpec, canonical_key: str) -> str:
    """The key actually stored in Snowflake's reference-data tables -- the commodity's
    2-letter code plus the bare 3-char canonical key (e.g. "ZC" + "Z26" -> "ZCZ26"),
    so Dec corn and Dec soybeans never collide despite sharing a canonical key."""
    return f"{commodity.code}{canonical_key}"
