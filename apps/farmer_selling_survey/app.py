"""
Farmer Selling Survey Dashboard
Share of the crop farmers report sold, by crop year: current-crop and new-crop forward sales
for corn, soybeans and HRW / SRW / HRS wheat.

John Stewart & Associates
Data: Snowflake JSA.FARMER_SURVEY (seeded from the Farmer Selling Survey workbook, extended monthly
from the Admin tab); falls back to data/*.csv when no Snowflake credentials are set.
Visual language follows the CFTC COT dashboard (sage palette, tiles, uppercase section headers,
50-year watermark on charts and tables).
"""
import sys as _sys  # portal-sync: sibling imports resolve to this folder
from pathlib import Path as _Path  # portal-sync
_sys.path.insert(0, str(_Path(__file__).parent))  # portal-sync
import base64
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import fs_db as db
from fs_loader import MONTHS, BLOCKS, load_workbook_tables

pass  # portal-sync: st.set_page_config removed (Home.py makes the one call allowed per run)

# -- palette (matches cftc-cot-dashboard) -------------------------------------
JSA_GREEN = "#5e7164"
DM_BG, DM_SURFACE, DM_BORDER = "#f6f8f7", "#ffffff", "#d7e2dc"
DM_TEXT, DM_MUTED = "#32373c", "#5f7267"
COL_POS, COL_NEG = "#16a34a", "#dc2626"
YEAR_COLORS = ["#b8c4bc", "#6fa8c4", "#c4785a", JSA_GREEN]  # oldest -> newest

START = {c: m for c, m in BLOCKS.values()}  # marketing-year start month
COMMODITIES = list(START)

HERE = Path(__file__).parent
WATERMARK = HERE / "assets" / "logo-50yr.png"
WATERMARK_OPACITY = 0.10


@st.cache_data(show_spinner=False)
def watermark_uri() -> str | None:
    try:
        return "data:image/png;base64," + base64.b64encode(WATERMARK.read_bytes()).decode()
    except OSError:
        return None


AXIS = dict(gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
            tickfont=dict(color=DM_MUTED, size=11), title_font=dict(color=DM_MUTED, size=11), zeroline=False)

_wm = watermark_uri()
# The dataframe grid paints on an opaque canvas, so the mark is overlaid (pointer-events:none).
table_wm_css = (f"""
[class*="st-key-tablewrap_"] {{ position: relative; }}
[class*="st-key-tablewrap_"]::after {{
  content: ""; position: absolute; inset: 0; pointer-events: none; z-index: 5;
  background-image: url('{_wm}'); background-repeat: no-repeat; background-position: center center;
  background-size: min(34%, 260px); opacity: {WATERMARK_OPACITY};
}}""" if _wm else "")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&family=Source+Sans+3:wght@400;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"] {{ background-color:{DM_BG}; color:{DM_TEXT}; }}
html, body, p, span, div, label, button, td, th {{ font-family:'Source Sans 3','Source Sans Pro',sans-serif; }}
.block-container {{ padding-top: 3.2rem; max-width: 1400px; }}
.dash-header {{ display:flex; align-items:center; gap:18px; padding-bottom:10px;
    border-bottom:1px solid {DM_BORDER}; margin-bottom:14px; }}
.dash-header img {{ height:40px; }}
.dash-header .t b {{ font-family:'EB Garamond',Georgia,serif; font-size:1.7rem; color:{DM_TEXT}; font-weight:600; }}
.dash-header .t div {{ font-size:.85rem; color:{DM_MUTED}; }}
@media (max-width: 640px) {{ .dash-header img {{ display:none; }} }}
.tile {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-top:3px solid {JSA_GREEN};
    border-radius:10px; padding:16px 20px; text-align:center; height:100%; }}
