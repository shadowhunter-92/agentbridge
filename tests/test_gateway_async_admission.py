"""Blocking SQL admission must not block asyncio or leak canceled reservations."""

import asyncio
import threading
import uuid

import pytest

from src.governance import AgentIdentity, Budget, BudgetManager, GovernanceGateway, IdentityRegistry
from src.governance.operation_ledger import OperationLedger


@pytest.mark.asyncio
async def test_sql_admission_leaves_event_loop_responsive(network_sql_stores, monkeypatch):
    store = network_sql_stores()
    identities = IdentityRegistry(store)
    identities.register(AgentIdentity.generate("worker"))
    budgets = BudgetManager(store)
    budgets.set_budget("worker", Budget(spend_limit=10))
    gateway = GovernanceGateway(identities=identities, budgets=budgets)
    started, release = threading.Event(), threading.Event()
    reserve = budgets.reserve

    def slow_reserve(*args, **kwargs):
        started.set()
        assert release.wait(1), "SQL admission blocked the event loop"
        return reserve(*args, **kwargs)

    monkeypatch.setattr(budgets, "reserve", slow_reserve)

    async def invoke(wire):
        return {"ok": True}

    task = asyncio.create_task(
        gateway.route_call(
            agent_id="worker",
            src_proto="mcp",
            dst_proto="mcp",
            src_wire={"method": "tools/call", "params": {"name": "read", "arguments": {}}},
            invoke=invoke,
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        release.set()
        assert (await task)["ok"]
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_losing_concurrent_claim_cannot_finish_winners_operation(network_sql_stores, monkeypatch):
    store = network_sql_stores()
    identities = IdentityRegistry(store)
    identities.register(AgentIdentity.generate("worker"))
    budgets = BudgetManager(store)
    budgets.set_budget("worker", Budget(spend_limit=10))
    gateway = GovernanceGateway(identities=identities, budgets=budgets)
    operation = "concurrent-operation-" + uuid.uuid4().hex
    barrier = threading.Barrier(2)
    get = OperationLedger.get

    def synchronized_get(ledger, agent, op):
        row = get(ledger, agent, op)
        if row is None and op == operation:
            barrier.wait(3)
        return row

    monkeypatch.setattr(OperationLedger, "get", synchronized_get)
    entered, release = asyncio.Event(), asyncio.Event()
    effects = []

    async def invoke(wire):
        effects.append(wire)
        entered.set()
        await release.wait()
        return {"ok": True}

    def call():
        return gateway.route_call(
            agent_id="worker",
            src_proto="mcp",
            dst_proto="mcp",
            operation_id=operation,
            src_wire={"method": "tools/call", "params": {"name": "read", "arguments": {}}},
            invoke=invoke,
        )

    tasks = [asyncio.create_task(call()) for _ in range(2)]
    try:
        await asyncio.wait_for(entered.wait(), 4)
        done, pending = await asyncio.wait(tasks, timeout=4, return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == 1 and len(pending) == 1
        from src.governance.operation_ledger import OperationConflict

        assert isinstance(next(iter(done)).exception(), OperationConflict)
        assert get(OperationLedger(store), "worker", operation)["state"] == "unknown"
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert sum(isinstance(r, dict) for r in results) == 1 and len(effects) == 1
        assert get(OperationLedger(store), "worker", operation)["state"] == "succeeded"
        assert budgets.get("worker").spent == 1 and budgets.get("worker").reserved == 0
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_after_dispatch_keeps_unknown_exposure(network_sql_stores):
    store = network_sql_stores()
    identities = IdentityRegistry(store)
    identities.register(AgentIdentity.generate("worker"))
    budgets = BudgetManager(store)
    budgets.set_budget("worker", Budget(spend_limit=10))
    gateway = GovernanceGateway(identities=identities, budgets=budgets)
    operation = "cancel-invoke-" + uuid.uuid4().hex
    entered = asyncio.Event()

    async def invoke(wire):
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        gateway.route_call(
            agent_id="worker",
            src_proto="mcp",
            dst_proto="mcp",
            operation_id=operation,
            src_wire={"method": "tools/call", "params": {"name": "read", "arguments": {}}},
            invoke=invoke,
        )
    )
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert OperationLedger(store).get("worker", operation)["state"] == "unknown"
    assert budgets.get("worker").reserved == 1 and budgets.get("worker").spent == 0


@pytest.mark.asyncio
async def test_cancellation_after_definite_success_finishes_settlement(network_sql_stores, monkeypatch):
    store = network_sql_stores()
    identities = IdentityRegistry(store)
    identities.register(AgentIdentity.generate("worker"))
    budgets = BudgetManager(store)
    budgets.set_budget("worker", Budget(spend_limit=10))
    gateway = GovernanceGateway(identities=identities, budgets=budgets)
    operation = "cancel-settle-" + uuid.uuid4().hex
    started, release = threading.Event(), threading.Event()
    commit = budgets.commit

    def paused_commit(*args, **kwargs):
        result = commit(*args, **kwargs)
        started.set()
        assert release.wait(3)
        return result

    monkeypatch.setattr(budgets, "commit", paused_commit)

    async def invoke(wire):
        return {"ok": True}

    task = asyncio.create_task(
        gateway.route_call(
            agent_id="worker",
            src_proto="mcp",
            dst_proto="mcp",
            operation_id=operation,
            src_wire={"method": "tools/call", "params": {"name": "read", "arguments": {}}},
            invoke=invoke,
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert OperationLedger(store).get("worker", operation)["state"] == "succeeded"
        assert budgets.get("worker").spent == 1 and budgets.get("worker").reserved == 0
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_during_admission_releases_before_any_effect(network_sql_stores, monkeypatch):
    store = network_sql_stores()
    identities = IdentityRegistry(store)
    identities.register(AgentIdentity.generate("worker"))
    budgets = BudgetManager(store)
    budgets.set_budget("worker", Budget(spend_limit=10))
    gateway = GovernanceGateway(identities=identities, budgets=budgets)
    started, release = threading.Event(), threading.Event()
    reserve = budgets.reserve
    effects = []

    def paused_reserve(*args, **kwargs):
        token = reserve(*args, **kwargs)
        started.set()
        assert release.wait(2), "admission was not independently cancellable"
        return token

    monkeypatch.setattr(budgets, "reserve", paused_reserve)

    async def invoke(wire):
        effects.append(wire)
        return {"ok": True}

    operation = "cancel-admission-" + uuid.uuid4().hex
    task = asyncio.create_task(
        gateway.route_call(
            agent_id="worker",
            src_proto="mcp",
            dst_proto="mcp",
            operation_id=operation,
            src_wire={"method": "tools/call", "params": {"name": "read", "arguments": {}}},
            invoke=invoke,
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert effects == []
        assert budgets.get("worker").reserved == 0
        assert budgets.get("worker").spent == 0
        row = OperationLedger(store).get("worker", operation)
        assert row is None or row["state"] == "failed"
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
