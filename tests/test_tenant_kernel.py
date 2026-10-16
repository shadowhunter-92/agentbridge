"""Tenant facade uses one kernel and preserves ownership through admission."""

import asyncio
import json
import time
import uuid

import pytest

from src.api.trusted_targets import SecurityConfigurationError
from src.governance.authority import AuthorityDenied, sign_tenant_request
from src.governance.gateway import GovernanceError
from src.governance.identity import AgentIdentity
from src.governance.operation_ledger import OperationConflict
from src.governance.rbac import AccessDenied
from src.governance.tenant_kernel import TenantKernel, principal_owner
from src.protocols.task_lifecycle import LifecycleRejected, TaskLifecycle, TaskState
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_store import namespaces as namespaces


@pytest.fixture
def tenant_app(authority, namespaces, monkeypatch):
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    directory, owner, token, _, _ = authority
    kernel = TenantKernel(
        directory,
        {"alpha": namespaces("alpha"), "beta": namespaces("beta")},
        costs={"alpha": {"read": 1, "write": 2}, "beta": {"read": 1, "write": 2}},
    )
    admins = {
        t: kernel.session(directory.authenticate_operator(ISSUER, token("administrator", tenant=t), tenant_id=t))
        for t in ("alpha", "beta")
    }
    agents = {t: AgentIdentity.generate("worker") for t in admins}
    for tenant, admin in admins.items():
        admin.enroll_agent("worker", agents[tenant].public_key_hex, capabilities=("read", "write"), targets=("ledger",))
        admin.set_budget("worker", spend_limit=10)
    return kernel, admins, agents, token, directory, owner


def signed_session(app, tenant="alpha", *, operation="same-operation-123456", delegation=None, **extra):
    kernel, _, agents, _, directory, _ = app
    body = json.dumps(
        {
            "src": "mcp",
            "dst": "mcp",
            "operation_id": operation,
            "wire": {"method": "tools/call", "params": {"name": "read", "arguments": {}}},
            **extra,
        }
    ).encode()
    nonce = f"{time.time()}:{uuid.uuid4().hex}"
    signature = sign_tenant_request(agents[tenant], tenant, nonce, body, delegation_id=delegation)
    principal = directory.authenticate_agent(tenant, "worker", nonce, body, signature, delegation_id=delegation)
    return kernel.session(principal), body, nonce


@pytest.mark.asyncio
async def test_same_agent_and_operation_ids_do_not_cross_tenants(tenant_app):
    a, body_a, nonce_a = signed_session(tenant_app)
    b, body_b, nonce_b = signed_session(tenant_app, "beta")
    results = await asyncio.gather(a.route(body_a, nonce=nonce_a), b.route(body_b, nonce=nonce_b))
    assert all("translated_wire" in r for r in results)
    assert a.operation("worker", "same-operation-123456")["state"] == "succeeded"
    assert b.operation("worker", "same-operation-123456")["state"] == "succeeded"
    assert (
        a.operation("worker", "same-operation-123456")["fingerprint"]
        != b.operation("worker", "same-operation-123456")["fingerprint"]
    )
    with pytest.raises(AuthorityDenied):
        tenant_app[0].session(a.principal, tenant_id="beta")
    assert tenant_app[1]["alpha"].get_budget("worker")["spent"] == 1
    assert tenant_app[1]["beta"].get_budget("worker")["spent"] == 1


@pytest.mark.asyncio
async def test_direct_gateway_and_policy_cannot_take_other_tenants_context(tenant_app):
    a, body, nonce = signed_session(tenant_app)
    beta = tenant_app[0]._runtimes["beta"]
    decision = beta.policy.authorize(agent_id="worker", capability="read", principal=a.principal)
    assert not decision.allowed
    effects = []

    async def invoke(wire):
        effects.append(wire)

    with pytest.raises(AuthorityDenied):
        await beta.gateway.route_call(
            agent_id="worker",
            src_proto="mcp",
            dst_proto="mcp",
            src_wire=json.loads(body)["wire"],
            operation_id="same-operation-123456",
            invoke=invoke,
            signed_body=body,
            signed_nonce=nonce,
            principal=a.principal,
        )
    assert effects == [] and beta.budgets.get("worker").spent == 0


@pytest.mark.asyncio
async def test_signed_conflicting_tenant_hint_rejected_before_mutation(tenant_app):
    session, body, nonce = signed_session(tenant_app, tenant_id="beta")
    runtime = tenant_app[0]._runtimes["alpha"]
    before = runtime.audit.count()
    with pytest.raises(AuthorityDenied):
        await session.route(body, nonce=nonce)
    assert runtime.operations.get("worker", "same-operation-123456") is None
    assert runtime.budgets.get("worker").reserved == 0
    assert runtime.approvals.pending() == [] and runtime.audit.count() == before


def test_operator_roles_and_exports_are_scoped(tenant_app):
    kernel, admins, _, token, directory, owner = tenant_app
    directory.enroll_member(owner, "alpha", ISSUER, "viewer", role="tenant_viewer")
    viewer = kernel.session(directory.authenticate_operator(ISSUER, token("viewer", tenant="alpha"), tenant_id="alpha"))
    assert len(viewer.list_identities()) == 1
    with pytest.raises(AccessDenied):
        viewer.set_budget("worker", spend_limit=100)
    with pytest.raises(AccessDenied):
        viewer.export_audit()
    with pytest.raises(AuthorityDenied):
        kernel.session(viewer.principal, tenant_id="beta")
    alpha_records = [json.loads(line) for line in admins["alpha"].export_audit().splitlines()]
    assert alpha_records
    for record in alpha_records:
        binding = json.loads(record["actor"].removeprefix("principal:v1:"))
        assert binding["tenant_id"] == "alpha"


