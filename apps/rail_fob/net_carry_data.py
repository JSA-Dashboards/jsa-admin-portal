"""net_carry_data.py — the data side of the portal's 💵 Net Carry tab.

The Net Carry maths is vendored UNCHANGED from the basis tracker (net_carry.py, net_carry_chart.py,
net_carry_compare.py, carry_rate.py, delivery_period.py — see CLAUDE.md for how to re-sync them).
This module only feeds it, from what the portal already reads:

  * the corridor catalog   — which corridors / commodities / posting dates can show a carry ladder,
                             from the rail_fob rows `rail_data.get_all()` returns (sources 'manual' + 'palmetto')
  * items                  — one corridor's posted bids on one date, as net_carry items
                             {'delivery': period label, 'futures': CME symbol or None, 'basis': bid in cents}
  * the futures curve      — {symbol: cents} from the basis tracker's FUTURES_PRICES (Snowflake
                             JSA.BASIS_TRACKER): the stored curve of the latest day on or before the as-of date
  * comparison entries     — the other corridors' latest postings, for the side-by-side table

Everything here is pure except `futures_curve`, whose single query goes through `rail_data._rows` (or any
function you pass in — the tests hand it a throwaway SQLite). Nothing imports Streamlit.

Bids are used exactly as archived (feedback_rail_entry: record as posted, never roll). The only thing this
module changes is the SYMBOL's spelling — see `full_symbol`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import net_carry as _nc
import net_carry_compare as _cmp
from rail_corridors import CORRIDOR_ORDER, RAIL_DISPLAY

# A corridor needs this many priced periods on a posting before there is a carry ladder to draw.
MIN_PERIODS = 2
# A compared corridor's posting may be at most this old (days before the as-of date) to count as current.
MAX_AGE_DAYS = 10
# The default number of other corridors the comparison starts with.
DEFAULT_PEERS = 3

_NOT_BID = re.compile(r"freight|shuttle", re.I)


def is_bid_market(market: str) -> bool:
    """False for the freight-rate lines — 'BN Freight', 'UP Freight', 'CPKC Freight', 'CSX Freight' and the
    '* Shuttle' boards are $/car freight, not FOB bids, so they have no basis to carry."""
    return not _NOT_BID.search(market or "")


# ── labels and symbols ─────────────────────────────────────────────────────────────────────────
_FULL_MONTHS = {"JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
                "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"}


def tidy_label(period) -> str:
    """The delivery label as shown. Palmetto's archive stores some full month names in capitals
    ('OCTOBER') and later ones in title case ('October'); fold the capitals so one month reads one way.
    Codes that are meant to be capitals ('JFM', 'AMJJ', 'OCT/NOV') are untouched."""
    s = " ".join(str(period or "").split())
    return s.capitalize() if s in _FULL_MONTHS else s


# Palmetto's scrape and the manual rundowns before Sept 2026 store a futures contract as a TWO-letter code —
# commodity letter + month code ('CZ' = Dec corn, 'SX' = Nov soybeans) — with no year. The tracker's
# delivery_period/net_carry need the full CME symbol ('ZCZ26') to place a delivery in time and to price
# the contract, so a short code would drop out of the ladder entirely.
_ROOT_FOR_LETTER = {"C": "ZC", "S": "ZS", "W": "ZW"}
_MONTH_OF_CODE = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
                  "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}


def full_symbol(code, as_of: date) -> str | None:
    """A futures code as a full CME symbol, the year taken from the posting date: the first contract of that
    month ON OR AFTER the posting month ('SX' posted 2026-10-02 -> 'ZSX26', 'SF' -> 'ZSF27'). Full symbols,
    'R' (a package spanning months) and anything unrecognised pass through unchanged; blank -> None.
    This only completes the SPELLING of the contract the bid was posted against — the bid is never touched."""
    c = (str(code).strip().upper() if code is not None else "")
    if not c:
        return None
    if _nc.parse_symbol(c):
        return c                                         # already an outright (ZCZ26)
    if len(c) == 2 and c[0] in _ROOT_FOR_LETTER and c[1] in _MONTH_OF_CODE:
        month = _MONTH_OF_CODE[c[1]]
        year = as_of.year if month >= as_of.month else as_of.year + 1
        return f"{_ROOT_FOR_LETTER[c[0]]}{c[1]}{year % 100:02d}"
    return c                                             # 'R', note rows, odd codes


# The whole settlement history of a commodity (Return to Carry reads ~20 crop years at once): ZC / ZS, one row per contract per day.
_FUT_HISTORY_SQL = "SELECT date, symbol, price_cents FROM futures_prices WHERE symbol LIKE %s AND date >= %s"


def futures_history(root: str, rows_fn=None, since: str = "2004-01-01") -> dict:
    """{date: {symbol: cents}} for every contract whose symbol starts with `root` ('ZC' corn, 'ZS' soybeans): the stored settlements
    (FUTURES_PRICES, from 2006-11) over the analyst's sheet weeks that come before them (return_to_carry_data.load_sheet_futures).
    One query; `rows_fn(sql, params) -> [dict]` defaults to the portal's rail_data._rows (the tests hand it a throwaway SQLite)."""
    import return_to_carry_data as rd
    if rows_fn is None:
        import rail_data
        rows_fn = rail_data._rows
    return rd.merge_futures(rd.load_sheet_futures(root=root), rd.futures_map(rows_fn(_FUT_HISTORY_SQL, (root + "%", since))))


