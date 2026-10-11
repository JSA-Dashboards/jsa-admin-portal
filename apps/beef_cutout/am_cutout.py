"""
The MORNING boxed beef cutout -- LM_XB402 -- and the history we have to keep
ourselves.

WHAT THIS IS. USDA publishes the daily boxed beef cutout TWICE. The portal has
always read the afternoon one, LM_XB403 (datamart slug 2453), which is the
close. The morning report is a different report: LM_XB402, "National Daily
Boxed Beef Cutout And Boxed Beef Cuts - Negotiated Sales - Morning", priced
"as of 9:30am" and published around 10:55 CT. It is the first read of the day
and it is routinely a long way from where the day finishes -- on 2026-10-06
the AM said Choice 382.46, +4.20, and the PM closed 378.93, +0.67 against the
prior close. A $3.53 fade that nothing on this portal could show.

THERE IS NO FEED FOR IT, AND NO HISTORY ANYWHERE. This was established by
probe on 2026-10-06 and is the whole reason this module is shaped the way it
is. Do not go looking again:

  * The datamart catalog (`GET /services/v1.1/reports`, 151 reports) does not
    list slug 2452 at all. 2453 is the only daily boxed beef cutout in it.
  * Slug 2452 answers HTTP **200** with the body `"No Results Found. "` to
    every query shape -- bare, `lastReports`, `allSections`, and an explicit
    `report_date` range. Asking for a named section instead returns "Unable to
    find this subreport", so the slug is known to the service and carries no
    rows. A 200 that means "nothing here" is the same trap `direct_reports.py`
    documents for MARS.
  * MARS v1.2 refuses it outright: "Slug Id is invalid / Report has no data".
    MARS has no boxed beef reports of any kind -- five titles match "beef" and
    they are trimmings, variety meats and retail features.
  * The only live copy is the PDF at AM_PDF below, **overwritten in place every
    morning**. A `?date=` parameter is accepted and ignored; it returns today's
    bytes whatever you ask for.

So the look-back cannot be back-filled. It accrues from the first day we
record one, which is what `bank()` is for.

IT COSTS NO NEW SECRET AND NO NEW HOST. `www.ams.usda.gov/mnreports/` is
already fetched by the deployed app -- `letter/sources.AMS_3208_PDF` parses a
report from that same directory with the same `pypdf` -- so unlike
`marsapi.ams.usda.gov`, which rejects Streamlit Community Cloud's IPs, this
path is known to work from the deployed portal.

PARENTHESES ARE NEGATIVE. USDA prints a down day as `(2.23)`, not `-2.23`;
verified against the PM report on 2026-10-06, where Select fell 2.23. The same
trap `letter/sterling.py` documents. A regex for a leading minus reads that as
a GAIN of 2.23, and a cutout that fell two dollars renders as one that rose
two.

THE SPREAD IS A FREE AUDIT. USDA prints Choice, Select and the Choice/Select
spread independently, and the first two must difference to the third. A
shifted parse -- the failure mode that does not raise and does not look wrong
-- breaks that identity. `parse_am` refuses to return a row that fails it
rather than handing back plausible nonsense, and `tests/test_am_cutout.py`
pins it.

IT VERIFIES THE REPORT IT PARSED. The guard on LM_XB402 and "Morning" is not
belt-and-braces: these two PDFs sit one slug apart in the same directory with
a near-identical layout, so if USDA ever repoints that path the parser would
happily bank the AFTERNOON close as a morning reading, and the AM-vs-PM fade
-- the entire point of this module -- would silently become a row of zeros.
"""
from __future__ import annotations

import importlib.util
import io
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
APPS = REPO / "apps"

AM_PDF    = "https://www.ams.usda.gov/mnreports/ams_2452.pdf"
AM_REPORT = "LM_XB402"
PM_REPORT = "LM_XB403"   # what the rest of the page reads, for contrast

# The table. Append-only and newest-wins per REPORT_DATE, exactly like
# JSA.LETTER.DRAFTS: USDA does issue corrections, and an INSERT needs no
# UPDATE grant and can never bury the figure that was actually published.
TABLE = "JSA.BOXED_BEEF.CUTOUT_AM"

