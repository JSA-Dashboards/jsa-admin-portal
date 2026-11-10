"""
quotes.py -- the nearby-futures price strip at the top of the CLIENT portal.

Corn, Chi Platts ethanol, SRW, HRW, soybeans, meal, soy oil and the soy crush, each on its NEARBY
contract with the last settlement and the change from the prior settlement.

DELAYED QUOTES (Kolten 2026-11-10: "make the quote tiles the 10 min delay after all"). The futures tiles show the LAST TRADE from Massive's
/snapshot, the change being that price less the PRIOR SESSION's settlement, and the footnote says when the trade was. The snapshot is only used when Massive
itself labels it DELAYED (CME's delay is 10 minutes): a feed that ever turned real-time would be ignored and the tile would fall back to the settlement
below, because showing real-time CME prices to clients is a licence matter, not a display one. The ethanol proxy and the Feeder Cattle Index have no
intraday price and stay end-of-day; the soy crush is rebuilt from the three delayed prices. The settlement figures below remain the fallback and the
prior-settle reference. The prior settlement comes from OUR settlement series, not from the snapshot's own `previous_settlement`:
after the day's settlement posts, Massive rolls that field to the settlement just posted (Dec corn on 2026-11-10 read 449.0, the very
settle, so the change came out -1.0 for a day that settled +9.75), which is wrong for a day-over-day change. The trade date of a last trade is
its calendar date before 5 PM CT and the next business day from 5 PM (CME's trade-date roll), and the reference is the latest settlement
BEFORE that trade date.

SETTLEMENTS, NOT LIVE QUOTES (the fallback, and the base the delayed prices are laid over). The grains come from the daily settlement bank
(JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS, filled each weekday at 4:30pm CT), so the strip reads the
previous session until that load runs; Chi Platts is the CME Chicago Ethanol (Platts) futures settle
from JSA.BASIS_TRACKER.ETHANOL_FUTURES, a futures proxy and not the Platts assessment.

NEARBY ROLLS AFTER FIRST NOTICE DAY, the way the Cost of Carry and COT dashboards do: a contract is
the nearby until the calendar date passes its first notice day (the last business day of the month
before delivery). Both ends of a change are the SAME contract, so a roll never shows up as a move.
Ethanol is cash-settled, so its nearby is the current-month contract.

SOY CRUSH is the board crush on the soybean nearby's delivery month, matched across the three
contracts so the spread never mixes months:  0.022 x meal ($/ton) + 0.11 x oil (cents/lb) -
soybeans (cents/bu / 100), in $/bu.

LIVESTOCK STRIP. The Livestock Apps tab swaps the strip for live cattle, feeder cattle, the CME Feeder Cattle
Index, lean hogs and corn (`build_livestock_quotes`). The three livestock futures are cash-settled, so the nearby
is the nearest contract that has not expired (no first notice day) and settles come from Massive, the way the COT
dashboard reads them; they are not in the settlement bank. The index is CME's own published cash index
(JSA.CME_FEEDER_CATTLE.CME_FTP_DAILY), which CME posts 1-3 business days behind, so its tile carries its own date
and it is never filled in with JSA's reconstruction of the days CME has not published.

The arithmetic (`build_quotes`) takes plain frames so it can be tested without Snowflake; `load()` is the
thin cached reader. The first-notice-day logic is the COT dashboard's own `futures_move.py`, loaded from
the mirrored copy under apps/cftc_cot so there is one implementation of it.
"""
from __future__ import annotations

import importlib.util
import logging
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

HERE = Path(__file__).parent
log = logging.getLogger("quotes")
CT = ZoneInfo("America/Chicago")
MONTHS = dict(zip("FGHJKMNQUVXZ", ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]))

