"""SQLite TEMP objects cannot replace durable execution control state."""
import json

import pytest

from src.governance.authority import AuthorityDenied
from src.governance.store import sql_atomic
from src.governance.task_execution_store import TaskExecutionStore
from tests.test_queued_dispatch_execution import _admit, _close, _effects, _open, _rows
from tests.test_queued_dispatch_execution import dispatch_app as dispatch_app

_EXECUTION_TABLES = (*TaskExecutionStore.TABLES, TaskExecutionStore.META)


def _shadow(store, table):
    with store._lock:
        source = store._db.execute("SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
        store._db.execute(source.replace("CREATE TABLE ", "CREATE TEMP TABLE ", 1))
        if table == TaskExecutionStore.META:
            store._db.execute("INSERT INTO temp." + table + " SELECT * FROM main." + table)


def _record(task, *, kind="closed"):
    return {"owner_id": task.refs[1], "task_id": task.refs[2], "agent_id": "worker",
            "operation_id": task.operation_id, "admission_link_sha256": task.admitted["link_sha256"],
            "domain": "agentbridge.task-execution-decision.v1", "kind": kind,
            "reason": "schema test only; no execution capability"}


def test_temp_decision_shadow_cannot_accept_a_volatile_marker(dispatch_app):
    app = dispatch_app
    task = _admit(app)
    _shadow(app.runtime.store, TaskExecutionStore.DECISIONS)
    with pytest.raises(AuthorityDenied, match="TEMP"):
        with sql_atomic(app.runtime.store):
            app.runtime.task_executions.insert_decision(_record(task))
    assert _rows(app.config["tenant_path"], TaskExecutionStore.DECISIONS) == []
    assert app.runtime.store._db.execute("SELECT count(*) FROM temp.task_execution_decisions_v1").fetchone()[0] == 0


def test_private_dispatch_refuses_temp_shadow_before_marker_or_effect(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    _shadow(app.runtime.store, TaskExecutionStore.DECISIONS)
    calls = []
    original = app.adapter.commit
    def commit(authorization, action_bytes):
        calls.append("destination-entry")
        return original(authorization, action_bytes)
    monkeypatch.setattr(app.adapter, "commit", commit)
    error = None
    try:
        app.kernel._dispatch_queued_once(*task.refs)
    except AuthorityDenied as exc:
        error = exc
    effects = _effects(app)
    markers = _rows(app.config["tenant_path"], TaskExecutionStore.DECISIONS)
    assert calls == [] and effects == [] and markers == [], {
        "calls": calls, "committed_effects": len(effects), "main_markers": len(markers),
    }
    assert isinstance(error, AuthorityDenied) and "TEMP" in str(error)
    assert app.runtime.store.get_budget("worker")["reserved"] == {task.admitted["reservation_token"]: 2}


@pytest.mark.parametrize("table", _EXECUTION_TABLES)
def test_bootstrap_rejects_each_existing_temp_execution_shadow(dispatch_app, table):
    app = dispatch_app
    _shadow(app.runtime.store, table)
    with pytest.raises(AuthorityDenied, match="TEMP"):
        TaskExecutionStore(app.runtime.store)


@pytest.mark.parametrize("table", _EXECUTION_TABLES)
@pytest.mark.parametrize("method", ["decision", "result", "cancellation"])
def test_each_read_refuses_all_execution_temp_shadows(dispatch_app, table, method):
    app = dispatch_app
    task = _admit(app)
    _shadow(app.runtime.store, table)
    with pytest.raises(AuthorityDenied, match="TEMP"):
        getattr(app.runtime.task_executions, method)(task.refs[1], task.refs[2])


@pytest.mark.parametrize("table", _EXECUTION_TABLES)
@pytest.mark.parametrize("method", ["insert_decision", "insert_result", "insert_cancellation"])
def test_each_write_refuses_all_execution_temp_shadows(dispatch_app, table, method):
    app = dispatch_app
    task = _admit(app)
    _shadow(app.runtime.store, table)
    record = _record(task)
    record["outcome"] = "succeeded"
    with pytest.raises(AuthorityDenied, match="TEMP"):
        with sql_atomic(app.runtime.store):
            getattr(app.runtime.task_executions, method)(record)
    assert _rows(app.config["tenant_path"], TaskExecutionStore.DECISIONS) == []
    assert _rows(app.config["tenant_path"], TaskExecutionStore.RESULTS) == []
    assert _rows(app.config["tenant_path"], TaskExecutionStore.CONTROLS) == []


def test_normal_main_marker_survives_restart_and_never_reacquires_or_resends(dispatch_app, monkeypatch):
    app = dispatch_app
    task = _admit(app)
    def stop_entry(*_):
        raise TimeoutError("local test stops at destination entry after durable main marker")
    monkeypatch.setattr(app.adapter, "commit", stop_entry)
    assert app.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
    main = _rows(app.config["tenant_path"], TaskExecutionStore.DECISIONS)
    assert len(main) == 1 and json.loads(main[0]["record"])["kind"] == "attempt"
    assert _effects(app) == []
    restarted = _open(app.config)
    try:
        calls = []
        def forbidden(*_):
            calls.append("retry")
            raise AssertionError("durable main marker forbids lease reacquisition and resend")
        monkeypatch.setattr(restarted.adapter, "acquire", forbidden)
        monkeypatch.setattr(restarted.adapter, "commit", forbidden)
        assert restarted.kernel._recover_queued(*task.refs)["state"] == "unknown"
        assert restarted.kernel._dispatch_queued_once(*task.refs)["state"] == "unknown"
        assert calls == []
        assert _rows(app.config["tenant_path"], TaskExecutionStore.DECISIONS) == main
        assert restarted.runtime.store.get_budget("worker")["reserved"] == {task.admitted["reservation_token"]: 2}
    finally:
        _close(restarted)
