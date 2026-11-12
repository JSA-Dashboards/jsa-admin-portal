"""
State Level tab: the river / export rows as INDEXES, state by state (Kolten, 2026-11-09 onwards: "list out the average or indexed values for river using the Basis
Tracker ...; use the state ethanol index bids, not individuals"). Each cleaned-up state has its own spec here:

  IL  Zone 2, Zone 3, Zone 5 and STL — the tracker's `delivery_zone` tags on its Illinois river terminals (Zones 2, 3 and 5), with STL (the St. Louis-area
      terminals) pulled OUT of the tracker's Zone 5, which lumps them with Havana / Beardstown / Meredosia, plus ADM Sauget (untagged). Terminals with no zone
      (the ADM ones, apart from Sauget) are in no group.
  IN  Evansville (ADM's four Evansville terminals and ADM Mt. Vernon) and Louisville (CGB Louisville, KY and CGB Jeffersonville, IN — the tracker types both as
      country elevators and has no Louisville river terminal).
  IA  Dubuque (ADM East Dubuque, ADM Grain — the only Dubuque location the tracker carries; it sits on the Illinois bank).
  MN  Winona (ADM Winona, CHS Winona) and Twin Cities (ADM St. Paul, and the CGB / CHS / Cargill Savage terminals).
  OH  Toledo (ADM Toledo export terminal, the two Andersons Toledo elevators) and Cincinnati (Cargill's Kellogg and River Road).
  IA  also Eastern / Western Iowa ethanol sub-indexes (split at 93.6 W, the Des Moines meridian).
  SD  no river rows; Eastern / Western South Dakota ethanol indexes (split at 97.5 W).
  ND  no river rows; Eastern (Red River Valley) / Western North Dakota ethanol indexes (split at 97.5 W).
  KS  Garden City region (every non-ethanol Kansas location the tracker has within 60 miles of Garden City) plus Northeast / Southwest Kansas ethanol indexes.
  NE  no river rows; Eastern / Central Nebraska ethanol indexes.

A group's index for a delivery month is the simple average of its locations' corn bids for it (a location's own bids for the month averaged first). Pure
functions plus the SQL; no Streamlit.
"""
import ethanol_index as EI

# ---- Illinois: the tracker's zone tags
ZONES = ("Zone 2", "Zone 3", "Zone 5")
STL_TERMINALS = {("Bunge", "Fairmont City"), ("Bunge", "Fairmont City, IL"), ("CGB", "CGB - Cahokia"), ("CHS", "CHS Cahokia"),
                 ("Cargill", "East St. Louis"), ("ADM", "Sauget, IL")}
IL_RIVER_ORDER = ("Zone 2", "Zone 3", "Zone 5", "STL")

# ---- the other cleaned-up states: named groups of (provider, location), read by name because the tracker leaves many of them untyped / in a neighbouring state
NAMED_GROUPS = {
    "IN": (("Evansville", (("ADM", "Evansville, IN (1st Ave.)"), ("ADM", "Evansville, IN (Broadway)"), ("ADM", "Evansville, IN (Ohio St.)"),
                           ("ADM", "Evansville, IN (River South)"), ("ADM", "Mt. Vernon, IN (Elevator)"))),
           ("Louisville", (("CGB", "CGB LOUISVILLE"), ("CGB", "CGB JEFFERSONVILLE")))),
    "IA": (("Dubuque", (("ADM", "East Dubuque, ADM Grain"),)),),
    "MN": (("Winona", (("ADM", "Winona, MN"), ("CHS", "Winona"))),
           ("Twin Cities", (("ADM", "St. Paul, MN (Elevator D)"), ("CGB", "CGB SAVAGE"), ("CHS", "Savage"), ("Cargill", "Savage")))),
    "OH": (("Toledo", (("ADM", "Toledo, OH"), ("Andersons", "Toledo - Edwin Dr"), ("Andersons", "Toledo - Kuhlman Dr"))),
           ("Cincinnati", (("Cargill", "Cincinnati Kellogg"), ("Cargill", "Cincinnati River Road")))),
}
# river-row group names per cleaned state, in display order (a state in here has no pickers; NE and KS have no river rows, KS has the Garden City region instead)
RIVER_ORDER = {"IL": IL_RIVER_ORDER, **{st: tuple(g for g, _m in groups) for st, groups in NAMED_GROUPS.items()}, "NE": (), "KS": (), "SD": (), "ND": ()}

# ---- state ethanol SUB-indexes (Kolten, 2026-11-10): the plants of a state split by where they sit. (label, test on (lat, lon)); a plant outside every box (West Nebraska)
# stays in the state Ethanol Index only. The tracker holds only four Kansas plants, so those indexes are one or two plants each.
ETHANOL_SUBINDEX = {
    "NE": (("Eastern NE index", lambda lat, lon: lon >= -97.7), ("Central NE index", lambda lat, lon: -100.5 <= lon < -97.7)),
    "IA": (("Eastern IA index", lambda lat, lon: lon >= -93.6), ("Western IA index", lambda lat, lon: lon < -93.6)),   # split at the Des Moines meridian
    "SD": (("Eastern SD index", lambda lat, lon: lon >= -97.5), ("Western SD index", lambda lat, lon: lon < -97.5)),   # James River valley and west vs the Big Sioux side
    "ND": (("Eastern ND index", lambda lat, lon: lon >= -97.5), ("Western ND index", lambda lat, lon: lon < -97.5)),   # Red River Valley vs the rest
    "KS": (("Northeast KS index", lambda lat, lon: lon >= -98.9), ("Southwest KS index", lambda lat, lon: lon < -98.9)),
}
# ---- a REGION value: every non-ethanol location of the state within `miles` of a centre
REGION = {"KS": ("Garden City region", (37.9717, -100.8727), 60)}

