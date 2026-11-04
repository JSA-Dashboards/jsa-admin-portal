"""
Every number the Tuesday letter prints, fetched from the same source the
matching dashboard uses.

WHY THE REPORT IDS ARE REPEATED HERE. The dashboards are Streamlit scripts:
apps/cash_trade/app.py and friends call st.markdown() at module scope, so
importing them to borrow a fetcher would execute a page. The constants below
are therefore copied, not imported -- and tests/test_letter_drift.py reads the
app files and asserts every one of them still agrees, so a dashboard changing
report IDs breaks the test instead of silently sending stale numbers to clients.

The two modules that ARE import-safe get imported rather than copied:
apps/livestock_seasonal/massive_api.py (no streamlit) and
apps/cme_feeder_cattle/snowflake_db.py (loaded under a private name -- see
_load_fci_db for why that matters).
"""
from __future__ import annotations

import importlib.util
import io
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config
from . import settle_log

REPO = Path(__file__).resolve().parent.parent
APPS = REPO / "apps"

# -- AMS LMR: mirrored from the dashboards (see module docstring) -------------
LMR_BASE = "https://mpr.datamart.ams.usda.gov/services/v1.1/reports"

CT150_ID = 2477    # apps/cash_trade/app.py  -- 5-Area Weekly Weighted Average Direct Slaughter Cattle
CT154_ID = 2481    # apps/cash_trade/app.py  -- National Weekly Direct Slaughter Cattle, Negotiated
XB403_ID = 2453    # apps/beef_cutout/app.py -- National Daily Boxed Beef Cutout PM
GRADING_ID = 2700  # apps/beef_cutout/app.py -- National Weekly Fed Cattle Comprehensive
AMS_SJ_LS712 = "https://www.ams.usda.gov/mnreports/sj_ls712.txt"

# AMS report 3208, "Daily Livestock and Poultry Slaughter" -- the source of the
# letter's daily and week-to-date bullets. Published as a PDF at a stable path
# that needs no API key. Also available through MyMarketNews as report 3208 if a
# structured feed is ever wanted; the PDF is used because it costs no secret.
AMS_3208_PDF = "https://www.ams.usda.gov/mnreports/ams_3208.pdf"


def _session(backoff: float = 1.5) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=backoff,
                  status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _num(x):
    """AMS ships numbers as strings with commas and the odd stray percent sign."""
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


# -- Futures ------------------------------------------------------------------

def _massive():
    sys.path.insert(0, str(APPS / "livestock_seasonal"))
    import ls_massive_api as massive_api
    return massive_api


_MONTHS = {"F": "Jan", "G": "Feb", "H": "Mar", "J": "Apr", "K": "May", "M": "Jun",
           "N": "Jul", "Q": "Aug", "U": "Sep", "V": "Oct", "X": "Nov", "Z": "Dec"}


def contract_month(ticker: str) -> str:
    """LEV6 -> 'Oct'. The letter labels contracts by month alone."""
    m = re.match(r"^[A-Z]{1,3}([FGHJKMNQUVXZ])\d$", ticker)
    return _MONTHS.get(m.group(1), ticker) if m else ticker


def fetch_futures(product_code: str, api_key: str, as_of: date, n: int = 3,
                  completed_only: bool = False) -> list[dict]:
    """
    Front n outright contracts: last settle plus both candidate net changes.

    Returns settle, change_day (previous session) and change_week (the last
    settle on or before the prior Friday) for each contract. Both are carried
    because which one the letter quotes is still unconfirmed -- see
    config.CHANGE_BASIS.

    completed_only EXCLUDES TODAY'S BAR, and the AM report needs it. The
    history's row for today is the session in progress, so a morning brief
    rebuilt at 09:00 was picking up live prices and calling them a settle --
    am_cattle_rows promises "yesterday's settle and its move" and was quietly
    getting neither. Invisible until the heading started printing the date it
    came from, on 2026-09-24, which is what a date on a number is for.

    The evening letter is built after the close and wants today's settle, so it
    leaves this off. One flag, because the two reports genuinely differ: at
    07:30 there is no settle for today and at 17:00 there is.
    """
    api = _massive()
    contracts = api.get_active_contract_tickers(product_code, api_key, as_of)[:n]
    tickers = [c["ticker"] for c in contracts]
    hist = api.get_settlement_histories(tickers, api_key)

    # The most recent Friday strictly before as_of. A letter written ON a Friday
    # should compare against the PREVIOUS Friday, not itself, hence the "or 7".
    prior_friday = as_of - timedelta(days=(as_of.weekday() - 4) % 7 or 7)

    def _clip(ser):
        # CLIP TO as_of. Without this the settle is always the NEWEST bar, so a
        # letter rebuilt for an earlier date silently carries today's prices --
        # and a stored letter stops being a record of what it printed.
        #
        # STRICTLY BEFORE for the morning report: today's bar exists from the
        # moment the session opens and is not a settle until it closes.
        ser = ser.dropna()
        return ser[ser.index < as_of] if completed_only else ser[ser.index <= as_of]

    series = {t: _clip(hist.get(t, pd.Series(dtype=float))) for t in tickers}

    # IS THE SETTLEMENT HISTORY BEHIND? Asked once for the whole curve, because
    # it is a property of the feed rather than of any one month, and because
    # the recovery below costs two extra requests per contract.
    #
    # THIS CHECK IS THE ACTUAL FIX. On 2026-09-28 the Monday brief printed
    # 09-11 settles as that morning's futures -- Oct feeders at 332.50 when
    # Friday had settled 335.00 -- and gather() returned no errors at all,
    # because "the newest bar" is always a perfectly good bar. Seventeen days
    # of staleness is invisible to every check that only asks whether data came
    # back. Nothing below trusts recency again.
    # THE TRIGGER IS TIGHTER THAN THE ALARM, deliberately, and they are not the
    # same question. Being wrong about whether to TRY the hourly bars costs one
    # request per contract. Being wrong about whether to shout "do not send"
    # costs the alarm its meaning, and a warning nobody believes is the state
    # this whole failure began in. So recovery starts the moment the series is
    # behind the last weekday it could have had a bar for, while settle_stale
    # below keeps the looser MAX_SETTLE_AGE_DAYS tolerance.
    #
    # The trigger fires needlessly on the nine or so exchange holidays a year,
    # when the last weekday has no bar because nothing traded. That is harmless:
    # the hourly bars have no bar for a holiday either, so nothing is filled and
    # nothing changes. A day-count tolerance loose enough to cover those
    # holidays is also loose enough to hide a feed that is one session behind,
    # which is this same bug in miniature -- on a Monday it would quote
    # Thursday's settle as Friday's and only the date line would say otherwise.
    last_weekday = as_of - timedelta(days=1) if completed_only else as_of
    while last_weekday.weekday() >= 5:
        last_weekday -= timedelta(days=1)

    # TWO WAYS TO BE BEHIND, and the letter needs both. The newest bar can be
    # old (the morning brief's failure on 2026-09-28), or the newest bar can be
    # today while the one BEFORE it is three weeks back -- the evening letter's
    # version of the same hole, which leaves it a settle and no move. Checking
    # only the first fixes the AM report and leaves the PM report changeless.
    #
    # Judged on the FRESHEST contract, not on every one: a back month that did
    # not trade yesterday has no bar for perfectly ordinary reasons, and asking
    # "is any contract behind" would fetch hourly bars every day of the year
    # for a January feeder nobody quoted.
    newest = [ser.index[-1] for ser in series.values() if len(ser)]
    freshest = max(newest) if newest else None
    holey = any(len(ser) > 1 and (ser.index[-1] - ser.index[-2]).days > MAX_SETTLE_AGE_DAYS
                for ser in series.values() if len(ser) and ser.index[-1] == freshest)
    history_stale = freshest is None or freshest < last_weekday or holey

    # THREE TIERS, AND THE SNAPSHOT IS NOT ONE OF THEM. It was, for about an
    # hour on 2026-09-28, and it was wrong in the most expensive way: its
    # session block reported settlement_price 335.00 for GFV6 when Friday
    # settled 334.925. That 335.00 is Friday's LAST TRADE. CME settles live and
    # feeder cattle on a weighted average of the closing range, so the last
    # trade and the settlement differ routinely -- by 0.025 to 0.075 across the
    # four contracts that day. Reading it as a settlement produced a wrong
    # number wearing the word "settlement", which is worse than no number.
    #
    # Its previous_settlement is no better: pre-open it read 334.925, which IS
    # Friday's settle, and by 08:52 the same field read 332.50 -- the 09-11
    # bar -- because once the session went active Massive recomputed it off the
    # broken daily series. A field that is right at 07:30 and wrong at 08:52 is
    # not a source, and the morning brief is built in that window.
    hourly, logged = {}, {}
    if history_stale:
        hourly = {t: _clip(session_closes_from_hourly(t, api_key)) for t in tickers}
        # OUR OWN BANKED SETTLES, which are real settlements and outrank an
        # hourly close. They also outlived Massive: the 09-23 and 09-24 values
        # here were recorded from bars the API has since retracted, and public
        # market reports confirm them to the half cent. See letter/settle_log.py.
        try:
            logged = settle_log.load()
        except Exception:
            logged = {}

    out = []
    for c in contracts:
        ticker = c["ticker"]
        s = series.get(ticker, pd.Series(dtype=float))

        # RECOVERY FILLS ONLY SESSIONS THE REAL HISTORY DOES NOT HAVE, in order
        # of how good the number is: a banked settlement first, an hourly close
        # only where there is nothing better. Splicing over a session that
        # already carries a settlement would swap it for a last trade and gain
        # nothing -- on 2026-09-11 those differed by 0.30.
        origin = {d: SETTLED for d in s.index}
        banked = _clip(pd.Series({
            pd.to_datetime(d).date(): float(v)
            for d, v in (logged.get(ticker) or {}).items()
        })) if logged.get(ticker) else pd.Series(dtype=float)

        for label, src in ((SETTLED, banked), (CLOSE_ONLY, hourly.get(ticker))):
            if src is None or not len(src):
                continue
            fill = src[~src.index.isin(s.index)] if len(s) else src
            if len(fill):
                # Concat only when there is something to concat to: pandas
                # deprecated inferring a dtype across empty entries, and an
                # empty settlement history is the normal case here.
                s = pd.concat([s, fill]).sort_index() if len(s) else fill.copy()
                origin.update({d: label for d in fill.index})

        if s.empty:
            continue

        last_date = s.index[-1]
        settle = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) > 1 else None
        prev_date = s.index[-2] if len(s) > 1 else None
        basis = origin.get(last_date, SETTLED)
        source = "settlement history" if last_date in series.get(
            ticker, pd.Series(dtype=float)).index else (
            "banked settlement" if basis == SETTLED else "hourly close")

        # NEVER SUBTRACT ACROSS A HOLE, AND NEVER ACROSS A CHANGE OF BASIS.
        #
        # The hole first: with no bars for 09-14..09-24 the bar before 09-25 is
        # 09-11, so settle - prev prints a fortnight's move as a daily change --
        # +4.95 on Oct feeders, on a day the market moved 3.175.
        #
        # The basis second, and it is subtler. Once the settle log fills 09-24
        # the two ends are adjacent again, but they are different KINDS of
        # number: Friday's last trade against Thursday's settlement gives +3.25
        # where the true settle-to-settle move is +3.175. That is a wrong figure
        # with every appearance of a right one, which is the whole family of
        # error this module keeps rediscovering. Mixed basis yields None and
        # the letter marks it.
        change_day = None
        if prev is not None and (last_date - prev_date).days <= MAX_SETTLE_AGE_DAYS \
                and origin.get(prev_date) == basis:
            change_day = round(settle - prev, 4)

        # THE PRIOR FRIDAY'S BAR MUST EXIST. Reaching further back when it is
        # missing is what made this quietly wrong: on 2026-09-22 the Massive
        # history had no bars at all for 09-14..09-18, so the "week" change fell
        # through to 09-11 and computed -0.90 where the letter's own arithmetic
        # (218.775 - 215.925) gives +2.85. A wrong number that looks right is
        # worse than a marked gap, so a missing base yields None.
        base_week = float(s.loc[prior_friday]) if prior_friday in s.index else None

        out.append({
            "ticker": ticker,
            "month": contract_month(ticker),
            "settle": settle,
            "settle_date": last_date.isoformat() if hasattr(last_date, "isoformat") else str(last_date),
            "settle_source": source,
            "settle_recovered": source != "settlement history",
            "settle_stale": (as_of - last_date).days > MAX_SETTLE_AGE_DAYS,
            "settle_basis": basis,
            "change_recovered": (origin.get(prev_date) != SETTLED
                                 if prev_date is not None else False),
            "change_missing": change_day is None,
            "change_day": change_day,
            "change_week": round(settle - base_week, 4) if base_week is not None else None,
            "week_base_date": prior_friday.isoformat(),
            "week_base_missing": base_week is None,
            "gaps": [d.isoformat() for d in session_gaps(s.index, prior_friday, as_of)],
        })
    return out


