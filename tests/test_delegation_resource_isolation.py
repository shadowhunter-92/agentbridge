"""Delegated agent/scope boundaries must survive status and history lookup."""

import hashlib
import json
import time

import httpx
import pytest

from src.api.tenant_control_plane import create_tenant_app
from src.governance.authority import AuthorityDenied
from src.governance.identity import AgentIdentity
from src.governance.tenant_kernel import binding_owner, principal_owner
from src.protocols.task_lifecycle import LifecycleRejected, TaskLifecycle, TaskState
from tests.test_authority import ISSUER, agent_request
from tests.test_authority import authority as authority
from tests.test_tenant_http import signed
from tests.test_tenant_kernel import signed_session
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


@pytest.fixture
def scoped_history(tenant_app):
    kernel, admins, agents, token, directory, owner = tenant_app
    admins["alpha"].enroll_agent(
        "worker", agents["alpha"].public_key_hex, capabilities=("read", "write"), targets=("ledger", "reports")
    )
    directory.enroll_member(
        owner,
        "alpha",
        ISSUER,
        "human",
        role="tenant_operator",
        capabilities=("read", "write"),
        targets=("ledger", "reports"),
    )
    user = directory.authenticate_operator(ISSUER, token("human", tenant="alpha"), tenant_id="alpha")

    def grant(*, agent="worker", capabilities=("read", "write"), targets=("ledger", "reports")):
        return directory.grant_delegation(
            admins["alpha"].principal,
            user,
            agent,
            capabilities=capabilities,
            targets=targets,
            expires_at=time.time() + 600,
        )

    original = grant()
    session, body, nonce = signed_session(tenant_app, delegation=original, operation="protected-operation-12345")
    return tenant_app, grant, session, body, nonce


async def seed(history):
    app, _, session, body, nonce = history
    await session.route(body, nonce=nonce)
    runtime = app[0]._runtimes["alpha"]
    runtime.tasks.create(principal_owner(session.principal), TaskLifecycle("protected-task", "private-context", "a2a"))
    runtime.tasks.transition(
        principal_owner(session.principal), "protected-task", TaskState.WORKING, expected_sequence=0
    )
    return runtime


def resource_request(resource):
    if resource == "operation":
        return "/v2/operations/read", {"request_scope": "operation.read", "operation_id": "protected-operation-12345"}
    if resource == "task":
        return "/v2/tasks/read", {"request_scope": "task.read", "task_id": "protected-task"}
    return "/v2/tasks/events", {"request_scope": "task.events", "task_id": "protected-task"}


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["operation", "task", "events"])
@pytest.mark.parametrize("narrowing", ["capability", "target"])
async def test_narrow_grant_cannot_read_broader_history_http(scoped_history, monkeypatch, resource, narrowing):
    await seed(scoped_history)
    app, grant, *_ = scoped_history
    narrow = grant(**({"capabilities": ("read",)} if narrowing == "capability" else {"targets": ("ledger",)}))
    monkeypatch.setenv("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")
    http_app = create_tenant_app(app[0])
    path, data = resource_request(resource)
    raw, headers = signed(app, data=data, delegation=narrow)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http_app), base_url="http://local") as client:
        response = await client.post(path, content=raw, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "resource or authority unavailable"}


@pytest.mark.asyncio
async def test_same_scope_replacement_grant_and_machine_workflows_remain_valid(scoped_history):
    runtime = await seed(scoped_history)
    app, grant, original, *_ = scoped_history
    renewed = grant(capabilities=("write", "read"), targets=("reports", "ledger"))
    session, _, _ = signed_session(app, delegation=renewed)
    assert original.principal.delegation_id != session.principal.delegation_id
    assert principal_owner(original.principal) == principal_owner(session.principal)
    assert session.operation("worker", "protected-operation-12345")["state"] == "succeeded"
    assert session.task("protected-task").context_id == "private-context"
    assert [row.sequence for row in session.task_events("protected-task")] == [0, 1]
    assert [row.sequence for row in session.task_events("protected-task", after_sequence=0, limit=1)] == [1]
    for state in ("unknown", "failed", "succeeded"):
        runtime.operations.finish("worker", "protected-operation-12345", state)
        assert session.operation("worker", "protected-operation-12345")["state"] == state
    machine, body, nonce = signed_session(app, operation="machine-operation-123456")
    await machine.route(body, nonce=nonce)
    runtime.tasks.create(principal_owner(machine.principal), TaskLifecycle("machine-task", "machine-context", "a2a"))
    assert machine.principal.delegation_id is None
    assert machine.operation("worker", "machine-operation-123456")["state"] == "succeeded"
    assert machine.task("machine-task").context_id == "machine-context"
    with pytest.raises(AuthorityDenied):
        session.operation("worker", "machine-operation-123456")
    with pytest.raises(LifecycleRejected):
        session.task("machine-task")
    assert app[1]["alpha"].operation("worker", "protected-operation-12345")["state"] == "succeeded"


@pytest.mark.asyncio
async def test_different_agent_cannot_inherit_same_humans_scope_history(scoped_history):
    await seed(scoped_history)
    app, grant, *_ = scoped_history
    identity = AgentIdentity.generate("other-worker")
    app[1]["alpha"].enroll_agent(
        identity.agent_id, identity.public_key_hex, capabilities=("read", "write"), targets=("ledger", "reports")
    )
    delegated = grant(agent=identity.agent_id)
    context = agent_request(app[4], identity=identity, delegation=delegated)
    session = app[0].session(context)
    with pytest.raises(AuthorityDenied):
        session.operation("worker", "protected-operation-12345")
    with pytest.raises(LifecycleRejected):
        session.task("protected-task")
    with pytest.raises(LifecycleRejected):
        session.task_events("protected-task")


def test_owner_projection_is_canonical_and_rejects_incomplete_material(tenant_app):
    session, _, _ = signed_session(tenant_app)
    binding = session.principal.binding()
    equivalent = {
        **binding,
        "capabilities": list(reversed(binding["capabilities"])),
        "targets": list(reversed(binding["targets"])),
    }
    assert binding_owner(equivalent) == principal_owner(session.principal)
    assert binding_owner({**binding, "delegation_id": "replacement", "revision": 999}) == binding_owner(binding)
    for field in ("kind", "agent_id", "capabilities", "targets", "tenant_id", "issuer", "subject"):
        malformed = dict(binding)
        malformed.pop(field)
        with pytest.raises(AuthorityDenied):
            binding_owner(malformed)
    for bad in ({"capabilities": "read"}, {"targets": [{}]}, {"kind": "tenant_admin"}, {"agent_id": None}):
        with pytest.raises(AuthorityDenied):
            binding_owner({**binding, **bad})
    with pytest.raises(AuthorityDenied):
        binding_owner(None)


def test_legacy_opaque_task_owners_fail_closed_without_deleting_history(tenant_app):
    session, _, _ = signed_session(tenant_app)
    p = session.principal
    old = hashlib.sha256(
        json.dumps([p.tenant_id, "machine", p.issuer, p.subject], separators=(",", ":")).encode()
    ).hexdigest()
    tasks = tenant_app[0]._runtimes["alpha"].tasks
    tasks.create(old, TaskLifecycle("legacy-task", "preserved-context", "a2a"))
    with pytest.raises(LifecycleRejected):
        session.task("legacy-task")
    with pytest.raises(LifecycleRejected):
        session.task_events("legacy-task")
    assert tasks.get(old, "legacy-task").context_id == "preserved-context"