.tile-label {{ color:{DM_MUTED}; font-size:0.68rem; text-transform:uppercase; letter-spacing:0.09em; margin-bottom:6px; }}
.tile-value {{ color:{DM_TEXT}; font-size:1.8rem; font-weight:700; line-height:1.1; }}
.tile-sub {{ color:{DM_MUTED}; font-size:0.72rem; margin-top:5px; }}
.tile-value.up {{ color:{COL_POS}; }} .tile-value.down {{ color:{COL_NEG}; }}
.sec-header {{ color:{DM_MUTED}; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.1em;
    padding:10px 0 4px; border-bottom:1px solid {DM_BORDER}; margin-bottom:12px; }}
.asof {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-radius:8px; padding:10px 16px;
    color:{DM_MUTED}; font-size:0.82rem; margin-bottom:12px; }}
.asof b {{ color:{DM_TEXT}; }}
.cy-card {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-top:3px solid {JSA_GREEN};
    border-radius:10px; padding:14px 16px; }}
.cy-row {{ color:{DM_TEXT}; font-size:1.05rem; padding:3px 0; }}
.cy-row.cy-new {{ font-weight:700; font-size:1.2rem; }}
.sum-wrap {{ background:{DM_SURFACE}; border:1px solid {DM_BORDER}; border-top:3px solid {JSA_GREEN};
    border-radius:10px; padding:6px 12px; overflow-x:auto; }}
table.sum {{ width:100%; border-collapse:collapse; font-size:0.95rem; }}
table.sum th {{ color:{DM_MUTED}; font-size:0.68rem; text-transform:uppercase; letter-spacing:0.09em;
    text-align:left; padding:10px 8px; border-bottom:1px solid {DM_BORDER}; font-weight:600; }}
table.sum td {{ padding:11px 8px; border-bottom:1px solid {DM_BORDER}; color:{DM_TEXT}; }}
table.sum tr:last-child td {{ border-bottom:none; }}
table.sum .num {{ text-align:right; white-space:nowrap; }}
table.sum td.big {{ font-size:1.25rem; font-weight:700; }}
table.sum td.up {{ color:{COL_POS}; font-weight:600; }} table.sum td.down {{ color:{COL_NEG}; font-weight:600; }}
hr {{ border-color:{DM_BORDER}; }}
{table_wm_css}
#MainMenu, footer {{ visibility:hidden; }}
.stDeployButton {{ display:none; }}
</style>
<div class="dash-header">
  <img src="https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png">
  <div class="t"><b>Farmer selling survey</b>
  <div>Share of the crop sold, by crop year &middot; John Stewart &amp; Associates</div></div>
