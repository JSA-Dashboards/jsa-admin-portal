"""
Read-only access to the River FOB Portal's CIF NOLA curves (Corn, Soybeans).

CN's Gulf Export freight doesn't net against a rail_fob bid market like
CSX/NS/BN do — Kolten's call (2026-08-26): net it against CIF NOLA from
the River FOB Portal instead, since CN's whole business here is moving grain
to the Gulf for export, same as the barge/river network CIF represents.

Backend: Snowflake (RIVER_FOB.PUBLIC — the portal's own database) when
USE_SNOWFLAKE is set; otherwise the portal's Postgres via RIVER_DATABASE_URL
(the same name the basis tracker already uses for this exact cross-database
read). Degrades to a notice, never raises, if neither is available.

cif_history stores value in $/bu (confirmed against basis-tracker's own
_riv_cif_cents, which does `value * 100` to get cents) — this module
converts to ¢/bu on the way out so it matches every other price in this app.
"""
import os

# Calendar order for CIF's month labels ("June","July","Aug",...,"Jan" — the
# first two are spelled out, the rest are 3-letter, per the source workbook's
# own SEED_MONTHS convention). Cycles past December.
_MONTH_ORDER = ["June", "July", "Aug", "Sep", "Oct", "Nov", "Dec",
                "Jan", "Feb", "Mar", "Apr", "May"]


def _url() -> str:
    env_val = os.environ.get("RIVER_DATABASE_URL", "").strip()
    if env_val:
        return env_val
    try:
        import _snowflake
        return (_snowflake.get_generic_secret_string("RIVER_DATABASE_URL") or "").strip()
    except ImportError:
        return ""   # not running inside Snowflake — no secret to fall back to


def _use_snowflake() -> bool:
    return os.environ.get("USE_SNOWFLAKE", "").strip().lower() in (
        "1", "true", "yes", "on")


def configured() -> bool:
    """Snowflake (RIVER_FOB.PUBLIC) counts as configured on its own; otherwise a
    RIVER_DATABASE_URL is required. False → the app shows a notice, never raises."""
    return _use_snowflake() or bool(_url())


def source_name() -> str:
    return "Snowflake" if _use_snowflake() else "Postgres"


# The River FOB archive lives in its OWN database, RIVER_FOB.PUBLIC — NOT the JSA
# database the admin-portal shell (Home.py) sets globally via SNOWFLAKE_DATABASE.
# Pin database/schema here or unqualified `cif_history` would resolve to JSA and
# silently find nothing.
_SF_DATABASE = "RIVER_FOB"
_SF_SCHEMA = "PUBLIC"


def _sf_connect():
    import snowflake.connector as sc
    kw = dict(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ.get("SNOWFLAKE_PASSWORD") or None,
        role=os.environ.get("SNOWFLAKE_ROLE") or None,
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE") or None,
        database=_SF_DATABASE,
        schema=_SF_SCHEMA,
        login_timeout=30,
    )
    conn = sc.connect(**{k: v for k, v in kw.items() if v is not None})
    try:
        conn._paramstyle = "pyformat"
    except Exception:
        pass
    return conn


def _sf_rows(sql, params):
    """Snowflake read against RIVER_FOB.PUBLIC; UPPERCASE column names lowered so
    callers (r['month'], r['value'], r['d']) are unchanged from the Postgres path."""
    import snowflake.connector
    conn = _sf_connect()
    try:
        cur = conn.cursor(snowflake.connector.DictCursor)
        cur.execute(sql, params)
        return [{k.lower(): v for k, v in r.items()} for r in cur.fetchall()]
    finally:
        conn.close()


def _pg_rows(sql, params):
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(_url(), cursor_factory=psycopg2.extras.RealDictCursor,
                            connect_timeout=10)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _rows(sql, params):
    return _sf_rows(sql, params) if _use_snowflake() else _pg_rows(sql, params)


def month_sort_key(label):
    try:
        return _MONTH_ORDER.index(label)
    except ValueError:
        return 99


def latest_cif(commodity="Corn"):
    """The most recently archived date's CIF NOLA curve for a commodity
    ("Corn" or "Soybeans", matching the River FOB Portal's own M.COMMODITIES
    spelling).
    -> (as_of_date_str_or_None, {month_label: cents_per_bu}), months ordered
    by _MONTH_ORDER when iterated via sorted(..., key=month_sort_key)."""
    head = _rows("SELECT MAX(as_of) AS d FROM cif_history WHERE commodity=%s", (commodity,))
    as_of = head[0]["d"] if head and head[0].get("d") else None
    if not as_of:
        return None, {}
    curve = _rows("SELECT month, value FROM cif_history WHERE commodity=%s AND as_of=%s",
                  (commodity, as_of))
    cif = {r["month"]: r["value"] * 100 for r in curve if r["value"] is not None}
    return as_of, cif
