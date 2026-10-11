"""
How much of the kill packers have already bought, and how much they still need.

Packer leverage is not a mood — it is a published ratio. Every week AMS breaks
the slaughter it reports down by HOW each animal was bought, and the share that
arrived on a formula or a forward contract is supply the packer never has to
bid for. When that share is high the cash market is a rounding error on their
week and they can stand back; when it falls they have to come and get cattle.

    LM_CT153 §B  slaughter, split formula / forward / negotiated / neg grid
    LM_CT153 §A  packer-owned slaughter — cattle they fed themselves
    LM_CT153 §C  forward contract purchases, weekly and cumulative
    LM_CT142     committed and delivered head, the forward book and its drain

TWO CLOCKS, AND MIXING THEM IS THE TRAP THIS MODULE EXISTS TO AVOID.
LM_CT154's row dated 9/28 is 47,138 head PURCHASED in the week just ended.
LM_CT153's row dated 9/28 is 62,190 head SLAUGHTERED in that week, bought
whenever they were bought — often weeks earlier. They are different
populations on different timelines and their ratio wanders: measured across
2026-08-24..09-28 it ran 0.83, 1.04, 1.15, 1.14, 1.15, 1.32. Dividing one by
the other produces a number that looks like a share, moves like a share, and
means nothing.

So **every share here is computed inside LM_CT153 alone** — numerator and
denominator from the same row of the same report. LM_CT154 is the purchase
side and belongs in the page's other tabs, which is where it stays.

NEGOTIATED GRID IS REPORTED SEPARATELY AND IS NOT FOLDED IN. Its base price is
negotiated in the week, so for "did the packer have to transact this week" it
belongs with negotiated cash; for "what share of the kill discovered a cash
price" the convention is negotiated cash alone. Both readings are defensible
and they differ a lot — 19.7% against 29.1% for the week ending 2026-09-28 —
so the page prints the strict one as the headline, shows grid as its own band
in the mix, and never silently picks.
"""
from __future__ import annotations

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

# Bump whenever load() changes the SHAPE of what it returns — a new key, a
# renamed column, a different index. The page passes this into its cached
# fetch, so the cache key moves with it.
#
# WITHOUT IT A SHAPE CHANGE SERVES THE OLD SHAPE SILENTLY. st.cache_data keys
# on the decorated function's own code and arguments, never on the modules it
# calls (CLAUDE.md records this costing two debugging sessions). fetch_leverage's
# body is one line that has not changed, so adding the `schedule` key here left
# the cache handing back a dict that lacked it — and the page rendered a tile
# reading "—" with nothing raising anywhere.
SCHEMA = 2

LMR_BASE = "https://mpr.datamart.ams.usda.gov/services/v1.1/reports"

CT142_ID = 2472   # Weekly Direct Slaughter Cattle - Committed and Delivered
CT153_ID = 2480   # National Weekly - Prior Week Slaughter and Contract Purchases

# Section names are a PATH SEGMENT, not a query parameter, and the bare slug
# answers 200 with a near-empty row rather than an error — the same shape
# CLAUDE.md documents for MARS 3208 and the direct/video slugs. The catalog
# endpoint lists them under `sectionNames`, which is the cheap way to check a
# name rather than guessing at it.
SEC_MIX = "B. Prior Week Formula & Contract Slaughter"
SEC_OWNED = "A. Packer Owned Slaughter"
SEC_FORWARD = "C. Forward Contract Purchases"
SEC_SCHEDULE = "C. Forward Contract Purchases Breakdown"

# The four ways a reported animal was bought. Domestic and imported are
# separate columns throughout and are summed: an imported formula steer is
# still supply the packer did not bid for this week.
MIX = {
    "formula": ("B_dom_formula_head_count", "B_imp_formula_head_count"),
    "forward": ("B_dom_forward_head_count", "B_imp_forward_head_count"),
    "negotiated": ("B_dom_neg_head_count", "B_imp_neg_head_count"),
    "neg_grid": ("B_dom_neg_grid_head_count", "B_imp_neg_grid_head_count"),
}
MIX_LABEL = {"formula": "Formula", "forward": "Forward contract",
             "negotiated": "Negotiated cash", "neg_grid": "Negotiated grid"}


