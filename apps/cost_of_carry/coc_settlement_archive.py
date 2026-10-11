"""Bank every daily settlement Massive serves, so the app's history stops expiring.

Massive's own window starts 2021-09 and only covers contracts it still carries; corn and
soybeans reach 2008 through a one-off workbook ETL (history_archive.py), but wheat, meal
and oil have nothing older. CME DataMine's end-of-day futures files would fill the gap and
the file codes are real, but JSA's licence doesn't cover them (403 "not entitled"), so the
gap can't be closed today.

What can be done is stop losing ground: snapshot every settlement Massive shows into
Snowflake (JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS) each day. The archive then deepens on
its own — a year from now wheat has six crop years instead of five, held by JSA rather
than rented from a vendor's rolling window.

    python scripts/refresh_settlements.py              # yesterday forward, all markets
    python scripts/refresh_settlements.py --backfill   # everything Massive still serves

Rows are keyed on (ticker, date) and MERGEd, so re-runs and overlapping windows are safe.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from coc_massive_api import get_settlement_histories

# Contract months actually listed per market — enumerating tickers directly avoids the
# /contracts endpoint, which only lists what is currently active.
PRODUCT_MONTHS = {
    "ZC": "HKNUZ",
    "ZS": "FHKNQUX",
    "ZM": "FHKNQUVZ",
    "ZL": "FHKNQUVZ",
    "ZW": "HKNUZ",
    "KE": "HKNUZ",
    "HRS": "HKNUZ",
}

# Massive's daily bars begin here; nothing earlier is worth asking for.
FEED_START = date(2021, 9, 1)
TABLE = "FUTURES_SETTLEMENTS"

DDL = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    PRODUCT_CODE VARCHAR(8)  NOT NULL,   -- ZC, ZS, ZM, ZL, ZW, KE, HRS
    TICKER       VARCHAR(16) NOT NULL,   -- as Massive spells it, e.g. ZWZ6
    MONTH        VARCHAR(1)  NOT NULL,   -- contract month letter
    YEAR         NUMBER(4,0) NOT NULL,   -- contract year, 4 digits
    DATE         DATE        NOT NULL,   -- trading date
    SETTLE       FLOAT       NOT NULL,   -- settlement in the market's quote units
    LOADED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
"""


def contract_years(today: date) -> range:
    """Contract years worth asking about: back to the feed's start, forward through the
    deferred months already listed."""
    return range(FEED_START.year, today.year + 3)


def tickers_for(product_code: str, today: date) -> list[tuple[str, str, int]]:
    """[(ticker, month_letter, contract_year)] for one market."""
    out = []
    for year in contract_years(today):
        for letter in PRODUCT_MONTHS[product_code]:
            out.append((f"{product_code}{letter}{year % 10}", letter, year))
    return out


def fetch(product_code: str, api_key: str, today: date, since: date | None = None,
          max_workers: int = 8) -> pd.DataFrame:
    """Settlements for one market as product_code / ticker / month / year / date / settle.

    Massive's single-digit year means one ticker can only be the contract year whose
    settlements fall inside its own trading life, so rows are filtered to a window around
    the contract year before being kept — otherwise ZCZ6 would absorb ZCZ 2016 bars too.
    """
    wanted = tickers_for(product_code, today)
    histories = get_settlement_histories([t for t, _, _ in wanted], api_key,
                                         max_workers=max_workers)
    rows = []
    for ticker, letter, year in wanted:
        series = histories.get(ticker)
        if series is None or not len(series):
            continue
        # A contract trades for at most ~3 years before its delivery month.
        lo = max(FEED_START, date(year - 3, 1, 1))
        hi = date(year + 1, 6, 30)
        for day, price in series.items():
            if not (lo <= day <= hi):
                continue
            if since is not None and day < since:
                continue
            rows.append({"product_code": product_code, "ticker": ticker, "month": letter,
                         "year": year, "date": day, "settle": float(price)})
    return pd.DataFrame(rows)


def merge(frame: pd.DataFrame) -> int:
    """Upsert on (ticker, date). Returns rows sent."""
    import coc_snowflake_db as snowflake_db

    if frame is None or not len(frame):
        return 0
    rows = [(r.product_code, r.ticker, r.month, int(r.year), r.date.isoformat(), float(r.settle))
            for r in frame.itertuples(index=False)]
    conn = snowflake_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {snowflake_db.SCHEMA}")
        cur.execute(DDL.format(schema=snowflake_db.SCHEMA, table=TABLE))
        table = f"{snowflake_db.SCHEMA}.{TABLE}"
        cur.execute(f"CREATE TEMPORARY TABLE SETTLE_STAGE LIKE {table}")
        cur.executemany(
            "INSERT INTO SETTLE_STAGE (PRODUCT_CODE, TICKER, MONTH, YEAR, DATE, SETTLE) "
            "VALUES (%s, %s, %s, %s, %s, %s)", rows)
        cur.execute(f"""
            MERGE INTO {table} t USING SETTLE_STAGE s
              ON t.TICKER = s.TICKER AND t.DATE = s.DATE
            WHEN MATCHED THEN UPDATE SET SETTLE = s.SETTLE, LOADED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (PRODUCT_CODE, TICKER, MONTH, YEAR, DATE, SETTLE)
                 VALUES (s.PRODUCT_CODE, s.TICKER, s.MONTH, s.YEAR, s.DATE, s.SETTLE)
        """)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def coverage() -> pd.DataFrame:
    """Rows, contracts and date span per market — what the archive actually holds."""
    import coc_snowflake_db as snowflake_db

    conn = snowflake_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT PRODUCT_CODE, COUNT(*), COUNT(DISTINCT TICKER),
                   MIN(DATE), MAX(DATE), MIN(YEAR), MAX(YEAR)
            FROM {snowflake_db.SCHEMA}.{TABLE} GROUP BY PRODUCT_CODE ORDER BY PRODUCT_CODE
        """)
        return pd.DataFrame(cur.fetchall(), columns=["product", "rows", "contracts",
                                                     "first", "last", "year_lo", "year_hi"])
    finally:
        conn.close()


def refresh(api_key: str, today: date | None = None, days: int = 7,
            backfill: bool = False) -> dict[str, int]:
    """Daily top-up (a week's overlap, so a missed run or a late settlement heals) or a
    full backfill of everything Massive still serves."""
    today = today or date.today()
    since = None if backfill else today - timedelta(days=days)
    sent = {}
    for product_code in PRODUCT_MONTHS:
        sent[product_code] = merge(fetch(product_code, api_key, today, since=since))
    return sent
