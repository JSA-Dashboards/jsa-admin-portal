"""
Read-only access to the basis tracker's rail_fob archive.

The rail corridor postings (manual chat-fed rundowns + the live Palmetto
CSX/NS scrape) already live in the basis tracker's own database, archived by
that app. This portal doesn't duplicate that ingestion — it only reads,
reformatted into a sheet layout — so there stays exactly one source of truth
for rail bids.

Backend: Snowflake (JSA.BASIS_TRACKER) when USE_SNOWFLAKE is set — the same
warehouse the basis tracker itself moved to; otherwise the basis tracker's
Postgres via BASIS_DATABASE_URL. When neither is available `configured()`
returns False and the app shows a notice instead of raising.

BASIS_DATABASE_URL arrives as a plain env var on Streamlit Community Cloud (via
st.secrets, bridged in app.py); Streamlit in Snowflake exposes it as a
SECRETS-mapped name read through the `_snowflake` module (only importable inside
Snowflake's runtime).
"""
import os

SOURCES = ("manual", "palmetto")


def _url() -> str:
    env_val = os.environ.get("BASIS_DATABASE_URL", "").strip()
    if env_val:
        return env_val
    try:
        import _snowflake
        return (_snowflake.get_generic_secret_string("BASIS_DATABASE_URL") or "").strip()
    except ImportError:
        return ""   # not running inside Snowflake — no secret to fall back to


def _in_sis() -> bool:
    """True when running inside Streamlit in Snowflake."""
    try:
        import _snowflake  # noqa: F401
        return True
    except ImportError:
        return False


def _use_snowflake() -> bool:
    if _in_sis():
        return True
    return os.environ.get("USE_SNOWFLAKE", "").strip().lower() in (
        "1", "true", "yes", "on")


def configured() -> bool:
    """Snowflake (JSA.BASIS_TRACKER) counts as configured on its own; otherwise a
    BASIS_DATABASE_URL is required. False → the app shows a notice, never raises."""
    return _use_snowflake() or bool(_url())


def source_name() -> str:
    return "Snowflake" if _use_snowflake() else "Postgres"


# This portal cross-reads two Snowflake databases — JSA.BASIS_TRACKER (rail bids,
# here) and RIVER_FOB.PUBLIC (CIF, in river_data.py) — so each module pins its own
# database+schema at connect time rather than relying on an ambient
# SNOWFLAKE_DATABASE. The basis tracker's rail archive lives in JSA.BASIS_TRACKER.
_SF_DATABASE = "JSA"
_SF_SCHEMA = "BASIS_TRACKER"


def _load_private_key():
    """RSA private key for Snowflake key-pair auth (the account enforces MFA on
    password sign-ins), as DER bytes; None if not configured (falls back to password).
    Source: SNOWFLAKE_PRIVATE_KEY_PATH (.p8 file) or SNOWFLAKE_PRIVATE_KEY (PEM text)."""
    path = (os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH") or "").strip()
    pem = os.environ.get("SNOWFLAKE_PRIVATE_KEY") or ""
    if not path and not pem.strip():
        return None
    from cryptography.hazmat.primitives import serialization
    data = open(path, "rb").read() if path else pem.replace("\\n", "\n").encode()
    pwd = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PWD") or None
    key = serialization.load_pem_private_key(data, password=pwd.encode() if pwd else None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())


def _sf_connect():
    if _in_sis():
        from snowflake.snowpark.context import get_active_session
        conn = get_active_session().connection
        conn.cursor().execute(f"USE DATABASE {_SF_DATABASE}")
        conn.cursor().execute(f"USE SCHEMA {_SF_SCHEMA}")
        return conn
    import snowflake.connector as sc
    kw = dict(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        role=os.environ.get("SNOWFLAKE_ROLE") or None,
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE") or None,
        database=_SF_DATABASE,
        schema=_SF_SCHEMA,
        login_timeout=30,
    )
    pkey = _load_private_key()
    if pkey is not None:
        kw["private_key"] = pkey
    else:
        kw["password"] = os.environ.get("SNOWFLAKE_PASSWORD") or None
    conn = sc.connect(**{k: v for k, v in kw.items() if v is not None})
    try:
        conn._paramstyle = "pyformat"
    except Exception:
        pass
    return conn


def _sf_rows(sql, params):
    """Snowflake read against JSA.BASIS_TRACKER. Snowflake returns UPPERCASE
    column names — lowercase them so callers (r['market'], r['period_order'] …)
    are unchanged from the Postgres path."""
    import snowflake.connector
    conn = _sf_connect()
    try:
        cur = conn.cursor(snowflake.connector.DictCursor)
        cur.execute(sql, params)
        return [{k.lower(): v for k, v in r.items()} for r in cur.fetchall()]
    finally:
        if not _in_sis():
            conn.close()


def _pg_rows(sql, params):
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _rows(sql, params):
    return _sf_rows(sql, params) if _use_snowflake() else _pg_rows(sql, params)


_DATES_SQL = "SELECT DISTINCT date FROM rail_fob WHERE source=%s ORDER BY date DESC"

_ALL_SQL = """SELECT date, market, rail, commodity, period, period_order,
                     futures, bid, offer, bid_raw, offer_raw
              FROM rail_fob WHERE source=%s
              ORDER BY market, period_order, period, date"""


def get_dates(source: str) -> list:
    """Distinct posting dates for a source, most recent first."""
    return [r["date"] for r in _rows(_DATES_SQL, (source,))]


def get_all(source: str) -> list:
    """All rail FOB cells for a source across every date.
    -> [{date, market, rail, commodity, period, period_order, futures,
         bid, offer, bid_raw, offer_raw}]"""
    return _rows(_ALL_SQL, (source,))
