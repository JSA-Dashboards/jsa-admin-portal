"""The position blotter. Phase 1 renders it read-only (`st.dataframe`); Phase 2 swaps
the render call for `st.data_editor` and wires edits back through `positions_repo` —
`build_blotter_dataframe` (the shared column computation) doesn't need to change for that.
"""
from typing import Callable, List

import pandas as pd
import streamlit as st

from jsa_risk.pricing.commodities import CORN, CommoditySpec
from jsa_risk.pricing.portfolio import book_totals, book_totals_by_group
from jsa_risk.pricing.stress import Position, StressState, effective_underlying_display, eval_position


def _position_col(commodity: CommoditySpec) -> str:
    """The position-scaled delta column: "Position (lb)" / "Position (bu)".

    Called Delta (lb) until the raw greek got a column of its own beside it, at which
    point one page had two adjacent columns both called Delta meaning different things.
    "Delta" now only ever means the greek; this one is what that leg is worth in pounds or
    bushels of the underlying.

    NOT "Net Position (lb)", though the footer and the KPI tile both say "Net Position":
    nothing is netted within a single row. The footer is the net OF this column, which is
    what the word is doing there."""
    return f"Position ({commodity.unit})"


def _columns(commodity: CommoditySpec) -> List[str]:
    return [
        "id", "Contract", "Underlying", "Type", "Strike", "DTE (d)", "Qty", "IV%", "Entry",
        "Mark", "Delta", _position_col(commodity), "Gamma $", "Vega $", "Theta $/d", "P&L", "Delete",
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
            # The option's OWN delta, sitting immediately left of the position-scaled one.
            # Delta x Qty x contract size gives the Position (lb) beside it, to within the
            # four decimals printed here -- close enough to check a sign or a magnitude
            # against, not close enough to reconcile to the pound. See the test.
            "Delta": round(r.delta, 4),
            _position_col(commodity): round(r.delta_d),
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
        "Delta": st.column_config.NumberColumn(format="%.4f"),
        _position_col(commodity): st.column_config.NumberColumn(format="%,d"),
        "Gamma $": st.column_config.NumberColumn(format="$%,d"),
        "Vega $": st.column_config.NumberColumn(format="$%,d"),
        "Theta $/d": st.column_config.NumberColumn(format="$%,d"),
        "P&L": st.column_config.NumberColumn(format="$%,d"),
    }


def editable_caption(stress: StressState) -> str:
    """The "what can I change here" line above the grid.

    It lives in this module rather than on the page because WHICH columns are editable
    depends on the stress scenario, and a caption that names Mark while Mark is locked is
    worse than none -- a reader who believes it types a price and watches it vanish.
    """
    if stress.is_neutral:
        return (
            "This book is private to your browser session — Qty, Entry and Mark are "
            "editable; check Delete to remove a row. A Mark you type overrides the "
            "automatic one until you reset it."
        )
    return (
        "This book is private to your browser session — Qty and Entry are editable; check "
        "Delete to remove a row. Mark is locked while a stress scenario is applied: under "
        "a scenario every cell is repriced by model, so a typed mark could not be shown."
    )


GAIN_COLOR = "#3a9d5d"
LOSS_COLOR = "#c0392b"


def _signed_columns(commodity: CommoditySpec) -> List[str]:
    """Columns colored green/red by sign. "Delta" -- the option's own delta -- is
    deliberately NOT one of them. Green/red on this page means gain, or long exposure, and
    a put's -0.29 is neither: short 160 of that put is +1,880,784 lb LONG. Coloring the
    raw greek would put a red number and a green one on the same row describing the same
    leg, which is the sort of contradiction a reader resolves by distrusting both."""
    return [_position_col(commodity), "Gamma $", "Vega $", "Theta $/d", "P&L"]


def _sign_style(v) -> str:
    if pd.isna(v):
        return ""
    return f"color: {GAIN_COLOR}" if v >= 0 else f"color: {LOSS_COLOR}"


def fmt_total_delta(v: float, unit: str) -> str:
    """Formatted to match the Delta column the total sits under -- comma-grouped, no
    decimals, a minus for short and NO plus for long. A total that is punctuated
    differently from the cells above it reads as a different kind of number."""
    return f"{'-' if v < 0 else ''}{abs(v):,.0f} {unit}"


def fmt_total_pnl(v: float) -> str:
    """Likewise the P&L column's own `$%,d`: a loss is -$1,234, never ($1,234) -- in USDA
    and CFTC reports parentheses mean negative, and this audience reads those daily."""
    return f"{'-' if v < 0 else ''}${abs(v):,.0f}"