# label, product code, unit shown, decimals
GRAIN_QUOTES = [
    ("Corn", "ZC", "¢/bu", 2),
    ("SRW wheat", "ZW", "¢/bu", 2),
    ("HRW wheat", "KE", "¢/bu", 2),
    ("Soybeans", "ZS", "¢/bu", 2),
    ("Soybean meal", "ZM", "$/ton", 2),
    ("Soybean oil", "ZL", "¢/lb", 2),
]
STALE_ETHANOL_DAYS = 5
STALE_INDEX_DAYS = 10
LIVESTOCK_QUOTES = [
    ("Live cattle", "LE", "¢/lb", 3),
    ("Feeder cattle", "GF", "¢/lb", 3),
    ("Lean hogs", "HE", "¢/lb", 3),
]


def _cot_module(name: str):
    """A module from the mirrored COT dashboard, under a private name so it can't clash with anything."""
    path = HERE / "apps" / "cftc_cot" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_jsa_quotes_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _label(year: int, month: str) -> str:
    return f"{MONTHS[month]} {str(year)[2:]}"


def _series(settles: pd.DataFrame, code: str, year: int, month: str) -> pd.Series:
    d = settles[(settles.product_code == code) & (settles.year.astype(int) == year) & (settles.month == month)]
    return d.set_index("date").settle.astype(float).sort_index()


def _hist(series: pd.Series, n: int = 8) -> dict:
    """The last `n` settlements of a series as {iso date: value}: what a delayed price is measured against."""
    s = series.dropna().tail(n)
    return {pd.Timestamp(d).date().isoformat(): float(v) for d, v in s.items()}


def trade_date(ts: datetime) -> date:
    """CME trade date of a trade at `ts` (Central): the calendar date before 5 PM, the next business day from 5 PM on."""
    d = ts.date() + timedelta(days=1) if ts.hour >= 17 else ts.date()
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def prior_settle(hist: dict | None, ts: datetime):
    """Latest settlement strictly before the trade date of `ts`; None when there is none close enough (a week-end and a
    holiday make 4 days) to be the real prior settlement."""
    td = trade_date(ts)
    before = [(date.fromisoformat(k), v) for k, v in (hist or {}).items() if date.fromisoformat(k) < td]
    if not before:
        return None
    d, v = max(before)
    return v if (td - d).days <= 4 else None


def _move(series: pd.Series):
    """(last, change from the prior settle, date of last) or None."""
    s = series.dropna()
    if s.empty:
        return None
    last = float(s.iloc[-1])
    prev = float(s.iloc[-2]) if len(s) > 1 else None
    return last, (None if prev is None else last - prev), s.index[-1]


