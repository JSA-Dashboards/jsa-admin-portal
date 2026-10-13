"""Turns valid staging rows into Position objects (back-filling missing IV/entry) and
commits them via positions_repo.replace_book — always replaces the whole book, same as
the original tool.
"""
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from jsa_risk.pricing.black76 import black76
from jsa_risk.pricing.stress import Position

from .staging import StagingRow, staging_row_valid


def positions_from_staging(
    staging_rows: List[StagingRow],
    get_contract_price: Callable[[str], float],
    snapshot_iv: Callable[[str], float],
    canonical_contract_key: Callable[[str], str],
    underlying_overrides: Optional[Dict[str, str]] = None,
) -> Tuple[List[Position], int]:
    """Returns (positions, estimated_iv_count). `underlying_overrides` maps a row's raw
    label to a manually-chosen canonical underlying key (e.g. "Z26") -- set on the import
    preview screen to fix one-off cases the automatic roll rule doesn't cover. Applied
    both to this import's price/IV lookups and persisted onto the resulting Position, so
    future re-pricing keeps respecting it."""
    overrides = underlying_overrides or {}
    positions: List[Position] = []
    estimated_count = 0

    for row in staging_rows:
        if not staging_row_valid(row):
            continue
        is_future = row.type == "future"
        override = overrides.get(row.label) or None
        canonical_key = override or canonical_contract_key(row.label)
        contract_f = get_contract_price(canonical_key)

        iv = row.iv
        iv_estimated = False
        if not is_future and iv is None:
            iv = snapshot_iv(canonical_key)
            iv_estimated = True
            estimated_count += 1

        entry = row.entry
        if entry is None:
            if is_future:
                entry = contract_f
            else:
                dte = (row.expiry - date.today()).days if row.expiry else 0
                T = max(dte, 0) / 365
                r = black76(contract_f, row.strike, T, iv, row.type == "call")
                entry = r.price

        import_mark = row.last_tick if row.last_tick is not None else entry

        positions.append(Position(
            id=0, label=row.label, type=row.type,
            strike=None if is_future else row.strike,
            expiry_date=None if is_future else row.expiry,
            qty=row.qty, iv=None if is_future else iv, iv_estimated=iv_estimated,
            entry=entry, last_tick=row.last_tick, import_mark=import_mark,
            underlying_override=override,
        ))

    return positions, estimated_count
