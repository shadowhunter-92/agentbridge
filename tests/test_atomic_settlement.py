"""A crash cannot split durable budget, outcome and audit settlement."""

import json
import os
import subprocess
import sys
import uuid

import pytest

from src.governance.audit import AuditLog
from src.governance.operation_ledger import OperationConflict, OperationLedger
from src.governance.store import SqliteStore
from tests.test_authority import authority as authority
from tests.test_tenant_kernel import signed_session
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["ledger", "audit"])
async def test_failed_settlement_retains_unknown_reservation_and_prevents_replay(
    tenant_app, monkeypatch, failure_stage
):
    session, body, nonce = signed_session(tenant_app, operation="settlement-failure-" + uuid.uuid4().hex)
    runtime = tenant_app[0]._runtimes["alpha"]
    request = json.loads(body)
    effects = []

    async def invoke(wire):
        effects.append(wire)
        return {"ok": True}

    def fail(*args, **kwargs):
        raise RuntimeError("injected settlement failure")

    if failure_stage == "ledger":
        original = OperationLedger.finish
        monkeypatch.setattr(OperationLedger, "finish", fail)
    else:
        original = runtime.audit.record

        def audit(**fields):
            if fields["decision"] == "allow":
                original(**fields)
                fail()
            return original(**fields)

        monkeypatch.setattr(runtime.audit, "record", audit)
    with pytest.raises(RuntimeError, match="settlement failure"):
        await runtime.gateway.route_call(
            agent_id="worker",
            src_proto="mcp",
            dst_proto="mcp",
            src_wire=request["wire"],
            operation_id=request["operation_id"],
            invoke=invoke,
            cost=1,
            signed_body=body,
            signed_nonce=nonce,
            principal=session.principal,
        )
    if failure_stage == "ledger":
        monkeypatch.setattr(OperationLedger, "finish", original)
    else:
        monkeypatch.setattr(runtime.audit, "record", original)
    assert len(effects) == 1
    row = runtime.operations.get("worker", request["operation_id"])
    budget = runtime.budgets.get("worker")
    assert row["state"] == "unknown" and budget.spent == 0 and budget.reserved == 1
    assert not any(entry.action == "route_call" and entry.decision == "allow" for entry in runtime.audit.entries())
    assert AuditLog.verify_chain(runtime.store.load_audit(), require_genesis=True)
    again, again_body, again_nonce = signed_session(tenant_app, operation=request["operation_id"])
    with pytest.raises(OperationConflict, match="no automatic replay"):
        await again.route(again_body, nonce=again_nonce)
    assert len(effects) == 1


