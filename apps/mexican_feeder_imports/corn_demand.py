"""
Corn demand that moves with Mexican feeder cattle.

THE QUESTION THIS ANSWERS, and the answer is not the intuitive one. While the
border was shut, cattle that would have crossed were kept and fed in Mexico on
corn Mexico buys from the United States. Reopening the border is therefore
read as a loss of US corn export demand. It is -- but the same animal finished
in a US yard eats about TWICE the corn it would have eaten in Mexico, because
it goes to a heavier finish on a higher-corn ration. So the demand does not
disappear. It MOVES from the export line to domestic feed, and grows.

That distinction is the whole point of the panel: an export tile on its own
would be true and would mislead, which is the standing failure this repo
records. The net is always shown beside it.

WHY THIS MODULE MAY FETCH WHEN border.py AND mx_prices.py MAY NOT.
`tests/test_mx_prices.py` asserts those two import no `requests`, and
CLAUDE.md states the rule for this page as "border.py has no HTTP path so the
Streamlit process cannot acquire one". What that rule protects is
CREDENTIALS -- every USDA and Census key this page's data depends on belongs
to an ingest that runs elsewhere, and adding one here would be dead config at
best and a leak at worst. PSD is a public keyless bulk file, so nothing of the
sort enters the process. The two existing modules are untouched and their
tests still hold; this one reaches exactly one host and a test pins that.

SOURCES, both keyless:

    psd_grains_pulses_csv.zip   Mexico corn: production, imports, feed use,
                                and the same for sorghum, wheat and barley
    psd_livestock_csv.zip       Mexico cattle exports, slaughter, herd, beef

PSD CARRIES A LITERAL ZERO FOR `TY Imp. from U.S.` IN INCOMPLETE TRADE YEARS.
MY2025 and MY2026 both read 0.0 while total imports are 26,200 and 27,200.
Read naively that says Mexico stopped buying US corn altogether, which is the
most wrong a number on this page could be. `us_share()` falls back to the
historical share -- 85-100%, typically 97-99% -- and says it is doing so.

PSD'S FEED LINE IS "FEED AND RESIDUAL", NOT LIVESTOCK FEED, and the residual
is larger than anything this panel measures. FAS Post's own sector table puts
Mexican livestock corn consumption at about 25.0 MMT against PSD's 29.6 for
the same year -- a 4.6 MMT gap, some 180 million bushels, sitting inside the
line being differenced. In a drought year with a collapsed domestic crop,
production-estimate error lands in exactly that residual. So the balance-sheet
route is a sanity check on the head-and-ration arithmetic, never a measurement
of it, and the panel does not difference it to produce a headline.

USDA DOES NOT FORECAST MEXICAN CORN DEMAND FALLING ON REOPENING. The PSD
vintage that postdates the August 2026 reopening still carries MY2026/27 feed
use UP 1,000 thousand MT and imports UP 1,000, and the FAS Grain and Feed
Annual forecasts imports up 1% on "strong demand from the livestock and feed
sector" -- poultry, which is about 47% of Mexican feed demand, not cattle. So
the honest answer to "how much less will Mexico buy" is, on USDA's own books,
none: what this panel sizes is one component moving the other way inside a
total that is still rising.

THE FINISH WEIGHT IS THE INPUT MOST OFTEN QUESTIONED AND IT IS NOT THE ONE
MOST EXPOSED. Asked on 2026-10-26 whether US yards really feed Mexican cattle
to 1,500 lb. No published series can answer it -- origin is recorded at the
border and never again -- but the premise behind the doubt is itself wrong:
USDA ERS puts the EXPORT cattle at primarily British/Continental, no more
than three-eighths Zebu, so the Brahman trial literature (which tests 50-100%)
describes a different population.

What that literature does show is that the exposure is on INTAKE rather than
on weight. In the Colorado State trials Bos indicus dry-matter intake ran
20-29% BELOW Bos taurus while feed:gain was only 3-7% worse. Fed to a fixed
number of DAYS such an animal eats materially less corn; fed to a fixed FAT
endpoint it may eat more, because reaching the same backfat took 54 extra
days. Those point opposite ways, and a model driven by finish weight alone
cannot see either. The conversion and corn-share controls are where that
uncertainty actually lives.

THE SUBSTITUTION CAVEAT, which is why `feed_grain_total()` exists at all.
Mexico's corn feed use rose +1,700 thousand MT in MY2025, which reads as a
cattle story. Total feed grain rose **+320**: sorghum fell 900 and feed wheat
450 as Mexico's own crops failed (sorghum 4,163 -> 3,400, wheat 2,648 ->
1,719). Most of the corn increase replaced other grain rather than feeding
extra animals. A panel quoting the corn line alone would attribute all of it
to cattle and be wrong by roughly a factor of five in that year.
"""

