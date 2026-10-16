"""
How the Monday Print Forecast has actually been doing.

Replays the forecast at the SAME POINT IN THE WEEK it is standing at right
now, for each recent week, and compares it with the figure USDA went on to
print. Two columns, because the tab's two steps fail differently and a single
accuracy number would hide that: the 5-Area call and the national one are
scored separately.

THE FORECAST FUNCTIONS ARE PASSED IN RATHER THAN IMPORTED, and that is the
whole point of this module existing. A scorecard that reimplements the thing
it scores grades a copy: the copy drifts, the page keeps its own behaviour,
and the scorecard reports on code nobody runs. `apps/cash_trade/app.py` is a
Streamlit script and cannot be imported, so the page hands its own
forecast_5area and forecast_national in and this replays those exact objects.

WHY THE CHECKPOINT MATCHES THE LIVE ONE instead of always scoring Friday's
1:30 pm cut. Accuracy is overwhelmingly a function of how far into the week
you are standing -- measured over 52 Friday checkpoints, the busiest quarter
of weeks land within a median 3% while the quietest are a median 36% out. A
scorecard fixed on Friday would therefore flatter a Wednesday reading of the
page by a factor of ten. Scoring past weeks at the same weekday and cut makes
the number underneath the forecast describe the forecast above it.

RECONSTRUCTION IS HONEST HERE, which is not something to assume -- the sibling
FCI scorecard exists precisely because reconstructing ITS estimate flatters it,
the input table growing as late auctions land until a replayed call has seen
data the real one never did. Checked 2026-10-02 rather than argued by analogy:

  - LM_CT150 History, the figure this scores AGAINST, carried **0** rows
    flagged `is_correction` over twelve months. The target never moves.
  - The daily /Summary files this replays FROM carried 44 corrections in
    8,160 rows, 0.54%. Rare and discrete, not the systematic upward drift the
    FCI case has.

So a replayed call is the call we would have made, to within half a percent of
input rows. The remaining exposure is real but small, and the fix for it is to
freeze each call when it is made rather than to stop replaying -- see
`capture_snapshots` in the cme-feeder-cattle-index repo for that shape.

Every week is replayed STRICTLY OUT OF SAMPLE: the analogue pool, the maturity
baseline and the 5-Area-to-national gap are all cut to weeks that had already
printed. Letting any of them see the week being scored would be marking our own
homework with the answers in front of us.
"""
from __future__ import annotations

import pandas as pd


def _truncate(vol: pd.DataFrame, week: pd.Timestamp, weekday: int, order: int,
              cut_order: dict) -> pd.DataFrame:
    """
    `vol` as it stood at one checkpoint: every earlier week in full, plus the
    scored week up to and including that publication and no further.

    The exclusion is what makes the replay out of sample. For a Friday 1:30 pm
    checkpoint the row that must not survive is Friday's MORNING file, which is
    published the following Monday and carries the finished week -- i.e. the
    answer.
    """
    if vol.empty:
        return vol
    v = vol.copy()
    v_week = v["trade_date"] - pd.to_timedelta(v["trade_date"].dt.weekday, unit="D")
    v_day = v["trade_date"].dt.weekday
    v_ord = v["cut"].map(cut_order)
    keep = (v_week < week) | (
        (v_week == week) & ((v_day < weekday) | ((v_day == weekday) & (v_ord <= order))))
    return v[keep]


def _checkpoints_before(vol: pd.DataFrame, week: pd.Timestamp, weekday: int,
                        order: int, cut_order: dict):
    """The publication immediately preceding one checkpoint, within its week."""
    if vol.empty:
        return None
    v = vol[vol["period"] == "wtd"].copy()
    if v.empty:
        return None
    v_week = v["trade_date"] - pd.to_timedelta(v["trade_date"].dt.weekday, unit="D")
    v = v[v_week == week]
    if v.empty:
        return None
    pairs = sorted({(int(d.weekday()), int(cut_order.get(c, 0)))
                    for d, c in zip(v["trade_date"], v["cut"])})
    before = [p for p in pairs if p < (weekday, order)]
    return before[-1] if before else None