</div>
""", unsafe_allow_html=True)


# -- helpers --------------------------------------------------------------------
def sec(text: str):
    st.markdown(f'<div class="sec-header">{text}</div>', unsafe_allow_html=True)


def tile(lbl, value, sub="", cls=""):
    return (f'<div class="tile"><div class="tile-label">{lbl}</div>'
            f'<div class="tile-value {cls}">{value}</div><div class="tile-sub">{sub}</div></div>')


def pts(v):
    return f"{v:+.0f} pts", ("up" if v > 0 else "down" if v < 0 else "")


def year_color(cy, years):
    n = len(years)
    return YEAR_COLORS[-(n - years.index(cy))] if n <= len(YEAR_COLORS) else YEAR_COLORS[-1]


def style_fig(fig, height=400, title=None):
    wm = watermark_uri()
    if wm:
        fig.add_layout_image(dict(source=wm, xref="paper", yref="paper", x=0.5, y=0.5, sizex=0.5, sizey=0.5,
                                  xanchor="center", yanchor="middle", sizing="contain",
                                  opacity=WATERMARK_OPACITY, layer="below"))
    if title:
        fig.update_layout(title=dict(text=title, x=0.5, xanchor="center", y=0.97,
                                     font=dict(size=22, color=DM_TEXT, family="EB Garamond, Georgia, serif")))
    fig.update_layout(height=height, margin=dict(l=60, r=20, t=90 if title else 10, b=50), paper_bgcolor=DM_SURFACE,
                      plot_bgcolor=DM_SURFACE, hovermode="x unified",
                      legend=dict(orientation="h", y=1.06 if title else 1.12, x=0.5 if title else 0,
                                  xanchor="center" if title else "left", font=dict(size=12, color=DM_MUTED)),
                      xaxis={**AXIS, "automargin": True, "tickfont": dict(color=DM_TEXT, size=13)},
                      yaxis={**AXIS, "automargin": True, "title": "% sold", "range": [0, 100], "ticksuffix": "%",
                             "tickfont": dict(color=DM_TEXT, size=13)})
    return fig


def show_table(df, key, **kw):
    with st.container(key=f"tablewrap_{key}"):
        st.dataframe(df, width="stretch", **kw)


@st.cache_data(show_spinner=False)
def load_upload(data: bytes):
    import io
    return load_workbook_tables(io.BytesIO(data))


def crop_years(com, now):
    """(current, new) crop-year labels for a commodity as of `now`, from its marketing-year start month."""
    y = now.year if now.month >= START[com] else now.year - 1
    fmt = lambda a: "%02d/%02d" % (a % 100, (a + 1) % 100)
    return fmt(y), fmt(y + 1)


SURVEY_COMMODITIES = ["Corn", "Soybeans"]
BUCKETS = [(0, 5)] + [(lo, lo + 4) for lo in range(6, 100, 5)]  # 0-5, 6-10, ..., 96-100
BUCKET_LABELS = ["%d-%d%%" % b for b in BUCKETS]
LOCATIONS = ["Illinois", "Indiana", "Iowa", "Kansas", "Michigan", "Minnesota", "Missouri", "Nebraska", "North Dakota",
             "Ohio", "South Dakota", "Wisconsin", "Other US state", "Canada", "Other"]
SURVEY_QUESTIONS = {
    "Corn": ("Based on your anticipated take of corn (included fall take, to arrive, direct positions, etc) "
             "what % sales has the farmer made for the {cy} crop year?",
             "What is the next price target for New Crop Corn (Basis Nearby Futures)? (Buys the next 5%)"),
    "Soybeans": ("Based on your anticipated take of soybeans (included fall take, to arrive, direct positions, etc) "
                 "what % sales has the farmer made for the {cy} crop year?",
                 "What is the next futures price point target (Basis Nearby Futures)? (Buys the next 5%)"),
}


def bucket_label(pct):
    """The 5% range label that contains a percent (e.g. 28 -> '26-30%')."""
    pct = max(0, min(100, round(pct)))
    return next(lbl for (lo, hi), lbl in zip(BUCKETS, BUCKET_LABELS) if lo <= pct <= hi)


def summarize(resp):
    """Per commodity: responses, average sold % (range midpoints), most common range, average price target."""
    out = {}
    for com in SURVEY_COMMODITIES:
        r = resp[(resp.commodity == com) & resp.pct_lo.notna()] if len(resp) else resp
        if not len(r):
            continue
        mid = (r.pct_lo + r.pct_hi) / 2
        counts = r.assign(lbl=r.pct_lo.astype(int).astype(str) + "-" + r.pct_hi.astype(int).astype(str) + "%") \
            .lbl.value_counts()
        tg = r.price_target.dropna()
        out[com] = dict(n=len(r), avg=float(mid.mean()), top=counts.index[0], counts=counts,
                        target=float(tg.mean()) if len(tg) else None, crop_year=r.crop_year.iloc[0])
    return out


def results_panel(resp, title):
    """Result cards + a range distribution chart per commodity (also shown to respondents right after submitting)."""
    s = summarize(resp)
    if not s:
        st.info("No responses yet for this month.")
        return
    sec(title)
    cols = st.columns(len(s))
    for col, (com, d) in zip(cols, s.items()):
        tgt = "&ndash;" if d["target"] is None else "%.2f" % d["target"]
        col.markdown(tile("%s %s sold" % (com, d["crop_year"]), bucket_label(d["avg"]),
                          "average of %d responses &middot; price target %s" % (d["n"], tgt)), unsafe_allow_html=True)
    for com, d in s.items():
        counts = d["counts"].reindex(BUCKET_LABELS).fillna(0)
        counts = counts.loc[counts.cumsum().gt(0) & counts[::-1].cumsum()[::-1].gt(0)]
        fig = go.Figure(go.Bar(x=counts.index, y=counts.values, marker_color=JSA_GREEN))
        style_fig(fig, height=260, title="%s: how much has the farmer sold?" % com)
        fig.update_layout(hovermode="closest", showlegend=False)
        fig.update_yaxes(title="responses", range=None, ticksuffix="", dtick=1)
        st.plotly_chart(fig, width="stretch", theme=None)


def shared_code():
    try:
        return str(st.secrets.get("SURVEY_CODE", "")).strip()
    except Exception:
        return ""


def survey_page():
    """Public anonymous monthly survey (?survey=1): optional shared code, then the poll; results show on submit."""
    st.markdown("<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'] {display:none}</style>",
                unsafe_allow_html=True)
    sec("JSA monthly farmer selling survey")
    if not db.configured():
        st.error("The survey is not available right now. Please try again later.")
        return
    ss = st.session_state
    code = shared_code()
    if code and not ss.get("svy_ok"):
        entered = st.text_input("Access code", key="svy_code", max_chars=24)
        if st.button("Continue", type="primary"):
            if entered.strip().lower() == code.lower():
                ss["svy_ok"] = True
                st.rerun()
            st.error("That code was not recognised.")
        return
    now = pd.Timestamp.now(tz="America/Chicago")
    month_key = now.strftime("%Y-%m")
    st.caption("All responses are completely anonymous. Instant results are shown once you submit.")
    for line in recap_lines(now):
        st.markdown(line)
    if ss.get("svy_done") == month_key:
        st.success("Thank you! Your answers are in. Here are the results so far this month:")
        results_panel(db.load_survey_responses(month_key), "Results so far, %s %d" % (MONTHS[now.month - 1], now.year))
        return
    entries = []
    with st.form("svy_form"):
        for com in SURVEY_COMMODITIES:
            cy = crop_years(com, now)[0]
            q_pct, q_price = SURVEY_QUESTIONS[com]
            st.markdown("**%s**" % com)
            pct = st.selectbox(q_pct.format(cy=cy), BUCKET_LABELS, index=None, placeholder="Choose a range",
                               key="svy_pct_" + com)
            price = st.number_input(q_price, min_value=0.0, step=0.05, value=None, format="%.2f",
                                    placeholder="Price, e.g. 5.55", key="svy_price_" + com)
            entries.append((com, cy, pct, price))
        loc = st.selectbox("Where are you located?", LOCATIONS, index=None, placeholder="Choose one", key="svy_loc")
        sent = st.form_submit_button("Submit", type="primary")
    if sent:
        answered = [e for e in entries if e[2] is not None]
        if not answered:
            st.warning("Please answer at least one % sold question.")
        else:
            rows = [(com, cy, BUCKETS[BUCKET_LABELS.index(pct)][0], BUCKETS[BUCKET_LABELS.index(pct)][1], price, loc)
                    for com, cy, pct, price in answered]
            db.save_survey_response(month_key, rows)
            ss["svy_done"] = month_key
            st.rerun()


def month_stats(mk):
    """{commodity: (average sold %, average price target)} for a survey month, from the saved responses."""
    try:
        s = summarize(db.load_survey_responses(mk))
    except Exception:
        return {}
    return {com: (d["avg"], d["target"]) for com, d in s.items()}


def recap_lines(now):
    """Last month's results, in the style of the survey email (with the change from the month before)."""
    prev, prev2 = [(now - pd.DateOffset(months=i)).strftime("%Y-%m") for i in (1, 2)]
    a, b = month_stats(prev), month_stats(prev2)
    mon = MONTHS[int(prev[5:]) - 1]
    mon2 = MONTHS[int(prev2[5:]) - 1]
    lines = []
    for com in SURVEY_COMMODITIES:
        if com not in a:
            continue
        pct, tgt = a[com]
        line = "**%s sales** %s" % (com, bucket_label(pct))
        if com in b:
            d_pct = round(pct - b[com][0])
            line += " (%s from %s)" % ("Flat" if d_pct == 0 else "%+d pts" % d_pct, mon2)
        if tgt is not None:
            line += " &nbsp;&middot;&nbsp; futures target %.2f" % tgt
            if com in b and b[com][1] is not None:
                d_c = round((tgt - b[com][1]) * 100)
                line += " (%s from %s)" % ("Flat" if d_c == 0 else "%+dc" % d_c, mon2)
        lines.append(line)
    return ["As a reminder, %s results showed:" % mon] + lines if lines else []


