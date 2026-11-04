"""
Builds data/waterways.json for the Map tab: BTS NTAD Navigable Waterway Network Lines (USACE, 2018), lower 48, as
{river name: [polyline, ...]}. Public-domain US DOT data. Re-run to refresh.
    python build_waterways.py
"""
import json
import os
import time

import requests

URL = ("https://services5.arcgis.com/HDRa0B57OVrv2E1q/ArcGIS/rest/services/"
       "Navigable_Waterway_Network_Lines/FeatureServer/0/query")
OUT = os.path.join(os.path.dirname(__file__), "data", "waterways.json")

if __name__ == "__main__":
    out, offset = {}, 0
    while True:
        r = requests.get(URL, params={
            "where": "1=1", "outFields": "rivername", "f": "json", "returnGeometry": "true",
            "geometry": "-125,24,-66,50", "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
            "outSR": 4326, "maxAllowableOffset": 0.004, "resultOffset": offset, "resultRecordCount": 1000}, timeout=120)
        r.raise_for_status()
        d = r.json()
        feats = d.get("features", [])
        for f in feats:
            name = (f["attributes"].get("rivername") or "").strip().upper()
            for path in f["geometry"]["paths"]:
                out.setdefault(name, []).append([[round(x, 3), round(y, 3)] for x, y in path])
        if not feats:
            break
        offset += len(feats)
        print(offset, end=" ", flush=True)
        time.sleep(0.2)
    with open(OUT, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print("\n", len(out), "rivers,", os.path.getsize(OUT) // 1024, "KB")
