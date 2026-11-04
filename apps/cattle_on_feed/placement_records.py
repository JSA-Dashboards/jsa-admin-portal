"""
Record-low placement months, and whether they mean what they look like.

Asked for by Ross on 2026-10-27, after he noticed placements had been the
lowest on record for their calendar month three reports running and wanted it
set against the 2014-15 rebuild.

WHAT THIS COMPUTES AND WHAT IT REFUSES TO. It reports WHAT moved -- how long
the run is, how it ranks, and what the herd and the heifer mix were doing at
the time. It does NOT say whether the cause is heifer retention. That split is
the one the 6 State market summary already runs on, and this page has a
standing rule against a caption that supplies a plausible wrong cause.

THE RECORD RULE IS THE WHOLE CORRECTNESS, and getting it wrong is how the
first pass at this analysis reached the opposite conclusion.

Placements are strongly seasonal -- October is always large, July always
small -- so "lowest ever" on the raw series is a statement about the calendar.
A record has to be conditioned on the calendar month. But then a month cannot
set a record the first time it appears, and a short history manufactures them:

    minimum prior years required     3-month runs found
                 0                   5   (1997, 1998, 2001, 2015, 2026)
                 5                   3   (2001, 2015, 2026)
                10                   2   (2015, 2026)
                20                   1   (2026)

**Sep-Nov 2001 is an artefact of a five-year-old series, and it reverses the
answer.** It cleared the bar with exactly five prior years, and it is not a
low-placement episode at all: its lowest "record" month is 1,908,000 head,
7.4% ABOVE the highest of the 2026 run, and its 12-month total ranks 302nd of
359 windows. Admit it and the record looks like something that happens in
ordinary years; exclude it and the only genuine precedent is 2015, which was a
retention cycle. MIN_PRIOR_YEARS is 10 for that reason and the page prints it.

THREE FRAMINGS, BECAUSE THEY DISAGREE AND THE DISAGREEMENT IS THE POINT:

  * calendar-month records -- what Ross noticed, and what USDA's own monthly
    comparison invites. Fragile: the August 2026 margin is 12,000 head and the
    largest revision on record is 20,000.
  * the 12-month rolling total -- seasonality-free and revision-proof. 2026 is
    the lowest of 359 windows; 2015 is 5th.
  * placements per 100 Jan-1 beef cows -- the one that separates "fewer cattle
    are being placed" from "there are fewer cattle". 2026 is mid-pack here
    while 2015 is 25th of 359, which is the single most useful number on the
    panel and the least likely to be reached for.
"""
from __future__ import annotations

import pandas as pd

# Bump when compare() changes the SHAPE of what it returns -- st.cache_data
# keys on the calling function and never on this module. Passed at the call
# site, because a default is not part of the key.
SCHEMA = 1

# See the module docstring. Ten admits 2015 and 2026 and excludes the 2001
# artefact; it is a judgement, which is why the panel states it rather than
# hiding it in here.
MIN_PRIOR_YEARS = 10

# Below this many percentile points the contrast is not worth a sentence --
# "from the 48th to the 52nd" is noise wearing the clothes of a finding.
# The shape `six_state.ROSTER_MATERIAL` already uses.
HEIFER_SPREAD_MATERIAL = 20

# A run shorter than this is not worth a headline -- single record months are
# ordinary (52 of 370 on the raw rule).
MIN_RUN = 2


def _ordered(placements: pd.DataFrame) -> pd.DataFrame:
    """Sorted by date, and REFUSED if any month appears twice.

    A duplicated (year, month) is the one input error that corrupts every
    figure here silently: `rolling(12)` counts ROWS, not calendar months, so a
    frame carrying two capacity classes gives a "12-month" window spanning six
    months and a total that is plausible, wrong, and un-noticeable. Hit while
    wiring the on-feed series, whose cache holds fifteen capacity classes
    under one short_desc -- unfiltered it ranked Jan 1997 twice, at 2.5M
    against a true 11M.
    """
    p = placements.sort_values(["year", "month"]).reset_index(drop=True)
    dup = p.duplicated(["year", "month"])
    if dup.any():
        first = p.loc[dup, ["year", "month"]].iloc[0]
        raise ValueError(
            f"{int(dup.sum())} duplicated month(s), first {int(first.year)}-"
            f"{int(first.month):02d}: filter the series to one class before "
            "ranking it")
    return p


