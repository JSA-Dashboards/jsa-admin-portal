"""
Builds data/map_points.json for the Map tab: the ethanol / corn processing plant list (PRX Corn Plant List) and the crush plant
list (Crush Plant Data), placed by city from the Census gazetteer, plus the railroads' grain shipper directories (the rows with
coordinates).
    python build_map_points.py
"""
import io
import json
import math
import os
import re
import zipfile

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "data", "rail_directory")
TRACKER = os.path.join(HERE, "..", "basis-tracker-streamlit")
MISC = r"C:\Users\KoltenPostin\John Stewart and Associates\JSA - Documents\Research Analyst\Misc"
ETHANOL_XLSX = os.path.join(MISC, "Ethanol", "PRX Corn Plant List - All.xlsx")
CRUSH_XLSX = os.path.join(MISC, "Crush", "Crush Plant Data.xlsx")
GAZ_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_place_national.zip"
_SUFFIX = re.compile(r"\s+(city|town|village|CDP|borough|municipality|township)$", re.I)


def _norm(s):
    s = re.sub(r"^(saint|st\.?)\s+", "st ", str(s).strip().lower())
    return re.sub(r"[^a-z0-9 ]", "", s.replace("-", " "))


# places the gazetteer lacks (unincorporated / hyphenated), approximate town centres
EXTRA = {("IA", "jewell"): (42.31, -93.64), ("IN", "clymers"): (40.745, -86.374), ("IN", "harrisville"): (40.175, -84.93),
         ("IN", "indianapolis"): (39.768, -86.158), ("KS", "campus"): (38.87, -100.8), ("MI", "riga"): (41.8, -83.77),
         ("MI", "woodbury"): (42.6, -85.1), ("VA", "elliston lafayette"): (37.13, -80.2), ("IN", "mt vernon"): (37.93, -87.9),
         ("MO", "n kansas city"): (39.14, -94.57)}


def _gazetteer():
    """{(ST, normalised place name): (lat, lon)} from the Census gazetteer (public domain); the bigger place wins a name clash."""
    z = zipfile.ZipFile(io.BytesIO(requests.get(GAZ_URL, timeout=120).content))
    g = pd.read_csv(z.open(z.namelist()[0]), sep="\t", encoding="latin1")
    g.columns = [c.strip() for c in g.columns]
    g = g.sort_values("ALAND_SQMI")
    out = {(r.USPS, _norm(_SUFFIX.sub("", r.NAME))): (r.INTPTLAT, r.INTPTLONG) for r in g.itertuples()}
    for k, v in EXTRA.items():
        out.setdefault(k, v)
    return out


def _num(v, div):
    try:
        x = round(float(v) / div, 1)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def _add(out, gaz, miss, name, st, city, status, **extra):
    if pd.isna(city) or pd.isna(st):
        return
    p = gaz.get((str(st).strip(), _norm(city)))
    if not p:
        miss.append(f"{name} ({city}, {st})")
        return
    out.append({"name": str(name).strip(), "state": str(st).strip(), "city": str(city).strip(),
                "status": "" if pd.isna(status) else str(status).strip(),
                "lat": round(p[0], 4), "lon": round(p[1], 4), **{k: v for k, v in extra.items() if v is not None}})


def _load(path):
    with open(path, encoding="utf8") as fh:
        return json.load(fh)


