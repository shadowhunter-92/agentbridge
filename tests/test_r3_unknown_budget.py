"""Fault simulation for conservative unknown outcomes (synthetic only)."""
import asyncio
import pytest
from src.governance.store import SqliteStore
from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.budget import Budget, BudgetManager
from src.governance.gateway import GovernanceGateway
from src.governance.operation_ledger import OperationLedger
from src.protocols.canonical import CanonicalCall


def test_lost_ack_does_not_release_outstanding_budget(tmp_path):
    store = SqliteStore(str(tmp_path / "unknown-budget.db"))
    try:
        ids = IdentityRegistry(store)
        ids.register(AgentIdentity.generate("caller"))
        budgets = BudgetManager(store)
        budgets.set_budget("caller", Budget(spend_limit=1, rate_limit=100))
        gateway = GovernanceGateway(identities=ids, budgets=budgets)
        call = gateway.registry.get("openai").from_canonical_call(
            CanonicalCall("charge", {"amount": 1}))
        effects = []
        async def commit_then_timeout(_):
            effects.append("committed")
            raise TimeoutError("ack lost")
        args = dict(agent_id="caller",src_proto="openai",dst_proto="mcp",
                    src_wire=call,invoke=commit_then_timeout,cost=1,
                    operation_id="lost-ack-operation-001")
        with pytest.raises(TimeoutError):
            asyncio.run(gateway.route_call(**args))
        assert effects == ["committed"]
        state = budgets.get("caller")
        assert state.reserved == 1
        assert OperationLedger(store).get("caller", "lost-ack-operation-001")["state"] == "unknown"
        assert not budgets.can_afford("caller", 1)[0]
    finally:
        store.close()
