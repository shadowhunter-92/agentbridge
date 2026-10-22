"""
Policy engine: the single authorize() gate combining identity + capability + approval + budget.

A call is allowed only if the caller is a known, non-revoked identity, is permitted to use
the requested capability, has any required human approval, and is within budget.
"""

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional, Set

from .approvals import ApprovalQueue
from .budget import BudgetManager
from .identity import IdentityRegistry
from .policy_rules import PolicyContext, PolicySet


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
                 policy_set: Optional[PolicySet] = None,
                 authority=None, tenant_id=None):
        if (authority is None) != (tenant_id is None):
            raise ValueError("authority and tenant_id must be configured together")
        if authority is not None:
            from .authority import AuthorityDirectory
            from .tenant_store import TenantPostgresStore, TenantSqliteStore
            if not isinstance(authority, AuthorityDirectory) or not isinstance(
                    identities.store, (TenantSqliteStore, TenantPostgresStore)) or identities.store.tenant_id != tenant_id:
                raise ValueError("enrolled authority and exactly bound tenant store required")
        self.authority, self.tenant_id = authority, tenant_id
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
                  request_scope: Optional[str] = None,
                  principal=None, target_id=None) -> Decision:
        denial = self._current_identity_policy(
            agent_id=agent_id, capability=capability, signed_data=signed_data,
            signature=signature, principal=principal, target_id=target_id,
        )
        if denial is not None:
            return denial

        approval_required = False
        # Keep public admission's approval/rule/budget order and reasons exact.
        if self.approvals and self.approvals.requires_approval(capability):
            approval_required = True
            if not self.approvals.is_granted(agent_id, capability, request_scope):
                return Decision(False, f"approval required for '{capability}'", needs_approval=True)

        rule = self._current_rule(agent_id, capability, cost, src_protocol, dst_protocol)
        if rule is not None:
            if not rule.allowed:
                return Decision(False, rule.reason)
            if rule.needs_approval:
                approval_required = True
                granted = self.approvals and self.approvals.is_granted(agent_id, capability, request_scope)
                if not granted:
                    return Decision(False, rule.reason, needs_approval=True)

        ok, why = self.budgets.can_afford(agent_id, cost)
        if not ok:
            return Decision(False, why)
        return Decision(True, "authorized", approval_required=approval_required)

    def current_dispatch_policy(self, *, agent_id, capability, cost, src_protocol, dst_protocol,
                                principal, target_id):
        """Current identity/scope/rules only; this is not another admission.

        The concrete dispatcher must validate its sealed admission, already
        consumed grant and held reservation. This observation issues no grant,
        reserves nothing, and must never be accepted as execution capability.
        """
        denial = self._current_identity_policy(
            agent_id=agent_id, capability=capability, principal=principal, target_id=target_id,
        )
        if denial is not None:
            return denial
        required = bool(self.approvals and self.approvals.requires_approval(capability))
        rule = self._current_rule(agent_id, capability, cost, src_protocol, dst_protocol)
        if rule is not None:
            if not rule.allowed:
                return Decision(False, rule.reason)
            required |= bool(rule.needs_approval)
        return Decision(True, "current dispatch policy allowed", approval_required=required)

    def _current_rule(self, agent_id, capability, cost, src_protocol, dst_protocol):
        if self.policy_set is None:
            return None
        return self.policy_set.evaluate(PolicyContext(
            agent_id=agent_id, capability=capability, cost=cost,
            src_protocol=src_protocol, dst_protocol=dst_protocol,
        ))

    def _current_identity_policy(self, *, agent_id, capability, signed_data=None, signature=None,
                                 principal=None, target_id=None):
        if self.authority is None:
            from ..authority_mode import require_legacy_authority
            require_legacy_authority()
        if self.authority is not None:
            from .authority import AuthorityDenied
            try:
                if principal is None or principal.tenant_id != self.tenant_id or principal.agent_id != agent_id:
                    raise AuthorityDenied("principal does not own this tenant/agent context")
                self.authority.authorize(principal, capability, target_id)
                with self.authority._transaction() as cur:
                    enrolled = self.authority._agent(cur, self.tenant_id, agent_id)
                identity = self.identities.get(agent_id)
                if identity is None or identity.public_key_hex != enrolled["public_key_hex"]:
                    raise AuthorityDenied("tenant identity and enrollment disagree")
            except AuthorityDenied as exc:
                return Decision(False, str(exc))
        # 1) identity (registered AND not revoked)
        if self.require_verified and not self.identities.is_registered(agent_id):
            return Decision(False, f"unknown or revoked identity '{agent_id}'")
        if signature is not None and signed_data is not None:
            if not self.identities.verify_signature(agent_id, signed_data, signature):
                return Decision(False, "signature verification failed")

        # 2) Strict, operator-owned capability allowlist in production. Registered
        # identities confer authentication only, never blanket authorization.
        if self.authority is not None:
            # The enrolled principal was already checked above. Never select a
            # tenant's capability policy from a shared caller-chosen agent ID.
            pass
        elif os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production"):
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

        return None
