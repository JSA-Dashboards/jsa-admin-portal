from datetime import date, timedelta

import pandas as pd
import streamlit as st

from jsa_risk import state
from jsa_risk.data import presets_repo
from jsa_risk.importer.commit import positions_from_staging
from jsa_risk.importer.mapping import IMPORT_TARGETS, QST_DEFAULT_MAPPING, auto_map, mapping_to_header_names
from jsa_risk.importer.parsing import parse_pasted_text
from jsa_risk.importer.staging import build_staging_row, label_commodity_code, staging_row_valid
from jsa_risk.pricing.commodities import COMMODITIES
from jsa_risk.pricing.symbols import canonical_contract_key, contract_display_name, normalize_underlying_override

# Defensive, not redundant -- see the matching comment in pages/dashboard.py.
state.init_session_state()


def _on_import_commodity_change() -> None:
    # clear_import_wizard=False: keeps whatever sheet is already pasted/parsed/staged so
    # it just gets re-filtered under the newly picked commodity, instead of forcing a
    # re-paste -- the whole point of picking it here rather than in the sidebar.
    state.set_commodity(st.session_state["import_commodity_picker"], clear_import_wizard=False)


_codes = list(COMMODITIES.keys())
st.selectbox(
    "Import as commodity",
    _codes,
    index=_codes.index(state.get_commodity_spec().code),
    format_func=lambda c: f"{COMMODITIES[c].icon} {COMMODITIES[c].name} ({c})",
    key="import_commodity_picker",
    on_change=_on_import_commodity_change,
    help="Only rows that look like this commodity's own contracts are pulled in below — "
         "everything else in the sheet is left out. Matches the sidebar; picking a "
         "different commodity here switches the whole dashboard to it.",
)

commodity = state.get_commodity_spec()

st.markdown("###### Getting this from QST")
st.info(
    "1. Go to QST\n"
    "2. Select your account\n"
    "3. Go to Orders and Positions Summary\n"
    "4. Export to Excel\n"
    f"5. Filter out all other commodities other than {commodity.name.lower()}\n"
    f"6. Copy the entire workbook (with {commodity.name.lower()} only filtered)\n"
    "7. Paste into cells below"
)

st.markdown("###### Paste or upload a position sheet")
st.caption(
    f"Works for {commodity.name.lower()} options and futures in the same sheet — column names "
    "and order don't need to match, you'll map them next. Every row needs a Contract symbol. "
    f"Strike, entry/premium, and last-tick prices are all read as {commodity.quote_unit}. If your "
    "Qty column is unsigned, also map Position (\"Net Long\"/\"Net Short\"/\"Net\") to supply the "
    "sign — a bare \"Net\" means flat and won't import. **Importing replaces your whole book** (cash positions you've entered are kept) — "
    "this only affects your own browser session, never anyone else's."
)


def _sample_text() -> str:
    exp1 = (date.today() + timedelta(days=32)).isoformat()
    exp2 = (date.today() + timedelta(days=95)).isoformat()
    return (
        "Symbol\tType\tStrike\tExpiration\tLots\tPremium\tLast Tick\n"
        f"ZCU26\tCall\t500\t{exp1}\t-30\t21\t2.0\n"
        f"ZCU26\tPut\t430\t{exp1}\t30\t19\t\n"
        "ZCU26\t\t\t\t10\t455\t\n"
        f"ZCZ26\tPut\t450\t{exp2}\t20\t22\t\n"
        f"ZCZ26\tCall\t490\t{exp2}\t-20\t15\t\n"
        "ZCZ26\t\t\t\t-8\t480\t465.25\n"
    )


col1, col2 = st.columns([4, 1])
with col2:
    st.write("")
    has_header = st.checkbox("First row is headers", value=True, key="import_has_header")
    load_sample_clicked = st.button("Load sample sheet")
if load_sample_clicked:
    st.session_state.import_paste_text = _sample_text()