def fmt_combined_delta(group) -> str:
    """The structure's own delta when its legs are all one size -- "0.5696", directly
    comparable with the per-leg figures in the Delta column above it.

    Where the legs are NOT one size there is no single structure to be one unit of, so the
    row falls back to the legs' deltas added with their sizes and says "deltas" out loud.
    Mixed units down one column is a cost; printing a per-unit figure for a group that has
    no unit would be a wrong number, which is worse."""
    if group.delta_per_unit is None:
        return f"{group.delta_contracts:+,.1f} deltas"
    return f"{group.delta_per_unit:+.4f}"


def _sign_style_color(v: float) -> str:
    return GAIN_COLOR if v >= 0 else LOSS_COLOR


def _totals_html(label: str, value_str: str, color: str) -> str:
    return (
        f"<span style='font-size:14px;color:#898781'>{label}</span>"
        f"<span style='font-size:1.15rem;font-weight:600;color:{color};margin-left:8px'>{value_str}</span>"
    )


def render_blotter_totals(
    positions: List[Position],
    stress: StressState,
    get_contract_price: Callable[[str], float],
    commodity: CommoditySpec = CORN,
) -> None:
    """The footer line under the blotter: net delta and total P&L across every row.

    Not a row inside the grid. `st.data_editor` maps an edit back to a position by ROW
    INDEX (`df.iloc[row_idx]["id"]`), so a totals row would carry no id, sit in that index
    space, and be editable and deletable like any other -- ticking its Delete box would
    raise on the int() of a missing id.

    THE DELTA TOTAL IS LABELLED "Net Position", NOT "Total Delta", and deliberately not
    after the column it sums. A per-row delta belongs in that row of scaled greeks beside
    Gamma $ and Vega $; summed over the book it stops being a greek and becomes the
    position itself -- a quantity of pounds or bushels, where "delta" names a RATE of
    change. The KPI strip at the top of the page already prints this exact figure, from
    this exact function, under the name "Net Position", and one number under two names on
    one page is the ambiguity worth removing. Ross's call, 2026-10-15."""
    if not positions:
        return
    evals = [eval_position(p, stress, get_contract_price, commodity=commodity) for p in positions]

    # Per-underlying rows FIRST, then the book line, so the eye runs parts -> whole.
    # The point of them is the COMBINED DELTA: a client reading the blotter otherwise has
    # to flip the short put's -0.2939 to +0.2939 and add it to the call's +0.2749 to see
    # that the Feb structure is 0.57 delta. Nothing else on the page does that -- "Greeks
    # by contract" nets the POUNDS per expiry, never the greek.
    #
    # Grouped on the blotter's own Underlying column rather than on the option expiry:
    # delta is exposure to a particular futures contract, so two expiries on one contract
    # genuinely add, where two contracts' deltas do not net. (Those bars group by expiry,
    # which is right for vega and theta and would be wrong here.)
    groups = book_totals_by_group(
        positions, evals, lambda p: effective_underlying_display(p, commodity=commodity)
    )
    # ONE GROUP STILL NEEDS ITS DELTA, and suppressing the whole block was wrong.
    # The rows duplicate the book line's Position and P&L when there is only one
    # underlying -- but the book line has never carried a DELTA, so suppressing them
    # left the combined figure nowhere on the page for a book held in a single
    # contract, which is what building one strangle looks like. Reported by Ross
    # 2026-10-28 on a two-leg Feb '27 book; he reasonably assumed the position had to
    # come from an import for the page to show it.
    #
    # So: several underlyings get the breakdown, one gets the delta on the book line
    # below. A book-level combined delta is only meaningful when every leg shares an
    # underlying -- deltas on different futures contracts do not add -- which is
    # exactly the case this branch covers.
    if len(groups) > 1:
        head = ("<div style='margin:4px 0 2px 2px;font-size:13px;color:#898781'>"
                "<span style='display:inline-block;min-width:150px'>Combined by underlying</span>"
                "<span style='display:inline-block;min-width:110px'>Delta</span>"
                f"<span style='display:inline-block;min-width:150px'>Position ({commodity.unit})</span>"
                "<span>P&amp;L</span></div>")
        rows = "".join(
            "<div style='margin:1px 0 1px 2px;font-size:0.95rem;font-weight:600'>"
            f"<span style='font-size:13px;font-weight:400;color:#898781;display:inline-block;min-width:150px'>{g.label}</span>"
            f"<span style='display:inline-block;min-width:110px;color:{_sign_style_color(g.delta_contracts)}'>"
            f"{fmt_combined_delta(g)}</span>"
            f"<span style='display:inline-block;min-width:150px;color:{_sign_style_color(g.position)}'>"
            f"{fmt_total_delta(g.position, commodity.unit)}</span>"
            f"<span style='color:{_sign_style_color(g.pnl)}'>{fmt_total_pnl(g.pnl)}</span>"
            "</div>"
            for g in groups
        )
        st.markdown(head + rows, unsafe_allow_html=True)

    net_delta, total_pnl = book_totals(evals)
    delta_str, pnl_str = fmt_total_delta(net_delta, commodity.unit), fmt_total_pnl(total_pnl)
    sep = "<span style='color:#898781;margin:0 14px'>|</span>"
    line = _totals_html("Net Position", delta_str, _sign_style_color(net_delta))
    if len(groups) == 1:
        g = groups[0]
        line += sep + _totals_html("Combined Delta", fmt_combined_delta(g),
                                   _sign_style_color(g.delta_contracts))
    line += sep + _totals_html("Total P&L", pnl_str, _sign_style_color(total_pnl))
    st.markdown(f"<div style='margin:2px 0 6px 2px'>{line}</div>", unsafe_allow_html=True)


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
    """Qty, Entry and Mark are editable and write straight through to this session's
    book; row deletion via the Delete checkbox. Full per-column filter/sort and richer
    cell editing (DTE) are a possible later pass.

    MARK WRITES `last_tick`, WHICH IS THE FIELD THE AUTOMATIC MARK ALREADY PREFERS --
    nothing about how a mark populates changes. `eval_position` has always taken
    `last_tick` over the model at zero stress (that is how an Excel import's prices reach
    the page); typing one by hand just puts a value in the same slot.

    THE WAY BACK IS THE BUTTON, NOT AN EMPTY CELL. Clearing a NumberColumn cell does not
    reach `edited_rows` at all -- measured in a browser, not assumed: typing 0.0450 wrote
    through and displayed, then clearing that same cell left `last_tick` at 0.045 while
    the grid drew the word "None" client-side. So an override with no button would be an
    override with no way back. The None branch below is kept anyway: it costs one
    comparison and is correct the day Streamlit does emit one.

    It is LOCKED under a non-neutral scenario, and that is the whole reason this function
    takes `stress`. `use_last_tick` in `eval_position` is `(F_override is None) and
    no_stress and has_tick`, so under any shock the grid shows the model whatever the tick
    says -- correct, since a shocked scenario cannot be marked to a frozen price, but it
    means an edit made there would be stored and never appear. Disabling the column is
    the honest version of that."""
    from jsa_risk import state

    df = build_blotter_dataframe(positions, stress, get_contract_price, commodity)

    # THE EDITOR MUST BE REMOUNTED ONCE AN EDIT HAS BEEN APPLIED, or it re-sends it for
    # ever. `edited_rows` lives in the widget, not the dataframe, and survives `st.rerun()`:
    # Streamlit only drops a pending edit when the data it is handed comes back EQUAL to
    # it. Typing a mark therefore looks fine -- the frame converges on the typed value and
    # the edit is absorbed -- while anything that moves the data AWAY from it does not.
    #
    # Reset was the case that exposed it. It writes last_tick=None, reruns, the editor
    # re-sends {"Mark": <the typed price>}, this handler writes it straight back, and the
    # reset is undone inside the same cycle -- so the button appeared to do nothing. The
    # re-application also meant `wrote_any` was true on every run, so the page reran in a
    # loop and the totals never settled.
    #
    # Bumping the key gives the next run a fresh widget with no pending edits. The cost is
    # that the grid loses its cell selection after an edit, which is cheap next to an edit
    # that cannot be undone.
    gen = st.session_state.setdefault("blotter_editor_gen", 0)
    editor_key = f"blotter_editor_{gen}"
    editable = ("Qty", "Entry", "Delete") + (("Mark",) if stress.is_neutral else ())

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
        disabled=[c for c in df.columns if c not in editable],
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
        if "Mark" in edits:
            # None is a CLEARED cell, not a zero -- `float(None)` raises, and a mark of
            # 0.0 is a real price meaning the leg is worthless. Writing None puts the row
            # back on the model.
            raw = edits["Mark"]
            state.update_position_field(position_id, "LAST_TICK", None if raw is None else float(raw))
            wrote_any = True

    def _applied() -> None:
        """Remount the editor, then rerun -- see the note above `editor_key`."""
        st.session_state["blotter_editor_gen"] = gen + 1
        st.rerun()

    if to_delete:
        for pid in to_delete:
            state.delete_position(pid)
        _applied()
    elif wrote_any:
        _applied()

    # Only offered when there is something to undo -- a permanently visible reset button
    # on a book nobody has marked by hand invites the question "reset what?".
    if stress.is_neutral and any(p.last_tick is not None for p in positions):
        n = sum(1 for p in positions if p.last_tick is not None)
        if st.button(f"Reset {n} manual mark{'s' if n != 1 else ''} to automatic",
                     key="reset_manual_marks"):
            for p in positions:
                if p.last_tick is not None:
                    state.update_position_field(p.id, "LAST_TICK", None)
            _applied()
