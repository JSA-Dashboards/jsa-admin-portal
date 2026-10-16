"""
What each signal means, and the few things that can only be said across two.

THREE TIERS, SPLIT ON WHETHER A SENTENCE CAN BE WRONG WITHOUT ANYONE NOTICING.

  1. The number and its as-of date. Arithmetic, or marked. No authoring.
  2. A committed sentence chosen by a rule from the signal's OWN direction.
     Written once, reviewed, in git, carrying `last_reviewed`.
  3. The cross-signal panels, which are the ONLY place a conclusion spanning
     two signals may be written.

**A TIER-2 TEMPLATE MAY NOT NAME A SIGNAL OUTSIDE ITS OWN `requires` SET**, and
a test asserts it against the rendered strings. This is not tidiness. An
earlier draft of this board had the cutout tile say "margin compressing on the
revenue side" -- a packer-margin call made from one leg -- six inches above a
cross-panel that refused to make that call because the cash print was eleven
days old. Both honestly computed; together, nonsense. That is the same shape as
the 2026-10-05 tiles-versus-scorecard failure CLAUDE.md records, and the fix is
structural: a sentence that needs two signals lives where both are in hand.

**STALENESS REPLACES THE CLAUSE; IT DOES NOT BADGE IT.** Past its window the
sentence is swapped for one naming the gap. A current-sounding reading under a
stale number is worse than no reading -- it is how the 2026-09-28 morning brief
printed 09-11 settles and read perfectly throughout.

**NOT AN LLM, WITH `ANTHROPIC_API_KEY` SITTING RIGHT THERE.** Three grounds,
each already paid for here in another form. It is non-deterministic, so the
board and the letter would agree on a number and disagree in words -- the
letter-versus-dashboard failure in a medium where nobody diffs two sentences.
It produces a confident sentence with no MISSING discipline, so a stale figure
acquires an explanation instead of a mark. And it is fetched editorial text
writing itself into a surface, the line `letter/render.py` has an import test
asserting it does not cross. The defensible use is generating CANDIDATES for a
human to pick, which is what the letter's headline panel already does, and it
is out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import mb_registry as registry
from mb_registry import _g

MISSING = "—"

OK, STALE, GONE = "ok", "stale", "missing"


# ── formatting ───────────────────────────────────────────────────────────────

def _f(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt(value, how: str) -> str:
    """
    Render one value. The ONLY arithmetic here is unit conversion of a single
    number -- a fraction to a percentage. Nothing is combined with anything.
    """
    v = _f(value)
    if v is None:
        return MISSING
    if how == "money":        return f"${v:,.2f}"
    if how == "money_signed": return f"{v:+,.2f}"
    if how == "pct":          return f"{v:,.1f}%"
    if how == "pct_signed":   return f"{v:+,.1f}%"
    if how == "frac":         return f"{v * 100:,.1f}%"
    if how == "frac_signed":  return f"{v * 100:+,.1f}%"
    if how == "head":         return f"{v:,.0f}"
    if how == "lb":           return f"{v:,.0f} lb"
    if how == "lb_signed":    return f"{v:+,.0f} lb"
    if how == "mil_lb":        return f"{v:,.0f}M lb"
    if how == "mil_lb_signed": return f"{v:+,.0f}M lb"
    if how == "ratio":        return f"{v:,.2f}"
    return f"{v:,.2f}"


def _as_date(v):
    """
    Anything the loaders hand back, as a plain `date`.

    THE ORDER OF THESE CHECKS IS THE WHOLE FUNCTION. `pandas.Timestamp`
    subclasses `datetime`, which subclasses `date` -- so an `isinstance(v, date)`
    test placed first returns the Timestamp UNCHANGED, and the next line that
    subtracts it from a real date raises. That is exactly how the first live run
    of this board failed, on data a hand-built fixture could never have
    produced: every fixture date was already a `date`.
    """
    if v is None:
        return None
    to_py = getattr(v, "to_pydatetime", None)      # pandas Timestamp
    if callable(to_py):
        try:
            v = to_py()
        except Exception:                          # noqa: BLE001
            pass
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def short(d) -> str:
    d = _as_date(d)
    return MISSING if d is None else f"{d.month}/{d.day}/{str(d.year)[2:]}"


# ── a reading ────────────────────────────────────────────────────────────────

@dataclass
class Reading:
    signal: registry.Signal
    value: object
    as_of: date | None
    state: str
    days_behind: int | None
    text: str = ""

    @property
    def shown(self) -> str:
        return fmt(self.value, self.signal.fmt)

    @property
    def ok(self) -> bool:
        return self.state == OK


def read(signal: registry.Signal, b: dict, today: date) -> Reading:
    """
    One tile's value, age and state.

    AGE IS MEASURED AGAINST THE EXPECTED NEXT PUBLICATION, which is what
    `max_age_days` encodes -- not against the report date. LM_CT153 reports the
    prior week by design, so a report-date rule would mark it stale every
    Thursday on perfectly current data. CLAUDE.md: a panel that cries every
    week is one nobody reads in the week it matters.
    """
    value = signal.pick(b)
    as_of = _as_date(signal.as_of(b))
    if value is None:
        return Reading(signal, None, as_of, GONE, None)
    behind = (today - as_of).days if as_of else None
    state = STALE if (behind is not None and behind > signal.max_age_days) else OK
    return Reading(signal, value, as_of, state, behind)


# ── tier 2: the rule table ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Rule:
    key: str
    #: bundle -> "up" | "down" | "flat" | None. None means we cannot tell, and
    #: the clause is then replaced rather than guessed at.
    direction: object
    up: str
    down: str
    flat: str = ""
    #: Signals this clause is allowed to mention. Enforced by test.
    requires: tuple = field(default_factory=tuple)
    last_reviewed: date = date(2026, 10, 7)


def _sign(v, dead=0.0):
    f = _f(v)
    if f is None:
        return None
    if f > dead:
        return "up"
    if f < -dead:
        return "down"
    return "flat"


RULES = {

    "choice_cutout": Rule(
        key="choice_cutout",
        direction=lambda b: _sign(_g(b, "cutout", "choice", "change")),
        up="Beef is worth more than it was at the last print. That is the "
           "packer's revenue line moving his way — it widens what he can pay "
           "and still make the kill work.",
        down="Beef is worth less than at the last print. The packer is selling "
             "into a weaker market, which is the configuration that precedes "
             "him slowing the chain rather than bidding up.",
        flat="Beef is unchanged on the print. Nothing in the cutout is pushing "
             "the packer either way today.",
        requires=("choice_cutout",),
    ),

    "select_cutout": Rule(
        key="select_cutout",
        direction=lambda b: _sign(_g(b, "cutout", "select", "change")),
        up="The Select carcass firmed. Select leads on the end meats, so it "
           "tends to move with grinding and food-service demand rather than "
           "with the middle meats.",
        down="The Select carcass broke. When Select falls and Choice does not, "
             "the composite is being held up by high-quality demand alone, "
             "which is narrower support than the headline suggests.",
        flat="Select is unchanged on the print.",
        requires=("select_cutout",),
    ),

    "negotiated_share": Rule(
        key="negotiated_share",
        direction=lambda b: _pctile_dir(b, "negotiated_pct"),
        up="An unusually large share of the kill had to be bid for this week. "
           "The packer could not lean on cattle he already owned, which is the "
           "condition under which cash discovers a real price.",
        down="An unusually small share of the kill had to be bid for. Most of "
             "the week's cattle were already committed, so the cash trade that "
             "did happen set the price for a thin slice of the market.",
        flat="The share needing a bid is near its three-year normal.",
        requires=("negotiated_share",),
    ),

    "forward_book": Rule(
        key="forward_book",
        direction=lambda b: _sign(_g(b, "near", "change")),
        up="The packer has MORE committed supply coming than a year ago. Cattle "
           "already bought are cattle he does not have to compete for, and that "
           "is leverage he can spend by standing back from the cash market.",
        down="The packer has LESS committed supply coming than a year ago. A "
             "shrinking book is the clearest single argument that he has to "
             "come to the cash market rather than wait it out.",
        flat="The forward book is level with a year ago.",
        requires=("forward_book",),
    ),

    "weight_vs_year": Rule(
        key="weight_vs_year",
        direction=lambda b: _sign(_g(b, "weight", "vs_year_ago")),
        up="Cattle are heavier than the same week a year ago. Animals held past "
           "their window put on weight, so the showlist is carrying more pounds "
           "than a head count suggests and feedyards are behind. It is also "
           "tonnage that arrives whether or not the kill grows.",
        down="Cattle are lighter than the same week a year ago. Feedyards are "
             "current or ahead, which means less standing inventory behind the "
             "showlist than a head count implies.",
        flat="Weights are level with the same week a year ago.",
        requires=("weight_vs_year",),
    ),

    "feeder_index": Rule(
        key="feeder_index",
        direction=lambda b: _sign(_g(b, "fci", "published", "change")),
        up="Buyers paid more for replacement cattle day on day. The index is "
           "the settlement reference the whole feeder complex prices against, "
           "so this is the number a feeder contract marks to.",
        down="Buyers paid less for replacement cattle day on day. Softer "
             "replacement demand usually reflects feed cost or a thin offering "
             "rather than a change in appetite for cattle.",
        flat="Replacement values were unchanged day on day.",
        requires=("feeder_index",),
    ),

    "kill_ytd": Rule(
        key="kill_ytd",
        direction=lambda b: _sign(_g(b, "slaughter", "weekly", "ytd_chg_pct")),
        up="More cattle have been killed this year than last. Read it as "
           "USDA's own published rate rather than our arithmetic — it is their "
           "Change row, and it moves when they restate.",
        down="Fewer cattle have been killed this year than last. A smaller kill "
             "against steady demand is the structural support under the whole "
             "complex, and it is the slowest-moving thing on this page.",
        flat="The kill is level with last year to date.",
        requires=("kill_ytd",),
    ),

    "cash_5area": Rule(
        key="cash_5area",
        direction=lambda b: _week_dir(b),
        up="Fed cattle traded higher than the previous week. The 5-Area average "
           "is head-weighted across steers and heifers, so a move here is "
           "volume-backed rather than one feedyard's print.",
        down="Fed cattle traded lower than the previous week. Worth reading "
             "beside the week's negotiated head: selling more cattle into a "
             "lower average is a different market from selling fewer.",
        flat="Fed cattle were level with the previous week.",
        requires=("cash_5area",),
    ),
    "exports_yoy": Rule(
        key="exports_yoy",
        direction=lambda b: _sign(_g(b, "exports", "yoy_pct")),
        up="More beef is leaving the country than a year ago. Export demand "
           "competes with domestic buyers for the same middle meats and the "
           "same variety meats, so it lifts the cutout from outside the "
           "domestic market entirely.",
        down="Less beef is leaving the country than a year ago. Product that "
             "would have shipped has to clear at home instead, which is "
             "cutout pressure that no domestic demand number will show.",
        flat="Exports are level with a year ago.",
        requires=("exports_yoy",),
    ),
    "imports_yoy": Rule(
        key="imports_yoy",
        direction=lambda b: _sign(_g(b, "imports", "yoy_pct")),
        up="More beef is coming in than a year ago. Imports are overwhelmingly "
           "lean trimmings, so a rise says domestic lean is tight and the "
           "grinding trade is sourcing abroad rather than bidding up cull "
           "cows — supportive for cows, and a ceiling on 90s.",
        down="Less beef is coming in than a year ago. Grinders are covering "
             "from domestic lean, which bids the cow market rather than the "
             "import offer.",
        flat="Imports are level with a year ago.",
        requires=("imports_yoy",),
    ),
    "exports_vs_forecast": Rule(
        key="exports_vs_forecast",
        direction=lambda b: _sign(_g(b, "exports", "implied_vs_forecast")),
        up="The year is running AHEAD of USDA's own full-year export forecast. "
           "A forecast the market is beating is one that gets revised up, and "
           "the revision is what moves deferred expectations.",
        down="The year is running BEHIND USDA's full-year export forecast. "
             "Either the back half has to accelerate or the forecast comes "
             "down, and the second is the more common resolution.",
        flat="Exports are tracking USDA's forecast.",
        requires=("exports_vs_forecast",),
    ),
    "imports_vs_forecast": Rule(
        key="imports_vs_forecast",
        direction=lambda b: _sign(_g(b, "imports", "implied_vs_forecast")),
        up="Imports are running AHEAD of USDA's full-year forecast. More "
           "foreign lean than expected is more total beef on the domestic "
           "market than the supply numbers alone imply.",
        down="Imports are running BEHIND USDA's full-year forecast. Less "
             "foreign lean than expected tightens the grinding trade further "
             "than the domestic kill suggests.",
        flat="Imports are tracking USDA's forecast.",
        requires=("imports_vs_forecast",),
    ),
}


def _pctile_dir(b, column):
    """
    Where this week's share sits in its own three-year distribution.

    `leverage.percentile` refuses to speak on fewer than 20 observations, so a
    thin window returns None here and the clause is replaced rather than
    computed from almost nothing.
    """
    import leverage
    mix = _g(b, "frames", "mix")
    value = _g(b, "lev", "mix", column)
    if mix is None or value is None or getattr(mix, "empty", True):
        return None
    try:
        p = leverage.percentile(mix, column, value, 3)
    except Exception:                               # noqa: BLE001
        return None
    if p is None:
        return None
    if p >= 0.67:
        return "up"
    if p <= 0.33:
        return "down"
    return "flat"


def _week_dir(b):
    """This week's 5-Area live average against last week's, as USDA prints both."""
    now, prior = _g(b, "cash", "live", "this_week"), _g(b, "cash", "live", "last_week")
    a, c = _f(now), _f(prior)
    if a is None or c is None:
        return None
    if a > c:
        return "up"
    if a < c:
        return "down"
    return "flat"


def clause(reading: Reading, b: dict) -> str:
    """
    The tier-2 sentence, or the reason there isn't one.

    FOUR STATES, AND THE LAST THREE ARE SENTENCES TOO. Missing, stale and
    undetermined all print something: a tile that silently loses its clause
    reads as a signal with nothing to say, which is itself a claim.
    """
    if reading.state == GONE:
        return "No reading — the source returned nothing for this figure."
    if reading.state == STALE:
        return (f"Not current enough to read. The newest observation is "
                f"{short(reading.as_of)}, {reading.days_behind} days back, past "
                f"the {reading.signal.max_age_days}-day window for this report.")
    rule = RULES.get(reading.signal.key)
    if rule is None:
        return ""
    try:
        d = rule.direction(b)
    except Exception:                               # noqa: BLE001
        d = None
    if d is None:
        return "Not enough to say which way this is pointing."
    return {"up": rule.up, "down": rule.down, "flat": rule.flat}.get(d, "")


# ── tier 3: the cross-signal panels ──────────────────────────────────────────

@dataclass(frozen=True)
class Cross:
    key: str
    title: str
    requires: tuple
    #: (readings_by_key, bundle) -> str
    body: object


def _packer_margin(r, b):
    cut, cash = r["choice_cutout"], r["cash_5area"]
    cd = _sign(_g(b, "cutout", "choice", "change"))
    sd = _week_dir(b)
    if cd is None or sd is None:
        return ("Not enough to say. One leg of the comparison has no direction "
                "this week.")
    lead = (f"Cutout {cd} as of {short(cut.as_of)}; 5-Area cash {sd} as of "
            f"{short(cash.as_of)} — different clocks, so read the dates.")
    if cd == "up" and sd != "up":
        return lead + (" **Margin widening.** The packer's revenue rose while "
                       "his cost did not. That is the configuration in which he "
                       "can afford to bid, whether or not he chooses to.")
    if cd == "down" and sd != "down":
        return lead + (" **Margin compressing.** Beef fell while cattle did "
                       "not. Historically this is what precedes a slower chain "
                       "and a harder bid, because the packer's answer to a "
                       "squeeze is volume, not price.")
    return lead + (" **Margin roughly held.** Both legs moved the same way, so "
                   "the squeeze between them is about where it was.")


def _leverage_tension(r, b):
    """
    The two readings that disagree, printed as two readings that disagree.

    NEVER AVERAGED INTO A SCORE. These genuinely point opposite ways right now,
    and that tension is the most informative thing on the page. A composite
    gauge would hide precisely the fact worth knowing — which is why this board
    carries no bull/bear needle anywhere.
    """
    w, f = r["weight_vs_year"], r["forward_book"]
    wv, fv = _f(w.value), _f(f.value)
    if wv is None or fv is None:
        return "Not enough to say — one side of the tension is missing."
    heavy, short_book = wv > 0, fv < 0
    lines = [
        f"**Weights {fmt(wv, 'lb_signed')} against the same week a year ago** "
        f"({short(w.as_of)}) — "
        + ("cattle are backing up, so the packer can wait rather than raise his bid."
           if heavy else
           "feedyards are current, so there is less standing inventory to lean on."),
        f"**Forward book {fmt(fv, 'frac_signed')} on the next three delivery "
        f"months** ({short(f.as_of)}) — "
        + ("he is short of committed supply and has to come to the cash market."
           if short_book else
           "he has committed supply coming and can stand back."),
    ]
    if heavy and short_book:
        lines.append("**These disagree, and that is the market, not a bug.** "
                     "Both are true. The board shows both rather than averaging "
                     "them into a score that would hide the tension.")
    else:
        lines.append("Both point the same way this week, which is the simpler "
                     "and rarer case.")
    return "\n\n".join(lines)


def _kill_vs_cutout(r, b):
    kill = _sign(_g(b, "slaughter", "weekly", "chg_wow_pct"))
    cut = _sign(_g(b, "cutout", "choice", "change"))
    if kill is None or cut is None:
        return "Not enough to say — one leg has no direction this week."
    if kill == "up" and cut == "down":
        return ("A rising kill into a falling cutout is tonnage being pushed, "
                "not demand being met. The packer is moving inventory by "
                "cutting price.")
    if kill == "down" and cut == "up":
        return ("A falling kill into a firming cutout is margin management — "
                "supply withheld from the box to hold the price up.")
    return ("Kill and cutout moved the same way, so the week is demand-led "
            "rather than a volume decision.")


def _demand_vs_supply(r, b):
    """
    The question the board could not ask before the demand card existed.

    A cutout firming because exports are strong is a different market from one
    firming because the kill shrank, and every other panel here reads supply.
    """
    ex, im = _f(r["exports_yoy"].value), _f(r["imports_yoy"].value)
    if ex is None or im is None:
        return "Not enough to say — one side of the trade picture is missing."
    lines = [
        f"**Exports {fmt(ex, 'pct_signed')} on the year** — "
        + ("foreign buyers are taking more product off the domestic market."
           if ex > 0 else
           "product that would have shipped is clearing at home instead."),
        f"**Imports {fmt(im, 'pct_signed')} on the year** — "
        + ("more foreign lean is arriving, so the grinding trade is sourcing "
           "abroad rather than bidding domestic cows."
           if im > 0 else
           "less foreign lean is arriving, which tightens the grind at home."),
    ]
    if ex < 0 < im:
        lines.append("**Net, the trade account is working against the domestic "
                     "market**: less going out and more coming in is more beef "
                     "to clear here than the kill alone implies. Read the "
                     "cutout against that rather than against supply only.")
    elif ex > 0 > im:
        lines.append("**Net, the trade account is tightening domestic supply**: "
                     "more leaving and less arriving. That is support the "
                     "slaughter figures do not show.")
    else:
        lines.append("Both moved the same way, so trade is not the swing factor "
                     "in domestic availability this year.")
    return "\n\n".join(lines)


CROSSES = (
    Cross("packer_margin", "Is the packer's margin widening or compressing?",
          ("choice_cutout", "cash_5area"), _packer_margin),
    Cross("leverage_tension", "These two disagree, and that is the market",
          ("weight_vs_year", "forward_book"), _leverage_tension),
    Cross("kill_vs_cutout", "Is the week demand-led or volume-led?",
          ("weekly_kill", "choice_cutout"), _kill_vs_cutout),
    Cross("demand_vs_supply", "Is trade adding to the domestic market or taking from it?",
          ("exports_yoy", "imports_yoy"), _demand_vs_supply),
)


def crosses(readings: dict, b: dict) -> list:
    """
    Every cross-panel whose members all resolved, with the ones that did not.

    A PANEL THAT CANNOT RENDER SAYS SO. Returning it silently absent would read
    as "these signals agree", which is a claim nobody made.
    """
    out = []
    for c in CROSSES:
        missing = [k for k in c.requires
                   if k not in readings or not readings[k].ok]
        if missing:
            labels = ", ".join(registry.BY_KEY[k].label for k in missing
                               if k in registry.BY_KEY)
            out.append((c, f"Not enough to say — waiting on {labels}.", False))
        else:
            out.append((c, c.body(readings, b), True))
    return out
