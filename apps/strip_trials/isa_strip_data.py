"""
ISA strip trials for the admin portal: the read side of the yield portal's Strip
trials page (JSA-Dashboards/yield-portal: isa_trials.py, nass.py,
app_pages/strip_trials.py). That repo's loader fills
YIELD_REPORTS.PUBLIC.ISA_STRIP_TRIALS from the text of ISA's reports, on the
Droplet; this only reads it, beside Iowa's NASS county and state yields from the
fleet's cache.

Keep in step with the yield portal: a change there to how fields are counted or
compared with NASS belongs here too. The module has a name no other bundled app
uses, because every app shares one process and one sys.modules (River FOB
already has a `db`).

Reads two databases, both fully qualified, so the ambient SNOWFLAKE_DATABASE and
SNOWFLAKE_SCHEMA don't matter. ADMIN_PORTAL_ROLE needs SELECT on
YIELD_REPORTS.PUBLIC (see CLAUDE.md).
"""
import re

import pandas as pd
import streamlit as st

import nass_cache_client as ncc

TABLE = "YIELD_REPORTS.PUBLIC.ISA_STRIP_TRIALS"
NASS_TABLE = "JSA.NASS_CACHE.NASS_CACHE"
COLUMNS = ["trial_id", "year", "crop", "county", "landform", "district", "trial_type",
           "trial_detail", "avg_response", "treatments", "yields", "trial_yield", "layout",
           "status", "report_url", "field_id", "listed_crop"]
READ = ("read", "unverified")               # statuses whose yields the page uses
FIRST_YEAR = 2005                           # = usda-nass-etl jobs/yield_portal.FIRST_YEAR
# the cache keys must hash exactly as usda-nass-etl's jobs/yield_portal.py and
# jobs/domestic_production.py build them (yield-portal nass.county_params/state_params)
COMMODITY = {"Corn": {"commodity_desc": "CORN", "util_practice_desc": "GRAIN"},
             "Soybeans": {"commodity_desc": "SOYBEANS"}}


def county_params(crop, year):
    return {"source_desc": "SURVEY", "sector_desc": "CROPS", "agg_level_desc": "COUNTY",
            "year": str(year), "statisticcat_desc": "YIELD", "unit_desc": "BU / ACRE",
            **COMMODITY[crop]}


def state_params(crop):
    return {**COMMODITY[crop], "statisticcat_desc": "YIELD", "unit_desc": "BU / ACRE",
            "source_desc": "SURVEY", "domain_desc": "TOTAL", "freq_desc": "ANNUAL",
            "agg_level_desc": "STATE", "year__GE": "1980"}


def norm(name) -> str:
    """'O'Brien' / 'O BRIEN' -> 'obrien' (yield-portal places.norm)."""
    s = str(name or "").lower().replace("saint ", "st ").replace("sainte ", "ste ")
    return re.sub(r"[^a-z]", "", s)


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return float("nan")                 # "(D)", "(NA)": withheld


@st.cache_data(ttl=3600, show_spinner="Loading ISA strip trials…")
def load_trials() -> pd.DataFrame:
    """Every trial the yield portal loaded, read or not."""
    conn = ncc._sf_connect()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {', '.join(COLUMNS)} FROM {TABLE}")
        d = pd.DataFrame(cur.fetchall(), columns=COLUMNS)
    finally:
        conn.close()
    for c in ("year", "treatments"):
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("Int64")
    for c in ("avg_response", "trial_yield"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


@st.cache_data(ttl=6 * 3600, show_spinner="Loading NASS yields…")
def load_nass(through_year: int):
    """Iowa's NASS yields -> (county: crop, year, county, yield; state: crop, year,
    final). Snowflake flattens the cached payloads to Iowa's ALL PRODUCTION
    PRACTICES records, so a few thousand rows come back, not ~80 MB of JSON. A
    state YEAR row counts as final only when loaded after the January following
    that harvest; before that it's USDA's latest forecast."""
    wanted = {}
    for crop in COMMODITY:
        wanted[ncc._cache_key("api_GET", state_params(crop))] = ("state", crop)
        for y in range(FIRST_YEAR, through_year + 1):
            wanted[ncc._cache_key("api_GET", county_params(crop, y))] = ("county", crop)
    keys = tuple(wanted)
    conn = ncc._sf_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT c.cache_key, r.value:year::string, r.value:county_name::string, "
            "r.value:county_ansi::string, r.value:Value::string, "
            "r.value:reference_period_desc::string, r.value:load_time::string "
            f"FROM {NASS_TABLE} c, LATERAL FLATTEN(input => c.data:data) r "
            f"WHERE c.error IS NULL AND c.cache_key IN ({', '.join(['%s'] * len(keys))}) "
            "AND r.value:prodn_practice_desc::string = 'ALL PRODUCTION PRACTICES' "
            "AND r.value:state_alpha::string = 'IA'", keys)
        rows = cur.fetchall()
    finally:
        conn.close()
    county, finals = [], {}
    for key, year, name, ansi, value, period, loaded in rows:
        kind, crop = wanted[key]
        v = _num(value)
        if v != v:
            continue
        if kind == "county":
            if ansi and "OTHER" not in (name or ""):
                county.append((crop, int(year), name, v))
        elif period == "YEAR" and str(loaded or "") >= f"{int(year) + 1}-01-01":
            finals[(crop, int(year))] = v
    return (pd.DataFrame(county, columns=["crop", "year", "county", "yield"]),
            pd.DataFrame([(c, y, v) for (c, y), v in finals.items()],
                         columns=["crop", "year", "final"]))


def with_nass(d: pd.DataFrame, county: pd.DataFrame, state: pd.DataFrame) -> pd.DataFrame:
    """+ county_final (the county's NASS yield that season, where NASS published
    it), state_final (Iowa's final) and the field over each, as fractions
    (vs_county, vs_state). ISA's counties are matched by name ("O'Brien" = NASS
    "O BRIEN")."""
    d = d.copy()
    cy = {(c, int(y), norm(n)): v for c, y, n, v in county.itertuples(index=False)}
    sy = {(c, int(y)): v for c, y, v in state.itertuples(index=False)}
    d["county_final"] = pd.to_numeric(pd.Series(
        [cy.get((c, int(y), norm(n))) for c, y, n in zip(d["crop"], d["year"], d["county"])],
        index=d.index, dtype="object"), errors="coerce")
    d["state_final"] = pd.to_numeric(pd.Series(
        [sy.get((c, int(y))) for c, y in zip(d["crop"], d["year"])],
        index=d.index, dtype="object"), errors="coerce")
    d["vs_county"] = d["trial_yield"] / d["county_final"] - 1
    d["vs_state"] = d["trial_yield"] / d["state_final"] - 1
    return d


def fields(d: pd.DataFrame) -> pd.DataFrame:
    """The read trials, each field once: of the trials sharing a report, the one
    that read the most treatments (the fullest mean)."""
    r = d[d["status"].isin(READ)]
    return r.sort_values("treatments", ascending=False, kind="stable").drop_duplicates("field_id")


def by_season(d: pd.DataFrame) -> pd.DataFrame:
    """with_nass's frame -> crop, year: fields read, field (their mean yield), county
    (mean NASS yield of their counties, over the fields that have one), state
    (Iowa), and over_county / over_state (the median of the fields' own ratios)."""
    return (fields(d).groupby(["crop", "year"], as_index=False)
            .agg(fields=("trial_id", "size"), field=("trial_yield", "mean"),
                 county=("county_final", "mean"), state=("state_final", "max"),
                 over_county=("vs_county", "median"), over_state=("vs_state", "median")))
