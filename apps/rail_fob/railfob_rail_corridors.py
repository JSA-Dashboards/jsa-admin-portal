"""
rail_corridors.py — Registry of rail corridors/sections, copied from the basis
tracker (basis-tracker-streamlit/rail_corridors.py). Pure display logic, no DB
access — kept in sync by hand if the basis tracker's registry changes.
"""
from __future__ import annotations

# Corridor registry (display/sort order) → rail carrier. "* Shuttle" rows are
# freight ($/car), placed per JSA: the BN shuttle just below BN PNW, the UP
# shuttle just below UP Group 3.
CORRIDORS = [
    ("CSX Columbus",     "CSX"),
    ("CSX Evansville",   "CSX"),
    ("CSX Freight",      "CSX"),
    ("NS Ft Wayne",      "NS"),
    ("UP Interior IA",   "UP"),
    ("UP Group 3",       "UP"),
    ("UP 110 Shuttle",   "UP"),
    ("UP Illinois (Dom)", "UP"),
    ("UP Illinois (Mex)", "UP"),
    ("BN Hereford",      "BNSF"),
    ("BN PNW",           "BNSF"),
    ("BN 110 Shuttle",   "BNSF"),
    ("BN PNW BE",        "BNSF"),
    ("BN PNW CP",        "BNSF"),
    ("BN COBO",          "BNSF"),
    ("CN 105s",          "CN"),
    ("CN 25's",          "CN"),
]
RAIL_BY_CORRIDOR = {n: r for n, r in CORRIDORS}
CORRIDOR_ORDER   = {n: i for i, (n, _) in enumerate(CORRIDORS)}

# Section grouping for the FOB sheet (matches the basis tracker's Rail FOB tab).
MANUAL_SECTIONS = [
    ("Eastern Rail",     ["CSX Columbus", "CSX Evansville", "NS Ft Wayne", "CSX Freight"]),
    ("Gulf Export Rail", ["CN 105s", "CN 25's"]),
    ("UP Western Rail",  ["UP Group 3", "UP Interior IA", "UP Illinois (Dom)",
                           "UP Illinois (Mex)", "UP 110 Shuttle"]),
    ("BN Western Rail",  ["BN Hereford", "BN PNW", "BN COBO", "BN 110 Shuttle",
                           "BN PNW BE", "BN PNW CP"]),
]

PALMETTO_SECTIONS = [
    ("Palmetto · CSX / NS (live)", ["COL, OH Corn 90's", "EVILLE, Corn- 90's",
                                     "NS FT. WAYNE, IN Corn- 105's", "COL, OH Beans 90's"]),
]

# Display-name overrides for markets whose stored name differs from what
# should print on the sheet.
RAIL_DISPLAY = {
    "BN PNW CP":         "CP PNW",
    "UP Illinois (Dom)": "Allen Station (Dom)",
    "UP Illinois (Mex)": "Allen Station (Mex)",
}

RAIL_COLORS = {"CSX": "#0693e3", "NS": "#7c3aed", "UP": "#d97706",
               "BNSF": "#16a34a", "CN": "#b91c1c"}
