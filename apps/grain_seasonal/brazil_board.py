"""Brazil section maths: CBOT front-month futures valued in Brazilian reais.

What a Brazilian farmer sees is the Chicago price times the exchange rate, so the series here is
the front-month settlement (cents per bushel) times USD/BRL (reais per dollar), which comes out
in centavos per bushel. It is sampled weekly, counting back from the latest completed session so
the line always ends on the newest close, and read four ways: the latest value, the week's
change and what drove it, the period high, and the change against a year ago.

Pure functions on settlement histories (no Streamlit), so they can be checked on their own.

Front month. The nearest contract that has not expired: it stays the front month through its
last trading day (the business day before the 15th of its delivery month) and the next contract
takes over the following session. That is how continuous front-month series are conventionally
built; weekends are the only closures applied, so a holiday on the 14th would shift a roll by a
day.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping

import pandas as pd

import trend_board

START = date(2025, 1, 1)       # the chart opens with the first weeks of 2025
STEP_DAYS = 7                  # one point a week
YEAR_DAYS = 364                # 52 weeks, so "a year ago" lands on the same weekday
MAX_GAP_DAYS = 5               # nearest settlement or rate may be at most this far before a point

TOP_OF_RANGE = 0.85            # share of the way up the range that counts as "near the top"
BOTTOM_OF_RANGE = 0.15
UNCHANGED = 0.0005             # a move inside +/-0.05% reads as unchanged
LITTLE_CHANGED = 0.005         # inside +/-0.5% reads as little changed
QUIET_WEEK = 0.005             # a week's net move this small is not worth explaining...
OFFSETTING = 0.01              # ...unless the futures or the real moved this much and cancelled out
DOMINANT = 2.0                 # one driver counts as the cause when it is this many times the other

MONTH_NUMBER = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
                "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}

WEEKLY_COLUMNS = ["contract", "cbot", "usdbrl", "centavos"]


@dataclass(frozen=True)
class Market:
    code: str        # CBOT product code
    name: str        # as it opens a sentence: "Soybeans priced in reais are ..."
    crop: str        # as it follows "expand ... acreage"
    plural: bool     # "Soybeans are / were / their", but "Corn is / was / its"
    months: str      # delivery months listed, as CME month letters

    @property
    def be(self) -> str:
        return "are" if self.plural else "is"

    @property
    def was(self) -> str:
        return "were" if self.plural else "was"

    @property
    def their(self) -> str:
        return "their" if self.plural else "its"


MARKETS = {
    "ZS": Market("ZS", "Soybeans", "soybean", True, "FHKNQUX"),
    "ZC": Market("ZC", "Corn", "corn", False, "HKNUZ"),
}


# ── Front month ──────────────────────────────────────────────────────────────

def last_trade_day(letter: str, year: int) -> date:
    """Last trading day of a CBOT grain contract: the business day before the 15th of its
    delivery month (weekends only, exchange holidays not applied)."""
    fifteenth = pd.Timestamp(year=year, month=MONTH_NUMBER[letter], day=15)
    return (fifteenth - pd.offsets.BDay(1)).date()


def contract_windows(code: str, first_day: date, last_day: date) -> list[tuple[str, int, date, date]]:
    """[(month letter, contract year, day before it takes over, its last trading day)] for every
    contract that is the front month at some point between the two dates."""
    market = MARKETS[code]
    contracts = sorted((last_trade_day(letter, year), letter, year)
                       for year in range(first_day.year - 1, last_day.year + 2)
                       for letter in market.months)
    out = []
    previous = date.min
    for last, letter, year in contracts:
        if last >= first_day and previous < last_day:
            out.append((letter, year, previous, last))
        previous = last
    return out


def front_month(code: str, histories: Mapping[tuple[str, int], pd.Series],
                first_day: date, last_day: date) -> pd.DataFrame:
    """The front-month settlement series: columns `settle` (cents per bushel) and `contract`
    (e.g. ZSX6), indexed by trading date. `histories` maps (month letter, contract year) to that
    contract's settlements; a contract with no history simply leaves a gap."""
    settles: dict[pd.Timestamp, float] = {}
    labels: dict[pd.Timestamp, str] = {}
    for letter, year, after, last in contract_windows(code, first_day, last_day):
        series = trend_board.clean(histories.get((letter, year)))
        if not len(series):
            continue
        window = series[(series.index > pd.Timestamp(after)) & (series.index <= pd.Timestamp(last))]
        for day, price in window.items():
            settles[day] = float(price)
            labels[day] = f"{code}{letter}{year % 10}"
    if not settles:
        return pd.DataFrame(columns=["settle", "contract"])
    frame = pd.DataFrame({"settle": pd.Series(settles), "contract": pd.Series(labels)})
    frame.index.name = "date"
    return frame.sort_index()


