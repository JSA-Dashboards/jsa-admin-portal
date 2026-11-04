"""
Any BN origin's freight and FOB, not only the 13 on the freight sheet (Kolten, 2026-10-28: "use the same logic to display
what a location's FOB value is if it's selected from the drop down list ... estimate miles from lat/lon").

BN freight = face rate + lane miles x that month's FSC $/mile + the BN Cars premium (freight_data.bn_build_row). The
BNSF price list in data/rail_directory/bn_shuttle_rates.json has a face rate for ~400 origins but no miles, so the
miles are ESTIMATED from the origin's coordinates in the BNSF shippers directory: miles = a + b x great-circle miles
to a fixed point, with a, b and the point fitted to the 13 origins whose real BN lane miles are on the freight sheet
(tests/test_bn_locator.py refits them). The fit is good to roughly +/-70 miles on those 13, about a cent a bushel at
today's FSC; it is least reliable far from them (the calibration box below), so a typed mileage always wins.

Face rates: the sheet's PNW rates are the price list's "DEST GRP 50 PNW" 286K / 5,001+ cu ft column plus $200 a car,
exactly, for every seeded origin that is on the list. Its Hereford rates are the list's column plus $0-$200 that varies by
origin, so the average of those gaps (hereford_adder) stands in, and is editable in the lookup.

Pure functions; no Streamlit. Seeded origins always use the sheet's own rates and miles.
"""
import json
import math
import os
from functools import lru_cache

_DIR = os.path.join(os.path.dirname(__file__), "data", "rail_directory")

PNW_GROUP = "DEST GRP 50 PNW"
PNW_ADDER = 200           # sheet face rate - price list rate, PNW (exact for all 7 seeded origins on the list)
RATE_FIELD = "r286_5001"  # 286K lb, 5,001+ cu ft: the column the freight sheet's rates come from

# miles = a + b x great-circle miles from the lane's point. PNW: Spokane. Hereford: a point in southern Kansas, since the
# lane runs through Kansas rather than straight to Hereford, TX (a straight line to Hereford fits far worse).
LANES = {
    "pnw": {"point": (47.66, -117.40), "a": 437.0, "b": 1.222},
    "hereford": {"point": (37.0, -96.0), "a": 336.0, "b": 1.442},
}
CAL_BOX = {"lat": (39.0, 47.5), "lon": (-103.0, -88.0)}   # the 13 fitted origins sit inside this
EST_ERROR_MILES = 70


def haversine(a, b):
    """Great-circle miles between two (lat, lon) points."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(h))


def estimate_miles(lane, lat, lon):
    p = LANES[lane]
    return round(p["a"] + p["b"] * haversine((lat, lon), p["point"]))


def in_calibration(lat, lon):
    return CAL_BOX["lat"][0] <= lat <= CAL_BOX["lat"][1] and CAL_BOX["lon"][0] <= lon <= CAL_BOX["lon"][1]


def norm(name):
    """'COUNCIL BLUFFS, IA +' / 'Council Bluffs, IA' -> 'COUNCIL BLUFFS, IA' ('+' = inside switching limits)."""
    name = (name or "").replace("+", " ")
    return " ".join(name.upper().split())


def _split(name):
    city, _, st = norm(name).rpartition(",")
    return city.strip(), st.strip()


def _station_key(city):
    """The shippers directory abbreviates stations to 9 characters with no spaces."""
    return city.replace(" ", "")[:9]


@lru_cache(maxsize=1)
def _load(name):
    with open(os.path.join(_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def place_coords():
    """{'CITY|ST': (lat, lon)} — Census centroids for stations the shippers directory has no coordinates for
    (data/rail_directory/place_coords.json; also the CN tariff origins, cn_miles.py)."""
    return {k: tuple(v) for k, v in _load("place_coords.json")["rows"].items()}


def station_coords(shippers):
    """{(station key, state): (lat, lon)} — the mean of the elevators on that station, where the directory has coordinates."""
    acc = {}
    for r in shippers:
        if r.get("lat") is None or r.get("lon") is None or not r.get("station"):
            continue
        acc.setdefault((r["station"].replace(" ", "").upper(), r["state"]), []).append((r["lat"], r["lon"]))
    return {k: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)) for k, v in acc.items()}


def list_rates(rates):
    """{name: {'pnw': $/car or None, 'hereford': $/car or None}} straight off the BNSF price list (no adders)."""
    out = {}
    for r in rates["pnw"]:
        if PNW_GROUP in r["destination"] and r.get(RATE_FIELD) is not None:
            out.setdefault(norm(r["origin"]), {})["pnw"] = r[RATE_FIELD]
    for r in rates["hereford_origins"]:
        if r.get(RATE_FIELD) is not None:
            out.setdefault(norm(r["name"]), {})["hereford"] = r[RATE_FIELD]
    return out


def hereford_adder(seed_origins, listed):
    """Average (sheet - price list) Hereford face rate over the seeded origins on the list, to the nearest $10."""
    gaps = [o["herf_rate"] - listed[norm(o["origin"])]["hereford"] for o in seed_origins
            if "hereford" in listed.get(norm(o["origin"]), {})]
    return int(round(sum(gaps) / len(gaps), -1)) if gaps else 0


def default_hereford_adder(seed_origins):
    return hereford_adder(seed_origins, list_rates(_load("bn_shuttle_rates.json")))


def origins(seed_origins, adder=None, rates=None, shippers=None):
    """Every origin that can be looked up: {name: {name, state, pnw_rate, herf_rate, pnw_miles, herf_miles, coords,
    seeded, off_box, miles_note}}. Seeded origins carry the sheet's rates and miles; the rest the price list's rates (plus
    the adders) and miles estimated from the shippers directory's coordinates (None when it has none — the caller asks for
    a typed figure). A lane the origin has no rate for is None."""
    rates = rates or _load("bn_shuttle_rates.json")
    shippers = shippers or _load("bnsf_shippers.json")["rows"]
    listed = list_rates(rates)
    if adder is None:
        adder = hereford_adder(seed_origins, listed)
    coords = station_coords(shippers["rows"] if isinstance(shippers, dict) else shippers)
    places = place_coords()
    seeded = {norm(o["origin"]): o for o in seed_origins}
    out = {}
    for name in sorted(set(listed) | set(seeded)):
        city, st = _split(name)
        xy = coords.get((_station_key(city), st))
        from_place = xy is None and f"{city}|{st}" in places
        if from_place:
            xy = places[f"{city}|{st}"]
        row = {"name": name, "state": st, "coords": xy, "seeded": name in seeded, "off_box": False}
        if name in seeded:
            o = seeded[name]
            row.update(pnw_rate=o["pnw_rate"], herf_rate=o["herf_rate"], pnw_miles=o["pnw_miles"], herf_miles=o["herf_miles"],
                       miles_note="freight sheet")
        else:
            lr = listed[name]
            row.update(pnw_list=lr.get("pnw"), herf_list=lr.get("hereford"),
                       pnw_rate=lr["pnw"] + PNW_ADDER if "pnw" in lr else None,
                       herf_rate=lr["hereford"] + adder if "hereford" in lr else None,
                       pnw_miles=None, herf_miles=None, miles_note="")
            if xy:
                row["pnw_miles"] = estimate_miles("pnw", *xy)
                row["herf_miles"] = estimate_miles("hereford", *xy)
                row["off_box"] = not in_calibration(*xy)
                row["miles_note"] = ("estimated from the town's coordinates" if from_place
                                     else "estimated from the BNSF directory's coordinates")
            else:
                row["miles_note"] = "no coordinates for this station"
        out[name] = row
    return out
