"""Admission-bound dispatch prerequisites; this unit enables no send path."""

import pytest

from src.governance.authority import AuthorityDenied
from src.governance.queued_task_dispatch import _linked_history, _load_admitted
from src.governance.store import sql_atomic
from src.governance.task_execution_store import TaskExecutionStore
from src.governance.task_intents import IntentLimits
from src.governance.tenant_kernel import principal_owner
from src.protocols.task_lifecycle import TaskState
from tests.test_authority import authority as authority
from tests.test_queued_intent_preparation import accepted
from tests.test_task_admission import admit, snapshot
from tests.test_task_admission_transactions import approved
from tests.test_task_intents import authenticated, submission
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def linked(app, *, approval=False):
    if approval:
        session, record, _ = approved(app)
    else:
        session, record, _, _ = accepted(app)
    link = admit(app, session, record)
    runtime = app[0]._runtimes["alpha"]
    owner = principal_owner(session.principal)
    return runtime, session, record, link, owner


def decision(record, link, owner, *, kind="attempt"):
    return {"domain": "agentbridge.task-execution-decision.v1", "kind": kind,
            "owner_id": owner, "task_id": record["submission"]["task_id"], "agent_id": "worker",
            "operation_id": record["submission"]["operation_id"], "admission_link_sha256": link["link_sha256"],
            "attempt_id": "a" * 32}


def test_initial_loader_stays_initial_only_and_admitted_loader_is_exact(queued_app):
    runtime, session, record, link, owner = linked(queued_app)
    before = snapshot(queued_app)
    with pytest.raises(AuthorityDenied):
        runtime.task_intents._load_for_execution(owner, "native-task", record["intent_sha256"])
    intent, actual, current = _load_admitted(queued_app[0], runtime, owner, "native-task",
                                           record["intent_sha256"], link["link_sha256"])
    assert intent.record["provenance"] == record["provenance"]
    assert actual == link and (current.state, current.sequence) == (TaskState.WORKING, 1)
    for invalid in ("0" * 64, "", None):
        with pytest.raises(AuthorityDenied):
            _load_admitted(queued_app[0], runtime, owner, "native-task", record["intent_sha256"], invalid)
    assert snapshot(queued_app) == before


def test_current_dispatch_policy_does_not_charge_or_consume_again(queued_app, monkeypatch):
    runtime, session, record, link, owner = linked(queued_app, approval=True)
    before = snapshot(queued_app)

    def prohibited(*args, **kwargs):
        pytest.fail("dispatch policy is not a second admission")

    for component, method in ((runtime.budgets, "can_afford"), (runtime.budgets, "reserve"),
                              (runtime.approvals, "is_granted"), (runtime.approvals, "consume")):
        monkeypatch.setattr(component, method, prohibited)
    outcome = runtime.policy.current_dispatch_policy(
        agent_id="worker", capability="read", cost=1, src_protocol="mcp", dst_protocol="mcp",
        principal=session.principal, target_id="ledger",
    )
    assert outcome.allowed and outcome.approval_required
    assert _load_admitted(queued_app[0], runtime, owner, "native-task", record["intent_sha256"], link["link_sha256"])
    assert snapshot(queued_app) == before


@pytest.mark.parametrize("change", ["status", "reservation", "operation", "authority"])
def test_admitted_loader_refuses_changed_status_or_owned_accounting(queued_app, monkeypatch, change):
    runtime, session, record, link, owner = linked(queued_app)
    if change == "status":
        runtime.tasks.cancel(owner, "native-task", expected_sequence=1)
    elif change == "reservation":
        runtime.budgets.release("worker", link["reservation_token"])
    elif change == "operation":
        runtime.operations.finish("worker", link["operation_id"], "failed")
    else:
        monkeypatch.setattr(runtime.operations, "authority_binding", lambda *args: {"forged": True})
    with pytest.raises(AuthorityDenied):
        _load_admitted(queued_app[0], runtime, owner, "native-task", record["intent_sha256"], link["link_sha256"])
    if change == "status":
        # Historical evidence remains inspectable; canceled status is not a refund.
        assert _linked_history(queued_app[0], runtime, owner, "native-task", record["intent_sha256"], link["link_sha256"])
        assert runtime.store.get_budget("worker")["reserved"] == {link["reservation_token"]: 1}