# ── one corridor, one posting ─────────────────────────────────────────────────────────────────
def _iso(d) -> str:
    return str(d)[:10]


def _commodity(row) -> str:
    return row.get("commodity") or "Corn"


def corridor_items(rows: list[dict], source: str | None, market: str, commodity: str, date_str: str) -> list[dict]:
    """A corridor's posted bids on one date as net_carry items. `rows` = rail_fob rows tagged with `source`
    (see `tag_rows`); `source=None` accepts any. Only rows WITH a bid are items (an offer-only row is not a bid
    to carry); the delivery label is the period as archived; the futures code is completed to a full symbol."""
    day = _iso(date_str)
    asof = date.fromisoformat(day)
    out = []
    for r in rows:
        if r["market"] != market or _commodity(r) != commodity or _iso(r["date"]) != day:
            continue
        if source is not None and r.get("source") != source:
            continue
        if r.get("bid") is None:
            continue
        out.append({"delivery": tidy_label(r["period"]), "futures": full_symbol(r.get("futures"), asof),
                    "basis": r["bid"]})
    return out


def tag_rows(rows_by_source: dict[str, list[dict]]) -> list[dict]:
    """{'manual': rows, 'palmetto': rows} -> one list with each row's `source` filled in."""
    return [dict(r, source=src) for src, rows in rows_by_source.items() for r in rows]


# ── the corridor catalog ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Corridor:
    key: str            # 'manual|CSX Columbus|Corn' — unique; used in widget keys
    source: str         # 'manual' | 'palmetto'
    market: str         # as archived
    commodity: str      # 'Corn' | 'Soybeans'
    label: str          # what the pick-list / a comparison column header shows
    rail: str           # carrier ('CSX', 'NS', 'UP', 'BNSF', 'CN') or ''
    dates: tuple        # ISO posting dates with a carry ladder (>= MIN_PERIODS priced periods), newest first
    posted: tuple       # every ISO date with any bid, newest first

    @property
    def spot_only(self) -> int:
        """Postings with fewer than MIN_PERIODS priced periods (the weekly spot history): no curve to draw."""
        return len(self.posted) - len(self.dates)


def corridor_label(source: str, market: str) -> str:
    """The portal's own display name (rail_corridors.RAIL_DISPLAY), with the source named for Palmetto's."""
    name = RAIL_DISPLAY.get(market, market)
    return f"{name} (Palmetto)" if source == "palmetto" else name


def build_catalog(rows: list[dict]) -> list[Corridor]:
    """Every (source, corridor, commodity) that has posted a bid, in the portal's corridor order — the
    registry's order first (CSX, NS, UP, BN, CN), then anything else (Palmetto's boards) alphabetically.
    The freight lines are left out (is_bid_market). A corridor posting two commodities gets the commodity
    added to its label so the two stay distinguishable."""
    groups: dict[tuple, dict[str, set]] = {}
    rails: dict[tuple, str] = {}
    for r in rows:
        if r.get("bid") is None or not is_bid_market(r["market"]):
            continue
        k = (r.get("source") or "manual", r["market"], _commodity(r))
        groups.setdefault(k, {}).setdefault(_iso(r["date"]), set()).add(r["period"])
        if not rails.get(k):
            rails[k] = r.get("rail") or ""
    n_commodities: dict[tuple, int] = {}
    for src, mkt, _com in groups:
        n_commodities[(src, mkt)] = n_commodities.get((src, mkt), 0) + 1

    out = []
    for (src, mkt, com), by_date in groups.items():
        posted = tuple(sorted(by_date, reverse=True))
        ladder = tuple(d for d in posted if len(by_date[d]) >= MIN_PERIODS)
        label = corridor_label(src, mkt)
        if n_commodities[(src, mkt)] > 1:
            label += f" · {com}"
        out.append(Corridor(f"{src}|{mkt}|{com}", src, mkt, com, label, rails[(src, mkt, com)], ladder, posted))
    out.sort(key=lambda c: (CORRIDOR_ORDER.get(c.market, 999), c.market.lower(), c.source, c.commodity))
    return out


