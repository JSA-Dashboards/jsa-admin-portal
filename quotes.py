"""
quotes.py -- the nearby-futures price strip at the top of the CLIENT portal.

Corn, Chi Platts ethanol, SRW, HRW, soybeans, meal, soy oil and the soy crush, each on its NEARBY
contract with the last settlement and the change from the prior settlement.

SETTLEMENTS, NOT LIVE QUOTES. The grains come from the daily settlement bank
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

The arithmetic (`build_quotes`) takes plain frames so it can be tested without Snowflake; `load()` is the
thin cached reader. The first-notice-day logic is the COT dashboard's own `futures_move.py`, loaded from
the mirrored copy under apps/cftc_cot so there is one implementation of it.
"""
from __future__ import annotations

import importlib.util
import logging
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
        return {"label": label, "contract": _label(*front), "value": last, "change": chg, "unit": unit,
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


def strip_html(quotes: list[dict]) -> tuple[str, str]:
    """(the tiles block, the footnote)."""
    block = '<div class="jsa-quotes">' + "".join(tile_html(q) for q in quotes) + "</div>"
    days = sorted({q["as_of"] for q in quotes})
    as_of = days[-1]
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
        return _load(datetime.now(CT).date().isoformat()), None
    except Exception as exc:  # noqa: BLE001
        log.warning("price strip failed: %s", exc)
        return [], str(exc)[:160]


def render() -> None:
    import streamlit as st
    quotes, err = load()
    if not quotes:
        # Say so rather than leave a gap nobody can explain; the reason goes to the app log, not to clients.
        log.warning("price strip is empty (error: %s)", err)
        st.markdown('<div style="color:#8a9a90;font-size:0.8rem;margin:0.2rem 0 0.8rem">'
                    'Futures prices are temporarily unavailable.</div>', unsafe_allow_html=True)
        return
    st.markdown(QUOTE_CSS, unsafe_allow_html=True)
    block, note = strip_html(quotes)
    st.markdown(block, unsafe_allow_html=True)
    st.markdown(f'<div class="jsa-q-note">{note}</div>', unsafe_allow_html=True)
