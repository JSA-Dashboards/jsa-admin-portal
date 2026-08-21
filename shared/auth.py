"""
Single shared login gate for the JSA Home Page.

Modeled on basis-tracker's own APP_PASSWORD gate, but keyed off ADMIN_PASSWORD
and run once at the shell level (Home.py) instead of once per dashboard — so
logging in covers every merged page in the session, and there's no risk of
each dashboard's own gate stacking awkwardly with this one.
"""
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
