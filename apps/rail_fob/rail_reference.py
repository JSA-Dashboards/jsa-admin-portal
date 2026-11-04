"""
Reference at the bottom of each railroad tab (Kolten, 2026-10-28): that railroad's fuel-surcharge equation with the
current months worked out from EIA diesel, and its archived shipper / loader directory. The directories are the six
files in JSA - Documents / Research Analyst / Misc / Rail Origins & Destinations, kept as JSON in data/rail_directory/
(business facility data only — the contact names, emails and phones in BNSF's list are NOT archived here; the repo is
public). Each list sits in a collapsed expander that only loads when opened, so the tab stays light.
"""
import json
import os
from datetime import date

import pandas as pd
import streamlit as st

import bn_fsc as BNF
import rail_fsc as RF

_DIR = os.path.join(os.path.dirname(__file__), "data", "rail_directory")
_KIND = {"published": "diesel month complete", "open": "diesel month still open", "forecast": "latest diesel held flat"}


@st.cache_data
def _load(name):
    with open(os.path.join(_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _expander(label, key):
    """(container, is it open). Lazy where Streamlit can report the open state; older versions load it always."""
    try:
        exp = st.expander(label, key=key, on_change="rerun")
        return exp, bool(exp.open)
    except TypeError:
        return st.expander(label), True


def _meta(d, extra=""):
    st.caption(f"From {d['source']} ({d['folder']}), archived {d['extracted']}. {d.get('note', '')} {extra}".strip())


def _listing(rows, fields, key, multi=(), checks=()):
    """A searchable table. fields: [(field, header)]; multi: headers to offer a multi-select for;
    checks: [(header, label)] — a checkbox that keeps only rows where that (boolean) column is true."""
    df = pd.DataFrame(rows)[[f for f, _ in fields]].rename(columns=dict(fields))
    cols = st.columns([2] + [1] * (len(multi) + len(checks)))
    q = cols[0].text_input("Search", key=f"{key}_q", placeholder="company, city, state ...", label_visibility="collapsed")
    view = df
    if q.strip():
        mask = view.astype(str).apply(lambda c: c.str.contains(q.strip(), case=False, regex=False)).any(axis=1)
        view = view[mask]
    for i, h in enumerate(multi):
        pick = cols[1 + i].multiselect(h, sorted(df[h].dropna().unique().tolist()), key=f"{key}_m{i}", placeholder=h,
                                       label_visibility="collapsed")
        if pick:
            view = view[view[h].isin(pick)]
    for j, (h, label) in enumerate(checks):
        if cols[1 + len(multi) + j].checkbox(label, key=f"{key}_c{j}"):
            view = view[view[h].astype(bool)]
    st.dataframe(view, hide_index=True, width="stretch", height=380)
    st.caption(f"{len(view):,} of {len(df):,}")


def _money_cols(*headers):
    return {h: st.column_config.NumberColumn(h, format="$%d") for h in headers}


# ------------------------------------------------------------------ fuel surcharge
def _fsc_block(rr, weekly):
    p = RF.PROGRAMS[rr]
    exp, opened = _expander(f"Fuel surcharge: {p['name']}", f"ref_{rr}_fsc")
    if not opened:
        return
    with exp:
        st.markdown(f"**Equation.** {RF.equation(rr)} Dollars per car-mile, added to the base freight "
                    "(\\$/car = \\$/mile × miles).")
        st.caption(f"Rule: {p['rule']}.")
        dec = p["dec"]
        pub = p["published"]
        if weekly:
            tbl = RF.table(rr, weekly, date.today())
            rows = []
            for k, y, m in BNF.grid_months(date.today())[:6]:
                a = tbl.get(k)
                if not a:
                    continue
                known = pub.get(f"{y}-{m:02d}")
                rows.append({"Month": f"{k.title()} {y}", "Diesel basis": a["basis"],
                             "Formula $/mile": a["fsc"], "Published $/mile": known, "Formula based on": _KIND[a["kind"]]})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                         column_config={"Formula $/mile": st.column_config.NumberColumn(format=f"%.{dec}f"),
                                        "Published $/mile": st.column_config.NumberColumn(format=f"%.{dec}f")})
            shown = {f"{y}-{m:02d}" for _, y, m in BNF.grid_months(date.today())[:6]}
            extra = {k: v for k, v in pub.items() if k not in shown}
            if extra:
                st.caption("Also published (" + p["published_from"] + "): " + " · ".join(
                    f"{k} {v:.{dec}f}" for k, v in sorted(extra.items())) + ".")
            else:
                st.caption(f"Published = {p['published_from']}. Months past the diesel data hold the latest weekly price flat.")
        else:
            st.caption("The month-by-month values need diesel prices (the EIA_API_KEY secret). Published so far "
                       f"({p['published_from']}): " + " · ".join(f"{k} {v:.{dec}f}" for k, v in sorted(pub.items())) + ".")
        st.caption(p["confidence"])
        st.markdown(" · ".join(f"[{t}]({u})" for t, u in p["links"]))


# ------------------------------------------------------------------ directories
def _csx():
    d = _load("csx_shippers.json")
    exp, opened = _expander(f"CSX shippers directory ({len(d['rows']):,})", "ref_csx_dir")
    if opened:
        with exp:
            _meta(d)
            _listing(d["rows"], [("name", "Company"), ("city", "City"), ("state", "State"), ("category", "Category"),
                                 ("service", "Service"), ("road", "Road"), ("address", "Address"), ("zip", "Zip")],
                     "csxdir", multi=("State", "Category"))


def _ns():
    d = _load("ns_loaders.json")
    exp, opened = _expander(f"NS grain loaders directory ({len(d['rows']):,})", "ref_ns_dir")
    if opened:
        with exp:
            _meta(d)
            _listing(d["rows"], [("name", "Company"), ("city", "City"), ("state", "State"), ("type", "Type"),
                                 ("switch_road", "Switch road"), ("switch_status", "Switch status"), ("storage", "Storage"),
                                 ("track_cap", "Track cap"), ("load_cap", "Load / unload cap"), ("unit_train", "Unit train"),
                                 ("address", "Address"), ("phone", "Phone")],
                     "nsdir", multi=("State", "Switch road"), checks=(("Unit train", "Unit trains only"),))


def _bn():
    d = _load("bnsf_shippers.json")
    exp, opened = _expander(f"BNSF shippers directory ({len(d['rows']):,})", "ref_bn_dir")
    if opened:
        with exp:
            _meta(d)
            _listing(d["rows"], [("name", "Elevator"), ("station", "Station"), ("state", "State"), ("road", "Service road"),
                                 ("track_cap", "Track cap"), ("track_type", "Track type"), ("capacity", "Capacity"),
                                 ("shuttle", "Shuttle"), ("number", "Number"), ("lat", "Lat"), ("lon", "Lon")],
                     "bndir", multi=("State", "Service road"), checks=(("Shuttle", "Shuttle loaders only"),))
    r = _load("bn_shuttle_rates.json")
    exp, opened = _expander(f"BN corn shuttle rates, BNSF price list ({len(r['pnw']) + len(r['hereford_origins']):,} rates)",
                            "ref_bn_rates")
    if opened:
        with exp:
            _meta(r, f"Price authority {r['price_authority']}. The face rates in the freight build are this list's third column "
                     "(286K lb, 5,001+ cu ft) plus later increases, mostly \\$200/car on PNW.")
            view = st.radio("Rates", ["PNW by origin", "Hereford by origin", "Hereford destination adjustments"],
                            horizontal=True, key="bnrates_view", label_visibility="collapsed")
            rate_f = [("r268_5000", "268K ≤5,000 cu ft"), ("r286_5000", "286K ≤5,000 cu ft"), ("r286_5001", "286K 5,001+ cu ft")]
            cc = _money_cols(*[h for _, h in rate_f])
            if view.startswith("PNW"):
                df = pd.DataFrame(r["pnw"]).rename(columns={"origin": "Origin", "destination": "Destination", "route": "Route",
                                                            **dict(rate_f)})
                q = st.text_input("Search", key="bnrates_q", placeholder="origin ...", label_visibility="collapsed")
                dest = st.multiselect("Destination", sorted(df["Destination"].unique()), key="bnrates_d", placeholder="Destination")
                if q.strip():
                    df = df[df["Origin"].str.contains(q.strip(), case=False, regex=False)]
                if dest:
                    df = df[df["Destination"].isin(dest)]
                st.dataframe(df, hide_index=True, width="stretch", height=380, column_config=cc)
            else:
                rows = r["hereford_origins"] if view == "Hereford by origin" else r["hereford_adjustments"]
                df = pd.DataFrame(rows).rename(columns={"name": "Origin" if rows is r["hereford_origins"] else "Destination group",
                                                        **dict(rate_f)})
                st.dataframe(df, hide_index=True, width="stretch", height=380, column_config=cc)
                if rows is r["hereford_adjustments"]:
                    st.caption("Per-car adjustments to the Hereford / Amarillo group rate for a different destination.")
            st.caption("\\$ per car, 110-120 car shuttles, subject to the mileage-based fuel surcharge above.")
            if st.checkbox("Show the destination group definitions", key="bnrates_geo"):
                st.text(r["geography"])


def _cn():
    d = _load("cn_origins.json")
    exp, opened = _expander(f"CN origins ({len(d['rows']):,})", "ref_cn_dir")
    if opened:
        with exp:
            _meta(d)
            rows = [{**r, "cars": None if r["cars"] is None else str(r["cars"])} for r in d["rows"]]   # 25, 105 and "<25" mixed
            _listing(rows, [("name", "Company"), ("city", "City"), ("state", "State"), ("cars", "Cars"),
                                 ("reference", "Reference point"), ("lat", "Lat"), ("lon", "Lon"), ("note", "Note")],
                     "cndir", multi=("State",), checks=(("Reference point", "Reference points only"),))


def _up():
    d = _load("up_shuttle.json")
    n = len(d["origins"]) + len(d["destinations"]) + len(d["mexico"])
    exp, opened = _expander(f"UP grain shuttle origins and destinations ({n:,})", "ref_up_dir")
    if opened:
        with exp:
            _meta(d, f"{d['program']}, issued {d['issued']}, effective {d['effective']}.")
            view = st.radio("List", [f"Origins ({len(d['origins'])})", f"US destinations ({len(d['destinations'])})",
                                     f"Mexico destinations ({len(d['mexico'])})"],
                            horizontal=True, key="updir_view", label_visibility="collapsed")
            rows = d["origins"] if view.startswith("Origins") else d["destinations"] if view.startswith("US") else d["mexico"]
            _listing(rows, [("state", "State"), ("city", "City"), ("cars", "Shuttle size (cars)"), ("company", "Company")],
                     "updir" + view[:2], multi=("State",))


_DIRS = {"CSX": [_csx], "NS": [_ns], "BN": [_bn], "CN": [_cn], "UP": [_up]}


def render(rr, weekly=None):
    """The fuel-surcharge equation and the directories for one railroad (CSX, NS, BN, CN or UP)."""
    st.markdown(f"#### {rr} reference")
    _fsc_block(rr, weekly)
    for fn in _DIRS[rr]:
        fn()
