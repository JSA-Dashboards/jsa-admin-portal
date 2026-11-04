"""A simple shared-password gate — not per-user accounts, just a single generic
password the whole app sits behind since it's public and link-accessible. Session-only:
closing the tab requires re-entering it.

The password lives in Streamlit secrets (`[app] password = "..."`), never in the repo. If it
isn't configured the gate stays shut for everyone."""
import hmac

import streamlit as st

from jsa_risk.config import get_app_password


def password_matches(entered: str, expected) -> bool:
    return bool(expected) and hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8"))


def require_password() -> None:
    if st.session_state.get("authenticated"):
        return

    expected = get_app_password()
    _, center, _ = st.columns([1, 1, 1])
    with center:
        st.markdown("##### JSA Risk Analyzer")
        if not expected:
            st.error("The app password isn't configured — add an [app] block with a password "
                     "to the app's secrets.")
            st.stop()
        st.caption("Enter the password to continue.")
        pwd = st.text_input("Password", type="password", key="auth_password_input")
        if st.button("Enter", type="primary"):
            if password_matches(pwd, expected):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()
