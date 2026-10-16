"""
The computable half of the Technicals section: moving averages and the recent
highs and lows the letter quotes as support and resistance.

WHAT THIS DOES NOT DO. The letter's technical read is part arithmetic and part
judgment -- "markets technically haven't done major damage but need to keep
finding support at 20-day" is not derivable from a price series, and nothing
here tries. The moving averages, the prior session's high and low, and the
recent swing extremes are computed; the interpretation stays a commentary slot.

The 9-day and 20-day are SIMPLE moving averages of daily settlements, which is
the convention the letter has been using (the 9-day quoted at 216.75 on
9/15/26 against a 215.925 October settle is a simple mean, not exponential).
Confirm against a letter you have already sent before trusting the first run.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import sources


def fetch_ohlc(ticker: str, api_key: str) -> pd.DataFrame:
    """
    Daily bars for one contract, indexed by session date.

    massive_api.get_settlement_history() keeps only the settle, but the same
    /aggs endpoint returns the full bar, and the letter's "traded below
    yesterday's low" lines need the low. Field names are probed rather than
    assumed -- the API has been seen using both long and single-letter keys, and
    a missing low degrades this to a settle-only frame rather than raising.
    """
    api = sources._massive()
    data = api._get(f"/aggs/{ticker}", api_key, params={"resolution": "1session", "limit": 5000})

    rows = []
    for bar in data.get("results", []):
        day = bar.get("session_end_date")
        if not day:
            continue

        def pick(*keys):
            for k in keys:
                v = bar.get(k)
                if isinstance(v, (int, float)) and v:
                    return float(v)
            return None

        close = pick("settlement_price", "close", "c")
        if close is None:
            continue
        rows.append({
            "date": pd.to_datetime(day).date(),
            "open": pick("open", "o"),
            "high": pick("high", "h"),
            "low": pick("low", "l"),
            "close": close,
        })

    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    return pd.DataFrame(rows).set_index("date").sort_index()


def moving_averages(closes: pd.Series, windows=(9, 20)) -> dict:
    """Simple moving average of daily settles for each window."""
    out = {}
    s = closes.dropna()
    for w in windows:
        out[w] = round(float(s.tail(w).mean()), 3) if len(s) >= w else None
    return out


def levels(ohlc: pd.DataFrame, swing_lookback: int = 20) -> dict:
    """
    The price levels the letter names: the prior session's high and low, and the
    highest high / lowest low of the recent swing.

    The swing extremes are what "resistance above at 223.60" tends to be -- the
    last place the contract turned -- but the letter's published figure is Ross's
    read, not this number. These are offered as a starting point and labelled as
    such in the draft, never printed as though they were the letter's own call.
    """
    if ohlc.empty:
        return {}
    have_low = "low" in ohlc and ohlc["low"].notna().any()
    have_high = "high" in ohlc and ohlc["high"].notna().any()

    prior = ohlc.iloc[-2] if len(ohlc) > 1 else None
    recent = ohlc.tail(swing_lookback)

    return {
        "last_close": round(float(ohlc["close"].iloc[-1]), 3),
        "last_date": ohlc.index[-1].isoformat(),
        "prior_low": round(float(prior["low"]), 3) if prior is not None and have_low and pd.notna(prior.get("low")) else None,
        "prior_high": round(float(prior["high"]), 3) if prior is not None and have_high and pd.notna(prior.get("high")) else None,
        "swing_low": round(float(recent["low"].min()), 3) if have_low else None,
        "swing_high": round(float(recent["high"].max()), 3) if have_high else None,
        "swing_days": int(len(recent)),
    }


def build(ticker: str, api_key: str, windows=(9, 20)) -> dict:
    """
    Everything the Technicals block needs for one contract.

    A MOVING AVERAGE OVER A SERIES WITH HOLES IS WRONG, NOT APPROXIMATE. On
    2026-09-22 Massive's history carried no bars at all for 09-14..09-18, so a
    "9-day" mean was really nine of the last fourteen sessions and read 216.392
    where the letter's own figure was 218.90. The averages are still computed --
    they are useful when the series is whole -- but `complete` records whether
    they can be trusted, and the renderer marks them rather than printing a
    number that is quietly two dollars out.
    """
    ohlc = fetch_ohlc(ticker, api_key)
    if ohlc.empty:
        return {"ticker": ticker, "error": "no bars returned"}

    out = {"ticker": ticker, "month": sources.contract_month(ticker)}
    out["ma"] = moving_averages(ohlc["close"], windows)
    out.update(levels(ohlc))

    span = max(windows) if windows else 20
    tail = ohlc.tail(span)
    gaps = sources.session_gaps(tail.index, tail.index[0], tail.index[-1]) if len(tail) else []
    out["gaps"] = [d.isoformat() for d in gaps]
    out["complete"] = not gaps
    return out
