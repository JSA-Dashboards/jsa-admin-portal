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
import base64
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).parent))

import streamlit as st
import streamlit.components.v1 as components

import freight_data as FD
import rail_data as RD
import river_data as RVD
# Renamed on disk (rail_corridors.py -> railfob_rail_corridors.py) for the JSA
# Admin Portal merge: basis_tracker has its OWN same-named module, and
# Python's sys.modules cache would silently hand one page's import to the
# other page once either had loaded first in this shared process.
from railfob_rail_corridors import MANUAL_SECTIONS, RAIL_DISPLAY, RAIL_COLORS

# Local .env, optional (Streamlit Cloud uses st.secrets instead).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    pass

try:
    for _secret_key in ("BASIS_DATABASE_URL", "RIVER_DATABASE_URL"):
        if _secret_key in st.secrets and not os.environ.get(_secret_key):
            os.environ[_secret_key] = st.secrets[_secret_key]
except Exception:
    pass  # st.secrets unavailable locally — fine, .env covers it

# st.set_page_config removed — the JSA Admin Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.


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

      /* Hide Streamlit's menu — NOT the header itself: the JSA Admin Portal
         shell's top nav (page switcher) lives inside stHeader, so hiding it
         would strand every page with no way to navigate elsewhere. */
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
         (Bids, CSX, NS, BN, CN, Map, References). */
      [role="tab"] p {{ display: flex; align-items: center; gap: 6px; }}
      [role="tab"]:nth-of-type(2) p::before {{
        content: ""; display: inline-block; width: 26px; height: 16px;
        background: url('{CSX_LOGO_URI}') no-repeat center / contain;
      }}
      [role="tab"]:nth-of-type(3) p::before {{
        content: ""; display: inline-block; width: 26px; height: 16px;
        background: url('{NS_LOGO_URI}') no-repeat center / contain;
      }}
      [role="tab"]:nth-of-type(4) p::before {{
        content: ""; display: inline-block; width: 26px; height: 16px;
        background: url('{BNSF_LOGO_URI}') no-repeat center / contain;
      }}
      [role="tab"]:nth-of-type(5) p::before {{
        content: ""; display: inline-block; width: 26px; height: 16px;
        background: url('{CN_LOGO_URI}') no-repeat center / contain;
      }}
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

if not RD.configured():
    st.warning(
        "BASIS_DATABASE_URL isn't set, so this portal can't reach the basis "
        "tracker's archive yet. Add it to `.env` locally or as a Streamlit "
        "secret to see live data."
    )
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