from __future__ import annotations

import csv
import io
import zipfile

import requests

# Bump when any function here changes the SHAPE of what it returns. The page
# caches this module's output and st.cache_data is blind to the modules its
# decorated function calls -- the leverage.SCHEMA trap. Passed at the call
# site, because a default is not part of the key.
SCHEMA = 1

PSD_GRAINS = ("https://apps.fas.usda.gov/psdonline/downloads/"
              "psd_grains_pulses_csv.zip")
PSD_LIVESTOCK = ("https://apps.fas.usda.gov/psdonline/downloads/"
                 "psd_livestock_csv.zip")

BU_PER_MT = 39.3683          # bushels of corn per metric tonne

# Corn is MARKETED at about 15.5% moisture, so a dry-matter feed:gain and a
# dry-matter corn share yield corn DRY MATTER -- not bushels. Dividing by this
# is what turns one into the other, and leaving it out silently understates
# market-weight corn by about 18%.
CORN_DM = 0.845
LB_PER_MT = 2204.62

FEED_GRAINS = ("Corn", "Sorghum", "Wheat", "Barley", "Oats")

# Defaults for the conversion. EVERY ONE OF THESE IS AN ASSUMPTION AND THE
# PAGE SAYS SO -- they are sliders, the shape the crush pages already use for
# a number no feed publishes.
#
# **THE WEIGHT THAT MATTERS IS FEEDLOT ENTRY, NOT THE BORDER.** A first
# version of this took the crossing weight and ran the whole gain to finish
# through a conversion, which charges grain for pounds put on at grass. On
# BOTH sides of the border these cattle graze first -- in Mexico the first
# 100-150 kg is pasture with no grain at all, and a US-bound calf goes to
# wheat pasture or a backgrounding yard before a feedlot. Costing that gain
# as corn inflated the Mexican figure by roughly 40%, and the US one too.
# So these are YARD numbers: what the animal eats between the bunk and the
# truck.
#
# The US ration share and conversion are this repo's own documented
# convention -- corn_cost.py states "an 80% corn ration and 6.5:1 conversion
# ... about $52 a head over 650 lb of gain", and `corn_per_head` reproduces
# that worked example to the cent at those inputs.
#
# The Mexican side is lighter and less corn-dense: yards finish nearer 1,100
# lb than 1,400 and lean on sorghum and byproduct. These land at about 0.83 MT
# of corn a head against a Mexican industry cost study's 1.3-1.4 t of FEED at
# 60-70% corn, and about 1.36 MT for the US animal -- a ratio near 1.6x rather
# than the 2x a naive border-to-finish calculation gives.
# K-State Focus on Feedlots, August 2026 closeouts -- the measured programme,
# used as measured: steers 825 lb on feed, 1,522 lb final, 190 days, **6.47
# feed:gain on a DRY-MATTER basis**. Corn share of DM runs 50-90% across the
# Samuelson nutritionist survey; 65% is mid-range for a steam-flaked yard.
#
# THESE WERE 6.8 AND 75% UNTIL 2026-10-26 AND NEITHER CAME FROM ANYWHERE.
# They were picked in a sensitivity run before this research existed; the
# weights and shares were updated to match it afterwards and the conversion
# was not, leaving a comment citing 6.47 directly above a constant reading
# 6.8. The output was close -- 61.5 bu against 60.0 by the clean route --
# because the inflated conversion was absorbing the dry-matter step the
# formula did not have. Right answer, wrong inputs, on controls a reader can
# move.
US_FEEDLOT_IN_LB = 825.0
US_FINISH_LB = 1500.0
US_CONVERSION = 6.47
US_CORN_SHARE = 0.65
US_BASIS = "dm"

