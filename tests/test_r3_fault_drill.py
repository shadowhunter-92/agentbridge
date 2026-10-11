"""R3 synthetic fault drill: uncertain remote outcome retains financial reservation."""
import asyncio
import pytest
from src.governance.store import SqliteStore
from src.governance.operation_ledger import OperationLedger, OperationConflict
from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.budget import BudgetManager, Budget
from src.governance.gateway import GovernanceGateway
from src.protocols.canonical import CanonicalCall


@pytest.mark.parametrize("outcome", ["timeout", "cancelled"])
def test_indeterminate_execution_retains_reservation(tmp_path, outcome):
    store = SqliteStore(str(tmp_path / "drill.db"))
    try:
        identities = IdentityRegistry(store)
        identities.register(AgentIdentity.generate("agent"))
        budgets = BudgetManager(store)
        budgets.set_budget("agent", Budget(spend_limit=1.0, rate_limit=10))
        gateway = GovernanceGateway(identities=identities, budgets=budgets)
        wire = gateway.registry.get("openai").from_canonical_call(
            CanonicalCall("transfer", {"amount": 100}))
        side_effects = []

        async def untrusted_destination(_):
            side_effects.append("committed")
            if outcome == "timeout":
                raise TimeoutError("response lost after commit")
            raise asyncio.CancelledError()

        params = dict(agent_id="agent", src_proto="openai", dst_proto="mcp",
                      src_wire=wire, invoke=untrusted_destination, cost=1.0,
                      operation_id="operation-0000001")
        with pytest.raises((TimeoutError, asyncio.CancelledError)):
            asyncio.run(gateway.route_call(**params))
        assert side_effects == ["committed"]
        assert OperationLedger(store).get("agent", params["operation_id"])["state"] == "unknown"
        state = store.get_budget("agent")
        assert sum(state["reserved"].values()) == 1.0
        with pytest.raises(OperationConflict):
            asyncio.run(gateway.route_call(**params))
        assert side_effects == ["committed"]
    finally:
        store.close()
