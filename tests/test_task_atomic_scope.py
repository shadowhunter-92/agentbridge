"""Task status joins local governance commits without escaping tenant guards."""

import json
import os
import subprocess
import sys

import pytest

from src.governance.store import SqliteStore, sql_atomic
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
from src.protocols.task_lifecycle import LifecycleRejected, TaskLifecycle, TaskState
from tests.test_authority import authority as authority
from tests.test_tenant_store import namespaces as namespaces


def submitted():
    return TaskLifecycle("task", "context", "a2a")


def test_task_only_write_does_not_commit_outer_transaction(network_sql_stores):
    store = network_sql_stores()
    tasks = DurableTaskLifecycle(store)
    with pytest.raises(RuntimeError, match="abort task"):
        with sql_atomic(store):
            tasks.create("owner", submitted())
            raise RuntimeError("abort task")
    with pytest.raises(LifecycleRejected, match="unavailable"):
        tasks.get("owner", "task")


def test_budget_upsert_does_not_commit_outer_transaction(network_sql_stores):
    store = network_sql_stores()
    with pytest.raises(RuntimeError, match="abort budget"):
        with sql_atomic(store):
            store.upsert_budget("worker", {"spent": 4})
            raise RuntimeError("abort budget")
    assert store.get_budget("worker") is None


def test_task_creation_and_governance_write_share_outer_rollback(network_sql_stores):
    store = network_sql_stores()
    tasks = DurableTaskLifecycle(store)
    with pytest.raises(RuntimeError, match="abort outer"):
        with sql_atomic(store):
            store.upsert_budget("worker", {"spent": 4})
            tasks.create("owner", submitted())
            assert tasks.get("owner", "task").sequence == 0
            raise RuntimeError("abort outer")
    assert store.get_budget("worker") is None
    with pytest.raises(LifecycleRejected, match="unavailable"):
        tasks.get("owner", "task")
    assert store._db.execute("SELECT count(*) AS n FROM task_lifecycle_events").fetchone()["n"] == 0


def test_failed_nested_update_preserves_outer_write_and_prior_history(network_sql_stores):
    store = network_sql_stores()
    tasks = DurableTaskLifecycle(store)
    tasks.create("owner", submitted())
    with sql_atomic(store):
        store.upsert_budget("worker", {"spent": 4})
        with pytest.raises(LifecycleRejected, match="illegal"):
            tasks.transition("owner", "task", TaskState.COMPLETED, expected_sequence=0)
        tasks.transition("owner", "task", TaskState.WORKING, expected_sequence=0)
    assert store.get_budget("worker")["spent"] == 4
    assert [task.sequence for task in tasks.events("owner", "task")] == [0, 1]
    with pytest.raises(RuntimeError, match="abort terminal"):
        with sql_atomic(store):
            tasks.cancel("owner", "task", expected_sequence=1)
            raise RuntimeError("abort terminal")
    assert tasks.get("owner", "task").state == TaskState.WORKING
    assert [task.sequence for task in tasks.events("owner", "task")] == [0, 1]


@pytest.mark.parametrize("table", ["task_lifecycle_snapshots", "task_lifecycle_events"])
def test_new_task_tables_immediately_reject_legacy_writes(authority, namespaces, table):
    scoped = namespaces("alpha")
    tasks = DurableTaskLifecycle(scoped)
    tasks.create("owner", submitted())
    legacy = namespaces("alpha", legacy=True)
    with pytest.raises(Exception, match="tenant write scope|agentbridge_current_tenant"):
        legacy._db.execute("DELETE FROM " + table)
    assert len(tasks.events("owner", "task")) == 1
    assert tasks.get("owner", "task").sequence == 0


@pytest.mark.parametrize("stage", ["create", "transition"])
def test_process_death_before_outer_commit_preserves_status_and_governance(
    network_sql_stores, tmp_path, stage
):
    store = network_sql_stores()
    tasks = DurableTaskLifecycle(store)
    store.upsert_budget("worker", {"spent": 1})
    if stage == "transition":
        tasks.create("owner", submitted())
    if isinstance(store, SqliteStore):
        config = {"backend": "sqlite", "path": store._db.execute("PRAGMA database_list").fetchone()["file"]}
    else:
        from psycopg.conninfo import make_conninfo

        config = {"backend": "postgres", "dsn": make_conninfo(store._db.info.dsn, password=store._db.info.password)}
    config["stage"] = stage
    child = tmp_path / "crash_task.py"
    child.write_text('''
import json, os
from src.governance.store import SqliteStore, PostgresStore, sql_atomic
from src.protocols.durable_task_lifecycle import DurableTaskLifecycle
from src.protocols.task_lifecycle import TaskLifecycle, TaskState
c = json.loads(os.environ["AGENTBRIDGE_CRASH_TASK"])
s = SqliteStore(c["path"]) if c["backend"] == "sqlite" else PostgresStore(c["dsn"])
t = DurableTaskLifecycle(s)
with sql_atomic(s):
    s.upsert_budget("worker", {"spent": 9})
    if c["stage"] == "create":
        t.create("owner", TaskLifecycle("task", "context", "a2a"))
    else:
        t.transition("owner", "task", TaskState.WORKING, expected_sequence=0)
    os._exit(75)
''', encoding="utf-8")
    environment = os.environ.copy()
    environment.update(AGENTBRIDGE_CRASH_TASK=json.dumps(config), PYTHONPATH=os.getcwd())
    result = subprocess.run([sys.executable, str(child)], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 75, result.stderr
    assert store.get_budget("worker")["spent"] == 1
    if stage == "create":
        with pytest.raises(LifecycleRejected, match="unavailable"):
            tasks.get("owner", "task")
        assert store._db.execute("SELECT count(*) AS n FROM task_lifecycle_events").fetchone()["n"] == 0
    else:
        assert tasks.get("owner", "task").state == TaskState.SUBMITTED
        assert [task.sequence for task in tasks.events("owner", "task")] == [0]
