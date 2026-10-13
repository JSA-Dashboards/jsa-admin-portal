"""The position blotter. Phase 1 renders it read-only (`st.dataframe`); Phase 2 swaps
the render call for `st.data_editor` and wires edits back through `positions_repo` —
`build_blotter_dataframe` (the shared column computation) doesn't need to change for that.
"""
from typing import Callable, List

import pandas as pd
import streamlit as st

from jsa_risk.pricing.commodities import CORN, CommoditySpec
from jsa_risk.pricing.stress import Position, StressState, effective_underlying_display, eval_position


def _delta_col(commodity: CommoditySpec) -> str:
    return f"Delta ({commodity.unit})"


def _columns(commodity: CommoditySpec) -> List[str]:
    return [
        "id", "Contract", "Underlying", "Type", "Strike", "DTE (d)", "Qty", "IV%", "Entry",
        "Mark", _delta_col(commodity), "Gamma $", "Vega $", "Theta $/d", "P&L", "Delete",
    ]


def build_blotter_dataframe(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec = CORN,
) -> pd.DataFrame:
    # An empty `rows` list would otherwise produce a DataFrame with NO columns at all
    # (pandas can't infer any from zero dicts) -- explicit `columns=` keeps every
    # downstream column lookup (styling, column_config, disabled=) valid even when the
    # book is empty, which happens for real now that a freshly selected commodity starts
    # with no seeded positions.
    rows = []
    for p in positions:
        r = eval_position(p, stress, get_contract_price, commodity=commodity)
        dte = None
        if p.expiry_date is not None:
            from datetime import date
            dte = (p.expiry_date - date.today()).days
        rows.append({
            "id": p.id,
            "Contract": p.label,
            "Underlying": effective_underlying_display(p, commodity=commodity),
            "Type": "cash" if p.is_cash else p.type,
            "Strike": p.strike,
            "DTE (d)": dte,
            "Qty": p.qty,
            "IV%": p.iv,
            "Entry": p.entry,
            "Mark": round(r.price, 4),
            _delta_col(commodity): round(r.delta_d),
            "Gamma $": round(r.gamma_d),
            "Vega $": round(r.vega_d),
            "Theta $/d": round(r.theta_d),
            "P&L": round(r.pnl),
            "Delete": False,
        })
    return pd.DataFrame(rows, columns=_columns(commodity))


def _computed_column_config(commodity: CommoditySpec) -> dict:
    return {
        "Qty": st.column_config.NumberColumn(format="%g"),
        "Strike": st.column_config.NumberColumn(format="$%.2f"),
        "Entry": st.column_config.NumberColumn(format="$%.4f"),
        "Mark": st.column_config.NumberColumn(format="$%.4f"),
        _delta_col(commodity): st.column_config.NumberColumn(format="%,d"),
        "Gamma $": st.column_config.NumberColumn(format="$%,d"),
        "Vega $": st.column_config.NumberColumn(format="$%,d"),
        "Theta $/d": st.column_config.NumberColumn(format="$%,d"),
        "P&L": st.column_config.NumberColumn(format="$%,d"),
    }


GAIN_COLOR = "#3a9d5d"
LOSS_COLOR = "#c0392b"


def _signed_columns(commodity: CommoditySpec) -> List[str]:
    return [_delta_col(commodity), "Gamma $", "Vega $", "Theta $/d", "P&L"]


def _sign_style(v) -> str:
    if pd.isna(v):
        return ""
    return f"color: {GAIN_COLOR}" if v >= 0 else f"color: {LOSS_COLOR}"


def render_blotter(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec = CORN,
) -> None:
    df = build_blotter_dataframe(positions, stress, get_contract_price, commodity).drop(columns=["id", "Delete"])
    styled = df.style.map(_sign_style, subset=_signed_columns(commodity))
    st.dataframe(styled, hide_index=True, use_container_width=True, column_config=_computed_column_config(commodity))


def render_editable_blotter(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec = CORN,
) -> None:
    """Qty and Entry are editable and write straight through to this session's book; row
    deletion via the Delete checkbox. Full per-column filter/sort and richer cell editing
    (DTE, Mark/last-tick) are a possible later pass."""
    from jsa_risk import state

    df = build_blotter_dataframe(positions, stress, get_contract_price, commodity)
    editor_key = "blotter_editor"

    # Styler colors only apply to non-editable columns (Streamlit's own constraint) --
    # Qty/Entry/Delete stay editable and plain; the computed P&L-style columns are
    # disabled below, so the green/red coloring renders for them.
    styled = df.style.map(_sign_style, subset=_signed_columns(commodity))

    edited = st.data_editor(
        styled,
        hide_index=True,
        use_container_width=True,
        key=editor_key,
        height="content",  # fit every row -- the page scrolls, not a scrollbar inside the grid
        disabled=[c for c in df.columns if c not in ("Qty", "Entry", "Delete")],
        column_config={**_computed_column_config(commodity), "id": None},
    )

    changes = st.session_state[editor_key]
    edited_rows = changes.get("edited_rows", {}) if isinstance(changes, dict) else {}
    to_delete = []
    wrote_any = False
    for row_idx_str, edits in edited_rows.items():
        row_idx = int(row_idx_str)
        position_id = int(df.iloc[row_idx]["id"])
        if edits.get("Delete"):
            to_delete.append(position_id)
            continue
        if "Qty" in edits:
            is_cash = any(p.id == position_id and p.is_cash for p in positions)
            qty = float(edits["Qty"]) if is_cash else int(edits["Qty"])
            state.update_position_field(position_id, "QTY", qty)
            wrote_any = True
        if "Entry" in edits:
            state.update_position_field(position_id, "ENTRY", float(edits["Entry"]))
            wrote_any = True

    if to_delete:
        for pid in to_delete:
            state.delete_position(pid)
        st.rerun()
    elif wrote_any:
        st.rerun()