def flag_records(placements: pd.DataFrame,
                 min_prior: int = MIN_PRIOR_YEARS) -> pd.DataFrame:
    """`placements` plus a `record` column and `n_prior`.

    A record is judged AT THE TIME -- below every prior year's same month, not
    below the whole series including years that had not happened yet.
    """
    p = _ordered(placements)
    rec, prior_n = [], []
    for r in p.itertuples():
        prior = p[(p.month == r.month) & (p.year < r.year)]
        prior_n.append(len(prior))
        rec.append(len(prior) >= min_prior and r.Value < prior.Value.min())
    p["n_prior"] = prior_n
    p["record"] = rec
    return p


def runs(flagged: pd.DataFrame, min_run: int = MIN_RUN) -> list:
    """[{start, end, months, values}] for each consecutive stretch of records."""
    out, cur = [], []
    for r in flagged.itertuples():
        if r.record:
            cur.append(r)
        else:
            if len(cur) >= min_run:
                out.append(cur)
            cur = []
    if len(cur) >= min_run:
        out.append(cur)
    return [{"start": (c[0].year, c[0].month), "end": (c[-1].year, c[-1].month),
             "months": len(c), "values": [c_.Value for c_ in c]} for c in out]


def current_run(flagged: pd.DataFrame) -> int:
    """Records ending at the newest month. 0 if the newest month is not one."""
    n = 0
    for r in reversed(list(flagged.itertuples())):
        if not r.record:
            break
        n += 1
    return n


def run_standing(flagged: pd.DataFrame) -> dict:
    """Where the run ending at the newest month sits against every other run.

    THE RUN IN PROGRESS IS NOT ONE OF ITS OWN PRECEDENTS, which is the only
    subtle thing here: `runs()` returns it like any other, so counting runs of
    the longest length without excluding it reports the current run as having
    matched itself.

    `ties` is therefore how many EARLIER runs reached the same length --
    0 means outright, 1 means "matched once before".
    """
    rs = runs(flagged, min_run=1)
    cur = current_run(flagged)
    longest = max((r["months"] for r in rs), default=0)
    newest = (int(flagged.iloc[-1].year), int(flagged.iloc[-1].month)) if len(flagged) else None
    ties = sum(1 for r in rs
               if r["months"] == longest and not (cur and r["end"] == newest))
    return {"current": cur, "longest": longest, "ties": ties,
            "is_longest": bool(cur) and cur == longest}


def records_in_last(flagged: pd.DataFrame, window: int = 12) -> dict:
    """How many of the last `window` months were records, and the series best.

    This is the framing that survives a revision: one month losing its record
    moves the count by one rather than breaking a run in half.
    """
    f = flagged.copy()
    f["cnt"] = f.record.rolling(window).sum()
    done = f.dropna(subset=["cnt"])
    if done.empty:
        return {}
    now = int(done.cnt.iloc[-1])
    best = int(done.cnt.max())
    return {"window": window, "now": now, "best": best,
            "is_best": now >= best,
            "months": [(int(r.year), int(r.month))
                       for r in f.tail(window).itertuples() if r.record]}


def rolling_total(placements: pd.DataFrame, window: int = 12) -> dict:
    """The trailing `window`-month placement total, and where it ranks.

    Seasonality-free: every window contains each calendar month exactly once,
    so no adjustment and no month-conditioning is needed.
    """
    p = _ordered(placements)
    p["roll"] = p.Value.rolling(window).sum()
    r = p.dropna(subset=["roll"])
    if r.empty:
        return {}
    cur = r.iloc[-1]
    rank = int((r.roll < cur.roll).sum()) + 1
    return {"window": window, "total": float(cur.roll), "rank": rank,
            "of": len(r), "ends": (int(cur.year), int(cur.month)),
            "lowest": [(int(x.year), int(x.month), float(x.roll))
                       for _, x in r.nsmallest(5, "roll").iterrows()]}