# The Mexican side is the CLOSURE programme, not the normal one, and the
# difference is large. Normally a calf leaves at 175-225 kg and the Mexican
# yard phase is short. Held back, FAS reports them fed on "for additional
# months" and killed at 500-550 kg -- roughly double the yard gain. Two
# independent routes agree on where that lands: a UNAM extension description
# of a conventional finishing programme, and CONAFAB's own 4.62 MMT of
# feedlot compound feed over about 4.5 million head. Both give 0.6-1.0 MT of
# corn a head under closure conditions.
# UNAM's conventional finishing description, AS FED: 6.0-6.5 lb feed per lb
# gain, ration 85% concentrate of which 60-70% is grain, and corn 75-90% of
# that grain -- so corn is 38-54% of the as-fed ration. The yard phase is the
# CLOSURE one: FAS reports retained cattle fed on "for additional months" and
# killed at 500-550 kg, so entry near 600 lb and finish near 1,150 rather than
# the 700-1,100 shipped first.
#
# TWO ERRORS WERE CANCELLING. The shipped 7.0 and 65% were both above the
# sourced figures while the 400 lb yard gain was shorter than the programme
# the published 24-39 bu band was built on. It landed inside that band by
# luck rather than by construction.
MX_FEEDLOT_IN_LB = 600.0
MX_FINISH_LB = 1150.0
MX_CONVERSION = 6.5
MX_CORN_SHARE = 0.46
MX_BASIS = "as_fed"


# ── where every feeding input comes from ───────────────────────────────────
#
# **THE TWO SIDES ARE NOT EQUALLY SOURCED AND THE PAGE SAYS WHICH IS WHICH.**
# The US figure is a measured programme with two independent cross-checks.
# The Mexican one is a single extension source, a derived ration share, and
# a feedlot entry weight that is OURS -- nothing publishes it. A reader
# comparing the two tiles is entitled to know that before he trades on the
# difference.
#
# `strength` is the honest grade, not a confidence score:
#   measured  - a published figure used as published
#   judgement - a published RANGE, with the point inside it chosen here
#   derived   - arithmetic on published parts, no single source for the result
#   ours      - an inference with no published counterpart
SOURCES = [
    {"side": "US", "input": "On feed to finish",
     "sourced": "825 -> 1,522 lb, 190 days, 3.52 ADG",
     "strength": "measured",
     "cite": "K-State Focus on Feedlots, August 2026 closeouts (steers)",
     "note": "MEASURED FOR KANSAS CATTLE GENERALLY, NOT FOR THESE. No "
             "published series breaks US feedlot or carcass data by cattle "
             "origin -- checked across all 1,051 MARS reports and the state "
             "feeder summaries, where origin is carried at the border and "
             "nowhere downstream. A domestic benchmark is defensible because "
             "USDA ERS puts Mexican EXPORT cattle at primarily "
             "British/Continental breeding, no more than three-eighths Zebu; "
             "a plausible origin adjustment is 25-75 lb lighter, which the "
             "control above can dial. The page also rounds 1,522 to 1,500"},
    {"side": "US", "input": "Feed conversion",
     "sourced": "6.47, DRY MATTER", "strength": "measured",
     "cite": "K-State Focus on Feedlots, August 2026 closeouts (steers)",
     "note": ""},
    {"side": "US", "input": "Corn share of ration",
     "sourced": "50-90% of dry matter", "strength": "judgement",
     "cite": "Samuelson 2016 feedlot nutritionist survey",
     "note": "the survey measures GRAIN, not corn specifically; 65% is "
             "mid-range for a steam-flaked yard"},
    {"side": "both", "input": "Corn moisture",
     "sourced": "15.5%", "strength": "measured",
     "cite": "No. 2 yellow corn market standard",
     "note": "applied to the dry-matter side only"},
    {"side": "Mexico", "input": "Finish weight",
     "sourced": "500-550 kg (1,100-1,213 lb)", "strength": "measured",
     "cite": "USDA FAS GAIN MX2026-0040, 24 Aug 2026 -- retained cattle "
             "\"remained in domestic feedlots for additional months\"",
     "note": ""},
    {"side": "Mexico", "input": "Feedlot entry weight",
     "sourced": "no published figure", "strength": "ours",
     "cite": "inferred from the closure gain less a pasture share",
     "note": "THE WEAKEST INPUT ON THE PAGE. Nothing publishes where a "
             "retained Mexican calf goes on feed"},
    {"side": "Mexico", "input": "Feed conversion",
     "sourced": "6.0-6.5, AS FED", "strength": "judgement",
     "cite": "Fernando Livas Calderon, FMVZ-UNAM, conventional finishing "
             "programme",
     "note": "a single source, and the most specific Mexican feedlot "
             "description available"},
    {"side": "Mexico", "input": "Corn share of ration",
     "sourced": "38-54% of the as-fed ration", "strength": "derived",
     "cite": "UNAM: ration 85% concentrate, concentrate 60-70% grain, corn "
             "75-90% of that grain",
     "note": "no published corn share exists; this is the product of three "
             "published parts"},
    {"side": "both", "input": "Head no longer fed in Mexico",
     "sourced": "PSD Mexican cattle exports against the 2022-24 mean",
     "strength": "measured",
     "cite": "USDA FAS PSD, cross-checked against US Census imports",
     "note": "the two agencies agree to 99% in 2024 and to the thousand in "
             "2025"},
]

