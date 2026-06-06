"""
Control-plane HTTP API tests: N-protocol mesh + GOVERNED, AUTHENTICATED access.

Covers: public translation, admin-key operator guard, Ed25519 signed agent requests,
nonce replay rejection, budget enforcement over HTTP, identity revocation, approvals.
"""

import json
import os
import uuid

# Admin key must be set before importing the app (read at import time).
os.environ["AGENTBRIDGE_ADMIN_KEY"] = "test-admin-key"

import pytest
from fastapi.testclient import TestClient

from src.api.control_plane import app
from src.governance import AgentIdentity, sign_request

client = TestClient(app)
ADMIN = {"X-Admin-Key": "test-admin-key"}


def _register_agent(agent_id: str) -> AgentIdentity:
    r = client.post("/control/identities", json={"agent_id": agent_id}, headers=ADMIN)
    assert r.status_code == 200
    priv = r.json()["private_key_hex"]
    return AgentIdentity.from_private_hex(agent_id, priv)


def _signed(agent: AgentIdentity, payload: dict):
    body = json.dumps(payload).encode()
    nonce = uuid.uuid4().hex
    sig = sign_request(agent, nonce, body)
    headers = {"X-Agent-Id": agent.agent_id, "X-Nonce": nonce, "X-Signature": sig}
    return body, headers


# --- public ---------------------------------------------------------------------------

def test_protocols_and_translation_are_public():
    assert client.get("/control/protocols").json()["protocols"] == \
        ["a2a", "acp", "agntcy", "gemini", "mcp", "openai"]
    openai_wire = {"id": "c1", "type": "function",
                   "function": {"name": "add", "arguments": "{\"a\": 2}"}}
    r = client.post("/control/translate/call",
                    json={"src": "openai", "dst": "mcp", "wire": openai_wire})
    assert r.json()["wire"]["params"]["name"] == "add"


# --- operator plane requires admin key ------------------------------------------------

def test_operator_endpoints_require_admin_key():
    assert client.post("/control/identities", json={"agent_id": "x"}).status_code == 401
    assert client.get("/control/identities").status_code == 401
    assert client.get("/control/audit").status_code == 401
    # With the key, it works and returns a one-time private key.
    r = client.post("/control/identities", json={"agent_id": "adm-test"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["private_key_hex"]


# --- agent plane requires a valid signature -------------------------------------------

def test_route_requires_signature_and_enforces_governance():
    agent = _register_agent("router-1")
    client.put("/control/budgets/router-1", json={"spend_limit": 2, "rate_limit": 100},
               headers=ADMIN)

    payload = {"src": "mcp", "dst": "a2a",
               "wire": {"jsonrpc": "2.0", "id": "1", "method": "tools/call",
                        "params": {"name": "add", "arguments": {"a": 1}}}, "cost": 1.0}

    # Unsigned -> 401.
    assert client.post("/control/route", json=payload).status_code == 401

    # Signed -> allowed, returns translated A2A wire.
    body, headers = _signed(agent, payload)
    r = client.post("/control/route", content=body, headers=headers)
    assert r.status_code == 200 and r.json()["decision"] == "allow"
    assert "translated_wire" in r.json()

    # Replaying the same nonce -> 401.
    assert client.post("/control/route", content=body, headers=headers).status_code == 401


def test_budget_exhaustion_over_http():
    agent = _register_agent("router-2")
    client.put("/control/budgets/router-2", json={"spend_limit": 1, "rate_limit": 100},
               headers=ADMIN)
    payload = {"src": "mcp", "dst": "a2a",
               "wire": {"method": "tools/call", "params": {"name": "add", "arguments": {}}},
               "cost": 1.0}
    body, headers = _signed(agent, payload)
    assert client.post("/control/route", content=body, headers=headers).status_code == 200
    # Second call exceeds the spend cap of 1.
    body2, headers2 = _signed(agent, payload)
    assert client.post("/control/route", content=body2, headers=headers2).status_code == 403


def test_revocation_blocks_agent():
    agent = _register_agent("router-3")
    client.put("/control/budgets/router-3", json={"spend_limit": 9, "rate_limit": 100},
               headers=ADMIN)
    client.post("/control/identities/router-3/revoke", headers=ADMIN)
    payload = {"src": "mcp", "dst": "a2a",
               "wire": {"method": "tools/call", "params": {"name": "add", "arguments": {}}}}
    body, headers = _signed(agent, payload)
    # Revoked identity fails authentication.
    assert client.post("/control/route", content=body, headers=headers).status_code == 401


def test_audit_trail_records_and_verifies():
    r = client.get("/control/audit", headers=ADMIN).json()
    assert r["integrity_ok"] is True
    assert len(r["entries"]) >= 1
