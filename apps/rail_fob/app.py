"""
Rail FOB Sheet — JPSI

Read-only sheet view of the rail corridor bids/offers already archived by the
basis tracker (`rail_fob` table, sources 'manual' + 'palmetto'), plus a
static-freight netback calculator (CSX / NS origin spreads -> FOB) built from
Kolten's Rail Spreads.xlsx. Visual language matches the River FOB Portal
(Source Sans Pro, JPSI dark/blue, card-style "sheet-wrap" tables, background-
tinted up/down cells) per Kolten's 2026-08-24 request to restart the styling
from that reference instead of the original dense mono-terminal look.

Three top-level tabs keep the raw bid boards separate from the CSX/NS origin
economics, instead of one long mixed scroll.
"""
import sys as _sys  # portal-sync: sibling imports resolve to this folder
from pathlib import Path as _Path  # portal-sync
_sys.path.insert(0, str(_Path(__file__).parent))  # portal-sync
import base64
import calendar
import hashlib
import json
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta
from html import escape as _esc
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

import bn_fsc as BNF
import bn_inputs as BNI
import bn_locator as BL
import cn_miles as CM
import ethanol_index as EI
import ns_miles as NSM
import freight_data as FD
import rail_data as RD
import rail_fsc as RF
import rail_reference as REF
import river_data as RVD
import up_spreads as US
import shipment_data as SD
from rail_corridors import MANUAL_SECTIONS, RAIL_DISPLAY, RAIL_COLORS

# The 💵 Net Carry tab's modules (vendored from the basis tracker — see CLAUDE.md). Guarded so that a runtime that
# can't import them costs only that tab, never the whole portal: net_carry_compare.py has a backslash inside an
# f-string expression (a SyntaxError before Python 3.12, e.g. the 3.11 that environment.sis.yml pins), and
# net_carry_chart.py needs Altair >= 5.
try:
    import carry_rate as CR
    import net_carry as NC
    import net_carry_chart as NCC
    import net_carry_compare as NCMP
    import net_carry_data as ND
    _NC_IMPORT_ERROR = None
except Exception as _nc_err:
    CR = NC = NCC = NCMP = ND = None
    _NC_IMPORT_ERROR = _nc_err

# The Return to Carry history under the Net Carry tab (return_to_carry*.py, vendored from the tracker as well). Guarded on its
# own: if it cannot load, the carry ladder above it still draws.
try:
    import return_to_carry_block as RTCB
    import return_to_carry_data as RTCD
    _RTC_IMPORT_ERROR = None
except Exception as _rtc_err:
    RTCB = RTCD = None
    _RTC_IMPORT_ERROR = _rtc_err

# Local .env, optional (Streamlit Cloud uses st.secrets instead).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    pass

try:
    # Snowflake (JSA.BASIS_TRACKER for rail bids, RIVER_FOB.PUBLIC for CIF) is the
    # live source when USE_SNOWFLAKE is set; the *_DATABASE_URL Postgres secrets
    # remain only as a rollback. rail_data/river_data pin their own database+schema
    # at connect time, so SNOWFLAKE_DATABASE/SCHEMA need not be set here.
    for _secret_key in ("BASIS_DATABASE_URL", "RIVER_DATABASE_URL", "USDA_APP_TOKEN", "EIA_API_KEY",
                        "RAIL_VIEW_ONLY",
                        "USE_SNOWFLAKE", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER",
                        "SNOWFLAKE_PASSWORD", "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE",
                        "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA"):
        if _secret_key in st.secrets and not os.environ.get(_secret_key):
            os.environ[_secret_key] = str(st.secrets[_secret_key])
except Exception:
    pass  # st.secrets unavailable locally — fine, .env covers it

pass  # portal-sync: st.set_page_config removed (Home.py makes the one call allowed per run)

# Hide the Streamlit Community Cloud viewer badge (the profile avatar that links
# to the creator's other apps) for a clean, client-facing footer.
# The Streamlit Cloud badge (creator avatar + logo) is drawn by Cloud's outer page,
# outside this iframe, so CSS here can't reach it; add the rule to the parent
# document instead (same-origin). No-op when run locally.
_BADGE_JS = """<script>(function(){try{var w=window;while(w.parent&&w.parent!==w){try{void w.parent.document;w=w.parent;}catch(e){break;}}var d=w.document;if(d.getElementById('jsa-hide-cloud-badge'))return;var s=d.createElement('style');s.id='jsa-hide-cloud-badge';s.textContent="[class*='_profileContainer_'],[class*='_viewerBadge_']{display:none !important;}";d.head.appendChild(s);}catch(e){}})();</script>"""
try:
    st.html(_BADGE_JS, unsafe_allow_javascript=True)
except TypeError:  # older Streamlit without st.html JS support
    import streamlit.components.v1 as _stc
    _stc.html(_BADGE_JS, height=0)


