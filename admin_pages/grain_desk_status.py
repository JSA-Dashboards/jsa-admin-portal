"""Grain Marketing Desk: status page (Admin).

A hand-written portal page, not a synced mirror, so it lives outside apps/. This repo is public: keep it to
facts that are safe to publish (no passwords, keys, account or user names).
Look and feel matches the CFTC COT dashboard (JSA green, EB Garamond headings, JPSI logo header).
"""
import streamlit as st

APP_URL = "https://jsa-grain-marketing.streamlit.app"
REPO_URL = "https://github.com/JSA-Dashboards/Grain-Marketing-App-Dashboard"
LOGO_URL = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"

# palette shared with the CFTC COT dashboard and the Livestock Portal
JSA_GREEN = "#5e7164"
BG, SURFACE, BORDER = "#f6f8f7", "#ffffff", "#d7e2dc"
TEXT, MUTED = "#32373c", "#5f7267"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&family=Source+Sans+3:wght@400;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"] {{ background-color:{BG}; color:{TEXT}; }}
html, body, p, span, div, label, button, li {{ font-family:'Source Sans 3','Source Sans Pro',sans-serif; }}
.dash-header {{ display:flex; align-items:center; gap:18px; padding-bottom:10px;
    border-bottom:1px solid {BORDER}; margin-bottom:14px; }}
.dash-header img {{ height:40px; }}
.dash-header .t b {{ font-family:'EB Garamond',Georgia,serif; font-size:1.7rem; color:{TEXT}; font-weight:600; }}
.dash-header .t div {{ font-size:.85rem; color:{MUTED}; }}
@media (max-width: 640px) {{ .dash-header img {{ display:none; }} }}
.asof {{ color:{MUTED}; font-size:0.82rem; margin-bottom:12px; }}
.asof b {{ color:{TEXT}; }}
div[class*="st-key-gd_card_"] {{ background:{SURFACE}; border:1px solid {BORDER}; border-top:3px solid {JSA_GREEN};
    border-radius:10px; padding:16px 20px; height:100%; }}
div[class*="st-key-gd_card_"] h3 {{ font-family:'EB Garamond',Georgia,serif; color:{TEXT}; font-weight:600; }}
.sec-header {{ color:{MUTED}; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.1em; margin:18px 0 6px; }}
</style>
<div class="dash-header">
  <img src="{LOGO_URL}" alt="John Stewart &amp; Associates">
  <div class="t"><b>Grain Marketing Desk</b>
  <div>Broker grain marketing app &middot; John Stewart &amp; Associates</div></div>
</div>
<div class="asof">Status as of <b>October 15, 2026</b></div>
""", unsafe_allow_html=True)

st.link_button("Open the Grain Marketing Desk", APP_URL, type="primary", icon=":material/open_in_new:")

st.markdown(
    "Megan Brott's grain marketing app for brokers and their customers: crop plans, contracts, "
    "storage, insurance and cash bids in one place. Each broker sees and edits only their own customers; "
    "admins see everything."
)

col_done, col_open = st.columns(2)

with col_done:
    with st.container(key="gd_card_done"):
        st.subheader(":material/check_circle: Done")
        st.markdown(
            "- App deployed on Streamlit Cloud\n"
            "- Sign-in: shared access password, then a work email and a 6-digit emailed code\n"
            "- Data stored in Snowflake\n"
            "- Futures, cash bids and weather refresh automatically each night\n"
            "- Two admins set up (Megan Brott, Kolten Postin)\n"
            "- Source code on GitHub"
        )

with col_open:
    with st.container(key="gd_card_open"):
        st.subheader(":material/pending: Still open")
        st.markdown(
            "- Test the sign-in end to end\n"
            "- Import Megan's existing farms and customers\n"
            "- Add the brokers (name must match the Broker field on their farms)\n"
            "- Turn on contract photo scanning (needs JSA's Claude API key)\n"
            "- Confirm the final access password before wider rollout\n"
            "- Decide what market data outside brokers may see (CME licence)"
        )

st.markdown('<div class="sec-header">Details</div>', unsafe_allow_html=True)

with st.expander("How to add or remove a broker"):
    st.markdown(
        "Sign in to the Grain Marketing Desk as an admin and open **People** in the top menu. "
        "Add the person with their @jpsi.com email and the name exactly as it appears in the Broker field "
        "of their farms. To remove access, switch **Can sign in** off; they are signed out within minutes."
    )

with st.expander("How it works"):
    st.markdown(
        "The app runs on Streamlit Cloud. The nightly jobs run on the JSA droplet and write futures, bids "
        "and weather to the same Snowflake schema the app reads. Producer access is planned for the end of the year."
    )

st.link_button("Source code on GitHub", REPO_URL, icon=":material/code:")
