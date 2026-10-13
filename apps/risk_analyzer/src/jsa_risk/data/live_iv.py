"""Live, per-option implied vol straight from CME DataMine for the Add Position form.

IV_SNAPSHOT holds one at-the-money vol per futures contract; a manually entered option has
its own strike and expiry, so this reads that option's own settlement vol (with skew) from
the newest DataMine file instead. The file is a few hundred KB, so it's fetched once per
half hour and shared by every session. Anything that goes wrong -- no credentials, a
product JSA isn't licensed for, CME unreachable -- just returns a reason, never an error.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import streamlit as st

from jsa_risk.config import get_cme_datamine_config
from jsa_risk.integrations.cme_datamine_client import DATAMINE_PRODUCTS, latest_available, option_iv, parse_eod_csv
from jsa_risk.pricing.commodities import CommoditySpec
from jsa_risk.pricing.symbols import MONTH_NUMBERS

_COLUMNS = ("Put/Call", "Strike Price", "Implied Volatility", "Contract Year", "Contract Month", "Contract Day")


@dataclass(frozen=True)
class LiveIv:
    iv_pct: Optional[float]
    note: str                       # one line for the UI, whether or not a vol was found


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch(commodity_code: str, api_id: str, password: str, base_url: str, token_url: str) -> dict:
    # Raises on failure, which st.cache_data deliberately doesn't cache -- a CME hiccup
    # shouldn't pin "no vol" for half an hour.
    from jsa_risk.integrations.cme_datamine_client import CmeDataMineConfig
    product = DATAMINE_PRODUCTS[commodity_code]
    config = CmeDataMineConfig(api_id, password, base_url, token_url)
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    trade_date, settlement, text = latest_available(
        config, today, 7, ("F", "P"), product.symbol, product.exchange)
    rows = [{c: r.get(c) for c in _COLUMNS} for r in parse_eod_csv(text)]
    return {"trade_date": trade_date, "settlement": settlement, "rows": rows}


def lookup_option_iv(commodity: CommoditySpec, label: str, put_call: str, strike: float) -> LiveIv:
    s = (label or "").strip().upper()
    if len(s) < 5 or s[2] not in MONTH_NUMBERS or not s[3:5].isdigit():
        return LiveIv(None, "Enter a contract symbol to pull its live vol.")
    if commodity.code not in DATAMINE_PRODUCTS:
        return LiveIv(None, f"No CME DataMine vol feed for {commodity.name} under JSA's license.")
    config = get_cme_datamine_config()
    if config is None:
        return LiveIv(None, "CME DataMine isn't configured here ([cme_datamine] secrets).")
    try:
        snap = _fetch(commodity.code, config.api_id, config.password, config.base_url, config.token_url)
    except Exception as e:
        return LiveIv(None, f"CME DataMine unavailable right now ({type(e).__name__}).")
    found = option_iv(snap["rows"], 2000 + int(s[3:5]), MONTH_NUMBERS[s[2]], put_call, strike,
                      DATAMINE_PRODUCTS[commodity.code].strike_divisor)
    if found is None:
        return LiveIv(None, f"CME lists no {s} options with a vol in its latest file.")
    kind = {"exact": "exact strike", "interpolated": "interpolated between listed strikes",
            "nearest strike": f"nearest listed strike (${found.strike:g})"}[found.method]
    settle = "Final" if snap["settlement"] == "F" else "Preliminary"
    return LiveIv(found.iv_pct, f"CME DataMine {settle} settlement {snap['trade_date']:%Y-%m-%d}, {kind}.")
