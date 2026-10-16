"""
US–Canada live cattle trade, in HEAD, both directions.

    https://www.ers.usda.gov/media/29545/cattle-monthly-us-trade-head.csv

**THE ADJACENT DOWNLOAD TO THE ONE THE PORTAL ALREADY READS.**
`apps/beef_trade/trade_flows.py` fetches media/29544, the monthly beef trade
file; this is 29545 on the same ERS data product page, same column shape
(COMMODITY_DESC, TRADE_FLOW, UNIT_DESC, GEOGRAPHY_CODE, GEOGRAPHY_DESC,
YEAR_ID, TIMEPERIOD_ID, AMOUNT), no API key, plain CSV. Monthly, 1989-2026,
119 partner countries.

WHY THIS AND NOT CENSUS. The obvious route is the Census trade API, which the
cme-feeder-cattle-index repo already uses for the Mexican head counts. It was
probed properly on 2026-10-12 and it is the worse source here, in four ways
that each cost real accuracy:

* **Exports collapse to one code.** Census Schedule B ships 99% of US cattle
  to Canada under `0102290000`, "CATTLE, LIVE, OTHER THAN PUREBRED BREEDING
  ANIMALS" — no weight band, no sex, no feeder/slaughter split. ERS is no
  better on exports (see below) but is no worse, and costs nothing.
* **Bison would contaminate a naive sum.** `0102390010` ran 70,884 head over
  2024-2026 and is the fifth largest Canadian line under `0102*`.
* **The sub-90kg codes are BOB CALVES, not feeders** — 96-98 lb average,
  newborn dairy bull calves — and about 111k head over three years. The
  sibling repo's `classify_commodity()` buckets them as "feeder".
* **The HS vocabulary breaks at 2012-01**, so a continuous series needs an
  explicit 010210/010290 -> 010221/010229 map.

ERS has already made every one of those decisions, in USDA's own classes.

**THE TWO DIRECTIONS ARE NOT SYMMETRIC, AND THE PAGE MUST NOT PAPER OVER IT.**
The IMPORT side splits into `Cattle and calves for feeding`, `Cattle for
breeding`, `Cattle for immediate slaughter` and `Cattle, total`. The EXPORT
side is `Cattle, total` and nothing else, for every country in the file. So
"Canadian feeder cattle imports" is a real published figure and "Canadian
feeder cattle exports" is not — there is no feeder class on the export side to
report. That is a property of what USDA publishes, not of this query, and a
panel that showed a feeder import figure beside a total export figure under
one heading would be comparing two different populations.

**THE CLASS SPLIT STARTS 2012; THE TOTAL GOES BACK TO 1989.** A chart that
opens on the full history of `Cattle, total` and overlays a feeder line
starting two decades in reads as feeders collapsing to zero before 2012.
`class_floor()` returns the first year the split exists so the page can say so
rather than letting the axis imply it.

**`World total` IS A ROW IN THE FILE**, the trap `trade_flows.py` records: a
groupby that forgets to exclude it doubles every figure, and a doubled cattle
import number is wrong and entirely plausible. Every helper here filters on a
named country instead of summing, and `reconciles()` audits the class identity
on every load.
"""

from __future__ import annotations

import io

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ERS_CATTLE_MONTHLY = ("https://www.ers.usda.gov/media/29545/"
                      "cattle-monthly-us-trade-head.csv")

CANADA = "Canada"
MEXICO = "Mexico"
WORLD = "World total"

IMPORTS = "Imports"
EXPORTS = "Exports"
FLOWS = (IMPORTS, EXPORTS)

#: USDA's own class names, verbatim. "Cattle and calves for feeding" is the
#: feeder class and is the one this dashboard leads with.
FEEDER = "Cattle and calves for feeding"
SLAUGHTER = "Cattle for immediate slaughter"
BREEDING = "Cattle for breeding"
TOTAL = "Cattle, total"

