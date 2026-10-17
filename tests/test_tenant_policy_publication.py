"""Tenant policy publication is serialized with admission and audit-atomic."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.governance.audit import AuditLog
from src.governance.authority import AuthorityDenied, AuthorityDirectory
from src.governance.gateway import GovernanceError
from src.governance.policy_rules import DenyCapabilities
from src.governance.rbac import AccessDenied
from src.governance.store import PostgresStore
from src.governance.tenant_kernel import TenantKernel
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_kernel import signed_session
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def publish(session, operation):
    if operation=="sensitive":
        session.mark_sensitive("read")
    else:
        session.add_policy(DenyCapabilities(["read"]))


@pytest.mark.parametrize("operation", ["sensitive", "rule"])
def test_policy_writer_waits_for_in_progress_admission_guard(tenant_app, authority, namespaces, operation):
    kernel, _, _, token, directory, _=tenant_app
    if not isinstance(directory.store,PostgresStore):
        pytest.skip("PostgreSQL cross-connection shared/exclusive authority barrier")
    other=AuthorityDirectory(authority[3](),verifiers=directory.verifiers)
    replica=TenantKernel(other,{t:namespaces(t) for t in ("alpha","beta")},costs={t:{"read":1,"write":2} for t in ("alpha","beta")})
    admin=replica.session(other.authenticate_operator(ISSUER,token("administrator",tenant="alpha"),tenant_id="alpha"))
    admission=signed_session(tenant_app)[0]
    future=None
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            with directory.guard(admission.principal):
                future=pool.submit(publish,admin,operation)
                deadline=time.monotonic()+5
                while True:
                    blocked=directory.store._db.execute(
                        "SELECT %s=ANY(pg_blocking_pids(%s)) AS blocked",
                        (directory.store._db.info.backend_pid,other.store._db.info.backend_pid),
                    ).fetchone()["blocked"]
                    if blocked:
                        break
                    if future.done():
                        future.result()
                        pytest.fail("policy publication overtook the held admission guard")
                    assert time.monotonic()<deadline,"expected SQL blocking edge not observed"
                    time.sleep(.01)
                runtime=kernel._runtimes["alpha"]
                assert not runtime.approvals.requires_approval("read")
                assert runtime.rules.rules==[]
        finally:
            if future is not None:
                future.result(timeout=10)
    runtime=kernel._runtimes["alpha"]
    assert runtime.approvals.requires_approval("read") if operation=="sensitive" else len(runtime.rules.rules)==1


@pytest.mark.parametrize("operation", ["sensitive", "rule"])
def test_policy_and_its_audit_rollback_together(tenant_app, monkeypatch, operation):
    kernel, admins, *_=tenant_app
    runtime=kernel._runtimes["alpha"]
    before=runtime.audit.count()
    original=runtime.audit.record
    def fail_after_append(**kwargs):
        original(**kwargs)
        raise RuntimeError("abort after policy audit")
    monkeypatch.setattr(runtime.audit,"record",fail_after_append)
    with pytest.raises(RuntimeError,match="abort after policy audit"):
        publish(admins["alpha"],operation)
    assert not runtime.approvals.requires_approval("read")
    assert runtime.rules.rules==[]
    assert runtime.audit.count()==before
    assert AuditLog.verify_chain(runtime.store.load_audit(),require_genesis=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["sensitive", "rule"])
async def test_after_publication_new_admission_observes_policy(tenant_app, operation):
    kernel, admins, *_=tenant_app
    publish(admins["alpha"],operation)
    session,body,nonce=signed_session(tenant_app)
    with pytest.raises(GovernanceError):
        await session.route(body,nonce=nonce)
    runtime=kernel._runtimes["alpha"]
    assert runtime.operations.get("worker","same-operation-123456") is None
    assert runtime.budgets.get("worker").reserved==0
    assert AuditLog.verify_chain(runtime.store.load_audit(),require_genesis=True)


@pytest.mark.parametrize("operation", ["sensitive", "rule"])
def test_policy_write_never_upgrades_existing_read_guard(tenant_app, operation):
    kernel,admins,_,_,directory,_=tenant_app
    runtime=kernel._runtimes["alpha"]
    before=runtime.audit.count()
    with directory.guard(admins["alpha"].principal):
        with pytest.raises(RuntimeError,match="cannot escalate"):
            publish(admins["alpha"],operation)
    assert not runtime.approvals.requires_approval("read")
    assert runtime.rules.rules==[] and runtime.audit.count()==before


@pytest.mark.parametrize("operation", ["sensitive", "rule"])
@pytest.mark.parametrize("kind", ["machine", "viewer"])
def test_policy_publication_requires_operator_write_permission(tenant_app, operation, kind):
    kernel,_,_,token,directory,owner=tenant_app
    if kind=="machine":
        session=signed_session(tenant_app)[0]
    else:
        directory.enroll_member(owner,"alpha",ISSUER,"viewer",role="tenant_viewer")
        principal=directory.authenticate_operator(ISSUER,token("viewer",tenant="alpha"),tenant_id="alpha")
        session=kernel.session(principal)
    runtime=kernel._runtimes["alpha"]
    before=runtime.audit.count()
    with pytest.raises((AuthorityDenied,AccessDenied)):
        publish(session,operation)
    assert not runtime.approvals.requires_approval("read")
    assert runtime.rules.rules==[] and runtime.audit.count()==before
