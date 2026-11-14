"""Portal Access (Admin): who may sign in to the client portal.

A hand-written staff page. The list lives in Snowflake (JSA.PORTAL_ACCESS.USERS, created by snowflake/portal_access.sql);
the client portal reads it on every session (five-minute cache), so a change here reaches a signed-in client within five
minutes. This repo is public: nothing on this page may carry a secret.
"""
import os

import pandas as pd
import streamlit as st

from shared import access_store

# Staff only. The tile is not in CLIENT_PAGES, so the client portal never registers this page; this is a second lock.
if os.environ.get("JSA_PORTAL_VIEW") == "client":
    st.error("This page is for JSA staff.")
    st.stop()

st.markdown("<h2 style='font-family:\"EB Garamond\",Georgia,serif;margin-bottom:0'>Portal Access</h2>",
            unsafe_allow_html=True)
st.caption("Who may sign in to the client portal (clients.jpsi.com) with Microsoft sign-in. A person types their email "
           "address and gets a one-time code; they get in only if they are on this list and switched on. "
           "Changes reach the client portal within five minutes.")


def _load():
    try:
        return access_store.read_all(), None
    except Exception as e:  # noqa: BLE001 - shown to staff, with the likely cause
        return None, e


rows, err = _load()
if err is not None:
    st.error("Could not read the access list. If it has not been created yet, run snowflake/portal_access.sql in "
             "Snowsight as ACCOUNTADMIN (it is in the portal repo).")
    st.caption(f"Technical detail: {str(err)[:300]}")
    st.stop()

# ── add ───────────────────────────────────────────────────────────────────────
with st.form("portal_access_add", clear_on_submit=True):
    st.markdown("**Add people**")
    pasted = st.text_area("Email addresses", placeholder="one or more, separated by commas, spaces or new lines",
                          height=90)
    c1, c2, c3 = st.columns([1, 2, 2])
    role = c1.selectbox("Access", access_store.ROLES, help="'client' opens the client portal; 'staff' also does, and is "
                        "reserved for the staff portal's own sign-in later.")
    name = c2.text_input("Name (optional)", help="Applied to every address above.")
    note = c3.text_input("Company or note (optional)")
    if st.form_submit_button("Add / switch on", type="primary"):
        good, bad = access_store.parse_emails(pasted)
        if bad:
            st.warning("Not valid email addresses, left out: " + ", ".join(bad))
        if not good:
            st.info("Nothing to add.")
        else:
            try:
                n = access_store.add_users(good, role, name=name, note=note, by="Portal Access page")
                st.success(f"{n} address(es) added or switched on.")
                rows, _ = _load()
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not save: {str(e)[:300]}")

# ── the list ──────────────────────────────────────────────────────────────────
st.markdown(f"**The list** ({len(rows or [])} people)")
if rows:
    df = pd.DataFrame(rows)
    df["ACTIVE"] = df["ACTIVE"].map(lambda v: "on" if v else "OFF")
    df = df.rename(columns={"EMAIL": "Email", "ROLE": "Access", "NAME": "Name", "NOTE": "Company / note",
                            "ACTIVE": "Status", "ADDED_AT": "Added (UTC)", "ADDED_BY": "Added by",
                            "UPDATED_AT": "Updated (UTC)"})
    st.dataframe(df, hide_index=True, width="stretch")

    emails = [r["EMAIL"] for r in rows]
    st.markdown("**Change one person**")
    pick = st.selectbox("Person", emails, label_visibility="collapsed", index=None, placeholder="Choose an address")
    if pick:
        current = next(r for r in rows if r["EMAIL"] == pick)
        b1, b2, b3 = st.columns([1, 1, 2])
        if current["ACTIVE"]:
            if b1.button("Switch off", key="pa_off"):
                access_store.set_active(pick, False)
                st.success(f"{pick} switched off.")
                st.rerun()
        else:
            if b1.button("Switch on", key="pa_on", type="primary"):
                access_store.set_active(pick, True)
                st.success(f"{pick} switched on.")
                st.rerun()
        with b3:
            sure = st.checkbox("Delete this row for good", key="pa_sure")
            if sure and st.button("Delete", key="pa_del"):
                access_store.remove(pick)
                st.success(f"{pick} deleted.")
                st.rerun()
else:
    st.info("Nobody is on the list yet.")

st.caption("Switching someone off keeps their row (so you can see who had access and switch them back on); delete only "
           "removes a mistake.")
