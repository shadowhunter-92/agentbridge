"""Failure, replay and authorization tests; all actions use inert fakes."""
import asyncio
import pytest
from src.governance.store import SqliteStore
from src.governance.operation_ledger import OperationLedger, OperationConflict
from src.governance.identity import IdentityRegistry, AgentIdentity
from src.governance.budget import Budget, BudgetManager
from src.governance.policy import PolicyEngine
from src.governance.gateway import GovernanceGateway
from src.protocols.canonical import CanonicalCall


def test_durable_operations_refuse_replay_and_payload_swap(tmp_path):
    path = str(tmp_path / "operations.db")
    first, second = SqliteStore(path), SqliteStore(path)
    try:
        a, b = OperationLedger(first), OperationLedger(second)
        a.claim("agent", "idempotency-key-abc", "hashA")
        with pytest.raises(OperationConflict, match="unknown"):
            b.claim("agent", "idempotency-key-abc", "hashA")
        with pytest.raises(OperationConflict, match="different request"):
            b.claim("agent", "idempotency-key-abc", "hashB")
        a.finish("agent", "idempotency-key-abc", "succeeded")
        assert b.get("agent", "idempotency-key-abc")["state"] == "succeeded"
        with pytest.raises(OperationConflict):
            b.claim("agent", "idempotency-key-abc", "hashA")
    finally:
        first.close()
        second.close()


def test_production_capability_defaults_to_deny(monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    monkeypatch.delenv("AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON", raising=False)
    ids = IdentityRegistry()
    ids.register(AgentIdentity.generate("agent"))
    policy = PolicyEngine(ids, BudgetManager())
    assert not policy.authorize(agent_id="agent", capability="transfer").allowed
    monkeypatch.setenv("AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON",
                       '{"agent":["read"]}')
    assert not policy.authorize(agent_id="agent", capability="transfer").allowed
    assert policy.authorize(agent_id="agent", capability="read").allowed


def test_repeated_gateway_operation_does_not_execute_twice(tmp_path):
    store = SqliteStore(str(tmp_path / "execution.db"))
    try:
        ids = IdentityRegistry(store)
        ids.register(AgentIdentity.generate("agent"))
        budgets = BudgetManager(store)
        budgets.set_budget("agent", Budget(spend_limit=10))
        policy = PolicyEngine(ids, budgets)
        gw = GovernanceGateway(identities=ids, budgets=budgets, policy=policy)
        wire = gw.registry.get("openai").from_canonical_call(
            CanonicalCall("read", {"id": 12}))
        calls = []
        async def fake_invoke(_):
            calls.append(1)
            return {"ok": True}
        kwargs=dict(agent_id="agent",src_proto="openai",dst_proto="mcp",
                    src_wire=wire,invoke=fake_invoke,operation_id="unique-operation-0001")
        assert asyncio.run(gw.route_call(**kwargs)) == {"ok":True}
        with pytest.raises(OperationConflict):
            asyncio.run(gw.route_call(**kwargs))
        assert calls == [1]
    finally:
        store.close()


def test_unknown_remote_outcome_is_not_retried(tmp_path):
    store = SqliteStore(str(tmp_path / "unknown.db"))
    try:
        ids = IdentityRegistry(store)
        ids.register(AgentIdentity.generate("agent"))
        buds = BudgetManager(store)
        buds.set_budget("agent", Budget(spend_limit=10))
        gw = GovernanceGateway(identities=ids, budgets=buds)
        wire = gw.registry.get("openai").from_canonical_call(
            CanonicalCall("read", {"id": 12}))
        calls = []
        async def uncertain(_):
            calls.append(1)
            raise TimeoutError("connection lost after possible execution")
        kwargs=dict(agent_id="agent",src_proto="openai",dst_proto="mcp",
                    src_wire=wire,invoke=uncertain,operation_id="unique-operation-0002")
        with pytest.raises(TimeoutError):
            asyncio.run(gw.route_call(**kwargs))
        with pytest.raises(OperationConflict):
            asyncio.run(gw.route_call(**kwargs))
        assert len(calls) == 1
        assert OperationLedger(store).get("agent","unique-operation-0002")["state"] == "unknown"
    finally:
        store.close()