def session_gaps(index, start: date, end: date) -> list:
    """
    Weekdays with no bar between start and end, reported only in RUNS OF TWO OR
    MORE.

    A single missing weekday is almost always an exchange holiday -- 2026-09-07
    was Labor Day and the series steps 09-04 to 09-08. A run of them is a data
    gap, and the 09-14..09-18 hole is what corrupted both the weekly change and
    the moving averages without raising anything.
    """
    have = {d for d in index}
    missing, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in have:
            missing.append(d)
        d += timedelta(days=1)

    runs, run = [], []
    for d in missing:
        if run and (d - run[-1]).days <= 3:
            run.append(d)
        else:
            if len(run) >= 2:
                runs.extend(run)
            run = [d]
    if len(run) >= 2:
        runs.extend(run)
    return runs


# HOW STALE IS TOO STALE. Friday to Monday is three days, and a Monday holiday
# makes Friday to Tuesday four, so four tolerates every ordinary weekend and
# flags anything beyond one. Deliberately tighter than the five days
# MAX_PRIOR_SETTLE_AGE_DAYS allows an outside market: the cattle block IS the
# letter, and a marked gap is the safe failure.
MAX_SETTLE_AGE_DAYS = 4

# What KIND of number a value is, which matters as much as its date. A
# settlement is CME's weighted average of the closing range; a close is the
# last trade. They differ routinely -- by 0.025 to 0.075 across the four cattle
# contracts on 2026-09-25 -- so a move measured from one to the other is wrong
# in a way that looks entirely plausible.
SETTLED = "settled"
CLOSE_ONLY = "close"


def session_closes_from_hourly(ticker: str, api_key: str) -> pd.Series:
    """
    Daily closes rebuilt from the HOURLY bars, indexed by trading date.

    WHAT THIS IS FOR. Massive's own daily aggregation is the thing that breaks.
    On 2026-09-28 /aggs at resolution 1session AND 1day ended at 2026-09-11 for
    every CME cattle contract -- 343 bars, nothing after -- while 1hour on the
    same ticker carried 2026-09-25. Same trades, same API; only the job that
    rolls them up daily had stopped. CL, ZC and ES were current at every
    resolution that morning, so the hole is cattle-only and upstream.

    It is worse than a gap: bars that were served on Friday were RETRACTED over
    the weekend. letter/data/settle_log.json still holds 09-23 and 09-24 values
    that this endpoint no longer returns, which is why nothing downstream can
    treat "the newest bar" as meaning "the last session".

    A LAST HOURLY CLOSE IS NOT A SETTLEMENT PRICE. CME settles on a closing
    range, not the last trade; on 2026-09-11 the two differed by up to 0.30
    (GFX6 closed 328.475 and settled 328.175). So this is a recovery source and
    never a replacement -- fetch_futures prefers the real settlement history,
    then the snapshot's official settlement, and only then this.
    """
    api = _massive()
    try:
        data = api._get(f"/aggs/{ticker}", api_key,
                        params={"resolution": "1hour", "limit": 50000})
    except Exception:
        return pd.Series(dtype=float)

    rows = [b for b in data.get("results", []) if b.get("session_end_date")]
    # SORT BY window_start. These bars carry no "timestamp" field, and sorting
    # on a key that is always None is not an error -- it silently leaves the
    # API's own order, which is not chronological. That cost an hour.
    rows.sort(key=lambda b: b.get("window_start") or 0)

    closes: dict = {}
    for b in rows:
        price = b.get("close")
        if not price:
            continue
        closes[pd.to_datetime(b["session_end_date"]).date()] = float(price)
    return pd.Series(closes).sort_index() if closes else pd.Series(dtype=float)


def fetch_settlement_series(ticker: str, api_key: str) -> pd.Series:
    """Daily settles for one contract -- what the moving averages are built on."""
    return _massive().get_settlement_history(ticker, api_key)


# -- Cash trade: LM_CT150 weighted averages + LM_CT154 negotiated volume ------

def fetch_cash_trade() -> dict:
    """
    The five "last week's cash trade" bullets.

    USDA publishes this week's and last week's figures in the SAME report, so
    the week-ago comparison is read straight out rather than stored and diffed
    here -- there is no history to keep and nothing to drift.
    """
    sess = _session()

    r = sess.get(f"{LMR_BASE}/{CT150_ID}/History", timeout=120)
    r.raise_for_status()
    price = pd.DataFrame(r.json().get("results", []))

    out: dict = {"live": {}, "dressed": {}, "volume": {}, "report_date": None}

    if not price.empty:
        price["report_date"] = pd.to_datetime(price["report_date"], format="%m/%d/%Y", errors="coerce")
        for col in ("head_count", "weighted_avg_price"):
            price[col] = pd.to_numeric(
                price[col].astype(str).str.replace(",", "", regex=False), errors="coerce")
        price = price.dropna(subset=["report_date"])
        latest = price["report_date"].max()
        cur = price[price["report_date"] == latest]
        out["report_date"] = latest.date().isoformat()

        # Steer and Heifer are published separately; the letter quotes one
        # number, so combine head-count-weighted exactly as the dashboard does.
        for basis, key in (("Live", "live"), ("Dressed", "dressed")):
            for period, label in (("WEEKLY WEIGHTED AVERAGES", "this_week"),
                                  ("SAME PERIOD LAST WEEK", "last_week")):
                rows = cur[(cur["selling_basis_desc"] == basis) &
                           (cur["current_period"] == period)]
                rows = rows.dropna(subset=["head_count", "weighted_avg_price"])
                if rows.empty or rows["head_count"].sum() == 0:
                    out[key][label] = None
                    continue
                out[key][label] = round(
                    float((rows["head_count"] * rows["weighted_avg_price"]).sum()
                          / rows["head_count"].sum()), 2)

    r = sess.get(f"{LMR_BASE}/{CT154_ID}", timeout=60)
    r.raise_for_status()
    vol = pd.DataFrame(r.json().get("results", []))
    if not vol.empty:
        vol["report_date"] = pd.to_datetime(vol["report_date"], format="%m/%d/%Y", errors="coerce")
        vol = vol.dropna(subset=["report_date"]).sort_values("report_date")
        v = vol.iloc[-1]
        # _1 / _2 are USDA's suffixes for the 1-14 and 15-30 day delivery windows.
        out["volume"] = {
            "confirmed": _num(v.get("total_head_count")),
            "confirmed_last_week": _num(v.get("head_count_week_ago")),
            "d14": _num(v.get("total_head_count_1")),
            "d14_last_week": _num(v.get("head_count_week_ago_1")),
            "d30": _num(v.get("total_head_count_2")),
            "d30_last_week": _num(v.get("head_count_week_ago_2")),
            "report_date": v["report_date"].date().isoformat(),
        }
    return out


# -- Boxed beef: LM_XB403 cutout + LSWFEDCC grading ---------------------------