def test_decision_is_one_shot_immutable_and_outer_rollback_owned(queued_app):
    runtime, session, record, link, owner = linked(queued_app)
    history = TaskExecutionStore(runtime.store)
    payload = decision(record, link, owner)
    with pytest.raises(RuntimeError, match="owned tenant transaction"):
        history.insert_decision(payload)
    with pytest.raises(RuntimeError, match="rollback"):
        with sql_atomic(runtime.store):
            inserted = history.insert_decision(payload)
            assert history.decision(owner, "native-task") == inserted
            raise RuntimeError("rollback")
    assert history.decision(owner, "native-task") is None
    with sql_atomic(runtime.store):
        inserted = history.insert_decision(payload)
    assert history.decision(owner, "native-task") == inserted
    for query in ("UPDATE task_execution_decisions_v1 SET kind='closed'", "DELETE FROM task_execution_decisions_v1"):
        with pytest.raises(Exception, match="immutable"):
            runtime.store._db.execute(query)
    with pytest.raises(Exception):
        with sql_atomic(runtime.store):
            history.insert_decision({**payload, "attempt_id": "b" * 32})
    assert runtime.operations.get("worker", link["operation_id"])["state"] == "unknown"
    assert runtime.store.get_budget("worker")["reserved"] == {link["reservation_token"]: 1}


def test_result_bytes_use_old_allowance_and_closed_decision_needs_no_result(queued_app):
    from dataclasses import asdict, replace

    queued_app[1]["alpha"].set_task_intent_capacity(**asdict(replace(IntentLimits(), max_result_bytes=1)))
    runtime, session, record, link, owner = linked(queued_app)
    history = TaskExecutionStore(runtime.store)
    payload = decision(record, link, owner)
    with sql_atomic(runtime.store):
        history.insert_decision(payload)
    with pytest.raises(Exception, match="unbounded"):
        with sql_atomic(runtime.store):
            history.insert_result({**payload, "outcome": "succeeded", "value": "too large"})
    assert history.result(owner, "native-task") is None
    assert record["result_limit_bytes"] == 1
    other, body, nonce = authenticated(queued_app, data=submission(
        task_id="refused-task", operation_id="refused-operation-123456",
    ))
    retained = other.submit_task(body, nonce=nonce)
    admitted = admit(queued_app, other, retained)
    with sql_atomic(runtime.store):
        history.insert_decision({**decision(retained, admitted, owner, kind="closed"),
                                 "reason": "immutable result allowance is insufficient"})
    assert history.decision(owner, "refused-task")["kind"] == "closed"
    assert history.result(owner, "refused-task") is None


@pytest.mark.parametrize("schema", ["partial", "unique", "partial_unique", "expression_unique"])
def test_execution_schema_fails_closed_on_partial_or_extra_restriction(namespaces, schema):
    from types import SimpleNamespace
    runtime = SimpleNamespace(store=namespaces("alpha"))
    if schema == "partial":
        runtime.store._db.execute("CREATE TABLE task_execution_results_v1(invalid TEXT)")
    else:
        TaskExecutionStore(runtime.store)
        expression = "lower(agent_id)" if schema == "expression_unique" else "agent_id"
        predicate = " WHERE kind='attempt'" if schema == "partial_unique" else ""
        runtime.store._db.execute("CREATE UNIQUE INDEX unsupported_execution_index ON task_execution_decisions_v1(" + expression + ")" + predicate)
    with pytest.raises(AuthorityDenied, match="schema"):
        TaskExecutionStore(runtime.store)


def test_admitted_loader_preserves_maximal_native_unicode_ids(queued_app):
    task_id, context_id, operation_id = "\U0001f9ed" * 128, "\U0001f30c" * 128, "\U0001f6f0" * 128
    session, body, nonce = authenticated(queued_app, data=submission(
        task_id=task_id, context_id=context_id, operation_id=operation_id,
    ))
    record = session.submit_task(body, nonce=nonce)
    link = admit(queued_app, session, record)
    runtime = queued_app[0]._runtimes["alpha"]
    loaded = _load_admitted(queued_app[0], runtime, principal_owner(session.principal), task_id,
                            record["intent_sha256"], link["link_sha256"])
    assert loaded[0].operation_id == operation_id and loaded[2].context_id == context_id
