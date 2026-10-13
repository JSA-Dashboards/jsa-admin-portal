from datetime import date, timedelta

import streamlit as st

from jsa_risk import state
from jsa_risk.data.live_iv import lookup_option_iv
from jsa_risk.pricing.black76 import black76
from jsa_risk.pricing.stress import Position
from jsa_risk.pricing.symbols import canonical_contract_key, contract_display_name, option_expiry_date
from jsa_risk.state import get_contract_price

INSTRUMENTS = ["call", "put", "future"]

# Defensive, not redundant -- see the matching comment in pages/dashboard.py.
state.init_session_state()
commodity = state.get_commodity_spec()


def _fmt_dollars_signed(v: float) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}${abs(v):,.0f}"


def _fmt_unit_signed(v: float, unit: str) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}{abs(v):,.0f} {unit}"


def _default_draft() -> dict:
    return {
        "label": "",
        "type": "call",
        "strike": round(commodity.default_price, 2),
        "expiry": date.today() + timedelta(days=60),
        "qty": 10,
        "iv": 25.0,
        "entry": None,
    }


if "add_pos_draft" not in st.session_state:
    st.session_state.add_pos_draft = _default_draft()
draft = st.session_state.add_pos_draft


# Expiration date and days-to-expiry are two views of one value: edit either and the other
# follows. Both are keyed widgets so a contract symbol can load the actual expiry into them.
EXPIRY_KEY, DTE_KEY = "add_pos_expiry", "add_pos_dte"


def _set_expiry(d: date) -> None:
    st.session_state[EXPIRY_KEY] = d
    st.session_state[DTE_KEY] = max((d - date.today()).days, 0)


def _on_expiry_edit() -> None:
    _set_expiry(st.session_state[EXPIRY_KEY])


def _on_dte_edit() -> None:
    _set_expiry(date.today() + timedelta(days=int(st.session_state[DTE_KEY])))


if EXPIRY_KEY not in st.session_state:
    _set_expiry(draft["expiry"] or (date.today() + timedelta(days=60)))


def _on_type_change() -> None:
    new_type = st.session_state.add_pos_type
    draft["type"] = new_type
    if new_type == "future":
        draft["strike"], draft["expiry"], draft["iv"] = None, None, None
    elif draft.get("strike") is None:
        draft["strike"] = round(get_contract_price(canonical_contract_key(draft["label"], commodity=commodity)), 2)
        draft["expiry"] = date.today() + timedelta(days=60)
        draft["iv"] = 25.0
        draft["expiry_loaded_for"] = None     # let the symbol's actual expiry load again
        _set_expiry(draft["expiry"])


st.markdown("###### New position ticket")
st.caption(
    f"Priced live against the current {commodity.name} futures market data — add it and it "
    "lands directly in the blotter."
)

field_col, preview_col = st.columns([3, 2])

with field_col:
    draft["label"] = st.text_input(
        "Contract symbol (required)", value=draft["label"], placeholder=f"e.g. {commodity.code}{commodity.listed_months[0]}26",
        help="Decoded to the underlying month/year automatically.",
    ).strip()
    st.selectbox(
        "Instrument", INSTRUMENTS, index=INSTRUMENTS.index(draft["type"]),
        key="add_pos_type", on_change=_on_type_change,
        format_func=lambda v: "FUTURE" if v == "future" else v.upper(),
    )
    is_future = draft["type"] == "future"

    if not is_future:
        draft["strike"] = st.number_input(
            "Strike", value=float(draft["strike"] or commodity.default_price), step=0.01, format="%.2f",
        )
        # A new contract symbol loads that option's actual expiry; after that, whatever you
        # set (date or days) sticks until the symbol changes again.
        actual_expiry = option_expiry_date(draft["label"], commodity)
        if actual_expiry and draft.get("expiry_loaded_for") != draft["label"]:
            _set_expiry(actual_expiry)
            draft["expiry_loaded_for"] = draft["label"]
        e_col, d_col = st.columns(2)
        draft["expiry"] = e_col.date_input(
            "Expiration date", key=EXPIRY_KEY, on_change=_on_expiry_edit,
            help="Loaded from the contract symbol's actual option expiry -- overwrite it for "
                 "weekly options or if an exchange holiday shifts it.",
        )
        d_col.number_input(
            "Days to expiry", min_value=0, step=1, key=DTE_KEY, on_change=_on_dte_edit,
            help="Calendar days from today. Edit this or the date; the other updates.",
        )
        if actual_expiry:
            st.caption(f"Actual expiry for {draft['label']}: {actual_expiry:%a %b %d, %Y}.")

    draft["qty"] = int(st.number_input(
        "Quantity (lots)", value=int(draft["qty"]), step=1, help="+long / -short",
    ))

    if not is_future:
        # This option's own live vol (strike- and expiry-specific, from CME DataMine) is the
        # starting point, so the model entry price is close to where it actually trades.
        # It follows the contract/strike you enter; type a vol of your own and it sticks.
        with st.spinner("Pulling live vol from CME…"):
            live = lookup_option_iv(commodity, draft["label"], draft["type"], draft["strike"] or 0.0)
        draft["iv"] = st.number_input(
            "Implied vol %", value=round(float(live.iv_pct or 25.0), 2), step=0.5,
            help="Pre-filled with this option's live settlement vol from CME when available "
                 "(otherwise 25%). Overwrite it with your own.",
        )
        st.caption(live.note if live.iv_pct else f"{live.note} Using a 25% placeholder.")

    # Priced here, before the entry field, so the field can default to the model value.
    F = get_contract_price(canonical_contract_key(draft["label"], commodity=commodity))
    pos_mult = draft["qty"] * commodity.contract_size
    result = None
    dte = None
    if is_future:
        model_price = F
    else:
        dte = max((draft["expiry"] - date.today()).days, 0) if draft["expiry"] else 0
        result = black76(F, draft["strike"] or 0.0001, dte / 365, draft["iv"] or 0.01, draft["type"] == "call")
        model_price = result.price

    # Always editable. Starts at the model value (and follows it as strike/IV/etc. change),
    # but whatever you type sticks, so the position can carry your actual fill.
    entry_label = "Entry price" if is_future else "Entry premium"
    entry_price = st.number_input(
        f"{entry_label} ($/{commodity.unit})", value=round(float(model_price), 4), min_value=0.0,
        step=0.01, format="%.4f",
        help=f"Pre-filled with the model value (${model_price:.4f}). Overwrite it with your actual "
             "fill to book the difference as P&L from day one.",
    )
    draft["entry"] = entry_price

