"""Signed SQLite tenant dispatch, independent recovery and real process death.

These tests use separate authority, tenant and demonstration destination files.
Local callback fault injection is labelled separately from subprocess death.
No PostgreSQL fixture or generic transport is involved.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.api.auth_oidc import OidcConfig, OidcVerifier
from src.governance.authority import AuthorityDenied, AuthorityDirectory, sign_tenant_request
from src.governance.gateway import GovernanceError
from src.governance.identity import AgentIdentity
from src.governance.queued_destination_contract import canonical_demo_action, normalize_queued_descriptor
from src.governance.queued_sqlite_adapter import QueuedSqliteAdapter
from src.governance.sandbox_readback import ObservationUnavailable
from src.governance.store import SqliteStore
from src.governance.task_intents import IntentLimits
from src.governance.tenant_kernel import TenantKernel, principal_owner
from src.governance.tenant_store import TenantSqliteStore
from src.protocols.task_lifecycle import TaskState

ISSUER = "https://queued-dispatch-issuer.example.test"
AUDIENCE = "agentbridge-authority"
CRASH_RETURN_CODES = {"after-marker": 73, "after-effect": 74, "before-marker-commit": 75,
                      "after-result-insert": 76, "after-local-commit": 77}
_CHILD_CRASH_SCRIPT = """
import json
import os
import sys
from tests.test_queued_dispatch_execution import _open
with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
app = _open(config)
stage = sys.argv[2]
if stage in ("after-marker", "after-effect"):
    original_commit = app.adapter.commit
    def crash(authorization, action_bytes):
        if stage == "after-effect":
            original_commit(authorization, action_bytes)
        os._exit(74 if stage == "after-effect" else 73)
    app.adapter.commit = crash
elif stage == "before-marker-commit":
    original_audit = app.runtime.audit.record
    def crash(*args, **kwargs):
        result = original_audit(*args, **kwargs)
        if kwargs.get("action") == "task.attempt-committed":
            os._exit(75)
        return result
    app.runtime.audit.record = crash
elif stage == "after-result-insert":
    original_insert = app.runtime.task_executions.insert_result
    def crash(record):
        original_insert(record)
        os._exit(76)
    app.runtime.task_executions.insert_result = crash
app.kernel._dispatch_queued_once(*config["refs"])
if stage == "after-local-commit":
    os._exit(77)
