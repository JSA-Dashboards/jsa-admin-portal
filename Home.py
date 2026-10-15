"""
JSA Admin Portal — shared shell for JPSI's internal dashboards.

Makes the one set_page_config call allowed per multi-page run, sets every
merged dashboard's env vars ONCE at process startup (never again — safe for
concurrent sessions once this is deployed multi-user), runs the single shared
login gate, then hands off to st.navigation (top nav, no sidebar).
"""
import html
import os
from pathlib import Path

import streamlit as st

from shared.auth import require_admin_login
from shared.fresh_modules import drop_changed_modules

HERE = Path(__file__).parent

# Runs first on every rerun: a redeploy re-reads each page's script but keeps
# the modules it imported, so changed sibling modules would otherwise serve old code.
drop_changed_modules()


def _asset(name: str) -> str:
    return str(HERE / "assets" / name)


st.set_page_config(
    page_title="JSA Admin Portal",
    page_icon=_asset("jsa_favicon.png"),
    layout="wide",
)

# Hide the Streamlit Community Cloud viewer badge (creator avatar + Streamlit
# logo, bottom-right). It is rendered by Cloud's OUTER page, not inside this
# app's iframe, so CSS in st.markdown never reaches it (verified live: still
# display:flex). The app iframe is same-origin with that page, so a script can
# add the rule to the parent document instead. Guarded by id; no-ops locally,
# where there is no outer page.
st.html(
    """<script>
    (function () {
      try {
        var doc = window.parent.document;
        if (doc.getElementById('jsa-hide-cloud-badge')) return;
        var s = doc.createElement('style');
        s.id = 'jsa-hide-cloud-badge';
        s.textContent = "[class*='_profileContainer_'],[class*='_viewerBadge_']{display:none !important;}";
        doc.head.appendChild(s);
      } catch (e) {}
    })();
    </script>""",
    unsafe_allow_javascript=True,
)

# ── One-time env var setup for every merged dashboard ────────────────────────
# Each dashboard's own DB env var was renamed (in its copy under apps/) to a
# distinct name so two apps sharing this one process never clobber each
# other's DATABASE_URL. Setting all of them once here, before navigation ever
# runs, means nothing mutates os.environ again after startup.
_ENV_SECRET_KEYS = (
    "RIVER_DATABASE_URL",         # rail_fob's cross-read of river data (Postgres rollback)
    "BASIS_DATABASE_URL",         # rail_fob's cross-read of basis data (Postgres rollback)
    "APP_PASSWORD",
    "VIEW_ONLY",
    "MASSIVE_API_KEY",           # cost_of_carry's + grain_seasonal's Massive futures feed
    "ANTHROPIC_API_KEY",         # grain_seasonal's Ask AI tab
    # Microsoft Graph app-only mail (basis_tracker's rail rundown / client reports read these
    # from st.secrets themselves; rail_shipments' email report reads os.environ).
    "GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_SENDER",
    # crop_conditions reads NASS_API_KEY straight from st.secrets (with a
    # working hardcoded fallback) — no os.environ bridge needed for it.
)
for _key in _ENV_SECRET_KEYS:
    try:
        if _key in st.secrets and not os.environ.get(_key):
            os.environ[_key] = str(st.secrets[_key])
    except Exception:
        pass  # st.secrets not available (no secrets.toml) — fine locally

# Snowflake settings are bridged HERE too, not left to Streamlit's own export of
# root-level secrets. That export skips any value that isn't a str/int/float, so
# `USE_SNOWFLAKE = true` (a TOML boolean) never reaches os.environ, and every
# module silently falls back to its stale Postgres URL. River FOB showed
# "Postgres" / Sept 3 on 2026-10-04. Without this, the backend also depended on
# which page loaded first, because cost_of_carry and cme_feeder_cattle bridge
# these lazily, only when opened. The flag is normalized to "1", which every
# module's check accepts. SNOWFLAKE_SCHEMA is deliberately absent; see CLAUDE.md.
_SNOWFLAKE_KEYS = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_ROLE",
                   "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_PRIVATE_KEY")
try:
    if "USE_SNOWFLAKE" in st.secrets:
        _flag = str(st.secrets["USE_SNOWFLAKE"]).strip().lower()
        os.environ["USE_SNOWFLAKE"] = "1" if _flag in ("1", "true", "yes", "on") else ""
    for _key in _SNOWFLAKE_KEYS:
        if _key in st.secrets and not os.environ.get(_key):
            os.environ[_key] = str(st.secrets[_key])