# ── the comparison ────────────────────────────────────────────────────────────────────────────
def latest_posting(c: Corridor, asof: date, max_age_days: int = MAX_AGE_DAYS) -> date | None:
    """The corridor's newest posting on or before `asof` and no more than `max_age_days` older than it, else None
    (the same rule as net_carry_compare.pick_latest, read straight off the catalog's date list)."""
    iso = asof.isoformat()
    for d in c.posted:                                   # newest first
        if d <= iso:
            day = date.fromisoformat(d)
            return day if (asof - day).days <= max_age_days else None
    return None


def compare_options(catalog: list[Corridor], main: Corridor, asof: date,
                    max_age_days: int = MAX_AGE_DAYS) -> list[Corridor]:
    """The corridors that can be compared with `main` on `asof`: the same commodity (every column must share one
    futures root and reference), not `main` itself, with a posting on or before the as-of date and no older than
    `max_age_days` — a corridor that has gone quiet would only show a stale column."""
    return [c for c in catalog
            if c.key != main.key and c.commodity == main.commodity and latest_posting(c, asof, max_age_days)]


def default_peers(main: Corridor, options: list[Corridor], n: int = DEFAULT_PEERS) -> list[Corridor]:
    """Who the comparison starts with: the same railroad's other corridors first (net_carry_compare.rail_peers —
    'CSX Columbus' -> 'CSX Evansville'), padded alphabetically from the rest. Palmetto's boards are the same
    corridors posted a second way, so only the manual rundown's corridors are defaults (they stay pickable)."""
    pool = [c for c in options if c.source == "manual"]
    by_market = {c.market: c for c in pool}
    return [by_market[m] for m in _cmp.rail_peers(main.market, list(by_market), n)]


def comparison_entries(rows: list[dict], main: Corridor, main_items: list[dict], asof: date,
                       picked: list[Corridor], max_age_days: int = MAX_AGE_DAYS) -> list[_cmp.Entry]:
    """Columns for net_carry_compare.build_comparison: the main corridor first (on its own posting, `asof`), then
    each picked corridor on its latest posting on or before `asof` — within `max_age_days`, else a 'no recent
    quote' column. The comparison re-bases every column to one reference, futures day and interest clock."""
    entries = [_cmp.Entry(main.key, main.label, "corridor", main_items, asof, True)]
    for c in picked:
        d = latest_posting(c, asof, max_age_days)
        items = corridor_items(rows, c.source, c.market, c.commodity, d.isoformat()) if d else []
        entries.append(_cmp.Entry(c.key, c.label, "corridor", items, d))
    return entries


# ── the futures curve ─────────────────────────────────────────────────────────────────────────
# FUTURES_PRICES (JSA.BASIS_TRACKER; date TEXT 'YYYY-MM-DD', symbol, price_cents) — one row per contract per
# day, written by the basis tracker's daily capture (since 2026-06-22) and backfilled from the Cost of Carry
# archives (ZC/ZS from 2006-11, ZW/KE from 2021-10). The same SQL runs on Snowflake and on Postgres.
_CURVE_SQL = ("SELECT symbol, price_cents, date FROM futures_prices "
              "WHERE date = (SELECT MAX(date) FROM futures_prices WHERE date <= %s)")


def futures_curve(as_of: date, rows_fn=None) -> tuple[dict, date | None]:
    """({symbol: cents}, the day the curve is from): the stored curve of the latest day ON OR BEFORE `as_of`
    (a weekend or holiday posting reads the previous trading day; a date before the archive starts gets
    ({}, None)). `rows_fn(sql, params) -> [dict]` defaults to the portal's own rail_data._rows — the same
    connection and key-pair auth as the rail bids."""
    if rows_fn is None:
        import rail_data
        rows_fn = rail_data._rows
    curve: dict[str, float] = {}
    days: set[str] = set()
    for r in rows_fn(_CURVE_SQL, (as_of.isoformat(),)):
        sym, px = r.get("symbol"), r.get("price_cents")
        if not sym or px is None:
            continue
        curve[str(sym).strip()] = float(px)
        days.add(_iso(r.get("date")))
    return curve, (date.fromisoformat(max(days)) if days else None)
