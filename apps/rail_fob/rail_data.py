"""
Read-only access to the basis tracker's rail_fob archive.

The rail corridor postings (manual chat-fed rundowns + the live Palmetto
CSX/NS scrape) already live in the basis tracker's own Supabase, archived by
that app. This portal doesn't duplicate that ingestion — it only reads,
reformatted into a sheet layout — so there stays exactly one source of truth
for rail bids.

Configured via the BASIS_DATABASE_URL secret. When it isn't set, `configured()`
returns False and the app shows a notice instead of raising.

Works unmodified on either deployment target: Streamlit Community Cloud sets
this as a plain env var (via st.secrets, bridged in app.py); Streamlit in
Snowflake exposes it as a SECRETS-mapped name instead, read through the
`_snowflake` module (only importable inside Snowflake's runtime).
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


def configured() -> bool:
    return bool(_url())


def _conn():
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(_url(), cursor_factory=psycopg2.extras.RealDictCursor)


def get_dates(source: str) -> list:
    """Distinct posting dates for a source, most recent first."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT date FROM rail_fob WHERE source=%s ORDER BY date DESC",
                    (source,))
        return [r["date"] for r in cur.fetchall()]
    finally:
        conn.close()


def get_all(source: str) -> list:
    """All rail FOB cells for a source across every date.
    -> [{date, market, rail, commodity, period, period_order, futures,
         bid, offer, bid_raw, offer_raw}]"""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT date, market, rail, commodity, period, period_order,
                              futures, bid, offer, bid_raw, offer_raw
                       FROM rail_fob WHERE source=%s
                       ORDER BY market, period_order, period, date""", (source,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