with preview_col:
    if is_future:
        delta_d, gamma_d, vega_d, theta_d = float(pos_mult), 0.0, 0.0, 0.0
    else:
        delta_d = result.delta * pos_mult
        gamma_d = result.gamma * pos_mult
        vega_d = (result.vega / 100) * pos_mult
        theta_d = (result.theta / 365) * pos_mult

    pnl = (round(float(model_price), 4) - entry_price) * pos_mult   # same 4dp as the field, so an untouched entry is exactly $0

    title = (draft["label"] or commodity.name) + " " + ("FUTURE" if is_future else f"{draft['type'].upper()} {draft['strike']}")
    st.markdown(f"**{title}**")
    contract_name = f"{draft['label']} futures" if draft["label"] else f"{commodity.name} futures (no contract picked — using default mark)"
    if is_future:
        sub = f"{contract_name} mark ${F:.3f}/{commodity.unit} · linear exposure, no expiry decay"
    else:
        sub = f"{contract_name} mark ${F:.3f}/{commodity.unit} · strike ${draft['strike'] or 0:.2f} · {dte}d to expiry"
    st.caption(sub)

    c1, c2 = st.columns(2)
    c1.metric("Model price", f"${model_price:.3f}")
    c2.metric(entry_label, f"${entry_price:.3f}")
    c1.metric(f"Delta ({commodity.unit})", _fmt_unit_signed(delta_d, commodity.unit))
    c2.metric("Gamma $", _fmt_dollars_signed(gamma_d))
    c1.metric("Vega $/vol pt", _fmt_dollars_signed(vega_d))
    c2.metric("Theta $/day", _fmt_dollars_signed(theta_d))
    st.metric("Day-one P&L vs entry", _fmt_dollars_signed(pnl))

st.markdown("---")
submit_col, reset_col, msg_col = st.columns([1, 1, 3])
submit_clicked = submit_col.button("Add to book", type="primary")
reset_clicked = reset_col.button("Clear form")

if reset_clicked:
    st.session_state.add_pos_draft = _default_draft()
    st.session_state.pop(EXPIRY_KEY, None)
    st.session_state.pop(DTE_KEY, None)
    st.rerun()

if submit_clicked:
    error = None
    if not draft["label"]:
        error = f"Enter the contract symbol this is against (e.g. {commodity.code}{commodity.listed_months[0]}26) — the strike is meaningless without it."
    elif not is_future and (not draft["strike"] or draft["strike"] <= 0):
        error = "Strike must be greater than 0."
    elif not is_future and draft["expiry"] is None:
        error = "Pick an expiration date."
    elif not is_future and (not draft["iv"] or draft["iv"] <= 0):
        error = "Implied vol must be greater than 0."
    elif not draft["qty"]:
        error = "Quantity can't be zero."

    if error:
        msg_col.error(error)
    else:
        new_position = Position(
            id=0,
            label=draft["label"],
            type=draft["type"],
            qty=draft["qty"],
            entry=entry_price,
            strike=None if is_future else draft["strike"],
            expiry_date=None if is_future else draft["expiry"],
            iv=None if is_future else draft["iv"],
        )
        new_id = state.add_position(new_position)
        st.session_state["_flash_added"] = (
            f"Added {contract_display_name(draft['label'], commodity=commodity)} {draft['type']} — position #{new_id}."
        )
        if st.session_state.get("_embedded"):
            # Hosted inside the JSA admin portal, whose page switcher (not st.navigation)
            # owns the pages: ask it to open the dashboard on the next run.
            st.session_state["_goto_page"] = "Risk dashboard"
            st.rerun()
        st.switch_page("pages/dashboard.py")
