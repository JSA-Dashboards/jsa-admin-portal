"""
Delivered corn cost at the feedyard -- the input a cost-of-gain build-up needs.

THE DISTINCTION THIS MODULE EXISTS FOR. Almost every published corn price is an
elevator BID: what a farmer receives for delivering grain there. A feedyard pays
something else entirely -- a delivered price carrying the elevator's margin and
the freight to the bunk. Measured on the one region where AMS publishes both:

    Texas South Plains, 30-day average
        Livestock Feeding Operations (delivered)   $6.27/bu
        Country Elevators (bid)                    $5.41/bu
        spread                                     +$0.86/bu

At an 80% corn ration and 6.5:1 conversion that 86c is about $8/cwt of gain, or
$52 a head over 650 lb of gain. Feeding an elevator bid into a cost-of-gain
calculation understates corn by that much, silently.

TWO SOURCES FOR THE BID, CHOSEN BY DEPTH.

  JSA Basis Tracker   ~50 scrapers pulling facility-level bids straight from
  (JSA.BASIS_TRACKER)  ADM, Bunge, Cargill, CHS, Scoular and the rest. Hundreds
                       of quotes per state where it is strong. Stored as BASIS
                       in cents against a futures symbol, so a flat price is
                       futures + basis.

  USDA AMS             state grain-bid reports, regional averages. Thinner, but
  (corn_bids)          it covers the Southern Plains where JSA has almost
                       nothing -- Texas is one location, Wyoming none.

Compared over ten states on 2026-09-11 the two agreed to within a dime wherever
JSA had depth (Iowa 1c apart on 654 quotes against 49), which is about as good
a cross-check as two independent collection methods can give. They diverged
only where JSA was thin. So: JSA where it is deep, AMS elsewhere, and the page
says which it used.

THE DELIVERY ADDER IS AN ASSUMPTION, and is surfaced as its own field rather
than buried in the corn price. Texas is the only empirical anchor at +86c, and
that is a grain-deficit region where corn ships a long way. The Corn Belt
defaults are lower because the crop grows next to the yard -- but they are
estimates, and a feeder who knows their own delivered basis should overwrite
them.
"""
from datetime import date, timedelta

import fcc_snowflake_db as db


def _nearby_months(today=None) -> tuple:
    """
    ('oct', 'nov') -- the month fragments a nearby-delivery quote may carry.

    Lowercase three-letter abbreviations, matched case-insensitively and
    UNANCHORED, which is what makes "Sept", "September" and "FH Sept 26" all
    fall out of the one fragment: `sep` is a substring of every spelling the
    feed uses. See `_jsa` for the measurement that settled it.

    Current month and the next, because a quote written late in a month is
    routinely for delivery early in the following one -- "By Oct 2" appears in
    September data. Two months is the window `delivered_corn` has always meant
    by "nearby"; it was simply spelled as two literals.
    """
    today = today or date.today()
    nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    return (today.strftime("%b").lower(), nxt.strftime("%b").lower())

# 110+ nearby quotes each in the 2026-09-11 comparison.
JSA_DEEP_STATES = {"IA", "SD", "NE", "MN", "ND", "MO", "KS", "CO"}

# Where AMS publishes a genuine delivered-to-feedyard price, no adder needed.
DELIVERED_STATES = {"TX"}

# Freight + elevator margin from the bid to the bunk, $/bu. Anchored on the one
# measured figure (Texas, +0.86, grain-deficit with long freight) and scaled
# down toward the Corn Belt where the corn is grown locally. ESTIMATES.
DELIVERY_ADDER = {
    "IA": 0.20, "MN": 0.20, "SD": 0.25, "ND": 0.25, "NE": 0.25, "MO": 0.25,
    "KS": 0.40, "CO": 0.50, "OK": 0.60, "WY": 0.60, "TX": 0.86,
}
DEFAULT_ADDER = 0.35

FEEDING_STATES = ["TX", "KS", "NE", "CO", "OK", "IA", "SD", "MO", "MN", "ND", "WY"]


