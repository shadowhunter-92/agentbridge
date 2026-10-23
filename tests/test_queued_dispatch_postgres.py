"""Real PG authority/accounting with the bounded SQLite demonstration effect."""
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.authority import AuthorityDenied, AuthorityDirectory, sign_tenant_request
from src.governance.queued_destination_contract import canonical_demo_action, normalize_queued_descriptor
from src.governance.queued_sqlite_adapter import QueuedSqliteAdapter
from src.governance.store import PostgresStore, sql_atomic
from src.governance.tenant_kernel import TenantKernel, principal_owner
from src.protocols.task_lifecycle import TaskState
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_queued_dispatch_execution import _effects, _public
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


@pytest.fixture
def pg_dispatch_app(tenant_app, authority, namespaces, tmp_path):
    if not isinstance(authority[0].store, PostgresStore):
        pytest.skip("this module requires real PostgreSQL authority and tenant accounting")
    prior, admins, identities, token, directory, _ = tenant_app
    keys = {role: Ed25519PrivateKey.generate() for role in ("authorizer", "destination", "observer")}
    descriptor = normalize_queued_descriptor({
        "kind": "queued_fenced_sqlite_v2", "protocol": "mcp", "tenant_id": "alpha", "target_id": "ledger",
        "destination_id": "pg-accounting-sqlite-demo", "path": str(tmp_path / "effect.sqlite"),
        "action_schema": "agentbridge.demo.append.v1", "call_timeout_seconds": 5, "max_action_bytes": 4096,
        **{role + "_key_id": role + "-key" for role in keys},
        **{role + "_public_key_hex": _public(key) for role, key in keys.items()},
    })
    def worker(current_directory, store):
        adapter = QueuedSqliteAdapter(descriptor, authorizer_sign=keys["authorizer"].sign,
            destination_sign=keys["destination"].sign, observer_sign=keys["observer"].sign)
        kernel = TenantKernel(current_directory, {"alpha": store}, costs={"alpha": {"write": 2}},
            targets={"alpha": {"ledger": {**descriptor, "capabilities": ["write"], "allowed_agents": ["worker"]}}},
            queued_dispatch_adapters={"alpha": {"ledger": adapter}})
        principal = current_directory.authenticate_operator(ISSUER, token("administrator", tenant="alpha"), tenant_id="alpha")
        return SimpleNamespace(kernel=kernel, runtime=kernel._runtimes["alpha"], directory=current_directory,
            adapter=adapter, identity=identities["alpha"], admin=kernel.session(principal), config={"descriptor": descriptor})
    app = worker(directory, prior._runtimes["alpha"].store)
    def reopen():
        independent = AuthorityDirectory(authority[3](), verifiers=authority[4])
        return worker(independent, namespaces("alpha"))
    app.reopen, app.token, app.owner = reopen, token, authority[1]
    return app


def _task(app, *, delegation=None):
    task_id, operation_id = "task-" + uuid.uuid4().hex, "operation-" + uuid.uuid4().hex
    request = {"request_scope": "task.submit", "task_id": task_id, "context_id": "context",
        "src": "mcp", "dst": "mcp", "target_id": "ledger", "operation_id": operation_id,
        "wire": {"method": "tools/call", "params": {"name": "write", "arguments": {"value": "actual PG-accounted demo"}}}}
    body, nonce = json.dumps(request).encode(), f"{time.time()}:{uuid.uuid4().hex}"
    signature = sign_tenant_request(app.identity, "alpha", nonce, body, delegation_id=delegation)
    principal = app.directory.authenticate_agent("alpha", "worker", nonce, body, signature, delegation_id=delegation)
    session = app.kernel.session(principal)
    accepted = session.submit_task(body, nonce=nonce)
    owner = principal_owner(principal)
    link = app.kernel._admit_queued_intent("alpha", owner, task_id, accepted["intent_sha256"])
    return SimpleNamespace(refs=("alpha", owner, task_id, accepted["intent_sha256"], link["link_sha256"]),
        link=link, operation_id=operation_id, action=canonical_demo_action(request["wire"]))


def _assert_state(app, task, *, succeeded, effects):
    assert len(_effects(app)) == effects
    assert app.runtime.operations.get("worker", task.operation_id)["state"] == ("succeeded" if succeeded else "unknown")
    state = app.runtime.store.get_budget("worker")
    assert state["spent"] == (2 if succeeded else 0)
    assert state["reserved"] == ({} if succeeded else {task.link["reservation_token"]: 2})
    result = app.runtime.task_executions.result(task.refs[1], task.refs[2])
    assert (result is not None) == succeeded
    assert app.runtime.tasks.get(task.refs[1], task.refs[2]).state == (TaskState.COMPLETED if succeeded else TaskState.WORKING)


