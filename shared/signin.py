"""Individual sign-in for the portals (2026-11-13): Microsoft Entra External ID through Streamlit's own st.login,
plus OUR allowlist. Replaces the one shared CLIENT_PASSWORD with "who are you" and "are you on the list".

HOW IT FITS
- It is OFF until the app's Secrets carry an `[auth]` block (redirect_uri, cookie_secret, client_id, client_secret,
  server_metadata_url: see deploy/secrets-names.md). With no block, shared/auth.py behaves exactly as before.
- The identity provider is a separate Entra External ID (customer) tenant where people sign in with their email and a
  one-time code. That code PROVES the email, so the allowlist is keyed on the email address. If a different kind of
  identity provider (a company account) is ever added, revisit this: an unverified email claim must not be trusted.
- The allowlist is JSA.PORTAL_ACCESS.USERS in Snowflake (shared/access_store.py; staff edit it on the Portal Access
  page). `SIGNIN_ALLOWED_EMAILS` (a secret, a list or comma-separated text) adds addresses that need no table row:
  for the first tests, and as a way in if Snowflake is down.
- Fail CLOSED everywhere: a user not on the list, an inactive row, a sign-in with no email, or an allowlist that cannot
  be read all stop at a screen that says so. Access is re-checked on every rerun (the Snowflake answer is cached for
  five minutes), so removing someone takes effect within five minutes even in a session already open.
- `SIGNIN_PASSWORD_FALLBACK = true` (a secret) keeps the shared CLIENT_PASSWORD working next to the Microsoft button,
  for the weeks while clients move over. Left out, once sign-in is configured the password no longer opens anything.

The pure parts (claim reading, the decision) have no Streamlit in them and are covered by test_signin.py.
"""
from __future__ import annotations

import hmac
import html
import os
from dataclasses import dataclass

import streamlit as st

from shared import access_store

REQUIRED_AUTH_KEYS = ("redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url")
CACHE_SECONDS = 300
_TRUE = ("1", "true", "yes", "on")


# ── pure helpers ──────────────────────────────────────────────────────────────

def settings_complete(auth) -> bool:
    """True when an [auth] section carries every key st.login needs (blank or placeholder values do not count)."""
    if auth is None or not hasattr(auth, "get"):
        return False
    for k in REQUIRED_AUTH_KEYS:
        v = auth.get(k)
        if not isinstance(v, str) or not v.strip() or v.strip().startswith("<"):
            return False
    return True


def claim_email(claims) -> str:
    """The user's email from the identity token's claims: `email`, else `preferred_username`, else the first of
    `emails` (the customer-tenant flows sometimes use that one). Lower-cased; '' when none looks like an address."""
    if not hasattr(claims, "get"):
        return ""
    for key in ("email", "preferred_username", "emails"):
        v = claims.get(key)
        if isinstance(v, (list, tuple)):
            v = next((x for x in v if access_store.normalize_email(x)), "")
        e = access_store.normalize_email(v)
        if e:
            return e
    return ""


def bootstrap_emails(value) -> list[str]:
    """SIGNIN_ALLOWED_EMAILS as a list of addresses (a TOML list, or text separated by commas / spaces / lines)."""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(x) for x in value)
    good, _bad = access_store.parse_emails(value if isinstance(value, str) else "")
    return good


@dataclass(frozen=True)
class Decision:
    ok: bool
    role: str = ""
    reason: str = ""   # "" | no_email | not_listed | inactive | wrong_role | unavailable


def _truthy(v) -> bool:
    return v is True or str(v).strip().lower() in _TRUE


def decide(email: str, rows, need: str = "client") -> Decision:
    """May this address in? `rows` are access rows (EMAIL / ROLE / ACTIVE, any key case). `need` 'client' lets a client
    or a staff row in; `need` 'staff' only a staff row."""
    e = access_store.normalize_email(email)
    if not e:
        return Decision(False, reason="no_email")
    mine = []
    for r in rows or []:
        r = {str(k).upper(): v for k, v in dict(r).items()}
        if access_store.normalize_email(r.get("EMAIL")) == e:
            mine.append(r)
    if not mine:
        return Decision(False, reason="not_listed")
    allowed = ("client", "staff") if need == "client" else ("staff",)
    live = [r for r in mine if _truthy(r.get("ACTIVE"))]
    if not live:
        return Decision(False, reason="inactive")
    for r in live:
        role = str(r.get("ROLE") or "").strip().lower()
        if role in allowed:
            return Decision(True, role=role)
    return Decision(False, reason="wrong_role")


# ── configuration read from the app's secrets ─────────────────────────────────

