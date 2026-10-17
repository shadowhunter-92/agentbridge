"""Queued intent acceptance is durable and atomic, but never executes an action."""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest

from src.api.trusted_targets import SecurityConfigurationError
from src.governance.authority import AuthorityDenied, AuthorityDirectory, sign_tenant_request
from src.governance.policy_rules import DenyCapabilities, RequireApprovalAboveCost
from src.governance.store import PostgresStore, sql_atomic
from src.governance.task_intents import IntentLimits, TaskIntentCapacity, TaskIntentConflict, TaskIntentStore
from src.governance.tenant_kernel import TenantKernel, principal_owner
from src.protocols.task_lifecycle import TaskLifecycle, TaskState
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_kernel import human_grant, signed_session
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces

TARGETS = {
    tenant: {"ledger": {"protocol": "mcp", "kind": "mcp_stdio", "command": "never-run",
                        "args": [], "capabilities": ["read", "write"], "allowed_agents": ["worker"]}}
    for tenant in ("alpha", "beta")
}


@pytest.fixture
def queued_app(tenant_app):
    original = tenant_app[0]
    kernel = TenantKernel(
        original.directory, {t: r.store for t, r in original._runtimes.items()},
        costs=original.costs, targets=TARGETS,
    )
    return (kernel, *tenant_app[1:])


def submission(**changes):
    return {
        "request_scope": "task.submit", "task_id": "native-task", "context_id": "native-context",
        "src": "mcp", "dst": "mcp", "target_id": "ledger", "operation_id": "queued-operation-123456",
        "wire": {"method": "tools/call", "params": {"name": "read", "arguments": {}}}, **changes,
    }


def authenticated(app, tenant="alpha", *, data=None, raw=None, delegation=None):
    body = raw if raw is not None else json.dumps(data or submission()).encode()
    nonce = f"{time.time()}:{uuid.uuid4().hex}"
    proof = sign_tenant_request(app[2][tenant], tenant, nonce, body, delegation_id=delegation)
    principal = app[4].authenticate_agent(tenant, "worker", nonce, body, proof, delegation_id=delegation)
    return app[0].session(principal), body, nonce


def count(store, table):
    return store._db.execute("SELECT count(*) AS n FROM " + table).fetchone()["n"]