# The breakdown table's row layout, verified against ams_2480.pdf 2026-10-05.
# SIXTEEN delivery months, each with six basis-month detail rows, then sixteen
# "Total <Mon> Deliveries" rows in the same order, then sixteen
# "Last Yr <Mon> Deliveries" rows in that same order again.
#
# THE MONTH LABELS REPEAT AND CANNOT BE KEYED ON. The window spans two years,
# so "Total Sep Deliveries" appears twice — 86,305 for Sep '26 and 9,453 for
# Sep '27 — and a dict keyed on the label silently keeps whichever came last,
# which is the far month. Only the DETAIL rows carry a year ("Sep '26/Oct"),
# so the delivery months are read from those in order and the summary rows are
# zipped onto that sequence by position.
_DETAIL = re.compile(r"^(\w{3}) '(\d{2})/(\w{3})$")
_TOTAL = re.compile(r"^Total (\w{3}) Deliveries$")
_LASTYR = re.compile(r"^Last Yr (\w{3}) Deliveries$")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")


def _rows(payload) -> list:
    """AMS answers 200 with a bare string when a window holds no report."""
    if isinstance(payload, dict):
        r = payload.get("results")
        return r if isinstance(r, list) else []
    if isinstance(payload, list):
        out = []
        for sec in payload:
            if isinstance(sec, dict) and isinstance(sec.get("results"), list):
                out.extend(sec["results"])
        return out
    return []


def fetch(session_factory, jobs: list, timeout: int = 180) -> dict:
    """Run the independent section GETs concurrently; a failure yields []."""
    def run(job):
        key, slug, section = job
        url = f"{LMR_BASE}/{slug}"
        if section:
            url += "/" + urllib.parse.quote(section)
        try:
            resp = session_factory().get(url, timeout=timeout)
            if resp.status_code in (204, 404):
                return key, []
            resp.raise_for_status()
            return key, _rows(resp.json())
        except Exception:
            return key, []

    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as ex:
        return dict(ex.map(run, jobs))


def load(session_factory) -> dict:
    """
    Every series this tab needs, as {name: DataFrame}, keyed on week.

    Full history on each — about 3 s and 6 MB across the four concurrently,
    which is the same order as the weekly price and volume fetches this page
    already makes on every load. The hidden-tab rule therefore costs roughly
    what the existing tabs do rather than multiplying it.
    """
    got = fetch(session_factory, [
        ("mix", CT153_ID, SEC_MIX),
        ("owned", CT153_ID, SEC_OWNED),
        ("forward", CT153_ID, SEC_FORWARD),
        ("committed", CT142_ID, None),
        ("schedule", CT153_ID, SEC_SCHEDULE),
    ])
    return {
        "mix": _mix_frame(got.get("mix", [])),
        "owned": _owned_frame(got.get("owned", [])),
        "forward": _forward_frame(got.get("forward", [])),
        "committed": _committed_frame(got.get("committed", [])),
        "schedule": _schedule_frame(got.get("schedule", [])),
    }


def _mix_frame(rows: list) -> pd.DataFrame:
    """One row per week: head by purchase type, the total, and the shares."""
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["week"] = pd.to_datetime(d["report_date"], format="%m/%d/%Y", errors="coerce")
    d = d.dropna(subset=["week"]).drop_duplicates("week", keep="last").sort_values("week")
    out = pd.DataFrame({"week": d["week"].values})
    for name, (dom, imp) in MIX.items():
        dv = _num(d[dom]) if dom in d else 0
        iv = _num(d[imp]) if imp in d else 0
        out[name] = (dv.fillna(0).values if hasattr(dv, "fillna") else dv) + \
                    (iv.fillna(0).values if hasattr(iv, "fillna") else iv)

    # USDA publishes its own total. Use it rather than the sum of the four:
    # if a fifth category is ever added, a derived total would quietly keep
    # the shares adding to 100% while describing less than the whole kill.
    out["total"] = _num(d["B_total_head_count"]).values if "B_total_head_count" in d \
        else out[list(MIX)].sum(axis=1)
    for name in MIX:
        out[f"{name}_pct"] = out[name] / out["total"]
    # Committed = everything the packer did not have to transact for this week.
    out["committed_pct"] = 1 - out["negotiated_pct"] - out["neg_grid_pct"]
    # ...and the looser reading, which counts a negotiated grid base as a
    # weekly transaction. Shown, never substituted for the headline.
    out["must_buy_pct"] = out["negotiated_pct"] + out["neg_grid_pct"]
    return out.dropna(subset=["total"])


