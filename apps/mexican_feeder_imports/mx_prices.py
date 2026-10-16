"""
What a Mexican feeder calf is worth INSIDE Mexico, against the US border quote.

The page has always been able to price a calf the moment it reaches the US
side -- AMS 3486 gives $/cwt F.O.B. at Douglas and Santa Teresa, and the
Border Prices section differences that against the CME index. This is the
other half: the same animal before it crosses.

    JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES   Tamaulipas auction, MXN/kg
    JSA.CME_FEEDER_CATTLE.FX_USDMXN           ECB reference rate, per sale day
    JSA.CME_FEEDER_CATTLE.BORDER_PRICES       AMS 3486, $/cwt F.O.B.

`scripts/mx_auction.py` writes the first two from the droplet. This module only
reads.

**IT DOES NOT IMPORT `requests`, AND THAT IS DELIBERATE.** CLAUDE.md records the
rule for this page: `border.py` has no HTTP path so the Streamlit process cannot
acquire one, and the ingest lives elsewhere. The conversion below is therefore a
second copy of `mx_auction.usd_per_cwt` rather than an import of it --
`mx_auction` needs `requests` for the scrape. `tests/test_mx_prices.py` runs the
two against each other over a grid so the copy cannot drift; that test may
import the scraper because a test is not the page.

THE COMPARISON IS HONEST ONLY IF THE READER IS TOLD WHAT IT IS NOT, and the
panel says all three out loud:

* **TAMAULIPAS IS NOT WHERE THESE CATTLE COME FROM.** Douglas and Santa Teresa
  take Sonora and Chihuahua cattle. Neither state has an auction on
  mexicoganadero.com, and the only figures for them anywhere are association
  spokesmen quoted in the Mexican press. Tamaulipas is a northern border state
  publishing real feeder bands by weight, which makes it the closest honest
  comparator and not the right one. A reader who takes the gap below as "the
  export premium at Douglas" has been misled by a number that is correctly
  computed.
* **THE TWO SIDES ARE RARELY QUOTED THE SAME DAY.** Tamaulipas sells roughly
  weekly; AMS quotes only on days enough head sell to establish a trend. So
  `compare()` pairs each sale with the NEAREST priced border date and returns
  `gap_days` for the panel to print. Pretending to a same-day spread would be
  the letter-vs-dashboard failure recorded in CLAUDE.md, arriving by a new
  route.
* **IT IS A LEVEL, NOT A MARGIN.** Nothing here nets out freight, the test, the
  crossing fee, shrink or the buyer's margin. A calf worth 60% of the Douglas
  price is not 40% profit.

WEIGHT IS MATCHED ON THE MIDPOINT, which is the one judgement call in here. The
two ladders do not align -- Tamaulipas bands in kg (151-180, 181-200, ...) and
AMS in lb (400-500, 500-600, ...) -- so a band is assigned to the US bracket
containing its own midpoint in pounds. Two Mexican bands can therefore land in
one US bracket, and they are kept as separate rows rather than averaged: with no
head counts an average would weight a thin band equally with a heavy one and
report a single figure that no lot ever traded at.

ONLY THE `CN` LADDER IS COMPARED. The site also prints wide `CNH` lots
(100-180, 181-260, 251-330 kg) which overlap the narrow ones and run far
cheaper -- BECERRO CNH 251-330 at 58.33 MXN/kg against CN 251-280 at 81.89 on
the 2026-09-30 sale. Mixing the two ladders would double-count a weight and
drag every comparison down by a grade difference the US quote does not share.
`CNH_PREFIXES` names them; `bands()` returns them flagged so the data table can
still show them, and `compare()` leaves them out.

SEX IS MATCHED TOO. BECERRO is a bull calf and pairs with AMS `Steers`;
BECERRA is a heifer calf and pairs with `Spayed Heifers`. Pairing a Mexican
heifer against a US steer quote would read as a discount that is really a sex
difference.
"""

from __future__ import annotations

from datetime import date

# Matches scripts/mx_auction.LB_PER_KG exactly; a test pins that it still does.
LB_PER_KG = 2.2046226218

MX_TABLE = "JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES"
FX_TABLE = "JSA.CME_FEEDER_CATTLE.FX_USDMXN"
US_TABLE = "border_prices"

PER_KG = "MXN/kg"

#: The auction this page compares against. Yucatan and Durango come free in the
#: same scrape and are kept in the table for context, but neither bands by
#: weight, so neither can be matched to an AMS bracket at all.
AUCTION = "TAMAULIPAS"

