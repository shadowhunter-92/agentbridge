"""A completed revocation cannot overtake a local tenant mutation."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.governance.authority import AuthorityDenied, AuthorityDirectory
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def test_revocation_waits_for_in_progress_budget_update(tenant_app, authority, monkeypatch):
    kernel, admins, _, token, directory, _ = tenant_app
    other = AuthorityDirectory(authority[3](), verifiers=directory.verifiers)
    owner = other.authenticate_operator(ISSUER, token("owner"))
    entered, release, revoking = threading.Event(), threading.Event(), threading.Event()
    original = kernel._runtimes["alpha"].store.mutate_budget

    def pause(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    def revoke():
        revoking.set()
        other.revoke_member(owner, "alpha", ISSUER, "administrator")

    monkeypatch.setattr(kernel._runtimes["alpha"].store, "mutate_budget", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        update = pool.submit(admins["alpha"].set_budget, "worker", spend_limit=12)
        try:
            assert entered.wait(5)
            revocation = pool.submit(revoke)
            assert revoking.wait(5)
            assert not threading.Event().wait(0.2)
            assert not revocation.done(), "revocation committed while prior mutation was still in progress"
        finally:
            release.set()
        update.result(timeout=5)
        revocation.result(timeout=5)
    with pytest.raises(AuthorityDenied):
        admins["alpha"].set_budget("worker", spend_limit=99)
    assert kernel._runtimes["alpha"].store.get_budget("worker")["spend_limit"] == 12


def test_nested_authority_transaction_cannot_upgrade_shared_lock(authority):
    directory, owner, _, _, _ = authority
    with directory.guard(owner):
        with pytest.raises(RuntimeError, match="cannot escalate"):
            directory.set_tenant(owner, "new-tenant", active=True)


def test_postgres_bootstrap_waits_without_holding_governance_schema_lock(authority, namespaces):
    import time

    from src.governance.operation_ledger import OperationLedger
    from src.governance.store import PostgresStore
    directory, owner, _, factory, _ = authority
    if not isinstance(directory.store, PostgresStore):
        pytest.skip("PostgreSQL cross-connection advisory lock ordering")
    other_store = factory()
    tenant_store = namespaces("alpha")
    pid = other_store._db.info.backend_pid
    with ThreadPoolExecutor(max_workers=1) as pool:
        with directory.guard(owner):
            starting = pool.submit(AuthorityDirectory, other_store, verifiers=directory.verifiers)
            deadline = time.monotonic()+2
            while time.monotonic() < deadline:
                row = directory.store._db.execute(
                    "SELECT 1 FROM pg_locks WHERE pid=%s AND locktype='advisory' "
                    "AND objid=911005 AND NOT granted", (pid,)
                ).fetchone()
                if row:
                    break
                threading.Event().wait(.01)
            assert row, "bootstrap did not reach the controlled authority-lock wait"
            # This must complete while bootstrap is waiting for our authority
            # guard; a reversed 911004 -> 911005 bootstrap order deadlocks here.
            OperationLedger(tenant_store)
        assert starting.result(timeout=5).store is other_store
