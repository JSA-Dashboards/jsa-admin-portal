import streamlit as st

from jsa_risk.state import get_commodity_spec, get_contract_price, init_session_state, visible_positions
from jsa_risk.ui.blotter import render_editable_blotter
from jsa_risk.ui.cash_position import render_cash_position_entry
from jsa_risk.ui.charts import (
    default_shock_window,
    render_delta_scenario,
    render_greeks_bars,
    render_payoff_chart,
    render_pnl_heatmap,
    shock_windows_for,
    shocks_in_cents,
)
from jsa_risk.ui.kpi import render_kpi_strip, render_var_panel
from jsa_risk.ui.market_strip import (
    render_iv_provenance,
    render_iv_refresh,
    render_market_strip,
    render_massive_refresh,
)

# Defensive, not redundant: app.py already calls this before dispatching to a page, but
# Streamlit Cloud reconnecting a browser tab to a session the server no longer has state
# for (e.g. after the app wakes from being asleep) can land directly on a page's script
# without that preamble having run for *this* render -- init_session_state() is written
# to be idempotent for exactly this reason (every page calls it at the top).
init_session_state()

flash_added = st.session_state.pop("_flash_added", None)
flash_market = st.session_state.pop("_flash_market_update", None)
flash_iv = st.session_state.pop("_flash_iv_update", None)
flash = flash_added or flash_market or flash_iv
if flash:
    st.success(flash)

commodity = get_commodity_spec()

st.markdown("###### Portfolio risk summary")
positions = visible_positions()
stress = st.session_state.stress

render_kpi_strip(positions, stress, get_contract_price, commodity)

st.markdown("---")

st.markdown("###### Stress scenario")
c1, c2, c3, c4 = st.columns([3, 3, 3, 1])
stress.price_pct = c1.slider("Price shock %", -30.0, 30.0, stress.price_pct, 1.0)
stress.vol_pct = c2.slider("Vol shock %", -50.0, 100.0, stress.vol_pct, 5.0)
stress.days = c3.slider("Days forward", 0, 120, int(stress.days), 1)
with c4:
    st.write("")
    st.write("")
    if st.button("Reset"):
        stress.price_pct, stress.vol_pct, stress.days = 0.0, 0.0, 0.0
        st.rerun()

st.markdown("---")

st.markdown("###### Live market data")
price_col, greeks_col = st.columns(2)
with price_col:
    render_massive_refresh(positions, commodity)
with greeks_col:
    render_iv_refresh(positions, commodity)
render_market_strip(positions, commodity)
render_iv_provenance(positions, commodity)

st.markdown("---")

render_cash_position_entry(positions, commodity)

st.markdown("---")

st.markdown("###### Position blotter")
st.caption("This book is private to your browser session — Qty and Entry are editable; check Delete to remove a row.")
render_editable_blotter(positions, stress, get_contract_price, commodity)

st.markdown("---")
st.markdown("###### Greeks by contract")
render_greeks_bars(positions, stress, get_contract_price, commodity)

st.markdown("---")
# Cattle's presets are in cents per pound, every other commodity's in percent -- so the
# options differ by commodity, and so does the widget key. One shared key would carry a
# percent label into a cents commodity (or back) on switching, and Streamlit raises when a
# stored radio value isn't among the options it's handed.
windows = shock_windows_for(commodity)
shock_window = st.radio(
    "Price shock window (applies to the three scenario charts below)",
    list(windows),
    index=list(windows).index(default_shock_window(commodity)),
    horizontal=True,
    key=f"shock_window_{commodity.code}",
)
shock_axis_text = (
    f"Price shock (x-axis, ¢ per {commodity.unit}, the same move on every contract, with the % of the "
    "book's average price beneath)" if shocks_in_cents(commodity) else
    f"Price shock (x-axis, % of the book's average price, with the ≈¢ per {commodity.unit} move "
    "beneath, applied equally to every contract)"
)

st.markdown("###### P&L scenario heatmap")
st.caption(f"{shock_axis_text} vs. vol shock (y-axis, %) layered on top of the current stress scenario.")
render_pnl_heatmap(positions, stress, get_contract_price, commodity=commodity, shock_window=shock_window)

st.markdown("###### Delta scenario")
render_delta_scenario(positions, stress, get_contract_price, commodity=commodity, shock_window=shock_window)

st.markdown("---")
st.markdown("###### Portfolio payoff")
payoff_shock_text = (
    f"¢ per {commodity.unit}, same move on every contract" if shocks_in_cents(commodity) else
    f"% of the book's average price, with the ≈¢ per {commodity.unit} move, applied equally to every contract"
)
st.caption(f"P&L vs. a {commodity.name.lower()} futures price shock ({payoff_shock_text}), current vol & time.")
render_payoff_chart(positions, stress, get_contract_price, commodity=commodity, shock_window=shock_window)

st.markdown("---")
st.markdown("###### Value at risk")
render_var_panel(positions, stress, get_contract_price, commodity)
