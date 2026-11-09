"""
Acreage Summary tab: planted acres by crop (wheat, feedgrains, oilseeds, cotton, hay and other), prevent plant and CRP,
as one table and a trend chart, for the U.S. or one state.

PORTED from the Acreage Summary tab of the RMA dashboard (JSA-Dashboards/rma-production-map, app.py). The table renderer,
crop parameters, state names and CRP history were lifted from that file by script; edit here, the two are no longer linked.

Differences from the RMA tab:
  * NASS data is read from the shared cache (usda-nass-etl, jobs/domestic_production.py `acreage_summary_jobs`): one broad
    AREA PLANTED pull per crop and level (NATIONAL / STATE, every year, every state), read in one batch and filtered here. No NASS key.
  * Prevent plant for corn, soybeans and wheat comes from data/acreage_prevent_plant.csv, the RMA Summary of Business
    workbook cut down to state x year (the workbook itself is not shipped). NASS QuickStats has no prevent-plant series.
  * CRP comes from data/acreage_crp.json (USDA FSA CRPHistoryState86-25), million acres by state and year.
"""
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from nass_cache_client import _cache_key, _sf_connect, _use_sf, fetch_cached

HERE = Path(__file__).parent

# palette: the domestic dashboard's
TEAL_DIM = "#3d7a84"
ACCENT   = "#5ba5af"
DARK     = "#f9fafb"
PANEL    = "#ffffff"
SURFACE  = "#f3f4f6"
BORDER   = "#e5e7eb"
TEXT     = "#111827"
MUTED    = "#6b7280"


ABBR_TO_NAME = {
    "AL": "Alabama",        "AK": "Alaska",         "AZ": "Arizona",
    "AR": "Arkansas",       "CA": "California",     "CO": "Colorado",
    "CT": "Connecticut",    "DE": "Delaware",       "FL": "Florida",
    "GA": "Georgia",        "HI": "Hawaii",         "ID": "Idaho",
    "IL": "Illinois",       "IN": "Indiana",        "IA": "Iowa",
    "KS": "Kansas",         "KY": "Kentucky",       "LA": "Louisiana",
    "ME": "Maine",          "MD": "Maryland",       "MA": "Massachusetts",
    "MI": "Michigan",       "MN": "Minnesota",      "MS": "Mississippi",
    "MO": "Missouri",       "MT": "Montana",        "NE": "Nebraska",
    "NV": "Nevada",         "NH": "New Hampshire",  "NJ": "New Jersey",
    "NM": "New Mexico",     "NY": "New York",       "NC": "North Carolina",
    "ND": "North Dakota",   "OH": "Ohio",           "OK": "Oklahoma",
    "OR": "Oregon",         "PA": "Pennsylvania",   "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota",   "TN": "Tennessee",
    "TX": "Texas",          "UT": "Utah",           "VT": "Vermont",
    "VA": "Virginia",       "WA": "Washington",     "WV": "West Virginia",
    "WI": "Wisconsin",      "WY": "Wyoming",
}

# Three entries differ from the RMA tab's, whose queries match no NASS series (so those columns are blank there): the commodity is
# SUNFLOWER (not SUNFLOWERS); dry beans are BEANS with class DRY EDIBLE, INCL CHICKPEAS; and NASS publishes hay as AREA HARVESTED only
# (the crop's statisticcat_desc overrides AREA PLANTED). Checked against live NASS 2026-11-09.
_ACR_PARAMS: dict = {
    "Wheat":      (("commodity_desc","WHEAT"),("class_desc","ALL CLASSES")),
    "Corn":       (("commodity_desc","CORN"),),
    "Sorghum":    (("commodity_desc","SORGHUM"),),
    "Barley":     (("commodity_desc","BARLEY"),),
    "Oats":       (("commodity_desc","OATS"),),
    "Soybeans":   (("commodity_desc","SOYBEANS"),),
    "Sunflowers": (("commodity_desc","SUNFLOWER"),("class_desc","ALL CLASSES")),
    "Canola":     (("commodity_desc","CANOLA"),),
    "Cotton":     (("commodity_desc","COTTON"),("class_desc","ALL CLASSES")),
    "Rice":       (("commodity_desc","RICE"),),
    "Peanuts":    (("commodity_desc","PEANUTS"),),
    "SugarBeets": (("commodity_desc","SUGARBEETS"),),
    "DryBeans":   (("commodity_desc","BEANS"),("class_desc","DRY EDIBLE, INCL CHICKPEAS")),
    "Hay":        (("commodity_desc","HAY"),("class_desc","ALL CLASSES"),("statisticcat_desc","AREA HARVESTED")),
}

