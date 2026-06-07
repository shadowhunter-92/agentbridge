"""
A tiny in-memory, per-key fixed-window rate limiter.

Used by the control plane to throttle requests to /control/* per client IP — in
particular this blunts brute-forcing the admin key. Thread-safe; no external
dependency. For multi-instance deployments, swap the in-memory dict for a shared
store (Redis) — the interface (`allow(key)`) stays the same.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Tuple


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max = max_requests
        self.window = window_seconds
        self._hits: Dict[str, Tuple[float, int]] = {}  # key -> (window_start, count)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record a hit for `key`; return False once it exceeds max within the window."""
        now = time.time()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            count += 1
            self._hits[key] = (start, count)
            return count <= self.max

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
