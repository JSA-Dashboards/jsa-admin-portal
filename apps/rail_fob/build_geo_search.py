"""
Builds data/geo_search.json.gz for the Map tab's search box: US places, counties and ZIP code areas with a centre point, from the
Census 2023 gazetteer files (public domain). Entries are [label, lat, lon, kind] with kind p (place), c (county) or z (ZIP).
    python build_geo_search.py
"""
import gzip
import io
import json
import os
import re
import zipfile

import pandas as pd
import requests

BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_{}_national.zip"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "geo_search.json.gz")
_SUFFIX = re.compile(r"\s+(city|town|village|CDP|borough|municipality|township)$", re.I)


def _read(kind):
    z = zipfile.ZipFile(io.BytesIO(requests.get(BASE.format(kind), timeout=180).content))
    g = pd.read_csv(z.open(z.namelist()[0]), sep="\t", encoding="latin1", dtype={"GEOID": str})
    g.columns = [c.strip() for c in g.columns]
    return g


def main():
    out = []
    for r in _read("place").itertuples():
        out.append([f"{_SUFFIX.sub('', r.NAME)}, {r.USPS}", round(r.INTPTLAT, 4), round(r.INTPTLONG, 4), "p"])
    for r in _read("counties").itertuples():
        out.append([f"{r.NAME}, {r.USPS}", round(r.INTPTLAT, 4), round(r.INTPTLONG, 4), "c"])
    for r in _read("zcta").itertuples():
        out.append([r.GEOID, round(r.INTPTLAT, 4), round(r.INTPTLONG, 4), "z"])
    with gzip.open(OUT, "wt", encoding="utf8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(len(out), "entries,", os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()
