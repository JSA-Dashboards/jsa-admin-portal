"""
Builds data/rail_lines.json for the Map tab: BTS NTAD North American Rail Network Lines, grouped by owner.
Public-domain US DOT data (ArcGIS FeatureServer). Pages through OBJECTID blocks (deep offsets error out on this service);
geometry is simplified and rounded so the file stays small.
    python build_rail_lines.py
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

URL = ("https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/"
       "NTAD_North_American_Rail_Network_Lines/FeatureServer/0/query")
BASE_OWNERS = ["CN", "UP", "BNSF", "CPKC", "CSXT", "NS", "TPW", "IAIS", "WSOR", "KO"]
# short lines that serve grain-belt plants and shippers (10-29 scan of the NTAD owners against the plant and shipper lists)
SHORT_LINES = ["RRVW", "NKCR", "IORY", "RCPE", "DMVW", "CVR", "CFE", "INRD", "TRRA", "KCTL", "ALS", "DN", "KYLE", "RJCW", "RJCC", "RJCM"]
OWNERS = BASE_OWNERS + SHORT_LINES
BBOX = "-125,24,-66,53"
BLOCK = 2000
OUT = os.path.join(os.path.dirname(__file__), "data", "rail_lines.json")


def _query(params):
    for attempt in range(8):
        try:
            r = requests.get(URL, params=params, timeout=180)
            r.raise_for_status()
            d = r.json()
            if "error" not in d:
                return d
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"query failed: {params['where']}")


def block(lo, owner_list=None):
    owners = ",".join(f"'{o}'" for o in (owner_list or OWNERS))
    out = {}
    d = _query({"where": f"OBJECTID>={lo} AND OBJECTID<{lo + BLOCK} AND RROWNER1 IN ({owners})", "outFields": "RROWNER1",
                "f": "json", "returnGeometry": "true", "geometry": BBOX, "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects", "outSR": 4326, "maxAllowableOffset": 0.01})
    if d.get("exceededTransferLimit"):
        raise RuntimeError(f"block {lo} exceeded the transfer limit; lower BLOCK")
    for f in d.get("features", []):
        for path in f["geometry"]["paths"]:
            out.setdefault(f["attributes"]["RROWNER1"], []).append([[round(x, 3), round(y, 3)] for x, y in path])
    return out


if __name__ == "__main__":
    import sys
    only = SHORT_LINES if "--short-lines" in sys.argv else None      # fetch just the short lines and merge them into the file
    owners = only or OWNERS
    top = _query({"where": "1=1", "returnIdsOnly": "true", "f": "json"})["objectIds"]
    hi = max(top)
    with ThreadPoolExecutor(6) as ex:
        parts = list(ex.map(lambda lo: block(lo, owners), range(0, hi + 1, BLOCK)))
    out = json.load(open(OUT)) if only else {}
    for o in owners:
        out[o] = []
    for p in parts:
        for o, v in p.items():
            out[o].extend(v)
    for o in owners:
        print(o, len(out[o]), "segments", flush=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(os.path.getsize(OUT) // 1024, "KB")
