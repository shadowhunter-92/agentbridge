"""Opt-in HTTP facade for enrolled tenant authority.

No global administrator key, implicit tenant assignment or caller-owned target
configuration is accepted. Generic production destination execution stays closed.
The supplied kernel is trusted operator configuration, never request data.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..governance.authority import AuthorityDenied
from ..governance.gateway import GovernanceError
from ..governance.operation_ledger import OperationConflict
from ..governance.rbac import AccessDenied
from ..governance.tenant_kernel import TenantKernel
from ..protocols.task_lifecycle import LifecycleRejected
from .trusted_targets import SecurityConfigurationError


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RouteBody(_Body):
    request_scope: Literal["route"]
    src: str = Field(min_length=1, max_length=32)
    dst: str = Field(min_length=1, max_length=32)
    wire: dict
    operation_id: str = Field(min_length=16, max_length=128)
    target_id: str | None = Field(default=None, min_length=1, max_length=128)


class OperationBody(_Body):
    request_scope: Literal["operation.read"]
    operation_id: str = Field(min_length=16, max_length=128)


class TaskBody(_Body):
    request_scope: Literal["task.read", "task.events"]
    task_id: str = Field(min_length=1, max_length=128)
    after_sequence: int = Field(default=-1, ge=-1, lt=2**63)
    limit: int = Field(default=100, ge=1, le=100)


class AgentBody(_Body):
    public_key_hex: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    capabilities: list[str] = Field(default_factory=list, max_length=128)
    targets: list[str] = Field(default_factory=list, max_length=128)


class BudgetBody(_Body):
    spend_limit: float = Field(ge=0, allow_inf_nan=False)
    rate_limit: int = Field(default=1000, ge=1, le=1000000)
    window_seconds: int = Field(default=3600, ge=1, le=31536000)


class QuotaBody(_Body):
    enabled: bool
    spend_limit: float = Field(default=1000.0, ge=0, allow_inf_nan=False)
    user_spend_limit: float = Field(default=100.0, ge=0, allow_inf_nan=False)
    rate_limit: int = Field(default=10000, ge=1, le=1000000)
    user_rate_limit: int = Field(default=1000, ge=1, le=1000000)
    window_seconds: int = Field(default=3600, ge=1, le=31536000)
    max_active: int = Field(default=128, ge=1, le=1000000)
    user_max_active: int = Field(default=32, ge=1, le=1000000)
    max_records: int = Field(default=100000, ge=1, le=10000000)


class TaskHistoryCapacityBody(_Body):
    max_tasks: int = Field(ge=1, le=1000000)


class TaskEventCapacityBody(_Body):
    max_event_bytes: int = Field(ge=4096, le=1073741824)


class ApprovalBody(_Body):
    granted: bool


class HoldBody(_Body):
    enabled: bool


class TenantBody(_Body):
    active: bool


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


async def _body(request, model, *, limit):
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise HTTPException(415, "application/json required")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415, "encoded request bodies prohibited")
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > limit:
                    raise HTTPException(413, "request body capacity exceeded")
                raw.extend(chunk)
    except TimeoutError as exc:
        raise HTTPException(408, "request body deadline exceeded") from exc
    try:
        data = json.loads(
            bytes(raw),
            object_pairs_hook=_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
        )
        return bytes(raw), model.model_validate(data)
    except (ValueError, UnicodeError, RecursionError, ValidationError) as exc:
        # Do not echo request bodies, credentials or validator input in errors.
        raise HTTPException(400, "invalid request body") from exc


def _header(request, name, *, required=True, limit=256):
    values = request.headers.getlist(name)
    if not values and not required:
        return None
    if len(values) != 1 or not values[0] or len(values[0]) > limit:
        raise HTTPException(401, "bounded unambiguous authentication headers required")
    return values[0]


def create_tenant_app(kernel: TenantKernel, *, max_body_bytes=1048576):
    if os.getenv("AGENTBRIDGE_AUTHORITY_MODE") != "multi_tenant":
        raise ValueError("explicit multi_tenant authority mode required")
    if not isinstance(kernel, TenantKernel) or type(max_body_bytes) is not int or not 256 <= max_body_bytes <= 1048576:
        raise ValueError("trusted tenant kernel and bounded body capacity required")
    app = FastAPI(title="AgentBridge tenant control plane", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def mode_boundary(request, call_next):
        if os.getenv("AGENTBRIDGE_AUTHORITY_MODE") != "multi_tenant":
            return JSONResponse({"detail": "authority mode changed; restart required"}, status_code=503)
        return await call_next(request)

    async def operator(request, *, platform=False):
        authorization = _header(request, "authorization", limit=16391)
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "operator bearer authentication required")
        issuer = _header(request, "x-issuer", limit=2048)
        tenant = _header(request, "x-tenant-id", required=False)
        if platform and tenant is not None:
            raise HTTPException(403, "explicit platform authentication required")
        principal = await asyncio.to_thread(
            kernel.directory.authenticate_operator, issuer, authorization[7:], tenant_id=tenant
        )
        if platform:
            if principal.kind != "platform_admin":
                raise AuthorityDenied("platform authority required")
            return principal
        # Platform scope is authenticated separately from its resource selector.
        resource = _header(request, "x-resource-tenant", required=False) if principal.kind == "platform_admin" else None
        return await asyncio.to_thread(kernel.session, principal, tenant_id=resource)

    async def agent(request, model):
        raw, value = await _body(request, model, limit=max_body_bytes)
        tenant = _header(request, "x-tenant-id")
        agent_id = _header(request, "x-agent-id")
        nonce = _header(request, "x-nonce")
        signature = _header(request, "x-signature", limit=128)
        delegation = _header(request, "x-delegation-id", required=False)
        principal = await asyncio.to_thread(
            kernel.directory.authenticate_agent, tenant, agent_id, nonce, raw, signature, delegation_id=delegation
        )
        return await asyncio.to_thread(kernel.session, principal), raw, value, nonce

    async def denied(request, exc):
        return JSONResponse({"detail": "resource or authority unavailable"}, status_code=403)

    for exception in (AuthorityDenied, AccessDenied, LifecycleRejected):
        app.add_exception_handler(exception, denied)

    @app.exception_handler(GovernanceError)
    async def governed_denial(request, exc):
        return JSONResponse({"detail": "governance denied", "approval_id": exc.approval_id}, status_code=403)

    @app.exception_handler(OperationConflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": "operation conflict; reconcile before retry"}, status_code=409)

    @app.exception_handler(SecurityConfigurationError)
    async def target_closed(request, exc):
        return JSONResponse({"detail": "target execution is not qualified"}, status_code=403)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": "invalid request"}, status_code=400)

    @app.exception_handler(TimeoutError)
    async def timeout(request, exc):
        return JSONResponse({"detail": "request deadline exceeded; inspect operation before retry"}, status_code=504)

    @app.get("/health")
    async def health():
        return {"status": "ok", "authority_mode": "multi_tenant"}

    @app.post("/v2/route")
    async def route(request: Request):
        session, raw, _, nonce = await agent(request, RouteBody)
        return await session.route(raw, nonce=nonce)

    @app.post("/v2/operations/read")
    async def operation(request: Request):
        session, _, value, _ = await agent(request, OperationBody)
        return await asyncio.to_thread(session.operation, session.principal.agent_id, value.operation_id)

    @app.post("/v2/tasks/read")
    async def task(request: Request):
        session, _, value, _ = await agent(request, TaskBody)
        if value.request_scope != "task.read":
            raise HTTPException(400, "request scope mismatch")
        return asdict(await asyncio.to_thread(session.task, value.task_id))

    @app.post("/v2/tasks/events")
    async def events(request: Request):
        session, _, value, _ = await agent(request, TaskBody)
        if value.request_scope != "task.events":
            raise HTTPException(400, "request scope mismatch")
        rows = await asyncio.to_thread(
            session.task_events, value.task_id, after_sequence=value.after_sequence, limit=value.limit
        )
        return [asdict(row) for row in rows]

    @app.get("/v2/operator/identities")
    async def identities(request: Request):
        return await asyncio.to_thread((await operator(request)).list_identities)

    @app.put("/v2/operator/identities/{agent_id}")
    async def enroll(agent_id: str, request: Request):
        session = await operator(request)
        _, value = await _body(request, AgentBody, limit=max_body_bytes)
        await asyncio.to_thread(session.enroll_agent, agent_id, **value.model_dump())
        return {"enrolled": True}

    @app.delete("/v2/operator/identities/{agent_id}")
    async def revoke(agent_id: str, request: Request):
        await asyncio.to_thread((await operator(request)).revoke_agent, agent_id)
        return {"revoked": True}

    @app.get("/v2/operator/budgets/{agent_id}")
    async def budget(agent_id: str, request: Request):
        return await asyncio.to_thread((await operator(request)).get_budget, agent_id)

    @app.put("/v2/operator/budgets/{agent_id}")
    async def set_budget(agent_id: str, request: Request):
        session = await operator(request)
        _, value = await _body(request, BudgetBody, limit=max_body_bytes)
        await asyncio.to_thread(session.set_budget, agent_id, **value.model_dump())
        return {"updated": True}

    @app.get("/v2/operator/quotas")
    async def quotas(request: Request):
        return await asyncio.to_thread((await operator(request)).get_quotas)

    @app.put("/v2/operator/quotas")
    async def set_quotas(request: Request):
        session = await operator(request)
        _, value = await _body(request, QuotaBody, limit=max_body_bytes)
        await asyncio.to_thread(session.set_quotas, **value.model_dump())
        return {"updated": True}

    @app.get("/v2/operator/task-history-capacity")
    async def task_history_capacity(request: Request):
        return await asyncio.to_thread((await operator(request)).task_history_capacity)

    @app.put("/v2/operator/task-history-capacity")
    async def set_task_history_capacity(request: Request):
        session = await operator(request)
        _, value = await _body(request, TaskHistoryCapacityBody, limit=max_body_bytes)
        await asyncio.to_thread(session.set_task_history_capacity, value.max_tasks)
        return {"updated": True}

    @app.get("/v2/operator/task-event-capacity")
    async def task_event_capacity(request: Request):
        return await asyncio.to_thread((await operator(request)).task_event_capacity)

    @app.put("/v2/operator/task-event-capacity")
    async def set_task_event_capacity(request: Request):
        session = await operator(request)
        _, value = await _body(request, TaskEventCapacityBody, limit=max_body_bytes)
        await asyncio.to_thread(session.set_task_event_capacity, value.max_event_bytes)
        return {"updated": True}

    @app.get("/v2/operator/approvals")
    async def approvals(request: Request):
        return await asyncio.to_thread((await operator(request)).pending_approvals)

    @app.post("/v2/operator/approvals/{request_id}")
    async def approve(request_id: str, request: Request):
        session = await operator(request)
        _, value = await _body(request, ApprovalBody, limit=max_body_bytes)
        return {"updated": await asyncio.to_thread(session.approve, request_id, granted=value.granted)}

    @app.get("/v2/operator/audit")
    async def audit(request: Request):
        return await asyncio.to_thread((await operator(request)).audit_records)

    @app.get("/v2/operator/audit/export")
    async def export(request: Request):
        return PlainTextResponse(
            await asyncio.to_thread((await operator(request)).export_audit), media_type="application/x-ndjson"
        )

    @app.put("/v2/operator/holds/{name}")
    async def hold(name: str, request: Request):
        session = await operator(request)
        _, value = await _body(request, HoldBody, limit=max_body_bytes)
        await asyncio.to_thread(session.set_legal_hold, name, value.enabled)
        return {"updated": True}

    @app.put("/v2/platform/tenants/{tenant_id}")
    async def tenant(tenant_id: str, request: Request):
        principal = await operator(request, platform=True)
        _, value = await _body(request, TenantBody, limit=max_body_bytes)
        await asyncio.to_thread(kernel.directory.set_tenant, principal, tenant_id, active=value.active)
        return {"updated": True}

    return app
