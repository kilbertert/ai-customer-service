"""M12 PR-8 — In-memory per-workspace rate limiter.

Per plan §3 PR-8b: 5-line in-memory dict limiter, no slowapi dependency.

Design:
  - Keyed on (workspace_id, route_name) tuple
  - Sliding window of last N timestamps; reject if >= limit in last 60s
  - Process-local only (single-instance deploys). For multi-instance use Redis
    INCR + EXPIRE (out of PR-8 scope).

API:
    limiter = RateLimiter(limit=10, window_seconds=60)
    if not limiter.allow(workspace_id=123, route="regenerate_workflow"):
        raise HTTPException(429, ...)
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque


class RateLimiter:
    """Simple sliding-window in-memory rate limiter."""

    def __init__(self, limit: int = 10, window_seconds: int = 60) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be >= 1")
        self.limit = limit
        self.window_seconds = window_seconds
        self._buckets: dict[tuple[int, str], Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, *, workspace_id: int, route: str) -> bool:
        """Record an attempt; return True if within limit, False if exceeded."""
        key = (workspace_id, route)
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def reset(self, *, workspace_id: int | None = None, route: str | None = None) -> None:
        """Test helper: clear buckets."""
        with self._lock:
            if workspace_id is None and route is None:
                self._buckets.clear()
            else:
                keys_to_drop = [
                    k for k in self._buckets
                    if (workspace_id is None or k[0] == workspace_id)
                    and (route is None or k[1] == route)
                ]
                for k in keys_to_drop:
                    del self._buckets[k]


# Module-level shared instances — wired into endpoints below.
_preview_limiter = RateLimiter(limit=10, window_seconds=60)
_regenerate_limiter = RateLimiter(limit=10, window_seconds=60)


def check_preview_limit(workspace_id: int) -> bool:
    """Rate-limit gate for ``POST /workflows/preview`` (10/min/workspace)."""
    return _preview_limiter.allow(workspace_id=workspace_id, route="workflows_preview")


def check_regenerate_limit(workspace_id: int) -> bool:
    """Rate-limit gate for ``POST /agents/{id}/regenerate-workflow`` (10/min/workspace)."""
    return _regenerate_limiter.allow(workspace_id=workspace_id, route="regenerate_workflow")


def reset_all_limits() -> None:
    """Test helper."""
    _preview_limiter.reset()
    _regenerate_limiter.reset()


__all__ = [
    "RateLimiter",
    "check_preview_limit",
    "check_regenerate_limit",
    "reset_all_limits",
]