_ACR_PP_CROPS = ("Corn","Soybeans","Wheat","Cotton","Sorghum","Rice","Peanuts","SugarBeets","DryBeans","Barley","Oats","Sunflowers","Canola")



def _render_acreage_html(rows: list, years: list,
                          title: str, scope_label: str,
                          unit_mul: float = 1.0,
                          unit_lbl: str = "mil ac") -> str:
    """
    Build PRX-style HTML table.
    rows: list of {col_key: value_or_None} dicts, one per year (oldest→newest).
    years: matching calendar years.
    unit_mul: multiply stored M-ac values before display (1.0=M ac, 1000=K ac).
    Returns full HTML string.
    """
    # ── style constants ──────────────────────────────────────────────────────
    HDR1  = ACCENT          # group header bg
    HDR2  = TEAL_DIM       # sub-header bg (slightly darker)
    UNIT  = "#e8f4fd"       # units row bg
    ROW_E = DARK            # even rows
    ROW_O = "#ffffff"       # odd rows
    CUR   = "#dbeafe"       # current-year highlight
    CHG_P = "#dcfce7"       # change row positive bg
    CHG_N = "#fee2e2"       # change row negative bg
    CHG_0 = SURFACE         # change row neutral bg
    FP    = "#166534"       # positive text
    FN    = "#991b1b"       # negative text
    TXT   = TEXT
    MUT   = MUTED
    W     = "white"

    def _fmt(v, decimals=1):
        if v is None or (isinstance(v, float) and (np.isnan(v) or v == 0)):
            return "—"
        return f"{v * unit_mul:,.{decimals}f}"

    # ── column schema ────────────────────────────────────────────────────────
    # (key, display, group, group_span_start)
    cols = [
        # key,              label,          group,       span_of_group
        ("mkt_yr",          "Crop<br>Year",  None,        0),
        ("Wheat",           "All<br>Wheat",  None,        0),
        # ── Feedgrains
        ("Corn",            "Corn",          "Feedgrains", 5),
        ("Sorghum",         "Sorg",          "Feedgrains", 0),
        ("Barley",          "Barley",        "Feedgrains", 0),
        ("Oats",            "Oats",          "Feedgrains", 0),
        ("FG_Total",        "Total",         "Feedgrains", 0),
        # ── Oilseeds
        ("Soybeans",        "Soy",           "Oilseeds",   4),
        ("Sunflowers",      "Sunseed",       "Oilseeds",   0),
        ("Canola",          "Canola",        "Oilseeds",   0),
        ("OS_Total",        "Total",         "Oilseeds",   0),
        # ── stand-alone
        ("CornSoy",         "Corn+Soy",      None,         0),
        ("Cotton",          "Cotton",        None,         0),
        ("Total_Major",     "Total<br>Major",None,         0),
        ("HayOther",        "All Hay<br>& Other", None,   0),
        ("Principal",       "Principal<br>Crops", None,   0),
        ("CRP",             "CRP*",          None,         0),
        ("TotalCRP",        "Total<br>w/CRP",None,        0),
        # ── Prevent Plant
        ("PP_Major",        "Cn/Soy/<br>Wht",  "Prevent Acres", 3),
        ("PP_Other",        "All<br>Other",     "Prevent Acres", 0),
        ("PP_Total",        "Total<br>w/PP",    "Prevent Acres", 0),
    ]

    def _th(text, bg, fg=W, rowspan=1, colspan=1, extra=""):
        rs = f' rowspan="{rowspan}"' if rowspan > 1 else ""
        cs = f' colspan="{colspan}"' if colspan > 1 else ""
        return (f'<th{rs}{cs} style="background:{bg};color:{fg};'
                f'padding:4px 6px;text-align:center;font-size:0.72rem;'
                f'border:1px solid #c8d5e3;white-space:nowrap;{extra}">'
                f'{text}</th>')

    def _td(text, bg=ROW_E, fg=TXT, bold=False, align="right", extra=""):
        b = "font-weight:600;" if bold else ""
        return (f'<td style="background:{bg};color:{fg};{b}'
                f'padding:3px 7px;text-align:{align};font-size:0.72rem;'
                f'border:1px solid #dde8f0;white-space:nowrap;{extra}">'
                f'{text}</td>')

    # ── build header rows ────────────────────────────────────────────────────
    # Row 1: group headers
    h1 = ""
    skip_until = 0
    for i,(key,lbl,grp,span) in enumerate(cols):
        if i < skip_until:
            continue
        if grp is None:
            h1 += _th(lbl, HDR1, rowspan=2)
        else:
            h1 += _th(grp, HDR2, colspan=span)
            skip_until = i + span

    # Row 2: sub-column headers (only for grouped cols)
    h2 = ""
    for key,lbl,grp,span in cols:
        if grp is not None:
            h2 += _th(lbl, HDR2)

    # Units row
    h3 = ""
    for key,lbl,grp,span in cols:
        if key == "mkt_yr":
            h3 += _td("", bg=UNIT, fg=MUT, align="center")
        else:
            h3 += _td(unit_lbl, bg=UNIT, fg=MUT, align="center")

    thead = (f'<thead><tr>{h1}</tr><tr>{h2}</tr>'
             f'<tr>{h3}</tr></thead>')

    # ── build body rows ──────────────────────────────────────────────────────
    tbody = "<tbody>"
    cur_yr = years[-1] if years else None
    for i,(yr, row) in enumerate(zip(years, rows)):
        is_cur = (yr == cur_yr)
        bg = CUR if is_cur else (ROW_O if i % 2 else ROW_E)
        tr = f'<tr style="background:{bg};">'
        for key,lbl,grp,span in cols:
            v = row.get(key)
            if key == "mkt_yr":
                txt = str(v) if v else "—"
                tr += _td(txt, bg=bg, fg=ACCENT if is_cur else TXT,
                          bold=is_cur, align="center")
            else:
                tr += _td(_fmt(v), bg=bg, fg=TXT, bold=is_cur)
        tr += "</tr>"
        tbody += tr

    # ── year-over-year change row ────────────────────────────────────────────
    if len(rows) >= 2:
        prev_row = rows[-2]
        cur_row  = rows[-1]
        tbody += f'<tr style="border-top:2px solid {BORDER};">'
        for key,lbl,grp,span in cols:
            if key == "mkt_yr":
                tbody += _td("Chg vs Prior Yr", bg=SURFACE, fg=MUT,
                             bold=True, align="center")
                continue
            cv = cur_row.get(key)
            pv = prev_row.get(key)
            if cv is None or pv is None:
                tbody += _td("—", bg=SURFACE, fg=MUT)
                continue
            delta = cv - pv
            if abs(delta) < 0.05:
                chg_bg, chg_fg = CHG_0, MUT
            elif delta > 0:
                chg_bg, chg_fg = CHG_P, FP
            else:
                chg_bg, chg_fg = CHG_N, FN
            sign = "+" if delta > 0 else ""
            tbody += _td(f"{sign}{delta * unit_mul:.1f}", bg=chg_bg, fg=chg_fg, bold=True)
        tbody += "</tr>"

    tbody += "</tbody>"

    scope_note = f" — {scope_label}" if scope_label and scope_label != "National" else ""
    html = f"""
<div style="overflow-x:auto;">
<p style="font-size:0.9rem;font-weight:700;color:{TXT};margin:0 0 4px 0;text-align:center;">
  US Major Field Crops Area Planted{scope_note}</p>
<p style="font-size:0.72rem;color:{MUT};margin:0 0 8px 0;text-align:center;">
  {title} &nbsp;|&nbsp; {unit_lbl}</p>
<table style="border-collapse:collapse;width:100%;font-family:sans-serif;">
{thead}{tbody}
</table>
<p style="font-size:0.7rem;color:{MUT};margin:4px 0 0 0;">
  * CRP = Conservation Reserve Program (FSA). Prevent Plant from USDA RMA. Values in {unit_lbl}.</p>
</div>"""
    return html