def fetch_cutout() -> dict:
    """Choice/Select PM cutout, the session change, 5-day averages, grading %."""
    sess = _session()
    r = sess.get(f"{LMR_BASE}/{XB403_ID}/",
                 params={"lastReports": 30, "allSections": "true"}, timeout=60)
    r.raise_for_status()
    payload = r.json()
    sections = {}
    for sec in (payload if isinstance(payload, list) else [payload]):
        if sec.get("results"):
            df = pd.DataFrame(sec["results"])
            df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
            sections[sec.get("reportSection", "")] = (
                df.dropna(subset=["report_date"]).sort_values("report_date"))

    cut = sections.get("Current Cutout Values", pd.DataFrame())
    out: dict = {}
    if not cut.empty:
        cut = cut.copy()
        cut["choice"] = pd.to_numeric(cut.get("choice_600_900_current"), errors="coerce")
        cut["select"] = pd.to_numeric(cut.get("select_600_900_current"), errors="coerce")
        for key in ("choice", "select"):
            s = cut[cut[key].notna()]
            if s.empty:
                continue
            cur = float(s.iloc[-1][key])
            prev = float(s.iloc[-2][key]) if len(s) > 1 else None
            out[key] = {
                "value": round(cur, 2),
                "change": round(cur - prev, 2) if prev is not None else None,
                # THE 5-DAY AVERAGE EXCLUDES THE DAY BEING REPORTED.
                #
                # It is the five sessions BEFORE this print, so it is a fixed
                # benchmark the new number is read against rather than a window
                # that moves with it. Including today makes the average chase
                # the print: a sharp day drags its own comparison toward itself
                # and the gap understates the move.
                #
                # This was `tail(5)` -- including today -- until 2026-10-06, and
                # the two conventions disagree by real money. For Monday
                # 2026-10-05: excluding today gives Choice 379.38 / Select
                # 358.14, including it gives 378.94 / 358.20. The first pair is
                # what the Cattle Market Rundown slide has always carried,
                # hand-typed, and the letter was quietly printing the other one.
                # Neither is wrong in isolation, which is exactly why it went
                # unnoticed -- see CLAUDE.md on the letter and a dashboard
                # disagreeing about the same figure.
                #
                # Needs SIX rows now, not five, because one of them is dropped.
                "avg5": (round(float(s[key].iloc[-6:-1].mean()), 2)
                         if len(s) >= 6 else None),
            }
        out["report_date"] = cut["report_date"].max().date().isoformat()

    r = sess.get(f"{LMR_BASE}/{GRADING_ID}/",
                 params={"lastReports": 10, "allSections": "true"}, timeout=60)
    r.raise_for_status()
    payload = r.json()
    for sec in (payload if isinstance(payload, list) else [payload]):
        if sec.get("reportSection") == "Weekly Fed Cattle Comprehensive":
            g = pd.DataFrame(sec["results"])
            g["report_date"] = pd.to_datetime(g["report_date"], errors="coerce")
            g["pct"] = pd.to_numeric(g.get("Pct_Choice_CW"), errors="coerce")
            # USDA'S OWN PRIOR WEEK, NOT THE PREVIOUS ROW WE HAPPEN TO HOLD.
            #
            # Pct_Choice_PW sits on the same row as Pct_Choice_CW and is the
            # figure USDA is comparing against. Taking g.iloc[-2] instead meant
            # "last week" was whatever row came before in the fetched window,
            # which is only the prior week while the series is contiguous --
            # and this one is not. The live LSWFEDCC history has a 561-day hole
            # between report dates 2024-09-16 and 2026-03-31, and replaying the
            # old code as of 2026-03-31 printed "89.3 versus 82.6 LW", a
            # fabricated 6.7-point weekly swing where USDA's own field on that
            # very row said flat.
            #
            # Same error as the futures block's: a difference taken across a
            # hole, plausible on its face, with nothing marking it. Here the
            # right answer was already in the response.
            g["pct_pw"] = pd.to_numeric(g.get("Pct_Choice_PW"), errors="coerce")
            g = g.dropna(subset=["report_date", "pct"]).sort_values("report_date")
            if not g.empty:
                last = g.iloc[-1]
                pw = last.get("pct_pw")
                out["grading"] = {
                    "pct": round(float(last["pct"]), 1),
                    # None rather than a neighbour when USDA withholds it: a
                    # marked gap beats a number measured from the wrong week.
                    "pct_last_week": round(float(pw), 1) if pd.notna(pw) else None,
                    "report_date": last["report_date"].date().isoformat(),
                }
            break
    return out


# -- Slaughter and carcass weights: AMS SJ_LS712 ------------------------------

