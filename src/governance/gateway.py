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

from typing import Any, Awaitable, Callable, Dict, Optional

from ..protocols import default_registry
from ..protocols.registry import ProtocolRegistry
from .identity import IdentityRegistry
from .budget import BudgetManager
from .approvals import ApprovalQueue
from .policy import PolicyEngine, Decision
from .audit import AuditLog, AuditEntry


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
        signed_data: Optional[bytes] = None,
        signature: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        canonical = self.registry.get(src_proto).to_canonical_call(src_wire)
        capability = canonical.capability

        decision = self.policy.authorize(
            agent_id=agent_id, capability=capability, cost=cost,
            signed_data=signed_data, signature=signature,
            src_protocol=src_proto, dst_protocol=dst_proto,
        )

        if not decision.allowed:
            approval_id = None
            if decision.needs_approval and self.approvals:
                approval_id = self.approvals.request(agent_id, capability, cost).id
            entry = self.audit.record(
                actor=agent_id, action="route_call",
                source_protocol=src_proto, target_protocol=dst_proto,
                capability=capability, decision="deny", reason=decision.reason, cost=0.0,
            )
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
            raise GovernanceError(Decision(False, why), entry)

        try:
            dst_wire = self.registry.translate_call(src_wire, src_proto, dst_proto)
            result = await invoke(dst_wire)
        except Exception as e:
            self.budgets.release(agent_id, token)
            self.audit.record(
                actor=agent_id, action="route_call",
                source_protocol=src_proto, target_protocol=dst_proto,
                capability=capability, decision="error", reason=str(e)[:200], cost=0.0,
            )
            raise

        self.budgets.commit(agent_id, token)
        if self.approvals and self.approvals.requires_approval(capability):
            self.approvals.consume(agent_id, capability)
        self.audit.record(
            actor=agent_id, action="route_call",
            source_protocol=src_proto, target_protocol=dst_proto,
            capability=capability, decision="allow", reason=decision.reason, cost=cost,
        )
        return result