#: Feeder calves. Everything else the sale prints -- VACA (cows), TORO (bulls),
#: TORETE, NOVILLONAS, VAQUILLAS -- is a different animal on a different market
#: and has no border quote to sit beside.
FEEDER_PREFIXES = ("BECERRO", "BECERRA")

#: The wide overlapping ladder, excluded from the comparison. See the docstring.
CNH_PREFIXES = ("BECERRO CNH", "BECERRA CNH")

#: Mexican sex -> the AMS class that quotes the same animal.
US_CLASS_BY_SEX = {"M": "Steers", "F": "Spayed Heifers"}

#: AMS publishes 1-2 and 2-3; the page headlines 1-2, so the comparison does.
US_GRADE = "1-2"

#: ONE CROSSING, AND THE PAGE PRINTS WHICH. Douglas and Santa Teresa both quote
#: on the same day and THEY DISAGREE -- 700-800 lb #1-2 steers on 2026-09-30
#: were $310 at Douglas and $315 at Santa Teresa, and 4 of 2026's quoted days
#: carry both. Taking every row built a slide with two anchors at the same
#: weight, so which one the interpolation used fell out of sort order: an
#: arbitrary choice between two real prices, with the tile labelled "Douglas"
#: whichever it picked. Preferred first, then whatever quoted, and the crossing
#: actually used is returned so the label cannot lie.
US_CROSSING_PREFERENCE = ("Douglas", "Santa Teresa")

#: How far apart a sale and a border quote may be and still be shown as a pair.
#: Beyond this the panel prints the sale with no comparison rather than a
#: spread across a fortnight of market movement.
MAX_GAP_DAYS = 21

#: Bumped whenever load() changes the SHAPE of what it returns. It is passed
#: into the cached fetch purely as part of the key -- st.cache_data keys on the
#: decorated function's own code and never on the modules it calls, the trap
#: recorded in CLAUDE.md for leverage.SCHEMA and am_cutout.SCHEMA. Without it a
#: new key renders "—" and nothing raises.
#:
#: 5 (2026-10-07): one crossing only, and compare() returns which. Every
#: us_price on a two-crossing day can change.
#: 4 (2026-10-07): load() carries ratio_series + the decomposition, so the
#: panel can say WHICH driver moved the ratio. A cached dict from before
#: this has neither key and the section renders empty.
#: 3 (2026-10-07): the AMS price is INTERPOLATED off the quote slide at the
#: band's own weight instead of taken from whichever bracket the midpoint
#: fell in. Row keys changed (us_low_lb/us_high_lb -> us_at_lb) and every
#: pct moved, so a cached dict from before this would both miss a key and
#: report superseded figures.
#: 2 (2026-10-07): bands() now sorts steers and the CN ladder first. The SHAPE
#: did not change, only the ORDER -- which is precisely a change the cache
#: cannot see, so the deployed page would have gone on serving the old
#: heifers-first ordering from a cached dict with nothing raising. Bump this
#: for an ordering or content change, not only for a new key.
SCHEMA = 5


def usd_per_cwt(mxn_per_kg, mxn_per_usd):
    """MXN/kg -> USD/cwt, the unit AMS 3486 quotes the border in.

    Kilos to pounds, pesos to dollars, per-pound to per-hundredweight. None
    propagates rather than defaulting, so a missing rate leaves the cell empty
    instead of silently pricing a calf at an implied 1.0 peso.

    Byte-for-byte the same arithmetic as scripts/mx_auction.usd_per_cwt; see
    this module's docstring for why it is copied rather than imported.
    """
    if mxn_per_kg is None or not mxn_per_usd:
        return None
    return float(mxn_per_kg) / LB_PER_KG / float(mxn_per_usd) * 100.0


def kg_to_lb(kg):
    return None if kg is None else float(kg) * LB_PER_KG


def band_midpoint_lb(low_kg, high_kg):
    """Midpoint of a Mexican band, in pounds, or None if it is open-ended.

    An open band ("menor a 150kg") has no midpoint that means anything, and
    inventing one by treating the missing end as zero would place a 150 kg calf
    at 75 kg and match it to a bracket four rungs down.
    """
    if low_kg is None or high_kg is None:
        return None
    return kg_to_lb((float(low_kg) + float(high_kg)) / 2.0)


