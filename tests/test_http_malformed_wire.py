"""Malformed action wires must reject before invocation or budget mutation."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from src.governance import AgentIdentity, Budget, sign_request


@pytest.mark.parametrize("protocol,wire", [
    ("mcp", {"method": "resources/read", "params": {"uri": "secret"}}),
    ("mcp", {"method": "tools/call", "params": "bad"}),
    ("mcp", {"method": "tools/call", "params": {"name": "add", "arguments": False}}),
    ("a2a", {"method": "tasks/cancel", "id": "t"}),
    ("a2a", {"kind": "task", "history": "bad"}),
    ("a2a", {"kind": "task", "history": [{"parts": [{"kind": "data", "data": False}]}]}),
    ("a2a", {"history": [{"parts": [{"kind": "data", "data": {"name": "one"}},
                                      {"kind": "data", "data": {"name": "two"}}]}]}),
])
def test_http_parser_rejects_malformed_action_before_effect(monkeypatch, protocol, wire):
    from src.api import control_plane as cp
    monkeypatch.setitem(cp._ready, "ok", True)
    invoked = []
    async def forbidden(*args):
        invoked.append(args)
        raise AssertionError("malformed action reached a transport")
    monkeypatch.setattr(cp, "_invoke_target", forbidden)
    agent = AgentIdentity.generate("malformed-" + uuid.uuid4().hex)
    cp.identities.register(agent)
    cp.budgets.set_budget(agent.agent_id, Budget(spend_limit=10, rate_limit=100))
    payload = {"src": protocol, "dst": "mcp", "wire": wire}
    body = json.dumps(payload).encode()
    nonce = uuid.uuid4().hex
    headers = {"X-Agent-Id": agent.agent_id, "X-Nonce": nonce,
               "X-Signature": sign_request(agent, nonce, body)}
    client = TestClient(cp.app)
    assert client.post("/control/route", content=body, headers=headers).status_code == 400
    assert client.post("/control/translate/call", json=payload).status_code == 400
    assert cp.budgets.get(agent.agent_id).spent == 0
    assert invoked == []


@pytest.mark.parametrize("raw", [b"[]", b"false", b"null", b"not-json"])
def test_signed_nonobject_body_rejected(monkeypatch, raw):
    from src.api import control_plane as cp
    monkeypatch.setitem(cp._ready, "ok", True)
    agent = AgentIdentity.generate("malformed-json-" + uuid.uuid4().hex)
    cp.identities.register(agent)
    client = TestClient(cp.app)
    for endpoint in ("/control/route", "/control/authorize"):
        nonce = uuid.uuid4().hex
        headers = {"X-Agent-Id": agent.agent_id, "X-Nonce": nonce,
                   "X-Signature": sign_request(agent, nonce, raw)}
        assert client.post(endpoint, content=raw, headers=headers).status_code == 400
