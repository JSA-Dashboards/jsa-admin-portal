"""
USDA WASDE -- U.S. Meats Supply and Use, parsed from the released report.

Written for the Beef Trade page, but DELIBERATELY GENERIC: nothing here knows
about beef in particular, or about trade in particular. `load()` returns every
commodity and every attribute in the table, so a second page wanting the WASDE
production or per-capita line can import this module rather than growing a
second WASDE reader. That is the `snowflake_db.py`-times-five lesson applied
before the fact rather than after it.

    import wasde
    w = wasde.load()
    w.value("Beef", "imports")        # current forecast, million lb
    w.revision("Beef", "imports")     # change from last month's WASDE

WHY THE .txt AND NOT THE .xml. ESMIS publishes each release four ways and the
XML is the structured one, which makes it the obvious choice and the wrong one
here: it is 2 MB against the text file's 24 KB, and the revision panel wants a
dozen releases. Twenty-five releases of XML is 50 MB for two numbers apiece.

A fixed-layout text parse normally argues the other way -- it is the fragile
thing nobody notices breaking. Two things make it safe here:

  * EVERY ROW CARRIES ITS OWN AUDIT. Beginning stocks + production + imports
    must equal total supply, and total supply less exports and ending stocks
    must equal total disappearance. A shifted column is the failure that does
    not raise and does not look wrong -- a plausible number in the wrong place.
    `_row_ok` refuses a row that fails either identity, so a layout change
    shows up as a missing figure rather than a silently wrong one.
  * THE XML IS THE TEST ORACLE. tests/test_wasde.py parses the XML
    independently and asserts this parser agrees with it figure for figure.
    The structured file still does the work it is good at; it just does it in
    CI instead of on every page load.

THE RELEASE ALREADY CONTAINS LAST MONTH'S FORECAST. Each projection year prints
two rows, the previous month's estimate and this one -- "Aug" then "Sep". So
the month-over-month revision costs no extra request and needs no stored
history, which is why the headline panel is free and only the longer revision
chart has to go and fetch.

WHAT ESMIS DOES NOT HAVE. /release/findByPubId/1659 returns 25 releases, which
as of 2026-10-07 is August 2024 forward. **October 2025 is absent** -- that
WASDE was not published -- so a revision series has a real hole in it and
`history()` returns the gap rather than bridging it. A straight line across a
month USDA never published would read as a forecast that did not move.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

import requests

# BUMP THIS whenever `load()` or `history()` changes the SHAPE of what they
# return. `st.cache_data` keys on the decorated function's own code and never
# on the modules it calls -- the trap CLAUDE.md records for `leverage.SCHEMA`
# and `am_cutout.SCHEMA`. Without it a page adds a key, reads "-", nothing
# raises, and the section quietly vanishes.
SCHEMA = 1

ESMIS_BASE = "https://esmis.nal.usda.gov/api/v1"
WASDE_PUB_ID = 1659

TABLE_TITLE = "U.S. Meats Supply and Use"

# The eight numeric columns, left to right, exactly as the report prints them.
# Order is the contract -- the text report has no per-column header a parser
# could key on, because "Beg-/inning/stocks" is split across three header
# lines. _row_ok is what defends the assumption.
COLUMNS = ["beginning_stocks", "production", "imports", "total_supply",
           "exports", "ending_stocks", "total_use", "per_capita"]

UNITS = "Million Pounds"

# Rounding slack on the two identities below. USDA rounds each component
# independently, so the disappearance identity misses by a pound now and then
# -- Pork 2025 prints 21,744 where the subtraction gives 21,743. Two is ample
# for that and far too tight to admit a shifted column, which moves a figure
# by thousands.
IDENTITY_TOLERANCE = 2.0

_FOOTNOTE = re.compile(r"\s*\d+\s*/\s*$")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")

_YEAR_ROW = re.compile(r"^\s{2,10}(\d{4})\s*(Proj\.|Est\.)?\s*(.*)$")
_MONTH_ROW = re.compile(r"^\s{10,}([A-Z][a-z]{2})\s+(.*)$")
_NUMS = re.compile(r"-?[\d,]+\.?\d*")


def _num(tok: str):
    """A report figure, or None. USDA writes a withheld cell as a bare dash."""
    tok = (tok or "").strip()
    if not tok or tok in ("-", "--", "NA", "N/A"):
        return None
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def _row_ok(v: dict) -> bool:
    """
    Both accounting identities hold.

    THE WHOLE REASON A FIXED-WIDTH PARSE IS ACCEPTABLE HERE. The report gives
    eight numbers whose relationships are fixed by what they mean, so a column
    read into the wrong slot is detectable without a second source. Checked on
    every row, including ones no page displays, because the cheapest place to
    catch a layout change is the row next to the one being read.
    """
    need = ("beginning_stocks", "production", "imports", "total_supply",
            "exports", "ending_stocks", "total_use")
    if any(v.get(k) is None for k in need):
        return False
    supply = v["beginning_stocks"] + v["production"] + v["imports"]
    if abs(supply - v["total_supply"]) > IDENTITY_TOLERANCE:
        return False
    disappearance = v["total_supply"] - v["exports"] - v["ending_stocks"]
    return abs(disappearance - v["total_use"]) <= IDENTITY_TOLERANCE


def _clean_commodity(raw: str) -> str:
    """
    "TotalRedMeat5/" -> "Total Red Meat".

    The report squeezes the spaces out of a commodity name to fit the column,
    so they are put back on the case boundaries rather than from a lookup
    table that would need editing the first time USDA adds a line.
    """
    name = _FOOTNOTE.sub("", (raw or "").strip())
    name = _CAMEL.sub(" ", name)
    name = re.sub(r"\s*&\s*", " & ", name)
    return re.sub(r"\s{2,}", " ", name).strip()


@dataclass
class Series:
    """One commodity-year, with this month's figures and last month's."""
    commodity: str
    year: int
    status: str = ""                 # "" (actual), "Proj.", "Est."
    current_month: str = ""          # "Sep"
    prior_month: str = ""            # "Aug"
    current: dict = field(default_factory=dict)
    prior: dict = field(default_factory=dict)

    @property
    def is_forecast(self) -> bool:
        return bool(self.status)


@dataclass
class Wasde:
    report_month: str = ""           # "September 2026"
    release_date: date | None = None
    units: str = UNITS
    series: list = field(default_factory=list)
    source_url: str = ""

    def commodities(self) -> list:
        seen = []
        for s in self.series:
            if s.commodity not in seen:
                seen.append(s.commodity)
        return seen

    def years(self, commodity: str) -> list:
        return sorted(s.year for s in self.series if s.commodity == commodity)

    def get(self, commodity: str, year: int | None = None):
        """
        One Series. With no year, the EARLIEST forecast year -- the marketing
        year currently being revised, which is what a trader means by "the
        WASDE number". WASDE carries the following year as well from May
        onward, and defaulting to the latest would silently switch the
        headline mid-season.
        """
        rows = [s for s in self.series if s.commodity == commodity]
        if year is not None:
            rows = [s for s in rows if s.year == year]
        else:
            forecasts = sorted((s for s in rows if s.is_forecast),
                               key=lambda s: s.year)
            rows = forecasts[:1] or rows
        return rows[0] if rows else None

    def value(self, commodity: str, attribute: str, year: int | None = None):
        s = self.get(commodity, year)
        return s.current.get(attribute) if s else None

    def revision(self, commodity: str, attribute: str, year: int | None = None):
        """
        This month's figure less last month's, or None when either is absent.

        None rather than zero, always: an actual year has no prior-month row,
        and "USDA did not revise this" and "there is nothing to compare" are
        different statements a zero would merge.
        """
        s = self.get(commodity, year)
        if not s:
            return None
        now, was = s.current.get(attribute), s.prior.get(attribute)
        if now is None or was is None:
            return None
        return now - was


def _table_body(lines: list, title: str):
    """
    (body_lines, report_month) for one WASDE table, found by its title.

    THE DATA BEGINS AFTER THE *SECOND* BANNER OF "=", not the first. Every
    table opens with one rule under its title, then several lines of column
    headings -- "Beg- Produc-", "Item inning tion", "stocks 1/ Imports" --
    then a second rule. Taking the first banner as the start reads those
    heading lines as data, and taking the first banner after them as the END
    closes the table before its first real row: the parse then returns a
    report month, nothing else, and no error at all. It reads exactly like a
    report that has stopped publishing. Cost one debugging round on
    2026-10-07.

    Shared by every table here, which is why two WASDE tables on the same
    printed page (production and prices both sit on page 31) are found
    independently by title rather than by page.
    """
    start = None
    for i, ln in enumerate(lines):
        if title in ln:
            start = i
            break
    if start is None:
        raise ValueError("%r not found in release" % title)

    # The month is printed in the page header, and a page can carry TWO
    # tables -- production and prices both sit on page 31 -- so the second
    # one has no header above it within any sane look-back. Fall back to the
    # first page header in the document, which carries the same month as
    # every other page of the same release.
    month = ""
    for ln in lines[max(0, start - 10):start]:
        m = re.search(r"([A-Z][a-z]+ \d{4})\s*$", ln)
        if m:
            month = m.group(1)
    if not month:
        for ln in lines:
            m = re.search(r"WASDE - \d+ - \d+\s+([A-Z][a-z]+ \d{4})\s*$", ln)
            if m:
                month = m.group(1)
                break

    banners = [i for i in range(start + 1, len(lines))
               if lines[i].startswith("===")]
    if len(banners) < 2:
        raise ValueError("%r has no header rule" % title)
    body_end = banners[2] if len(banners) > 2 else len(lines)
    return lines[banners[1] + 1:body_end], month


def parse(text: str, release_date: date | None = None,
          source_url: str = "") -> Wasde:
    """Parse the U.S. Meats Supply and Use table out of a WASDE text release."""
    lines = (text or "").splitlines()

    body, month = _table_body(lines, TABLE_TITLE)

    out: list = []
    commodity = ""
    cur: Series | None = None

    i = 0
    while i < len(body):
        raw = body[i].rstrip()
        i += 1
        if not raw.strip() or UNITS in raw:
            continue

        m = _MONTH_ROW.match(raw)
        if m and cur is not None:
            vals = _collect(m.group(2))
            if vals:
                # Rows arrive oldest first -- "Aug" then "Sep" -- so each one
                # pushes the one before it into `prior`. Reading positionally
                # rather than by month name is what keeps December-to-January
                # working, where the prior month's name sorts after the
                # current one.
                cur.prior, cur.prior_month = cur.current, cur.current_month
                cur.current, cur.current_month = vals, m.group(1)
            continue

        m = _YEAR_ROW.match(raw)
        if m and commodity:
            cur = Series(commodity=commodity, year=int(m.group(1)),
                         status=(m.group(2) or "").strip())
            out.append(cur)
            vals = _collect(m.group(3))
            if vals:
                cur.current = vals          # an actual year: one row, no month
            continue

        # Anything else at the left margin is a commodity heading -- and it
        # may be only part of one. The report wraps a long name across two
        # lines ("TotalRed" / "Meat5/", "Total" / "Poultry6/").
        #
        # THE JOIN IS DECIDED BY WHAT FOLLOWS, not by how the fragment looks.
        # Trailing padding separates them today -- a finished heading is
        # space-filled to the column width and a fragment is not -- but
        # "RedMeat& Poultry" is a complete heading with no padding, so that
        # tell is wrong on the last commodity in the table. A heading is
        # finished when the next line with anything on it is indented.
        if raw[:1] not in (" ", "\t"):
            if _NUMS.search(raw):
                continue
            head = raw.strip()
            while i < len(body):
                nxt = body[i]
                if not nxt.strip():
                    i += 1
                    continue
                if nxt[:1] in (" ", "\t"):
                    break
                head += nxt.strip()
                i += 1
            commodity = _clean_commodity(head)
            cur = None

    return Wasde(report_month=month, release_date=release_date,
                 series=[s for s in out if s.current], source_url=source_url)


def _collect(tail: str) -> dict:
    """The eight figures on a data row, or {} if they do not audit."""
    toks = _NUMS.findall(tail or "")
    if len(toks) < len(COLUMNS):
        return {}
    vals = {k: _num(t) for k, t in zip(COLUMNS, toks[:len(COLUMNS)])}
    return vals if _row_ok(vals) else {}


# -- fetching ----------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "JSA-Livestock-Portal/1.0 (+https://www.jpsi.com)"
    return s


def releases(sess: requests.Session | None = None) -> list:
    """
    [{date, url}] newest first, for every WASDE release ESMIS still serves.

    THE LIST IS SHORT AND HAS A HOLE IN IT. Twenty-five releases as of
    2026-10-07, so roughly two years, and October 2025 is simply not there --
    that WASDE was never published. Callers must treat a missing month as
    missing; see `history`.
    """
    sess = sess or _session()
    r = sess.get("%s/release/findByPubId/%d" % (ESMIS_BASE, WASDE_PUB_ID),
                 timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("results", payload) if isinstance(payload, dict) else payload
    out = []
    for rec in rows if isinstance(rows, list) else []:
        if not isinstance(rec, dict):
            continue
        txt = [f for f in (rec.get("files") or []) if str(f).lower().endswith(".txt")]
        if not txt:
            continue
        try:
            when = datetime.strptime(str(rec["release_datetime"])[:10], "%Y-%m-%d").date()
        except (KeyError, ValueError, TypeError):
            continue
        out.append({"date": when, "url": txt[0]})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def load(sess: requests.Session | None = None) -> Wasde:
    """The newest WASDE."""
    sess = sess or _session()
    rel = releases(sess)
    if not rel:
        raise RuntimeError("ESMIS returned no WASDE releases")
    newest = rel[0]
    r = sess.get(newest["url"], timeout=45)
    r.raise_for_status()
    return parse(r.text, release_date=newest["date"], source_url=newest["url"])


def history(commodity: str, attribute: str, year: int, n: int = 12,
            sess: requests.Session | None = None) -> list:
    """
    [{date, value, report_month}] -- how one WASDE figure has been revised,
    oldest release first, over the n most recent releases that carry it.

    EXPENSIVE BY THE STANDARDS OF THIS PAGE and deliberately not called on
    load: n releases is n requests. 24 KB apiece rather than the XML's 2 MB is
    what makes a dozen tolerable at all.

    A release that does not carry the year is skipped rather than zero-filled
    -- WASDE only adds the following marketing year in May, so asking for 2027
    across twelve releases legitimately returns seven points. And the months
    USDA never published are absent from `releases()` entirely, so the gap is
    in the returned dates. Do not draw through it.
    """
    sess = sess or _session()
    out = []
    for rel in releases(sess)[:n]:
        try:
            r = sess.get(rel["url"], timeout=45)
            r.raise_for_status()
            w = parse(r.text, release_date=rel["date"], source_url=rel["url"])
        except (requests.RequestException, ValueError):
            continue
        s = w.get(commodity, year)
        if s and s.current.get(attribute) is not None:
            out.append({"date": rel["date"], "value": s.current[attribute],
                        "report_month": w.report_month})
    out.sort(key=lambda r: r["date"])
    return out


# -- the quarterly tables ----------------------------------------------------
#
# WASDE page 31 carries two tables of the same shape: quarterly production and
# quarterly prices. The Cash Cattle Trade page wants the steer price out of the
# second; everything here is written for both, because they differ only in
# their column list and writing it twice is how a second reader gets born.

QUARTERLY_PRICES_TITLE = "U.S. Quarterly Prices for Animal Products"
QUARTERLY_PRODUCTION_TITLE = "U.S. Quarterly Animal Product Production"

# Left to right as printed. "Streers" is USDA's own spelling and is not fixed
# here -- see QUARTERLY_PRICE_NOTE.
QUARTERLY_PRICE_COLUMNS = ["steer", "barrows_gilts", "broilers", "turkeys",
                           "eggs", "milk"]
QUARTERLY_PRODUCTION_COLUMNS = ["beef", "pork", "red_meat", "broiler",
                                "turkey", "total_poultry", "red_meat_poultry",
                                "egg", "milk"]

# WASDE's own footnote 2/ on the price table. WORTH CARRYING AROUND rather
# than paraphrasing: it is what makes the figure comparable to the Cash Cattle
# Trade page's weekly series at all, and "the USDA steer price" on its own
# would not be.
STEER_PRICE_BASIS = "5-Area, Direct, Total all grades"

_QTR_YEAR = re.compile(r"^(\d{4})\s*$")
# LEADING WHITESPACE IS OPTIONAL, AND THAT IS NOT TIDINESS. The quarter rows
# are indented ("     III*") but the annual rows are NOT ("AugProj.    245.35"
# at column zero, exactly like a year heading). Requiring indentation silently
# dropped every annual row, which is the only row the forecast panel wants --
# the table parsed, the quarters were all correct, and `annual()` returned
# None with nothing raising.
_QTR_PERIOD = re.compile(
    r"^\s*(I{1,3}V?|Annual|[A-Z][a-z]{2}Proj\.)\s*(\*?)\s+(.*)$")

# The annual figure must equal the simple mean of the four quarters. USDA's
# footnote 1/ says the annual is a simple average of months and each quarter
# is three months, so the two are the same arithmetic. Checked where all four
# quarters are present; a tenth of a cent of slack for the rounding USDA
# applies to each quarter independently.
QUARTERLY_TOLERANCE = 0.02


# Roman quarter labels, as printed. AN EXPLICIT MAP, because the obvious
# shortcut -- the length of the numeral -- is right for I, II and III and
# wrong for IV, which it calls Q2. That shipped for about ten minutes and
# rendered "Q3 proj / Q2 proj" as the last two quarters of the year.
QUARTER_NUMBER = {"I": 1, "II": 2, "III": 3, "IV": 4}


def quarter_number(period: str):
    """1-4 for a Roman quarter label, or None for an annual row."""
    return QUARTER_NUMBER.get((period or "").strip())


@dataclass
class QuarterRow:
    year: int
    period: str                  # "I".."IV", "Annual", "SepProj."
    projected: bool              # the printed asterisk
    values: dict = field(default_factory=dict)

    @property
    def is_annual(self) -> bool:
        return self.period == "Annual" or self.period.endswith("Proj.")


# How a table's annual figure relates to its quarters. A PROPERTY OF THE
# TABLE, not of the caller: a price is an average of its quarters and a
# quantity is their sum, and the two tables sit on the same printed page.
#
# Hard-coding "mean" was right for the steer price and wrong for production,
# where 6,148 + 6,154 + 6,140 + 6,435 = 24,877 exactly and the mean is 6,219.
# The audit would have printed "WASDE's annual figure no longer equals the
# mean of its four quarters" on every single load of the Cattle Weights
# panel -- a false alarm that teaches readers to ignore a real one. Caught
# by running the audit against the production table before shipping it.
AGGREGATE_BY_TITLE = {
    QUARTERLY_PRICES_TITLE: "mean",
    QUARTERLY_PRODUCTION_TITLE: "sum",
}


@dataclass
class Quarterly:
    report_month: str = ""
    title: str = ""
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    aggregate: str = "mean"          # "mean" for prices, "sum" for quantities

    def years(self) -> list:
        return sorted({r.year for r in self.rows})

    def quarters(self, year: int) -> list:
        return [r for r in self.rows if r.year == year and not r.is_annual]

    def annual(self, column: str, year: int):
        """
        The year's annual figure and whether it is a forecast.

        A COMPLETED YEAR PRINTS "Annual"; A FORECAST YEAR PRINTS "<Mon>Proj."
        twice -- last month's and this month's -- and there is no "Annual" row
        at all. So the newest Proj. row IS the annual forecast, and reaching
        for "Annual" on the current year silently returns nothing.
        """
        rows = [r for r in self.rows if r.year == year and r.is_annual]
        if not rows:
            return None, False
        exact = [r for r in rows if r.period == "Annual"]
        if exact:
            return exact[-1].values.get(column), False
        return rows[-1].values.get(column), True

    def prior_annual(self, column: str, year: int):
        """Last month's forecast of the same annual figure, or None."""
        proj = [r for r in self.rows
                if r.year == year and r.period.endswith("Proj.")]
        if len(proj) < 2:
            return None
        return proj[-2].values.get(column)

    def reconciles(self, column: str, year: int):
        """
        {ok, annual, mean, quarters} -- does the annual equal the mean of its
        four quarters?

        THE ONLY AUDIT THIS TABLE OFFERS. The meats table has two accounting
        identities; a price table has none, so a shifted column there would be
        undetectable from the row alone. This is the substitute, and it does
        work: for September 2026 the four steer quarters average 237.3525
        against a printed 237.35.

        `ok` is None, not False, when fewer than four quarters are published --
        which is every forecast year before the following May. Refusing to
        judge is different from judging it wrong.
        """
        qs = [r for r in self.quarters(year)
              if r.values.get(column) is not None]
        annual, _ = self.annual(column, year)
        if annual is None or len(qs) != 4:
            return {"ok": None, "annual": annual, "expected": None,
                    "how": self.aggregate, "quarters": len(qs)}
        total = sum(r.values[column] for r in qs)
        expected = total / 4.0 if self.aggregate == "mean" else total
        # A sum of four five-digit figures carries four roundings, so the
        # slack scales with the aggregation rather than staying at a price's
        # two cents.
        tol = (QUARTERLY_TOLERANCE if self.aggregate == "mean"
               else QUARTERLY_TOLERANCE * 4)
        return {"ok": abs(expected - annual) <= tol, "annual": annual,
                "expected": expected, "how": self.aggregate, "quarters": 4}


