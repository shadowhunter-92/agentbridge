"""Regression tests for request-bound, one-shot approval authorization."""
import asyncio
import pytest
from src.governance import (
    AgentIdentity, IdentityRegistry, BudgetManager, Budget,
    ApprovalQueue, PolicyEngine, GovernanceGateway, GovernanceError,
)
from src.protocols.canonical import CanonicalCall


def _fixture():
    ids = IdentityRegistry()
    ids.register(AgentIdentity.generate("caller"))
    buds = BudgetManager()
    buds.set_budget("caller", Budget(spend_limit=100, rate_limit=1000))
    approvals = ApprovalQueue()
    approvals.mark_sensitive("transfer")
    policy = PolicyEngine(ids, buds, approvals=approvals)
    gateway = GovernanceGateway(identities=ids, budgets=buds,
                                approvals=approvals, policy=policy)
    return gateway, approvals


def _wire(gateway, amount):
    return gateway.registry.get("openai").from_canonical_call(
        CanonicalCall("transfer", {"amount": amount}))


def _call(gateway, wire):
    async def invoke(_):
        return {"executed": True}
    return gateway.route_call(agent_id="caller", src_proto="openai",
                              dst_proto="mcp", src_wire=wire,
                              invoke=invoke, cost=1, target_id="approved-target")


def test_approval_is_one_shot_and_request_bound():
    gateway, approvals = _fixture()
    wire = _wire(gateway, 100)
    with pytest.raises(GovernanceError) as denial:
        asyncio.run(_call(gateway, wire))
    approval_id = denial.value.approval_id
    assert approval_id and approvals.approve(approval_id)
    changed = _wire(gateway, 999)
    with pytest.raises(GovernanceError):
        asyncio.run(_call(gateway, changed))
    assert asyncio.run(_call(gateway, wire))["executed"]
    with pytest.raises(GovernanceError):
        asyncio.run(_call(gateway, wire))


def test_approval_preconsumed_even_on_target_failure():
    gateway, approvals = _fixture()
    wire = _wire(gateway, 5)
    with pytest.raises(GovernanceError) as denial:
        asyncio.run(_call(gateway, wire))
    approvals.approve(denial.value.approval_id)

    async def fails(_):
        raise RuntimeError("indeterminate target failure")

    with pytest.raises(RuntimeError):
        asyncio.run(gateway.route_call(agent_id="caller", src_proto="openai",
                                       dst_proto="mcp", src_wire=wire,
                                       invoke=fails, cost=1,
                                       target_id="approved-target"))
    with pytest.raises(GovernanceError):
        asyncio.run(_call(gateway, wire))
