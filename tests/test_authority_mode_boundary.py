"""A legacy ingress cannot quietly inherit tenant-mode configuration."""

import httpx
import pytest

from src.authority_mode import authority_mode
from src.config import ConfigError
from src.governance.gateway import GovernanceGateway
from src.serve.mcp_gateway import _approved_remote_target, build_server


def test_unknown_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "typo")
    with pytest.raises(ConfigError, match="unknown authority mode"):
        authority_mode()


def test_new_legacy_gateway_and_mcp_server_reject_multi_tenant(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    for action in (GovernanceGateway, build_server, lambda: _approved_remote_target("https://destination.example.org")):
        with pytest.raises(ConfigError, match="legacy entry point"):
            action()


@pytest.mark.asyncio
async def test_preexisting_legacy_gateway_cannot_route_after_mode_change(monkeypatch):
    monkeypatch.delenv("AGENTBRIDGE_AUTHORITY_MODE", raising=False)
    gateway = GovernanceGateway()
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    effects = []

    async def invoke(wire):
        effects.append(wire)

    with pytest.raises(ConfigError, match="legacy entry point"):
        await gateway.route_call(
            agent_id="worker",
            src_proto="mcp",
            dst_proto="mcp",
            src_wire={"method": "tools/call", "params": {"name": "read", "arguments": {}}},
            invoke=invoke,
        )
    assert effects == []


def test_legacy_policy_cannot_silently_authorize_multi_tenant(monkeypatch):
    policy = GovernanceGateway().policy
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    with pytest.raises(ConfigError, match="legacy entry point"):
        policy.authorize(agent_id="worker", capability="read")


@pytest.mark.asyncio
async def test_preexisting_legacy_http_refuses_mode_drift(monkeypatch):
    from src.api.control_plane import app

    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        response = await client.get("/control/identities", headers={"x-admin-key": "anything"})
    assert response.status_code == 503