def _fob_cell(v, better=False):
    if v is None:
        return '<td>—</td>'
    cls = ' class="better"' if better else ''
    return f'<td{cls}>{v:+.1f}</td>'


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
    return f'<td{cls}>{round(v):+d}</td>'


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
    variant, ¢/bu = bid − freight."""
    vals = []
    for label, cells, frt in variants:
        row = [None if cells.get(p, {}).get("bid") is None else cells[p]["bid"] - frt
               for p in periods]
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
    """Best (highest) FOB among the given origins, for one corridor/region, per period."""
    out = []
    for p in periods:
        bid = cells.get(p, {}).get("bid")
        if bid is None:
            out.append(None)
            continue
        best = None
        for o in origins:
            v = bid - o[field]
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
            cells = ''.join(f'<td>{round(v):+d}</td>' if v is not None else '<td>—</td>' for v in vals)
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
    st.markdown("### Rail FOB — CSX")
    _raw_corridor_table([m for m, _ in active_markets], sel_date)

    st.markdown("### FOB Index by State")
    variant_fields = ([("Columbus", "columbus_cpb")] if show_col else []) + \
                      ([("Evansville", "eville_altkyla_cpb")] if show_evv else [])
    bid_cells_map = {"Columbus": col_cells, "Evansville": evv_cells}
    _state_fob_table(rows, variant_fields, bid_cells_map, periods, per_variant=True,
                      name="csx_state_index")

    st.markdown("### Highlighted Origins")
    if asof_bits:
        st.caption(" · ".join(asof_bits))
    highlighted = [r for r in rows if r["highlighted"]]
    if periods and highlighted:
        ncols = 1 + len(periods)
        html = _origin_table_open(periods, ncols)
        flagged = []
        for r in highlighted:
            variants = []
            if show_col:
                variants.append(("Columbus", col_cells, r["columbus_cpb"]))
            if show_evv:
                variants.append(("Evansville", evv_cells, r["eville_altkyla_cpb"]))
                if r["eville_altkyla"] != r["eville_gafl"]:
                    flagged.append((_location_only(r["buying_station"]), r["eville_gafl_cpb"], r["eville_altkyla_cpb"]))
            star = " *" if show_evv and r["eville_altkyla"] != r["eville_gafl"] else ""
            frt_desc = " / ".join(f"{lbl} {v:.1f}¢" for lbl, _, v in variants)
            html.append(
                f'<tr class="origin-hdr"><td colspan="{ncols}">{r["state"]} · {_location_only(r["buying_station"])}'
                f'<span class="fut-sub"> &nbsp;freight {frt_desc}{star}</span></td></tr>'
            )
            html.extend(_fob_variant_rows(variants, periods))
        html.append('</tbody></table>')
        table_html = ''.join(html)
        st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
        _table_actions(table_html, "csx_highlighted_origins.png")
        if flagged:
            notes = "; ".join(f"{n} (GA/FL {g:+.1f}¢ vs AL/TN/KY/LA {a:+.1f}¢ used)"
                               for n, g, a in flagged)
            st.caption(f"* Evansville's rate depends on the unit train's downstream "
                       f"market — {notes}.")
    else:
        st.caption("No CSX Columbus/Evansville postings on or before this date yet.")

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
        '<div class="legend">FOB(origin) = bid − rail freight to that buying station '
        '(¢/bu = $/car ÷ 3500 bu/car × 100). Freight is a static reference rate from the '
        'CSX origin-spread workbook — only the bid side is live/archived. Highlighted = '
        'the origins starred in that workbook; <span class="sw bt"></span>blue = the '
        'better-netback corridor for that origin/period.</div>',
        unsafe_allow_html=True,
    )


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
    rows = FD.load_ns()

    ftw_cells, ftw_eff = _bid_cells_for("manual", FD.NS_BID_MARKET, sel_date)
    periods = _period_union(ftw_cells)

    st.markdown("### Rail FOB — NS")
    _raw_corridor_table([FD.NS_BID_MARKET], sel_date)

    st.markdown("### FOB Index by State")
    variant_fields = [(region, field + "_cpb") for region, field in active]
    bid_cells_map = {region: ftw_cells for region, _ in active}
    _state_fob_table(rows, variant_fields, bid_cells_map, periods, name="ns_state_index")

    st.markdown("### Highlighted Origins")
    if ftw_eff and ftw_eff != sel_date:
        st.caption(f"{FD.NS_BID_MARKET} as of {ftw_eff}")
    highlighted = [r for r in rows if r["highlighted"]]
    if periods and highlighted:
        ncols = 1 + len(periods)
        html = _origin_table_open(periods, ncols)
        for r in highlighted:
            variants = [(region, ftw_cells, r[f"{field}_cpb"]) for region, field in active]
            # All three regions net against the SAME NS Ft Wayne bid, so the
            # cheapest-freight region is the best one for every period, not
            # just some — default to showing just that one row, not all 3.
            best = min(variants, key=lambda v: v[2])
            frt_desc = f"{best[0]} {best[2]:.1f}¢"
            flag = ' <span class="fut-sub">(105-car eligible)</span>' if r["flag_105"] else ""
            html.append(
                f'<tr class="origin-hdr"><td colspan="{ncols}">{r["state"]} · {r["origin"]}'
                f'<span class="fut-sub"> &nbsp;best freight {frt_desc}</span>{flag}</td></tr>'
            )
            html.extend(_fob_variant_rows([best], periods))
        html.append('</tbody></table>')
        table_html = ''.join(html)
        st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
        _table_actions(table_html, "ns_highlighted_origins.png")
    else:
        st.caption(f"No {FD.NS_BID_MARKET} postings on or before this date yet.")

    with st.expander(f"All NS origins, ranked by freight spread ({len(rows)} total)"):
        _expanded_freight_table(
            rows, state_key="state",
            label_cols=[("Origin", lambda r: r["origin"]),
                        ("105-car", lambda r: "Y" if r["flag_105"] else "")],
            variants=[(region, field + "_cpb", show[field]) for region, field in FD.NS_REGIONS.items()],
            name="ns_all_origins",
        )

    st.markdown(
        '<div class="legend">FOB(origin) = bid at NS Ft Wayne − rail freight (¢/bu, '
        'already $/bu in the source workbook × 100). GA / NC-SC-VA / East are three '
        'published through-rate variants against the same physical move, all pricing '
        'off the same bid — so Highlighted Origins defaults to just the cheapest-freight '
        'region among whichever are checked above, not all three; see the expander below '
        'to compare regions side by side.</div>',
        unsafe_allow_html=True,
    )


_BN_TARGET_MONTHS = ("Aug", "Sep", "Oct", "Nov")


def _bn_sibling_bid(cells, *labels):
    """First matching period's bid among the given exact labels
    (case-insensitive) — None if that period isn't posted or has no bid."""
    by_lower = {p.lower(): c for p, c in cells.items()}
    for lbl in labels:
        c = by_lower.get(lbl.lower())
        if c and c.get("bid") is not None:
            return c["bid"]
    return None