except Exception:
    pass  # st.secrets not available (no secrets.toml) — fine locally

require_admin_login()

# ── Landing page ──────────────────────────────────────────────────────────────
# Order here is display order — dashboards are grouped by "category" on the
# home page, in the order each category is first seen.
LIVE_DASHBOARDS = [
    {"title": "Basis Tracker", "category": "Cash Grain",
     "desc": "Cash grain basis history for corn and soy: processing, river, rail, and milling trends.",
     "page": "apps/basis_tracker/app.py", "url_path": "basis-tracker"},
    # Bundled again 2026-10-11, now as a generated mirror of its own repo
    # (sync/apps.json) so it can't drift the way the hand-copy did.
    {"title": "River FOB Portal", "category": "Cash Grain",
     "desc": "CIF NOLA, barge freight, location FOB values by river reach, net carry and return to carry.",
     "page": "apps/river_fob/app.py", "url_path": "river-fob"},
    {"title": "Rail FOB", "category": "Cash Grain",
     "desc": "Rail corridor bids/offers plus CSX/NS origin freight netback to FOB.",
     "page": "apps/rail_fob/app.py", "url_path": "rail-fob"},

    {"title": "Cost of Carry & Seasonal Spreads", "category": "Futures, Options & Spreads",
     "desc": "CBOT/MGEX grain spreads priced against full carry, with seasonal spread analysis.",
     "page": "apps/cost_of_carry/app.py", "url_path": "cost-of-carry"},
    {"title": "Grain Seasonal Futures & Spreads", "category": "Futures, Options & Spreads",
     "desc": "CBOT corn/soybean/wheat seasonal charts, multi-leg & cross-commodity spreads, WASDE/NASS markers, AI chat.",
     "page": "apps/grain_seasonal/app.py", "url_path": "grain-seasonal-spreads"},
    {"title": "CFTC Commitments of Traders", "category": "Futures, Options & Spreads",
     "desc": "Managed money, producer, swap and index-trader positioning across ag futures, with history back to 1986.",
     "page": "apps/cftc_cot/app.py", "url_path": "cftc-cot"},
    {"title": "Risk Analyzer", "category": "Futures, Options & Spreads",
     "desc": "Black-76 options & futures portfolio risk: Greeks, price/vol/time stress grids, payoff charts and VaR.",
     "page": "apps/risk_analyzer/app.py", "url_path": "risk-analyzer"},
    {"title": "CSO & Spread Risk Analyzer", "category": "Futures, Options & Spreads",
     "desc": "CME calendar spread options on the nearby-minus-deferred spread: Greeks, stress grids, quote-implied skew and hedge effectiveness.",
     "page": "apps/cso_risk_analyzer/app.py", "url_path": "cso-risk-analyzer"},

    {"title": "RMA Production Map", "category": "Supply & Demand",
     "desc": "Interactive state → county drill-down of RMA yield & production.",
     "page": "apps/rma_map/app.py", "url_path": "rma-map"},
    {"title": "Domestic Production", "category": "Supply & Demand",
     "desc": "USDA NASS corn production — national overview and state-level detail.",
     "page": "apps/domestic_production/app.py", "url_path": "domestic-production"},
    {"title": "Crop Conditions & Yield Model", "category": "Supply & Demand",
     "desc": "NASS weekly crop conditions, HRW weighted index, analog yield model.",
     "page": "apps/crop_conditions/app.py", "url_path": "crop-conditions"},
    {"title": "JSA Yield Observations", "category": "Supply & Demand",
     "desc": "County yield reports from Ag Trader Talk and JSA, reports vs normal, field issues, variety and strip trials.",
     "page": "apps/yield_portal/app.py", "url_path": "yield-observations"},
    {"title": "EIA Energy", "category": "Supply & Demand",
     "desc": "Natural gas production/storage/prices + ethanol & biofuels capacity.",
     "page": "apps/eia_energy/app.py", "url_path": "eia-energy"},
    {"title": "WASDE Dashboard", "category": "Supply & Demand",
     "desc": "Monthly USDA balance sheets, revision progression, WASDE tendencies by release month, and top-country breakdowns for corn, soybeans, wheat, cotton, rice, and soy oil.",
     "page": "https://jsa-wasde-dashboard.streamlit.app/", "url_path": "wasde"},

    # Mirror of global-exports-dashboard (reads a daily Snowflake cache + live USDA
    # PSD). The old hand-copy had gone stale; this one is synced.
    {"title": "Major Exporters", "category": "Grain Flows",
     "desc": "Monthly exports by major origin for corn, soybeans, meal and wheat, with USDA forecasts, inspections and export sales.",
     "page": "apps/major_exporters/app.py", "url_path": "major-exporters"},
    {"title": "Rail Shipments", "category": "Grain Flows",
     "desc": "USDA agtransport weekly rail carloads by railroad and destination.",
     "page": "apps/rail_shipments/app.py", "url_path": "rail-shipments"},
    {"title": "Vessel Lineup", "category": "Grain Flows",
     "desc": "Export vessel lineup by region — USG, PNW, TXG — and commodity.",
     "page": "apps/vessel_lineup/app.py", "url_path": "vessel-lineup"},

    {"title": "CME Feeder Cattle Index", "category": "Livestock",
     "desc": "12-state feeder steer index trend, weekly rundown, and basis by sale location.",
     "page": "apps/cme_feeder_cattle/app.py", "url_path": "cme-feeder-cattle-index"},
    {"title": "Cattle on Feed", "category": "Livestock",
     "desc": "USDA on-feed inventory, placements, marketings, and the quarterly heifers-on-feed share.",
     "page": "apps/cattle_on_feed/app.py", "url_path": "cattle-on-feed"},
    {"title": "Beef Weight", "category": "Livestock",
     "desc": "USDA NASS weekly beef slaughter weights by class, dressed & live.",
     "page": "apps/beef_weight/app.py", "url_path": "beef-weight"},
    {"title": "Beef Cutout", "category": "Livestock",
     "desc": "Daily USDA boxed beef cutout — Choice & Select composites, spread, volume.",
     "page": "apps/beef_cutout/app.py", "url_path": "beef-cutout"},
    {"title": "Livestock Inventory", "category": "Livestock",
     "desc": "USDA NASS livestock, poultry, aquaculture inventory & dairy production.",
     "page": "apps/livestock_inventory/app.py", "url_path": "livestock-inventory"},
    {"title": "Cash Cattle Trade", "category": "Livestock",
     "desc": "Combined Steer/Heifer FOB & Dressed prices, plus national negotiated cash trade volume.",
     "page": "apps/cash_trade/app.py", "url_path": "cash-trade"},

    {"title": "Teams Broadcast", "category": "Admin",
     "desc": "Send a message to Teams chats or WhatsApp groups in one shot.",
     "page": "apps/teams_broadcast/app.py", "url_path": "teams-broadcast"},
]

