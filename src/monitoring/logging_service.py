"""
Monitoring and Logging Service
==============================

Comprehensive observability with structured logging, metrics, and tracing.

Author: MiniMax Agent
"""

import json
import time
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from collections import defaultdict
import asyncio

import redis.asyncio as redis


class LogLevel(str, Enum):
    """Log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    """Structured log entry."""
    timestamp: str
    level: str
    logger: str
    message: str
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    service: str = "agent-bridge"
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricPoint:
    """Metric data point."""
    name: str
    value: float
    timestamp: int  # Unix timestamp
    labels: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """
    Metrics collector with in-memory and Redis backends.
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._last_flush = time.time()

    async def increment(self, name: str, value: float = 1, labels: Dict = None):
        """Increment a counter."""
        self._counters[f"{name}:{json.dumps(labels or {}, sort_keys=True)}"] += value

        if self.redis_client:
            key = f"metrics:counter:{name}"
            if labels:
                for k, v in labels.items():
                    key += f":{k}={v}"
            await self.redis_client.incrbyfloat(key, value)
            await self.redis_client.expire(key, 86400)  # 24h TTL

    async def gauge(self, name: str, value: float, labels: Dict = None):
        """Set a gauge value."""
        self._gauges[f"{name}:{json.dumps(labels or {}, sort_keys=True)}"] = value

        if self.redis_client:
            key = f"metrics:gauge:{name}"
            if labels:
                for k, v in labels.items():
                    key += f":{k}={v}"
            await self.redis_client.set(key, str(value))
            await self.redis_client.expire(key, 3600)  # 1h TTL

    async def histogram(self, name: str, value: float, labels: Dict = None):
        """Record a histogram value."""
        label_key = json.dumps(labels or {}, sort_keys=True)
        self._histograms[f"{name}:{label_key}"].append(value)

        if self.redis_client:
            key = f"metrics:histogram:{name}"
            if labels:
                for k, v in labels.items():
                    key += f":{k}={v}"

            # Store as sorted set with timestamp as score
            now = time.time()
            await self.redis_client.zadd(key, {f"{now}:{value}": now})
            await self.redis_client.expire(key, 86400)

    async def timing(self, name: str, duration_ms: float, labels: Dict = None):
        """Record timing/duration."""
        await self.histogram(f"{name}_duration_ms", duration_ms, labels)

    def get_stats(self) -> Dict[str, Any]:
        """Get current metrics stats."""
        stats = {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {}
        }

        for key, values in self._histograms.items():
            if values:
                sorted_values = sorted(values)
                stats["histograms"][key] = {
                    "count": len(values),
                    "sum": sum(values),
                    "min": min(values),
                    "max": max(values),
                    "avg": sum(values) / len(values),
                    "p50": sorted_values[len(sorted_values) // 2],
                    "p95": sorted_values[int(len(sorted_values) * 0.95)] if len(sorted_values) > 1 else sorted_values[0],
                    "p99": sorted_values[int(len(sorted_values) * 0.99)] if len(sorted_values) > 1 else sorted_values[0]
                }

        return stats


class TracingService:
    """
    Distributed tracing service.
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self._active_spans: Dict[str, Dict] = {}

    def start_span(self, name: str, trace_id: Optional[str] = None,
                   parent_span_id: Optional[str] = None) -> Dict:
        """Start a new trace span."""
        span_id = uuid.uuid4().hex[:16]
        trace_id = trace_id or uuid.uuid4().hex

        span = {
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": name,
            "start_time": time.time(),
            "end_time": None,
            "duration_ms": None,
            "status": "started"
        }

        self._active_spans[span_id] = span

        if self.redis_client:
            self.redis_client.hset(
                f"trace:{trace_id}",
                span_id,
                json.dumps(span)
            )

        return span

    def end_span(self, span: Dict, status: str = "ok", error: str = None):
        """End a span."""
        span["end_time"] = time.time()
        span["duration_ms"] = (span["end_time"] - span["start_time"]) * 1000
        span["status"] = status

        if error:
            span["error"] = error

        span_id = span["span_id"]
        if span_id in self._active_spans:
            del self._active_spans[span_id]

        if self.redis_client:
            self.redis_client.hset(
                f"trace:{span['trace_id']}",
                span_id,
                json.dumps(span)
            )

        return span


class LoggingService:
    """
    Structured logging service.
    """

    def __init__(self, metrics: MetricsCollector, redis_client: Optional[redis.Redis] = None):
        self.metrics = metrics
        self.redis_client = redis_client
        self.log_buffer: List[LogEntry] = []
        self.max_buffer_size = 100
        self.flush_interval = 5  # seconds

    async def log(self, level: LogLevel, logger_name: str, message: str,
                  trace_id: Optional[str] = None, duration_ms: Optional[float] = None,
                  **metadata):
        """Log a structured entry."""
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=level.value,
            logger=logger_name,
            message=message,
            trace_id=trace_id,
            duration_ms=duration_ms,
            metadata=metadata
        )

        # Console output (structured JSON for log aggregation)
        log_line = json.dumps(asdict(entry), ensure_ascii=False)
        print(log_line, flush=True)

        # Buffer for Redis storage
        self.log_buffer.append(entry)

        # Flush buffer if needed
        if len(self.log_buffer) >= self.max_buffer_size:
            await self._flush_buffer()

        # Update metrics
        if level in [LogLevel.ERROR, LogLevel.CRITICAL]:
            await self.metrics.increment("logs_error_total", labels={"logger": logger_name})
        else:
            await self.metrics.increment("logs_total", labels={"logger": logger_name, "level": level.value})

    async def debug(self, logger: str, message: str, **kwargs):
        await self.log(LogLevel.DEBUG, logger, message, **kwargs)

    async def info(self, logger: str, message: str, **kwargs):
        await self.log(LogLevel.INFO, logger, message, **kwargs)

    async def warning(self, logger: str, message: str, **kwargs):
        await self.log(LogLevel.WARNING, logger, message, **kwargs)

    async def error(self, logger: str, message: str, **kwargs):
        await self.log(LogLevel.ERROR, logger, message, **kwargs)

    async def critical(self, logger: str, message: str, **kwargs):
        await self.log(LogLevel.CRITICAL, logger, message, **kwargs)

    async def _flush_buffer(self):
        """Flush log buffer to Redis."""
        if not self.redis_client or not self.log_buffer:
            return

        pipe = self.redis_client.pipeline()
        for entry in self.log_buffer:
            key = f"logs:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            pipe.rpush(key, json.dumps(asdict(entry)))
        pipe.expire(key, 604800)  # 7 days TTL

        await pipe.execute()
        self.log_buffer.clear()

    async def flush(self):
        """Force flush buffer."""
        await self._flush_buffer()


class HealthCheckService:
    """
    Health check service with dependency monitoring.
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self._checks: Dict[str, Dict] = {}

    async def register_check(self, name: str, check_fn, critical: bool = True):
        """Register a health check."""
        self._checks[name] = {
            "fn": check_fn,
            "critical": critical,
            "last_check": None,
            "last_status": None,
            "last_error": None
        }

    async def run_checks(self) -> Dict[str, Any]:
        """Run all health checks."""
        results = {
            "healthy": True,
            "checks": {},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        for name, check in self._checks.items():
            try:
                start = time.time()
                status = await check["fn"]()
                duration = (time.time() - start) * 1000

                results["checks"][name] = {
                    "status": "healthy" if status else "unhealthy",
                    "duration_ms": round(duration, 2),
                    "critical": check["critical"]
                }

                if not status and check["critical"]:
                    results["healthy"] = False

                check["last_check"] = datetime.now(timezone.utc).isoformat()
                check["last_status"] = status

            except Exception as e:
                results["checks"][name] = {
                    "status": "error",
                    "error": str(e),
                    "critical": check["critical"]
                }
                if check["critical"]:
                    results["healthy"] = False

                check["last_error"] = str(e)

        return results


# Singleton instances
_metrics: Optional[MetricsCollector] = None
_logging: Optional[LoggingService] = None
_tracing: Optional[TracingService] = None
_health: Optional[HealthCheckService] = None


async def initialize_monitoring(redis_client: Optional[redis.Redis] = None):
    """Initialize monitoring services."""
    global _metrics, _logging, _tracing, _health

    _metrics = MetricsCollector(redis_client)
    _logging = LoggingService(_metrics, redis_client)
    _tracing = TracingService(redis_client)
    _health = HealthCheckService(redis_client)

    # Register default health checks
    if redis_client:
        async def redis_check():
            try:
                await redis_client.ping()
                return True
            except:
                return False

        await _health.register_check("redis", redis_check, critical=False)

    return _metrics, _logging, _tracing, _health


def get_metrics() -> MetricsCollector:
    return _metrics


def get_logging() -> LoggingService:
    return _logging


def get_tracing() -> TracingService:
    return _tracing


def get_health() -> HealthCheckService:
    return _health