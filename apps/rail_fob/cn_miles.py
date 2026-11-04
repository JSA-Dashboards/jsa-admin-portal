"""
Rail miles to the Gulf for the CN fuel surcharge (Kolten, 2026-10-28: "check on CN FSC ... I believe it should be added").

CN's fuel surcharge (tariff CN 7403, rail_fsc.PROGRAMS["CN"]) is $/car-MILE, so it needs each origin's miles to the Gulf
Exports Group, which CN gives only through its Get Rail Miles tool (an eBusiness login; its public price-documents pages ask for
a visitor registration). What can be checked — USDA AMS's AgTransport tariff dataset (data/usda_cn_tariff.json) carries CN's own
route miles and the surcharge CN billed:
  * Gibson City, IL -> Reserve, LA is 870 miles and CN billed $0.825/mile in Oct 2026 = $717.75 a car (the USDA Grain
    Transportation Report's $718). That is the real mileage (ANCHOR_MILES). It confirms the surcharge is ADDED to the tariff rate.
    (An earlier version took 983 miles from CN's page figure $0.7303/mile; the billed rate is 1.1298 x that, so 983 was wrong.)
  * Ida Grove, IA -> Convent, LA is 1,376 miles (USDA), and Minneapolis -> New Orleans 1,277. Both fit going through Chicago on the
    straight-line distance to Chicago (C_CHICAGO = 1.0): Champaign + 136 (Chicago-Champaign) + the great-circle miles to Chicago.
  * Everything else is estimated from the origin's place coordinates (data/rail_directory/place_coords.json, Census centroids).
    Champaign is ~33 miles south of Gibson City on the same line (837). Origins in IA / WI / MI / MN go via Chicago as above; the
    rest sit on or near the Illinois Central line, so miles = Champaign's +/- 1.10 x the great-circle miles to Champaign (+ north of
    it, - south; 1.10 is what Chicago-Champaign's 136 rail miles vs 124 great-circle gives). Judgement beyond those two checks, so
    treat an estimate as good to roughly 10% of the distance from Champaign, and prefer a typed figure.

Against a bid FOB Champaign the Champaign figure cancels: FOB(origin) = bid + freight(Champaign) - freight(origin), so the
fuel surcharge only enters as FSC x (Champaign miles - origin miles), which needs just the distance difference, not
anybody's absolute miles.

Pure functions; no Streamlit.
"""
import bn_locator as BL

ANCHOR = ("GIBSON CITY", "IL")
ANCHOR_MILES = 870                         # USDA AgTransport route_mileage; $0.825 x 870 = $717.75 (Oct), $0.695 x 870 = $604.65 (Sep)
CHAMPAIGN_MILES = ANCHOR_MILES - 33        # Champaign is ~33 miles south of Gibson City on the same line
CHICAGO = (41.8781, -87.6298)
CHICAGO_TO_CHAMPAIGN = 136                 # rail miles, Illinois Central main line
VIA_CHICAGO = {"IA", "WI", "MI", "MN"}
C_CHICAGO = 1.0                            # Ida Grove IA (1,376 mi) and Minneapolis (1,277 to New Orleans) both fit ~1.0
C_DIRECT = 1.10
EST_NOTE = "estimated from the town's coordinates"

# Sidings that load at / are served from a town (Kolten, 2026-10-28): measured from that town.
ALIASES = {("COLES", "IL"): ("MATTOON", "IL"), ("DORANS", "IL"): ("MATTOON", "IL"), ("CLYMERS", "IN"): ("LOGANSPORT", "IN"),
           ("COCKRELL", "IL"): ("MATTOON", "IL"), ("GREEN'S SWITCH", "IL"): ("MATTOON", "IL"),     # Kolten, 2026-10-28: "just use Mattoon"
           ("INDIAN OAKS", "IL"): ("MATTOON", "IL")}


def coords(origin, state):
    origin, state = ALIASES.get((origin.upper(), state), (origin.upper(), state))
    return BL.place_coords().get(f"{origin}|{state}")


def delta_miles(origin, state):
    """Estimated miles from Champaign to the origin, along the way to the Gulf: positive = farther from the Gulf than
    Champaign. None when the origin has no coordinates."""
    xy = coords(origin, state)
    champ = coords("CHAMPAIGN", "IL")
    if xy is None or champ is None:
        return None
    if state in VIA_CHICAGO:
        return round(C_CHICAGO * BL.haversine(xy, CHICAGO) + CHICAGO_TO_CHAMPAIGN)
    d = C_DIRECT * BL.haversine(xy, champ)
    return round(d if xy[0] >= champ[0] else -d)


def miles_to_gulf(origin, state, champaign_miles=CHAMPAIGN_MILES):
    """(miles, note): the origin's rail miles to the Gulf Exports Group, or (None, why)."""
    if (origin.upper(), state) == ANCHOR:
        return ANCHOR_MILES, "USDA tariff table (Sept / Oct 2026)"
    if (origin.upper(), state) == ("CHAMPAIGN", "IL"):
        return champaign_miles, "about 33 miles south of Gibson City's 870"
    d = delta_miles(origin, state)
    if d is None:
        return None, "no coordinates for this station"
    alias = ALIASES.get((origin.upper(), state))
    return champaign_miles + d, (f"measured from {alias[0].title()}, {alias[1]}" if alias else EST_NOTE)