with col1:
    pasted = st.text_area("Paste sheet cells here", key="import_paste_text", height=140,
                           placeholder="Symbol\tType\tStrike\tExpiration\tQty\tIV%\tEntry")

c1, c2 = st.columns(2)
parse_clicked = c1.button("Parse data", type="primary")
if c2.button("Reset"):
    for k in ["import_headers", "import_rows", "import_mapping", "import_staging"]:
        st.session_state.pop(k, None)
    st.rerun()

if parse_clicked:
    headers, rows = parse_pasted_text(st.session_state.import_paste_text, has_header)
    st.session_state.import_headers = headers
    st.session_state.import_rows = rows
    remembered = presets_repo.get_default_preset() or presets_repo.get_last_used_mapping() or QST_DEFAULT_MAPPING
    st.session_state.import_mapping = auto_map(headers, remembered)
    st.session_state.pop("import_staging", None)
    st.success(f"Parsed {len(rows)} row(s), {len(headers)} column(s). Map the columns below.")

if "import_headers" in st.session_state:
    headers = st.session_state.import_headers
    st.markdown("---")
    st.markdown("###### Map columns")

    presets = presets_repo.list_presets()
    preset_col, save_col = st.columns([2, 2])
    with preset_col:
        chosen_preset = st.selectbox("Load a saved preset", ["— none —"] + list(presets.keys()))
        # The button must always be instantiated -- `if cond and st.button(...)` only
        # calls st.button() when cond is true, and Streamlit can't reliably track a
        # widget's click across reruns if it isn't instantiated every run.
        apply_clicked = st.button("Apply preset", disabled=chosen_preset == "— none —")
        if apply_clicked and chosen_preset != "— none —":
            st.session_state.import_mapping = {
                t.key: headers.index(presets[chosen_preset][t.key]) if presets[chosen_preset].get(t.key) in headers else -1
                for t in IMPORT_TARGETS
            }
            st.rerun()
    with save_col:
        preset_name = st.text_input("Save current mapping as preset named…")
        if st.button("Save preset") and preset_name:
            header_mapping = mapping_to_header_names(st.session_state.import_mapping, headers)
            presets_repo.save_preset(preset_name, header_mapping, created_by="CJACOBS")
            st.success(f'Saved preset "{preset_name}".')
            st.rerun()

    options = ["— none —"] + headers
    new_mapping = {}
    cols = st.columns(3)
    for i, target in enumerate(IMPORT_TARGETS):
        idx = st.session_state.import_mapping.get(target.key, -1)
        with cols[i % 3]:
            selection = st.selectbox(target.label, options, index=idx + 1, key=f"map_{target.key}")
        new_mapping[target.key] = options.index(selection) - 1
    st.session_state.import_mapping = new_mapping

    if st.button("Build preview", type="primary"):
        header_mapping = mapping_to_header_names(new_mapping, headers)
        presets_repo.set_last_used_mapping(header_mapping, updated_by="CJACOBS")
        staging = [build_staging_row(row, headers, new_mapping, commodity.price_divisor) for row in st.session_state.import_rows]
        st.session_state.import_staging = staging

