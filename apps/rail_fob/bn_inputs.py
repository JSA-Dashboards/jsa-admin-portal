"""
BN freight inputs the desk feeds by hand (Kolten, 2026-10-28): the secondary-market
BN 110-car shuttle quotes (bid / offer by shuttle period) and the fuel surcharge by
month. Together with the face rates and miles in bn_freight_seed.json they build the
freight: rate + miles x FSC + the month's BN Cars premium (Hereford takes half).

Where they live: saved as one JSON payload per save in JSA.RAIL_FOB.BN_FREIGHT_INPUTS
(bn_inputs_setup.sql creates it) — append-only, so a save is a single INSERT (no
DELETE-then-INSERT race, see reference_snowflake_replace_race) and every change stays
as history; the latest row wins. Until that table exists (or off Snowflake) the tab
falls back to the defaults in the seed, and an edit holds for the session only.

Shuttle quote -> month: the BID is the premium (Kolten's call). A month's own full-month
quote wins; otherwise the midpoint of its F/H and L/H bids when both are posted (the lone
half if only one is); otherwise the NARROWEST package covering it (Jan-Feb-Mar, April-May,
April-July, ...). A quote with no bid ('-') doesn't count, so the month falls through to
a package or to 0. Same hierarchy as the basis tracker's forward_month rule.

No Streamlit in here — the pure parts are covered by tests/test_bn_inputs.py.
"""
import copy
import json
import re

import freight_data as FD
import rail_data as RD

TABLE = "JSA.RAIL_FOB.BN_FREIGHT_INPUTS"

# BN's quote horizon runs by crop year, so the month grid is Oct..Sep.
MONTH_ORDER = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]

_MONTH_NAME = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b")
_RANGE_JOINER = re.compile(r"\s*(?:-|–|—|to|thru|through)\s*")
_FIRST_HALF = re.compile(r"\b(?:f/?h|first half)\b")
_LAST_HALF = re.compile(r"\b(?:l/?h|last half)\b")
_YEAR = re.compile(r"\b(?:19|20)\d\d\b")
_PACKAGES = {
    "jfm": [1, 2, 3], "fma": [2, 3, 4], "mam": [3, 4, 5], "amj": [4, 5, 6], "mjj": [5, 6, 7],
    "jja": [6, 7, 8], "jas": [7, 8, 9], "aso": [8, 9, 10], "son": [9, 10, 11], "ond": [10, 11, 12],
    "ndj": [11, 12, 1], "djf": [12, 1, 2], "amjj": [4, 5, 6, 7], "am": [4, 5], "jj": [6, 7], "as": [8, 9],
}


def month_key(m):
    return FD._BN_MONTH3_REV[m]


def period_months(label):
    """A shuttle period label -> (months covered, kind). kind is 'full' (one whole
    month), 'fh' / 'lh' (one half-month), 'package' (several months) or 'none'
    (Return Trip and anything that names no month)."""
    s = _YEAR.sub(" ", (label or "").lower())
    half = "fh" if _FIRST_HALF.search(s) else "lh" if _LAST_HALF.search(s) else None
    s = _LAST_HALF.sub(" ", _FIRST_HALF.sub(" ", s))
    found = list(_MONTH_NAME.finditer(s))
    if found:
        nums = [FD._BN_MONTH3[m.group(1)[:3]] for m in found]
        if len(found) == 2 and _RANGE_JOINER.fullmatch(s[found[0].end():found[1].start()]):
            months, m = [nums[0]], nums[0]
            while m != nums[1]:
                m = m % 12 + 1
                months.append(m)
        else:
            months = list(dict.fromkeys(nums))
    else:
        pkg = next((t for t in re.findall(r"[a-z]+", s) if t in _PACKAGES), None)
        months = list(_PACKAGES[pkg]) if pkg else []
    if not months:
        return [], "none"
    if len(months) > 1:
        return months, "package"
    return months, half or "full"


def cars_by_month(quotes):
    """{month number: (BN Cars $/car, what it came from)} for every month a bid covers."""
    parsed = []
    for q in quotes:
        if q.get("bid") is None:
            continue
        months, kind = period_months(q.get("period"))
        if months:
            parsed.append((q["period"], float(q["bid"]), months, kind))
    out = {}
    for m in range(1, 13):
        cover = [p for p in parsed if m in p[2]]
        full = [p for p in cover if p[3] == "full"]
        fh = [p for p in cover if p[3] == "fh"]
        lh = [p for p in cover if p[3] == "lh"]
        pkg = [p for p in cover if p[3] == "package"]
        if full:
            out[m] = (full[0][1], full[0][0])
        elif fh and lh:
            out[m] = ((fh[0][1] + lh[0][1]) / 2, f"{fh[0][0]} + {lh[0][0]}")
        elif fh or lh:
            half = (fh or lh)[0]
            out[m] = (half[1], half[0])
        elif pkg:
            best = min(pkg, key=lambda p: len(p[2]))
            out[m] = (best[1], best[0])
    return out


