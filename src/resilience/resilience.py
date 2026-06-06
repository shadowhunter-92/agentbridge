"""
Resilience: Retry Logic and Circuit Breaker
============================================

Enterprise-grade resilience patterns for reliable operations.

Author: MiniMax Agent
"""

import asyncio
import inspect
import time
from typing import Callable, TypeVar, Optional, List, Any, Dict
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps

import redis.asyncio as redis

from ..monitoring.logging_service import get_logging, get_metrics


async def _call(func: Callable, *args, **kwargs) -> Any:
    """Invoke a callable that may be either synchronous or asynchronous."""
    result = func(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class RetryConfig:
    """Retry configuration."""
    max_attempts: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on: List[Exception] = field(default_factory=lambda: [Exception])


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5  # failures before opening
    success_threshold: int = 2  # successes to close
    timeout: float = 60.0  # seconds before trying half-open
    half_open_max_calls: int = 3


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker."""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
            else:
                raise CircuitOpenError(f"Circuit {self.name} is OPEN")

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls >= self.config.half_open_max_calls:
                raise CircuitOpenError(f"Circuit {self.name} is HALF-OPEN, max calls reached")

            self.half_open_calls += 1

        try:
            result = await _call(func, *args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure(e)
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if not self.last_failure_time:
            return True
        return time.time() - self.last_failure_time >= self.config.timeout

    async def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0

        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.success_count = 0
                logging = get_logging()
                if logging:
                    await logging.info(
                        "circuit_breaker",
                        f"Circuit {self.name} CLOSED"
                    )

    async def _on_failure(self, error: Exception):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.success_count = 0

        metrics = get_metrics()
        if metrics:
            await metrics.increment("circuit_breaker_failures", labels={"circuit": self.name})

        logging = get_logging()
        if logging:
            await logging.warning(
                "circuit_breaker",
                f"Circuit {self.name} failure: {error}",
                failure_count=self.failure_count
            )

        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            if logging:
                await logging.error(
                    "circuit_breaker",
                    f"Circuit {self.name} OPENED after {self.failure_count} failures"
                )

    def get_state(self) -> Dict:
        """Get circuit breaker state."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time
        }


class CircuitOpenError(Exception):
    """Raised when circuit is open."""
    pass


async def retry_with_backoff(
    func: Callable,
    config: Optional[RetryConfig] = None,
    *args,
    **kwargs
) -> Any:
    """
    Retry function with exponential backoff.

    Args:
        func: Async function to retry
        config: Retry configuration
        *args, **kwargs: Arguments to pass to function

    Returns:
        Function result

    Raises:
        Last exception if all retries exhausted
    """
    config = config or RetryConfig()
    last_error = None

    for attempt in range(config.max_attempts):
        try:
            result = await _call(func, *args, **kwargs)

            if attempt > 0:
                metrics = get_metrics()
                if metrics:
                    await metrics.increment("retry_success", labels={"attempt": str(attempt + 1)})

            return result

        except Exception as e:
            last_error = e

            # Check if we should retry this exception
            should_retry = any(isinstance(e, exc_type) for exc_type in config.retry_on)

            if not should_retry or attempt >= config.max_attempts - 1:
                raise

            # Calculate delay
            delay = min(
                config.base_delay * (config.exponential_base ** attempt),
                config.max_delay
            )

            # Add jitter
            if config.jitter:
                import random
                delay = delay * (0.5 + random.random())

            logging = get_logging()
            if logging:
                await logging.warning(
                    "retry",
                    f"Retry attempt {attempt + 1}/{config.max_attempts} after {delay:.2f}s: {e}"
                )

            await asyncio.sleep(delay)

            metrics = get_metrics()
            if metrics:
                await metrics.increment("retry_attempt", labels={"attempt": str(attempt + 1)})

    raise last_error


def circuit_breaker_protect(circuit: CircuitBreaker):
    """
    Decorator to protect function with circuit breaker.

    Usage:
        @circuit_breaker_protect(my_circuit)
        async def my_function():
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await circuit.call(func, *args, **kwargs)
        return wrapper
    return decorator


class CircuitBreakerManager:
    """Manages multiple circuit breakers."""

    def __init__(self):
        self._circuits: Dict[str, CircuitBreaker] = {}

    def get_or_create(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
        """Get existing or create new circuit breaker."""
        if name not in self._circuits:
            self._circuits[name] = CircuitBreaker(name, config)
        return self._circuits[name]

    def get_all_states(self) -> List[Dict]:
        """Get state of all circuit breakers."""
        return [cb.get_state() for cb in self._circuits.values()]

    def reset_all(self):
        """Reset all circuit breakers to closed state."""
        for cb in self._circuits.values():
            cb.state = CircuitState.CLOSED
            cb.failure_count = 0
            cb.success_count = 0


# Global circuit breaker manager
_circuit_manager: Optional[CircuitBreakerManager] = None


def get_circuit_manager() -> CircuitBreakerManager:
    global _circuit_manager
    if not _circuit_manager:
        _circuit_manager = CircuitBreakerManager()
    return _circuit_manager


# Bulkhead pattern for resource isolation
class Bulkhead:
    """
    Semaphore-based bulkhead for limiting concurrent calls.
    """

    def __init__(self, max_concurrent: int, timeout: float = 30.0):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._active = 0

    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with bulkhead limit."""
        async with self.semaphore:
            self._active += 1
            try:
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.timeout
                )
                return result
            finally:
                self._active -= 1

    def get_stats(self) -> Dict:
        """Get bulkhead stats."""
        return {
            "max_concurrent": self.max_concurrent,
            "active": self._active,
            "available": self.max_concurrent - self._active
        }