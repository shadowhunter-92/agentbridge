"""Governance plane: identity, audit, budgets, policy, approvals — the meta-bridge moat."""

from .store import GovernanceStore, InMemoryStore, SqliteStore, PostgresStore, make_store
from .identity import AgentIdentity, IdentityRegistry, did_from_public_hex
from .request_auth import RequestAuthenticator, sign_request, canonical_payload
from .audit import AuditLog, AuditEntry
from .budget import Budget, BudgetManager
from .approvals import ApprovalQueue, ApprovalRequest
from .policy import PolicyEngine, Decision
from .policy_rules import (
    PolicySet, PolicyContext, RuleResult, Rule,
    MaxCostPerCall, RequireApprovalAboveCost, DenyCapabilities, AllowOnlyCapabilities,
    BusinessHoursOnly, DenyProtocolRoute,
)
from .rbac import role_can, require, AccessDenied, ROLE_PERMISSIONS, PERMISSIONS
from .gateway import GovernanceGateway, GovernanceError

__all__ = [
    "GovernanceStore", "InMemoryStore", "SqliteStore", "PostgresStore", "make_store",
    "AgentIdentity", "IdentityRegistry", "did_from_public_hex",
    "RequestAuthenticator", "sign_request", "canonical_payload",
    "AuditLog", "AuditEntry",
    "Budget", "BudgetManager",
    "ApprovalQueue", "ApprovalRequest",
    "PolicyEngine", "Decision",
    "PolicySet", "PolicyContext", "RuleResult", "Rule",
    "MaxCostPerCall", "RequireApprovalAboveCost", "DenyCapabilities", "AllowOnlyCapabilities",
    "BusinessHoursOnly", "DenyProtocolRoute",
    "role_can", "require", "AccessDenied", "ROLE_PERMISSIONS", "PERMISSIONS",
    "GovernanceGateway", "GovernanceError",
]
