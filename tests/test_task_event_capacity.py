"""Retained event bytes reserve room for terminal events across SQL workers."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from src.governance.store import PostgresStore, SqliteStore, sql_atomic
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle, LifecycleCapacity
from src.protocols.task_lifecycle import LifecycleRejected, TaskLifecycle, TaskState
from tests.test_authority import ISSUER
from tests.test_authority import authority as authority
from tests.test_tenant_http import http_app as http_app
from tests.test_tenant_http import operator
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def task(identity="task"):
    return TaskLifecycle(identity, "context", "a2a")


def size(service, value):
    return len(service._encode(value).encode("utf-8"))


def test_byte_saturation_preserves_terminal_room_for_every_active_task(network_sql_stores):
    service = DurableTaskLifecycle(network_sql_stores())
    for owner in ("one", "two"):
        service.create(owner, task(owner))
    usage = service.event_capacity()
    working = size(service, task("one").transition(TaskState.WORKING, sequence=1))
    cap = usage["used_event_bytes"] + usage["reserved_control_bytes"] + working
    service.set_event_capacity(cap)
    service.transition("one", "one", TaskState.WORKING, expected_sequence=0)
    with pytest.raises(LifecycleCapacity, match="event-byte capacity"):
        service.transition("two", "two", TaskState.WORKING, expected_sequence=0)
    assert service.get("two", "two").sequence == 0
    service.cancel("one", "one", expected_sequence=1)
    service.cancel("two", "two", expected_sequence=0)
    final = service.event_capacity()
    assert final["reserved_control_bytes"] == 0 and final["used_event_bytes"] <= cap
    assert len(service.events("one", "one")) == 3
    assert len(service.events("two", "two")) == 2


def test_saturated_create_does_not_leave_snapshot_or_consume_task_history(network_sql_stores):
    service = DurableTaskLifecycle(network_sql_stores())
    service.set_event_capacity(4096)
    with pytest.raises(LifecycleCapacity, match="event-byte"):
        service.create("owner", task())
    assert service.history_capacity()["used_tasks"] == 0
    assert service.event_capacity()["used_event_bytes"] == 0
    service.set_event_capacity(10000)
    service.create("owner", task())
    with pytest.raises(LifecycleCapacity):
        service.create("other", task("other"))
    service.cancel("owner", "task", expected_sequence=0)
    service.create("other", task("other"))


@pytest.mark.parametrize("state", [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED, TaskState.REJECTED])
def test_reserved_terminal_bound_covers_maximum_unicode_identifiers_and_sequence(state):
    value = TaskLifecycle("\U0001f680" * 128, "\U0001f680" * 128, "a2a", state, 2**63 - 1)
    assert len(DurableTaskLifecycle._encode(value).encode("utf-8")) <= 4096


def test_restart_and_actual_utf8_storage_accounting(network_sql_stores):
    store = network_sql_stores()
    service = DurableTaskLifecycle(store)
    service.create("owner", TaskLifecycle("\U0001f680", "\u00e9", "a2a"))
    raw = service._encode(service.get("owner", "\U0001f680"))
    # A historical serializer can store equivalent UTF-8 instead of JSON escapes.
    raw = raw.replace("\\ud83d\\ude80", "\U0001f680").replace("\\u00e9", "\u00e9")
    with sql_atomic(store):
        cur = store._db.cursor()
        try:
            service._execute(cur, "UPDATE task_lifecycle_events SET snapshot=?", (raw,))
        finally:
            cur.close()
    service.set_event_capacity(10000)
    reopened = DurableTaskLifecycle(network_sql_stores())
    assert reopened.event_capacity() == {
        "max_event_bytes": 10000,
        "used_event_bytes": len(raw.encode("utf-8")),
        "reserved_control_bytes": 8192,
    }
    with pytest.raises(LifecycleCapacity, match="cannot overwrite"):
        DurableTaskLifecycle(network_sql_stores(), initial_max_event_bytes=6000)


@pytest.mark.parametrize("table", ["task_lifecycle_event_policy_v1", "task_lifecycle_event_meta_v1"])
@pytest.mark.parametrize("damage", ["missing-row", "unknown-version", "missing-table"])
def test_missing_event_policy_never_silently_reseeds(network_sql_stores, table, damage):
    store = network_sql_stores()
    service = DurableTaskLifecycle(store)
    service.set_event_capacity(10000)
    if damage == "missing-table":
        store._db.execute("DROP TABLE " + table)
    elif damage == "missing-row":
        store._db.execute("DELETE FROM " + table)
    else:
        store._db.execute("UPDATE " + table + " SET version=99")
    with pytest.raises(LifecycleCapacity, match="capacity (schema|policy)"):
        DurableTaskLifecycle(network_sql_stores())


@pytest.mark.parametrize("table", ["task_lifecycle_event_policy_v1", "task_lifecycle_event_meta_v1"])
def test_event_tables_immediately_reject_unscoped_writes(authority, namespaces, table):
    service = DurableTaskLifecycle(namespaces("alpha"))
    old = namespaces("alpha", legacy=True)
    with pytest.raises(Exception, match="tenant write scope|agentbridge_current_tenant"):
        old._db.execute("DELETE FROM " + table)
    assert service.event_capacity()["max_event_bytes"] == 67108864


def raw_transition(store, service, owner, state):
    with sql_atomic(store):
        cur = store._db.cursor()
        try:
            current = service._execute(
                cur, "SELECT snapshot FROM task_lifecycle_snapshots WHERE owner_id=? AND task_id=?", (owner, owner)
            ).fetchone()
            current = service._decode(current["snapshot"])
            updated = current.transition(state, sequence=current.sequence + 1)
            raw = service._encode(updated)
            service._execute(
                cur, "INSERT INTO task_lifecycle_events VALUES(?,?,?,?)", (owner, owner, updated.sequence, raw)
            )
            service._execute(
                cur,
                "UPDATE task_lifecycle_snapshots SET snapshot=?,terminal=? WHERE owner_id=? AND task_id=?",
                (raw, int(updated.terminal), owner, owner),
            )
        finally:
            cur.close()


def test_older_raw_worker_cannot_spend_another_tasks_terminal_reserve(authority, namespaces):
    service = DurableTaskLifecycle(namespaces("alpha"))
    for owner in ("one", "two"):
        service.create(owner, task(owner))
    usage = service.event_capacity()
    service.set_event_capacity(usage["used_event_bytes"] + usage["reserved_control_bytes"])
    old = namespaces("alpha")
    with pytest.raises(Exception, match="event-byte capacity"):
        raw_transition(old, service, "one", TaskState.WORKING)
    raw_transition(old, service, "one", TaskState.CANCELED)
    raw_transition(old, service, "two", TaskState.CANCELED)
    assert service.event_capacity()["reserved_control_bytes"] == 0
    assert service.get("one", "one").terminal and service.get("two", "two").terminal


def test_old_postgres_worker_rechecks_byte_budget_after_real_lock_wait(authority, namespaces):
    first = namespaces("alpha")
    if not isinstance(first, PostgresStore):
        pytest.skip("PostgreSQL trigger visibility after held transaction")
    second = namespaces("alpha")
    service = DurableTaskLifecycle(first)
    for owner in ("one", "two"):
        service.create(owner, task(owner))
    usage = service.event_capacity()
    service.set_event_capacity(
        usage["used_event_bytes"]
        + usage["reserved_control_bytes"]
        + size(service, task("one").transition(TaskState.WORKING, sequence=1))
    )

    def second_insert():
        with pytest.raises(Exception, match="event-byte capacity"):
            raw_transition(second, service, "two", TaskState.WORKING)

    future = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            with sql_atomic(first):
                raw_transition(first, service, "one", TaskState.WORKING)
                future = pool.submit(second_insert)
                deadline = time.monotonic() + 5
                while not first._db.execute(
                    "SELECT %s=ANY(pg_blocking_pids(%s)) AS blocked",
                    (first._db.info.backend_pid, second._db.info.backend_pid),
                ).fetchone()["blocked"]:
                    if future.done():
                        future.result()
                        pytest.fail("expected trigger blocker absent")
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
        finally:
            if future is not None:
                future.result(timeout=10)
    assert service.get("two", "two").sequence == 0
    service.cancel("two", "two", expected_sequence=0)


def test_competing_replicas_share_event_capacity(authority, namespaces):
    services = [DurableTaskLifecycle(namespaces("alpha")) for _ in range(2)]
    services[0].set_event_capacity(10000)

    def create(index):
        try:
            services[index].create(str(index), task(str(index)))
            return True
        except LifecycleCapacity:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, range(2))) == [False, True]
    assert services[0].history_capacity()["used_tasks"] == 1
    beta = DurableTaskLifecycle(namespaces("beta"))
    assert beta.event_capacity()["used_event_bytes"] == 0


def test_callback_and_outer_rollback_restore_policy_events_and_reservations(tenant_app, monkeypatch):
    kernel, admins, *_ = tenant_app
    service = kernel._runtimes["alpha"].tasks
    before = service.event_capacity()

    original = kernel._runtimes["alpha"].audit.record
    before_audit = kernel._runtimes["alpha"].audit.count()

    def fail(**kwargs):
        original(**kwargs)
        raise RuntimeError("abort event policy audit")

    monkeypatch.setattr(kernel._runtimes["alpha"].audit, "record", fail)
    with pytest.raises(RuntimeError, match="event policy audit"):
        admins["alpha"].set_task_event_capacity(10000)
    assert service.event_capacity() == before
    assert kernel._runtimes["alpha"].audit.count() == before_audit
    with pytest.raises(RuntimeError, match="abort create"):
        with sql_atomic(service.store):
            service.create("owner", task())
            raise RuntimeError("abort create")
    assert service.event_capacity() == before
    service.create("owner", task())
    before = service.event_capacity()
    with pytest.raises(RuntimeError, match="abort terminal"):
        with sql_atomic(service.store):
            service.cancel("owner", "task", expected_sequence=0)
            raise RuntimeError("abort terminal")
    assert service.event_capacity() == before
    with pytest.raises(LifecycleCapacity, match="control reservations"):
        service.set_event_capacity(4096)


@pytest.mark.parametrize("limit", [True, 4095, 1073741825, "10000", None])
def test_invalid_event_capacity_rejected(network_sql_stores, limit):
    service = DurableTaskLifecycle(network_sql_stores())
    with pytest.raises(LifecycleRejected):
        service.set_event_capacity(limit)


@pytest.mark.asyncio
async def test_event_capacity_http_permissions_validation_and_tenant_scope(tenant_app, http_app, loopback_server):
    directory, owner = tenant_app[4:]
    directory.enroll_member(owner, "alpha", ISSUER, "viewer", role="tenant_viewer")
    with loopback_server(lambda _: http_app) as (url, _):
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            endpoint = "/v2/operator/task-event-capacity"
            assert (
                await client.put(
                    endpoint, headers=operator(tenant_app, subject="viewer"), json={"max_event_bytes": 10000}
                )
            ).status_code == 403
            assert (
                await client.put(endpoint, headers=operator(tenant_app), json={"max_event_bytes": 10000})
            ).status_code == 200
            assert (await client.get(endpoint, headers=operator(tenant_app))).json()["max_event_bytes"] == 10000
            assert (await client.get(endpoint, headers=operator(tenant_app, "beta"))).json()[
                "max_event_bytes"
            ] == 67108864
            assert (
                await client.put(endpoint, headers=operator(tenant_app), json={"max_event_bytes": True})
            ).status_code == 400


def test_prior_task_schema_upgrade_is_atomic_and_preserves_exact_history(network_sql_stores):
    store = network_sql_stores()
    identifier = "\U0001f680" * 128
    submitted = TaskLifecycle(identifier, identifier, "a2a")
    working = submitted.transition(TaskState.WORKING, sequence=1)
    before = [DurableTaskLifecycle._encode(value) for value in (submitted, working)]
    with sql_atomic(store):
        cur = store._db.cursor()
        try:
            cur.execute(
                "CREATE TABLE task_lifecycle_snapshots (owner_id TEXT NOT NULL,task_id TEXT NOT NULL,snapshot TEXT NOT NULL,terminal INTEGER NOT NULL,PRIMARY KEY(owner_id,task_id))"
            )
            cur.execute(
                "CREATE TABLE task_lifecycle_events (owner_id TEXT NOT NULL,task_id TEXT NOT NULL,sequence BIGINT NOT NULL,snapshot TEXT NOT NULL,PRIMARY KEY(owner_id,task_id,sequence))"
            )
            placeholder = "?" if isinstance(store, SqliteStore) else "%s"
            cur.execute(
                "INSERT INTO task_lifecycle_snapshots VALUES(" + ",".join([placeholder] * 4) + ")",
                ("owner", identifier, before[1], 0),
            )
            for sequence, raw in enumerate(before):
                cur.execute(
                    "INSERT INTO task_lifecycle_events VALUES(" + ",".join([placeholder] * 4) + ")",
                    ("owner", identifier, sequence, raw),
                )
        finally:
            cur.close()
    with pytest.raises(LifecycleCapacity, match="reviewed event-byte capacity recovery"):
        DurableTaskLifecycle(store, initial_max_event_bytes=8000)
    if isinstance(store, SqliteStore):
        assert (
            store._db.execute("SELECT name FROM sqlite_master WHERE name='task_lifecycle_event_policy_v1'").fetchone()
            is None
        )
    else:
        assert (
            store._db.execute("SELECT to_regclass('task_lifecycle_event_policy_v1') AS relation").fetchone()["relation"]
            is None
        )
    service = DurableTaskLifecycle(store, initial_max_event_bytes=20000)
    assert [
        row["snapshot"]
        for row in store._db.execute("SELECT snapshot FROM task_lifecycle_events ORDER BY sequence").fetchall()
    ] == before
    assert service.event_capacity()["used_event_bytes"] == sum(len(raw.encode("utf-8")) for raw in before)
    assert service.get("owner", identifier) == working
    service.cancel("owner", identifier, expected_sequence=1)


def test_process_death_after_terminal_event_insert_preserves_reserved_headroom(network_sql_stores, tmp_path):
    store = network_sql_stores()
    service = DurableTaskLifecycle(store)
    service.create("owner", task())
    before = service.event_capacity()
    service.set_event_capacity(before["used_event_bytes"] + before["reserved_control_bytes"])
    before = service.event_capacity()
    if isinstance(store, SqliteStore):
        config = {"backend": "sqlite", "path": store._db.execute("PRAGMA database_list").fetchone()["file"]}
    else:
        from psycopg.conninfo import make_conninfo

        config = {"backend": "postgres", "dsn": make_conninfo(store._db.info.dsn, password=store._db.info.password)}
    child = tmp_path / "crash_event.py"
    child.write_text(
        """import os,json
