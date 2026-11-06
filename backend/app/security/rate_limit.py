"""Small dependency-free sliding-window limiter for the EC2 API process.

This protects the application even when it is reached without an edge proxy.
The limiter is deliberately bounded so attacker-controlled keys cannot grow
process memory without limit.  A shared edge/Redis limiter remains appropriate
when the service is scaled to multiple workers or hosts.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from fastapi import Request

from app.security.tokens import TokenError, decode_access_token


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class SlidingWindowRateLimiter:
    """Concurrency-safe per-process sliding-window request limiter."""

    def __init__(self, *, window_seconds: float = 60.0, max_keys: int = 10_000) -> None:
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._buckets: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def check(
        self,
        scope: str,
        key: str,
        limit: int,
        *,
        now: float | None = None,
    ) -> RateLimitDecision:
        if limit < 1:
            raise ValueError("rate limit must be at least one request")

        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - self.window_seconds
        bucket_key = (scope, key)

        async with self._lock:
            bucket = self._buckets.setdefault(bucket_key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, math.ceil(bucket[0] + self.window_seconds - timestamp))
                self._buckets.move_to_end(bucket_key)
                return RateLimitDecision(False, limit, 0, retry_after)

            bucket.append(timestamp)
            self._buckets.move_to_end(bucket_key)
            self._evict_excess(cutoff)
            return RateLimitDecision(True, limit, limit - len(bucket), 0)

    def _evict_excess(self, cutoff: float) -> None:
        """Drop idle/old keys before enforcing the hard memory bound."""
        while self._buckets:
            first_key = next(iter(self._buckets))
            first_bucket = self._buckets[first_key]
            while first_bucket and first_bucket[0] <= cutoff:
                first_bucket.popleft()
            if first_bucket or len(self._buckets) <= self.max_keys:
                break
            self._buckets.popitem(last=False)

        while len(self._buckets) > self.max_keys:
            self._buckets.popitem(last=False)

    async def reset(self) -> None:
        """Clear all buckets (used by isolated tests and graceful reconfiguration)."""
        async with self._lock:
            self._buckets.clear()


def request_identity(request: Request) -> str:
    """Return a privacy-preserving rate-limit key.

    Valid access tokens are keyed by subject, while invalid/missing tokens use
    the ASGI peer address. This prevents callers from bypassing limits by
    inventing arbitrary bearer strings. Forwarded headers are intentionally
    ignored because trusting them requires explicit proxy setup.
    """
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        try:
            payload = decode_access_token(token)
            subject = payload.get("sub")
            if isinstance(subject, str) and subject:
                digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
                return f"principal:{digest}"
        except TokenError:
            pass
    return request_peer_identity(request)


def request_peer_identity(request: Request) -> str:
    """Return the direct ASGI peer key, ignoring caller-supplied auth headers."""
    host = request.client.host if request.client else "unknown"
    return f"peer:{host}"
