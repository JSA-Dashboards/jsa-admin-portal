"""
US beef & veal trade -- monthly actuals, from USDA ERS.

    https://www.ers.usda.gov/data-products/livestock-and-meat-international-trade-data

Exports and imports, by partner country, monthly back to 1989, on a CARCASS
WEIGHT basis in 1,000 pounds. One CSV, no API key, no new host.

WHY THIS SOURCE AND NOT THE OBVIOUS TWO.

  * FAS ESR is what JSA's own Export Sales dashboard already reads, and it is
    excellent for what it is -- weekly, by destination, with outstanding sales
    -- but it is EXPORTS ONLY, it reports sales rather than customs-cleared
    trade, and it is product weight in metric tons. None of that can be
    compared with a WASDE forecast.
  * Census (the API the Mexican Feeder Imports ingest uses) is the underlying
    customs data, but it is product weight by HS code. Turning 0201/0202/0206
    into a carcass-weight equivalent means applying conversion factors, which
    is exactly the modelling step ERS has already done and publishes.

AND THE REASON THAT MATTERS: ERS IS THE SERIES WASDE FORECASTS, EXACTLY.
For 2025 this file's world totals are Exports 2,579.1 and Imports 5,388.0
million lb; the September 2026 WASDE prints 2,579 and 5,388. Verified on
2026-10-07 and pinned by tests/test_beef_trade.py. That identity is the only
reason an actual-versus-forecast panel on this page means anything -- it is
not a plausible comparison of two similar numbers, it is the same number.
**If it ever stops holding, the comparison is invalid**, not merely noisy, and
`basis_agrees()` exists so the page can say so instead of drawing it anyway.

"WORLD TOTAL" IS A ROW IN THE FILE, NOT SOMETHING TO DERIVE. Summing every
GEOGRAPHY_DESC double-counts the total by exactly 100%, which produces a
monthly export figure around 390 million lb against a true 195 -- a number
that is wrong by a factor of two and still looks like a perfectly reasonable
beef trade figure. The countries sum to the published total with ZERO error
across all 452 month/flow pairs, so `reconciles()` checks the identity rather
than trusting either side, and every helper here filters the row explicitly.

THE SERIES IS RESTATED. The file is republished whole each month and Census
revises, so a month already on this page can move. Nothing here caches it
longer than the page does, and the page prints the latest month it actually
received rather than inferring one from the calendar.
"""
from __future__ import annotations

import io
import re
from datetime import date

import pandas as pd
import requests

# BUMP THIS whenever load()/monthly()/pace() change the SHAPE of what they
# return -- `st.cache_data` never notices that this module changed. See
# `leverage.SCHEMA` in CLAUDE.md.
SCHEMA = 1

ERS_PAGE = "https://www.ers.usda.gov/data-products/livestock-and-meat-international-trade-data"

# The Drupal media id is stable in practice, and the ?v= cache-buster on the
# page is NOT required -- the bare path serves the current file. It is still
# only an id, so `_discover` re-reads the index page by filename if it 404s
# rather than letting the page go dark on a CMS renumber.
ERS_BEEF_MONTHLY = ("https://www.ers.usda.gov/media/29544/"
                    "beef-and-veal-monthly-us-trade-carcass-weight-1000-pounds.csv")
_DISCOVER_PAT = re.compile(
    r'href="(/media/\d+/beef-and-veal-monthly-us-trade-carcass-weight-1000-pounds\.csv[^"]*)"',
    re.I)

WORLD = "World total"
FLOWS = ("Exports", "Imports")

# ERS publishes 1,000 lb; WASDE prints million lb. Everything this module
# RETURNS is million lb, so the two are never side by side in different
# units -- the conversion happens once, here, at the edge.
THOUSAND_LB_TO_MILLION_LB = 1.0 / 1000.0

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "JSA-Livestock-Portal/1.0 (+https://www.jpsi.com)"
    return s


def _discover(sess: requests.Session) -> str | None:
    try:
        r = sess.get(ERS_PAGE, timeout=45)
        r.raise_for_status()
    except requests.RequestException:
        return None
    m = _DISCOVER_PAT.search(r.text)
    return ("https://www.ers.usda.gov" + m.group(1)) if m else None