def survey_admin():
    """Admin: responses by month, the average roll-up (publish into the dashboard data), and the email recap."""
    sec("Client survey")
    if not db.configured():
        st.info("The client survey needs the Snowflake connection.")
        return
    now = pd.Timestamp.now(tz="America/Chicago")
    keys = [(now - pd.DateOffset(months=i)).strftime("%Y-%m") for i in range(12)]
    mk = st.selectbox("Survey month", keys, key="svy_admin_month")
    try:
        resp = db.load_survey_responses(mk)
    except Exception:
        st.warning("Survey table not found. Run sql/survey_responses.sql in Snowflake first.")
        return
    st.caption("Survey link: this app's address followed by `?survey=1`. Everyone uses the same access code, "
               "set as `SURVEY_CODE` in the app's secrets (leave it unset for an open link).")
    results_panel(resp, "Results, %s" % mk)
    s = summarize(resp)
    if s:
        if st.button("Publish averages to monthly data", icon=":material/publish:", key="svy_publish"):
            mon = MONTHS[int(mk[5:]) - 1]
            out = pd.DataFrame([(com, "current", d["crop_year"], mon, round(d["avg"])) for com, d in s.items()],
                               columns=["commodity", "kind", "crop_year", "month", "pct"])
            db.save_monthly(out)
            st.cache_data.clear()
            st.toast("Published %d value(s) for %s." % (len(out), mon), icon=":material/check:")
        with st.expander("Individual responses"):
            st.dataframe(resp.drop(columns=["response_id"]), hide_index=True, width="stretch")
    nxt = pd.Timestamp(int(mk[:4]), int(mk[5:]), 1, tz="America/Chicago") + pd.DateOffset(months=1)
    recap = recap_lines(nxt)
    if recap:
        st.markdown("**Recap lines for next month's email**")
        st.code("\n".join(l.replace("**", "").replace("&nbsp;&middot;&nbsp;", " |") for l in recap), language=None)


