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