#: The three classes that should sum to TOTAL on the import side. Checked on
#: every load by reconciles() rather than assumed -- it is the only free audit
#: this file offers, and a missing class looks like a smaller market.
IMPORT_CLASSES = (FEEDER, SLAUGHTER, BREEDING)

#: Bumped whenever load() changes the SHAPE of what it returns. st.cache_data
#: keys on the decorated function's own code and arguments and never on the
#: modules it calls -- the trap CLAUDE.md records, which was inert in nineteen
#: loaders because the argument carried a leading underscore or sat at its
#: default. No underscore, and the call site passes it.
SCHEMA = 1


def _session() -> requests.Session:
    """Retries on 5xx. ERS serves this from a CDN that flaps occasionally, and
    a single-shot GET reports an outage that is not happening -- the lesson
    paid for on marsapi in the Beef Trimmings work."""
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=0.6,
                  status_forcelist=[500, 502, 503, 504],
                  allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def fetch(sess=None) -> pd.DataFrame:
    """The whole file, normalised. Columns: flow, country, commodity, year,
    month, head."""
    sess = sess or _session()
    r = sess.get(ERS_CATTLE_MONTHLY, timeout=120)
    r.raise_for_status()
    return parse(r.content)


def parse(payload) -> pd.DataFrame:
    """Split out from fetch() so a test can exercise it without the network."""
    df = pd.read_csv(io.BytesIO(payload) if isinstance(payload, (bytes, bytearray))
                     else payload, encoding="utf-8-sig")
    need = {"COMMODITY_DESC", "TRADE_FLOW", "GEOGRAPHY_DESC",
            "YEAR_ID", "TIMEPERIOD_ID", "AMOUNT"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError("ERS cattle CSV is missing %s" % sorted(missing))

    out = pd.DataFrame({
        "flow": df["TRADE_FLOW"].astype(str).str.strip(),
        "country": df["GEOGRAPHY_DESC"].astype(str).str.strip(),
        "commodity": df["COMMODITY_DESC"].astype(str).str.strip(),
        "year": pd.to_numeric(df["YEAR_ID"], errors="coerce"),
        "month": pd.to_numeric(df["TIMEPERIOD_ID"], errors="coerce"),
        "head": pd.to_numeric(df["AMOUNT"], errors="coerce"),
    }).dropna(subset=["year", "month", "head"])
    out["year"] = out["year"].astype(int)
    out["month"] = out["month"].astype(int)
    return out[out["flow"].isin(FLOWS)].reset_index(drop=True)


# ── the audit ───────────────────────────────────────────────────────────────

def reconciles(df: pd.DataFrame, country: str = CANADA,
               tolerance: int = 0) -> dict:
    """{ok, checked, worst, worst_at} — do the three import classes sum to
    USDA's own `Cattle, total`?

    The free audit on this file. A class quietly absent from a month looks
    exactly like a smaller market, and nothing else here would notice: every
    figure stays a plausible head count. Default tolerance is ZERO because
    these are integer head counts published by one agency in one file -- any
    slack is a hole rather than a safeguard, the argument `leverage.py` makes
    for OI_TOLERANCE.
    """
    imp = df[(df["flow"] == IMPORTS) & (df["country"] == country)]
    parts = (imp[imp["commodity"].isin(IMPORT_CLASSES)]
             .groupby(["year", "month"])["head"].sum())
    whole = (imp[imp["commodity"] == TOTAL]
             .set_index(["year", "month"])["head"])
    both = parts.index.intersection(whole.index)
    if len(both) == 0:
        return {"ok": None, "checked": 0, "worst": None, "worst_at": None}
    diff = (parts.loc[both] - whole.loc[both]).abs()
    worst = float(diff.max())
    at = diff.idxmax()
    return {"ok": worst <= tolerance, "checked": int(len(both)),
            "worst": worst, "worst_at": (int(at[0]), int(at[1]))}


# ── series ──────────────────────────────────────────────────────────────────

def series(df: pd.DataFrame, flow: str, commodity: str,
           country: str = CANADA) -> pd.DataFrame:
    """Monthly [year, month, head] for one flow/class/country, oldest first.

    Filtered on a NAMED country, never summed over the frame -- `World total`
    is a row in this file and a groupby that forgets it doubles the answer.
    """
    sub = df[(df["flow"] == flow) & (df["country"] == country)
             & (df["commodity"] == commodity)]
    return (sub[["year", "month", "head"]]
            .sort_values(["year", "month"]).reset_index(drop=True))


def annual(df: pd.DataFrame, flow: str, commodity: str,
           country: str = CANADA, complete_only: bool = True) -> pd.DataFrame:
    """[year, head, months] summed by calendar year.

    `complete_only` drops the year in progress. A bar covering eight months
    beside twelve-month bars is a true number telling a false story -- the rule
    `trade_flows.annual_figure` already enforces on the beef page.
    """
    s = series(df, flow, commodity, country)
    if s.empty:
        return s.assign(months=[])
    g = s.groupby("year").agg(head=("head", "sum"), months=("month", "nunique"))
    g = g.reset_index()
    return g[g["months"] == 12].reset_index(drop=True) if complete_only else g


def ytd(df: pd.DataFrame, flow: str, commodity: str, year: int,
        country: str = CANADA, through_month: int | None = None):
    """(head, months) for a calendar year to date, or (None, 0).

    `through_month` caps the window so a prior year can be compared on the same
    months -- a full prior year against eight months of this one is the part-
    year error wearing a different hat.
    """
    s = series(df, flow, commodity, country)
    s = s[s["year"] == year]
    if through_month is not None:
        s = s[s["month"] <= through_month]
    if s.empty:
        return None, 0
    return int(s["head"].sum()), int(s["month"].nunique())


def latest_month(df: pd.DataFrame, country: str = CANADA):
    """(year, month) of the newest month published, or None.

    Taken off `Cattle, total` imports, which is the series that exists for
    every year -- reading it off the feeder class would report the file as
    ending wherever the class split ends.
    """
    s = series(df, IMPORTS, TOTAL, country)
    if s.empty:
        return None
    r = s.iloc[-1]
    return int(r["year"]), int(r["month"])


def class_floor(df: pd.DataFrame, country: str = CANADA):
    """The first year the import class split exists, or None.

    `Cattle, total` runs from 1989 and the classes from 2012, so a chart that
    opens on the full history and overlays a feeder line makes feeders look
    like they collapsed to zero for twenty-three years. The page prints this
    rather than letting the axis imply it -- the same reasoning as `FIRST_YEAR`
    on the Saturday Slaughter view.
    """
    s = series(df, IMPORTS, FEEDER, country)
    return int(s["year"].min()) if not s.empty else None


def export_classes(df: pd.DataFrame, country: str = CANADA) -> list:
    """Every commodity class present on the EXPORT side.

    Exists so the page can assert the asymmetry from the data rather than
    asserting it from this docstring: if ERS ever adds a feeder export class,
    this returns it and the caption stops being true. Measured 2026-10-12 it is
    ['Cattle, total'] alone.
    """
    sub = df[(df["flow"] == EXPORTS) & (df["country"] == country)]
    return sorted(sub["commodity"].unique().tolist())


def share_of_us_imports(df: pd.DataFrame, year: int,
                        through_month: int | None = None):
    """Canada's share of all US cattle imports, as a percentage, or None.

    Against `World total`, which is USDA's own row -- not a sum over the 119
    partner countries, which would double it.
    """
    ca, _ = ytd(df, IMPORTS, TOTAL, year, CANADA, through_month)
    world, _ = ytd(df, IMPORTS, TOTAL, year, WORLD, through_month)
    if not ca or not world:
        return None
    return ca / world * 100.0
