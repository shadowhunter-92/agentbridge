"""Durable lifecycle ownership, recovery, contention and bounded consumption."""

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.governance.store import PostgresStore, SqliteStore
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle, LifecycleCapacity
from src.protocols.task_lifecycle import LifecycleRejected, TaskLifecycle, TaskState


@pytest.fixture(params=["sqlite", "postgres"])
def stores(request, tmp_path):
    handles = []
    if request.param == "sqlite":
        def factory():
            s = SqliteStore(str(tmp_path / "tasks.db"))
            handles.append(s)
            return s
        yield factory
    else:
        dsn = os.getenv("AGENTBRIDGE_TEST_PG")
        if not dsn:
            pytest.skip("explicit disposable PostgreSQL required")
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        schema = "ab_tasks_test_" + uuid.uuid4().hex
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            def factory():
                s = PostgresStore(make_conninfo(dsn, options="-csearch_path=" + schema))
                handles.append(s)
                return s
            try:
                yield factory
            finally:
                for s in handles:
                    s.close()
                handles.clear()
                admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
    for s in handles:
        s.close()


def submitted(task_id="task"):
    return TaskLifecycle(task_id, "context", "a2a")


def test_restart_cursor_resume_and_terminal_immutability(stores):
    first = DurableTaskLifecycle(stores())
    first.create("owner", submitted())
    first.transition("owner", "task", TaskState.WORKING, expected_sequence=0)
    reopened = DurableTaskLifecycle(stores())
    assert reopened.get("owner", "task").sequence == 1
    reopened.transition("owner", "task", TaskState.INPUT_REQUIRED, expected_sequence=1)
    reopened.transition("owner", "task", TaskState.WORKING, expected_sequence=2)
    reopened.transition("owner", "task", TaskState.COMPLETED, expected_sequence=3)
    assert [t.sequence for t in first.events("owner", "task", after_sequence=1, limit=2)] == [2, 3]
    assert first.events("owner", "task", after_sequence=4) == []
    with pytest.raises(LifecycleRejected):
        first.transition("owner", "task", TaskState.WORKING, expected_sequence=4)
    with pytest.raises(LifecycleRejected):
        first.create("owner", submitted())


def test_owner_scope_does_not_read_update_cancel_or_replay_another_task(stores):
    service = DurableTaskLifecycle(stores())
    service.create("alice", submitted())
    for action in (lambda: service.get("bob", "task"),
                   lambda: service.cancel("bob", "task", expected_sequence=0),
                   lambda: service.events("bob", "task")):
        with pytest.raises(LifecycleRejected, match="unavailable"):
            action()
    service.create("bob", submitted())
    service.cancel("bob", "task", expected_sequence=0)
    assert service.get("alice", "task").state == TaskState.SUBMITTED


def test_competing_connections_only_one_transition_commits(stores):
    one, two = DurableTaskLifecycle(stores()), DurableTaskLifecycle(stores())
    one.create("owner", submitted())
    def update(service):
        try:
            service.transition("owner", "task", TaskState.WORKING, expected_sequence=0)
            return True
        except LifecycleRejected:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, (one, two))) == [False, True]
    assert [t.sequence for t in two.events("owner", "task")] == [0, 1]


def test_capacity_is_atomic_and_terminal_releases_admission(stores):
    services = [DurableTaskLifecycle(stores(), max_active_per_owner=1) for _ in range(2)]
    def create(i):
        try:
            services[i].create("owner", submitted(str(i)))
            return i
        except LifecycleCapacity:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create, range(2)))
    accepted = [o for o in outcomes if o is not None]
    assert len(accepted) == 1
    services[0].cancel("owner", str(accepted[0]), expected_sequence=0)
    services[1].create("owner", submitted("replacement"))


def test_event_capacity_reserves_terminal_slot_and_stale_cancel_fails(stores):
    service = DurableTaskLifecycle(stores(), max_events_per_task=3)
    service.create("owner", submitted())
    service.transition("owner", "task", TaskState.WORKING, expected_sequence=0)
    with pytest.raises(LifecycleCapacity):
        service.transition("owner", "task", TaskState.INPUT_REQUIRED, expected_sequence=1)
    with pytest.raises(LifecycleRejected, match="stale"):
        service.cancel("owner", "task", expected_sequence=0)
    service.cancel("owner", "task", expected_sequence=1)
    assert service.get("owner", "task").terminal


@pytest.mark.parametrize("cursor,limit", [(True, 1), (-2, 1), (3, 1), (-1, True), (-1, 0), (-1, 101)])
def test_malformed_or_future_recovery_cursor_rejected(stores, cursor, limit):
    service = DurableTaskLifecycle(stores())
    service.create("owner", submitted())
    with pytest.raises(LifecycleRejected):
        service.events("owner", "task", after_sequence=cursor, limit=limit)


async def test_watch_reconnects_after_consumed_cursor_without_reexecution(stores):
    service = DurableTaskLifecycle(stores())
    service.create("owner", submitted())
    stream = service.watch("owner", "task", page_size=1, poll_seconds=0.01)
    assert (await anext(stream)).sequence == 0
    await stream.aclose()
    service.transition("owner", "task", TaskState.WORKING, expected_sequence=0)
    service.cancel("owner", "task", expected_sequence=1)
    history = [t async for t in service.watch("owner", "task", after_sequence=0, page_size=1, poll_seconds=0.01)]
    assert [t.sequence for t in history] == [1, 2]
    # Cancellation concerns status only: the SDK never creates operation/budget rows.
    assert service.store.get_budget("owner") is None


async def test_disconnect_and_async_cancellation_preserve_durable_task(stores):
    service = DurableTaskLifecycle(stores())
    service.create("owner", submitted())
    stream = service.watch("owner", "task", after_sequence=0, poll_seconds=0.01)
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.025)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await stream.aclose()
    assert service.get("owner", "task").state == TaskState.SUBMITTED
