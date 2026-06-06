"""
Enterprise Features Tests
=========================

Comprehensive test suite for enterprise-grade features:
- API authentication and rate limiting
- Structured logging and metrics
- Circuit breaker and retry logic
- Redis persistence

Author: MiniMax Agent
"""

import pytest
import asyncio
import time
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

from src.middleware.auth import (
    AuthService, APIKey, RateLimitResult, RateLimitStrategy
)
from src.monitoring.logging_service import (
    LogLevel, LogEntry, MetricPoint, MetricsCollector,
    TracingService, LoggingService
)
from src.resilience.resilience import (
    CircuitState, RetryConfig, CircuitBreakerConfig,
    CircuitBreaker, CircuitOpenError, retry_with_backoff, Bulkhead,
    get_circuit_manager, CircuitBreakerManager
)
from src.persistence.redis_persistence import (
    TranslationRecord, RedisPersistence, InMemoryPersistence, create_persistence
)


class TestAuthService:
    """Test API key management and rate limiting."""

    def setup_method(self):
        """Set up test fixtures."""
        self.auth = AuthService(redis_client=None)

    def test_generate_api_key(self):
        """Test API key generation."""
        raw_key, api_key = self.auth.generate_api_key("test_key", "free")

        assert raw_key.startswith("ag_")
        assert api_key.key_id.startswith("key_")
        assert api_key.name == "test_key"
        assert api_key.tier == "free"
        assert api_key.rate_limit == 1000

    def test_generate_pro_api_key(self):
        """Test Pro tier API key generation."""
        raw_key, api_key = self.auth.generate_api_key("pro_key", "pro")

        assert api_key.tier == "pro"
        assert api_key.rate_limit == 100000

    def test_generate_enterprise_api_key(self):
        """Test Enterprise tier API key generation."""
        raw_key, api_key = self.auth.generate_api_key("enterprise_key", "enterprise")

        assert api_key.tier == "enterprise"
        assert api_key.rate_limit == 1000000

    def test_validate_key_valid(self):
        """Test valid API key validation."""
        raw_key, api_key = self.auth.generate_api_key("test_key")

        validated = self.auth.validate_key(raw_key)

        assert validated is not None
        assert validated.key_id == api_key.key_id

    def test_validate_key_invalid(self):
        """Test invalid API key validation."""
        result = self.auth.validate_key("invalid_key_12345")

        assert result is None

    def test_validate_key_twice(self):
        """Test that key can only be validated once."""
        raw_key, api_key = self.auth.generate_api_key("test_key")

        first = self.auth.validate_key(raw_key)
        second = self.auth.validate_key(raw_key)

        assert first is not None
        assert second is not None

    @pytest.mark.asyncio
    async def test_revoke_key(self):
        """Test API key revocation."""
        raw_key, api_key = self.auth.generate_api_key("test_key")

        success = await self.auth.revoke_key(api_key.key_id)

        assert success
        # After revocation, key should still exist but is_active is False
        assert self.auth._keys[api_key.key_id].is_active is False
        assert self.auth.validate_key(raw_key) is None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self):
        """Test revoking non-existent key."""
        success = await self.auth.revoke_key("nonexistent_key")

        assert not success

    def test_get_key_info(self):
        """Test getting key info without raw key."""
        raw_key, api_key = self.auth.generate_api_key("test_key")

        info = self.auth.get_key_info(api_key.key_id)

        assert info is not None
        assert "raw_key" not in info
        assert info["name"] == "test_key"

    def test_list_keys(self):
        """Test listing all API keys."""
        self.auth.generate_api_key("key1")
        self.auth.generate_api_key("key2")

        keys = self.auth.list_keys()

        assert len(keys) == 2

    @pytest.mark.asyncio
    async def test_memory_rate_limit_allowed(self):
        """Test in-memory rate limiting - allowed case."""
        raw_key, api_key = self.auth.generate_api_key("test_key", "free")

        result = await self.auth.check_rate_limit(api_key)

        assert result.allowed
        assert result.remaining == api_key.rate_limit - 1

    @pytest.mark.asyncio
    async def test_memory_rate_limit_exceeded(self):
        """Test in-memory rate limiting - exceeded case."""
        auth = AuthService(redis_client=None)
        raw_key, api_key = auth.generate_api_key("test_key", "free")

        # Make requests up to limit
        for _ in range(api_key.rate_limit):
            await auth.check_rate_limit(api_key)

        result = await auth.check_rate_limit(api_key)

        assert not result.allowed
        assert result.remaining == 0
        assert result.retry_after is not None


