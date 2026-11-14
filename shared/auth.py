"""
Single shared login gate for the JSA Home Page.

Modeled on basis-tracker's own APP_PASSWORD gate, but keyed off ADMIN_PASSWORD
and run once at the shell level (Home.py) instead of once per dashboard — so
logging in covers every merged page in the session, and there's no risk of
each dashboard's own gate stacking awkwardly with this one.
"""
import hmac
import os
import streamlit as st


def require_admin_login():
    """Gate the whole app behind ADMIN_PASSWORD (secret or env). Unset -> open."""
    expected = None
    try:
        expected = st.secrets.get("ADMIN_PASSWORD")
    except Exception:
        pass
    expected = expected or os.environ.get("ADMIN_PASSWORD")

    if not expected or st.session_state.get("_jsa_authed"):
        return

    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.markdown(
            "<div style='text-align:center;padding-top:64px'>"
            "<div style='font-size:24px;font-weight:700;color:#32373c;"
            "font-family:\"EB Garamond\",Georgia,serif'>"
            "JSA Admin Portal</div>"
            "<div style='color:#64748b;font-size:13px;margin:6px 0 16px'>"
            "John Stewart &amp; Associates · enter the password to continue</div></div>",
            unsafe_allow_html=True,
        )
        entered = st.text_input(
            "Password", type="password", key="_jsa_pw_input",
            label_visibility="collapsed", placeholder="Password",
        )
        if entered:
            if entered == expected:
                st.session_state["_jsa_authed"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()


def require_client_login():
    """Gate the CLIENT portal behind one shared CLIENT_PASSWORD (secret or env).

    UNLIKE require_admin_login, THIS FAILS CLOSED: with no CLIENT_PASSWORD configured nobody gets in
    and the page says why. The staff gate can afford to be open when unset (local dev), but a client
    deployment that lost its secret on a redeploy must not come up quietly open to the internet.
    A different value from ADMIN_PASSWORD, so handing clients this one never hands out the staff portal."""
    expected = None
    try:
        expected = st.secrets.get("CLIENT_PASSWORD")
    except Exception:
        pass
    expected = expected or os.environ.get("CLIENT_PASSWORD")

    # Individual Microsoft sign-in (shared/signin.py) takes over as soon as the app's Secrets carry a complete [auth]
    # block; without one this function is exactly the shared-password gate it always was. The shared password then only
    # opens anything when SIGNIN_PASSWORD_FALLBACK is on (the weeks while clients move over).
    from shared import signin
    if signin.is_enabled():
        signin.require_signin(
            title="JSA Client Portal", need="client",
            password_fallback=(expected if expected and signin.password_fallback_enabled() else None))
        return

    if expected and st.session_state.get("_jsa_client_authed"):
        return

    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.markdown(
            "<div style='text-align:center;padding-top:64px'>"
            "<div style='font-size:24px;font-weight:700;color:#32373c;"
            "font-family:\"EB Garamond\",Georgia,serif'>"
            "JSA Client Portal</div>"
            "<div style='color:#64748b;font-size:13px;margin:6px 0 16px'>"
            "John Stewart &amp; Associates · enter your access password to continue</div></div>",
            unsafe_allow_html=True,
        )
        if not expected:
            st.error("This portal is not configured yet (no access password is set), so it is closed.")
            st.stop()
        entered = st.text_input(
            "Password", type="password", key="_jsa_client_pw_input",
            label_visibility="collapsed", placeholder="Password",
        )
        if entered:
            if hmac.compare_digest(entered.strip(), str(expected)):
                st.session_state["_jsa_client_authed"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()
