"""
Each railroad's mileage-based grain fuel surcharge, in dollars per car-mile (researched 2026-10-28).

All five key off the monthly average of EIA's weekly US on-highway diesel (the railroads call it HDF) with a
two-month lag — diesel for month M sets the surcharge for month M+2 — and differ in strike, step and rounding:

    BN   strike 3.25  1c per 5c   round up each started step   (fitted; BNSF's rule text isn't public — bn_fsc.py)
    UP   strike 2.30  1c per 5c   full steps only, plus a 5c base   (UP's own page, table checked)
    NS   strike 2.50  1c per 4c   round up, diesel truncated to the cent first   (NS's page; the rounding is inferred)
    CN   strike 2.30  0.575c per 2.5c   round up   (CN 7403 on CN's page; lag and rounding inferred)
    CSX  strike ~3.749  1c per 4c   round up   (INFERRED from the June 2026 surcharge and a third-party calculator;
                                                CSX's own page wasn't readable)

`published` are the surcharges each railroad's page (or the USDA AMS Grain Transportation Report) showed when this was
written — what tests/test_rail_fsc.py reproduces from the diesel prices. Whether a given railroad's grain shuttles move
under these public programs rather than a contract one was not verified for UP, NS or CSX.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import bn_fsc as BNF

LAG = 2

PROGRAMS = {
    "BN": {
        "name": "BNSF mileage-based fuel surcharge",
        "rule": "Item 3377-Series, $3.25 strike price, of BNSF Rules Book 6100-Series (cited in BNSF's grain price lists)",
        "strike": 3.25, "step": 0.05, "per_step": 0.01, "base": 0.0, "rounding": "up", "trunc_cents": False, "dec": 2,
        "confidence": "Fitted to the surcharges BN has published (Aug .36, Sep .35, Oct .45, Nov .61 — all exact); the "
                      "$3.25 strike is in BNSF's price lists, the rule text itself isn't public.",
        "links": [("BNSF grain price list (cites Item 3377-Series)",
                   "https://www.bnsf.com/ship-with-bnsf/agricultural-products/ag-price-documents/BNSF-4022-71005-M.pdf")],
        "published": {"2026-08": 0.36, "2026-09": 0.35, "2026-10": 0.45, "2026-11": 0.61},
        "published_from": "the surcharges BN has actually had",
    },
    "UP": {
        "name": "UP carload mileage-based standard HDF",
        "rule": "UP's customer fuel-surcharge page (the page states no tariff number; some sources call it UP 6004)",
        "strike": 2.30, "step": 0.05, "per_step": 0.01, "base": 0.05, "rounding": "down", "trunc_cents": False, "dec": 2,
        "confidence": "Documented on UP's own page and checked against its table. The page says it covers most UP regulated "
                      "public pricing; that grain shuttles use it wasn't verified.",
        "links": [("UP mileage-based fuel surcharge", "https://www.up.com/customers/surcharge/mileage/index.htm")],
        "published": {"2026-09": 0.58, "2026-10": 0.68, "2026-11": 0.84},
        "published_from": "UP's page",
    },
    "NS": {
        "name": "NS mileage-based fuel surcharge",
        "rule": "NS's $2.50 mileage-based program (NS also publishes WTI-crude percentage programs NS-8003 / NS-8004)",
        "strike": 2.50, "step": 0.04, "per_step": 0.01, "base": 0.0, "rounding": "up", "trunc_cents": True, "dec": 2,
        "confidence": "Values and program wording are on NS's page; the diesel-to-the-cent truncation and the rounding are "
                      "inferred (they reproduce every published value). The page states the $2.50 program for Industrial "
                      "Products — that grain moves under it wasn't verified.",
        "links": [("NS fuel surcharges", "https://norfolksouthern.com/en/ship-by-rail/shipping-tools/terms-conditions/fuel-surcharges")],
        "published": {"2026-09": 0.62, "2026-10": 0.74, "2026-11": 0.95},
        "published_from": "NS's page",
    },
    "CN": {
        "name": "CN 7403 mileage-based carload fuel surcharge",
        "rule": "Tariff CN 7403 — bulk commodities (coal, fertilizer, grain) 0.575c per mile per 2.5c of diesel over a $2.30 US base",
        "strike": 2.30, "step": 0.025, "per_step": 0.006496, "base": 0.0, "rounding": "up", "trunc_cents": False, "dec": 3,
        "confidence": "Strike, step and round-up are on CN's page and reproduce its values; but the $/mile CN BILLS on grain (USDA AgTransport's "
                      "fsc_per_mile, e.g. $0.825 in Oct) is 1.1298 x the page's 0.575c per step, exactly, so per_step is 0.6496c, "
                      "fitted to USDA's Jun-Oct 2026 values (all exact). The lag is inferred.",
        "links": [("CN fuel surcharge", "https://www.cn.ca/en/customer-centre/prices-tariffs-transit-times/fuel-surcharge/")],
        "published": {"2026-09": 0.695, "2026-10": 0.825, "2026-11": 1.039},
        "published_from": "USDA AgTransport (what CN billed, Sep / Oct); Nov = CN's page 0.92 x 1.1298 (160 steps)",
    },
    "CSX": {
        "name": "CSX public-tariff mileage surcharge (publication 8662)",
        "rule": "Publication 8662, reinstated June 5, 2026 per the USDA AMS Grain Transportation Report",
        "strike": 3.749, "step": 0.04, "per_step": 0.01, "base": 0.0, "rounding": "up", "trunc_cents": False, "dec": 2,
        "confidence": "INFERRED: the June 2026 surcharge ($0.44 from April's $5.501 diesel) and a third-party calculator "
                      "(strike about $3.749, 1c per 4c). CSX's own page wasn't readable, so check it before relying on this.",
        "links": [("USDA AMS Grain Transportation Report, 6/4/26", "https://ams-prod.azureedge.us/sites/default/files/media/GTR06042026.pdf"),
                  ("CSX fuel surcharge page", "https://www.csx.com/index.cfm/customers/resources/price-lists-and-fuel-surcharge/fuel-surcharge/")],
        "published": {"2026-06": 0.44},
        "published_from": "USDA AMS GTR",
    },
}


def fsc(rr, price):
    """$/car-mile for a monthly-average diesel price under that railroad's program."""
    p = PROGRAMS[rr]
    if p["trunc_cents"]:
        price = math.floor(price * 100 + 1e-9) / 100
    if price < p["strike"]:
        return 0.0
    q = round((price - p["strike"]) / p["step"], 6)
    n = math.ceil(q) if p["rounding"] == "up" else math.floor(q)
    val = Decimal(str(p["base"])) + n * Decimal(str(p["per_step"]))
    return float(val.quantize(Decimal(1).scaleb(-p["dec"]), rounding=ROUND_HALF_UP))


