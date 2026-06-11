"""
HTTP-level tests for operator RBAC + OIDC SSO + policy rules over the control plane.

Verifies the wiring (not just the library modules): the admin key maps to the admin role,
an OIDC bearer token maps a role claim to RBAC, viewers can read but not write, operators
can write but not change policy, and policy rules are manageable over HTTP.
"""

import json
import os
import time
import uuid

os.environ["AGENTBRIDGE_ADMIN_KEY"] = "test-admin-key"

import pytest
from fastapi.testclient import TestClient

from src.api import control_plane
from src.api.control_plane import app
from src.api.auth_oidc import OidcConfig, OidcVerifier

client = TestClient(app)
ADMIN = {"X-Admin-Key": "test-admin-key"}

ISSUER, AUDIENCE = "https://idp.test", "agentbridge"


def _rsa_pair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv_pem, pub_pem


@pytest.fixture()
def oidc(monkeypatch):
    """Enable OIDC on the live app with a locally-minted RSA key; yields a token factory."""
    import jwt
    priv_pem, pub_pem = _rsa_pair()
    verifier = OidcVerifier(OidcConfig(issuer=ISSUER, audience=AUDIENCE,
                                       public_key_pem=pub_pem, algorithms=["RS256"]))
    monkeypatch.setattr(control_plane, "oidc_verifier", verifier)

    def token(role: str) -> dict:
        t = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": f"{role}@test",
                        "role": role, "exp": int(time.time()) + 300},
                       priv_pem, algorithm="RS256")
        return {"Authorization": f"Bearer {t}"}

    yield token


@pytest.fixture(autouse=True)
def _clean_policy_rules():
    """Policy rules are module-level state; never leak them into other tests."""
    yield
    control_plane.policy_rules.rules.clear()


def test_admin_key_still_works_as_admin_role():
    r = client.post("/control/policy/rules",
                    json={"type": "max_cost", "params": {"max_cost": 50}}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["rules_active"] >= 1


def test_viewer_can_read_but_not_write(oidc):
    viewer = oidc("viewer")
    assert client.get("/control/identities", headers=viewer).status_code == 200
    assert client.get("/control/audit", headers=viewer).status_code == 200
    r = client.put("/control/budgets/some-agent",
                   json={"spend_limit": 5, "rate_limit": 10}, headers=viewer)
    assert r.status_code == 403            # budgets:write not granted to viewer
    assert client.get("/control/audit/export", headers=viewer).status_code == 403


def test_operator_can_write_but_not_policy(oidc):
    op = oidc("operator")
    r = client.put("/control/budgets/rbac-agent",
                   json={"spend_limit": 5, "rate_limit": 10}, headers=op)
    assert r.status_code == 200
    r = client.post("/control/policy/rules",
                    json={"type": "deny_capabilities", "params": {"capabilities": ["x"]}},
                    headers=op)
    assert r.status_code == 403            # policy:write is admin-only
    assert client.get("/control/policy/rules", headers=op).status_code == 200  # policy:read ok


def test_unknown_role_and_bad_token_rejected(oidc):
    nobody = oidc("nobody")
    assert client.get("/control/identities", headers=nobody).status_code == 403
    bad = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/control/identities", headers=bad).status_code == 401
    assert client.get("/control/identities").status_code == 401  # no auth at all


def test_policy_rule_enforced_end_to_end():
    """Add a max_cost rule over HTTP; a signed agent call above the cap is denied 403."""
    from src.governance import AgentIdentity, sign_request
    # register agent + generous budget (so the POLICY, not the budget, is what denies)
    r = client.post("/control/identities", json={"agent_id": "policy-agent"}, headers=ADMIN)
    agent = AgentIdentity.from_private_hex("policy-agent", r.json()["private_key_hex"])
    client.put("/control/budgets/policy-agent",
               json={"spend_limit": 1000, "rate_limit": 1000}, headers=ADMIN)
    # cap any single call at cost 5
    client.post("/control/policy/rules",
                json={"type": "max_cost", "params": {"max_cost": 5}}, headers=ADMIN)

    payload = {"src": "mcp", "dst": "a2a", "cost": 50.0,
               "wire": {"method": "tools/call", "params": {"name": "add", "arguments": {}}}}
    body = json.dumps(payload).encode()
    nonce = uuid.uuid4().hex
    headers = {"X-Agent-Id": "policy-agent", "X-Nonce": nonce,
               "X-Signature": sign_request(agent, nonce, body)}
    r = client.post("/control/route", content=body, headers=headers)
    assert r.status_code == 403
    assert "per-call cap" in json.dumps(r.json())
