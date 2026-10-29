"""Snowflake hand-off between your PC (Outlook) and the hosted app.

push_wire.py writes three JSON payloads per Central-time day; streamlit_app.py
reads the latest of each. With no Snowflake config the app falls back to the
local files, so it runs on your PC unchanged.

Config (first hit wins): FINWIRE_SF_* env vars (+ .env), then st.secrets["snowflake"]
with keys account, user, role, warehouse, database, schema, private_key
(PEM text) or private_key_path.
"""
import json
import os
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).parent
KEYS = ("account", "user", "role", "warehouse", "database", "schema", "private_key", "private_key_path")
KINDS = ("wire", "pj", "bbg", "mkts", "req")


def ct_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago"))
    except Exception:
        return datetime.now()


def today_ct() -> date:
    """Streamlit Cloud runs in UTC - after 7 PM CT date.today() is already tomorrow."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:
        return date.today()


def config():
    try:
        from dotenv import load_dotenv
        load_dotenv(HERE / ".env", override=True)   # absolute path: a stray env var must not win
    except ImportError:
        pass
    c = {k: os.environ.get("FINWIRE_SF_" + k.upper()) for k in KEYS}
    if not c["account"]:
        try:
            import streamlit as st
            s = st.secrets.get("snowflake")
            if s:
                c = {k: s.get(k) for k in KEYS}
        except Exception:
            pass
    ok = c.get("account") and c.get("user") and (c.get("private_key") or c.get("private_key_path"))
    if not ok:
        # Inside the admin portal: reuse its Snowflake service account (SNOWFLAKE_* env, bridged from the
        # portal's secrets) against the FIN_WIRE database. Its role needs SELECT on FIN_WIRE.PUBLIC.
        e = os.environ
        if e.get("SNOWFLAKE_ACCOUNT") and e.get("SNOWFLAKE_USER") and e.get("SNOWFLAKE_PRIVATE_KEY"):
            return {"account": e["SNOWFLAKE_ACCOUNT"], "user": e["SNOWFLAKE_USER"],
                    "role": e.get("SNOWFLAKE_ROLE"), "warehouse": e.get("SNOWFLAKE_WAREHOUSE"),
                    "database": "FIN_WIRE", "schema": "PUBLIC", "private_key": e["SNOWFLAKE_PRIVATE_KEY"]}
        return None
    return c


def _connect(c):
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization
    pem = c.get("private_key") or Path(c["private_key_path"]).read_text()
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    return snowflake.connector.connect(
        account=c["account"], user=c["user"], private_key=der,
        role=c.get("role") or "FIN_WIRE_ROLE", warehouse=c.get("warehouse") or "COMPUTE_WH",
        database=c.get("database") or "FIN_WIRE", schema=c.get("schema") or "PUBLIC")


def push(kind: str, data, as_of: date, c=None) -> None:
    assert kind in KINDS
    c = c or config()
    if not c:
        raise RuntimeError("No Snowflake config (FINWIRE_SF_* in financial_wire/.env)")
    conn = _connect(c)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("DELETE FROM WIRE_PAYLOAD WHERE AS_OF = %s AND KIND = %s", (as_of.isoformat(), kind))
        cur.execute("INSERT INTO WIRE_PAYLOAD (AS_OF, KIND, PAYLOAD) VALUES (%s, %s, %s)",
                    (as_of.isoformat(), kind, json.dumps(data, ensure_ascii=False)))
        cur.execute("COMMIT")
    except Exception:
        conn.cursor().execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _read_snowflake(c):
    conn = _connect(c)
    try:
        cur = conn.cursor()
        cur.execute("SELECT KIND, AS_OF, PUSHED_AT, PAYLOAD FROM WIRE_PAYLOAD "
                    "QUALIFY ROW_NUMBER() OVER (PARTITION BY KIND ORDER BY AS_OF DESC, PUSHED_AT DESC) = 1")
        return {k: {"as_of": a, "pushed_at": p, "data": json.loads(j)} for k, a, p, j in cur.fetchall()}
    finally:
        conn.close()


def _read_local():
    def rd(name):
        p = HERE / name
        if not p.exists():
            return None
        raw = p.read_text(encoding="utf-8-sig").strip()
        return json.loads(raw) if raw else []
    out = {}
    for kind, name in (("wire", "fin_input.json"), ("pj", "pj_candidates.json"), ("bbg", "bbg_candidates.json"), ("mkts", "mkts.json")):
        d = rd(name)
        if d is not None:
            if kind in ("pj", "bbg"):   # local files are the raw rows; the app wants headline-shaped items
                d = _as_items(kind, d)
            out[kind] = {"as_of": None, "pushed_at": datetime.fromtimestamp((HERE / name).stat().st_mtime), "data": d}
    return out


def _as_items(kind, rows):
    rows = [rows] if isinstance(rows, dict) else rows
    if kind == "pj":
        return [{"topic": "PJ Quaid", "feed": r["subject"], "title": r["text"],
                 "source": f'PJ Quaid, StoneX - "{r["subject"]}"', "link": "", "when": r["received"]} for r in rows]
    return [{"topic": "Bloomberg Markets Daily", "feed": r["section"], "title": r["text"],
             "source": f'Bloomberg - {r["section"]}', "link": "", "when": r["received"]} for r in rows]


def read_latest():
    """-> (payloads_by_kind, origin) where origin is 'snowflake' or 'local files'."""
    c = config()
    if c:
        try:
            return _read_snowflake(c), "snowflake"
        except Exception as e:   # a bad key or missing grant should read as a notice, not a stack trace
            return {}, f"snowflake unavailable ({type(e).__name__}: {str(e)[:120]})"
    return _read_local(), "local files"


def request_refresh() -> str:
    """Ask the PC to re-read Outlook (the hosted app cannot). Writes a 'req' row that the PC's
    scheduled push_wire.py --scheduled sees within ~10 minutes. Returns '' or a reason it failed."""
    try:
        push("req", {"at": datetime.now().isoformat(timespec="seconds")}, today_ct())
        return ""
    except Exception as e:   # e.g. the portal's read-only role has no INSERT on WIRE_PAYLOAD
        return f"{type(e).__name__}: {str(e)[:160]}"


def refresh_pending() -> bool:
    """True when the newest 'req' is newer than the newest 'wire' push (compared by Snowflake's own clock)."""
    c = config()
    if not c:
        return False
    p = _read_snowflake(c)
    req, wire = p.get("req"), p.get("wire")
    return bool(req and (not wire or req["pushed_at"] > wire["pushed_at"]))


def clear_all() -> int:
    """The 4:00 AM clean slate: delete every saved payload so nothing from yesterday is shown.
    The 6:30 AM pull builds the new day. Returns the number of rows removed."""
    c = config()
    if not c:
        raise RuntimeError("No Snowflake config (FINWIRE_SF_* in financial_wire/.env)")
    conn = _connect(c)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM WIRE_PAYLOAD")
        return cur.rowcount or 0
    finally:
        conn.close()
