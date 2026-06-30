"""
Observability for AgentBridge — OpenTelemetry traces + Prometheus metrics.

Production-ready observability with graceful fallbacks:
  - OpenTelemetry tracing (optional). Set OTEL_EXPORTER_OTLP_ENDPOINT to ship spans.
  - Prometheus metrics at /metrics (Counter/Histogram/Gauge).
  - Lightweight, no-op safe when OTel is not installed.

Design choices:
  - Lazy initialization so unit tests and the in-process mesh aren't penalized.
  - All metrics are module-level singletons so they register exactly once with the
    default Prometheus registry (no duplicate-collector errors on reload).
  - Span creation is wrapped so that callers don't need to know whether OTel is active.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger("agentbridge.observability")

# --- OpenTelemetry (optional) ---------------------------------------------------------

_otel_initialized = False
_otel_tracer = None
_otel_init_lock = threading.Lock()


def _init_otel() -> None:
    """Initialize OpenTelemetry tracing exactly once.

    Enabled when `OTEL_EXPORTER_OTLP_ENDPOINT` (or `AGENTBRIDGE_OTEL_ENABLED=1`) is set.
    Uses the OTLP HTTP exporter by default; service.name from OTEL_SERVICE_NAME or
    `agentbridge`. Safe to call from any thread; safe to call when opentelemetry isn't
    installed (silent no-op).
    """
    global _otel_initialized, _otel_tracer
    if _otel_initialized:
        return
    with _otel_init_lock:
        if _otel_initialized:
            return
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        enabled = os.getenv("AGENTBRIDGE_OTEL_ENABLED", "").lower() in ("1", "true", "yes")
        if not (endpoint or enabled):
            _otel_initialized = True
            return
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            except ImportError:
                OTLPSpanExporter = None  # type: ignore[assignment]

            resource = Resource.create({
                "service.name": os.getenv("OTEL_SERVICE_NAME", "agentbridge"),
                "service.version": os.getenv("OTEL_SERVICE_VERSION", "1.0.0"),
            })
            provider = TracerProvider(resource=resource)
            if endpoint and OTLPSpanExporter is not None:
                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint + "/v1/traces"))
                )
            trace.set_tracer_provider(provider)
            _otel_tracer = trace.get_tracer("agentbridge")
            logger.info("OpenTelemetry tracing enabled (endpoint=%s)", endpoint or "noop")
        except ImportError:
            logger.info("OpenTelemetry SDK not installed; tracing disabled")
        except Exception as e:
            logger.warning("OpenTelemetry init failed: %s; tracing disabled", e)
        finally:
            _otel_initialized = True


@contextmanager
def span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Iterator[Any]:
    """Open a traced span if OTel is active; otherwise a no-op context manager.

    Use it everywhere we want to break down latency:
        with span("gateway.route_call", {"agent_id": agent_id, "src": src}):
            ...
    """
    _init_otel()
    if _otel_tracer is None:
        yield None
        return
    with _otel_tracer.start_as_current_span(name) as s:
        if attributes and s is not None:
            for k, v in attributes.items():
                try:
                    s.set_attribute(k, v)
                except Exception:
                    pass  # OTel is picky about value types; never fail the call
        yield s


# --- Prometheus metrics ---------------------------------------------------------------

try:
    from prometheus_client import (
        Counter, Histogram, Gauge, Info, CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest,
    )
    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover - prometheus_client is a hard dependency in pyproject
    _PROM_AVAILABLE = False
    logger.warning("prometheus_client not installed; /metrics will be unavailable")

_REGISTRY = CollectorRegistry() if _PROM_AVAILABLE else None

if _PROM_AVAILABLE:
    # NOTE: use a private registry so we never collide with other libs that auto-register
    # against the default. The /metrics endpoint serves from this registry only.
    _INFO = Info("agentbridge", "AgentBridge control-plane build info", registry=_REGISTRY)
    _INFO.info({"version": "1.0.0", "python": "3.11+"})

    CALLS_TOTAL = Counter(
        "agentbridge_calls_total",
        "Total governed calls routed through the gateway",
        ["src_protocol", "dst_protocol", "capability", "decision"],
        registry=_REGISTRY,
    )

    CALL_DURATION = Histogram(
        "agentbridge_call_duration_seconds",
        "End-to-end governed call duration in seconds",
        ["src_protocol", "dst_protocol"],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=_REGISTRY,
    )

    TRANSLATE_DURATION = Histogram(
        "agentbridge_translate_duration_seconds",
        "Pure canonical-translation duration in seconds",
        ["src_protocol", "dst_protocol"],
        buckets=(0.000005, 0.00001, 0.000025, 0.00005, 0.0001, 0.0005, 0.001),
        registry=_REGISTRY,
    )

    AUDIT_ENTRIES = Gauge(
        "agentbridge_audit_entries",
        "Current number of audit entries in the chain",
        registry=_REGISTRY,
    )

    BUDGET_SPENT = Gauge(
        "agentbridge_budget_spent",
        "Agent's spent budget",
        ["agent_id"],
        registry=_REGISTRY,
    )

    BUDGET_REMAINING = Gauge(
        "agentbridge_budget_remaining",
        "Agent's remaining budget (limit - spent - reserved)",
        ["agent_id"],
        registry=_REGISTRY,
    )

    APPROVALS_PENDING = Gauge(
        "agentbridge_approvals_pending",
        "Number of pending human-approval requests",
        registry=_REGISTRY,
    )

    HTTP_REQUESTS = Counter(
        "agentbridge_http_requests_total",
        "HTTP requests handled by the control plane",
        ["method", "path", "status"],
        registry=_REGISTRY,
    )

    HTTP_DURATION = Histogram(
        "agentbridge_http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "path"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
        registry=_REGISTRY,
    )

    RATE_LIMIT_HITS = Counter(
        "agentbridge_rate_limit_hits_total",
        "Requests rejected by the per-IP rate limiter",
        registry=_REGISTRY,
    )

    AUTH_FAILURES = Counter(
        "agentbridge_auth_failures_total",
        "Operator/agent authentication failures",
        ["kind"],  # operator | agent
        registry=_REGISTRY,
    )

else:
    # Stub objects so importers never crash when prometheus_client is absent.
    class _Stub:
        def labels(self, *a, **k):
            return self
        def inc(self, *a, **k):
            pass
        def observe(self, *a, **k):
            pass
        def set(self, *a, **k):
            pass
        def info(self, *a, **k):
            pass

    CALLS_TOTAL = TRANSLATE_DURATION = CALL_DURATION = _Stub()  # type: ignore[assignment]
    AUDIT_ENTRIES = BUDGET_SPENT = BUDGET_REMAINING = _Stub()   # type: ignore[assignment]
    APPROVALS_PENDING = HTTP_REQUESTS = HTTP_DURATION = _Stub() # type: ignore[assignment]
    RATE_LIMIT_HITS = AUTH_FAILURES = _Stub()                   # type: ignore[assignment]


def render_metrics() -> tuple[bytes, str]:
    """Return (body_bytes, content_type) for the /metrics endpoint."""
    if not _PROM_AVAILABLE:
        return b"# prometheus_client not installed\n", "text/plain; version=0.0.4"
    return generate_latest(_REGISTRY), CONTENT_TYPE_LATEST


def record_call(src: str, dst: str, capability: str, decision: str, duration_s: float) -> None:
    """Called by the governance gateway after each route_call attempt."""
    CALLS_TOTAL.labels(src_protocol=src, dst_protocol=dst,
                       capability=capability or "<none>", decision=decision).inc()
    CALL_DURATION.labels(src_protocol=src, dst_protocol=dst).observe(duration_s)


def record_translate(src: str, dst: str, duration_s: float) -> None:
    TRANSLATE_DURATION.labels(src_protocol=src, dst_protocol=dst).observe(duration_s)


def update_audit_count(n: int) -> None:
    AUDIT_ENTRIES.set(n)


def update_approvals_pending(n: int) -> None:
    APPROVALS_PENDING.set(n)


def update_budget_gauge(agent_id: str, spent: float, remaining: float) -> None:
    BUDGET_SPENT.labels(agent_id=agent_id).set(spent)
    BUDGET_REMAINING.labels(agent_id=agent_id).set(remaining)


class Stopwatch:
    """Tiny monotonic timer for code that needs duration without a span."""

    __slots__ = ("_t0",)

    def __init__(self) -> None:
        self._t0: float = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._t0