def lowest_windows(placements: pd.DataFrame, beef_cows: pd.Series = None,
                   n: int = 10, window: int = 12, per_year: bool = False,
                   agg: str = "sum") -> dict:
    """The `n` lowest rolling `window`-month placement totals, lowest first.

    WINDOWS OVERLAP, AND THAT IS THE THING TO KNOW BEFORE READING THIS AS A
    LEAGUE TABLE. The 12 months ending August and the 12 months ending
    September share eleven of their months, so ONE quiet stretch fills several
    rows -- on the series as it stands the ten lowest windows touch just three
    calendar years. That is not a fault in the ranking, it is what a rolling
    window is, but a reader who takes ten rows for ten episodes has been
    misled. `stretches` counts how many SEPARATE runs of consecutive
    month-ends the rows come from, so the page can say so out loud.

    `per_year` ranks the quietest window ENDING in each calendar year instead,
    which is the view that reads as a league table -- ten distinct years rather
    than one stretch seen from several month-ends. It does not abolish overlap
    and does not claim to: a December window and the following January window
    are different years and still share eleven months, so `stretches` is
    computed in both modes.

    `per100` rides along per row because the panel's whole point is that the
    total and the per-cow figure disagree; a window can be among the lowest
    totals on file and unremarkable per cow.
    """
    p = _ordered(placements)
    # SUM FOR A FLOW, MEAN FOR A STOCK. Placements are a flow -- head that
    # went on feed during the month -- so twelve of them add up. On-feed
    # INVENTORY is a stock: summing it counts the same animal in every month
    # it stands in the yard, which is a category error that still produces a
    # plausible-looking number in the tens of millions.
    roll = p.Value.rolling(window)
    p["roll"] = roll.mean() if agg == "mean" else roll.sum()
    r = p.dropna(subset=["roll"]).copy()
    if r.empty:
        return {"rows": [], "stretches": 0, "of": 0, "window": window,
                "agg": agg, "per_year": per_year}
    if beef_cows is not None:
        r["per100"] = r.roll / r.year.map(beef_cows) * 100
    if per_year:
        # The quietest window ENDING in each calendar year. It does not remove
        # overlap, it bounds it: a December window and the following January
        # window are different years and still share eleven months, which is
        # why `stretches` is computed either way rather than assumed to be n.
        r = r.loc[r.groupby("year").roll.idxmin()]
    rows = []
    # TIES BREAK ON THE EARLIER WINDOW, explicitly. `nsmallest` leaves the
    # order of tied rows to pandas, which is a poor thing to put a RANK
    # column against -- two windows on the same total would swap places
    # between runs with nothing in the data having changed.
    ranked = r.sort_values(["roll", "year", "month"]).head(n)
    for i, (_, x) in enumerate(ranked.iterrows(), 1):
        per = x.per100 if beef_cows is not None else None
        rows.append({"rank": i, "year": int(x.year), "month": int(x.month),
                     "total": float(x.roll),
                     "per100": None if per is None or pd.isna(per) else float(per)})
    ends = sorted(d["year"] * 12 + d["month"] for d in rows)
    stretches = 1 + sum(1 for a, b in zip(ends, ends[1:]) if b - a > 1)
    return {"rows": rows, "stretches": stretches, "of": len(r),
            "window": window, "per_year": per_year, "agg": agg}


def per_cow(placements: pd.DataFrame, beef_cows: pd.Series,
            window: int = 12) -> dict:
    """Trailing placements per 100 Jan-1 beef cows, and its rank.

    THE DISCRIMINATOR. A record-low placement total means one of two very
    different things -- fewer cattle are being placed, or there are fewer
    cattle. Dividing by the breeding herd separates them, and it is the only
    measure here on which 2026 and 2015 come apart.

    `beef_cows` is a year-indexed Series of Jan-1 head. It MUST be the SURVEY
    series: "CATTLE, COWS, BEEF - INVENTORY" also carries CENSUS rows, and the
    census years 1997, 2002 and 2017 come back at 1.4M, 1.2M and 4.0M against a
    true ~30M, which reads as a collapse and recovery that never happened.
    """
    p = _ordered(placements)
    p["roll"] = p.Value.rolling(window).sum()
    r = p.dropna(subset=["roll"]).copy()
    r["cows"] = r.year.map(beef_cows)
    r = r.dropna(subset=["cows"])
    if r.empty:
        return {}
    r["per100"] = r.roll / r.cows * 100
    cur = r.iloc[-1]
    rank = int((r.per100 < cur.per100).sum()) + 1
    return {"value": float(cur.per100), "rank": rank, "of": len(r),
            "ends": (int(cur.year), int(cur.month)),
            "by_year": {int(y): float(v) for y, v in
                        r.groupby("year").per100.last().items()}}