# Its own schema rather than a corner of JSA.LETTER. letter/draft_store.py
# creates JSA.LETTER from the deployed app, so CREATE SCHEMA is a thing the
# portal's identity has been able to do; if it cannot here, `ensure_table()`
# returns the reason and the page prints it rather than quietly never
# recording anything.
DDL = [
    "CREATE SCHEMA IF NOT EXISTS JSA.BOXED_BEEF",
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
            REPORT_DATE     DATE          NOT NULL,
            CHOICE_600_900  NUMBER(9,2),
            SELECT_600_900  NUMBER(9,2),
            CHANGE_CHOICE   NUMBER(9,2),
            CHANGE_SELECT   NUMBER(9,2),
            SPREAD          NUMBER(9,2),
            LOAD_COUNT      NUMBER(9,0),
            AVG5_CHOICE     NUMBER(9,2),
            AVG5_SELECT     NUMBER(9,2),
            RECORDED_AT     TIMESTAMP_NTZ NOT NULL,
            RECORDED_BY     VARCHAR(128)
        )""",
]

FIELDS = ("choice", "select", "change_choice", "change_select",
          "spread", "loads", "avg5_choice", "avg5_select")

# PASSED INTO THE PAGE'S CACHED FETCH PURELY AS PART OF THE CACHE KEY.
# `st.cache_data` keys on the decorated function's own code and arguments and
# NEVER on the modules it calls -- so adding a field to `parse_am` leaves the
# page serving a dict from before that field existed, and the tile that reads
# it renders "--" with nothing raising. The identical trap is recorded against
# `leverage.SCHEMA` in CLAUDE.md. BUMP THIS whenever `parse_am` changes the
# shape of what it returns.
SCHEMA = 1

_COLS = ("CHOICE_600_900", "SELECT_600_900", "CHANGE_CHOICE", "CHANGE_SELECT",
         "SPREAD", "LOAD_COUNT", "AVG5_CHOICE", "AVG5_SELECT")

# The spread identity, in dollars. USDA rounds each of the three to the
# nearest cent independently, so the difference can miss by a cent without
# anything being wrong; two cents is a parse that has shifted.
SPREAD_TOLERANCE = 0.02


# -- Parsing ------------------------------------------------------------------

_TOKEN = re.compile(r"\(?-?\$?\d[\d,]*(?:\.\d+)?\)?")

# How far past a label to look for its values. Bounded on purpose: an
# unbounded scan over a report with a missing figure silently borrows the next
# section's number, which is the "padding still renders and shifts every
# column" failure letter/sterling.py was bitten by.
_SCAN_CHARS = 120


def _num(tok: str):
    """A USDA numeric token. Parentheses are a MINUS SIGN -- see the docstring."""
    t = tok.strip().replace(",", "").replace("$", "")
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    if not t or t == "-":
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _after(text: str, label: str, n: int):
    """
    The n numeric tokens following `label`, or None if fewer than n are within
    `_SCAN_CHARS` of it.

    None rather than a short list, deliberately: a caller that got two values
    where it asked for two cannot tell a padded list from a complete one, and
    a shifted column renders perfectly.
    """
    i = text.find(label)
    if i < 0:
        return None
    window = text[i + len(label): i + len(label) + _SCAN_CHARS]
    vals = [_num(m.group(0)) for m in _TOKEN.finditer(window)]
    vals = [v for v in vals if v is not None]
    return vals[:n] if len(vals) >= n else None


_DATE_LINE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def _report_date(text: str):
    """The report's own date, off the masthead ('October 06, 2026')."""
    m = _DATE_LINE.search(text[:400])
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").date()
    except ValueError:
        return None


