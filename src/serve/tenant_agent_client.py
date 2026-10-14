"""Tenant v2 signed HTTP client; no implicit replay, redirects or proxy trust."""

from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from urllib.parse import urlsplit

from ..governance.authority import _identifier, sign_tenant_request


class TenantAgentClient:
    def __init__(
        self,
        base_url,
        tenant_id,
        identity,
        *,
        delegation_id=None,
        timeout=30,
        allow_loopback_http=False,
        max_response_bytes=1048576,
    ):
        parsed = urlsplit(base_url)
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.scheme != "https"
            and not (
                allow_loopback_http and parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "::1", "localhost")
            )
        ):
            raise ValueError("HTTPS origin or explicitly opted-in loopback HTTP required")
        _identifier(tenant_id, "tenant_id")
        _identifier(identity.agent_id, "agent_id")
        if delegation_id is not None:
            _identifier(delegation_id, "delegation_id")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0.05 <= timeout <= 120
        ):
            raise ValueError("bounded client timeout required")
        if type(max_response_bytes) is not int or not 256 <= max_response_bytes <= 16777216:
            raise ValueError("bounded response capacity required")
        self.base_url, self.tenant_id, self.identity = base_url.rstrip("/"), tenant_id, identity
        self.delegation_id, self.timeout, self.max_response = delegation_id, timeout, max_response_bytes
        self._client = None

    async def __aenter__(self):
        import httpx

        if self._client is not None:
            raise RuntimeError("client context already open")
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout, follow_redirects=False, trust_env=False
        )
        return self

    async def __aexit__(self, *args):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, path, data):
        if self._client is None:
            raise RuntimeError("use TenantAgentClient as an async context manager")
        body = json.dumps(data, separators=(",", ":"), allow_nan=False).encode()
        if len(body) > 1048576:
            raise ValueError("request body capacity exceeded")
        nonce = f"{time.time()}:{uuid.uuid4().hex}"
        headers = {
            "content-type": "application/json",
            "x-tenant-id": self.tenant_id,
            "x-agent-id": self.identity.agent_id,
            "x-nonce": nonce,
            "x-signature": sign_tenant_request(
                self.identity, self.tenant_id, nonce, body, delegation_id=self.delegation_id
            ),
        }
        if self.delegation_id is not None:
            headers["x-delegation-id"] = self.delegation_id
        async with (
            asyncio.timeout(self.timeout),
            self._client.stream("POST", path, content=body, headers=headers) as response,
        ):
            response.raise_for_status()
            result = bytearray()
            async for chunk in response.aiter_bytes():
                if len(result) + len(chunk) > self.max_response:
                    raise ValueError("response body capacity exceeded")
                result.extend(chunk)
        return json.loads(result)

    async def route(self, src, dst, wire, *, operation_id, target_id=None):
        return await self._post(
            "/v2/route",
            {
                "request_scope": "route",
                "src": src,
                "dst": dst,
                "wire": wire,
                "operation_id": operation_id,
                "target_id": target_id,
            },
        )

    async def operation(self, operation_id):
        return await self._post(
            "/v2/operations/read", {"request_scope": "operation.read", "operation_id": operation_id}
        )

    async def task(self, task_id):
        return await self._post("/v2/tasks/read", {"request_scope": "task.read", "task_id": task_id})

    async def task_events(self, task_id, *, after_sequence=-1, limit=100):
        return await self._post(
            "/v2/tasks/events",
            {"request_scope": "task.events", "task_id": task_id, "after_sequence": after_sequence, "limit": limit},
        )
