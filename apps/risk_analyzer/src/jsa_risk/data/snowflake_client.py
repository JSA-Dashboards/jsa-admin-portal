"""A single cached Snowflake connection, built from `config.get_snowflake_config()`.

Uses the connector directly (rather than `st.connection`'s SnowflakeConnection) so
key-pair auth is unambiguous and matches exactly what `scripts/bootstrap_snowflake.py`
already validated. `st.cache_resource` keeps one connection alive across reruns instead
of reconnecting on every widget interaction.
"""
import pandas as pd
import snowflake.connector
import streamlit as st
from cryptography.hazmat.primitives import serialization
from snowflake.connector.cursor import SnowflakeCursor

from jsa_risk.config import SnowflakeConfig, get_snowflake_config


def _load_private_key_der(cfg: SnowflakeConfig) -> bytes:
    """Prefers an inline PEM (required on Streamlit Cloud, which has no persistent
    filesystem to point a path at) over a local file path (local dev convenience)."""
    if cfg.private_key_pem:
        pem_bytes = cfg.private_key_pem.encode("utf-8")
    else:
        with open(cfg.private_key_path, "rb") as f:
            pem_bytes = f.read()
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@st.cache_resource(show_spinner=False)
def get_connection() -> snowflake.connector.SnowflakeConnection:
    cfg = get_snowflake_config()
    return snowflake.connector.connect(
        account=cfg.account,
        user=cfg.user,
        private_key=_load_private_key_der(cfg),
        role=cfg.role,
        warehouse=cfg.warehouse,
        database=cfg.database,
        schema=cfg.schema,
        # Heartbeats keep the session and master token from lapsing while the app sits
        # idle. It narrows the window but can't close it (a sleeping container sends no
        # heartbeat), which is what _with_connection below is for.
        client_session_keep_alive=True,
    )


# Snowflake's token-lifecycle error codes: ID token expired, session expired, master
# token not found / expired / invalid. The connector raises these as a ProgrammingError
# once it has tried and failed to renew the session itself - which a key-pair login
# can't do, since renewing needs the private key the connector no longer holds.
# 390400 (bad request) shares that code path but is deliberately excluded: it can mean
# a genuinely malformed request, and retrying one of those only doubles the failure.
_SESSION_EXPIRED_ERRNOS = frozenset({390110, 390112, 390113, 390114, 390115})


def _is_session_expired(exc: BaseException) -> bool:
    if getattr(exc, "errno", None) in _SESSION_EXPIRED_ERRNOS:
        return True
    # The connector raises the ProgrammingError from inside its own
    # ReauthenticationRequest handler, so the marker may sit on the context instead.
    ctx = exc.__cause__ or exc.__context__
    return type(ctx).__name__ == "ReauthenticationRequest"


def _with_connection(work):
    """Run `work(connection)`, reconnecting once if the cached session has expired.

    `get_connection` is cached for the life of the process, so without this an expired
    session breaks every page until someone reboots the app - which is exactly what
    took the Cloud deployment down on 2026-09-21. One retry, no loop: a second failure
    on a brand-new connection is a real error and should surface as one.

    Retrying writes is safe: Snowflake rejects an expired session at authentication,
    before the statement executes, so the retried INSERT is the only one that runs.
    """
    conn = get_connection()
    if conn.is_closed():
        get_connection.clear()
        conn = get_connection()
    try:
        return work(conn)
    except snowflake.connector.errors.DatabaseError as exc:
        if not _is_session_expired(exc):
            raise
        get_connection.clear()
        return work(get_connection())


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    def work(conn):
        cur: SnowflakeCursor = conn.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetch_pandas_all()
        finally:
            cur.close()
    return _with_connection(work)


def execute(sql: str, params: tuple = ()) -> None:
    def work(conn):
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
        finally:
            cur.close()
    return _with_connection(work)


def executemany(sql: str, seq_of_params: list) -> None:
    if not seq_of_params:
        return

    def work(conn):
        cur = conn.cursor()
        try:
            cur.executemany(sql, seq_of_params)
        finally:
            cur.close()
    return _with_connection(work)
