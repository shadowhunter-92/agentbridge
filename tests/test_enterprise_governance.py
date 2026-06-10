"""
Tests for the enterprise governance layer:
  - declarative policy rules (policy engine v2) + PolicyEngine integration
  - RBAC (operator roles/permissions)
  - signed, third-party-verifiable audit checkpoints
  - OIDC/JWT operator authentication (real RS256 round-trip)
"""

import time
from datetime import datetime, timezone

import pytest

from src.governance import (
    PolicySet, PolicyContext, MaxCostPerCall, RequireApprovalAboveCost,
    DenyCapabilities, AllowOnlyCapabilities, BusinessHoursOnly, DenyProtocolRoute,
    PolicyEngine, IdentityRegistry, BudgetManager, AgentIdentity, Budget, AuditLog,
    role_can, require, AccessDenied,
)


# ---------------- policy rules ----------------

def test_max_cost_and_allow_deny_rules():
    ps = PolicySet([MaxCostPerCall(5), DenyCapabilities(["delete"])])
    assert ps.evaluate(PolicyContext("a", "add", cost=3)).allowed
    assert not ps.evaluate(PolicyContext("a", "add", cost=9)).allowed       # over cap
    assert not ps.evaluate(PolicyContext("a", "delete", cost=1)).allowed    # denied cap


def test_allow_only_and_route_rules():
    ps = PolicySet([AllowOnlyCapabilities(["add", "echo"]), DenyProtocolRoute("a2a", "mcp")])
    assert ps.evaluate(PolicyContext("a", "add")).allowed
    assert not ps.evaluate(PolicyContext("a", "search")).allowed
    assert not ps.evaluate(PolicyContext("a", "add", src_protocol="a2a", dst_protocol="mcp")).allowed
    assert ps.evaluate(PolicyContext("a", "add", src_protocol="openai", dst_protocol="mcp")).allowed


def test_require_approval_above_cost():
    ps = PolicySet([RequireApprovalAboveCost(5)])
    r = ps.evaluate(PolicyContext("a", "spend", cost=10))
    assert r.allowed and r.needs_approval
    assert not ps.evaluate(PolicyContext("a", "spend", cost=2)).needs_approval


def test_business_hours_rule():
    ps = PolicySet([BusinessHoursOnly(9, 17, days=[0, 1, 2, 3, 4])])  # Mon-Fri 9-17 UTC
    sat = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)            # Saturday noon
    wed_3pm = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)       # Wednesday 15:00
    wed_8pm = datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc)       # Wednesday 20:00
    assert not ps.evaluate(PolicyContext("a", "x", now=sat)).allowed
    assert ps.evaluate(PolicyContext("a", "x", now=wed_3pm)).allowed
    assert not ps.evaluate(PolicyContext("a", "x", now=wed_8pm)).allowed


def test_policy_engine_integration():
    ids = IdentityRegistry()
    ids.register(AgentIdentity.generate("agent-1"))
    buds = BudgetManager()
    buds.set_budget("agent-1", Budget(spend_limit=1000, rate_limit=10**6))
    ps = PolicySet([MaxCostPerCall(5), DenyCapabilities(["wire_transfer"])])
    engine = PolicyEngine(ids, buds, policy_set=ps)

    assert engine.authorize(agent_id="agent-1", capability="add", cost=2).allowed
    assert not engine.authorize(agent_id="agent-1", capability="add", cost=99).allowed
    d = engine.authorize(agent_id="agent-1", capability="wire_transfer", cost=1)
    assert not d.allowed and "denied by policy" in d.reason


# ---------------- RBAC ----------------

def test_rbac_roles():
    assert role_can("admin", "policy:write")
    assert role_can("operator", "budgets:write")
    assert not role_can("operator", "policy:write")
    assert role_can("viewer", "audit:read")
    assert not role_can("viewer", "budgets:write")
    assert not role_can("nobody", "audit:read")


def test_rbac_require_raises():
    require("operator", "budgets:write")          # ok, no raise
    with pytest.raises(AccessDenied):
        require("viewer", "identities:write")


# ---------------- signed audit checkpoints ----------------

def test_signed_audit_checkpoint_roundtrip():
    log = AuditLog()
    log.record(actor="a", action="route_call", source_protocol="openai",
               target_protocol="mcp", capability="add", decision="allow")
    operator = AgentIdentity.generate("operator-key")
    cp = log.checkpoint(sign=operator.sign, public_key_hex=operator.public_key_hex)
    assert AuditLog.verify_checkpoint(cp) is True

    # tamper the head hash -> verification fails
    bad = dict(cp, head_hash="0" * 64)
    assert AuditLog.verify_checkpoint(bad) is False
    # tamper the signature -> fails
    bad2 = dict(cp, signature_hex="00" * 64)
    assert AuditLog.verify_checkpoint(bad2) is False


# ---------------- OIDC / JWT operator auth ----------------

def _rsa_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv_pem, pub_pem


def test_oidc_verifies_valid_token_and_extracts_role():
    import jwt
    from src.api.auth_oidc import OidcConfig, OidcVerifier, OidcError

    priv_pem, pub_pem = _rsa_keypair()
    cfg = OidcConfig(issuer="https://idp.example.com", audience="agentbridge",
                     public_key_pem=pub_pem, algorithms=["RS256"], role_claim="role")
    verifier = OidcVerifier(cfg)

    token = jwt.encode({"iss": "https://idp.example.com", "aud": "agentbridge",
                        "sub": "alice", "role": "operator",
                        "exp": int(time.time()) + 300}, priv_pem, algorithm="RS256")
    claims, role = verifier.authenticate(f"Bearer {token}")
    assert claims["sub"] == "alice"
    assert role == "operator"
    assert role_can(role, "budgets:write")


def test_oidc_rejects_bad_audience_and_expired():
    import jwt
    from src.api.auth_oidc import OidcConfig, OidcVerifier, OidcError

    priv_pem, pub_pem = _rsa_keypair()
    cfg = OidcConfig(issuer="https://idp.example.com", audience="agentbridge",
                     public_key_pem=pub_pem, algorithms=["RS256"])
    verifier = OidcVerifier(cfg)

    wrong_aud = jwt.encode({"iss": "https://idp.example.com", "aud": "someone-else",
                            "exp": int(time.time()) + 300}, priv_pem, algorithm="RS256")
    with pytest.raises(OidcError):
        verifier.verify(wrong_aud)

    expired = jwt.encode({"iss": "https://idp.example.com", "aud": "agentbridge",
                          "exp": int(time.time()) - 10}, priv_pem, algorithm="RS256")
    with pytest.raises(OidcError):
        verifier.verify(expired)

    with pytest.raises(OidcError):
        verifier.authenticate(None)
