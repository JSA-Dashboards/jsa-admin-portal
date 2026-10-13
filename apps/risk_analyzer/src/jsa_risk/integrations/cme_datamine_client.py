"""CME DataMine end-of-day corn options: at-the-money implied vol per contract.

JSA's CME license is DataMine "F&O End of Market Summary Standard" (LIC-A174271), not the
Options Analytics Greeks REST API -- an earlier integration attempt against that API 403s
permanently for this account, so IV_SNAPSHOT is refreshed from DataMine's daily settlement
files instead. DataMine is JSA's only CME data source; there is no Greeks API fallback.

Verified against the live service on 2026-09-20. Things that are not obvious:

1. Auth is an OAuth bearer token from the same token endpoint as the Greeks API, using an
   API ID whose Customer Center Role is "DataMine API (OAuth)". HTTP Basic is rejected
   (401), even though CME's own DataMine docs still describe Basic Auth IDs.
2. DataMine moved platforms in 2025. The old datamine.cmegroup.com /cme/api/v1/list is
   gone; the new host only serves /cme/api/v2/download?fid=<file id>. There is no list
   endpoint on it, so file IDs are built from the pattern on the product page:
   {YYYYMMDD}-EOD_XCBT_PY_OPT_0_{session}. Corn options are symbol PY, not OZC.
3. Three files a day: RTH_E (Early, ~6pm CT), ETH_P (Preliminary, ~10pm CT), ETH_F
   (Final, ~10am CT next trade date). The Early file carries NO implied volatility — every
   row blank — so it is deliberately not offered here.
4. A not-yet-posted file returns 404 with detail "File not found", distinct from a bad
   path's "The requested URL was not found". The former is normal and means "try an
   older date"; the latter means the URL is wrong.
5. Settlement prices are in tenths of a cent (1275 = 127.5 c/bu). Delta is reported as a
   positive magnitude for puts too, so a put's delta must be negated before use.
6. The file has no underlying futures price. It is recovered by put-call parity at the
   ATM strike, F = K + (C - P). That uses r = 0, which is the rate that best reproduces
   CME's own settlements from its own IVs; on 2026-09-18 the Oct, Nov and Dec options all
   implied the same December future to within 0.25c, which is a good consistency check.

IV arrives as a decimal (0.2163); IV_SNAPSHOT stores percent (21.63), so everything
leaving this module for that table is already multiplied by 100.

Every failure raises CmeDataMineUnavailable (or its subclass FileNotPosted) so callers can
report "not available" rather than crash.
"""
import csv
import gzip
import io
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import requests


DATAMINE_BASE_URL = "https://datamine.new.cmegroup.com/cme/api/v2"
CME_TOKEN_URL = "https://auth.cmegroup.com/as/token.oauth2"


@dataclass(frozen=True)
class CmeDataMineConfig:
    """Defined here rather than in jsa_risk.config so that a headless run (the droplet
    cron) imports no Streamlit. config.py re-exports it for the app's use."""
    api_id: str
    password: str
    base_url: str = DATAMINE_BASE_URL
    token_url: str = CME_TOKEN_URL


def config_from_dict(s) -> CmeDataMineConfig:
    """Build from any mapping - st.secrets in the app, a tomllib dict in a script."""
    return CmeDataMineConfig(
        api_id=s["api_id"], password=s["password"],
        base_url=s.get("base_url", DATAMINE_BASE_URL),
        token_url=s.get("token_url", CME_TOKEN_URL),
    )


CORN_OPTION_SYMBOL = "PY"


@dataclass(frozen=True)
class DataMineProduct:
    """Where a commodity's option settlements live in DataMine, and the file's own units
    (they differ by product, so put-call parity needs them to line strike and price up)."""
    exchange: str
    symbol: str
    strike_divisor: float = 1.0       # file strike / this = cents per unit
    settlement_divisor: float = 10.0  # file settlement / this = cents per unit


# Keyed by the app's commodity code. Corn is on CBOT (strikes in cents/bu, settlements in
# tenths of a cent); live cattle is on CME (strikes in tenths of a cent/lb, settlements in
# cents). Feeder cattle isn't here: no readable file for it under JSA's license -- a scan of
# the CME exchange found only XCME_OK (live cattle) entitled for this API ID.
DATAMINE_PRODUCTS = {
    "ZC": DataMineProduct("XCBT", CORN_OPTION_SYMBOL, 1.0, 10.0),
    "LE": DataMineProduct("XCME", "OK", 10.0, 1.0),
}
_USER_AGENT = "JSA-Risk-Analyzer/1.0 (python-requests)"
DEFAULT_TOKEN_TTL_SECONDS = 30 * 60
_EARLY_REFRESH_SECONDS = 30

