"""Admission crashes cannot consume an approval or orphan a reservation."""

import json
import os
import subprocess
import sys
import uuid

import pytest

from src.governance.audit import AuditLog
from src.governance.budget import Budget, BudgetManager
from src.governance.durable_policy import DurableApprovalQueue
from src.governance.gateway import GovernanceError, GovernanceGateway
from src.governance.identity import AgentIdentity, IdentityRegistry
from src.governance.operation_ledger import OperationLedger
from src.governance.store import SqliteStore
from tests.test_authority import authority as authority
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


@pytest.mark.parametrize("stage", ["reserve", "approval", "claim"])
def test_process_death_before_admission_commit_preserves_grant_and_budget(
    network_sql_stores, tmp_path, monkeypatch, stage
):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "legacy_single_tenant")
    store = network_sql_stores()
    identities = IdentityRegistry(store)
    identities.register(AgentIdentity.generate("worker"))
    budgets = BudgetManager(store)
    budgets.set_budget("worker", Budget(spend_limit=10))
    approvals = DurableApprovalQueue(store)
    approvals.mark_sensitive("read")
    audit = AuditLog(store)
    gateway = GovernanceGateway(identities=identities, budgets=budgets, approvals=approvals, audit=audit)
    operation = "admission-crash-" + uuid.uuid4().hex
    arguments = {
        "agent_id": "worker",
        "src_proto": "mcp",
        "dst_proto": "mcp",
        "cost": 2.0,
        "operation_id": operation,
        "src_wire": {"method": "tools/call", "params": {"name": "read", "arguments": {}}},
    }
    with pytest.raises(GovernanceError) as denied:
        gateway._admit(**arguments)
    approval = denied.value.approval_id
    assert approval and approvals.approve(approval)
    count = audit.count()
    if isinstance(store, SqliteStore):
        config = {"backend": "sqlite", "path": store._db.execute("PRAGMA database_list").fetchone()["file"]}
    else:
        from psycopg.conninfo import make_conninfo

        config = {"backend": "postgres", "dsn": make_conninfo(store._db.info.dsn, password=store._db.info.password)}
    config.update(arguments=arguments, stage=stage)
    child = tmp_path / "crash_admission.py"
    child.write_text(
        """
import json,os
from src.governance.audit import AuditLog
from src.governance.budget import BudgetManager
from src.governance.durable_policy import DurableApprovalQueue
from src.governance.gateway import GovernanceGateway
from src.governance.identity import IdentityRegistry
from src.governance.operation_ledger import OperationLedger
from src.governance.store import SqliteStore,PostgresStore
c=json.loads(os.environ['AGENTBRIDGE_CRASH_ADMISSION'])
s=SqliteStore(c['path']) if c['backend']=='sqlite' else PostgresStore(c['dsn'])
b=BudgetManager(s); q=DurableApprovalQueue(s); a=AuditLog(s)
g=GovernanceGateway(identities=IdentityRegistry(s),budgets=b,approvals=q,audit=a)
if c['stage']=='reserve':
    original=b.reserve
    def crash(*args,**kwargs):
        result=original(*args,**kwargs)
        assert result[0]
        os._exit(75)
    b.reserve=crash
elif c['stage']=='approval':
    original=q.consume
    def crash(*args,**kwargs):
        assert original(*args,**kwargs)
        os._exit(75)
    q.consume=crash
else:
    original=OperationLedger.claim
    def crash(self,*args,**kwargs):
        original(self,*args,**kwargs)
        os._exit(75)
    OperationLedger.claim=crash
g._admit(**c['arguments'])
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(AGENTBRIDGE_CRASH_ADMISSION=json.dumps(config), PYTHONPATH=os.getcwd())
    result = subprocess.run([sys.executable, str(child)], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 75, result.stderr
    budget = budgets.get("worker")
    assert budget.spent == 0 and budget.reserved == 0
    assert approvals.get(approval).status == "approved"
    assert OperationLedger(store).get("worker", operation) is None
    assert audit.count() == count and AuditLog.verify_chain(store.load_audit(), require_genesis=True)


def test_reservation_link_rejects_wrong_agent_reuse_and_terminal_operation(network_sql_stores):
    from src.governance.operation_ledger import OperationConflict

    store = network_sql_stores()
    budget = BudgetManager(store)
    for agent in ("one", "two"):
        budget.set_budget(agent, Budget(spend_limit=10))
    token, _ = budget.reserve("one", 2)
    ledger = OperationLedger(store)
    ledger.claim("one", "owned-operation-12345", "owned")
    ledger.claim("one", "other-operation-12345", "other")
    ledger.claim("two", "other-agent-operation", "other-agent")
    with pytest.raises(OperationConflict, match="not pending for this agent"):
        ledger.attach_reservation("two", "other-agent-operation", token)
    ledger.attach_reservation("one", "owned-operation-12345", token)
    from src.governance.store import sql_atomic

    with pytest.raises(OperationConflict, match="already has a reservation"):
        with sql_atomic(store):
            another, _ = budget.reserve("one", 1)
            ledger.attach_reservation("one", "owned-operation-12345", another)
    assert budget.get("one").reserved == 2
    with pytest.raises(OperationConflict, match="already attached"):
        ledger.attach_reservation("one", "other-operation-12345", token)
    ledger.finish("one", "other-operation-12345", "failed")
    with pytest.raises(OperationConflict, match="unresolved owned operation"):
        ledger.attach_reservation("one", "other-operation-12345", token)
    assert budget.get("one").reserved == 2 and budget.get("two").reserved == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception-after-consume", "rejected-consume"])
async def test_signed_tenant_admission_failure_restores_grant_and_keeps_denial_audit(tenant_app, monkeypatch, failure):
    from tests.test_tenant_kernel import signed_session

    kernel, admins, _, _, _, _ = tenant_app
    runtime = kernel._runtimes["alpha"]
    admins["alpha"].mark_sensitive("read")
    operation = "atomic-approval-" + uuid.uuid4().hex
    initial, body, nonce = signed_session(tenant_app, operation=operation)
    with pytest.raises(GovernanceError) as denied:
        await initial.route(body, nonce=nonce)
    approval = denied.value.approval_id
    assert admins["alpha"].approve(approval)
    count = runtime.audit.count()
    consume = runtime.approvals.consume

    def fail(*args, **kwargs):
        if failure == "rejected-consume":
            return False
        assert consume(*args, **kwargs)
        raise RuntimeError("failure after approval mutation")

    monkeypatch.setattr(runtime.approvals, "consume", fail)
    retry, body, nonce = signed_session(tenant_app, operation=operation)
    expected = GovernanceError if failure == "rejected-consume" else RuntimeError
    with pytest.raises(expected):
        await retry.route(body, nonce=nonce)
    assert runtime.budgets.get("worker").spent == 0 and runtime.budgets.get("worker").reserved == 0
    assert runtime.operations.get("worker", operation) is None
    assert runtime.approvals.get(approval).status == "approved"
    assert runtime.audit.count() == count + (failure == "rejected-consume")
    assert AuditLog.verify_chain(runtime.store.load_audit(), require_genesis=True)


@pytest.mark.asyncio
async def test_other_connection_cannot_see_partial_admission(tenant_app, namespaces, monkeypatch):
    import asyncio
    import threading

    from tests.test_tenant_kernel import signed_session

    kernel, admins, _, _, _, _ = tenant_app
    runtime = kernel._runtimes["alpha"]
    observer = namespaces("alpha")
    observed_operations = OperationLedger(observer)
    admins["alpha"].mark_sensitive("read")
    operation = "atomic-visible-" + uuid.uuid4().hex
    initial, body, nonce = signed_session(tenant_app, operation=operation)
    with pytest.raises(GovernanceError) as denied:
        await initial.route(body, nonce=nonce)
    approval = denied.value.approval_id
    assert admins["alpha"].approve(approval)
    entered, release = threading.Event(), threading.Event()
    consume = runtime.approvals.consume

    def pause(*args, **kwargs):
        result = consume(*args, **kwargs)
        assert result
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(runtime.approvals, "consume", pause)
    retry, body, nonce = signed_session(tenant_app, operation=operation)
    routing = asyncio.create_task(retry.route(body, nonce=nonce))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert observed_operations.get("worker", operation) is None
        assert observer.get_budget("worker")["reserved"] == {}
        assert observer.get_approval(approval)["status"] == "approved"
    finally:
        release.set()
    assert "translated_wire" in await routing
    assert observed_operations.get("worker", operation)["state"] == "succeeded"
    assert observer.get_budget("worker")["spent"] == 1
    assert observer.get_approval(approval)["status"] == "consumed"


@pytest.mark.asyncio
async def test_unsupported_translation_preserves_admission_state(tenant_app, monkeypatch):
    from tests.test_tenant_kernel import signed_session

    kernel, admins, _, _, _, _ = tenant_app
    runtime = kernel._runtimes["alpha"]
    admins["alpha"].mark_sensitive("read")
    operation = "unsupported-translation-" + uuid.uuid4().hex
    initial, body, nonce = signed_session(tenant_app, operation=operation)
    with pytest.raises(GovernanceError) as denied:
        await initial.route(body, nonce=nonce)
    approval = denied.value.approval_id
    assert admins["alpha"].approve(approval)

    def unsupported(*args, **kwargs):
        raise ValueError("unsupported translation semantics")

    monkeypatch.setattr(runtime.gateway.registry, "translate_call", unsupported)
    retry, body, nonce = signed_session(tenant_app, operation=operation)
    with pytest.raises(ValueError, match="unsupported translation semantics"):
        await retry.route(body, nonce=nonce)
    assert runtime.operations.get("worker", operation) is None
    budget = runtime.budgets.get("worker")
    assert budget.spent == 0 and budget.reserved == 0
    assert runtime.approvals.get(approval).status == "approved"