def contract_tickers(code: str, first_day: date, last_day: date) -> list[tuple[str, int, str]]:
    """[(letter, year, Massive ticker)] for the contracts a front-month series between the two
    dates needs. Massive spells the year with one digit, which is unambiguous here because its
    per-contract history only reaches back to 2021."""
    return [(letter, year, f"{code}{letter}{year % 10}")
            for letter, year, _, _ in contract_windows(code, first_day, last_day)]


# ── Weekly series ────────────────────────────────────────────────────────────

def _position_on_or_before(index: pd.DatetimeIndex, day: pd.Timestamp) -> int | None:
    pos = index.searchsorted(day, side="right") - 1
    if pos < 0 or (day - index[pos]).days > MAX_GAP_DAYS:
        return None
    return int(pos)


def weekly_points(front: pd.DataFrame, fx: pd.Series, first_day: date = START,
                  before: date | None = None) -> pd.DataFrame:
    """One point a week, counting back from the newest session both series share. Columns:
    `contract`, `cbot` (cents per bushel), `usdbrl` (reais per dollar) and `centavos` (the price
    in reais, in hundredths, per bushel). A week with no settlement or rate close enough to it is
    left out rather than filled. `before` leaves out that date and later: today's bar, which a
    live feed carries before the session has closed, is not a close."""
    rates = trend_board.clean(fx)
    if before is not None:
        cutoff = pd.Timestamp(before)
        front = front[front.index < cutoff]
        rates = rates[rates.index < cutoff]
    if front.empty or not len(rates):
        return pd.DataFrame(columns=WEEKLY_COLUMNS)
    newest = min(front.index[-1], rates.index[-1])
    rows = []
    day = newest
    while day.date() >= first_day:
        f_pos = _position_on_or_before(front.index, day)
        r_pos = _position_on_or_before(rates.index, day)
        if f_pos is not None and r_pos is not None:
            cbot = float(front["settle"].iloc[f_pos])
            rate = float(rates.iloc[r_pos])
            rows.append((day, front["contract"].iloc[f_pos], cbot, rate, cbot * rate))
        day -= pd.Timedelta(days=STEP_DAYS)
    frame = pd.DataFrame(rows, columns=["date", *WEEKLY_COLUMNS]).set_index("date")
    return frame.sort_index()


# ── Reading it ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Summary:
    market: Market
    first_date: date
    latest_date: date
    latest: float            # centavos per bushel
    latest_cbot: float
    latest_fx: float
    contract: str            # front-month contract on the latest date
    week_change: int | None  # centavos, of the rounded figures shown
    week_pct: float | None
    cbot_pct: float | None   # the week's change in the futures alone
    fx_pct: float | None     # and in USD/BRL alone
    high: float
    high_date: date
    low: float
    low_date: date
    position: float          # where the latest value sits between the low (0) and the high (1)
    year_ago: float | None
    year_ago_date: date | None
    year_ago_pct: float | None
    points: int