def _previous_week_checkpoint(vol: pd.DataFrame, week: pd.Timestamp,
                              cut_order: dict):
    """
    The last checkpoint of the most recent week before `week` that traded.

    Used when the live week is still empty. Returns the final pre-print
    publication of that earlier week — Friday's 1:30 pm cut where a Friday
    final exists, because the final IS the answer and scoring against it
    measures nothing (the same reason build_scorecard steps back when done).
    """
    # Derived from `vol` directly rather than through the page's
    # wtd_checkpoints: this module is handed the forecast functions, not the
    # app's helpers, and importing them would be the circular dependency the
    # whole pass-them-in design exists to avoid.
    if vol.empty:
        return None
    v = vol[vol["period"] == "wtd"].copy()
    if v.empty:
        return None
    v["wk"] = v["trade_date"] - pd.to_timedelta(v["trade_date"].dt.weekday, unit="D")
    v = v[v["wk"] < week]
    if v.empty:
        return None
    v["head"] = pd.to_numeric(v["head"], errors="coerce").fillna(0.0)
    traded = v.groupby("wk")["head"].sum()
    traded = traded[traded > 0]
    if traded.empty:
        return None
    last_week = traded.index.max()
    w = v[v["wk"] == last_week]
    pairs = sorted({(int(d.weekday()), int(cut_order.get(c, 0)))
                    for d, c in zip(w["trade_date"], w["cut"])})
    if not pairs:
        return None
    # Friday's FINAL is the answer, not a forecast of it — step back one, the
    # same rule the `done` branch above applies.
    if pairs[-1] == (4, cut_order.get("morning", 1)) and len(pairs) > 1:
        return pairs[-2]
    return pairs[-1]


GREEN_MATURITY = 0.50
"""Live maturity below which a checkpoint is not worth scoring at.

forecast_5area's own "weak" boundary, reused rather than re-chosen. See the
measurement table in build_scorecard for why this is the line.
"""


def _too_green(live: dict) -> bool:
    """
    Has the live week traded enough for a call from it to mean anything?

    A missing maturity counts as too green: it means there is no typical week
    to measure against, which is not a state to replay ten weeks from.
    """
    m = live.get("maturity")
    if m is None or m != m:          # NaN
        return True
    return float(m) < GREEN_MATURITY


def checkpoint_of(sc: pd.DataFrame):
    """
    The (weekday, order) every row in `sc` was scored at, or None if empty.

    The page needs this to label the panel honestly: when build_scorecard steps
    back, "the last N calls at this point in the week" stops being true, and a
    headline accuracy borrowed from a later checkpoint is flattering rather
    than merely wrong.
    """
    if sc.empty or "cp_weekday" not in sc.columns:
        return None
    scored = sc[~sc["pending"].fillna(False).astype(bool)] if "pending" in sc else sc
    if scored.empty:
        return None
    return int(scored["cp_weekday"].iloc[0]), int(scored["cp_order"].iloc[0])