def _bn_infer_month_bid(cells, month):
    """Best-effort bid for one of Aug/Sep/Oct/Nov when it wasn't posted as
    its own literal period that day, from whatever partial pieces WERE
    posted (Kolten's call, 2026-08-26 — only bother for these 4 "big"
    months, not every smaller package). Display-only for FOB purposes —
    never writes back to the archive, and the raw Rail FOB grid still shows
    only what was literally posted. Tries, in order:
      1. FH/LH <month> averaged (or whichever one exists, if only one does)
      2. Split <month>, treated the same as a literal posting
      3. for Oct/Nov only: the OND package (Oct/Nov/Dec combined) — used
         directly for Oct, or reverse-averaged against Oct for Nov
         (assuming OND = (Oct+Nov+Dec)/3 and Nov≈Dec) when Oct is otherwise
         known; a straight OND substitution if Oct isn't known either."""
    direct = _bn_sibling_bid(cells, month)
    if direct is not None:
        return direct
    fh = _bn_sibling_bid(cells, f"FH {month}")
    lh = _bn_sibling_bid(cells, f"LH {month}")
    if fh is not None and lh is not None:
        return (fh + lh) / 2
    if fh is not None:
        return fh
    if lh is not None:
        return lh
    split = _bn_sibling_bid(cells, f"Split {month}")
    if split is not None:
        return split
    if month in ("Oct", "Nov"):
        ond = _bn_sibling_bid(cells, "OND", "LH OND", "FH OND")
        if ond is not None:
            if month == "Oct":
                return ond
            oct_val = _bn_infer_month_bid(cells, "Oct")
            if oct_val is not None and oct_val != ond:
                return (3 * ond - oct_val) / 2
            return ond
    return None


def _bn_effective_bid(cells, period):
    """The literal bid if posted, else a best-effort inferred value — but
    only for the 4 target months (Aug/Sep/Oct/Nov); every other period
    (FH Sep, Split Nov, OND, JFM, ...) stays exactly as posted, blank if
    it wasn't."""
    direct = cells.get(period, {}).get("bid")
    if direct is not None:
        return direct
    p = period.strip()
    if p.title() in _BN_TARGET_MONTHS:
        return _bn_infer_month_bid(cells, p.title())
    return None


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


def _bn_state_best_row(origins, cells, field, periods):
    out = []
    for p in periods:
        bid = _bn_effective_bid(cells, p)
        if bid is None:
            out.append(None)
            continue
        best = None
        for o in origins:
            frt = FD.bn_freight_cpb(o[field], p)
            if frt is None:
                continue
            v = bid - frt
            if best is None or v > best:
                best = v
        out.append(best)
    return out