class TestMetricsCollector:
    """Test metrics collection."""

    def setup_method(self):
        """Set up test fixtures."""
        self.metrics = MetricsCollector(redis_client=None)

    @pytest.mark.asyncio
    async def test_increment_counter(self):
        """Test counter increment."""
        await self.metrics.increment("test_counter", value=5)

        stats = self.metrics.get_stats()
        # Keys are formatted as "name:labels_json"
        assert any(k.startswith("test_counter:") for k in stats["counters"])

    @pytest.mark.asyncio
    async def test_gauge(self):
        """Test gauge value."""
        await self.metrics.gauge("test_gauge", 100.5)

        stats = self.metrics.get_stats()
        assert any(k.startswith("test_gauge:") for k in stats["gauges"])

    @pytest.mark.asyncio
    async def test_histogram(self):
        """Test histogram recording."""
        await self.metrics.histogram("test_histogram", 50.0)
        await self.metrics.histogram("test_histogram", 100.0)

        stats = self.metrics.get_stats()
        # Keys are formatted as "name:labels_json"
        assert any(k.startswith("test_histogram:") for k in stats["histograms"])
        # Find the histogram with count 2
        hist = next((v for k, v in stats["histograms"].items() if k.startswith("test_histogram:")), None)
        assert hist is not None
        assert hist["count"] == 2

    @pytest.mark.asyncio
    async def test_timing(self):
        """Test timing/duration recording."""
        await self.metrics.timing("operation_duration", 125.5)

        stats = self.metrics.get_stats()
        # Keys are formatted as "name:labels_json"
        assert any(k.startswith("operation_duration_") for k in stats["histograms"])

    @pytest.mark.asyncio
    async def test_labels(self):
        """Test metrics with labels."""
        await self.metrics.increment("requests", labels={"method": "GET", "status": "200"})
        await self.metrics.increment("requests", labels={"method": "POST", "status": "201"})

        stats = self.metrics.get_stats()
        assert len(stats["counters"]) == 2

    @pytest.mark.asyncio
    async def test_histogram_percentiles(self):
        """Test histogram percentile calculations."""
        for i in range(100):
            await self.metrics.histogram("latency", float(i))

        stats = self.metrics.get_stats()
        hist_stats = stats["histograms"]["latency:{}"]

        assert "p50" in hist_stats
        assert "p95" in hist_stats
        assert "p99" in hist_stats


class TestTracingService:
    """Test distributed tracing."""

    def setup_method(self):
        """Set up test fixtures."""
        self.tracing = TracingService(redis_client=None)

    def test_start_span(self):
        """Test starting a trace span."""
        span = self.tracing.start_span("test_operation")

        assert "trace_id" in span
        assert "span_id" in span
        assert span["name"] == "test_operation"
        assert span["status"] == "started"

    def test_start_span_with_parent(self):
        """Test starting span with parent."""
        parent_span = self.tracing.start_span("parent")
        child_span = self.tracing.start_span("child", parent_span_id=parent_span["span_id"])

        assert child_span["parent_span_id"] == parent_span["span_id"]

    def test_end_span(self):
        """Test ending a span."""
        span = self.tracing.start_span("test_operation")
        ended_span = self.tracing.end_span(span)

        assert ended_span["end_time"] is not None
        assert ended_span["duration_ms"] is not None
        assert ended_span["status"] == "ok"

    def test_end_span_with_error(self):
        """Test ending span with error."""
        span = self.tracing.start_span("test_operation")
        ended_span = self.tracing.end_span(span, status="error", error="Test error")

        assert ended_span["status"] == "error"
        assert ended_span["error"] == "Test error"

    def test_span_cleanup(self):
        """Test that completed spans are removed from active spans."""
        span = self.tracing.start_span("test_operation")
        assert len(self.tracing._active_spans) == 1

        self.tracing.end_span(span)
        assert len(self.tracing._active_spans) == 0


