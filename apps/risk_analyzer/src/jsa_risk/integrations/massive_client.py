"""Live futures-price fetch from Massive — a direct port of the JSA Risk Analyzer HTML
tool's refreshPricesFromMassive(). Runs server-side now: the API key lives in Streamlit
secrets and never reaches the browser, unlike the original where it sat in plain
client-side JS (the HTML tool's own file even carried a comment warning about that).

Kept free of Streamlit/Snowflake imports — pure request-building/parsing logic, so it's
unit-testable with a mocked `requests.get`. The caller (a page) is responsible for writing
results through `reference_repo.set_contract_price()` and logging via `data/audit_repo.py`.
"""
import json
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

from jsa_risk.config import MassiveConfig

CANONICAL_KEY_RE = re.compile(r"^[A-Z]\d{2}$")
RETRY_DELAY_SECONDS = 0.8


@dataclass(frozen=True)
class MassiveFetchResult:
    updated: Dict[str, float]  # canonical_key -> price ($/bu)
    timeframe: Optional[str]


def canonical_key_to_massive_ticker(key: str, commodity_code: str = "ZC") -> str:
    """Massive's outright futures tickers are the 2-letter product code + month letter +
    the LAST digit of the year (e.g. corn's canonical key "Z26" -> "ZCZ6"); our decoder
    always keys by month letter + 2-digit year, so this only ever needs the final digit."""
    return f"{commodity_code}{key[0]}{key[-1]}"


def _fetch_json(url: str, params: dict) -> dict:
    resp = requests.get(url, params=params, timeout=10)
    body_text = resp.text
    try:
        payload = json.loads(body_text)
    except ValueError:
        snippet = (body_text or f"HTTP {resp.status_code}")[:120]
        raise RuntimeError(f"upstream returned a non-JSON response ({snippet})")
    if not resp.ok or payload.get("status") == "ERROR":
        raise RuntimeError(payload.get("error") or f"HTTP {resp.status_code}")
    return payload


def fetch_futures_prices(
    config: MassiveConfig, canonical_keys: List[str], commodity_code: str = "ZC"
) -> MassiveFetchResult:
    """One quiet retry after ~800ms — a gateway hiccup or rate limit can return a plain-text
    body (not JSON), almost always a transient upstream timeout, matching the original
    tool's fix. Raises on a second failure; the caller decides how to surface that."""
    keys = [k for k in canonical_keys if CANONICAL_KEY_RE.match(k)]
    if not keys:
        return MassiveFetchResult(updated={}, timeframe=None)

    tickers = [canonical_key_to_massive_ticker(k, commodity_code) for k in keys]
    url = f"{config.base_url}/futures/v1/snapshot"
    params = {"ticker.any_of": ",".join(tickers), "apiKey": config.api_key}

    try:
        payload = _fetch_json(url, params)
    except Exception as first_err:
        time.sleep(RETRY_DELAY_SECONDS)
        try:
            payload = _fetch_json(url, params)
        except Exception:
            raise first_err

    results = payload.get("results") or []
    updated: Dict[str, float] = {}
    timeframe = None
    for r in results:
        ticker = (r.get("details") or {}).get("ticker")
        last_trade = r.get("last_trade") or {}
        price = last_trade.get("price")
        if not ticker or price is None:
            continue
        # ticker e.g. "ZCZ6" -> canonical key "Z26": month letter stays, single year digit
        # expands back to a 2-digit year by matching it against the keys we actually asked for.
        month_letter, year_digit = ticker[2], ticker[3]
        match_key = next((k for k in keys if k[0] == month_letter and k[-1] == year_digit), None)
        if not match_key:
            continue
        updated[match_key] = price / 100  # cents/bu -> $/bu, same convention as everywhere else
        timeframe = timeframe or last_trade.get("timeframe")
    return MassiveFetchResult(updated=updated, timeframe=timeframe)
