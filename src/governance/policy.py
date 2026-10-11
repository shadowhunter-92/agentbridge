"""
Policy engine: the single authorize() gate combining identity + capability + approval + budget.

A call is allowed only if the caller is a known, non-revoked identity, is permitted to use
the requested capability, has any required human approval, and is within budget.
"""

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional, Set

from .identity import IdentityRegistry
from .budget import BudgetManager
from .approvals import ApprovalQueue
from .policy_rules import PolicySet, PolicyContext


@dataclass
class Decision:
    allowed: bool
    reason: str
    needs_approval: bool = False
    approval_required: bool = False


class PolicyEngine:
    def __init__(self, identities: IdentityRegistry, budgets: BudgetManager,
                 approvals: Optional[ApprovalQueue] = None,
                 require_verified: bool = True,
                 policy_set: Optional[PolicySet] = None):
        self.identities = identities
        self.budgets = budgets
        self.approvals = approvals
        self.require_verified = require_verified
        self.policy_set = policy_set            # declarative rules (policy engine v2), optional
        self._capability_allow: Dict[str, Set[str]] = {}

    def allow_capability(self, agent_id: str, capability: str) -> None:
        self._capability_allow.setdefault(agent_id, set()).add(capability)

    def authorize(self, *, agent_id: str, capability: str, cost: float = 1.0,
                  signed_data: Optional[bytes] = None,
                  signature: Optional[bytes] = None,
                  src_protocol: Optional[str] = None,
                  dst_protocol: Optional[str] = None,
                  request_scope: Optional[str] = None) -> Decision:
        # 1) identity (registered AND not revoked)
        if self.require_verified and not self.identities.is_registered(agent_id):
            return Decision(False, f"unknown or revoked identity '{agent_id}'")
        if signature is not None and signed_data is not None:
            if not self.identities.verify_signature(agent_id, signed_data, signature):
                return Decision(False, "signature verification failed")

        # 2) Strict, operator-owned capability allowlist in production. Registered
        # identities confer authentication only, never blanket authorization.
        if os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
            try:
                allowlists = json.loads(os.getenv("AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON", "{}"))
                if not isinstance(allowlists, dict):
                    raise ValueError("capability allowlist must be an object")
                allowed = allowlists.get(agent_id)
                if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
                    return Decision(False, "production capability allowlist missing or invalid")
            except (ValueError, TypeError):
                return Decision(False, "production capability allowlist invalid")
            if capability not in allowed:
                return Decision(False, f"capability '{capability}' not permitted for '{agent_id}'")
        else:
            allowed = self._capability_allow.get(agent_id)
            if allowed is not None and capability not in allowed:
                return Decision(False, f"capability '{capability}' not permitted for '{agent_id}'")

        approval_required = False
        # 3) human approval for sensitive capabilities
        if self.approvals and self.approvals.requires_approval(capability):
            approval_required = True
            if not self.approvals.is_granted(agent_id, capability, request_scope):
                return Decision(False, f"approval required for '{capability}'", needs_approval=True)

        # 4) declarative policy rules (policy engine v2), if configured
        if self.policy_set is not None:
            ctx = PolicyContext(agent_id=agent_id, capability=capability, cost=cost,
                                src_protocol=src_protocol, dst_protocol=dst_protocol)
            r = self.policy_set.evaluate(ctx)
            if not r.allowed:
                return Decision(False, r.reason)
            if r.needs_approval:
                approval_required = True
                granted = self.approvals and self.approvals.is_granted(agent_id, capability, request_scope)
                if not granted:
                    return Decision(False, r.reason, needs_approval=True)

        # 5) budget (capacity pre-check; the atomic reservation happens in the gateway)
        ok, why = self.budgets.can_afford(agent_id, cost)
        if not ok:
            return Decision(False, why)

        return Decision(True, "authorized", approval_required=approval_required)
