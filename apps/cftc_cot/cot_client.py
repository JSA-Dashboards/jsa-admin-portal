"""
cot_client.py -- read-only access to JSA.CFTC_COT (loaded by cftc-cot-etl).

Reads the three analyst views (COT_DISAGG, COT_LEGACY, COT_CIT). Positions are
contracts. Credentials come from st.secrets, then the environment, then a
local .env (dev only). Key-pair auth is used when a key is supplied.
"""
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

try:  # local dev only; Cloud and the droplet use secrets / real env vars
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

DB = "JSA"
SCHEMA = "CFTC_COT"


def _secret(key: str, default: str = "") -> str:
    try:
        v = st.secrets.get(key, "")
        if v:
            return str(v).strip()
    except Exception:
        pass
    return os.environ.get(key, default).strip()


def _load_private_key():
    pem = _secret("SNOWFLAKE_PRIVATE_KEY")
    path = _secret("SNOWFLAKE_PRIVATE_KEY_PATH")
    if not pem and not path:
        return None
    from cryptography.hazmat.primitives import serialization
    data = open(path, "rb").read() if path else pem.replace("\n", "\n").encode()
    pwd = _secret("SNOWFLAKE_PRIVATE_KEY_PWD") or None
    key = serialization.load_pem_private_key(data, password=pwd.encode() if pwd else None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())


def _connect():
    import snowflake.connector
    kw = dict(
        account=_secret("SNOWFLAKE_ACCOUNT"),
        user=_secret("SNOWFLAKE_USER"),
        role=_secret("SNOWFLAKE_ROLE") or None,
        warehouse=_secret("SNOWFLAKE_WAREHOUSE") or None,
        database=DB, schema=SCHEMA, login_timeout=30,
    )
    pkey = _load_private_key()
    if pkey is not None:
        kw["private_key"] = pkey
    else:
        kw["password"] = _secret("SNOWFLAKE_PASSWORD")
    return snowflake.connector.connect(**kw)