def us_anchors(us_bands):
    """[(weight_lb, price)] — one point per AMS bracket, at its own midpoint.

    AMS quotes a bracket, not a weight, so the price for "400-500 lb at $415"
    is treated as the price of a 450 lb calf. That is the only reading that
    lets the quotes be used as a slide.
    """
    by_w = {}
    for low, high, price in us_bands or []:
        if low is None or high is None or price is None:
            continue
        w = (float(low) + float(high)) / 2.0
        by_w.setdefault(w, []).append(float(price))
    # Two prices at one weight should be impossible once a single crossing is
    # selected, but a duplicate anchor makes the interpolation depend on sort
    # order rather than on anything meaningful, so it is collapsed here too
    # rather than trusted not to happen.
    return sorted((w, sum(v) / len(v)) for w, v in by_w.items())


def us_coverage(us_bands):
    """(lightest_lb, heaviest_lb) AMS quoted at all, or (None, None)."""
    lows = [float(l) for l, h, _p in us_bands or [] if l is not None]
    highs = [float(h) for l, h, _p in us_bands or [] if h is not None]
    if not lows or not highs:
        return None, None
    return min(lows), max(highs)


def interpolate_us(mid_lb, us_bands):
    """The AMS price AT `mid_lb`, read off the quote slide, or None.

    REPLACES BRACKET MATCHING, and the reason is that bracket matching had no
    defensible rule. A 201-230 kg lot is 443-507 lb and straddles two AMS
    brackets; calling it a four-weight gives $415 and 55%, calling it a
    five-weight gives $385 and 60%. Same calf, same 229.68, and the answer came
    down to which edge of the band you looked at.

    Feeder prices slide with weight, so the quotes are points on a curve rather
    than labels on bins: $415 at 450 lb, $385 at 550, $345 at 650, $315 at 750.
    Reading the curve at the band's own weight gives every lot a price matched
    to what it actually weighs, and removes the choice entirely.

    Three rules, each of which matters:

    * **Linear between adjacent anchors.** Four points over 450-750 lb is not
      enough to fit a curve to, and a spline through four points would invent
      shape USDA never published.
    * **FLAT inside the end brackets, never extrapolated past them.** A 420 lb
      calf sits below the 450 anchor but inside the 400-500 bracket, and AMS
      genuinely quotes it at $415 -- so the flat segment is USDA's own number,
      not an assumption. Past the covered range it returns None: a 828 lb lot
      is outside anything AMS quoted, and running the slide on would price it
      by projecting a trend off the end of the data.
    * **None if fewer than two anchors.** One bracket is a point, not a slide.
      It still prices anything inside that one bracket, flat, which is right.
    """
    if mid_lb is None:
        return None
    pts = us_anchors(us_bands)
    if not pts:
        return None
    lo_cov, hi_cov = us_coverage(us_bands)
    if lo_cov is None or not (lo_cov <= mid_lb <= hi_cov):
        return None

    if mid_lb <= pts[0][0]:
        return pts[0][1]
    if mid_lb >= pts[-1][0]:
        return pts[-1][1]
    for (w0, p0), (w1, p1) in zip(pts, pts[1:]):
        if w0 <= mid_lb <= w1:
            if w1 == w0:
                return p0
            return p0 + (mid_lb - w0) / (w1 - w0) * (p1 - p0)
    return None


def is_feeder(clasificacion: str) -> bool:
    c = (clasificacion or "").upper()
    return any(c.startswith(p) for p in FEEDER_PREFIXES)


def is_cnh(clasificacion: str) -> bool:
    c = (clasificacion or "").upper()
    return any(c.startswith(p) for p in CNH_PREFIXES)


# ── reads ───────────────────────────────────────────────────────────────────

def sale_dates(conn, auction=AUCTION):
    """Every sale date held, newest first. The site keeps two sales and no
    archive, so this list only ever grows forwards from the first run."""
    cur = conn.cursor()
    rows = cur.execute(
        f"SELECT DISTINCT SALE_DATE FROM {MX_TABLE} "
        f"WHERE AUCTION = %s ORDER BY SALE_DATE DESC", (auction,)
    ).fetchall()
    return [r[0] for r in rows]