def parse_quarterly(text: str, title: str, columns: list) -> Quarterly:
    """Parse one of the page-31 quarterly tables."""
    body, month = _table_body((text or "").splitlines(), title)
    out = Quarterly(report_month=month, title=title, columns=list(columns),
                    aggregate=AGGREGATE_BY_TITLE.get(title, "mean"))
    year = None
    for raw in body:
        line = raw.rstrip()
        if not line.strip() or line.startswith("==="):
            continue
        m = _QTR_YEAR.match(line.strip()) if line[:1] not in (" ", "\t") else None
        if m:
            year = int(m.group(1))
            continue
        m = _QTR_PERIOD.match(line)
        if not m or year is None:
            continue
        toks = _NUMS.findall(m.group(3))
        if len(toks) < len(columns):
            continue
        out.rows.append(QuarterRow(
            year=year, period=m.group(1), projected=bool(m.group(2)),
            values={k: _num(t) for k, t in zip(columns, toks[:len(columns)])}))
    return out


def load_quarterly_prices(sess: requests.Session | None = None) -> Quarterly:
    """The newest WASDE's quarterly animal-product prices."""
    sess = sess or _session()
    rel = releases(sess)
    if not rel:
        raise RuntimeError("ESMIS returned no WASDE releases")
    r = sess.get(rel[0]["url"], timeout=45)
    r.raise_for_status()
    return parse_quarterly(r.text, QUARTERLY_PRICES_TITLE,
                           QUARTERLY_PRICE_COLUMNS)


