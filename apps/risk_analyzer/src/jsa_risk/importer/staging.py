"""Normalizes raw sheet rows into staging rows ready for preview/commit — ported from
the HTML tool's buildStagingFromMapping/stagingRowValid, including the Position+Qty
sign-derivation rule that was a real bug fix in the original.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, List, Optional, Set

from jsa_risk.pricing.commodities import COMMODITIES


def parse_num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    cleaned = str(s).strip().replace(",", "").replace("$", "")
    if cleaned == "":
        return None
    # "(1,234.50)" style negative accounting notation.
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    # Trailing-period numbers like "23." are valid floats to Python already.
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if negative else value


def parse_type(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = s.strip().lower()
    if t.startswith("c"):
        return "call"
    if t.startswith("p"):
        return "put"
    return None


_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"]


def normalize_date_str(s: Optional[str]) -> Optional[date]:
    if not s or not str(s).strip():
        return None
    s = str(s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def strip_label_suffix(label: str) -> str:
    """Some platforms embed the option suffix in the symbol itself, e.g. "ZCV26{A}P525"
    — strip anything from the { onward so the base symbol decodes normally."""
    idx = label.find("{")
    return label[:idx] if idx >= 0 else label


def label_commodity_code(label: Optional[str]) -> Optional[str]:
    """The recognized 2-letter commodity code at the start of this label (e.g. "ZC" from
    "ZCZ26"), or None when the prefix isn't a known code. An unusual-but-legitimate symbol
    format is never treated as belonging to some *other* commodity -- it's only ever
    excluded from an import when it's positively identified as one."""
    prefix = (label or "").strip().upper()[:2]
    return prefix if prefix in COMMODITIES else None


def distinct_commodity_codes(labels: Iterable[str]) -> Set[str]:
    """The set of recognized commodity codes among these labels' own prefixes -- e.g. to
    tell the user exactly which other commodities were found (and skipped) in a sheet."""
    return {code for code in (label_commodity_code(l) for l in labels) if code is not None}


def looks_like_unit_mismatch(value: Optional[float], reference_price: float) -> bool:
    if value is None or reference_price == 0:
        return False
    ratio = abs(value / reference_price)
    return ratio > 20 or ratio < 0.05


@dataclass
class StagingRow:
    label: str
    type: str
    strike: Optional[float]
    expiry: Optional[date]
    qty: Optional[int]
    iv: Optional[float]
    entry: Optional[float]
    last_tick: Optional[float]


def build_staging_row(raw_row: List[str], headers: List[str], mapping: dict) -> StagingRow:
    def col(key: str) -> str:
        idx = mapping.get(key, -1)
        if idx is None or idx < 0 or idx >= len(raw_row):
            return ""
        return raw_row[idx] or ""

    label_raw = col("label")
    label = strip_label_suffix(label_raw)

    strike_raw = parse_num(col("strike"))
    type_raw = parse_type(col("type"))
    is_future = strike_raw is None
    position_type = "future" if is_future else (type_raw or "call")
    # Strike is quoted in cents/bu (e.g. 440 = $4.40), same convention as futures prices.
    strike = None if strike_raw is None else strike_raw / 100

    expiry = normalize_date_str(col("expiryDate"))

    # Qty is the unsigned contract count; Position ("Net Long"/"Net Short"/"Net") supplies
    # the sign when mapped. "Net" alone (no Long/Short) means flat — qty becomes 0 and the
    # row is dropped by staging_row_valid. If Position isn't mapped, Qty is used as-is
    # (assumed already signed), matching simpler sheet formats.
    qty_raw = parse_num(col("qty"))
    pos_dir = col("positionDir").strip()
    if pos_dir:
        qty_mag = abs(qty_raw) if qty_raw is not None else 0
        if re.search(r"short", pos_dir, re.I):
            qty = -qty_mag
        elif re.search(r"long", pos_dir, re.I):
            qty = qty_mag
        else:
            qty = 0
    else:
        qty = qty_raw

    iv_raw = parse_num(col("iv"))
    iv = None
    if iv_raw is not None:
        iv = iv_raw * 100 if abs(iv_raw) <= 1.5 else iv_raw

    entry_raw = parse_num(col("entry"))
    # Entry/premium is quoted in cents/bu for both futures and options.
    entry = None if entry_raw is None else entry_raw / 100

    last_tick_raw = parse_num(col("lastTick"))
    last_tick = None if last_tick_raw is None else last_tick_raw / 100

    return StagingRow(
        label=label, type=position_type, strike=strike, expiry=expiry,
        qty=None if qty is None else int(qty), iv=iv, entry=entry, last_tick=last_tick,
    )


def staging_row_valid(row: StagingRow) -> bool:
    if not row.label or not row.label.strip():
        return False
    if row.type == "future":
        return row.qty is not None and row.qty != 0
    return (
        row.strike is not None and row.strike > 0
        and row.expiry is not None
        and row.qty is not None and row.qty != 0
        and (row.iv is None or row.iv > 0)
    )