COMING_SOON = [
    "High/Low Model",
]

_TILE_CSS = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&display=swap');

/* The tile IS the dark box: padding lives on it and overflow is clipped to the
   rounded corners, so the title link and its description both sit inside it.
   Same look as the Livestock Portal's tiles. */
div[class*="st-key-tile_"] {
    background: #32373c;
    border-radius: 6px;
    overflow: hidden;
    padding: 16px 18px 18px;
    min-height: 132px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.16);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    margin-bottom: 22px;
}
div[class*="st-key-tile_"]:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 18px rgba(0,0,0,0.26);
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"] {
    display: block;
    padding: 0 !important;
    margin: 0 !important;
    text-align: left;
    text-decoration: none !important;
    background: transparent !important;
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"] p {
    color: #ffffff !important;
    font-family: 'EB Garamond', Georgia, serif !important;
    font-size: 20px !important;
    font-weight: 600 !important;
    line-height: 1.22 !important;
    letter-spacing: 0.1px !important;
    margin: 0 !important;
    overflow-wrap: anywhere;
    hyphens: none;
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"]:hover p {
    color: #cfe8fb !important;
}
.jsa-tile-desc {
    color: #a8b3ad;
    font-family: 'Source Sans Pro', system-ui, -apple-system, sans-serif;
    font-size: 12.5px;
    line-height: 1.45;
    margin-top: 9px;
}
.jsa-cat-hdr {
    color: #32373c;
    font-family: 'EB Garamond', Georgia, serif;
    font-size: 22px;
    font-weight: 600;
    margin: 10px 0 12px;
    padding-bottom: 6px;
    border-bottom: 1px solid #d7dde2;
}
div[class*="st-key-soon_"] {
    background: #e9edf0;
    border-radius: 6px;
    min-height: 132px; margin-bottom: 22px;
    padding: 16px 18px 18px;
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

/* Tablet widths only (an iPad held upright): four across leaves each tile too narrow
   for its title, so wrap to two across. Streamlit already stacks the columns on a
   phone (under 640px) and a laptop or landscape iPad is wider than 1000px, so the
   four-across desktop grid is not touched by this block. */
@media (min-width: 641px) and (max-width: 1000px) {
    div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-tile_"]),
    div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-soon_"]) {
        flex-wrap: wrap;
    }
    div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-tile_"]) > div[data-testid="stColumn"],
    div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-soon_"]) > div[data-testid="stColumn"] {
        /* no growing: a short last row keeps the same tile width as the rows above */
        flex: 0 0 calc(50% - 0.5rem) !important;
        width: calc(50% - 0.5rem) !important;
        min-width: calc(50% - 0.5rem) !important;
    }
    /* the empty slots that pad a short last row would only add blank gaps */
    div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-tile_"]) > div[data-testid="stColumn"]:not(:has(div[data-testid="stElementContainer"])) {
        display: none;
    }
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

    categories = []
    for d in LIVE_DASHBOARDS:
        if d["category"] not in categories:
            categories.append(d["category"])

    # Four tiles per row, like the Livestock Portal. Always ask for
    # TILES_PER_ROW columns, even on a short last row, so every tile keeps the
    # same width as the rows above it instead of stretching to fill.
    TILES_PER_ROW = 4
    tile_i = 0
    for cat in categories:
        st.markdown(f"<div class='jsa-cat-hdr'>{html.escape(cat)}</div>", unsafe_allow_html=True)
        cat_dashboards = [d for d in LIVE_DASHBOARDS if d["category"] == cat]
        for start in range(0, len(cat_dashboards), TILES_PER_ROW):
            cols = st.columns(TILES_PER_ROW)
            for offset, d in enumerate(cat_dashboards[start:start + TILES_PER_ROW]):
                with cols[offset]:
                    with st.container(key=f"tile_{tile_i}"):
                        st.page_link(d["page"], label=d["title"])
                        st.markdown(
                            f"<div class='jsa-tile-desc'>{html.escape(d['desc'])}</div>",
                            unsafe_allow_html=True,
                        )
                tile_i += 1

    st.caption("Pilot migrated the first three dashboards into this shell — the rest follow the same pattern.")
    soon_cols = st.columns(TILES_PER_ROW)
    for i, title in enumerate(COMING_SOON):
        with soon_cols[i % TILES_PER_ROW]:
            with st.container(key=f"soon_{i}"):
                st.markdown(
                    f"<div><span class='jsa-soon-tag'>Coming soon</span><p>{title}</p></div>",
                    unsafe_allow_html=True,
                )