def _owned_frame(rows: list) -> pd.DataFrame:
    """Packer-owned slaughter — the purest captive supply, domestic + imported."""
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["week"] = pd.to_datetime(d["report_date"], format="%m/%d/%Y", errors="coerce")
    d["head"] = _num(d["head_count"])
    d = d.dropna(subset=["week"])
    g = d.groupby("week", as_index=False)["head"].sum(min_count=1)
    return g.rename(columns={"head": "packer_owned"}).sort_values("week")


def _forward_frame(rows: list) -> pd.DataFrame:
    """Forward contract purchases: the week's buying and the standing book."""
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["week"] = pd.to_datetime(d["report_date"], format="%m/%d/%Y", errors="coerce")
    d = d.dropna(subset=["week"]).drop_duplicates("week", keep="last").sort_values("week")
    return pd.DataFrame({
        "week": d["week"].values,
        "fwd_week": _num(d["C_weekly_head_count"]).values,
        "fwd_book": _num(d["C_cumulative_head_count"]).values,
    })


def _committed_frame(rows: list) -> pd.DataFrame:
    """
    LM_CT142's committed book and what actually shipped against it.

    Two rows per week — `purchasing_basis` is Committed or Delivered — so this
    pivots rather than filters.

    BOTH COLUMNS ARE WEEKLY FLOWS AND NEITHER IS AN INVENTORY. `Committed` is
    head committed DURING that week, not head standing committed; the daily
    sibling LM_CT106 settles it, where `acc_current_volume` accumulates within
    the week, resets each Monday, and ends the week on exactly this figure
    (316,910 for w/e 2026-09-28, 409,230 for 10-05).
    
    This shipped once as "weeks of coverage" — committed over a four-week
    delivery pace — which read as weeks of supply and is nothing of the kind.
    The tell was there and was misread as a virtue: the ratio sits at a median
    1.03 with a standard deviation of 0.08 across sixteen years, which is what
    two flows in steady state look like, not a stock over a flow. What it
    actually measures is whether the book grew or drained that week, so that is
    what it is now called. The standing inventory is in _schedule_frame.
    """
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["week"] = pd.to_datetime(d["report_date_end"], format="%m/%d/%Y", errors="coerce")
    d["vol"] = _num(d["current_volume"])
    d = d.dropna(subset=["week"])
    p = (d.pivot_table(index="week", columns="purchasing_basis", values="vol",
                       aggfunc="last").reset_index())
    p.columns.name = None
    p = p.rename(columns={"Committed": "committed", "Delivered": "delivered"})
    for c in ("committed", "delivered"):
        if c not in p:
            p[c] = float("nan")
    # Delivery pace over four weeks, not one: a holiday week halves the
    # denominator and would print a coverage spike that is the calendar.
    # Four weeks, not one: a holiday week halves the denominator and would
    # swing this hard on nothing but the calendar.
    pace = p["delivered"].rolling(4, min_periods=2).mean()
    p["signings_vs_pace"] = p["committed"] / pace
    return p.sort_values("week")


