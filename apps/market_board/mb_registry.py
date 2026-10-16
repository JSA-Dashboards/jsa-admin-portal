"""
One declaration per signal. The board renders these; nothing else defines them.

WHY A REGISTRY AND NOT TWENTY TILES WRITTEN OUT. Two consumers read the same
list -- the live board, and (later) the historical layer that asks what a
reading like today's has meant for cash. A second list would drift from the
first, and the drift would be invisible: both would render, both would be
defensible, and they would describe different signals. That is the
letter-versus-dashboard failure CLAUDE.md records twice, and this is the
generalisation of the fix `letter/rundown.py` already applies -- one assembly,
many renderers.

**`pick` MAY NOT DO ARITHMETIC ON MARKET NUMBERS.** It reaches into the bundle
and returns a value some upstream module already computed. The moment a tile
computes its own figure, this page becomes a second implementation of a number
another page already shows, and the two can disagree while both look right.
`tests/test_market_board.py` asserts it by AST: no `BinOp` anywhere in this
file. Where a figure genuinely needs deriving -- the packer-owned SHARE, which
`leverage` returns as head -- the derivation belongs in the module that owns
the data, with its own test, or the tile does not ship. It does not ship.

**EVERY SIGNAL CARRIES A BASIS STRING AND IT IS NOT OPTIONAL.** Half the traps
in CLAUDE.md are two correct numbers on different populations or different
clocks: head PURCHASED in a week against head SLAUGHTERED in it, a 7-day
rolling index window against a daily count, a 5-Area negotiated weight against
a national FI average. A tile without its basis invites exactly that
arithmetic from the reader.

**`max_age_days` IS MEASURED FROM WHEN THE NEXT PUBLICATION IS DUE**, never
from the report date. LM_CT153 reports the PRIOR week by schedule, so a
report-date rule marks it stale every Thursday on perfectly fresh data -- and
a panel that cries every week is one nobody reads in the week it matters.

**`depth` IS THE BACKTEST VERDICT, DECLARED HERE RATHER THAN DISCOVERED.**
`full` means the measured history spans the window a conditional study needs;
`partial` means it runs but over a span short enough that the page must say so
on every cell; `none` means no history claim may be made at all. Every value
below was established by live probe on 2026-10-07, not inferred from how old a
report looks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

# -- the four questions, in the market's own causal order ---------------------
#
# What beef is worth sets what the packer earns, which sets what he can pay for
# a fat, which sets what a feeder is worth. Supply is the slow backdrop behind
# all three. Ordering the cards any other way -- alphabetically, or by how
# interesting the number is -- breaks the only through-line the page has.
Q_BEEF = "What is beef worth?"
Q_DEMAND = "What is demand doing?"
Q_PACKER = "What is the packer's position?"
Q_FEEDER = "What is a feeder worth?"
Q_SUPPLY = "What is supply doing?"

# DEMAND SITS SECOND, between what beef is worth and what the packer earns,
# because it is the reason the cutout moves rather than a consequence of it. A
# cutout firming because Japan is buying is a different market from one firming
# because the kill shrank, and until this card existed the board could not tell
# those apart -- its entire demand side was the cutout itself.
QUESTIONS = (Q_BEEF, Q_DEMAND, Q_PACKER, Q_FEEDER, Q_SUPPLY)

FULL, PARTIAL, NONE = "full", "partial", "none"


@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    question: str
    #: What this number IS -- report, population, unit, clock. Mandatory.
    basis: str
    #: The feed, for the provenance footer.
    source: str
    #: bundle -> value. No arithmetic; see the module docstring.
    pick: Callable
    #: "money" | "pct" | "frac" | "head" | "lb" | "date" | "ratio"
    fmt: str
    cadence: str
    #: Days past the EXPECTED next publication before the figure is stale.
    max_age_days: int
    #: bundle -> date | None, the observation this value describes.
    as_of: Callable
    depth: str
    depth_note: str
    #: Which dashboard owns this number, for the "see it in full" link.
    page: str = ""


def _g(d, *path, default=None):
    """
    Walk nested dicts/Series without arithmetic and without raising.

    A missing key returns None so the tile renders as MISSING and the page says
    so. It never substitutes zero: CLAUDE.md records that a withheld cash
    region shown as "0 head" reads as "nobody traded", which is a statement and
    a wrong one.
    """
    cur = d
    for k in path:
        if cur is None:
            return default
        try:
            cur = cur[k]
        except (KeyError, IndexError, TypeError):
            return default
    return default if cur is None else cur


# ── the signals ──────────────────────────────────────────────────────────────

SIGNALS: tuple = (

    # -- Q_BEEF ---------------------------------------------------------------
    Signal(
        key="choice_cutout",
        label="Choice cutout",
        question=Q_BEEF,
        basis="LM_XB403 PM close · 600–900 lb Choice carcass composite · $/cwt",
        source="LM_XB403",
        pick=lambda b: _g(b, "cutout", "choice", "value"),
        fmt="money", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "cutout", "report_date"),
        depth=FULL,
        depth_note="2004-01-05, 22 yrs. Rows dated 2001–2003 carry a date and a null.",
        page="Beef Cutout",
    ),
    Signal(
        key="choice_5day",
        label="Choice 5-day average",
        question=Q_BEEF,
        basis="LM_XB403 · the five sessions BEFORE this print, not including it "
              "· $/cwt",
        source="LM_XB403",
        pick=lambda b: _g(b, "cutout", "choice", "avg5"),
        fmt="money", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "cutout", "report_date"),
        depth=FULL,
        depth_note="Window changed to iloc[-6:-1] on 2026-10-06; it needs six rows.",
        page="Beef Cutout",
    ),
    Signal(
        key="select_cutout",
        label="Select cutout",
        question=Q_BEEF,
        basis="LM_XB403 PM close · 600–900 lb Select carcass composite · $/cwt",
        source="LM_XB403",
        pick=lambda b: _g(b, "cutout", "select", "value"),
        fmt="money", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "cutout", "report_date"),
        depth=FULL, depth_note="2004-01-05, 22 yrs.",
        page="Beef Cutout",
    ),
    Signal(
        key="grading_pct",
        label="Choice & higher grading",
        question=Q_BEEF,
        basis="LSWFEDCC · % of graded carcasses · weekly · USDA's own prior-week "
              "column, never the preceding row we happen to hold",
        source="LSWFEDCC",
        pick=lambda b: _g(b, "cutout", "grading", "pct"),
        fmt="pct", cadence="weekly", max_age_days=14,
        as_of=lambda b: _g(b, "cutout", "grading", "report_date"),
        depth=PARTIAL,
        depth_note="Not probed to its start; treat any history claim as unverified.",
        page="Beef Cutout",
    ),

    # -- Q_DEMAND -------------------------------------------------------------
    #
    # A DIFFERENT CLOCK FROM EVERYTHING ELSE ON THIS BOARD, and the basis
    # strings say so on every tile. ERS publishes monthly and runs about six
    # weeks behind -- August data on 7 October -- where the cutout is same-day
    # and the purchase mix is a week. That is not staleness, it is customs
    # data, and a `max_age_days` written against a weekly cadence would mark
    # the whole card stale every day of its life.
    #
    # WHY ERS AND NOT FAS ESR, which JSA already publishes at
    # jpsi.com/export-sales-dashboard: ESR is weekly and far timelier, but it
    # is EXPORTS ONLY, it reports SALES rather than customs-cleared trade, and
    # it is product weight in metric tons. None of that can be set against a
    # WASDE forecast. ERS is the series WASDE forecasts, exactly -- for 2025
    # its world totals are 2,579.1 and 5,388.0 against the September 2026
    # WASDE's 2,579 and 5,388 -- which is the only reason an
    # actual-versus-forecast tile here means anything.
    Signal(
        key="exports_ytd",
        label="Beef exports, year to date",
        question=Q_DEMAND,
        basis="USDA ERS · customs-cleared, CARCASS weight, million lb · "
              "monthly, about six weeks behind · NOT the weekly FAS sales "
              "figure the Export Sales dashboard shows",
        source="USDA ERS",
        pick=lambda b: _g(b, "exports", "ytd"),
        fmt="mil_lb", cadence="monthly", max_age_days=80,
        as_of=lambda b: _g(b, "trade_asof"),
        depth=FULL,
        depth_note="ERS monthly to 1989. The countries sum to the published "
                   "World total with zero error across 904 month/flow pairs.",
        page="US Beef Trade",
    ),
    Signal(
        key="exports_yoy",
        label="Beef exports, year on year",
        question=Q_DEMAND,
        basis="USDA ERS · the same months a year earlier, so the comparison is "
              "like for like rather than against a part year",
        source="USDA ERS",
        pick=lambda b: _g(b, "exports", "yoy_pct"),
        fmt="pct_signed", cadence="monthly", max_age_days=80,
        as_of=lambda b: _g(b, "trade_asof"),
        depth=FULL, depth_note="ERS monthly to 1989.",
        page="US Beef Trade",
    ),
    Signal(
        key="imports_ytd",
        label="Beef imports, year to date",
        question=Q_DEMAND,
        basis="USDA ERS · customs-cleared, CARCASS weight, million lb · the "
              "other half of the demand picture, and the larger one",
        source="USDA ERS",
        pick=lambda b: _g(b, "imports", "ytd"),
        fmt="mil_lb", cadence="monthly", max_age_days=80,
        as_of=lambda b: _g(b, "trade_asof"),
        depth=FULL, depth_note="ERS monthly to 1989.",
        page="US Beef Trade",
    ),
    Signal(
        key="imports_yoy",
        label="Beef imports, year on year",
        question=Q_DEMAND,
        basis="USDA ERS · imports rise when domestic lean is tight, so this "
              "reads as a SUPPLY signal as much as a demand one",
        source="USDA ERS",
        pick=lambda b: _g(b, "imports", "yoy_pct"),
        fmt="pct_signed", cadence="monthly", max_age_days=80,
        as_of=lambda b: _g(b, "trade_asof"),
        depth=FULL, depth_note="ERS monthly to 1989.",
        page="US Beef Trade",
    ),
    Signal(
        key="exports_vs_forecast",
        label="Exports vs USDA's full-year forecast",
        question=Q_DEMAND,
        basis="ERS actuals projected on the five-year SEASONAL shape, less the "
              "WASDE forecast · million lb · a flat YTD x 12/n would be wrong "
              "in a direction that changes with the month you ask in",
        source="USDA ERS + WASDE",
        pick=lambda b: _g(b, "exports", "implied_vs_forecast"),
        fmt="mil_lb_signed", cadence="monthly", max_age_days=80,
        as_of=lambda b: _g(b, "trade_asof"),
        depth=PARTIAL,
        depth_note="ESMIS serves 25 WASDE releases, August 2024 forward, and "
                   "October 2025 is absent — that release was not published.",
        page="US Beef Trade",
    ),
    Signal(
        key="imports_vs_forecast",
        label="Imports vs USDA's full-year forecast",
        question=Q_DEMAND,
        basis="ERS actuals on the five-year seasonal shape, less the WASDE "
              "forecast · million lb · imports run heavy in the first quarter",
        source="USDA ERS + WASDE",
        pick=lambda b: _g(b, "imports", "implied_vs_forecast"),
        fmt="mil_lb_signed", cadence="monthly", max_age_days=80,
        as_of=lambda b: _g(b, "trade_asof"),
        depth=PARTIAL, depth_note="As exports vs forecast.",
        page="US Beef Trade",
    ),

    # -- Q_PACKER -------------------------------------------------------------
    Signal(
        key="negotiated_share",
        label="Negotiated share of the kill",
        question=Q_PACKER,
        basis="LM_CT153 §B · cash alone, grid EXCLUDED · share of USDA's "
              "published total REPORTED kill · reports the prior week",
        source="LM_CT153 §B",
        pick=lambda b: _g(b, "lev", "mix", "negotiated_pct"),
        fmt="frac", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "lev", "mix", "week"),
        depth=FULL,
        depth_note="2008-07-21, 950 wks. The four-way split does not exist before it.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="must_buy_share",
        label="Must-buy share (cash + neg. grid)",
        question=Q_PACKER,
        basis="LM_CT153 §B · negotiated + negotiated grid ÷ published total · "
              "the wider reading, shown beside the strict one, never folded in",
        source="LM_CT153 §B",
        pick=lambda b: _g(b, "lev", "mix", "must_buy_pct"),
        fmt="frac", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "lev", "mix", "week"),
        depth=FULL, depth_note="2008-07-21, 950 wks.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="committed_share",
        label="Already-bought share (formula + forward)",
        question=Q_PACKER,
        basis="LM_CT153 §B · formula + forward ÷ published total · the kill "
              "nobody had to bid for this week",
        source="LM_CT153 §B",
        pick=lambda b: _g(b, "lev", "mix", "committed_pct"),
        fmt="frac", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "lev", "mix", "week"),
        depth=FULL, depth_note="2008-07-21, 950 wks.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="forward_book",
        label="Forward book, next 3 delivery months",
        question=Q_PACKER,
        basis="LM_CT153 §C Breakdown · head COMMITTED and not yet delivered, "
              "vs the same months a year ago · a STOCK, not a weekly flow",
        source="LM_CT153 §C",
        pick=lambda b: _g(b, "near", "change"),
        fmt="frac_signed", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "lev", "forward", "week"),
        depth=PARTIAL,
        depth_note="A 100,000-row cap truncates the OLD end: the feed reports "
                   "MIN 2011-10-03 where the real start is 2009-02-16.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="cash_need",
        label="Cash need, 4-week run rate",
        question=Q_PACKER,
        basis="LM_CT153 §B · head/wk packers HAD to transact for over the last "
              "four weeks · a RUN RATE, not a forecast of this week",
        source="LM_CT153 §B",
        pick=lambda b: _g(b, "need", "cash"),
        fmt="head", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "need", "to"),
        depth=FULL, depth_note="2008-07-21, 950 wks.",
        page="Cash Cattle Trade",
    ),
    # AGAINST THE SAME WEEK A YEAR AGO, Ross's call on 2026-10-07.
    #
    # `weight_context` returns both this and `vs_trend`, a fit on the same ISO
    # week of the prior eight years. The trend figure reads larger -- +85.7 lb
    # against +67.3 on 2026-10-05 -- because fed cattle have got heavier for two
    # decades at roughly +6.9 lb/yr on this series, so a raw year-ago delta
    # carries about 7 lb of secular drift inside it. That is the argument for
    # the trend version and it is recorded here rather than argued in the UI.
    #
    # The year-ago figure is what the trade quotes and what every other weight
    # comparison on this portal uses, and a number nobody states the same way
    # twice is worse than a slightly noisier one. Same ISO week either way, so
    # the season is removed without a separate adjustment.
    Signal(
        key="weight_vs_year",
        label="Live weight vs year ago",
        question=Q_PACKER,
        basis="LM_CT150 · head-weighted steer+heifer live weight · against the "
              "SAME ISO WEEK a year ago, so the season is removed",
        source="LM_CT150",
        pick=lambda b: _g(b, "weight", "vs_year_ago"),
        fmt="lb_signed", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "weight", "week"),
        depth=FULL,
        depth_note="LM_CT150 runs to 2004-05-03, 1,169 wks. A year-ago "
                   "comparison needs only the prior year, so it reaches "
                   "back further than the fitted version would.",
        page="Cash Cattle Trade",
    ),

    # -- Q_FEEDER -------------------------------------------------------------
    # THE SETTLED INDEX, NEVER THE FORWARD ESTIMATE. Both tiles read the
    # `published` block, which is the newest COMPLETED session -- CME's own
    # printed figure when they have one (`from_cme`), our estimate for a
    # finished day when they have not. It is never the unfinished day.
    #
    # `fetch_feeder_index`'s top-level `value` is the index CME will print
    # NEXT. That is right for the CME Feeder Cattle Index dashboard and for the
    # morning brief, which both label it an estimate -- the AM block's heading
    # is literally "JSA FCI Estimate". It is wrong here for the same reason it
    # was wrong in the evening letter on 2026-10-07: this board prints a figure
    # with a label and no qualifier, so a reader takes it for the index as it
    # stands. On that date the forward estimate read 335.86 off 228 locations
    # and 17,524 head with the day still running, while CME had that morning
    # published 10/06 at 337.87 -- a figure our own estimate had already agreed
    # with to the cent (337.869294).
    #
    # `render.fci_published()` reads the same block for the two evening
    # rundowns and the rundown slide, so the letter, the slide and this board
    # quote one number and cannot drift. CLAUDE.md records three mornings lost
    # to this figure disagreeing across surfaces.
    Signal(
        key="feeder_index",
        label="CME Feeder Cattle Index",
        question=Q_FEEDER,
        basis="Pound-weighted 12-state #1 and #1-2 M&L steers 700–899 lb · "
              "rolling 7-day window · $/cwt · the newest COMPLETED session, "
              "CME's published figure where they have printed one — never the "
              "estimate for a day still running",
        source="JSA.CME_FEEDER_CATTLE (cme_ftp_daily)",
        pick=lambda b: _g(b, "fci", "published", "value"),
        fmt="money", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "fci", "published", "date"),
        depth=FULL,
        depth_note="CME_FTP_DAILY 2015-01-01, 11.75 yrs. RESTATED values only — "
                   "one row per date, no as-of column. Point-in-time starts "
                   "2026-08-19 with FCI_SNAPSHOTS.",
        page="CME Feeder Cattle Index",
    ),
    Signal(
        key="feeder_index_change",
        label="Feeder index, session on session",
        question=Q_FEEDER,
        basis="Two COMPLETED sessions · values rounded first, THEN differenced "
              "— so a reader holding two prints can subtract them and get this",
        source="JSA.CME_FEEDER_CATTLE (cme_ftp_daily)",
        pick=lambda b: _g(b, "fci", "published", "change"),
        fmt="money_signed", cadence="daily", max_age_days=4,
        as_of=lambda b: _g(b, "fci", "published", "date"),
        depth=FULL, depth_note="As the index.",
        page="CME Feeder Cattle Index",
    ),
    Signal(
        key="corn_delivered",
        label="Delivered corn, Nebraska",
        question=Q_FEEDER,
        basis="Elevator bid plus a delivery adder · $/bu DELIVERED to the "
              "feedyard, not an elevator bid · nearby delivery only",
        source="JSA.BASIS_TRACKER",
        pick=lambda b: _g(b, "corn", "NE", "price"),
        fmt="money", cadence="daily", max_age_days=14,
        as_of=lambda b: _g(b, "asof", "corn"),
        depth=PARTIAL,
        depth_note="Snapshot history not probed to its start. The ZC settlement "
                   "chain in BASIS_TRACKER reaches 2007-01-05 if a study needs one.",
        page="Fed Cattle Crush",
    ),

    # -- Q_SUPPLY -------------------------------------------------------------
    Signal(
        key="weekly_kill",
        label="Weekly FI cattle slaughter",
        question=Q_SUPPLY,
        basis="SJ_LS712 · ESTIMATE — Saturday and most of Friday are projected · "
              "week ending the Saturday AFTER publication",
        source="SJ_LS712",
        pick=lambda b: _g(b, "slaughter", "weekly", "value"),
        fmt="head", cadence="weekly", max_age_days=10,
        as_of=lambda b: _g(b, "slaughter", "weekly", "week_ending"),
        depth=NONE,
        depth_note="SJ_LS712 keeps ONE week — a 3.8 KB file, absent from both "
                   "report catalogs. A study must use NASS weekly head (1978-) "
                   "instead, which lags this by about two weeks.",
        page="Cattle Weights",
    ),
    Signal(
        key="kill_ytd",
        label="Slaughter, year to date",
        question=Q_SUPPLY,
        basis="SJ_LS712 · USDA's OWN published Change row, not our arithmetic",
        source="SJ_LS712",
        pick=lambda b: _g(b, "slaughter", "weekly", "ytd_chg_pct"),
        fmt="pct_signed", cadence="weekly", max_age_days=10,
        as_of=lambda b: _g(b, "slaughter", "weekly", "week_ending"),
        depth=NONE, depth_note="As the kill.",
        page="Cattle Weights",
    ),
    Signal(
        key="beef_production_ytd",
        label="Beef production, year to date",
        question=Q_SUPPLY,
        basis="SJ_LS712 · USDA's OWN published Change row · million lb",
        source="SJ_LS712",
        pick=lambda b: _g(b, "slaughter", "beef_production", "ytd_chg_pct"),
        fmt="pct_signed", cadence="weekly", max_age_days=10,
        as_of=lambda b: _g(b, "slaughter", "beef_production", "week_ending"),
        depth=NONE, depth_note="As the kill.",
        page="Cattle Weights",
    ),
    Signal(
        key="cash_5area",
        label="5-Area live cash",
        question=Q_SUPPLY,
        basis="LM_CT150 · head-weighted, steer+heifer combined · $/cwt · the "
              "headline price is NOT discounted for shrink; the WEIGHT is",
        source="LM_CT150",
        pick=lambda b: _g(b, "cash", "live", "this_week"),
        fmt="money", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "cash", "report_date"),
        depth=FULL,
        depth_note="2004-05-03, 1,169 wks, one hole (the Oct 1-16 2013 shutdown). "
                   "The negotiated head this price is discovered in fell 75% "
                   "between 2005 and 2025.",
        page="Cash Cattle Trade",
    ),
    Signal(
        key="negotiated_head",
        label="National negotiated head",
        question=Q_SUPPLY,
        basis="LM_CT154 · head PURCHASED in the week just ended — a DIFFERENT "
              "clock from LM_CT153's head SLAUGHTERED. Never divide one by the "
              "other: that ratio wandered 0.83–1.32 over six weeks.",
        source="LM_CT154",
        pick=lambda b: _g(b, "cash", "volume", "confirmed"),
        fmt="head", cadence="weekly", max_age_days=11,
        as_of=lambda b: _g(b, "cash", "volume", "report_date"),
        depth=FULL, depth_note="2002-11-18, 24 yrs.",
        page="Cash Cattle Trade",
    ),
)

BY_KEY = {s.key: s for s in SIGNALS}
ALL_KEYS = frozenset(BY_KEY)


def for_question(question: str) -> tuple:
    return tuple(s for s in SIGNALS if s.question == question)
