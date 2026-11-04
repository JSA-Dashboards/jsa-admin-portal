"""
cot_groups.py -- add COT positions up across markets (the soy complex = soybeans + meal + oil).

No Streamlit in here, so it can be tested on its own.

TWO WAYS TO ADD, because the contracts are different sizes. A soybean contract is 5,000 bu, a meal
contract 100 tons and an oil contract 60,000 lb, so adding raw contracts counts a meal contract
the same as a soybean one:

  Contracts     -- the plain sum of each position column across the markets.
  Dollar value  -- each market's positions are first multiplied by (contract size x price) and shown
                   in $ millions, then summed. The price is the LATEST front-month settle, held
                   constant over the whole history: the weight on each market is fixed, so a change in
                   the group's position reflects what the funds did and not what prices did. (It
                   also means old history is valued at today's prices, which is the point of the
                   constant weight, not an error.)

A group only exists on report dates where EVERY member reported, and a preset group is skipped
unless every member is present, so a missing market can never make a group look smaller.
`traders_total` is not summed: a trader active in two markets would be counted twice.
"""
from __future__ import annotations

import pandas as pd

# Preset groups: key -> (label, member series). Keys start with GRP_ so they can never clash with a
# CFTC series name.
BASKETS = {
    "GRP_SOY_COMPLEX": ("Soy complex", ["SOYBEANS", "SOYBEAN_MEAL", "SOYBEAN_OIL"]),
    "GRP_ALL_WHEAT": ("All wheat", ["WHEAT_SRW", "WHEAT_HRW", "WHEAT_HRS"]),
    "GRP_LIVESTOCK": ("Livestock", ["LIVE_CATTLE", "FEEDER_CATTLE", "LEAN_HOGS"]),
}
CUSTOM = "GRP_CUSTOM"

# Dollars per contract for each 1.00 of the settle price, in the unit the settle is quoted in:
#   grains   5,000 bu, price in cents/bu          -> 5,000 / 100 = 50
#   meal       100 tons, price in $/ton           -> 100
#   oil     60,000 lb, price in cents/lb          -> 60,000 / 100 = 600
#   live cattle 40,000 lb, feeder 50,000 lb, hogs 40,000 lb, price in cents/lb -> 400 / 500 / 400
DOLLARS_PER_POINT = {
    "CORN": 50.0, "SOYBEANS": 50.0, "WHEAT_SRW": 50.0, "WHEAT_HRW": 50.0, "WHEAT_HRS": 50.0,
    "SOYBEAN_MEAL": 100.0, "SOYBEAN_OIL": 600.0,
    "LIVE_CATTLE": 400.0, "FEEDER_CATTLE": 500.0, "LEAN_HOGS": 400.0,
}

# Every column that is a count of contracts and so can be added across markets.
SUMMED = (
    "open_interest", "open_interest_chg",
    "prod_merc_long", "prod_merc_short", "prod_merc_net",
    "swap_long", "swap_short", "swap_net",
    "mm_long", "mm_short", "mm_spread", "mm_net", "mm_long_chg", "mm_short_chg",
    "other_long", "other_short", "other_net",
    "nonrept_long", "nonrept_short", "nonrept_net",
)


def dollar_weights(prices: dict[str, float]) -> dict[str, float]:
    """$ millions per contract for each series that has both a contract size and a price."""
    return {s: DOLLARS_PER_POINT[s] * p / 1e6 for s, p in prices.items()
            if s in DOLLARS_PER_POINT and p is not None and pd.notna(p) and p > 0}


def to_dollars(df: pd.DataFrame, weights: dict[str, float]) -> tuple[pd.DataFrame, list[str]]:
    """Positions in $ millions. Series with no weight (no price, or no known contract size) are
    dropped and returned by name, never silently valued at zero."""
    cols = [c for c in SUMMED if c in df.columns]
    have = list(dict.fromkeys(df.series))
    out = df[df.series.isin(weights)].copy()
    out[cols] = out[cols].mul(out.series.map(weights), axis=0)
    return out, [s for s in have if s not in weights]


def combine(df: pd.DataFrame, key: str, members: list[str]) -> pd.DataFrame:
    """One new series `key`: the members' position columns summed on the report dates they all share."""
    parts = []
    for m in members:
        p = df[df.series == m].drop_duplicates("report_date").set_index("report_date")
        if p.empty:
            return df.iloc[0:0]
        parts.append(p)
    idx = parts[0].index
    for p in parts[1:]:
        idx = idx.intersection(p.index)
    if len(idx) == 0:
        return df.iloc[0:0]
    cols = [c for c in SUMMED if c in df.columns]
    total = parts[0].loc[idx, cols].copy()
    for p in parts[1:]:
        total = total + p.loc[idx, cols]
    out = total.reset_index().sort_values("report_date")
    for c in df.columns:  # columns that are not positions (report_type ...): same for every member
        if c not in out.columns and c != "series":
            out[c] = parts[0][c].iloc[0] if c in parts[0].columns else pd.NA
    out["series"] = key
    if "traders_total" in out.columns:
        out["traders_total"] = float("nan")
    return out[[c for c in df.columns if c in out.columns]]


def with_groups(df: pd.DataFrame, custom: list[str] | None = None,
                label=lambda s: s) -> tuple[pd.DataFrame, list[str]]:
    """`df` plus one series per group that can be built from it, and a note for each that could not.
    `label` turns a series code into the name shown in a note."""
    present = set(df.series)
    extra, notes = [], []
    for key, (name, members) in BASKETS.items():
        missing = [m for m in members if m not in present]
        if missing:
            notes.append(f"{name} is not shown: no data for {', '.join(label(m) for m in missing)}.")
            continue
        g = combine(df, key, members)
        if g.empty:
            notes.append(f"{name} is not shown: its markets share no report dates.")
        else:
            extra.append(g)
    custom = list(custom or [])
    if len(custom) >= 2:
        missing = [m for m in custom if m not in present]
        if missing:
            notes.append(f"Your custom group is not shown: no data for {', '.join(label(m) for m in missing)}.")
        else:
            g = combine(df, CUSTOM, custom)
            if g.empty:
                notes.append("Your custom group is not shown: its markets share no report dates.")
            else:
                extra.append(g)
    return (pd.concat([df, *extra], ignore_index=True) if extra else df), notes