# Settlement code -> the session suffix in the file ID. Early ("RTH_E") is omitted on
# purpose: it has no implied vol, so offering it would only produce empty refreshes.
SETTLEMENTS = {"F": "ETH_F", "P": "ETH_P"}
SETTLEMENT_NAMES = {"F": "Final", "P": "Preliminary"}

# Option expiry month number -> CME month letter, quarterly months only. IV_SNAPSHOT is
# keyed by the underlying quarterly future, and the quarterly option is the one whose
# expiry matches that future, so it is the defensible single value for the key. Serial
# options (Oct/Nov onto Dec, etc.) would otherwise collide on the same key.
QUARTERLY_MONTH_LETTERS = {3: "H", 5: "K", 7: "N", 9: "U", 12: "Z"}

# How far from 50 delta the chosen strike may sit before we decline to call it ATM.
# Beyond ~35-65 delta, skew makes the vol unrepresentative.
_NEAR_THE_MONEY_DELTA_TOLERANCE = 0.15

_token_cache: Dict[Tuple[str, str], Tuple[str, float]] = {}


class CmeDataMineUnavailable(RuntimeError):
    """Any failure fetching or reading a DataMine file."""


class FileNotPosted(CmeDataMineUnavailable):
    """The file for this date/settlement isn't published yet (or never will be, e.g. a
    holiday). Normal — the caller should try an older date."""


@dataclass(frozen=True)
class EodIvQuote:
    """One quarterly contract's at-the-money settlement IV, ready for IV_SNAPSHOT."""
    canonical_key: str        # "Z26" — the underlying quarterly future
    iv_pct: float             # percent, e.g. 21.63
    trade_date: date          # the settlement's trade date, NOT the fetch date
    settlement: str           # "F" or "P"
    atm_strike: float
    undly_sym: str            # "ZCZ26"
    undly_px: Optional[float] # implied by put-call parity, cents/bu
    dte: Optional[int]        # calendar days from trade date to last trade date
    method: str               # "ATM C+P", "ATM C", or "~0.43d" style fallback

    @property
    def settlement_name(self) -> str:
        return SETTLEMENT_NAMES.get(self.settlement, self.settlement)

    @property
    def source_label(self) -> str:
        return (f"CME DataMine EOD {self.settlement_name} {self.method} "
                f"(K={self.atm_strike:g} @ {self.trade_date.isoformat()})")


def file_id(
    trade_date: date, settlement: str = "F", symbol: str = CORN_OPTION_SYMBOL, exchange: str = "XCBT",
) -> str:
    if settlement not in SETTLEMENTS:
        raise ValueError(f"settlement must be one of {sorted(SETTLEMENTS)}, got {settlement!r}")
    return f"{trade_date:%Y%m%d}-EOD_{exchange}_{symbol}_OPT_0_{SETTLEMENTS[settlement]}"


