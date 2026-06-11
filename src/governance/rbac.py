"""
Role-based access control (RBAC) for OPERATORS of the control plane.

Distinct from agent identity (which authenticates the *agents* making calls). This governs
which *humans/services operating the control plane* may do what: an admin can do everything,
an operator can manage agents/budgets/approvals, a viewer can only read.

Roles map to permission strings checked at each operator endpoint. Wire it to your IdP via
the OIDC verifier (a role claim in the token -> a role here); without OIDC, the admin key
maps to the `admin` role.
"""

from __future__ import annotations

from typing import Dict, Set

# Canonical permission strings (verb-scoped).
PERMISSIONS: Set[str] = {
    "identities:read", "identities:write",
    "budgets:read", "budgets:write",
    "approvals:read", "approvals:write",
    "audit:read", "audit:export",
    "policy:read", "policy:write",
}

ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "admin": {"*"},
    "operator": {
        "identities:read", "identities:write",
        "budgets:read", "budgets:write",
        "approvals:read", "approvals:write",
        "audit:read", "audit:export",
        "policy:read",
    },
    "viewer": {
        "identities:read", "budgets:read", "approvals:read", "audit:read",
        "policy:read",
    },
}


def role_can(role: str, permission: str) -> bool:
    """True if `role` grants `permission` (admin's '*' grants everything)."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return "*" in perms or permission in perms


class AccessDenied(PermissionError):
    """Raised when a role lacks a required permission."""


def require(role: str, permission: str) -> None:
    if not role_can(role, permission):
        raise AccessDenied(f"role '{role}' lacks permission '{permission}'")
