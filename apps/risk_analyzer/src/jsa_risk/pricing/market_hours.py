"""Is a commodity's futures market open right now? Decides which Massive price the "Update
prices" button should pull: the last trade while the market is open (overnight or day
session), the exchange's settlement price once it is closed.

Times are US Central (the exchange's clock), taken from each CommoditySpec. Weekends and CME
holidays are closed. The overnight session starts the previous evening (Sun-Thu) and belongs
to the next trading day, so Friday evening and Saturday are closed and Sunday evening opens.
"""
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .commodities import CommoditySpec
from .symbols import _is_business_day

CENTRAL = ZoneInfo("America/Chicago")


def now_central() -> datetime:
    return datetime.now(CENTRAL)


def market_is_open(commodity: CommoditySpec, now: Optional[datetime] = None) -> bool:
    now = now.astimezone(CENTRAL) if now is not None and now.tzinfo else (now or now_central())
    t, today = now.time(), now.date()

    day_open, day_close = commodity.day_session
    if _is_business_day(today) and day_open <= t < day_close:
        return True

    if commodity.overnight_session is None:
        return False
    eve_open, morning_close = commodity.overnight_session
    if t < morning_close:                           # the small hours of a trading day
        return _is_business_day(today)
    if t >= eve_open:                               # the evening before one
        return _is_business_day(today + timedelta(days=1))
    return False
