from datetime import date

import pandas as pd
import pytest

import quotes

FM = quotes._cot_module("futures_move")
TODAY = date(2026, 11, 4)


def rows(code, month, year, prices, start="2026-10-28"):
    days = pd.date_range(start, periods=len(prices), freq="B")
    return [dict(product_code=code, month=month, year=year, date=d, settle=p) for d, p in zip(days, prices)]


def settles(extra=()):
    r = []
    r += rows("ZC", "Z", 2026, [430, 431, 433, 432, 436])            # Dec corn
    r += rows("ZS", "F", 2027, [1000, 1004, 1010, 1008, 1020])       # Jan beans (Nov rolled off on Oct 31)
    r += rows("ZS", "X", 2026, [990, 995, 1000, 1002, 1003])         # Nov beans, past first notice (Oct 31)
    r += rows("ZM", "F", 2027, [300, 301, 302, 303, 304])
    r += rows("ZL", "F", 2027, [50, 51, 50.5, 52, 53])
    r += rows("ZM", "Z", 2026, [290, 291, 292, 293, 294])
    r += rows("ZL", "Z", 2026, [48, 48, 48, 48, 48])
    r += rows("ZW", "Z", 2026, [540, 541, 539, 542, 545])
    r += rows("KE", "Z", 2026, [560, 561, 562, 563, 564])
    r += list(extra)
    return pd.DataFrame(r)


ETH = pd.DataFrame([
    dict(asof_date="2026-11-03", contract_ym="2026-11", settle=2.14, prev_settle=2.10),
    dict(asof_date="2026-11-03", contract_ym="2026-12", settle=2.20, prev_settle=2.17),
])


def by_label(qs):
    return {q["label"]: q for q in qs}


def test_every_requested_market_is_present_in_display_order():
    qs = quotes.build_quotes(settles(), ETH, TODAY, FM)
    assert [q["label"] for q in qs] == ["Corn", "Chi Platts ethanol", "SRW wheat", "HRW wheat",
                                        "Soybeans", "Soybean meal", "Soybean oil", "Soy crush"]


def test_nearby_rolls_after_first_notice_day_and_the_change_is_on_one_contract():
    q = by_label(quotes.build_quotes(settles(), ETH, TODAY, FM))["Soybeans"]
    assert q["contract"] == "Jan 27"                    # Nov's notice day (Oct 31) has passed
    assert q["value"] == 1020 and q["change"] == 1020 - 1008   # Jan to Jan, never Nov to Jan


def test_still_front_on_the_first_notice_day_itself():
    s = settles()
    assert FM.first_notice_day(2026, "X") == date(2026, 10, 30)     # Nov beans: last business day of October
    on_fnd = by_label(quotes.build_quotes(s, ETH, date(2026, 10, 30), FM))["Soybeans"]
    after = by_label(quotes.build_quotes(s, ETH, date(2026, 11, 2), FM))["Soybeans"]
    assert on_fnd["contract"] == "Nov 26"                           # still the nearby ON its notice day
    assert after["contract"] == "Jan 27"                            # rolled the day after


def test_each_market_uses_its_own_nearby():
    qs = by_label(quotes.build_quotes(settles(), ETH, TODAY, FM))
    assert qs["Corn"]["contract"] == "Dec 26" and qs["Corn"]["change"] == 436 - 432
    # meal's own notice day (Nov 30) is still ahead, so its nearby is Dec, while beans are already on Jan
    assert qs["Soybean meal"]["contract"] == "Dec 26"
    assert qs["Soybean meal"]["change"] == 294 - 293


def test_soy_crush_is_the_board_crush_on_the_soybean_month():
    q = by_label(quotes.build_quotes(settles(), ETH, TODAY, FM))["Soy crush"]
    last = 0.022 * 304 + 0.11 * 53 - 1020 / 100
    prev = 0.022 * 303 + 0.11 * 52 - 1008 / 100
    assert q["value"] == pytest.approx(last)
    assert q["change"] == pytest.approx(last - prev)
    assert q["contract"] == "Jan 27 board" and q["unit"] == "$/bu"