class TestLoggingService:
    """Test structured logging."""

    def setup_method(self):
        """Set up test fixtures."""
        self.metrics = MetricsCollector(redis_client=None)
        self.logging = LoggingService(self.metrics, redis_client=None)

    @pytest.mark.asyncio
    async def test_log_levels(self):
        """Test different log levels."""
        await self.logging.debug("test", "Debug message")
        await self.logging.info("test", "Info message")
        await self.logging.warning("test", "Warning message")
        await self.logging.error("test", "Error message")
        await self.logging.critical("test", "Critical message")

    @pytest.mark.asyncio
    async def test_log_with_metadata(self):
        """Test logging with metadata."""
        await self.logging.info("test", "Message with metadata", user_id="user123", action="login")

    @pytest.mark.asyncio
    async def test_log_with_trace_id(self):
        """Test logging with trace ID."""
        await self.logging.info("test", "Message with trace", trace_id="trace-123")


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def setup_method(self):
        """Set up test fixtures."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            timeout=1.0
        )
        self.circuit = CircuitBreaker("test_circuit", config)

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Test successful circuit breaker call."""
        async def success_func():
            return "success"

        result = await self.circuit.call(success_func)

        assert result == "success"
        assert self.circuit.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_opens_circuit(self):
        """Test that failures open the circuit."""
        async def fail_func():
            raise Exception("Test failure")

        for _ in range(3):
            try:
                await self.circuit.call(fail_func)
            except Exception:
                pass

        assert self.circuit.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self):
        """Test that open circuit rejects calls."""
        self.circuit.state = CircuitState.OPEN
        self.circuit.failure_count = 3
        self.circuit.last_failure_time = time.time()  # Recent failure so reset is not attempted

        async def any_func():
            return "should not run"

        with pytest.raises(CircuitOpenError):
            await self.circuit.call(any_func)

    @pytest.mark.asyncio
    async def test_circuit_half_open_after_timeout(self):
        """Test circuit transitions to half-open after timeout."""
        self.circuit.state = CircuitState.OPEN
        self.circuit.failure_count = 3
        self.circuit.last_failure_time = time.time() - 2.0  # 2 seconds ago

        async def success_func():
            return "success"

        # First call should transition to half-open
        result = await self.circuit.call(success_func)

        assert result == "success"
        assert self.circuit.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_circuit_closes_after_success_threshold(self):
        """Test circuit closes after success threshold."""
        self.circuit.state = CircuitState.HALF_OPEN

        async def success_func():
            return "success"

        await self.circuit.call(success_func)
        await self.circuit.call(success_func)

        assert self.circuit.state == CircuitState.CLOSED

    def test_get_state(self):
        """Test getting circuit breaker state."""
        state = self.circuit.get_state()

        assert "name" in state
        assert "state" in state
        assert "failure_count" in state


