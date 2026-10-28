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
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import requests

from jsa_risk.config import MassiveConfig

CANONICAL_KEY_RE = re.compile(r"^[A-Z]\d{2}$")
RETRY_DELAY_SECONDS = 0.8


# A settlement price further than this from the last trade is treated as unusable (wrong
# units, a stale or placeholder value) rather than marked into the book.
SETTLE_SANITY_BAND = 0.20

BASIS_LAST = "last trade"
BASIS_SETTLE = "settlement"
BASIS_SETTLE_MISSING = "last trade (no settlement posted yet)"


@dataclass(frozen=True)
class MassiveFetchResult:
    updated: Dict[str, float]  # canonical_key -> price ($/bu)
    timeframe: Optional[str]
    # canonical_key -> which Massive field the price came from (BASIS_*)
    basis: Dict[str, str] = field(default_factory=dict)
    # canonical_key -> what Massive actually sent for that contract (last trade, the session's
    # settlement fields, and which session keys exist), so a "why not the settle?" question is
    # answered from the data rather than guessed at.
    detail: Dict[str, dict] = field(default_factory=dict)


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


def describe_row(result: dict) -> dict:
    last = result.get("last_trade") or {}
    session = result.get("session") or {}
    return {
        "last_trade": last.get("price"),
        "last_trade_at": last.get("last_updated") or last.get("sip_timestamp"),
        "settlement_price": session.get("settlement_price"),
        "previous_settlement": session.get("previous_settlement"),
        "session_close": session.get("close"),
        "session_fields": ", ".join(sorted(session)) or "(none)",
    }


def pick_price(result: dict, use_settlement: bool):
    """(price in Massive's own units, basis) for one snapshot row, or (None, None).

    Market open -> the last trade. Market closed -> the exchange's official settle, falling
    back to the last trade (and saying so) when no usable settlement is there.

    The official settle is the snapshot's session.previous_settlement, NOT session.settlement_price:
    observed on Massive after the close, settlement_price just repeats the last trade / session
    close (it is the live price the day's change is measured from), while previous_settlement
    holds the latest official settle -- today's, once the exchange has posted it (Feb live
    cattle: 230.875 there against yesterday's 229.625, matching CME)."""
    last = (result.get("last_trade") or {}).get("price")
    if not use_settlement:
        return (last, BASIS_LAST) if last is not None else (None, None)
    settle = (result.get("session") or {}).get("previous_settlement")
    if settle is not None and settle > 0 and (
        last is None or abs(settle - last) <= SETTLE_SANITY_BAND * last
    ):
        return settle, BASIS_SETTLE
    return (last, BASIS_SETTLE_MISSING) if last is not None else (None, None)


def fetch_futures_prices(
    config: MassiveConfig, canonical_keys: List[str], commodity_code: str = "ZC",
    use_settlement: bool = False, price_divisor: float = 100.0,
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
    basis: Dict[str, str] = {}
    detail: Dict[str, dict] = {}
    timeframe = None
    for r in results:
        ticker = (r.get("details") or {}).get("ticker")
        last_trade = r.get("last_trade") or {}
        price, how = pick_price(r, use_settlement)
        if not ticker or price is None:
            continue
        # ticker e.g. "ZCZ6" -> canonical key "Z26": month letter stays, single year digit
        # expands back to a 2-digit year by matching it against the keys we actually asked for.
        month_letter, year_digit = ticker[2], ticker[3]
        match_key = next((k for k in keys if k[0] == month_letter and k[-1] == year_digit), None)
        if not match_key:
            continue
        updated[match_key] = price / price_divisor  # cents -> $ (or $/ton as-is), the app's unit
        basis[match_key] = how
        detail[match_key] = {**describe_row(r), "used": how}
        timeframe = timeframe or last_trade.get("timeframe")
    return MassiveFetchResult(updated=updated, timeframe=timeframe, basis=basis, detail=detail)


def fetch_daily_settles(
    config: MassiveConfig, canonical_key: str, commodity_code: str = "ZC",
    since: Optional[date] = None, before: Optional[date] = None,
) -> Dict[date, float]:
    """One contract's daily settlement prices, {trading date: price}, from Massive's session
    bars (`/futures/v1/aggs/{ticker}?resolution=1session`). Each session bar carries the
    exchange's settlement_price; the bar's close stands in for the rare bar without one.
    Prices stay in Massive's own units (cents) -- only returns are built from them, so the
    unit never matters. Sessions on or after `before` are left out (today's isn't final).

    Raises on a failed request, so the caller's cache never stores an empty history."""
    if not CANONICAL_KEY_RE.match(canonical_key):
        return {}
    ticker = canonical_key_to_massive_ticker(canonical_key, commodity_code)
    url = f"{config.base_url}/futures/v1/aggs/{ticker}"
    params = {"resolution": "1session", "limit": 5000, "apiKey": config.api_key}
    if since is not None:
        params["window_start.gte"] = since.isoformat()

    prices: Dict[date, float] = {}
    for _ in range(20):                                   # pages; one is normally plenty
        payload = _fetch_json(url, params)
        for bar in payload.get("results") or []:
            day, px = bar.get("session_end_date"), bar.get("settlement_price") or bar.get("close")
            if not day or not px:
                continue
            d = date.fromisoformat(day)
            if before is None or d < before:
                prices[d] = float(px)
        next_url = payload.get("next_url")
        if not next_url:
            break
        url, params = next_url, {"apiKey": config.api_key}
    return prices