def summary(q: Quarterly, column: str, year: int | None = None) -> dict:
    """
    One figure from a quarterly table, with everything a panel needs:
    {year, value, prior, revision, revision_pct, base_year, base, yoy_pct,
     next_year, next_value, next_revision, quarters, audit}.

    SHARED SO THREE PAGES CANNOT DISAGREE ABOUT ONE NUMBER. Cash Cattle
    Trade, Cattle Weights and Fed Cattle Crush all show a WASDE figure, and
    each computing its own revision and year-on-year is how two of them end
    up a decimal apart with both defensible -- the letter-versus-dashboard
    failure CLAUDE.md records twice. The LAYOUT stays per page, because the
    three pages have different tile styling; only the arithmetic is here.

    `year` defaults to the earliest forecast year, matching `Wasde.get`.
    """
    years = q.years()
    if not years:
        return {}
    if year is None:
        forecast_years = [y for y in years if q.annual(column, y)[1]]
        year = min(forecast_years) if forecast_years else max(years)

    value, is_forecast = q.annual(column, year)
    prior = q.prior_annual(column, year)
    base, _ = q.annual(column, year - 1)
    nxt, _ = q.annual(column, year + 1)
    nxt_prior = q.prior_annual(column, year + 1)

    def _pct(new, old):
        if new is None or not old:
            return None
        return (new / old - 1.0) * 100.0

    return {
        "year": year,
        "value": value,
        "is_forecast": is_forecast,
        "prior": prior,
        "revision": (value - prior) if (value is not None and prior is not None) else None,
        "revision_pct": _pct(value, prior),
        "base_year": year - 1,
        "base": base,
        "yoy_pct": _pct(value, base),
        "yoy_abs": (value - base) if (value is not None and base is not None) else None,
        "next_year": year + 1,
        "next_value": nxt,
        "next_revision": (nxt - nxt_prior) if (nxt is not None and nxt_prior is not None) else None,
        "next_vs_this": _pct(nxt, value),
        "quarters": [{"period": r.period, "number": quarter_number(r.period),
                      "value": r.values.get(column), "projected": r.projected}
                     for r in q.quarters(year)],
        "audit": q.reconciles(column, year),
        "report_month": q.report_month,
    }