def _parse_ls712_date(s: str):
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def parse_3208(text: str) -> dict:
    """
    Pull the Cattle row out of AMS report 3208's extracted text.

    The report has two blocks -- Current Day and Previous Day -- each a table of
    species rows. Both contain a "Cattle" line, and the FIRST is the current
    day, which is the one the letter quotes. A third "Cattle" appears in the
    Previous Day Breakdown (Steers/Heifers, Cows/Bulls) and is skipped because
    it is reached only after nine numbers have already been collected.

    Columns, in the order they extract:

        current_day, day_week_ago, day_year_ago,
        wtd, wtd_week_ago, wtd_year_ago,
        ytd, ytd_prev_year, ytd_pct_change

    Verified against the 9/15/26 letter: the 9/22 report's day_week_ago (108,000)
    and wtd_week_ago (211,000) are exactly what that letter printed as its own
    daily and WTD figures.

    A bare "R" between values marks a revised figure and is skipped -- it is a
    footnote, not a column, and treating it as one would shift everything after
    it by a place.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    try:
        start = lines.index("Cattle")
    except ValueError:
        return {}

    vals = []
    for ln in lines[start + 1:]:
        if ln == "R":
            continue
        try:
            vals.append(float(ln.replace(",", "").replace("%", "")))
        except ValueError:
            break
        if len(vals) == 9:
            break

    if len(vals) < 9:
        return {}

    keys = ["current_day", "day_week_ago", "day_year_ago",
            "wtd", "wtd_week_ago", "wtd_year_ago",
            "ytd", "ytd_prev_year", "ytd_pct_change"]
    out = dict(zip(keys, vals))

    m = re.search(r"Report for (\w+ \d+, \d{4})\s*-\s*(\w+)", text)
    if m:
        try:
            out["report_date"] = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
        # "Final" or "Preliminary". An early-afternoon run can catch a
        # preliminary print, and the letter should not quote one unknowingly.
        out["status"] = m.group(2)
    return out


def fetch_daily_slaughter() -> dict:
    """Daily and week-to-date cattle slaughter from AMS report 3208."""
    from pypdf import PdfReader

    r = _session().get(AMS_3208_PDF, timeout=40)
    r.raise_for_status()
    reader = PdfReader(io.BytesIO(r.content))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    return parse_3208(text)


# -- Carcass weights: AMS MARS report 3658 -----------------------------------
# The SAME source the Cattle Weights dashboard uses, which is where Ross reads
# this figure. Mirrored from apps/beef_weight/app.py (see module docstring) and
# guarded by tests/test_letter_drift.py.
#
# Deliberately NOT the "Average Weights" table in SJ_LS712. That table carries
# USDA's weekly ESTIMATE and reads 889# where 3658's actual for the week Ross
# was quoting read 887#. Two defensible numbers, but only one is the series the
# letter has been printing, and quietly swapping series is how a letter starts
# disagreeing with the dashboard it is supposed to summarise.
MARS_BASE = "https://marsapi.ams.usda.gov/services/v1.2/reports"
FIS_REPORT_ID = 3658
# A PATH SEGMENT, NOT A QUERY PARAM -- "?section=" is accepted, ignored, and
# returns the header with zero rows and HTTP 200.
FIS_SECTION = "Report FIS Meat Production"


def fetch_carcass_weights() -> dict:
    """
    Weekly actual FIS dressed weight from AMS MARS 3658, Cattle AND Steers.

    The Cattle figures stay at the top level and Steers sits under "steers",
    so nothing that already read this function has to change.

    Published Thursday, covering the week that ended about twelve days earlier,
    so on a Tuesday the newest row is roughly a fortnight old. That lag is the
    series behaving normally, not a stale fetch. It is wide enough to mislead:
    the Cattle Market Rundown slide carried "as of 8/19/26" for a week ending
    2026-09-19, a hand-typed month that nobody caught because a four-week-old
    weight looks no different from a two-week-old one. The week_ending is
    returned so it can be PRINTED rather than remembered.

    Needs MARS_API_KEY -- the same secret Beef Trimmings already uses, so no new
    credential. Returns {} with an error key rather than raising.
    """
    from urllib.parse import quote

    import os
    key = (os.environ.get("MARS_API_KEY") or "").strip()
    if not key:
        return {"error": "MARS_API_KEY not configured"}

    r = _session().get(f"{MARS_BASE}/{FIS_REPORT_ID}/{quote(FIS_SECTION)}",
                       auth=(key, ""), timeout=(5, 120))
    if r.status_code in (204, 404):
        return {"error": f"AMS returned HTTP {r.status_code}"}
    r.raise_for_status()

    # TWO CLASSES, ONE REQUEST. 3658 carries Cattle, Steers, Heifers, Cows and
    # Bulls as separate `class` values in the same section, so the Steers line
    # the rundown slide quotes costs no extra call -- only a second bucket.
    by_class = {"Cattle": {}, "Steers": {}}
    for x in r.json().get("results", []):
        if str(x.get("commodity", "")).strip() != "Slaughter Cattle":
            continue
        if str(x.get("description", "")).strip() != "Dressed Weight":
            continue
        cls = str(x.get("class", "")).strip()
        if cls not in by_class:
            continue
        # Unit guard, as in the dashboard: a silent unit rename would land as a
        # plausible wrong number rather than an error.
        if str(x.get("unit", "")).strip().lower() != "lbs":
            continue
        # 3658 has NO report_date field. The END date is the week ending.
        wk = x.get("report_end_date") or x.get("report_begin_date")
        val = _num(x.get("volume"))
        if not wk or val is None:
            continue
        try:
            d = datetime.strptime(str(wk).split()[0], "%m/%d/%Y").date()
        except ValueError:
            continue
        by_class[cls][d] = val

    if not by_class["Cattle"]:
        return {"error": "no Slaughter Cattle / Dressed Weight rows in report 3658"}

    def _block(by_date: dict) -> dict:
        if not by_date:
            return {}
        last = max(by_date)
        return {
            "value": by_date.get(last),
            "week_ending": last.isoformat(),
            "last_week": by_date.get(last - timedelta(days=7)),
            # same weekday, 52 weeks back
            "year_ago": by_date.get(last - timedelta(days=364)),
        }

    out = _block(by_class["Cattle"])
    # Nested rather than flattened, so every existing caller keeps reading the
    # Cattle figures off the top level exactly as before.
    out["steers"] = _block(by_class["Steers"])
    return out


# -- CFTC Commitments of Traders ---------------------------------------------
# Managed money net long for the Friday letter's CFTC block.
#
# THE VARIANT IS LOAD-BEARING. This must be the DISAGGREGATED, FUTURES-ONLY
# report. Verified against the 9/18/26 letter: futures-only gives Live Cattle
# 47,696 / -1,209 and Feeder 7,211 / -237, matching to the contract. The
# futures-and-options-combined set gives 45,262 / -1,987 and 6,701 / -81, and
# the legacy commercial/non-commercial breakdown flips Feeder Cattle to a NET
# SHORT of 3,853 -- which would invert the market read. All three return
# plausible cattle numbers, so a wrong choice here fails silently.
#
# THE DATASET ID IS ALSO LOAD-BEARING. publicreporting.cftc.gov carries a
# frozen duplicate (ubmb-6exi) last updated in 2022. It answers happily with
# four-year-old positions and no error.
CFTC_DATASET = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
CFTC_MARKETS = {
    "057642": "Live Cattle",
    "061641": "Feeder Cattle",
}


def fetch_cftc() -> dict:
    """
    Latest managed money net long and week-on-week change for both cattle
    contracts, plus the report's as-of date.

    Net long is long minus short. The spread column is deliberately excluded --
    including it does not reproduce the letter.

    FILTERED ON cftc_contract_market_code, NEVER ON cftc_commodity_code. The
    commodity code comes back in two whitespace variants ('057' and '057 '), so
    an equality filter on it silently drops rows.
    """
    params = {
        "$select": ("report_date_as_yyyy_mm_dd,cftc_contract_market_code,"
                    "m_money_positions_long_all,m_money_positions_short_all,"
                    "change_in_m_money_long_all,change_in_m_money_short_all"),
        "$where": "cftc_contract_market_code in('057642','061641')",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": 8,
    }
    r = _session().get(CFTC_DATASET, params=params, timeout=60)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return {}

    as_of = max(row["report_date_as_yyyy_mm_dd"] for row in rows)[:10]
    out = {"as_of": as_of, "markets": {}}
    for row in rows:
        if row["report_date_as_yyyy_mm_dd"][:10] != as_of:
            continue
        name = CFTC_MARKETS.get(row["cftc_contract_market_code"])
        if not name:
            continue
        long_, short = int(row["m_money_positions_long_all"]), int(row["m_money_positions_short_all"])
        d_long = int(row["change_in_m_money_long_all"])
        d_short = int(row["change_in_m_money_short_all"])
        out["markets"][name] = {"net_long": long_ - short, "wow": d_long - d_short}
    return out


def cftc_is_current(cftc: dict, issue: date) -> bool:
    """
    True when the fetched report is the one for the issue's own week.

    THE TIMING TRAP. CFTC releases Friday at 3:30pm ET, as-of the Tuesday three
    days earlier. A Friday letter built before 3:30 gets LAST week's report with
    no error at all -- correct-looking positions that are a week stale. Callers
    warn on False rather than printing it silently.
    """
    as_of = cftc.get("as_of")
    if not as_of:
        return False
    tuesday = issue - timedelta(days=(issue.weekday() - 1) % 7)
    return as_of == tuesday.isoformat()


# -- Regional cash cattle trade ----------------------------------------------
# The Friday letter's "Cash Cattle Trade" block: North and South negotiated
# ranges. AMS has no north/south field, so the regions are assembled from the
# per-state daily reports -- North being Nebraska plus the Western Cornbelt.
#
# Verified against 9/18/26: min low / max high of LIVE FOB across NE and IA-MN,
# restricted to STEER and HEIFER, gives 220.00-222.50, exactly the letter's
# "North: 220-222.50 FOB live".
#
# THE CLASS FILTER IS NOT COSMETIC. Including MIXED STEER/HEIFER or the
# ALL BEEF TYPE rollup widens it to 218.00-222.50, and DAIRYBRED rows drag the
# dressed range down to 320.00.
CASH_REGIONS = {
    "North": {2667: "Nebraska", 2671: "Iowa/Minnesota"},
    "South": {2663: "TX/OK/NM", 2665: "Kansas"},
}
CASH_CLASSES = ("STEER", "HEIFER")


def _cash_rows(slug: int, on: date) -> list:
    """
    Detail rows for one region on one day, or [] when nothing was published.

    AMS ANSWERS 200 WITH A BARE JSON STRING when a date has no report -- not an
    error status, not an empty list, not an object with zero results. Iterating
    that as sections walks its CHARACTERS and dies on str.get, which is how a
    perfectly ordinary "no trade that day" took the whole section down. Every
    shape other than the documented one is treated as no rows.
    """
    r = _session().get(f"{LMR_BASE}/{slug}/Detail",
                       params={"q": f"report_date={on.strftime('%m/%d/%Y')}"}, timeout=60)
    if r.status_code in (204, 404):
        return []
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError:
        return []

    if isinstance(payload, dict):
        results = payload.get("results")
        return results if isinstance(results, list) else []
    if isinstance(payload, list):
        out = []
        for sec in payload:
            if isinstance(sec, dict) and isinstance(sec.get("results"), list):
                out.extend(sec["results"])
        return out
    return []


# The same daily reports, kept flat and abbreviated the way the morning brief
# names them -- "NE 221.00-222.50 live, 350 dressed" rather than a North/South
# rollup. The evening letter still wants the rollup; this is a different read of
# the same four slugs.
# THE SUMMARY REPORTS, NOT THE AFTERNOON ONES -- and the difference is not
# cosmetic. Nebraska on Monday 2026-09-21: the Afternoon report carried ZERO
# priced rows while the Summary carried nine, so a week-to-date built on
# Afternoon silently dropped Nebraska from a week it had traded.
#
# The evening letter still uses the Afternoon reports, deliberately. Written on
# a Friday evening, that is the latest print available, and it is what Ross
# quoted: 9/18 Afternoon gives the letter's 220-222.50, while the Summary for
# the same day runs to 224.00 because it includes trade confirmed later. Same
# day, two honest answers to two different questions -- "what is out now" and
# "what did the day finally do".
# (label, FINAL slug, 1:30 PM CUT slug) -- the same eight reports the Cash
# Cattle Trade dashboard reads, and for the same reason.
#
# USDA PUBLISHES EACH REGION TWICE A DAY AND THE TWO FILES DESCRIBE DIFFERENT
# TRADING DAYS. The afternoon file (~15:08 CT) is dated its trading day and
# carries that day's trade as of the 1:30 pm cut, still moving. The morning
# file (~11:17 CT) is dated the day it is PUBLISHED and carries the PREVIOUS
# business day's COMPLETE trade.
#
# This list held the morning slugs alone until 2026-10-16, and both halves of
# that were wrong:
#
#   The Monday-dated morning file is FRIDAY's trade, so every week-to-date
#   opened with last week's number counted as this week's. On Friday
#   2026-10-16 the letter printed "NE: 218.00-223.00 live" -- Nebraska's
#   trade of Friday 2026-10-09 -- while the dashboard showed 225. Ross put
#   the two side by side; nothing else would have.
#
#   And the current trading day exists ONLY in the afternoon file, because
#   its own final file is not published until the next morning. So the day
#   the letter is actually about was the one day it could never see.
#
# Reading the morning file alone was itself a fix, for a real symptom: on
# Monday 2026-09-21 Nebraska's afternoon file carried zero priced rows and
# the morning one carried nine, so an afternoon-only week-to-date dropped a
# state that had traded. Both observations are correct and neither rule is --
# the file is not the unit, the TRADING DAY is.
CASH_STATES = [
    ("NE", 2668, 2667),           # LM_CT124 / LM_CT123
    ("IA/MN", 2672, 2671),        # LM_CT137 / LM_CT136
    ("TX/OK/NM", 2664, 2663),     # LM_CT118 / LM_CT117
    ("KS", 2666, 2665),           # LM_CT121 / LM_CT120
]

# USDA prints each class once per grade AND once as a roll-up. Summing both
# double-counts: Nebraska steers on the 10/12 file are 5,458 + 178 graded
# against a 5,636 total, and the old code added all three to 11,094. Only the
# roll-up is kept, which is the filter the dashboard already applies.
CASH_GRADE_TOTAL = "Total all grades"


def _prev_business_day(d: date) -> date:
    """
    The session before `d`, skipping weekends.

    HOLIDAYS ARE NOT SKIPPED, the same limitation the dashboard's BDay shift
    carries: a morning file published the day after a holiday resolves to the
    holiday rather than the last session that traded. It is off by one session
    on a few dates a year and the tell is a holiday carrying a full day of
    trade. Worth knowing before trusting a Tuesday-after-Monday-holiday range.
    """
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _cash_rows_between(slug: int, start: date, end: date) -> list:
    """
    Detail rows for one report over a RANGE of file dates.

    One request per slug rather than one per day -- the datamart takes
    `report_date=MM/DD/YYYY:MM/DD/YYYY`, so a week costs 8 requests instead
    of 40. The grade filter is passed to the server as an optimisation and
    re-checked below, because only one extra filter can be chained before AMS
    returns its bare-string no-results sentinel instead of an intersection.
    """
    q = (f"report_date={start.strftime('%m/%d/%Y')}:{end.strftime('%m/%d/%Y')}"
         f";grade_desc={CASH_GRADE_TOTAL}")
    r = _session().get(f"{LMR_BASE}/{slug}/Detail", params={"q": q}, timeout=60)
    if r.status_code in (204, 404):
        return []
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError:
        return []
    if isinstance(payload, dict):
        results = payload.get("results")
        return results if isinstance(results, list) else []
    if isinstance(payload, list):
        out = []
        for sec in payload:
            if isinstance(sec, dict) and isinstance(sec.get("results"), list):
                out.extend(sec["results"])
        return out
    return []


def _cash_by_trading_day(label_slugs, monday: date, as_of: date) -> dict:
    """
    {trading_day: {cut: {basis: [(low, high, head), ...]}}} for one region.

    The file window is Monday..as_of for BOTH reports, which lands exactly the
    trading days wanted and no others:

        final file Tue..Fri  -> trading Mon..Thu      (kept)
        final file Mon       -> trading LAST Friday   (dropped, out of week)
        cut file   Mon..Fri  -> trading Mon..Fri      (kept)

    So today appears through its 1:30 pm cut, and every earlier day through
    its completed final file. Today has no final file; it is published
    tomorrow morning.
    """
    _label, final_slug, cut_slug = label_slugs
    by_day = {}
    for cut, slug in (("final", final_slug), ("cut", cut_slug)):
        for row in _cash_rows_between(slug, monday, as_of):
            if str(row.get("purchase_type_code", "")).strip() != "NEGOTIATED CASH":
                continue
            if str(row.get("class_desc", "")).strip() not in CASH_CLASSES:
                continue
            if str(row.get("grade_desc", "")).strip() != CASH_GRADE_TOTAL:
                continue
            lo = _num(row.get("price_range_low"))
            hi = _num(row.get("price_range_high"))
            if lo is None or hi is None:
                continue
            basis = str(row.get("selling_basis_desc", "")).strip()
            if basis == "LIVE FOB":
                key = "live"
            elif basis.startswith("DRESSED"):
                key = "dressed"
            else:
                continue
            try:
                filed = datetime.strptime(
                    str(row.get("report_date", "")).strip(), "%m/%d/%Y").date()
            except ValueError:
                continue
            traded = _prev_business_day(filed) if cut == "final" else filed
            if not (monday <= traded <= as_of):
                continue
            slot = by_day.setdefault(traded, {}).setdefault(cut, {})
            slot.setdefault(key, []).append((lo, hi, _num(row.get("head_count")) or 0))
    return by_day


def fetch_regional_cash_wtd(as_of: date) -> dict:
    """
    Week-to-date negotiated cash by state, Monday through as_of, keyed on the
    TRADING day rather than the file date.

    A single day is the wrong window for a morning brief: Monday is routinely
    untested, so a Tuesday brief built from Monday alone says "no established
    test" while the week has in fact traded. Ranges span every priced day of the
    week so far, and `days` records how many actually carried a price.

    **WHICH FILE A PRICE CAME FROM IS THE WHOLE CORRECTNESS OF THIS** -- see
    CASH_STATES for what reading one of the two did to the 2026-10-16 letter.
    Each row is moved to the day it describes, and then:

      ONE CUT PER TRADING DAY, FINAL PREFERRED. The final file is the same
      day's trade completed -- more head, usually a wider range -- so taking
      both would count the day twice and let the partial drag the range. This
      is the rule the dashboard's daily_price_state already states: "final cut
      preferred over the 1:30 pm cut".

    Same class filter as the evening letter -- STEER and HEIFER only. Adding
    MIXED or the ALL BEEF TYPE rollup widens the range, and DAIRYBRED drags
    dressed down. Only the "Total all grades" roll-up is read; see
    CASH_GRADE_TOTAL for the double count that caused.
    """
    monday = as_of - timedelta(days=as_of.weekday())

    out = {"from": monday.isoformat(), "to": as_of.isoformat(), "regions": {}}
    for entry in CASH_STATES:
        label = entry[0]
        by_day = _cash_by_trading_day(entry, monday, as_of)
        lows = {"live": [], "dressed": []}
        highs = {"live": [], "dressed": []}
        head, days = 0.0, set()
        for traded in sorted(by_day):
            cuts = by_day[traded]
            chosen = cuts.get("final") or cuts.get("cut") or {}
            for key, rows in chosen.items():
                for lo, hi, hd in rows:
                    lows[key].append(lo)
                    highs[key].append(hi)
                    if key == "live":
                        head += hd
                if rows:
                    days.add(traded)
        out["regions"][label] = {
            "live_low": min(lows["live"]) if lows["live"] else None,
            "live_high": max(highs["live"]) if highs["live"] else None,
            "dressed_low": min(lows["dressed"]) if lows["dressed"] else None,
            "dressed_high": max(highs["dressed"]) if highs["dressed"] else None,
            "head": int(head) or None,
            "days": len(days),
            "undefined": not lows["live"] and not lows["dressed"],
        }
    return out


# -- Outside markets, for the morning brief ----------------------------------
# Corn is feed cost, equities are risk appetite, crude moves both. Fetched
# through the same Massive client the Seasonal dashboard uses.
#
# THESE ARE THE ONLY ONES WITH A REAL OVERNIGHT MOVE AT 8:30am CENTRAL. CME
# livestock futures do not open until 08:30 CT, so there is no overnight cattle
# print to report -- grain and equities have traded through the night and are
# where the morning signal actually is. Dollar Index is deliberately absent:
# Massive returns no contracts for DX.
# "eighths" quotes in whole cents and eighths -- 531.25 prints as 531'2, the way
# the grain trade writes it and the way Ross writes it ("5'4 lower at 531'2").
# Corn, wheat, oats and soybeans trade in eighths; meal, equities and crude are
# plain decimals.
OUTSIDE_MARKETS = [
    ("ZC", "Corn", "eighths"),
    # Directly under corn, because the order here IS the order on the page and
    # the two are read together -- beans set the acreage fight that decides
    # next year's corn crop, and the meal side of the board is a feed cost.
    ("ZS", "Soybeans", "eighths"),
    ("ES", "S&P", "decimal"),
    ("CL", "Crude", "decimal"),
]


def front_contracts(product_code: str, api_key: str, as_of: date, n: int = 1) -> list:
    """
    The n nearest outright contracts, following /contracts pagination.

    massive_api.get_active_contract_tickers() reads ONE page. That is fine for
    cattle and corn, whose listings are mostly outrights, and silently wrong for
    crude: CL's page is dominated by spread and butterfly combos, the response
    caps at 1000 rows, and the near months fall off the end. On 2026-09-23 it
    returned six CL outrights, all January and February, so the brief quoted
    CLF7 at 86.85 while the actual front month CLX6 was 91.94 -- five dollars
    away, with nothing to show anything was wrong.

    Following next_url fixes it without touching the shared dashboard module.
    """
    api = _massive()
    seen, url, params = {}, "/contracts", {
        "product_code": product_code, "active": "true",
        "date": as_of.isoformat(), "limit": 1000,
    }
    for _ in range(12):                      # bounded: a runaway feed cannot hang a build
        data = api._get(url, api_key, params=params) if params else api._get(url, api_key)
        for r in data.get("results", []):
            ticker = r.get("ticker", "")
            if not api._is_outright_ticker(ticker, product_code):
                continue
            when = r.get("settlement_date") or r.get("last_trade_date")
            if when:
                seen.setdefault(ticker, when)
        nxt = data.get("next_url")
        if not nxt:
            break
        # next_url is absolute; strip the base so _get can prepend it again.
        url, params = nxt.replace(api.BASE_URL, ""), None

    rows = [{"ticker": t, "expiration": w} for t, w in seen.items()]
    rows.sort(key=lambda r: r["expiration"])
    live = [r for r in rows if str(r["expiration"])[:10] >= as_of.isoformat()]
    return (live or rows)[:n]


# How many CALENDAR days back the prior session's settle may sit before the gap
# is a hole rather than a weekend. Fri->Tue over a Monday holiday is 4; Massive's
# 2026-09-14..09-18 outage was 7 and must never be quoted as one session's move.
MAX_PRIOR_SETTLE_AGE_DAYS = 5


def _prior_settle(api, ticker: str, api_key: str, as_of: date):
    """
    The last settle STRICTLY BEFORE as_of, with its date, from the history.

    Strictly before, because the history's newest bar is today's own in-progress
    session -- differencing against that gave corn -0.25 where the real overnight
    move was -9.00.

    Returns (settle, date) or (None, None) when the newest usable bar is too old
    to be the previous session. A multi-session move quoted as an overnight one
    is a wrong number that looks right, so the brief marks it [[?]] instead.
    """
    hist = api.get_settlement_histories([ticker], api_key).get(ticker)
    if hist is None:
        return None, None
    prior = hist.dropna()
    prior = prior[prior.index < as_of]
    if prior.empty:
        return None, None
    when = prior.index[-1]
    when = when.date() if hasattr(when, "date") else when
    if (as_of - when).days > MAX_PRIOR_SETTLE_AGE_DAYS:
        return None, None
    return float(prior.iloc[-1]), when


def fetch_front_history(product_code: str, api_key: str, as_of: date,
                        sessions: int = 60, completed_only: bool = True) -> dict:
    """
    The front contract's last N settles, for the chart of the day.

    Reuses the series technicals already pulls, so this is one more call against
    a response the build is fetching anyway rather than a new source with a new
    way to fail. completed_only by default because the morning brief quotes
    settled sessions and a chart ending on a half-finished bar would contradict
    the numbers printed beside it.

    Returns {} rather than raising: a missing chart is a letter without a chart.
    """
    try:
        api = _massive()
        # front_contracts, NOT get_active_contract_tickers. The latter reads one
        # page, and for CL that page is mostly spread and butterfly combos with
        # the near months falling off the end -- on 2026-09-24 it answered CLF7
        # where the front month was CLX6, five dollars away. Harmless for cattle
        # and corn, wrong for crude, and the chart pool contains crude.
        contracts = front_contracts(product_code, api_key, as_of, n=1)
        if not contracts:
            return {}
        ticker = contracts[0]["ticker"]
        s = api.get_settlement_histories([ticker], api_key).get(ticker)
        if s is None:
            return {}
        s = s.dropna()
        s = s[s.index < as_of] if completed_only else s[s.index <= as_of]
        s = s.tail(int(sessions))
        if len(s) < 5:
            return {}

        # A STALE OR HOLED SERIES IS WORSE THAN NO CHART, because the chart is
        # printed beside the numbers it is supposed to illustrate. On
        # 2026-09-28 this returned GFV6's 60 sessions ending 2026-09-11 at
        # 332.50, and it would have been drawn on the same page as "Oct
        # feeders: 334.925" -- a picture quietly contradicting the text, with
        # the whole 09-12..09-25 move simply absent from it.
        #
        # Returning {} rather than recovering, deliberately: the hole is
        # unrecoverable at any resolution (Massive's /trades has zero ticks for
        # every day of it), so the best a filled series could do is join 09-11
        # to 09-25 with a straight line through a fortnight that is not there.
        # build_chart falls through to the next market in the pool, and corn,
        # crude and the S&P were all current throughout.
        last_weekday = as_of - timedelta(days=1) if completed_only else as_of
        while last_weekday.weekday() >= 5:
            last_weekday -= timedelta(days=1)
        if s.index[-1] < last_weekday - timedelta(days=MAX_SETTLE_AGE_DAYS):
            return {}
        if session_gaps(s.index, s.index[0], s.index[-1]):
            return {}

        return {"ticker": ticker,
                "month": contract_month(ticker),
                "dates": list(s.index),
                "values": [float(v) for v in s.values],
                "sessions": len(s)}
    except Exception:
        return {}


def fetch_outside_markets(api_key: str, as_of: date) -> list:
    """
    Front-month price and overnight change for each outside market.

    THE BASE COMES FROM THE SETTLEMENT HISTORY, NOT THE SNAPSHOT. This used to
    trust session.previous_settlement and session.change on the grounds that
    Massive already carries both, and on 2026-09-24 that was wrong by a whole
    session for crude: the CLX6 snapshot reported previous_settlement 90.52,
    which is Tuesday 09-22, while Wednesday 09-23 settled 92.16. The brief
    printed Nov Crude +3.26 against a real overnight move of +1.41, and nothing
    anywhere said so. Corn and the S&P agreed with the history that same
    morning, which is exactly why it went unnoticed -- one instrument out of
    three, on a field the code had been told to trust.

    The history is the same series the futures block already reads and it is
    dated, so "the settle before today" is a fact rather than a label. The
    snapshot's own figure is still recorded for comparison, because the two
    disagreeing is worth being able to see after the fact.
    """
    api = _massive()
    out = []
    for code, label, style in OUTSIDE_MARKETS:
        row = {"code": code, "label": label, "style": style,
               "price": None, "change": None, "month": None, "ticker": None}
        try:
            contracts = front_contracts(code, api_key, as_of, n=1)
            if contracts:
                front = contracts[0]["ticker"]
                snap = api.get_snapshots([front], api_key).get(front, {})
                session = snap.get("session") or {}
                price = (session.get("settlement_price")
                         or (snap.get("last_trade") or {}).get("price")
                         or session.get("close"))
                prior, prior_date = _prior_settle(api, front, api_key, as_of)
                snap_prior = session.get("previous_settlement")

                # No dated base means no change. Falling back to the snapshot
                # here would reinstate the bug on exactly the days the history
                # is unreliable, which are the days it matters most.
                change = (float(price) - prior) if (price is not None and prior) else None

                row.update({
                    "ticker": front, "month": contract_month(front),
                    "price": round(float(price), 4) if price else None,
                    "prior_settle": round(prior, 4) if prior else None,
                    "prior_settle_date": prior_date.isoformat() if prior_date else None,
                    "snapshot_prior_settle": (round(float(snap_prior), 4)
                                              if snap_prior else None),
                    "snapshot_disagrees": bool(
                        prior and snap_prior and abs(float(snap_prior) - prior) > 0.0001),
                    "change": round(float(change), 4) if change is not None else None,
                })
        except Exception:
            pass
        out.append(row)
    return out


# -- USDA release calendar ----------------------------------------------------
# What prints today. The highest value-per-second line in a morning brief: it
# says what to be ready for. Same ESMIS endpoint and publication ids the
# Seasonal dashboard uses for its report vlines.
ESMIS_BASE = "https://esmis.nal.usda.gov/api/v1"

# THE MONTHLY REPORTS ONLY. Weekly rhythms -- carcass weights, CFTC, weekly
# meat production -- are deliberately absent: they recur on the same weekday
# every week, so listing them is a line the reader already knows and skips, and
# in a three-minute brief that costs more than it gives.
#
# IDS, NOT SLUGS, AND CHECKED. Several near-misses exist: "Cold Storage Annual
# Summary" (1190) and "Weekly Cold Storage Holdings" (1867) are not "Cold
# Storage" (2111), and "Historical Track Record - Grain Stocks" (58) is not
# "Grain Stocks" (1480). The web slugs are not guessable either -- Cattle on
# Feed lives at /publication/cattle-feed, not /cattle-on-feed.
ESMIS_PUBLICATIONS = {
    "WASDE": 1659,
    "Cattle on Feed": 2270,
    "Cold Storage": 2111,
    "Grain Stocks": 1480,
    "Crop Production": 1632,
}

# The window is the REST OF THIS MONTH, not a rolling number of days. A week is
# wrong for monthly reports -- most weeks show nothing and the section reads as
# broken -- and a fixed 45 days makes "this month" mean something different
# every morning.
#
# Late in a month that leaves little or nothing, so it rolls into the following
# month when fewer than MIN_ITEMS remain. The heading says Upcoming rather than
# naming a month, so extending it is not a contradiction.
CALENDAR_MIN_ITEMS = 2

_WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def fetch_report_calendar(as_of: date) -> dict:
    """
    The monthly USDA reports due between today and roughly six weeks out.

    READS upcoming_releases FROM /publication/findById. The obvious endpoint,
    /release/findByPubId, is an ARCHIVE -- it returns only releases that have
    already happened, newest first, so a forward calendar built on it comes back
    empty and looks like a bug rather than a wrong source. The publication
    record carries the scheduled dates directly, as ISO timestamps.

    Forward-looking on purpose: a WASDE or a Cattle on Feed a fortnight out
    changes how the month is traded, and a reader who first hears about it on
    the morning is hearing too late.
    """
    # End of the current month, then the end of the next, as a fallback.
    def _month_end(d):
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    this_month_end = _month_end(as_of)
    horizon = _month_end(this_month_end + timedelta(days=1))
    sess = _session()
    scheduled = []

    for name, pub_id in ESMIS_PUBLICATIONS.items():
        try:
            r = sess.get(f"{ESMIS_BASE}/publication/findById/{pub_id}", timeout=25)
            r.raise_for_status()
            payload = r.json()
        except (requests.RequestException, ValueError):
            continue
        rows = payload.get("results", [payload]) if isinstance(payload, dict) else payload
        for rec in (rows if isinstance(rows, list) else [rows]):
            if not isinstance(rec, dict):
                continue
            for stamp in rec.get("upcoming_releases") or []:
                try:
                    when = pd.to_datetime(stamp)
                except (ValueError, TypeError):
                    continue

                # CONVERT TO CENTRAL. ESMIS sends a tz-AWARE Eastern stamp --
                # "2026-10-23T15:00:00-0400" -- and reading .hour off that
                # gives the Eastern hour. The letter printed "Grain Stocks:
                # Wed 9/30, 12:00pm" for a release at noon EASTERN, which is
                # 11am where Ross and his clients are. Reported 2026-09-30.
                #
                # The feed gets daylight saving right on its own (the very next
                # release in the same list carries -0500), so converting to the
                # named zone rather than a fixed offset keeps that correct
                # through the switch in November.
                #
                # The DATE can move with the hour in principle; taking it after
                # the conversion rather than before is what stops a late-evening
                # Eastern release being filed under the wrong Central day.
                try:
                    when = (when.tz_convert(config.LETTER_TZ) if when.tzinfo
                            else when.tz_localize("America/New_York")
                                     .tz_convert(config.LETTER_TZ))
                except Exception:           # noqa: BLE001 -- a bad stamp, not a bad zone
                    pass

                d = when.date()
                if not (as_of <= d <= horizon):
                    continue
                # Built by hand: "%-I" is a POSIX extension and raises
                # ValueError on Windows, which is where this runs.
                hour = when.hour % 12 or 12
                ampm = "am" if when.hour < 12 else "pm"
                # LABELLED, because an unlabelled hour is what caused this. CT
                # covers both CDT and CST without the reader doing arithmetic.
                scheduled.append({"date": d, "name": name,
                                  "time": f"{hour}:{when.minute:02d}{ampm} CT"})

    # WASDE: ESMIS lists it as an active monthly publication but returns
    # upcoming_releases: [] for it -- WAOB publishes it, not NASS, and the
    # forward schedule is simply not in this feed. Rather than drop a report
    # that was explicitly asked for, it is paired with Crop Production, which
    # USDA releases in the SAME noon-ET slot.
    #
    # THE LIMIT, AND IT IS ABSENCE NOT ERROR: a paired date is right whenever it
    # appears, but WASDE also prints in months with no Crop Production release
    # (roughly December through April), and those will not show. Flagged with
    # "inferred" so the build can say so.
    if not any(r["name"] == "WASDE" for r in scheduled):
        for r in [x for x in scheduled if x["name"] == "Crop Production"]:
            scheduled.append({"date": r["date"], "name": "WASDE",
                              "time": r["time"], "inferred": True})

    scheduled.sort(key=lambda r: (r["date"], r["name"]))

    # Prefer this month alone; roll into next only when this month is thin.
    this_month = [r for r in scheduled if r["date"] <= this_month_end]
    if len(this_month) >= CALENDAR_MIN_ITEMS:
        scheduled = this_month

    return {
        "inferred": [f"{r['name']} {r['date'].isoformat()}"
                     for r in scheduled if r.get("inferred")],
        "items": [{"date": r["date"].isoformat(),
                   "label": r["name"],
                   "when": f"{_WD[r['date'].weekday()]} {r['date'].month}/{r['date'].day}, {r['time']}",
                   "is_today": r["date"] == as_of}
                  for r in scheduled],
    }


def _ls712_section(text: str, heading: str) -> list:
    """
    Split one SJ_LS712 table into classified rows.

    Every table in this report shares a layout: a week-ending row for the
    current week, one for the prior week, a "Change:" percentage row, a row for
    the same week a year ago, another "Change:", then two "<year> YTD" rows and
    a final "Change:". Rows are returned in file order as (kind, label, numbers)
    with kind one of "week", "ytd", "change", so the caller can index by
    position without re-parsing.
    """
    m = re.search(rf"{heading}(.*?)(?:----)", text, re.DOTALL)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        s = line.strip()
        if not s:
            continue
        parts = s.split()
        nums = [n for n in (_num(p) for p in parts) if n is not None]
        if s.startswith("Change:"):
            # Percentages carry a trailing % that _num already strips.
            rows.append(("change", "Change", nums))
            continue
        d = _parse_ls712_date(parts[0])
        if d:
            rows.append(("week", d.isoformat(), [n for n in (_num(p) for p in parts[1:]) if n is not None]))
        elif len(parts) >= 2 and parts[1].upper() == "YTD":
            rows.append(("ytd", parts[0], [n for n in (_num(p) for p in parts[2:]) if n is not None]))
    return rows


def _first_col(rows: list, kind: str, index: int):
    """The Cattle/Beef column is the first number in every one of these tables."""
    hits = [r for r in rows if r[0] == kind]
    if index >= len(hits) or not hits[index][2]:
        return None, None
    return hits[index][2][0], hits[index][1]


# The chart of the day's cutout series. Six years, because a five-year average
# needs five prior years plus the running one.
CUTOUT_CHART_YEARS = 6
CUTOUT_SECTION = "Current Cutout Values"


def fetch_cutout_history(reports: int = 1700) -> "pd.Series":
    """
    Daily Choice cutout, indexed by report date, for the chart of the day.

    THE SECTION GOES IN THE PATH, and that is the whole difference between
    this being viable and not. `allSections=true` -- what fetch_cutout uses
    for a handful of reports -- returns all ELEVEN sections of LM_XB403,
    including every individual Choice and Select cut. At 1,700 reports that is
    **37.8 seconds and 183 MB**, which no 90-second build can spend. Asking for
    one section as a path segment returns the same 1,700 rows in 3.5s and
    1.3 MB: 140 times less data for exactly the numbers wanted.

    1,700 reports is about 6.7 years, which covers the five-year average with
    room to spare. The archive goes back further -- to 2004-01-05 in practice,
    NOT the 2001-04-03 the earliest report_date claims, because choice and
    select are null on all 699 rows before then -- but a chart does not need
    it and the full pull costs 9s.

    Keyless: the public AMS datamart, the same LMR_BASE the letter already uses.
    """
    r = _session().get(f"{LMR_BASE}/{XB403_ID}/{CUTOUT_SECTION}",
                       params={"lastReports": int(reports)}, timeout=90)
    r.raise_for_status()
    rows = r.json().get("results") or []
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df.get("report_date"), errors="coerce")
    df["v"] = pd.to_numeric(df.get("choice_600_900_current"), errors="coerce")
    df = df.dropna(subset=["d", "v"]).sort_values("d")
    return pd.Series(df["v"].values, index=df["d"].dt.date.values, dtype=float)


def cutout_premium_series(weeks: int = 52, years: int = 5, reports: int = 1700) -> dict:
    """
    Choice cutout as a premium to the same week's five-year average, $/cwt.

    ONE LINE, NOT TWO, AND THAT IS THE POINT. The obvious seasonal chart plots
    this year against the five-year average and lets the reader take the
    difference. Measured in the letter's actual 3.10 x 1.62in box that is a bad
    chart in 2026: cattle is running 26-27% over the five-year average, the two
    lines never cross, and the average drags the axis out until this year uses
    29% of the plot band. That is precisely the failure _nice_bounds' own
    docstring was written against -- an axis so wide the move reads as a drift.

    Subtracting first gives the same insight in one honest line that uses 82%
    of the band, and it answers the question directly: how far above normal is
    the cutout, and is that gap widening. Zero is "normal".

    WEEKLY MEANS, NOT DAILY. 52 weekly points fit the box; 260 daily ones are a
    smear at this size, and the day-to-day noise is not the story a seasonal
    chart tells.

    Matched on ISO week, so week 14 is compared with week 14 -- the calendar
    dates differ by definition and matching on them would compare a Tuesday
    with a Friday.
    """
    daily = fetch_cutout_history(reports)
    if daily.empty:
        return {}

    f = pd.DataFrame({"v": daily.values},
                     index=pd.to_datetime(pd.Series(list(daily.index))))
    iso = f.index.isocalendar()
    f["yr"], f["wk"], f["dow"] = iso["year"].values, iso["week"].values, iso["day"].values
    wk = f.groupby(["yr", "wk"])["v"].mean()
    # Keyed by (year, week, weekday) so a base year can be restricted to the
    # same days the current week actually has. See below.
    by_day = f.groupby(["yr", "wk", "dow"])["v"].mean()

    out_dates, out_vals = [], []
    for (yr, w), v in wk.tail(int(weeks)).items():
        # LIKE-FOR-LIKE WEEKDAYS, because the newest week is almost always
        # SHORT. The current week is only as long as the market has traded --
        # on 2026-10-01 week 40 held Mon/Tue/Wed -- while every base year's
        # week 40 is a full five days. Averaging three days of a rising market
        # against five-day baselines overstated the premium by 0.75 $/cwt on
        # the one point the chart labels. Holidays do the same thing to seven
        # of the 52 plotted weeks.
        #
        # Matching the weekday set rather than dropping the short week keeps
        # the letter's most recent reading on the chart, which is the point of
        # having it.
        present = sorted(f[(f["yr"] == yr) & (f["wk"] == w)]["dow"].unique())
        base = []
        for n in range(1, int(years) + 1):
            days = [by_day.get((yr - n, w, d)) for d in present]
            days = [x for x in days if x is not None and not pd.isna(x)]
            if days:
                base.append(sum(days) / len(days))
        # ALL FIVE OR NONE. An "average" over two of the five years is a
        # different statistic wearing the same label, and the gap it implies
        # would be wrong rather than approximate.
        if len(base) < int(years):
            continue
        # Monday of that ISO week, so the axis carries a real date.
        out_dates.append(date.fromisocalendar(int(yr), int(w), 1))
        out_vals.append(round(float(v) - sum(base) / len(base), 2))

    if len(out_vals) < 5:
        return {}
    # "PREMIUM TO", NOT "VS". The line is the SPREAD, not the cutout, and
    # "Choice cutout vs 5-yr avg" reads as though the cutout itself is
    # plotted -- so a reader who knows the cutout is 382 sees 81.88 and
    # reasonably calls it wrong. Reported 2026-10-01. The spread is still the
    # right thing to draw (see above); only the label was lying about it.
    return {"dates": out_dates, "values": out_vals,
            "title": f"Choice cutout premium to {years}-yr avg ($/cwt)",
            "style": "decimal"}


def fetch_slaughter() -> dict:
    """
    Completed-week cattle slaughter and carcass weights from AMS SJ_LS712.

    WHAT THIS REPORT IS, AND IS NOT. SJ_LS712 is "Estimated Weekly Meat
    Production Under Federal Inspection" -- published Friday, covering the week
    ending the SATURDAY AFTER IT, which is the day after publication.

    THAT SENTENCE READ "the week ending the previous Saturday" until
    2026-09-29, and it is the reason the headline was never questioned. The
    report dated Friday 2026-09-25 carries week_ending 2026-09-26: Saturday
    entirely and most of Friday are PROJECTED, not counted. So this is not a
    completed week at all, and the function's own name overstates it.

    It gives that week, the week before, the same week a year ago, and
    year-to-date, which is exactly the "529,000 compared to 505,000 head LW and
    559,000 LY" line and both YTD percentages -- and those three head counts are
    not the same KIND of number. USDA labels the rows in the file itself:

        this week   Estimate   -- two days of it projected
        last week   Estimate   -- revised once since
        year ago    Actual

    render.friday_rundown_block therefore prints the week ending date and an
    "est." on that line. The Cattle Weights dashboard has always labelled its
    tiles "Live (Est.) - Wk Ending Sep 26, 2026"; the letter now agrees with it.

    It contains NO DAILY FIGURES AT ALL -- the letter's "Daily slaughter" and
    "WTD slaughter" bullets come from AMS report 3208 instead (fetch_daily_
    slaughter), and its "Average Weights" table is NOT the carcass weight the
    letter prints either (fetch_carcass_weights, AMS 3658). What is used from
    here is the completed-week head count and the two YTD percentages.

    Recent weeks are USDA ESTIMATES; only the year-ago row is actual. The report
    says so itself and the estimate is revised the following week -- which is
    why the weights here are reference only.

    week_ending is carried through so the letter can say which week it means.
    It is the report's own figure, not report_date + 1: relying on the offset
    is how the docstring above came to be wrong for months.
    """
    r = _session().get(AMS_SJ_LS712, timeout=30)
    r.raise_for_status()
    text = r.text

    out: dict = {
        "daily": None,          # not in this report -- see docstring
        "wtd": None,            # ditto
        "weekly": {},
        "beef_production": {},
        "weights": {},
        "report_date": None,
    }

    m = re.search(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+\s+\d+,\s+\d{4})", text)
    if m:
        try:
            out["report_date"] = datetime.strptime(
                m.group(2).strip(), "%b %d, %Y").date().isoformat()
        except ValueError:
            pass

    # -- Head slaughtered -----------------------------------------------------
    rows = _ls712_section(text, r"Livestock Slaughter \(head\)")
    if rows:
        cur, cur_date = _first_col(rows, "week", 0)
        lw, _ = _first_col(rows, "week", 1)
        ly, ly_date = _first_col(rows, "week", 2)
        changes = [r[2][0] for r in rows if r[0] == "change" and r[2]]
        out["weekly"] = {
            "value": cur, "week_ending": cur_date,
            "last_week": lw, "year_ago": ly, "year_ago_week": ly_date,
            # Three Change rows in order: week on week, year on year, then YTD.
            "chg_wow_pct": changes[0] if len(changes) > 0 else None,
            "chg_yoy_pct": changes[1] if len(changes) > 1 else None,
            "ytd_chg_pct": changes[2] if len(changes) > 2 else None,
        }

    # -- Beef production ------------------------------------------------------
    rows = _ls712_section(text, r"Meat Production \(millions of pounds\)")
    if rows:
        cur, cur_date = _first_col(rows, "week", 0)
        changes = [r[2][0] for r in rows if r[0] == "change" and r[2]]
        out["beef_production"] = {
            "value": cur, "week_ending": cur_date,
            "chg_wow_pct": changes[0] if len(changes) > 0 else None,
            "chg_yoy_pct": changes[1] if len(changes) > 1 else None,
            "ytd_chg_pct": changes[2] if len(changes) > 2 else None,
        }

    # -- Average weights ------------------------------------------------------
    # Live and Dressed are two blocks under one heading, each with the same
    # three rows (current week, prior week, year ago). The block header lines
    # carry "Live:" / "Dressed:" and no date, so they switch mode without
    # contributing a row.
    m = re.search(r"Average Weights \(lbs\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        mode = None
        blocks: dict = {"live": [], "dressed": []}
        for line in m.group(1).splitlines():
            s = line.strip()
            if not s:
                continue
            if re.search(r"\bLive:", s, re.IGNORECASE):
                mode = "live"
            elif re.search(r"\bDressed:", s, re.IGNORECASE):
                mode = "dressed"
            if mode is None:
                continue
            parts = s.split()
            d = _parse_ls712_date(parts[0])
            if not d:
                continue
            # Row shape: "<date> Estimate 889 217 212 56" -- skip the word.
            nums = [n for n in (_num(p) for p in parts[1:]) if n is not None]
            if nums:
                blocks[mode].append((d.isoformat(), nums[0]))
        for mode, rows_ in blocks.items():
            if rows_:
                out["weights"][mode] = {
                    "value": rows_[0][1],
                    "date": rows_[0][0],
                    "last_week": rows_[1][1] if len(rows_) > 1 else None,
                    "year_ago": rows_[2][1] if len(rows_) > 2 else None,
                }
    return out


# -- Snowflake: CME feeder cattle index, Douglas imports ----------------------

def _load_fci_db():
    """
    Load apps/cme_feeder_cattle/snowflake_db.py under a PRIVATE module name.

    CLAUDE.md records that snowflake_db.py exists five times in this repo and
    that Python caches by module NAME, so whichever page imports first wins and
    every later one silently gets that copy. This generator never runs inside
    the Streamlit process today, but naming the module "_letter_fci_db" means it
    can never join that collision if it ever does.
    """
    path = APPS / "cme_feeder_cattle" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_letter_fci_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_letter_fci_db"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_index_dates():
    """index_dates.py, under a private name -- same reasoning as _load_fci_db."""
    path = APPS / "cme_feeder_cattle" / "index_dates.py"
    spec = importlib.util.spec_from_file_location("_letter_index_dates", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_letter_index_dates"] = mod
    spec.loader.exec_module(mod)
    return mod


def fetch_feeder_index(today: date = None) -> dict:
    """
    JSA's OWN feeder cattle index estimate, as the dashboard headlines it.

    READS fci_daily, NOT cme_ftp_daily. fci_daily is the JSA reconstruction --
    the number the CME Feeder Cattle Index dashboard leads with and the one the
    letter should quote. cme_ftp_daily holds CME's published file and is read
    here only for its DATE, to decide which of our own estimates is the headline.

    WHICH DATE. Not MAX(report_date) -- the newest row is always the least
    complete, and on a Monday it can hold one Saturday auction and nothing else.
    The rule is the first business day after CME's last published file, which is
    index_dates.headline_index_date(), the same function the dashboard and the
    daily email use. CLAUDE.md is explicit that this must not be simplified back
    to the newest row, and the tests for it live in the cme-feeder-cattle-index
    repo.

    One consequence worth knowing: the headline follows CME's publication clock,
    so if the CME ingest breaks, this figure freezes while the rest of the letter
    keeps moving.
    """
    db = _load_fci_db()
    idx = _load_index_dates()
    conn = db.get_conn()
    try:
        ours = db.read_sql_lower(
            "SELECT report_date AS date, fci_value FROM fci_daily "
            "WHERE fci_value IS NOT NULL", conn)
        try:
            # fci_value TOO, not just the date. See the merge below -- reading
            # this table for its date alone is what produced a wrong change.
            published = db.read_sql_lower(
                "SELECT report_date AS date, fci_value FROM cme_ftp_daily", conn)
        except Exception:
            # A missing CME table degrades to the newest estimate rather than
            # to nothing -- headline_index_date() handles last_published=None.
            published = pd.DataFrame(columns=["date", "fci_value"])
    finally:
        conn.close()

    if ours.empty:
        return {}

    ours["date"] = pd.to_datetime(ours["date"], errors="coerce")
    ours = ours.dropna(subset=["date"]).sort_values("date")
    available = {d.date() for d in ours["date"]}

    last_published = None
    if not published.empty:
        pub = pd.to_datetime(published["date"], errors="coerce").dropna()
        if not pub.empty:
            last_published = pub.max().date()

    headline = idx.headline_index_date(last_published, available)
    if headline is None:
        return {}

    # CME'S PUBLISHED VALUE WINS FOR ANY DATE IT COVERS. fci_daily is JSA's
    # MARS reconstruction, and its job is the trailing day or two CME has not
    # printed yet -- a prediction, not a stand-in for data CME has already
    # released. The dashboard's load_data() says exactly that in its priority
    # order, and this function did not honour it: it read cme_ftp_daily for
    # its DATE and threw the value away.
    #
    # What that cost, 2026-10-01. CME published 09-29 at 338.03; our estimate
    # for the same date was 338.68 and was never superseded. The brief printed
    #
    #     339.05 - 338.68 (our stale estimate)  = +0.37
    #
    # where the dashboard, taking CME's print, showed
    #
    #     339.05 - 338.03 (CME's published)     = +1.02
    #
    # Reported by Ross as "the daily fci estimate is 1.02 higher". Same class
    # of failure as the rounding disagreement below: a letter whose change
    # contradicts the dashboard is wrong however it was computed, and nothing
    # raised because both numbers were real.
    #
    # The headline date is by definition the first business day AFTER CME's
    # last file, so its own value always stays ours. It is the PRIOR date that
    # CME has usually printed by now.
    merged = {d.date(): float(v) for d, v in zip(ours["date"], ours["fci_value"])}
    cme_dates = set()
    if not published.empty and "fci_value" in published.columns:
        pub2 = published.copy()
        pub2["date"] = pd.to_datetime(pub2["date"], errors="coerce")
        pub2 = pub2.dropna(subset=["date", "fci_value"])
        for d, v in zip(pub2["date"], pub2["fci_value"]):
            merged[d.date()] = float(v)
            cme_dates.add(d.date())

    if headline not in merged:
        return {}
    value = merged[headline]

    # Prior available date, for the day-on-day move.
    #
    # WEEKENDS ARE FILLER, NOT SESSIONS. fci_daily carries Friday forward over
    # Saturday and Sunday -- 2026-10-17 and 10-18 both hold Friday's
    # 343.45715 to the digit, with no same-day price on either. Differencing
    # against one of those on a Monday or Tuesday gives a move against Friday
    # that is a cent out from CME's own, because merged holds CME's rounded
    # 343.45 for Friday and our unrounded 343.457 for the filler: on
    # 2026-10-20 that printed -1.30 where CME's REPORTED_CHANGE said -1.29.
    # One cent, on the figure the letter and the dashboard must agree about.
    earlier = sorted(d for d in available if d < headline and d.weekday() < 5)
    prev_val = merged.get(earlier[-1]) if earlier else None

    # ROUND BOTH VALUES TO DISPLAY PRECISION BEFORE DIFFERENCING, not after,
    # and the reason is that the letter and the dashboard must agree.
    #
    # On 2026-09-29 the brief printed "-0.17 at 337.63" while the FCI dashboard
    # showed the same 337.63 down 0.16. Neither was wrong in isolation: the raw
    # move was -0.169151, which rounds to -0.17, while 337.63 minus a 337.79
    # that itself came from 337.794466 is -0.16. The letter rounded the
    # difference; the dashboard rounds the values first, deliberately -- see
    # the comment on `day_chg` in apps/cme_feeder_cattle/app.py.
    #
    # The dashboard's convention wins here, and it is the better one anyway:
    # this letter PRINTS 337.63 today and printed 337.79 yesterday, so a reader
    # holding both subtracts them and gets 0.16. A change that disagrees with
    # the letter's own published figures is wrong however it was computed.
    shown = round(value, 2)
    prev_shown = round(prev_val, 2) if prev_val is not None else None

    # WHAT CME HAS ACTUALLY PRINTED, alongside the forward estimate.
    #
    # `value` above is the index CME will publish NEXT -- the first business
    # day after their last file -- which is the right headline for the
    # dashboard and for the morning brief, both of which label it an
    # ESTIMATE. It is the wrong number for the evening letter, which prints
    # "Feeder Cattle Index: x" with no date and no qualifier, so a reader
    # takes it for the index as it stands.
    #
    # Reported by Ross on 2026-10-07: the afternoon report quoted 335.86 for
    # index date 10/07, an estimate built on 228 locations and 17,524 head
    # with the day still running, when CME had that morning published 10/06
    # at 337.87 -- a figure our own 10/06 estimate matched to the cent
    # (337.869294). Two dollars apart, and the published one was available.
    #
    # So both are returned and the caller chooses by what it is claiming.
    # Nothing here changes `value`; the morning brief's "JSA FCI Estimate"
    # is doing exactly what it says.
    # IT IS BUILT FROM `merged`, NOT FROM cme_ftp_daily DIRECTLY, and that is
    # the whole robustness of it.
    #
    # The first version read the CME table itself and returned None when it
    # came back empty -- whereupon the caller fell back to `value`, the
    # forward estimate, which is precisely the figure Ross had reported. The
    # deployed app reads a DIFFERENT Snowflake from this machine (see
    # CLAUDE.md), the table did not answer there, and the "fix" shipped the
    # original bug wearing a label. A fallback that lands on the reported
    # defect is worse than no fallback.
    #
    # `merged` already applies the rule that matters -- CME's published value
    # wins for any date it covers, ours fills the rest -- so taking the last
    # COMPLETED date out of it gives CME's print when we have it and our own
    # estimate for that same day when we do not. Those agree closely by
    # construction: for 2026-10-06 ours was 337.869294 against CME's 337.87.
    # Either way it can never be the unfinished forward day.
    # IT IS KEYED ON THE DATES CME HAS PRINTED, not on "the last date before
    # the headline", which is what it was until 2026-10-20. That rule failed
    # in two ways at once, and both were live that morning while Ross was
    # writing: *"the feeder cattle index isn't updating to either today's FCI
    # -- which the CME just released -- or using our JSA Daily FCI Estimate.
    # It's stale with yesterday's CME fci."*
    #
    # FIRST, fci_daily CARRIES FRIDAY FORWARD OVER THE WEEKEND. 2026-10-17 and
    # 10-18 both hold Friday's 343.45715, to the digit. They are filler, not
    # sessions -- no auction trades on a Sunday -- and "the last date before
    # the headline" landed on one.
    #
    # SECOND, THE HEADLINE DEGRADES ONTO A REAL SESSION. headline_index_date()
    # returns the first business day after CME's last file ONLY while we hold
    # an estimate for it; when CME has caught up with everything in fci_daily
    # it falls back to max(available), which is deliberate and documented
    # there. So on a morning where the MARS ingest has not yet produced
    # today's estimate, the headline sits on the newest REAL session -- and
    # `d < headline` then excludes precisely the index CME just published.
    #
    # Together, on 2026-10-20:
    #
    #     headline   342.16  10-19   (CME had printed this that morning)
    #     published  343.46  10-18   a Sunday, Friday's number, change 0.00
    #
    # A date CME has printed is a finished session by construction, so keying
    # on cme_dates keeps the property the old rule was written for -- it can
    # never be the unfinished forward day -- without depending on the headline
    # at all. The two are answering different questions and should not be
    # chained.
    #
    # THE PRIOR IS THE PREVIOUS PRINTED DATE, NOT THE PREVIOUS CALENDAR ROW,
    # and that is the same bug in the change. Against Sunday's filler the move
    # read -1.30; against Friday, which is what CME differenced, it is -1.29 --
    # exactly CME's own REPORTED_CHANGE for 10-19. That column is a free audit
    # of this arithmetic and `tests/test_feeder_index.py` uses it.
    # THE MOST RECENT COMPLETED SESSION, WHOEVER HOLDS IT -- CME's print for
    # a date they have archived, ours for one they have not. Ross's call,
    # 2026-10-21, after this line sat on Monday's index for two days.
    #
    # IT WAS KEYED ON cme_dates FOR A DAY AND THAT WAS TOO NARROW. CME
    # disseminates the index on their market-data feed the moment they
    # compute it -- which is where Ross sees it, on QST -- but the only
    # channel this pipeline reads is the FTP settlement-calculation archive,
    # `ftp.cmegroup.com/cash_settled_commodity_index_prices/...`, and that
    # lands the NEXT DAY between about 13:00 and 14:35 CT. On 2026-10-21 it
    # had not landed at all by 16:14, so the letter was still printing 10/19
    # while his screen showed 10/20. Nothing was broken; we were reading a
    # slower channel.
    #
    # WHAT MAKES OUR OWN NUMBER ACCEPTABLE HERE is that it is the same
    # number. Over the 21 days both series cover, the reconstruction differs
    # from CME's print by at most **0.022** and a median of 0.004 -- 10/19
    # was ours 342.17 against their 342.16. So "most recent completed
    # session" costs a rounding cent and buys a day of currency.
    #
    # COMPLETED MEANS STRICTLY BEFORE TODAY, in Central, and that is the
    # safety property the old `d < headline` rule was really protecting: it
    # can never be the unfinished forward day. Today's row exists from the
    # moment the first barn reports -- 2026-10-21 stood at 248 locations and
    # 868 same-day head against Tuesday's 303 and 19,504 -- and quoting that
    # as the index is the 2026-10-07 defect over again.
    #
    # Weekdays only: fci_daily carries Friday forward across Saturday and
    # Sunday (10/17 and 10/18 both hold 343.45715 to the digit), and those
    # rows are filler, not sessions.
    # INJECTABLE, so a test is not a function of the day it runs on.
    # What counts as a completed session depends on today's date, and a
    # test that reads the real clock passes in October and fails in
    # November for no reason anyone will remember.
    today_ct = today or config.now_central().date()
    completed = sorted(d for d in merged
                       if d < today_ct and d.weekday() < 5)
    s_date = completed[-1] if completed else None
    s_prev_date = completed[-2] if len(completed) > 1 else None

    pub_block = None
    if s_date is not None:
        s_val = round(merged[s_date], 2)
        # Same round-then-subtract convention as below: a reader holding two
        # letters subtracts the printed figures and must get this.
        s_prev = round(merged[s_prev_date], 2) if s_prev_date is not None else None
        from_cme = s_date in cme_dates
        pub_block = {
            "value": s_val,
            "date": s_date.isoformat(),
            "change": round(s_val - s_prev, 2) if s_prev is not None else None,
            "source": ("CME published (cme_ftp_daily)" if from_cme
                       else "JSA estimate for a completed session"),
            "from_cme": from_cme,
        }

    return {
        "value": shown,
        "date": headline.isoformat(),
        "change": round(shown - prev_shown, 2) if prev_shown is not None else None,
        "source": "JSA estimate (fci_daily)",
        "cme_last_published": last_published.isoformat() if last_published else None,
        "published": pub_block,
    }


def fetch_douglas_ytd(year: int = None) -> dict:
    """Year-to-date feeder imports through the Douglas, AZ crossing."""
    year = year or date.today().year
    db = _load_fci_db()
    conn = db.get_conn()
    try:
        df = db.read_sql_lower(
            "SELECT report_date AS date, crossing_point, receipts_est "
            "FROM border_receipts WHERE is_total = 0", conn)
    finally:
        conn.close()
    if df.empty:
        return {"year": year, "head": None}
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[df["date"].dt.year == year]
    doug = df[df["crossing_point"].astype(str).str.contains("Douglas", case=False, na=False)]
    if doug.empty:
        return {"year": year, "head": None}
    return {"year": year,
            "head": int(pd.to_numeric(doug["receipts_est"], errors="coerce").fillna(0).sum())}