def heifer_share(heifers: pd.DataFrame, steers: pd.DataFrame) -> pd.DataFrame:
    """Heifers as a percent of heifers+steers on feed, quarterly.

    Against the ON-FEED total rather than reading a published share, so the
    denominator is explicit -- see the panel's caption about imported steers
    sitting in it.
    """
    m = heifers.merge(steers, on=["year", "month"], suffixes=("_h", "_s"))
    m["pct"] = m.Value_h / (m.Value_h + m.Value_s) * 100
    return m[["year", "month", "pct"]].sort_values(["year", "month"]).reset_index(drop=True)


def share_at(share: pd.DataFrame, year: int) -> dict:
    """That year's mean heifer share and its percentile in the whole series."""
    s = share[share.year == year].pct
    if s.empty:
        return {}
    v = float(s.mean())
    return {"pct": v, "percentile": float((share.pct < v).mean() * 100)}


def total_by_year(placements: pd.DataFrame, window: int = 12,
                  agg: str = "sum") -> dict:
    """{year: the window ENDING that December} -- the chart's other basis.

    Mirrors `per_cow()["by_year"]` exactly: the LAST window of each calendar
    year, so the two chart modes cover identical periods and the annual heifer
    line lines up with both. Taking a different window for one of them would
    put two series on one axis that describe different twelve-month spans,
    which no caption can repair.
    """
    p = _ordered(placements)
    roll = p.Value.rolling(window)
    p["roll"] = roll.mean() if agg == "mean" else roll.sum()
    r = p.dropna(subset=["roll"])
    if r.empty:
        return {}
    return {int(y): float(v) for y, v in r.groupby("year").roll.last().items()}


def retention_signal(placements: pd.DataFrame, beef_cows: pd.Series,
                     share: pd.DataFrame) -> dict:
    """How closely per-cow placements track two measures of retention.

    MEASURED, NEVER ASSERTED, and the measurement is the reason this exists.
    "Fewer placed per cow means heifers are being kept back" is the obvious
    reading of this page and it is mostly WRONG: against the following year's
    beef cow change the per-cow figure runs about r = -0.19 over 30 years,
    which is close to no relationship. The heifer share on feed manages about
    r = -0.63 on the same question. So the honest answer to "does this show
    retention" is "barely -- look at the heifer share instead", and a page
    that implied otherwise would be supplying a plausible wrong cause, which
    this panel exists not to do.

    Note the per-cow-to-heifer-share link is PARTLY DEFINITIONAL: heifers are
    counted in placements, so the two cannot be independent. That is a reason
    to read the +0.35 as weaker than it looks, not stronger.
    """
    pc = pd.Series(per_cow(placements, beef_cows).get("by_year", {}), dtype=float)
    cw = pd.Series(beef_cows, dtype=float).sort_index()
    if pc.empty or cw.empty:
        return {}
    sh = (share.groupby("year").pct.mean() if share is not None and len(share)
          else pd.Series(dtype=float))
    frame = pd.DataFrame({"pc": pc, "sh": sh, "nx": (cw.shift(-1) / cw - 1) * 100})

    def _r(a: str, b: str):
        # NaN IS NOT A CORRELATION. A series with no variance -- a short
        # window, or a state whose share never moves -- makes corr() return
        # NaN, and a caption interpolating it prints "r = nan" on the page.
        # None means "not measurable here" and the caption drops the sentence.
        d = frame[[a, b]].dropna()
        if len(d) <= 2:
            return None, len(d)
        v = d[a].corr(d[b])
        return (None if pd.isna(v) else float(v)), len(d)

    r_share, n_share = _r("pc", "sh")
    r_herd, n_herd = _r("pc", "nx")
    r_sh_herd, n_sh_herd = _r("sh", "nx")
    return {"per_cow_vs_share": r_share, "n_share": n_share,
            "per_cow_vs_herd": r_herd, "n_herd": n_herd,
            "share_vs_herd": r_sh_herd, "n_share_herd": n_sh_herd}