def build_quotes(settles: pd.DataFrame, ethanol: pd.DataFrame, today: date, fm) -> list[dict]:
    """The strip's tiles, in display order. `settles`: product_code, month, year, date, settle (date may be a
    Timestamp). `ethanol`: the latest capture's rows (contract_ym 'YYYY-MM', settle, prev_settle, asof_date).
    `fm` is the futures_move module (first notice days). A market with no data is left out, never faked."""
    out: list[dict] = []
    settles = settles.copy()
    if len(settles):
        settles["date"] = pd.to_datetime(settles["date"]).dt.date
    fronts: dict[str, tuple[int, str]] = {}

    def grain(label, code, unit, dec):
        d = settles[settles.product_code == code]
        if d.empty:
            return None
        latest_day = d["date"].max()
        live = d[d["date"] == latest_day]
        front = fm.front_month(list(zip(live.year.astype(int), live.month)), today)
        if front is None:
            return None
        fronts[code] = front
        mv = _move(_series(settles, code, *front))
        if mv is None:
            return None
        last, chg, day = mv
        return {"label": label, "contract": _label(*front), "ticker": f"{code}{front[1]}{str(front[0])[-1]}",
                "hist": _hist(_series(settles, code, *front)), "value": last, "change": chg, "unit": unit,
                "decimals": dec, "as_of": day}

    by_label = {}
    for label, code, unit, dec in GRAIN_QUOTES:
        try:
            q = grain(label, code, unit, dec)
        except Exception as exc:  # noqa: BLE001 -- one market must not take the strip down
            log.warning("quote %s failed: %s", label, exc)
            continue
        if q:
            by_label[label] = q

    # Chi Platts: current-month CU contract of the latest capture (cash-settled: no notice day)
    eth = None
    try:
        if ethanol is not None and len(ethanol):
            e = ethanol.dropna(subset=["settle"]).copy()
            if len(e):
                asof = pd.to_datetime(e["asof_date"]).dt.date.max()
                if (today - asof).days <= STALE_ETHANOL_DAYS:
                    cur = asof.strftime("%Y-%m")
                    e = e[e.contract_ym.astype(str) >= cur].sort_values("contract_ym")
                    if len(e):
                        r = e.iloc[0]
                        y, m = int(str(r.contract_ym)[:4]), int(str(r.contract_ym)[5:7])
                        chg = None if pd.isna(r.get("prev_settle")) else float(r.settle) - float(r.prev_settle)
                        eth = {"label": "Chi Platts ethanol", "contract": f"{MONTHS['FGHJKMNQUVXZ'[m - 1]]} {str(y)[2:]}",
                               "value": float(r.settle), "change": chg, "unit": "$/gal", "decimals": 4, "as_of": asof}
    except Exception as exc:  # noqa: BLE001 -- the grains still draw without the ethanol proxy
        log.warning("Chi Platts quote failed: %s", exc)
        eth = None

    # Soy crush on the soybean nearby's month
    crush = None
    try:
        if "ZS" in fronts:
            y, m = fronts["ZS"]
            soy, meal, oil = (_series(settles, c, y, m) for c in ("ZS", "ZM", "ZL"))
            both = pd.concat([soy, meal, oil], axis=1, keys=["soy", "meal", "oil"]).dropna()
            if len(both) >= 1:
                board = 0.022 * both.meal + 0.11 * both.oil - both.soy / 100.0
                mv = _move(board)
                if mv:
                    last, chg, day = mv
                    crush = {"label": "Soy crush", "contract": f"{_label(y, m)} board", "value": last, "change": chg,
                             "crush_tickers": {c: f"{c}{m}{str(y)[-1]}" for c in ("ZS", "ZM", "ZL")},
                             "hist": _hist(board),
                             "unit": "$/bu", "decimals": 2, "as_of": day}
    except Exception as exc:  # noqa: BLE001
        log.warning("Soy crush quote failed: %s", exc)
        crush = None

    for label in ("Corn",):
        if label in by_label:
            out.append(by_label[label])
    if eth:
        out.append(eth)
    for label in ("SRW wheat", "HRW wheat", "Soybeans", "Soybean meal", "Soybean oil"):
        if label in by_label:
            out.append(by_label[label])
    if crush:
        out.append(crush)
    return out