def test_postgres_success_and_exact_result_link_charge(pg_dispatch_app):
    app = pg_dispatch_app
    task = _task(app)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"
    _assert_state(app, task, succeeded=True, effects=1)
    decision = app.runtime.task_executions.decision(task.refs[1], task.refs[2])
    assert decision["admission_link_sha256"] == task.link["link_sha256"]
    assert app.runtime.task_executions.result(task.refs[1], task.refs[2])["decision_sha256"] == decision["record_sha256"]


def test_postgres_concurrent_independent_workers_commit_one_attempt(pg_dispatch_app):
    app = pg_dispatch_app
    task, other = _task(app), app.reopen()
    barrier, sends, lock = threading.Barrier(2), [], threading.Lock()
    for handle in (app, other):
        original = handle.adapter.commit
        def counted(*args, original=original):
            with lock:
                sends.append(args[0]["attempt_id"])
            return original(*args)
        handle.adapter.commit = counted
    def dispatch(handle):
        barrier.wait(timeout=5)
        return handle.kernel._dispatch_queued_once(*task.refs)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(dispatch, handle) for handle in (app, other)]
        results = [future.result(timeout=25) for future in futures]
    assert {value["state"] for value in results} <= {"unknown", "succeeded"}
    assert len(sends) == 1
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_state(other, task, succeeded=True, effects=1)


def test_postgres_local_lost_return_readback_outage_restart_never_resends(pg_dispatch_app, monkeypatch):
    app = pg_dispatch_app
    task = _task(app)
    original = app.adapter.commit
    def lost(*args):
        original(*args)
        raise TimeoutError("local dropped return, not network loss")
    monkeypatch.setattr(app.adapter, "commit", lost)
    monkeypatch.setattr(app.adapter, "observe", lambda *_: (_ for _ in ()).throw(RuntimeError("temporarily withheld")))
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    _assert_state(app, task, succeeded=False, effects=1)
    other = app.reopen()
    monkeypatch.setattr(other.adapter, "commit", lambda *_: pytest.fail("restart cannot resend"))
    assert other.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_state(app, task, succeeded=True, effects=1)


@pytest.mark.parametrize("stage", ["result", "budget", "ledger", "event", "audit"])
def test_postgres_after_effect_atomic_local_failure_holds_for_readback(pg_dispatch_app, monkeypatch, stage):
    app = pg_dispatch_app
    task = _task(app)
    component, method = {"result": (app.runtime.task_executions, "insert_result"),
        "budget": (app.runtime.budgets, "commit"), "ledger": (app.runtime.operations, "finish"),
        "event": (app.runtime.tasks, "transition"), "audit": (app.runtime.audit, "record")}[stage]
    original = getattr(component, method)
    def fault(*args, **kwargs):
        value = original(*args, **kwargs)
        if stage != "audit" or kwargs.get("action") == "task.verified-execution":
            raise RuntimeError("after " + stage)
        return value
    monkeypatch.setattr(component, method, fault)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    _assert_state(app, task, succeeded=False, effects=1)
    monkeypatch.setattr(component, method, original)
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_state(app, task, succeeded=True, effects=1)


def test_postgres_repeatable_read_rejected_without_attempt(pg_dispatch_app):
    app = pg_dispatch_app
    task = _task(app)
    with pytest.raises(AuthorityDenied, match="READ COMMITTED"):
        with sql_atomic(app.runtime.store):
            app.runtime.store._db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            app.runtime.task_executions.decision(task.refs[1], task.refs[2])
    assert app.runtime.task_executions.decision(task.refs[1], task.refs[2]) is None
    _assert_state(app, task, succeeded=False, effects=0)


def test_postgres_real_delegation_revocation_waits_for_active_dispatch_guard(pg_dispatch_app):
    app = pg_dispatch_app
    app.directory.enroll_member(app.owner, "alpha", ISSUER, "writer", role="tenant_operator", capabilities=("write",), targets=("ledger",))
    user = app.directory.authenticate_operator(ISSUER, app.token("writer", tenant="alpha"), tenant_id="alpha")
    grant = app.directory.grant_delegation(app.admin.principal, user, "worker", capabilities=("write",),
        targets=("ledger",), expires_at=time.time() + 600)
    task, other = _task(app, delegation=grant), app.reopen()
    entered, release, started, revoked = (threading.Event() for _ in range(4))
    commit = app.adapter.commit
    def gated(*args):
        entered.set()
        assert release.wait(timeout=8)
        return commit(*args)
    app.adapter.commit = gated
    def revoke():
        started.set()
        other.directory.revoke_delegation(other.admin.principal, "alpha", grant)
        revoked.set()
    with ThreadPoolExecutor(max_workers=2) as executor:
        dispatched = executor.submit(app.kernel._dispatch_queued_once, *task.refs)
        assert entered.wait(timeout=8)
        writer = executor.submit(revoke)
        assert started.wait(timeout=3)
        assert not revoked.wait(timeout=0.2)
        release.set()
        assert dispatched.result(timeout=15)["state"] == "succeeded"
        writer.result(timeout=15)
    assert revoked.is_set()
    _assert_state(app, task, succeeded=True, effects=1)