def _query(sql: str, params: list | None = None) -> pd.DataFrame:
    conn = _connect()
    try:
        df = pd.read_sql(sql, conn, params=params)
    finally:
        conn.close()
    df.columns = [c.lower() for c in df.columns]
    if "report_date" in df.columns:
        df["report_date"] = pd.to_datetime(df["report_date"])
    for c in df.columns:
        if c not in ("report_date", "series", "report_type", "date", "product_code", "month"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


_DISAGG_COLS = ("report_date, series, open_interest, open_interest_chg, "
                "prod_merc_long, prod_merc_short, prod_merc_net, "
                "swap_long, swap_short, swap_net, "
                "mm_long, mm_short, mm_spread, mm_net, mm_long_chg, mm_short_chg, "
                "other_long, other_short, other_net, nonrept_long, nonrept_short, nonrept_net, "
                "traders_total")


CT = ZoneInfo("America/Chicago")

# THE CACHE EXPIRES ON THE EVENT, NOT ON A TIMER. CFTC posts Friday ~2:30pm CT and the droplet
# loads Snowflake on the schedule below (crontab "CFTC COT pull"). An hour's TTL alone could
# serve the previous week for up to an hour after the new one landed, so every query is also
# keyed on the most recent run that has finished: the minute the ETL has had time to run
# (about 1 minute, +2 spare), the next page view re-reads Snowflake. KEEP IN STEP WITH THE
# CRONTAB: Fri 14:35, 15:00, 15:30, 16:30, 18:00 and Mon 15:00 (weekday 4 = Friday, 0 = Monday).
ETL_RUNS = ((4, time(14, 38)), (4, time(15, 3)), (4, time(15, 33)), (4, time(16, 33)),
            (4, time(18, 3)), (0, time(15, 3)))


def data_epoch(now: datetime | None = None) -> str:
    """Changes right after each scheduled ETL run, so a cached read never outlives a load."""
    now = (now or datetime.now(CT)).astimezone(CT)
    best = None
    for back in range(0, 9):
        day = now.date() - timedelta(days=back)
        for wd, t in ETL_RUNS:
            if day.weekday() == wd:
                stamp = datetime.combine(day, t, tzinfo=CT)
                if stamp <= now and (best is None or stamp > best):
                    best = stamp
    return best.isoformat() if best else "none"


def freshness(latest_report, now: datetime | None = None) -> dict:
    """Is the newest report on file the one CFTC should have published by now?

    A report dated Tuesday T is published the Friday after (T+3d, 2:30pm CT). `overdue` only
    turns on after the last retry run of that day has had its chance (6:30pm CT), so the
    ordinary Friday-afternoon gap never shows as a fault. Holiday weeks slip to Monday, which
    is why the message says so rather than blaming the ETL outright."""
    now = (now or datetime.now(CT)).astimezone(CT)
    latest = latest_report.date()
    tue = now.date() - timedelta(days=(now.weekday() - 1) % 7)   # most recent Tuesday on/before today
    while True:
        release = datetime.combine(tue + timedelta(days=3), time(18, 30), tzinfo=CT)
        if release <= now:
            break
        tue -= timedelta(days=7)
    behind = (tue - latest).days // 7
    return {"expected": tue, "weeks_behind": max(behind, 0), "overdue": behind > 0,
            "release": datetime.combine(tue + timedelta(days=3), time(14, 30), tzinfo=CT)}


@st.cache_data(ttl=1800, show_spinner="Loading disaggregated positions…")
def _disagg(report_type: str, epoch: str) -> pd.DataFrame:
    return _query(f"SELECT {_DISAGG_COLS} FROM COT_DISAGG "
                  "WHERE series IS NOT NULL AND report_type = %s ORDER BY series, report_date",
                  [report_type])


@st.cache_data(ttl=1800, show_spinner="Loading legacy history…")
def _legacy(report_type: str, series: str, epoch: str) -> pd.DataFrame:
    return _query("SELECT report_date, open_interest, noncomm_long, noncomm_short, noncomm_net, "
                  "comm_long, comm_short, comm_net, nonrept_net "
                  "FROM COT_LEGACY WHERE series = %s AND report_type = %s ORDER BY report_date",
                  [series, report_type])


@st.cache_data(ttl=1800, show_spinner="Loading index-trader positions…")
def _cit(epoch: str) -> pd.DataFrame:
    return _query("SELECT report_date, series, open_interest, cit_long, cit_short, cit_net, "
                  "noncomm_net, comm_net, cit_long_chg, cit_short_chg, cit_long_pct_oi, "
                  "cit_short_pct_oi FROM COT_CIT WHERE series IS NOT NULL "
                  "ORDER BY series, report_date")


# The public loaders ALWAYS pass the epoch: st.cache_data keys on the arguments actually
# supplied (defaults are not part of the key), so a call site that forgot it would silently
# keep the hour-long cache.
def load_disagg(report_type: str) -> pd.DataFrame:
    return _disagg(report_type, data_epoch())


def load_legacy(report_type: str, series: str) -> pd.DataFrame:
    return _legacy(report_type, series, data_epoch())


def load_cit() -> pd.DataFrame:
    return _cit(data_epoch())


@st.cache_data(ttl=1800, show_spinner="Loading futures settlements…")
def load_settlements(since: str) -> pd.DataFrame:
    """Daily settles for the markets on the price-move chart, from `since` (YYYY-MM-DD) on.

    JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS is filled each weekday at 4:30pm CT by the droplet, so
    the newest row is the previous trading day until then."""
    df = _query("SELECT product_code, month, year, date, settle "
                "FROM JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS "
                "WHERE product_code IN ('ZC','ZS','ZM','ZL','ZW','KE','HRS') AND date >= %s "
                "ORDER BY product_code, year, month, date", [since])
    df["date"] = pd.to_datetime(df["date"])
    return df


def clear_cache() -> None:
    """Drop every cached query so the next render re-reads Snowflake."""
    _disagg.clear()
    _legacy.clear()
    _cit.clear()
    load_settlements.clear()