def build_livestock_quotes(ls: pd.DataFrame, index: pd.DataFrame, corn: dict | None, today: date) -> list[dict]:
    """The Livestock tab's tiles, in display order: live cattle, feeder cattle, CME Feeder Cattle Index, lean
    hogs, corn. `ls`: product_code, month, year, date, settle, expiry (Massive, next two contracts of each).
    `index`: report_date, fci_value (CME's published index). `corn` is the grain strip's corn tile, or None.
    A market with no data is left out, never faked."""
    made: dict[str, dict] = {}
    if ls is not None and len(ls):
        ls = ls.copy()
        ls["date"] = pd.to_datetime(ls["date"]).dt.date
        ls["expiry"] = pd.to_datetime(ls["expiry"]).dt.date
        for label, code, unit, dec in LIVESTOCK_QUOTES:
            try:
                d = ls[ls.product_code == code]
                if d.empty:
                    continue
                live = d[d["date"] == d["date"].max()]         # contracts that traded on the latest day
                ahead = {(int(r.year), r.month): r.expiry for r in live.itertuples() if r.expiry >= today}
                if not ahead:
                    continue
                y, m = min(ahead, key=ahead.get)               # cash-settled: nearest unexpired contract
                mv = _move(_series(ls, code, y, m))
                if mv is None:
                    continue
                last, chg, day = mv
                made[label] = {"label": label, "contract": _label(y, m), "ticker": f"{code}{m}{str(y)[-1]}",
                               "hist": _hist(_series(ls, code, y, m)), "value": last, "change": chg,
                               "unit": unit, "decimals": dec, "as_of": day}
            except Exception as exc:  # noqa: BLE001 -- one market must not take the strip down
                log.warning("quote %s failed: %s", label, exc)

    idx = None
    try:
        if index is not None and len(index):
            e = index.dropna(subset=["fci_value"]).copy()
            e["report_date"] = pd.to_datetime(e["report_date"]).dt.date
            e = e.sort_values("report_date")
            if len(e):
                day = e["report_date"].iloc[-1]
                if (today - day).days <= STALE_INDEX_DAYS:
                    last = float(e["fci_value"].iloc[-1])
                    chg = last - float(e["fci_value"].iloc[-2]) if len(e) > 1 else None
                    idx = {"label": "Feeder Cattle Index", "contract": f"CME cash index · {day.strftime('%b')} {day.day}",
                           "value": last, "change": chg, "unit": "$/cwt", "decimals": 2, "as_of": day, "index": True}
    except Exception as exc:  # noqa: BLE001
        log.warning("Feeder Cattle Index quote failed: %s", exc)

    out = [made[k] for k in ("Live cattle", "Feeder cattle") if k in made]
    if idx:
        out.append(idx)
    if "Lean hogs" in made:
        out.append(made["Lean hogs"])
    if corn:
        out.append(corn)
    return out


SNAPSHOT_TTL = 60                 # seconds the delayed prices are reused for, across every visitor


def parse_snapshots(results: list[dict]) -> dict[str, dict]:
    """{ticker: {"price", "as_of"}} from /snapshot rows. A row counts only when it carries a last trade AND Massive's
    own DELAYED label; anything else is left out (the tile keeps its settlement)."""
    out: dict[str, dict] = {}
    for r in results or []:
        try:
            lt = r.get("last_trade") or {}
            tf = str(lt.get("timeframe", "")).upper()
            px, ts = lt.get("price"), lt.get("last_updated")
            if tf != "DELAYED" or not px or not ts:
                continue
            tkr = (r.get("details") or {}).get("ticker") or r.get("ticker")      # Massive puts it under details
            if not tkr:
                continue
            out[tkr] = {"price": float(px), "as_of": datetime.fromtimestamp(int(ts) / 1e9, CT)}
        except Exception as exc:  # noqa: BLE001 -- one bad row must not take the rest down
            log.warning("snapshot row skipped: %s", exc)
    return out


def overlay_delayed(tiles: list[dict], snaps: dict[str, dict]) -> list[dict]:
    """Lay the delayed last-trade prices over settlement tiles (same order, same labels). A tile whose ticker has no
    usable snapshot keeps its settlement; the soy crush is rebuilt only when all three legs have one."""
    out = []
    for q in tiles:
        q = dict(q)
        sn = snaps.get(q.get("ticker", ""))
        if sn:
            prev = prior_settle(q.get("hist"), sn["as_of"])
            if prev is not None:
                q.update(value=sn["price"], change=sn["price"] - prev, as_of=sn["as_of"], delayed=True)
        elif q.get("crush_tickers"):
            legs = {c: snaps.get(t) for c, t in q["crush_tickers"].items()}
            if all(legs.values()):
                when = min(v["as_of"] for v in legs.values())
                prev = prior_settle(q.get("hist"), when)
                if prev is not None:
                    last = 0.022 * legs["ZM"]["price"] + 0.11 * legs["ZL"]["price"] - legs["ZS"]["price"] / 100.0
                    q.update(value=last, change=last - prev, delayed=True, as_of=when)
        out.append(q)
    return out


def wanted_tickers(tiles: list[dict]) -> list[str]:
    t: list[str] = []
    for q in tiles:
        if q.get("ticker"):
            t.append(q["ticker"])
        t.extend((q.get("crush_tickers") or {}).values())
    return sorted(set(t))