def human_grant(app, user="human"):
    kernel, admins, _, token, directory, owner = app
    if user != "human":
        directory.enroll_member(
            owner, "alpha", ISSUER, user, role="tenant_operator", capabilities=("read",), targets=("ledger",)
        )
    principal = directory.authenticate_operator(ISSUER, token(user, tenant="alpha"), tenant_id="alpha")
    return directory.grant_delegation(
        admins["alpha"].principal,
        principal,
        "worker",
        capabilities=("read",),
        targets=("ledger",),
        expires_at=time.time() + 600,
    )


@pytest.mark.asyncio
async def test_approval_and_operation_ownership_bind_delegated_human(tenant_app):
    _, admins, _, _, _, _ = tenant_app
    admins["alpha"].mark_sensitive("read")
    first_grant = human_grant(tenant_app)
    second_grant = human_grant(tenant_app, "other-human")
    first, body, nonce = signed_session(tenant_app, delegation=first_grant)
    with pytest.raises(GovernanceError) as denied:
        await first.route(body, nonce=nonce)
    approval = denied.value.approval_id
    assert admins["alpha"].approve(approval)
    second, other_body, other_nonce = signed_session(tenant_app, delegation=second_grant)
    with pytest.raises(GovernanceError) as other_denied:
        await second.route(other_body, nonce=other_nonce)
    assert other_denied.value.approval_id != approval
    renewed, body, nonce = signed_session(tenant_app, delegation=first_grant)
    assert "translated_wire" in await renewed.route(body, nonce=nonce)
    assert renewed.operation("worker", "same-operation-123456")["authority"]["subject"] == "human"
    with pytest.raises(AuthorityDenied):
        second.operation("worker", "same-operation-123456")
    with pytest.raises(OperationConflict):
        await second.route(other_body, nonce=other_nonce)


@pytest.mark.asyncio
async def test_revoked_delegation_cannot_consume_approved_request(tenant_app):
    kernel, admins, _, _, directory, owner = tenant_app
    admins["alpha"].mark_sensitive("read")
    grant = human_grant(tenant_app)
    session, body, nonce = signed_session(tenant_app, delegation=grant)
    with pytest.raises(GovernanceError) as denied:
        await session.route(body, nonce=nonce)
    approval = denied.value.approval_id
    assert admins["alpha"].approve(approval)
    directory.revoke_delegation(owner, "alpha", grant)
    with pytest.raises(AuthorityDenied):
        await session.route(body, nonce=nonce)
    runtime = kernel._runtimes["alpha"]
    assert runtime.store.get_approval(approval)["status"] == "approved"
    assert runtime.budgets.get("worker").spent == runtime.budgets.get("worker").reserved == 0
    assert runtime.operations.get("worker", "same-operation-123456") is None


def test_budget_reconfiguration_preserves_unknown_exposure(tenant_app):
    kernel, admins, _, _, _, _ = tenant_app
    runtime = kernel._runtimes["alpha"]
    token, _ = runtime.budgets.reserve("worker", 7)
    runtime.operations.claim("worker", "unknown-operation-1234", "fingerprint", reservation_token=token)
    admins["alpha"].set_budget("worker", spend_limit=8, rate_limit=500)
    state = admins["alpha"].get_budget("worker")
    assert state["reserved"] == {token: 7} and state["rate_limit"] == 500
    with pytest.raises(ValueError, match="outstanding exposure"):
        admins["alpha"].set_budget("worker", spend_limit=6)
    assert admins["alpha"].get_budget("worker")["reserved"] == {token: 7}


def test_task_snapshot_and_events_require_current_tenant_owner(tenant_app):
    kernel, _, _, _, directory, owner = tenant_app
    a, _, _ = signed_session(tenant_app)
    b, _, _ = signed_session(tenant_app, "beta")
    for session in (a, b):
        kernel._runtimes[session.tenant_id].tasks.create(
            principal_owner(session.principal), TaskLifecycle("same-task", "context", "a2a")
        )
    kernel._runtimes["alpha"].tasks.transition(
        principal_owner(a.principal), "same-task", TaskState.WORKING, expected_sequence=0
    )
    assert a.task("same-task").state == TaskState.WORKING
    assert b.task("same-task").state == TaskState.SUBMITTED
    human, _, _ = signed_session(tenant_app, delegation=human_grant(tenant_app))
    with pytest.raises(LifecycleRejected):
        human.task("same-task")
    directory.revoke_agent(owner, "alpha", "worker")
    with pytest.raises(AuthorityDenied):
        a.task_events("same-task")


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["prod", "production"])
async def test_production_target_gate_remains_intact(tenant_app, monkeypatch, environment):
    old, _, agents, token, directory, owner = tenant_app
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    monkeypatch.setenv("AGENTBRIDGE_EGRESS_PROXY_URL", "http://proxy.example.test:3128")
    record = {
        "protocol": "a2a",
        "kind": "a2a_http",
        "base_url": "https://destination.example.org",
        "capabilities": ["read"],
        "allowed_agents": ["worker"],
    }
    kernel = TenantKernel(
        directory,
        {t: r.store for t, r in old._runtimes.items()},
        costs={"alpha": {"read": 1}, "beta": {"read": 1}},
        targets={"alpha": {"ledger": record}},
    )
    app = (kernel, {}, agents, token, directory, owner)
    session, body, nonce = signed_session(app, target_id="ledger", dst="a2a")
    before = kernel._runtimes["alpha"].audit.count()
    with pytest.raises(SecurityConfigurationError, match="destination-atomic"):
        await session.route(body, nonce=nonce)
    assert kernel._runtimes["alpha"].audit.count() == before
    assert kernel._runtimes["alpha"].budgets.get("worker").reserved == 0
