"""The standard JSA legal disclaimer: the page footer, and the same wording as plain text for the
images that leave the app (chart, table and card PNGs)."""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape

import streamlit as st

DISCLAIMER_FOOTER_HTML = (
    '<hr style="border-color:#3a3a3a;margin-top:32px;margin-bottom:16px">'
    '<div style="font-family:inherit;color:#888;font-size:inherit;line-height:1.6;text-align:center;padding:0 24px 24px;">'
    'Trading commodity futures, options on futures, cash commodities, and over-the-counter derivative '
    'products involves substantial risk of loss and may not be suitable for all investors. '
    'This communication is provided for informational purposes only and does not constitute investment '
    'advice, a recommendation, or an offer or solicitation to buy or sell any futures, options, cash '
    'commodities, or derivative products. John Stewart &amp; Associates, Inc. does not accept orders to '
    'buy or sell any financial instruments via email. The information contained herein has been obtained '
    'from sources believed to be reliable; however, its accuracy and completeness are not guaranteed. '
    'Any opinions expressed are solely those of the author, are subject to change without notice, and '
    'should not be relied upon as a basis for investment decisions. Past performance is not indicative of '
    'future results. This message may contain confidential or proprietary information intended solely for '
    'the use of the designated recipient. &copy; John Stewart &amp; Associates, Inc. {year}</div>'
)


def render_disclaimer_footer():
    """The standard JSA legal footer used across the dashboard family (verbatim, see
    e.g. beef-trimmings-dashboard/app.py)."""
    st.markdown(DISCLAIMER_FOOTER_HTML.format(year=datetime.now().year), unsafe_allow_html=True)


def disclaimer_text() -> str:
    """The footer's wording as plain text, for the images that leave the app."""
    plain = unescape(re.sub(r"<[^>]*>", "", DISCLAIMER_FOOTER_HTML))
    return plain.format(year=datetime.now().year)