home_page = st.Page(render_home, title="Home", url_path="home", default=True)

# Basis Tracker's and River FOB's "page" is an external URL (their own live
# Cloud apps, not bundled copies) -- st.page_link handles that fine on the home
# tile, but st.Page/st.navigation only take local pages, so they're excluded here.
pg = st.navigation(
    [home_page] + [
        st.Page(d["page"], title=d["title"], url_path=d["url_path"])
        for d in LIVE_DASHBOARDS
        if not d["page"].startswith("http")
    ],
    position="top",
)

# Dashboards synced from their standalone repos run unmodified, and many of them
# hide Streamlit's header/toolbar for their standalone look -- which is where this
# portal's top navigation lives. The extra specificity ("html body") beats those
# rules wherever they were injected, so no per-app patch is needed. Home keeps its
# own chrome.
if pg.title != "Home":
    st.markdown(
        "<style>"
        "html body header[data-testid='stHeader'], html body [data-testid='stHeader'],"
        "html body [data-testid='stToolbar']"
        "{display:flex !important; visibility:visible !important;}"
        "</style>",
        unsafe_allow_html=True,
    )

# Narrow screens only (tablet and phone). The dashboards pad their content 2rem a
# side, which on a phone leaves about 17% of the width unused, and a few draw plain
# HTML tables that would push the page sideways. Nothing here applies above 1000px,
# so the desktop layout is untouched. Measured on Vessel Lineup: content 311px of 375.
_NARROW_CSS = """
<style>
@media (max-width: 1000px) {
    html body [data-testid="stMainBlockContainer"],
    html body .block-container {
        padding-left: 1.25rem !important;
        padding-right: 1.25rem !important;
    }
}
@media (max-width: 640px) {
    html body [data-testid="stMainBlockContainer"],
    html body .block-container {
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
    }
    /* a wide hand-built table scrolls inside its own box instead of widening the page */
    html body [data-testid="stMarkdownContainer"] table {
        display: block;
        max-width: 100%;
        overflow-x: auto;
    }
    html body .vega-embed { max-width: 100%; overflow-x: auto; }
}
</style>
"""
st.markdown(_NARROW_CSS, unsafe_allow_html=True)
pg.run()
