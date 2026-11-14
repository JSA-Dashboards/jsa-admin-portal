"""The portal access list: who may sign in, kept in Snowflake (JSA.PORTAL_ACCESS.USERS).

The CLIENT portal only ever READS it (its Snowflake role is SELECT-only) and asks about ONE email at a time, so
a client process never holds the whole list. The STAFF portal's Portal Access page (admin_pages/portal_access.py)
is the only writer. Created by snowflake/portal_access.sql.

No Streamlit imports at module level on purpose: the pure parts are tested without a running app, and the
connection is built from the SNOWFLAKE_* environment variables that Home.py bridges from the secrets before any
login gate runs (the same ones every bundled dashboard reads).
"""
from __future__ import annotations

import os
import re

TABLE = "JSA.PORTAL_ACCESS.USERS"
ROLES = ("client", "staff")
_EMAIL_RE = re.compile(r"^[^@\s,;<>()\[\]\"']+@[^@\s,;<>()\[\]\"']+\.[^@\s,;<>()\[\]\"']+$")


def normalize_email(value) -> str:
    """Lower-case, trimmed; '' when it does not look like one address."""
    if not isinstance(value, str):
        return ""
    v = value.strip().lower()
    return v if _EMAIL_RE.match(v) else ""


def parse_emails(text) -> tuple[list[str], list[str]]:
    """Split pasted text (commas, semicolons, spaces, new lines, 'Name <a@b.com>') into (valid emails, rejected
    pieces). Order kept, duplicates dropped."""
    if not isinstance(text, str):
        return [], []
    good: list[str] = []
    bad: list[str] = []
    for piece in re.split(r"[\s,;]+", text.replace("<", " ").replace(">", " ")):
        if not piece:
            continue
        e = normalize_email(piece)
        if e:
            if e not in good:
                good.append(e)
        else:
            bad.append(piece)
    return good, bad


def _connect():
    """A Snowflake connection from the bridged SNOWFLAKE_* environment (key-pair login, like every module here)."""
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    pem = os.environ.get("SNOWFLAKE_PRIVATE_KEY", "").strip()
    if not pem:
        raise RuntimeError("no Snowflake login is configured")
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
        role=os.environ.get("SNOWFLAKE_ROLE") or None,
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE") or None,
        database=os.environ.get("SNOWFLAKE_DATABASE") or "JSA",
        private_key=der, client_session_keep_alive=False)


def _rows(sql: str, params=()) -> list[dict]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [c[0].upper() for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def _exec(sql: str, params=()) -> None:
    conn = _connect()
    try:
        conn.cursor().execute(sql, params)
    finally:
        conn.close()


# ── read (client portal and staff) ────────────────────────────────────────────

def read_for_email(email: str) -> list[dict]:
    """The access rows for ONE address (0 or 1, in practice). Raises if Snowflake cannot be read: the caller must
    treat that as 'cannot check', never as 'not listed'."""
    e = normalize_email(email)
    if not e:
        return []
    return _rows(f"SELECT EMAIL, ROLE, ACTIVE FROM {TABLE} WHERE LOWER(EMAIL) = %s", (e,))


# ── write (staff portal's Portal Access page only) ────────────────────────────

def read_all() -> list[dict]:
    return _rows(f"SELECT EMAIL, ROLE, NAME, NOTE, ACTIVE, ADDED_AT, ADDED_BY, UPDATED_AT FROM {TABLE} ORDER BY EMAIL")


def add_users(emails: list[str], role: str, name: str = "", note: str = "", by: str = "") -> int:
    """Add (or re-activate and re-label) each address. Returns how many were written."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    good = [normalize_email(e) for e in emails]
    good = [e for e in good if e]
    if not good:
        return 0
    conn = _connect()
    try:
        cur = conn.cursor()
        for e in good:
            cur.execute(
                f"MERGE INTO {TABLE} t USING (SELECT %s AS EMAIL, %s AS ROLE, %s AS NAME, %s AS NOTE, %s AS ADDED) s "
                "ON LOWER(t.EMAIL) = s.EMAIL "
                "WHEN MATCHED THEN UPDATE SET ROLE = s.ROLE, ACTIVE = TRUE, UPDATED_AT = SYSDATE(), "
                "  NAME = COALESCE(NULLIF(s.NAME, ''), t.NAME), NOTE = COALESCE(NULLIF(s.NOTE, ''), t.NOTE) "
                "WHEN NOT MATCHED THEN INSERT (EMAIL, ROLE, NAME, NOTE, ACTIVE, ADDED_AT, ADDED_BY, UPDATED_AT) "
                "  VALUES (s.EMAIL, s.ROLE, NULLIF(s.NAME, ''), NULLIF(s.NOTE, ''), TRUE, SYSDATE(), s.ADDED, SYSDATE())",
                (e, role, name.strip(), note.strip(), by))
        return len(good)
    finally:
        conn.close()


def set_active(email: str, active: bool) -> None:
    e = normalize_email(email)
    if e:
        _exec(f"UPDATE {TABLE} SET ACTIVE = %s, UPDATED_AT = SYSDATE() WHERE LOWER(EMAIL) = %s", (bool(active), e))


def remove(email: str) -> None:
    e = normalize_email(email)
    if e:
        _exec(f"DELETE FROM {TABLE} WHERE LOWER(EMAIL) = %s", (e,))
