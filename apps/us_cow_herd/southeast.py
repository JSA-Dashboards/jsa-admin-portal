"""
The same retention incentive, measured at seven southeastern barns since 2008.

WHY A SECOND PANEL EXISTS AT ALL. The twelve markets behind the main chart --
Joplin, OKC West, Oklahoma National, Woodward, Ozarks, Springfield, Ada, Tina,
Salina, Palmyra, Billings -- did not report a bred cow to USDA before 2019.
That is not a gap to be filled: in the whole legacy auction archive, 2000-2019,
bred-cow rows run GA 34,864 / KY 25,991 / NC 16,094 / SC 15,480 / TN 13,141 and
**zero Oklahoma, zero Missouri, zero Texas**. There is no file to load. 2019 is
the floor for the plains and always will be.

Bred cows WERE reported in the southeast throughout, so a long series is
available there -- at different barns, for different cattle.

THE TWO PANELS MUST NOT SHARE AN AXIS, and that is the whole reason this is a
separate view rather than eleven more bars on the existing chart. The
southeast-to-plains offset is tight over 2019-2026 (about +0.25, sd 0.013) and
looks eminently subtractable. It is not: the one pre-2019 plains-versus-
southeast comparison that can actually be run has that offset wandering from
+0.085 to +0.312, which is wider than the plains series' entire modern range of
0.247. Calibrating a shift on the recent years and extrapolating it backwards
was tested inside the legacy archive on ten matched state pairs: median
back-window error 0.092, maximum 0.264. A small calibration-window sd does not
buy out-of-window stability. So this line is drawn on its own baseline, against
its own normal, and no number here is ever added to a plains number.

THE PANEL IS BALANCED: all seven barns report in every year, 268-323 paired
sale-dates each. That is not cosmetic. The first version carried Athens GA,
which reports no bred cows in 2010 or 2011, and Orangeburg SC, which all but
stops after 2019 -- so 2011 rested on three barns and the modern half ran on
four while the caption said five. Fewer barns still draws a bar, at a level set
by whichever markets happened to report, and nothing raises.

WHAT IT IS GOOD FOR. Not a level, a shape. Over the overlap the two panels move
together, and the long view reaches years the plains series cannot. Do NOT
restate where the high and low sit in prose, here or in the caption: the page
reads them off the series at render time, because an earlier version of this
note claimed 2010-2012 was the trough of the whole record -- true of the
five-barn panel, false of this one, where 2023 and 2022 are both lower.

HOW THE SERIES IS BUILT, and why it is a file rather than a query. The 2008-2018
half comes from the USDA legacy auction archive, two zips totalling about 960MB
of CSV -- far too much to parse on a page load, and a static archive that will
never gain a row. It is precomputed into data/southeast_retention.json by
scripts/build_southeast_retention.py and read from there. The 2019-2026 half is
MARS, recomputed by the same script.

Three things in the build that look wrong and are not:

- **The legacy archive has no price-unit column**, and quotes bred cows per cwt
  at some barns and per head at others IN THE SAME YEAR, with SELLING_BASIS
  reading "Live" on every row either way. The split is cleanly bimodal --
  20,491 rows under $250, 78 between $250 and $300, 104,583 above -- so the
  threshold is a fact rather than a judgement, and moving it between 250 and 300
  changes any annual ratio by at most 0.002. Read naively, 2002-2007 computes to
  about 0.11 instead of 1.1: a factor of ten that looks like a market collapse,
  raises nothing, and charts plausibly.
- **One source per barn, with the handover at that barn's own date.** Most of
  these barns hand over cleanly -- legacy's last bred sale falls days before
  MARS's first -- but Norwood and Turnersburg are carried by BOTH archives for
  a few weeks of mid-2019. Where that happens the two are transcriptions of the
  same AMS report and agree to the dollar, so it is a double-count rather than a
  disagreement, and summing them would weight those barns twice in the median.
  MARS wins from the first date it carries a barn; the superseded legacy rows
  are dropped. Same shape as feeder_receipts' CHANNEL_LEGACY_THROUGH: one source
  per channel per week, decided per channel rather than globally. The build then
  asserts zero remaining overlap and refuses to write if any survives.
- **The legacy archive has no `Bred Heifers` class at all**, while MARS carries
  it (15-21% of bred head, priced about 16% above bred cows). The pre-2019 half
  is therefore a slightly narrower definition than the post-2019 half. It is
  left that way rather than dropping Bred Heifers from the modern side, because
  the alternative is discarding real data to match an archive's omission -- but
  it is a reason to read the join as approximate in level even though it is
  exact in dates.

2007 and earlier are deliberately absent: coverage thins to two months at these
barns, and `MIN_MONTHS` drops it.
"""
import json
from pathlib import Path
from statistics import median

