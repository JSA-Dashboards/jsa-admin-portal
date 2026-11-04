"""
UP origin spreads (Kolten, 2026-11-02, from his own description of how UP origins trade):

  * Group 3 is based off North Bend, NE; Interior IA off Joice, IA. Interior IA typically trades an 8c DISCOUNT to Group 3.
  * Some IA / MN origins spread off Group 3 at a smaller discount than that paper spread, so they trade Group 3 and apply the lesser
    discount: Brewster and Heron Lake MN trade 3c off Group 3 AND 3c off Interior IA (so mostly Group 3), Savage MN 12c off Group 3 /
    7c off Interior IA, Sloan IA 3c off Group 3; Randolph MN 8c, Hope MN 7c and Welcome MN 6c off Interior IA.
  * Most other IA origins are par or a small discount to Interior IA, most other Nebraska origins par or a small discount to Group 3
    (the small discount isn't stated, so it is taken as par).
  * Allen Station (IL) is posted as its own bids: typically 20c better than Interior IA to Mexico and about 30c to domestic destinations.

So an origin's FOB is a base bid LESS its discount — the discount is the freight spread, like the CSX / NS ones — and an origin with
only one stated discount takes the other through the 8c paper spread. Pure functions; no Streamlit.
"""

IIA_UNDER_G3 = 8                       # Interior IA's typical discount to Group 3, cents
BASES = {"Group 3": "UP Group 3", "Interior IA": "UP Interior IA"}      # base -> bid market
BASE_POINTS = {"Group 3": "North Bend, NE", "Interior IA": "Joice, IA"}
ALLEN_OVER_IIA = {"Mexico": 20, "Domestic": 30}                            # typical, cents (Allen better than Interior IA)
ALLEN_MARKETS = {"Mexico": "UP Illinois (Mex)", "Domestic": "UP Illinois (Dom)"}

# (name, state, discount to Group 3, discount to Interior IA, note) — None = not stated, taken through the 8c paper spread
ORIGINS = [
    ("North Bend, NE", "NE", 0, None, "the Group 3 base"),
    ("Joice, IA", "IA", None, 0, "the Interior IA base"),
    ("Brewster, MN", "MN", 3, 3, "3c off both, so mostly Group 3"),
    ("Heron Lake, MN", "MN", 3, 3, "3c off both, so mostly Group 3"),
    ("Savage, MN", "MN", 12, 7, "12c off Group 3, 7c off Interior IA"),
    ("Randolph, MN", "MN", None, 8, "8c off Interior IA"),
    ("Hope, MN", "MN", None, 7, "7c off Interior IA"),
    ("Welcome, MN", "MN", None, 6, "6c off Interior IA"),
    ("Sloan, IA", "IA", 3, None, "3c off Group 3"),
]
# every other origin in these states: par to its state's base (a small discount isn't stated)
GENERIC = {"IA": ("Interior IA", 0), "NE": ("Group 3", 0)}


def spreads(g3, iia):
    """(discount to Group 3, discount to Interior IA, g3 derived?, iia derived?) — a missing side comes through the paper spread."""
    if g3 is None and iia is None:
        return None, None, False, False
    if g3 is None:
        return iia + IIA_UNDER_G3, iia, True, False
    if iia is None:
        return g3, g3 - IIA_UNDER_G3, False, True
    return g3, iia, False, False


def origin_spreads():
    """[{name, state, g3, iia, g3_derived, iia_derived, note}] for the named origins."""
    out = []
    for name, state, g3, iia, note in ORIGINS:
        a, b, da, db = spreads(g3, iia)
        out.append({"name": name, "state": state, "g3": a, "iia": b, "g3_derived": da, "iia_derived": db, "note": note})
    return out


def generic_spreads(state):
    """The par-to-base spreads for an unnamed origin in `state`, or None where there is no stated rule (MN, SD, ...)."""
    if state not in GENERIC:
        return None
    base, d = GENERIC[state]
    a, b, da, db = spreads(d if base == "Group 3" else None, d if base == "Interior IA" else None)
    return {"name": f"Other {state} origin", "state": state, "g3": a, "iia": b, "g3_derived": da, "iia_derived": db,
            "note": f"par to {base} (a small discount isn't modelled)"}


def fob(spread, base, bid):
    """The origin's FOB on a base: that base's bid less its discount; None where either is missing."""
    d = spread["g3"] if base == "Group 3" else spread["iia"]
    return None if bid is None or d is None else bid - d
