"""A simple shared-password gate — not per-user accounts, just a single generic
password the whole app sits behind since it's public and link-accessible. Session-only:
closing the tab requires re-entering it."""
import streamlit as st

APP_PASSWORD = "jpsi"


def require_password() -> None:
    if st.session_state.get("authenticated"):
        return

    _, center, _ = st.columns([1, 1, 1])
    with center:
        st.markdown("##### JSA Risk Analyzer")
        st.caption("Enter the password to continue.")
        pwd = st.text_input("Password", type="password", key="auth_password_input")
        if st.button("Enter", type="primary"):
            if pwd == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()