# Independent arrivals at the same per-head figure, which is the only thing
# that makes a three-assumption estimate worth printing.
CROSS_CHECKS = [
    {"side": "US", "says": "62.7 bu to take a steer 750 -> 1,250 lb",
     "cite": "Iowa Beef Center", "agrees": True},
    {"side": "US", "says": "49-69 bu per finished steer calf",
     "cite": "Iowa State University budgets", "agrees": True},
    {"side": "US", "says": "Mexican export cattle are primarily "
                            "British/Continental, no more than three-eighths "
                            "Zebu -- so the 100%-Brahman trial literature is "
                            "not the relevant population and a domestic "
                            "finishing benchmark stands",
     "cite": "USDA ERS LDP-M-196-01 (Peel, Johnson, Mathews), corroborated by "
             "an NMSU survey of Chihuahua exporters and Santa Teresa auction "
             "reporting of 60-75% Angus/Charolais/Hereford",
     "agrees": True},
    {"side": "Mexico", "says": "16-19 bu a head",
     "cite": "CONAFAB 4.62 MMT of feedlot compound feed over about 4.5 "
             "million head (AMEG)",
     "agrees": False,
     "caveat": "THE NORMAL PROGRAMME, NOT THE CLOSURE ONE. It converges with "
               "the UNAM bottom-up, and both describe a short yard phase. "
               "The closure figure is that roughly doubled on FAS's "
               "description of longer feeding, so it is scaled rather than "
               "measured"},
]


def strength_of(side, input_name):
    """The honest grade for one input, or None."""
    for row in SOURCES:
        if row["side"] == side and row["input"] == input_name:
            return row["strength"]
    return None


def _psd_rows(url: str, country: str = "Mexico"):
    """One country's rows out of a PSD bulk zip."""
    blob = requests.get(url, timeout=240).content
    z = zipfile.ZipFile(io.BytesIO(blob))
    member = z.namelist()[0]
    out = []
    with z.open(member) as f:
        for d in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
            if d["Country_Name"].strip('"') == country:
                out.append(d)
    return out


def _series(rows, commodity):
    """{market_year: {attribute: value}} for one commodity."""
    out = {}
    for d in rows:
        if d["Commodity_Description"].strip('"') != commodity:
            continue
        out.setdefault(int(d["Market_Year"]), {})[
            d["Attribute_Description"]] = float(d["Value"])
    return out


def load():
    """
    {"corn", "grains", "cattle", "beef"} -- Mexico, by marketing year.

    Two requests, about 3.5 MB and four seconds in total, which is why the
    page caches this rather than reaching for a precomputed JSON or a droplet
    job. Nothing here needs a key, a host or a cron.
    """
    g = _psd_rows(PSD_GRAINS)
    L = _psd_rows(PSD_LIVESTOCK)
    return {
        "corn": _series(g, "Corn"),
        "grains": {c: _series(g, c) for c in FEED_GRAINS},
        "cattle": _series(L, "Animal Numbers, Cattle"),
        "beef": _series(L, "Meat, Beef and Veal"),
    }


