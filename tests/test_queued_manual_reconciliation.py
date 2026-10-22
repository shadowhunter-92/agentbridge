"""Manual review retains current operator authority through local commit."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.governance.authority import AuthorityDenied, AuthorityDirectory
from src.governance.operator_review import canonical_review_payload
from src.governance.reconciliation import Reconciliation
from src.governance.store import PostgresStore, sql_atomic
from src.governance.tenant_kernel import TenantKernel
from tests.test_queued_dispatch_execution import ISSUER, _admit, _assert_unknown, _public
from tests.test_queued_dispatch_execution import dispatch_app as dispatch_app
from tests.test_queued_dispatch_postgres import _assert_state, _task
from tests.test_queued_dispatch_postgres import authority as authority
from tests.test_queued_dispatch_postgres import namespaces as namespaces
from tests.test_queued_dispatch_postgres import pg_dispatch_app as pg_dispatch_app
from tests.test_queued_dispatch_postgres import tenant_app as tenant_app


def _review(app, task, monkeypatch):
    observe = app.adapter.observe
    monkeypatch.setattr(app.adapter, "observe", lambda *_: (_ for _ in ()).throw(RuntimeError("withheld for manual review")))
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    monkeypatch.setattr(app.adapter, "observe", observe)
    prepared = app.kernel._prepare_queued_reconciliation(app.admin, *task.refs[1:])
    signer = Ed25519PrivateKey.generate()
    monkeypatch.setenv("AGENTBRIDGE_RECONCILIATION_OPERATOR_KEYS_JSON", json.dumps({"reviewer": _public(signer)}))
    signature = signer.sign(canonical_review_payload({"reviewer": "reviewer", **prepared["review_material"]})).hex()
    return prepared["completion"], signature


def test_operator_revoked_after_entry_guard_cannot_commit_manual_review(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    completion, signature = _review(app, task, monkeypatch)
    app.directory.enroll_platform_admin(app.operator, ISSUER, "second-authorized-admin")
    record = Reconciliation.record_task
    def revoked_after_guard(instance, *args, **kwargs):
        # This hook is exactly after _reconcile_queued releases its entry guard.
        # Revoke through the real enrollment API, with an independently retained
        # second administrator so the last-administrator guard remains intact.
        app.directory.revoke_platform_admin(app.operator, ISSUER, "owner")
        return record(instance, *args, **kwargs)
    monkeypatch.setattr(Reconciliation, "record_task", revoked_after_guard)
    with pytest.raises(AuthorityDenied):
        app.kernel._reconcile_queued(app.admin, completion, reviewer="reviewer", reviewer_signature_hex=signature)
    _assert_unknown(app, task, effects=1)


def test_operator_expiring_after_settlement_audit_rolls_back_manual_review(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    completion, signature = _review(app, task, monkeypatch)
    audit = app.runtime.audit.record
    def expiry_after_audit(*args, **kwargs):
        value = audit(*args, **kwargs)
        if kwargs.get("action") == "task.verified-execution":
            monkeypatch.setattr(time, "time", lambda: app.operator.valid_until + 1)
        return value
    monkeypatch.setattr(app.runtime.audit, "record", expiry_after_audit)
    with pytest.raises(AuthorityDenied):
        app.kernel._reconcile_queued(app.admin, completion, reviewer="reviewer", reviewer_signature_hex=signature)
    _assert_unknown(app, task, effects=1)


def test_platform_resource_tenant_disabled_after_entry_cannot_commit_review(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    completion, signature = _review(app, task, monkeypatch)
    record = Reconciliation.record_task
    def disabled_after_guard(instance, *args, **kwargs):
        app.directory.set_tenant(app.operator, "alpha", active=False)
        return record(instance, *args, **kwargs)
    monkeypatch.setattr(Reconciliation, "record_task", disabled_after_guard)
    with pytest.raises(AuthorityDenied):
        app.kernel._reconcile_queued(app.admin, completion, reviewer="reviewer", reviewer_signature_hex=signature)
    _assert_unknown(app, task, effects=1)


def test_postgres_callback_namespace_is_preserved_for_manual_authority(pg_dispatch_app, monkeypatch):
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from tests.test_authority import ISSUER as PG_ISSUER
    app = pg_dispatch_app
    schema = app.directory.store._db.execute("SELECT current_schema() AS name").fetchone()["name"]
    parameters = app.directory.store._db.info.get_parameters()
    if app.directory.store._db.pgconn.password:
        parameters["password"] = app.directory.store._db.pgconn.password.decode()
    parameters["options"] = "-cstatement_timeout=10000 -clock_timeout=5000"
    def initialize(connection):
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
    store = PostgresStore(make_conninfo(**parameters), initialize_connection=initialize)
    try:
        directory = AuthorityDirectory(store, verifiers=app.directory.verifiers)
        target = app.config["descriptor"]
        kernel = TenantKernel(directory, {"alpha": app.runtime.store}, costs={"alpha": {"write": 2}},
            targets={"alpha": {"ledger": {**target, "capabilities": ["write"], "allowed_agents": ["worker"]}}},
            queued_dispatch_adapters={"alpha": {"ledger": app.adapter}})
        app.directory, app.kernel, app.runtime = directory, kernel, kernel._runtimes["alpha"]
        operator = directory.authenticate_operator(PG_ISSUER, app.token("administrator", tenant="alpha"), tenant_id="alpha")
        app.admin = kernel.session(operator)
        task = _task(app)
        completion, signature = _review(app, task, monkeypatch)
        assert app.kernel._reconcile_queued(app.admin, completion, reviewer="reviewer", reviewer_signature_hex=signature)["state"] == "succeeded"
        _assert_state(app, task, succeeded=True, effects=1)
    finally:
        store.close()


def test_postgres_platform_resource_tenant_disabled_after_entry_is_rechecked(pg_dispatch_app, monkeypatch):
    app = pg_dispatch_app
    task = _task(app)
    completion, signature = _review(app, task, monkeypatch)
    platform = app.kernel.session(app.owner, tenant_id="alpha")
    record = Reconciliation.record_task
    def disable_after_entry(instance, *args, **kwargs):
        app.directory.set_tenant(app.owner, "alpha", active=False)
        return record(instance, *args, **kwargs)
    monkeypatch.setattr(Reconciliation, "record_task", disable_after_entry)
    with pytest.raises(AuthorityDenied, match="tenant unavailable"):
        app.kernel._reconcile_queued(platform, completion, reviewer="reviewer", reviewer_signature_hex=signature)
    _assert_state(app, task, succeeded=False, effects=1)


def test_postgres_manual_session_cannot_borrow_another_tenants_principal(pg_dispatch_app):
    from src.governance.queued_manual_settlement import settlement_atomic
    from src.governance.tenant_kernel import TenantSession
    from tests.test_authority import ISSUER as PG_ISSUER
    app = pg_dispatch_app
    principal = app.directory.authenticate_operator(PG_ISSUER, app.token("administrator", tenant="beta"), tenant_id="beta")
    forged = TenantSession(app.kernel, principal, "alpha")
    with pytest.raises(AuthorityDenied, match="principal and resource tenant"):
        with settlement_atomic(app.kernel, app.runtime, forged):
            pytest.fail("cross-tenant operator scope reached settlement")


def test_postgres_manual_reader_rejects_later_namespace_configuration_drift(pg_dispatch_app):
    from psycopg import sql

    from src.governance.queued_manual_settlement import assert_authority_reader_configuration
    app = pg_dispatch_app
    schema = app.directory.store._db.execute("SELECT current_schema() AS name").fetchone()["name"]
    with app.directory.store._lock:
        app.directory.store._db.execute("SET search_path TO public")
        try:
            with pytest.raises(AuthorityDenied, match="configuration changed"):
                assert_authority_reader_configuration(app.kernel)
        finally:
            app.directory.store._db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))


def test_manual_review_cannot_return_from_an_uncommitted_outer_transaction(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    completion, signature = _review(app, task, monkeypatch)
    with sql_atomic(app.runtime.store):
        with pytest.raises(AuthorityDenied, match="own durable transaction"):
            app.kernel._reconcile_queued(app.admin, completion, reviewer="reviewer", reviewer_signature_hex=signature)
    _assert_unknown(app, task, effects=1)


@pytest.mark.parametrize("writer_connection", ["same-directory", "independent-directory"])
def test_postgres_manual_review_uses_one_fence_with_queued_writer_and_current_journal(pg_dispatch_app, monkeypatch, writer_connection):
    import src.governance.queued_manual_settlement as module
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
    task = _task(app)
    completion, signature = _review(app, task, monkeypatch)
    other = app if writer_connection == "same-directory" else app.reopen()
    fence_acquired, mutex_held, revoked = (threading.Event() for _ in range(3))
    check = module._independent_authority_current
    def after_fence(*args):
        fence_acquired.set()
        assert mutex_held.wait(timeout=4)
        # The writer owns its Python mutex and is queued on exclusive911005.
        # The independent bounded read must never wait on that Python mutex or
        # acquire another shared911005 on a second backend.
        assert not revoked.wait(timeout=0.2)
        return check(*args)
    monkeypatch.setattr(module, "_independent_authority_current", after_fence)
    def revoke():
        assert fence_acquired.wait(timeout=4)
        with other.directory.store._lock:
            mutex_held.set()
            other.directory.revoke_member(other.admin.principal, "alpha", app.admin.principal.issuer,
                                          app.admin.principal.subject)
        revoked.set()
    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(revoke)
        reviewed = executor.submit(app.kernel._reconcile_queued, app.admin, completion,
                                   reviewer="reviewer", reviewer_signature_hex=signature)
        assert reviewed.result(timeout=12)["state"] == "succeeded"
        writer.result(timeout=12)
    assert revoked.is_set()
    _assert_state(app, task, succeeded=True, effects=1)
    result = app.runtime.task_executions.result(task.refs[1], task.refs[2])
    assert result["operator_authority"] == json.loads(json.dumps(app.admin.principal.binding()))
