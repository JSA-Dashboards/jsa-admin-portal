"""Daily settlement history per contract, for the VaR covariance matrix.

Fetched from Massive and cached for hours: a settlement series changes once a day, so there
is no reason to re-request it on every Streamlit rerun. A failed fetch is NOT cached (the
cached function raises), but a failure is remembered for a few minutes so a Massive outage
doesn't cost a 10-second timeout on every click.
"""
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

import streamlit as st

from jsa_risk.config import get_massive_config
from jsa_risk.integrations import massive_client
from jsa_risk.pricing.commodities import CommoditySpec
from jsa_risk.pricing.market_hours import now_central
from jsa_risk.pricing.var import log_returns

LOOKBACK_DAYS = 450            # ~300 sessions; EWMA(0.94) gives the oldest of these ~no weight
CACHE_SECONDS = 6 * 3600
RETRY_AFTER_FAILURE_SECONDS = 600
_FAILED_AT = "_var_history_failed_at"
_FAILED_MSG = "_var_history_failed_msg"


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def _settles(commodity_code: str, key: str, today_iso: str) -> Dict[str, float]:
    config = get_massive_config()
    if config is None:
        raise RuntimeError("Massive isn't configured")
    today = date.fromisoformat(today_iso)
    prices = massive_client.fetch_daily_settles(
        config, key, commodity_code, since=today - timedelta(days=LOOKBACK_DAYS), before=today)
    return {d.isoformat(): p for d, p in prices.items()}


def get_return_history(commodity: CommoditySpec, keys: List[str]) -> Tuple[Dict[str, Dict[date, float]], str]:
    """({key: {date: daily log return}}, problem). `problem` is "" when every contract loaded;
    contracts that failed are simply absent from the dict."""
    if get_massive_config() is None:
        return {}, "Massive isn't configured, so there is no price history to estimate volatility from."

    failed_at = st.session_state.get(_FAILED_AT)
    if failed_at and time.time() - failed_at < RETRY_AFTER_FAILURE_SECONDS:
        return {}, st.session_state.get(_FAILED_MSG, "Price history is unavailable right now.")

    today = now_central().date()
    out: Dict[str, Dict[date, float]] = {}
    for key in keys:
        try:
            prices = _settles(commodity.code, key, today.isoformat())
        except Exception as e:                            # noqa: BLE001 -- surfaced, not swallowed
            msg = f"Couldn't load price history from Massive ({e})."
            st.session_state[_FAILED_AT], st.session_state[_FAILED_MSG] = time.time(), msg
            return out, msg
        out[key] = log_returns({date.fromisoformat(d): p for d, p in prices.items()})
    return out, ""