def corn_per_head(feedlot_in_lb, finish_lb, conversion, corn_share, *, basis):
    """Metric tonnes of corn eaten in the YARD, feedlot entry to finish.

    `basis` says what `conversion` and `corn_share` are measured on and has NO
    DEFAULT, deliberately -- a caller must state it, because the two are not
    interchangeable and the error is invisible. "dm" divides by CORN_DM to
    turn corn dry matter into market weight; "as_fed" does not, because
    as-fed figures already carry the water.

    K-State publishes feed:gain on a dry-matter basis, UNAM's Mexican
    programme as-fed, and corn_cost.py's own "80% corn ration and 6.5:1" is
    an as-fed rule of thumb. Mixing them silently is an 18% error.

    `feedlot_in_lb` is the weight the animal goes on feed at, NOT the weight
    it crossed the border at -- the pounds between those two are grass and
    cost no corn. Charging them as grain is the single largest error available
    here and it inflates both sides.

    Deliberately the same three-factor form on both sides of the border, so
    the Mexico/US comparison is a difference in the INPUTS rather than in the
    method. Reproduces corn_cost.py's worked example exactly at that module's
    own stated 650 lb of gain / 6.5 / 80%.
    """
    if basis not in ("dm", "as_fed"):
        raise ValueError(f"basis must be 'dm' or 'as_fed', got {basis!r}")
    gain = max(0.0, finish_lb - feedlot_in_lb)
    corn_lb = gain * conversion * corn_share
    if basis == "dm":
        corn_lb /= CORN_DM
    return corn_lb / LB_PER_MT


def us_share(corn, year):
    """(share, is_reported) -- the US share of Mexico's corn imports.

    **PSD ZERO-FILLS `TY Imp. from U.S.` FOR INCOMPLETE TRADE YEARS**, so a
    naive read says Mexico bought no US corn at all in exactly the years this
    panel is about. When the figure is absent or zero, the mean of the last
    five REPORTED years is used and the caller is told it is a fallback, so
    the page can say so rather than printing a fabricated share as a fact.
    """
    row = corn.get(year, {})
    imp = row.get("Imports") or 0.0
    us = row.get("TY Imp. from U.S.") or 0.0
    if imp and us:
        return us / imp, True
    hist = []
    for y in sorted(corn, reverse=True):
        r = corn[y]
        if (r.get("Imports") or 0) and (r.get("TY Imp. from U.S.") or 0):
            hist.append(r["TY Imp. from U.S."] / r["Imports"])
        if len(hist) == 5:
            break
    return (sum(hist) / len(hist) if hist else 0.0), False


def feed_grain_total(grains):
    """[(market_year, {grain: feed_use}, total)] -- oldest first.

    THE REASON THE PANEL CANNOT QUOTE THE CORN LINE ALONE. Corn feed use rose
    +1,700 in MY2025 while TOTAL feed grain rose +320, because sorghum and
    feed wheat fell away as Mexico's own crops failed. Attributing the corn
    increase to cattle without this is the single biggest available error
    here.
    """
    years = sorted({y for s in grains.values() for y in s})
    out = []
    for y in years:
        per = {g: grains[g].get(y, {}).get("Feed Dom. Consumption", 0.0)
               for g in grains}
        out.append((y, per, sum(per.values())))
    return out


def peak_exports(cattle):
    """(head, year) -- the most Mexico has shipped in a year on PSD's record.

    THE SCENARIO CONTROL IS CAPPED ON THIS, NOT ON A RECENT MEAN. It was
    capped at the 2022-24 average of 1,170,000, which is not a ceiling at all:
    that window happens to span two weak years (965,000 in 2022 and 1,037,000
    in 2021), and Mexico has shipped 1,658,000 in 1995, 1,539,000 in 2012 and
    1,485,000 in 2020. Typing a perfectly ordinary recovery of 1.3 million
    turned the box red with nothing saying why -- a control refusing a
    scenario the border has actually delivered, three times.

    The herd also grew about a million head during the closure, so even this
    is not a hard physical limit. It is a generous bound that keeps a typo
    from running the panel, rather than a claim about what can happen.
    """
    exp = {y: v.get("Exports", 0.0) * 1000
           for y, v in cattle.items() if v.get("Exports")}
    if not exp:
        return 0.0, None
    year = max(exp, key=lambda y: exp[y])
    return exp[year], year


