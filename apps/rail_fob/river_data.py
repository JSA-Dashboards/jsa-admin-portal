"""
Read-only access to the River FOB Portal's CIF NOLA curves (Corn, Soybeans).

CN's Gulf Export freight doesn't net against a rail_fob bid market like
CSX/NS/BN do — Kolten's call (2026-08-26): net it against CIF NOLA from
the River FOB Portal instead, since CN's whole business here is moving grain
to the Gulf for export, same as the barge/river network CIF represents.

Configured via the RIVER_DATABASE_URL secret (same name the basis tracker
already uses for this exact cross-database read — kept consistent rather
than inventing a new one). Degrades to a notice, never raises, if unset.

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
    return os.environ.get("RIVER_DATABASE_URL", "").strip()


def configured() -> bool:
    return bool(_url())


def _conn():
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(_url(), cursor_factory=psycopg2.extras.RealDictCursor)


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
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(as_of) AS d FROM cif_history WHERE commodity=%s", (commodity,))
        row = cur.fetchone()
        as_of = row["d"] if row else None
        if not as_of:
            return None, {}
        cur.execute("SELECT month, value FROM cif_history WHERE commodity=%s AND as_of=%s",
                    (commodity, as_of))
        cif = {r["month"]: r["value"] * 100 for r in cur.fetchall() if r["value"] is not None}
        return as_of, cif
    finally:
        conn.close()