def bands(conn, sale_date, auction=AUCTION):
    """Feeder bands for one sale.

    [{clasificacion, sex, low_kg, high_kg, low, high, avg, unit, cnh}] with
    `low`/`high` in POUNDS. Rows priced per head rather than per kilo are
    returned with avg None: the scraper records the unit it saw, and a per-head
    price divided by a weight the sale did not state is a number nobody quoted.
    """
    cur = conn.cursor()
    rows = cur.execute(
        f"SELECT CLASIFICACION, SEX, WEIGHT_LOW_KG, WEIGHT_HIGH_KG, "
        f"       PRICE_MIN, PRICE_MAX, PRICE_AVG, UNIT "
        f"FROM {MX_TABLE} WHERE AUCTION = %s AND SALE_DATE = %s ",
        (auction, sale_date)
    ).fetchall()
    out = []
    for cls, sex, lo_kg, hi_kg, lo, hi, avg, unit in rows:
        if not is_feeder(cls):
            continue
        out.append({
            "clasificacion": cls,
            "sex": sex,
            "low_kg": float(lo_kg) if lo_kg is not None else None,
            "high_kg": float(hi_kg) if hi_kg is not None else None,
            "low_lb": kg_to_lb(lo_kg),
            "high_lb": kg_to_lb(hi_kg),
            "mid_lb": band_midpoint_lb(lo_kg, hi_kg),
            "price_min": float(lo) if lo is not None else None,
            "price_max": float(hi) if hi is not None else None,
            "price_avg": float(avg) if avg is not None and unit == PER_KG else None,
            "unit": unit,
            "cnh": is_cnh(cls),
        })

    # THE ROWS THAT CARRY A COMPARISON COME FIRST, and that is not cosmetic.
    # Sorted by the SQL's `SEX, WEIGHT_LOW_KG`, F sorts before M -- so the first
    # ten rows were heifers, every one of them showing a dash in the AMS
    # columns because AMS stopped quoting Spayed Heifers in May 2025. The whole
    # point of the table sat below the fold under a block of em-dashes, which
    # reads as a broken join rather than as the US feed's state. Spotted on the
    # deployed page, not in a test, because no test looks at row order.
    #
    # Steers before heifers, the clean CN ladder before the wide CNH lots, then
    # ascending weight -- so the table opens on the ladder a reader can compare
    # straight down and the uncomparable rows collect at the bottom.
    out.sort(key=lambda r: (0 if r["sex"] == "M" else 1,
                            1 if r["cnh"] else 0,
                            r["low_kg"] if r["low_kg"] is not None else -1.0))
    return out


def fx_on(conn, when):
    """(rate_date, mxn_per_usd) for `when`, falling back to the newest rate
    BEFORE it.

    Strictly before, never after. A sale is priced at the rate that stood when
    it traded; reaching forward to a later rate would restate a past sale every
    time the peso moved, which is the decay failure `FORECAST_MAX_ANALOGUES`
    exists to stop on the cash forecast tab.
    """
    cur = conn.cursor()
    r = cur.execute(
        f"SELECT RATE_DATE, MXN_PER_USD FROM {FX_TABLE} "
        f"WHERE RATE_DATE <= %s ORDER BY RATE_DATE DESC LIMIT 1", (when,)
    ).fetchone()
    if not r:
        return None, None
    return r[0], float(r[1])


def us_last_quoted(conn, us_class, grade=US_GRADE):
    """The newest date AMS priced `us_class` at all, ignoring any gap limit.

    EXISTS SO A BLANK COLUMN CAN EXPLAIN ITSELF. AMS has not quoted Spayed
    Heifers since 2025-05-12 -- 2026 carries 23 priced days and every one of
    them is Steers -- so every Mexican heifer band correctly matches nothing.
    Without this the panel would show a column of dashes that looks exactly
    like a broken join, and the honest answer ("the US side stopped quoting
    this class eighteen months ago") is one query away.
    """
    cur = conn.cursor()
    r = cur.execute(
        f"SELECT MAX(report_date) FROM {US_TABLE} "
        f"WHERE avg_price IS NOT NULL AND class_desc = %s AND muscle_grade = %s",
        (us_class, grade)
    ).fetchone()
    return r[0] if r else None


