"""Real PostgreSQL waits cannot outlive admission authority or adopt status."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.governance.authority import AuthorityDenied
from src.governance.store import PostgresStore, sql_atomic
from src.governance.tenant_kernel import principal_owner
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
from src.protocols.task_lifecycle import TaskState
from tests.test_authority import authority as authority
from tests.test_queued_intent_preparation import prepare
from tests.test_task_admission import snapshot
from tests.test_task_admission_transactions import approved, fresh
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def wait_for_advisory_block(observer, pending, worker_pid, holder_pid):
    """Prove the intended server-side wait; propagate an early worker failure."""
    deadline = time.monotonic() + 8
    last = None
    tick = threading.Event()
    while time.monotonic() < deadline:
        if pending.done():
            pending.result(timeout=1)
            pytest.fail("admission completed before the held advisory lock was released")
        last = observer._db.execute(
            "SELECT wait_event_type,wait_event,query,pg_blocking_pids(pid) AS blockers "
            "FROM pg_stat_activity WHERE pid=%s", (worker_pid,),
        ).fetchone()
        if last and last["wait_event_type"] == "Lock" and last["wait_event"] == "advisory" \
                and holder_pid in last["blockers"]:
            assert "pg_advisory_xact_lock" in last["query"]
            return
        tick.wait(.01)
    pytest.fail("admission did not reach its held advisory lock: " + repr(last))


def hold_admission_lock(store, kind, operation_id):
    if kind == "lifecycle":
        store._db.execute("SELECT pg_advisory_xact_lock(%s)", (911006,))
    else:
        key = "operation:worker:" + operation_id if kind == "operation" else "budget:worker"
        store._db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))


def prepare_worker(app, session, record, ready, deadlines):
    with prepare(app, session, record) as prepared:
        deadlines["original"] = prepared._authority.original_deadline
        deadlines["process"] = prepared._authority.principal.valid_until
        ready.set()
        return app[0]._runtimes["alpha"].gateway._admit_queued_intent(prepared)


def postgres_workers(queued_app, namespaces, authority):
    if not isinstance(queued_app[0]._runtimes["alpha"].store, PostgresStore):
        pytest.skip("requires genuine PostgreSQL independent-connection advisory waits")
    worker = fresh(queued_app, namespaces, authority)
    runtime = worker[0]._runtimes["alpha"]
    # A failed schedule must also release its executor thread in bounded time.
    runtime.store._db.execute("SET statement_timeout='12s'")
    worker[4].store._db.execute("SET statement_timeout='12s'")
    holder, observer = namespaces("alpha"), namespaces("alpha")
    assert len({runtime.store._db.info.backend_pid, holder._db.info.backend_pid,
                observer._db.info.backend_pid}) == 3
    return worker, runtime, holder, observer


@pytest.mark.parametrize("lock_kind", ["operation", "budget", "lifecycle"])
@pytest.mark.parametrize("deadline_kind", ["original", "process"])
def test_postgres_wait_expiry_rolls_back_every_admission_mutation(
    queued_app, namespaces, authority, monkeypatch, lock_kind, deadline_kind
):
    if not isinstance(queued_app[0]._runtimes["alpha"].store, PostgresStore):
        pytest.skip("requires genuine PostgreSQL independent-connection advisory waits")
    session, record, approval_id = approved(queued_app)
    worker, runtime, holder, observer = postgres_workers(queued_app, namespaces, authority)
    before = snapshot(queued_app)
    initial = session.task_events("native-task")
    operation_acquired, budget_precheck = threading.Event(), threading.Event()
    claim, can_afford = runtime.operations.claim, runtime.budgets.can_afford

    def claim_then_signal(*args, **kwargs):
        result = claim(*args, **kwargs)
        operation_acquired.set()
        return result

    def ordered_precheck(*args, **kwargs):
        assert operation_acquired.is_set(), "budget precheck ran before operation acquisition"
        budget_precheck.set()
        return can_afford(*args, **kwargs)

    monkeypatch.setattr(runtime.operations, "claim", claim_then_signal)
    monkeypatch.setattr(runtime.budgets, "can_afford", ordered_precheck)
    ready, deadlines = threading.Event(), {}
    with monkeypatch.context() as clock:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with sql_atomic(holder):
                hold_admission_lock(holder, lock_kind, record["submission"]["operation_id"])
                pending = pool.submit(prepare_worker, worker, session, record, ready, deadlines)
                assert ready.wait(8), "worker did not establish its own preparation guard"
                wait_for_advisory_block(observer, pending, runtime.store._db.info.backend_pid,
                                        holder._db.info.backend_pid)
                assert deadlines["process"] < deadlines["original"]
                if lock_kind == "operation":
                    assert not operation_acquired.is_set()
                    assert not budget_precheck.is_set()
                    # Holding operation while acquiring budget must remain possible:
                    # a waiter taking budget first would produce a real inversion.
                    holder._db.execute("SET LOCAL lock_timeout='1s'")
                    holder._db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("budget:worker",))
                clock.setattr("src.governance.queued_intent_preparation.time.time",
                              lambda: deadlines[deadline_kind])
            with pytest.raises(AuthorityDenied):
                pending.result(timeout=15)
    assert snapshot(queued_app) == before
    assert session.task_events("native-task") == initial
    assert queued_app[0]._runtimes["alpha"].approvals.get(approval_id).status == "approved"
    assert runtime.operations.get("worker", record["submission"]["operation_id"]) is None


@pytest.mark.parametrize("winning_state", [TaskState.WORKING, TaskState.CANCELED])
def test_postgres_status_winner_during_lifecycle_wait_prevents_admission(
    queued_app, namespaces, authority, winning_state
):
    if not isinstance(queued_app[0]._runtimes["alpha"].store, PostgresStore):
        pytest.skip("requires genuine PostgreSQL independent-connection advisory waits")
    session, record, approval_id = approved(queued_app)
    worker, runtime, holder, observer = postgres_workers(queued_app, namespaces, authority)
    tasks = DurableTaskLifecycle(holder)
    owner = principal_owner(session.principal)
    before = snapshot(queued_app)
    initial = session.task_events("native-task")
    ready, deadlines = threading.Event(), {}
    with ThreadPoolExecutor(max_workers=1) as pool:
        with sql_atomic(holder):
            hold_admission_lock(holder, "lifecycle", record["submission"]["operation_id"])
            pending = pool.submit(prepare_worker, worker, session, record, ready, deadlines)
            assert ready.wait(8), "worker did not establish its own preparation guard"
            wait_for_advisory_block(observer, pending, runtime.store._db.info.backend_pid,
                                    holder._db.info.backend_pid)
            if winning_state == TaskState.CANCELED:
                winner = tasks.cancel(owner, "native-task", expected_sequence=0)
            else:
                winner = tasks.transition(owner, "native-task", winning_state, expected_sequence=0)
        with pytest.raises(AuthorityDenied):
            pending.result(timeout=15)
    expected = {**before, "counts": {**before["counts"],
                                     "task_lifecycle_events": before["counts"]["task_lifecycle_events"] + 1}}
    assert snapshot(queued_app) == expected
    assert session.task("native-task") == winner
    assert session.task_events("native-task") == initial + [winner]
    assert queued_app[0]._runtimes["alpha"].approvals.get(approval_id).status == "approved"
    assert runtime.operations.get("worker", record["submission"]["operation_id"]) is None