def heifer_by_year(share: pd.DataFrame) -> dict:
    """{year: {"pct", "percentile"}} for every year in the share series.

    DELEGATES TO share_at() PER YEAR rather than recomputing, so the chart and
    the runs table cannot quote different percentiles for one year. That is
    the failure this file records five times over, and it is cheap to make
    impossible: the percentile is a year's MEAN placed in the QUARTERLY
    distribution, which is a convention, not a fact, and two surfaces reading
    it two ways would both be defensible.
    """
    if share is None or not len(share):
        return {}
    out = {}
    for y in sorted(int(v) for v in share.year.unique()):
        at = share_at(share, y)
        if at:
            out[y] = at
    return out


def heifer_spread(rows: list, heifer: dict,
                  material: int = HEIFER_SPREAD_MATERIAL) -> dict:
    """The widest heifer-share contrast among a set of ranked rows.

    READ OFF THE DATA AT RENDER TIME, NEVER WRITTEN INTO PROSE. The caption
    this feeds currently says the 4th percentile against the 54th; both ends
    move as USDA revises and as new windows enter the ranking, and a sentence
    carrying the numbers would go stale against the table directly above it.
    That is the mistake `southeast.py` records for "2010-2012 is the trough of
    the whole record", which was true of one panel and false of the next.

    It reports WHAT the two ends are and never why they differ.
    """
    pts = [(r["year"], heifer[r["year"]]) for r in rows
           if heifer.get(r["year"]) and heifer[r["year"]].get("percentile") is not None]
    if len(pts) < 2:
        return {}
    # TIES BREAK ON THE SHARE ITSELF. Percentiles print rounded, so two years
    # both reading "4th" can differ underneath, and picking between them on
    # float order names whichever pandas happened to rank first -- a caption
    # citing 2016 at 32.9% while the table above shows 2015 at 32.6% on the
    # same printed percentile. The more extreme share wins.
    lo = min(pts, key=lambda t: (t[1]["percentile"], t[1]["pct"]))
    hi = max(pts, key=lambda t: (t[1]["percentile"], t[1]["pct"]))
    gap = float(hi[1]["percentile"] - lo[1]["percentile"])
    return {"low": dict(year=lo[0], **lo[1]), "high": dict(year=hi[0], **hi[1]),
            "gap": gap, "material": gap >= material}


def compare(placements: pd.DataFrame, beef_cows: pd.Series,
            share: pd.DataFrame, min_prior: int = MIN_PRIOR_YEARS,
            inventory: pd.DataFrame = None) -> dict:
    """Everything the panel draws, from one pass over the series."""
    flagged = flag_records(placements, min_prior)
    roll = rolling_total(placements)
    rows = []
    for run in runs(flagged, min_run=3):
        y = run["end"][0]
        rows.append({
            "run": run,
            "year": y,
            "share": share_at(share, y),
            "cows_next": _chg(beef_cows, y, y + 1),
            "cows_then": _chg(beef_cows, y + 1, y + 2),
        })
    return {
        "flagged": flagged,
        "current_run": current_run(flagged),
        "standing": run_standing(flagged),
        "last12": records_in_last(flagged),
        "rolling": roll,
        "per_cow": per_cow(placements, beef_cows),
        "total_by_year": total_by_year(placements),
        "retention_signal": retention_signal(placements, beef_cows, share),
        "heifer_by_year": heifer_by_year(share),
        "lowest_onfeed": (lowest_windows(inventory, agg="mean")
                          if inventory is not None and len(inventory) else {}),
        "lowest_onfeed_per_year": (
            lowest_windows(inventory, agg="mean", per_year=True)
            if inventory is not None and len(inventory) else {}),
        "lowest_windows": lowest_windows(placements, beef_cows),
        "lowest_per_year": lowest_windows(placements, beef_cows, per_year=True),
        "runs": rows,
        "min_prior": min_prior,
        "first_year": int(_ordered(placements).year.min()),
    }


def _chg(series: pd.Series, a: int, b: int):
    if a in series.index and b in series.index and series[a]:
        return float(series[b] / series[a] - 1) * 100
    return None