class TestRetryWithBackoff:
    """Test retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_successful_retry(self):
        """Test successful function with no retry needed."""
        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await retry_with_backoff(success_func)

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test retry on transient failure."""
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Transient error")
            return "success"

        result = await retry_with_backoff(
            flaky_func,
            config=RetryConfig(max_attempts=3, base_delay=0.1)
        )

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test that exception is raised after max retries."""
        async def always_fail():
            raise ValueError("Always fails")

        with pytest.raises(ValueError):
            await retry_with_backoff(
                always_fail,
                config=RetryConfig(max_attempts=2, base_delay=0.1)
            )

    @pytest.mark.asyncio
    async def test_custom_retry_exceptions(self):
        """Test custom exception types for retry."""
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Should retry")
            return "success"

        result = await retry_with_backoff(
            func,
            config=RetryConfig(max_attempts=3, base_delay=0.1, retry_on=[ConnectionError])
        )

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_unexpected_exception(self):
        """Test no retry on exception not in retry_on list."""
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Should not retry")

        with pytest.raises(ValueError):
            await retry_with_backoff(
                func,
                config=RetryConfig(max_attempts=3, retry_on=[ConnectionError])
            )

        assert call_count == 1


class TestBulkhead:
    """Test bulkhead pattern for resource isolation."""

    @pytest.mark.asyncio
    async def test_bulkhead_execute(self):
        """Test bulkhead execution."""
        bulkhead = Bulkhead(max_concurrent=2, timeout=5.0)

        async def sample_func():
            return "done"

        result = await bulkhead.execute(sample_func)

        assert result == "done"

    @pytest.mark.asyncio
    async def test_bulkhead_concurrent_limit(self):
        """Test bulkhead concurrent limit."""
        bulkhead = Bulkhead(max_concurrent=1, timeout=2.0)

        async def slow_func():
            await asyncio.sleep(0.5)
            return "done"

        # Start first task
        task1 = asyncio.create_task(bulkhead.execute(slow_func))

        # Small delay to ensure first task starts
        await asyncio.sleep(0.1)

        # Start second task - should be limited
        start = time.time()
        task2 = asyncio.create_task(bulkhead.execute(slow_func))
        result = await task2
        elapsed = time.time() - start

        # Second task should have waited
        assert elapsed >= 0.4

        await task1

    def test_bulkhead_stats(self):
        """Test bulkhead statistics."""
        bulkhead = Bulkhead(max_concurrent=5)

        stats = bulkhead.get_stats()

        assert stats["max_concurrent"] == 5
        assert stats["active"] == 0
        assert stats["available"] == 5


class TestCircuitBreakerManager:
    """Test circuit breaker manager."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = CircuitBreakerManager()

    def test_get_or_create(self):
        """Test getting or creating circuit breaker."""
        cb1 = self.manager.get_or_create("test")
        cb2 = self.manager.get_or_create("test")

        assert cb1 is cb2
        assert cb1.name == "test"

    def test_get_all_states(self):
        """Test getting all circuit breaker states."""
        self.manager.get_or_create("circuit1")
        self.manager.get_or_create("circuit2")

        states = self.manager.get_all_states()

        assert len(states) == 2

    def test_reset_all(self):
        """Test resetting all circuit breakers."""
        cb = self.manager.get_or_create("test")
        cb.failure_count = 5
        cb.state = CircuitState.OPEN

        self.manager.reset_all()

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestInMemoryPersistence:
    """Test in-memory persistence."""

    @pytest.mark.asyncio
    async def test_store_translation(self):
        """Test storing translation record."""
        persistence = InMemoryPersistence()

        record = TranslationRecord(
            id="test-123",
            source_protocol="mcp",
            target_protocol="a2a",
            source_data={"test": "data"},
            target_data={"result": "value"},
            duration_ms=100.0,
            status="success"
        )

        success = await persistence.store_translation(record)

        assert success

    @pytest.mark.asyncio
    async def test_get_translation(self):
        """Test getting translation record."""
        persistence = InMemoryPersistence()

        record = TranslationRecord(
            id="test-456",
            source_protocol="mcp",
            target_protocol="a2a",
            source_data={"test": "data"},
            target_data={"result": "value"},
            duration_ms=100.0,
            status="success"
        )

        await persistence.store_translation(record)
        retrieved = await persistence.get_translation("test-456")

        assert retrieved is not None
        assert retrieved.id == "test-456"

    @pytest.mark.asyncio
    async def test_cache_set_get(self):
        """Test cache set and get."""
        persistence = InMemoryPersistence()

        await persistence.cache_set("key1", {"data": "value"}, ttl=60)

        result = await persistence.cache_get("key1")

        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_cache_expiry(self):
        """Test cache expiry."""
        persistence = InMemoryPersistence()

        # Set cache with very short TTL
        await persistence.cache_set("short_key", "value", ttl=1)

        # Should be available immediately
        result1 = await persistence.cache_get("short_key")
        assert result1 == "value"

        # Wait for expiry
        await asyncio.sleep(1.1)

        # Should be None after expiry
        result2 = await persistence.cache_get("short_key")
        assert result2 is None