@pytest.mark.parametrize("failure_stage", ["ledger", "audit"])
@pytest.mark.parametrize("transition", ["settle", "abort"])
def test_process_death_before_settlement_commit_preserves_unknown_exposure(
    tenant_app, tmp_path, failure_stage, transition
):
    runtime = tenant_app[0]._runtimes["alpha"]
    token, _ = runtime.budgets.reserve("worker", 2)
    operation = "settlement-crash-" + uuid.uuid4().hex
    runtime.operations.claim("worker", operation, "controlled-crash-fingerprint", reservation_token=token)
    store = runtime.store
    if isinstance(store, SqliteStore):
        config = {"backend": "sqlite", "path": str(store.path)}
    else:
        from psycopg.conninfo import make_conninfo

        config = {
            "backend": "postgres",
            "schema": store.schema,
            "dsn": make_conninfo(store._db.info.dsn, password=store._db.info.password),
        }
    config.update(token=token, operation=operation, stage=failure_stage, transition=transition)
    child = tmp_path / "crash_settlement.py"
    child.write_text(
        """
import json,os,time
from types import SimpleNamespace
from src.governance.audit import AuditLog
from src.governance.budget import BudgetManager
from src.governance.gateway import GovernanceGateway
from src.governance.identity import IdentityRegistry
from src.governance.operation_ledger import OperationLedger
from src.governance.policy import Decision
from src.governance.tenant_store import TenantSqliteStore,TenantPostgresStore
c=json.loads(os.environ['AGENTBRIDGE_CRASH_STORE'])
s=TenantSqliteStore(c['path'],tenant_id='alpha') if c['backend']=='sqlite' else TenantPostgresStore(c['dsn'],schema=c['schema'],tenant_id='alpha')
b=BudgetManager(s); a=AuditLog(s); l=OperationLedger(s)
g=GovernanceGateway(identities=IdentityRegistry(s),budgets=b,audit=a)
def crash(*args,**kwargs): os._exit(74)
if c['stage']=='ledger': l.finish=crash
else:
    original=a.record
    def crash_audit(**fields):
        original(**fields)
        os._exit(74)
    a.record=crash_audit
method=g._settle if c['transition']=='settle' else g._abort_admission
method(SimpleNamespace(agent_id='worker',token=c['token'],ledger=l,operation_id=c['operation'],actor='worker',
                         src='mcp',dst='mcp',capability='read',cost=2,decision=Decision(True,'ok'),started=time.monotonic()))
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(AGENTBRIDGE_CRASH_STORE=json.dumps(config), PYTHONPATH=os.getcwd())
    process = subprocess.run([sys.executable, str(child)], env=environment, capture_output=True, text=True, timeout=20)
    assert process.returncode == 74, process.stderr
    budget = runtime.budgets.get("worker")
    assert budget.spent == 0 and budget.reserved == 2
    assert runtime.operations.get("worker", operation)["state"] == "unknown"
    assert not any(entry.action == "route_call" for entry in runtime.audit.entries())


def test_other_connection_observes_no_partial_settlement(tenant_app, namespaces, monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from src.governance.operation_ledger import OperationLedger
    from src.governance.policy import Decision

    runtime = tenant_app[0]._runtimes["alpha"]
    observer = namespaces("alpha")
    token, _ = runtime.budgets.reserve("worker", 2)
    operation = "settlement-visible-" + uuid.uuid4().hex
    runtime.operations.claim("worker", operation, "visibility-fingerprint", reservation_token=token)
    original = runtime.budgets.commit
    entered, release = threading.Event(), threading.Event()

    def pause(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(runtime.budgets, "commit", pause)
    admission = SimpleNamespace(
        agent_id="worker",
        token=token,
        ledger=runtime.operations,
        operation_id=operation,
        actor="worker",
        src="mcp",
        dst="mcp",
        capability="read",
        cost=2,
        decision=Decision(True, "ok"),
        started=time.monotonic(),
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        settling = pool.submit(runtime.gateway._settle, admission)
        try:
            assert entered.wait(5)
            budget = observer.get_budget("worker")
            assert budget["spent"] == 0 and budget["reserved"][token] == 2
            assert (
                observer._db.execute(
                    "SELECT state FROM agent_operations WHERE operation_id="
                    + ("?" if isinstance(observer, SqliteStore) else "%s"),
                    (operation,),
                ).fetchone()["state"]
                == "unknown"
            )
        finally:
            release.set()
        settling.result(timeout=5)
    assert observer.get_budget("worker")["spent"] == 2
    assert observer.get_budget("worker")["reserved"] == {}
    assert OperationLedger(observer).get("worker", operation)["state"] == "succeeded"
    assert len([e for e in runtime.audit.entries() if e.action == "route_call" and e.decision == "allow"]) == 1


def test_nested_component_rollback_does_not_commit_outer_sql_work(tenant_app):
    from src.governance.store import sql_atomic

    runtime = tenant_app[0]._runtimes["alpha"]
    with sql_atomic(runtime.store):
        runtime.audit.record(
            actor="worker",
            action="atomic-positive",
            source_protocol="mcp",
            target_protocol="mcp",
            capability="read",
            decision="allow",
        )
        with pytest.raises(RuntimeError, match="nested rollback"):
            with sql_atomic(runtime.store):
                abandoned, _ = runtime.budgets.reserve("worker", 2)
                assert abandoned
                raise RuntimeError("nested rollback")
        retained, _ = runtime.budgets.reserve("worker", 1)
    budget = runtime.budgets.get("worker")
    assert budget.spent == 0 and budget.reserved == 1
    assert abandoned not in budget.state()["reserved"] and retained in budget.state()["reserved"]
    assert AuditLog.verify_chain(runtime.store.load_audit(), require_genesis=True)


@pytest.mark.asyncio
async def test_telemetry_failure_does_not_invalidate_committed_outcome(tenant_app, monkeypatch):
    import src.governance.gateway as module

    session, body, nonce = signed_session(tenant_app, operation="settlement-metrics-" + uuid.uuid4().hex)

    def fail(*args, **kwargs):
        raise RuntimeError("injected telemetry failure")

    monkeypatch.setattr(module, "record_call", fail)
    result = await session.route(body, nonce=nonce)
    assert "translated_wire" in result
    runtime = tenant_app[0]._runtimes["alpha"]
    assert runtime.operations.get("worker", json.loads(body)["operation_id"])["state"] == "succeeded"
    assert runtime.budgets.get("worker").spent == 1 and runtime.budgets.get("worker").reserved == 0
    events = [entry for entry in runtime.audit.entries() if entry.action == "route_call"]
    assert len(events) == 1 and events[0].decision == "allow"


def test_live_settlement_cannot_overwrite_concurrent_reconciliation(network_sql_stores, monkeypatch):
    import hashlib
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from src.governance.budget import Budget, BudgetManager
    from src.governance.gateway import GovernanceGateway
    from src.governance.identity import AgentIdentity, IdentityRegistry
    from src.governance.policy import Decision
    from src.governance.reconciliation import Reconciliation

    store, other = network_sql_stores(), network_sql_stores()
    identities = IdentityRegistry(store)
    identities.register(AgentIdentity.generate("worker"))
    budgets = BudgetManager(store)
    budgets.set_budget("worker", Budget(spend_limit=10))
    audit = AuditLog(store)
    ledger = OperationLedger(store)
    gateway = GovernanceGateway(identities=identities, budgets=budgets, audit=audit)
    reconciliation = Reconciliation(other)
    token, _ = budgets.reserve("worker", 2)
    operation = "settlement-race-" + uuid.uuid4().hex
    ledger.claim("worker", operation, "race-fingerprint", reservation_token=token)
    entered, release, committed = threading.Event(), threading.Event(), threading.Event()
    verify = reconciliation._verify_evidence

    def pause_verification(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return verify(*args, **kwargs)

    monkeypatch.setattr(reconciliation, "_verify_evidence", pause_verification)
    commit = budgets.commit

    def observe_commit(*args, **kwargs):
        result = commit(*args, **kwargs)
        committed.set()
        return result

    monkeypatch.setattr(budgets, "commit", observe_commit)
    admission = SimpleNamespace(
        agent_id="worker",
        token=token,
        ledger=ledger,
        operation_id=operation,
        actor="worker",
        src="mcp",
        dst="mcp",
        capability="read",
        cost=2,
        decision=Decision(True, "ok"),
        started=time.monotonic(),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        reviewed = pool.submit(
            reconciliation.record,
            agent_id="worker",
            operation_id=operation,
            result="succeeded",
            external_reference="controlled-simulator",
            evidence_sha256=hashlib.sha256(b"controlled").hexdigest(),
            reviewer="controlled-operator",
        )
        try:
            assert entered.wait(5)
            live = pool.submit(gateway._settle, admission)
            assert not committed.wait(0.2), "live settlement locked budget before the operation"
        finally:
            release.set()
        assert reviewed.result(timeout=5)["state"] == "succeeded"
        with pytest.raises(OperationConflict, match="already settled"):
            live.result(timeout=5)
    assert budgets.get("worker").spent == 2 and budgets.get("worker").reserved == 0
    assert ledger.get("worker", operation)["state"] == "succeeded"
    assert len([entry for entry in audit.entries() if entry.action == "reconcile_operation"]) == 1