def _view_only():
    """A view-only build (Kolten, 2026-10-28): no BN freight inputs, no editing anywhere. Switched on by the
    RAIL_VIEW_ONLY secret (a separate Cloud app that nobody can edit from) or, for a quick shareable link, ?view=1."""
    if os.environ.get("RAIL_VIEW_ONLY", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return str(st.query_params.get("view", "")).strip().lower() in ("1", "true", "yes")


@st.cache_data
def _asset_uri(filename):
    p = os.path.join(os.path.dirname(__file__), "assets", filename)
    mime = "image/svg+xml" if filename.endswith(".svg") else "image/png"
    try:
        with open(p, "rb") as f:
            return f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    except OSError:
        return ""


WATERMARK = _asset_uri("jsa_50yr.png")
LOGO_URI = _asset_uri("logo-full.png")
CSX_LOGO_URI = _asset_uri("csx_logo.svg")
NS_LOGO_URI = _asset_uri("ns_logo.svg")
BNSF_LOGO_URI = _asset_uri("bnsf_logo.svg")
CN_LOGO_URI = _asset_uri("cn_logo.svg")
UP_LOGO_URI = _asset_uri("up_logo.svg")       # "" until assets/up_logo.svg exists (then the UP tab, #7, shows it)
UP_LOGO_RULE = (f'[role="tab"]:nth-of-type(8) p::before {{ content: ""; display: inline-block; width: 26px; height: 16px; '
                f"background: url('{UP_LOGO_URI}') no-repeat center / contain; }}" if UP_LOGO_URI else "")

JPSI_DARK = "#32373c"
JPSI_BLUE = "#0693e3"

# Table-only styling, factored out so the copy/PNG capture (which runs in an
# isolated components.html iframe with no access to the page's own
# stylesheet) can inject the exact same rules rather than drifting from a
# second hand-maintained copy.
_TABLE_CSS = f"""
  table.sheet {{ width: 100%; border-collapse: collapse; font-size: 0.85rem;
    font-family: 'Source Sans Pro', system-ui, -apple-system, sans-serif; }}
  table.sheet th, table.sheet td {{ font-variant-numeric: tabular-nums; }}
  table.sheet th {{
    font-size: 0.68rem; font-weight: 700; color: #6b7280; text-transform: uppercase;
    letter-spacing: .03em; padding: 7px 10px; border-bottom: 2px solid #e2e8f0;
    text-align: right; white-space: nowrap;
  }}
  table.sheet th.lblhdr {{ text-align: left; }}
  table.sheet td {{
    padding: 6px 10px; text-align: right; border-bottom: 1px solid #f5f5f5;
    color: #333; white-space: nowrap;
  }}
  table.sheet tr.section td {{
    background: #f0f0f0; color: {JPSI_DARK}; font-weight: 700;
    padding: 7px 16px; border-top: 1px solid #ddd; border-bottom: none;
    font-size: 0.75rem; text-transform: uppercase; letter-spacing: .04em;
    text-align: left;
  }}
  table.sheet tr.origin-hdr td {{
    padding: 10px 10px 4px 10px; border-bottom: none; font-weight: 700;
    color: {JPSI_DARK}; text-align: left;
  }}
  table.sheet td.lbl {{ text-align: left; font-weight: 600; color: #2c3e50; }}
  table.sheet td.sub-lbl {{
    text-align: left; color: #6b7280; padding-left: 26px; font-style: italic;
  }}
  table.sheet td.up {{ background: #e8f5e9; color: #1f2328; font-weight: 700; }}
  table.sheet td.down {{ background: #ffebee; color: #1f2328; font-weight: 700; }}
  table.sheet td.better {{ background: #eaf4fc; color: {JPSI_DARK}; font-weight: 700; }}
  table.sheet th.title {{ font-size: 1.15rem; color: {JPSI_DARK}; text-align: left; text-transform: none;
    letter-spacing: 0; vertical-align: middle; padding-right: 18px; }}
  table.sheet th.grp {{ text-align: center; font-size: .82rem; color: {JPSI_DARK}; text-decoration: underline;
    text-transform: none; letter-spacing: 0; border-bottom: 1px solid #e2e8f0; }}
  table.sheet th.sub {{ text-align: center; color: {JPSI_DARK}; text-transform: none; letter-spacing: 0; font-size: .74rem; }}
  table.sheet .gl {{ border-left: 2px solid #e2e8f0; }}
  table.sheet td.bidrow {{ background: #fff9c4; text-align: center; font-weight: 600; color: {JPSI_DARK}; }}
  table.sheet tr.carsrow td {{ text-align: center; font-weight: 600; color: {JPSI_DARK};
    border-top: 1px solid #94a3b8; border-bottom: 1px solid #94a3b8; }}
  table.sheet tr.carsrow td.lbl {{ text-align: left; }}
  table.sheet td.fobv {{ text-align: center; }}
  table.sheet td.fobv.neg {{ color: #c00000; }}
  table.sheet td.fobv.divide {{ background: #fbe5d6; }}
  table.sheet td.ovr {{ border-bottom: 1px dotted #64748b; }}
  table.sheet td.pending {{ color: #94a3b8; }}
  table.sheet .off {{ color: {JPSI_BLUE}; font-weight: 600; }}
  .fut-sub {{ font-size: 0.68rem; color: #9aa5b1; font-weight: 400; }}
  .rail-chip {{
    font-size: 9px; color: #fff; padding: 2px 7px; border-radius: 8px;
    margin-left: 6px; font-weight: 700;
  }}
  .asof-chip {{
    font-size: 9px; color: #fff; background: #d97706; padding: 2px 7px;
    border-radius: 8px; margin-left: 6px;
  }}
  /* 💵 Net Carry ladder. Colour semantics follow the basis tracker's tab: green = inverse (+),
     red = carry (−), amber = the top of net carry. In here (not the page style) so the
     copy / PNG export of the table looks the same as the page. */
  table.sheet.nc th {{ white-space: normal; line-height: 1.25; vertical-align: bottom; }}
  table.sheet td.fut {{ text-align: left; color: #6b7280; }}
  table.sheet td.dim {{ color: #94a3b8; }}
  table.sheet td.inv {{ color: #0a7f3f; font-weight: 700; }}
  table.sheet td.car {{ color: #c0392b; font-weight: 700; }}
  table.sheet td.flat {{ color: #64748b; }}
  table.sheet tr.nc-top td {{ background: #fff4e5; }}
  /* the amber accent bar on the row's first cell is a gradient, not an inset box-shadow: html2canvas (the PNG
     export) paints an inset shadow as a solid fill over the whole cell */
  table.sheet tr.nc-top td:first-child {{
    background: linear-gradient(to right, #f28e2b 0, #f28e2b 4px, #fff4e5 4px);
  }}
  table.sheet tr.nc-top td.net {{ font-weight: 800; }}
  .nc-tag {{
    background: #f28e2b; color: #fff; font-size: 9px; font-weight: 700; letter-spacing: .05em;
    padding: 2px 7px; border-radius: 9px; margin-left: 8px; white-space: nowrap; vertical-align: 1px;
  }}
  .nc-flag {{ color: #c0392b; }}
"""

st.markdown(
    f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600;700&display=swap');
      html, body, [class*="css"], .stApp, button, input, select, textarea, table, td, th,
      .stMarkdown, h1, h2, h3, h4, h5, h6, p, span, div {{
        font-family: 'Source Sans Pro', system-ui, -apple-system, sans-serif !important;
      }}
      {_TABLE_CSS}

      header[data-testid="stHeader"] {{ display: none !important; }}
      #MainMenu {{ visibility: hidden !important; }}
      footer {{ visibility: hidden !important; }}
      .block-container {{ padding-top: 0.75rem !important; padding-bottom: 1rem !important; max-width: 1300px; }}
      .stApp {{ background-color: #ffffff; }}

      .dash-header {{
        background: #ffffff; border-bottom: 3px solid {JPSI_BLUE};
        padding: 18px 8px 14px 8px; margin: -0.75rem 0 22px 0;
        display: flex; align-items: center; gap: 20px;
      }}
      .dash-header-logo {{ flex-shrink: 0; }}
      .dash-header-logo img {{ height: 54px; display: block; }}
      .dash-header-text {{ flex: 1; text-align: center; }}
      .dash-header-text h1 {{
        margin: 0; color: {JPSI_DARK} !important; font-size: 1.7rem;
        font-weight: 700; letter-spacing: -0.01em;
      }}
      .dash-header-text .subtitle {{ color: #6b7280; font-size: 0.85rem; margin: 3px 0 0 0; }}

      h2, h3, h4 {{ color: {JPSI_DARK} !important; font-weight: 700 !important; }}
      h2 {{ border-bottom: 3px solid {JPSI_BLUE}; padding-bottom: 8px;
            margin-top: 24px; margin-bottom: 16px; }}
      h3 {{ margin-top: 20px; margin-bottom: 10px; }}

      .sheet-wrap {{
        border-radius: 10px; overflow: hidden; position: relative;
        box-shadow: 0 2px 8px rgba(50,55,60,0.12); border: 1px solid #ddd;
        background: #fff; margin-bottom: 18px;
      }}
      .sheet-wrap::after {{
        content: ""; position: absolute; inset: 0;
        background: url('{WATERMARK}') center 46% / 32% auto no-repeat;
        opacity: 0.05; pointer-events: none; z-index: 0;
      }}
      .sheet-wrap-inner {{ position: relative; z-index: 1; overflow-x: auto; }}

      .legend {{ font-size: 0.78rem; color: #6b7280; padding: 4px 2px 14px 2px; }}
      .legend .sw {{
        display: inline-block; width: 11px; height: 11px; border-radius: 3px;
        vertical-align: middle; margin: 0 4px 0 10px;
      }}
      .legend .sw.up {{ background: #e8f5e9; border: 1px solid #0d7f3d; }}
      .legend .sw.dn {{ background: #ffebee; border: 1px solid #c00000; }}
      .legend .sw.bt {{ background: #eaf4fc; border: 1px solid {JPSI_BLUE}; }}

      /* 💵 Net Carry tab: the one-line summary and the amber "top of net carry" callout. */
      .nc-summary {{ font-size: 0.78rem; color: #6b7280; margin: 8px 0 4px 0; }}
      .nc-callout {{
        background: #fff7ed; border: 1px solid #fed7aa; border-left: 5px solid #f28e2b;
        border-radius: 8px; padding: 10px 14px; margin: 8px 0 10px 0;
        font-size: 0.92rem; line-height: 1.5; color: #7c2d12;
      }}
      .nc-callout .tri {{ color: #f28e2b; font-size: 15px; margin-right: 6px; }}

      .stButton > button {{
        background: {JPSI_BLUE}; color: #fff; border: none; border-radius: 6px; font-weight: 600;
      }}
      .stButton > button:hover {{ background: #057ec2; color: #fff; }}
      label {{ color: {JPSI_DARK} !important; font-weight: 600 !important; }}

      .stTabs [data-baseweb="tab-list"] {{ gap: 0; background: #ffffff; border-bottom: 1px solid #e2e8f0; }}
      [role="tab"], [role="tab"] *, .stTabs [data-baseweb="tab"], .stTabs [data-baseweb="tab"] * {{
        color: {JPSI_DARK} !important; opacity: 1 !important; font-weight: 700 !important;
        font-size: 14px !important; -webkit-text-fill-color: {JPSI_DARK} !important;
      }}
      [role="tab"] {{ padding: 8px 18px; border-radius: 0; }}
      [role="tab"]:hover, [role="tab"]:hover * {{
        color: {JPSI_BLUE} !important; -webkit-text-fill-color: {JPSI_BLUE} !important;
      }}
      [role="tab"][aria-selected="true"] {{ border-bottom: 3px solid {JPSI_BLUE} !important; }}
      [role="tab"][aria-selected="true"], [role="tab"][aria-selected="true"] * {{
        color: #000000 !important; -webkit-text-fill-color: #000000 !important; font-weight: 800 !important;
      }}
      .stTabs [data-baseweb="tab-panel"] {{ padding-top: 10px !important; }}

      /* Railroad logos on their tabs, in place of a generic emoji. Streamlit's
         st.tabs() only takes plain text, so this positions each carrier's mark
         via nth-of-type — must stay in sync with the literal tab order below
         (Bids, State Summary, State Level, CSX, NS, BN, CN, UP, Map, Shipments, References, Net Carry). Logos sit on
         tabs 4-8, so inserting a tab before position 6 means shifting these four numbers with it. */
      [role="tab"] p {{ display: flex; align-items: center; gap: 6px; }}
      [role="tab"]:nth-of-type(4) p::before {{
        content: ""; display: inline-block; width: 26px; height: 16px;
        background: url('{CSX_LOGO_URI}') no-repeat center / contain;
      }}
      [role="tab"]:nth-of-type(5) p::before {{
        content: ""; display: inline-block; width: 26px; height: 16px;
        background: url('{NS_LOGO_URI}') no-repeat center / contain;
      }}
      [role="tab"]:nth-of-type(6) p::before {{
        content: ""; display: inline-block; width: 26px; height: 16px;
        background: url('{BNSF_LOGO_URI}') no-repeat center / contain;
      }}
      [role="tab"]:nth-of-type(7) p::before {{
        content: ""; display: inline-block; width: 26px; height: 16px;
        background: url('{CN_LOGO_URI}') no-repeat center / contain;
      }}
      {UP_LOGO_RULE}
    </style>
    """,
    unsafe_allow_html=True,
)

_logo_html = (f'<img src="{LOGO_URI}" alt="John Stewart &amp; Associates">' if LOGO_URI else '')
st.markdown(
    f'<div class="dash-header">'
    f'  <div class="dash-header-logo">{_logo_html}</div>'
    f'  <div class="dash-header-text">'
    f'    <h1>Rail Corridors</h1>'
    f'    <div class="subtitle">Commodity &amp; Ag Risk Management Specialists &nbsp;·&nbsp; est. 1976</div>'
    f'  </div>'
    f'  <div style="width:180px"></div>'
    f'</div>',
    unsafe_allow_html=True,
)

if _view_only():
    st.info("👁 **View-only version.** Everything here is read-only: the bids update as JSA posts them, and the freight inputs "
            "(BN shuttle quotes, fuel-surcharge months) are maintained by JSA.")

# JSA's standard compliance disclaimer (the River FOB Portal's wording, verbatim), shown under every tab of the page — it is drawn after the
# tab blocks, so it sits at the bottom whichever tab is open. The year rolls over by itself.
def _render_disclaimer():
    text = (
        "Trading commodity futures, options on futures, cash commodities, and over-the-counter derivative products involves substantial "
        "risk of loss and may not be suitable for all investors. This communication is provided for informational purposes only and does "
        "not constitute investment advice, a recommendation, or an offer or solicitation to buy or sell any futures, options, cash "
        "commodities, or derivative products. John Stewart &amp; Associates, Inc. does not accept orders to buy or sell any financial "
        "instruments via email. The information contained herein has been obtained from sources believed to be reliable; however, its "
        "accuracy and completeness are not guaranteed. Any opinions expressed are solely those of the author, are subject to change "
        "without notice, and should not be relied upon as a basis for investment decisions. Past performance is not indicative of future "
        "results. This message may contain confidential or proprietary information intended solely for the use of the designated "
        f"recipient. &copy; John Stewart &amp; Associates, Inc. {date.today().year}")
    st.markdown(
        '<div style="font-family:inherit;margin-top:1.5rem;padding-top:0.7rem;border-top:1px solid #e0e0e0;font-size:inherit;'
        f'line-height:1.4;color:#8a9199;text-align:justify;">{text}</div>',
        unsafe_allow_html=True)


if not RD.configured():
    st.warning(
        "BASIS_DATABASE_URL isn't set, so this portal can't reach the basis "
        "tracker's archive yet. Add it to `.env` locally or as a Streamlit "
        "secret to see live data."
    )
    _render_disclaimer()
    # Which settings this app can see — names only, never values — so a missing or misnamed secret shows up at a glance.
    _seen = []
    for _k in ("USE_SNOWFLAKE", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE",
               "SNOWFLAKE_PRIVATE_KEY", "SNOWFLAKE_PASSWORD"):
        try:
            _has = bool(os.environ.get(_k)) or (_k in st.secrets)
        except Exception:
            _has = bool(os.environ.get(_k))
        _seen.append(f"{'✅' if _has else '❌'} `{_k}`")
    st.caption("Settings this app can see: " + " · ".join(_seen) + ". `USE_SNOWFLAKE` must be `1` (or `true`) and sit at the top "
               "level of the secrets, not under a [section]; the secrets need a reboot after a change.")
    st.stop()


@st.cache_data(ttl=300)
def _cached_dates(source):
    return RD.get_dates(source)


@st.cache_data(ttl=300)
def _cached_all(source):
    return RD.get_all(source)


def _card_open():
    return '<div class="sheet-wrap"><div class="sheet-wrap-inner">'


def _card_close():
    return '</div></div>'


def _table_actions(table_html, filename):
    """Copy-to-clipboard (rich text) + download-as-PNG buttons for one
    table's raw `<table>...</table>` HTML (not the card wrapper). Runs in
    its own components.html iframe, which can't see the page's real
    stylesheet — so it injects _TABLE_CSS itself rather than depending on
    it, the same reason basis-tracker's copy_button() needs its own inline
    styling. PNG capture via html2canvas (CDN); real browser tab, not a
    sandboxed artifact viewer, so a script-triggered download works fine."""
    payload = json.dumps(table_html).replace("</", "<\\/")
    fname = json.dumps(filename)
    btn_css = (
        "font-family:'Source Sans Pro',system-ui,sans-serif;font-size:12px;font-weight:600;"
        f"background:{JPSI_BLUE};color:#fff;border:none;border-radius:6px;"
        "padding:6px 14px;cursor:pointer;margin-right:8px"
    )
    if RD._in_sis():
        return  # components.html blocked in Streamlit in Snowflake
    components.html(f"""
      <style>{_TABLE_CSS}</style>
      <div>
        <button id="copy_b" style="{btn_css}">📋 Copy</button>
        <button id="png_b" style="{btn_css}">⬇ PNG</button>
        <span id="msg" style="font-family:'Source Sans Pro',system-ui,sans-serif;font-size:12px;
              color:#16a34a;font-weight:600;margin-left:4px"></span>
      </div>
      <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
      <script>
        const H = {payload};
        const FN = {fname};
        function showMsg(t) {{
          const m = document.getElementById('msg');
          m.textContent = t;
          setTimeout(() => {{ m.textContent = ''; }}, 1800);
        }}
        document.getElementById('copy_b').onclick = function() {{
          const d = document.createElement('div');
          d.style.cssText = 'position:fixed;left:-99999px;top:0;';
          d.innerHTML = H;
          document.body.appendChild(d);
          const rg = document.createRange(); rg.selectNodeContents(d);
          const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg);
          let ok = false;
          try {{ ok = document.execCommand('copy'); }} catch (e) {{}}
          s.removeAllRanges(); document.body.removeChild(d);
          showMsg(ok ? 'Copied!' : 'Press Ctrl+C');
        }};
        document.getElementById('png_b').onclick = function() {{
          if (typeof html2canvas === 'undefined') {{ showMsg('PNG unavailable'); return; }}
          const d = document.createElement('div');
          d.style.cssText = 'position:fixed;left:-99999px;top:0;background:#fff;padding:14px;';
          d.innerHTML = H;
          document.body.appendChild(d);
          html2canvas(d, {{backgroundColor: '#ffffff', scale: 2}}).then(function(canvas) {{
            const link = document.createElement('a');
            link.download = FN;
            link.href = canvas.toDataURL('image/png');
            link.click();
            document.body.removeChild(d);
          }}).catch(function() {{
            showMsg('PNG failed');
            document.body.removeChild(d);
          }});
        }};
      </script>
    """, height=44)


def _disp(num, raw):
    """Prefer the raw display token (?, notations) over the parsed number."""
    if raw:
        return raw
    return f"{num:+d}" if num is not None else None


def _period_key(period_order, period):
    return (period_order if period_order is not None else 99, period)


# Periods to hide from every table on this sheet (still archived as posted —
# this is display-only). "Nov (No Holiday)" duplicates the plain "Nov" column.
_DROP_PERIODS = {"nov (no holiday)"}


def _keep_period(p):
    return p.strip().lower() not in _DROP_PERIODS


def _location_only(buying_station):
    """CSX's buying_station is stored "COMPANY | TOWN" — drop the company,
    keep just the location (Kolten's call, 2026-08-24: company names clutter
    the location labels)."""
    if not buying_station:
        return ""
    return buying_station.split("|", 1)[-1].strip() if "|" in buying_station else buying_station


def _prior_row(mkt_dates_sorted, by_md, market, eff_date):
    """The market's previous posting strictly before eff_date, or None."""
    earlier = [d for d in mkt_dates_sorted.get(market, ()) if d < eff_date]
    return by_md.get((market, earlier[-1])) if earlier else None


def _cell_html(cell, prior_map):
    """One <td> for a corridor × period cell, tinted like a spreadsheet
    change cell (green/red background) rather than colored bold text."""
    if cell is None:
        return '<td>—</td>'
    bid_disp = _disp(cell.get("bid"), cell.get("bid_raw"))
    if bid_disp is None:
        return '<td>—</td>'
    if bid_disp == "?":
        return '<td class="pending">?</td>'
    prior_cell = (prior_map or {}).get(cell["period"])
    pb = prior_cell.get("bid") if prior_cell else None
    b = cell.get("bid")
    cls = ""
    if pb is not None and b is not None and b != pb:
        cls = "up" if b > pb else "down"
    txt = bid_disp
    off_disp = _disp(cell.get("offer"), cell.get("offer_raw"))
    if off_disp:
        txt += f' <span class="off">/ {off_disp}</span>'
    cls_attr = f' class="{cls}"' if cls else ''
    return f'<td{cls_attr}>{txt}</td>'


def _sheet_board(source, sections, key, other_keep=None):
    """other_keep: if given, only these market names may appear in the
    catch-all "Other" section (leftover markets not in any named section);
    pass None to keep every leftover (the old default)."""
    dates = _cached_dates(source)
    if not dates:
        st.caption("No postings archived yet for this board.")
        return None

    sel_col, _ = st.columns([3, 7])
    with sel_col:
        sel_date = st.selectbox("Posting date", dates, key=f"rail_sheet_date_{key}")

    rows = _cached_all(source)
    by_md, mkt_dates = {}, {}
    for r in rows:
        by_md.setdefault((r["market"], r["date"]), {})[r["period"]] = r
        mkt_dates.setdefault(r["market"], set()).add(r["date"])
    mkt_dates_sorted = {m: sorted(ds) for m, ds in mkt_dates.items()}

    placed = {m for _, ms in sections for m in ms}
    elig_markets = {m for m, ds in mkt_dates.items() if any(d <= sel_date for d in ds)}
    leftover = sorted(elig_markets - placed)
    if other_keep is not None:
        leftover = [m for m in leftover if m in other_keep]
    all_sections = list(sections) + ([("Other", leftover)] if leftover else [])

    for title, markets in all_sections:
        section_rows = []
        for m in markets:
            elig = [d for d in mkt_dates_sorted.get(m, ()) if d <= sel_date]
            if not elig:
                continue
            eff = max(elig)
            cells = by_md.get((m, eff), {})
            if not cells:
                continue
            prior = _prior_row(mkt_dates_sorted, by_md, m, eff)
            section_rows.append((m, eff, cells, prior))
        if not section_rows:
            continue

        col_keys = {}
        for _, _, cells, _ in section_rows:
            for p, c in cells.items():
                if _keep_period(p):
                    col_keys.setdefault(p, _period_key(c.get("period_order"), p))
        periods = sorted(col_keys, key=lambda p: col_keys[p])

        col_fut = {}
        for p in periods:
            futs = [cells[p].get("futures") for _, _, cells, _ in section_rows
                    if p in cells and cells[p].get("futures")]
            col_fut[p] = Counter(futs).most_common(1)[0][0] if futs else ""

        ncols = 1 + len(periods)
        html = ['<table class="sheet"><tbody>',
                f'<tr class="section"><td colspan="{ncols}">{title}</td></tr>',
                '<tr>', '<th class="lblhdr">Corridor</th>']
        for p in periods:
            fut = col_fut[p]
            sub = f'<br><span class="fut-sub">{fut}</span>' if fut else ''
            html.append(f'<th>{p}{sub}</th>')
        html.append('</tr>')

        for m, eff, cells, prior in section_rows:
            rail = cells[next(iter(cells))].get("rail") or ""
            rcol = RAIL_COLORS.get(rail, "#64748b")
            asof = ''
            if eff != sel_date:
                yy, mo, dd = eff.split("-")
                asof = f'<span class="asof-chip">as of {int(mo)}/{int(dd)}</span>'
            label = RAIL_DISPLAY.get(m, m)
            html.append(
                f'<tr><td class="lbl">{label}'
                f'<span class="rail-chip" style="background:{rcol}">{rail}</span>'
                f'{asof}</td>'
            )
            for p in periods:
                html.append(_cell_html(cells.get(p), prior))
            html.append('</tr>')
        html.append('</tbody></table>')
        table_html = ''.join(html)
        st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
        fname = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "corridors"
        _table_actions(table_html, f"bids_{key}_{fname}.png")

    st.markdown(
        f'<div class="legend">As of {sel_date} · a corridor not posted that day carries '
        'forward its most recent posting (amber "as of M/D") · '
        '<span class="sw up"></span>up <span class="sw dn"></span>down vs that corridor\'s '
        'previous posting · offer shown in blue after "/" · values are archived exactly as '
        'posted, no roll or spread math applied · ? = pending side.</div>',
        unsafe_allow_html=True,
    )
    return sel_date


def _rnd(v):
    """A whole number, halves away from zero (Python's round() takes halves to even): FOB values show without decimals (Kolten, 2026-11-02)."""
    n = int(abs(v) + 0.5)
    return -n if v < 0 else n


def _fob_cell(v, better=False):
    if v is None:
        return '<td>—</td>'
    cls = ' class="better"' if better else ''
    return f'<td{cls}>{_rnd(v):+d}</td>'


def _bid_cells_for(source, market, sel_date):
    """Effective (carry-forward) {period: row} for one market at/≤ sel_date,
    plus the actual posting date used (for an 'as of' note)."""
    if sel_date is None:
        return {}, None
    rows = _cached_all(source)
    dates = sorted({r["date"] for r in rows if r["market"] == market and r["date"] <= sel_date})
    if not dates:
        return {}, None
    eff = dates[-1]
    return {r["period"]: r for r in rows if r["market"] == market and r["date"] == eff}, eff


def _period_union(*cell_dicts):
    keys = {}
    for cells in cell_dicts:
        for p, c in cells.items():
            if _keep_period(p):
                keys.setdefault(p, _period_key(c.get("period_order"), p))
    return sorted(keys, key=lambda p: keys[p])


def _fob_cell_int(v, better=False):
    if v is None:
        return '<td>—</td>'
    cls = ' class="better"' if better else ''
    return f'<td{cls}>{_rnd(v):+d}</td>'


def _variant_value_rows(label_rows, cell_fn=_fob_cell, row_label_fn=lambda lbl: f'via {lbl}'):
    """label_rows: [(label, [value_or_None per period]), ...] — one <tr> per
    label. The best (max) value per period across ALL given rows is tinted
    (via `cell_fn`'s `better` flag), so this one function drives both CSX's
    2-way and NS's up-to-3-way comparisons, and the state-level rollups."""
    rows_html = []
    for i, (label, row) in enumerate(label_rows):
        better = []
        for pi in range(len(row)):
            v = row[pi]
            others = [label_rows[j][1][pi] for j in range(len(label_rows)) if j != i and label_rows[j][1][pi] is not None]
            better.append(v is not None and bool(others) and all(v > o for o in others))
        cells_html = ''.join(cell_fn(v, b) for v, b in zip(row, better))
        rows_html.append(f'<tr><td class="sub-lbl">{row_label_fn(label)}</td>{cells_html}</tr>')
    return rows_html


def _fob_variant_rows(variants, periods):
    """variants: [(label, bid_cells_dict, freight_cpb), ...] — one row per
    variant, ¢/bu = bid − freight. freight_cpb may be a callable(period) -> ¢/bu (None = no freight) for freight that
    moves by period (the NS fuel surcharge)."""
    vals = []
    for label, cells, frt in variants:
        row = []
        for p in periods:
            bid = cells.get(p, {}).get("bid")
            f = frt(p) if callable(frt) else frt
            row.append(None if bid is None or f is None else bid - f)
        vals.append((label, row))
    return _variant_value_rows(vals)


def _origin_table_open(periods, ncols):
    html = ['<table class="sheet"><tbody><tr>', '<th class="lblhdr">Origin</th>']
    html += [f'<th>{p}</th>' for p in periods]
    html.append('</tr>')
    return html


def _bid_cells_prior_for(source, market, sel_date):
    """Like _bid_cells_for, but also returns the market's prior posting (for
    up/down coloring) — used by the per-tab raw corridor table."""
    if sel_date is None:
        return {}, None, None
    rows = _cached_all(source)
    dates_all = sorted({r["date"] for r in rows if r["market"] == market})
    dates_le = [d for d in dates_all if d <= sel_date]
    if not dates_le:
        return {}, None, None
    eff = dates_le[-1]
    cells = {r["period"]: r for r in rows if r["market"] == market and r["date"] == eff}
    earlier = [d for d in dates_all if d < eff]
    prior = ({r["period"]: r for r in rows if r["market"] == market and r["date"] == earlier[-1]}
             if earlier else None)
    return cells, eff, prior


def _raw_corridor_table(markets, sel_date):
    """The raw bid/offer grid for just the given market(s) — same styling as
    the Bids tab, but scoped to only this railroad's own corridor(s) so each
    tab is self-contained."""
    entries = []
    for m in markets:
        cells, eff, prior = _bid_cells_prior_for("manual", m, sel_date)
        if cells:
            entries.append((m, eff, cells, prior))
    if not entries:
        st.caption("No postings on or before this date yet.")
        return
    periods = _period_union(*[e[2] for e in entries])
    html = ['<table class="sheet"><tbody><tr>', '<th class="lblhdr">Corridor</th>']
    html += [f'<th>{p}</th>' for p in periods]
    html.append('</tr>')
    for m, eff, cells, prior in entries:
        rail = cells[next(iter(cells))].get("rail") or ""
        rcol = RAIL_COLORS.get(rail, "#64748b")
        asof = ''
        if eff != sel_date:
            yy, mo, dd = eff.split("-")
            asof = f'<span class="asof-chip">as of {int(mo)}/{int(dd)}</span>'
        label = RAIL_DISPLAY.get(m, m)
        html.append(f'<tr><td class="lbl">{label}'
                    f'<span class="rail-chip" style="background:{rcol}">{rail}</span>{asof}</td>')
        for p in periods:
            html.append(_cell_html(cells.get(p), prior))
        html.append('</tr>')
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    fname = re.sub(r"[^a-z0-9]+", "_", "_".join(markets).lower()).strip("_")
    _table_actions(table_html, f"rail_fob_{fname}.png")


def _state_best_row(origins, cells, field, periods):
    """Best (highest) FOB among the given origins, for one corridor/region, per period. `field` is the row key of the
    freight in ¢/bu, or a callable (row, period) -> ¢/bu for freight that moves by period (None = no freight for that row)."""
    out = []
    for p in periods:
        bid = cells.get(p, {}).get("bid")
        if bid is None:
            out.append(None)
            continue
        best = None
        for o in origins:
            frt = field(o, p) if callable(field) else o[field]
            if frt is None:
                continue
            v = bid - frt
            if best is None or v > best:
                best = v
        out.append(best)
    return out


def _state_fob_table(rows, variant_fields, bid_cells_map, periods, state_key="state",
                      per_variant=False, name="state_index"):
    """One row per state, one column per period. Each cell is the BEST
    (highest) FOB among every origin in that state for that corridor/region
    — an index, not any single origin's actual number.

    per_variant=False (NS's style): one combined row per state, best across
    every active region — mirrors NS's Highlighted Origins, which already
    collapses to a single best-region row per origin.
    per_variant=True (CSX's style): one row per state PER active corridor
    (e.g. "via Columbus" / "via Evansville"), the better one tinted — mirrors
    CSX's Highlighted Origins, which compares corridors side by side."""
    if not variant_fields or not periods:
        st.caption("Select at least one corridor/region above to see this table.")
        return
    by_state = {}
    for r in rows:
        by_state.setdefault(r[state_key], []).append(r)
    if not by_state:
        st.caption("No data to index by state yet.")
        return

    ncols = 1 + len(periods)
    html = ['<table class="sheet"><tbody><tr>', '<th class="lblhdr">State</th>']
    html += [f'<th>{p}</th>' for p in periods]
    html.append('</tr>')
    for s in sorted(by_state):
        origins = by_state[s]
        if per_variant:
            label_rows = [(label, _state_best_row(origins, bid_cells_map[label], field, periods))
                          for label, field in variant_fields]
            html.append(f'<tr class="origin-hdr"><td colspan="{ncols}">{s}</td></tr>')
            html.extend(_variant_value_rows(label_rows, cell_fn=_fob_cell_int))
        else:
            vals = [None] * len(periods)
            for label, field in variant_fields:
                row = _state_best_row(origins, bid_cells_map[label], field, periods)
                for i, v in enumerate(row):
                    if v is not None and (vals[i] is None or v > vals[i]):
                        vals[i] = v
            cells = ''.join(f'<td>{_rnd(v):+d}</td>' if v is not None else '<td>—</td>' for v in vals)
            html.append(f'<tr><td class="lbl">{s}</td>{cells}</tr>')
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, f"{name}.png")
    if per_variant:
        st.caption("Best (highest) FOB among every origin in that state, per corridor, per "
                   "period — blue = the better corridor for that state/period, same "
                   "comparison style as Highlighted Origins below.")
    else:
        st.caption("Best (highest) FOB among every origin in that state, per period — "
                   "an index, not any single origin's actual number.")


def _fsc_by_period(rr, periods, today_for_blank=True):
    """({period: fuel surcharge $/car-mile}, [caption bits]) for a railroad's program over the bid periods (rail_fsc.window:
    published > formula on EIA diesel > last published held flat). A period that names no month (Spot, In Transit) takes
    the current month's."""
    kinds = {"published": "published", "formula": "formula on EIA diesel", "held": "last published, held flat"}
    win = RF.window(rr, _diesel_weekly, date.today())
    by_p, parts = {}, []
    for p in periods:
        mo = FD.bn_period_first_month(p) or (date.today().month if today_for_blank else None)
        w = win.get(FD._BN_MONTH3_REV[mo]) if mo else None
        by_p[p] = w["fsc"] if w else None
        parts.append(f"{p} {w['fsc']:.2f} ({kinds[w['kind']]})" if w else f"{p} —")
    return by_p, parts


def _loc_label(name):
    """'AMBOY (USRP)' / 'DES MOINES via IAIS' -> 'Amboy (USRP)' / 'Des Moines via IAIS'."""
    t = str(name).title()
    t = re.sub(r"\(([^)]*)\)", lambda m: "(" + m.group(1).upper() + ")", t)
    return re.sub(r" Via (\w+)", lambda m: " via " + m.group(1).upper(), t)


def _csx_loc(r):
    """The location of a CSX row: the buying station's town, or — where the workbook lists none — the origin group."""
    loc = _location_only(r["buying_station"])
    return r["origin_group"] if not loc or loc == "Rule 11 Origin" else loc


def _csx_differs(r):
    """Evansville's rate depends on the unit train's downstream market: True where the GA/FL and AL/TN/KY/LA rates differ."""
    return r["eville_altkyla"] != r["eville_gafl"]


def _csx_fob_by_corridor(rows, active, periods, fsc_by_p, name, title="FOB CSX"):
    """FOB (¢/bu), Columbus | Evansville side by side under each bid period — the layout of the BN tab's FOB by Origin (Kolten,
    2026-10-28): the bid in a yellow row, the fuel surcharge noted beneath it (not included), negatives in parentheses red, and the
    better corridor for each row / period shaded. rows: [(label, calc)], calc(freight field, bid) -> ¢/bu;
    active: [(corridor label, bid cells {period: row}, freight field)]."""
    n = len(active)

    def gl(i):
        return " gl" if i == 0 else ""

    def num(v):
        return f"{v:+.0f}" if float(v).is_integer() else f"{v:+.1f}"

    def bid_html(cells, p):
        c = cells.get(p) or {}
        if c.get("bid") is None:
            return "—"
        return num(c["bid"]) + (f' <span class="off">/ {num(c["offer"])}</span>' if c.get("offer") is not None else "")

    def fsc_html(p):
        return "—" if fsc_by_p.get(p) is None else format(fsc_by_p[p], ".2f")

    html = ['<table class="sheet"><tbody>',
            f'<tr><th class="title" rowspan="3">{title}</th>'
            + ''.join(f'<th class="grp gl" colspan="{n}">{p}</th>' for p in periods) + '</tr>',
            '<tr>' + ''.join(f'<th class="sub{gl(i)}">{lbl}</th>' for _ in periods for i, (lbl, _c, _f) in enumerate(active)) + '</tr>',
            '<tr>' + ''.join(f'<td class="bidrow{gl(i)}">{bid_html(cells, p)}</td>'
                             for p in periods for i, (_l, cells, _f) in enumerate(active)) + '</tr>']
    if fsc_by_p is not None:
        html.append('<tr class="carsrow"><td class="lbl">Fuel surcharge &#36;/mi (not included)</td>'
                    + ''.join(f'<td class="gl" colspan="{n}">{fsc_html(p)}</td>' for p in periods) + '</tr>')
    for label, calc in rows:
        grid = []
        for p in periods:
            vals = []
            for _l, cells, field in active:
                bid = (cells.get(p) or {}).get("bid")
                vals.append(None if bid is None else calc(field, bid))
            best = max(range(n), key=lambda i: vals[i]) if n == 2 and all(v is not None for v in vals) else None
            for i, v in enumerate(vals):
                txt, neg = _bn_fob_cell(v)
                grid.append(f'<td class="fobv{neg}{" divide" if i == best else ""}{gl(i)}">{txt}</td>')
        html.append(f'<tr><td class="lbl">{label}</td>' + ''.join(grid) + '</tr>')
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, f"{name}.png")


def _csx_flag_note(flagged):
    if flagged:
        st.caption("* Evansville's rate depends on the unit train's downstream market — "
                   + "; ".join(f"{loc} (GA/FL {_rnd(g):+d}¢ vs AL/TN/KY/LA {_rnd(a):+d}¢ used)" for loc, g, a in flagged) + ".")


def _csx_origin_rows(origins, label_fn):
    """([(label, calc)], flagged) for CSX origin rows: bid - the row's freight on whichever corridor field is asked."""
    out, flagged = [], []
    for r in origins:
        out.append((label_fn(r) + (" *" if _csx_differs(r) else ""), lambda f, bid, r=r: bid - r[f + "_cpb"]))
        if _csx_differs(r):
            flagged.append((_csx_loc(r), r["eville_gafl_cpb"], r["eville_altkyla_cpb"]))
    return out, flagged


def _csx_location_lookup(rows, active, periods, fsc_by_p):
    """One CSX origin picked from a list — every origin in the freight workbook, not only the starred ones — in the same
    table as the key corridors (Kolten, 2026-10-28)."""
    st.markdown("### FOB at Any CSX Location")
    labels = {}
    for r in rows:
        labels.setdefault(f"{r['state']} · {_csx_loc(r)} · {r['train_type']}", []).append(r)
    pick = st.selectbox("CSX origin", sorted(labels), index=None, key="csx_loc_pick", label_visibility="collapsed",
                        placeholder=f"Pick or type an origin — {len(labels)} in the CSX freight workbook ...")
    if not pick:
        st.caption("Pick an origin to see its FOB on each corridor, same as the tables above.")
        return
    if not periods:
        st.caption("No CSX Columbus/Evansville postings on or before this date yet.")
        return
    origin_rows, flagged = _csx_origin_rows(labels[pick], lambda r: pick)
    _csx_fob_by_corridor(origin_rows, active, periods, fsc_by_p, "csx_fob_origin")
    _csx_flag_note(flagged)


def _csx_tab(sel_date):
    st.caption(f"Posting date **{sel_date}** — change it on the 📋 Bids tab.")
    fc, fe = st.columns(2)
    show_col = fc.checkbox("Columbus", value=True, key="csx_f_col")
    show_evv = fe.checkbox("Evansville", value=True, key="csx_f_evv")
    if not show_col and not show_evv:
        st.info("Select at least one corridor to filter on.")
        return
    rows = FD.load_csx()

    col_cells, col_eff = _bid_cells_for("manual", "CSX Columbus", sel_date) if show_col else ({}, None)
    evv_cells, evv_eff = _bid_cells_for("manual", "CSX Evansville", sel_date) if show_evv else ({}, None)
    periods = _period_union(col_cells, evv_cells)
    asof_bits = []
    if col_eff and col_eff != sel_date:
        asof_bits.append(f"Columbus as of {col_eff}")
    if evv_eff and evv_eff != sel_date:
        asof_bits.append(f"Evansville as of {evv_eff}")

    active_markets = ([("CSX Columbus", col_cells)] if show_col else []) + \
                      ([("CSX Evansville", evv_cells)] if show_evv else [])
    active = ([("Columbus", col_cells, "columbus")] if show_col else []) + \
              ([("Evansville", evv_cells, "eville_altkyla")] if show_evv else [])
    st.markdown("### Rail FOB — CSX")
    _raw_corridor_table([m for m, _ in active_markets], sel_date)
    fsc_by_p, fsc_parts = _fsc_by_period("CSX", periods) if periods else ({}, [])
    if periods:
        st.caption("CSX fuel surcharge, $/car-mile (publication 8662; the formula is inferred): " + " · ".join(fsc_parts)
                   + ". **Noted only — not included** in the freight or the FOB below (Kolten, 2026-10-28).")

    st.markdown("### FOB by State — Columbus vs Evansville")
    if asof_bits:
        st.caption(" · ".join(asof_bits))
    if periods:
        by_state = {}
        for r in rows:
            by_state.setdefault(r["state"], []).append(r)
        state_rows = [(s_, lambda f, bid, os_=os_: max(bid - o[f + "_cpb"] for o in os_)) for s_, os_ in sorted(by_state.items())]
        _csx_fob_by_corridor(state_rows, active, periods, fsc_by_p, "csx_state_index")
        st.caption("Best (highest) FOB among every origin in the state, per corridor and bid period — an index, not any single "
                   "origin's number. Shaded = the better corridor for that state / period.")
    else:
        st.caption("No CSX Columbus/Evansville postings on or before this date yet.")

    st.markdown("### Key Corridors — Highlighted Origins")
    highlighted = [r for r in rows if r["highlighted"]]
    if periods and highlighted:
        origin_rows, flagged = _csx_origin_rows(highlighted, lambda r: f"{r['state']} · {_csx_loc(r)}")
        _csx_fob_by_corridor(origin_rows, active, periods, fsc_by_p, "csx_highlighted_origins")
        _csx_flag_note(flagged)
    else:
        st.caption("No CSX Columbus/Evansville postings on or before this date yet.")

    _csx_location_lookup(rows, active, periods, fsc_by_p)

    with st.expander(f"All CSX origins, ranked by freight spread ({len(rows)} total)"):
        _expanded_freight_table(
            rows, state_key="state", label_cols=[
                ("Origin", lambda r: r["origin_group"]),
                ("Location", lambda r: _location_only(r["buying_station"])),
                ("Type", lambda r: r["train_type"]),
            ],
            variants=[("Columbus", "columbus_cpb", show_col), ("Evansville", "eville_altkyla_cpb", show_evv)],
            name="csx_all_origins",
        )

    st.markdown(
        '<div class="legend">¢/bu, FOB(origin) = bid − rail freight to that buying station '
        '(¢/bu = &#36;/car ÷ 3800 bu/car × 100); negatives in parentheses. Freight is a static reference rate from the '
        'CSX origin-spread workbook — only the bid side is live/archived. The yellow row is the bid / offer on each corridor; '
        "CSX's fuel surcharge is shown beneath it but not added. Highlighted = "
        'the origins starred in that workbook. Shaded = the better corridor for that row and period.</div>',
        unsafe_allow_html=True,
    )


_UP_NOTES = ("UP origins trade as a discount to a base — Group 3 (North Bend, NE) or Interior IA (Joice, IA) — so FOB(origin) = the base "
             "bid less that origin's discount, the way the CSX / NS freight spreads work. Interior IA typically trades 8¢ under Group 3; an origin "
             "with only one stated discount takes the other through that 8¢ († = derived). Other Iowa origins are par to Interior IA and other "
             "Nebraska ones par to Group 3 (a small discount isn't stated, so it isn't modelled); MN and SD origins have no rule beyond the named ones.")


def _up_origin_rows(spreads, label_fn):
    """[(label, calc)] for UP origins in the BN-layout table: calc(base, bid) = the base bid less the origin's discount."""
    out = []
    for o in spreads:
        out.append((label_fn(o) + (" †" if o["g3_derived"] or o["iia_derived"] else ""), lambda b, bid, o=o: US.fob(o, b, bid)))
    return out


def _up_state_rows():
    """The UP state index rows: each state's best origin per base, the named origins plus the unnamed ones par to their state's base."""
    named = US.origin_spreads()
    rows = []
    for state in ("NE", "IA", "MN"):
        grp = [o for o in named if o["state"] == state]
        g = US.generic_spreads(state)
        if g:
            grp.append(g)
        rows.append((state, lambda b, bid, grp=grp: max([v for v in (US.fob(o, b, bid) for o in grp) if v is not None], default=None)))
    return rows


def _up_location_lookup(active, periods):
    """One UP origin — the named ones, or any of the 147 on UP's shuttle program list, which take their state's par rule where there
    is one (IA, NE) — in the same table as the key corridors (Kolten, 2026-11-02)."""
    st.markdown("### FOB at Any UP Location")
    named = {f"{o['state']} · {o['name'].split(',')[0]}": o for o in US.origin_spreads()}
    options = dict(named)
    for r in json.load(open(os.path.join(os.path.dirname(__file__), "data", "rail_directory", "up_shuttle.json"),
                            encoding="utf-8"))["origins"]:
        label = f"{r['state']} · {r['city'].title()}"
        if label not in options:
            options[label] = None
    pick = st.selectbox("UP origin", sorted(options), index=None, key="up_loc_pick", label_visibility="collapsed",
                        placeholder=f"Pick or type an origin — {len(options)} on UP's shuttle list and the named spreads ...")
    if not pick:
        st.caption("Pick an origin to see its FOB on Group 3 and on Interior IA.")
        return
    spread = options[pick] or US.generic_spreads(pick.split(" · ")[0])
    if spread is None:
        st.caption(f"No stated spread rule for {pick.split(' · ')[0]} origins — only the named MN / IA origins and the IA / NE "
                   "par rule are modelled.")
        return
    if not periods:
        st.caption("No UP Group 3 / Interior IA postings on or before this date yet.")
        return
    rows = _up_origin_rows([dict(spread, name=pick)], lambda o: o["name"])
    _csx_fob_by_corridor(rows, active, periods, None, "up_fob_origin", title="FOB UP")
    st.caption(f"{pick}: {spread['note']}; discount to Group 3 {spread['g3']}¢{' †' if spread['g3_derived'] else ''}, to Interior IA "
               f"{spread['iia']}¢{' †' if spread['iia_derived'] else ''}.")


def _up_tab(sel_date):
    st.caption(f"Posting date **{sel_date}** — change it on the 📋 Bids tab.")
    g3, g3_eff = _bid_cells_for("manual", US.BASES["Group 3"], sel_date)
    iia, iia_eff = _bid_cells_for("manual", US.BASES["Interior IA"], sel_date)
    mex = _bid_cells_for("manual", US.ALLEN_MARKETS["Mexico"], sel_date)[0]
    dom = _bid_cells_for("manual", US.ALLEN_MARKETS["Domestic"], sel_date)[0]
    periods = _period_union(g3, iia)
    active = [("Group 3", g3, "Group 3"), ("Interior IA", iia, "Interior IA")]

    st.markdown("### Rail FOB — UP")
    _raw_corridor_table(list(US.BASES.values()) + list(US.ALLEN_MARKETS.values()), sel_date)
    st.caption(_UP_NOTES)

    st.markdown("### FOB by State — Group 3 vs Interior IA")
    if periods:
        _csx_fob_by_corridor(_up_state_rows(), active, periods, None, "up_state_index", title="FOB UP")
        st.caption("Best (highest) FOB among the state's named origins and the unnamed ones par to the base, per base and bid period — an "
                   "index, not any single origin's number. Shaded = the better base for that state / period.")
    else:
        st.caption("No UP Group 3 / Interior IA postings on or before this date yet.")

    st.markdown("### Key Corridors — Named Origins")
    if periods:
        rows = _up_origin_rows(US.origin_spreads(), lambda o: f"{o['state']} · {o['name'].split(',')[0]}")
        _csx_fob_by_corridor(rows, active, periods, None, "up_named_origins", title="FOB UP")
        st.caption("; ".join(f"{o['name']} — {o['note']}" for o in US.origin_spreads()) + ". † = the second discount is derived through the 8¢ spread.")
    else:
        st.caption("No UP Group 3 / Interior IA postings on or before this date yet.")

    st.markdown("### Allen Station, IL — Mexico vs Domestic")
    allen_periods = _period_union(mex, dom)
    if allen_periods:
        _csx_fob_by_corridor([("IL · Allen Station", lambda f, bid: bid)], [("Mexico", mex, "m"), ("Domestic", dom, "d")], allen_periods,
                             None, "up_allen", title="FOB UP")
        bits = []
        for p in allen_periods:
            iv = (iia.get(p) or {}).get("bid")
            for lbl, cells in (("Mexico", mex), ("Domestic", dom)):
                av = (cells.get(p) or {}).get("bid")
                if iv is not None and av is not None:
                    bits.append(f"{p} {lbl} {av - iv:+.0f}")
        st.caption("Allen's own bids are already FOB at Allen. Against Interior IA: " + (" · ".join(bits[:8]) if bits else "—")
                   + f" (typically +{US.ALLEN_OVER_IIA['Mexico']}¢ to Mexico, about +{US.ALLEN_OVER_IIA['Domestic']}¢ domestic).")
    else:
        st.caption("No Allen Station postings on or before this date yet.")

    _up_location_lookup(active, periods)


def _ns_freight_fn(field, fsc_on, fsc_by_p):
    """freight(row, period) in ¢/bu for one NS region: the workbook's spread to Ft Wayne plus, when the fuel surcharge is on,
    that period's NS $/car-mile x the origin's estimated extra rail miles to the region vs Ft Wayne (ns_miles.py). None when
    the surcharge or the origin's coordinates aren't known, so the cell shows "—" rather than a spread without its fuel."""
    def freight(r, p):
        base = r[f"{field}_cpb"]
        if not fsc_on:
            return base
        d, f = NSM.delta_miles(r["origin"], r["state"], field), fsc_by_p.get(p)
        if d is None or f is None:
            return None
        return base + FD.fsc_cpb(f, d, FD.NS_BU_PER_CAR)
    return freight


def _ns_origin_block(r, active, ftw_cells, periods, ncols, fns):
    """One NS origin's FOB rows: header, then the cheapest-freight region per period."""
    def best(p):
        fs = [f for f in (fns[field](r, p) for _, field in active) if f is not None]
        return min(fs) if fs else None
    first = next((v for v in (best(p) for p in periods) if v is not None), None)
    desc = "" if first is None else f"best freight {_rnd(first)}¢"
    flag = ' <span class="fut-sub">(105-car eligible)</span>' if r["flag_105"] else ""
    return [f'<tr class="origin-hdr"><td colspan="{ncols}">{r["state"]} · {_loc_label(r["origin"])}'
            f'<span class="fut-sub"> &nbsp;{desc}</span>{flag}</td></tr>'] + \
        _fob_variant_rows([("best region", ftw_cells, best)], periods)


def _ns_location_lookup(rows, active, ftw_cells, periods, fns, fsc_on):
    """One NS origin picked from a list — every origin in the NS freight workbook, with a row per region so the regions can
    be compared (Kolten, 2026-10-28)."""
    st.markdown("### FOB at Any NS Location")
    names = {f"{r['state']} · {_loc_label(r['origin'])}": r for r in rows}
    pick = st.selectbox("NS origin", sorted(names), index=None, key="ns_loc_pick", label_visibility="collapsed",
                        placeholder=f"Pick or type an origin — {len(names)} in the NS freight workbook ...")
    if not pick:
        st.caption("Pick an origin to see its FOB in each region, across the bid periods.")
        return
    if not periods:
        st.caption(f"No {FD.NS_BID_MARKET} postings on or before this date yet.")
        return
    r = names[pick]
    ncols = 1 + len(periods)
    label_rows = []
    for region, field in active:
        vals = []
        for p in periods:
            bid, f = ftw_cells.get(p, {}).get("bid"), fns[field](r, p)
            vals.append(None if bid is None or f is None else bid - f)
        label_rows.append((region, vals))
    flag = ' <span class="fut-sub">(105-car eligible)</span>' if r["flag_105"] else ""
    html = _origin_table_open(periods, ncols)
    html.append(f'<tr class="origin-hdr"><td colspan="{ncols}">{pick}{flag}</td></tr>')
    html.extend(_variant_value_rows(label_rows))
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, "ns_fob_origin.png")
    if fsc_on:
        deltas = [(region, NSM.delta_miles(r["origin"], r["state"], field)) for region, field in active]
        if any(d is None for _, d in deltas):
            st.caption("Fuel surcharge: no coordinates for this station, so no FOB.")
        else:
            st.caption(f"Fuel surcharge miles ({NSM.note(r['origin'], r['state'])}) — extra rail miles vs Ft Wayne: "
                       + " · ".join(f"{region} {d:+,.0f}" for region, d in deltas) + ".")


def _ns_tab(sel_date):
    st.caption(f"Posting date **{sel_date}** — change it on the 📋 Bids tab.")
    cols = st.columns(3)
    show = {}
    for (region, field), c in zip(FD.NS_REGIONS.items(), cols):
        show[field] = c.checkbox(region, value=True, key=f"ns_f_{field}")
    active = [(region, field) for region, field in FD.NS_REGIONS.items() if show[field]]
    if not active:
        st.info("Select at least one region to filter on.")
        return
    fsc_on = st.checkbox("Include NS fuel surcharge (\\$ per car-mile on the extra rail miles vs Ft Wayne)", value=True,
                         key="ns_fsc_on")
    only105 = st.checkbox("State index: 105-car origins only (the workbook's \"105?\" column)", value=True, key="ns_idx_105",
                          help="The state index takes each state's best origin. Without this, small sidings that can't load a 105-car "
                               "train (and aren't in NS's grain loader directory, e.g. Browns, IL) can set a state's number.")
    rows = FD.load_ns()

    ftw_cells, ftw_eff = _bid_cells_for("manual", FD.NS_BID_MARKET, sel_date)
    periods = _period_union(ftw_cells)
    fsc_by_p, fsc_parts = _fsc_by_period("NS", periods) if fsc_on else ({}, [])
    fns = {field: _ns_freight_fn(field, fsc_on, fsc_by_p) for _, field in FD.NS_REGIONS.items()}

    st.markdown("### Rail FOB — NS")
    _raw_corridor_table([FD.NS_BID_MARKET], sel_date)
    if fsc_on and periods:
        st.caption("NS fuel surcharge, \\$/car-mile: " + " · ".join(fsc_parts)
                   + ". The freight below is a spread to Ft Wayne, so the surcharge counts only on each origin's estimated "
                     "extra rail miles vs Ft Wayne to the region (negative for origins nearer the region than Ft Wayne).")

    st.markdown("### FOB Index by State")
    variant_fields = [(region, fns[field]) for region, field in active]
    bid_cells_map = {region: ftw_cells for region, _ in active}
    idx_rows = [r for r in rows if r["flag_105"]] if only105 else rows
    _state_fob_table(idx_rows, variant_fields, bid_cells_map, periods, name="ns_state_index")

    st.markdown("### Highlighted Origins")
    if ftw_eff and ftw_eff != sel_date:
        st.caption(f"{FD.NS_BID_MARKET} as of {ftw_eff}")
    highlighted = [r for r in rows if r["highlighted"]]
    if periods and highlighted:
        ncols = 1 + len(periods)
        html = _origin_table_open(periods, ncols)
        for r in highlighted:
            # All three regions net against the SAME NS Ft Wayne bid, so each period shows the cheapest-freight region
            # for it (with the fuel surcharge the best region can change by period).
            html.extend(_ns_origin_block(r, active, ftw_cells, periods, ncols, fns))
        html.append('</tbody></table>')
        table_html = ''.join(html)
        st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
        _table_actions(table_html, "ns_highlighted_origins.png")
    else:
        st.caption(f"No {FD.NS_BID_MARKET} postings on or before this date yet.")

    _ns_location_lookup(rows, active, ftw_cells, periods, fns, fsc_on)

    with st.expander(f"All NS origins, ranked by freight spread ({len(rows)} total)"):
        st.caption("The workbook's spreads to Ft Wayne, before the fuel surcharge.")
        _expanded_freight_table(
            rows, state_key="state",
            label_cols=[("Origin", lambda r: r["origin"]),
                        ("105-car", lambda r: "Y" if r["flag_105"] else "")],
            variants=[(region, field + "_cpb", show[field]) for region, field in FD.NS_REGIONS.items()],
            name="ns_all_origins",
        )

    st.markdown(
        '<div class="legend">FOB(origin) = bid at NS Ft Wayne − rail freight (¢/bu, '
        'already $/bu in the source workbook × 100) − NS fuel surcharge on the estimated extra rail miles vs Ft Wayne '
        '(\\$/car-mile ÷ 3800 bu/car × 100; the miles are great-circle distance to a representative town in each region '
        '× 1.10, rough). GA / NC-SC-VA / East are three '
        'published through-rate variants against the same physical move, all pricing '
        'off the same bid — so Highlighted Origins shows the cheapest-freight '
        'region among whichever are checked above for each period, not all three; see FOB at Any NS Location or the expander '
        'below to compare regions side by side.</div>',
        unsafe_allow_html=True,
    )


# The tab's "big" bid periods (Oct / Nov / Dec / JFM as of 2026-10-28) come from the
# freight seed's `index_periods`, so a roll needs no code change. Only these get the
# FH+LH / Split / OND bid inference below and a column in the FOB Index by State.
_BN_TARGET_MONTHS = tuple(FD.load_bn_index_periods())
_BN_TARGET_BY_LOWER = {m.lower(): m for m in _BN_TARGET_MONTHS}


# A headline period with no posting of its own takes its package's: AM and JJ both sit inside AMJJ.
_BN_FILL_PACKAGES = {"AM": ("AMJJ",), "JJ": ("AMJJ",)}


def _bn_pair(cells, *labels):
    """(bid, offer) of the first matching period (exact label, case-insensitive) that has a bid —
    None if none does."""
    by_lower = {p.lower(): c for p, c in cells.items()}
    for lbl in labels:
        c = by_lower.get(lbl.lower())
        if c and c.get("bid") is not None:
            return (c["bid"], c.get("offer"))
    return None


def _bn_mean(a, b):
    """Midpoint, or whichever side exists."""
    return b if a is None else a if b is None else (a + b) / 2


def _bn_infer_quote(cells, month):
    """Best-effort (bid, offer) for one of the headline periods (_BN_TARGET_MONTHS) when it wasn't
    posted as its own literal period that day, from whatever partial pieces WERE posted (Kolten's
    call, 2026-08-26 — only bother for the "big" periods, not every smaller package). Display-only
    for FOB purposes — never writes back to the archive, and the raw Rail FOB grid still shows only
    what was literally posted. The offer comes from the same posting as the bid. Tries, in order:
      1. Split <month>, treated as the full month (the basis tracker's rule: a full month wins)
      2. FH/LH <month> averaged (or whichever one exists, if only one does)
      3. the package that contains it (AM and JJ from AMJJ)
      4. for Oct/Nov/Dec only: the OND package (Oct/Nov/Dec combined) — used directly for Oct, or
         reverse-averaged against Oct for Nov and Dec (assuming OND = (Oct+Nov+Dec)/3 and Nov≈Dec)
         when Oct is otherwise known; a straight OND substitution if Oct isn't known either.
    JFM (a package already) gets steps 1-2 only, otherwise just what's posted."""
    direct = _bn_pair(cells, month)
    if direct:
        return direct
    split = _bn_pair(cells, f"Split {month}")
    if split:
        return split
    fh, lh = _bn_pair(cells, f"FH {month}"), _bn_pair(cells, f"LH {month}")
    if fh and lh:
        return ((fh[0] + lh[0]) / 2, _bn_mean(fh[1], lh[1]))
    if fh or lh:
        return fh or lh
    for pkg in _BN_FILL_PACKAGES.get(month, ()):
        q = _bn_pair(cells, pkg)
        if q:
            return q
    if month in ("Oct", "Nov", "Dec"):
        ond = _bn_pair(cells, "OND", "LH OND", "FH OND")
        if ond:
            if month == "Oct":
                return ond
            oct_q = _bn_infer_quote(cells, "Oct")
            if oct_q and oct_q[0] != ond[0]:
                off = (3 * ond[1] - oct_q[1]) / 2 if ond[1] is not None and oct_q[1] is not None else None
                return ((3 * ond[0] - oct_q[0]) / 2, off)
            return ond
    return None


def _bn_effective_quote(cells, period):
    """(bid, offer) as posted if the period has a bid, else a best-effort inferred pair — but only for
    the headline periods (_BN_TARGET_MONTHS); every other period (FH Dec, Split Nov, OND, ...) stays
    exactly as posted, blank if it wasn't."""
    c = cells.get(period) or {}
    if c.get("bid") is not None:
        return (c["bid"], c.get("offer"))
    target = _BN_TARGET_BY_LOWER.get(period.strip().lower())
    return _bn_infer_quote(cells, target) if target else None


def _bn_effective_bid(cells, period):
    q = _bn_effective_quote(cells, period)
    return q[0] if q else None


def _bn_variant_row(cells, month_rates_cpb, periods):
    """¢/bu per period = bid − freight, but freight only exists for a period
    whose first named month falls in BN's currently-published rolling
    window (whatever months that is right now) — everything else is None
    (no roll, no guessing)."""
    row = []
    for p in periods:
        bid = _bn_effective_bid(cells, p)
        frt = FD.bn_freight_cpb(month_rates_cpb, p)
        row.append(None if bid is None or frt is None else bid - frt)
    return row


@st.cache_data(ttl=60)
def _bn_saved_inputs():
    """(latest saved inputs row | None, error text | None)."""
    try:
        return BNI.fetch_latest(), None
    except Exception as e:
        return None, str(e)


def _bn_inputs_state():
    """The inputs the tab runs on: this session's applied edit (only when a save wasn't
    possible), else the latest saved in Snowflake, else the seed's defaults."""
    saved, err = _bn_saved_inputs()
    session = st.session_state.get("bn_inputs_session")
    if session:
        payload, source = session, "Showing values applied for this session only — they are not saved."
    elif saved:
        payload = saved["payload"]
        source = f"Saved in Snowflake {str(saved['saved_at'])[:16]} UTC."
    else:
        payload = BNI.default_payload()
        if err:
            source = "Using the built-in defaults (the 2026-10-28 sheet) — the saved inputs couldn't be read."
        elif BNI.sf_available():
            source = "Using the built-in defaults (the 2026-10-28 sheet) — nothing saved yet."
        else:
            source = ("Using the built-in defaults (the 2026-10-28 sheet) — this isn't running against "
                      "Snowflake, so an edit holds for this session only.")
    ver = hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]
    return {"payload": payload, "source": source, "ver": ver, "error": err, "session": bool(session)}


def _num(x):
    return None if x is None or pd.isna(x) else float(x)


def _bn_save(payload):
    try:
        if BNI.sf_available():
            BNI.save(payload)
            st.session_state.pop("bn_inputs_session", None)
            _bn_saved_inputs.clear()
            st.session_state["bn_save_msg"] = ("ok", "Saved. The freight above now uses these.")
        else:
            st.session_state["bn_inputs_session"] = payload
            st.session_state["bn_save_msg"] = ("warn", "Applied for this session only — this isn't running "
                                                       "against Snowflake, so nothing was saved.")
    except Exception as e:
        st.session_state["bn_inputs_session"] = payload
        st.session_state["bn_save_msg"] = ("warn", f"Couldn't save to Snowflake ({str(e)[:200]}), so these apply "
                                                   "for this session only. If the table is missing, run "
                                                   "bn_inputs_setup.sql there.")
    st.rerun()


@st.cache_data(ttl=21600)
def _bn_weekly_diesel(anchor_year):
    """(EIA weekly US diesel [(Monday, $/gal)] | None, why not | None)."""
    if not BNF.available():
        return None, "no EIA_API_KEY"
    try:
        return BNF.fetch_weekly(date(anchor_year, 7, 1)), None
    except Exception as e:
        return None, str(e)


def _bn_auto_fsc():
    """(the FSC table the BN formula gives from diesel | None, the weekly diesel | None, why not | None)."""
    weekly, err = _bn_weekly_diesel(BNF.crop_year_anchor(date.today()))
    return (BNF.auto_table(weekly, date.today()) if weekly else None), weekly, err


def _bn_fsc_line(payload, auto):
    """The monthly FSC as one subtle line: consecutive months with the same value and source are folded
    (Jan–Mar 0.50); forecast, held-flat and overridden months are marked."""
    groups = []
    for r in BNI.month_rows(payload, auto):
        v = r["fsc"]
        tag = {"forecast": "diesel held flat", "open": "month still open"}.get(r["fsc_kind"], "")
        if r["fsc_source"].startswith("held"):
            tag = "held flat"
        elif r["fsc_source"] == "override":
            tag = "override"
        if groups and groups[-1][2] == v and groups[-1][3] == tag:
            groups[-1][1] = r["label"]
        else:
            groups.append([r["label"], r["label"], v, tag])
    parts = []
    for a, b, v, tag in groups:
        span = a if a == b else a + "–" + b
        parts.append("%s %.2f%s" % (span, v, f" ({tag})" if tag else "") if v is not None
                     else f"{span} not yet entered")
    return " · ".join(parts)


def _bn_secondary_table(payload, auto):
    """The saved shuttle quotes laid out like the delivered-quotes board above it: the shuttle periods across,
    bid with the offer in blue beside it, the FSC as a quiet line underneath. Edited in BN freight inputs below."""
    st.markdown("### Secondary freight")
    quotes = payload.get("quotes", [])
    try:
        d = date.fromisoformat(payload["as_of"])
        asof = f'<span class="asof-chip">as of {d.month}/{d.day}</span>'
    except (KeyError, TypeError, ValueError):
        asof = ""
    n = lambda v: f"{v:,.0f}"

    def cell(q):
        bid, off = q.get("bid"), q.get("offer")
        if bid is None and off is None:
            return "<td>—</td>"
        return "<td>" + (n(bid) if bid is not None else "—") + (
            f' <span class="off">/ {n(off)}</span>' if off is not None else "") + "</td>"

    html = ['<table class="sheet"><tbody><tr><th class="lblhdr">Shuttle</th>']
    html += [f'<th>{_esc(str(q["period"]))}</th>' for q in quotes]
    html.append('</tr><tr><td class="lbl">BN 110-car'
                f'<span class="rail-chip" style="background:{RAIL_COLORS.get("BNSF", "#64748b")}">BNSF</span>{asof}</td>')
    html += [cell(q) for q in quotes]
    html.append('</tr></tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, "bn_secondary_freight.png")
    st.markdown(f'<div class="legend">&#36;/car over the tariff, bid / offer; the bid is what the freight uses. '
                f'FSC &#36;/mile{" from EIA diesel" if auto and payload.get("fsc_mode", "formula") == "formula" else ""}: '
                f'{_bn_fsc_line(payload, auto)}. Update both in BN freight inputs at the bottom.</div>',
                unsafe_allow_html=True)


def _bn_inputs_section(state, auto, weekly, diesel_err):
    """Where Kolten feeds the secondary-market shuttle quotes and the monthly FSC (2026-10-28)."""
    payload, ver = state["payload"], state["ver"]
    st.markdown("### BN freight inputs")
    st.caption("Feed these when the secondary market or the fuel surcharge moves; the freight above rebuilds "
               "from them on Save. " + state["source"])
    msg = st.session_state.pop("bn_save_msg", None)
    if msg:
        (st.success if msg[0] == "ok" else st.warning)(msg[1])
    if state["error"]:
        st.warning(f"Couldn't read the saved inputs ({state['error'][:160]}). If the table doesn't exist yet, "
                   "run bn_inputs_setup.sql in Snowflake.")

    with st.container():
        st.markdown("**Secondary freight — BN 110-car shuttles**")
        as_of = st.date_input("As of", value=pd.to_datetime(payload.get("as_of") or date.today()).date(),
                               key=f"bn_asof_{ver}")
        qdf = pd.DataFrame(payload.get("quotes", []), columns=["period", "bid", "offer"]).astype(
            {"bid": float, "offer": float})
        edited_q = st.data_editor(
            qdf, num_rows="dynamic", hide_index=True, width="stretch", key=f"bn_quotes_{ver}",
            column_config={"period": st.column_config.TextColumn("Period", help="As quoted: F/H November, "
                                                                                 "December, Jan, Feb, Mar 2027, ..."),
                           "bid": st.column_config.NumberColumn("Bid $/car", format="%.0f"),
                           "offer": st.column_config.NumberColumn("Offer $/car", format="%.0f")})
        st.caption("\\$/car over the tariff. The freight uses the BID: a month takes its own full-month quote, "
                   "else the midpoint of its F/H and L/H bids, else the narrowest package covering it; a blank "
                   "bid means no premium. Return Trip is for reference.")
    with st.container():
        st.markdown("**Fuel surcharge (FSC) by month**")
        formula = st.radio("FSC source", ["Formula (EIA diesel)", "Typed values"], horizontal=True,
                           index=0 if payload.get("fsc_mode", "formula") == "formula" else 1,
                           key=f"bn_fscmode_{ver}").startswith("Formula")
        if formula and auto:
            last_d, last_v = weekly[-1]
            st.caption("BN's surcharge follows diesel: 1¢/mile for every 5¢ that the monthly average of EIA's weekly US "
                       "on-highway diesel, two months earlier, sits above \\$3.25. It reproduces every surcharge BN has "
                       f"published (Aug .36, Sep .35, Oct .45, Nov .61). Latest diesel \\${last_v:.3f} ({last_d}); months "
                       "past the data hold it flat. Type an override to replace the formula for a month.")
        elif formula:
            st.warning("Diesel prices aren't available, so the typed FSC (held flat) is used for now. "
                       + ("Add EIA_API_KEY to the app's secrets to turn the formula on."
                          if not BNF.available() else f"EIA couldn't be reached ({str(diesel_err)[:120]})."))
        fld = "fsc_override" if formula else "fsc"
        by_key = {m["key"]: m for m in payload.get("months", [])}
        mdf = pd.DataFrame([{"month": BNI.month_key(n).title(), "fsc": by_key.get(BNI.month_key(n), {}).get(fld),
                             "cars_override": by_key.get(BNI.month_key(n), {}).get("cars_override")}
                            for n in BNI.MONTH_ORDER]).astype({"fsc": float, "cars_override": float})
        edited_m = st.data_editor(
            mdf, hide_index=True, disabled=["month"], width="stretch", key=f"bn_months_{ver}_{formula}",
            column_config={"month": st.column_config.TextColumn("Month"),
                           "fsc": st.column_config.NumberColumn("Override $/mile" if formula else "FSC $/mile",
                                                                format="%.2f"),
                           "cars_override": st.column_config.NumberColumn(
                               "Cars override $/car", format="%.0f",
                               help="Replaces the shuttle-derived premium for that month.")})
        if formula:
            hold = payload.get("hold_fsc", True)
        else:
            hold = st.checkbox("Hold the last FSC flat for months with none",
                               value=payload.get("hold_fsc", True), key=f"bn_hold_{ver}",
                               help="Months past the last one you've typed stay steady at it until the next is "
                                    "typed. Off: a month with no FSC has no freight.")
            st.caption("Leave a month blank to hold the latest FSC; type one to replace it, and every later blank "
                       "month follows it.")

    with st.container():
        st.markdown("**Delivered bid overrides**")
        cur = BNI.bid_overrides(payload)
        g = lambda dest, p, f: (cur.get(dest, {}).get(p) or {}).get(f)
        odf = pd.DataFrame([{"period": p, "pnw_bid": g("PNW", p, "bid"), "pnw_offer": g("PNW", p, "offer"),
                             "herf_bid": g("Hereford", p, "bid"), "herf_offer": g("Hereford", p, "offer")}
                            for p in _BN_TARGET_MONTHS]).astype({c: float for c in ("pnw_bid", "pnw_offer", "herf_bid", "herf_offer")})
        edited_o = st.data_editor(
            odf, hide_index=True, disabled=["period"], width="stretch", key=f"bn_ovr_{ver}",
            column_config={"period": st.column_config.TextColumn("Period"),
                           "pnw_bid": st.column_config.NumberColumn("PNW bid", format="%.0f"),
                           "pnw_offer": st.column_config.NumberColumn("PNW offer", format="%.0f"),
                           "herf_bid": st.column_config.NumberColumn("Hereford bid", format="%.0f"),
                           "herf_offer": st.column_config.NumberColumn("Hereford offer", format="%.0f")})
        st.caption("Cents. Type a bid (and offer) to replace what the board shows for a headline period — for a posting "
                   "that hasn't come through, say. Blank uses the board; typed ones are underlined in FOB by Origin.")

    new_payload = {
        "as_of": as_of.isoformat(),
        "fsc_mode": "formula" if formula else "typed",
        "hold_fsc": hold,
        "quotes": [{"period": str(r.period).strip(), "bid": _num(r.bid), "offer": _num(r.offer)}
                   for r in edited_q.itertuples() if isinstance(r.period, str) and r.period.strip()],
        "bid_overrides": {dest: {r.period: {"bid": _num(getattr(r, f"{pre}_bid")), "offer": _num(getattr(r, f"{pre}_offer"))}
                                 for r in edited_o.itertuples() if _num(getattr(r, f"{pre}_bid")) is not None}
                          for dest, pre in (("PNW", "pnw"), ("Hereford", "herf"))},
        "months": [{"key": str(r.month).lower(),
                    "fsc": by_key.get(str(r.month).lower(), {}).get("fsc") if formula else _num(r.fsc),
                    "fsc_override": _num(r.fsc) if formula else by_key.get(str(r.month).lower(), {}).get("fsc_override"),
                    "cars_override": _num(r.cars_override)}
                   for r in edited_m.itertuples()],
    }
    st.markdown("**What the freight will use**")
    preview = pd.DataFrame([{"Month": r["label"], "FSC $/mile": r["fsc"], "FSC from": r["fsc_source"],
                             "BN Cars $/car (PNW)": r["cars"], "Hereford (÷ 2)": r["cars"] / 2,
                             "Cars from": r["cars_source"]}
                            for r in BNI.month_rows(new_payload, auto)])
    st.dataframe(preview, hide_index=True, width="stretch",
                 column_config={"FSC $/mile": st.column_config.NumberColumn(format="%.2f"),
                                "BN Cars $/car (PNW)": st.column_config.NumberColumn(format="%.0f"),
                                "Hereford (÷ 2)": st.column_config.NumberColumn(format="%.0f")})
    for p in BNI.problems(new_payload):
        st.warning(p)

    b1, b2, _ = st.columns([1, 1, 4])
    if b1.button("Save inputs", type="primary", key=f"bn_save_{ver}"):
        _bn_save(new_payload)
    if state["session"] and b2.button("Use saved values", key=f"bn_discard_{ver}"):
        st.session_state.pop("bn_inputs_session", None)
        st.rerun()


def _bn_fob_cell(v):
    """Accountant style, as on Kolten's sheet: negatives in parentheses (red), no plus sign."""
    if v is None:
        return "—", ""
    n = _rnd(v)
    return (f"({abs(n)})", " neg") if n < 0 else (f"{n}", "")


def _bn_quote(cells_by_dest, overrides, dest, p):
    """((bid, offer) | None, typed override?) — a bid typed in BN freight inputs replaces the board's."""
    ov = (overrides.get(dest) or {}).get(p)
    if ov and ov.get("bid") is not None:
        return (ov["bid"], ov.get("offer")), True
    return _bn_effective_quote(cells_by_dest[dest], p), False


def _bn_fob_by_origin(rows, active, cells_by_dest, window, overrides, legend=True, by_state=False, name="bn_fob_by_origin", eth=None):
    """FOB (¢/bu) per origin, PNW | Hereford side by side under each of the headline periods, in the layout of
    Kolten's "FOB BN" sheet (2026-10-28): the bid in a yellow row, the BN Car Val / FSC per Mi row, and the
    better destination for each origin shaded (the geographical PNW-Hereford divide). by_state: one row per state, each
    cell the BEST FOB among that state's origins (an index, not any one origin). eth: the state ethanol index ({state: {(y, m): (basis, plants)}},
    _ethanol_index) — one more column per period, in grey italics, for the row's state: a benchmark, never shaded."""
    periods = list(_BN_TARGET_MONTHS)
    n = len(active)
    ne = 1 if eth else 0
    today = date.today()
    by_key = {w["key"]: w for w in window}

    def month_win(p):
        m = FD.bn_period_first_month(p)
        return by_key.get(FD._BN_MONTH3_REV[m]) if m else None

    def gl(i):
        return " gl" if i == 0 else ""

    def num(v):
        return f"{v:+.0f}" if float(v).is_integer() else f"{v:+.1f}"

    def quote(dest, p):
        return _bn_quote(cells_by_dest, overrides, dest, p)

    def quote_html(q):
        if q is None:
            return "—"
        return num(q[0]) + (f' <span class="off">/ {num(q[1])}</span>' if q[1] is not None else "")

    html = ['<table class="sheet"><tbody>',
            '<tr><th class="title" rowspan="3">FOB BN</th>'
            + ''.join(f'<th class="grp gl" colspan="{n + ne}">{p}</th>' for p in periods) + '</tr>',
            '<tr>' + ''.join(''.join(f'<th class="sub{gl(i)}">{dest}</th>' for i, (dest, _s) in enumerate(active))
                             + ('<th class="sub">Ethanol</th>' if eth else '') for _ in periods) + '</tr>',
            '<tr>' + ''.join(''.join(f'<td class="bidrow{" ovr" if quote(dest, p)[1] else ""}{gl(i)}">{quote_html(quote(dest, p)[0])}</td>'
                                     for i, (dest, _s) in enumerate(active))
                             + ('<td class="bidrow">plant avg</td>' if eth else '') for p in periods) + '</tr>',
            '<tr class="carsrow"><td class="lbl">BN Car Val / FSC per Mi</td>']
    for p in periods:
        w = month_win(p)
        cars = "—" if w is None else f"{w['cars']:,.0f}"
        fsc = "—" if w is None else f"{w['fsc_per_mile']:.2f}"
        core = [d for d, _s in active if d != "COBO"]
        cells = ([cars, fsc] if len(core) == 2 else [f"{cars} / {fsc}"] if len(core) == 1 else []) + (["—"] if len(core) < n else []) + (["—"] if eth else [])
        html.append(''.join(f'<td class="gl">{c}</td>' if i == 0 else f'<td>{c}</td>' for i, c in enumerate(cells)))
    html.append('</tr>')
    groups = [(r["origin"], [r]) for r in rows]
    if by_state:
        by = {}
        for r in rows:
            by.setdefault(r["state"], []).append(r)
        groups = sorted(by.items())
    for label, grp in groups:
        grid = []
        for p in periods:
            vals = []
            for dest, spec in active:
                q = quote(dest, p)[0]
                bid = q[0] if q else None
                best_v = None
                for r in grp:
                    frt = FD.bn_freight_cpb(r[spec["field"] + "_cpb"], p)
                    if bid is None or frt is None:
                        continue
                    if best_v is None or bid - frt > best_v:
                        best_v = bid - frt
                vals.append(best_v)
            bi = (max((i for i in range(n) if vals[i] is not None), key=lambda i: vals[i])
                  if sum(v is not None for v in vals) >= 2 else None)
            for i, v in enumerate(vals):
                txt, neg = _bn_fob_cell(v)
                grid.append(f'<td class="fobv{neg}{" divide" if i == bi else ""}{gl(i)}">{txt}</td>')
            if eth:
                st_ = label if by_state else grp[0].get("state")
                mo = FD.bn_period_first_month(p)
                hit = EI.lookup(eth, st_, mo, today) if mo and st_ else None
                txt, _neg = _bn_fob_cell(None if hit is None else hit[0])
                grid.append(f'<td class="fobv" style="font-style:italic;color:#64748b">{txt}</td>')
        html.append(f'<tr><td class="lbl">{label}</td>' + ''.join(grid) + '</tr>')
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, f"{name}.png")
    if not legend:
        return
    st.markdown(
        '<div class="legend">BN COBO is the bid less the California tariff only (Hereford face + &#36;960 a car, per USDA AMS) — the COBO buyer takes the car cost and fuel surcharge. ¢/bu, bid − freight: negatives in parentheses; a dotted underline marks a bid typed in BN freight inputs. The yellow row is the bid / offer used (a Split '
        "month, FH+LH averaged or the OND / AMJJ package filled in where that period wasn't posted). BN Car Val is the "
        'secondary-market shuttle bid in &#36;/car (Hereford takes half) and FSC is &#36;/mile, both from the inputs '
        'below. Shaded = the better destination for that origin (the geographical PNW–Hereford divide). Ethanol (grey) is the state\'s ethanol '
        'plant index — the Basis Tracker\'s Corn Processing plants\' average corn basis for the period\'s first month — a benchmark, never shaded.</div>',
        unsafe_allow_html=True)


@st.cache_data
def _bn_lookup_origins():
    return BL.origins(FD.load_bn_seed()["origins"]), BL.default_hereford_adder(FD.load_bn_seed()["origins"])


def _bn_all_rows(window):
    """Every BNSF location with a price-list or sheet rate — the sheet's 13 and the price list's others — built like the sheet's
    rows (the sheet's own rates and miles where it has them; elsewhere the price list's rate plus the default adders and
    miles estimated from the shippers' coordinates). A lane with no rate or no miles is left out of that origin's FOB."""
    opts, _adder0 = _bn_lookup_origins()
    out = []
    for name, o in opts.items():
        out.append(FD.bn_build_row({"origin": name.title(), "state": o["state"], "pnw_rate": o["pnw_rate"], "pnw_miles": o["pnw_miles"],
                                    "herf_rate": o["herf_rate"], "herf_miles": o["herf_miles"]}, window))
    return out


def _bn_location_lookup(active, cells_by_dest, window, overrides, eth=None):
    """FOB for ANY origin on the BNSF price list (Kolten, 2026-10-28), not only the sheet's 13: its face rates from the price
    list, lane miles estimated from the BNSF shippers directory's coordinates (bn_locator.py) — both editable here — then the
    same freight and FOB as the table above."""
    st.markdown("### FOB at Any BN Location")
    opts, adder0 = _bn_lookup_origins()
    pick = st.selectbox("BN origin", list(opts), index=None, key="bn_loc_pick", label_visibility="collapsed",
                        placeholder=f"Pick or type an origin — {len(opts)} on the BNSF price list ...")
    if not pick:
        st.caption("Pick an origin for its FOB the way the table above builds it: BNSF price list face rate, lane miles "
                   "estimated from the shipper's coordinates (you can type your own), this month's FSC and BN Cars premium.")
        return
    o = opts[pick]
    k = re.sub(r"\W+", "_", pick)
    c1, c2, c3 = st.columns(3)
    pm = c1.number_input("PNW miles", min_value=0, step=10, value=o["pnw_miles"], key=f"bn_loc_pm_{k}",
                         disabled=o["pnw_rate"] is None, placeholder="type miles")
    hm = c2.number_input("Hereford miles", min_value=0, step=10, value=o["herf_miles"], key=f"bn_loc_hm_{k}",
                         disabled=o["herf_rate"] is None, placeholder="type miles")
    herf_rate = o["herf_rate"]
    if not o["seeded"] and o.get("herf_list") is not None:
        adder = c3.number_input("Hereford adder \\$/car", min_value=0, step=10, value=adder0, key="bn_loc_adder",
                                help="The sheet's Hereford face rates run \\$0-\\$200 a car over the price list's, "
                                     "varying by origin; this is their average. Edit it if you know better.")
        herf_rate = o["herf_list"] + adder
    row = FD.bn_build_row({"origin": f"{pick.title()[:-2]}{o['state']}", "state": o["state"], "pnw_rate": o["pnw_rate"], "pnw_miles": pm,
                           "herf_rate": herf_rate, "herf_miles": hm}, window)
    _bn_fob_by_origin([row], active, cells_by_dest, window, overrides, legend=False, eth=eth)

    def src(est, typed):
        if o["seeded"]:
            return "from the freight sheet"
        if typed is None:
            return o["miles_note"] + " — type miles to get this lane's FOB"
        return o["miles_note"] if typed == est else "typed"
    bits = []
    if o["pnw_rate"] is None:
        bits.append("No PNW rate for this origin on the BNSF price list.")
    else:
        bits.append(f"PNW face \\${o['pnw_rate']:,.0f}/car" + ("" if o["seeded"] else f" (price list \\${o['pnw_list']:,.0f} + \\${BL.PNW_ADDER})")
                    + f", {'—' if pm is None else f'{pm:,.0f}'} mi ({src(o['pnw_miles'], pm)})")
    if o["herf_rate"] is None:
        bits.append("No Hereford rate for this origin on the BNSF price list.")
    else:
        bits.append(f"Hereford face \\${herf_rate:,.0f}/car" + ("" if o["seeded"] else f" (price list \\${o['herf_list']:,.0f} + \\${adder})")
                    + f", {'—' if hm is None else f'{hm:,.0f}'} mi ({src(o['herf_miles'], hm)})")
    st.caption(" · ".join(bits) + ". Freight and the FSC / BN Car Val in the table are the same as above.")
    if not o["seeded"] and o["coords"] and o["off_box"] and (pm == o["pnw_miles"] or hm == o["herf_miles"]):
        st.caption(f"⚠️ This origin is outside the area the mileage estimate was fitted on (about MN / SD / NE / IA / IL), "
                   f"so treat the estimate as rougher than the usual ±{BL.EST_ERROR_MILES} miles (~1¢/bu) — typing the real miles is better.")
    elif not o["seeded"]:
        st.caption(f"Estimated miles are good to about ±{BL.EST_ERROR_MILES} (~1¢/bu at the current FSC); type the real figure to override.")


def _bn_tab(sel_date):
    st.caption(f"Posting date **{sel_date}** — change it on the 📋 Bids tab.")
    dest_cols = st.columns(len(FD.BN_DESTINATIONS) + 1)
    show = {}
    for (dest, spec), c in zip(FD.BN_DESTINATIONS.items(), dest_cols):
        show[dest] = c.checkbox(dest, value=True, key=f"bn_f_{spec['field']}")
    eth = _ethanol_index() if dest_cols[-1].checkbox("Ethanol index", value=True, key="bn_f_eth",
                                                      help="The state's ethanol plant index (Basis Tracker) beside each period — a benchmark.") else None
    active = [(dest, spec) for dest, spec in FD.BN_DESTINATIONS.items() if show[dest]]
    if not active:
        st.info("Select at least one destination to filter on.")
        return
    inputs = _bn_inputs_state()
    auto, weekly, diesel_err = _bn_auto_fsc()
    window = BNI.effective_window(inputs["payload"], auto)
    rows = FD.load_bn(window)
    published_disp = "/".join(w["label"] for w in window) or "no months yet"

    cells_by_dest, eff_by_dest = {}, {}
    for dest, spec in active:
        cells_by_dest[dest], eff_by_dest[dest] = _bid_cells_for("manual", spec["market"], sel_date)
    periods = _period_union(*cells_by_dest.values())
    asof_bits = [f"{dest} as of {eff_by_dest[dest]}" for dest, _ in active
                 if eff_by_dest[dest] and eff_by_dest[dest] != sel_date]

    st.markdown("### Rail FOB — BN")
    _raw_corridor_table([spec["market"] for _, spec in active], sel_date)

    _bn_secondary_table(inputs["payload"], auto)

    st.markdown("### FOB by State — PNW vs Hereford")
    if any(cells_by_dest.values()):
        overrides = BNI.bid_overrides(inputs["payload"])
        all_rows = _bn_all_rows(window)
        _bn_fob_by_origin(all_rows, active, cells_by_dest, window, overrides, legend=False, by_state=True, name="bn_state_index", eth=eth)
        est = sum(1 for o in _bn_lookup_origins()[0].values() if not o["seeded"]
                  and any(o[f"{lane}_rate"] is not None and o[f"{lane}_miles"] is not None for lane in ("pnw", "herf")))
        st.caption(f"Best (highest) FOB among every BNSF location in the state — the sheet's {len(rows)} origins plus {est} more from the BNSF "
                   "price list whose face rate is the list's (+ the Hereford adder) and whose miles are estimated from the shipper's "
                   "coordinates (about ±70 miles, ~1¢/bu; rougher outside MN / SD / NE / IA / IL) — an index, not any single origin's "
                   "number. Shaded = the better destination for that state / period.")
        st.markdown("### Key Corridors — Highlighted Origins")
        _bn_fob_by_origin(rows, active, cells_by_dest, window, overrides, eth=eth)
        _bn_location_lookup(active, cells_by_dest, window, overrides, eth=eth)
    else:
        st.caption("No BN PNW/Hereford postings on or before this date yet.")

    st.markdown("### BN Origins")
    if asof_bits:
        st.caption(" · ".join(asof_bits))
    if periods:
        ncols = 1 + len(periods)
        html = _origin_table_open(periods, ncols)
        for r in rows:
            label_rows = [(dest, _bn_variant_row(cells_by_dest[dest], r[spec["field"] + "_cpb"], periods))
                          for dest, spec in active]
            html.append(
                f'<tr class="origin-hdr"><td colspan="{ncols}">{r["state"]} · {r["origin"]}'
                f'<span class="fut-sub"> &nbsp;freight published for {published_disp}</span></td></tr>'
            )
            html.extend(_variant_value_rows(label_rows))
        html.append('</tbody></table>')
        table_html = ''.join(html)
        st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
        _table_actions(table_html, "bn_origins.png")
    else:
        st.caption("No BN PNW/Hereford postings on or before this date yet.")

    st.markdown(
        '<div class="legend">FOB(origin) = bid at BN PNW/Hereford − rail freight (¢/bu = '
        '&#36;/car ÷ 4000 bu/car × 100). Unlike CSX/NS, BN publishes rates by month rather than '
        f'one flat number — currently <b>{published_disp}</b> — a period nets against freight '
        'only when its first named month has one (a package like JFM nets on its first month, '
        'Jan); everything else shows "—" until that month has an FSC (entered, or held flat from '
        'the latest one — see the inputs below). '
        "Freight &#36;/car = face rate + lane miles × that month's fuel surcharge &#36;/mile + "
        "that month's BN Cars premium (the secondary-market shuttle bid; PNW takes all of it, "
        "Hereford half) — see the freight build and the BN freight inputs below. "
        f'For the {" / ".join(_BN_TARGET_MONTHS)} columns specifically, a bid not posted that '
        'literal day is filled in best-effort from whatever partial pieces WERE posted — FH+LH '
        'averaged, a Split-month quote used as the month, the AMJJ package for AM / JJ, or (for '
        'Oct/Nov/Dec) the OND package reverse-averaged against Oct when Oct is known — before '
        'falling back to "—"; every '
        'other, smaller period (FH Dec, Split Nov, OND itself, ...) is shown exactly as posted, '
        f'no inference. All {len(rows)} BN origins are shown (the workbook has no separate '
        'highlighted subset for this railroad). Blue = the better destination for that '
        'origin/period.</div>',
        unsafe_allow_html=True,
    )

    with st.expander("Freight build"):
        html = ['<table class="sheet"><tbody><tr>', '<th class="lblhdr">Origin</th>',
                '<th>PNW rate</th>', '<th>PNW mi</th>', '<th>Herf rate</th>', '<th>Herf mi</th>']
        html += [f'<th>PNW {w["label"]}<br><span class="fut-sub">¢/bu</span></th>' for w in window]
        html += [f'<th>Herf {w["label"]}<br><span class="fut-sub">¢/bu</span></th>' for w in window]
        html.append('</tr>')
        for r in rows:
            html.append(
                f'<tr><td class="lbl">{r["origin"]}</td>'
                f'<td>{r["pnw_rate"]:,.0f}</td><td>{r["pnw_miles"]:,.0f}</td>'
                f'<td>{r["herf_rate"]:,.0f}</td><td>{r["herf_miles"]:,.0f}</td>'
                + ''.join(f'<td>{_rnd(r["pnw_cpb"][w["key"]])}</td>' for w in window)
                + ''.join(f'<td>{_rnd(r["hereford_cpb"][w["key"]])}</td>' for w in window)
                + '</tr>')
        html.append('</tbody></table>')
        table_html = ''.join(html)
        st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
        _table_actions(table_html, "bn_freight_build.png")
        st.caption("Rates in \\$/car, then freight in ¢/bu. Fuel surcharge \\$/mile: "
                   + " · ".join(f"{w['label']} {w['fsc_per_mile']:.2f}" for w in window)
                   + ". BN Cars premium \\$/car (Hereford takes half): "
                   + " · ".join(f"{w['label']} {w['cars']:,.0f}" for w in window) + ".")

    if not _view_only():
        _bn_inputs_section(inputs, auto, weekly, diesel_err)


_CN_LETTER = {v: k[-1].upper() for k, v in FD.CN_RATE_FIELD.items()}


def _cn_state_fob_table(filtered, base_fn, freight_fn, months, labels, active_cols, col_word):
    """One row per state per active car size/source variant, one column per price period — best (highest)
    FOB among every origin/volume-tier in that state for that variant. Mirrors CSX's per-variant FOB Index by
    State (_state_fob_table above), but built against CN's price columns and per-row size/source freight instead
    of a period-keyed bid market. base_fn(period, size, rate field) is the price the freight comes off (the CIF
    month, or a bean bid carried from Champaign), None where there isn't one; freight_fn(row, size, rate field, period)
    is the row's freight in ¢/bu (tariff + fuel surcharge), None where its miles or the surcharge aren't known."""
    by_state = {}
    for r in filtered:
        by_state.setdefault(r["state"], []).append(r)
    if not by_state:
        st.caption("No data to index by state yet.")
        return

    ncols = 1 + len(months)
    html = ['<table class="sheet"><tbody><tr>', '<th class="lblhdr">State</th>']
    html += [f'<th>{lbl}</th>' for lbl in labels]
    html.append('</tr>')
    for s in sorted(by_state):
        rows_s = by_state[s]
        label_rows = []
        for size, source, field in active_cols:
            vals = []
            for m in months:
                base = base_fn(m, size, field)
                fobs = [] if base is None else [base - f for f in (freight_fn(r, size, field, m) for r in rows_s)
                                                  if f is not None]
                vals.append(max(fobs) if fobs else None)
            label_rows.append((f"{size} · {source}", vals))
        html.append(f'<tr class="origin-hdr"><td colspan="{ncols}">{s}</td></tr>')
        html.extend(_variant_value_rows(label_rows))
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, "cn_state_index.png")
    st.caption("Best (highest) FOB among every origin/volume-tier in that state, per car "
               f"size/source, per {col_word} — an index, not any single origin's actual "
               "number. Blue = the better size/source for that state/period.")


def _cn_origin_block(r, base_fn, freight_fn, months, active_cols, ncols):
    """The FOB by Origin rows for one tariff row: its header, then a line per car size / source."""
    label_rows = []
    for size, source, field in active_cols:
        vals = []
        for m in months:
            base, frt = base_fn(m, size, field), freight_fn(r, size, field, m)
            vals.append(None if base is None or frt is None else base - frt)
        label_rows.append((f"{size} · {source}", vals))
    switch_mark = ' <span class="fut-sub">⇄ recip. switch</span>' if r["switch"] else ''
    return [f'<tr class="origin-hdr"><td colspan="{ncols}">{r["state"]} · {r["origin"]}'
            f'<span class="fut-sub"> &nbsp;{r["tier"] or r["notes"] or ""}</span>{switch_mark}</td></tr>',
            *_variant_value_rows(label_rows)]


def _cn_freight_factory(commodity, fsc_on, fsc_by_m, champ_miles, uplift_by_m):
    """make(over) -> freight_fn(row, size, rate field, period) in ¢/bu: the tariff rate plus, when the fuel surcharge is on,
    that period's CN 7403 $/mile x the origin's miles to the Gulf (cn_miles.py; `over` = {(origin, state): typed miles}).
    None when the surcharge or the miles aren't known, so the cell shows "—" rather than a freight without its fuel."""
    def make(over=None):
        over = over or {}

        def freight(r, size, field, m):
            extra = float(uplift_by_m.get(m, 0))
            if fsc_on:
                key = (r["origin"], r["state"])
                mi = over[key] if key in over else CM.miles_to_gulf(key[0], key[1], champ_miles)[0]
                f = fsc_by_m.get(m)
                if f is None or mi is None:
                    return None
                extra += f * mi
            return FD.cn_freight_cpb(r[field], size, commodity, extra)
        return freight
    return make


def _cn_location_lookup(lookup_rows, base_fn, make_freight, months, labels, active_cols, commodity, fsc_on, champ_miles):
    """One CN origin picked from a list: every volume tier it has, per car size / source — the same numbers as FOB by Origin
    (Kolten, 2026-10-28). The miles to the Gulf behind the fuel surcharge can be typed here for the one origin."""
    st.markdown(f"### {commodity} FOB at Any CN Location")
    names = sorted({f"{r['origin'].title()}, {r['state']}" for r in lookup_rows})
    pick = st.selectbox("CN origin", names, index=None, key="cn_loc_pick", label_visibility="collapsed",
                        placeholder=f"Pick or type an origin — {len(names)} in the CN tariff ...")
    if not pick:
        st.caption("Pick an origin to see just its rows from the table above, across the volume tiers it has.")
        return
    rows_o = [r for r in lookup_rows if f"{r['origin'].title()}, {r['state']}" == pick]
    over = {}
    if fsc_on:
        o_name, o_state = rows_o[0]["origin"], rows_o[0]["state"]
        est, note = CM.miles_to_gulf(o_name, o_state, champ_miles)
        k = re.sub(r"\W+", "_", pick)
        typed = st.number_input("Rail miles to the Gulf", min_value=0, step=10, value=est, key=f"cn_loc_mi_{k}",
                                placeholder="type miles", help="CN's Get Rail Miles tool gives the exact figure.")
        if typed is not None:
            over[(o_name, o_state)] = typed
        st.caption(f"Miles: {'—' if typed is None else f'{typed:,.0f}'} ({'typed' if typed != est and typed is not None else note})"
                   + ("" if typed is not None else " — type miles to get this origin's FOB"))
    freight_fn = make_freight(over)
    ncols = 1 + len(months)
    html = _origin_table_open(labels, ncols)
    for r in rows_o:
        html.extend(_cn_origin_block(r, base_fn, freight_fn, months, active_cols, ncols))
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, "cn_fob_origin.png")


def _cn_tab(sel_date):
    st.caption("Raw CN Gulf Export tariff rates (Supplement 41 to Tariff CN 004050-A8), plus "
               "a FOB netback against CIF NOLA from the River FOB Portal — corn and soybeans both, tariff plus CN's fuel surcharge. "
               "Soybeans can instead net against the CN 105s Beans bids (FOB Champaign) from the rail bid archive.")

    sc, pc, cc = st.columns(3)
    with sc:
        st.caption("Car size")
        sizes = [s for s in FD.CN_SIZES if st.checkbox(f"{s} ({FD.CN_SIZES[s]})", value=True,
                                                          key=f"cn_size_{s}")]
    with pc:
        st.caption("Car source")
        sources = [s for s in FD.CN_SOURCES if st.checkbox(f"{s} ({FD.CN_SOURCES[s]})", value=True,
                                                              key=f"cn_src_{s}")]
    with cc:
        st.caption("Commodity")
        commodity = st.radio("Commodity", FD.CN_COMMODITIES, key="cn_commodity",
                              label_visibility="collapsed")
        bean_bids = False
        if commodity == "Soybeans":
            st.caption("Soybean price")
            bean_bids = st.radio("Soybean price", ["CN 105s Beans bids", "Soybeans CIF NOLA"], key="cn_soy_src",
                                 label_visibility="collapsed").startswith("CN")
    active_cols = [(size, source, FD.CN_RATE_FIELD[(size, source)])
                   for size in sizes for source in sources]
    if not active_cols:
        st.info("Select at least one car size and one car source to filter on.")
        return

    rows = FD.load_cn()
    states = sorted({r["state"] for r in rows})
    tier_order = FD.CN_VOLUME_TIER_ORDER
    tiers = sorted({r["tier"] for r in rows if r["tier"]}, key=tier_order.index)
    fc1, fc2 = st.columns(2)
    with fc1:
        sel_states = st.multiselect("Filter by state", states, default=states, key="cn_states")
    with fc2:
        sel_tiers = st.multiselect("Filter by volume tier", tiers, default=tiers, key="cn_tiers")
    filtered = sorted((r for r in rows if r["state"] in sel_states and r["tier"] in sel_tiers),
                       key=lambda r: (r["state"], r["origin"], tier_order.index(r["tier"])))

    fsc_on = st.checkbox("Include CN fuel surcharge (CN 7403 — \\$ per car-mile on the miles to the Gulf)", value=True,
                         key="cn_fsc_on")
    champ_miles = CM.CHAMPAIGN_MILES            # fixed: USDA's 870 for Gibson City, less ~33 (cn_miles.py)
    uplift_by_m = {}
    fsc_by_m = {}
    make_freight = _cn_freight_factory(commodity, fsc_on, fsc_by_m, champ_miles, uplift_by_m)
    freight_fn = make_freight()

    # ── FOB sections up top; the raw tariff table moves to the bottom for reference — Kolten's call,
    # 2026-08-26: the FOB values are what's actually used day to day, the raw $/car rates are backup detail.
    # Corn and (optionally) soybeans net against the CIF NOLA curve. Soybeans can instead use the CN 105s Beans bids
    # (2026-10-28): the bid is FOB Champaign for a 105-car shuttle, so each 105+ car origin's FOB is that bid
    # carried by the freight difference from Champaign — bid + freight(Champaign) - freight(origin), like for like
    # in car size and source.
    price_error, base_fn, months, labels, legend = None, None, [], [], ""
    fob_rows, as_of, bids = filtered, None, {}
    top_tier = FD.CN_VOLUME_TIER_ORDER[-1]
    if bean_bids:
        cells, as_of = _bid_cells_for("manual", "CN 105s Beans", sel_date)
        champ = next((r for r in rows if r["origin"] == "CHAMPAIGN" and r["state"] == "IL" and r["tier"] == top_tier), None)
        periods = [p for p in _period_union(cells) if cells[p].get("bid") is not None]
        if not periods:
            price_error = "No CN 105s Beans bids on or before this posting date yet (change it on the Bids tab)."
        elif champ is None:
            price_error = "The tariff has no Champaign, IL 105+ car rate to carry the bean bids from."
        else:
            bids = {p: cells[p]["bid"] for p in periods}
            months = periods
            labels = [p + (f" · {cells[p]['futures']}" if cells[p].get("futures") else "") for p in periods]
            def base_fn(m, size, field):
                f = freight_fn(champ, size, field, m)
                return None if f is None else bids[m] + f
            fob_rows = [r for r in filtered if r["tier"] == top_tier]
    elif not RVD.configured():
        price_error = ("RIVER_DATABASE_URL isn't set, so this can't reach the River FOB Portal's "
                       "CIF NOLA archive yet. Add it to `.env` locally or as a Streamlit secret.")
    else:
        try:
            as_of, cif = RVD.latest_cif(commodity)
        except Exception as e:
            price_error = f"Couldn't reach the River FOB Portal's database: {e}"
        else:
            if not as_of or not cif:
                price_error = f"No {commodity} CIF NOLA history found in the River FOB Portal's archive yet."
            else:
                months = sorted(cif, key=RVD.month_sort_key)
                labels = months
                base_fn = lambda m, size, field: cif.get(m)

    fsc_win = RF.window("CN", _diesel_weekly, date.today()) if fsc_on else {}
    seed_level = FD.cn_seed_level()
    tariff_bits = []
    for m in months:
        mo = FD.bn_period_first_month(m)
        if mo:
            level, kind = FD.cn_tariff_level(mo, date.today())
            uplift_by_m[m] = 0 if level is None else level - seed_level
            tariff_bits.append(f"{m} {uplift_by_m[m]:+,.0f} (" + ("USDA actual" if kind == "actual" else "USDA's same month last year"
                               if kind else "no USDA data") + ")")
        else:
            uplift_by_m[m] = 0
            tariff_bits.append(f"{m} +0")
        fsc_by_m[m] = (fsc_win.get(FD._BN_MONTH3_REV[mo]) or {}).get("fsc") if mo else None
    if months and not price_error:
        st.caption("CN tariff level vs the seed, \\$/car on every origin: " + " · ".join(tariff_bits)
                   + f". The seed (Supplement 41) is USDA's Gibson City rate for Jun-Aug 2026 (\\${seed_level:,} large railroad car); "
                   "CN's tariff moves by month — Oct is a seasonal peak, and Nov fell $330 last year. USDA publishes two CN origins, Gibson City "
                   "and Ida Grove, IA: the seed equals both of their Jun-Aug 2026 rates exactly and both took the same step in every month "
                   "since except Oct 2026 (Gibson City +$495, Ida Grove +$275), so the same step is applied to every origin; USDA's later "
                   "months replace last year's stand-ins as they are published. It cancels against the Champaign bean bids.")
    if fsc_on and months and not price_error:
        kinds = {"published": "CN-published", "formula": "formula on EIA diesel", "held": "last published, held flat"}
        parts = []
        for m in months:
            mo = FD.bn_period_first_month(m)
            w = fsc_win.get(FD._BN_MONTH3_REV[mo]) if mo else None
            parts.append(f"{m} {w['fsc']:.4f} ({kinds[w['kind']]})" if w else f"{m} —")
        st.caption("Fuel surcharge \\$/car-mile: " + " · ".join(parts)
                   + ". Added to the tariff rate on the miles to the Gulf — USDA's tariff table adds it the same way "
                   "(Gibson City, IL: \\$3,011 tariff + \\$718 fuel in October).")

    st.markdown(f"### {commodity} FOB Index by State")
    if price_error:
        st.info(price_error)
    else:
        _cn_state_fob_table(fob_rows, base_fn, freight_fn, months, labels, active_cols,
                            "bid period" if bean_bids else "CIF month")

    st.markdown(f"### {commodity} FOB by Origin")
    if price_error:
        st.info(price_error)
    elif not fob_rows:
        st.caption("No 105+ car origins in the current filters.")
    else:
        ncols = 1 + len(months)
        html = _origin_table_open(labels, ncols)
        for r in fob_rows:
            html.extend(_cn_origin_block(r, base_fn, freight_fn, months, active_cols, ncols))
        html.append('</tbody></table>')
        table_html = ''.join(html)
        st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
        _table_actions(table_html, "cn_fob.png")
        if fsc_on:
            nomiles = sorted({f"{r['origin'].title()}, {r['state']}" for r in fob_rows
                              if CM.miles_to_gulf(r["origin"], r["state"], champ_miles)[0] is None})
            fsc_note = (" Fuel surcharge = CN 7403 \\$/car-mile × rail miles to the Gulf (a mileage estimated from the town's "
                        "coordinates, good to roughly 10-15% of its distance from Champaign — type your own in FOB at Any "
                        "CN Location)" + (", so against the Champaign bid only the difference in miles counts." if bean_bids
                                          else ".")
                        + (f" No FOB (no coordinates for the station): {', '.join(nomiles)}." if nomiles else ""))
        else:
            fsc_note = " Fuel surcharge not included."
        bpc = FD.CN_BU_PER_CAR[commodity]
        soy_note = (' (derived from the same car\'s weight capacity as corn, ÷60 lb/bu instead of 56)'
                    if commodity == "Soybeans" else '')
        bu_note = (f'Bu/car is by car SIZE only — {bpc["Small"]:,} bu for Small (≤5149 ft³), {bpc["Large"]:,} bu for '
                   f'Large (>5149 ft³){soy_note} — railroad- vs private-supplied doesn\'t change how many bushels '
                   'physically fit.')
        if bean_bids:
            st.markdown(
                f'<div class="legend">FOB(origin) = the CN 105s Beans bid (FOB Champaign, as of {as_of}, ¢/bu vs the futures '
                'shown on each column) + rail freight from Champaign − rail freight from the origin (¢/bu = &#36;/car ÷ '
                f'bu/car), 105+ car tier only, since the bid is for a 105-car shuttle; origins with no 105+ car rate aren\'t '
                f'shown. {bu_note} One column per bid period posted; blue = the better car size/source for that '
                f'origin/period.{fsc_note}</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div class="legend">FOB(origin) = {commodity} CIF NOLA (as of {as_of}, River FOB Portal) − rail freight '
                f'(¢/bu = &#36;/car ÷ bu/car). {bu_note} One column per CIF delivery month currently archived; blue = the '
                f'better car size/source for that origin/month.{fsc_note}</div>', unsafe_allow_html=True)

    if not price_error:
        _cn_location_lookup([r for r in rows if not bean_bids or r["tier"] == top_tier], base_fn, make_freight, months, labels,
                            active_cols, commodity, fsc_on, champ_miles)

    st.markdown("### Raw CN Gulf Export Rates")
    html = ['<table class="sheet"><tbody><tr>',
            '<th class="lblhdr">State</th>', '<th class="lblhdr">Origin</th>',
            '<th class="lblhdr">Volume Tier</th>']
    html += [f'<th>{size}<br><span class="fut-sub">{source}</span></th>' for size, source, _ in active_cols]
    html.append('</tr>')

    def _rate_cell(r, size, field):
        v = r[field]
        letter = _CN_LETTER[field]
        mark = ' <span class="fut-sub">(C)</span>' if letter.lower() in (r.get("changed") or ()) else ''
        cpb = FD.cn_freight_cpb(v, size, commodity)
        return f'<td>{_rnd(cpb)}¢/bu{mark}<br><span class="fut-sub">&#36;{v:,.0f}/car</span></td>'

    for r in filtered:
        switch_mark = ' <span class="fut-sub">⇄ recip. switch</span>' if r["switch"] else ''
        html.append(
            f'<tr><td class="lbl">{r["state"]}</td><td class="lbl">{r["origin"]}</td>'
            f'<td class="lbl">{r["tier"] or r["notes"] or ""}'
            f'<span class="fut-sub"> ({r["notes"] or "—"})</span>{switch_mark}</td>'
            + ''.join(_rate_cell(r, size, field) for size, _, field in active_cols)
            + '</tr>'
        )
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, "cn_rates.png")
    st.caption(f"{len(filtered)} of {len(rows)} rate rows shown as {commodity.lower()} ¢/bu "
               f"({FD.CN_LB_PER_BU[commodity]} lb/bu), with the tariff's own \\$/car rate below each. "
               "All rows currently go to Gulf Exports Group — multiple rows per origin are different "
               "volume tiers, not different destinations. (C) = tariff-flagged as recently changed. "
               "⇄ recip. switch = this rate includes a reciprocal switch at origin (up to "
               "\\$139/car) — most rows exclude it, this just flags the ones that don't.")

    with st.expander("Note codes"):
        st.markdown(
            "  \n".join(f"**{k}** — {v}" for k, v in FD.CN_NOTES.items())
        )


def _expanded_freight_table(rows, state_key, label_cols, variants, name="all_origins"):
    """Sortable reference table: one row per origin, one column per active
    freight variant (¢/bu), ranked cheapest-first across whichever variants
    are active. `variants`: [(label, cpb_field, is_active), ...]."""
    active = [(lbl, f) for lbl, f, on in variants if on]
    if not active:
        st.caption("Select at least one corridor/region above to see this list.")
        return

    def sort_key(r):
        return min(r[f] for _, f in active)

    ordered = sorted(rows, key=sort_key)
    html = ['<table class="sheet"><tbody><tr>',
            '<th class="lblhdr">State</th>']
    html += [f'<th class="lblhdr">{lbl}</th>' for lbl, _ in label_cols]
    html += [f'<th>{lbl} ¢/bu</th>' for lbl, _ in active]
    if len(active) > 1:
        html.append('<th class="lblhdr">Best</th>')
    html.append('</tr>')
    for r in ordered:
        cells = [f'<td class="lbl">{r[state_key]}</td>']
        cells += [f'<td class="lbl">{fn(r)}</td>' for _, fn in label_cols]
        cells += [f'<td>{_rnd(r[f]):+d}</td>' for _, f in active]
        if len(active) > 1:
            best_lbl = min(active, key=lambda lf: r[lf[1]])[0]
            cells.append(f'<td class="lbl">{best_lbl}</td>')
        html.append('<tr>' + ''.join(cells) + '</tr>')
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, f"{name}.png")
    st.caption(f"{len(ordered)} locations, ranked cheapest freight first.")


REFERENCES = [
    ("CN GeoMapGuide — interactive rail network map", "https://cnebusiness.geomapguide.ca/"),
    ("NS Grain Customer Directory", "http://www.nscorp.com/content/nscorp/en/shipping-options/agriculture-and-forest-products/grain-customer-directory.html"),
    ("CSX Publications & Tariffs", "https://www.csx.com/index.cfm/customers/publications-tariffs/"),
    ("UP Shuttle Train Programs", "https://www.up.com/customers/bulk/shuttle/index.htm"),
    ("BNSF Grain Shuttle Facilities", "http://www.bnsf.com/customers/grain-facilities/shuttles/"),
    ("Rail Rate Checker — Useful Railroad Links", "https://www.railratechecker.com/Useful%20Railroad%20Links.html"),
    ("USDA AgTransport — Grain Rail Cars Loaded and Billed",
     "https://agtransport.usda.gov/Rail/Grain-Rail-Cars-Loaded-and-Billed/27k8-utc2/explore/query/"
     "SELECT%0A%20%20%60date%60%2C%0A%20%20%60week%60%2C%0A%20%20%60month%60%2C%0A%20%20%60year%60%2C%0A"
     "%20%20%60railroad%60%2C%0A%20%20%60state%60%2C%0A%20%20%60all%60%2C%0A%20%20%60dedicated_or_shuttle%60"
     "%2C%0A%20%20%60other%60%2C%0A%20%20%60state_point%60%0AORDER%20BY%20%60date%60%20DESC%20NULL%20FIRST/page/filter"),
]


def _map_tab():
    import rail_map
    rail_map.render()


def _references_tab():
    st.markdown("### Reference Links")
    html = ['<table class="sheet"><tbody>']
    for label, url in REFERENCES:
        html.append(
            f'<tr><td class="lbl" style="white-space:normal">'
            f'<a href="{url}" target="_blank" style="color:#0693e3;font-weight:600">{label}</a>'
            f'<br><span class="fut-sub">{url}</span></td></tr>'
        )
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, "reference_links.png")


# ─────────────────────────────────────────────────────────────────────────────
# SHIPMENTS TAB — USDA AMS carload/shipment-volume data, merged in from the
# standalone "JSA Rail Freight Dashboard" (jsa-home-page/apps/rail_freight),
# 2026-08-26. That app had its own dark-green CSS theme; Kolten's call was to
# drop that and re-theme its charts to this portal's existing light JPSI
# palette instead, so this reads as one product rather than two apps bolted
# together. The underlying data/math (MY week convention, Olympic average,
# bu/car conversion) is untouched — only the presentation layer changed.
# ─────────────────────────────────────────────────────────────────────────────
_SHIP_MONTH_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_SHIP_WESTERN_STATES = ["IA", "NE", "SD", "ND", "MN", "KS", "MO"]
_SHIP_EASTERN_STATES = ["IL", "IN", "OH", "MI", "KY"]
_SHIP_VALID_STATES = [
    'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'IA', 'ID', 'IL', 'IN', 'KS',
    'KY', 'LA', 'MA', 'MD', 'ME', 'MI', 'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH',
    'NJ', 'NM', 'NV', 'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT',
    'VA', 'VT', 'WA', 'WI', 'WV', 'WY',
]
_SHIP_POS, _SHIP_NEG, _SHIP_GOLD = "#16a34a", "#dc2626", "#b45309"
_SHIP_PARQUET_PATH = Path(__file__).parent / "data" / "rail_data.parquet"


def _ship_layout(**kwargs):
    """Plotly layout defaults matching this portal's light JPSI theme
    (paper/plot white, muted-gray axis text, JPSI_BLUE/DARK accents) rather
    than the source dashboard's own dark theme."""
    layout = dict(
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#6b7280", family="Source Sans Pro, system-ui, sans-serif", size=11),
        margin=dict(l=8, r=8, t=36, b=8),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(0,0,0,0)",
                    font=dict(color="#6b7280", size=10)),
        xaxis=dict(gridcolor="#e2e8f0", zerolinecolor="#e2e8f0", tickfont=dict(color="#6b7280")),
        yaxis=dict(gridcolor="#e2e8f0", zerolinecolor="#e2e8f0", tickfont=dict(color="#6b7280")),
    )
    layout.update(kwargs)
    return layout


def _ship_oly_avg(vals):
    """Olympic average: drop highest and lowest, mean of the rest (simple
    mean under 4 values, 0 if empty)."""
    v = [x for x in vals if x is not None and not np.isnan(x)]
    if not v:
        return 0
    if len(v) >= 4:
        return float(np.mean(sorted(v)[1:-1]))
    return float(np.mean(v))


def _ship_pct(curr, base):
    return None if not base else round((curr / base - 1) * 100, 1)


def _ship_fbu(n):
    n = float(n)
    if abs(n) >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(int(n))


def _ship_fdiff(curr, base):
    if not base:
        return "—"
    diff = curr - base
    return f"{'+' if diff >= 0 else ''}{_ship_fbu(diff)}"


def _ship_fpct(v):
    return "—" if v is None else f"{'+' if v >= 0 else ''}{v:.1f}%"


def _ship_prep_df(df, cp_mode):
    if cp_mode == "Combined":
        df = df.copy()
        df['Railroad'] = df['Railroad'].replace({'CP': 'CP/CPKC', 'CPKC': 'CP/CPKC'})
    return df


def _ship_get_rrs(df, cp_mode):
    rrs = sorted(df['Railroad'].dropna().unique().tolist())
    if cp_mode != "Combined":
        return rrs
    merged = []
    for r in rrs:
        if r in ('CP', 'CPKC'):
            if 'CP/CPKC' not in merged:
                merged.append('CP/CPKC')
        else:
            merged.append(r)
    return merged


@st.cache_data(ttl=3600)
def _ship_load_from_api(token=""):
    df = SD.load_usda_data(app_token=token or None)
    return df, datetime.now().strftime("%b %d %Y %I:%M %p")


@st.cache_data
def _ship_load_from_file():
    df = pd.read_parquet(_SHIP_PARQUET_PATH)
    ts = datetime.fromtimestamp(_SHIP_PARQUET_PATH.stat().st_mtime).strftime("%b %d %Y")
    return df, ts


def _shipments_tab():
    st.caption("USDA AMS weekly grain rail carloads (agtransport.usda.gov), converted to "
               "bushels at 4,000 bu/car — merged in from the standalone Rail Freight "
               "Dashboard. This is shipment VOLUME, not a freight rate — a different "
               "question from the FOB tabs above (\"how much moved\" vs. \"what does it cost\").")

    token = ""
    if not _view_only():
        for _ in __import__("portal_view").staff_expander("Data source"):
            token = st.text_input("USDA App Token (optional)", type="password",
                                   help="Free token from agtransport.usda.gov — increases rate limits.",
                                   key="ship_token")
            if st.button("Refresh from live API", key="ship_refresh"):
                st.cache_data.clear()
                st.session_state["ship_force_api"] = True
                st.rerun()
            st.caption("Loads from bundled data by default; use the button above for the latest.")
            st.caption("KCS reported as a national total only (no state breakdown).")

    _secret_token = os.environ.get("USDA_APP_TOKEN", "")
    if not _secret_token:
        try:
            import _snowflake
            _secret_token = (_snowflake.get_generic_secret_string("USDA_APP_TOKEN") or "").strip()
        except ImportError:
            pass  # not running inside Snowflake — fine, this secret is optional anyway
    effective_token = token or _secret_token

    if st.session_state.get("ship_force_api"):
        with st.spinner("Fetching latest USDA data from API…"):
            try:
                df, last_updated = _ship_load_from_api(effective_token)
                data_source = "LIVE API"
            except Exception as e:
                st.error(f"API fetch failed: {e}")
                st.session_state["ship_force_api"] = False
                st.rerun()
    elif _SHIP_PARQUET_PATH.exists():
        df, last_updated = _ship_load_from_file()
        data_source = "Bundled"
    else:
        with st.spinner("Fetching USDA data…"):
            try:
                df, last_updated = _ship_load_from_api(effective_token)
                data_source = "LIVE API"
            except Exception as e:
                st.error(f"Failed to load data: {e}")
                st.stop()

    badge = ("🟢 LIVE API" if data_source == "LIVE API" else f"🔵 data as of {last_updated}")
    st.caption(f"**{badge}**")

    all_years = sorted(df['Market Year'].dropna().unique().tolist())

    (sub_progress, sub_month, sub_map, sub_weekly, sub_yearly, sub_summary) = st.tabs([
        "Progress", "Railroad by month", "State map", "Weekly by year",
        "Yearly by railroad", "Summary",
    ])

    with sub_progress:
        _ship_tab_progress(df, all_years)
    with sub_month:
        _ship_tab_by_month(df)
    with sub_map:
        _ship_tab_state_map(df, all_years)
    with sub_weekly:
        _ship_tab_weekly(df, all_years)
    with sub_yearly:
        _ship_tab_yearly(df)
    with sub_summary:
        _ship_tab_summary(df, all_years)


def _ship_tab_progress(df, all_years):
    c1, c2, c3, c4 = st.columns([1.5, 1.5, 2, 2])
    with c1:
        sel_yr = st.selectbox("Market year", list(reversed(all_years)), index=0, key="t1_year")
    with c2:
        cp_mode1 = st.radio("CP/CPKC", ["Combined", "Split"], horizontal=True, key="t1_cp")
    with c3:
        dfc1 = _ship_prep_df(df, cp_mode1)
        sel_rr1 = st.selectbox("Railroad", ["All"] + _ship_get_rrs(df, cp_mode1), key="t1_rr")
    with c4:
        states_avail1 = sorted(df['State'].dropna().unique().tolist())
        st.selectbox("State", ["All"] + states_avail1, key="t1_state")

    max_wk = int(df[df['Market Year'] == sel_yr]['MY Week'].max())
    _yr_idx = all_years.index(sel_yr)
    ly_yr = all_years[_yr_idx - 1] if _yr_idx > 0 else None
    pool_years = sorted([y for y in all_years if y < sel_yr])[-6:]
    is_split = (cp_mode1 == "Split")
    pool_label = f"{min(pool_years)}–{max(pool_years)}" if pool_years else "—"
    st.caption(f"{sel_yr} — Week {max_wk} · vs LY: {ly_yr or 'N/A'} · "
               f"6-yr avg: {pool_label} (drop hi/lo)")

    def _s(d, year, rr=None, state=None):
        mask = (d['Market Year'] == year) & (d['MY Week'] <= max_wk)
        if rr:
            mask &= (d['Railroad'] == rr)
        if state:
            mask &= (d['State'] == state)
        return float(d.loc[mask, 'Est Bushels'].sum())

    def metrics(rr=None, state=None):
        curr = _s(dfc1, sel_yr, rr, state)
        ly = _s(dfc1, ly_yr, rr, state)
        avg = _ship_oly_avg([_s(dfc1, y, rr, state) for y in pool_years])
        return dict(current=curr, ly=ly, avg=avg,
                    pct_ly=_ship_pct(curr, ly), pct_avg=_ship_pct(curr, avg))

    st.markdown("#### Railroad summary")
    all_rrs = _ship_get_rrs(dfc1, cp_mode1)
    rr_rows = []
    for rr in all_rrs:
        m = metrics(rr=rr)
        hide = is_split and rr in ("CP", "CPKC")
        rr_rows.append({
            "Railroad": rr, "MYtD bu": _ship_fbu(m['current']),
            "vs LY": "—" if hide else _ship_fdiff(m['current'], m['ly']),
            "% vs LY": "—" if hide else _ship_fpct(m['pct_ly']),
            "vs 6-yr avg": "—" if hide else _ship_fdiff(m['current'], m['avg']),
            "% vs avg": "—" if hide else _ship_fpct(m['pct_avg']),
        })
    tot = metrics()
    rr_rows.append({"Railroad": "TOTAL", "MYtD bu": _ship_fbu(tot['current']),
                     "vs LY": _ship_fdiff(tot['current'], tot['ly']),
                     "% vs LY": _ship_fpct(tot['pct_ly']),
                     "vs 6-yr avg": _ship_fdiff(tot['current'], tot['avg']),
                     "% vs avg": _ship_fpct(tot['pct_avg'])})
    with st.container(border=True):
        st.dataframe(pd.DataFrame(rr_rows), width='stretch', hide_index=True,
                     height=min(42 * (len(rr_rows) + 1) + 38, 500))

    st.markdown("#### Railroad deviation")
    dev_rrs, pct_ly_vals, pct_avg_vals, diff_ly_vals, diff_avg_vals = [], [], [], [], []
    for rr in all_rrs:
        m = metrics(rr=rr)
        if is_split and rr in ("CP", "CPKC"):
            continue
        dev_rrs.append(rr)
        pct_ly_vals.append(m['pct_ly'] or 0)
        pct_avg_vals.append(m['pct_avg'] or 0)
        diff_ly_vals.append(_ship_fdiff(m['current'], m['ly']))
        diff_avg_vals.append(_ship_fdiff(m['current'], m['avg']))

    fig_rr = go.Figure()
    fig_rr.add_trace(go.Bar(name="% vs last year", y=dev_rrs, x=pct_ly_vals, orientation='h',
                             marker_color=[_SHIP_POS if v >= 0 else _SHIP_NEG for v in pct_ly_vals],
                             text=diff_ly_vals, textposition='outside'))
    fig_rr.add_trace(go.Bar(name="% vs 6-yr avg", y=dev_rrs, x=pct_avg_vals, orientation='h',
                             marker_color=[JPSI_BLUE if v >= 0 else _SHIP_GOLD for v in pct_avg_vals],
                             text=diff_avg_vals, textposition='outside'))
    rr_layout = _ship_layout(barmode='group', height=max(300, len(dev_rrs) * 52 + 80),
                              title=dict(text=f"Deviation from LY & 6-yr avg — Week {max_wk}",
                                         font=dict(color=JPSI_DARK, size=13)))
    rr_layout['xaxis'].update(tickformat='+.0f', ticksuffix='%')
    fig_rr.update_layout(**rr_layout)
    with st.container(border=True):
        st.plotly_chart(fig_rr, width='stretch')

    st.markdown("#### State deviation")
    state_group = st.radio("State group",
                            ["Top 15", "All states", "Western (IA NE SD ND MN KS MO)",
                             "Eastern (IL IN OH MI KY)"], horizontal=True, key="t1_state_group")
    if "Western" in state_group:
        state_universe = _SHIP_WESTERN_STATES
    elif "Eastern" in state_group:
        state_universe = _SHIP_EASTERN_STATES
    else:
        state_universe = states_avail1

    rel_years = [sel_yr, ly_yr] + pool_years
    dfc1_filt = dfc1[dfc1['Market Year'].isin(rel_years)]
    if sel_rr1 != "All":
        dfc1_filt = dfc1_filt[dfc1_filt['Railroad'] == sel_rr1]

    def _ss(d, year, state):
        mask = (d['Market Year'] == year) & (d['MY Week'] <= max_wk) & (d['State'] == state)
        return float(d.loc[mask, 'Est Bushels'].sum())

    state_data = []
    for st_code in state_universe:
        curr = _ss(dfc1_filt, sel_yr, st_code)
        ly = _ss(dfc1_filt, ly_yr, st_code)
        avg = _ship_oly_avg([_ss(dfc1_filt, y, st_code) for y in pool_years])
        state_data.append(dict(state=st_code, current=curr, ly=ly, avg=avg,
                                pct_ly=_ship_pct(curr, ly), pct_avg=_ship_pct(curr, avg)))
    state_data.sort(key=lambda x: x['pct_ly'] if x['pct_ly'] is not None else -999, reverse=True)
    if state_group == "Top 15":
        state_data = state_data[:15]

    s_names = [x['state'] for x in state_data]
    s_pct_ly = [x['pct_ly'] or 0 for x in state_data]
    s_pct_avg = [x['pct_avg'] or 0 for x in state_data]
    s_diff_ly = [_ship_fdiff(x['current'], x['ly']) for x in state_data]
    s_diff_avg = [_ship_fdiff(x['current'], x['avg']) for x in state_data]

    fig_st = go.Figure()
    fig_st.add_trace(go.Bar(name="% vs last year", y=s_names, x=s_pct_ly, orientation='h',
                             marker_color=[_SHIP_POS if v >= 0 else _SHIP_NEG for v in s_pct_ly],
                             text=s_diff_ly, textposition='outside'))
    fig_st.add_trace(go.Bar(name="% vs 6-yr avg", y=s_names, x=s_pct_avg, orientation='h',
                             marker_color=[JPSI_BLUE if v >= 0 else _SHIP_GOLD for v in s_pct_avg],
                             text=s_diff_avg, textposition='outside'))
    st_layout = _ship_layout(barmode='group', height=max(500, len(s_names) * 34 + 80),
                              title=dict(text=f"State deviation — Week {max_wk}",
                                         font=dict(color=JPSI_DARK, size=13)))
    st_layout['xaxis'].update(tickformat='+.0f', ticksuffix='%')
    fig_st.update_layout(**st_layout)
    with st.container(border=True):
        st.plotly_chart(fig_st, width='stretch')


def _ship_tab_by_month(df):
    c1, c2, c3 = st.columns([2, 1.5, 2])
    with c1:
        all_years = sorted(df['Market Year'].dropna().unique().tolist())
        sel_yr2 = st.selectbox("Market year", ["All years"] + list(reversed(all_years)), key="t2_year")
    with c2:
        cp_mode2 = st.radio("CP/CPKC", ["Combined", "Split"], horizontal=True, key="t2_cp")
    with c3:
        states_avail2 = sorted(df['State'].dropna().unique().tolist())
        sel_state2 = st.selectbox("State", ["All"] + states_avail2, key="t2_state")

    dfc2 = _ship_prep_df(df, cp_mode2)
    if sel_yr2 != "All years":
        dfc2 = dfc2[dfc2['Market Year'] == sel_yr2]
    if sel_state2 != "All":
        dfc2 = dfc2[dfc2['State'] == sel_state2]
    dfc2 = dfc2.copy()
    dfc2['Calendar Month'] = dfc2['Calendar Month'].astype(str).str.strip()

    grp2 = dfc2.groupby(['Calendar Month', 'Railroad'], as_index=False)['Est Bushels'].sum()
    month_map = {'1': 'Jan', '2': 'Feb', '3': 'Mar', '4': 'Apr', '5': 'May', '6': 'Jun',
                 '7': 'Jul', '8': 'Aug', '9': 'Sep', '10': 'Oct', '11': 'Nov', '12': 'Dec',
                 'January': 'Jan', 'February': 'Feb', 'March': 'Mar', 'April': 'Apr',
                 'May': 'May', 'June': 'Jun', 'July': 'Jul', 'August': 'Aug',
                 'September': 'Sep', 'October': 'Oct', 'November': 'Nov', 'December': 'Dec'}
    grp2['Month'] = grp2['Calendar Month'].map(lambda x: month_map.get(x, x))
    grp2 = grp2[grp2['Month'].isin(_SHIP_MONTH_ORDER)]
    grp2['Month'] = pd.Categorical(grp2['Month'], categories=_SHIP_MONTH_ORDER, ordered=True)
    grp2 = grp2.sort_values('Month')

    fig2 = go.Figure()
    for rr in _ship_get_rrs(dfc2, cp_mode2):
        sub = grp2[grp2['Railroad'] == rr]
        fig2.add_trace(go.Bar(name=rr, x=sub['Month'], y=sub['Est Bushels'],
                               marker_color=RAIL_COLORS.get(rr, JPSI_DARK)))
    title2 = "Bushels by month & railroad" + (f" — {sel_yr2}" if sel_yr2 != "All years" else " — all years")
    lay2 = _ship_layout(barmode='stack', height=480,
                         title=dict(text=title2, font=dict(color=JPSI_DARK, size=13)))
    lay2['xaxis'].update(categoryorder='array', categoryarray=_SHIP_MONTH_ORDER)
    lay2['yaxis'].update(tickformat='.2s')
    fig2.update_layout(**lay2)
    with st.container(border=True):
        st.plotly_chart(fig2, width='stretch')


def _ship_tab_state_map(df, all_years):
    c1, c2, c3 = st.columns([1.5, 2, 2])
    with c1:
        sel_yr3 = st.selectbox("Market year", list(reversed(all_years)), key="t3_year")
    with c2:
        rr_list3 = _ship_get_rrs(df, "Combined")
        sel_rr3 = st.selectbox("Railroad", ["All"] + rr_list3, key="t3_rr")
    with c3:
        metric3 = st.radio("Metric", ["Total bu", "% vs LY", "% vs 6-yr avg"],
                            horizontal=True, key="t3_metric")

    dfc3 = _ship_prep_df(df, "Combined")
    if sel_rr3 != "All":
        dfc3 = dfc3[dfc3['Railroad'] == sel_rr3]

    _idx3 = all_years.index(sel_yr3)
    ly_yr3 = all_years[_idx3 - 1] if _idx3 > 0 else None
    comp3 = sorted([y for y in all_years if y < sel_yr3])[-6:]

    map_data = []
    for st_code in _SHIP_VALID_STATES:
        curr3 = float(dfc3.loc[(dfc3['Market Year'] == sel_yr3) & (dfc3['State'] == st_code), 'Est Bushels'].sum())
        ly3 = float(dfc3.loc[(dfc3['Market Year'] == ly_yr3) & (dfc3['State'] == st_code), 'Est Bushels'].sum())
        pool_v3 = [float(dfc3.loc[(dfc3['Market Year'] == y) & (dfc3['State'] == st_code), 'Est Bushels'].sum())
                   for y in comp3]
        avg3 = _ship_oly_avg(pool_v3)
        map_data.append(dict(state=st_code, curr=curr3, ly=ly3, avg=avg3,
                              pct_ly=_ship_pct(curr3, ly3), pct_avg=_ship_pct(curr3, avg3)))
    map_df = pd.DataFrame(map_data)

    if metric3 == "Total bu":
        z_vals, z_label = map_df['curr'].tolist(), "Bushels"
        colorscale = [[0.0, "#eaf4fc"], [0.5, "#4db3f0"], [1.0, JPSI_BLUE]]
        zmid, tickfmt = None, ".2s"
    else:
        col = 'pct_ly' if metric3 == "% vs LY" else 'pct_avg'
        z_vals = [x if x is not None else 0 for x in map_df[col].tolist()]
        z_label, colorscale, zmid, tickfmt = metric3, "RdYlGn", 0, "+.0f"

    hover_text = [
        f"<b>{row['state']}</b><br>Current: {_ship_fbu(row['curr'])}<br>"
        f"vs LY: {_ship_fpct(row['pct_ly'])}<br>vs 6-yr avg: {_ship_fpct(row['pct_avg'])}"
        for _, row in map_df.iterrows()
    ]
    fig3 = go.Figure(go.Choropleth(
        locations=map_df['state'], z=z_vals, locationmode='USA-states',
        colorscale=colorscale, zmid=zmid,
        colorbar=dict(title=dict(text=z_label, font=dict(color="#6b7280")),
                      tickformat=tickfmt, tickfont=dict(color="#6b7280"),
                      bgcolor="#ffffff", bordercolor="#e2e8f0"),
        hoverinfo='text', text=hover_text,
    ))
    map_layout = _ship_layout(height=480)
    map_layout.update(
        geo=dict(scope='usa', bgcolor="#ffffff", lakecolor="#f6f8fa",
                 landcolor="#f6f8fa", subunitcolor="#e2e8f0"),
        title=dict(text=f"State {metric3} — {sel_yr3}", font=dict(color=JPSI_DARK, size=13)),
        margin=dict(l=0, r=0, t=40, b=0),
    )
    fig3.update_layout(**map_layout)

    map_col, detail_col = st.columns([3, 2])
    with map_col:
        with st.container(border=True):
            st.plotly_chart(fig3, width='stretch')
    with detail_col:
        detail_state = st.selectbox("Select state", ["(none)"] + _SHIP_VALID_STATES,
                                     key="t3_detail_state")
        if detail_state != "(none)":
            dfc3_state = dfc3[(dfc3['State'] == detail_state) & (dfc3['Market Year'] == sel_yr3)]
            rr_bu = dfc3_state.groupby('Railroad')['Est Bushels'].sum().reset_index()
            rr_bu = rr_bu.sort_values('Est Bushels', ascending=True)
            fig3b = go.Figure(go.Bar(
                x=rr_bu['Est Bushels'], y=rr_bu['Railroad'], orientation='h',
                marker_color=[RAIL_COLORS.get(r, JPSI_DARK) for r in rr_bu['Railroad']],
                text=[_ship_fbu(v) for v in rr_bu['Est Bushels']], textposition='outside',
            ))
            lay3b = _ship_layout(height=300, title=dict(
                text=f"{detail_state} by railroad — {sel_yr3}", font=dict(color=JPSI_DARK, size=12)))
            lay3b['xaxis'].update(tickformat='.2s')
            fig3b.update_layout(**lay3b)
            with st.container(border=True):
                st.plotly_chart(fig3b, width='stretch')


def _ship_tab_weekly(df, all_years):
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        sel_yrs4 = st.multiselect("Years", list(reversed(all_years)),
                                   default=list(reversed(all_years))[:4], key="t4_years")
    with c2:
        rr_list4 = _ship_get_rrs(df, "Combined")
        sel_rr4 = st.selectbox("Railroad", ["All"] + rr_list4, key="t4_rr")
    with c3:
        states_avail4 = sorted(df['State'].dropna().unique().tolist())
        sel_state4 = st.selectbox("State", ["All"] + states_avail4, key="t4_state")

    if not sel_yrs4:
        st.info("Select at least one year above.")
        return

    dfc4 = df.copy()
    if sel_rr4 != "All":
        dfc4 = dfc4[dfc4['Railroad'] == sel_rr4]
    if sel_state4 != "All":
        dfc4 = dfc4[dfc4['State'] == sel_state4]
    dfc4 = dfc4[dfc4['Market Year'].isin(sel_yrs4)]
    wk_grp = dfc4.groupby(['Market Year', 'MY Week'], as_index=False)['Est Bushels'].sum()

    year_palette = [_SHIP_POS, JPSI_BLUE, _SHIP_GOLD, _SHIP_NEG,
                     "#7c3aed", "#fb923c", "#0e7490", "#db2777"]

    fig4a = go.Figure()
    for i, yr in enumerate(sorted(sel_yrs4)):
        sub = wk_grp[wk_grp['Market Year'] == yr].sort_values('MY Week')
        fig4a.add_trace(go.Bar(name=str(yr), x=sub['MY Week'], y=sub['Est Bushels'],
                                marker_color=year_palette[i % len(year_palette)]))
    lay4a = _ship_layout(barmode='group', height=320,
                          title=dict(text="Weekly shipments by year", font=dict(color=JPSI_DARK, size=13)))
    lay4a['yaxis'].update(tickformat='.2s')
    fig4a.update_layout(**lay4a)
    with st.container(border=True):
        st.plotly_chart(fig4a, width='stretch')

    fig4b = go.Figure()
    for i, yr in enumerate(sorted(sel_yrs4)):
        sub = wk_grp[wk_grp['Market Year'] == yr].sort_values('MY Week').copy()
        sub['Cumulative'] = sub['Est Bushels'].cumsum()
        fig4b.add_trace(go.Scatter(name=str(yr), x=sub['MY Week'], y=sub['Cumulative'],
                                    mode='lines', line=dict(color=year_palette[i % len(year_palette)], width=2)))
    lay4b = _ship_layout(height=320,
                          title=dict(text="Cumulative shipments by year", font=dict(color=JPSI_DARK, size=13)))
    lay4b['yaxis'].update(tickformat='.2s')
    fig4b.update_layout(**lay4b)
    with st.container(border=True):
        st.plotly_chart(fig4b, width='stretch')


def _ship_tab_yearly(df):
    c1, c2, c3 = st.columns([1.5, 2, 2])
    with c1:
        cp_mode5 = st.radio("CP/CPKC", ["Combined", "Split"], horizontal=True, key="t5_cp")
    with c2:
        rr_list5 = _ship_get_rrs(df, cp_mode5)
        focus_rr5 = st.selectbox("Focus railroad (dims others)", ["All"] + rr_list5, key="t5_focus")
    with c3:
        states_avail5 = sorted(df['State'].dropna().unique().tolist())
        sel_state5 = st.selectbox("State", ["All"] + states_avail5, key="t5_state")

    dfc5 = _ship_prep_df(df, cp_mode5)
    if sel_state5 != "All":
        dfc5 = dfc5[dfc5['State'] == sel_state5]
    yr_rr_grp = dfc5.groupby(['Market Year', 'Railroad'], as_index=False)['Est Bushels'].sum()

    fig5 = go.Figure()
    for rr in rr_list5:
        sub = yr_rr_grp[yr_rr_grp['Railroad'] == rr].sort_values('Market Year')
        opacity = 1.0 if (focus_rr5 in ("All", rr)) else 0.25
        fig5.add_trace(go.Bar(name=rr, x=sub['Market Year'].astype(str), y=sub['Est Bushels'],
                               marker=dict(color=RAIL_COLORS.get(rr, JPSI_DARK), opacity=opacity)))
    lay5 = _ship_layout(barmode='stack', height=480, title=dict(
        text="Annual shipments by railroad" + (f" — focus: {focus_rr5}" if focus_rr5 != "All" else ""),
        font=dict(color=JPSI_DARK, size=13)))
    lay5['yaxis'].update(tickformat='.2s')
    fig5.update_layout(**lay5)
    with st.container(border=True):
        st.plotly_chart(fig5, width='stretch')


def _ship_tab_summary(df, all_years):
    c1, c2 = st.columns([2, 2])
    with c1:
        sel_yrs6 = st.multiselect("Years", list(reversed(all_years)),
                                   default=list(reversed(all_years))[:3], key="t6_years")
    with c2:
        rr_list6 = _ship_get_rrs(df, "Combined")
        sel_rr6 = st.selectbox("Railroad", ["All"] + rr_list6, key="t6_rr")

    if not sel_yrs6:
        st.info("Select at least one year above.")
        return

    dfc6 = df.copy()
    if sel_rr6 != "All":
        dfc6 = _ship_prep_df(dfc6, "Combined")
        dfc6 = dfc6[dfc6['Railroad'] == sel_rr6]

    cur_yr6 = max(sel_yrs6)
    _idx6 = all_years.index(cur_yr6)
    ly_yr6 = all_years[_idx6 - 1] if _idx6 > 0 else None
    cur_data6 = dfc6[dfc6['Market Year'] == cur_yr6]
    ly_data6 = dfc6[dfc6['Market Year'] == ly_yr6]
    cur_total6 = float(cur_data6['Est Bushels'].sum())
    ly_total6 = float(ly_data6['Est Bushels'].sum())
    cur_wk6 = int(cur_data6['MY Week'].max()) if not cur_data6.empty else 0
    pct_ly6 = _ship_pct(cur_total6, ly_total6)
    min_yr6, max_yr6 = min(sel_yrs6), max(sel_yrs6)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"Total bu ({cur_yr6})", _ship_fbu(cur_total6))
    k2.metric("vs last year", _ship_fpct(pct_ly6), delta=_ship_fdiff(cur_total6, ly_total6))
    k3.metric("Current week", str(cur_wk6))
    k4.metric("Data range", f"{min_yr6}–{max_yr6}")

    dfc6_sel = dfc6[dfc6['Market Year'].isin(sel_yrs6)]
    dfc6_cp = _ship_prep_df(dfc6_sel, "Combined")
    yr_rr6 = dfc6_cp.groupby(['Market Year', 'Railroad'], as_index=False)['Est Bushels'].sum()
    rr_list6b = sorted(dfc6_cp['Railroad'].dropna().unique().tolist())

    fig6a = go.Figure()
    for rr in rr_list6b:
        sub = yr_rr6[yr_rr6['Railroad'] == rr].sort_values('Market Year')
        fig6a.add_trace(go.Bar(name=rr, x=sub['Market Year'].astype(str), y=sub['Est Bushels'],
                                marker_color=RAIL_COLORS.get(rr, JPSI_DARK)))
    lay6a = _ship_layout(barmode='stack', height=360,
                          title=dict(text="Annual totals by railroad", font=dict(color=JPSI_DARK, size=13)))
    lay6a['yaxis'].update(tickformat='.2s')
    fig6a.update_layout(**lay6a)
    with st.container(border=True):
        st.plotly_chart(fig6a, width='stretch')

    year_pal6 = [_SHIP_POS, JPSI_BLUE, _SHIP_GOLD, _SHIP_NEG, "#7c3aed", "#fb923c"]
    wk_grp6 = dfc6_sel.groupby(['Market Year', 'MY Week'], as_index=False)['Est Bushels'].sum()
    fig6b = go.Figure()
    for i, yr in enumerate(sorted(sel_yrs6)):
        sub = wk_grp6[wk_grp6['Market Year'] == yr].sort_values('MY Week').copy()
        sub['Cumulative'] = sub['Est Bushels'].cumsum()
        fig6b.add_trace(go.Scatter(name=str(yr), x=sub['MY Week'], y=sub['Cumulative'],
                                    mode='lines', line=dict(color=year_pal6[i % len(year_pal6)], width=2)))
    lay6b = _ship_layout(height=320,
                          title=dict(text="Cumulative weekly shipments", font=dict(color=JPSI_DARK, size=13)))
    lay6b['yaxis'].update(tickformat='.2s')
    fig6b.update_layout(**lay6b)
    with st.container(border=True):
        st.plotly_chart(fig6b, width='stretch')


# ─────────────────────────────────────────────────────────────────────────────
# NET CARRY TAB (added 2026-10-05) — the basis tracker's 💵 Net Carry tab for
# this portal's corridors: every delivery a corridor posted, re-expressed against
# ONE futures contract, charged interest from the carry-start month and netted;
# plus the top of net carry, the Cash Fwd Curve chart and a side-by-side
# comparison of corridors. The maths is VENDORED unchanged from the tracker
# (net_carry*.py, carry_rate.py, delivery_period.py — re-sync with
# basis-tracker-streamlit/sync_carry_modules.py, see CLAUDE.md); net_carry_data.py
# feeds it: the bids from the rail_fob rows read above, the futures from the
# tracker's FUTURES_PRICES. Everything is cents/bu.
# ─────────────────────────────────────────────────────────────────────────────
_NC_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@st.cache_data(ttl=300, show_spinner=False)
def _nc_archive():
    """(rows, catalog): every rail_fob bid cell from both sources, each tagged with its source, and the
    corridors that can show a carry ladder. Built from the same cached reads the Bids tab uses."""
    rows = ND.tag_rows({src: _cached_all(src) for src in RD.SOURCES})
    return rows, ND.build_catalog(rows)


@st.cache_data(ttl=600, show_spinner=False)
def _nc_curve(asof_iso):
    """({symbol: cents}, the day it is from): the basis tracker's FUTURES_PRICES, latest day on/before the date."""
    return ND.futures_curve(date.fromisoformat(asof_iso))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _nc_fed_funds():
    """Effective fed funds history behind the default interest rate (FRED, with the committed
    data/fed_funds_dff.csv snapshot as the offline fallback)."""
    return CR.load_fed_funds()


@st.cache_data(ttl=6 * 3600, show_spinner="Loading the futures history…")
def _nc_futures_history(root):
    """{date: {symbol: cents}} for every ZC / ZS contract: the analyst-sheet weeks before the settlement archive starts, under the
    basis tracker's FUTURES_PRICES (Return to Carry rolls the hedge through the crop year with it)."""
    return ND.futures_history(root)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _nc_prime():
    """Bank prime rate history (FRED DPRIME, the committed data/prime_rate.csv snapshot offline) — the Return to Carry report's rate."""
    return CR.load_prime()


def _nc_f(v, dec=1, sign=True):
    if v is None:
        return "—"
    return f"{v:+.{dec}f}" if sign else f"{v:.{dec}f}"


def _nc_quoted(v):
    """Quoted basis: whole cents when it is whole, else one decimal."""
    return _nc_f(v, 0 if float(v).is_integer() else 1)


def _nc_ladder_html(nc_rows, ref_sym, top_row):
    """The Net Carry sheet as one <table class="sheet nc">: Delivery | Futures | Quoted basis | Futures spread
    vs REF | Basis REF | Interest | Net of Interest | Inverse(+)/Carry(−). `top_row` = the table row holding the
    top of net carry (tagged, amber)."""
    ref = _esc(ref_sym or "ref")
    heads = [("lblhdr", "Delivery"), ("lblhdr", "Futures"), ("", "Quoted basis"),
             ("", f"Futures spread vs {ref}"), ("", f"Basis {ref}"), ("", "Interest"),
             ("", f"Net of interest {ref}"), ("", "Inverse (+) / Carry (−)")]
    out = ['<table class="sheet nc"><tbody><tr>']
    out += [f'<th class="{c}">{h}</th>' if c else f'<th>{h}</th>' for c, h in heads]
    out.append('</tr>')
    for i, r in enumerate(nc_rows):
        top = i == top_row
        flag = '' if r.converted else (' <span class="nc-flag" title="no futures spread to the '
                                       'reference — raw basis">·</span>')
        tag = '<span class="nc-tag">▲ TOP OF NET CARRY</span>' if top else ''
        if r.credit is None:
            spread = '<td class="dim">—</td>'
        elif abs(r.credit) < 0.05:           # quoted off the reference itself: nothing to credit
            spread = '<td class="dim">0.0</td>'
        else:
            spread = f'<td>{_nc_f(r.credit)}</td>'
        interest = '' if r.months == 0 else _nc_f(r.interest, 1, sign=False)
        if r.carry is None:
            carry = '<td></td>'
        else:
            cls = 'inv' if r.carry > 0.0049 else 'car' if r.carry < -0.0049 else 'flat'
            carry = f'<td class="{cls}">{_nc_f(r.carry)}</td>'
        out.append(
            ('<tr class="nc-top">' if top else '<tr>')
            + f'<td class="lbl">{_esc(r.delivery)}{flag}{tag}</td>'
            + f'<td class="fut">{_esc(r.futures) if r.futures else "—"}</td>'
            + f'<td>{_nc_quoted(r.raw_basis)}</td>' + spread
            + f'<td>{_nc_f(r.basis_ref)}</td><td>{interest}</td>'
            + f'<td class="net">{_nc_f(r.net)}</td>' + carry + '</tr>')
    out.append('</tbody></table>')
    return ''.join(out)


@st.fragment
def _netcarry_tab():
    if _NC_IMPORT_ERROR is not None:
        st.warning(f"Net Carry isn't available in this runtime — its modules didn't load "
                   f"({type(_NC_IMPORT_ERROR).__name__}: {_NC_IMPORT_ERROR}). The other tabs are unaffected.")
        return
    st.caption(
        "Each delivery a corridor posted, re-expressed against one futures contract and netted against the cost "
        "to carry grain forward. **Inverse (+)** = the market pays to move grain now; **Carry (−)** = the market "
        "pays to store it. Bids are exactly as archived — only the futures spread and the interest are added. "
        "Values are ¢/bu.")
    try:
        rows, catalog = _nc_archive()
    except Exception as e:
        st.warning(f"Couldn't read the rail archive for Net Carry ({type(e).__name__}: {e}).")
        return
    pickable = [c for c in catalog if c.dates]
    if not pickable:
        st.info("No corridor has posted two or more priced forward periods yet, so there is no carry curve to build.")
        return
    by_key = {c.key: c for c in pickable}

    # ── which corridor, which posting ─────────────────────────────────────────
    ca, cb = st.columns([3, 2])
    with ca:
        ckey = st.selectbox("Corridor", list(by_key), format_func=lambda k: by_key[k].label, key="nc_corridor")
    corridor = by_key[ckey]
    latest = corridor.dates[0]
    with cb:
        # the key carries the corridor: the options depend on it (a stale value would not be one of them)
        dsel = st.selectbox(
            "Posting date", list(corridor.dates), key=f"nc_date_{corridor.key}",
            format_func=lambda d: date.fromisoformat(d).strftime("%b %d, %Y") + (" · latest" if d == latest else ""),
            help="The dates this corridor posted two or more priced periods. Each date reads its own bids and "
                 "that day's futures curve.")
    asof = date.fromisoformat(dsel)
    if corridor.spot_only:
        st.caption(f"{corridor.spot_only:,} other posting{'s' if corridor.spot_only != 1 else ''} carried only one "
                   "priced period (mostly the weekly spot history) — nothing to build a curve from, so "
                   "they aren't listed.")
    items = ND.corridor_items(rows, corridor.source, corridor.market, corridor.commodity, dsel)

    # ── how to express it: reference contract, carry start, interest rate ─────
    o1, o2, o3 = st.columns(3)
    with o1:
        mode_lbl = st.radio(
            "Express basis vs", ["Front delivery's futures", "Nearest new-crop"], horizontal=True, key="nc_refmode",
            help="Front delivery's futures: the contract the nearest delivery is quoted off. It reads exactly as "
                 "quoted, and every later month is credited its futures spread vs that contract. Nearest "
                 "new-crop: corn Dec / soy Nov / wheat Jul.")
    with o2:
        anchor_lbl = st.selectbox("Carry starts (interest = 0)", _NC_MONTHS, index=9, key="nc_anchor")
    # The default rate is the Cost of Carry sheet's: effective fed funds on the posting date + 2.25%. The widget key
    # carries the date so the default is re-derived when the date changes (a widget otherwise keeps its first value).
    cr = CR.rate_for(asof, _nc_fed_funds())
    with o3:
        rate_pct = st.number_input(
            "Interest rate (annual %)", min_value=0.0, max_value=25.0, value=min(25.0, round(cr.rate_pct, 2)),
            step=0.01, key=f"nc_rate_{dsel}",
            help="Defaults to the Cost of Carry sheet's rate: effective fed funds on the posting date + "
                 f"{CR.FED_FUNDS_SPREAD_PCT:.2f}%. Edit to use your own cost of funds.")
    anchor_month = _NC_MONTHS.index(anchor_lbl) + 1
    mode = "front" if mode_lbl.startswith("Front") else "newcrop"

    # ── the futures that day (basis tracker's FUTURES_PRICES) ─────────────────
    curve, curve_day, curve_failed = {}, None, False
    try:
        curve, curve_day = _nc_curve(dsel)
    except Exception as e:
        curve_failed = True
        st.warning(f"Couldn't read futures prices from the basis tracker's archive ({type(e).__name__}: {e}). "
                   "Showing the quoted basis only — no futures spread or interest.")
    if not curve_failed and curve_day is None:
        st.warning(f"No futures prices are on file on or before {asof:%b %d, %Y} (the archive starts in Nov 2006), "
                   "so only the quoted basis is shown — no futures spread or interest.")
    elif curve_day is not None and curve_day != asof:
        st.caption(f"Futures prices are from {curve_day:%a %b %d, %Y} — the latest curve on file on or before "
                   "the posting date.")

    # ── the maths (vendored from the basis tracker) ───────────────────────────
    try:
        ref_sym = NC.reference_symbol(corridor.commodity, mode, curve, asof, items=items, anchor_month=anchor_month)
        nc_rows, meta = NC.compute_net_carry(items, ref_sym, curve, anchor_month, rate_pct / 100.0)
        mpts = NC.monthly_carry(nc_rows)      # one point per calendar month (its best quote): charts + the top
        top = NC.top_of_net_carry(mpts, meta["anchor_ym"]) if meta["ref_price"] is not None else None
    except Exception as e:
        st.warning(f"Couldn't build the carry ladder for this posting ({type(e).__name__}: {e}).")
        return
    if not nc_rows:
        # either every quote is a package spanning months (AMJJ), or the archive has no futures contract for them,
        # and a month name alone ('Sep') cannot be placed in time without one
        st.info("None of this posting's quotes can be placed on a delivery month — they are packages spanning "
                "several months (AMJJ) or have no futures contract recorded to date them by — so there is no "
                "carry ladder to draw.")
        if meta.get("skipped"):
            st.caption("Not on the carry ladder: " + ", ".join(meta["skipped"]))
        return

    ay = meta["anchor_ym"]
    anchor_abbr = _NC_MONTHS[ay[1] - 1] if ay else anchor_lbl
    anchor_txt = f"{anchor_abbr} {ay[0] % 100:02d}" if ay else anchor_lbl

    # ── summary line + the headline answer ────────────────────────────────────
    bits = [f"Reference <b>{ref_sym or '—'}</b> "
            + ("(front delivery's futures)" if mode == "front" else "(nearest new-crop)")]
    if meta["ref_price"] is not None:
        bits.append(f"board {meta['ref_price'] / 100:.2f}")
    if meta["per_month"] is not None:
        bits.append(f"interest <b>{meta['per_month']:.2f}¢/mo</b> @ {rate_pct:.2f}%")
    bits.append(f"carry from <b>{anchor_txt}</b>")
    if curve_day is not None:
        bits.append(f"futures of {curve_day:%b %d}")
    st.markdown(f'<div class="nc-summary">{" · ".join(bits)}</div>', unsafe_allow_html=True)
    if top:
        st.markdown(
            '<div class="nc-callout"><span class="tri">▲</span>'
            f'<b>{_esc(NC.top_headline(top))}.</b> {_esc(NC.top_detail(top))}</div>',
            unsafe_allow_html=True)
    if cr.source == "fallback":
        rate_src = ("Fed funds history is unavailable, so the default is the Cost of Carry fallback rate, "
                    f"{CR.FALLBACK_ANNUAL_RATE_PCT:.2f}%.")
    else:
        rate_src = (f"Default rate = effective fed funds {cr.fed_funds_pct:.2f}% ({cr.obs_date:%b %d, %Y}, FRED) + "
                    f"{CR.FED_FUNDS_SPREAD_PCT:.2f}% = {cr.rate_pct:.2f}%.")
    st.caption("Interest = reference board price × rate × days ÷ 360 (actual days from the carry-start month) — the "
               "same formula as the Cost of Carry sheet. " + rate_src)
    st.caption(f"Futures spread = the futures price of the contract each delivery is quoted off minus "
               f"{ref_sym or 'the reference'}'s, in cents. It is credited to the quoted basis so every month is on "
               f"the same footing: quoted basis + futures spread = basis vs {ref_sym or 'reference'}.")
    if ay and ay[1] != anchor_month:
        st.caption(f"This posting has no {anchor_lbl} delivery, so interest starts at its front delivery, {anchor_txt}.")
    if any(r.new_crop for r in nc_rows):
        st.caption("NC (new crop) is the harvest-time bid — the earliest new-crop delivery — so it is the front of "
                   f"the ladder and the carry anchor: interest starts there ({anchor_lbl}).")
    if not meta["all_converted"]:
        st.caption("⚠️ Some deliveries lack a futures spread to the reference contract — those rows show raw basis "
                   "(flagged ·) and their carry may be off.")
    if meta.get("skipped"):
        st.caption("Not on the carry ladder (a package spanning several months, or no futures contract recorded "
                   "to place it in time): " + ", ".join(meta["skipped"]))

    # ── the table ─────────────────────────────────────────────────────────────
    st.markdown(f"### Carry ladder — {corridor.label}")
    table_html = _nc_ladder_html(nc_rows, ref_sym, top["row"] if top else None)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    slug = re.sub(r"[^a-z0-9]+", "_", f"{corridor.label}_{dsel}".lower()).strip("_")
    _table_actions(table_html, f"net_carry_{slug}.png")
    src_txt = "Palmetto's scrape" if corridor.source == "palmetto" else "the manual rundown"
    st.markdown(
        f'<div class="legend">{_esc(corridor.label)} · posted {asof:%b %d, %Y} ({src_txt}), bids exactly as '
        'archived — no roll or adjustment. <span class="sw up"></span>inverse (+) '
        '<span class="sw dn"></span>carry (−) '
        '<span class="sw" style="background:#fff4e5;border:1px solid #f28e2b"></span>top of net carry. '
        'A red <span class="nc-flag">·</span> after a delivery = no futures spread to the reference, so it shows '
        'its raw basis. Every quote keeps its own row, so a month quoted twice (first half / last half, a package) '
        'shows both.</div>',
        unsafe_allow_html=True)

    # ── the Cash Fwd Curve ────────────────────────────────────────────────────
    st.markdown("### Cash forward curve")
    if len(mpts) >= 2:
        show_net = meta["ref_price"] is not None
        ttl, sub = NCC.chart_titles(corridor.commodity, ref_sym, corridor.label)
        try:
            # The legend sits under the plot and is clipped on a ~360 px phone if its entries run long, so the
            # net line is just "Net of interest" (where interest starts is in the summary line and the caption).
            chart = NCC.build_curve_chart(
                mpts, top, title=ttl, subtitle=sub, curve_label=asof.strftime("%m/%d/%y"),
                net_label="Net of interest", anchor_ym=ay, show_net=show_net, logo_uri=WATERMARK or None)
            with st.container(border=True):
                st.altair_chart(chart, width="stretch")
        except Exception as e:
            st.warning(f"Couldn't draw the chart ({type(e).__name__}: {e}).")
        st.caption(
            f"Solid blue = each month's basis re-expressed against {ref_sym or 'its own futures'} (the Basis "
            "column). " + (f"Orange dashed = the same curve net of interest from {anchor_txt} (the Net of Interest "
                           "column); ▲ marks its top. " if show_net else "")
            + "One point per calendar month — a month quoted more than once uses its best quote (the table "
              "above keeps every one).")
    else:
        st.caption("Only one delivery month is quoted on this posting, so there is no curve to chart.")

    # ── Return to carry: what storing this corridor's grain from harvest has paid, crop year by crop year ──────
    view = st.radio(
        "View", ["Net of interest", "Gross carry (before interest)"], horizontal=True, key="nc_measure",
        help="Net of interest = after the interest to carry the grain. Gross carry = the same numbers before "
             "the interest. Applies to the return history below and to the comparison after it.")
    measure = "net" if view.startswith("Net") else "gross"
    if _RTC_IMPORT_ERROR is not None:
        st.info("The return-to-carry history isn't available in this runtime "
                f"({type(_RTC_IMPORT_ERROR).__name__}: {_RTC_IMPORT_ERROR}).")
    else:
        RTCB.render(
            obs=RTCD.obs_from_rail(rows, corridor.market, corridor.commodity),
            quotes=RTCD.quotes_from_rail(rows, corridor.market, corridor.commodity),
            asof=asof, grain=corridor.commodity, measure=measure, tab_rate_pct=rate_pct,
            load_futures=_nc_futures_history, load_prime=_nc_prime, load_fed_funds=_nc_fed_funds,
            logo_uri=WATERMARK or None, scope=corridor.key,
            note="History: this corridor's weekly Spot bid in the rail archive (the old rundown reports), or its nearest forward "
                 "period where the rundown stopped posting Spot; the shipment table's forward bids are the periods posted since "
                 "August 2026.")

    # ── side by side with other corridors ─────────────────────────────────────
    st.markdown("### Compare corridors along the curve")
    options = ND.compare_options(pickable, corridor, asof)
    if not options:
        st.caption(f"No other {corridor.commodity.lower()} corridor has posted within {ND.MAX_AGE_DAYS} days of "
                   f"{asof:%b %d} to compare with.")
        return
    opt_by_key = {c.key: c for c in options}
    default_keys = [c.key for c in ND.default_peers(corridor, options)]
    picked_keys = st.multiselect(
        "Compare with", list(opt_by_key), default=default_keys, format_func=lambda k: opt_by_key[k].label,
        key=f"nc_cmp_{corridor.key}_{dsel}",
        help=f"Corridors that posted {corridor.commodity.lower()} in the last {ND.MAX_AGE_DAYS} days. Starts with "
             "the same railroad's other corridors (Palmetto's boards are pickable but not preselected — they "
             "are the same corridors posted a second way). Type to search.")
    entries = ND.comparison_entries(rows, corridor, items, asof, [opt_by_key[k] for k in picked_keys])
    res = NCMP.build_comparison(entries, ref_sym, curve, anchor_month, meta["anchor_ym"], rate_pct / 100.0,
                                measure, asof)
    cmp_html = NCMP.render_html(res)
    st.markdown(_card_open() + '<div style="padding:8px 8px 2px">' + cmp_html + '</div>' + _card_close(),
                unsafe_allow_html=True)
    # the vendored table sets no font of its own (on the page it inherits Source Sans Pro); the export iframe
    # has no page stylesheet, so give it the same stack or the PNG / copied table comes out in a serif
    _table_actions("<div style=\"font-family:'Source Sans Pro',system-ui,-apple-system,sans-serif\">"
                   + cmp_html + "</div>", f"net_carry_compare_{slug}_{measure}.png")
    st.caption(
        f"Every corridor is re-based to {ref_sym or 'its own futures'} on the same futures day, with interest from "
        f"{anchor_txt} at {rate_pct:.2f}% — so the columns compare directly. ★ = the corridor above · amber ▲ = "
        f"that corridor's top of {'net' if measure == 'net' else 'gross'} carry · green = the best in that month. "
        f"Each corridor shows its latest posting on or before {asof:%b %d} (within {ND.MAX_AGE_DAYS} days); a "
        "different date is flagged under its name.")
    if len(entries) == 1:
        st.caption("Pick more corridors above to compare them with this one.")


def _month_quote(cells, month):
    """(bid, offer, how) for ONE whole calendar month (1-12) from a corridor's posted periods {label: row}, or None:
    the plain month; else Split <month> (a full month wins); else FH / LH <month> averaged (or whichever one is posted); else the
    narrowest posted package that covers it (JFM covers Jan-Mar, AMJJ Apr-Jul, "Jan July" Jan-Jul ...). how: 'month' | 'inferred'."""
    def pair(c):
        return (c["bid"], c.get("offer")) if c and c.get("bid") is not None else None
    name = calendar.month_abbr[month]
    by_lower = {p.strip().lower(): c for p, c in cells.items()}
    for key in (name.lower(), calendar.month_name[month].lower()):
        q = pair(by_lower.get(key))
        if q:
            return (*q, "month")
    q = pair(by_lower.get(f"split {name.lower()}"))
    if q:
        return (*q, "inferred")
    fh, lh = pair(by_lower.get(f"fh {name.lower()}")), pair(by_lower.get(f"lh {name.lower()}"))
    if fh and lh:
        return ((fh[0] + lh[0]) / 2, _bn_mean(fh[1], lh[1]), "inferred")
    if fh or lh:
        return (*(fh or lh), "inferred")
    covering = []
    for p, c in cells.items():
        months = FD.period_months(p)
        if len(months) > 1 and month in months and c.get("bid") is not None:
            covering.append((len(months), c.get("period_order") or 99, p, c))
    if covering:
        c = min(covering, key=lambda t: t[:3])[3]
        return (c["bid"], c.get("offer"), "inferred")
    return None


@st.cache_data(ttl=600, show_spinner=False)
def _ethanol_index():
    """{state: {(year, month): (average corn basis ¢, plants)}} from the Basis Tracker's Corn Processing plants (ethanol_index.py);
    {} off Snowflake or if it can't be read — the summary then simply has no benchmark column."""
    try:
        if not RD._use_snowflake():
            return {}
        since = (date.today() - timedelta(days=EI.LOOKBACK_DAYS)).isoformat()
        return EI.state_index(RD._sf_rows(EI.SQL, (since,)))
    except Exception:
        return {}


def _summary_corridors(sel_date, months, cn_src="CN 105s bids"):
    """The corridors the State Summary compares, for `months` = [(1-12, 'Nov'), ...]: [{label, bid(m) -> text, fob(state, m) -> ¢/bu
    | None, states}] and the footnotes. Each value is the corridor's STATE INDEX — the best (highest) FOB among that state's
    origins — built from the same freight, fuel surcharge and bids as the railroad's own tab, with each corridor's bid resolved to
    the WHOLE month (see _month_quote)."""
    corridors, notes = [], []
    labels = {m: lbl for m, lbl in months}

    def bid_text(q):
        if q is None:
            return "—"
        return f"{q[0]:+.0f}" + (f" / {q[1]:+.0f}" if q[1] is not None else "") + ("*" if q[2] != "month" else "")

    # ---- CSX: Columbus and Evansville, no fuel surcharge (noted on its tab)
    csx = FD.load_csx()
    for label, market, field in (("CSX COL", "CSX Columbus", "columbus"), ("CSX Eville", "CSX Evansville", "eville_altkyla")):
        cells, _eff = _bid_cells_for("manual", market, sel_date)
        quotes = {m: _month_quote(cells, m) for m, _l in months}

        def fob(state, m, quotes=quotes, field=field):
            q = quotes.get(m)
            vals = [q[0] - r[field + "_cpb"] for r in csx if r["state"] == state] if q else []
            return max(vals) if vals else None
        corridors.append({"label": label, "bid": lambda m, quotes=quotes: bid_text(quotes.get(m)), "fob": fob,
                          "states": {r["state"] for r in csx}})
    notes.append("CSX: the 2026-27 origin spreads; its fuel surcharge isn't included.")

    # ---- NS: best region, 105-car origins, with the fuel surcharge
    ns = [r for r in FD.load_ns() if r["flag_105"]]
    ftw, _eff = _bid_cells_for("manual", FD.NS_BID_MARKET, sel_date)
    ns_quotes = {m: _month_quote(ftw, m) for m, _l in months}
    ns_fsc, _parts = _fsc_by_period("NS", list(labels.values()))
    ns_fns = {field: _ns_freight_fn(field, True, ns_fsc) for field in FD.NS_REGIONS.values()}

    def ns_fob(state, m):
        q = ns_quotes.get(m)
        if not q:
            return None
        vals = [q[0] - f for r in ns if r["state"] == state for f in (fn(r, labels[m]) for fn in ns_fns.values()) if f is not None]
        return max(vals) if vals else None
    corridors.append({"label": "NS", "bid": lambda m: bid_text(ns_quotes.get(m)), "fob": ns_fob,
                      "states": {r["state"] for r in ns}})
    notes.append("NS: 105-car-eligible origins, the cheapest of its three regions, with NS's fuel surcharge on the extra miles vs Ft Wayne.")

    # ---- BN: PNW and Hereford over every BNSF location
    inputs = _bn_inputs_state()
    auto, _weekly, _err = _bn_auto_fsc()
    window = BNI.effective_window(inputs["payload"], auto)
    bn_rows = _bn_all_rows(window)
    overrides = BNI.bid_overrides(inputs["payload"])
    cells_by_dest = {dest: _bid_cells_for("manual", spec["market"], sel_date)[0] for dest, spec in FD.BN_DESTINATIONS.items()}
    for dest, spec in FD.BN_DESTINATIONS.items():
        if dest == "COBO":            # COBO stays on the BN tab; the summary compares PNW and Hereford (Kolten, 2026-11-02)
            continue

        def bn_quote(m, dest=dest):
            lbl = labels[m]
            if lbl in _BN_TARGET_MONTHS:                       # Oct / Nov / Dec: the BN tab's own inference and typed bids
                q = _bn_quote(cells_by_dest, overrides, dest, lbl)[0]
                if q:
                    return (q[0], q[1], "month")
            return _month_quote(cells_by_dest[dest], m)
        quotes = {m: bn_quote(m) for m, _l in months}

        def bn_fob(state, m, spec=spec, quotes=quotes):
            q = quotes.get(m)
            if not q:
                return None
            vals = [q[0] - f for r in bn_rows if r["state"] == state
                    for f in [FD.bn_freight_cpb(r[spec["field"] + "_cpb"], labels[m])] if f is not None]
            return max(vals) if vals else None
        corridors.append({"label": f"BN {dest}", "bid": lambda m, quotes=quotes: bid_text(quotes.get(m)), "fob": bn_fob,
                          "states": {r["state"] for r in bn_rows}})
    notes.append("BN: every BNSF location in the state (the sheet's 13 plus the price list's, with estimated miles), freight and fuel "
                 "surcharge for that month.")

    # ---- UP: each state's best origin on Group 3 / Interior IA (the named origins, and the unnamed ones par to the base); IL from
    # Allen Station's own bids (Mexico or domestic, the better)
    g3_cells = _bid_cells_for("manual", US.BASES["Group 3"], sel_date)[0]
    iia_cells = _bid_cells_for("manual", US.BASES["Interior IA"], sel_date)[0]
    allen_cells = [_bid_cells_for("manual", mk, sel_date)[0] for mk in US.ALLEN_MARKETS.values()]
    up_q = {m: (_month_quote(g3_cells, m), _month_quote(iia_cells, m), [_month_quote(c, m) for c in allen_cells]) for m, _l in months}
    up_rows = dict(_up_state_rows())

    def up_fob(state, m):
        g, i, al = up_q[m]
        if state == "IL":
            vals = [q[0] for q in al if q]
        else:
            vals = [v for v in (up_rows[state]("Group 3", g[0]) if g else None, up_rows[state]("Interior IA", i[0]) if i else None)
                    if v is not None]
        return max(vals) if vals else None

    def up_bid(m):
        g, i, _al = up_q[m]
        if not g and not i:
            return "—"
        return " / ".join(f"{n} {q[0]:+.0f}" + ("*" if q[2] != "month" else "") for n, q in (("G3", g), ("IIA", i)) if q)
    corridors.append({"label": "UP", "bid": up_bid, "fob": up_fob, "states": {"NE", "IA", "MN", "IL"}})
    notes.append("UP: each state's best origin on Group 3 or Interior IA (named origins at their stated discounts, the rest par to the base), "
                 "IL from Allen Station's own bids.")

    # ---- CN: 105+ car shuttle origins, large railroad cars, the USDA tariff level plus the fuel surcharge on estimated miles —
    # either the CN 105s corn bids (FOB Champaign: bid + freight(Champaign) - freight(origin), like the CN tab's bean bids) or a
    # corn netback from the CIF NOLA curve
    cn = [r for r in FD.load_cn() if r["tier"] == FD.CN_VOLUME_TIER_ORDER[-1]]
    fsc_win = RF.window("CN", _diesel_weekly, date.today())
    seed_level = FD.cn_seed_level()
    cn_field = FD.CN_RATE_FIELD[("Large", "Railroad")]

    def cn_freight(r, m, miles):
        """¢/bu for one tariff row in month m (1-12): tariff + USDA level + fuel surcharge x miles; None where unknown."""
        level, _k = FD.cn_tariff_level(m, date.today())
        fsc = (fsc_win.get(FD._BN_MONTH3_REV[m]) or {}).get("fsc")
        if fsc is None or miles is None:
            return None
        return FD.cn_freight_cpb(r[cn_field], "Large", "Corn", (0 if level is None else level - seed_level) + fsc * miles)

    champ = next((r for r in cn if r["origin"] == "CHAMPAIGN" and r["state"] == "IL"), None)
    cn_cells = _bid_cells_for("manual", "CN 105s", sel_date)[0]
    if cn_src.startswith("CN 105s") and cn_cells and champ is not None:
        quotes = {m: _month_quote(cn_cells, m) for m, _l in months}

        def cn_fob(state, m):
            q = quotes.get(m)
            f_champ = cn_freight(champ, m, CM.CHAMPAIGN_MILES) if q else None
            if f_champ is None:
                return None
            vals = []
            for r in cn:
                if r["state"] != state:
                    continue
                f = cn_freight(r, m, CM.miles_to_gulf(r["origin"], r["state"])[0])
                if f is not None:
                    vals.append(q[0] + f_champ - f)
            return max(vals) if vals else None
        corridors.append({"label": "CN 105s", "bid": lambda m: bid_text(quotes.get(m)), "fob": cn_fob,
                          "states": {r["state"] for r in cn}})
        notes.append("CN: the CN 105s corn bid (FOB Champaign) carried to each origin by the freight difference — 105+ car shuttle origins, large "
                     "railroad cars, tariff at USDA's level plus CN's fuel surcharge on estimated miles.")
    else:
        try:
            cif = RVD.latest_cif("Corn")[1] if RVD.configured() else {}
        except Exception:
            cif = {}
        if cif:
            def cn_fob(state, m):
                price = cif.get(labels[m])
                if price is None:
                    return None
                vals = []
                for r in cn:
                    if r["state"] != state:
                        continue
                    f = cn_freight(r, m, CM.miles_to_gulf(r["origin"], r["state"])[0])
                    if f is not None:
                        vals.append(price - f)
                return max(vals) if vals else None
            corridors.append({"label": "CN CIF NOLA",
                              "bid": lambda m: "—" if cif.get(labels[m]) is None else f"{cif[labels[m]]:+.0f}",
                              "fob": cn_fob, "states": {r["state"] for r in cn}})
            why = "" if cn_src.startswith("CIF") else " (no CN 105s bids on or before this posting date, so the CIF NOLA netback is shown)"
            notes.append("CN: corn netted back from the CIF NOLA curve (River FOB Portal), 105+ car shuttle origins, large railroad cars, tariff at "
                         "USDA's level plus CN's fuel surcharge on estimated miles" + why + ".")
        else:
            notes.append("CN: left out — no CN 105s bids and no CIF NOLA corn curve reachable.")
    # ---- the state ETHANOL INDEX — a benchmark to read the corridors against, not a corridor (never "best")
    eth = _ethanol_index()
    if eth:
        today = date.today()

        def eth_fob(state, m):
            hit = EI.lookup(eth, state, m, today)
            return None if hit is None else hit[0]

        def eth_bid(m):
            n = sum((EI.lookup(eth, st_, m, today) or (0, 0))[1] for st_ in eth)
            return f"{n} plants" if n else "—"
        corridors.append({"label": "Ethanol Index", "benchmark": True, "bid": eth_bid, "fob": eth_fob, "states": set(eth)})
        notes.append("Ethanol plant index: the average corn basis (¢ vs futures) of the Basis Tracker's Corn Processing plants in the state, "
                     "from each plant's latest bid for the month — a benchmark, so it is never shaded as the best corridor.")
    return corridors, notes


@st.cache_data(ttl=600, show_spinner=False)
def _state_locations(state):
    """{(facility_type, provider, location): {(year, month): basis ¢}} for the Basis Tracker's ethanol plants / corn processors and river
    terminals in one state (ethanol_index.location_series); {} off Snowflake or if it can't be read."""
    try:
        if not RD._use_snowflake():
            return {}
        since = (date.today() - timedelta(days=EI.LOOKBACK_DAYS)).isoformat()
        return EI.location_series(RD._sf_rows(EI.LOC_SQL, (state, since)))
    except Exception:
        return {}


# State Level rail rows, in the order and grouping of Kolten's "FOB Central IL Corn" sheet: (group, summary column label prefix, gateway)
_SL_RAIL_ROWS = (("East Rail", "CN", "Champaign"), ("East Rail", "CSX COL", "Columbus"), ("East Rail", "CSX Eville", "Evansville"),
                 ("East Rail", "NS", "Ft Wayne"), ("West Rail", "UP", "Group 3 / Interior IA"), ("West Rail", "BN PNW", "PNW"),
                 ("West Rail", "BN Hereford", "Hereford"))


@st.fragment
def _state_level_tab(sel_date):
    st.caption(f"Posting date **{sel_date}** — change it on the 📋 Bids tab. One state's FOB (¢/bu) across the rail corridors, its ethanol plants "
               "and river terminals, for the next eight delivery months — the layout of the JSA FOB sheet.")
    today = date.today()
    months = [(((today.month - 1 + k) % 12) + 1, calendar.month_abbr[((today.month - 1 + k) % 12) + 1]) for k in range(8)]
    corridors, notes = _summary_corridors(sel_date, months, "CN 105s bids")
    by_label = {c["label"]: c for c in corridors}
    states = sorted({s_ for c in corridors for s_ in c["states"]})
    state = st.selectbox("State", states, index=states.index("IL") if "IL" in states else 0, key="sl_state")
    locs = _state_locations(state)

    def lbl(key):
        return f"{key[1]} · {key[2]}"
    plants = sorted((k for k in locs if k[0] == "Corn Processing"), key=lambda k: (-len(locs[k]), lbl(k)))
    rivers = sorted((k for k in locs if k[0] == "River Terminal"), key=lambda k: (-len(locs[k]), lbl(k)))
    c1, c2 = st.columns(2)
    sel_plants = c1.multiselect("Ethanol plants", plants, default=plants[:5], format_func=lbl, key=f"sl_plants_{state}")
    sel_rivers = c2.multiselect("River terminals", rivers, default=rivers[:5], format_func=lbl, key=f"sl_rivers_{state}")

    def year_of(m):
        return today.year if m >= today.month else today.year + 1

    # rows: (group, origin, gateway / type, [value per month], rail?)
    rows = []
    for key in sel_rivers:
        rows.append(("River", lbl(key), "At the terminal", [locs[key].get((year_of(m), m)) for m, _n in months], False))
    eth = by_label.get("Ethanol Index")
    if eth and state in eth["states"]:
        rows.append(("Processor", "Ethanol Index (state average)", "Del", [eth["fob"](state, m) for m, _n in months], False))
    for key in sel_plants:
        rows.append(("Processor", lbl(key), "Del", [locs[key].get((year_of(m), m)) for m, _n in months], False))
    for group, prefix, gateway in _SL_RAIL_ROWS:
        c = next((c for lb, c in by_label.items() if lb == prefix or lb.startswith(prefix + " ")), None)
        if c and state in c["states"]:
            rows.append((group, c["label"], gateway, [c["fob"](state, m) for m, _n in months], True))
    if not any(any(v is not None for v in r[3]) for r in rows):
        st.info(f"No bids found for {state} yet.")
        return

    # shade the rail rows only (the sheet's rankings leave the river out): best two green, worst two red, per month
    shade = {}
    for j in range(len(months)):
        ranked = sorted(((r[3][j], i) for i, r in enumerate(rows) if r[4] and r[3][j] is not None), reverse=True)
        if len(ranked) >= 4:
            for _v, i in ranked[:2]:
                shade[(i, j)] = "#dcfce7"
            for _v, i in ranked[-2:]:
                shade[(i, j)] = "#fee2e2"
    sub_labels = ["Spot"] + [f"{k} Mon" for k in range(1, len(months))]
    html = ['<table class="sheet"><tbody>',
            f'<tr><th class="title" rowspan="2" colspan="3">FOB {state} Corn</th>' + ''.join(f'<th class="grp gl">{n}</th>' for _m, n in months) + '</tr>',
            '<tr>' + ''.join(f'<th class="sub gl">{t}</th>' for t in sub_labels) + '</tr>']
    last_group, spans = None, {}
    for r in rows:
        spans[r[0]] = spans.get(r[0], 0) + 1
    for i, (group, origin, gate, vals, _rail) in enumerate(rows):
        cells = []
        if group != last_group:
            cells.append(f'<td class="lbl" rowspan="{spans[group]}" style="font-style:italic;color:#64748b">{group}</td>')
            last_group = group
        cells.append(f'<td class="lbl">{origin}</td><td class="lbl" style="color:#64748b">{gate}</td>')
        for j, v in enumerate(vals):
            txt, neg = _bn_fob_cell(v)
            bg = f' style="background:{shade[(i, j)]}"' if (i, j) in shade else ""
            cells.append(f'<td class="fobv{neg}{" gl" if j == 0 else ""}"{bg}>{txt}</td>')
        html.append('<tr>' + ''.join(cells) + '</tr>')
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, f"state_level_{state.lower()}.png")
    st.markdown('<div class="legend">¢/bu as posted, negatives in parentheses. Rail rows are the state\'s best origin on that corridor after freight '
                '(the State Summary\'s numbers); river terminal and ethanol plant rows are the Basis Tracker\'s latest corn bids for the month at that '
                'location (a plant bid is delivered; a river bid is at the terminal — truck freight and margin to bring them to an origin FOB, like the '
                '37¢ + 4¢ on the sheet, are not applied). Ethanol Index is the average of every Corn Processing plant in the state. Green / red = the best / '
                'worst two rail rows for the month. ' + " ".join(n for n in notes if n.startswith(("CSX", "NS", "BN", "UP", "CN"))) + '</div>',
                unsafe_allow_html=True)


# The core shipping states the State Summary opens on (Kolten, 2026-11-02: "a sub set of states ... the core shipping states"); the rest are
# behind the toggle. My pick of the main rail-loading states across the corridors — edit here.
_CORE_STATES = ("IA", "IL", "IN", "MI", "MN", "ND", "NE", "OH", "SD")


@st.fragment
def _summary_tab(sel_date):
    st.caption(f"Posting date **{sel_date}** — change it on the 📋 Bids tab. State-indexed FOB (¢/bu, the best origin in each state) for "
               "every rail corridor, one table per delivery month: the front month and the four after it.")
    today = date.today()
    # The front month is the current month, always (Kolten, 2026-11-02: "November as the front month and then the 4 months to follow",
    # then "default with showing the current month").
    first = today.month          # always the current month first (Kolten, 2026-11-03: "always show the nearest month ... not even an option")
    months = [(((first - 1 + k) % 12) + 1, calendar.month_abbr[((first - 1 + k) % 12) + 1]) for k in range(5)]
    cn_src = st.radio("CN price", ["CN 105s bids", "CIF NOLA netback"], horizontal=True, key="sum_cn_src",
                      help="CN 105s bids: the CN 105s corn bid (FOB Champaign) carried to each origin by the freight difference. "
                           "CIF NOLA netback: the River FOB Portal's CIF NOLA corn price less each origin's full freight.")
    all_states = st.toggle("Show all states", value=False, key="sum_all_states",
                           help="Off: the core shipping states (" + ", ".join(_CORE_STATES) + "). On: every state any corridor has an origin in.")
    corridors, notes = _summary_corridors(sel_date, months, cn_src)
    states_all = sorted({s_ for c in corridors for s_ in c["states"]})
    if not all_states:
        states_all = [s_ for s_ in states_all if s_ in _CORE_STATES]
    for m, name in months:
        html = ['<table class="sheet"><tbody>',
                f'<tr><th class="title" rowspan="2">FOB — {name}</th>'
                + ''.join(f'<th class="sub{" gl" if i == 0 else ""}">{c["label"]}</th>' for i, c in enumerate(corridors))
                + '<th class="sub gl">Best</th></tr>',
                '<tr>' + ''.join(f'<td class="bidrow{" gl" if i == 0 else ""}">{c["bid"](m)}</td>' for i, c in enumerate(corridors))
                + '<td class="bidrow gl">bid</td></tr>']
        rows_n = 0
        for state in states_all:
            vals = [c["fob"](state, m) if state in c["states"] else None for c in corridors]
            if all(v is None for v in vals):
                continue
            rows_n += 1
            ranked = [v for v, c in zip(vals, corridors) if v is not None and not c.get("benchmark")]
            top = max(ranked) if ranked else None
            best_labels = [corridors[i]["label"] for i, v in enumerate(vals)
                           if v is not None and top is not None and v == top and not corridors[i].get("benchmark")]
            tds = []
            for i, v in enumerate(vals):
                txt, neg = _bn_fob_cell(v)
                tds.append(f'<td class="fobv{neg}{" divide" if v is not None and v == top and len(ranked) > 1 and not corridors[i].get("benchmark") else ""}'
                           f'{" gl" if i == 0 else ""}">{txt}</td>')
            html.append(f'<tr><td class="lbl">{state}</td>' + ''.join(tds) + f'<td class="fobv gl">{" / ".join(best_labels) or "—"}</td></tr>')
        html.append('</tbody></table>')
        table_html = ''.join(html)
        if rows_n:
            st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
            _table_actions(table_html, f"state_fob_summary_{name.lower()}.png")
        else:
            st.caption(f"**{name}** — no corridor has a bid for this month yet.")
    st.markdown('<div class="legend">¢/bu, bid − freight, negatives in parentheses; the yellow row is each corridor\'s bid for the month '
                '(CN: the CIF NOLA price). * = not posted as that month on its own: a Split / FH+LH month, or the package that covers it '
                '(JFM for Jan-Mar, AMJJ for Apr-Jul, ...). Shaded = the best corridor for that state. — = no bid for that month on that '
                'corridor, or no origin in the state. ' + " ".join(notes) + '</div>', unsafe_allow_html=True)


bids_tab, summary_tab, state_tab, csx_tab, ns_tab, bn_tab, cn_tab, up_tab, map_tab, ship_tab, refs_tab, carry_tab = st.tabs(
    ["📋 Bids", "📊 State Summary", "📍 State Level", "CSX", "NS", "BN", "CN", "UP", "🗺️ Map", "📦 Shipments", "🔗 References", "💵 Net Carry"])
_diesel_weekly = _bn_auto_fsc()[1]

with bids_tab:
    st.markdown("### Manual Rail Corridors (chat-fed)")
    _manual_date = _sheet_board("manual", MANUAL_SECTIONS, "man", other_keep=set())

with summary_tab:
    _summary_tab(_manual_date)

with state_tab:
    _state_level_tab(_manual_date)

with csx_tab:
    _csx_tab(_manual_date)
    REF.render("CSX", _diesel_weekly)

with ns_tab:
    _ns_tab(_manual_date)
    REF.render("NS", _diesel_weekly)

with bn_tab:
    _bn_tab(_manual_date)
    REF.render("BN", _diesel_weekly)

with cn_tab:
    _cn_tab(_manual_date)
    REF.render("CN", _diesel_weekly)

with up_tab:
    _up_tab(_manual_date)
    REF.render("UP", _diesel_weekly)

with map_tab:
    _map_tab()

with refs_tab:
    _references_tab()

with ship_tab:
    _shipments_tab()

# The railroad logos on tabs 3-6 are CSS-keyed to tab position (see the style block): a new tab shifts them.
with carry_tab:
    _netcarry_tab()

_render_disclaimer()