def _secret(name: str, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


def is_enabled() -> bool:
    """Sign-in is on only when the [auth] block is complete."""
    try:
        return settings_complete(st.secrets.get("auth"))
    except Exception:
        return False


def password_fallback_enabled() -> bool:
    return str(_secret("SIGNIN_PASSWORD_FALLBACK", "")).strip().lower() in _TRUE


# ── the access check (cached) ─────────────────────────────────────────────────

@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def _rows_for(email: str) -> list[dict]:
    # raises when Snowflake cannot be read, and st.cache_data does not cache a raise
    return access_store.read_for_email(email)


def check_access(email: str, need: str = "client") -> Decision:
    rows: list[dict] = []
    unavailable = False
    try:
        rows = list(_rows_for(email))
    except Exception:
        unavailable = True
    if email in bootstrap_emails(_secret("SIGNIN_ALLOWED_EMAILS", "")):
        rows.append({"EMAIL": email, "ROLE": "client", "ACTIVE": True})
    d = decide(email, rows, need)
    if not d.ok and unavailable and d.reason in ("not_listed", "inactive", "wrong_role"):
        return Decision(False, reason="unavailable")
    return d


# ── who is signed in (the one place that touches st.user) ─────────────────────

@dataclass(frozen=True)
class Who:
    logged_in: bool
    email: str = ""
    name: str = ""


def current_user() -> Who:
    try:
        u = st.user
        if not getattr(u, "is_logged_in", False):
            return Who(False)
        claims = u.to_dict() if hasattr(u, "to_dict") else {}
        return Who(True, claim_email(claims), str(claims.get("name") or "").strip())
    except Exception:
        return Who(False)


# ── screens ───────────────────────────────────────────────────────────────────

def _card(title: str, subtitle: str) -> None:
    st.markdown(
        "<div style='text-align:center;padding-top:64px'>"
        "<div style='font-size:24px;font-weight:700;color:#32373c;"
        "font-family:\"EB Garamond\",Georgia,serif'>"
        f"{html.escape(title)}</div>"
        f"<div style='color:#64748b;font-size:13px;margin:6px 0 16px'>{subtitle}</div></div>",
        unsafe_allow_html=True,
    )


def _login_screen(title: str, password_fallback) -> None:
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        _card(title, "John Stewart &amp; Associates · sign in with your email address")
        st.button("Sign in", type="primary", width="stretch", key="jsa_signin_btn", on_click=st.login)
        st.caption("We email you a one-time code. There is no password to remember.")
        if password_fallback:
            with st.expander("Use the access password instead"):
                entered = st.text_input("Password", type="password", key="_jsa_client_pw_input",
                                        label_visibility="collapsed", placeholder="Password")
                if entered:
                    if hmac.compare_digest(entered.strip(), str(password_fallback)):
                        st.session_state["_jsa_client_authed"] = True
                        st.rerun()
                    else:
                        st.error("Incorrect password.")


_DENIED_TEXT = {
    "no_email": "Your sign-in did not include an email address, so we cannot tell who you are.",
    "not_listed": "is not on the access list for this portal.",
    "inactive": "no longer has access to this portal.",
    "wrong_role": "does not have access to this part of the portal.",
    "unavailable": "We could not check the access list just now. Please try again in a minute.",
}


def _denied_screen(title: str, who: Who, d: Decision) -> None:
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        _card(title, "John Stewart &amp; Associates")
        text = _DENIED_TEXT.get(d.reason, _DENIED_TEXT["not_listed"])
        if d.reason in ("not_listed", "inactive", "wrong_role"):
            st.error(f"{who.email} {text}")
            st.caption("If you should have access, contact your JSA representative and tell them the address above.")
        else:
            st.error(text)
        st.button("Sign out", key="jsa_signout_denied", on_click=st.logout)


# ── the gate ──────────────────────────────────────────────────────────────────

def require_signin(title: str = "JSA Client Portal", need: str = "client", password_fallback=None) -> bool:
    """Let the person in, or draw a screen and stop the script. Returns True when they may continue.

    `password_fallback` is the shared password (a string) to offer next to the sign-in button, or None for none."""
    who = current_user()
    if who.logged_in:
        d = check_access(who.email, need) if who.email else Decision(False, reason="no_email")
        if d.ok:
            st.session_state["_jsa_signin_email"] = who.email
            st.session_state["_jsa_signin_role"] = d.role
            return True
        st.session_state.pop("_jsa_signin_email", None)
        _denied_screen(title, who, d)
        st.stop()
    st.session_state.pop("_jsa_signin_email", None)
    if password_fallback and st.session_state.get("_jsa_client_authed"):
        return True
    _login_screen(title, password_fallback)
    st.stop()
    return False  # unreachable; st.stop() raises


def render_account_bar() -> None:
    """A slim 'Signed in as ... Sign out' line above the page, shown only to someone signed in with Microsoft."""
    email = st.session_state.get("_jsa_signin_email")
    if not email:
        return
    left, right = st.columns([8, 1.4], vertical_alignment="center")
    with left:
        st.markdown(
            f"<div style='text-align:right;color:#64748b;font-size:12px'>Signed in as "
            f"<b>{html.escape(email)}</b></div>", unsafe_allow_html=True)
    with right:
        st.button("Sign out", key="jsa_signout", on_click=st.logout, width="stretch")
