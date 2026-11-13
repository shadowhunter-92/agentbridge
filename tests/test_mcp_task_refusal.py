"""MCP task augmentation cannot silently become a synchronous action."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.governance import (
    AgentIdentity, AuditLog, Budget, BudgetManager, GovernanceGateway,
    IdentityRegistry, sign_request,
)
from src.governance.durable_policy import DurableApprovalQueue
from src.protocols import default_registry
from src.protocols.mcp import McpAdapter
from src.proxy.inline_proxy import InlineProxy


TASK_VALUES = [
    pytest.param({"ttl": 60000}, id="ttl"),
    pytest.param({}, id="empty"),
    pytest.param(None, id="null"),
    pytest.param(False, id="false"),
    pytest.param(True, id="true"),
    pytest.param(0, id="zero"),
    pytest.param([], id="array"),
    pytest.param("deferred", id="string"),
]


def tool_call():
    return {"jsonrpc": "2.0", "id": "task-refusal", "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "synthetic read-only"}}}


def task_call(task):
    wire = tool_call()
    wire["params"]["task"] = task
    return wire


@pytest.mark.parametrize("task", TASK_VALUES)
def test_adapter_rejects_task_presence(task):
    with pytest.raises(ValueError, match="task"):
        McpAdapter().to_canonical_call(task_call(task))


@pytest.mark.parametrize("destination", default_registry.protocols())
@pytest.mark.parametrize("task", TASK_VALUES)
def test_registry_cannot_erase_task_semantics(task, destination):
    with pytest.raises(ValueError, match="task"):
        default_registry.translate_call(task_call(task), "mcp", destination)


@pytest.mark.parametrize("task", TASK_VALUES)
def test_inline_task_refusal_precedes_transport(task):
    with patch("src.proxy.transport.send_a2a_message", new_callable=AsyncMock,
               return_value={"texts": ["synthetic"], "raw": {}}) as invoke:
        with pytest.raises(ValueError, match="task"):
            asyncio.run(InlineProxy().mcp_request_to_a2a_agent(
                task_call(task), "https://example.invalid"))
        invoke.assert_not_awaited()


@pytest.mark.parametrize("task", TASK_VALUES)
async def test_library_task_refusal_precedes_budget_or_invocation(task, network_sql_stores):
    store = network_sql_stores()
    approvals = DurableApprovalQueue(store)
    approvals.mark_sensitive("echo")
    gateway = GovernanceGateway(identities=IdentityRegistry(store), budgets=BudgetManager(store),
                                approvals=approvals, audit=AuditLog(store))
    agent = AgentIdentity.generate("mcp-task-local")
    gateway.identities.register(agent)
    gateway.budgets.set_budget(agent.agent_id, Budget(spend_limit=10, rate_limit=100))
    before = gateway.budgets.get(agent.agent_id).state()
    invoke = AsyncMock(return_value={"synthetic": True})
    with pytest.raises(ValueError, match="task"):
        await gateway.route_call(agent_id=agent.agent_id, src_proto="mcp", dst_proto="a2a",
                                 src_wire=task_call(task), invoke=invoke, cost=3)
    invoke.assert_not_awaited()
    assert gateway.budgets.get(agent.agent_id).state() == before
    assert gateway.audit.count() == 0
    assert approvals.pending() == []


def http_agent(monkeypatch):
    from src.api import control_plane as cp

    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    monkeypatch.setitem(cp._ready, "ok", True)
    agent = AgentIdentity.generate("mcp-task-http-" + uuid.uuid4().hex)
    cp.identities.register(agent)
    cp.budgets.set_budget(agent.agent_id, Budget(spend_limit=10, rate_limit=100))
    invoke = AsyncMock(return_value={"synthetic": True})
    monkeypatch.setattr(cp, "_invoke_target", invoke)
    return cp, agent, invoke


def signed_route(client, agent, payload):
    body = json.dumps(payload).encode()
    nonce = uuid.uuid4().hex
    return client.post("/control/route", content=body, headers={
        "X-Agent-Id": agent.agent_id, "X-Nonce": nonce,
        "X-Signature": sign_request(agent, nonce, body),
    })


@pytest.mark.parametrize("task", TASK_VALUES)
def test_signed_http_task_refusal_precedes_budget_or_invocation(monkeypatch, task):
    cp, agent, invoke = http_agent(monkeypatch)
    before = cp.budgets.get(agent.agent_id).state()
    audit_before = cp.audit.count()
    payload = {"src": "mcp", "dst": "a2a", "wire": task_call(task), "cost": 3}
    client = TestClient(cp.app)
    assert signed_route(client, agent, payload).status_code == 400
    assert client.post("/control/translate/call", json=payload).status_code == 400
    invoke.assert_not_awaited()
    assert cp.budgets.get(agent.agent_id).state() == before
    assert cp.audit.count() == audit_before


@pytest.mark.parametrize("task", [{}, {"ttl": 60000}])
def test_reviewed_official_sdk_accepts_task_augmented_request_shape(task):
    mcp = pytest.importorskip("mcp.types")
    params = mcp.CallToolRequestParams.model_validate(task_call(task)["params"])
    assert params.model_dump(exclude_none=True)["task"] == task


@pytest.mark.parametrize("destination", default_registry.protocols())
def test_ordinary_tool_argument_named_task_still_translates(destination):
    wire = tool_call()
    wire["params"]["arguments"]["task"] = {"ttl": 60000}
    rendered = default_registry.translate_call(wire, "mcp", destination)
    decoded = default_registry.get(destination).to_canonical_call(rendered)
    assert decoded.capability == "echo"
    assert decoded.arguments == wire["params"]["arguments"]


def test_ordinary_inline_tool_call_still_dispatches():
    with patch("src.proxy.transport.send_a2a_message", new_callable=AsyncMock,
               return_value={"texts": ["synthetic result"], "raw": {}}) as invoke:
        result = asyncio.run(InlineProxy().mcp_request_to_a2a_agent(
            tool_call(), "https://example.invalid"))
    invoke.assert_awaited_once_with("https://example.invalid", "synthetic read-only")
    assert result["mcp_result"]["result"] == {
        "content": [{"type": "text", "text": "synthetic result"}], "isError": False}


def test_ordinary_signed_http_tool_call_still_settles_once(monkeypatch):
    cp, agent, invoke = http_agent(monkeypatch)
    payload = {"src": "mcp", "dst": "a2a", "wire": tool_call(), "cost": 3}
    client = TestClient(cp.app)
    response = signed_route(client, agent, payload)
    assert response.status_code == 200
    assert response.json()["decision"] == "allow"
    assert client.post("/control/translate/call", json=payload).status_code == 200
    invoke.assert_awaited_once()
    budget = cp.budgets.get(agent.agent_id)
    assert budget.spent == 3 and budget.reserved == 0
    assert len(budget.state()["calls"]) == 1
