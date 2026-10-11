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



def test_production_gateway_requires_signed_agent_proof(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    monkeypatch.setenv("AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON", '{"agent":["read"]}')
    store = SqliteStore(str(tmp_path / "signed.db"))
    try:
        ids = IdentityRegistry(store)
        identity = AgentIdentity.generate("agent")
        ids.register(identity)
        budgets = BudgetManager(store)
        budgets.set_budget("agent", Budget(spend_limit=10))
        gateway = GovernanceGateway(identities=ids, budgets=budgets)
        wire = gateway.registry.get("openai").from_canonical_call(
            CanonicalCall("read", {"id": 1}))
        executions = []
        async def target(_):
            executions.append(1)
            return {"ok": True}
        base = dict(agent_id="agent", src_proto="openai", dst_proto="mcp",
                    src_wire=wire, invoke=target, cost=1,
                    operation_id="signed-prod-operation-0001")
        from src.governance.gateway import GovernanceError
        with pytest.raises(GovernanceError, match="request-bound signed agent proof required"):
            asyncio.run(gateway.route_call(**base))
        assert executions == []
        # Signing unrelated bytes is never sufficient.
        with pytest.raises(GovernanceError, match="request-bound signed agent proof required"):
            asyncio.run(gateway.route_call(**base, signed_data=b"proof",
                                           signature=identity.sign(b"proof")))
        assert executions == []
        import json
        from src.governance.request_auth import canonical_payload
        body = json.dumps({"src":"openai", "dst":"mcp", "wire":wire,
                           "operation_id":"signed-prod-operation-0001"}).encode()
        nonce = "signed-library-proof"
        proof = canonical_payload("agent", nonce, body)
        result = asyncio.run(gateway.route_call(
            **base, signed_body=body, signed_nonce=nonce,
            signed_data=proof, signature=identity.sign(proof)))
        assert result == {"ok": True}
        assert executions == [1]
        changed = json.dumps({"src":"openai", "dst":"mcp",
                               "operation_id":"signed-prod-operation-0001",
                               "wire": {"tool": "delete"}}).encode()
        changed_proof = canonical_payload("agent", nonce, changed)
        with pytest.raises(GovernanceError, match="request-bound signed agent proof required"):
            asyncio.run(gateway.route_call(
                **base, signed_body=changed, signed_nonce=nonce,
                signed_data=changed_proof, signature=identity.sign(changed_proof)))
        assert executions == [1]
    finally:
        store.close()


def test_atomic_duplicate_claim_has_one_winner(tmp_path):
    import threading
    path = str(tmp_path / "claim-race.db")
    first, second = SqliteStore(path), SqliteStore(path)
    outcomes = []
    try:
        ledgers = [OperationLedger(first), OperationLedger(second)]
        barrier = threading.Barrier(2)
        def worker(ledger):
            barrier.wait()
            try:
                ledger.claim("agent", "key-1234567891011", "scope")
                outcomes.append("claimed")
            except OperationConflict:
                outcomes.append("duplicate")
        threads = [threading.Thread(target=worker, args=(l,)) for l in ledgers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not any(t.is_alive() for t in threads)
        assert sorted(outcomes) == ["claimed", "duplicate"]
    finally:
        first.close()
        second.close()


def test_production_rejects_missing_operation_identity_before_invocation(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "production")
    monkeypatch.setenv("AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON", '{"agent":["read"]}')
    store = SqliteStore(str(tmp_path / "prod.db"))
    try:
        ids = IdentityRegistry(store)
        identity = AgentIdentity.generate("agent")
        ids.register(identity)
        budget = BudgetManager(store)
        budget.set_budget("agent", Budget(spend_limit=10))
        gateway = GovernanceGateway(identities=ids, budgets=budget)
        wire = gateway.registry.get("openai").from_canonical_call(CanonicalCall("read", {"id": 1}))
        effects = []
        async def invoke(_):
            effects.append(1)
            return {"ok": True}
        from src.governance.gateway import GovernanceError
        with pytest.raises(GovernanceError, match="durable operation_id required"):
            asyncio.run(gateway.route_call(agent_id="agent", src_proto="openai", dst_proto="mcp",
                                            src_wire=wire, invoke=invoke))
        assert effects == []
    finally:
        store.close()


def test_budget_state_roundtrip_preserves_reservations():
    budget = Budget(spend_limit=5)
    token, _ = budget.reserve(2)
    restored = Budget.from_state(budget.state())
    assert restored.reserved == 2
    assert not restored.can_afford(4)[0]
    assert restored.release(token)