def _get_token(config: CmeDataMineConfig) -> str:
    cache_key = (config.token_url, config.api_id)
    cached = _token_cache.get(cache_key)
    now = time.time()
    if cached and cached[1] > now:
        return cached[0]
    try:
        resp = requests.post(
            config.token_url,
            data={"grant_type": "client_credentials"},
            auth=(config.api_id, config.password),
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        token = payload["access_token"]
    except Exception as e:
        raise CmeDataMineUnavailable(f"CME token request failed: {e}") from e
    expires_in = payload.get("expires_in", DEFAULT_TOKEN_TTL_SECONDS)
    _token_cache[cache_key] = (token, now + expires_in - _EARLY_REFRESH_SECONDS)
    return token


def download_eod(
    config: CmeDataMineConfig, trade_date: date, settlement: str = "F",
    symbol: str = CORN_OPTION_SYMBOL, exchange: str = "XCBT",
) -> str:
    """The decompressed CSV text for one day's settlement file."""
    fid = file_id(trade_date, settlement, symbol, exchange)
    token = _get_token(config)
    try:
        resp = requests.get(
            f"{config.base_url.rstrip('/')}/download",
            params={"fid": fid},
            headers={"Authorization": f"Bearer {token}", "User-Agent": _USER_AGENT},
            timeout=90,
        )
    except Exception as e:
        raise CmeDataMineUnavailable(f"DataMine request failed for {fid}: {e}") from e

    if resp.status_code == 404:
        detail = ""
        try:
            detail = " ".join(err.get("detail", "") for err in resp.json().get("errors", []))
        except Exception:
            pass
        if "file not found" in detail.lower():
            raise FileNotPosted(f"{fid} is not posted")
        raise CmeDataMineUnavailable(f"DataMine 404 for {fid} (bad path?): {detail or resp.text[:200]}")
    if resp.status_code in (401, 403):
        raise CmeDataMineUnavailable(
            f"DataMine returned {resp.status_code} for {fid}. The API ID must have the "
            f"'DataMine API (OAuth)' role and the license must cover symbol {symbol}."
        )
    if resp.status_code != 200:
        raise CmeDataMineUnavailable(f"DataMine returned {resp.status_code} for {fid}: {resp.text[:200]}")

    raw = resp.content
    try:
        return gzip.decompress(raw).decode("utf-8") if raw[:2] == b"\x1f\x8b" else raw.decode("utf-8")
    except Exception as e:
        raise CmeDataMineUnavailable(f"Could not read {fid} as gzip CSV: {e}") from e


def latest_available(
    config: CmeDataMineConfig, today: date, lookback_days: int = 7,
    settlements: Iterable[str] = ("F", "P"), symbol: str = CORN_OPTION_SYMBOL,
    exchange: str = "XCBT",
) -> Tuple[date, str, str]:
    """(trade_date, settlement, csv_text) for the newest posted file.

    Walks back from `today`, newest date first, trying Final before Preliminary for each
    date. A newer Preliminary therefore beats an older Final, and when the Final for a day
    posts the next morning, the next run naturally upgrades to it. Weekends are skipped
    without a request; holidays just 404 and fall through.
    """
    settlements = tuple(settlements)
    for back in range(lookback_days + 1):
        d = today - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        for s in settlements:
            try:
                return d, s, download_eod(config, d, s, symbol, exchange)
            except FileNotPosted:
                continue
    raise FileNotPosted(
        f"No {'/'.join(settlements)} settlement file found in the {lookback_days} days "
        f"up to {today.isoformat()}"
    )


def parse_eod_csv(text: str) -> List[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def _num(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "", "NULL") else None
    except ValueError:
        return None


def _yyyymmdd(v) -> Optional[date]:
    v = (v or "").strip()
    if len(v) != 8 or not v.isdigit():
        return None
    return date(int(v[:4]), int(v[4:6]), int(v[6:8]))


def atm_iv_by_canonical_key(
    rows: Iterable[dict], settlement: str = "F", trade_date: Optional[date] = None,
    month_letters: Optional[Dict[int, str]] = None, commodity_code: str = "ZC",
    strike_divisor: float = 1.0, settlement_divisor: float = 10.0,
) -> Dict[str, EodIvQuote]:
    """ATM settlement IV per quarterly contract, e.g. {"Z26": EodIvQuote(iv_pct=21.63, ...)}.

    ATM is the strike whose CALL delta sits nearest 0.50 — the file has no moneyness flag
    and no underlying price, and put deltas are unsigned. Where that strike has both a call
    and a put IV, the two are averaged. A contract whose nearest strike is further than
    0.15 delta from 0.50 is skipped rather than guessed at.
    """
    month_letters = month_letters or QUARTERLY_MONTH_LETTERS   # {month number: letter} of listed futures
    by_month: Dict[Tuple[int, int], Dict[float, Dict[str, dict]]] = {}
    for r in rows:
        iv = _num(r.get("Implied Volatility"))
        if not iv:                                   # blank or zero: nothing to use
            continue
        if (r.get("Contract Day") or "00").strip() not in ("", "0", "00"):
            continue                                 # not a standard monthly expiry
        try:
            year, month = int(r["Contract Year"]), int(r["Contract Month"])
        except (KeyError, ValueError):
            continue
        if month not in month_letters:
            continue
        strike = _num(r.get("Strike Price"))
        pc = (r.get("Put/Call") or "").strip().upper()
        if strike is None or pc not in ("C", "P"):
            continue
        by_month.setdefault((year, month), {}).setdefault(strike, {})[pc] = r

    quotes: Dict[str, EodIvQuote] = {}
    for (year, month), strikes in by_month.items():
        calls = {k: v["C"] for k, v in strikes.items()
                 if "C" in v and _num(v["C"].get("Delta")) is not None}
        if calls:
            k_atm = min(calls, key=lambda k: abs(_num(calls[k]["Delta"]) - 0.5))
            sel_delta = _num(calls[k_atm]["Delta"])
        else:                                        # puts only: their |delta| is given
            puts = {k: v["P"] for k, v in strikes.items()
                    if "P" in v and _num(v["P"].get("Delta")) is not None}
            if not puts:
                continue
            k_atm = min(puts, key=lambda k: abs(abs(_num(puts[k]["Delta"])) - 0.5))
            sel_delta = abs(_num(puts[k_atm]["Delta"]))
        dist = abs(sel_delta - 0.5)
        if dist > _NEAR_THE_MONEY_DELTA_TOLERANCE:
            continue

        legs = strikes[k_atm]
        ivs = [_num(legs[pc]["Implied Volatility"]) for pc in ("C", "P") if pc in legs]
        iv = sum(ivs) / len(ivs)
        if dist <= 0.05:
            method = "ATM C+P" if len(ivs) == 2 else f"ATM {'C' if 'C' in legs else 'P'}"
        else:
            method = f"~{sel_delta:.2f}d"

        undly_px = None
        if "C" in legs and "P" in legs:
            c, p = _num(legs["C"].get("Settlement")), _num(legs["P"].get("Settlement"))
            if c is not None and p is not None:
                undly_px = round(k_atm / strike_divisor + (c - p) / settlement_divisor, 4)

        any_leg = next(iter(legs.values()))
        td = trade_date or _yyyymmdd(any_leg.get("Trade Date"))
        last = _yyyymmdd(any_leg.get("Last Trade Date"))
        letter = month_letters[month]
        key = f"{letter}{year % 100:02d}"
        quotes[key] = EodIvQuote(
            canonical_key=key,
            iv_pct=round(iv * 100, 4),                     # IV_SNAPSHOT.IV is NUMBER(8,4), percent
            trade_date=td,
            settlement=settlement,
            atm_strike=k_atm,
            undly_sym=f"{commodity_code}{key}",
            undly_px=undly_px,
            dte=(last - td).days if (last and td) else None,
            method=method,
        )
    return quotes


@dataclass(frozen=True)
class OptionIv:
    """One specific option's settlement vol, as found (or interpolated) in a DataMine file."""
    iv_pct: float
    strike: float        # dollars per unit; the listed strike used (the nearer one when interpolating)
    method: str          # "exact", "interpolated", or "nearest strike"


def option_iv(
    rows: Iterable[dict], year: int, month: int, put_call: str, strike: float,
    strike_divisor: float = 1.0,
) -> Optional[OptionIv]:
    """This option's own settlement IV -- strike- and expiry-specific, so it carries the
    skew and covers serial months, unlike the one ATM vol per contract in IV_SNAPSHOT.

    `strike` is dollars per unit (e.g. 5.05); the file quotes cents scaled by the product's
    strike_divisor (corn 505, live cattle 2300 for $2.30). An exact listed strike wins;
    between two listed strikes it interpolates linearly; outside the listed range it takes
    the nearest. Same side (call/put) first -- the other side only if that side has no vols
    at all for the month, since parity ties them together. Standard monthly options only
    (Contract Day 00); weeklies are skipped.
    """
    want = put_call.strip().upper()[:1]
    by_side: Dict[str, Dict[float, float]] = {"C": {}, "P": {}}
    for r in rows:
        iv = _num(r.get("Implied Volatility"))
        side = (r.get("Put/Call") or "").strip().upper()
        k = _num(r.get("Strike Price"))
        if not iv or side not in by_side or k is None:
            continue
        if (r.get("Contract Day") or "00").strip() not in ("", "0", "00"):
            continue
        try:
            if int(r["Contract Year"]) != year or int(r["Contract Month"]) != month:
                continue
        except (KeyError, ValueError):
            continue
        by_side[side][k / (100 * strike_divisor)] = iv * 100

    curve = by_side.get(want) or by_side["C" if want == "P" else "P"]
    if not curve:
        return None
    ks = sorted(curve)
    for k in ks:
        if abs(k - strike) < 1e-6:
            return OptionIv(round(curve[k], 4), k, "exact")
    lo = max((k for k in ks if k < strike), default=None)
    hi = min((k for k in ks if k > strike), default=None)
    if lo is not None and hi is not None:
        w = (strike - lo) / (hi - lo)
        near = lo if w < 0.5 else hi
        return OptionIv(round(curve[lo] + w * (curve[hi] - curve[lo]), 4), near, "interpolated")
    nearest = min(ks, key=lambda k: abs(k - strike))
    return OptionIv(round(curve[nearest], 4), nearest, "nearest strike")
