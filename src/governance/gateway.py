"""Governance admission and conservative outcome accounting.

Authorization, budget reservation, required approval consumption and operation
claim precede invocation. An uncertain post-dispatch outcome retains UNKNOWN
and reserved exposure; it is never automatically replayed. A pre-invocation
abort releases its owned reservation and marks its claim failed.

For one shared SQL store, definite-success settlement and pre-invocation abort
commit budget, operation state and chained audit together. A remote effect is
outside that local transaction. Legacy embeddings with separate/in-memory
participants retain their weaker accounting contract.
"""

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, Optional

from ..observability import record_call, span, update_audit_count, update_budget_gauge
from ..protocols import default_registry
from ..protocols.registry import ProtocolRegistry
from .approvals import ApprovalQueue
from .audit import AuditEntry, AuditLog
from .budget import BudgetManager, _checked_cost
from .identity import IdentityRegistry
from .operation_ledger import OperationConflict, OperationLedger
from .policy import Decision, PolicyEngine
from .request_auth import canonical_payload
from .store import PostgresStore, SqliteStore, sql_atomic


class GovernanceError(PermissionError):
    """Raised when a call is denied by policy."""

    def __init__(self, decision: Decision, audit_entry: AuditEntry,
                 approval_id: Optional[str] = None):
        super().__init__(decision.reason)
        self.decision = decision
        self.audit_entry = audit_entry
        self.approval_id = approval_id