def equation(rr):
    """The program in one sentence."""
    p = PROGRAMS[rr]
    cents = lambda v: f"{v * 100:g}"
    base = f"{cents(p['base'])}¢ plus " if p["base"] else ""
    steps = "each full" if p["rounding"] == "down" else "each started"
    trunc = " (the diesel price is cut to the cent first)" if p["trunc_cents"] else ""
    strike = f"{p['strike']:.3f}"
    strike = strike[:-1] if strike.endswith("0") else strike
    return (f"{base}{cents(p['per_step'])}¢ per car-mile for {steps} {cents(p['step'])}¢ that the monthly average of EIA's "
            f"weekly US on-highway diesel, two months earlier, is above \\${strike}{trunc}.")


def table(rr, weekly, today):
    """The BN-style month grid ({key: {fsc, kind, basis, year, month}}) under this railroad's program."""
    return BNF.auto_table(weekly, today, lambda price: fsc(rr, price))


def window(rr, weekly, today):
    """{month key: {fsc, kind}} for the Oct..Sep grid: the value the railroad has PUBLISHED where it has one, else the
    program's formula on EIA diesel (months past the diesel data hold the latest weekly price flat), else — with no diesel
    data — the last published value held flat. kind: 'published' | 'formula' | 'held'. {} when there is nothing to go on."""
    pub = PROGRAMS[rr]["published"]
    tbl = table(rr, weekly, today) if weekly else {}
    out, last = {}, None
    for key, y, m in BNF.grid_months(today):
        known = pub.get(f"{y}-{m:02d}")
        if known is not None:
            out[key] = {"fsc": known, "kind": "published"}
        elif key in tbl:
            out[key] = {"fsc": tbl[key]["fsc"], "kind": "formula"}
        elif last is not None:
            out[key] = {"fsc": last, "kind": "held"}
        if key in out:
            last = out[key]["fsc"]
    return out
