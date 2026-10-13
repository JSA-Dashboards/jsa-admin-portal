"""Session-state schema for the JSA Risk Analyzer.

The book is session-only: this app is shared with customers via a public URL, and
positions are the customer's own hypothetical/actual holdings, not a shared JSA book — so
each browser session gets its own private copy, never written to Snowflake, never visible
to any other session. (An earlier Phase 2 briefly made positions Snowflake-backed for a
single-internal-user assumption that no longer holds once the app went out to customers;
`data/positions_repo.py` and the POSITIONS/IMPORT_BATCHES/POSITION_HISTORY tables are kept
around unused, in case a separate internal-only view is wanted later.)

Reference data — contract marks, IV snapshot, prior settles, import presets — stays
Snowflake-backed via `data/reference_repo.py` / `data/presets_repo.py`: that's real shared
market data and format templates, not customer-specific, so it's correct for every session
to see the same values. Since those tables are keyed by a bare 3-char canonical key (e.g.
"Z26") that isn't unique across commodities, every read/write here goes through the
current session's commodity so the stored key is prefixed with its 2-letter product code
(see commodities.reference_key) -- Dec corn and Dec soybeans never collide.

The dashboard shows exactly one commodity at a time (see get_commodity_spec/set_commodity)
— positions are commodity-specific, so switching clears the book rather than mixing
contracts that price completely differently (different $ multiplier, different quoting
unit) into one view.
"""
from dataclasses import replace
from datetime import date, timedelta
from typing import Dict, List, Optional

import streamlit as st

from jsa_risk.data import reference_repo
from jsa_risk.pricing.commodities import CORN, CommoditySpec, get_commodity, reference_key
from jsa_risk.pricing.stress import Position, StressState, effective_underlying_key

# session_state keys tied to whatever commodity was previously selected -- cleared on a
# commodity switch made elsewhere (e.g. the sidebar) so nothing from the old book/screen
# lingers. The import-wizard keys are kept separate: switching commodity *from the Import
# screen's own picker* (see pages/import_excel.py) deliberately leaves these alone, since
# the whole point there is to keep the pasted sheet and re-filter it under the newly
# picked commodity, not force a re-paste.
_ADD_POSITION_KEY = "add_pos_draft"
_IMPORT_WIZARD_KEYS = [
    "import_headers", "import_rows", "import_mapping",
    "import_staging", "import_underlying_overrides",
]


def _in_days(n: int) -> date:
    return date.today() + timedelta(days=n)


def _default_positions(commodity_code: str) -> List[Position]:
    """The same 10-position corn demo book the original HTML tool always opened with —
    customers see a populated, explorable example before pasting/adding their own. There's
    no equivalent seed book for the other commodities yet, so they start empty."""
    if commodity_code != CORN.code:
        return []
    return [
        Position(id=1, label="ZCU26", type="call", qty=-30, entry=0.21, strike=5.00,
                 expiry_date=_in_days(32), iv=25.20, iv_estimated=True, last_tick=0.020),
        Position(id=2, label="ZCU26", type="put", qty=30, entry=0.19, strike=4.30,
                 expiry_date=_in_days(32), iv=25.20, iv_estimated=True),
        Position(id=3, label="ZCU26", type="call", qty=15, entry=0.18, strike=4.70,
                 expiry_date=_in_days(32), iv=25.20, iv_estimated=True),
        Position(id=4, label="ZCZ26", type="put", qty=20, entry=0.22, strike=4.50,
                 expiry_date=_in_days(95), iv=23.43, iv_estimated=True),
        Position(id=5, label="ZCZ26", type="call", qty=-20, entry=0.15, strike=4.90,
                 expiry_date=_in_days(95), iv=23.43, iv_estimated=True),
        Position(id=6, label="ZCU26", type="future", qty=10, entry=4.55, last_tick=4.6525),
        Position(id=7, label="ZCZ26", type="future", qty=-8, entry=4.80),
        Position(id=8, label="ZCN27", type="call", qty=12, entry=0.24, strike=4.60,
                 expiry_date=_in_days(220), iv=21.50, iv_estimated=True),
        Position(id=9, label="ZCN27", type="future", qty=6, entry=4.50),
        Position(id=10, label="ZCV26", type="put", qty=10, entry=0.17, strike=4.55,
                 expiry_date=_in_days(63), iv=23.43, iv_estimated=True),
    ]


def init_session_state() -> None:
    """Idempotent — safe to call at the top of every page."""
    if "commodity_code" not in st.session_state:
        st.session_state.commodity_code = CORN.code
    if "stress" not in st.session_state:
        st.session_state.stress = StressState()
    if "positions" not in st.session_state:
        st.session_state.positions = _default_positions(st.session_state.commodity_code)
        st.session_state.next_position_id = len(st.session_state.positions) + 1


def get_commodity_spec() -> CommoditySpec:
    return get_commodity(st.session_state.get("commodity_code", CORN.code))


