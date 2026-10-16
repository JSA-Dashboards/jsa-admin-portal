"""
Heifers as a share of cattle on feed: the feedlot side of the retention story.

WHY THIS SITS BESIDE THE RECEIPTS CHART. It measures the same decision from the
opposite end and from an unrelated dataset. The receipts share counts heifers
arriving at auction (USDA AMS, barn-level); this counts heifers standing in
feedlots (USDA NASS, a survey of feedyards). A heifer on feed is a heifer that
was NOT kept back to breed, so both series fall when producers retain -- and
they are wrong in different ways, which is exactly why agreeing means something.

They do agree. Peak 2023 in both. Trough 2015-2016 in both. Down about two and a
half points from peak in both, as of mid-2026.

THIS IS NOT REPLACEMENT-HEIFER INVENTORY, and the names invite that mistake.
"Heifers on feed" are females committed to beef; "beef replacement heifers" are
females held for breeding. They are mirror images, not substitutes. The
replacement series is still absent from the NASS cache -- see the Awaiting Data
note on the page.

NO API KEY. This reads the shared NASS cache (JSA.NASS_CACHE), populated by the
usda-nass-etl job that holds the key. The series is already cached for the
Cattle on Feed dashboard, and cache keys are (endpoint, params) with no
dashboard in them, so it is readable here with no new ETL and no new secret --
which keeps the promise in CLAUDE.md that this page needs no credential beyond
the Snowflake block.

COMPARE LIKE QUARTER WITH LIKE. The series is seasonal: April sits roughly 1.3
points below the other three quarters, every year. So a raw quarter-on-quarter
move is mostly calendar. The chart therefore plots a trailing FOUR-QUARTER mean,
the direct analogue of the 52-week window used on the receipts chart and for the
same reason, and the year-ago tile compares a quarter with its own quarter.
"""
from statistics import mean

import nass_env  # noqa: F401  -- import order matters: bridges the passphrase
import nass_cache_client as nc  # noqa: E402  -- must follow nass_env

# Matches jobs/cattle_on_feed.py in usda-nass-etl exactly. The cache key is a
# hash of these params, so any difference here silently returns an empty result
# rather than an error -- do not "tidy" them.
BASE = {
    "source_desc": "SURVEY",
    "sector_desc": "ANIMALS & PRODUCTS",
    "group_desc": "LIVESTOCK",
    "commodity_desc": "CATTLE",
}
HEIFERS = "CATTLE, HEIFERS & HEIFER CALVES, ON FEED - INVENTORY"
STEERS = "CATTLE, STEERS & STEER CALVES, ON FEED - INVENTORY"

QUARTERS = {"FIRST OF JAN": 1, "FIRST OF APR": 2,
            "FIRST OF JUL": 3, "FIRST OF OCT": 4}
LABELS = {1: "Jan 1", 2: "Apr 1", 3: "Jul 1", 4: "Oct 1"}
WINDOW = 4                      # quarters in the trailing mean


def _national(short_desc):
    """{(year, quarter): head} for the national series."""
    out = {}
    for x in nc.fetch_cached({**BASE, "short_desc": short_desc}).get("data", []):
        if x.get("agg_level_desc") != "NATIONAL":
            continue
        q = QUARTERS.get(x.get("reference_period_desc"))
        if not q:
            continue
        try:
            out[(int(x["year"]), q)] = int(str(x["Value"]).replace(",", ""))
        except (ValueError, KeyError, TypeError):
            continue            # NASS suppresses cells as "(D)"; skip them
    return out


def on_feed_share():
    """
    [{year, quarter, label, heifers, steers, share, trailing}] oldest first.

    `trailing` is the mean share over this quarter and the three before it, and
    is None until four quarters exist. It is the seasonally neutral read; the
    raw `share` is not comparable across quarters.
    """
    H, S = _national(HEIFERS), _national(STEERS)
    keys = sorted(set(H) & set(S))
    rows = []
    for y, q in keys:
        h, s = H[(y, q)], S[(y, q)]
        if not (h + s):
            continue
        rows.append({"year": y, "quarter": q, "label": f"{LABELS[q]} {y}",
                     "heifers": h, "steers": s,
                     "share": 100.0 * h / (h + s), "trailing": None})
    for i in range(WINDOW - 1, len(rows)):
        # Only average over quarters that are actually consecutive -- a gap in
        # the survey would otherwise be averaged straight through.
        span = rows[i - WINDOW + 1:i + 1]
        steps = [(b["year"] - a["year"]) * 4 + (b["quarter"] - a["quarter"])
                 for a, b in zip(span, span[1:])]
        if all(step == 1 for step in steps):
            rows[i]["trailing"] = mean(r["share"] for r in span)
    return rows


def on_feed_summary():
    """Headline figures, all on the seasonally neutral trailing mean."""
    rows = on_feed_share()
    have = [r for r in rows if r["trailing"] is not None]
    if len(have) < 8:
        return None
    cur = have[-1]
    hi = max(have, key=lambda r: r["trailing"])
    lo = min(have, key=lambda r: r["trailing"])
    # Same quarter, a year earlier -- the only honest single-step comparison.
    prior = next((r for r in rows
                  if r["year"] == cur["year"] - 1 and r["quarter"] == cur["quarter"]), None)
    return {
        "rows": rows, "current": cur, "high": hi, "low": lo,
        "fall_from_high": cur["trailing"] - hi["trailing"],
        "year_ago": prior,
        "yoy_pts": (cur["share"] - prior["share"]) if prior else None,
    }