# every location of one state, whatever its type (Kansas: the region and the plants come from the same pull)
ALL_SQL = """
WITH latest AS (
  SELECT s.id, s.provider, s.location, s.timestamp,
         ROW_NUMBER() OVER (PARTITION BY s.provider, s.location ORDER BY s.timestamp DESC) AS rn
  FROM snapshots s
  JOIN location_meta lm ON lm.provider = s.provider AND lm.location = s.location
  WHERE lm.state = %s AND s.timestamp >= %s
)
SELECT l.provider, l.location, lm.state, lm.facility_type, lm.delivery_zone, lm.lat, lm.lon, r.grain, r.delivery_month, r.futures_symbol, r.basis_cents, r.is_spot
FROM latest l
JOIN location_meta lm ON lm.provider = l.provider AND lm.location = l.location
JOIN snapshot_rows r ON r.snapshot_id = l.id
WHERE l.rn = 1 AND r.basis_cents IS NOT NULL
"""


def named_members(state):
    """[(provider, location)] for a named-group state, flat."""
    return [m for _g, members in NAMED_GROUPS.get(state, ()) for m in members]


def named_sql(state):
    """(sql, params-before-since): the latest corn bids at the state's named locations, whatever their type or state in the tracker (a LEFT JOIN, since
    some — East Dubuque — have no location_meta row at all). Pass the params then `since`."""
    members = named_members(state)
    marks = ", ".join(["%s"] * len(members)) or "''"
    sql = f"""
WITH latest AS (
  SELECT s.id, s.provider, s.location, s.timestamp,
         ROW_NUMBER() OVER (PARTITION BY s.provider, s.location ORDER BY s.timestamp DESC) AS rn
  FROM snapshots s
  WHERE s.provider || '|' || s.location IN ({marks}) AND s.timestamp >= %s
)
SELECT l.provider, l.location, lm.state, lm.facility_type, lm.delivery_zone, lm.lat, lm.lon, r.grain, r.delivery_month, r.futures_symbol, r.basis_cents, r.is_spot
FROM latest l
LEFT JOIN location_meta lm ON lm.provider = l.provider AND lm.location = l.location
JOIN snapshot_rows r ON r.snapshot_id = l.id
WHERE l.rn = 1 AND r.basis_cents IS NOT NULL
"""
    return sql, tuple(f"{p}|{loc}" for p, loc in members)


def group_of(provider, location, zone):
    """Illinois: 'STL' for the St. Louis-area terminals, else the tracker's zone when it is one of ZONES, else None."""
    if (provider, location) in STL_TERMINALS:
        return "STL"
    return zone if zone in ZONES else None


def group_of_named(state, provider, location):
    """The named group of a location in a named-group state, or None."""
    for g, members in NAMED_GROUPS.get(state, ()):
        if (provider, location) in members:
            return g
    return None


def river_index(rows, state="IL"):
    """{group: {(year, month): (average basis ¢, locations)}} from the state's rows: Illinois = Zone 2 / Zone 3 / Zone 5 / STL (river terminals only), the
    named-group states = their groups."""
    if state == "IL":
        river = [r for r in rows if r.get("facility_type") == "River Terminal"]
        zone = {(r["provider"], r["location"]): r.get("delivery_zone") for r in river}
        of = lambda prov, loc: group_of(prov, loc, zone.get((prov, loc)))
        use = river
    else:
        of = lambda prov, loc: group_of_named(state, prov, loc)
        use = rows
    groups = {}
    for (_ft, prov, loc), series in EI.location_series(use).items():
        g = of(prov, loc)
        if g:
            for ym, v in series.items():
                groups.setdefault(g, {}).setdefault(ym, []).append(v)
    return {g: {ym: (sum(vs) / len(vs), len(vs)) for ym, vs in months.items()} for g, months in groups.items()}


def _average(per_location):
    """{(year, month): (average, locations)} from [{ym: value}, ...]."""
    months = {}
    for series in per_location:
        for ym, v in series.items():
            months.setdefault(ym, []).append(v)
    return {ym: (sum(vs) / len(vs), len(vs)) for ym, vs in months.items()}


def ethanol_subindex(rows, state):
    """{label: {(year, month): (average basis ¢, plants)}} for the state's ethanol sub-indexes (ETHANOL_SUBINDEX), from rows that carry lat / lon:
    each Corn Processing plant falls in the first box that contains it."""
    plants = [r for r in rows if r.get("facility_type") == "Corn Processing" and r.get("lat") is not None and r.get("lon") is not None]
    coords = {(r["provider"], r["location"]): (float(r["lat"]), float(r["lon"])) for r in plants}
    out = {}
    series = EI.location_series(plants)
    for label, test in ETHANOL_SUBINDEX.get(state, ()):
        members = [v for (_ft, prov, loc), v in series.items() if test(*coords[(prov, loc)])]
        if members:
            out[label] = _average(members)
    return out


def region_index(rows, state):
    """(label, {(year, month): (average basis ¢, locations)}) for the state's REGION value: every non-ethanol location within the radius, or None."""
    if state not in REGION:
        return None
    import bn_locator as BL
    label, centre, miles = REGION[state]
    near = [r for r in rows if r.get("facility_type") != "Corn Processing" and r.get("lat") is not None and r.get("lon") is not None
            and BL.haversine(centre, (float(r["lat"]), float(r["lon"]))) <= miles]
    return label, _average(EI.location_series(near).values())