# Plants the lists don't carry. CHS Evansville WI: $700M, ~80M bu/yr soybean crush, announced 2023 (70M bu then), completion targeted
# fall 2028 (AgWeb); tagged Proposed as Kolten asked. Canadian plants near the US border are from the soy-crush-calculator's Ontario
# list (ontario.NODES) and COPA's July 2026 plant map (oilseed-crush-margins/data/canola_plants.csv): ethanol capacity is the corn
# use those sources quote (M bu/yr); COPA lists no crush capacities.
EXTRA_CRUSH = [
    {"name": "CHS Inc. (Evansville, WI plant)", "state": "WI", "city": "Evansville", "status": "Proposed", "lat": 42.778, "lon": -89.299, "mbu": 80.0},
    {"name": "ADM", "state": "ON", "city": "Windsor", "status": "Run", "lat": 42.30, "lon": -83.03, "country": "CA"},
    {"name": "Bunge", "state": "ON", "city": "Hamilton", "status": "Run", "lat": 43.26, "lon": -79.87, "country": "CA"},
    {"name": "Bunge", "state": "QC", "city": "Becancour", "status": "Run", "lat": 46.36, "lon": -72.43, "country": "CA"},
    {"name": "Bunge", "state": "MB", "city": "Altona", "status": "Run", "lat": 49.10, "lon": -97.56, "country": "CA"},
    {"name": "Bunge", "state": "MB", "city": "Ste. Agathe", "status": "Run", "lat": 49.57, "lon": -97.17, "country": "CA"},
    {"name": "Bunge", "state": "MB", "city": "Harrowby", "status": "Run", "lat": 50.30, "lon": -101.20, "country": "CA"},
    {"name": "Cargill", "state": "SK", "city": "Regina", "status": "Run", "lat": 50.45, "lon": -104.61, "country": "CA"},
    {"name": "Richardson", "state": "AB", "city": "Lethbridge", "status": "Run", "lat": 49.69, "lon": -112.84, "country": "CA"},
]
EXTRA_ETHANOL = [
    {"name": "Suncor St. Clair", "state": "ON", "city": "Mooretown", "status": "Run", "lat": 42.8945, "lon": -82.4736, "mbu": 40.0, "country": "CA"},
    {"name": "IGPC Ethanol", "state": "ON", "city": "Aylmer", "status": "Run", "lat": 42.7686, "lon": -80.9831, "mbu": 15.0, "country": "CA"},
    {"name": "Greenfield Global", "state": "ON", "city": "Chatham", "status": "Run", "lat": 42.4048, "lon": -82.1910, "country": "CA"},
    {"name": "Greenfield Global", "state": "ON", "city": "Johnstown", "status": "Run", "lat": 44.7253, "lon": -75.4936, "mbu": 20.0, "country": "CA"},
]


# Changes since the plant lists were made. Incobrasa Gilman IL: ~$250M expansion opened June 22 2026 (the crush list still has 36M bu;
# reports cite ~43M bu before and ~98-100M after, one ~300,000 bu/day extraction line, TPW rail loop), biodiesel 75 -> 170M gal in early
# Oct 2026. Capacity is the lower end of the reported range; figures are from press coverage Kolten supplied, not company filings.
UPDATES = [
    {"match": ("Incobrasa", "Gilman", "IL"), "set": {"mbu": 98.0, "note": "Expanded June 2026: ~43 to ~98 M bu/yr (list had 36); biodiesel 75 to 170 M gal/yr Oct 2026"}},
    # plants the list still shows as Build that Kolten says are live (10-29)
    {"match": ("SDSP", "Mitchell", "SD"), "set": {"status": "Run", "note": "Now live (list had Build)"}},
    {"match": ("Ag Processing", "David City", "NE"), "set": {"status": "Run", "note": "Now live (list had Build)"}},
    {"match": ("Louis Dreyfus", "Upper Sandusky", "OH"), "set": {"status": "Run", "note": "Now live (list had Build)"}},
    {"match": ("WSBCP", "Waupun", "WI"), "set": {"status": "Run", "note": "Now live (list had Proposed)"}},
    # no longer proposed (Kolten, 10-29): kept in the data as Cancelled, which draws with the closed plants (off by default)
    {"match": ("Moberly", "Moberly", "MO"), "set": {"status": "Cancelled", "note": "No longer proposed"}},
    {"match": ("St. Lawrence Soyway", "Massena", "NY"), "set": {"status": "Cancelled", "note": "No longer proposed"}},
    {"match": ("Green Plains", "Obion", "TN"), "set": {"status": "Cancelled", "note": "No longer proposed"}},
]


