"""
Retry decorator with exponential backoff — for transient store failures only.

Used by the durable stores so a transient SQLite "database is locked" or a Postgres
connection blip doesn't fail the call. We only retry on the specific exception types
that indicate a transient problem; permanent errors (constraint violations, programming
bugs) bubble up immediately.

The retry is intentionally bounded (default max 3 attempts, max 1s total) — long
retries belong in a queue, not in the call path of a governed agent request.
"""

from __future__ import annotations

import functools
import logging
import random
import sqlite3
import time
from typing import Any, Callable, Iterable, Tuple, Type

logger = logging.getLogger("agentbridge.resilience")

# SQLite "database is locked" / "disk I/O error" (transient). NOT sqlite3.DatabaseError —
# that's the parent of IntegrityError/ProgrammingError, which are PERMANENT and must not retry.
_SQLITE_TRANSIENT = (sqlite3.OperationalError,)

# psycopg "OperationalError" — transient connection/lock issues. Imported lazily.
def _psycopg_transient() -> Tuple[Type[Exception], ...]:
    try:
        import psycopg
        return (psycopg.OperationalError,)
    except ImportError:  # pragma: no cover
        return ()


def retry_transient(
    max_attempts: int = 3,
    base_delay: float = 0.02,
    max_delay: float = 1.0,
    extra_exceptions: Iterable[Type[Exception]] = (),
) -> Callable:
    """Retry a function on transient store exceptions.

    Backoff: exponential with jitter, capped at `max_delay`. Default 3 attempts means
    a worst-case latency of ~0.06s + jitter — well under a normal network hop, so the
    governance plane stays sub-millisecond-ish even under contention.
    """
    transient: Tuple[Type[Exception], ...] = tuple(_SQLITE_TRANSIENT) + tuple(extra_exceptions)
    # Try to add psycopg transient errors if psycopg is installed.
    transient += _psycopg_transient()

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except transient as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    delay = delay * (0.5 + random.random() * 0.5)  # 50-100% jitter
                    logger.debug("transient %s in %s (attempt %d/%d); retrying in %.3fs",
                                 type(e).__name__, fn.__qualname__, attempt, max_attempts, delay)
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return deco
