"""Opt-in A2A 0.3 status-only HTTP/SSE projection of admitted durable tasks.

Trusted workers own task creation/transitions. This service never dispatches,
retries, cancels an external effect or settles a reservation. Limits are per
application process, not fleet-wide tenant quotas. HTTP requires TLS outside
explicit loopback evaluation.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import math
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from src.api.auth_oidc import OidcError, OidcVerifier
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
from src.protocols.task_lifecycle import LifecycleRejected, TaskState


@dataclass(frozen=True)
class StreamLimits:
    max_body_bytes: int = 16384
    page_size: int = 16
    max_streams: int = 64
    max_streams_per_owner: int = 4
    max_seconds: float = 60
    request_seconds: float = 5
    poll_seconds: float = 0.1
    heartbeat_seconds: float = 5

    def __post_init__(self):
        for value, minimum, maximum in (
            (self.max_body_bytes, 256, 1048576), (self.page_size, 1, 100),
            (self.max_streams, 1, 10000), (self.max_streams_per_owner, 1, 10000),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("invalid bounded stream capacity")
        for value, minimum, maximum in (
            (self.max_seconds, .05, 3600), (self.poll_seconds, .01, 2),
            (self.heartbeat_seconds, .01, 30), (self.request_seconds, .01, 30),
        ):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or \
                    not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError("invalid bounded stream timing")


class _Streams:
    def __init__(self, limits):
        self.limits, self.total, self.owners = limits, 0, {}
        self.lock = threading.Lock()

    def acquire(self, owner):
        with self.lock:
            count = self.owners.get(owner, 0)
            if self.total >= self.limits.max_streams or count >= self.limits.max_streams_per_owner:
                return None
            self.total += 1
            self.owners[owner] = count + 1
        released = False

        def release():
            nonlocal released
            with self.lock:
                if released:
                    return
                released = True
                self.total -= 1
                remaining = self.owners[owner] - 1
                if remaining:
                    self.owners[owner] = remaining
                else:
                    del self.owners[owner]
        return release


class _BoundedStreamingResponse(StreamingResponse):
    """Bound the whole ASGI send, including a reader stalled by backpressure."""

    def __init__(self, *args, max_seconds, release, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_seconds, self.release = max_seconds, release

    async def __call__(self, scope, receive, send):
        try:
            async with asyncio.timeout(self.max_seconds):
                await super().__call__(scope, receive, send)
        except TimeoutError:
            # Complete the HTTP stream when possible; never wait indefinitely for
            # a stalled peer. A timeout never writes a terminal task state.
            with suppress(Exception):
                await asyncio.wait_for(send({"type": "http.response.body", "body": b"",
                                             "more_body": False}), timeout=.1)
        finally:
            self.release()


def _reject_constant(_):
    raise ValueError("non-finite JSON constant")


def _accepts_stream(value):
    best, quality = -1, 0.0
    for item in value.split(","):
        media, *parameters = (piece.strip().lower() for piece in item.split(";"))
        specificity = {"*/*": 0, "text/*": 1, "text/event-stream": 2}.get(media, -1)
        if specificity < 0:
            continue
        try:
            weights = [p.split("=", 1)[1] for p in parameters if p.startswith("q=")]
            weight = float(weights[0]) if len(weights) == 1 else (1.0 if not weights else 0.0)
            if not math.isfinite(weight) or not 0 <= weight <= 1:
                weight = 0.0
        except ValueError:
            weight = 0.0
        if specificity > best:
            best, quality = specificity, weight
    return quality > 0


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message, *, status=200, headers=None):
    return JSONResponse({"jsonrpc": "2.0", "id": request_id,
                         "error": {"code": code, "message": message}},
                        status_code=status, headers=headers)


def _finished(task):
    return task.terminal or task.state in (TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED)


def _task(task):
    return {"kind": "task", "id": task.task_id, "contextId": task.context_id,
            "status": {"state": task.state.value},
            "metadata": {"agentbridge_sequence": task.sequence}}


def _update(task):
    return {"kind": "status-update", "taskId": task.task_id, "contextId": task.context_id,
            "status": {"state": task.state.value}, "final": _finished(task),
            "metadata": {"agentbridge_sequence": task.sequence}}


def _cursor_scope(owner, task_id):
    return hashlib.sha256(json.dumps([owner, task_id], separators=(",", ":")).encode()).hexdigest()


def _cursor(owner, task_id, sequence):
    return "ab:" + _cursor_scope(owner, task_id) + ":" + str(sequence)


def _parse_cursor(raw, owner, task_id):
    if raw is None:
        return -1
    if not isinstance(raw, str) or len(raw) > 90:
        raise ValueError("invalid replay cursor")
    prefix, scope, sequence = raw.split(":")
    if prefix != "ab" or scope != _cursor_scope(owner, task_id) or \
            not sequence.isascii() or not sequence.isdigit() or len(sequence) > 19:
        raise ValueError("invalid replay cursor")
    value = int(sequence)
    if value >= 2**63:
        raise ValueError("invalid replay cursor")
    return value


def create_a2a_status_app(tasks: DurableTaskLifecycle, verifier: OidcVerifier, *,
                          public_url: str, limits: StreamLimits | None = None,
                          allow_loopback_http: bool = False):
    """Project existing owner-scoped tasks; opt in with a configured OIDC verifier.

    A single issuer/audience maps its verified subject to the SDK owner_id.
    Embedders must admit/publish tasks under that subject through the trusted
    governance path. No custom identity header or wire metadata selects an owner.
    """
    if not isinstance(tasks, DurableTaskLifecycle) or not isinstance(verifier, OidcVerifier):
        raise ValueError("durable tasks and a configured OIDC verifier required")
    if not isinstance(verifier.config.issuer, str) or not verifier.config.issuer.startswith("https://") or not verifier.config.audience:
        raise ValueError("explicit trusted issuer and audience required")
    parsed = urlsplit(public_url)
    loopback = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or \
            parsed.path not in ("", "/") or not parsed.hostname or \
            (parsed.scheme != "https" and not (allow_loopback_http and loopback and parsed.scheme == "http")):
        raise ValueError("explicit HTTPS public origin or opted-in loopback HTTP required")
    try:
        version = importlib.metadata.version("a2a-sdk")
        if version.split(".")[:2] != ["0", "3"]:
            raise ValueError("this service requires the reviewed a2a-sdk 0.3 family")
        from a2a.types import CancelTaskRequest, GetTaskRequest, SendMessageRequest, TaskResubscriptionRequest
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError("install AgentBridge with its a2a extra") from exc
    models = {"tasks/get": GetTaskRequest, "tasks/cancel": CancelTaskRequest,
              "tasks/resubscribe": TaskResubscriptionRequest,
              "message/send": SendMessageRequest, "message/stream": SendMessageRequest}
    limits = limits or StreamLimits()
    if not isinstance(limits, StreamLimits):
        raise ValueError("validated stream limits required")
    streams = _Streams(limits)
    from ..authority_mode import require_legacy_authority
    require_legacy_authority()
    app = FastAPI(title="AgentBridge admitted-task status", docs_url=None, redoc_url=None)
    app.state.status_streams = streams

    async def owner_of(request):
        require_legacy_authority()
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise OidcError("Bearer authentication required")
        claims = await asyncio.to_thread(verifier.verify, header[7:].strip())
        owner = claims.get("sub")
        if not isinstance(owner, str) or not 1 <= len(owner) <= 128 or owner.strip() != owner:
            raise OidcError("bounded authenticated subject required")
        return owner

    @app.get("/.well-known/agent-card.json")
    async def card():
        return {"name": "AgentBridge task-status observer", "version": "0.1.0",
                "protocolVersion": "0.3.0", "url": public_url.rstrip("/") + "/a2a",
                "description": "Observe existing admitted tasks; no tool execution or remote cancellation.",
                "capabilities": {"streaming": True, "pushNotifications": False},
                "defaultInputModes": ["text/plain"], "defaultOutputModes": ["application/json"],
                "securitySchemes": {"oidc": {"type": "openIdConnect", "openIdConnectUrl":
                    verifier.config.issuer.rstrip("/") + "/.well-known/openid-configuration"}},
                "security": [{"oidc": []}],
                "skills": [{"id": "observe-admitted-task", "name": "Observe an admitted task",
                            "description": "Supply your existing taskId; replay cursor is an AgentBridge extension.",
                            "tags": ["status", "read-only"]}]}

    async def events(request, owner, task_id, request_id, cursor, release):
        deadline = time.monotonic() + limits.max_seconds
        heartbeat = time.monotonic()
        initial = True
        try:
            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    return
                try:
                    if await owner_of(request) != owner:
                        raise OidcError("authenticated owner changed")
                    page = await asyncio.to_thread(tasks.events, owner, task_id,
                                                   after_sequence=cursor, limit=limits.page_size)
                except OidcError:
                    yield "data: " + json.dumps({"jsonrpc": "2.0", "id": request_id,
                          "error": {"code": -32000, "message": "Stream authorization expired or revoked"}}) + "\n\n"
                    return
                except Exception:
                    yield "data: " + json.dumps({"jsonrpc": "2.0", "id": request_id,
                          "error": {"code": -32603, "message": "Task status unavailable"}}) + "\n\n"
                    return
                for task in page:
                    if await request.is_disconnected() or time.monotonic() >= deadline:
                        return
                    result = _task(task) if initial else _update(task)
                    initial = False
                    cursor = task.sequence
                    yield "id: " + _cursor(owner, task_id, cursor) + "\ndata: " + \
                          json.dumps(_result(request_id, result), separators=(",", ":")) + "\n\n"
                    if _finished(task):
                        return
                if time.monotonic() - heartbeat >= limits.heartbeat_seconds:
                    yield ": keep-alive\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(limits.poll_seconds)
            yield ": reconnect with the last consumed event id\n\n"
        finally:
            release()

    @app.post("/a2a")
    async def rpc(request: Request):
        try:
            owner = await owner_of(request)
        except OidcError:
            return _error(None, -32000, "Authentication required", status=401,
                          headers={"WWW-Authenticate": "Bearer"})
        if request.headers.get("a2a-version", "0.3.0") != "0.3.0":
            return _error(None, -32600, "This endpoint supports A2A 0.3.0", status=400)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return _error(None, -32600, "application/json required", status=415)
        body = bytearray()
        try:
            async with asyncio.timeout(limits.request_seconds):
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > limits.max_body_bytes:
                        return _error(None, -32600, "Request too large", status=413)
        except TimeoutError:
            return _error(None, -32600, "Request body deadline exceeded", status=408)
        try:
            raw = json.loads(body, parse_constant=_reject_constant)
        except (ValueError, UnicodeDecodeError):
            return _error(None, -32700, "Invalid JSON", status=400)
        if not isinstance(raw, dict) or set(raw) - {"jsonrpc", "id", "method", "params"} or \
                raw.get("jsonrpc") != "2.0" or type(raw.get("id")) not in (str, int):
            return _error(None, -32600, "Invalid JSON-RPC request", status=400)
        request_id, method = raw["id"], raw.get("method")
        if not isinstance(method, str) or method not in models:
            return _error(request_id, -32601, "Method not supported")
        try:
            validated = models[method].model_validate({**raw, "method": "message/send"}
                                                       if method == "message/stream" else raw)
            if method.startswith("message/"):
                message = validated.params.message
                if not message.task_id:
                    return _error(request_id, -32004, "Task creation requires trusted governed admission")
                if message.role.value != "user" or any(part.root.kind != "text" for part in message.parts):
                    return _error(request_id, -32005, "Only text status queries are supported")
                if validated.params.configuration is not None:
                    return _error(request_id, -32004, "Message configuration not supported by status observer")
                task_id = message.task_id
            else:
                task_id = validated.params.id
            current = await asyncio.to_thread(tasks.get, owner, task_id)
        except ValidationError:
            return _error(request_id, -32602, "Invalid method parameters")
        except LifecycleRejected:
            return _error(request_id, -32001, "Task not found")
        except Exception:
            return _error(request_id, -32603, "Task status unavailable", status=503)
        if method.startswith("message/") and message.context_id is not None and message.context_id != current.context_id:
            return _error(request_id, -32602, "Context does not match the owned task")
        if method == "tasks/cancel":
            return _error(request_id, -32002, "Status observer cannot cancel an external task")
        if method in ("tasks/get", "message/send"):
            return JSONResponse(_result(request_id, _task(current)))
        if not _accepts_stream(request.headers.get("accept", "*/*")):
            return _error(request_id, -32600, "text/event-stream must be accepted", status=406)
        try:
            cursor = _parse_cursor(request.headers.get("last-event-id"), owner, task_id)
            if cursor > current.sequence:
                raise ValueError("future cursor")
        except ValueError:
            return _error(request_id, -32602, "Invalid task replay cursor")
        if cursor == current.sequence and _finished(current):
            return _error(request_id, -32004, "This interaction has no subsequent events")
        release = streams.acquire(owner)
        if release is None:
            return _error(request_id, -32000, "Stream capacity reached", status=429,
                          headers={"Retry-After": "1"})
        return _BoundedStreamingResponse(events(request, owner, task_id, request_id, cursor, release),
                                 max_seconds=limits.max_seconds, release=release,
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                                 background=BackgroundTask(release))

    return app
