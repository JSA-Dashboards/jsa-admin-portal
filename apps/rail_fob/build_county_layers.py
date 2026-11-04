"""
Builds the Map tab's production overlay files in data/:
  county_geo.json         simplified county polygons (Plotly's public Census-derived counties GeoJSON), clockwise exteriors
  county_prod_avg.json    {crop: {fips: 5-year average production, bu}}, the crop years used, names {fips: "County, ST"}
  state_lines.json        state boundary segments (from the basis tracker's outline file)
NASS county production comes from the basis tracker's committed heat files (data/heat/county_production.csv.gz, withheld counties
already filled by its heat_build.py); refresh those there first, then re-run this.
    python build_county_layers.py
"""
import gzip
import json
import os

import pandas as pd
import requests
from shapely.geometry import mapping, shape
from shapely.geometry.polygon import orient

HERE = os.path.dirname(os.path.abspath(__file__))
TRACKER = os.path.join(HERE, "..", "basis-tracker-streamlit")
RMA = os.path.join(HERE, "..", "rma-production-map", "data")
GEO_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
YEARS = 5


def _round(obj):
    if isinstance(obj, (list, tuple)):
        return [_round(o) for o in obj]
    return round(obj, 3)


def main():
    gj = requests.get(GEO_URL, timeout=120).json()
    feats = []
    for f in gj["features"]:
        g = shape(f["geometry"]).simplify(0.01, preserve_topology=True)
        if g.is_empty:
            continue
        polys = [orient(p, -1.0) for p in (g.geoms if g.geom_type == "MultiPolygon" else [g])]
        geom = mapping(polys[0] if len(polys) == 1 else type(g)(polys))
        feats.append({"type": "Feature", "id": f["id"], "geometry": {"type": geom["type"], "coordinates": _round(geom["coordinates"])}})
    with open(os.path.join(HERE, "data", "county_geo.json"), "w") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh, separators=(",", ":"))

    prod = pd.read_csv(os.path.join(TRACKER, "data", "heat", "county_production.csv.gz"), dtype={"fips": str})
    names = pd.read_csv(os.path.join(RMA, "census_county_fips.csv"), dtype=str)
    nm = {r.state_fips + r.county_fips: f"{r.county_name}, {r.state}" for r in names.itertuples()}
    out = {"years": {}, "avg": {}, "names": nm}
    for crop, g in prod.groupby("crop"):
        yrs = sorted(g["year"].unique())[-YEARS:]
        out["years"][crop] = [int(y) for y in yrs]
        out["avg"][crop] = {k: round(v) for k, v in g[g["year"].isin(yrs)].groupby("fips")["value"].mean().items() if v > 0}
    with open(os.path.join(HERE, "data", "county_prod_avg.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))

    with gzip.open(os.path.join(TRACKER, "data", "maps", "us_geometry.json.gz"), "rt") as fh:
        lines = json.load(fh)["state_lines"]
    with open(os.path.join(HERE, "data", "state_lines.json"), "w") as fh:
        json.dump(lines, fh, separators=(",", ":"))
    print(len(feats), "counties;", {c: len(v) for c, v in out["avg"].items()}, out["years"])


if __name__ == "__main__":
    main()