if st.query_params.get("survey"):
    survey_page()
    st.stop()

up = None if __import__("portal_view").is_client() else st.sidebar.file_uploader("Load a newer workbook (.xlsx)", type="xlsx",
                              help="Overrides the bundled data for this session only.")
surveys, monthly = load_upload(up.getvalue()) if up else (db.load_surveys(), db.load_monthly())

commodity = st.segmented_control("Commodity", COMMODITIES, default="Corn", key="commodity") or "Corn"
sm = START[commodity]
order = MONTHS[sm - 1:] + MONTHS[:sm - 1]
close = order[0] + " close"
mo = monthly[monthly.commodity == commodity]

tab_sum, tab_month, tab_data, tab_admin = __import__("portal_view").tabs(["Summary", "Monthly view", "Data", "Admin"], hide={"Admin"})


def snap_stats(com):
    """Latest current-crop % for one commodity vs last year / prior-year average, plus new-crop forward sales."""
    m = monthly[monthly.commodity == com]
    cur = m[m.kind == "current"]
    if cur.empty:
        return None
    s = START[com]
    ords = MONTHS[s - 1:] + MONTHS[:s - 1]
    ords = ords + [ords[0] + " close"]
    newest = max(cur.crop_year)
    mon = max(cur[cur.crop_year == newest].month, key=ords.index)
    now = cur[(cur.crop_year == newest) & (cur.month == mon)].pct.iloc[0]
    others = cur[(cur.month == mon) & (cur.crop_year != newest)].sort_values("crop_year").pct
    nw = m[m.kind == "new"]
    new_pct = None
    if len(nw):
        ny = max(nw.crop_year)
        rows = nw[nw.crop_year == ny]
        new_pct = (ny, max(rows.month, key=ords.index), rows[rows.month == max(rows.month, key=ords.index)].pct.iloc[0])
    return dict(com=com, crop=newest, month=mon, now=now,
                ly=others.iloc[-1] if len(others) else None, avg=others.mean() if len(others) else None, new=new_pct)


