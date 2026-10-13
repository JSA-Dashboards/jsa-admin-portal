"""Audit log for every external API call (Massive futures snapshot, CME Greeks fetch) —
EXTERNAL_FETCH_LOG. Failures are logged too, so a string of bad live-price fetches is
visible without digging through server logs."""
from typing import Optional

from . import snowflake_client as sf


def log_fetch(
    provider: str,
    endpoint: str,
    success: bool,
    http_status: Optional[int] = None,
    retry_count: int = 0,
    error_message: Optional[str] = None,
    requested_by: Optional[str] = None,
) -> None:
    sf.execute(
        """
        INSERT INTO EXTERNAL_FETCH_LOG
            (PROVIDER, ENDPOINT, SUCCESS, HTTP_STATUS, RETRY_COUNT, ERROR_MESSAGE, REQUESTED_BY)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (provider, endpoint, success, http_status, retry_count, error_message, requested_by),
    )