def with_delayed(tiles: list[dict]) -> list[dict]:
    """`tiles` with delayed prices laid over them. Never raises: any failure leaves the settlement tiles as they are."""
    import streamlit as st

    @st.cache_data(ttl=SNAPSHOT_TTL, show_spinner=False)
    def _snaps(tickers: tuple) -> dict:
        cc = _cot_module("cot_client")
        key = cc._secret("MASSIVE_API_KEY")
        if not key:
            raise RuntimeError("no MASSIVE_API_KEY")
        data = _cot_module("cot_massive")._get("/snapshot", key, {"ticker.any_of": ",".join(tickers), "limit": len(tickers)})
        return parse_snapshots(data.get("results", []))      # raising above keeps a failure out of the cache

    try:
        tk = wanted_tickers(tiles)
        return overlay_delayed(tiles, _snaps(tuple(tk))) if tk else tiles
    except Exception as exc:  # noqa: BLE001
        log.warning("delayed prices unavailable, showing settlements: %s", exc)
        return tiles


def _clock(ts: datetime) -> str:
    h = ts.hour % 12 or 12
    return f"{ts.strftime('%a %b')} {ts.day}, {h}:{ts.minute:02d} {'AM' if ts.hour < 12 else 'PM'} CT"


def tile_html(q: dict) -> str:
    """One tile. Classes only (Streamlit's markdown sanitizer rewrites inline styles)."""
    dec = q["decimals"]
    chg = q["change"]
    if chg is None:
        cls, arrow, txt = "flat", "", "&mdash;"
    elif abs(chg) < 0.5 * 10 ** -dec:
        cls, arrow, txt = "flat", "", "unch"
    else:
        cls, arrow = ("up", "▲ ") if chg > 0 else ("down", "▼ ")
        txt = f"{abs(chg):,.{dec}f}"
    return (f'<div class="jsa-quote"><div class="jsa-q-label">{q["label"]}</div>'
            f'<div class="jsa-q-price">{q["value"]:,.{dec}f}<span class="jsa-q-unit">{q["unit"]}</span></div>'
            f'<div class="jsa-q-chg jsa-q-{cls}">{arrow}{txt}</div>'
            f'<div class="jsa-q-contract">{q["contract"]}</div></div>')


QUOTE_CSS = """
<style>
.jsa-quotes { display:grid; grid-template-columns:repeat(auto-fill, minmax(132px, 1fr)); gap:0.6rem; margin:0.2rem 0 0.4rem; }
.jsa-quote { background:#ffffff; border:1px solid #d7e2dc; border-top:3px solid #5e7164;
  border-radius:8px; padding:0.55rem 0.75rem 0.5rem; }
.jsa-q-label { font-size:0.68rem; text-transform:uppercase; letter-spacing:0.08em; color:#5f7267; font-weight:600; }
.jsa-q-price { font-size:1.35rem; font-weight:700; color:#32373c; line-height:1.25; font-variant-numeric:tabular-nums; }
.jsa-q-unit { font-size:0.68rem; font-weight:500; color:#8a9a90; margin-left:0.3rem; }
.jsa-q-chg { font-size:0.82rem; font-weight:600; font-variant-numeric:tabular-nums; }
.jsa-q-up { color:#16a34a; } .jsa-q-down { color:#dc2626; } .jsa-q-flat { color:#8a9a90; }
.jsa-q-contract { font-size:0.68rem; color:#8a9a90; margin-top:0.05rem; }
.jsa-q-note { font-size:0.72rem; color:#8a9a90; margin:0 0 0.9rem; }
</style>
"""


SKELETON_CSS = """
<style>
@keyframes jsa-shimmer { 0% { background-position:200% 0; } 100% { background-position:-200% 0; } }
.jsa-q-skel { min-height:6.4rem; background:linear-gradient(90deg,#f1f5f3 25%,#e4ece7 50%,#f1f5f3 75%);
  background-size:200% 100%; animation:jsa-shimmer 1.6s linear infinite; border-top-color:#d7e2dc; }
</style>
"""


