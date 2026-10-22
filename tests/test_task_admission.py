"""First queued admission links local state atomically; no target is dispatched."""

import json

import pytest

from src.governance.authority import AuthorityDenied
from src.governance.tenant_kernel import principal_owner
from src.protocols.task_lifecycle import TaskState
from tests.test_authority import authority as authority
from tests.test_queued_intent_preparation import accepted
from tests.test_task_intents import count
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def admit(app, session, record):
    return app[0]._admit_queued_intent(
        "alpha", principal_owner(session.principal), record["submission"]["task_id"], record["intent_sha256"]
    )


def snapshot(app):
    runtime = app[0]._runtimes["alpha"]
    tables = ("task_intents_v1", "task_lifecycle_snapshots", "task_lifecycle_events", "agent_operations",
              "operation_authority", "operation_reservations", "admission_quota_records_v1", "approvals",
              "task_operation_links_v1")
    return {"budget": runtime.store.get_budget("worker"), "audit": runtime.store.load_audit_head(),
            "counts": {table: count(runtime.store, table) for table in tables}}


def test_first_admission_is_metadata_only_unknown_and_preserves_accepted_history(queued_app, monkeypatch):
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    before = snapshot(queued_app)
    initial = session.task_events("native-task")

    def prohibited(*args, **kwargs):
        pytest.fail("first admission cannot invoke or route a target")

    monkeypatch.setattr("src.proxy.transport.invoke_target", prohibited)
    monkeypatch.setattr(runtime.gateway, "route_call", prohibited)
    result = admit(queued_app, session, record)
    assert result["phase"] == "admitted" and result["execution_admitted"] is True
    assert result["operation_state_at_admission"] == "unknown"
    assert "wire" not in result and "principal" not in result and "target" not in result
    assert result["result_limit_bytes"] == record["result_limit_bytes"]
    assert result["original_authorization_expires_at"] == record["provenance"]["authorization_expires_at"]
    assert json.loads(json.dumps(result)) == result
    operation = runtime.operations.get("worker", result["operation_id"])
    assert operation["state"] == "unknown" and operation["fingerprint"] == result["action_sha256"]
    budget = runtime.store.get_budget("worker")
    assert budget["spent"] == 0 and budget["reserved"] == {result["reservation_token"]: 1.0}
    assert session.task_intent("native-task") == record
    events = session.task_events("native-task")
    assert events[:1] == initial and (events[-1].state, events[-1].sequence) == (TaskState.WORKING, 1)
    assert queued_app[0]._queued_admission("alpha", principal_owner(session.principal), "native-task",
                                          record["intent_sha256"]) == result
    after = snapshot(queued_app)
    for name in ("agent_operations", "operation_authority", "operation_reservations",
                 "admission_quota_records_v1", "task_operation_links_v1", "task_lifecycle_events"):
        assert after["counts"][name] == before["counts"][name] + 1
    assert after["counts"]["approvals"] == before["counts"]["approvals"]
    with pytest.raises(AuthorityDenied):
        admit(queued_app, session, record)