DATA = Path(__file__).parent / "data" / "southeast_retention.json"

# A year needs this many distinct months to be drawn, the same rule
# herd.MIN_ANNUAL_MONTHS applies to the plains panel.
MIN_MONTHS = 6

# Bump when the JSON's shape changes -- app.py passes it into the cached loader
# so st.cache_data notices, the trap recorded for leverage.SCHEMA.
SCHEMA = 1

# Matches herd.BASELINE_YEARS so "normal" means the same span on both panels.
# The VALUE is computed from this panel's own years and is nothing like the
# plains figure -- see the module note on why the two never share a baseline.
BASELINE_YEARS = (2021, 2025)


TABLE = "JSA.CME_FEEDER_CATTLE.SOUTHEAST_RETENTION"


def _from_file():
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return None


def _from_snowflake(conn):
    """Newest row per year. Returns None on any trouble -- never raises.

    The committed JSON is a seed, not a live series: it only moves when someone
    runs scripts/build_southeast_retention.py against 960MB of archive on a
    machine that has it. deploy/refresh_southeast.py keeps this table current
    from the droplet instead, which is the only place that can -- marsapi
    rejects Streamlit Community Cloud's IPs, so the page cannot fetch its own
    MARS half.
    """
    try:
        cur = conn.cursor().execute(
            f"SELECT YEAR, RATIO, N, MONTHS, BARNS, SOURCE, SPAN, PANEL FROM {TABLE} "
            f"QUALIFY ROW_NUMBER() OVER (PARTITION BY YEAR ORDER BY RECORDED_AT DESC) = 1 "
            f"ORDER BY YEAR")
        rows = cur.fetchall()
    except Exception:
        return None
    if not rows:
        return None
    series, panel = [], None
    for y, ratio, n, months, barns, source, span, pan in rows:
        rec = {"year": int(y), "ratio": float(ratio), "n": n,
               "months": months, "barns": barns, "source": source}
        if span:
            try:
                rec["span"] = json.loads(span)
            except Exception:
                pass
        series.append(rec)
        panel = pan or panel
    # PANEL is a JSON list. It must not be comma-split: every barn name
    # contains a comma, so a split turns seven barns into fourteen and the
    # caption says so. A row written before that was fixed parses as nothing
    # here, and load() then falls back to the file's panel.
    try:
        names = json.loads(panel) if panel else []
        if not isinstance(names, list):
            names = []
    except Exception:
        names = []
    return {"panel": names, "series": series}


def load(conn=None):
    """{'panel': [barn names], 'series': [{year, ratio, n, months, barns, source}]}

    Snowflake first, the committed file as a fallback. Returns None rather than
    raising if neither answers, so a packaging slip or an outage costs the
    toggle and not the page.

    THE FALLBACK IS NOT DECORATION. If the droplet job has never run, or the
    table is empty, or Snowflake is unreachable, the page still draws the
    series as of the last full rebuild. It stops advancing; it does not vanish.
    """
    d = _from_snowflake(conn) if conn is not None else None
    if not d or not d.get("series"):
        d = _from_file()
    if not d:
        return None
    rows = [r for r in d.get("series", []) if (r.get("months") or 0) >= MIN_MONTHS]
    if not rows:
        return None
    if not d.get("panel"):
        f = _from_file() or {}
        d["panel"] = f.get("panel", [])
    d["series"] = sorted(rows, key=lambda r: r["year"])
    return d


def baseline(series):
    """This panel's own normal, over BASELINE_YEARS."""
    v = [r["ratio"] for r in series
         if BASELINE_YEARS[0] <= r["year"] <= BASELINE_YEARS[1]]
    return median(v) if v else None


def span(series):
    """('Jan','Oct') for a trailing part year, else None -- as herd.annual_span."""
    if not series:
        return None
    last = series[-1]
    if last.get("months", 0) >= 12:
        return None
    return last.get("span")
