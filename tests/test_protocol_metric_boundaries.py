"""Rejected protocol IDs must not allocate persistent per-input telemetry."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from src.governance import AgentIdentity, Budget, sign_request
from src.observability import CALL_DURATION, CALLS_TOTAL, TRANSLATE_DURATION, record_call, record_translate


@pytest.mark.parametrize("field", ["src", "dst"])
def test_rejected_protocols_do_not_enter_governance_or_allocate_metrics(monkeypatch, field):
    from src.api import control_plane as cp
    monkeypatch.setenv("AGENTBRIDGE_ENV", "development")
    monkeypatch.setitem(cp._ready, "ok", True)
    agent = AgentIdentity.generate("metric-probe-" + uuid.uuid4().hex)
    cp.identities.register(agent)
    cp.budgets.set_budget(agent.agent_id, Budget(spend_limit=100, rate_limit=1000))
    before = len(CALLS_TOTAL._metrics), len(CALL_DURATION._metrics), cp.audit.count()
    client = TestClient(cp.app)
    for number in range(25):
        payload = {"src": "mcp", "dst": "a2a", "wire": {
            "method": "tools/call", "params": {"name": "add", "arguments": {}}}}
        payload[field] = "unregistered-" + field + str(number)
        body = json.dumps(payload).encode()
        nonce = uuid.uuid4().hex
        response = client.post("/control/route", content=body, headers={
            "X-Agent-Id": agent.agent_id, "X-Nonce": nonce,
            "X-Signature": sign_request(agent, nonce, body)})
        assert response.status_code == 400
    assert (len(CALLS_TOTAL._metrics), len(CALL_DURATION._metrics), cp.audit.count()) == before
    assert cp.budgets.get(agent.agent_id).spent == 0


def test_direct_metric_protocol_labels_have_a_finite_domain():
    before = len(CALLS_TOTAL._metrics), len(CALL_DURATION._metrics), len(TRANSLATE_DURATION._metrics)
    for number in range(200):
        record_call("unknown-src-" + str(number), "unknown-dst-" + str(number), "add", "deny", .01)
        record_translate("unknown-src-" + str(number), "unknown-dst-" + str(number), .01)
    assert len(CALLS_TOTAL._metrics) - before[0] <= 1
    assert len(CALL_DURATION._metrics) - before[1] <= 1
    assert len(TRANSLATE_DURATION._metrics) - before[2] <= 1
    record_call("mcp", "a2a", "add", "allow", .01)
    assert any(key[0:2] == ("mcp", "a2a") for key in CALLS_TOTAL._metrics)


def test_capability_and_decision_metric_labels_are_bounded():
    before = len(CALLS_TOTAL._metrics)
    for number in range(300):
        record_call("mcp", "a2a", "untrusted-capability-" + str(number), "unknown-decision-" + str(number), .01)
    assert len(CALLS_TOTAL._metrics) - before <= 129
    before = len(CALLS_TOTAL._metrics)
    for number in range(100):
        record_call("mcp", "a2a", "oversized-" + str(number) + "x" * 1000, "deny", .01)
    assert len(CALLS_TOTAL._metrics) - before <= 1


@pytest.mark.parametrize("field", ["src_proto", "dst_proto"])
async def test_library_rejects_unknown_protocol_before_any_policy_state(field):
    from src.governance import GovernanceGateway
    gateway = GovernanceGateway()
    invoked = []

    async def invoke(wire):
        invoked.append(wire)
        return {}

    request = {"agent_id": "not-enrolled", "src_proto": "mcp", "dst_proto": "a2a",
               "src_wire": {"method": "tools/call", "params": {"name": "add", "arguments": {}}},
               "invoke": invoke}
    request[field] = "unregistered-protocol"
    with pytest.raises(KeyError, match="Unknown protocol"):
        await gateway.route_call(**request)
    assert not invoked
    assert gateway.audit.count() == 0