def fetch(sess: requests.Session | None = None) -> pd.DataFrame:
    """
    The raw ERS table, tidied: one row per flow/country/year/month.

    Columns: flow, country, year, month, mil_lb.
    """
    sess = sess or _session()
    text = None
    try:
        r = sess.get(ERS_BEEF_MONTHLY, timeout=120)
        r.raise_for_status()
        text = r.content
    except requests.RequestException:
        alt = _discover(sess)
        if not alt:
            raise
        r = sess.get(alt, timeout=120)
        r.raise_for_status()
        text = r.content

    df = pd.read_csv(io.BytesIO(text), encoding="utf-8-sig")
    need = {"TRADE_FLOW", "GEOGRAPHY_DESC", "YEAR_ID", "TIMEPERIOD_ID", "AMOUNT"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError("ERS CSV is missing %s" % sorted(missing))

    out = pd.DataFrame({
        "flow": df["TRADE_FLOW"].astype(str).str.strip(),
        "country": df["GEOGRAPHY_DESC"].astype(str).str.strip(),
        "year": pd.to_numeric(df["YEAR_ID"], errors="coerce"),
        "month": pd.to_numeric(df["TIMEPERIOD_ID"], errors="coerce"),
        "mil_lb": pd.to_numeric(df["AMOUNT"], errors="coerce") * THOUSAND_LB_TO_MILLION_LB,
    }).dropna(subset=["year", "month", "mil_lb"])
    out["year"] = out["year"].astype(int)
    out["month"] = out["month"].astype(int)
    return out[out["flow"].isin(FLOWS)].reset_index(drop=True)


# -- the audit ---------------------------------------------------------------

def reconciles(df: pd.DataFrame, tolerance: float = 0.5) -> dict:
    """
    {ok, checked, worst, worst_at} -- do the countries sum to USDA's own total?

    The free audit on this file, and the one that catches the mistake that
    would otherwise ship silently: `World total` is a ROW, so a groupby that
    forgets to exclude it doubles every figure. Doubling beef exports gives
    ~390 million lb a month, which is wrong and entirely plausible-looking.

    Measured zero error across 452 month/flow pairs on 2026-10-07. The default
    tolerance is half a million pounds, which is slack against float summation
    over 220 countries and nowhere near enough to admit a missing partner.
    """
    world = df[df["country"] == WORLD]
    parts = df[df["country"] != WORLD]
    w = world.groupby(["flow", "year", "month"])["mil_lb"].sum()
    p = parts.groupby(["flow", "year", "month"])["mil_lb"].sum()
    joined = pd.concat([w.rename("world"), p.rename("parts")], axis=1).dropna()
    if joined.empty:
        return {"ok": False, "checked": 0, "worst": None, "worst_at": None}
    diff = (joined["parts"] - joined["world"]).abs()
    i = diff.idxmax()
    return {"ok": bool(diff.max() <= tolerance), "checked": int(len(joined)),
            "worst": float(diff.max()), "worst_at": i}


# -- shaping -----------------------------------------------------------------

def monthly(df: pd.DataFrame, flow: str) -> pd.DataFrame:
    """
    USDA's published world total for one flow: year, month, mil_lb, date.

    Reads the `World total` ROW rather than summing the countries. They agree
    -- `reconciles` proves it -- but when they ever do not, USDA's own figure
    is the published one and the sum is ours.
    """
    sub = df[(df["flow"] == flow) & (df["country"] == WORLD)]
    out = (sub.groupby(["year", "month"], as_index=False)["mil_lb"].sum()
              .sort_values(["year", "month"]).reset_index(drop=True))
    out["date"] = pd.to_datetime(
        dict(year=out["year"], month=out["month"], day=1))
    return out


def latest_month(df: pd.DataFrame, flow: str):
    """(year, month) of the newest month on file, or None."""
    m = monthly(df, flow)
    if m.empty:
        return None
    row = m.iloc[-1]
    return int(row["year"]), int(row["month"])


def ytd(df: pd.DataFrame, flow: str, year: int, through: int) -> float:
    """Million lb, January through `through` inclusive."""
    m = monthly(df, flow)
    sel = m[(m["year"] == year) & (m["month"] <= through)]
    return float(sel["mil_lb"].sum())


def seasonal_shape(df: pd.DataFrame, flow: str, year: int,
                   years_back: int = 5) -> pd.Series:
    """
    Each month's share of the calendar year, averaged over the `years_back`
    COMPLETE years before `year`.

    Only complete years, because a part year's shares would sum to one over
    the months it happens to have and quietly re-weight the rest.
    """
    m = monthly(df, flow)
    full = (m.groupby("year")["month"].count() == 12)
    done = [y for y in full[full].index if y < year][-years_back:]
    if not done:
        return pd.Series(dtype=float)
    hist = m[m["year"].isin(done)]
    tot = hist.groupby("year")["mil_lb"].transform("sum")
    hist = hist.assign(share=hist["mil_lb"] / tot)
    return hist.groupby("month")["share"].mean()


def pace(df: pd.DataFrame, flow: str, year: int, through: int,
         forecast: float | None) -> dict:
    """
    Is the year tracking USDA's forecast?

    Returns million lb throughout:
        ytd                 actual, Jan..through
        ytd_prior           the same months a year earlier
        yoy_pct             change between those two
        run_rate            average of the last three months on file
        required            (forecast - ytd) / months remaining
        gap_pct             required against run_rate, as a percentage
        projection          the seasonal full-year projection (below)
        implied_vs_forecast projection - forecast
        prior_year_total    last COMPLETE calendar year, for the comparison
                            below; None until that year has all 12 months
        projection_yoy_pct  the projection against that full prior year --
                            the figure that stands beside USDA's own
                            forecast-versus-last-year percentage

    TWO DIFFERENT QUESTIONS, AND THE PAGE SHOWS BOTH. "What must the rest of
    the year average to hit USDA's number" is arithmetic. "What will the year
    come to if it carries on behaving like a normal year" is a projection, and
    it has to be seasonal: beef imports run heavy in the first quarter and
    exports are flatter, so YTD x 12/n is wrong in a direction that changes
    with the month you ask in.

    The projection scales the five-year average seasonal shape to this year's
    realised YTD -- ytd / (share of the year those months normally carry) --
    which needs no assumption about the remaining months beyond their usual
    weight. With no usable history it returns None rather than falling back to
    the naive annualisation, because a bad projection labelled like a good one
    is worse than a missing one.
    """
    out = {"ytd": None, "ytd_prior": None, "yoy_pct": None, "run_rate": None,
           "required": None, "gap_pct": None, "projection": None,
           "implied_vs_forecast": None, "prior_year_total": None,
           "projection_yoy_pct": None, "months_left": max(0, 12 - through)}

    m = monthly(df, flow)
    if m.empty or through < 1:
        return out

    out["ytd"] = ytd(df, flow, year, through)
    prior = ytd(df, flow, year - 1, through)
    out["ytd_prior"] = prior if prior else None
    if prior:
        out["yoy_pct"] = (out["ytd"] / prior - 1.0) * 100.0

    recent = m[(m["year"] == year) & (m["month"] <= through)].tail(3)
    if not recent.empty:
        out["run_rate"] = float(recent["mil_lb"].mean())

    shape = seasonal_shape(df, flow, year)
    if not shape.empty:
        covered = float(shape[shape.index <= through].sum())
        if covered > 0:
            out["projection"] = out["ytd"] / covered

    # THE FULL PRIOR YEAR, not the year-to-date months. `yoy_pct` above
    # compares like periods (Jan-Aug against Jan-Aug); this compares the
    # projected FULL year against the completed one, which is the figure that
    # sits beside USDA's own forecast-versus-last-year percentage. Mixing the
    # two would put a part-year comparison next to a full-year one under
    # labels that look alike.
    prior_full = m[m["year"] == year - 1]
    if len(prior_full) == 12:
        out["prior_year_total"] = float(prior_full["mil_lb"].sum())
        if out["projection"] is not None and out["prior_year_total"]:
            out["projection_yoy_pct"] = (
                out["projection"] / out["prior_year_total"] - 1.0) * 100.0

    if forecast is not None:
        left = out["months_left"]
        if left > 0:
            out["required"] = (forecast - out["ytd"]) / left
            if out["run_rate"]:
                out["gap_pct"] = (out["required"] / out["run_rate"] - 1.0) * 100.0
        if out["projection"] is not None:
            out["implied_vs_forecast"] = out["projection"] - forecast
    return out


def countries(df: pd.DataFrame, flow: str, year: int, through: int,
              top: int = 12) -> pd.DataFrame:
    """
    YTD by partner against the same months last year: country, ytd, prior,
    change, pct, share.

    Excludes the `World total` row -- see the module docstring -- and takes
    the share against USDA's published total so the column means "share of
    the trade", not "share of the countries that happen to be listed".
    """
    sub = df[(df["flow"] == flow) & (df["country"] != WORLD)
             & (df["month"] <= through) & (df["year"].isin([year, year - 1]))]
    if sub.empty:
        return pd.DataFrame()
    piv = (sub.groupby(["country", "year"])["mil_lb"].sum()
              .unstack("year").fillna(0.0))
    if year not in piv.columns:
        return pd.DataFrame()
    out = pd.DataFrame({
        "country": piv.index,
        "ytd": piv[year].values,
        "prior": piv[year - 1].values if (year - 1) in piv.columns else 0.0,
    })
    out["change"] = out["ytd"] - out["prior"]
    out["pct"] = out.apply(
        lambda r: (r["ytd"] / r["prior"] - 1.0) * 100.0 if r["prior"] else None,
        axis=1)
    total = ytd(df, flow, year, through)
    out["share"] = (out["ytd"] / total * 100.0) if total else None
    return out.sort_values("ytd", ascending=False).head(top).reset_index(drop=True)


def net_trade(df: pd.DataFrame) -> pd.DataFrame:
    """
    Imports less exports, monthly: year, month, date, exports, imports, net.

    Positive net means the US is a net importer of beef, which it now firmly
    is -- the sign convention that makes the chart read the way the market
    talks about it.
    """
    e = monthly(df, "Exports").rename(columns={"mil_lb": "exports"})
    i = monthly(df, "Imports").rename(columns={"mil_lb": "imports"})
    out = e.merge(i[["year", "month", "imports"]], on=["year", "month"],
                  how="inner")
    out["net"] = out["imports"] - out["exports"]
    return out


def net_run(df: pd.DataFrame) -> dict:
    """
    The current unbroken run of net-IMPORT calendar years:
    {start, years, first, latest, flipped}.

    COMPUTED, NOT ASSERTED. The caption under the net-trade chart said "the US
    crossed over durably in 2024" until the series was actually checked, and
    that is wrong twice: the run begins in **2023**, and the US has crossed
    back and forth repeatedly -- net importer 2014-17, exporter 2018,
    importer 2019-20, **exporter again in 2021 and 2022**. What is new is the
    SCALE, not the sign: 687 million lb net in 2023 against 2,809 in 2025.

    A caption that hard-codes a figure above it will disagree with it, which
    this repo has paid for before. `flipped` is how many times the sign has
    changed over the complete years on file, so the page can say "repeatedly"
    with a number behind it.
    """
    nt = net_trade(df)
    complete = nt.groupby("year")["month"].count()
    years = [int(y) for y in complete[complete == 12].index]
    ann = nt[nt["year"].isin(years)].groupby("year")["net"].sum()
    if ann.empty:
        return {"start": None, "years": 0, "first": None, "latest": None,
                "flipped": 0}

    signs = (ann > 0).tolist()
    flipped = sum(1 for a, b in zip(signs, signs[1:]) if a != b)

    run = 0
    for positive in reversed(signs):
        if not positive:
            break
        run += 1
    if run == 0:
        return {"start": None, "years": 0, "first": None,
                "latest": float(ann.iloc[-1]), "flipped": flipped}
    start = int(ann.index[-run])
    return {"start": start, "years": run, "first": float(ann.iloc[-run]),
            "latest": float(ann.iloc[-1]), "flipped": flipped}


def landmarks(df: pd.DataFrame, flow: str) -> dict:
    """
    The record low, record high and biggest one-year move for a flow:
    {low, high, biggest_fall, biggest_rise}, each {year, value, pct}.

    COMPLETE YEARS ONLY, and that is not a detail. The part year in progress
    is eight months of trade, so including it hands back "biggest fall: 2026,
    -19%" -- a calendar artefact reported as a market event, in a caption
    whose whole job is to explain the chart.

    COMPUTED RATHER THAN WRITTEN DOWN, so the caption cannot drift from the
    bars above it. The record import year changed twice in three years; a
    hard-coded "the 2025 record" would have been wrong by the following
    spring, which is the failure `scorecard.py` and the hard-coded-caption
    commit in this repo's history both exist to prevent.

    Returns {} where there is not enough history to rank anything.
    """
    m = monthly(df, flow)
    if m.empty:
        return {}
    complete = m.groupby("year")["month"].count()
    years = [int(y) for y in complete[complete == 12].index]
    annual = m[m["year"].isin(years)].groupby("year")["mil_lb"].sum()
    if len(annual) < 3:
        return {}
    change = annual.pct_change() * 100.0

    def _at(idx, series, pct_series=None):
        if idx is None or idx not in series.index:
            return None
        out = {"year": int(idx), "value": float(series[idx])}
        if pct_series is not None and idx in pct_series.index:
            v = pct_series[idx]
            out["pct"] = None if pd.isna(v) else float(v)
        return out

    # A "biggest fall" must actually be a fall. Over a window where every
    # year rose, idxmin() returns the smallest RISE and the caption prints
    # "biggest fall: +0.2%" -- a contradiction in its own sentence. Seen on
    # the 2019-2025 test fixture before it could reach a page.
    fall = _at(change.idxmin(), annual, change)
    if fall and not (fall.get("pct") or 0) < 0:
        fall = None
    rise = _at(change.idxmax(), annual, change)
    if rise and not (rise.get("pct") or 0) > 0:
        rise = None

    return {
        "low": _at(annual.idxmin(), annual),
        "high": _at(annual.idxmax(), annual),
        "biggest_fall": fall,
        "biggest_rise": rise,
        "first_year": int(annual.index.min()),
        "last_year": int(annual.index.max()),
    }


def recovered_year(df: pd.DataFrame, flow: str, after: int):
    """
    The first year after `after` that got back to its level -- how long a
    collapse actually lasted, which a bar chart shows and does not say.

    US beef exports fell 82% in 2004 and did not regain their 2003 total
    until 2011. Seven years is the fact worth printing; "there is a dip" is
    what the chart already conveys on its own.
    """
    m = monthly(df, flow)
    complete = m.groupby("year")["month"].count()
    years = [int(y) for y in complete[complete == 12].index]
    annual = m[m["year"].isin(years)].groupby("year")["mil_lb"].sum()
    if after not in annual.index:
        return None
    later = annual[(annual.index > after) & (annual >= annual[after])]
    return int(later.index.min()) if not later.empty else None


def basis_agrees(df: pd.DataFrame, year: int, wasde_imports: float | None,
                 wasde_exports: float | None, tolerance: float = 2.0) -> dict:
    """
    Does this file's completed year reproduce WASDE's actual for that year?

    THE CHECK THAT LICENCES THE WHOLE PAGE. ERS and WASDE are supposed to be
    the same series on the same basis, and on 2026-10-07 they were identical
    to the million pound for 2025 (2,579.1 / 2,579 and 5,388.0 / 5,388). The
    actual-versus-forecast panel only means something while that holds, so it
    is checked against live data rather than asserted in a comment.

    `tolerance` is 2 million lb -- WASDE prints whole million pounds and ERS
    carries decimals, so they cannot agree exactly, and anything larger than a
    rounding step means the two have diverged.
    """
    res = {"ok": None, "year": year, "ers_imports": None, "ers_exports": None,
           "wasde_imports": wasde_imports, "wasde_exports": wasde_exports}
    m_i, m_e = monthly(df, "Imports"), monthly(df, "Exports")
    full_i = m_i[m_i["year"] == year]
    full_e = m_e[m_e["year"] == year]
    if len(full_i) != 12 or len(full_e) != 12:
        return res                      # not a complete year; nothing to check
    res["ers_imports"] = float(full_i["mil_lb"].sum())
    res["ers_exports"] = float(full_e["mil_lb"].sum())
    checks = []
    if wasde_imports is not None:
        checks.append(abs(res["ers_imports"] - wasde_imports) <= tolerance)
    if wasde_exports is not None:
        checks.append(abs(res["ers_exports"] - wasde_exports) <= tolerance)
    res["ok"] = all(checks) if checks else None
    return res


def month_name(m: int) -> str:
    return MONTHS[m - 1] if 1 <= m <= 12 else str(m)
