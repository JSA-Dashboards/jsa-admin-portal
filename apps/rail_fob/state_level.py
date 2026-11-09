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


def group_of(provider, location, zone):
    """'STL' for the St. Louis-area terminals, else the tracker's zone when it is one of ZONES, else None."""
    if (provider, location) in STL_TERMINALS:
        return "STL"
    return zone if zone in ZONES else None


def river_index(rows):
    """{group: {(year, month): (average basis ¢, terminals)}} for Zone 2 / Zone 3 / Zone 5 / STL, from LOC_SQL's rows (river terminals only)."""
    river = [r for r in rows if r.get("facility_type") == "River Terminal"]
    zone = {(r["provider"], r["location"]): r.get("delivery_zone") for r in river}
    groups = {}
    for (_ft, prov, loc), series in EI.location_series(river).items():
        g = group_of(prov, loc, zone.get((prov, loc)))
        if g:
            for ym, v in series.items():
                groups.setdefault(g, {}).setdefault(ym, []).append(v)
    return {g: {ym: (sum(vs) / len(vs), len(vs)) for ym, vs in months.items()} for g, months in groups.items()}
