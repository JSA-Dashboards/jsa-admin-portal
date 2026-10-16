"""
The head counts: how many breeding females there are, and how fast they are
being culled. The half of this page that was "awaiting data" until the two NASS
series behind it were added to usda-nass-etl (jobs/us_cow_herd.py).

Everything else on the page is a price or a receipt. Those measure the retention
DECISION and what producers did about it at the sale barn. These measure the
herd itself:

    replacement heifers / beef cows   the standard expansion measure -- females
                                      entering the herd against females in it
    beef cow slaughter                the culling side of the same ledger

READ THEM TOGETHER, AND EXPECT THE STOCK TO LAG THE FLOWS. Slaughter and the
replacement ratio are flows; the cow herd is a stock. Culling can stop and
heifers start being kept while the herd is still shrinking, because the herd only
grows once retained heifers calve. A rebuild therefore shows up in this order:
slaughter falls, the ratio turns up, and beef cow inventory bottoms last.

TWO TRAPS, BOTH SILENT.

1. PARAM SHAPE DECIDES THE CACHE KEY, and the shapes are not uniform. Beef cows
   are cached by jobs/livestock_inventory.py with only short_desc +
   agg_level_desc; the two series added for this page carry the full BASE block
   as well, matching jobs/us_cow_herd.py. Query with the wrong shape and the
   cache returns {"data": []} -- no error, just nothing. Each series below is
   paired with the shape that actually fetches it.

2. THE SLAUGHTER RESPONSE MIXES THREE FREQUENCIES. One call returns WEEKLY
   (~2,100 rows), MONTHLY (~490) and ANNUAL (~40) together. Summing without
   filtering freq_desc triple-counts the year -- it produced a 2022 figure of
   11.9 million against a true 3.95 million, which looks like a plausible cattle
   number rather than an obvious error. Always filter on freq_desc.
"""
import nass_env  # noqa: F401  -- import order matters: bridges the passphrase
import nass_cache_client as nc  # noqa: E402  -- must follow nass_env

# The BASE block jobs/us_cow_herd.py caches with. Beef cows deliberately do NOT
# use it -- see trap 1 above.
BASE = {
    "source_desc": "SURVEY",
    "sector_desc": "ANIMALS & PRODUCTS",
    "group_desc": "LIVESTOCK",
    "commodity_desc": "CATTLE",
}

REPL_HEIFERS = {**BASE, "agg_level_desc": "NATIONAL",
                "short_desc": "CATTLE, HEIFERS, GE 500 LBS, BEEF REPLACEMENT - INVENTORY"}
BEEF_COWS = {"agg_level_desc": "NATIONAL",
             "short_desc": "CATTLE, COWS, BEEF - INVENTORY"}
COW_SLAUGHTER = {**BASE, "agg_level_desc": "NATIONAL",
                 "short_desc": "CATTLE, COWS, (EXCL MILK), SLAUGHTER, COMMERCIAL, "
                               "FI - SLAUGHTERED, MEASURED IN HEAD"}

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _num(v):
    try:
        return int(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None                 # NASS suppresses cells as "(D)"


def _rows(params):
    return [x for x in nc.fetch_cached(params).get("data", [])
            if x.get("agg_level_desc") == "NATIONAL"]


def _jan1(params):
    """{year: head} from the Jan 1 inventory rows."""
    out = {}
    for x in _rows(params):
        if x.get("reference_period_desc") != "FIRST OF JAN":
            continue
        v = _num(x.get("Value"))
        if v is not None:
            out[int(x["year"])] = v
    return out


def replacement_ratio():
    """
    [{year, heifers, cows, ratio}] -- replacement heifers as a percent of beef
    cows, January 1. The standard measure of whether the herd is set to grow.
    """
    h, c = _jan1(REPL_HEIFERS), _jan1(BEEF_COWS)
    return [{"year": y, "heifers": h[y], "cows": c[y],
             "ratio": 100.0 * h[y] / c[y]}
            for y in sorted(set(h) & set(c)) if c[y]]


def cow_slaughter():
    """
    {"annual": [{year, head}], "ytd": [{year, head, through}]}

    Annual comes from the ANNUAL rows, never from summing months -- see trap 2.
    The YTD series compares each year over the SAME months the newest year has
    reported, so a part-year is not set against whole ones.
    """
    rows = _rows(COW_SLAUGHTER)
    annual = {}
    monthly = {}
    for x in rows:
        v = _num(x.get("Value"))
        if v is None:
            continue
        freq, year = x.get("freq_desc"), int(x["year"])
        if freq == "ANNUAL":
            annual[year] = v
        elif freq == "MONTHLY":
            monthly[(year, x.get("reference_period_desc"))] = v

    ytd = []
    if monthly:
        newest = max(y for y, _ in monthly)
        have = [m for m in MONTHS if (newest, m) in monthly]
        if have:
            for y in sorted({y for y, _ in monthly}):
                got = [monthly[(y, m)] for m in have if (y, m) in monthly]
                if len(got) == len(have):       # only whole, comparable spans
                    ytd.append({"year": y, "head": sum(got), "through": have[-1]})
    return {"annual": [{"year": y, "head": annual[y]} for y in sorted(annual)],
            "ytd": ytd}


def inventory_summary():
    """Headline figures, or None if the series have not been cached yet."""
    ratio = replacement_ratio()
    sl = cow_slaughter()
    if len(ratio) < 5 or not sl["ytd"]:
        return None
    cur = ratio[-1]
    prev = ratio[-2]
    recent = [r for r in ratio if r["year"] >= cur["year"] - 15]
    hi = max(recent, key=lambda r: r["ratio"])
    lo = min(recent, key=lambda r: r["ratio"])
    y = sl["ytd"]
    sl_hi = max(sl["annual"][-15:], key=lambda r: r["head"]) if sl["annual"] else None
    return {
        "ratio": ratio, "current": cur, "prev": prev,
        "recent_high": hi, "recent_low": lo,
        "turned_up": cur["ratio"] > prev["ratio"],
        "slaughter": sl, "ytd_current": y[-1], "ytd_prev": y[-2] if len(y) > 1 else None,
        "slaughter_peak": sl_hi,
        "slaughter_annual_latest": sl["annual"][-1] if sl["annual"] else None,
    }