def parse_am(text: str) -> dict:
    """
    The morning cutout, from the extracted text of ams_2452.pdf.

    Returns {"error": ...} rather than raising, and returns an error rather
    than a half-parsed row: every figure here is one a reader would act on.
    """
    if AM_REPORT not in text:
        return {"error": f"Not {AM_REPORT} -- the PDF at {AM_PDF} is a different report now."}
    if "Morning" not in text:
        return {"error": f"{AM_REPORT} no longer says 'Morning'; refusing to bank it as the AM read."}

    cur = _after(text, "Current Cutout Values:", 2)
    if cur is None:
        return {"error": "No 'Current Cutout Values' in the morning report."}
    spread = _after(text, "Choice/Select spread:", 1)
    if spread is None:
        return {"error": "No Choice/Select spread in the morning report."}

    chg   = _after(text, "Change from prior day:", 2)
    loads = _after(text, "Total Load Count", 1)
    avg5  = _after(text, "Current 5 Day Simple Average:", 2)

    choice, select = cur

    # THE AUDIT. Choice minus Select must be the printed spread.
    if abs((choice - select) - spread[0]) > SPREAD_TOLERANCE:
        return {"error": (
            f"Morning report does not reconcile: {choice:.2f} - {select:.2f} = "
            f"{choice - select:.2f}, but it prints a spread of {spread[0]:.2f}. "
            "Refusing to use a parse that has shifted."
        )}

    return {
        "report_date":   _report_date(text),
        "choice":        choice,
        "select":        select,
        "change_choice": chg[0] if chg else None,
        "change_select": chg[1] if chg else None,
        "spread":        spread[0],
        "loads":         loads[0] if loads else None,
        "avg5_choice":   avg5[0] if avg5 else None,
        "avg5_select":   avg5[1] if avg5 else None,
    }


def fetch_am(timeout: int = 40) -> dict:
    """Today's morning cutout, live. `{"error": ...}` on any failure."""
    try:
        import requests
        from pypdf import PdfReader
        raw = requests.get(AM_PDF, timeout=timeout).content
        pages = PdfReader(io.BytesIO(raw)).pages
        return parse_am(pages[0].extract_text() or "")
    except Exception as e:
        return {"error": f"Could not read the morning cutout: {e}"}


# -- Which session the page should open on ------------------------------------

def default_session(am_date, pm_date, today) -> str:
    """
    "AM" while the morning read is the newest thing published, "PM" otherwise.

    DRIVEN BY WHAT IS PUBLISHED, NOT BY THE CLOCK, and that is the correctness
    of it. A rule like "after 3pm show the PM" is wrong on every day USDA runs
    late -- it would default to a PM report that does not exist yet and show
    yesterday's close as though it were today's. Reading the dates instead
    gives the same answer on a normal day and the right one on a slow one.

    Before the morning release the AM PDF still holds YESTERDAY's report, so
    am_date != today and this correctly falls through to PM.
    """
    if am_date is not None and am_date == today and pm_date != today:
        return "AM"
    return "PM"


# -- Banking it, because nobody else keeps it ---------------------------------

def enabled() -> bool:
    """Snowflake is configured. The same flag the rest of the portal uses."""
    return os.getenv("USE_SNOWFLAKE", "").strip().lower() in ("1", "true", "yes", "on")


def _load_db():
    """
    apps/cme_feeder_cattle/snowflake_db.py under a PRIVATE module name.

    The trick draft_store._load_db() and sources._load_fci_db() both use, for
    the same reason: snowflake_db.py exists five times in this repo and Python
    caches modules by NAME, so a plain `import snowflake_db` gets whichever
    page loaded first. "_am_cutout_db" can never join that collision.
    """
    path = APPS / "cme_feeder_cattle" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_am_cutout_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_am_cutout_db"] = mod
    spec.loader.exec_module(mod)
    return mod


_CONN = None


def _conn():
    global _CONN
    if _CONN is None:
        _CONN = _load_db().get_conn()
    return _CONN


def _drop_conn():
    global _CONN
    try:
        if _CONN is not None:
            _CONN.close()
    except Exception:
        pass
    _CONN = None


def _run(fn):
    """fn(cursor), reconnecting once -- a cached connection outlives its token."""
    for attempt in (1, 2):
        try:
            cur = _conn().cursor()
            try:
                return fn(cur)
            finally:
                cur.close()
        except Exception:
            _drop_conn()
            if attempt == 2:
                raise
    return None


def _who() -> str:
    try:
        host = socket.gethostname()
    except Exception:
        host = "?"
    return f"portal@{host}"[:128]


def _round(v):
    """Compare and store at the precision the column holds, so a float that
    round-trips through NUMBER(9,2) does not read as a correction."""
    return None if v is None else round(float(v), 2)