class _AdmissionRejected(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.decision = Decision(False, reason)


class GovernanceGateway:
    def __init__(self, *, identities: Optional[IdentityRegistry] = None,
                 budgets: Optional[BudgetManager] = None,
                 approvals: Optional[ApprovalQueue] = None,
                 policy: Optional[PolicyEngine] = None,
                 audit: Optional[AuditLog] = None,
                 registry: Optional[ProtocolRegistry] = None,
                 require_verified: bool = True,
                 authority=None, tenant_id=None):
        if authority is None:
            from ..authority_mode import require_legacy_authority
            require_legacy_authority()
        if (authority is None) != (tenant_id is None):
            raise ValueError("authority and tenant_id must be configured together")
        self.authority, self.tenant_id = authority, tenant_id
        self.identities = identities or IdentityRegistry()
        self.budgets = budgets or BudgetManager()
        self.approvals = approvals
        self.policy = policy or PolicyEngine(self.identities, self.budgets,
                                             approvals=approvals,
                                             require_verified=require_verified,
                                             authority=authority, tenant_id=tenant_id)
        self.audit = audit or AuditLog()
        self.registry = registry or default_registry
        self._operations = None
        self._quotas = None
        self._operations_init_lock = threading.Lock()
        if authority is not None:
            if self.policy.authority is not authority or self.policy.tenant_id != tenant_id:
                raise ValueError("gateway policy must share authenticated tenant authority")
            if any(component is not None and component.store is not self.identities.store
                   for component in (self.budgets, self.approvals, self.audit)):
                raise ValueError("all tenant governance components must share the same bound store")

    def _shared_sql_store(self, ledger):
        store = self.identities.store
        participants = (self.budgets, self.approvals, self.audit, ledger)
        if isinstance(store, (SqliteStore, PostgresStore)) and all(
            component is None or component.store is store for component in participants
        ):
            return store
        if self.authority is not None:
            raise ValueError("tenant governance requires one shared durable SQL store")
        return None

    @contextmanager
    def _atomic_state(self, admission):
        store = self._shared_sql_store(admission.ledger)
        if store is not None:
            with sql_atomic(store):
                if admission.ledger is not None:
                    # Reconciliation locks operation -> budget -> audit. Match
                    # that order and never overwrite an already settled result.
                    query = "SELECT state FROM agent_operations WHERE agent_id=? AND operation_id=?"
                    if isinstance(store, PostgresStore):
                        query = query.replace("?", "%s") + " FOR UPDATE"
                    row = store._db.execute(query, (admission.agent_id, admission.operation_id)).fetchone()
                    if not row or row["state"] != "unknown":
                        raise OperationConflict("operation missing or already settled; inspect its durable outcome")
                yield
            return
        # Caller-owned legacy embeddings with separate/in-memory participants
        # keep their explicitly weaker local-state contract.
        yield

    def _operation_ledger(self):
        # The ledger caches no operation/authorization state. Cache only its
        # schema-bound handle so steady-state requests do not execute DDL twice.
        with self._operations_init_lock:
            if self._operations is None:
                ledger = OperationLedger(self.identities.store)
                quotas = None
                if self.authority is not None:
                    from .admission_quotas import AdmissionQuotas
                    quotas = AdmissionQuotas(self.identities.store)
                self._operations, self._quotas = ledger, quotas
            elif self._operations.store is not self.identities.store:
                raise ValueError("gateway governance store cannot change after initialization")
            return self._operations

    async def route_call(
        self,
        *,
        agent_id: str,
        src_proto: str,
        dst_proto: str,
        src_wire: Dict[str, Any],
        invoke: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
        cost: float = 1.0,
        target_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        signed_data: Optional[bytes] = None,
        signature: Optional[bytes] = None,
        signed_body: Optional[bytes] = None,
        signed_nonce: Optional[str] = None,
        principal=None,
    ) -> Dict[str, Any]:
        # SQL/JWT/policy work runs off the network event loop. Shield admission
        # so cancellation cannot lose the reservation token while a SQL worker
        # is still completing its transaction. No invocation starts on this path.
        prepare = asyncio.create_task(asyncio.to_thread(
            self._admit, agent_id=agent_id, src_proto=src_proto, dst_proto=dst_proto,
            src_wire=src_wire, cost=cost, target_id=target_id, operation_id=operation_id,
            signed_data=signed_data, signature=signature, signed_body=signed_body,
            signed_nonce=signed_nonce, principal=principal))
        try:
            admission = await asyncio.shield(prepare)
        except asyncio.CancelledError:
            try:
                admission = await self._complete(prepare)
            except BaseException:
                # _admit performs its own cleanup before returning an error.
                pass
            else:
                cleanup = asyncio.create_task(asyncio.to_thread(self._abort_admission, admission))
                try:
                    await self._complete(cleanup)
                except BaseException:
                    logging.getLogger(__name__).exception(
                        "canceled admission cleanup failed; operation requires reconciliation")
            raise
        try:
            result = await invoke(admission.wire)
        except BaseException as exc:
            cleanup = asyncio.create_task(asyncio.to_thread(self._invocation_failed, admission, exc))
            await self._complete(cleanup)
            raise
        settle = asyncio.create_task(asyncio.to_thread(self._settle, admission))
        try:
            await asyncio.shield(settle)
        except asyncio.CancelledError:
            # A definite successful result must finish settling even when its
            # HTTP caller disconnects; cancellation never causes an auto replay.
            try:
                await self._complete(settle)
            except BaseException as exc:
                failure = asyncio.create_task(asyncio.to_thread(self._invocation_failed, admission, exc))
                await self._complete(failure)
            raise
        except BaseException as exc:
            failure = asyncio.create_task(asyncio.to_thread(self._invocation_failed, admission, exc))
            await self._complete(failure)
            raise
        return result

    @staticmethod
    async def _complete(task):
        """Finish a bounded SQL cleanup despite repeated caller cancellation."""
        while True:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.cancelled():
                    raise

    def _audit_admission(self, admission, decision, reason, cost=0.0, *, observe=True):
        self.audit.record(actor=admission.actor, action="route_call",
                          source_protocol=admission.src, target_protocol=admission.dst,
                          capability=admission.capability, decision=decision,
                          reason=reason, cost=cost)
        if observe:
            self._observe_admission(admission, decision)

    def _observe_admission(self, admission, decision):
        try:
            update_audit_count(self.audit.count())
            record_call(admission.src, admission.dst, admission.capability,
                        decision, time.monotonic()-admission.started)
        except Exception:
            logging.getLogger(__name__).exception("governance telemetry unavailable after durable audit")

    def _abort_admission(self, admission):
        with self._atomic_state(admission):
            self.budgets.release(admission.agent_id, admission.token)
            if admission.ledger is not None:
                admission.ledger.finish(admission.agent_id, admission.operation_id, "failed")
            self._audit_admission(admission, "error", "request canceled before invocation", observe=False)
        self._observe_admission(admission, "error")

    def _invocation_failed(self, admission, exc):
        uncertain = admission.ledger is not None
        if not uncertain:
            self.budgets.release(admission.agent_id, admission.token)
        self._audit_admission(admission, "unknown" if uncertain else "error",
                              str(exc)[:200] or type(exc).__name__)

    def _settle(self, admission):
        with self._atomic_state(admission):
            if not self.budgets.commit(admission.agent_id, admission.token):
                raise RuntimeError("budget reservation missing after invocation; reconcile outcome")
            if admission.ledger is not None:
                admission.ledger.finish(admission.agent_id, admission.operation_id, "succeeded")
            self._audit_admission(admission, "allow", admission.decision.reason, admission.cost, observe=False)
        self._observe_admission(admission, "allow")
        try:
            budget = self.budgets.get(admission.agent_id)
            update_budget_gauge(admission.agent_id, budget.spent, budget.remaining())
        except Exception:
            pass  # telemetry cannot invalidate a committed operation

    def _admit(self, **kwargs):
        if self.authority is None:
            return self._admit_guarded(**kwargs)
        with self.authority.guard(kwargs.get("principal")):
            return self._admit_guarded(**kwargs)

    def _admit_guarded(
        self,
        *,
        agent_id: str,
        src_proto: str,
        dst_proto: str,
        src_wire: Dict[str, Any],
        cost: float = 1.0,
        target_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        signed_data: Optional[bytes] = None,
        signature: Optional[bytes] = None,
        signed_body: Optional[bytes] = None,
        signed_nonce: Optional[str] = None,
        principal=None,
    ) -> Dict[str, Any]:
        if self.authority is None:
            from ..authority_mode import require_legacy_authority

            require_legacy_authority()
        # Canonicalize the same validated value used by budget arithmetic.
        # Equivalent integer/float operator costs must share an operation scope.
        cost = _checked_cost(cost)
        audit_actor = agent_id
        if self.authority is not None:
            from .authority import AuthorityDenied

            if principal is None or principal.tenant_id != self.tenant_id or principal.agent_id != agent_id:
                raise AuthorityDenied("principal does not own this tenant gateway")
            self.authority.assert_request(principal, body=signed_body, nonce=signed_nonce)
            audit_actor = "principal:v1:" + json.dumps(principal.binding(), sort_keys=True, separators=(",", ":"))

        def audit_record(**fields):
            fields["actor"] = audit_actor
            return self.audit.record(**fields)

        # Library callers receive the same fail-closed protocol admission as HTTP.
        self.registry.get(src_proto)
        self.registry.get(dst_proto)
        t0 = time.monotonic()
        with span(
            "gateway.admission",
            {
                "agent_id": agent_id,
                "src": src_proto,
                "dst": dst_proto,
                "cost": cost,
            },
        ):
            canonical = self.registry.get(src_proto).to_canonical_call(src_wire)
            capability = canonical.capability
            material = {
                "agent_id": agent_id,
                "src": src_proto,
                "dst": dst_proto,
                "wire": src_wire,
                "cost": cost,
                "target_id": target_id,
                "operation_id": operation_id,
            }
            if self.authority is not None:
                self.authority.authorize(principal, capability, target_id)
                try:
                    body = json.loads(signed_body)
                    if not isinstance(body, dict) or not (
                        body.get("src") == src_proto
                        and body.get("dst") == dst_proto
                        and body.get("wire") == src_wire
                        and body.get("target_id") == target_id
                        and body.get("operation_id") == operation_id
                    ):
                        raise ValueError("signed operation differs from invocation")
                except (ValueError, TypeError, UnicodeError) as exc:
                    raise AuthorityDenied("signed principal proof does not bind this operation") from exc
                material["authority"] = principal.binding()
            request_material = json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            request_scope = hashlib.sha256(request_material).hexdigest()

            if self.authority is not None or os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
                if not isinstance(operation_id, str) or not 16 <= len(operation_id) <= 128:
                    entry = audit_record(
                        actor=agent_id,
                        action="route_call",
                        source_protocol=src_proto,
                        target_protocol=dst_proto,
                        capability=capability,
                        decision="deny",
                        reason="durable operation_id required in production",
                        cost=0.0,
                    )
                    raise GovernanceError(Decision(False, "durable operation_id required in production"), entry)
                # An identity registered in SQL is not proof that an arbitrary
                # in-process caller possesses its signing key.
                proof_ok = self.authority is not None
                try:
                    # Proof has to authenticate this operation, not unrelated
                    # caller-selected bytes. Cost is an operator reservation, so
                    # it is not trusted from the signed caller payload.
                    body = json.loads(signed_body) if signed_body is not None else None
                    if isinstance(body, dict) and isinstance(signed_nonce, str):
                        matches = (
                            body.get("src") == src_proto
                            and body.get("dst") == dst_proto
                            and body.get("wire") == src_wire
                            and body.get("target_id") == target_id
                            and body.get("operation_id") == operation_id
                        )
                        if (
                            self.authority is None
                            and matches
                            and signed_data == canonical_payload(agent_id, signed_nonce, signed_body)
                        ):
                            proof_ok = signature is not None and self.identities.verify_signature(
                                agent_id, signed_data, signature
                            )
                except (TypeError, ValueError, UnicodeError):
                    proof_ok = False
                if not proof_ok:
                    entry = audit_record(
                        actor=agent_id,
                        action="route_call",
                        source_protocol=src_proto,
                        target_protocol=dst_proto,
                        capability=capability,
                        decision="deny",
                        reason="request-bound signed agent proof required",
                        cost=0.0,
                    )
                    raise GovernanceError(Decision(False, "request-bound signed agent proof required"), entry)

            # Detect a known idempotency collision before the budget pre-check.
            # This is a read-only hint, NOT the concurrency lock: atomic
            # ledger.claim below remains the authority for new operations.
            if operation_id is not None:
                existing = self._operation_ledger().get(agent_id, operation_id)
                if existing is not None:
                    if existing["fingerprint"] != request_scope:
                        raise OperationConflict("idempotency key reused for different request")
                    raise OperationConflict("existing operation is " + existing["state"] + "; no automatic replay")

            decision = self.policy.authorize(
                agent_id=agent_id,
                capability=capability,
                cost=cost,
                signed_data=signed_data,
                signature=signature,
                src_protocol=src_proto,
                dst_protocol=dst_proto,
                request_scope=request_scope,
                **({"principal": principal, "target_id": target_id} if self.authority is not None else {}),
            )

            if not decision.allowed:
                approval_id = None
                if decision.needs_approval and self.approvals:
                    approval_id = self.approvals.request(agent_id, capability, cost, request_scope).id
                entry = audit_record(
                    actor=agent_id,
                    action="route_call",
                    source_protocol=src_proto,
                    target_protocol=dst_proto,
                    capability=capability,
                    decision="deny",
                    reason=decision.reason,
                    cost=0.0,
                )
                update_audit_count(self.audit.count())
                record_call(src_proto, dst_proto, capability, "deny", time.monotonic() - t0)
                raise GovernanceError(decision, entry, approval_id=approval_id)

            # Translation is pure preparation: reject unsupported semantics before
            # reserving budget, consuming a grant or creating a durable claim.
            dst_wire = self.registry.translate_call(src_wire, src_proto, dst_proto)
            ledger = self._operation_ledger() if operation_id is not None else None
            store = self._shared_sql_store(ledger)
            token, claimed = None, False
            binding = {"authority_binding": principal.binding()} if self.authority is not None else {}
            try:
                with sql_atomic(store) if store is not None else nullcontext():
                    if store is not None and ledger is not None:
                        # Lock/claim operation before budget, matching outcome
                        # settlement and reconciliation. Nothing is visible until
                        # reservation, approval and its token link commit together.
                        quota_hook = None
                        if self._quotas is not None:
                            def quota_hook():
                                from .admission_quotas import QuotaDenied
                                try:
                                    self._quotas.admit(principal, agent_id, operation_id, request_scope, cost)
                                except QuotaDenied as exc:
                                    raise _AdmissionRejected(str(exc)) from exc
                        ledger.claim(agent_id, operation_id, request_scope, before_insert=quota_hook, **binding)
                        claimed = True
                    token, why = self.budgets.reserve(agent_id, cost)
                    if token is None:
                        raise _AdmissionRejected(why)
                    if self.authority is not None:
                        self.authority.authorize(principal, capability, target_id)
                    if ledger is not None and claimed:
                        ledger.attach_reservation(agent_id, operation_id, token)
                    if decision.approval_required and (
                        not self.approvals or not self.approvals.consume(agent_id, capability, request_scope)
                    ):
                        raise _AdmissionRejected("approval grant already consumed")
                    if ledger is not None and not claimed:
                        # Preserve the explicitly weaker legacy embedding path
                        # when its participants do not share one SQL connection.
                        ledger.claim(agent_id, operation_id, request_scope, reservation_token=token, **binding)
                        claimed = True
                    if self.authority is not None:
                        self.authority.authorize(principal, capability, target_id)
            except BaseException as exc:
                if store is None:
                    if token is not None:
                        self.budgets.release(agent_id, token)
                    if ledger is not None and claimed:
                        ledger.finish(agent_id, operation_id, "failed")
                if isinstance(exc, _AdmissionRejected):
                    # Denials are durable after rollback; do not commit partial
                    # reservation/approval state just to retain an audit entry.
                    entry = audit_record(
                        actor=agent_id,
                        action="route_call",
                        source_protocol=src_proto,
                        target_protocol=dst_proto,
                        capability=capability,
                        decision="deny",
                        reason=exc.decision.reason,
                        cost=0.0,
                    )
                    update_audit_count(self.audit.count())
                    record_call(src_proto, dst_proto, capability, "deny", time.monotonic() - t0)
                    raise GovernanceError(exc.decision, entry) from exc
                raise
            return SimpleNamespace(
                agent_id=agent_id,
                src=src_proto,
                dst=dst_proto,
                capability=capability,
                cost=cost,
                token=token,
                ledger=ledger,
                operation_id=operation_id,
                wire=dst_wire,
                decision=decision,
                actor=audit_actor,
                started=t0,
            )
