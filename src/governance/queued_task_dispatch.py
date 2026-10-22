"""Private admission-bound one-shot dispatch; generic transports are excluded."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass

from ..protocols.task_lifecycle import TaskState
from .authority import AuthorityDenied
from .fenced_sqlite_destination import SqliteFenceDenied
from .operation_ledger import OperationConflict
from .owned_settlement import lock_unknown_operation, settle_owned_reservation
from .queued_destination_contract import QUEUED_RESULT_ENVELOPE_LIMIT_BYTES, canonical_demo_action
from .queued_intent_preparation import (
    _assert_queued_lifetime,
    _authority_seal,
    _derive,
    _json,
    _plan,
    _QueuedIntentAuthority,
    _require_read_committed,
)
from .store import PostgresStore, SqliteStore, sql_atomic
from .task_admission import _action_scope
from .trust_sdk import verify_queued_action_evidence


def _execute(runtime, query, values=()):
    return runtime.store._db.execute(query.replace("?", "%s") if isinstance(runtime.store, PostgresStore) else query, values)


def _linked_history(kernel, runtime, owner_id, task_id, intent_sha256, admission_link_sha256):
    """Exact immutable linkage, without renewing authority or taking lifecycle.

    Readback of a historical execution may use this after original expiry. First
    dispatch additionally requires a fresh enrolled guard and the checks below.
    """
    if kernel.storage._stores.get(runtime.store.tenant_id) is not runtime.store:
        raise AuthorityDenied("operator-bound dispatch runtime required")
    intent, initial, current = runtime.task_intents._load_immutable(owner_id, task_id, intent_sha256)
    link = runtime.task_admissions.get(owner_id, task_id, intent_sha256)
    if link["link_sha256"] != admission_link_sha256:
        raise AuthorityDenied("exact immutable admission link required")
    with runtime.store._lock:
        admission = _execute(runtime, "SELECT snapshot FROM task_operation_links_v1 WHERE owner_id=? AND task_id=?",
                             (owner_id, task_id)).fetchone()
        event = _execute(runtime, "SELECT snapshot FROM task_lifecycle_events WHERE owner_id=? AND task_id=? AND sequence=1",
                         (owner_id, task_id)).fetchone()
    expected = initial.transition(TaskState.WORKING, sequence=1)
    if admission is None or event is None or admission["snapshot"] != event["snapshot"] or \
            runtime.tasks._decode(event["snapshot"]) != expected:
        raise AuthorityDenied("admission event linkage unavailable")
    provenance = intent.record["provenance"]
    action = intent.record["submission"]
    original = _action_scope(agent_id=intent.agent_id, src=action["src"], dst=action["dst"], wire=action["wire"],
                             cost=provenance["operator_cost"], target_id=action["target_id"],
                             operation_id=intent.operation_id, authority=provenance["authority"])
    scope = hashlib.sha256(json.dumps({
        "domain": "agentbridge.queued-action.v1", "owner_id": owner_id, "task_id": task_id,
        "intent_sha256": intent_sha256, "original_action_sha256": original,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if link["action_sha256"] != scope or link["original_action_sha256"] != original or \
            link["target_configuration_sha256"] != provenance["target_configuration_sha256"]:
        raise AuthorityDenied("admission action or target binding unavailable")
    if (link["tenant_id"], link["owner_id"], link["task_id"], link["context_id"], link["agent_id"],
        link["operation_id"], link["intent_sha256"], link["result_limit_bytes"],
        link["original_authorization_expires_at"], link["reserved_cost"], link["event_sequence"]) != (
            runtime.store.tenant_id, owner_id, task_id, initial.context_id, intent.agent_id, intent.operation_id,
            intent_sha256, intent.result_limit_bytes, provenance["authorization_expires_at"],
            provenance["operator_cost"], 1):
        raise AuthorityDenied("admission does not match immutable accepted intent")
    operation = runtime.operations.get(intent.agent_id, intent.operation_id)
    binding = runtime.operations.authority_binding(intent.agent_id, intent.operation_id)
    if operation is None or operation["fingerprint"] != link["action_sha256"] or \
            json.dumps(binding, sort_keys=True) != json.dumps(provenance["authority"], sort_keys=True):
        raise AuthorityDenied("admission operation or authority binding unavailable")
    return intent, link, initial, current, operation


def _load_admitted(kernel, runtime, owner_id, task_id, intent_sha256, admission_link_sha256):
    """First-dispatch integrity loader, separate from initial-only preparation."""
    intent, link, initial, current, operation = _linked_history(
        kernel, runtime, owner_id, task_id, intent_sha256, admission_link_sha256,
    )
    if current != initial.transition(TaskState.WORKING, sequence=1) or operation["state"] != "unknown":
        raise AuthorityDenied("first dispatch requires the unchanged admitted task and UNKNOWN operation")
    with runtime.store._lock:
        reservation = _execute(runtime, "SELECT token FROM operation_reservations WHERE agent_id=? AND operation_id=?",
                               (intent.agent_id, intent.operation_id)).fetchone()
        budget = runtime.store.get_budget(intent.agent_id)
    amount = budget.get("reserved", {}).get(link["reservation_token"]) if isinstance(budget, dict) else None
    if reservation is None or reservation["token"] != link["reservation_token"] or type(amount) not in (int, float) or \
            amount != link["reserved_cost"]:
        raise AuthorityDenied("exact already-held admission reservation required")
    if type(link["approval_required"]) is not bool:
        raise AuthorityDenied("recorded admission approval decision required")
    if link["approval_required"]:
        with runtime.store._lock:
            consumed = _execute(runtime,
                                "SELECT 1 FROM approvals WHERE agent_id=? AND capability=? AND status='consumed' LIMIT 1",
                                (intent.agent_id, intent.record["provenance"]["capability"] + "|" + link["action_sha256"])).fetchone()
        if consumed is None:
            raise AuthorityDenied("exact admission-scoped consumed grant unavailable")
    return intent, link, current


def _runtime(kernel, tenant_id):
    runtime = kernel._runtimes.get(tenant_id)
    if runtime is None or kernel.storage._stores.get(tenant_id) is not runtime.store:
        raise AuthorityDenied("operator-bound dispatch runtime required")
    if kernel.environment in ("prod", "production"):
        raise AuthorityDenied("queued demo dispatch is nonproduction only")
    return runtime


def _budget_lock(runtime, agent_id):
    if isinstance(runtime.store, PostgresStore):
        _execute(runtime, "SELECT pg_advisory_xact_lock(hashtext(?))", ("budget:" + agent_id,))


def _idle(runtime):
    # A savepoint release cannot establish the durable-before-call boundary.
    # Callers may compose settlement, but first dispatch must own the commit.
    with runtime.store._lock:
        if isinstance(runtime.store, SqliteStore):
            busy = runtime.store._db.in_transaction
        else:
            from psycopg.pq import TransactionStatus
            busy = runtime.store._db.info.transaction_status != TransactionStatus.IDLE
        if busy:
            raise AuthorityDenied("first dispatch requires its own durable transaction")


def _audit(runtime, intent, action, reason):
    runtime.audit.record(actor="queued-task:" + intent.owner_id, action=action,
                         source_protocol="mcp", target_protocol="mcp", capability=intent.record["provenance"]["capability"],
                         decision="allow", cost=0.0, reason=reason)


def _base(intent, link):
    return {"owner_id": intent.owner_id, "task_id": intent.task_id, "agent_id": intent.agent_id,
            "operation_id": intent.operation_id, "admission_link_sha256": link["link_sha256"]}


@contextmanager
def _guard_admitted(kernel, runtime, refs):
    directory = kernel.directory
    with directory._transaction(claim=isinstance(directory.store, SqliteStore)) as cur:
        _require_read_committed(cur)
        intent, _, _ = _load_admitted(kernel, runtime, *refs)
        principal, deadline = _derive(directory, cur, runtime.task_intents, intent,
                                      valid_until=time.time() + min(30, kernel.deadline_seconds))
        lease = object()
        guards = getattr(directory._transaction_context, "queued_intent_guards", None)
        if guards is None:
            guards = directory._transaction_context.queued_intent_guards = set()
        guards.add(lease)
        authority = _QueuedIntentAuthority(intent, principal, runtime.store.store_id, deadline, lease)
        from dataclasses import replace
        authority = replace(authority, _proof=_authority_seal(directory, authority))
        try:
            yield authority
        finally:
            guards.discard(lease)
            if not guards:
                del directory._transaction_context.queued_intent_guards


def _current(kernel, runtime, authority, refs):
    _assert_queued_lifetime(kernel.directory, authority, runtime.task_intents)
    intent, link, current = _load_admitted(kernel, runtime, *refs)
    if intent != authority.intent:
        raise AuthorityDenied("admitted intent changed under execution guard")
    plan = json.loads(_plan(kernel, runtime, authority))
    if plan["target"].get("kind") != "queued_fenced_sqlite_v2":
        raise AuthorityDenied("explicit queued-only destination required")
    decision = runtime.policy.current_dispatch_policy(
        agent_id=intent.agent_id, capability=plan["capability"], cost=plan["cost"], src_protocol=plan["src"],
        dst_protocol=plan["dst"], principal=authority.principal, target_id=plan["target_id"])
    if not decision.allowed or (decision.approval_required and not link["approval_required"]):
        raise AuthorityDenied("current policy requires an admission-scoped consumed approval")
    return intent, link, current, plan


def execution(kernel, tenant_id, owner_id, task_id, intent_sha256, admission_link_sha256):
    runtime = _runtime(kernel, tenant_id)
    _linked_history(kernel, runtime, owner_id, task_id, intent_sha256, admission_link_sha256)
    return {"decision": runtime.task_executions.decision(owner_id, task_id),
            "result": runtime.task_executions.result(owner_id, task_id),
            "cancellation": runtime.task_executions.cancellation(owner_id, task_id)}


def _status(runtime, owner_id, task_id):
    decision = runtime.task_executions.decision(owner_id, task_id)
    result = runtime.task_executions.result(owner_id, task_id)
    return {"state": result["outcome"] if result else "closed" if decision and decision["kind"] == "closed" else "unknown",
            "decision_sha256": decision["record_sha256"] if decision else None, "result": result}


def _close(runtime, intent, link, *, reason, terminal):
    # Only a transactionally absent immutable attempt permits this no-effect
    # decision. UNKNOWN alone never proves that an existing attempt did nothing.
    if runtime.task_executions.decision(intent.owner_id, intent.task_id) is not None:
        raise AuthorityDenied("execution decision already exists")
    runtime.task_executions.insert_decision({**_base(intent, link),
        "domain": "agentbridge.task-execution-decision.v1", "kind": "closed", "reason": reason})
    settle_owned_reservation(runtime.store, runtime.budgets, runtime.operations, agent_id=intent.agent_id,
                             operation_id=intent.operation_id, token=link["reservation_token"], outcome="failed",
                             expected_cost=link["reserved_cost"])
    current = runtime.tasks.get(intent.owner_id, intent.task_id)
    if not current.terminal:
        runtime.tasks.transition(intent.owner_id, intent.task_id, terminal, expected_sequence=current.sequence)
    _audit(runtime, intent, "task.closed-before-dispatch", reason)


def dispatch_once(kernel, tenant_id, owner_id, task_id, intent_sha256, admission_link_sha256):
    runtime = _runtime(kernel, tenant_id)
    refs = owner_id, task_id, intent_sha256, admission_link_sha256
    _idle(runtime)
    _linked_history(kernel, runtime, *refs)
    if runtime.task_executions.decision(owner_id, task_id) is not None:
        return recover(kernel, tenant_id, *refs)
    if not kernel._queued_dispatch_slots.acquire(blocking=False):
        raise AuthorityDenied("bounded queued worker is busy")
    try:
        attempted = False
        with _guard_admitted(kernel, runtime, refs) as authority:
            # Preliminary observations do not authorize the call. All loader,
            # policy and marker checks are repeated under owned SQL locks below.
            intent, link, _, plan = _current(kernel, runtime, authority, refs)
            adapter = kernel._queued_adapter(tenant_id, plan["target_id"], plan["target"])
            if intent.result_limit_bytes < QUEUED_RESULT_ENVELOPE_LIMIT_BYTES:
                with sql_atomic(runtime.store):
                    lock_unknown_operation(runtime.store, intent.agent_id, intent.operation_id)
                    _budget_lock(runtime, intent.agent_id)
                    with runtime.tasks._transaction():
                        intent, link, _, _ = _current(kernel, runtime, authority, refs)
                        _close(runtime, intent, link, reason="immutable result allowance is insufficient for queued evidence",
                               terminal=TaskState.REJECTED)
                        _assert_queued_lifetime(kernel.directory, authority, runtime.task_intents)
                return _status(runtime, owner_id, task_id)
            attempt_id = secrets.token_hex(16)
            fence_scope = hashlib.sha256(_json({"tenant": tenant_id, "store": runtime.store.store_id,
                                               "agent": intent.agent_id, "operation": intent.operation_id}).encode()).hexdigest()
            try:
                epoch, fence_expiry = adapter.acquire(fence_scope, attempt_id)
            except SqliteFenceDenied:
                # A competing worker can own the destination fence before its
                # marker is visible. It still owns this admission's exposure.
                return _status(runtime, owner_id, task_id)
            action_bytes = canonical_demo_action(plan["wire"])
            with sql_atomic(runtime.store):
                lock_unknown_operation(runtime.store, intent.agent_id, intent.operation_id)
                _budget_lock(runtime, intent.agent_id)
                with runtime.tasks._transaction():
                    intent, link, _, locked_plan = _current(kernel, runtime, authority, refs)
                    if locked_plan != plan or runtime.task_executions.decision(owner_id, task_id) is not None:
                        raise AuthorityDenied("queued decision or current plan changed")
                    stamp = time.time()
                    deadline = min(authority.original_deadline, authority.principal.valid_until, fence_expiry,
                                   stamp + plan["target"]["call_timeout_seconds"])
                    if stamp >= deadline:
                        raise AuthorityDenied("queued dispatch deadline expired")
                    authorization = adapter.authorize({
                        "domain": "agentbridge.queued-authorization.v2", "tenant_id": tenant_id,
                        "store_id": runtime.store.store_id, **_base(intent, link),
                        "authority_sha256": hashlib.sha256(_json(intent.record["provenance"]["authority"]).encode()).hexdigest(),
                        "context_id": plan["context_id"], "intent_sha256": intent_sha256,
                        "fingerprint": link["action_sha256"], "original_action_sha256": link["original_action_sha256"],
                        "target_id": plan["target_id"], "target_configuration_sha256": plan["target_configuration_sha256"],
                        "destination_id": plan["target"]["destination_id"], "action_sha256": hashlib.sha256(action_bytes).hexdigest(),
                        "result_limit_bytes": intent.result_limit_bytes, "attempt_id": attempt_id,
                        "fence_scope": fence_scope, "fence_owner": attempt_id, "fence_epoch": epoch,
                        "issued_at": stamp, "expires_at": deadline, "authorizer_key_id": plan["target"]["authorizer_key_id"],
                    })
                    runtime.task_executions.insert_decision({**_base(intent, link), "kind": "attempt",
                        "domain": "agentbridge.task-execution-decision.v1", "attempt_id": attempt_id,
                        "authorization": authorization, "descriptor": plan["target"]})
                    _audit(runtime, intent, "task.attempt-committed", "one-shot attempt " + attempt_id)
                    _assert_queued_lifetime(kernel.directory, authority, runtime.task_intents)
            # This branch alone owns the just-committed attempt. Durable rows
            # are never converted back into a send capability after restart.
            attempted = True
            try:
                _assert_queued_lifetime(kernel.directory, authority, runtime.task_intents)
                if time.time() >= authorization["expires_at"]:
                    raise AuthorityDenied("attempt expired before destination entry")
                adapter.commit(authorization, action_bytes)
            except Exception:
                # A rejected call and a lost return can be indistinguishable to
                # the worker. Preserve UNKNOWN and the exact held token.
                pass
        # Release the separate authority guard before taking signing trust or
        # accounting locks. Observation uses a new read-only destination handle.
        if attempted:
            return recover(kernel, tenant_id, *refs)
        return _status(runtime, owner_id, task_id)
    except (AuthorityDenied, OperationConflict):
        if runtime.task_executions.decision(owner_id, task_id) is not None:
            return recover(kernel, tenant_id, *refs)
        raise
    finally:
        kernel._queued_dispatch_slots.release()


@dataclass(frozen=True, slots=True)
class _Readback:
    tenant_id: str
    refs: tuple
    decision_sha256: str
    evidence_json: str
    proof: bytes


def _readback_seal(kernel, tenant_id, refs, decision_sha256, evidence_json):
    return hmac.digest(kernel._queued_dispatch_key, _json({"domain": "agentbridge.private-readback.v1",
        "tenant": tenant_id, "refs": refs, "decision": decision_sha256, "evidence": evidence_json}).encode(), "sha256")


def _observe(kernel, runtime, refs, decision):
    intent, link, _, _, _ = _linked_history(kernel, runtime, *refs)
    descriptor, authorization = decision["descriptor"], decision["authorization"]
    adapter = kernel._queued_adapter(runtime.store.tenant_id, intent.record["submission"]["target_id"], descriptor)
    # Require current operator configuration to match the immutable destination;
    # historical authority itself is not renewed for this readback.
    from ..api.trusted_targets import resolve_queued_target
    submission = intent.record["submission"]
    current = resolve_queued_target(submission["target_id"], submission["dst"], intent.record["provenance"]["capability"],
        tenant_id=runtime.store.tenant_id, wire=submission["wire"], env=kernel._target_env[runtime.store.tenant_id], agent_id=intent.agent_id)
    if current != descriptor or authorization["admission_link_sha256"] != link["link_sha256"]:
        raise AuthorityDenied("current queued readback configuration changed")
    action_bytes = canonical_demo_action(submission["wire"])
    result, receipt, proof = adapter.observe(authorization, action_bytes)
    evidence_json = _json({"result": result, "destination_receipt": receipt, "readback_attestation": proof})
    return _Readback(runtime.store.tenant_id, refs, decision["record_sha256"], evidence_json,
        _readback_seal(kernel, runtime.store.tenant_id, refs, decision["record_sha256"], evidence_json))


def _finish_verified(kernel, completion, *, review=None, operator_session=None):
    if not isinstance(completion, _Readback) or not hmac.compare_digest(completion.proof, _readback_seal(
        kernel, completion.tenant_id, completion.refs, completion.decision_sha256, completion.evidence_json)):
        raise AuthorityDenied("actual bound read-only observation required")
    runtime = _runtime(kernel, completion.tenant_id)
    if (review is None) != (operator_session is None) or \
            review is not None and (not isinstance(review, dict) or set(review) != {"reviewer", "signature_hex"}):
        raise AuthorityDenied("concrete current operator session and signed review required")
    owner_id, task_id, _, _ = completion.refs
    evidence = json.loads(completion.evidence_json)
    from .queued_manual_settlement import settlement_atomic
    with settlement_atomic(kernel, runtime, operator_session):
        decision = runtime.task_executions.decision(owner_id, task_id)
        if decision is None or decision["kind"] != "attempt" or decision["record_sha256"] != completion.decision_sha256:
            raise AuthorityDenied("exact immutable attempt required for settlement")
        intent, link, _, _, operation = _linked_history(kernel, runtime, *completion.refs)
        existing = runtime.task_executions.result(owner_id, task_id)
        if existing is not None:
            return _status(runtime, owner_id, task_id)
        descriptor, authorization = decision["descriptor"], decision["authorization"]
        adapter = kernel._queued_adapter(completion.tenant_id, intent.record["submission"]["target_id"], descriptor)
        cur = runtime.store._db.cursor()
        try:
            trust = adapter.settlement_trust(runtime, cur)
        finally:
            cur.close()
        lock_unknown_operation(runtime.store, intent.agent_id, intent.operation_id)
        _budget_lock(runtime, intent.agent_id)
        with runtime.tasks._transaction():
            # Re-read all immutable linkage under operation/accounting/lifecycle.
            intent, link, _, current, operation = _linked_history(kernel, runtime, *completion.refs)
            verified = verify_queued_action_evidence(authorization=authorization,
                action_bytes=canonical_demo_action(intent.record["submission"]["wire"]), descriptor=descriptor, **evidence)
            if (verified.tenant_id, verified.store_id, verified.owner_id, verified.agent_id, verified.task_id,
                verified.operation_id, verified.intent_sha256, verified.admission_link_sha256, verified.fingerprint,
                verified.attempt_id) != (completion.tenant_id, runtime.store.store_id, owner_id, intent.agent_id, task_id,
                intent.operation_id, intent.intent_sha256, link["link_sha256"], operation["fingerprint"], decision["attempt_id"]):
                raise AuthorityDenied("verified result does not match the admitted task")
            if review is not None:
                from .operator_review import verify_operator_review
                verify_operator_review(agent_id=intent.agent_id, operation_id=intent.operation_id,
                    fingerprint=verified.fingerprint, outcome=verified.outcome, external_reference=verified.external_reference,
                    destination_receipt_sha256=verified.destination_receipt_sha256, readback_sha256=verified.readback_sha256,
                    trusted_operators_json=os.getenv("AGENTBRIDGE_RECONCILIATION_OPERATOR_KEYS_JSON"), **review)
            runtime.task_executions.insert_result({**_base(intent, link),
                "domain": "agentbridge.task-execution-result.v1", "outcome": verified.outcome,
                "decision_sha256": decision["record_sha256"], "authorization": authorization, **evidence,
                "trust_context": trust, "review": review,
                "operator_authority": operator_session.principal.binding() if operator_session is not None else None,
                "previous_terminal_state": current.state.value if current.terminal else None})
            settle_owned_reservation(runtime.store, runtime.budgets, runtime.operations, agent_id=intent.agent_id,
                operation_id=intent.operation_id, token=link["reservation_token"], outcome=verified.outcome,
                expected_cost=link["reserved_cost"])
            if not current.terminal:
                runtime.tasks.transition(owner_id, task_id, TaskState.COMPLETED, expected_sequence=current.sequence)
            _audit(runtime, intent, "task.verified-execution", "independent readback sha256:" + verified.readback_sha256 +
                   ("; preserved prior terminal status " + current.state.value if current.terminal else ""))
    return _status(runtime, owner_id, task_id)


def recover(kernel, tenant_id, owner_id, task_id, intent_sha256, admission_link_sha256):
    runtime = _runtime(kernel, tenant_id)
    refs = owner_id, task_id, intent_sha256, admission_link_sha256
    _linked_history(kernel, runtime, *refs)
    decision = runtime.task_executions.decision(owner_id, task_id)
    if decision is None or decision["kind"] == "closed" or runtime.task_executions.result(owner_id, task_id) is not None:
        return _status(runtime, owner_id, task_id)
    try:
        completion = _observe(kernel, runtime, refs, decision)
        return runtime.gateway._settle_queued_result(completion)
    except Exception:
        # Missing, stale, mismatched or locally unrecordable evidence is not a
        # failed external action. Only authoritative success currently settles.
        return _status(runtime, owner_id, task_id)


def cancel(kernel, tenant_id, owner_id, task_id, intent_sha256, admission_link_sha256, *, reason):
    if not isinstance(reason, str) or not reason.strip() or len(reason.encode()) > 200:
        raise ValueError("bounded cancellation reason required")
    runtime = _runtime(kernel, tenant_id)
    refs = owner_id, task_id, intent_sha256, admission_link_sha256
    with sql_atomic(runtime.store):
        intent, link, _, _, _ = _linked_history(kernel, runtime, *refs)
        decision = runtime.task_executions.decision(owner_id, task_id)
        if runtime.task_executions.result(owner_id, task_id) is not None or decision and decision["kind"] == "closed":
            return _status(runtime, owner_id, task_id)
        lock_unknown_operation(runtime.store, intent.agent_id, intent.operation_id)
        _budget_lock(runtime, intent.agent_id)
        with runtime.tasks._transaction():
            intent, link, _, _, _ = _linked_history(kernel, runtime, *refs)
            decision = runtime.task_executions.decision(owner_id, task_id)
            if decision is None:
                # Admission-only canonical producer 083 never invoked effects;
                # its absent marker is the explicit migration assumption here.
                _close(runtime, intent, link, reason=reason, terminal=TaskState.CANCELED)
            elif runtime.task_executions.cancellation(owner_id, task_id) is None:
                runtime.task_executions.insert_cancellation({**_base(intent, link), "kind": "cancel-request",
                    "domain": "agentbridge.task-cancellation-request.v1", "reason": reason})
                _audit(runtime, intent, "task.cancellation-requested", reason + "; attempt remains unresolved")
    return _status(runtime, owner_id, task_id)