# ── data ──────────────────────────────────────────────────────────────────────
def _planted_params(crop_key: str, agg_level: str) -> dict:
    params = {
        "source_desc": "SURVEY", "sector_desc": "CROPS", "agg_level_desc": agg_level,
        "domain_desc": "TOTAL", "statisticcat_desc": "AREA PLANTED", "unit_desc": "ACRES",
    }
    params.update(dict(_ACR_PARAMS[crop_key]))        # a crop's own statisticcat_desc (hay) overrides AREA PLANTED
    return params


@st.cache_data(ttl=3600, show_spinner=False)
def _planted_pulls(agg_level: str) -> dict:
    """{crop_key: DataFrame} of every crop's AREA PLANTED at NATIONAL or STATE level (every year, every state), as the shared cache
    holds it. One connection and one batched lookup for all crops. A query missing from the cache raises, so a gap is loud and is
    never cached as an empty table."""
    crops = list(_ACR_PARAMS)
    plist = [_planted_params(ck, agg_level) for ck in crops]
    if _use_sf():
        keys = [_cache_key("api_GET", p) for p in plist]
        found: dict = {}
        conn = _sf_connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT cache_key, data FROM nass_cache WHERE cache_key IN (%s)" % ",".join(["%s"] * len(keys)), keys)
            for k, d in cur.fetchall():
                found[k] = d if isinstance(d, (dict, list)) else json.loads(d)
        finally:
            conn.close()
        missing = [ck for ck, k in zip(crops, keys) if k not in found]
        if missing:
            raise RuntimeError(f"{len(missing)} NASS acreage queries are not in the cache yet ({', '.join(missing)}). "
                               "Run usda-nass-etl's domestic-production-dashboard job list.")
        rows = {ck: found[k].get("data", []) for ck, k in zip(crops, keys)}
    else:
        rows = {ck: fetch_cached(p).get("data", []) for ck, p in zip(crops, plist)}
    return {ck: pd.DataFrame(r) for ck, r in rows.items()}


