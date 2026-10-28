"""Reference data — replaces the HTML tool's hardcoded IV_SNAPSHOT / PRIOR_SETTLE JS
blocks and in-memory contractPrices map with admin-editable Snowflake tables. Reads are
cached briefly since these change only when someone runs a refresh, not every rerun.
"""
from typing import Dict, List, Optional

import streamlit as st

from . import snowflake_client as sf

DEFAULT_IV = 21.0
DEFAULT_CONTRACT_PRICE = 4.62


@st.cache_data(ttl=60, show_spinner=False)
def get_iv_snapshot() -> Dict[str, float]:
    df = sf.query_df("SELECT CANONICAL_KEY, IV FROM IV_SNAPSHOT")
    return {row["CANONICAL_KEY"]: float(row["IV"]) for _, row in df.iterrows()}


def snapshot_iv(canonical_key: str) -> float:
    return get_iv_snapshot().get(canonical_key, DEFAULT_IV)


@st.cache_data(ttl=60, show_spinner=False)
def get_iv_provenance() -> List[dict]:
    """Per-contract vol with where it came from and how old it is.

    The vols are refreshed out-of-band by scripts/refresh_iv_from_cme.py, so nothing in
    the app makes their age visible. A settlement vol from a fortnight ago looks exactly
    like this morning's until you show AS_OF, and an expired contract's row lingers
    indefinitely — hence this.
    """
    df = sf.query_df(
        "SELECT CANONICAL_KEY, IV, AS_OF, SOURCE FROM IV_SNAPSHOT ORDER BY AS_OF DESC NULLS LAST"
    )
    return [
        {"key": r["CANONICAL_KEY"], "iv": float(r["IV"]), "as_of": r["AS_OF"],
         "source": r["SOURCE"] or ""}
        for _, r in df.iterrows()
    ]


def upsert_iv_snapshot(canonical_key: str, iv: float, source: str, updated_by: str) -> None:
    sf.execute(
        """
        MERGE INTO IV_SNAPSHOT t USING (SELECT %s AS KEY) s ON t.CANONICAL_KEY = s.KEY
        WHEN MATCHED THEN UPDATE SET IV=%s, SOURCE=%s, AS_OF=CURRENT_TIMESTAMP(), UPDATED_AT=CURRENT_TIMESTAMP(), UPDATED_BY=%s
        WHEN NOT MATCHED THEN INSERT (CANONICAL_KEY, IV, SOURCE, AS_OF, UPDATED_BY)
                          VALUES (%s, %s, %s, CURRENT_TIMESTAMP(), %s)
        """,
        (canonical_key, iv, source, updated_by, canonical_key, iv, source, updated_by),
    )
    get_iv_snapshot.clear()
    get_iv_provenance.clear()


@st.cache_data(ttl=60, show_spinner=False)
def get_contract_mark_provenance() -> List[dict]:
    """Per-contract futures mark with where it came from and how old it is.

    The exact counterpart of get_iv_provenance, and added for a sharper reason: the mark
    is refreshed only when somebody presses "Update prices from Massive", so a mark from
    last week looks precisely like this morning's. Every greek on the page is priced off
    it, so when it stands still the heatmap, the Greeks bars and Net Position all stand
    still with it -- while the blotter keeps moving, because that prices each leg off its
    own last tick. That divergence was reported as "the heatmap isn't updating" and took
    an investigation to trace; UPDATED_AT was already on the table and nothing read it.
    """
    df = sf.query_df(
        "SELECT CANONICAL_KEY, MARK_PRICE, SOURCE, UPDATED_AT FROM CONTRACT_MARKS "
        "ORDER BY UPDATED_AT DESC NULLS LAST"
    )
    return [
        {"key": r["CANONICAL_KEY"], "price": float(r["MARK_PRICE"]),
         "source": r["SOURCE"] or "", "updated_at": r["UPDATED_AT"]}
        for _, r in df.iterrows()
    ]


@st.cache_data(ttl=60, show_spinner=False)
def get_contract_marks() -> Dict[str, float]:
    df = sf.query_df("SELECT CANONICAL_KEY, MARK_PRICE FROM CONTRACT_MARKS")
    return {row["CANONICAL_KEY"]: float(row["MARK_PRICE"]) for _, row in df.iterrows()}


def get_contract_price(canonical_key: str, default: float = DEFAULT_CONTRACT_PRICE) -> float:
    return get_contract_marks().get(canonical_key, default)


def set_contract_price(canonical_key: str, price: float, source: str = "manual") -> None:
    sf.execute(
        """
        MERGE INTO CONTRACT_MARKS t USING (SELECT %s AS KEY) s ON t.CANONICAL_KEY = s.KEY
        WHEN MATCHED THEN UPDATE SET MARK_PRICE=%s, SOURCE=%s, UPDATED_AT=CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (CANONICAL_KEY, MARK_PRICE, SOURCE) VALUES (%s, %s, %s)
        """,
        (canonical_key, price, source, canonical_key, price, source),
    )
    get_contract_marks.clear()
    # Both caches read the same row, so clearing one and not the other would leave the
    # age caption calling a mark a day old a second after someone refreshed it.
    get_contract_mark_provenance.clear()


@st.cache_data(ttl=60, show_spinner=False)
def get_prior_settle_future(canonical_key: str) -> Optional[float]:
    df = sf.query_df("SELECT SETTLE_PRICE FROM PRIOR_SETTLE_FUTURES WHERE CANONICAL_KEY = %s", (canonical_key,))
    return None if df.empty else float(df.iloc[0]["SETTLE_PRICE"])


@st.cache_data(ttl=60, show_spinner=False)
def get_prior_settle_option(canonical_key: str, opt_type: str, strike: float) -> Optional[float]:
    df = sf.query_df(
        "SELECT SETTLE_PRICE FROM PRIOR_SETTLE_OPTIONS WHERE CANONICAL_KEY=%s AND OPT_TYPE=%s AND STRIKE=%s",
        (canonical_key, opt_type, strike),
    )
    return None if df.empty else float(df.iloc[0]["SETTLE_PRICE"])
