"""Actual HTTP authority, request-domain and namespace boundary regressions."""

import json
import time
import uuid

import httpx
import pytest

from src.api.tenant_control_plane import create_tenant_app
from src.governance.authority import sign_tenant_request
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def signed(app, tenant="alpha", *, data=None, raw=None, delegation=None):
    raw = (
        raw
        if raw is not None
        else json.dumps(
            data
            or {
                "request_scope": "route",
                "src": "mcp",
                "dst": "mcp",
                "operation_id": "network-operation-123456",
                "wire": {"method": "tools/call", "params": {"name": "read", "arguments": {}}},
            }
        ).encode()
    )
    nonce = f"{time.time()}:{uuid.uuid4().hex}"
    return raw, {
        "content-type": "application/json",
        "x-tenant-id": tenant,
        "x-agent-id": "worker",
        "x-nonce": nonce,
        "x-signature": sign_tenant_request(app[2][tenant], tenant, nonce, raw, delegation_id=delegation),
        **({"x-delegation-id": delegation} if delegation else {}),
    }


def operator(app, tenant="alpha", subject="administrator"):
    return {"x-issuer": ISSUER, "x-tenant-id": tenant, "authorization": "Bearer " + app[3](subject, tenant=tenant)}


@pytest.fixture
def http_app(tenant_app, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    return create_tenant_app(tenant_app[0])


@pytest.mark.asyncio
async def test_signed_route_and_operation_read_isolated_on_real_network(tenant_app, http_app, loopback_server):
    with loopback_server(lambda _: http_app) as (url, _):
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            raw, headers = signed(tenant_app)
            result = await client.post("/v2/route", content=raw, headers=headers)
            assert result.status_code == 200, result.text
            assert (await client.post("/v2/route", content=raw, headers=headers)).status_code == 403
            read = {"request_scope": "operation.read", "operation_id": "network-operation-123456"}
            raw, headers = signed(tenant_app, data=read)
            assert (await client.post("/v2/operations/read", content=raw, headers=headers)).json()[
                "state"
            ] == "succeeded"
            raw, headers = signed(tenant_app, "beta", data=read)
            assert (await client.post("/v2/operations/read", content=raw, headers=headers)).status_code == 403
            assert tenant_app[1]["beta"].get_budget("worker")["spent"] == 0


@pytest.mark.asyncio
async def test_http_operator_membership_scope_and_no_admin_key_fallback(tenant_app, http_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http_app), base_url="http://local") as client:
        assert (await client.get("/v2/operator/identities", headers={"x-admin-key": "legacy"})).status_code == 401
        headers = operator(tenant_app)
        headers["x-tenant-id"] = "beta"
        assert (await client.get("/v2/operator/identities", headers=headers)).status_code == 403
        a = (await client.get("/v2/operator/identities", headers=operator(tenant_app))).json()
        b = (await client.get("/v2/operator/identities", headers=operator(tenant_app, "beta"))).json()
        assert a != b
        assert (
            await client.put("/v2/platform/tenants/evil", headers=operator(tenant_app), json={"active": True})
        ).status_code == 403
        exported = await client.get("/v2/operator/audit/export", headers=operator(tenant_app))
        assert exported.status_code == 200
        assert all(
            json.loads(json.loads(row)["actor"].split("principal:v1:")[1])["resource_tenant_id"] == "alpha"
            for row in exported.text.splitlines()
        )


@pytest.mark.asyncio
async def test_wrong_signature_scope_unknown_fields_and_duplicate_members_have_no_effect(tenant_app, http_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http_app), base_url="http://local") as client:
        raw, headers = signed(tenant_app)
        headers["x-tenant-id"] = "beta"
        assert (await client.post("/v2/route", content=raw, headers=headers)).status_code == 403
        data = json.loads(raw)
        for change in (
            {"target": {"url": "https://evil.example.org"}},
            {"tenant_id": "beta"},
            {"principal": "owner"},
            {"request_scope": "operation.read"},
            {"cost": 0},
        ):
            payload, proof = signed(tenant_app, data={**data, **change})
            assert (await client.post("/v2/route", content=payload, headers=proof)).status_code == 400
        duplicate = raw[:-1] + b',"src":"a2a"}'
        payload, proof = signed(tenant_app, raw=duplicate)
        assert (await client.post("/v2/route", content=payload, headers=proof)).status_code == 400
        assert tenant_app[1]["alpha"].get_budget("worker")["spent"] == 0


@pytest.mark.asyncio
async def test_revoked_authority_and_viewer_write_denied(tenant_app, http_app):
    directory, owner = tenant_app[4:]
    directory.enroll_member(owner, "alpha", ISSUER, "viewer", role="tenant_viewer")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http_app), base_url="http://local") as client:
        response = await client.put(
            "/v2/operator/budgets/worker", headers=operator(tenant_app, subject="viewer"), json={"spend_limit": 1.0}
        )
        assert response.status_code == 403
        raw, proof = signed(tenant_app)
        directory.revoke_agent(owner, "alpha", "worker")
        assert (await client.post("/v2/route", content=raw, headers=proof)).status_code == 403


@pytest.mark.asyncio
async def test_platform_has_explicit_resource_selector_and_audit_binding(tenant_app, http_app):
    headers = {"authorization": "Bearer " + tenant_app[3]("owner"), "x-issuer": ISSUER}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http_app), base_url="http://local") as client:
        assert (await client.get("/v2/operator/identities", headers=headers)).status_code == 400
        headers["x-resource-tenant"] = "beta"
        response = await client.put("/v2/operator/budgets/worker", headers=headers, json={"spend_limit": 15.0})
        assert response.status_code == 200
        rows = (await client.get("/v2/operator/audit", headers=headers)).json()
        last = json.loads(rows[-1]["actor"].removeprefix("principal:v1:"))
        assert last["tenant_id"] is None and last["resource_tenant_id"] == "beta"
        assert tenant_app[1]["alpha"].get_budget("worker")["spend_limit"] == 10


@pytest.mark.asyncio
async def test_bounded_body_duplicate_headers_and_mode_drift(tenant_app, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    app = create_tenant_app(tenant_app[0], max_body_bytes=256)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        raw, proof = signed(tenant_app, raw=b" " * 257)
        assert (await client.post("/v2/route", content=raw, headers=proof)).status_code == 413
        raw, proof = signed(tenant_app)
        duplicate = list(proof.items()) + [("x-tenant-id", "beta")]
        assert (await client.post("/v2/route", content=raw, headers=duplicate)).status_code == 401
        monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "legacy_single_tenant")
        assert (await client.get("/health")).status_code == 503


def test_http_factory_requires_explicit_mode(tenant_app, monkeypatch):
    monkeypatch.delenv("AGENTBRIDGE_AUTHORITY_MODE", raising=False)
    with pytest.raises(ValueError, match="explicit multi_tenant"):
        create_tenant_app(tenant_app[0])