def _acreage_hist(crop_key: str, state_abbr: str, prevent_plant: bool, start_yr: int, end_yr: int) -> dict:
    """{calendar_year: million acres} of planted (or prevent-plant) acres, for the U.S. or one state."""
    df = _planted_pulls("STATE" if state_abbr else "NATIONAL")[crop_key]
    if df.empty:
        return {}
    if state_abbr:
        df = df[df["state_alpha"].str.strip() == state_abbr]
    if "short_desc" in df.columns:
        has_pp = df["short_desc"].str.upper().str.contains("PREVENT", na=False)
        df = df[has_pp] if prevent_plant else df[~has_pp]
    if df.empty:
        return {}
    df = df.copy()
    df["val"] = pd.to_numeric(df["Value"].str.replace(",", "", regex=False), errors="coerce")
    df["yr"] = pd.to_numeric(df["year"], errors="coerce")
    df = df[(df["yr"] >= start_yr) & (df["yr"] <= end_yr)]
    if "reference_period_desc" in df.columns:
        yr_rows = df[df["reference_period_desc"] == "YEAR"]
        if not yr_rows.empty:
            df = yr_rows
    if "prodn_practice_desc" in df.columns:
        all_p = df[df["prodn_practice_desc"] == "ALL PRODUCTION PRACTICES"]
        if not all_p.empty:
            df = all_p
    df = df.dropna(subset=["yr", "val"])
    return {int(y): float(g["val"].sum()) / 1_000_000 for y, g in df.groupby("yr")}


@st.cache_data(show_spinner=False)
def _crp_data() -> dict:
    d = json.loads((HERE / "data" / "acreage_crp.json").read_text(encoding="utf-8"))
    return {k: {int(y): v for y, v in s.items()} for k, s in d.items()}


@st.cache_data(show_spinner=False)
def _rma_prevent_plant() -> pd.DataFrame:
    return pd.read_csv(HERE / "data" / "acreage_prevent_plant.csv")


