"""Brand header + the two-paragraph disclaimer — rendered once by app.py before
dispatching to whichever page/tab is active, so it's guaranteed identical everywhere."""
from pathlib import Path

import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets"

_ACCENT_CSS = """
<style>
[data-testid="stMetricValue"], .stDataFrame, .stNumberInput input { font-variant-numeric: tabular-nums; }
.jsa-logo-card { background:#ffffff; border-radius:8px; padding:5px 9px; display:inline-flex;
  align-items:center; box-shadow: 0 1px 3px rgba(0,0,0,0.18); }
.jsa-brand-title { font-weight:800; font-size:20px; letter-spacing:0.01em; }
.jsa-brand-title span { color:#d55181; }
.jsa-brand-sub { font-size:13px; opacity:0.72; }
.jsa-disclaimer { font-size:10.5px; opacity:0.68; line-height:1.6; border-top:1px solid rgba(128,128,128,0.35);
  border-bottom:1px solid rgba(128,128,128,0.35); padding:12px 0; margin: 4px 0 18px; }
.jsa-disclaimer p { margin: 0 0 10px; }
.jsa-disclaimer p:last-child { margin-bottom: 0; }
</style>
"""

_DISCLAIMER_HTML = """
<div class="jsa-disclaimer">
<p>All prices, Greeks, P&amp;L, and risk figures on this dashboard are theoretical model outputs
generated from the Black-76 pricing model and the position data entered or imported by the user.
They are provided for informational and analytical purposes only, do not constitute a guarantee
of accuracy, and may differ materially from actual market prices, executable levels, or realized
results. Verify all figures against an official broker or exchange source before making any
trading or risk decision. Futures prices pulled via a live market-data feed are delayed
approximately 10 minutes and are not real-time or executable quotes.</p>
<p>Trading commodity futures, options on futures, cash commodities, and over-the-counter
derivative products involves substantial risk of loss and may not be suitable for all investors.
This communication is provided for informational purposes only and does not constitute
investment advice, a recommendation, or an offer or solicitation to buy or sell any futures,
options, cash commodities, or derivative products.  John Stewart &amp; Associates, Inc. does not
accept orders to buy or sell any financial instruments via email. The information contained
herein has been obtained from sources believed to be reliable; however, its accuracy and
completeness are not guaranteed. Any opinions expressed are solely those of the author, are
subject to change without notice, and should not be relied upon as a basis for investment
decisions. Past performance is not indicative of future results. This message may contain
confidential or proprietary information intended solely for the use of the designated recipient.
&copy; John Stewart &amp; Associates, Inc. 2026</p>
</div>
"""


def render_header_and_disclaimer(commodity_name: str = "Corn") -> None:
    st.markdown(_ACCENT_CSS, unsafe_allow_html=True)

    logo_col, title_col = st.columns([1, 8], vertical_alignment="center")
    logo_path = ASSETS_DIR / "jsa_logo.png"
    with logo_col:
        if logo_path.exists():
            st.markdown('<div class="jsa-logo-card">', unsafe_allow_html=True)
            st.image(str(logo_path), width=120)
            st.markdown("</div>", unsafe_allow_html=True)
    with title_col:
        st.markdown(
            '<div class="jsa-brand-title">JSA<span> RISK ANALYZER</span></div>'
            f'<div class="jsa-brand-sub">{commodity_name} Options &amp; Futures — Portfolio Risk Dashboard</div>',
            unsafe_allow_html=True,
        )

    st.markdown(_DISCLAIMER_HTML, unsafe_allow_html=True)