def build_scorecard(vol: pd.DataFrame, published5: pd.Series, national: pd.Series,
                    forecast_5area, forecast_national, cut_order: dict,
                    weeks: int = 10) -> pd.DataFrame:
    """
    One row per scored week, newest first.

    Returns empty when the live forecast cannot be formed or no past week
    published at the same checkpoint -- an empty frame is the page's cue to say
    so rather than to print an accuracy built on one or two weeks.
    """
    live = forecast_5area(vol, published5)
    if not live or published5.empty:
        return pd.DataFrame()

    cp = live["checkpoint"]
    weekday, order = int(cp["weekday"]), int(cp["order"])
    cur_week = pd.Timestamp(live["week"])

    # ONCE FRIDAY'S FINAL HAS LANDED THE LIVE CHECKPOINT IS THE ANSWER, not a
    # forecast of it -- forecast_5area reports done=True and returns the
    # week-to-date unchanged. Scoring past weeks at that same checkpoint would
    # compare each answer with itself: a perfect record, truthfully computed,
    # describing nothing. Step back to the last checkpoint that still had
    # something to predict, which is also the most useful reading there is on a
    # Monday -- it is the call we actually made before the print.
    if live.get("done"):
        earlier = _checkpoints_before(vol, cur_week, weekday, order, cut_order)
        if earlier is None:
            return pd.DataFrame()
        weekday, order = earlier

    # ...AND THE SAME PROBLEM ARRIVES FROM THE OTHER END EVERY TUESDAY.
    #
    # Once a new trading week opens, the live checkpoint is early and nearly
    # nothing has traded. Scoring the last ten weeks at THAT point replays
    # every one of them from a near-empty base, so each estimate is the
    # analogue median with noise added, every row grades "weak", and the
    # accuracy reads 23% when the calls those weeks actually produced were a
    # median 1.4% out.
    #
    # Worse, it contradicts the tiles. On 2026-10-06 the tiles reported the
    # settled Sep 28 week — called 60,897 against USDA's 60,063, scored where
    # the call was really made — while the table underneath said 49,062 for
    # that same week, scored at a Monday that had not happened when we called
    # it. Same week, two "we called" figures, one screen.
    #
    # **THE FIRST VERSION OF THIS GUARD TESTED `not live["wtd"]`, AND THAT
    # CAUGHT ONLY A LITERAL ZERO.** On 2026-10-07 the live week stood at 337
    # head — 0.75% of a typical week, which is nothing — so the guard sat out
    # and the whole failure came back: the table showed Sep 28 at 45,784 /
    # 66,340 against the 60,897 / 81,453 we actually called, and the headline
    # accuracy read 23.8% / 29.4% against 1.4% / 7.9% at the real checkpoint.
    # A head count of 337 is zero in every sense except the arithmetic one.
    #
    # SO THE TEST IS MATURITY, AND THE LINE IS THE ONE forecast_5area ALREADY
    # DRAWS. Below `maturity` 0.50 it grades the call "weak", and that boundary
    # turns out to be exactly where the forecast stops being worth replaying.
    # Measured over 457 (week, checkpoint) pairs on the live feed, against the
    # naive alternative of ignoring the week and printing a typical one:
    #
    #     maturity     forecast   naive      maturity     forecast   naive
    #     0–1%            19.4%   17.8%      35–50%          39.2%   32.3%
    #     1–2%            30.9%   17.9%      50–75%          20.9%   22.9%
    #     2–5%            34.4%   19.1%      75–101%         14.3%    5.9%
    #     5–10%           45.1%   41.4%      101%+            6.7%   26.7%
    #     10–35%        35–47%   26–27%
    #
    # The forecast beats the naive baseline nowhere below 0.50 and clearly
    # above it, so scoring a sub-0.50 live checkpoint grades a call that
    # carries no information — and prints numbers that are not the ones we
    # made. Stepping back lands on the checkpoint the tiles are showing.
    #
    # **It costs something and the page must say so.** The accuracy then
    # describes a Friday-cut call while a weak live call sits above it, which
    # is flattering if it goes unlabelled — the exact distortion this module's
    # docstring argues against. `checkpoint_of()` exists so the header can name
    # the checkpoint it really scored, and a test pins that the page uses it.
    if not live.get("done") and _too_green(live):
        prior = _previous_week_checkpoint(vol, cur_week, cut_order)
        if prior is None:
            return pd.DataFrame()
        weekday, order = prior

    # Only weeks USDA has printed can be scored, and published5 holds exactly
    # those -- so the live week belongs in the list once its figure lands,
    # which is the week anyone opening this on a Monday wants to see.
    candidates = [w for w in published5.index if w <= cur_week]
    candidates.sort(reverse=True)

    rows = []
    for w in candidates:
        if len(rows) >= weeks:
            break
        sub_vol = _truncate(vol, w, weekday, order, cut_order)
        sub_p5 = published5[published5.index < w]
        sub_nat = national[national.index < w]
        if sub_p5.empty or sub_nat.empty:
            continue
        f5 = forecast_5area(sub_vol, sub_p5)
        if not f5:
            continue
        # The week must have published at the SAME checkpoint, or we would be
        # comparing a Thursday call against a Friday one and calling it a week.
        c = f5["checkpoint"]
        if int(c["weekday"]) != weekday or int(c["order"]) != order:
            continue
        if pd.Timestamp(f5["week"]) != pd.Timestamp(w):
            continue

        fn = forecast_national(f5, sub_p5, sub_nat)
        actual5 = float(published5.get(w, float("nan")))
        actualn = float(national.get(w, float("nan")))
        rows.append({
            "week": pd.Timestamp(w),
            # Carried per row rather than on .attrs, which pandas drops through
            # most operations -- including the concat the page does with the
            # pending row. checkpoint_of() reads it back.
            "cp_weekday": weekday, "cp_order": order,
            "wtd": f5["wtd"],
            "grade": f5.get("grade"),
            "f5": f5["central"], "f5_lo": f5["low"], "f5_hi": f5["high"],
            "a5": actual5,
            "fn": fn.get("central") if fn else float("nan"),
            "fn_lo": fn.get("low") if fn else float("nan"),
            "fn_hi": fn.get("high") if fn else float("nan"),
            "an": actualn,
        })

    sc = pd.DataFrame(rows)
    if sc.empty:
        return sc
    # Every row here is a SCORED week. pending_row() sets this True, and
    # summarise() drops those -- see the guard there for why that matters.
    sc["pending"] = False
    for side, f, a, lo, hi in (("5", "f5", "a5", "f5_lo", "f5_hi"),
                               ("n", "fn", "an", "fn_lo", "fn_hi")):
        sc[f"miss{side}"] = sc[f] - sc[a]
        sc[f"pct{side}"] = sc[f"miss{side}"] / sc[a]
        sc[f"in{side}"] = (sc[a] >= sc[lo]) & (sc[a] <= sc[hi])
    return sc


