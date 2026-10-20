"""Deterministic recovery and exponential backoff retry engine for API and daemon resilience."""

import logging
import random
from typing import Optional, Set

logger = logging.getLogger("cf-tunnel-sync")

RETRYABLE_STATUS_CODES: Set[int] = {429, 500, 502, 503, 504}


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    with_jitter: bool = True,
) -> float:
    """Calculate exponential backoff delay with optional random jitter.

    attempt: 1-indexed attempt number (1, 2, 3...)
    """
    attempt = max(1, attempt)
    raw_delay = base_delay * (2 ** (attempt - 1))
    clamped = min(max_delay, raw_delay)
    if with_jitter:
        # Add up to 25% uniform jitter to avoid thundering herds
        jitter_amount = random.uniform(0.0, clamped * 0.25)
        return clamped + jitter_amount
    return clamped


def parse_retry_after(
    header_val: Optional[str],
    default_delay: float = 1.0,
    max_delay: float = 60.0,
) -> float:
    """Parse HTTP Retry-After header (in seconds) and clamp to safe boundaries."""
    if not header_val:
        return default_delay
    try:
        val = float(str(header_val).strip())
        return max(0.1, min(max_delay, val))
    except (ValueError, TypeError):
        return default_delay


class RetryPolicy:
    """Configurable retry policy for remote Cloudflare API calls."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
        retryable_statuses: Optional[Set[int]] = None,
    ):
        self.max_retries = max(0, max_retries)
        self.base_delay = max(0.01, base_delay)
        self.max_delay = max_delay
        self.retryable_statuses = retryable_statuses or RETRYABLE_STATUS_CODES

    def is_retryable(self, status_code: int) -> bool:
        """Return True if the HTTP status code qualifies for automated retry."""
        return status_code in self.retryable_statuses

    def get_delay(self, attempt: int, retry_after: Optional[str] = None) -> float:
        """Determine delay before the next retry, respecting Retry-After if provided."""
        if retry_after:
            return parse_retry_after(retry_after, default_delay=self.base_delay, max_delay=self.max_delay)
        return calculate_backoff_delay(attempt, base_delay=self.base_delay, max_delay=self.max_delay)