def test_acceptance_keeps_exact_provenance_and_no_effect_or_budget_mutation(queued_app, monkeypatch):
    kernel = queued_app[0]
    runtime = kernel._runtimes["alpha"]
    before = runtime.store.get_budget("worker")
    queued_app[1]["alpha"].mark_sensitive("read")
    queued_app[1]["alpha"].add_policy(RequireApprovalAboveCost(0))

    def prohibited(*args, **kwargs):
        raise AssertionError("queued acceptance must not invoke admission")

    for component, method in (
        (runtime.policy, "authorize"), (runtime.budgets, "get"), (runtime.budgets, "reserve"),
        (runtime.budgets, "can_afford"), (runtime.approvals, "request"), (runtime.approvals, "consume"),
        (runtime.gateway, "route_call"), (runtime.operations, "claim"),
    ):
        monkeypatch.setattr(component, method, prohibited)
    monkeypatch.setattr("src.proxy.transport.invoke_target", prohibited)
    session, body, nonce = authenticated(queued_app)
    accepted = session.submit_task(body, nonce=nonce)
    assert accepted == session.task_intent("native-task")
    assert accepted["phase"] == "queued" and accepted["execution_admitted"] is False
    assert accepted["submission"] == json.loads(body)
    provenance = accepted["provenance"]
    assert provenance["request_body"].encode() == body
    assert provenance["request_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert provenance["authorization_expires_at"] == session.principal.valid_until
    assert provenance["request_nonce"] == nonce
    assert provenance["approval_required_at_submission"] is True
    assert provenance["operator_cost"] == 1.0
    assert "_proof" not in provenance["authority"]
    task = session.task("native-task")
    assert (task.source_protocol, task.state, task.sequence) == ("agentbridge", TaskState.SUBMITTED, 0)
    assert session.task_events("native-task") == [task]
    assert runtime.store.get_budget("worker") == before
    assert count(runtime.store, "agent_operations") == count(runtime.store, "approvals") == 0
    assert count(runtime.store, "operation_reservations") == 0
    last = runtime.store.load_audit_head()
    assert last["action"] == "task.submit" and last["cost"] == 0
    assert accepted["intent_sha256"] in last["reason"]


def test_acceptance_never_seeds_missing_budget_and_preserves_old_snapshots(queued_app):
    session, body, nonce = authenticated(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    runtime.store._db.execute("DELETE FROM budgets WHERE agent_id='worker'")
    owner = principal_owner(session.principal)
    runtime.tasks.create(owner, TaskLifecycle("old-task", "old-context", "a2a"))
    old = runtime.store._db.execute("SELECT snapshot FROM task_lifecycle_snapshots WHERE task_id='old-task'").fetchone()["snapshot"]
    session.submit_task(body, nonce=nonce)
    assert runtime.store.get_budget("worker") is None
    assert runtime.store._db.execute("SELECT snapshot FROM task_lifecycle_snapshots WHERE task_id='old-task'").fetchone()["snapshot"] == old
    assert session.task("old-task").source_protocol == "a2a"


@pytest.mark.parametrize("change", [
    {"owner_id": "chosen-owner"}, {"cost": 0}, {"principal": {}}, {"target": {}}, {"tenant_id": "alpha"},
    {"request_scope": "route"}, {"target_id": None}, {"task_id": " "}, {"operation_id": " " * 16},
])
def test_direct_submission_enforces_strict_signed_contract(queued_app, change):
    session, body, nonce = authenticated(queued_app, data=submission(**change))
    with pytest.raises((ValueError, AuthorityDenied)):
        session.submit_task(body, nonce=nonce)
    assert count(queued_app[0]._runtimes["alpha"].store, "task_intents_v1") == 0


def test_exact_request_binding_and_duplicate_json_rejection(queued_app):
    session, body, nonce = authenticated(queued_app)
    with pytest.raises(AuthorityDenied):
        session.submit_task(body + b" ", nonce=nonce)
    with pytest.raises(AuthorityDenied):
        session.submit_task(body, nonce=nonce + "changed")
    duplicate = body[:-1] + b',"task_id":"replacement"}'
    session, duplicate, nonce = authenticated(queued_app, raw=duplicate)
    with pytest.raises(ValueError):
        session.submit_task(duplicate, nonce=nonce)
    assert count(queued_app[0]._runtimes["alpha"].store, "task_intents_v1") == 0


@pytest.mark.parametrize("change", [
    {}, {"context_id": "changed"}, {"operation_id": "different-operation-1234"},
    {"task_id": "different-task"}, {"wire": {"method": "tools/call", "params": {"name": "write"}}},
])
def test_duplicate_or_mutated_identity_never_replaces_intent(queued_app, change):
    session, body, nonce = authenticated(queued_app)
    original = session.submit_task(body, nonce=nonce)
    other, raw, proof_nonce = authenticated(queued_app, data=submission(**change))
    with pytest.raises(TaskIntentConflict):
        other.submit_task(raw, nonce=proof_nonce)
    assert session.task_intent("native-task") == original
    assert len(session.task_events("native-task")) == 1


def test_existing_operation_and_status_identity_are_never_adopted(queued_app):
    session, body, nonce = authenticated(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    runtime.operations.claim("worker", "queued-operation-123456", "old", authority_binding=session.principal.binding())
    with pytest.raises(TaskIntentConflict):
        session.submit_task(body, nonce=nonce)
    session, body, nonce = authenticated(queued_app, data=submission(operation_id="unclaimed-operation-1234"))
    runtime.tasks.create(principal_owner(session.principal), TaskLifecycle("native-task", "old", "a2a"))
    with pytest.raises(TaskIntentConflict):
        session.submit_task(body, nonce=nonce)
    assert runtime.operations.get("worker", "queued-operation-123456")["state"] == "unknown"
    assert session.task("native-task").context_id == "old"


def test_tenant_and_exact_owner_views_and_same_scope_renewal(queued_app):
    directory, owner = queued_app[4:]
    directory.enroll_member(owner, "alpha", ISSUER, "human", role="tenant_operator",
                            capabilities=("read", "write"), targets=("ledger",))
    user = directory.authenticate_operator(ISSUER, queued_app[3]("human", tenant="alpha"), tenant_id="alpha")

    def broad_grant():
        return directory.grant_delegation(queued_app[1]["alpha"].principal, user, "worker",
                                          capabilities=("read", "write"), targets=("ledger",),
                                          expires_at=time.time() + 600)

    grant = broad_grant()
    session, body, nonce = authenticated(queued_app, delegation=grant)
    original = session.submit_task(body, nonce=nonce)
    for tenant, delegation in (("beta", None), ("alpha", None), ("alpha", human_grant(queued_app, "other-human"))):
        other, _, _ = authenticated(queued_app, tenant, delegation=delegation)
        with pytest.raises(AuthorityDenied):
            other.task_intent("native-task")
    renewed, _, _ = authenticated(queued_app, delegation=broad_grant())
    assert renewed.task_intent("native-task") == original
    narrow, _, _ = authenticated(queued_app, delegation=human_grant(queued_app))
    with pytest.raises(AuthorityDenied):
        narrow.task_intent("native-task")
    beta, body, nonce = authenticated(queued_app, "beta")
    assert beta.submit_task(body, nonce=nonce)["submission"]["task_id"] == "native-task"


@pytest.mark.parametrize("stage", ["intent", "snapshot", "event", "audit"])
def test_acceptance_rolls_back_every_mutation(queued_app, monkeypatch, stage):
    session, body, nonce = authenticated(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    old_audit = runtime.store.load_audit_head()
    old_budget = runtime.store.get_budget("worker")
    if stage == "audit":
        original = runtime.audit.record

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("acceptance fault")

        monkeypatch.setattr(runtime.audit, "record", fail)
    else:
        component = runtime.task_intents if stage == "intent" else runtime.tasks
        original = component._execute
        table = {"intent": "task_intents_v1", "snapshot": "task_lifecycle_snapshots", "event": "task_lifecycle_events"}[stage]

        def fail(*args, **kwargs):
            result = original(*args, **kwargs)
            query = args[0] if stage == "intent" else args[1]
            if query.startswith("INSERT INTO " + table + " "):
                raise RuntimeError("acceptance fault")
            return result

        monkeypatch.setattr(component, "_execute", fail)
    with pytest.raises(RuntimeError, match="acceptance fault"):
        session.submit_task(body, nonce=nonce)
    assert count(runtime.store, "task_intents_v1") == 0
    assert count(runtime.store, "task_lifecycle_snapshots") == count(runtime.store, "task_lifecycle_events") == 0
    assert runtime.store.load_audit_head() == old_audit
    assert runtime.store.get_budget("worker") == old_budget
    assert count(runtime.store, "agent_operations") == count(runtime.store, "operation_reservations") == 0


def test_outer_rollback_and_nested_failure_preserve_prior_history(queued_app):
    session, body, nonce = authenticated(queued_app)
    store = queued_app[0]._runtimes["alpha"].store
    with pytest.raises(RuntimeError):
        with sql_atomic(store):
            session.submit_task(body, nonce=nonce)
            raise RuntimeError("outer rollback")
    assert count(store, "task_intents_v1") == 0
    session.submit_task(body, nonce=nonce)
    with sql_atomic(store):
        with pytest.raises(TaskIntentConflict):
            session.submit_task(body, nonce=nonce)
        store.upsert_budget("worker", {"spent": 3})
    assert session.task("native-task").state == TaskState.SUBMITTED
    assert store.get_budget("worker")["spent"] == 3


def test_other_connection_cannot_observe_partial_acceptance(queued_app, namespaces, monkeypatch):
    session, body, nonce = authenticated(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    observer = namespaces("alpha")
    audit = observer.load_audit_head()
    original = runtime.audit.record
    started, release = threading.Event(), threading.Event()

    def pause(*args, **kwargs):
        result = original(*args, **kwargs)
        started.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(runtime.audit, "record", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(session.submit_task, body, nonce=nonce)
        try:
            assert started.wait(5)
            for table in ("task_intents_v1", "task_lifecycle_snapshots", "task_lifecycle_events"):
                assert count(observer, table) == 0
            assert observer.load_audit_head() == audit
        finally:
            release.set()
        pending.result(10)
    assert count(observer, "task_intents_v1") == count(observer, "task_lifecycle_events") == 1
    assert observer.load_audit_head() != audit


def test_restart_reloads_intent_policy_and_provenance_without_execution(queued_app, namespaces, authority):
    session, body, nonce = authenticated(queued_app)
    original = session.submit_task(body, nonce=nonce)
    directory = AuthorityDirectory(authority[3](), verifiers=authority[4])
    kernel = TenantKernel(directory, {t: namespaces(t) for t in ("alpha", "beta")}, costs=queued_app[0].costs, targets=TARGETS)
    restarted = (kernel, *queued_app[1:4], directory, queued_app[5])
    renewed, _, _ = authenticated(restarted)
    assert renewed.task_intent("native-task") == original
    assert renewed.task_events("native-task") == [renewed.task("native-task")]
    assert count(kernel._runtimes["alpha"].store, "agent_operations") == 0
    with pytest.raises(AuthorityDenied):
        kernel.session(session.principal)


@pytest.mark.parametrize("collision", ["same", "capacity"])
def test_simultaneous_first_submissions_commit_one_across_connections(queued_app, namespaces, authority, collision):
    if collision == "capacity":
        queued_app[1]["alpha"].set_task_intent_capacity(**asdict(replace(IntentLimits(), max_intents=1)))
    other_directory = AuthorityDirectory(authority[3](), verifiers=authority[4])
    other_kernel = TenantKernel(
        other_directory, {t: namespaces(t) for t in ("alpha", "beta")}, costs=queued_app[0].costs, targets=TARGETS
    )
    other_app = (other_kernel, *queued_app[1:4], other_directory, queued_app[5])
    first = authenticated(queued_app)
    second = authenticated(other_app, data=submission(
        **({"task_id": "other-task", "operation_id": "other-operation-123456"} if collision == "capacity" else {})
    ))
    barrier = threading.Barrier(2)

    def submit(args):
        session, body, nonce = args
        barrier.wait(5)
        try:
            return session.submit_task(body, nonce=nonce)
        except (TaskIntentConflict, TaskIntentCapacity) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, (first, second)))
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    store = queued_app[0]._runtimes["alpha"].store
    assert count(store, "task_intents_v1") == count(store, "task_lifecycle_events") == 1
    assert count(store, "agent_operations") == 0


def test_immutable_rows_bounds_and_original_result_allowances(queued_app):
    session, body, nonce = authenticated(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    accepted = session.submit_task(body, nonce=nonce)
    capacity = runtime.task_intents.capacity()
    assert capacity["used_intents"] == 1
    raw = runtime.store._db.execute("SELECT record FROM task_intents_v1").fetchone()["record"]
    assert capacity["used_retained_bytes"] == len(raw.encode()) + accepted["result_limit_bytes"]
    for query in ("DELETE FROM task_intents_v1", "UPDATE task_intents_v1 SET fingerprint='replacement'"):
        with pytest.raises(Exception, match="immutable"):
            runtime.store._db.execute(query)
    lower = replace(IntentLimits(), max_result_bytes=1)
    queued_app[1]["alpha"].set_task_intent_capacity(**asdict(lower))
    assert session.task_intent("native-task")["result_limit_bytes"] == accepted["result_limit_bytes"]
    with pytest.raises(TaskIntentCapacity):
        queued_app[1]["alpha"].set_task_intent_capacity(**asdict(replace(lower, max_retained_bytes=256)))
    assert runtime.task_intents.capacity()["max_result_bytes"] == 1


@pytest.mark.parametrize("bound", ["intent", "aggregate"])
def test_byte_capacity_fails_closed_and_never_deletes_old_history(queued_app, bound):
    limits = replace(IntentLimits(), **({"max_intent_bytes": 256} if bound == "intent" else {"max_retained_bytes": 256}))
    queued_app[1]["alpha"].set_task_intent_capacity(**asdict(limits))
    session, body, nonce = authenticated(queued_app)
    with pytest.raises(TaskIntentCapacity):
        session.submit_task(body, nonce=nonce)
    assert count(queued_app[0]._runtimes["alpha"].store, "task_intents_v1") == 0


def test_sql_guards_reject_oversized_direct_insert_and_legacy_writes(queued_app, namespaces):
    store = queued_app[0]._runtimes["alpha"].store
    execute = queued_app[0]._runtimes["alpha"].task_intents._execute
    with pytest.raises(Exception, match="capacity"):
        execute("INSERT INTO task_intents_v1 VALUES(?,?,?,?,?,?,?)", ("owner", "task", "worker", "op", "fp", "x" * 65537, 65536))
    legacy = namespaces("alpha", legacy=True)
    with pytest.raises(Exception, match="tenant write scope required|agentbridge_current_tenant"):
        legacy._db.execute("DELETE FROM task_intent_policy_v1")
    assert count(store, "task_intent_policy_v1") == 1


@pytest.mark.parametrize("damage", ["version", "missing"])
def test_corrupt_durable_policy_prevents_new_acceptance_and_bootstrap(queued_app, damage):
    runtime = queued_app[0]._runtimes["alpha"]
    runtime.store._db.execute("UPDATE task_intent_policy_v1 SET version=2" if damage == "version"
                              else "DELETE FROM task_intent_policy_v1")
    session, body, nonce = authenticated(queued_app)
    with pytest.raises(TaskIntentCapacity):
        session.submit_task(body, nonce=nonce)
    with pytest.raises(TaskIntentCapacity):
        TaskIntentStore(runtime.store, runtime.tasks)
    assert count(runtime.store, "task_intents_v1") == 0


def test_unsupported_postgres_isolation_fails_closed(queued_app):
    store = queued_app[0]._runtimes["alpha"].store
    if not isinstance(store, PostgresStore):
        pytest.skip("PostgreSQL isolation only")
    store._db.execute("SET default_transaction_isolation='repeatable read'")
    session, body, nonce = authenticated(queued_app)
    try:
        with pytest.raises(TaskIntentCapacity, match="READ COMMITTED"):
            session.submit_task(body, nonce=nonce)
        assert count(store, "task_intents_v1") == 0
    finally:
        store._db.execute("SET default_transaction_isolation='read committed'")


@pytest.mark.parametrize("environment", ["prod", "production"])
def test_production_generic_target_stays_closed_before_acceptance(queued_app, monkeypatch, environment):
    monkeypatch.setenv("AGENTBRIDGE_ENV", environment)
    original = queued_app[0]
    kernel = TenantKernel(original.directory, {t: r.store for t, r in original._runtimes.items()}, costs=original.costs, targets=TARGETS)
    session, body, nonce = authenticated((kernel, *queued_app[1:]))
    with pytest.raises(SecurityConfigurationError, match="destination-atomic"):
        session.submit_task(body, nonce=nonce)
    assert count(kernel._runtimes["alpha"].store, "task_intents_v1") == 0


def test_current_policy_and_revocation_reject_queued_submission(queued_app):
    session, body, nonce = authenticated(queued_app)
    queued_app[1]["alpha"].add_policy(DenyCapabilities(["read"]))
    with pytest.raises(AuthorityDenied):
        session.submit_task(body, nonce=nonce)
    queued_app[4].revoke_agent(queued_app[5], "alpha", "worker")
    with pytest.raises(AuthorityDenied):
        session.submit_task(body, nonce=nonce)
    assert count(queued_app[0]._runtimes["alpha"].store, "task_intents_v1") == 0


@pytest.mark.asyncio
async def test_queued_submission_does_not_reserve_operation_identity_against_later_route(queued_app):
    session, body, nonce = authenticated(queued_app)
    accepted = session.submit_task(body, nonce=nonce)
    route, body, nonce = signed_session(queued_app, operation=submission()["operation_id"])
    assert "translated_wire" in await route.route(body, nonce=nonce)
    assert route.operation("worker", submission()["operation_id"])["state"] == "succeeded"
    assert session.task_intent("native-task") == accepted
    assert session.task("native-task").state == TaskState.SUBMITTED
    assert count(queued_app[0]._runtimes["alpha"].store, "agent_operations") == 1


@pytest.mark.parametrize("change", [
    {"src": "unknown"}, {"dst": "unknown"}, {"target_id": "unregistered"},
    {"wire": {"method": "tasks/get", "params": {}}},
    {"wire": {"method": "tools/call", "params": {"name": "delete"}}},
])
def test_protocol_action_capability_and_target_validation_precede_acceptance(queued_app, change):
    session, body, nonce = authenticated(queued_app, data=submission(**change))
    with pytest.raises((ValueError, AuthorityDenied, SecurityConfigurationError)):
        session.submit_task(body, nonce=nonce)
    assert count(queued_app[0]._runtimes["alpha"].store, "task_intents_v1") == 0


def test_missing_operator_cost_and_expired_context_prevent_acceptance(queued_app, monkeypatch):
    original = queued_app[0]
    kernel = TenantKernel(original.directory, {t: r.store for t, r in original._runtimes.items()},
                          costs={"alpha": {}, "beta": {}}, targets=TARGETS)
    session, body, nonce = authenticated((kernel, *queued_app[1:]))
    with pytest.raises(AuthorityDenied, match="cost schedule"):
        session.submit_task(body, nonce=nonce)
    session, body, nonce = authenticated(queued_app)
    monkeypatch.setattr("src.governance.authority.time.time", lambda: session.principal.valid_until + 1)
    with pytest.raises(AuthorityDenied, match="expired"):
        session.submit_task(body, nonce=nonce)
    assert count(original._runtimes["alpha"].store, "task_intents_v1") == 0


@pytest.mark.parametrize("stage", ["intent", "audit"])
def test_real_process_death_before_acceptance_commit_leaves_no_partial_state(queued_app, tmp_path, stage):
    session, body, nonce = authenticated(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    # Capture a genuine accepted provenance shape, then roll the local acceptance
    # back. The child exercises persistence only; it never mints authority.
    with pytest.raises(RuntimeError):
        with sql_atomic(runtime.store):
            record = session.submit_task(body, nonce=nonce)
            raise RuntimeError("capture rollback")
    if isinstance(runtime.store, PostgresStore):
        from psycopg.conninfo import make_conninfo

        config = {"backend": "postgres", "schema": runtime.store.schema,
                  "dsn": make_conninfo(runtime.store._db.info.dsn, password=runtime.store._db.info.password)}
    else:
        config = {"backend": "sqlite", "path": runtime.store._db.execute("PRAGMA database_list").fetchone()["file"]}
    config.update(stage=stage, owner=principal_owner(session.principal), provenance=record["provenance"],
                  body=body.decode())
    child = tmp_path / "crash_intent.py"
    child.write_text('''
import json, os
from src.governance.audit import AuditLog
from src.governance.task_intents import TaskIntentStore, parse_submission
from src.governance.tenant_store import TenantSqliteStore, TenantPostgresStore
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
c = json.loads(os.environ["AGENTBRIDGE_CRASH_INTENT"])
s = (TenantSqliteStore(c["path"], tenant_id="alpha") if c["backend"] == "sqlite" else
     TenantPostgresStore(c["dsn"], schema=c["schema"], tenant_id="alpha"))
t = DurableTaskLifecycle(s)
i = TaskIntentStore(s, t)
a = AuditLog(s)
original = i._execute
def execute(query, values=()):
    result = original(query, values)
    if c["stage"] == "intent" and query.startswith("INSERT INTO task_intents_v1 "):
        os._exit(75)
    return result
i._execute = execute
def accepted(fingerprint):
    a.record(actor="crash-test", action="task.submit", source_protocol="mcp", target_protocol="mcp",
             capability="read", decision="allow", cost=0.0, reason=fingerprint)
    os._exit(75)
i._accept(c["owner"], parse_submission(c["body"].encode()), c["provenance"], audit=accepted)
''', encoding="utf-8")
    environment = os.environ.copy()
    environment.update(AGENTBRIDGE_CRASH_INTENT=json.dumps(config), PYTHONPATH=os.getcwd())
    audit = runtime.store.load_audit_head()
    budget = runtime.store.get_budget("worker")
    result = subprocess.run([sys.executable, str(child)], env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 75, "intent crash child did not reach the selected transaction boundary"
    assert count(runtime.store, "task_intents_v1") == count(runtime.store, "task_lifecycle_events") == 0
    assert runtime.store.load_audit_head() == audit
    assert runtime.store.get_budget("worker") == budget
    assert count(runtime.store, "agent_operations") == 0
