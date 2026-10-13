"""Cash (physical) position entry. A cash position is risked exactly like a futures
position on the contract it's tied to -- linear delta, no gamma/vega/theta -- but it never
expires, and it's entered in the commodity's own unit (bushels/pounds) rather than whole
lots, since inventory isn't sized in contracts.
"""
import re
from typing import List

import streamlit as st

from jsa_risk import state
from jsa_risk.pricing.commodities import CORN, CommoditySpec
from jsa_risk.pricing.stress import Position, effective_underlying_key
from jsa_risk.pricing.symbols import MONTH_NUMBERS, format_canonical_key, upcoming_contract_keys

_KEY_RE = re.compile(r"^[A-Z]\d{2}$")


def _chronological(keys) -> List[str]:
    valid = [k for k in set(keys) if _KEY_RE.match(k) and k[0] in MONTH_NUMBERS]
    return sorted(valid, key=lambda k: (int(k[1:]), MONTH_NUMBERS[k[0]]))


def contract_choices(positions: List[Position], commodity: CommoditySpec) -> List[str]:
    """Contracts the book already trades, plus the next few listed ones so the
    form still works on an empty book (or for a contract the book doesn't touch yet)."""
    in_book = [effective_underlying_key(p, commodity=commodity) for p in positions]
    return _chronological(in_book + upcoming_contract_keys(commodity))


def render_cash_position_entry(positions: List[Position], commodity: CommoditySpec = CORN) -> None:
    st.markdown("###### Cash position")
    st.caption(
        f"Physical {commodity.name.lower()} priced and risked like a futures position on the "
        f"contract you pick below, with no expiry. Enter {commodity.unit} held (+) or sold "
        f"forward (−); {commodity.contract_size:,} {commodity.unit} = 1 contract."
    )

    choices = contract_choices(positions, commodity)
    in_book_keys = {effective_underlying_key(p, commodity=commodity) for p in positions}
    default_idx = next((i for i, k in enumerate(choices) if k in in_book_keys), 0)

    c_contract, c_qty, c_entry = st.columns([2, 2, 2])
    key = c_contract.selectbox(
        "Contract", choices, index=default_idx, format_func=format_canonical_key,
        key=f"cash_contract_{commodity.code}",
        help="The contract the book is priced against -- the cash position moves with it.",
    )
    units = c_qty.number_input(
        f"Quantity ({commodity.unit})", value=0, step=1000, key=f"cash_qty_{commodity.code}",
        help=f"+ long / owned, − short / sold forward. Whole {commodity.unit}.",
    )
    mark = state.get_contract_price(key)
    # Starts at the current mark (and follows it), but whatever you type sticks -- so the
    # position can carry your actual cost rather than today's price.
    entry = c_entry.number_input(
        f"Entry price ($/{commodity.unit})", value=round(float(mark), 4), min_value=0.0, step=0.01,
        format="%.4f", help=f"Pre-filled with the current mark (${mark:.4f}). Overwrite with your actual cost.",
    )

    lots = units / commodity.contract_size
    if units:
        st.caption(f"≈ {lots:+,.2f} contracts of {format_canonical_key(key)} at ${mark:.4f}/{commodity.unit}.")

    if st.button("Add cash position", disabled=not units):
        new_id = state.add_position(Position(
            id=0, label=f"CASH {commodity.code}{key}", type="future", qty=lots, entry=float(entry),
            underlying_override=key, is_cash=True,
        ))
        st.session_state["_flash_added"] = (
            f"Added cash position {units:+,.0f} {commodity.unit} on {format_canonical_key(key)} — position #{new_id}."
        )
        st.session_state.pop(f"cash_qty_{commodity.code}", None)  # back to blank so a double-click can't add twice
        st.rerun()