def _bn_tab(sel_date):
    st.caption(f"Posting date **{sel_date}** — change it on the 📋 Bids tab.")
    fc, fe = st.columns(2)
    show = {}
    for (dest, spec), c in zip(FD.BN_DESTINATIONS.items(), (fc, fe)):
        show[dest] = c.checkbox(dest, value=True, key=f"bn_f_{spec['field']}")
    active = [(dest, spec) for dest, spec in FD.BN_DESTINATIONS.items() if show[dest]]
    if not active:
        st.info("Select at least one destination to filter on.")
        return
    rows = FD.load_bn()
    published_months = sorted({m for r in rows for spec in FD.BN_DESTINATIONS.values()
                                for m in r[spec["field"] + "_cpb"]}, key=FD.bn_month_sort_key)
    published_disp = "/".join(m.upper() if m == "jj" else m.title() for m in published_months)

    cells_by_dest, eff_by_dest = {}, {}
    for dest, spec in active:
        cells_by_dest[dest], eff_by_dest[dest] = _bid_cells_for("manual", spec["market"], sel_date)
    periods = _period_union(*cells_by_dest.values())
    asof_bits = [f"{dest} as of {eff_by_dest[dest]}" for dest, _ in active
                 if eff_by_dest[dest] and eff_by_dest[dest] != sel_date]

    st.markdown("### Rail FOB — BN")
    _raw_corridor_table([spec["market"] for _, spec in active], sel_date)

    st.markdown("### FOB Index by State")
    index_periods = list(_BN_TARGET_MONTHS)
    if any(cells_by_dest.values()):
        by_state = {}
        for r in rows:
            by_state.setdefault(r["state"], []).append(r)
        ncols = 1 + len(index_periods)
        html = ['<table class="sheet"><tbody><tr>', '<th class="lblhdr">State</th>']
        html += [f'<th>{p}</th>' for p in index_periods]
        html.append('</tr>')
        for s in sorted(by_state):
            origins = by_state[s]
            label_rows = [(dest, _bn_state_best_row(origins, cells_by_dest[dest], spec["field"] + "_cpb", index_periods))
                          for dest, spec in active]
            html.append(f'<tr class="origin-hdr"><td colspan="{ncols}">{s}</td></tr>')
            html.extend(_variant_value_rows(label_rows, cell_fn=_fob_cell_int))
        html.append('</tbody></table>')
        table_html = ''.join(html)
        st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
        _table_actions(table_html, "bn_state_index.png")
        st.caption("Best (highest) FOB among every origin in that state, per destination, per "
                   "one of the 4 clean months — FH/LH splits and packages (Split Nov, OND, "
                   "etc.) are folded into these columns rather than listed separately (see "
                   "the Rail FOB and BN Origins tables above/below for every period exactly "
                   f"as posted). Blue = the better destination. Only periods whose first "
                   f"named month is currently published ({published_disp}) show a value.")

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
        '$/car ÷ 4000 bu/car × 100). Unlike CSX/NS, BN publishes rates for a rolling ~4-month '
        f'window rather than one flat number — currently <b>{published_disp}</b> — a period '
        'nets against freight only when its first named month falls in that window; '
        'everything else shows "—" until the workbook rolls forward (re-run the extraction '
        'against a freshly saved copy to pick up the new months). For the Aug/Sep/Oct/Nov '
        'columns specifically, a bid not posted that literal day is filled in best-effort '
        'from whatever partial pieces WERE posted — FH+LH averaged, a Split-month quote used '
        'directly, or (for Oct/Nov) the OND package, reverse-averaged against Oct when Oct is '
        'known — before falling back to "—"; every other, smaller period (FH Sep, Split Nov, '
        'OND itself, JFM, ...) is shown exactly as posted, no inference. All 11 BN origins are '
        'shown (the workbook has no separate highlighted subset for this railroad). Blue = '
        'the better destination for that origin/period.</div>',
        unsafe_allow_html=True,
    )


_CN_LETTER = {v: k[-1].upper() for k, v in FD.CN_RATE_FIELD.items()}