def default_payload():
    """The inputs as of the seed (the 2026-10-28 shuttle sheet and the FSC in Kolten's workbook)."""
    return copy.deepcopy(FD.load_bn_seed()["defaults"])


def bid_overrides(payload):
    """{destination: {headline period: {bid, offer}}} typed over the board's delivered bids in FOB by Origin
    (Kolten, 2026-10-28: Hereford Oct +85, PNW Dec +100). A payload saved before the feature existed takes the
    seed's; once saved it keeps whatever is typed, even none."""
    src = payload["bid_overrides"] if "bid_overrides" in payload else default_payload().get("bid_overrides", {})
    return {dest: {p: v for p, v in per.items() if v and v.get("bid") is not None} for dest, per in (src or {}).items()}


def month_rows(payload, auto=None):
    """Per month in crop-year order: key, fsc, the BN Cars $/car the freight will use and
    where each came from — what the tab shows as a preview and what effective_window()
    keeps (the months with an FSC).
    FSC: in formula mode (payload "fsc_mode", the default) a month's FSC is what bn_fsc computes from diesel
    (`auto`, bn_fsc.auto_table), unless Kolten typed an override for it. Without `auto` (no EIA key, or EIA
    unreachable) — or in "typed" mode — it's the typed FSC, and a month with none takes the last entered
    month's, held flat (payload "hold_fsc", on unless switched off)."""
    derived = cars_by_month(payload.get("quotes", []))
    by_key = {m["key"]: m for m in payload.get("months", [])}
    formula = payload.get("fsc_mode", "formula") == "formula" and bool(auto)
    hold = payload.get("hold_fsc", True)
    out, last = [], None
    for n in MONTH_ORDER:
        key = month_key(n)
        mo = by_key.get(key, {})
        override = mo.get("cars_override")
        if override is not None:
            cars, src = float(override), "typed in"
        elif n in derived:
            cars, src = derived[n]
        else:
            cars, src = 0.0, "no bid quoted"
        if formula:
            typed = mo.get("fsc_override")
            if typed is not None:
                fsc, fsc_src = typed, "override"
            elif key in auto:
                fsc, fsc_src = auto[key]["fsc"], "formula: " + auto[key]["basis"]
            else:
                fsc, fsc_src = None, ""
        else:
            fsc = mo.get("fsc")
            if fsc is not None:
                last, fsc_src = (key.title(), fsc), "entered"
            elif hold and last is not None:
                fsc, fsc_src = last[1], f"held flat from {last[0]}"
            else:
                fsc_src = ""
        out.append({"key": key, "label": key.title(), "fsc": fsc, "fsc_source": fsc_src,
                    "fsc_kind": auto[key]["kind"] if formula and key in auto and fsc_src.startswith("formula") else "",
                    "cars": cars, "cars_source": src})
    return out


def effective_window(payload, auto=None):
    """What freight_data.load_bn() takes: [{key, label, fsc_per_mile, cars}], only for
    months that have an FSC — a month with none yet has no freight (its bids show '—')
    until one is entered."""
    return [{"key": r["key"], "label": r["label"], "fsc_per_mile": float(r["fsc"]), "cars": r["cars"]}
            for r in month_rows(payload, auto) if r["fsc"] is not None]


def problems(payload):
    """Human-readable issues worth warning about before a save (never blocks it)."""
    out = []
    for q in payload.get("quotes", []):
        if q.get("period") and period_months(q["period"])[1] == "none" and "return" not in q["period"].lower():
            out.append(f"'{q['period']}' names no month, so it isn't used")
    for m in payload.get("months", []):
        for f in ("fsc", "fsc_override"):
            if m.get(f) is not None and not 0 <= m[f] <= 5:
                out.append(f"{m['key'].title()} FSC {m[f]} looks off ($/mile)")
    return out


def sf_available():
    return RD._use_snowflake()


def fetch_latest():
    """The latest saved row as {payload, saved_at, saved_by}, or None if nothing is saved
    yet or this isn't running against Snowflake. Raises if the table can't be read."""
    if not sf_available():
        return None
    rows = RD._sf_rows(f"SELECT saved_at, saved_by, payload FROM {TABLE} ORDER BY saved_at DESC LIMIT 1", ())
    if not rows:
        return None
    return {"payload": json.loads(rows[0]["payload"]), "saved_at": rows[0]["saved_at"],
            "saved_by": rows[0]["saved_by"]}


def save(payload, saved_by="rail-fob-portal"):
    """Append one row. SYSDATE() is UTC whatever the session timezone is
    (reference_snowflake_identity_and_session_tz)."""
    conn = RD._sf_connect()
    try:
        conn.cursor().execute(f"INSERT INTO {TABLE} (saved_at, saved_by, payload) SELECT SYSDATE(), %s, %s",
                              (saved_by, json.dumps(payload, separators=(",", ":"))))
    finally:
        if not RD._in_sis():
            conn.close()
