"""
Did the herd actually expand, and did these signals call it?

Three signals the page already carries, set against the one thing that is not
a signal at all -- USDA's January 1 beef cow count:

    retention incentive      PRICE    what keeping her paid
    heifer share of receipts VOLUME   what producers did at the sale barn
    heifers on feed          VOLUME   where the heifers actually went
    beef cow inventory       COUNT    what the herd did, per NASS

THE VERDICT FOR A YEAR IS NEXT JANUARY'S COUNT, not this one's. Decisions made
during 2015 show up in the January 1 2016 inventory, so a signal read in 2015
is scored against the change from Jan-2015 to Jan-2016. Scoring it against the
change INTO 2015 would be asking whether the signal remembers the past, which
it does slightly better (r=+0.79) and which is worth nothing.

WHAT IS ACTUALLY ESTABLISHED, and it is less than the first cut of this
suggested. The retention incentive moves with the herd's change at r=+0.87
over 18 years, which needs no threshold and is the honest headline.

A DIVIDING LINE EXISTS BUT IT IS SOFT. Fitting a single cut to these 18 years
gets 17 of them right at 1.068 -- and that is an IN-SAMPLE number with one free
parameter chosen on the same data it is scored against. Leave-one-out, refitting
the cut without each year and then predicting it, gives **15/18** against a null
of 13/18 for simply saying "contract" every year. The refitted cut ranges 1.064
to 1.102 across those 18 refits. So the page draws a BAND, not a line, and says
15/18 rather than 17/18. Two years of edge over always-guessing-down is real and
is not a rule to trade off alone.

The other two signals have cuts of the same kind -- heifers on feed near 35.9%,
heifer receipts near 40.8% -- and combining all three scores no better than
retention by itself, so there is no ensemble here worth the name. They are
shown because their DISAGREEMENT is where the interest is: the three split in
5 of 19 years -- 2014, 2017, 2018, 2019 and 2026 -- and four of those sit at
the start, inside or at the end of the single expansion on record. That is
suggestive and it is not a rule: 2017 is squarely mid-expansion, and 2018 and
2019 split the same way and went opposite directions.
"""
from statistics import mean

import herd
import inventory
import nass_cache_client as nc
import on_feed
import southeast

# Bump when load() changes the shape of what it returns -- app.py passes it into
# the cached loader, which is otherwise blind to this module. The leverage.SCHEMA
# trap, recorded in CLAUDE.md.
SCHEMA = 2

# A year counts as expansion when the herd grew by more than this. Flat years
# are neither, and calling a +0.1% year an expansion would manufacture signal.
GROWTH_EPS = 0.25

# Fitted, and reported as fitted. See the module note: in-sample these give
# 17/18, 17/18 and 15/17; leave-one-out the retention cut gives 15/18.
CUTS = {"ret": (1.068, "above"), "hs": (40.8, "below"), "of": (35.9, "below")}

# The range the retention cut takes across the 18 leave-one-out refits. Drawn
# as a band because a single hairline would claim a precision that the fit does
# not have -- the same reason the southeastern panel is not shifted onto the
# plains axis.
CUT_BAND = (1.064, 1.102)

# SCORE A REGION'S PRICE AGAINST THAT REGION'S HERD. The plains barns price
# plains cattle, and the plains herd does not move with the national one: it
# turned up a year earlier in 2013, turned down two years earlier in 2017, and
# GREW 1.2% in 2024 while the national count was still falling. Four of
# eighteen years disagree outright. Scoring a plains signal against a national
# count asks it to predict a herd it is not part of.
REGION_STATES = {
    "plains": ("OKLAHOMA", "MISSOURI", "KANSAS", "MONTANA"),
    "southeast": ("GEORGIA", "SOUTH CAROLINA", "NORTH CAROLINA", "TENNESSEE"),
}

# NASS STOPPED PUBLISHING NC AND SC SEPARATELY AFTER 2024, folding them into an
# aggregate with eighteen other states. So the southeastern herd is complete
# only through 2024 and its last two years cannot be scored at all. They come
# back as unknown rather than as contractions -- "we have no count" and "the
# herd shrank" are different answers, and NASS withdrawing a series is not a
# market event. The plains four are all still published.
BEEF_COWS_STATE = {"agg_level_desc": "STATE",
                   "short_desc": "CATTLE, COWS, BEEF - INVENTORY"}


def _state_herd(states):
    """{year: head} summed over `states`, only for years ALL of them report.

    A year missing a state would read as a step down of that state's whole
    herd -- which is what makes a quietly dropped series look like a
    liquidation.
    """
    per = {}
    for st in states:
        try:
            rows = nc.fetch_cached({**BEEF_COWS_STATE, "state_name": st}).get("data", [])
        except Exception:
            return {}
        for x in rows:
            if x.get("reference_period_desc") != "FIRST OF JAN":
                continue
            try:
                v = float(str(x["Value"]).replace(",", ""))
            except (KeyError, ValueError):
                continue
            per.setdefault(int(x["year"]), {})[st] = v
    return {y: sum(v.values()) for y, v in per.items() if len(v) == len(states)}

SCORE = {"in_sample": 17, "out_of_sample": 15, "null": 13, "n": 18}


def load(conn, region=None):
    """
    [{year, ret, hs, of, cows, grew, expanded, votes}] oldest first.

    `grew` is the percentage change in beef cows over that year, and is None
    for the year still in progress -- there is no count for it yet, which is
    the point. `expanded` is None there too rather than False: not yet known
    is not the same as did not happen.
    """
    se = southeast.load(conn)
    ret = {r["year"]: r["ratio"] for r in se["series"]} if se else {}

    try:
        hs = {r["year"]: r["share"] for r in herd.heifer_share_annual(conn)}
    except Exception:
        hs = {}

    of = {}
    try:
        for r in on_feed.on_feed_share() or []:
            of.setdefault(r["year"], []).append(r["share"])
        of = {y: mean(v) for y, v in of.items()}
    except Exception:
        of = {}

    cows = {}
    if region in REGION_STATES:
        cows = _state_herd(REGION_STATES[region])
    if not cows:
        # National, and the fallback when a regional series cannot be built.
        try:
            for r in inventory.replacement_ratio() or []:
                cows[r["year"]] = r["cows"]
        except Exception:
            cows = {}
        region = "national"

    if not ret or not cows:
        return None

    out = []
    for y in sorted(ret):
        c, nxt = cows.get(y), cows.get(y + 1)
        grew = (nxt - c) / c * 100.0 if c and nxt else None
        row = {"year": y, "ret": ret.get(y), "hs": hs.get(y), "of": of.get(y),
               "cows": c, "grew": grew, "region": region,
               "expanded": None if grew is None else grew > GROWTH_EPS}
        votes = {}
        for k, (cut, d) in CUTS.items():
            v = row.get(k)
            if v is not None:
                votes[k] = (v > cut) if d == "above" else (v < cut)
        row["votes"] = votes
        out.append(row)
    return out


def split_years(rows):
    """Years where the three signals disagreed -- historically, the turns."""
    return [r["year"] for r in rows
            if len(r["votes"]) == 3 and 0 < sum(r["votes"].values()) < 3]
