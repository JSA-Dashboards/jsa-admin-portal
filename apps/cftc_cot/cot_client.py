"""
cot_client.py -- read-only access to JSA.CFTC_COT (loaded by cftc-cot-etl).

Reads the three analyst views (COT_DISAGG, COT_LEGACY, COT_CIT). Positions are
contracts. Credentials come from st.secrets, then the environment, then a
local .env (dev only). Key-pair auth is used when a key is supplied.
"""
import os

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
        if c not in ("report_date", "series", "report_type"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


_DISAGG_COLS = ("report_date, series, open_interest, open_interest_chg, "
                "prod_merc_long, prod_merc_short, prod_merc_net, "
                "swap_long, swap_short, swap_net, "
                "mm_long, mm_short, mm_spread, mm_net, mm_long_chg, mm_short_chg, "
                "other_long, other_short, other_net, nonrept_long, nonrept_short, nonrept_net, "
                "traders_total")


@st.cache_data(ttl=3600, show_spinner="Loading disaggregated positions…")
def load_disagg(report_type: str) -> pd.DataFrame:
    return _query(f"SELECT {_DISAGG_COLS} FROM COT_DISAGG "
                  "WHERE series IS NOT NULL AND report_type = %s ORDER BY series, report_date",
                  [report_type])


@st.cache_data(ttl=3600, show_spinner="Loading legacy history…")
def load_legacy(report_type: str, series: str) -> pd.DataFrame:
    return _query("SELECT report_date, open_interest, noncomm_long, noncomm_short, noncomm_net, "
                  "comm_long, comm_short, comm_net, nonrept_net "
                  "FROM COT_LEGACY WHERE series = %s AND report_type = %s ORDER BY report_date",
                  [series, report_type])


@st.cache_data(ttl=3600, show_spinner="Loading index-trader positions…")
def load_cit() -> pd.DataFrame:
    return _query("SELECT report_date, series, open_interest, cit_long, cit_short, cit_net, "
                  "noncomm_net, comm_net, cit_long_chg, cit_short_chg, cit_long_pct_oi, "
                  "cit_short_pct_oi FROM COT_CIT WHERE series IS NOT NULL "
                  "ORDER BY series, report_date")
