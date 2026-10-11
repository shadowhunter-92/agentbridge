"""
GovernanceGateway — governance enforced IN the call path of the meta-bridge mesh.

For every cross-protocol call:
    authorize (identity + capability + approval + budget)
      -> denied: audit(deny); if approval needed, open a pending request; raise.
      -> allowed: RESERVE budget -> translate (any->any) -> invoke target
                  -> success: COMMIT budget, consume approval grant, audit(allow)
                  -> failure: RELEASE budget, audit(error), re-raise.

Atomic reserve/commit closes the TOCTOU race. Protocol-agnostic — the moat in action.
"""

import time
import json
import hashlib
import os
from typing import Any, Awaitable, Callable, Dict, Optional

from ..protocols import default_registry
from ..protocols.registry import ProtocolRegistry
from .identity import IdentityRegistry
from .budget import BudgetManager
from .approvals import ApprovalQueue
from .policy import PolicyEngine, Decision
from .audit import AuditLog, AuditEntry
from .operation_ledger import OperationLedger, OperationConflict
from .request_auth import canonical_payload
from ..observability import span, record_call, update_audit_count, update_budget_gauge


class GovernanceError(PermissionError):
    """Raised when a call is denied by policy."""
    def __init__(self, decision: Decision, audit_entry: AuditEntry,
                 approval_id: Optional[str] = None):
        super().__init__(decision.reason)
        self.decision = decision
        self.audit_entry = audit_entry
        self.approval_id = approval_id


