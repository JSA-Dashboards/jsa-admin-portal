"""
Shared-passphrase gate, usable for one page or for the whole portal.

WHY A SHARED PASSPHRASE AND NOT REAL ACCOUNTS. Streamlit Community Cloud's
viewer allowlist needs every viewer invited by email and signed in. That is the
stronger control, but it does not fit a list that includes clients. The trade is
explicit: one secret everyone shares, no per-person revocation, and it WILL get
forwarded. Rotating it is the only revocation there is.

IT FAILS CLOSED. With no passphrase configured nobody gets in, and the page says
why rather than silently pretending to be a login. A gate that turns itself off
when misconfigured is not a gate. So whatever you gate, set its secret FIRST:
wiring a gate whose secret is missing takes that page down until it is added,
and per CLAUDE.md a fix means a manual reboot rather than a push.

TWO WAYS TO USE IT:

  # one page -- call at the very top of the page script, before anything renders
  portal_auth.require_passphrase("REPORTS_PASSPHRASE", title="JSA Daily Cattle Reports")

  # the whole portal -- call in Home.py immediately after set_page_config, and
  # ABOVE st.navigation. Streamlit runs Home.py on every request including a
  # deep link straight to /beef-cutout, then dispatches; below st.navigation,
  # or inside a page, every deep link would be open.
  portal_auth.require_passphrase()

Each secret name gets its own session key, so a page gate and a portal gate are
independent and unlocking one does not unlock the other.

THESE ARE NOT CHAT_PASSPHRASE. That gates the Ask AI tab to cap Anthropic spend.
Give every gate a different value -- reusing one that is handed to clients would
hand out the API budget with it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import streamlit as st

DEFAULT_SECRET = "PORTAL_PASSPHRASE"

# -- Admin vs client ----------------------------------------------------------
#
# ONE QUESTION, ASKED IN ONE PLACE. "Is this the admin?" is now is_admin(), so
# every page asks it the same way and the answer can change without hunting
# through the portal for URL-parameter checks.
#
# TODAY it is a shared passphrase, which is the weaker backing and worth naming:
# one secret everyone with it can forward, no per-person revocation, no record
# of who did what. It is proportionate while "admin" means the letter tool and
# nothing else.
#
# THE UPGRADE IS THIS FUNCTION AND NOTHING ELSE. JSA runs on Microsoft 365, so
# st.login() against Entra gives real identity -- clients keep browsing
# anonymously and admin becomes "signed in as Ross". When that is wanted,
# is_admin() checks st.user instead and no caller changes.
#
# ADMIN_PASSPHRASE is the name; REPORTS_PASSPHRASE is still honoured so an
# already-configured deployment does not break on the rename.
ADMIN_SECRETS = ("ADMIN_PASSPHRASE", "REPORTS_PASSPHRASE")
_ADMIN_KEY = "_portal_is_admin"


def admin_passphrase() -> str:
    for name in ADMIN_SECRETS:
        value = configured_passphrase(name)
        if value:
            return value
    return ""


def is_admin() -> bool:
    """The one question. Backed by a passphrase today, by identity later."""
    return bool(st.session_state.get(_ADMIN_KEY))


def admin_sign_in(label: str = "Staff sign-in") -> None:
    """
    A discreet sign-in, for the foot of the home page.

    Says nothing about what it unlocks: a client seeing "Staff sign-in" learns
    that staff exist, not that a letter tool does.
    """
    if is_admin():
        return
    secret = admin_passphrase()
    if not secret:
        return
    with st.expander(label, expanded=False):
        with st.form("admin_gate", clear_on_submit=True):
            entered = st.text_input("Passphrase", type="password",
                                    label_visibility="collapsed", placeholder="Passphrase")
            if st.form_submit_button("Sign in") and entered:
                if hmac.compare_digest(entered.strip(), secret):
                    st.session_state[_ADMIN_KEY] = True
                    st.rerun()
                else:
                    st.error("Incorrect passphrase.")


def require_admin(title: str = "Restricted") -> None:
    """
    Block a page unless this session is the admin.

    Fails closed with no passphrase configured, exactly as require_passphrase
    does -- a control that disables itself when misconfigured is not one.
    """
    if is_admin():
        return
    secret = admin_passphrase()
    if not secret:
        _shell(f"{title} is not configured",
               f"No <code>{ADMIN_SECRETS[0]}</code> is set for this deployment, so "
               "access cannot be verified and this page is closed.<br><br>"
               "Add it to the app&rsquo;s secrets to restore it.")
        st.stop()

    _shell(title, "This section is restricted. Enter the passphrase to continue.")
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form("admin_required", clear_on_submit=False):
            entered = st.text_input("Passphrase", type="password",
                                    label_visibility="collapsed", placeholder="Passphrase")
            if st.form_submit_button("Enter", use_container_width=True):
                if hmac.compare_digest(entered.strip(), secret):
                    st.session_state[_ADMIN_KEY] = True
                    st.rerun()
                else:
                    st.error("Incorrect passphrase.")
    st.stop()


def configured_passphrase(secret_name: str = DEFAULT_SECRET) -> str:
    """
    Secrets first, then the environment.

    st.secrets RAISES rather than returning empty when there is no secrets.toml
    at all, which is the normal state on a fresh clone -- hence the try.
    """
    try:
        value = st.secrets.get(secret_name, "")
    except Exception:
        value = ""
    return (value or os.environ.get(secret_name, "")).strip()


def _session_key(secret_name: str) -> str:
    return f"_unlocked__{secret_name}"


def is_unlocked(secret_name: str = DEFAULT_SECRET) -> bool:
    return bool(st.session_state.get(_session_key(secret_name)))


# -- Remembering the unlock across a page load --------------------------------
#
# ST.SESSION_STATE IS NOT ENOUGH, and that is what Ross reported on 2026-10-26:
# "it makes me enter the password every time i click a different dashboard
# tab." A Streamlit session dies on any FULL page load -- a refresh, a new tab,
# a deep link pasted in, the Community Cloud iframe re-navigating -- and
# session_state dies with it. Reproduced under Streamlit 1.64 locally: clicking
# a top-nav link keeps the session (client-side routing, the gate stays open),
# but a full navigation to the same URL comes back gated.
#
# IT DOES NOT WORK ON STREAMLIT COMMUNITY CLOUD, AND THAT IS MEASURED.
# `st.context.cookies` returns an EMPTY dict there -- the proxy in front of the
# app does not forward the browser's cookies to it. Probed on the live app,
# 2026-10-26, from a page carrying eight cookies the browser could see:
#
#     browser (document.cookie) : proxy-tracking-id, _ga, ajs_anonymous_id,
#                                 jsa_portal_PORTAL_PASSPHRASE, jsa_portal_probe, ...
#     server  (st.context.cookies) : []
#
# So the WRITE below is fine and the READ is blind. The token machinery is kept
# because it is correct, tested, and reusable by whatever channel replaces the
# read -- but nothing here can remember an unlock on Community Cloud today, and
# a reader should not assume otherwise. See CLAUDE.md for the options.
#
# So the unlock is remembered in a COOKIE as well. The cookie never contains
# the passphrase; it holds an expiry and an HMAC of that expiry keyed on the
# passphrase, so the browser cannot forge one or extend its own.
#
# THREE PROPERTIES THAT MATTER, none of them accidental:
#
#   * ROTATING THE PASSPHRASE INVALIDATES EVERY TOKEN. The passphrase is the
#     HMAC key, so changing it changes every signature. That keeps the one
#     revocation story this gate has ever had -- see this module's header.
#   * THE TOKEN IS NEVER STRONGER THAN THE PASSPHRASE. It is a bearer token in
#     a cookie that JavaScript can read, because JavaScript is what sets it;
#     Streamlit has no API to set a cookie server-side. Anyone who can read it
#     could equally have been handed the passphrase it stands in for, which is
#     already shared and forwardable. It buys convenience, not secrecy.
#   * IT STILL FAILS CLOSED. Verification needs the configured secret, so a
#     deployment with no secret has nothing to check a token against and the
#     gate shuts exactly as before.
#
# The cookie is per-ORIGIN, so the client app and the staff app keep separate
# ones on their own subdomains -- and even if a token crossed over it would
# fail the other app's HMAC, because the two passphrases differ.

REMEMBER_DAYS = 30          # 0 turns the cookie off; the gate reverts to
                            # session-only and Ross re-enters on every reload.
COOKIE_PREFIX = "jsa_portal_"


def _cookie_name(secret_name: str) -> str:
    return COOKIE_PREFIX + secret_name


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(secret: str, days: int = REMEMBER_DAYS) -> str:
    """`<expires>.<hmac>` — the expiry is inside the signature, so a browser
    cannot push it forward."""
    expires = str(int(time.time()) + days * 86400)
    return f"{expires}.{_sign(secret, expires)}"


def token_is_valid(token: str, secret: str) -> bool:
    if not token or not secret:
        return False
    expires, _, sig = token.partition(".")
    if not sig or not expires.isdigit():
        return False
    if int(expires) <= time.time():
        return False
    return hmac.compare_digest(sig, _sign(secret, expires))


def _cookie(name: str) -> str:
    """st.context.cookies, defensively. It is absent on older Streamlit and can
    raise when there is no live request context (a bare script run, a test)."""
    try:
        return st.context.cookies.get(name) or ""
    except Exception:
        return ""


def _remember_in_browser(secret_name: str, token: str) -> None:
    """
    Write the cookie from the page, because Streamlit cannot write one.

    `Secure` is conditional: on http://localhost a Secure cookie is silently
    DROPPED, so hard-coding it would make this work on the deployed app and do
    nothing in local testing -- the shape of bug this repo keeps recording.
    """
    max_age = REMEMBER_DAYS * 86400
    js = (
        "<script>(function(){try{"
        f"var v={json.dumps(token)};"
        f"var n={json.dumps(_cookie_name(secret_name))};"
        "var s=(location.protocol==='https:')?';Secure':'';"
        f"document.cookie=n+'='+v+';path=/;max-age={max_age};SameSite=Lax'+s;"
        "}catch(e){}})();</script>"
    )
    try:
        st.html(js, unsafe_allow_javascript=True)
    except TypeError:          # older Streamlit without the JS flag
        import streamlit.components.v1 as _stc
        _stc.html(js, height=0)


def forget_in_browser(secret_name: str = DEFAULT_SECRET) -> None:
    """Expire the cookie. Nothing calls this yet; it is the sign-out hook."""
    js = (
        "<script>(function(){try{"
        f"document.cookie={json.dumps(_cookie_name(secret_name))}"
        "+'=;path=/;max-age=0';"
        "}catch(e){}})();</script>"
    )
    try:
        st.html(js, unsafe_allow_javascript=True)
    except TypeError:
        import streamlit.components.v1 as _stc
        _stc.html(js, height=0)


def _shell(title: str, body_html: str) -> None:
    st.markdown(
        f"""
        <div style="max-width:430px;margin:10vh auto 0;text-align:center;">
          <div style="font-size:1.4rem;font-weight:600;color:#32373c;
                      font-family:'EB Garamond',Georgia,serif;margin-bottom:6px;">{title}</div>
          <div style="color:#64748b;font-size:0.9rem;line-height:1.5;">{body_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def require_passphrase(secret_name: str = DEFAULT_SECRET, *,
                       title: str = "JSA Livestock Portal",
                       subtitle: str = "Enter the access passphrase to continue.") -> None:
    """
    Block the script unless this session has entered the passphrase.

    Returns normally when unlocked. Otherwise renders the prompt and calls
    st.stop(), so nothing after it ever runs.
    """
    if is_unlocked(secret_name):
        # The cookie is written on the run AFTER the one that accepted the
        # passphrase. st.rerun() tears the page down immediately, so a <script>
        # emitted beside it may never reach the browser -- the token is parked
        # in session_state and flushed here instead, once, on a page that is
        # actually rendering.
        pending = st.session_state.pop(f"_issue__{secret_name}", None)
        if pending:
            _remember_in_browser(secret_name, pending)
        return

    secret = configured_passphrase(secret_name)

    # A valid cookie unlocks without a prompt. Checked AFTER the session-state
    # fast path and BEFORE the "not configured" branch, so a deployment with no
    # secret still has nothing to verify against and still fails closed.
    if secret and REMEMBER_DAYS and token_is_valid(_cookie(_cookie_name(secret_name)), secret):
        st.session_state[_session_key(secret_name)] = True
        return

    if not secret:
        _shell(
            f"{title} is not configured",
            f"No <code>{secret_name}</code> is set for this deployment, so access "
            "cannot be verified and this page is closed.<br><br>"
            "Add it to the app&rsquo;s secrets to restore it.",
        )
        st.stop()

    _shell(title, subtitle)

    attempts_key = f"_attempts__{secret_name}"
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form(f"gate__{secret_name}", clear_on_submit=False):
            entered = st.text_input("Passphrase", type="password",
                                    label_visibility="collapsed", placeholder="Passphrase")
            submitted = st.form_submit_button("Enter", use_container_width=True)

        if submitted:
            # compare_digest, not ==, so a wrong guess takes the same time
            # whatever its first character is.
            if hmac.compare_digest(entered.strip(), secret):
                st.session_state[_session_key(secret_name)] = True
                if REMEMBER_DAYS:
                    # Parked, not written: st.rerun() below ends this run at
                    # once. The unlocked branch at the top flushes it.
                    st.session_state[f"_issue__{secret_name}"] = issue_token(secret)
                # Rerun so the caller continues with the form gone, rather than
                # rendering the page underneath it.
                st.rerun()
            else:
                st.session_state[attempts_key] = st.session_state.get(attempts_key, 0) + 1
                st.error("Incorrect passphrase.")

        if st.session_state.get(attempts_key, 0) >= 3:
            st.caption("Contact John Stewart &amp; Associates if you need the current passphrase.")

    st.stop()