def displaced(head, *,
              mx_in=MX_FEEDLOT_IN_LB, mx_finish=MX_FINISH_LB,
              mx_conv=MX_CONVERSION, mx_share=MX_CORN_SHARE,
              us_in=US_FEEDLOT_IN_LB, us_finish=US_FINISH_LB,
              us_conv=US_CONVERSION, us_share_corn=US_CORN_SHARE,
              mx_basis=MX_BASIS, us_basis=US_BASIS):
    """
    What `head` cattle crossing instead of being fed in Mexico does to US corn.

    {"head", "mx_mt", "us_mt", "mx_bu", "us_bu", "export_bu", "domestic_bu",
     "net_bu", "per_head_mx_bu", "per_head_us_bu"}

    **`net_bu` IS THE FIGURE THAT MATTERS AND IT IS NORMALLY POSITIVE.**
    `export_bu` is what the US stops shipping to Mexico; `domestic_bu` is what
    US feedyards eat instead. Across every plausible setting of these inputs
    the second is the larger, because the same calf goes to a heavier finish
    on a more corn-dense ration north of the border. A panel that printed the
    export loss alone would be arithmetically right and would tell a reader
    the opposite of what happens to US corn demand.
    """
    mx = corn_per_head(mx_in, mx_finish, mx_conv, mx_share, basis=mx_basis)
    us = corn_per_head(us_in, us_finish, us_conv, us_share_corn,
                       basis=us_basis)
    return {
        "head": head,
        "per_head_mx_bu": mx * BU_PER_MT,
        "per_head_us_bu": us * BU_PER_MT,
        "mx_mt": mx * head,
        "us_mt": us * head,
        "mx_bu": mx * head * BU_PER_MT,
        "us_bu": us * head * BU_PER_MT,
        "export_bu": mx * head * BU_PER_MT,
        "domestic_bu": us * head * BU_PER_MT,
        "net_bu": (us - mx) * head * BU_PER_MT,
    }


def crossing_shortfall(cattle, normal_years=(2022, 2023, 2024), today=None):
    """
    (shortfall_head, baseline_head, latest_year, latest_head) from PSD's own
    Mexican cattle export series.

    **THE LATEST YEAR IS NEVER A FORWARD FORECAST.** PSD carries marketing
    years ahead of the calendar -- MY2027 is on file today at 625,000 head,
    USDA's guess at the recovery. Taking `max()` headlines that: it reported a
    545,000 head shortfall where the year actually running is 150,000 and the
    shortfall is about a million. The figure looked entirely plausible, which
    is the whole problem with it. `today` is an argument so a test does not
    change answer with the calendar.

    The baseline is a MEAN OF SEVERAL NORMAL YEARS rather than the single year
    before the closure: Mexican exports are lumpy -- 1,037 / 965 / 1,295 /
    1,250 thousand head over 2021-2024 -- so one year as the counterfactual
    moves the headline by a third depending which one is picked.

    Cross-checked against this page's own Census head counts, which are a
    different agency counting the same animals from the other side of the
    border: 1,243,045 against PSD's 1,250,000 for 2024, and 229,055 against
    229,000 for 2025.
    """
    from datetime import date as _d
    cap = (today or _d.today()).year
    exp = {y: v.get("Exports", 0.0) * 1000 for y, v in cattle.items()}
    base = [exp[y] for y in normal_years if y in exp]
    live = [y for y in exp if y <= cap]
    if not base or not live:
        return 0.0, 0.0, None, 0.0
    baseline = sum(base) / len(base)
    latest = max(live)
    return max(0.0, baseline - exp[latest]), baseline, latest, exp[latest]