_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def _schedule_frame(rows: list) -> pd.DataFrame:
    """
    The forward book broken out by the month the cattle are due to be
    delivered, against the same month a year earlier.

    THIS IS THE STANDING INVENTORY, not a weekly flow. USDA's own heading on
    ams_2480.pdf reads "Cumulative Total for Listed Months: 714,623" — cattle
    bought and not yet delivered, summed across every month still listed. The
    book rises as contracts are signed and steps down as a delivery month
    completes and drops off the window.

    Parsed by POSITION, never by label — see the _DETAIL / _TOTAL / _LASTYR
    note above for why the repeated month names cannot be keyed on.

    The sixteen monthly totals sum to the published book total exactly
    (714,623 on 2026-09-28), which `reconciles()` checks and a test pins. That
    identity is the whole audit: if the row layout ever shifts, the sum stops
    matching rather than quietly mis-attributing a month.
    """
    if not rows:
        return pd.DataFrame()
    latest_date = None
    for r in rows:
        d = pd.to_datetime(r.get("report_date"), format="%m/%d/%Y", errors="coerce")
        if d is not pd.NaT and (latest_date is None or d > latest_date):
            latest_date = d
    if latest_date is None:
        return pd.DataFrame()
    cur = [r for r in rows
           if pd.to_datetime(r.get("report_date"), format="%m/%d/%Y",
                             errors="coerce") == latest_date]

    order, seen = [], set()
    totals, lastyr = [], []
    for r in cur:
        t = (r.get("left_title") or "").strip()
        m = _DETAIL.match(t)
        if m:
            key = (m.group(1), m.group(2))
            if key not in seen:
                seen.add(key)
                order.append(key)
            continue
        if _TOTAL.match(t):
            totals.append((_TOTAL.match(t).group(1), r))
        elif _LASTYR.match(t):
            lastyr.append((_LASTYR.match(t).group(1), r))

    if not order or len(totals) != len(order):
        return pd.DataFrame()

    out = []
    for i, (mon, yy) in enumerate(order):
        tmon, trow = totals[i]
        # The summary row's month must line up with the detail block it is
        # being attached to, or the zip has slipped and every figure after it
        # belongs to the wrong month.
        if tmon != mon:
            return pd.DataFrame()
        lrow = lastyr[i][1] if i < len(lastyr) and lastyr[i][0] == mon else None
        out.append({
            "delivery": pd.Timestamp(year=2000 + int(yy), month=_MONTHS[mon], day=1),
            "month": mon, "year": 2000 + int(yy),
            "committed": _num(pd.Series([trow.get("cumulative_total_for_month")])).iloc[0],
            "new_last_week": _num(pd.Series([trow.get("new_last_week")])).iloc[0],
            "last_year": (_num(pd.Series([lrow.get("cumulative_total_for_month")])).iloc[0]
                          if lrow else float("nan")),
            "report_date": latest_date,
        })
    d = pd.DataFrame(out)
    d["vs_last_year"] = d["committed"] / d["last_year"] - 1
    return d


def reconciles(schedule: pd.DataFrame, book_total: float, tol: int = 0) -> bool:
    """Do the monthly totals add back to the book USDA published?"""
    if schedule.empty or book_total != book_total:
        return False
    return abs(float(schedule["committed"].sum()) - float(book_total)) <= tol


def near_months(schedule: pd.DataFrame, n: int = 3) -> dict:
    """
    The next `n` delivery months against the same months a year ago.

    The near months are the ones that bear on this week's bidding: cattle
    contracted for delivery next spring do nothing for a packer who needs a
    kill filled on Thursday.
    """
    if schedule.empty:
        return {}
    d = schedule.head(n)
    cur, prior = float(d["committed"].sum()), float(d["last_year"].sum())
    if not prior or prior != prior:
        return {}
    return {"n": int(len(d)), "committed": cur, "last_year": prior,
            "change": cur / prior - 1,
            "from": d.iloc[0]["month"], "to": d.iloc[-1]["month"]}


