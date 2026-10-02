"""Retry Google API requests on rate limits (429, or 403 with a rate-limit reason)."""

from __future__ import annotations

import time

SLEEP = time.sleep
MAX_TRIES = 7  # waits 2, 4, 8, 16, 32, 64 seconds


def _is_rate_limit(exc: Exception) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 429:
        return True
    if status == 403:
        reasons = {d.get("reason") for d in (getattr(exc, "error_details", None) or []) if isinstance(d, dict)}
        return bool(reasons & {"rateLimitExceeded", "userRateLimitExceeded"}) or "Quota exceeded" in str(exc)
    return False


def execute(request):
    for attempt in range(MAX_TRIES):
        try:
            return request.execute()
        except Exception as exc:
            if not _is_rate_limit(exc) or attempt == MAX_TRIES - 1:
                raise
            SLEEP(2 ** (attempt + 1))
