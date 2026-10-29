import time
from collections import defaultdict
from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.security import UserContext


class SlidingWindowRateLimiter:
    """Sliding-window in-memory rate limiter per authenticated user.

    Tracks request timestamps within a moving time window.
    Automatically purges expired timestamps on every check.
    Thread/coroutine safe for async request handlers.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # user_id -> list of float timestamps (time.time())
        self._history: dict[UUID, list[float]] = defaultdict(list)

    def is_allowed(self, user_id: UUID) -> tuple[bool, int]:
        """Checks if a request from user_id is permitted under the sliding window.

        Returns (is_allowed, retry_after_seconds).
        """
        now = time.time()
        window_start = now - self.window_seconds

        timestamps = self._history[user_id]
        # Retain only timestamps within the active sliding window
        valid_timestamps = [ts for ts in timestamps if ts > window_start]

        if len(valid_timestamps) >= self.max_requests:
            # Over limit: compute seconds until earliest record expires
            earliest = valid_timestamps[0]
            retry_after = max(1, int(earliest + self.window_seconds - now))
            self._history[user_id] = valid_timestamps
            return False, retry_after

        # Under limit: append current timestamp and accept
        valid_timestamps.append(now)
        self._history[user_id] = valid_timestamps
        return True, 0

    def reset(self) -> None:
        """Clears all rate limit history (useful in test teardown)."""
        self._history.clear()


# Pre-configured rate limiters conforming to API_SPEC.md §5:
# - POST /api/v1/meetings: 20 requests / hour (3600s)
# - POST /api/v1/meetings/{id}/confirm-upload: 20 requests / hour (3600s)
# - GET /api/v1/meetings/{id}/status: 300 requests / minute (60s)
# - General read endpoints: 120 requests / minute (60s)

create_meeting_limiter = SlidingWindowRateLimiter(max_requests=20, window_seconds=3600)
confirm_upload_limiter = SlidingWindowRateLimiter(max_requests=20, window_seconds=3600)
job_control_limiter = SlidingWindowRateLimiter(max_requests=30, window_seconds=60)
status_polling_limiter = SlidingWindowRateLimiter(max_requests=300, window_seconds=60)
general_read_limiter = SlidingWindowRateLimiter(max_requests=120, window_seconds=60)


def rate_limit(limiter: SlidingWindowRateLimiter) -> Callable[..., Any]:
    """FastAPI dependency factory enforcing rate limits on endpoints."""

    async def _dependency(
        current_user: Annotated[UserContext, Depends(get_current_user)],
    ) -> None:
        allowed, retry_after = limiter.is_allowed(current_user.user_id)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency
