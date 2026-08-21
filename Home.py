"""
JSA Admin Portal — shared shell for JPSI's internal dashboards.

Makes the one set_page_config call allowed per multi-page run, sets every
merged dashboard's env vars ONCE at process startup (never again — safe for
concurrent sessions once this is deployed multi-user), runs the single shared
login gate, then hands off to st.navigation (top nav, no sidebar).
"""
import os
from pathlib import Path

import streamlit as st

from shared.auth import require_admin_login

HERE = Path(__file__).parent


def _asset(name: str) -> str:
    return str(HERE / "assets" / name)


st.set_page_config(
    page_title="JSA Admin Portal",
    page_icon=_asset("jsa_favicon.png"),
    layout="wide",
)

# ── One-time env var setup for every merged dashboard ────────────────────────
# Each dashboard's own DB env var was renamed (in its copy under apps/) to a
# distinct name so two apps sharing this one process never clobber each
# other's DATABASE_URL. Setting all of them once here, before navigation ever
# runs, means nothing mutates os.environ again after startup.
_ENV_SECRET_KEYS = (
    "BASISTRACKER_DATABASE_URL",  # basis_tracker's own DB (was DATABASE_URL)
    "RIVER_DATABASE_URL",         # basis_tracker's cross-read of river data
    "RIVERFOB_DATABASE_URL",      # river_fob's own DB (was DATABASE_URL)
    "BASIS_DATABASE_URL",         # river_fob's cross-read of basis data
    "FOB_VESSEL_API_KEY",
    "FOB_VESSEL_SERVICE_NAME",
    "APP_PASSWORD",
    "VIEW_ONLY",
    # crop_conditions reads NASS_API_KEY straight from st.secrets (with a
    # working hardcoded fallback) — no os.environ bridge needed for it.
)
for _key in _ENV_SECRET_KEYS:
    try:
        if _key in st.secrets and not os.environ.get(_key):
            os.environ[_key] = str(st.secrets[_key])
    except Exception:
        pass  # st.secrets not available (no secrets.toml) — fine locally

require_admin_login()

# ── Landing page ──────────────────────────────────────────────────────────────
LIVE_DASHBOARDS = [
    {"title": "Basis Tracker",
     "desc": "ADM + Mendota cash grain basis, rail FOB, river FOB, trends.",
     "page": "apps/basis_tracker/app.py", "url_path": "basis-tracker"},
    {"title": "River FOB Portal",
     "desc": "CIF NOLA, barge freight, and location FOB values by river reach.",
     "page": "apps/river_fob/app.py", "url_path": "river-fob"},
    {"title": "RMA Production Map",
     "desc": "Interactive state → county drill-down of RMA yield & production.",
     "page": "apps/rma_map/app.py", "url_path": "rma-map"},
    {"title": "Crop Conditions & Yield Model",
     "desc": "NASS weekly crop conditions, HRW weighted index, analog yield model.",
     "page": "apps/crop_conditions/app.py", "url_path": "crop-conditions"},
    {"title": "Rail Shipments",
     "desc": "USDA agtransport weekly rail carloads by railroad and destination.",
     "page": "apps/rail_shipments/app.py", "url_path": "rail-shipments"},
    {"title": "Domestic Production",
     "desc": "USDA NASS corn production — national overview and state-level detail.",
     "page": "apps/domestic_production/app.py", "url_path": "domestic-production"},
]

COMING_SOON = [
    "Beef Weight", "Beef Cutout",
    "Livestock Inventory", "WASDE", "Vessel Lineup",
    "High/Low Model",
]

_TILE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&display=swap');

div[class*="st-key-tile_"] {
    background: #32373c;
    border-radius: 4px;
    box-shadow: 0 6px 0 #ffffff, 0 6px 14px rgba(0,0,0,0.18);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    margin-bottom: 28px;
}
div[class*="st-key-tile_"]:hover {
    transform: translateY(-3px);
    box-shadow: 0 6px 0 #ffffff, 0 10px 20px rgba(0,0,0,0.25);
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"] {
    display: flex; align-items: center; justify-content: center;
    height: 132px; padding: 14px 18px; text-decoration: none !important;
    text-align: center;
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"] p {
    color: #ffffff !important;
    font-family: 'EB Garamond', Georgia, serif !important;
    font-size: 21px !important;
    font-weight: 600 !important;
    line-height: 1.3 !important;
    margin: 0 !important;
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"]:hover p {
    color: #cfe8fb !important;
}
div[class*="st-key-soon_"] {
    background: #e9edf0;
    border-radius: 4px;
    box-shadow: 0 6px 0 #ffffff;
    height: 132px; margin-bottom: 28px;
    display: flex; align-items: center; justify-content: center;
    text-align: center; padding: 14px 18px;
}
div[class*="st-key-soon_"] p {
    color: #7c8791 !important;
    font-family: 'EB Garamond', Georgia, serif !important;
    font-size: 18px !important;
    font-weight: 600 !important;
    margin: 0 !important;
}
.jsa-soon-tag {
    display: block; font-family: 'Source Sans Pro', system-ui, sans-serif;
    font-size: 10px; color: #0693e3; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.06em; margin-bottom: 4px;
}
</style>
"""


def render_home():
    st.markdown(_TILE_CSS, unsafe_allow_html=True)
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        st.image(_asset("logo-full.png"), width=140)
    with col_title:
        st.markdown(
            "<div style='padding-top:14px'>"
            "<h2 style='margin:0;color:#32373c;font-family:\"EB Garamond\",Georgia,serif'>"
            "JSA Admin Portal</h2>"
            "<div style='color:#64748b'>John Stewart &amp; Associates · pick a dashboard</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.write("")
    cols = st.columns(3)
    for i, d in enumerate(LIVE_DASHBOARDS):
        with cols[i % 3]:
            with st.container(key=f"tile_{i}"):
                st.page_link(d["page"], label=d["title"])

    st.caption("Pilot migrated the first three dashboards into this shell — the rest follow the same pattern.")
    soon_cols = st.columns(3)
    for i, title in enumerate(COMING_SOON):
        with soon_cols[i % 3]:
            with st.container(key=f"soon_{i}"):
                st.markdown(
                    f"<div><span class='jsa-soon-tag'>Coming soon</span><p>{title}</p></div>",
                    unsafe_allow_html=True,
                )


home_page = st.Page(render_home, title="Home", url_path="home", default=True)

pg = st.navigation(
    [home_page] + [
        st.Page(d["page"], title=d["title"], url_path=d["url_path"])
        for d in LIVE_DASHBOARDS
    ],
    position="top",
)
pg.run()
