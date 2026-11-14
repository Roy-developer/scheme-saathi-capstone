"""Small in-memory rate limits for the household memory routes.

The return code is the only secret protecting a saved household profile, so
the routes that take one are limited per client: a general request limit, and
a stricter limit on unknown-code lookups that stops anyone scanning for codes.

Limits are per API process. The client key is the connecting address, so
behind a proxy that does not forward client addresses all clients share one
budget (which errs on the side of blocking, not of allowing).
"""

import os
import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """Allow at most ``limit`` events per key in any ``window_seconds``."""

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        events = self._events.setdefault(key, deque())
        while events and now - events[0] >= self.window_seconds:
            events.popleft()
        return events

    def blocked(self, key: str) -> bool:
        """Whether ``key`` has used up its budget, without recording an event."""

        with self._lock:
            return len(self._recent(key, self._clock())) >= self.limit

    def hit(self, key: str) -> bool:
        """Record one event for ``key``; return False if it is over the limit."""

        with self._lock:
            now = self._clock()
            events = self._recent(key, now)
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True

    def retry_after(self, key: str) -> int:
        """Seconds until ``key`` may try again (at least 1)."""

        with self._lock:
            now = self._clock()
            events = self._recent(key, now)
            if not events:
                return 1
            return max(1, int(self.window_seconds - (now - events[0])) + 1)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


# Any household request: 30 per client per minute.
household_requests = SlidingWindowLimiter(
    _env_int("SCHEME_SAATHI_HOUSEHOLD_RATE_LIMIT", 30), 60,
)
# Unknown or refused return codes: 10 per client per 15 minutes.
household_failures = SlidingWindowLimiter(
    _env_int("SCHEME_SAATHI_HOUSEHOLD_FAILURE_LIMIT", 10), 15 * 60,
)


def reset_household_limits() -> None:
    household_requests.reset()
    household_failures.reset()