def delta_cell(v):
    if v is None:
        return '<td class="num">&ndash;</td>'
    cls = "up" if v > 0 else "down" if v < 0 else ""
    return f'<td class="num {cls}">{v:+.0f} pts</td>'


@st.fragment
def summary():
    rows = [r for r in (snap_stats(c) for c in COMMODITIES) if r]
    def pct(v):
        return "&ndash;" if v is None else "%.0f%%" % v

    def gap(a, b):
        return None if b is None else a - b

    body = ""
    for r in rows:
        new = r["new"]
        body += ('<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td class="num big">%s</td>'
                 '<td class="num">%s</td>%s<td class="num">%s</td>%s<td>%s</td><td class="num">%s</td></tr>'
                 % (r["com"], r["crop"], r["month"], pct(r["now"]),
                    pct(r["ly"]), delta_cell(gap(r["now"], r["ly"])),
                    pct(r["avg"]), delta_cell(gap(r["now"], r["avg"])),
                    "&ndash;" if new is None else new[0], pct(None if new is None else new[2])))
    sec("Current-crop sales, all commodities")
    st.markdown(
        '<div class="sum-wrap"><table class="sum"><thead><tr><th>Commodity</th><th>Crop year</th><th>As of</th>'
        '<th class="num">% sold</th><th class="num">Last year</th><th class="num">vs LY</th>'
        '<th class="num">Avg prior yrs</th><th class="num">vs avg</th><th>New crop</th>'
        f'<th class="num">New-crop % sold</th></tr></thead><tbody>{body}</tbody></table></div>',
        unsafe_allow_html=True)
    st.caption("% sold is the share of the crop reported sold as of the latest survey month for the newest crop year. "
               "Last year and the prior-year average are for the same month.")


def kpi_tiles():
    cur = mo[mo.kind == "current"]
    newest = max(cur.crop_year)
    ord_s = order + [close]
    latest_m = max(cur[cur.crop_year == newest].month, key=ord_s.index)
    now = cur[(cur.crop_year == newest) & (cur.month == latest_m)].pct.iloc[0]
    others = cur[(cur.month == latest_m) & (cur.crop_year != newest)].sort_values("crop_year")
    st.markdown(f'<div class="asof">Current-crop sales, <b>{newest}</b> crop, as of the <b>{latest_m}</b> survey.</div>',
                unsafe_allow_html=True)
    cols = st.columns(4)
    cols[0].markdown(tile(f"{newest} sold", f"{now:.0f}%", "current crop"), unsafe_allow_html=True)
    if len(others):
        d, cls = pts(now - others.pct.iloc[-1])
        cols[1].markdown(tile("vs last year", d, f"last year {others.pct.iloc[-1]:.0f}%", cls), unsafe_allow_html=True)
        d, cls = pts(now - others.pct.mean())
        cols[2].markdown(tile(f"vs {len(others)}-yr avg", d, f"average {others.pct.mean():.0f}%", cls),
                         unsafe_allow_html=True)
    nw = mo[mo.kind == "new"]
    if len(nw):
        ny = max(nw.crop_year)
        rows = nw[nw.crop_year == ny]
        ny_m = max(rows.month, key=ord_s.index)
        cols[3].markdown(tile(f"{ny} new crop", f"{rows[rows.month == ny_m].pct.iloc[0]:.0f}%",
                              f"forward sales, {ny_m}"), unsafe_allow_html=True)


@st.fragment
def monthly_view():
    kpi_tiles()
    for kind, lbl in (("current", "Current-crop sales"), ("new", "New-crop forward sales")):
        k = mo[mo.kind == kind]
        if k.empty:
            continue
        sec(lbl)
        ord_k = list(order if kind == "current" else MONTHS[8:] + MONTHS[:8])
        if close in set(k.month):
            ord_k.append(close)
        fig = go.Figure()
        ks = sorted(k.crop_year.unique())
        for cy in ks:
            d = k[k.crop_year == cy].assign(i=lambda t: t.month.map(ord_k.index)).sort_values("i")
            fig.add_scatter(x=d.month, y=d.pct, name=cy, mode="lines+markers", marker=dict(size=5),
                            line=dict(color=year_color(cy, ks), width=3.5 if cy == ks[-1] else 2.2))
        fig.update_xaxes(categoryorder="array", categoryarray=ord_k)
        kind_lbl = "Current crop" if kind == "current" else "New crop"
        style_fig(fig, title=f"Farmer Selling % - {commodity} ({kind_lbl})")
        # side card: every crop year's % sold at the latest month reported for the newest crop year
        latest = k[k.crop_year == ks[-1]].month.map(ord_k.index).max()
        mon = ord_k[latest]
        vals = k[k.month == mon].set_index("crop_year").pct
        card = "".join(f'<div class="cy-row{" cy-new" if cy == ks[-1] else ""}">{cy} {vals[cy]:.0f}%</div>'
                       for cy in reversed(ks) if cy in vals.index)
        c_chart, c_card = st.columns([5, 1])
        c_chart.plotly_chart(fig, width="stretch", theme=None)
        c_card.markdown(f'<div class="cy-card"><div class="tile-label">{mon} % sold</div>{card}</div>',
                        unsafe_allow_html=True)
        piv =k.pivot(index="month", columns="crop_year", values="pct").reindex(ord_k).dropna(how="all")
        show_table(piv.map(lambda v: None if pd.isna(v) else f"{v:.0f}%"), f"m_{kind}")


@st.fragment
def data_view():
    sv = surveys[surveys.commodity == commodity]
    show_table(sv.sort_values(["crop_year", "date"], ascending=[False, False])
               .assign(date=lambda t: t.date.dt.date), "data", hide_index=True)
    st.download_button("Download survey points (CSV)", sv.to_csv(index=False), f"{commodity}_survey.csv")


with tab_sum:
    summary()
with tab_month:
    monthly_view()
with tab_data:
    data_view()

with tab_admin:
    if not __import__("portal_view").shown(tab_admin):
        st.stop()   # client portal: the Admin tab is hidden and its body must not run (it is the last block)
    try:
        pw = st.secrets.get("EDIT_PASSWORD", "")
    except Exception:  # no secrets file locally
        pw = ""
    if pw and st.text_input("Admin password", type="password", key="admin_pw") != pw:
        st.info("Enter the admin password to add data.")
    elif up:
        st.warning("An uploaded workbook is loaded for this session; remove it to edit the saved data.")
    else:
        sec("Add monthly survey results")
        st.caption("Leave % blank for anything not reported; an existing month / crop year / crop type row is overwritten.")
        month = st.selectbox("Month", MONTHS, index=(pd.Timestamp.today().month - 1), key="admin_month")
        base = []
        for com in COMMODITIES:
            for kind in ("current", "new"):
                k = monthly[(monthly.commodity == com) & (monthly.kind == kind)]
                if not k.empty:
                    base.append({"commodity": com, "kind": kind, "crop_year": max(k.crop_year), "pct": None})
        edited = st.data_editor(
            pd.DataFrame(base), hide_index=True, width="stretch", key=f"admin_grid_{month}",
            disabled=["commodity", "kind"],
            column_config={"pct": st.column_config.NumberColumn("% sold", min_value=0, max_value=100, step=1),
                           "crop_year": st.column_config.TextColumn("Crop year", help="e.g. 26/27")})
        if st.button("Save to monthly data", type="primary", icon=":material/save:"):
            new = edited.dropna(subset=["pct"])
            if new.empty:
                st.warning("Nothing to save: fill in at least one % sold.")
            else:
                new = new.assign(month=month)[["commodity", "kind", "crop_year", "month", "pct"]]
                db.save_monthly(new)
                st.cache_data.clear()
                st.toast(f"Saved {len(new)} value(s) for {month}.", icon=":material/check:")
                st.rerun()
        st.divider()
        survey_admin()
