"""
Extra rail miles behind the NS fuel surcharge (Kolten, 2026-10-28: "we need to add FSC for NS and CSX as well").

NS's freight in ns_freight_seed.json is a SPREAD to NS Ft Wayne, the one bid market (Ft Wayne = 0, a few origins east / south of
it negative), in $/bu to three destination regions (GA, NC/SC/VA, East). So the surcharge only enters as the DIFFERENCE in rail
miles to the destination between the origin and Ft Wayne:

    FOB(origin) = Ft Wayne bid - (spread + FSC $/car-mile x (miles(origin -> dest) - miles(Ft Wayne -> dest)) / bu per car x 100)

Nobody publishes those miles here, so they are estimated: great-circle miles to one representative town per region
(GA Gainesville, NC/SC/VA Greensboro, East Harrisburg) x 1.10 for rail circuity. Check: across the 66 seeded origins with
coordinates, the seed's spreads track that great-circle difference (R^2 0.7-0.8 per region), which is also what says the seed is a
spread to Ft Wayne; the representative towns and the 1.25 are judgement, so treat an estimate as rough (a few tens of miles ~ a
few tenths of a cent at NS's $/mile).

Pure functions; no Streamlit.
"""
import re

import bn_locator as BL

FTW = ("FT WAYNE", "IN")
C_RAIL = 1.10                                      # CN's USDA-checked routes run 1.0-1.1 x great circle (Chicago-Champaign: 136 rail vs 124)
DEST = {"ga": (34.30, -83.82), "ncscva": (36.07, -79.79), "east": (40.27, -76.88)}
SIBLING = {("DYER", "OH"): ("FOSTORIA", "OH"),        # no coordinates of its own; same spreads as Beaverdam / Fostoria
           ("WTNN", "TN"): ("JACKSON", "TN")}          # West Tennessee Railroad: a shortline based in Jackson, TN (NS interchange at Jackson / Corinth)
EST_NOTE = "estimated from the town's coordinates"


def clean(origin):
    """'AMBOY (USRP)' -> 'AMBOY'; 'DES MOINES via IAIS' -> 'DES MOINES'; 'PLEASANT HILL, IA' -> 'PLEASANT HILL'."""
    return re.sub(r"\s*\(.*?\)|\s+via .*|,.*", "", origin).strip().upper()


def coords(origin, state):
    k = SIBLING.get((clean(origin), state), (clean(origin), state))
    return BL.place_coords().get(f"{k[0]}|{k[1]}")


def delta_miles(origin, state, field):
    """Estimated rail miles from the origin to the region's destination minus Ft Wayne's: positive = farther than Ft Wayne.
    `field` is 'ga' | 'ncscva' | 'east'. None when the origin has no coordinates."""
    xy, ftw = coords(origin, state), coords(*FTW)
    if xy is None or ftw is None:
        return None
    d = DEST[field]
    return round(C_RAIL * (BL.haversine(xy, d) - BL.haversine(ftw, d)))


def note(origin, state):
    if coords(origin, state) is None:
        return "no coordinates for this station"
    k = SIBLING.get((clean(origin), state))
    return f"measured from {k[0].title()}, {k[1]}" if k else EST_NOTE
