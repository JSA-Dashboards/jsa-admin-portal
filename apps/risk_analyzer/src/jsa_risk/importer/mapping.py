"""Column-mapping target descriptors and the guess/preferredGuess matching algorithm,
ported from the HTML tool's IMPORT_TARGETS.
"""
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class ImportTarget:
    key: str
    label: str
    guess: re.Pattern
    preferred_guess: Optional[re.Pattern] = None


IMPORT_TARGETS: List[ImportTarget] = [
    ImportTarget("label", "Contract symbol (required)", re.compile(r"symbol|ticker|contract|product|commod|instrument", re.I),
                 re.compile(r"^instrument$", re.I)),
    ImportTarget("type", "Type (call/put/future)", re.compile(r"type|call.*put|c/p|right", re.I)),
    ImportTarget("strike", "Strike (cents/bu; blank = futures position)", re.compile(r"strike", re.I)),
    ImportTarget("expiryDate", "Expiration date (options only)", re.compile(r"expir|maturity|exp\.?\s*date|dte|days", re.I)),
    ImportTarget("qty", "Quantity — unsigned contract count", re.compile(r"qty|quantity|lots|contracts|size", re.I),
                 re.compile(r"^qty$", re.I)),
    ImportTarget("positionDir", "Position direction (optional)", re.compile(r"^position$", re.I)),
    ImportTarget("iv", "Implied vol % (optional)", re.compile(r"\biv\b|vol(atility)?|implied", re.I)),
    ImportTarget("entry", "Entry price / premium (optional)", re.compile(r"entry|premium|cost|paid|price", re.I),
                 re.compile(r"^price$", re.I)),
    ImportTarget("lastTick", "Last tick / mark (optional)", re.compile(r"last\s*tick|last\s*price|\bltp\b|\bmark\b", re.I)),
]


# Hardcoded so it's always available, regardless of whether IMPORT_PRESETS has been
# seeded in Snowflake -- matches the real QST "Orders and Positions Summary" export
# (Instrument/Call-Put/Strike/Expiration Date/Qty/Position/Price/Last Tick), not the
# sample-sheet placeholder names ("Symbol"/"Lots"/"Premium") the DB-seeded preset had
# been carrying by mistake.
QST_DEFAULT_MAPPING = {
    "label": "Instrument",
    "type": "Call/Put",
    "strike": "Strike",
    "expiryDate": "Expiration Date",
    "qty": "Qty",
    "positionDir": "Position",
    "iv": None,
    "entry": "Price",
    "lastTick": "Last Tick",
}


def match_header_idx(header_name: Optional[str], headers: List[str]) -> int:
    if not header_name:
        return -1
    target = header_name.strip().lower()
    for i, h in enumerate(headers):
        if h.strip().lower() == target:
            return i
    return -1


def auto_map(headers: List[str], remembered: Optional[dict]) -> dict:
    """Two-pass, first-match-wins matching: remembered mapping (exact name) > preferred
    (specific) regex > loose (generic) regex — mirrors the HTML tool's buildImportMapFields.
    """
    used = set()
    mapping: dict = {}
    for target in IMPORT_TARGETS:
        idx = match_header_idx((remembered or {}).get(target.key), headers) if remembered else -1
        if idx < 0 and target.preferred_guess:
            for i, h in enumerate(headers):
                if i not in used and target.preferred_guess.search(h):
                    idx = i
                    break
        if idx < 0:
            for i, h in enumerate(headers):
                if i in used:
                    continue
                if target.guess.search(h):
                    idx = i
                    break
        if idx >= 0:
            used.add(idx)
        mapping[target.key] = idx
    return mapping


def mapping_to_header_names(mapping: dict, headers: List[str]) -> dict:
    """Converts an {target_key: column_index} mapping into {target_key: header_name} —
    the shape actually persisted as a preset, so it still matches if column order changes."""
    result = {}
    for target in IMPORT_TARGETS:
        idx = mapping.get(target.key, -1)
        result[target.key] = headers[idx] if idx is not None and idx >= 0 and idx < len(headers) else None
    return result