# Every selectbox that lets the user pick the active commodity, keyed by its own widget
# key -- kept in sync here so that switching commodity from ANY one of them (e.g. the
# Import screen's own picker) updates how the OTHERS display too (e.g. the sidebar),
# rather than each independently-keyed widget clinging to its own last-set value and
# fighting over which is "right" on the next rerun.
_COMMODITY_WIDGET_KEYS = ["commodity_selector", "import_commodity_picker"]


def set_commodity(code: str, clear_import_wizard: bool = True) -> None:
    """Switching commodities starts a fresh book -- a position priced against one
    commodity's contracts (different $ multiplier, different quoting unit) is meaningless
    under another's, so there's no sensible way to carry the old book over.

    `clear_import_wizard=False` is for the Import screen's own commodity picker: it
    switches the commodity same as the sidebar does, but keeps whatever sheet is already
    pasted/parsed/staged so it can just be re-filtered under the new commodity, instead of
    forcing the user back to square one."""
    st.session_state.commodity_code = code
    st.session_state.positions = _default_positions(code)
    st.session_state.next_position_id = len(st.session_state.positions) + 1
    st.session_state.pop(_ADD_POSITION_KEY, None)
    if clear_import_wizard:
        for k in _IMPORT_WIZARD_KEYS:
            st.session_state.pop(k, None)
    for widget_key in _COMMODITY_WIDGET_KEYS:
        st.session_state[widget_key] = code


def visible_positions() -> List[Position]:
    """No blotter filters yet (that's a later pass) — every session-local position is
    visible."""
    return st.session_state.positions


def add_position(p: Position) -> int:
    new_id = st.session_state.next_position_id
    st.session_state.next_position_id += 1
    st.session_state.positions.append(replace(p, id=new_id))
    return new_id


def update_position_field(position_id: int, field: str, value) -> None:
    field_map = {
        "LABEL": "label", "TYPE": "type", "STRIKE": "strike", "EXPIRY_DATE": "expiry_date",
        "QTY": "qty", "IV": "iv", "IV_ESTIMATED": "iv_estimated", "ENTRY": "entry",
        "LAST_TICK": "last_tick",
    }
    attr = field_map.get(field, field.lower())
    positions = st.session_state.positions
    for i, p in enumerate(positions):
        if p.id == position_id:
            positions[i] = replace(p, **{attr: value})
            return


def delete_position(position_id: int) -> None:
    st.session_state.positions = [p for p in st.session_state.positions if p.id != position_id]


def replace_book(positions: List[Position]) -> int:
    """Replaces the whole session-local book — assigns fresh sequential ids, matching the
    "importing replaces the whole book" UX carried over from the original tool. Returns
    the count of positions replaced (there's no batch/history table anymore, so nothing
    else to hand back)."""
    # Cash positions are entered by hand on the dashboard (a broker export doesn't carry
    # them), so an import replaces the exported positions but leaves the cash in place.
    kept_cash = [p for p in st.session_state.positions if p.is_cash]
    next_id = 1
    numbered = []
    for p in list(positions) + kept_cash:
        numbered.append(replace(p, id=next_id))
        next_id += 1
    st.session_state.positions = numbered
    st.session_state.next_position_id = next_id
    return len(positions)


def get_contract_price(canonical_key: str) -> float:
    spec = get_commodity_spec()
    return reference_repo.get_contract_price(reference_key(spec, canonical_key), default=spec.default_price)


def positions_without_ticks_for(positions: List[Position], canonical_key: str, commodity: CommoditySpec) -> List[Position]:
    """Positions with last_tick cleared where they price off this contract. A last tick is
    the broker's price at import time; once the contract's mark has been updated it's stale,
    and left in place it would keep the blotter's Mark and P&L on the old price while the
    scenario charts (which only use live marks) moved on."""
    return [
        replace(p, last_tick=None)
        if p.last_tick is not None and effective_underlying_key(p, commodity=commodity) == canonical_key else p
        for p in positions
    ]


def set_contract_price(canonical_key: str, price: float, source: str = "manual") -> None:
    spec = get_commodity_spec()
    reference_repo.set_contract_price(reference_key(spec, canonical_key), price, source)
    # The live mark now wins for everything priced off this contract.
    st.session_state.positions = positions_without_ticks_for(st.session_state.positions, canonical_key, spec)


def snapshot_iv(canonical_key: str) -> float:
    spec = get_commodity_spec()
    return reference_repo.snapshot_iv(reference_key(spec, canonical_key))


def get_contract_marks() -> Dict[str, float]:
    """Bulk marks for the *current* commodity only, de-prefixed back to bare canonical
    keys (e.g. "ZCZ26" -> "Z26") so callers can look them up the same way get_contract_price
    is called elsewhere. Relies on every commodity code being exactly 2 characters."""
    spec = get_commodity_spec()
    prefix = spec.code
    return {
        k[len(prefix):]: v
        for k, v in reference_repo.get_contract_marks().items()
        if k.startswith(prefix)
    }


def get_iv_provenance() -> List[dict]:
    """Same de-prefixing as get_contract_marks, for the per-contract IV provenance rows."""
    spec = get_commodity_spec()
    prefix = spec.code
    return [
        {**r, "key": r["key"][len(prefix):]}
        for r in reference_repo.get_iv_provenance()
        if r["key"].startswith(prefix)
    ]