def test_postgres_approval_policy_writer_wins_before_waiting_dispatch(pg_dispatch_app):
    app = pg_dispatch_app
    task, other = _task(app), app.reopen()
    published, release = threading.Event(), threading.Event()
    def write_policy():
        with other.directory.guard(other.admin.principal, write=True):
            with sql_atomic(other.runtime.store):
                other.runtime.approvals.mark_sensitive("write")
                published.set()
                assert release.wait(timeout=8)
    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(write_policy)
        assert published.wait(timeout=8)
        waiting = executor.submit(app.kernel._dispatch_queued_once, *task.refs)
        assert not waiting.done()
        release.set()
        writer.result(timeout=15)
        with pytest.raises(AuthorityDenied):
            waiting.result(timeout=15)
    assert app.runtime.task_executions.decision(task.refs[1], task.refs[2]) is None
    _assert_state(app, task, succeeded=False, effects=0)


def test_postgres_actual_audit_capacity_after_effect_rolls_back_all_local_participants(pg_dispatch_app, monkeypatch):
    app = pg_dispatch_app
    task = _task(app)
    capacity, observe, saved = app.runtime.audit_trust, app.adapter.observe, {}
    def saturated(*args):
        observed = observe(*args)
        current = capacity.capacity()
        saved.update(current)
        capacity.set_capacity(max_records=current["used_records"], max_bytes=current["max_bytes"],
                              max_entry_bytes=current["max_entry_bytes"])
        return observed
    monkeypatch.setattr(app.adapter, "observe", saturated)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    _assert_state(app, task, succeeded=False, effects=1)
    capacity.set_capacity(max_records=saved["max_records"], max_bytes=saved["max_bytes"],
                          max_entry_bytes=saved["max_entry_bytes"])
    monkeypatch.setattr(app.adapter, "observe", observe)
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("capacity recovery cannot resend"))
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_state(app, task, succeeded=True, effects=1)


@pytest.mark.parametrize("connection", ["tenant", "authority"])
def test_postgres_dispatch_entry_rejects_repeatable_read_default(pg_dispatch_app, connection):
    app = pg_dispatch_app
    task = _task(app)
    store = app.runtime.store if connection == "tenant" else app.directory.store
    store._db.execute("SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    try:
        with pytest.raises(AuthorityDenied, match="READ COMMITTED"):
            app.kernel._dispatch_queued_once(*task.refs)
    finally:
        store._db.execute("SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED")
    assert app.runtime.task_executions.decision(task.refs[1], task.refs[2]) is None
    _assert_state(app, task, succeeded=False, effects=0)


def test_postgres_signing_journal_settlement_after_queued_authority_writer_has_no_lock_cycle(pg_dispatch_app):
    from examples.qualify_trust_evidence import signed_registry
    from src.governance.signing_trust_journal import SigningTrustJournal
    app = pg_dispatch_app
    controllers = {domain: Ed25519PrivateKey.generate() for domain in ("destination", "readback")}
    journal = SigningTrustJournal(app.runtime.store, controller_keys={domain: _public(key) for domain, key in controllers.items()})
    for domain, role in (("destination", "destination"), ("readback", "observer")):
        journal.publish(signed_registry(controllers[domain], domain, 1, None, [{
            "key_id": app.config["descriptor"][role + "_key_id"],
            "public_key_hex": app.config["descriptor"][role + "_public_key_hex"], "state": "active"}]))
    app.adapter.trust_journal = journal
    task, other = _task(app), app.reopen()
    entered, release, started, revoked = (threading.Event() for _ in range(4))
    commit = app.adapter.commit
    def gated(*args):
        entered.set()
        assert release.wait(timeout=8)
        return commit(*args)
    app.adapter.commit = gated
    def revoke():
        started.set()
        other.directory.revoke_agent(other.admin.principal, "alpha", "worker")
        revoked.set()
    with ThreadPoolExecutor(max_workers=2) as executor:
        dispatched = executor.submit(app.kernel._dispatch_queued_once, *task.refs)
        assert entered.wait(timeout=8)
        writer = executor.submit(revoke)
        assert started.wait(timeout=3)
        assert not revoked.wait(timeout=0.2)
        release.set()
        assert dispatched.result(timeout=15)["state"] == "succeeded"
        writer.result(timeout=15)
    assert revoked.is_set()
    _assert_state(app, task, succeeded=True, effects=1)
    assert app.runtime.task_executions.result(task.refs[1], task.refs[2])["trust_context"]["readback_revision"] == 1