def ensure_table() -> str:
    """Create the schema and table if missing. "" on success, else the reason."""
    if not enabled():
        return "Snowflake is not configured (USE_SNOWFLAKE is unset)."
    try:
        def go(cur):
            for stmt in DDL:
                cur.execute(stmt)
        _run(go)
        return ""
    except Exception as e:
        return f"Could not reach Snowflake: {e}"


def bank(row: dict) -> str:
    """
    Record one morning reading, if it is not already recorded.

    OPPORTUNISTIC, AND THE PAGE IS THE ONLY THING THAT CALLS IT. Community
    Cloud has no scheduler -- the same constraint letter/rundown.py records --
    so the series fills on the days somebody opens this page after the morning
    release, and has a hole on the days nobody does. A cron on the droplet that
    already writes JSA.BEEF_TRIMMINGS.IMPORT_COW90 can take the same table over
    later without changing anything here or on the page.

    Returns "" when nothing needed doing, "banked" on an insert, else a reason.
    """
    if row.get("error") or row.get("report_date") is None:
        return ""
    if not enabled():
        return "Snowflake is not configured (USE_SNOWFLAKE is unset)."
    try:
        def go(cur):
            cur.execute(
                f"SELECT {', '.join(_COLS)} FROM {TABLE} "
                "WHERE REPORT_DATE = %s ORDER BY RECORDED_AT DESC LIMIT 1",
                (row["report_date"],),
            )
            existing = cur.fetchone()
            new = tuple(_round(row.get(f)) for f in FIELDS)
            # A row already there and unchanged needs no second copy; one that
            # DIFFERS is a USDA correction and gets its own, so the published
            # figure and the corrected one both survive.
            if existing is not None and tuple(_round(v) for v in existing) == new:
                return ""
            cur.execute(
                f"INSERT INTO {TABLE} (REPORT_DATE, {', '.join(_COLS)}, "
                "RECORDED_AT, RECORDED_BY) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (row["report_date"], *new,
                 datetime.now(timezone.utc).replace(tzinfo=None), _who()),
            )
            return "banked"
        return _run(go) or ""
    except Exception as e:
        return f"Could not record the morning cutout: {e}"


def history(limit: int = 400):
    """
    The banked mornings, newest row per report date, oldest first.

    Returns a DataFrame, empty when there is nothing yet -- which is the
    expected state until this has been running for a few days, and is not an
    error worth shouting about.
    """
    import pandas as pd
    if not enabled():
        return pd.DataFrame()
    try:
        def go(cur):
            cur.execute(
                f"SELECT REPORT_DATE, {', '.join(_COLS)} FROM ("
                f"  SELECT REPORT_DATE, {', '.join(_COLS)}, "
                "         ROW_NUMBER() OVER (PARTITION BY REPORT_DATE "
                "                            ORDER BY RECORDED_AT DESC) AS RN "
                f"  FROM {TABLE}"
                ") WHERE RN = 1 ORDER BY REPORT_DATE DESC LIMIT %s",
                (limit,),
            )
            return cur.fetchall()
        rows = _run(go) or []
        df = pd.DataFrame(rows, columns=["report_date", *(c.lower() for c in _COLS)])
        if df.empty:
            return df
        df = df.rename(columns={"choice_600_900": "choice", "select_600_900": "select"})
        df["report_date"] = pd.to_datetime(df["report_date"])
        num = [c for c in df.columns if c != "report_date"]
        df[num] = df[num].apply(pd.to_numeric, errors="coerce")
        return df.sort_values("report_date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def fade(am_df, pm_hist):
    """
    The AM reading against the PM close for the same day: what the morning
    said, where the day finished, and the difference.

    `pm_hist` is the page's own history frame, so the two columns come from
    the two reports and nothing is recomputed. An inner join on purpose -- a
    morning with no close yet is not a fade.
    """
    import pandas as pd
    if am_df is None or len(am_df) == 0 or pm_hist is None or len(pm_hist) == 0:
        return pd.DataFrame()
    pm = pm_hist[["report_date", "choice", "select"]].copy()
    pm["report_date"] = pd.to_datetime(pm["report_date"])
    out = am_df.merge(pm, on="report_date", how="inner", suffixes=("_am", "_pm"))
    if out.empty:
        return out
    out["choice_fade"] = out["choice_pm"] - out["choice_am"]
    out["select_fade"] = out["select_pm"] - out["select_am"]
    return out