def placeholder_html(n: int = 8) -> str:
    """Grey, shimmering tiles the size of the real ones, shown while the prices load so the page does not jump
    when they arrive (the tabs below draw first, then the strip fills in above them)."""
    return (QUOTE_CSS + SKELETON_CSS
            + f"<style>@media (min-width: 900px){{.jsa-quotes{{grid-template-columns:repeat({n}, minmax(0, 1fr));}}}}</style>"
            + '<div class="jsa-quotes">' + '<div class="jsa-quote jsa-q-skel"></div>' * n + "</div>"
            + '<div class="jsa-q-note">Loading prices&hellip;</div>')


def strip_html(quotes: list[dict], kind: str = "grain") -> tuple[str, str]:
    """(the tiles block, the footnote)."""
    delayed = [q for q in quotes if q.get("delayed")]
    if delayed:
        # Tiles with no intraday price (ethanol) are marked as end-of-day so the strip is honest tile by tile.
        quotes = [q if (q.get("delayed") or q.get("index")) else dict(q, contract=f"{q['contract']} · settle") for q in quotes]
        block = '<div class="jsa-quotes">' + "".join(tile_html(q) for q in quotes) + "</div>"
        latest = max(q["as_of"] for q in delayed)
        idx = next((q for q in quotes if q.get("index")), None)
        what = ("Chi Platts is the CME Chicago ethanol futures settle (end of day). "
                if any(q["label"] == "Chi Platts ethanol" for q in quotes) else "")
        crush = ("Soy crush is the board crush on the soybean nearby month. "
                 if any(q["label"] == "Soy crush" for q in quotes) else "")
        roll = ("Nearby contracts roll after first notice day. " if kind == "grain"
                else "Livestock futures are on the nearest unexpired contract. ")
        cash = (f"The Feeder Cattle Index is CME's published cash index for {idx['as_of'].strftime('%b')} {idx['as_of'].day}; "
                "CME posts it 1-3 business days after the sales date. " if idx else "")
        note = (f"Futures prices are delayed at least 10 minutes (last trade as of {_clock(latest)}); change is from the prior settlement. "
                f"{roll}{what}{crush}{cash}Not live quotes.")
        return block, note
    block = '<div class="jsa-quotes">' + "".join(tile_html(q) for q in quotes) + "</div>"
    days = sorted({q["as_of"] for q in quotes if not q.get("index")} or {q["as_of"] for q in quotes})
    as_of = days[-1]
    if kind == "livestock":
        idx = next((q for q in quotes if q.get("index")), None)
        note = (f"Settlement prices as of {as_of.strftime('%a %b')} {as_of.day}, change from the prior settlement. "
                "Livestock futures are on the nearest unexpired contract. "
                + (f"The Feeder Cattle Index is CME's published cash index for {idx['as_of'].strftime('%b')} "
                   f"{idx['as_of'].day}; CME posts it 1-3 business days after the sales date. " if idx else "")
                + "End-of-day settlements, not live quotes.")
        return block, note
    note = (f"Settlement prices as of {as_of.strftime('%a %b')} {as_of.day}, change from the prior settlement. Nearby "
            "contracts roll after first notice day. Chi Platts is the CME Chicago ethanol futures settle. Soy crush "
            "is the board crush on the soybean nearby month. End-of-day settlements, not live quotes.")
    return block, note


# -- data ---------------------------------------------------------------------
ETHANOL_SQL = (
    "SELECT asof_date, contract_ym, settle, prev_settle FROM JSA.BASIS_TRACKER.ETHANOL_FUTURES "
    "WHERE product_code = 'CU' AND settle IS NOT NULL AND asof_date = "
    "(SELECT MAX(asof_date) FROM JSA.BASIS_TRACKER.ETHANOL_FUTURES WHERE product_code = 'CU' "
    "AND settle IS NOT NULL) ORDER BY contract_ym")