if "import_staging" in st.session_state:
    st.markdown("---")
    st.markdown("###### Preview & fix")
    staging = st.session_state.import_staging

    # A row whose label is positively identified as a *different* commodity is never
    # pulled in -- everything else (this commodity's own rows, plus any row whose label
    # doesn't recognizably belong to any commodity) is left for the usual Ready/Fix check.
    # Keyed by label rather than by row identity/equality, since two otherwise-identical
    # rows (same label, strike, qty, ...) would break an object-membership check.
    row_codes = {r.label: label_commodity_code(r.label) for r in staging if r.label}

    def _row_included(r) -> bool:
        return row_codes.get(r.label) in (None, commodity.code)

    included = [r for r in staging if _row_included(r)]
    skipped = [r for r in staging if not _row_included(r)]

    def _status(r) -> str:
        if not _row_included(r):
            other = COMMODITIES[row_codes[r.label]]
            return f"Skipped ({other.name})"
        return "Ready" if staging_row_valid(r) else "Fix"

    df = pd.DataFrame([{
        "Label": r.label, "Type": r.type, "Strike": r.strike, "Expiry": r.expiry,
        "Qty": r.qty, "IV%": r.iv, "Entry": r.entry, "Last tick": r.last_tick,
        "Status": _status(r),
    } for r in staging])
    st.dataframe(df, hide_index=True, use_container_width=True)

    valid_count = sum(1 for r in included if staging_row_valid(r))
    st.caption(f"{valid_count} of {len(included)} {commodity.name.lower()} row(s) are ready to import.")

    if skipped:
        skipped_codes = sorted({row_codes[r.label] for r in skipped})
        names = ", ".join(f"{COMMODITIES[c].name} ({c})" for c in skipped_codes)
        st.info(
            f"Skipped {len(skipped)} row(s) that look like a different commodity — {names}. "
            f"Only {commodity.name} rows are pulled in here; pick a different commodity above "
            "to import those instead.",
            icon=":material/info:",
        )
    if staging and not included:
        st.warning(
            f"None of these rows look like {commodity.name} contracts. Pick the commodity "
            "this sheet actually belongs to above, or fix the symbols, before importing.",
            icon=":material/warning:",
        )

    st.markdown("###### Adjust underlying futures contracts (optional)")
    st.caption(
        "Auto-derived per symbol — serial months roll to the next listed future"
        + (", and a listed month itself rolls forward once its own contract month begins (e.g. "
           "September corn options price off December starting Sep 1). "
           if commodity.rolls_at_month_start else
           f", and a {commodity.name.lower()} contract stays current through its own month. ")
        + "Override only the one-offs that still need fixing, using a canonical key like Z26 for December '26."
    )
    distinct_labels = sorted({r.label for r in included if r.label})
    prior_overrides = st.session_state.get("import_underlying_overrides", {})
    override_df = pd.DataFrame([{
        "Symbol": label,
        "Auto underlying": contract_display_name(label, commodity=commodity),
        "Override (blank = auto)": prior_overrides.get(label, ""),
    } for label in distinct_labels])
    edited_overrides = st.data_editor(
        override_df, hide_index=True, use_container_width=True,
        key="underlying_override_editor",
        disabled=["Symbol", "Auto underlying"],
    )
    new_overrides = {}
    bad_overrides = []
    for _, row in edited_overrides.iterrows():
        val = str(row["Override (blank = auto)"] or "").strip().upper()
        if not val:
            continue
        key = normalize_underlying_override(val, commodity)
        if key:
            new_overrides[row["Symbol"]] = key
        else:
            bad_overrides.append((row["Symbol"], val))
    st.session_state.import_underlying_overrides = new_overrides
    if bad_overrides:
        bad_str = ", ".join(f'{sym}: "{val}"' for sym, val in bad_overrides)
        st.warning(
            f'Ignoring invalid override(s) — use a month letter + 2-digit year, e.g. "V26" or '
            f'"{commodity.code}V26" for October \'26: {bad_str}'
        )

    if st.button(f"Replace book with {valid_count} position(s)", type="primary", disabled=valid_count == 0):
        positions, estimated_count = positions_from_staging(
            included,
            get_contract_price=state.get_contract_price,
            snapshot_iv=state.snapshot_iv,
            canonical_contract_key=lambda label: canonical_contract_key(label, commodity=commodity),
            underlying_overrides=new_overrides,
        )
        kept_cash = sum(1 for p in state.visible_positions() if p.is_cash)
        count = state.replace_book(positions)
        for k in ["import_headers", "import_rows", "import_mapping", "import_staging", "import_underlying_overrides"]:
            st.session_state.pop(k, None)
        msg = f"Replaced your book with {count} position(s)."
        if kept_cash:
            msg += f" Kept your {kept_cash} cash position(s)."
        if estimated_count:
            msg += f" {estimated_count} had no IV in the sheet — filled from the market snapshot."
        st.success(msg)