# ── tab ───────────────────────────────────────────────────────────────────────
def render():
    ac1, ac2, _ = st.columns([1.5, 2, 1.5])
    with ac1:
        states = ["National"] + sorted(ABBR_TO_NAME.keys())
        state = st.selectbox(
            "Geography", states, key="acr_state",
            format_func=lambda x: x if x == "National" else f"{x}  —  {ABBR_TO_NAME.get(x, x)}",
        )
    with ac2:
        n_yrs = st.radio("Years shown", [10, 15, 20], horizontal=True, key="acr_n_yrs", index=1)

    state_abbr = "" if state == "National" else state
    end_yr = date.today().year
    start_yr = end_yr - n_yrs + 1
    cal_yrs = list(range(start_yr, end_yr + 1))

    def _mkt_yr(y: int) -> str:
        return f"{str(y)[2:]}-{str(y + 1)[2:]}"

    try:
        with st.spinner("Loading acreage data…"):
            acr: dict = {}
            pp: dict = {}
            for ck in _ACR_PARAMS:
                acr[ck] = _acreage_hist(ck, state_abbr, False, start_yr, end_yr)
                if ck in _ACR_PP_CROPS:
                    pp[ck] = _acreage_hist(ck, state_abbr, True, start_yr, end_yr)
    except Exception as e:
        st.error(f"NASS cache error: {e}")
        return
    if not any(acr.values()):
        st.warning("No planted-acreage data came back from the NASS cache for this selection.")
        return

    rma_pp: dict = {}                 # {year: {crop: million acres}}
    rdf = _rma_prevent_plant()
    if state_abbr:
        rdf = rdf[rdf["state"] == state_abbr]
    for (crop, yr), grp in rdf.groupby(["crop", "year"]):
        rma_pp.setdefault(int(yr), {})[crop] = float(grp["acres"].sum()) / 1e6

    def _g(crop, yr):
        return acr.get(crop, {}).get(yr)

    def _gp(crop, yr):
        return pp.get(crop, {}).get(yr)

    def _s(*vals):
        vs = [v for v in vals if v is not None]
        return sum(vs) if vs else None

    crp_src = _crp_data().get("US" if not state_abbr else state_abbr, {})

    acr_rows = []
    for yr in cal_yrs:
        wh, co, sg, ba, oa = (_g(k, yr) for k in ("Wheat", "Corn", "Sorghum", "Barley", "Oats"))
        sy, su, ca, ct = (_g(k, yr) for k in ("Soybeans", "Sunflowers", "Canola", "Cotton"))
        ri, pe, sb, db, ha = (_g(k, yr) for k in ("Rice", "Peanuts", "SugarBeets", "DryBeans", "Hay"))
        fg = _s(co, sg, ba, oa)
        os_ = _s(sy, su, ca)
        tmaj = _s(wh, fg, os_, ct)
        hayo = _s(ha, _s(ri, pe, sb, db))
        prin = _s(tmaj, hayo)
        pp_yr = rma_pp.get(yr, {})
        pp_co = _gp("Corn", yr) or pp_yr.get("Corn")
        pp_sy = _gp("Soybeans", yr) or pp_yr.get("Soybeans")
        pp_wh = _gp("Wheat", yr) or pp_yr.get("Wheat")
        pp_maj = _s(pp_co, pp_sy, pp_wh)
        pp_oth = _s(*[_gp(k, yr) for k in _ACR_PP_CROPS if k not in ("Corn", "Soybeans", "Wheat")])
        crp = crp_src.get(yr)
        acr_rows.append({
            "mkt_yr": _mkt_yr(yr), "Wheat": wh, "Corn": co, "Sorghum": sg, "Barley": ba, "Oats": oa, "FG_Total": fg,
            "Soybeans": sy, "Sunflowers": su, "Canola": ca, "OS_Total": os_, "CornSoy": _s(co, sy), "Cotton": ct,
            "Total_Major": tmaj, "HayOther": hayo, "Principal": prin, "CRP": crp, "TotalCRP": _s(prin, crp),
            "PP_Major": pp_maj, "PP_Other": pp_oth, "PP_Total": _s(pp_maj, pp_oth),
        })

    scope_lbl = "National" if not state_abbr else f"{state_abbr}  —  {ABBR_TO_NAME.get(state_abbr, '')}"
    tbl_title = f"{_mkt_yr(start_yr)} to {_mkt_yr(end_yr)}"

    indv = ("Corn", "Soybeans", "Wheat", "Cotton", "Sorghum", "Barley", "Oats", "Sunflowers", "Canola")
    max_indv = max((row.get(k) or 0.0 for row in acr_rows for k in indv), default=0.0)
    if max_indv >= 2.0:
        tbl_mul, tbl_unit = 1.0, "mil ac"
    elif max_indv >= 0.002:
        tbl_mul, tbl_unit = 1000.0, "K ac"
    else:
        tbl_mul, tbl_unit = 1_000_000.0, "ac"

    st.markdown(_render_acreage_html(acr_rows, cal_yrs, tbl_title, scope_lbl, unit_mul=tbl_mul, unit_lbl=tbl_unit),
                unsafe_allow_html=True)
    st.markdown(
        f"<p style='font-size:0.72rem;color:{MUTED};margin-top:8px;'>"
        "Planted acres: USDA NASS QuickStats (shared cache). "
        "Prevent Plant (Cn/Soy/Wht only): USDA RMA Summary of Business, years available in the RMA workbook. "
        "CRP: USDA FSA CRPHistoryState86-25 (fiscal year = planting calendar year), million acres."
        "</p>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<div style='margin-top:28px;'><div class='jsa-section-hdr'>Planted Acres Trend</div>"
        f"<p style='color:{MUTED};font-size:0.78rem;margin:0 0 12px 0;'>"
        "Select one or more crops / aggregates to compare over time.</p></div>",
        unsafe_allow_html=True,
    )
    chart_cols = {
        "Corn": "Corn", "Soybeans": "Soybeans", "All Wheat": "Wheat", "Sorghum": "Sorghum", "Barley": "Barley",
        "Oats": "Oats", "Sunflowers": "Sunflowers", "Canola": "Canola", "Cotton": "Cotton",
        "Feedgrains Total": "FG_Total", "Oilseeds Total": "OS_Total", "Corn + Soy": "CornSoy",
        "Hay & Other": "HayOther", "Total Major Crops": "Total_Major", "Principal Crops": "Principal",
        "CRP": "CRP", "Total w/CRP": "TotalCRP", "Prevent Plant Total": "PP_Total",
    }
    colors = ["#0693e3", "#f97316", "#22c55e", "#a855f7", "#ef4444", "#ca8a04", "#06b6d4", "#ec4899", "#84cc16", "#8b5cf6"]
    sel = st.multiselect("Commodities", options=list(chart_cols), default=["Corn", "Soybeans", "All Wheat", "CRP"],
                         key="acr_chart_sel", label_visibility="collapsed")
    if sel and acr_rows:
        fig = go.Figure()
        x_labs = [row["mkt_yr"] for row in acr_rows]
        for i, lbl in enumerate(sel):
            ys = [row.get(chart_cols[lbl]) for row in acr_rows]
            cc = colors[i % len(colors)]
            fig.add_trace(go.Scatter(
                x=[x_labs[j] for j, y in enumerate(ys) if y is not None], y=[y for y in ys if y is not None],
                mode="lines+markers", name=lbl, line=dict(color=cc, width=2),
                marker=dict(color=cc, size=5, line=dict(color="#ffffff", width=1)),
                hovertemplate=f"<b>{lbl}</b><br>%{{x}}: %{{y:.2f}}M ac<extra></extra>",
            ))
        fig.update_layout(
            yaxis_title="Million Acres", xaxis_title="Marketing Year", hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
            height=440, margin=dict(l=60, r=20, t=56, b=80), plot_bgcolor=PANEL, paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT, family="sans-serif", size=12),
            xaxis=dict(tickangle=-45, showgrid=False, linecolor=BORDER, tickfont=dict(size=10), zeroline=False),
            yaxis=dict(gridcolor=BORDER, gridwidth=1, zeroline=False, tickfont=dict(size=10)),
        )
        st.plotly_chart(fig, use_container_width=True)