from src.governance.store import SqliteStore,PostgresStore
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
c=json.loads(os.environ["AGENTBRIDGE_CRASH_EVENT"])
s=SqliteStore(c["path"]) if c["backend"]=="sqlite" else PostgresStore(c["dsn"])
t=DurableTaskLifecycle(s)
original=t._execute
def crash(cur,query,values):
    result=original(cur,query,values)
    if query.startswith("INSERT INTO task_lifecycle_events"):
        os._exit(75)
    return result
t._execute=crash
t.cancel("owner","task",expected_sequence=0)
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(AGENTBRIDGE_CRASH_EVENT=json.dumps(config), PYTHONPATH=os.getcwd())
    result = subprocess.run([sys.executable, str(child)], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 75, result.stderr
    assert service.event_capacity() == before
    assert service.get("owner", "task").state == TaskState.SUBMITTED
    assert len(service.events("owner", "task")) == 1
    service.cancel("owner", "task", expected_sequence=0)


@pytest.mark.parametrize("wait_state", [TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED])
def test_saturated_byte_budget_allows_one_recovery_wait_then_terminal(network_sql_stores, wait_state):
    service = DurableTaskLifecycle(network_sql_stores())
    service.create("owner", task())
    service.transition("owner", "task", TaskState.WORKING, expected_sequence=0)
    usage = service.event_capacity()
    service.set_event_capacity(usage["used_event_bytes"] + usage["reserved_control_bytes"])
    service.transition("owner", "task", wait_state, expected_sequence=1)
    assert service.event_capacity()["reserved_control_bytes"] == 4096
    with pytest.raises(LifecycleCapacity, match="event-byte capacity"):
        service.transition("owner", "task", TaskState.WORKING, expected_sequence=2)
    assert service.get("owner", "task").state == wait_state
    service.cancel("owner", "task", expected_sequence=2)
    assert service.event_capacity()["reserved_control_bytes"] == 0


def test_older_raw_worker_has_bounded_recovery_wait_and_terminal_headroom(authority, namespaces):
    service = DurableTaskLifecycle(namespaces("alpha"))
    service.create("owner", task("owner"))
    usage = service.event_capacity()
    service.set_event_capacity(usage["used_event_bytes"] + usage["reserved_control_bytes"])
    old = namespaces("alpha")
    raw_transition(old, service, "owner", TaskState.AUTH_REQUIRED)
    assert service.event_capacity()["reserved_control_bytes"] == 4096
    with pytest.raises(Exception, match="event-byte capacity"):
        raw_transition(old, service, "owner", TaskState.WORKING)
    assert service.get("owner", "owner").state == TaskState.AUTH_REQUIRED
    raw_transition(old, service, "owner", TaskState.CANCELED)
    assert service.event_capacity()["reserved_control_bytes"] == 0