def _cn_tab():
    st.caption("Raw CN Gulf Export tariff rates (Supplement 41 to Tariff CN 004050-A8), plus "
               "a FOB netback against CIF NOLA from the River FOB Portal — CN's freight "
               "doesn't net against a rail_fob bid market like CSX/NS/BN do, since this "
               "corridor is entirely about moving grain to the Gulf for export.")

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
        return f'<td>{v:,.0f}{mark}<br><span class="fut-sub">{cpb:.1f}¢/bu</span></td>'

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
    st.caption(f"{len(filtered)} of {len(rows)} rate rows shown (\\$/car, with the {commodity.lower()} "
               f"¢/bu equivalent below each — {FD.CN_LB_PER_BU[commodity]} lb/bu). All rows currently "
               "go to Gulf Exports Group — multiple rows per origin are different volume "
               "tiers, not different destinations. (C) = tariff-flagged as recently changed. "
               "⇄ recip. switch = this rate includes a reciprocal switch at origin (up to "
               "\\$139/car) — most rows exclude it, this just flags the ones that don't.")

    with st.expander("Note codes"):
        st.markdown(
            "  \n".join(f"**{k}** — {v}" for k, v in FD.CN_NOTES.items())
        )

    st.markdown(f"### {commodity} FOB by Origin")
    if not RVD.configured():
        st.info("RIVER_DATABASE_URL isn't set, so this can't reach the River FOB Portal's "
                 "CIF NOLA archive yet. Add it to `.env` locally or as a Streamlit secret.")
        return
    as_of, cif = RVD.latest_cif(commodity)
    if not as_of or not cif:
        st.caption(f"No {commodity} CIF NOLA history found in the River FOB Portal's archive yet.")
        return
    months = sorted(cif, key=RVD.month_sort_key)

    ncols = 1 + len(months)
    html = _origin_table_open(months, ncols)
    for r in filtered:
        variants = [(f"{size} · {source}", FD.cn_freight_cpb(r[field], size, commodity))
                    for size, source, field in active_cols]
        label_rows = [(lbl, [None if cif.get(m) is None else cif[m] - frt for m in months])
                      for lbl, frt in variants]
        switch_mark = ' <span class="fut-sub">⇄ recip. switch</span>' if r["switch"] else ''
        html.append(
            f'<tr class="origin-hdr"><td colspan="{ncols}">{r["state"]} · {r["origin"]}'
            f'<span class="fut-sub"> &nbsp;{r["tier"] or r["notes"] or ""}</span>{switch_mark}</td></tr>'
        )
        html.extend(_variant_value_rows(label_rows))
    html.append('</tbody></table>')
    table_html = ''.join(html)
    st.markdown(_card_open() + table_html + _card_close(), unsafe_allow_html=True)
    _table_actions(table_html, "cn_fob.png")
    bpc = FD.CN_BU_PER_CAR[commodity]
    soy_note = (' (derived from the same car\'s weight capacity as corn, ÷60 lb/bu instead of 56)'
                if commodity == "Soybeans" else '')
    st.markdown(
        f'<div class="legend">FOB(origin) = {commodity} CIF NOLA (as of {as_of}, River FOB '
        'Portal) − rail freight (¢/bu = $/car ÷ bu/car). Bu/car is by car SIZE only — '
        f'{bpc["Small"]:,} bu for Small (≤5149 ft³), {bpc["Large"]:,} bu for Large '
        f'(>5149 ft³){soy_note} — railroad- vs private-supplied doesn\'t change how many '
        'bushels physically fit. One column per CIF delivery month currently archived; blue = '
        'the better car size/source for that origin/month.</div>',
        unsafe_allow_html=True,
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
        cells += [f'<td>{r[f]:+.1f}</td>' for _, f in active]
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
    st.markdown("### CN Rail Network Map")
    st.caption("Live embed of CN's GeoMapGuide. If it doesn't load (some networks block "
               "third-party embeds), use the link below to open it directly.")
    components.iframe("https://cnebusiness.geomapguide.ca/", height=750, scrolling=True)
    st.markdown(
        '<div style="margin-top:8px">'
        '<a href="https://cnebusiness.geomapguide.ca/" target="_blank" '
        'style="color:#0693e3;font-weight:600">Open CN GeoMapGuide in a new tab ↗</a>'
        '</div>',
        unsafe_allow_html=True,
    )


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


bids_tab, csx_tab, ns_tab, bn_tab, cn_tab, map_tab, refs_tab = st.tabs(
    ["📋 Bids", "CSX", "NS", "BN", "CN", "🗺️ Map", "🔗 References"])

with bids_tab:
    st.markdown("### Manual Rail Corridors (chat-fed)")
    _manual_date = _sheet_board("manual", MANUAL_SECTIONS, "man", other_keep=set())

with csx_tab:
    _csx_tab(_manual_date)

with ns_tab:
    _ns_tab(_manual_date)

with bn_tab:
    _bn_tab(_manual_date)

with cn_tab:
    _cn_tab()

with map_tab:
    _map_tab()

with refs_tab:
    _references_tab()