def us_bands_near(conn, when, us_class, grade=US_GRADE, max_gap=MAX_GAP_DAYS):
    """(quote_date, [(low_lb, high_lb, avg)], gap_days, crossing) near `when`.

    Nearest in EITHER direction, because a sale can fall between two quoted
    border days and the closer one is the better comparator whichever side it
    sits. Returns (None, [], None, None) when nothing is within `max_gap`.

    ONE CROSSING ONLY -- see US_CROSSING_PREFERENCE. Mixing Douglas and Santa
    Teresa put two different prices at the same weight on one slide.
    """
    cur = conn.cursor()
    r = cur.execute(
        f"SELECT report_date, ABS(DATEDIFF('day', report_date, %s)) g "
        f"FROM {US_TABLE} WHERE avg_price IS NOT NULL AND class_desc = %s "
        f"  AND muscle_grade = %s "
        f"ORDER BY g ASC, report_date DESC LIMIT 1", (when, us_class, grade)
    ).fetchone()
    if not r or r[1] is None or int(r[1]) > max_gap:
        return None, [], None, None
    on, gap = r[0], int(r[1])

    rows = cur.execute(
        f"SELECT weight_low, weight_high, avg_price, crossing_point "
        f"FROM {US_TABLE} "
        f"WHERE report_date = %s AND class_desc = %s AND muscle_grade = %s "
        f"  AND avg_price IS NOT NULL ORDER BY weight_low", (on, us_class, grade)
    ).fetchall()
    if not rows:
        return on, [], gap, None

    by_cross = {}
    for lo, hi, price, cross in rows:
        by_cross.setdefault(cross, []).append((lo, hi, float(price)))

    pick = next((c for c in US_CROSSING_PREFERENCE if c in by_cross), None)
    if pick is None:
        # Whatever quoted the most brackets that day; ties broken by name so
        # the choice is reproducible rather than dict-order dependent.
        pick = max(sorted(by_cross), key=lambda c: len(by_cross[c]))
    return on, by_cross[pick], gap, pick


# ── the comparison ──────────────────────────────────────────────────────────

def compare(conn, sale_date=None, auction=AUCTION):
    """Everything the panel draws, for one sale. None if no sale is held.

    Every row that carries a US counterpart gets `usd`, `us_price`, `pct` and
    `diff`; a row with no counterpart keeps `usd` and leaves the rest None, so
    the table still prices it in dollars and simply shows no spread.
    """
    dates = sale_dates(conn, auction)
    if not dates:
        return None
    on = sale_date or dates[0]

    rate_date, rate = fx_on(conn, on)
    rows = bands(conn, on, auction)

    us_cache = {}
    for sex, us_class in US_CLASS_BY_SEX.items():
        us_cache[sex] = us_bands_near(conn, on, us_class)

    out = []
    for b in rows:
        b = dict(b)
        b["usd"] = usd_per_cwt(b["price_avg"], rate)
        us_date, us_list, gap, cross = us_cache.get(
            b["sex"], (None, [], None, None))
        b["us_class"] = US_CLASS_BY_SEX.get(b["sex"])
        b["us_date"] = us_date
        b["gap_days"] = gap
        b["us_crossing"] = cross
        price = None if b["cnh"] else interpolate_us(b["mid_lb"], us_list)
        if price is not None and b["usd"] is not None:
            b["us_price"] = price
            b["us_at_lb"] = b["mid_lb"]
            b["pct"] = b["usd"] / price * 100.0 if price else None
            b["diff"] = b["usd"] - price
        else:
            b["us_price"] = b["us_at_lb"] = None
            b["pct"] = b["diff"] = None
        out.append(b)

    return {
        "auction": auction,
        "sale_date": on,
        "sale_dates": dates,
        "fx_date": rate_date,
        "fx": rate,
        "rows": out,
        "us_dates": {s: us_cache[s][0] for s in us_cache},
        # The slide itself, so the panel can show what it read the price off.
        "us_slide": {s: us_anchors(us_cache[s][1]) for s in us_cache},
        "gaps": {s: us_cache[s][2] for s in us_cache},
        # Which border crossing each sex was priced against, so the tile can
        # name it rather than hard-coding "Douglas" on a day only Santa Teresa
        # quoted.
        "us_crossings": {s: us_cache[s][3] for s in us_cache},
        # Only populated for a sex whose quote is missing, so the panel can say
        # WHY rather than printing a column of dashes. See us_last_quoted().
        "us_last": {s: us_last_quoted(conn, US_CLASS_BY_SEX[s])
                    for s in US_CLASS_BY_SEX if us_cache[s][0] is None},
    }