def summarize(weekly: pd.DataFrame, market: Market) -> Summary | None:
    """The tile figures and the facts the commentary rests on; None if fewer than two weeks."""
    if len(weekly) < 2:
        return None
    last, prev = weekly.iloc[-1], weekly.iloc[-2]
    high_at, low_at = weekly["centavos"].idxmax(), weekly["centavos"].idxmin()
    high, low = float(weekly["centavos"].max()), float(weekly["centavos"].min())
    span = high - low
    year = None
    target = weekly.index[-1] - pd.Timedelta(days=YEAR_DAYS)
    hit = weekly.index.get_indexer([target], method="nearest", tolerance=pd.Timedelta(days=3))[0]
    if hit >= 0 and weekly.index[hit] < weekly.index[-1]:
        year = weekly.iloc[hit]
    return Summary(
        market=market,
        first_date=weekly.index[0].date(),
        latest_date=weekly.index[-1].date(),
        latest=float(last["centavos"]),
        latest_cbot=float(last["cbot"]),
        latest_fx=float(last["usdbrl"]),
        contract=str(last["contract"]),
        week_change=round(float(last["centavos"])) - round(float(prev["centavos"])),
        week_pct=float(last["centavos"] / prev["centavos"] - 1),
        cbot_pct=float(last["cbot"] / prev["cbot"] - 1),
        fx_pct=float(last["usdbrl"] / prev["usdbrl"] - 1),
        high=high, high_date=high_at.date(), low=low, low_date=low_at.date(),
        position=0.5 if span <= 0 else float((last["centavos"] - low) / span),
        year_ago=None if year is None else float(year["centavos"]),
        year_ago_date=None if year is None else weekly.index[hit].date(),
        year_ago_pct=None if year is None else float(last["centavos"] / year["centavos"] - 1),
        points=len(weekly),
    )


def fmt_centavos(value: float) -> str:
    return f"{value:,.0f}"


def fmt_reais(centavos: float) -> str:
    return f"R${centavos / 100:,.2f}/bu"


def fmt_date(day: date) -> str:
    return f"{day.month}/{day.day}/{day.year}"


def fmt_pct(fraction: float, signed: bool = True) -> str:
    return f"{fraction:+.1%}" if signed else f"{abs(fraction):.1%}"


def _futures_move(summary: Summary) -> str:
    """How the futures did over the week, as a verb phrase for "while CBOT soybeans ..."."""
    move = summary.cbot_pct or 0.0
    size = abs(move)
    if size < UNCHANGED:
        return f"{summary.market.was} unchanged"
    if size < LITTLE_CHANGED:
        return f"{summary.market.was} little changed"
    verb = ("edged up" if move > 0 else "slipped") if size < 0.015 else ("rose" if move > 0 else "fell")
    return f"{verb} {fmt_pct(move, signed=False)}"


def _real_move(summary: Summary) -> str:
    """How the real did, as a verb phrase for "while the real ...". The percentage is the move
    in USD/BRL, the way it is quoted: a dollar worth 6.6% more reais is a real that weakened 6.6%."""
    move = summary.fx_pct or 0.0
    if abs(move) < LITTLE_CHANGED:
        return "was little changed"
    return f"{'weakened' if move > 0 else 'strengthened'} about {fmt_pct(move, signed=False)}"


def week_driver(summary: Summary) -> str:
    """Which of the two ingredients moved the week: "fx", "cbot", "both" (same direction),
    "offset" (opposite directions, similar size) or "flat" (nothing worth explaining)."""
    total, cbot, fx = summary.week_pct, summary.cbot_pct, summary.fx_pct
    if total is None:
        return "flat"
    lc, lf = math.log1p(cbot), math.log1p(fx)
    if abs(total) < QUIET_WEEK:
        # A flat week can still hide two big moves that cancelled, which is worth saying.
        return "offset" if max(abs(lc), abs(lf)) >= OFFSETTING else "flat"
    if abs(lf) >= DOMINANT * abs(lc):
        return "fx"
    if abs(lc) >= DOMINANT * abs(lf):
        return "cbot"
    return "both" if lc * lf > 0 else "offset"


def week_tile_note(summary: Summary) -> str:
    """The line under the week-change figure: "+6.6%, driven by a weaker real"."""
    if summary.week_pct is None:
        return ""
    driver = week_driver(summary)
    pct = fmt_pct(summary.week_pct)
    if driver == "flat":
        return f"{pct}, little changed"
    if driver == "fx":
        return f"{pct}, driven by a {'weaker' if summary.fx_pct > 0 else 'stronger'} real"
    if driver == "cbot":
        return f"{pct}, driven by {'higher' if summary.cbot_pct > 0 else 'lower'} CBOT futures"
    if driver == "both":
        return f"{pct}, from both CBOT and the real"
    return f"{pct}, CBOT and the real offset"