def test_chi_platts_is_the_current_month_contract_with_its_own_prior_settle():
    q = by_label(quotes.build_quotes(settles(), ETH, TODAY, FM))["Chi Platts ethanol"]
    assert q["contract"] == "Nov 26" and q["value"] == 2.14 and q["change"] == pytest.approx(0.04)


def test_stale_or_missing_ethanol_is_left_out_not_faked():
    old = ETH.assign(asof_date="2026-10-01")
    assert "Chi Platts ethanol" not in by_label(quotes.build_quotes(settles(), old, TODAY, FM))
    assert "Chi Platts ethanol" not in by_label(quotes.build_quotes(settles(), pd.DataFrame(), TODAY, FM))


def test_a_market_with_no_settles_is_left_out():
    s = settles()
    s = s[s.product_code != "KE"]
    assert "HRW wheat" not in by_label(quotes.build_quotes(s, ETH, TODAY, FM))


def test_tiles_color_the_change_and_say_unch():
    up = quotes.tile_html(dict(label="Corn", contract="Dec 26", value=436.0, change=4.0, unit="¢/bu", decimals=2))
    dn = quotes.tile_html(dict(label="Corn", contract="Dec 26", value=436.0, change=-4.0, unit="¢/bu", decimals=2))
    fl = quotes.tile_html(dict(label="Corn", contract="Dec 26", value=436.0, change=0.0, unit="¢/bu", decimals=2))
    assert "jsa-q-up" in up and "▲" in up and "jsa-q-down" in dn and "▼" in dn and "unch" in fl


def test_a_broken_ethanol_frame_never_takes_the_grains_down():
    """The live bug: cot_client._query coerced contract_ym and asof_date to numbers (NaN), which raised inside
    build_quotes and removed EVERY tile. A bad ethanol read must cost only the Chi Platts tile."""
    mangled = pd.DataFrame(dict(asof_date=[float("nan")] * 2, contract_ym=[float("nan")] * 2,
                                settle=[2.14, 2.20], prev_settle=[2.10, 2.17]))
    qs = by_label(quotes.build_quotes(settles(), mangled, TODAY, FM))
    assert "Chi Platts ethanol" not in qs
    assert {"Corn", "SRW wheat", "HRW wheat", "Soybeans", "Soybean meal", "Soybean oil", "Soy crush"} <= set(qs)


def test_one_failing_grain_does_not_remove_the_others(monkeypatch):
    real = FM.front_month

    def boom(contracts, today):
        if any(m == "F" for _, m in contracts):     # the soybean/meal/oil Jan contracts
            raise RuntimeError("bad contract data")
        return real(contracts, today)

    monkeypatch.setattr(FM, "front_month", boom)
    qs = by_label(quotes.build_quotes(settles(), ETH, TODAY, FM))
    assert "Corn" in qs and "SRW wheat" in qs


def test_the_ethanol_reader_keeps_the_contract_month_and_date(monkeypatch):
    class Conn:
        closed = False

        def close(self):
            Conn.closed = True

    class Cc:
        @staticmethod
        def _connect():
            return Conn()

    raw = pd.DataFrame({"ASOF_DATE": ["2026-11-03"], "CONTRACT_YM": ["2026-11"], "SETTLE": ["2.14"], "PREV_SETTLE": ["2.10"]})
    monkeypatch.setattr(pd, "read_sql", lambda sql, conn: raw.copy())
    df = quotes._read_ethanol(Cc)
    assert list(df.columns) == ["asof_date", "contract_ym", "settle", "prev_settle"]
    assert df.contract_ym.iloc[0] == "2026-11" and str(df.asof_date.iloc[0]) == "2026-11-03"
    assert df.settle.iloc[0] == 2.14 and Conn.closed
    q = by_label(quotes.build_quotes(settles(), df, TODAY, FM))["Chi Platts ethanol"]
    assert q["contract"] == "Nov 26" and q["value"] == 2.14
