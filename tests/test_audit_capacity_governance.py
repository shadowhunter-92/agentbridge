"""Real governed admission and settlement fail closed on audit saturation."""
import json
import uuid

import pytest

from src.governance.audit import AuditLog
from src.governance.audit_trust import AuditTrustStore
from src.governance.operation_ledger import OperationConflict
from src.protocols.task_lifecycle import TaskState
from tests.test_authority import authority as authority
from tests.test_queued_intent_preparation import accepted
from tests.test_task_admission import admit, snapshot
from tests.test_task_admission_transactions import approved
from tests.test_task_intents import queued_app as queued_app
from tests.test_tenant_kernel import signed_session
from tests.test_tenant_kernel import tenant_app as tenant_app
from tests.test_tenant_store import namespaces as namespaces


def saturate(runtime):
    trust = AuditTrustStore(runtime.store)
    current = trust.capacity()
    trust.set_capacity(max_records=current["used_records"], max_bytes=current["max_bytes"],
                       max_entry_bytes=current["max_entry_bytes"])
    return trust, trust.capacity()


def test_queued_saturation_rolls_back_real_approval_quota_reservation_and_link(queued_app):
    session, record, approval = approved(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    trust, capacity = saturate(runtime)
    before = snapshot(queued_app)
    events = session.task_events("native-task")
    with pytest.raises(Exception, match="audit capacity"):
        admit(queued_app, session, record)
    assert snapshot(queued_app) == before
    assert runtime.approvals.get(approval).status == "approved"
    assert session.task_events("native-task") == events
    assert session.task("native-task").state == TaskState.SUBMITTED
    assert trust.capacity() == capacity
    # Controlled capacity recovery permits the originally unexecuted admission;
    # the failed transaction left no operation identity or consumed approval.
    trust.set_capacity(max_records=capacity["max_records"] + 1, max_bytes=capacity["max_bytes"],
                       max_entry_bytes=capacity["max_entry_bytes"])
    result = admit(queued_app, session, record)
    assert result["operation_state_at_admission"] == "unknown"
    assert result["event_sequence"] == 1
    assert runtime.approvals.get(approval).status == "consumed"
    assert runtime.budgets.get("worker").reserved == 1
    assert trust.capacity()["used_records"] == capacity["used_records"] + 1


def test_missing_approval_and_saturated_denial_audit_leave_no_partial_pending_row(queued_app):
    queued_app[1]["alpha"].mark_sensitive("read")
    session, record, _, _ = accepted(queued_app)
    runtime = queued_app[0]._runtimes["alpha"]
    trust, capacity = saturate(runtime)
    before = snapshot(queued_app)
    with pytest.raises(Exception, match="audit capacity"):
        admit(queued_app, session, record)
    assert snapshot(queued_app) == before
    assert trust.capacity() == capacity
    assert session.task("native-task").state == TaskState.SUBMITTED


@pytest.mark.asyncio
async def test_real_effect_then_saturated_settlement_keeps_unknown_without_refund_or_replay(tenant_app):
    operation = "capacity-settlement-" + uuid.uuid4().hex
    session, body, nonce = signed_session(tenant_app, operation=operation)
    request = json.loads(body)
    runtime = tenant_app[0]._runtimes["alpha"]
    trust, capacity = saturate(runtime)
    effects = []

    async def invoke(wire):
        effects.append(wire)
        return {"ok": True}

    with pytest.raises(Exception, match="audit capacity"):
        await runtime.gateway.route_call(
            agent_id="worker", src_proto="mcp", dst_proto="mcp", src_wire=request["wire"],
            operation_id=operation, invoke=invoke, cost=1, signed_body=body,
            signed_nonce=nonce, principal=session.principal,
        )
    assert len(effects) == 1
    assert runtime.operations.get("worker", operation)["state"] == "unknown"
    budget = runtime.budgets.get("worker")
    assert budget.spent == 0 and budget.reserved == 1
    assert trust.capacity() == capacity
    assert not any(entry.action == "route_call" and entry.decision == "allow" for entry in runtime.audit.entries())
    assert AuditLog.verify_chain(runtime.store.load_audit(), require_genesis=True)
    again, next_body, next_nonce = signed_session(tenant_app, operation=operation)
    with pytest.raises(OperationConflict, match="no automatic replay"):
        await again.route(next_body, nonce=next_nonce)
    assert len(effects) == 1