def why_it_matters(summary: Summary) -> str:
    """The note under the chart: where the price sits in its range and what that means for a
    Brazilian farmer's incentive to sell and plant, then what moved the latest week."""
    m = summary.market
    if summary.position >= TOP_OF_RANGE:
        first = (f"{m.name} priced in reais {m.be} near the top of {m.their} range, which encourages "
                 f"Brazilian farmers to sell and to expand {m.crop} acreage.")
    elif summary.position <= BOTTOM_OF_RANGE:
        first = (f"{m.name} priced in reais {m.be} near the bottom of {m.their} range, which "
                 f"discourages Brazilian farmers from selling and from adding {m.crop} acreage.")
    else:
        first = (f"{m.name} priced in reais {m.be} in the middle of {m.their} range, so Brazilian "
                 f"farmers have no strong price signal to sell or to change {m.crop} acreage.")

    total, cbot, fx = summary.week_pct, summary.cbot_pct, summary.fx_pct
    if total is None:
        return first
    driver = week_driver(summary)
    cbot_name = f"CBOT {m.name.lower()}"
    if driver == "flat":
        if max(abs(cbot), abs(fx)) < LITTLE_CHANGED:
            second = f"The latest week was quiet: neither {cbot_name} nor the real moved much."
        else:
            second = (f"The latest week was quiet: {cbot_name} {_futures_move(summary)} and the real "
                      f"{_real_move(summary)}.")
    elif driver == "fx":
        lead = "Nearly all" if abs(math.log1p(fx)) >= 0.8 * abs(math.log1p(total)) else "Most"
        second = (f"{lead} of the latest week's {'jump' if total > 0 else 'drop'} came from the "
                  f"currency: the real {_real_move(summary)} while {cbot_name} {_futures_move(summary)}.")
    elif driver == "cbot":
        lead = "Nearly all" if abs(math.log1p(cbot)) >= 0.8 * abs(math.log1p(total)) else "Most"
        second = (f"{lead} of the latest week's {'jump' if total > 0 else 'drop'} came from futures: "
                  f"{cbot_name} {_futures_move(summary)} while the real {_real_move(summary)}.")
    elif driver == "both":
        second = (f"Futures and the currency pushed the same way: {cbot_name} {_futures_move(summary)} "
                  f"and the real {_real_move(summary)}.")
    else:
        second = (f"Futures and the currency pulled against each other: {cbot_name} "
                  f"{_futures_move(summary)} while the real {_real_move(summary)}, a net "
                  f"{fmt_pct(total)} for the week.")
    return f"{first} {second}"


def subtitle(summary: Summary) -> str:
    m = summary.market
    return (f"Front-month CBOT {m.crop} futures × USD/BRL — weekly, "
            f"{summary.first_date:%b %Y} to {summary.latest_date:%b} {summary.latest_date.day}, "
            f"{summary.latest_date.year}")


def source_note(market: Market) -> str:
    return (f"CBOT/CME ({market.code}, nearest unexpired contract) and USD/BRL daily closes via "
            f"Massive; JSA calculations.")


def export_frame(weekly: pd.DataFrame) -> pd.DataFrame:
    """The weekly points as a plain table for CSV / copy."""
    out = weekly.copy()
    out.index = [d.date() for d in out.index]
    out.index.name = "week"
    out = out.rename(columns={"contract": "contract", "cbot": "cbot_cents_per_bu",
                              "usdbrl": "usd_brl", "centavos": "reais_centavos_per_bu"})
    out["cbot_cents_per_bu"] = out["cbot_cents_per_bu"].round(2)
    out["usd_brl"] = out["usd_brl"].round(4)
    out["reais_centavos_per_bu"] = out["reais_centavos_per_bu"].round(1)
    return out.reset_index()
