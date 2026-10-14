"""Opaque transports are evaluation paths, not qualified production effects."""
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from src.api.trusted_targets import SecurityConfigurationError, resolve_target
from src.governance import (
    AgentIdentity,
    AuditLog,
    Budget,
    BudgetManager,
    GovernanceGateway,
    IdentityRegistry,
    sign_request,
)
from src.governance.durable_policy import DurableApprovalQueue
from src.governance.operation_ledger import OperationLedger
from src.governance.request_auth import RequestAuthenticator
from src.governance.store import SqliteStore


def target_record(protocol):
    base = {"protocol": protocol, "capabilities": ["do_work"], "allowed_agents": ["worker"]}
    if protocol == "mcp":
        return {**base, "kind": "mcp_stdio", "command": "python", "args": ["synthetic.py"]}
    return {**base, "kind": protocol + "_http", "base_url": "https://destination.example.org"}


@pytest.fixture
def owned_route(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ADMIN_KEY", "test-only-target-qualification-admin")
    from src.api import control_plane as cp
    store = SqliteStore(str(tmp_path / "qualification.db"))
    identities = IdentityRegistry(store)
    identity = AgentIdentity.generate("worker")
    identities.register(identity)
    budgets = BudgetManager(store)
    budgets.set_budget("worker", Budget(spend_limit=10))
    audit, approvals = AuditLog(store), DurableApprovalQueue(store)
    gateway = GovernanceGateway(identities=identities, budgets=budgets, approvals=approvals, audit=audit)
    for name, value in {"store": store, "identities": identities, "budgets": budgets,
                        "audit": audit, "approvals": approvals, "gateway": gateway,
                        "authenticator": RequestAuthenticator(identities)}.items():
        monkeypatch.setattr(cp, name, value)
    monkeypatch.setitem(cp._ready, "ok", True)
    monkeypatch.setenv("AGENTBRIDGE_COST_SCHEDULE_JSON", '{"do_work":1}')
    monkeypatch.setenv("AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON", '{"worker":["do_work"]}')
    monkeypatch.setenv("AGENTBRIDGE_EGRESS_PROXY_URL", "http://egress.example.org:3128")
    calls = []

    async def invoke(protocol, wire, target):
        if target is None:
            return {"translated_wire": wire}
        calls.append((protocol, wire, target))
        return {"result": {"synthetic": True}}

    monkeypatch.setattr(cp, "_invoke_target", invoke)
    try:
        yield TestClient(cp.app), identity, budgets, audit, approvals, store, calls
    finally:
        store.close()


def send(client, identity, protocol, target_id="owned"):
    operation_id = "qualified-operation-" + uuid.uuid4().hex
    body = json.dumps({"src": "mcp", "dst": protocol, "target_id": target_id,
                       "operation_id": operation_id, "wire": {
        "method": "tools/call", "params": {"name": "do_work", "arguments": {"id": 1}}}}).encode()
    nonce = str(time.time()) + ":" + uuid.uuid4().hex
    return client.post("/control/route", content=body, headers={
        "X-Agent-Id": identity.agent_id, "X-Nonce": nonce,
        "X-Signature": sign_request(identity, nonce, body)}), operation_id


@pytest.mark.parametrize("environment", ["prod", "production"])
@pytest.mark.parametrize("protocol", ["mcp", "a2a", "acp"])
def test_production_rejects_before_effect_or_governance_admission(owned_route, monkeypatch, environment, protocol):
    client, identity, budgets, audit, approvals, store, calls = owned_route
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    monkeypatch.setenv("AGENTBRIDGE_TARGETS_JSON", json.dumps({"owned": target_record(protocol)}))
    response, operation = send(client, identity, protocol)
    assert response.status_code == 400
    assert "destination-atomic" in response.json()["detail"]
    assert not calls
    assert budgets.get("worker").spent == 0
    assert budgets.get("worker").reserved == 0
    assert audit.count() == 0
    assert store.list_approvals() == []
    assert OperationLedger(store).get("worker", operation) is None


@pytest.mark.parametrize("protocol", ["mcp", "a2a", "acp"])
def test_nonproduction_owned_evaluation_still_dispatches(owned_route, monkeypatch, protocol):
    client, identity, budgets, audit, approvals, store, calls = owned_route
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    monkeypatch.setenv("AGENTBRIDGE_TARGETS_JSON", json.dumps({"owned": target_record(protocol)}))
    response, operation = send(client, identity, protocol)
    assert response.status_code == 200
    assert response.json()["result"]["synthetic"]
    assert len(calls) == 1
    assert budgets.get("worker").spent == 1
    assert OperationLedger(store).get("worker", operation)["state"] == "succeeded"


def test_metadata_cannot_self_certify_destination_enforcement():
    record = {**target_record("mcp"), "fenced": True,
              "execution_mode": "read_only", "qualification": {"production_accepted": True}}
    env = {"AGENTBRIDGE_ENV": "production", "AGENTBRIDGE_TARGETS_JSON": json.dumps({"owned": record})}
    with pytest.raises(SecurityConfigurationError, match="destination-atomic"):
        resolve_target("owned", "mcp", "do_work", env=env, agent_id="worker")
    assert resolve_target(None, "mcp", "do_work", env=env, agent_id="worker") is None


@pytest.mark.parametrize("environment", ["prod", "production"])
def test_translation_without_execution_remains_authorized(owned_route, monkeypatch, environment):
    client, identity, budgets, audit, approvals, store, calls = owned_route
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    response, operation = send(client, identity, "mcp", target_id=None)
    assert response.status_code == 200
    assert "translated_wire" in response.json()
    assert not calls
    assert OperationLedger(store).get("worker", operation)["state"] == "succeeded"
