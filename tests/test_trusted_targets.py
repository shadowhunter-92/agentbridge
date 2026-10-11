"""Regression checks for operator-owned routing targets and cost schedule."""
import json
import pytest
from src.api.trusted_targets import (
    SecurityConfigurationError, resolve_target, validate_cost, effective_call_cost
)


@pytest.fixture
def routes():
    return {"AGENTBRIDGE_TARGETS_JSON": json.dumps({
        "math": {"protocol": "mcp", "capabilities": ["add"], "kind": "mcp_stdio",
                 "command": "python", "args": ["examples/mcp_server_agent.py"]},
        "billing": {"protocol": "acp", "capabilities": ["invoice_status"],
                    "kind": "acp_http", "base_url": "https://billing.example.org"}
    })}


def test_translation_only_no_target(routes):
    assert resolve_target(None, "mcp", "add", env=routes) is None


def test_operator_owned_mcp_target(routes):
    assert resolve_target("math", "mcp", "add", env=routes) == {
        "kind": "mcp_stdio", "command": "python",
        "args": ["examples/mcp_server_agent.py"]}


@pytest.mark.parametrize("protocol,capability,target", [
    ("mcp", "delete_database", "math"), ("a2a", "add", "math"),
    ("mcp", "add", "unlisted"), ("acp", "add", "billing")
])
def test_unregistered_or_unapproved_target_rejected(routes, protocol, capability, target):
    with pytest.raises(SecurityConfigurationError):
        resolve_target(target, protocol, capability, env=routes)


@pytest.mark.parametrize("bad", [-1, "-2", float("nan"), float("inf"),
                                 "inf", "nan", True, "not-a-number", None])
def test_invalid_cost_rejected(bad):
    with pytest.raises(SecurityConfigurationError):
        validate_cost(bad)


def test_production_uses_operator_cost():
    env = {"AGENTBRIDGE_ENV": "production",
           "AGENTBRIDGE_COST_SCHEDULE_JSON": '{"add":7.5}'}
    assert effective_call_cost(0, "add", env=env) == 7.5
    assert effective_call_cost(9999, "add", env=env) == 7.5


def test_production_unknown_cost_fails_closed():
    with pytest.raises(SecurityConfigurationError):
        effective_call_cost(0, "transfer", env={"AGENTBRIDGE_ENV": "production"})


def test_production_requires_https(routes):
    routes["AGENTBRIDGE_ENV"] = "production"
    routes["AGENTBRIDGE_TARGETS_JSON"] = json.dumps({
        "x": {"protocol": "a2a", "kind": "a2a_http",
              "capabilities": ["send"], "base_url": "http://internal.local"}})
    with pytest.raises(SecurityConfigurationError, match="HTTPS"):
        resolve_target("x", "a2a", "send", env=routes)


def test_invalid_capability_allowlist_fails_closed():
    with pytest.raises(SecurityConfigurationError):
        resolve_target("x", "mcp", "add", env={
            "AGENTBRIDGE_TARGETS_JSON": '{"x":{"protocol":"mcp","kind":"mcp_stdio","capabilities":[],"command":"python"}}'})
