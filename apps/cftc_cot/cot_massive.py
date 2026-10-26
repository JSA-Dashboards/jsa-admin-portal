"""
cot_massive.py -- livestock futures settles from the Massive REST API (api.massive.com/futures/v1).

Only for the price-move chart. The grains come from the Snowflake settlement bank; live cattle,
feeder cattle and lean hogs are not in it, so they are fetched here. Named cot_massive, NOT
massive_api: the admin portal runs many apps in one process and grain_seasonal already owns
`massive_api` in sys.modules (river_fob hit the same collision).

Contract notes (see the livestock seasonal dashboard): LE live cattle (Feb/Apr/Jun/Aug/Oct/Dec),
GF feeder cattle (Jan/Mar/Apr/May/Aug/Sep/Oct/Nov), HE lean hogs (Feb/Apr/May/Jun/Jul/Aug/Oct/Dec),
all quoted in cents/lb. They are cash-settled, so there is no first notice day: a contract is the
front month until its last trading day.
"""
import re
from datetime import date

import pandas as pd
import requests

BASE_URL = "https://api.massive.com/futures/v1"
_TICKER_RE = re.compile(r"^([A-Z]{1,3})([FGHJKMNQUVXZ])(\d)$")


class MassiveError(RuntimeError):
    pass


def _get(path: str, api_key: str, params: dict | None = None) -> dict:
    r = requests.get(f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {api_key}"},
                     params=params or {}, timeout=25)
    if r.status_code != 200:
        raise MassiveError(f"Massive {path} returned {r.status_code}: {r.text[:200]}")
    return r.json()


def nearest_contracts(product: str, api_key: str, as_of: date, n: int = 2) -> list[dict]:
    """The next `n` outright contracts that have not expired, nearest first: ticker, month, year, expiry."""
    data = _get("/contracts", api_key, {"product_code": product, "active": "true",
                                        "date": as_of.isoformat(), "limit": 400})
    rows = {}
    for r in data.get("results", []):
        t = r.get("ticker", "")
        m = _TICKER_RE.match(t)
        exp = r.get("settlement_date") or r.get("last_trade_date")
        if not (m and t.startswith(product) and exp):
            continue
        rows[t] = {"ticker": t, "month": m.group(2), "expiry": pd.to_datetime(exp).date()}
    out = sorted(rows.values(), key=lambda r: r["expiry"])
    for r in out:
        r["year"] = r["expiry"].year        # single-digit ticker year is the expiry year's last digit
    return [r for r in out if r["expiry"] >= as_of][:n]


def settled_history(ticker: str, api_key: str, since: date) -> pd.Series:
    """Daily SETTLEMENT prices only, indexed by trading date. A session still open has
    settlement_price 0, and a close is not a settle, so those bars are left out."""
    data = _get(f"/aggs/{ticker}", api_key, {"resolution": "1session", "limit": 50000})
    rows = {}
    for bar in data.get("results", []):
        day, px = bar.get("session_end_date"), bar.get("settlement_price")
        if day and px:
            d = pd.to_datetime(day).date()
            if d >= since:
                rows[d] = float(px)
    return pd.Series(rows, dtype=float).sort_index()


def livestock_settles(api_key: str, as_of: date, since: date, products=("LE", "GF", "HE")) -> pd.DataFrame:
    """Bank-shaped rows (product_code, month, year, date, settle) plus `expiry`, for the next two
    contracts of each livestock product."""
    frames = []
    for p in products:
        for c in nearest_contracts(p, api_key, as_of):
            s = settled_history(c["ticker"], api_key, since)
            if s.empty:
                continue
            frames.append(pd.DataFrame({"product_code": p, "month": c["month"], "year": c["year"],
                                        "date": pd.to_datetime(list(s.index)), "settle": s.values,
                                        "expiry": c["expiry"]}))
    cols = ["product_code", "month", "year", "date", "settle", "expiry"]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