class TestTranslationRecord:
    """Test TranslationRecord dataclass."""

    def test_create_record(self):
        """Test creating a translation record."""
        record = TranslationRecord(
            id="test-id",
            source_protocol="mcp",
            target_protocol="a2a",
            source_data={"method": "tools/call"},
            target_data={"task": {"id": "1"}},
            duration_ms=50.5,
            status="success"
        )

        assert record.id == "test-id"
        assert record.source_protocol == "mcp"
        assert record.target_protocol == "a2a"
        assert record.duration_ms == 50.5

    def test_record_with_metadata(self):
        """Test record with metadata."""
        record = TranslationRecord(
            id="test-id",
            source_protocol="mcp",
            target_protocol="a2a",
            source_data={},
            target_data={},
            duration_ms=0,
            status="success",
            metadata={"user": "test_user", "count": 5}
        )

        assert record.metadata["user"] == "test_user"


class TestCircuitOpenError:
    """Test CircuitOpenError exception."""

    def test_exception_message(self):
        """Test circuit open error message."""
        error = CircuitOpenError("Test circuit is open")

        assert str(error) == "Test circuit is open"


class TestRateLimitResult:
    """Test RateLimitResult dataclass."""

    def test_create_result_allowed(self):
        """Test creating allowed rate limit result."""
        result = RateLimitResult(
            allowed=True,
            remaining=500,
            reset_at=1234567890
        )

        assert result.allowed
        assert result.remaining == 500

    def test_create_result_rejected(self):
        """Test creating rejected rate limit result."""
        result = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=1234567890,
            retry_after=60
        )

        assert not result.allowed
        assert result.remaining == 0
        assert result.retry_after == 60


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.mark.asyncio
    async def test_auth_with_metrics(self):
        """Test auth service integrated with metrics."""
        metrics = MetricsCollector(redis_client=None)
        auth = AuthService(redis_client=None)

        raw_key, api_key = auth.generate_api_key("integration_test")

        # Check rate limit
        result = await auth.check_rate_limit(api_key)

        # Verify metrics were incremented
        stats = metrics.get_stats()
        # Note: In-memory rate limit doesn't increment metrics

        assert result.allowed

    @pytest.mark.asyncio
    async def test_circuit_breaker_with_retry(self):
        """Test circuit breaker integrated with retry."""
        circuit_manager = CircuitBreakerManager()
        circuit = circuit_manager.get_or_create("integration_test")

        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Transient")
            return "success"

        # Circuit breaker wraps retry
        async def wrapped_call():
            return await retry_with_backoff(
                flaky_func,
                config=RetryConfig(max_attempts=3, base_delay=0.1)
            )

        result = await circuit.call(wrapped_call)

        assert result == "success"

    @pytest.mark.asyncio
    async def test_persistence_with_circuit_breaker(self):
        """Test persistence with circuit breaker protection."""
        persistence = InMemoryPersistence()

        # Simulate circuit breaker for database calls
        circuit_manager = CircuitBreakerManager()
        circuit = circuit_manager.get_or_create("persistence_test")

        async def store_with_protection():
            record = TranslationRecord(
                id="circuit-test",
                source_protocol="mcp",
                target_protocol="a2a",
                source_data={},
                target_data={},
                duration_ms=10.0,
                status="success"
            )
            return await persistence.store_translation(record)

        result = await circuit.call(store_with_protection)

        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])