"""Async-friendly rate limiter utilities."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from time import monotonic
from typing import Deque, Dict, Optional


@dataclass(frozen=True)
class RateLimitConfig:
    limit: int
    window: timedelta


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: Optional[float]


class RateLimiter:
    """Sliding window rate limiter safe for asyncio usage."""

    def __init__(self, config: RateLimitConfig) -> None:
        self._config = config
        self._hits: Dict[int, Deque[float]] = {}
        self._lock = asyncio.Lock()

    async def hit(self, key: int, *, bypass: bool = False) -> RateLimitResult:
        if bypass:
            return RateLimitResult(True, None)

        now = monotonic()
        window_seconds = self._config.window.total_seconds()
        cutoff = now - window_seconds

        async with self._lock:
            queue = self._hits.setdefault(key, deque())
            while queue and queue[0] <= cutoff:
                queue.popleft()

            if len(queue) >= self._config.limit:
                oldest = queue[0]
                retry_after = max(0.0, window_seconds - (now - oldest))
                return RateLimitResult(False, retry_after)

            queue.append(now)

        return RateLimitResult(True, None)

    async def remaining(self, key: int) -> int:
        async with self._lock:
            queue = self._hits.get(key)
            if not queue:
                return self._config.limit
            return max(0, self._config.limit - len(queue))


__all__ = ["RateLimiter", "RateLimitConfig", "RateLimitResult"]