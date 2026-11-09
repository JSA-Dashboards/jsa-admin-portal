"""Audit log for every external API call (Massive futures snapshot, CME Greeks fetch) —
EXTERNAL_FETCH_LOG. Failures are logged too, so a string of bad live-price fetches is
visible without digging through server logs."""
import logging
from typing import Optional

from . import snowflake_client as sf

log = logging.getLogger(__name__)


def log_fetch(
    provider: str,
    endpoint: str,
    success: bool,
    http_status: Optional[int] = None,
    retry_count: int = 0,
    error_message: Optional[str] = None,
    requested_by: Optional[str] = None,
) -> None:
    # Best effort: the log must never break the fetch it describes. A read-only Snowflake login (the admin
    # portal's client app runs as one) cannot write it, and the user still needs their prices.
    try:
        sf.execute(
            """
            INSERT INTO EXTERNAL_FETCH_LOG
                (PROVIDER, ENDPOINT, SUCCESS, HTTP_STATUS, RETRY_COUNT, ERROR_MESSAGE, REQUESTED_BY)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (provider, endpoint, success, http_status, retry_count, error_message, requested_by),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not write the fetch log: %s", exc)
