"""
State Level tab: the Illinois river rows as INDEXES (Kolten, 2026-11-09: "list out the average or indexed values for river using the Basis Tracker
for Zone 2, 3, 5 and STL; use the state ethanol index bids, not individuals").

The Basis Tracker tags each river terminal with a `delivery_zone` in location_meta (IL: Zone 1, 2, 3 and 5). Zones 2, 3 and 5 are those tags; STL is the
St. Louis-area terminals, pulled OUT of the tracker's Zone 5 (which lumps them with Havana / Beardstown / Meredosia), plus ADM Sauget (untagged). A
group's index for a delivery month is the simple average of its terminals' corn bids for it (a terminal's own bids for the month averaged first).
Terminals the tracker has no zone for (the ADM ones, apart from Sauget) are not in any group. Pure functions; no Streamlit.
"""
import ethanol_index as EI

ZONES = ("Zone 2", "Zone 3", "Zone 5")
STL_TERMINALS = {("Bunge", "Fairmont City"), ("Bunge", "Fairmont City, IL"), ("CGB", "CGB - Cahokia"), ("CHS", "CHS Cahokia"),
                 ("Cargill", "East St. Louis"), ("ADM", "Sauget, IL")}
IL_RIVER_ORDER = ("Zone 2", "Zone 3", "Zone 5", "STL")
# Indiana (Kolten, 2026-11-10: "for IN use Evansville and Louisville for river values", then "add ADM Mt Vernon into the avg", "keep Louisville as 1"): Evansville =
# ADM's four Evansville terminals plus ADM Mt. Vernon (Newburgh / Rockport are not shown); Louisville = CGB Louisville (KY) and CGB Jeffersonville (IN, across the river) —
# the tracker types those two as country elevators, and has no Louisville river terminal.
IN_GROUPS = (("Evansville", ("Evansville, IN", "Mt. Vernon, IN")), ("Louisville", ("CGB LOUISVILLE", "CGB JEFFERSONVILLE")))
IN_EXTRA_LOCATIONS = ("CGB LOUISVILLE", "CGB JEFFERSONVILLE")
RIVER_ORDER = {"IL": IL_RIVER_ORDER, "IN": tuple(g for g, _t in IN_GROUPS)}       # the states whose State Level river rows are indexes

# the Louisville bids sit outside Indiana (and outside the river-terminal type), so they are read by name
EXTRA_SQL = """
WITH latest AS (
  SELECT s.id, s.provider, s.location, s.timestamp,
         ROW_NUMBER() OVER (PARTITION BY s.provider, s.location ORDER BY s.timestamp DESC) AS rn
  FROM snapshots s
  JOIN location_meta lm ON lm.provider = s.provider AND lm.location = s.location
  WHERE lm.location IN (%s, %s) AND s.timestamp >= %s
)
SELECT l.provider, l.location, lm.state, lm.facility_type, lm.delivery_zone, r.grain, r.delivery_month, r.futures_symbol, r.basis_cents, r.is_spot
FROM latest l
JOIN location_meta lm ON lm.provider = l.provider AND lm.location = l.location
JOIN snapshot_rows r ON r.snapshot_id = l.id
WHERE l.rn = 1 AND r.basis_cents IS NOT NULL
"""


def group_of(provider, location, zone):
    """'STL' for the St. Louis-area terminals, else the tracker's zone when it is one of ZONES, else None."""
    if (provider, location) in STL_TERMINALS:
        return "STL"
    return zone if zone in ZONES else None


def group_of_in(location):
    """The Indiana river group of a location by its name (ADM Evansville x4; CGB Louisville / Jeffersonville), or None."""
    for g, towns in IN_GROUPS:
        if any(location.startswith(t) for t in towns):
            return g
    return None


def river_index(rows, state="IL"):
    """{group: {(year, month): (average basis ¢, terminals)}} from LOC_SQL's rows (river terminals only): Illinois = Zone 2 / Zone 3 / Zone 5 / STL,
    Indiana = Evansville and Mt. Vernon / Newburgh / Rockport."""
    river = [r for r in rows if r.get("facility_type") == "River Terminal" or (state == "IN" and r.get("location") in IN_EXTRA_LOCATIONS)]
    zone = {(r["provider"], r["location"]): r.get("delivery_zone") for r in river}
    groups = {}
    for (_ft, prov, loc), series in EI.location_series(river).items():
        g = group_of_in(loc) if state == "IN" else group_of(prov, loc, zone.get((prov, loc)))
        if g:
            for ym, v in series.items():
                groups.setdefault(g, {}).setdefault(ym, []).append(v)
    return {g: {ym: (sum(vs) / len(vs), len(vs)) for ym, vs in months.items()} for g, months in groups.items()}