def latest(frames: dict) -> dict:
    """The newest complete reading of each series, for the headline tiles."""
    out = {}
    mix = frames.get("mix")
    if mix is not None and not mix.empty:
        r = mix.iloc[-1]
        prior = mix.iloc[-2] if len(mix) > 1 else None
        yr = mix[mix["week"] <= r["week"] - pd.Timedelta(weeks=52)]
        out["mix"] = r
        out["mix_prior"] = prior
        out["mix_year"] = yr.iloc[-1] if not yr.empty else None
    sch = frames.get("schedule")
    if sch is not None and not sch.empty:
        out["schedule"] = sch
    for key in ("owned", "forward", "committed"):
        f = frames.get(key)
        if f is not None and not f.empty:
            out[key] = f.iloc[-1]
            out[f"{key}_prior"] = f.iloc[-2] if len(f) > 1 else None
    return out


# Weeks averaged for the cash-need figure. FOUR, because the quantity is noisy
# and the alternative to averaging is quoting last week as though it were next
# week. Measured over the last 56 weeks (2026-10-05), a four-week mean lands
# within a median 8.8% of the following week's negotiated head, 21.8% at the
# 90th percentile; including negotiated grid it is tighter at 7.3% / 18.9%,
# because grid and cash partly offset each other week to week.
NEED_WEEKS = 4


def cash_need(mix: pd.DataFrame, weeks: int = NEED_WEEKS) -> dict:
    """
    How many head packers have to transact for in a week, at the recent rate.

    THIS IS A RUN RATE, NOT A FORECAST, and the page says so. There is no
    published figure for "cattle still to buy this week" — the week's purchases
    and the week's slaughter are different populations on different clocks (see
    the module docstring), so subtracting one from the other would manufacture
    a number rather than measure one. What can honestly be said is how many
    head the recent weeks have each required, and how much that has varied.

    Both readings, for the same reason the headline shows both: `cash` is
    negotiated cash alone, `must_buy` adds negotiated grid, whose base is
    struck in the week and which therefore is a transaction the packer has to
    make even though it does not set a cash quote.

    The band is the actual high and low of those weeks, not a standard
    deviation — with four observations a spread is something you can point at
    and a sigma is a decoration.
    """
    if mix.empty or len(mix) < 2:
        return {}
    d = mix.tail(weeks)
    cash = d["negotiated"]
    must = d["negotiated"] + d["neg_grid"]
    return {
        "weeks": int(len(d)),
        "cash": float(cash.mean()), "cash_lo": float(cash.min()), "cash_hi": float(cash.max()),
        "must": float(must.mean()), "must_lo": float(must.min()), "must_hi": float(must.max()),
        "kill": float(d["total"].mean()),
        "from": pd.Timestamp(d["week"].min()), "to": pd.Timestamp(d["week"].max()),
    }


def need_accuracy(mix: pd.DataFrame, weeks: int = NEED_WEEKS,
                  lookback: int = 52) -> dict:
    """
    How close that run rate has actually landed to the week that followed.

    Computed live rather than hard-coded, so the claim on the page keeps
    describing the market rather than the market of the day it was written.
    Median absolute error, because the misses are skewed by holiday weeks and
    a mean would describe none of the ordinary ones.
    """
    if mix.empty or len(mix) < weeks + 8:
        return {}
    d = mix.tail(lookback + weeks)
    out = {}
    for key, series in (("cash", d["negotiated"]),
                        ("must", d["negotiated"] + d["neg_grid"])):
        errs = []
        vals = series.to_numpy(dtype=float)
        for i in range(weeks, len(vals)):
            pred = vals[i - weeks:i].mean()
            if vals[i]:
                errs.append(abs(pred - vals[i]) / vals[i])
        if errs:
            e = pd.Series(errs)
            out[key] = {"median": float(e.median()), "p90": float(e.quantile(0.90)),
                        "n": int(len(e))}
    return out


# Years of same-week history the weight trend is fitted on. Eight, because the
# drift is secular and slow (about +10 lb a year on live weight since 2016) and
# a short fit mistakes a run of heavy years for the baseline, which is exactly
# the error this measure exists to avoid.
WEIGHT_TREND_YEARS = 8