raise SystemExit(99)
"""


def _public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def _private(key):
    return key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption()).hex()


def _verifiers(config):
    # Every reopened process has the actual configured signature verifier. It
    # neither constructs Principal nor trusts serialized principal proof bits.
    return {ISSUER: OidcVerifier(OidcConfig(
        issuer=ISSUER, audience=AUDIENCE, algorithms=("EdDSA",), public_key_pem=config["issuer_public_pem"],
    ))}


def _open(config):
    directory_store = SqliteStore(config["authority_path"])
    tenant_store = TenantSqliteStore(config["tenant_path"], tenant_id="alpha")
    try:
        directory = AuthorityDirectory(directory_store, verifiers=_verifiers(config))
        keys = {role: Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw))
                for role, raw in config["demo_private_keys"].items()}
        adapter = QueuedSqliteAdapter(
            config["descriptor"], authorizer_sign=keys["authorizer"].sign,
            destination_sign=keys["destination"].sign, observer_sign=keys["observer"].sign,
        )
        kernel = TenantKernel(
            directory, {"alpha": tenant_store}, costs={"alpha": {"write": 2}},
            targets={"alpha": {"ledger": {**config["descriptor"], "capabilities": ["write"], "allowed_agents": ["worker"]}}},
            queued_dispatch_adapters={"alpha": {"ledger": adapter}},
        )
        return SimpleNamespace(kernel=kernel, directory=directory, adapter=adapter,
                               runtime=kernel._runtimes["alpha"], stores=(tenant_store, directory_store), config=config)
    except BaseException:
        tenant_store.close()
        directory_store.close()
        raise


def _close(handle):
    for store in handle.stores:
        store.close()


@pytest.fixture
def dispatch_app(tmp_path, monkeypatch, request):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    issuer_key = Ed25519PrivateKey.generate()
    keys = {role: Ed25519PrivateKey.generate() for role in ("authorizer", "destination", "observer")}
    descriptor = normalize_queued_descriptor({
        "kind": "queued_fenced_sqlite_v2", "protocol": "mcp", "tenant_id": "alpha", "target_id": "ledger",
        "destination_id": "dedicated-demo", "path": str(tmp_path / "destination.sqlite"),
        "action_schema": "agentbridge.demo.append.v1", "call_timeout_seconds": getattr(request, "param", 5), "max_action_bytes": 4096,
        **{role + "_key_id": role + "-key" for role in keys},
        **{role + "_public_key_hex": _public(key) for role, key in keys.items()},
    })
    config = {
        "authority_path": str(tmp_path / "authority.sqlite"), "tenant_path": str(tmp_path / "alpha.sqlite"),
        "issuer_public_pem": issuer_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
        # These are disposable generated demonstration keys, never credentials
        # for any external service. Subprocess tests need the same operator pins.
        "demo_private_keys": {role: _private(key) for role, key in keys.items()}, "descriptor": descriptor,
    }
    app = _open(config)
    try:
        app.directory.bootstrap_platform_admin(ISSUER, "owner")
        token = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "owner", "exp": time.time() + 1800},
                           issuer_key, algorithm="EdDSA")
        operator = app.directory.authenticate_operator(ISSUER, token)
        app.directory.set_tenant(operator, "alpha", active=True)
        identity = AgentIdentity.generate("worker")
        admin = app.kernel.session(operator, tenant_id="alpha")
        admin.enroll_agent("worker", identity.public_key_hex, capabilities=("write",), targets=("ledger",))
        admin.set_budget("worker", spend_limit=20)
        app.identity, app.operator, app.admin = identity, operator, admin
        yield app
    finally:
        _close(app)


def _admit(app, *, task_id="native-task", context_id="native-context", operation_id="queued-operation-123456", value="demo value", approval=False):
    if approval:
        app.admin.mark_sensitive("write")
    submission = {"request_scope": "task.submit", "task_id": task_id, "context_id": context_id,
                  "src": "mcp", "dst": "mcp", "target_id": "ledger", "operation_id": operation_id,
                  "wire": {"method": "tools/call", "params": {"name": "write", "arguments": {"value": value}}}}
    body = json.dumps(submission, ensure_ascii=True).encode()
    nonce = f"{time.time()}:{uuid.uuid4().hex}"
    signature = sign_tenant_request(app.identity, "alpha", nonce, body)
    principal = app.directory.authenticate_agent("alpha", "worker", nonce, body, signature)
    session = app.kernel.session(principal)
    accepted = session.submit_task(body, nonce=nonce)
    owner = principal_owner(principal)
    approval_id = None
    if approval:
        with pytest.raises(GovernanceError) as denied:
            app.kernel._admit_queued_intent("alpha", owner, task_id, accepted["intent_sha256"])
        approval_id = denied.value.approval_id
        assert approval_id is not None
        assert app.admin.approve(approval_id)
    admitted = app.kernel._admit_queued_intent("alpha", owner, task_id, accepted["intent_sha256"])
    refs = ("alpha", owner, task_id, accepted["intent_sha256"], admitted["link_sha256"])
    return SimpleNamespace(session=session, accepted=accepted, admitted=admitted, refs=refs,
                           action=canonical_demo_action(submission["wire"]), operation_id=operation_id,
                           initial_events=session.task_events(task_id), approval_id=approval_id)


def _rows(path, table):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
            return []
        return [dict(row) for row in db.execute("SELECT * FROM " + table)]


def _effects(app):
    return _rows(app.config["descriptor"]["path"], "ab_queued_effects_v2")


def _assert_unknown(app, task, *, effects):
    assert len(_effects(app)) == effects
    operation = app.runtime.operations.get("worker", task.operation_id)
    budget = app.runtime.store.get_budget("worker")
    assert operation["state"] == "unknown"
    assert budget["spent"] == 0
    assert budget["reserved"] == {task.admitted["reservation_token"]: 2}
    assert len(_rows(app.config["tenant_path"], "task_execution_decisions_v1")) == 1
    assert _rows(app.config["tenant_path"], "task_execution_results_v1") == []


def _assert_success(app, task):
    effects = _effects(app)
    assert len(effects) == 1
    assert effects[0]["action_bytes"] == task.action
    assert effects[0]["action_sha256"] == hashlib.sha256(task.action).hexdigest()
    assert app.runtime.operations.get("worker", task.operation_id)["state"] == "succeeded"
    budget = app.runtime.store.get_budget("worker")
    assert budget["spent"] == 2 and budget["reserved"] == {}
    assert len(_rows(app.config["tenant_path"], "task_execution_decisions_v1")) == 1
    assert len(_rows(app.config["tenant_path"], "task_execution_results_v1")) == 1
    events = app.runtime.tasks.events(task.refs[1], task.refs[2])
    assert events[:2] == task.initial_events
    assert events[-1].state == TaskState.COMPLETED
    assert [event.sequence for event in events] == list(range(len(events)))
    assert app.runtime.task_intents.get(task.refs[1], task.refs[2]) == task.accepted


def test_real_signed_dispatch_persists_one_exact_effect_attempt_result_and_charge(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app, value="\U0001f33f" * 256)
    assert task.initial_events[-1].state == TaskState.WORKING
    assert _effects(app) == []
    monkeypatch.setattr("src.proxy.transport.invoke_target", lambda *_a, **_k: pytest.fail("generic transport invoked"))
    result = app.kernel._dispatch_queued_once(*task.refs)
    assert result["state"] == "succeeded"
    _assert_success(app, task)
    decision = app.runtime.task_executions.decision(task.refs[1], task.refs[2])
    stored = app.runtime.task_executions.result(task.refs[1], task.refs[2])
    assert decision["kind"] == "attempt"
    assert decision["admission_link_sha256"] == task.admitted["link_sha256"]
    assert len(json.dumps(stored, sort_keys=True, separators=(",", ":")).encode()) <= task.accepted["result_limit_bytes"]
    for method in (app.kernel._dispatch_queued_once, app.kernel._recover_queued):
        assert method(*task.refs)["state"] == "succeeded"
        _assert_success(app, task)


def test_independent_authority_tenant_connections_restart_without_resend(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"
    restarted = _open(app.config)
    try:
        assert restarted.runtime.store._db is not app.runtime.store._db
        assert restarted.directory.store._db is not app.directory.store._db
        monkeypatch.setattr(restarted.adapter, "commit", lambda *_: pytest.fail("restart must not resend"))
        assert restarted.kernel._recover_queued(*task.refs)["state"] == "succeeded"
        assert restarted.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"
        _assert_success(restarted, task)
    finally:
        _close(restarted)


def test_concurrent_independent_kernels_share_exactly_one_dispatch_decision(dispatch_app):
    app = dispatch_app
    task = _admit(app)
    other = _open(app.config)
    barrier = threading.Barrier(2)
    calls, call_lock = [], threading.Lock()
    for handle in (app, other):
        original = handle.adapter.commit
        def commit(authorization, action_bytes, original=original):
            with call_lock:
                calls.append(authorization["attempt_id"])
            return original(authorization, action_bytes)
        handle.adapter.commit = commit
    def dispatch(handle):
        barrier.wait(timeout=5)
        return handle.kernel._dispatch_queued_once(*task.refs)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(dispatch, handle) for handle in (app, other)]
            results = [future.result(timeout=20) for future in futures]
        assert all(result["state"] in ("unknown", "succeeded") for result in results)
        assert any(result["state"] == "succeeded" for result in results)
        assert len(calls) == 1
        _assert_success(app, task)
        _assert_success(other, task)
    finally:
        _close(other)


def test_local_dropped_return_after_real_commit_recovers_by_readback(dispatch_app, monkeypatch):
    """A local callback drops the return; this is not a transport-loss test."""
    app = dispatch_app
    task = _admit(app)
    original = app.adapter.commit
    def drop_return(authorization, action_bytes):
        original(authorization, action_bytes)
        raise TimeoutError("local test dropped committed destination return")
    monkeypatch.setattr(app.adapter, "commit", drop_return)
    # The live dispatcher may immediately read back or report UNKNOWN for a
    # later recovery; either preserves exactly one committed effect.
    result = app.kernel._dispatch_queued_once(*task.refs)
    assert result["state"] in ("unknown", "succeeded")
    assert len(_effects(app)) == 1
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("lost return cannot trigger resend"))
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_success(app, task)


def test_missing_independent_readback_preserves_unknown_and_held_exposure(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    original_observe = app.adapter.observe
    monkeypatch.setattr(app.adapter, "observe", lambda *_: (_ for _ in ()).throw(ObservationUnavailable("local injected readback outage")))
    result = app.kernel._dispatch_queued_once(*task.refs)
    assert result["state"] == "unknown"
    _assert_unknown(app, task, effects=1)
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("readback outage cannot trigger resend"))
    assert app.kernel._recover_queued(*task.refs)["state"] == "unknown"
    _assert_unknown(app, task, effects=1)
    monkeypatch.setattr(app.adapter, "observe", original_observe)
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_success(app, task)


def test_local_result_insert_failure_rolls_back_all_local_participants(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    original_insert = app.runtime.task_executions.insert_result
    def fail_after_insert(record):
        original_insert(record)
        raise RuntimeError("local injected failure after result INSERT")
    monkeypatch.setattr(app.runtime.task_executions, "insert_result", fail_after_insert)
    result = app.kernel._dispatch_queued_once(*task.refs)
    assert result["state"] == "unknown"
    _assert_unknown(app, task, effects=1)
    monkeypatch.setattr(app.runtime.task_executions, "insert_result", original_insert)
    monkeypatch.setattr(app.adapter, "commit", lambda *_: pytest.fail("settlement rollback cannot trigger resend"))
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    _assert_success(app, task)


@pytest.mark.parametrize("dispatch_app", [1], indirect=True)
@pytest.mark.parametrize("stage", ["after-marker", "after-effect", "before-marker-commit", "after-result-insert", "after-local-commit"])
def test_real_process_death_recovers_by_readback_and_never_resends(dispatch_app, tmp_path, stage):
    app = dispatch_app
    task = _admit(app)
    config_path = tmp_path / "disposable-child-config.json"
    config_path.write_text(json.dumps({**app.config, "refs": task.refs}), encoding="utf-8")
    command = [sys.executable, "-c", _CHILD_CRASH_SCRIPT, str(config_path), stage]
    # This is a real child process with the same configured issuer verifier,
    # existing enrolled authority/tenant files and independently reopened SQL.
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert completed.returncode == CRASH_RETURN_CODES[stage], (completed.stdout, completed.stderr)
    if stage == "before-marker-commit":
        assert _effects(app) == []
        assert app.runtime.task_executions.decision(task.refs[1], task.refs[2]) is None
        assert app.runtime.task_executions.result(task.refs[1], task.refs[2]) is None
        assert app.runtime.store.get_budget("worker")["reserved"] == {task.admitted["reservation_token"]: 2}
        assert app.runtime.store.get_budget("worker")["spent"] == 0
        assert app.runtime.operations.get("worker", task.operation_id)["state"] == "unknown"
    elif stage == "after-local-commit":
        _assert_success(app, task)
    else:
        _assert_unknown(app, task, effects=0 if stage == "after-marker" else 1)
    decision_before = app.runtime.task_executions.decision(task.refs[1], task.refs[2])
    result_before = app.runtime.task_executions.result(task.refs[1], task.refs[2])
    restarted = _open(app.config)
    try:
        original_acquire, original_commit = restarted.adapter.acquire, restarted.adapter.commit
        attempted_calls = []
        def forbidden(*_):
            attempted_calls.append("forbidden-retry")
            raise AssertionError("process death never authorizes a resend")
        restarted.adapter.acquire = restarted.adapter.commit = forbidden
        recovery = restarted.kernel._recover_queued(*task.refs)
        if stage in ("after-effect", "after-result-insert", "after-local-commit"):
            assert recovery["state"] == "succeeded"
            _assert_success(restarted, task)
        elif stage == "after-marker":
            assert recovery["state"] == "unknown"
            _assert_unknown(restarted, task, effects=0)
            assert restarted.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
            _assert_unknown(restarted, task, effects=0)
        else:
            assert recovery["state"] == "unknown"
            assert restarted.runtime.task_executions.decision(task.refs[1], task.refs[2]) is None
            # The uncommitted marker grants no send capability. Its separately
            # acquired orphan lease remains authoritative until real expiry.
            leases = _rows(app.config["descriptor"]["path"], "ab_destination_fences")
            remaining = max(0, max(row["expires_seconds"] for row in leases) - time.time())
            assert remaining <= 3
            time.sleep(remaining + 0.05)
            restarted.adapter.acquire, restarted.adapter.commit = original_acquire, original_commit
            assert restarted.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"
            _assert_success(restarted, task)
        assert attempted_calls == []
        if decision_before is not None:
            assert restarted.runtime.task_executions.decision(task.refs[1], task.refs[2]) == decision_before
        if result_before is not None:
            assert restarted.runtime.task_executions.result(task.refs[1], task.refs[2]) == result_before
    finally:
        _close(restarted)


@pytest.mark.parametrize("limit", [1, 65535])
def test_small_original_result_allowance_closes_before_any_attempt(dispatch_app, limit):
    app = dispatch_app
    app.admin.set_task_intent_capacity(**asdict(replace(IntentLimits(), max_result_bytes=limit)))
    task = _admit(app)
    result = app.kernel._dispatch_queued_once(*task.refs)
    assert result["state"] == "closed"
    assert _effects(app) == []
    assert app.runtime.operations.get("worker", task.operation_id)["state"] == "failed"
    assert app.runtime.store.get_budget("worker")["reserved"] == {}
    assert app.runtime.store.get_budget("worker")["spent"] == 0
    decision = app.runtime.task_executions.decision(task.refs[1], task.refs[2])
    assert decision["kind"] == "closed"
    assert app.runtime.task_executions.result(task.refs[1], task.refs[2]) is None


def test_cancel_before_dispatch_closes_without_effect_and_cannot_reopen(dispatch_app):
    app = dispatch_app
    task = _admit(app)
    result = app.kernel._cancel_queued(*task.refs, reason="operator canceled before first attempt")
    assert result["state"] == "closed"
    assert _effects(app) == []
    assert app.runtime.store.get_budget("worker")["reserved"] == {}
    assert app.runtime.store.get_budget("worker")["spent"] == 0
    assert app.runtime.tasks.get(task.refs[1], task.refs[2]).state == TaskState.CANCELED
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "closed"
    assert _effects(app) == []


def test_wrong_exact_reference_cannot_dispatch_other_admission(dispatch_app):
    app = dispatch_app
    task = _admit(app)
    for position in (1, 2, 3, 4):
        refs = list(task.refs)
        refs[position] = "0" * 64 if position in (1, 3, 4) else "another-task"
        with pytest.raises((AuthorityDenied, ValueError)):
            app.kernel._dispatch_queued_once(*refs)
    assert _effects(app) == []
    assert app.runtime.store.get_budget("worker")["reserved"] == {task.admitted["reservation_token"]: 2}


def test_marker_transaction_audit_failure_prevents_call_and_rolls_back_decision(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    original_audit = app.runtime.audit.record
    before_head = app.runtime.store.load_audit_head()
    calls = []
    def fail_marker_audit(*args, **kwargs):
        result = original_audit(*args, **kwargs)
        if kwargs.get("action") == "task.attempt-committed":
            raise RuntimeError("local injected marker audit failure")
        return result
    def forbidden_commit(*_):
        calls.append("commit")
        raise AssertionError("uncommitted marker cannot authorize a destination call")
    monkeypatch.setattr(app.runtime.audit, "record", fail_marker_audit)
    monkeypatch.setattr(app.adapter, "commit", forbidden_commit)
    with pytest.raises(RuntimeError, match="marker audit failure"):
        app.kernel._dispatch_queued_once(*task.refs)
    assert calls == [] and _effects(app) == []
    assert app.runtime.task_executions.decision(task.refs[1], task.refs[2]) is None
    assert app.runtime.task_executions.result(task.refs[1], task.refs[2]) is None
    assert app.runtime.store.load_audit_head() == before_head
    assert app.runtime.store.get_budget("worker")["reserved"] == {task.admitted["reservation_token"]: 2}
    assert app.runtime.store.get_budget("worker")["spent"] == 0
    assert app.runtime.operations.get("worker", task.operation_id)["state"] == "unknown"
    assert app.runtime.tasks.events(task.refs[1], task.refs[2]) == task.initial_events


def test_existing_attempt_and_recovery_never_acquire_or_call_destination_again(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    original_acquire = app.adapter.acquire
    calls = []
    def acquire(scope, owner):
        calls.append("acquire")
        return original_acquire(scope, owner)
    def stop_at_entry(*_):
        calls.append("commit-entry")
        raise TimeoutError("local test stopped at destination call entry")
    monkeypatch.setattr(app.adapter, "acquire", acquire)
    monkeypatch.setattr(app.adapter, "commit", stop_at_entry)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    _assert_unknown(app, task, effects=0)
    assert calls == ["acquire", "commit-entry"]
    def forbidden(*_):
        calls.append("forbidden-retry")
        raise AssertionError("existing marker cannot acquire a lease or resend")
    monkeypatch.setattr(app.adapter, "acquire", forbidden)
    monkeypatch.setattr(app.adapter, "commit", forbidden)
    for method in (app.kernel._recover_queued, app.kernel._dispatch_queued_once, app.kernel._recover_queued):
        assert method(*task.refs)["state"] == "unknown"
    assert calls == ["acquire", "commit-entry"]
    _assert_unknown(app, task, effects=0)


def test_consumed_exact_admission_approval_does_not_trigger_second_admission(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app, approval=True)
    approval = app.runtime.store.get_approval(task.approval_id)
    assert task.admitted["approval_required"] is True
    assert (approval["agent_id"], approval["capability"], approval["status"]) == (
        "worker", "write|" + task.admitted["action_sha256"], "consumed")
    assert len(_rows(app.config["tenant_path"], "approvals")) == 1
    prohibited_calls = []
    def prohibited(*_args, **_kwargs):
        prohibited_calls.append("second-admission")
        raise AssertionError("dispatch cannot admit, reserve or consume an approval again")
    for component, method in (
        (app.runtime.policy, "authorize"), (app.runtime.budgets, "get"), (app.runtime.budgets, "can_afford"),
        (app.runtime.budgets, "reserve"), (app.runtime.approvals, "request"), (app.runtime.approvals, "consume"),
        (app.runtime.approvals, "is_granted"), (app.runtime.operations, "claim"),
    ):
        monkeypatch.setattr(component, method, prohibited)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"
    assert app.kernel._recover_queued(*task.refs)["state"] == "succeeded"
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "succeeded"
    assert prohibited_calls == []
    _assert_success(app, task)
    assert app.runtime.store.get_approval(task.approval_id) == approval
    assert len(_rows(app.config["tenant_path"], "approvals")) == 1
    assert len(app.runtime.store.get_budget("worker")["calls"]) == 1
