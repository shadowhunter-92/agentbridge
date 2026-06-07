"""Governance plane: identity, audit, budgets, policy, approvals — the meta-bridge moat."""

from .store import GovernanceStore, InMemoryStore, SqliteStore, PostgresStore, make_store
from .identity import AgentIdentity, IdentityRegistry, did_from_public_hex
from .request_auth import RequestAuthenticator, sign_request, canonical_payload
from .audit import AuditLog, AuditEntry
from .budget import Budget, BudgetManager
from .approvals import ApprovalQueue, ApprovalRequest
from .policy import PolicyEngine, Decision
from .gateway import GovernanceGateway, GovernanceError

__all__ = [
    "GovernanceStore", "InMemoryStore", "SqliteStore", "PostgresStore", "make_store",
    "AgentIdentity", "IdentityRegistry", "did_from_public_hex",
    "RequestAuthenticator", "sign_request", "canonical_payload",
    "AuditLog", "AuditEntry",
    "Budget", "BudgetManager",
    "ApprovalQueue", "ApprovalRequest",
    "PolicyEngine", "Decision",
    "GovernanceGateway", "GovernanceError",
]