class GovernanceGateway:
    def __init__(self, *, identities: Optional[IdentityRegistry] = None,
                 budgets: Optional[BudgetManager] = None,
                 approvals: Optional[ApprovalQueue] = None,
                 policy: Optional[PolicyEngine] = None,
                 audit: Optional[AuditLog] = None,
                 registry: Optional[ProtocolRegistry] = None,
                 require_verified: bool = True):
        self.identities = identities or IdentityRegistry()
        self.budgets = budgets or BudgetManager()
        self.approvals = approvals
        self.policy = policy or PolicyEngine(self.identities, self.budgets,
                                             approvals=approvals,
                                             require_verified=require_verified)
        self.audit = audit or AuditLog()
        self.registry = registry or default_registry

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
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        with span("gateway.route_call", {
            "agent_id": agent_id, "src": src_proto, "dst": dst_proto, "cost": cost,
        }):
            canonical = self.registry.get(src_proto).to_canonical_call(src_wire)
            capability = canonical.capability
            request_material = json.dumps({
                "agent_id": agent_id, "src": src_proto, "dst": dst_proto,
                "wire": src_wire, "cost": cost, "target_id": target_id,
            }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            request_scope = hashlib.sha256(request_material).hexdigest()

            if os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
                # An identity registered in SQL is not proof that an arbitrary
                # in-process caller possesses its signing key.
                proof_ok = False
                try:
                    # Proof has to authenticate this operation, not unrelated
                    # caller-selected bytes. Cost is an operator reservation, so
                    # it is not trusted from the signed caller payload.
                    body = json.loads(signed_body) if signed_body is not None else None
                    if isinstance(body, dict) and isinstance(signed_nonce, str):
                        matches = (
                            body.get("src") == src_proto and body.get("dst") == dst_proto
                            and body.get("wire") == src_wire
                            and body.get("target_id") == target_id
                            and body.get("operation_id") == operation_id
                        )
                        if matches and signed_data == canonical_payload(
                                agent_id, signed_nonce, signed_body):
                            proof_ok = (signature is not None and
                                        self.identities.verify_signature(
                                            agent_id, signed_data, signature))
                except (TypeError, ValueError, UnicodeError):
                    proof_ok = False
                if not proof_ok:
                    entry = self.audit.record(actor=agent_id, action="route_call",
                        source_protocol=src_proto, target_protocol=dst_proto,
                        capability=capability, decision="deny",
                        reason="request-bound signed agent proof required", cost=0.0)
                    raise GovernanceError(Decision(False, "request-bound signed agent proof required"), entry)

            decision = self.policy.authorize(
                agent_id=agent_id, capability=capability, cost=cost,
                signed_data=signed_data, signature=signature,
                src_protocol=src_proto, dst_protocol=dst_proto,
                request_scope=request_scope,
            )

            if not decision.allowed:
                approval_id = None
                if decision.needs_approval and self.approvals:
                    approval_id = self.approvals.request(agent_id, capability, cost, request_scope).id
                entry = self.audit.record(
                    actor=agent_id, action="route_call",
                    source_protocol=src_proto, target_protocol=dst_proto,
                    capability=capability, decision="deny", reason=decision.reason, cost=0.0,
                )
                update_audit_count(self.audit.count())
                record_call(src_proto, dst_proto, capability, "deny", time.monotonic() - t0)
                raise GovernanceError(decision, entry, approval_id=approval_id)

            # Atomically reserve budget before doing any work. The reservation is recorded in
            # the durable store inside an atomic section, so concurrent workers can't both pass
            # the cap (the fix for the multi-worker double-spend).
            token, why = self.budgets.reserve(agent_id, cost)
            if token is None:
                entry = self.audit.record(
                    actor=agent_id, action="route_call",
                    source_protocol=src_proto, target_protocol=dst_proto,
                    capability=capability, decision="deny", reason=why, cost=0.0,
                )
                update_audit_count(self.audit.count())
                record_call(src_proto, dst_proto, capability, "deny", time.monotonic() - t0)
                raise GovernanceError(Decision(False, why), entry)

            # Claim a one-shot grant BEFORE the target is invoked. The store operation
            # is atomic: parallel calls cannot execute on the same approval.
            if decision.approval_required:
                if not self.approvals or not self.approvals.consume(agent_id, capability, request_scope):
                    self.budgets.release(agent_id, token)
                    entry = self.audit.record(actor=agent_id, action="route_call",
                        source_protocol=src_proto, target_protocol=dst_proto,
                        capability=capability, decision="deny", reason="approval grant already consumed", cost=0.0)
                    raise GovernanceError(Decision(False, "approval grant already consumed"), entry)

            ledger = None
            if operation_id is not None:
                # Claim after authorization, budget reservation and approval, but
                # BEFORE translation or external execution. A failed/unknown
                # downstream outcome is never automatically replayed.
                ledger = OperationLedger(self.identities.store)
                try:
                    ledger.claim(agent_id, operation_id, request_scope)
                except BaseException:
                    self.budgets.release(agent_id, token)
                    raise

            # A remote timeout may occur AFTER the target committed its side effect.
            # When using durable operation IDs, retain the budget reservation until
            # an operator reconciles this unknown outcome. Otherwise a timeout could
            # free capacity for another potentially consequential action.
            invocation_started = False
            try:
                dst_wire = self.registry.translate_call(src_wire, src_proto, dst_proto)
                invocation_started = True
                result = await invoke(dst_wire)
            except BaseException as e:
                uncertain = invocation_started and ledger is not None
                if not uncertain:
                    self.budgets.release(agent_id, token)
                self.audit.record(
                    actor=agent_id, action="route_call",
                    source_protocol=src_proto, target_protocol=dst_proto,
                    capability=capability,
                    decision="unknown" if uncertain else "error",
                    reason=(str(e)[:200] or type(e).__name__), cost=0.0,
                )
                update_audit_count(self.audit.count())
                record_call(src_proto, dst_proto, capability,
                            "unknown" if uncertain else "error", time.monotonic() - t0)
                raise

            self.budgets.commit(agent_id, token)
            if ledger is not None:
                ledger.finish(agent_id, operation_id, "succeeded")
            self.audit.record(
                actor=agent_id, action="route_call",
                source_protocol=src_proto, target_protocol=dst_proto,
                capability=capability, decision="allow", reason=decision.reason, cost=cost,
            )

            # Update gauges so Prometheus sees live state.
            update_audit_count(self.audit.count())
            try:
                b = self.budgets.get(agent_id)
                update_budget_gauge(agent_id, b.spent, b.remaining())
            except Exception:
                pass  # budget gauge is best-effort; never break a real call for it

            record_call(src_proto, dst_proto, capability, "allow", time.monotonic() - t0)
            return result
