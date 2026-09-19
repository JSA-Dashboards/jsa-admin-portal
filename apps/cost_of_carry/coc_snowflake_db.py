"""Snowflake backend for the pre-2021 futures history archive.

Deliberately thin: this app's only persistent data is one immutable reference table,
read once per session and cached, so there is no need for the cursor/dict shims the
other JSA apps carry. A single query returns a DataFrame and the column names are
lowercased to match what the CSV path produces.

Enabled by USE_SNOWFLAKE=1. When it is off — or when Snowflake is unreachable — the
committed CSV is used instead, so the app never hard-fails on a database outage.
"""
from __future__ import annotations

import os

import pandas as pd

SCHEMA = "COST_OF_CARRY"
TABLE = "FUTURES_HISTORY_ARCHIVE"

_TRUE = {"1", "true", "yes", "on"}


def use_snowflake() -> bool:
    return os.environ.get("USE_SNOWFLAKE", "").strip().lower() in _TRUE


def connect():
    """Explicit-credentials connection. No Snowpark/active-session path — this app is
    hosted on Streamlit Community Cloud, never Streamlit-in-Snowflake."""
    import snowflake.connector

    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        # `or` rather than a .get default: an unset GitHub secret arrives as "" not absent.
        role=os.environ.get("SNOWFLAKE_ROLE") or "ACCOUNTADMIN",
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE") or "COMPUTE_WH",
        database=os.environ.get("SNOWFLAKE_DATABASE") or "JSA",
        schema=os.environ.get("SNOWFLAKE_SCHEMA") or SCHEMA,
    )


def read_archive() -> pd.DataFrame:
    """The whole archive as product_code / month / year / date / price.

    Snowflake returns UPPERCASE column names and native date objects; both are
    normalised here so callers cannot tell which backend served the rows.
    """
    conn = connect()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                f"SELECT PRODUCT_CODE, MONTH, YEAR, DATE, PRICE "
                f"FROM {SCHEMA}.{TABLE} ORDER BY PRODUCT_CODE, YEAR, MONTH, DATE"
            )
            rows = cur.fetchall()
        finally:
            cur.close()
    finally:
        conn.close()

    frame = pd.DataFrame(rows, columns=["product_code", "month", "year", "date", "price"])
    frame["date"] = pd.to_datetime(frame["date"])
    frame["year"] = frame["year"].astype(int)
    frame["price"] = frame["price"].astype(float)
    return frame


# ── USDA AMS ethanol prices (refreshed by .github/workflows/refresh-ams.yml) ──────────

AMS_COLUMNS = ["date", "commodity", "state", "variety", "trans_mode",
               "price", "price_min", "price_max", "unit"]
AMS_KEY = ["date", "commodity", "state", "variety", "trans_mode"]
AMS_TABLES = {"weekly": "AMS_ETHANOL_WEEKLY", "daily": "AMS_PLANT_CORN"}

AMS_DDL = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    DATE        DATE          NOT NULL,
    COMMODITY   VARCHAR(40)   NOT NULL,   -- Ethanol, Distillers Grain, Distillers Corn Oil, Corn
    STATE       VARCHAR(40)   NOT NULL,
    VARIETY     VARCHAR(40)   NOT NULL,   -- DDG grade ('Dried 10%' ...); '' when not applicable
    TRANS_MODE  VARCHAR(20)   NOT NULL,   -- Truck, Rail, Ocean Vessel
    PRICE       FLOAT         NOT NULL,   -- AMS avg_price in the report's unit
    PRICE_MIN   FLOAT,
    PRICE_MAX   FLOAT,
    UNIT        VARCHAR(30),
    LOADED_AT   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
"""


def ensure_ams_tables(cur) -> None:
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    for table in AMS_TABLES.values():
        cur.execute(AMS_DDL.format(schema=SCHEMA, table=table))


def read_ams(kind: str) -> pd.DataFrame:
    """One AMS table as the same frame ethanol_grind builds from the API."""
    table = AMS_TABLES[kind]
    conn = connect()
    try:
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT {', '.join(c.upper() for c in AMS_COLUMNS)} "
                        f"FROM {SCHEMA}.{table} ORDER BY DATE")
            rows = cur.fetchall()
        finally:
            cur.close()
    finally:
        conn.close()
    frame = pd.DataFrame(rows, columns=AMS_COLUMNS)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["variety"] = frame["variety"].fillna("")
    for col in ("price", "price_min", "price_max"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def max_ams_date(kind: str):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT MAX(DATE) FROM {SCHEMA}.{AMS_TABLES[kind]}")
        return cur.fetchone()[0]
    finally:
        conn.close()


def merge_ams(kind: str, frame: pd.DataFrame, replace: bool = False) -> int:
    """Upsert rows keyed on (date, commodity, state, variety, trans_mode). With
    `replace`, the table is emptied first (initial load). Returns rows sent."""
    if frame is None or not len(frame):
        return 0
    table = f"{SCHEMA}.{AMS_TABLES[kind]}"
    clean = frame[AMS_COLUMNS].copy()
    clean = clean.dropna(subset=["price"]).drop_duplicates(subset=AMS_KEY, keep="last")
    for col in ("state", "variety", "trans_mode", "commodity"):
        clean[col] = clean[col].fillna("").astype(str)
    rows = [
        (pd.Timestamp(r.date).date().isoformat(), r.commodity, r.state, r.variety, r.trans_mode,
         float(r.price),
         None if pd.isna(r.price_min) else float(r.price_min),
         None if pd.isna(r.price_max) else float(r.price_max),
         None if pd.isna(r.unit) else str(r.unit))
        for r in clean.itertuples(index=False)
    ]
    conn = connect()
    try:
        cur = conn.cursor()
        ensure_ams_tables(cur)
        if replace:
            cur.execute(f"TRUNCATE TABLE {table}")
        cur.execute(f"CREATE TEMPORARY TABLE AMS_STAGE LIKE {table}")
        cur.executemany(
            "INSERT INTO AMS_STAGE (DATE, COMMODITY, STATE, VARIETY, TRANS_MODE, PRICE, "
            "PRICE_MIN, PRICE_MAX, UNIT) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
        cur.execute(f"""
            MERGE INTO {table} t USING AMS_STAGE s
              ON t.DATE = s.DATE AND t.COMMODITY = s.COMMODITY AND t.STATE = s.STATE
             AND t.VARIETY = s.VARIETY AND t.TRANS_MODE = s.TRANS_MODE
            WHEN MATCHED THEN UPDATE SET PRICE = s.PRICE, PRICE_MIN = s.PRICE_MIN,
                 PRICE_MAX = s.PRICE_MAX, UNIT = s.UNIT, LOADED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (DATE, COMMODITY, STATE, VARIETY, TRANS_MODE, PRICE,
                 PRICE_MIN, PRICE_MAX, UNIT)
                 VALUES (s.DATE, s.COMMODITY, s.STATE, s.VARIETY, s.TRANS_MODE, s.PRICE,
                 s.PRICE_MIN, s.PRICE_MAX, s.UNIT)
        """)
        conn.commit()
        return len(rows)
    finally:
        conn.close()