def pending_row(vol: pd.DataFrame, published5: pd.Series, national: pd.Series,
                forecast_5area, forecast_national) -> pd.DataFrame:
    """
    The week in flight, as an UNSCORED row — or empty once USDA has printed it.

    Same columns build_scorecard returns, so the two concatenate, but with the
    actuals and every miss left as NaN because there is nothing yet to compare
    against. `pending` is True here and False there, which is what tells the
    page and summarise() apart from each other.

    IT DISAPPEARS THE MOMENT THE WEEK PRINTS, and that is the only thing this
    function really has to get right. Once `published5` carries the week,
    build_scorecard scores it for real; a pending row surviving alongside that
    would show the same week twice, once with a miss and once blank, and the
    blank one would look like a second, failed call.

    IT STANDS AT THE LIVE CHECKPOINT, not the stepped-back one build_scorecard
    uses. Those differ on a Monday: once Friday's final lands the live number
    is the answer rather than a forecast, so the scored rows step back to the
    last checkpoint that still had something to predict (see build_scorecard).
    This row is the call shown in the tiles above it on the page, so it has to
    be the live one or the table would contradict the tiles.
    """
    live = forecast_5area(vol, published5)
    if not live:
        return pd.DataFrame()
    week = pd.Timestamp(live["week"])
    if not published5.empty and week in published5.index:
        return pd.DataFrame()

    fn = forecast_national(live, published5, national) if not national.empty else None
    nan = float("nan")

    # NO CALL MEANS NO CALL, HERE TOO. Once the week is too green the tiles
    # above stop printing an estimate, and a pending row that still carried
    # one would put the suppressed number back on the page six inches lower --
    # under a footnote saying it is "the same call as the tiles above". Same
    # shape as the letter-vs-dashboard disagreements this file keeps hitting:
    # both halves truthful, together a contradiction.
    green = bool(live.get("no_call"))
    f5c, f5lo, f5hi = ((nan, nan, nan) if green
                       else (live["central"], live["low"], live["high"]))
    fnc, fnlo, fnhi = ((nan, nan, nan) if (green or not fn)
                       else (fn["central"], fn["low"], fn["high"]))

    return pd.DataFrame([{
        "week": week,
        # Present but empty: this row is the LIVE checkpoint by definition, and
        # checkpoint_of() must not read it when build_scorecard has stepped the
        # scored rows back to a different one. Same columns so the two still
        # concatenate without pandas inventing them.
        "cp_weekday": nan, "cp_order": nan,
        "wtd": live["wtd"],
        "grade": live.get("grade"),
        "f5": f5c, "f5_lo": f5lo, "f5_hi": f5hi,
        "a5": nan,
        "fn": fnc, "fn_lo": fnlo, "fn_hi": fnhi,
        "an": nan,
        "miss5": nan, "pct5": nan, "in5": False,
        "missn": nan, "pctn": nan, "inn": False,
        "pending": True,
    }])


def summarise(sc: pd.DataFrame) -> dict:
    """
    Headline accuracy over the scored weeks.

    Median absolute percentage rather than mean: the misses are right-skewed
    (late trade can surprise upward and cannot go below zero), so a mean is
    dragged by the one back-loaded week in ten and describes none of them.
    """
    if sc.empty:
        return {}
    # THE PENDING ROW MUST NEVER REACH THE AVERAGE. Its actual is NaN, so a
    # median would skip it silently and "the last 10 calls" would describe 9 --
    # or, once a caller concatenates before summarising, count a week that has
    # not happened yet. The page keeps them apart by calling this first; this
    # guard means it stays true even if someone later stops doing that.
    if "pending" in sc.columns:
        sc = sc[~sc["pending"].fillna(False).astype(bool)]
    if sc.empty:
        return {}
    out = {"n": int(len(sc))}
    for side, label in (("5", "five"), ("n", "nat")):
        pct, inb = sc[f"pct{side}"].abs(), sc[f"in{side}"]
        out[label] = {
            "median_abs_pct": float(pct.median()),
            "median_abs_head": float(sc[f"miss{side}"].abs().median()),
            "in_band": float(inb.mean()),
            "within_10": float((pct <= 0.10).mean()),
            "bias": float(sc[f"pct{side}"].median()),
        }
    return out