def load_quarterly_production(sess: requests.Session | None = None) -> Quarterly:
    """The newest WASDE's quarterly animal-product PRODUCTION table."""
    sess = sess or _session()
    rel = releases(sess)
    if not rel:
        raise RuntimeError("ESMIS returned no WASDE releases")
    r = sess.get(rel[0]["url"], timeout=45)
    r.raise_for_status()
    return parse_quarterly(r.text, QUARTERLY_PRODUCTION_TITLE,
                           QUARTERLY_PRODUCTION_COLUMNS)


def quarters_by_year(q: Quarterly, column: str) -> dict:
    """
    {year: [{number, value, projected}]} for every year the table quotes.

    `summary()` carries one year's quarters, which is all a forecast panel
    needs. A page matching a DATE to a quarter needs the others: the Fed
    Cattle Crush default start date puts the sale in the following year, and
    looking only in the current one made an April 2027 sale fall back to the
    2026 annual average -- then report the gap as though the two were the
    same period. WASDE carries the next year's Q1 and Q2 from May onward, so
    the figure was there and simply not being looked at.
    """
    out = {}
    for year in q.years():
        rows = [{"number": quarter_number(r.period), "value": r.values.get(column),
                 "projected": r.projected}
                for r in q.quarters(year)]
        rows = [r for r in rows if r["number"] and r["value"] is not None]
        if rows:
            out[year] = rows
    return out
