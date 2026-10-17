"""Small, deterministic retry bounds shared by safe GETs and atomic replacements."""
from email.utils import parsedate_to_datetime
import math
import time

MAX_ATTEMPTS = 3
MAX_DELAY = 2.0


def retry_delay(failure_index, retry_after=None, now=None):
    """Exponential fallback or bounded Retry-After seconds/HTTP-date (never NaN)."""
    fallback = min(MAX_DELAY, 0.25 * (2 ** min(max(failure_index, 0), 3)))
    if retry_after is None:
        return fallback
    try:
        delay = float(retry_after)
    except (TypeError, ValueError, OverflowError):
        try:
            date = parsedate_to_datetime(str(retry_after))
            delay = date.timestamp() - (time.time() if now is None else now)
            delay = max(0.0, delay)
        except (TypeError, ValueError, OverflowError, OSError):
            return fallback
    if not math.isfinite(delay) or delay < 0:
        return fallback
    return min(MAX_DELAY, delay)


def retry_call(operation, retryable):
    """At most three attempts and two sleeps, only for explicitly safe errors."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return operation()
        except Exception as exc:
            if attempt == MAX_ATTEMPTS - 1 or not retryable(exc):
                raise
            time.sleep(retry_delay(attempt))
