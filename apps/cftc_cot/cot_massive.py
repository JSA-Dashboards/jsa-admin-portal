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
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

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


MONTH_NUM = dict(zip("FGHJKMNQUVXZ", range(1, 13)))
LIVESTOCK_MONTHS = {"LE": "GJMQVZ", "GF": "FHJKQUVX", "HE": "GJKMNQVZ"}


def livestock_history(product: str, api_key: str, since: date, today: date) -> pd.DataFrame:
    """Every contract of `product` that traded since `since`, as bank-shaped rows plus `expiry`,
    for building a continuous front-month series. Tickers are built, not looked up: the one-digit
    year is unambiguous from 2021 on (Massive's history floor), and a contract that does not
    exist simply returns no bars. A contract that has expired has its last settle as its expiry,
    which is exact for these cash-settled contracts; live ones take the real date from /contracts."""
    live = {c["ticker"]: c["expiry"] for c in nearest_contracts(product, api_key, today, n=40)}
    # Each call costs about a second (Massive's throughput does not scale with workers), so only ask for
    # contracts that can be the front month inside the window: from ~2 months before `since`, to ~3 after today.
    lo, hi = since - timedelta(days=70), today + timedelta(days=100)
    tickers = [(f"{product}{m}{str(y)[-1]}", m, y)
               for y in range(max(since.year, 2021), today.year + 2) for m in LIVESTOCK_MONTHS[product]
               if lo <= date(y, MONTH_NUM[m], 1) <= hi]

    def one(t):
        tk, m, y = t
        try:
            s = settled_history(tk, api_key, since)
        except MassiveError:
            return None
        if s.empty:
            return None
        exp = live.get(tk) or s.index.max()
        return pd.DataFrame({"product_code": product, "month": m, "year": y,
                             "date": pd.to_datetime(list(s.index)), "settle": s.values, "expiry": exp})

    with ThreadPoolExecutor(max_workers=6) as ex:
        frames = [f for f in ex.map(one, tickers) if f is not None]
    cols = ["product_code", "month", "year", "date", "settle", "expiry"]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
