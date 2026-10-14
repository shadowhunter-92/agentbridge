"""
Structured logging for AgentBridge.

- JSON to stdout when AGENTBRIDGE_LOG_JSON=1 (production default).
- Plain text otherwise (dev default).
- Correlation ID per request (read from X-Request-ID header or generated).
- `bind_request_id` stores the id in a ContextVar so log records pick it up automatically.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Any, Dict

# Per-request correlation id. Set by the FastAPI middleware; surfaced by the log formatter.
_request_id: ContextVar[str] = ContextVar("agentbridge_request_id", default="-")


def bind_request_id(rid: str) -> None:
    _request_id.set(rid)


def current_request_id() -> str:
    return _request_id.get()


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class JsonFormatter(logging.Formatter):
    """One JSON object per log line. Stable fields so log shippers can index them."""

    _RESERVED = {"name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                 "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                 "created", "msecs", "relativeCreated", "thread", "threadName",
                 "processName", "process", "message", "taskName"}

    def format(self, record: logging.LogRecord) -> str:
        # ISO-8601 with milliseconds. We can't rely on strftime %f being available
        # cross-platform, so format the milliseconds explicitly.
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(ts.microsecond / 1000):03d}Z"
        payload: Dict[str, Any] = {
            "ts": ts_str,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": _request_id.get(),
        }
        # Attach any extra attributes the caller passed via `extra=`.
        for k, v in record.__dict__.items():
            if k not in self._RESERVED and not k.startswith("_"):
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


class PlainFormatter(logging.Formatter):
    DEFAULT = "%(asctime)s %(levelname)-7s [%(name)s] req=%(request_id)s %(message)s"

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = _request_id.get()  # type: ignore[attr-defined]
        return super().format(record)


def configure_logging(level: str | None = None) -> None:
    """Configure root logging. Idempotent — safe to call multiple times."""
    level = level or os.getenv("AGENTBRIDGE_LOG_LEVEL", "INFO").upper()
    use_json = os.getenv("AGENTBRIDGE_LOG_JSON", "1" if _is_prod() else "0") in ("1", "true", "yes")

    root = logging.getLogger()
    # Don't double-add handlers on re-init.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(PlainFormatter())
    root.addHandler(handler)

    # Library noise reduction
    for noisy in ("uvicorn.access", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(os.getenv("AGENTBRIDGE_LOG_LIBS", "WARNING").upper())


def _is_prod() -> bool:
    env = os.getenv("AGENTBRIDGE_ENV", "").lower()
    return env in ("prod", "production") or os.getenv("KUBERNETES_SERVICE_HOST") is not None