def headline(cmp_, sex="M"):
    """The single best-matched pair, for the tiles, or None.

    Picks the HEAVIEST matched band rather than the first, because the page's
    own border headline is 700-800 lb and the heaviest Mexican band that
    matches anything is the one that lands there. A reader comparing the two
    panels should see the same bracket in both.
    """
    best = None
    for r in cmp_["rows"] if cmp_ else []:
        if r["sex"] != sex or r["pct"] is None or r["mid_lb"] is None:
            continue
        if best is None or r["mid_lb"] > best["mid_lb"]:
            best = r
    return best


def ratio_series(conn, sex="M", auction=AUCTION):
    """[{date, mxn_kg, fx, usd, us, pct, band}] oldest first, one row per sale.

    Carries the PESO price and the exchange rate alongside the ratio, because
    without them the ratio cannot be read -- see decompose().
    """
    out = []
    for d in reversed(sale_dates(conn, auction)):
        c = compare(conn, d, auction)
        h = headline(c, sex)
        if not h or not c.get("fx"):
            continue
        out.append({"date": d, "mxn_kg": h["price_avg"], "fx": c["fx"],
                    "usd": h["usd"], "us": h["us_price"], "pct": h["pct"],
                    "band": h["clasificacion"], "at_lb": h["us_at_lb"]})
    return out


def decompose(a, b):
    """Split the change in the ratio between two sales into its three drivers.

    THE RATIO MOVES FOR THREE REASONS AND THEY DO NOT MEAN THE SAME THING.

        ratio = (MXN_per_kg / LB_PER_KG / fx * 100) / US_per_cwt

    so ln(ratio) = ln(MXN) - ln(fx) - ln(US) + const, and the change splits
    EXACTLY into three additive parts. Returns percentage changes in logs plus
    the residual, which is zero by construction and is returned anyway so the
    page can assert it rather than trust it.

    **THIS EXISTS BECAUSE THE RAW RATIO IS ACTIVELY MISLEADING.** Over the
    first three sales on file the ratio fell 3.55 points, 62.25% -> 58.70%,
    which reads as Mexican cattle cheapening against the border. They did not:
    in PESOS the Tamaulipas price rose 0.24%, 75.20 -> 75.38 MXN/kg. The whole
    move was the peso going 17.14 -> 18.13 to the dollar. A page that printed
    the ratio alone would have had a reader concluding something about cattle
    from a currency chart -- which is exactly what happened to me before this
    function existed.

    The two readings are both legitimate and answer different questions:

    * **"Are Mexican cattle cheapening?"** -- look at `mxn` alone. Currency is
      not part of that question.
    * **"Is exporting more attractive?"** -- look at the whole ratio. A weaker
      peso genuinely does make a US sale worth more at home, so FX belongs in
      that one.

    A page that does not say which question it is answering will be read as
    answering the first while computing the second.
    """
    import math
    for v in (a.get("pct"), b.get("pct"), a.get("mxn_kg"), b.get("mxn_kg"),
              a.get("fx"), b.get("fx"), a.get("us"), b.get("us")):
        if not v or v <= 0:
            return None
    d_ratio = math.log(b["pct"] / a["pct"])
    d_mxn = math.log(b["mxn_kg"] / a["mxn_kg"])
    d_fx = -math.log(b["fx"] / a["fx"])
    d_us = -math.log(b["us"] / a["us"])
    return {
        "pts": b["pct"] - a["pct"],
        "ratio": d_ratio * 100.0,
        "mxn": d_mxn * 100.0,
        "fx": d_fx * 100.0,
        "us": d_us * 100.0,
        "residual": (d_ratio - (d_mxn + d_fx + d_us)) * 100.0,
    }


def dominant(parts):
    """Which driver moved the ratio most, as (key, label, signed %).

    Named rather than ranked silently, because "the peso" and "Mexican cattle"
    lead to opposite decisions and the page must say which one it saw.
    """
    if not parts:
        return None
    LABELS = {"mxn": "the Mexican market, in pesos",
              "fx": "the peso against the dollar",
              "us": "the US border price"}
    k = max(LABELS, key=lambda k: abs(parts.get(k) or 0.0))
    return k, LABELS[k], parts[k]


def spread_history(conn, sex="M", auction=AUCTION):
    """[(sale_date, pct, usd, us_price)] oldest first -- kept for the chart.

    It accrues from the first run and cannot be backfilled:
    mexicoganadero.com keeps the current sale and one previous, with no archive
    and no date parameter. Same shape as JSA.BOXED_BEEF.CUTOUT_AM.
    """
    return [(r["date"], r["pct"], r["usd"], r["us"])
            for r in ratio_series(conn, sex, auction)]