def weight_frame(price_df: pd.DataFrame) -> pd.DataFrame:
    """
    Head-weighted live and dressed weights per week, from the 5-Area report.

    NO NEW REQUEST: the page already pulls LM_CT150's full History for the
    price panel and `weight_range_avg` rides along on it, back to 2004.

    Steer and heifer are combined head-weighted rather than averaged — a
    50-head heifer lot and a 3,000-head steer lot are not two equal readings,
    the same combine the price tiles use and for the same reason.
    """
    if price_df.empty or "weight_range_avg" not in price_df:
        return pd.DataFrame()
    d = price_df[price_df["current_period"] == "WEEKLY WEIGHTED AVERAGES"].copy()
    d = d.dropna(subset=["weight_range_avg", "head_count", "report_date"])
    if d.empty:
        return pd.DataFrame()
    d["hw"] = d["head_count"] * d["weight_range_avg"]
    g = d.groupby(["report_date", "selling_basis_desc"], as_index=False).agg(
        head=("head_count", "sum"), hw=("hw", "sum"))
    g = g[g["head"] > 0].copy()
    g["weight"] = g["hw"] / g["head"]
    out = g.pivot(index="report_date", columns="selling_basis_desc",
                  values="weight").reset_index()
    out.columns.name = None
    return out.sort_values("report_date")


def weight_context(weights: pd.DataFrame, column: str = "Live",
                   years: int = WEIGHT_TREND_YEARS) -> dict:
    """
    This week's weight against what the trend says it should be.

    A RAW YEAR-AGO COMPARISON OVERSTATES THE SIGNAL and would be the easy
    mistake here. Fed cattle have got heavier for two decades — genetics,
    feeding efficiency, cheap corn — at about +10 lb a year on live weight
    since 2016. So "+67 lb on the year" is partly a market telling you cattle
    are backing up and partly a trend that was always going to happen.

    The fix is the same shape the COF Recap uses for its year-ago column:
    compare like with like. The trend is fitted on the SAME ISO WEEK in prior
    years, which also removes the seasonal swing without a separate
    adjustment — week 41 against week 41, never against an annual mean.

    Returns the raw year-ago move, the fitted expectation and the deviation
    from it, so the page can show that most of the move is real rather than
    asserting it.
    """
    if weights.empty or column not in weights:
        return {}
    d = weights.dropna(subset=[column]).copy()
    if d.empty:
        return {}
    d["iso_week"] = d["report_date"].dt.isocalendar().week.astype(int)
    d["year"] = d["report_date"].dt.year
    cur = d.iloc[-1]
    same = d[(d["iso_week"] == int(cur["iso_week"])) & (d["year"] < int(cur["year"]))]
    same = same.tail(years)
    if len(same) < 4:
        return {"weight": float(cur[column]), "week": pd.Timestamp(cur["report_date"])}

    import numpy as np
    fit = np.polyfit(same["year"].to_numpy(dtype=float),
                     same[column].to_numpy(dtype=float), 1)
    expected = float(np.polyval(fit, float(cur["year"])))
    prior = float(same[column].iloc[-1])
    return {
        "weight": float(cur[column]),
        "week": pd.Timestamp(cur["report_date"]),
        "iso_week": int(cur["iso_week"]),
        "year_ago": prior,
        "vs_year_ago": float(cur[column]) - prior,
        "expected": expected,
        "vs_trend": float(cur[column]) - expected,
        "slope": float(fit[0]),
        "n": int(len(same)),
    }


def percentile(mix: pd.DataFrame, column: str, value: float, years: int = 3) -> float:
    """
    Where this week's share sits against its own recent history.

    A share means little in isolation — 19.7% negotiated is loose or tight only
    against what this market has been doing. Three years rather than the full
    run because the formula share has trended for two decades, and a percentile
    against 2005 would say more about that trend than about this week.
    """
    if mix.empty or column not in mix:
        return float("nan")
    cutoff = mix["week"].max() - pd.Timedelta(weeks=52 * years)
    s = mix[mix["week"] >= cutoff][column].dropna()
    if len(s) < 20:
        return float("nan")
    return float((s < value).mean())