def _jsa_bids(conn, days=10):
    """
    {state: (mean $/bu, n quotes)} nearby cash from the basis tracker.

    Fully qualified table names: the portal deliberately leaves SNOWFLAKE_SCHEMA
    unset (each bundled module defaults its own, and setting it breaks the
    others), so this cannot rely on the session schema.

    Nearby delivery only. A December bid is not what a feeder pays in September,
    and the curve between them is real money.

    THE MONTHS ARE DERIVED AND THE MATCH IS UNANCHORED. Both halves of that were
    wrong until 2026-10-07, and each was wrong on its own.

    It read `ILIKE 'Sep%' OR ILIKE 'Oct%'` -- two literal months, correct for
    two months of the year. From November it would have matched nothing and
    `delivered_corn` would have fallen through to the thinner AMS path while
    still labelling the figure "USDA AMS".

    The anchor was the larger defect and it was costing rows every day.
    DELIVERY_MONTH is free text as the elevator typed it, so a nearby October
    quote is spelled "FH Oct 2026", "By Oct 9th", "Delv by Oct 10th",
    "LH October 2026" or "10/02/2026 - 10/09/2026" at least as often as it is
    spelled "Oct ...". Measured over the ten days to 2026-10-07: the anchored
    filter returned 5,062 corn rows where an unanchored current-plus-next-month
    filter returns 7,377. A THIRD of the nearby quotes were being dropped, and
    which third depended on how each elevator writes a date -- so the per-state
    average was taken over a biased subset, with the right number of states and
    nothing to show anything was missing.

    NAMES ONLY, NOT NUMERIC FORMS. `%10/%` would add the "10/02/2026 -
    10/09/2026" spellings, worth 42 rows of the 7,377, and would also match the
    "10/" inside a date like 1/10/2027. Names alone carry 7,347 of the 7,377 --
    99.6% of the gain for none of the false-positive surface.
    """
    near = _nearby_months()
    rows = conn.cursor().execute(f"""
        SELECT m.STATE, r.FUTURES_SYMBOL, r.BASIS_CENTS
        FROM JSA.BASIS_TRACKER.SNAPSHOT_ROWS r
        JOIN JSA.BASIS_TRACKER.SNAPSHOTS s ON s.ID = r.SNAPSHOT_ID
        JOIN JSA.BASIS_TRACKER.LOCATION_META m
          ON m.PROVIDER = s.PROVIDER AND m.LOCATION = s.LOCATION
        WHERE r.GRAIN = 'Corn' AND r.BASIS_CENTS IS NOT NULL
          AND s.TIMESTAMP >= DATEADD(day, -{int(days)}, CURRENT_DATE())
          AND (r.DELIVERY_MONTH ILIKE %s OR r.DELIVERY_MONTH ILIKE %s)
    """, [f"%{near[0]}%", f"%{near[1]}%"]).fetchall()
    fut = dict(conn.cursor().execute("""
        SELECT SYMBOL, PRICE_CENTS FROM JSA.BASIS_TRACKER.FUTURES_PRICES
        WHERE DATE = (SELECT MAX(DATE) FROM JSA.BASIS_TRACKER.FUTURES_PRICES)
    """).fetchall())
    acc = {}
    for st, sym, basis in rows:
        f = fut.get(sym)
        if f is None or not st:
            continue
        acc.setdefault(str(st), []).append(f / 100.0 + float(basis) / 100.0)
    return {s: (sum(v) / len(v), len(v)) for s, v in acc.items() if v}


def _ams(conn, days=10):
    """
    {state: {"bid": x, "delivered": y or None, "n": n}} from our AMS ingest.

    Delivered is kept separate from the bid rather than averaged in -- they are
    different products and blending them would hide the very spread this module
    exists to respect.
    """
    since = ("DATEADD(day, -%d, CURRENT_DATE())" % days if db.use_snowflake()
             else "date('now','-%d day')" % days)
    rows = conn.cursor().execute(f"""
        SELECT state,
               AVG(CASE WHEN delivery_point NOT LIKE '%Feeding%'
                        THEN avg_price END),
               AVG(CASE WHEN delivery_point LIKE '%Feeding%'
                        THEN avg_price END),
               COUNT(*)
        FROM corn_bids WHERE report_date >= {since}
        GROUP BY state
    """).fetchall()
    return {str(s): {"bid": float(b) if b is not None else None,
                     "delivered": float(d) if d is not None else None,
                     "n": int(n)}
            for s, b, d, n in rows}


def delivered_corn(conn, days=10):
    """
    {state: {...}} best available DELIVERED corn cost per feeding state.

    Each entry carries how it was arrived at, because "corn is $5.80" means
    different things depending on whether it was published that way or built
    from a bid plus an assumed adder -- and the page has to be able to say so.
    """
    try:
        jsa = _jsa_bids(conn, days)
    except Exception:
        jsa = {}                      # basis tracker unreachable; AMS still works
    try:
        ams = _ams(conn, days)
    except Exception:
        ams = {}

    out = {}
    for st in FEEDING_STATES:
        a = ams.get(st, {})
        # 1. A published delivered price beats anything we could construct.
        if st in DELIVERED_STATES and a.get("delivered"):
            out[st] = {"price": a["delivered"], "bid": a.get("bid"),
                       "adder": None, "source": "AMS delivered to feedyard",
                       "n": a.get("n", 0), "assumed": False}
            continue
        # 2. Otherwise a bid -- JSA where it has depth, AMS where it does not.
        j = jsa.get(st)
        if st in JSA_DEEP_STATES and j and j[1] >= 50:
            bid, n, src = j[0], j[1], "JSA Basis Tracker"
        elif a.get("bid"):
            bid, n, src = a["bid"], a.get("n", 0), "USDA AMS"
        elif j:
            bid, n, src = j[0], j[1], "JSA Basis Tracker"
        else:
            continue
        adder = DELIVERY_ADDER.get(st, DEFAULT_ADDER)
        out[st] = {"price": bid + adder, "bid": bid, "adder": adder,
                   "source": src, "n": n, "assumed": True}
    return out
