"""First-admission ownership, approval and durable history contracts."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from src.governance.authority import AuthorityDenied, AuthorityDirectory
from src.governance.gateway import GovernanceError
from src.governance.store import PostgresStore, sql_atomic
from src.governance.tenant_kernel import TenantKernel, principal_owner
from src.protocols.task_lifecycle import TaskState
from tests.test_authority import authority as authority
from tests.test_queued_intent_preparation import accepted, prepare
from tests.test_task_admission import admit, snapshot
from tests.test_task_intents import TARGETS, authenticated, count, submission
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import human_grant, signed_session
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def action_scopes(session, record, *, task_id=None, intent_sha256=None):
    action = record["submission"]
    original = digest({
        "agent_id": session.principal.agent_id,
        "src": action["src"], "dst": action["dst"], "wire": action["wire"],
        "cost": record["provenance"]["operator_cost"], "target_id": action["target_id"],
        "operation_id": action["operation_id"], "authority": session.principal.binding(),
    })
    queued = digest({
        "domain": "agentbridge.queued-action.v1", "owner_id": principal_owner(session.principal),
        "task_id": action["task_id"] if task_id is None else task_id,
        "intent_sha256": record["intent_sha256"] if intent_sha256 is None else intent_sha256,
        "original_action_sha256": original,
    })
    return queued, original


def assert_unadmitted(app, session, record, budget):
    runtime = app[0]._runtimes["alpha"]
    assert runtime.store.get_budget("worker") == budget
    for table in ("agent_operations", "operation_authority", "operation_reservations",
                  "admission_quota_records_v1", "task_operation_links_v1"):
        assert count(runtime.store, table) == 0
    task_id = record["submission"]["task_id"]
    assert session.task(task_id).state == TaskState.SUBMITTED
    assert len(session.task_events(task_id)) == 1
    assert session.task_intent(task_id) == record


def test_maximal_unicode_identifiers_admit_and_survive_restart(queued_app, namespaces, authority):
    task_id, context_id, operation_id = "\U0001f9ed" * 128, "\U0001f30c" * 128, "\U0001f6f0" * 128
    session, body, nonce = authenticated(
        queued_app, data=submission(task_id=task_id, context_id=context_id, operation_id=operation_id)
    )
    record = session.submit_task(body, nonce=nonce)
    owner = principal_owner(session.principal)
    runtime = queued_app[0]._runtimes["alpha"]
    initial = session.task_events(task_id)
    intent_bytes = runtime.store._db.execute("SELECT record FROM task_intents_v1").fetchone()["record"]
    submitted_bytes = runtime.store._db.execute(
        "SELECT snapshot FROM task_lifecycle_events WHERE sequence=0"
    ).fetchone()["snapshot"]

    receipt = admit(queued_app, session, record)
    assert (receipt["task_id"], receipt["context_id"], receipt["operation_id"]) == (
        task_id, context_id, operation_id
    )
    assert (receipt["action_sha256"], receipt["original_action_sha256"]) == action_scopes(session, record)
    assert session.task_intent(task_id) == record
    assert session.task_events(task_id)[:1] == initial
    assert runtime.store._db.execute("SELECT record FROM task_intents_v1").fetchone()["record"] == intent_bytes
    assert runtime.store._db.execute(
        "SELECT snapshot FROM task_lifecycle_events WHERE sequence=0"
    ).fetchone()["snapshot"] == submitted_bytes

    directory = AuthorityDirectory(authority[3](), verifiers=authority[4])
    restarted = TenantKernel(directory, {tenant: namespaces(tenant) for tenant in ("alpha", "beta")},
                             costs=queued_app[0].costs, targets=TARGETS)
    reopened = restarted._runtimes["alpha"]
    assert restarted._queued_admission("alpha", owner, task_id, record["intent_sha256"]) == receipt
    assert reopened.task_intents.get(owner, task_id) == record
    events = reopened.tasks.events(owner, task_id)
    assert events[:1] == initial
    assert [(event.state, event.sequence) for event in events] == [
        (TaskState.SUBMITTED, 0), (TaskState.WORKING, 1)
    ]
    assert reopened.operations.get("worker", operation_id)["state"] == "unknown"
    assert reopened.store.get_budget("worker") == runtime.store.get_budget("worker")
    assert reopened.store.get_budget("worker")["reserved"] == {receipt["reservation_token"]: 1.0}
    with pytest.raises(AuthorityDenied):
        restarted._queued_admission("alpha", owner, task_id, "0" * 64)
    with pytest.raises(AuthorityDenied):
        restarted._queued_admission("beta", owner, task_id, record["intent_sha256"])


@pytest.mark.parametrize("mutation", ["update_link", "delete_link", "update_meta", "delete_meta",
                                     "truncate_link", "truncate_meta"])
def test_admission_history_and_schema_metadata_are_immutable(queued_app, mutation):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    if mutation.startswith("truncate") and not isinstance(runtime.store, PostgresStore):
        pytest.skip("TRUNCATE is PostgreSQL-only")
    receipt = admit(queued_app, session, record)
    before = snapshot(queued_app)
    queries = {
        "update_link": "UPDATE task_operation_links_v1 SET record=record",
        "delete_link": "DELETE FROM task_operation_links_v1",
        "update_meta": "UPDATE task_operation_links_meta_v1 SET version=version",
        "delete_meta": "DELETE FROM task_operation_links_meta_v1",
        "truncate_link": "TRUNCATE task_operation_links_v1",
        "truncate_meta": "TRUNCATE task_operation_links_meta_v1",
    }
    with pytest.raises(Exception, match="immutable"):
        with sql_atomic(runtime.store):
            runtime.store._db.execute(queries[mutation])
    assert snapshot(queued_app) == before
    assert runtime.task_admissions.get(principal_owner(session.principal), "native-task",
                                       record["intent_sha256"]) == receipt
    assert count(runtime.store, "task_operation_links_meta_v1") == 1


@pytest.mark.parametrize("case", ["mapping", "plan_seal", "proof_type", "authority_lease", "wrong_kernel",
                                 "wrong_gateway", "unbound_gateway", "thread", "exited"])
def test_gateway_admission_requires_its_live_sealed_preparation(queued_app, monkeypatch, case):
    session, record, _, _ = accepted(queued_app)
    kernel = queued_app[0]
    gateway = kernel._runtimes["alpha"].gateway
    other = None
    if case == "wrong_kernel":
        other = TenantKernel(kernel.directory, {tenant: runtime.store for tenant, runtime in kernel._runtimes.items()},
                             costs=kernel.costs, targets=TARGETS)
    before = snapshot(queued_app)

    with prepare(queued_app, session, record) as prepared:
        if case == "mapping":
            candidate = prepared.plan
        elif case == "plan_seal":
            candidate = replace(prepared, plan_json="{}")
        elif case == "proof_type":
            candidate = replace(prepared, _proof=prepared._proof.hex())
        elif case == "authority_lease":
            candidate = replace(prepared, _authority=replace(prepared._authority, _lease=object()))
        else:
            candidate = prepared
        if case == "wrong_kernel":
            gateway = other._runtimes["alpha"].gateway
        elif case == "wrong_gateway":
            gateway = kernel._runtimes["beta"].gateway
        elif case == "unbound_gateway":
            monkeypatch.setattr(gateway, "_queued_kernel", None)
        if case == "thread":
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(gateway._admit_queued_intent, candidate)
                with pytest.raises(AuthorityDenied):
                    pending.result(timeout=5)
        elif case != "exited":
            with pytest.raises(AuthorityDenied):
                gateway._admit_queued_intent(candidate)
    if case == "exited":
        with pytest.raises(AuthorityDenied):
            gateway._admit_queued_intent(prepared)
    assert snapshot(queued_app) == before
    assert session.task_intent("native-task") == record


@pytest.mark.parametrize("original_required,current_required", [(False, False), (False, True), (True, False), (True, True)])
def test_approval_floor_combines_original_and_current_exact_queued_scope(
    queued_app, monkeypatch, original_required, current_required
):
    admin = queued_app[1]["alpha"]
    if original_required:
        admin.mark_sensitive("read")
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    monkeypatch.setattr(runtime.approvals, "requires_approval", lambda capability: current_required)
    assert record["provenance"]["approval_required_at_submission"] is original_required
    queued_scope, original_scope = action_scopes(session, record)
    assert queued_scope != original_scope
    budget = runtime.store.get_budget("worker")
    required = original_required or current_required
    approval_id = None
    if required:
        with pytest.raises(GovernanceError) as denied:
            admit(queued_app, session, record)
        approval_id = denied.value.approval_id
        assert approval_id is not None
        pending = runtime.store.get_approval(approval_id)
        assert (pending["agent_id"], pending["capability"], pending["status"]) == (
            "worker", "read|" + queued_scope, "pending"
        )
        assert_unadmitted(queued_app, session, record, budget)
        assert admin.approve(approval_id)
    receipt = admit(queued_app, session, record)
    assert receipt["approval_required"] is required
    assert receipt["action_sha256"] == queued_scope
    assert receipt["original_action_sha256"] == original_scope
    assert session.task_intent("native-task") == record
    if approval_id is None:
        assert count(runtime.store, "approvals") == 0
    else:
        assert runtime.store.get_approval(approval_id)["status"] == "consumed"
        assert not runtime.approvals.is_granted("worker", "read", queued_scope)


@pytest.mark.parametrize("grant_kind", ["unscoped", "synchronous", "other_task", "other_intent",
                                       "other_agent", "other_capability", "consumed"])
def test_wrong_or_consumed_grant_cannot_authorize_queued_admission(queued_app, grant_kind):
    admin = queued_app[1]["alpha"]
    admin.mark_sensitive("read")
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    queued_scope, original_scope = action_scopes(session, record)
    agent_id, capability, scope = "worker", "read", queued_scope
    if grant_kind == "unscoped":
        scope = None
    elif grant_kind == "synchronous":
        scope = original_scope
    elif grant_kind == "other_task":
        scope = action_scopes(session, record, task_id="other-task")[0]
    elif grant_kind == "other_intent":
        scope = action_scopes(session, record, intent_sha256="0" * 64)[0]
    elif grant_kind == "other_agent":
        agent_id = "other-worker"
    elif grant_kind == "other_capability":
        capability = "write"
    wrong = runtime.approvals.request(agent_id, capability, 1.0, scope)
    assert admin.approve(wrong.id)
    if grant_kind == "consumed":
        assert runtime.approvals.consume("worker", "read", queued_scope)
    previous_status = "consumed" if grant_kind == "consumed" else "approved"
    budget = runtime.store.get_budget("worker")

    with pytest.raises(GovernanceError) as denied:
        admit(queued_app, session, record)
    assert_unadmitted(queued_app, session, record, budget)
    assert runtime.store.get_approval(wrong.id)["status"] == previous_status
    exact_id = denied.value.approval_id
    assert exact_id is not None and exact_id != wrong.id
    assert runtime.store.get_approval(exact_id)["capability"] == "read|" + queued_scope
    assert admin.approve(exact_id)
    assert admit(queued_app, session, record)["approval_required"] is True
    assert runtime.store.get_approval(exact_id)["status"] == "consumed"
    assert runtime.store.get_approval(wrong.id)["status"] == previous_status


@pytest.mark.asyncio
@pytest.mark.parametrize("delegated", [False, True])
async def test_synchronous_operation_fingerprint_keeps_established_material(queued_app, monkeypatch, delegated):
    grant = human_grant(queued_app) if delegated else None
    session, body, nonce = signed_session(queued_app, target_id="ledger", delegation=grant)
    action = json.loads(body)
    expected = digest({
        "agent_id": "worker", "src": action["src"], "dst": action["dst"], "wire": action["wire"],
        "cost": 1.0, "target_id": "ledger", "operation_id": action["operation_id"],
        "authority": session.principal.binding(),
    })
    calls = []

    async def invoke(dst, wire, target, *, registry):
        calls.append((dst, wire, target))
        return {"ok": True}

    monkeypatch.setattr("src.proxy.transport.invoke_target", invoke)
    assert await session.route(body, nonce=nonce) == {"ok": True}
    assert len(calls) == 1
    operation = session.operation("worker", action["operation_id"])
    assert operation["fingerprint"] == expected
    assert operation["state"] == "succeeded"
    runtime = queued_app[0]._runtimes["alpha"]
    assert runtime.store.get_budget("worker")["spent"] == 1.0
    assert runtime.store.get_budget("worker")["reserved"] == {}
    assert count(runtime.store, "task_operation_links_v1") == 0