def _read_ethanol(cc) -> pd.DataFrame:
    """The latest ethanol capture, read straight from the connection. NOT through cot_client._query: that
    helper turns every column it does not know into a number, which blanked contract_ym and asof_date and
    took the whole strip down with it."""
    conn = cc._connect()
    try:
        df = pd.read_sql(ETHANOL_SQL, conn)
    finally:
        conn.close()
    df.columns = [c.lower() for c in df.columns]
    for c in ("settle", "prev_settle"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


INDEX_SQL = ("SELECT report_date, fci_value FROM JSA.CME_FEEDER_CATTLE.CME_FTP_DAILY "
             "WHERE fci_value IS NOT NULL ORDER BY report_date DESC LIMIT 5")


def _read_index(cc) -> pd.DataFrame:
    """CME's published Feeder Cattle Index, newest five days, straight off the connection (the same reason as
    `_read_ethanol`: cot_client._query coerces columns it does not know)."""
    conn = cc._connect()
    try:
        df = pd.read_sql(INDEX_SQL, conn)
    finally:
        conn.close()
    df.columns = [c.lower() for c in df.columns]
    df["fci_value"] = pd.to_numeric(df["fci_value"], errors="coerce")
    return df


def _read_livestock(cm, key: str, today: date) -> pd.DataFrame:
    """Massive settles for the next two contracts of LE, GF and HE, the three markets fetched side by side
    (each is two or three calls and Massive answers in about a second apiece)."""
    from concurrent.futures import ThreadPoolExecutor
    since = today - timedelta(days=14)

    def one(code):
        return cm.livestock_settles(key, today, since, products=(code,))

    frames = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [(c, ex.submit(one, c)) for _, c, _, _ in LIVESTOCK_QUOTES]
        for code, fut in futs:
            try:
                frames.append(fut.result())
            except Exception as exc:  # noqa: BLE001 -- the other markets still draw
                log.warning("livestock settles %s failed: %s", code, exc)
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_livestock() -> tuple[list[dict], str | None]:
    """Cached readers for the Livestock tab's strip: (tiles, error). Never raises. The futures and the index are
    cached separately and a failed or empty read RAISES inside its cached function, because Streamlit does not
    cache an exception: a hiccup at Massive or Snowflake then costs one rerun, not 15 minutes of blank tiles."""
    import streamlit as st

    @st.cache_data(ttl=900, show_spinner=False)
    def _futures(day_iso: str) -> pd.DataFrame:
        cc = _cot_module("cot_client")
        key = cc._secret("MASSIVE_API_KEY")
        if not key:
            return pd.DataFrame()
        ls = _read_livestock(_cot_module("cot_massive"), key, date.fromisoformat(day_iso))
        if ls.empty:
            raise RuntimeError("Massive returned no livestock settlements")
        return ls

    @st.cache_data(ttl=900, show_spinner=False)
    def _index(day_iso: str) -> pd.DataFrame:
        return _read_index(_cot_module("cot_client"))

    today = datetime.now(CT).date()
    ls, idx, corn = pd.DataFrame(), pd.DataFrame(), None
    try:
        ls = _futures(today.isoformat())
    except Exception as exc:  # noqa: BLE001 -- the index and corn still draw
        log.warning("livestock futures read failed: %s", exc)
    try:
        idx = _index(today.isoformat())
    except Exception as exc:  # noqa: BLE001 -- the futures still draw without the index
        log.warning("feeder index read failed: %s", exc)
    try:
        grain, _ = load()
        corn = next((q for q in grain if q["label"] == "Corn"), None)
    except Exception as exc:  # noqa: BLE001
        log.warning("corn tile for the livestock strip failed: %s", exc)
    try:
        tiles = with_delayed(build_livestock_quotes(ls, idx, corn, today))
    except Exception as exc:  # noqa: BLE001
        log.warning("livestock strip failed: %s", exc)
        return [], str(exc)[:160]
    return tiles, None


WARM_EVERY_SECONDS = 780          # a little under the 15-minute cache, so the cache is refilled as it expires
_warm_lock = threading.Lock()
_warm_at = 0.0


def warm_livestock() -> bool:
    """Fill the Livestock strip's caches in the background, so the first click on Livestock Apps is instant.

    Called once the grain strip is drawn. At most one warm-up per WARM_EVERY_SECONDS for the whole app process
    (the caches are shared by every visitor), so a busy hour is one extra set of Massive calls per window, not
    one per visit. A daemon thread that never touches the page: it calls `load_livestock()`, which only fills
    st.cache_data, and a failure there just leaves the tab to load it the ordinary way. Returns whether it
    started one."""
    global _warm_at
    with _warm_lock:
        if time.time() - _warm_at < WARM_EVERY_SECONDS:
            return False
        _warm_at = time.time()

    def work():
        try:
            load_livestock()
        except Exception as exc:  # noqa: BLE001 -- load_livestock does not raise; belt and braces
            log.warning("livestock warm-up failed: %s", exc)

    t = threading.Thread(target=work, name="jsa-livestock-warm", daemon=True)
    try:   # let the cache see the app's runtime, as Streamlit documents for threads that use its caches
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        ctx = get_script_run_ctx()
        if ctx is not None:
            add_script_run_ctx(t, ctx)
    except Exception:  # noqa: BLE001
        pass
    t.start()
    return True


def load() -> tuple[list[dict], str | None]:
    """Cached reader: (tiles, error). Never raises: the strip must not take the page down."""
    import streamlit as st

    @st.cache_data(ttl=900, show_spinner=False)
    def _load(day_iso: str):
        today = date.fromisoformat(day_iso)
        cc = _cot_module("cot_client")
        fm = _cot_module("futures_move")
        settles = cc.load_settlements((today - timedelta(days=40)).isoformat())
        try:
            eth = _read_ethanol(cc)
        except Exception as exc:  # noqa: BLE001 -- the grains still draw without the ethanol proxy
            log.warning("ethanol read failed: %s", exc)
            eth = pd.DataFrame()
        return build_quotes(settles, eth, today, fm)

    try:
        return with_delayed(_load(datetime.now(CT).date().isoformat())), None
    except Exception as exc:  # noqa: BLE001
        log.warning("price strip failed: %s", exc)
        return [], str(exc)[:160]


def fetch(kind: str = "grain") -> tuple[list[dict], str | None]:
    """The slow half of `render`: `kind` is "grain" (the default strip) or "livestock" (the Livestock Apps tab's).
    Kept apart from drawing so the page can show a placeholder while this runs and replace it only once the
    prices are in hand (opening a container in an st.empty() slot clears the slot at once)."""
    return load_livestock() if kind == "livestock" else load()


def render(kind: str = "grain", data: tuple[list[dict], str | None] | None = None) -> None:
    """Draw the strip; `data` is `fetch(kind)`'s result when the caller already has it."""
    import streamlit as st
    quotes, err = data if data is not None else fetch(kind)
    if not quotes:
        # Say so rather than leave a gap nobody can explain; the reason goes to the app log, not to clients.
        log.warning("price strip is empty (error: %s)", err)
        st.markdown('<div style="color:#8a9a90;font-size:0.8rem;margin:0.2rem 0 0.8rem">'
                    'Futures prices are temporarily unavailable.</div>', unsafe_allow_html=True)
        return
    # On a wide screen the tiles share the whole row equally (auto-fill would leave an empty column at the right
    # edge); on a narrower one the base rule wraps them into rows of equal-width tiles.
    st.markdown(QUOTE_CSS + f"<style>@media (min-width: 900px){{.jsa-quotes{{grid-template-columns:"
                f"repeat({len(quotes)}, minmax(0, 1fr));}}}}</style>", unsafe_allow_html=True)
    block, note = strip_html(quotes, kind)
    st.markdown(block, unsafe_allow_html=True)
    st.markdown(f'<div class="jsa-q-note">{note}</div>', unsafe_allow_html=True)
