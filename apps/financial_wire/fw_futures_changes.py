"""Nearby futures: last settle plus day, week, month and year change in nominal terms,
with the month and year also as % in parentheses.

Run by push_wire.py on your PC (needs MASSIVE_API_KEY in financial_wire/.env);
the hosted app only reads the result from Snowflake, so the key never leaves your PC.

Day   = last settle minus the prior session's settle.
Week  = last settle minus the settle five sessions back.
Month = vs the last settle on or before 30 days ago (within 7 days).
Year  = vs the last settle on or before 365 days ago (within 10 days).
All on the SAME contract, so a roll to the next contract never shows up as a move
(a year-ago comparison therefore needs the contract to have traded back then).
Units are the contract's own quote: grains in cents/bu, meal in $/short ton,
soybean oil and cattle in cents/lb.
"""
from datetime import date, timedelta

import fw_massive_api as mx

# name, Massive product code, unit, decimals shown
PRODUCTS = [
    ("Corn", "ZC", "¢/bu", 2),
    ("Soybeans", "ZS", "¢/bu", 2),
    ("Soybean meal", "ZM", "$/st", 2),
    ("Soybean oil", "ZL", "¢/lb", 2),
    ("SRW wheat", "ZW", "¢/bu", 2),
    ("HRW wheat", "KE", "¢/bu", 2),
    ("Live cattle", "LE", "¢/lb", 3),
]


def _ago(s, as_of: date, days: int, tol: int):
    """Last value in series s dated on/before as_of - days, if it is within tol days of that target."""
    target = as_of - timedelta(days=days)
    old = s[[target - timedelta(days=tol) <= d <= target for d in s.index]]
    return float(old.iloc[-1]) if len(old) else None


def _changes(s, as_of: date) -> dict:
    """last/day/week/month/year (nominal) and month_pct/year_pct for a date-indexed settle series."""
    last = float(s.iloc[-1])
    out = {"asof": str(s.index[-1]), "last": round(last, 4),
           "day": round(last - float(s.iloc[-2]), 4) if len(s) >= 2 else None,
           "week": round(last - float(s.iloc[-6]), 4) if len(s) >= 6 else None}
    for key, days, tol in (("month", 30, 7), ("year", 365, 10)):
        old = _ago(s, as_of, days, tol)
        out[key] = round(last - old, 4) if old is not None else None
        out[key + "_pct"] = round((last - old) / old * 100, 2) if old else None
    return out


def build(api_key: str, as_of: date | None = None) -> list[dict]:
    as_of = as_of or date.today()
    nearby = {}
    for name, code, _, _ in PRODUCTS:
        contracts = mx.get_active_contract_tickers(code, api_key, as_of)
        if contracts:
            nearby[name] = contracts[0]["ticker"]
    bars = mx.get_daily_bars_many(list(nearby.values()), api_key)

    rows = []
    for name, code, unit, dec in PRODUCTS:
        t = nearby.get(name)
        df = bars.get(t) if t else None
        if df is None or len(df) < 2:
            continue
        rows.append({"name": name, "ticker": t, "unit": unit, "decimals": dec, **_changes(df["settle"], as_of)})

    cr = crush_row(bars, nearby, as_of)
    if cr:
        rows.append(cr)
    try:
        eth = ethanol_row(api_key, as_of)
        if eth:
            rows.append(eth)
    except Exception as e:   # ethanol is thin and flaky; never drop the grain rows for it
        print("ETHANOL ERROR:", e)
    return rows


def crush_row(bars: dict, nearby: dict, as_of: date) -> dict | None:
    """Nearby board crush ($/bu) = 44 lb meal + 11 lb oil less the beans, from the three nearby
    contracts; every change is on the crush value itself."""
    try:
        tb, tm, to = nearby["Soybeans"], nearby["Soybean meal"], nearby["Soybean oil"]
        df = bars[tb]["settle"].to_frame("b").join(bars[tm]["settle"].rename("m"), how="inner") \
            .join(bars[to]["settle"].rename("o"), how="inner")
    except KeyError:
        return None
    if len(df) < 2:
        return None
    c = 0.022 * df["m"] + 0.11 * df["o"] - df["b"] / 100.0
    return {"name": "Board crush", "ticker": f"{tb}/{tm}/{to}", "unit": "$/bu", "decimals": 3, **_changes(c, as_of)}


def ethanol_row(api_key: str, as_of: date) -> dict | None:
    """CME Chicago Ethanol (Platts) futures, nearest contract with a settlement. A futures PROXY
    for the Platts assessment (it settles against the month's average). Day = settle minus the
    snapshot's previous settlement (exists even on no-trade days); week/month/year come from the
    contract's own sparse bars and are n/a when it did not trade near the target date."""
    contracts = mx.get_active_contract_tickers("CU", api_key, as_of, limit=1000)[:6]
    snaps = mx.get_snapshots([c["ticker"] for c in contracts], api_key)
    for c in contracts:
        sess = (snaps.get(c["ticker"]) or {}).get("session") or {}
        settle, prev = sess.get("settlement_price"), sess.get("previous_settlement")
        if not settle:
            continue
        settle = float(settle)
        row = {"name": "Chicago ethanol (Platts fut)", "ticker": c["ticker"], "unit": "$/gal", "decimals": 4,
               "asof": str(as_of), "last": round(settle, 4),
               "day": round(settle - float(prev), 4) if prev else None,
               "week": None, "month": None, "month_pct": None, "year": None, "year_pct": None}
        bars = mx.get_daily_bars(c["ticker"], api_key)
        if len(bars):
            s = bars["settle"]
            for key, days, tol in (("week", 7, 4), ("month", 30, 10), ("year", 365, 20)):
                old = _ago(s, as_of, days, tol)
                if old is not None:
                    row[key] = round(settle - old, 4)
                    if key != "week":
                        row[key + "_pct"] = round((settle - old) / old * 100, 2)
        return row
    return None
