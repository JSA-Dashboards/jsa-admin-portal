"""
CN's tariff history for the Gibson City, IL -> Reserve, LA lane (the lane USDA AMS publishes monthly): the committed snapshot
(data/usda_cn_tariff.json), refreshed from USDA's public AgTransport API (dataset 3az4-jkr6, no key needed; USDA_APP_TOKEN is sent if set)
so a month USDA has since added — the actual November rate, say — replaces last year's stand-in without a code change.
A live month overrides the snapshot's; any failure (offline, USDA down, a changed shape) leaves the snapshot. Cached 6 hours in process.
Set USDA_CN_LIVE=0 to read only the snapshot (the unit tests do).
"""
import json
import os
import time
import urllib.parse
import urllib.request

URL = "https://agtransport.usda.gov/resource/3az4-jkr6.json"
TTL = 6 * 3600
_cache = {"t": 0.0, "rows": None}


def snapshot():
    with open(os.path.join(os.path.dirname(__file__), "data", "usda_cn_tariff.json"), encoding="utf-8") as f:
        return json.load(f)["rows"]


def fetch(timeout=10):
    """{'YYYY-MM': {'Railroad', 'Private', 'fsc_per_mile', 'miles'}} from USDA's API, or {} on any failure."""
    q = urllib.parse.urlencode({"$where": "railroad='CN' AND commodity='Corn' AND origin='Gibson City, IL'", "$limit": "500", "$order": "date"})
    req = urllib.request.Request(URL + "?" + q)
    if os.environ.get("USDA_APP_TOKEN"):
        req.add_header("X-App-Token", os.environ["USDA_APP_TOKEN"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        out = {}
        for r_ in data:
            e = out.setdefault(r_["date"][:7], {"fsc_per_mile": float(r_["fsc_per_mile"]), "miles": int(r_["route_mileage"])})
            e[r_["car_ownership"]] = int(r_["tariff_per_car"])
        return {m: e for m, e in out.items() if "Railroad" in e and "Private" in e}
    except Exception:
        return {}


def series():
    """The snapshot with any live months laid over it."""
    rows = snapshot()
    if os.environ.get("USDA_CN_LIVE", "1") == "0":
        return rows
    if _cache["rows"] is None or time.time() - _cache["t"] > TTL:
        _cache["rows"], _cache["t"] = fetch(), time.time()
    return {**rows, **_cache["rows"]} if _cache["rows"] else rows