def main():
    pts = {"crush": [], "ethanol": [], "shipper": [], "river": []}
    gaz = _gazetteer()
    miss = []
    eth = pd.read_excel(ETHANOL_XLSX, header=1)
    for _, r in eth.iterrows():
        _add(pts["ethanol"], gaz, miss, r["COMPANY"], r["ST"], r["CITY"], r.get("STATUS"),
             cls=None if pd.isna(r.get("CLASS")) else str(r["CLASS"]), mgy=_num(r.get("Ethanol (Gallons)"), 1e6))
    cr = pd.read_excel(CRUSH_XLSX, sheet_name=0)
    for _, r in cr.iterrows():
        _add(pts["crush"], gaz, miss, r["COMPANY"], r["ST"], r["CITY"], r.get("STATUS"), mbu=_num(r.get("ANNUAL CAPACITY"), 1e6))
    # river loading facilities: the basis tracker's River Terminal tags joined to its geocoded pins (its archive of every location it has bid)
    coords = {(c["provider"], c["location"]): c for c in _load(os.path.join(TRACKER, "coords_seed.json"))}
    for t in _load(os.path.join(TRACKER, "facility_tags_seed.json")):
        c = coords.get((t["provider"], t["location"]))
        if t["facility_type"] == "River Terminal" and c and c.get("lat") is not None:
            pts["river"].append({"name": t["location"] if t["location"].startswith(t["provider"]) else f'{t["provider"]} {t["location"]}',
                                 "state": t.get("state") or c.get("state") or "",
                                 "lat": round(c["lat"], 4), "lon": round(c["lon"], 4)})
    pts["crush"].extend(EXTRA_CRUSH)
    pts["ethanol"].extend(EXTRA_ETHANOL)
    for u in UPDATES:
        name, city, st = u["match"]
        hit = [r for k in ("crush", "ethanol") for r in pts[k] if name.lower() in r["name"].lower() and r["city"] == city and r["state"] == st]
        assert hit, f"update matched nothing: {u['match']}"
        for r in hit:
            r.update(u["set"])
    place = _load(os.path.join(DIR, "place_coords.json"))["rows"]
    for r in _load(os.path.join(DIR, "bnsf_shippers.json"))["rows"]:
        if r.get("lat") is not None and r.get("state") not in ("AB", "SK", "MB", "BC"):
            pts["shipper"].append({"name": r["name"], "state": r["state"], "road": "BNSF", "lat": round(r["lat"], 4),
                                   "lon": round(r["lon"], 4), "shuttle": bool(r.get("shuttle"))})
    for r in _load(os.path.join(DIR, "cn_origins.json"))["rows"]:
        if r.get("lat") is None:
            continue
        pts["shipper"].append({"name": r["name"], "state": r["state"], "road": "CN", "lat": round(r["lat"], 4), "lon": round(r["lon"], 4)})
    up_miss = []
    for r in _load(os.path.join(DIR, "up_shuttle.json"))["origins"]:            # UP's grain shuttle loaders (program 4052-A, as issued Oct 2023)
        city = re.sub(r"\s*\(.*$", "", r["city"]).strip()                          # "ALBION (NCRC)": the short line serving it is in the name
        p = gaz.get((r["state"], _norm(city))) or place.get(f'{city.upper()}|{r["state"]}')
        if p:
            pts["shipper"].append({"name": r["company"].title(), "state": r["state"], "road": "UP", "lat": round(p[0], 4), "lon": round(p[1], 4),
                                   "cars": r["cars"], "shuttle": True})
        else:
            up_miss.append(f'{r["company"]} ({r["city"]}, {r["state"]})')
    print("UP loaders with no coordinates:", up_miss)
    for road, f in (("CSX", "csx_shippers"), ("NS", "ns_loaders")):
        for r in _load(os.path.join(DIR, f + ".json"))["rows"]:
            p = gaz.get((r["state"], _norm(r["city"]))) or place.get(f'{r["city"].upper()}|{r["state"]}')
            if p:
                pts["shipper"].append({"name": r["name"], "state": r["state"], "road": road, "lat": round(p[0], 4), "lon": round(p[1], 4)})
    with open(os.path.join(HERE, "data", "map_points.json"), "w") as fh:
        json.dump(pts, fh, separators=(",", ":"))
    print({k: len(v) for k, v in pts.items()})
    print("no coordinates:", miss)


if __name__ == "__main__":
    main()
