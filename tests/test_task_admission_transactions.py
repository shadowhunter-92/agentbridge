"""Admission failure boundaries and independent SQL connection schedules."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.governance.authority import AuthorityDenied, AuthorityDirectory
from src.governance.gateway import GovernanceError
from src.governance.operation_ledger import OperationConflict
from src.governance.store import PostgresStore, sql_atomic
from src.governance.task_admission import TaskAdmissionStore
from src.governance.tenant_kernel import TenantKernel, principal_owner
from src.protocols.durable_task_lifecycle import LifecycleCapacity
from src.protocols.task_lifecycle import TaskState
from tests.test_authority import authority as authority
from tests.test_queued_intent_preparation import accepted, prepare
from tests.test_task_admission import admit, snapshot
from tests.test_task_intents import TARGETS, count
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import signed_session
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def approved(app):
    app[1]["alpha"].mark_sensitive("read")
    session, record, _, _ = accepted(app)
    with pytest.raises(GovernanceError) as denied:
        admit(app, session, record)
    assert app[1]["alpha"].approve(denied.value.approval_id)
    return session, record, denied.value.approval_id


@pytest.mark.parametrize("stage", ["quota", "claim", "precheck", "reserve", "attach", "consume",
                                        "event", "snapshot", "link", "audit", "final"])
def test_failure_after_each_mutation_rolls_back_owned_admission(queued_app, monkeypatch, stage):
    session, record, approval = approved(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    before = snapshot(queued_app)
    events = session.task_events("native-task")

    def after(component, method):
        original = getattr(component, method)

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("fault after " + stage)

        monkeypatch.setattr(component, method, fail)

    if stage in ("event", "snapshot"):
        original = runtime.tasks._execute

        def execute(cur, query, values):
            result = original(cur, query, values)
            match = "INSERT INTO task_lifecycle_events" if stage == "event" else "UPDATE task_lifecycle_snapshots"
            if query.startswith(match):
                raise RuntimeError("fault after " + stage)
            return result

        monkeypatch.setattr(runtime.tasks, "_execute", execute)
    elif stage == "final":
        import src.governance.queued_intent_preparation as module
        after(module, "_assert_admission_lifetime")
    else:
        component, method = {
            "quota": (runtime.gateway._quotas, "admit"), "claim": (runtime.operations, "claim"),
            "precheck": (runtime.budgets, "can_afford"), "reserve": (runtime.budgets, "reserve"),
            "attach": (runtime.operations, "attach_reservation"), "consume": (runtime.approvals, "consume"),
            "link": (runtime.task_admissions, "_insert"), "audit": (runtime.audit, "record"),
        }[stage]
        after(component, method)
    with pytest.raises(RuntimeError, match="fault after"):
        admit(queued_app, session, record)
    assert snapshot(queued_app) == before
    assert runtime.approvals.get(approval).status == "approved"
    assert session.task_events("native-task") == events


def test_outer_rollback_owns_successful_nested_admission_and_failed_savepoint(queued_app, monkeypatch):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    before = snapshot(queued_app)
    with pytest.raises(RuntimeError, match="outer rollback"):
        with sql_atomic(runtime.store):
            receipt = admit(queued_app, session, record)
            assert receipt["event_sequence"] == 1
            raise RuntimeError("outer rollback")
    assert snapshot(queued_app) == before
    with sql_atomic(runtime.store):
        with monkeypatch.context() as patch:
            patch.setattr(runtime.audit, "record", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("audit")))
            with pytest.raises(RuntimeError, match="audit"):
                admit(queued_app, session, record)
        assert snapshot(queued_app) == before
        assert admit(queued_app, session, record)["event_sequence"] == 1


@pytest.mark.parametrize("failure", ["missing_budget", "budget", "quota", "event_bytes", "event_count"])
def test_capacity_denial_keeps_submitted_history_without_exposure(queued_app, failure):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    if failure == "missing_budget":
        runtime.store._db.execute("DELETE FROM budgets WHERE agent_id='worker'")
    elif failure == "budget":
        queued_app[1]["alpha"].set_budget("worker", spend_limit=0)
    elif failure == "quota":
        queued_app[1]["alpha"].set_quotas(enabled=True, spend_limit=0)
    elif failure == "event_bytes":
        capacity = runtime.tasks.event_capacity()
        runtime.tasks.set_event_capacity(capacity["used_event_bytes"] + capacity["reserved_control_bytes"])
    else:
        runtime.tasks.max_events = 2
    before = snapshot(queued_app)
    with pytest.raises((GovernanceError, LifecycleCapacity)):
        admit(queued_app, session, record)
    after = snapshot(queued_app)
    assert after["budget"] == before["budget"]
    assert after["counts"] == before["counts"]
    assert after["audit"] == before["audit"] if failure.startswith("event") else after["audit"]["decision"] == "deny"
    assert session.task("native-task").state == TaskState.SUBMITTED


def fresh(app, namespaces, authority):
    directory = AuthorityDirectory(authority[3](), verifiers=authority[4])
    kernel = TenantKernel(directory, {t: namespaces(t) for t in ("alpha", "beta")},
                          costs=app[0].costs, targets=TARGETS)
    return (kernel, *app[1:4], directory, app[5])


def test_independent_workers_commit_one_and_never_release_winner(queued_app, namespaces, authority, monkeypatch):
    session, record, _, _ = accepted(queued_app)
    other = fresh(queued_app, namespaces, authority)
    barrier = threading.Barrier(2)
    runtime = queued_app[0]._runtimes["alpha"]
    for app in (queued_app, other):
        monkeypatch.setattr(app[0]._runtimes["alpha"].gateway, "_abort_admission",
                            lambda *args, **kwargs: pytest.fail("loser must not abort winner"), raising=False)

    def worker(app):
        barrier.wait(5)
        try:
            return admit(app, session, record)
        except (AuthorityDenied, OperationConflict) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (queued_app, other)))
    receipts = [result for result in results if isinstance(result, dict)]
    assert len(receipts) == 1
    assert runtime.store.get_budget("worker")["reserved"] == {receipts[0]["reservation_token"]: 1}
    assert count(runtime.store, "task_operation_links_v1") == 1
    assert count(runtime.store, "agent_operations") == count(runtime.store, "admission_quota_records_v1") == 1
    assert runtime.operations.get("worker", record["submission"]["operation_id"])["state"] == "unknown"


@pytest.mark.parametrize("state", ["unknown", "failed", "succeeded"])
def test_preexisting_operation_is_never_adopted_or_finished(queued_app, state):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    operation = record["submission"]["operation_id"]
    runtime.operations.claim("worker", operation, "another-action", authority_binding=session.principal.binding())
    runtime.operations.finish("worker", operation, state)
    before = snapshot(queued_app)
    with pytest.raises(OperationConflict):
        admit(queued_app, session, record)
    assert snapshot(queued_app) == before
    assert runtime.operations.get("worker", operation)["state"] == state


def test_other_connection_sees_only_complete_commit_and_status_cancel_holds_exposure(queued_app, namespaces, monkeypatch):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    observer = namespaces("alpha")
    before = observer.load_audit_head()
    entered, release = threading.Event(), threading.Event()
    original = runtime.audit.record

    def pause(**kwargs):
        result = original(**kwargs)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(runtime.audit, "record", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(admit, queued_app, session, record)
        try:
            assert entered.wait(5)
            for table in ("agent_operations", "operation_authority", "operation_reservations",
                          "admission_quota_records_v1", "task_operation_links_v1"):
                assert count(observer, table) == 0
            assert count(observer, "task_lifecycle_events") == 1
            assert observer.get_budget("worker")["reserved"] == {}
            assert observer.load_audit_head() == before
        finally:
            release.set()
        result = pending.result(10)
    assert count(observer, "task_operation_links_v1") == 1
    assert count(observer, "task_lifecycle_events") == 2
    runtime.tasks.cancel(principal_owner(session.principal), "native-task", expected_sequence=1)
    assert runtime.store.get_budget("worker")["reserved"] == {result["reservation_token"]: 1}
    assert runtime.operations.get("worker", result["operation_id"])["state"] == "unknown"


@pytest.mark.parametrize("deadline", ["original", "process"])
def test_expiry_after_working_and_audit_rolls_back_everything(queued_app, monkeypatch, deadline):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    before = snapshot(queued_app)
    original = runtime.audit.record
    with prepare(queued_app, session, record) as prepared:
        expires = prepared._authority.original_deadline if deadline == "original" else prepared._authority.principal.valid_until

        def expire(**kwargs):
            result = original(**kwargs)
            monkeypatch.setattr("src.governance.queued_intent_preparation.time.time", lambda: expires)
            return result

        monkeypatch.setattr(runtime.audit, "record", expire)
        with pytest.raises(AuthorityDenied):
            runtime.gateway._admit_queued_intent(prepared)
    assert snapshot(queued_app) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["sync", "queued"])
async def test_public_and_queued_operation_collision_preserves_winner(queued_app, winner):
    session, record, _, _ = accepted(queued_app)
    operation = record["submission"]["operation_id"]
    route, body, nonce = signed_session(queued_app, operation=operation)
    if winner == "sync":
        assert "translated_wire" in await route.route(body, nonce=nonce)
        before = snapshot(queued_app)
        with pytest.raises(OperationConflict):
            admit(queued_app, session, record)
    else:
        admit(queued_app, session, record)
        before = snapshot(queued_app)
        with pytest.raises(OperationConflict):
            await route.route(body, nonce=nonce)
    assert snapshot(queued_app) == before


@pytest.mark.parametrize("corruption", ["partial", "version", "digest", "column", "primary", "unique", "object"])
def test_restart_rejects_partial_unknown_or_incompatible_link_schema(namespaces, corruption):
    store = namespaces("alpha")
    postgres = isinstance(store, PostgresStore)
    def execute(query):
        return store._db.execute(query)
    if corruption == "object":
        execute("CREATE VIEW task_operation_links_v1 AS SELECT 1 AS invalid")
    elif corruption == "partial":
        execute("CREATE TABLE task_operation_links_v1(invalid TEXT)")
    else:
        fields = [name + " " + typ + " NOT NULL" for name, typ in TaskAdmissionStore.COLUMNS]
        if corruption == "column":
            fields = fields[:-1]
        if corruption != "primary":
            fields.append("PRIMARY KEY(owner_id,task_id)")
        if corruption != "unique":
            fields.append("UNIQUE(agent_id,operation_id)")
        execute("CREATE TABLE task_operation_links_v1(" + ",".join(fields) + ")")
        execute("CREATE TABLE task_operation_links_meta_v1(singleton INTEGER NOT NULL PRIMARY KEY,"
                "version INTEGER NOT NULL,schema_sha256 TEXT NOT NULL)")
        values = (1, 2 if corruption == "version" else 1,
                  "0" * 64 if corruption == "digest" else TaskAdmissionStore.SCHEMA_SHA256)
        store._db.execute("INSERT INTO task_operation_links_meta_v1 VALUES(" + ("%s,%s,%s" if postgres else "?,?,?") + ")", values)
    with pytest.raises(AuthorityDenied, match="schema"):
        TaskAdmissionStore(store)


def test_concurrent_link_bootstrap_and_restart_share_database_fence(namespaces):
    stores = [namespaces("alpha"), namespaces("alpha")]
    barrier = threading.Barrier(2)

    def start(store):
        barrier.wait(5)
        return TaskAdmissionStore(store)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(start, stores))) == 2
    for store in stores:
        TaskAdmissionStore(store)
        assert count(store, "task_operation_links_meta_v1") == 1
