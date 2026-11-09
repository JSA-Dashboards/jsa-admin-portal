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


# -- Livestock tab strip ---------------------------------------------------------------
def ls_rows(code, month, year, prices, expiry, start="2026-10-28"):
    days = pd.date_range(start, periods=len(prices), freq="B")
    return [dict(product_code=code, month=month, year=year, date=d, settle=p, expiry=expiry)
            for d, p in zip(days, prices)]


def livestock():
    r = []
    r += ls_rows("LE", "Z", 2026, [230.1, 231.0, 232.5, 232.0, 233.25], date(2026, 12, 31))
    r += ls_rows("LE", "G", 2027, [235.0, 235.5, 236.0, 236.5, 237.0], date(2027, 2, 26))
    r += ls_rows("GF", "F", 2027, [340.0, 341.0, 342.0, 341.5, 343.0], date(2027, 1, 28))
    r += ls_rows("GF", "X", 2026, [335.0, 336.0, 337.0, 336.5, 338.0], date(2026, 11, 20))
    r += ls_rows("HE", "Z", 2026, [80.0, 80.5, 81.0, 80.25, 80.75], date(2026, 12, 14))
    return pd.DataFrame(r)


FEEDER = pd.DataFrame([dict(report_date="2026-11-02", fci_value=361.10), dict(report_date="2026-11-03", fci_value=362.40)])
CORN_TILE = dict(label="Corn", contract="Dec 26", value=436.0, change=4.0, unit="¢/bu", decimals=2,
                 as_of=date(2026, 11, 3))


def test_livestock_tiles_in_the_requested_order():
    qs = quotes.build_livestock_quotes(livestock(), FEEDER, CORN_TILE, TODAY)
    assert [q["label"] for q in qs] == ["Live cattle", "Feeder cattle", "Feeder Cattle Index", "Lean hogs", "Corn"]


def test_livestock_nearby_is_the_nearest_unexpired_contract_and_change_is_one_contract():
    q = by_label(quotes.build_livestock_quotes(livestock(), FEEDER, CORN_TILE, TODAY))
    assert q["Live cattle"]["contract"] == "Dec 26"
    assert q["Live cattle"]["value"] == 233.25 and q["Live cattle"]["change"] == pytest.approx(1.25)
    assert q["Feeder cattle"]["contract"] == "Nov 26"             # nearer than Jan 27 and not expired yet
    assert q["Feeder cattle"]["value"] == 338.0


def test_an_expired_livestock_contract_is_skipped_for_the_next():
    q = by_label(quotes.build_livestock_quotes(livestock(), FEEDER, CORN_TILE, date(2026, 11, 21)))
    assert q["Feeder cattle"]["contract"] == "Jan 27"             # Nov expired on the 20th


def test_feeder_index_carries_its_own_published_date_and_change():
    q = by_label(quotes.build_livestock_quotes(livestock(), FEEDER, CORN_TILE, TODAY))["Feeder Cattle Index"]
    assert q["value"] == 362.40 and q["change"] == pytest.approx(1.30) and q["unit"] == "$/cwt"
    assert q["as_of"] == date(2026, 11, 3) and "Nov 3" in q["contract"]


def test_stale_feeder_index_is_left_out_and_missing_pieces_do_not_break_the_rest():
    old = pd.DataFrame([dict(report_date="2026-10-01", fci_value=350.0)])
    qs = quotes.build_livestock_quotes(livestock(), old, None, TODAY)
    assert [q["label"] for q in qs] == ["Live cattle", "Feeder cattle", "Lean hogs"]
    only_index = quotes.build_livestock_quotes(pd.DataFrame(), FEEDER, None, TODAY)
    assert [q["label"] for q in only_index] == ["Feeder Cattle Index"]
    assert quotes.build_livestock_quotes(pd.DataFrame(), pd.DataFrame(), None, TODAY) == []


def test_livestock_footnote_dates_the_futures_and_the_index_separately():
    qs = quotes.build_livestock_quotes(livestock(), FEEDER, CORN_TILE, TODAY)
    _, note = quotes.strip_html(qs, "livestock")
    assert "Nov 3" in note and "1-3 business days" in note and "Nearby contracts roll after first notice" not in note


def test_livestock_warmup_starts_at_most_once_per_window(monkeypatch):
    started = []
    monkeypatch.setattr(quotes, "load_livestock", lambda: started.append(1) or ([], None))
    monkeypatch.setattr(quotes, "_warm_at", 0.0)
    assert quotes.warm_livestock() is True
    assert quotes.warm_livestock() is False          # a second visitor in the same window does not start another
    for t in __import__("threading").enumerate():
        if t.name == "jsa-livestock-warm":
            t.join(5)
    assert started == [1]
    monkeypatch.setattr(quotes, "_warm_at", quotes.time.time() - quotes.WARM_EVERY_SECONDS - 1)
    assert quotes.warm_livestock() is True           # the window has passed: warm again
