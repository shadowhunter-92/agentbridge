"""Actual local stdio negatives and offline evidence tampering controls."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from mcp.types import CallToolResult, TextContent

from examples.governed_mcp_demo import decoded_result, run_demo, validate_demo_call
from src.governance.evidence_cli import verify_bundle


@pytest.mark.parametrize("scenario,effects,state,reserved", [
    ("success", 1, "succeeded", 0), ("lost-ack", 1, "unknown", 1000000),
    ("denied", 0, None, 0), ("tool-error", 0, "unknown", 1000000),
    ("timeout", 0, "unknown", 1000000), ("split-brain", 1, "succeeded", 0),
])
def test_actual_governed_stdio_scenarios(tmp_path, scenario, effects, state, reserved):
    output = tmp_path / scenario
    result = asyncio.run(run_demo(output, scenario, approve=lambda: scenario != "denied"))
    assert result["passed"], result
    assert result["effects"] == effects
    assert result["operation_state"] == state
    assert result["reserved_cents"] == reserved
    assert result["mcp_server"]["pid"] > 0
    assert result["mcp_server"]["mcp_sdk"] == "1.30.0"
    if scenario in {"lost-ack", "tool-error", "timeout"}:
        assert result["checks"]["exact_injected_fault_observed"]
        assert result["error_type"] == ("McpError" if scenario == "timeout" else "McpToolFault")
    if effects:
        bundle = json.loads((output / "evidence-bundle.json").read_bytes())
        roots = json.loads((output / "trust-roots.json").read_bytes())
        expected = json.loads((output / "expected-action.json").read_bytes())
        assert verify_bundle(bundle, roots, expected_action=expected)["verdict"] == "signature_and_binding_verified"
        changed = copy.deepcopy(bundle)
        changed["expected"]["operation_id"] = "replayed-other-operation"
        with pytest.raises(ValueError):
            verify_bundle(changed, roots, expected_action=expected)
        changed = copy.deepcopy(bundle)
        changed["receipt"]["signature_hex"] = "00" * 64
        with pytest.raises(ValueError):
            verify_bundle(changed, roots, expected_action=expected)


def test_mcp_tool_error_cannot_be_returned_as_success():
    with pytest.raises(RuntimeError):
        decoded_result(CallToolResult(isError=True, content=[TextContent(type="text", text="failure")]))
    with pytest.raises(RuntimeError):
        decoded_result(CallToolResult(content=[TextContent(type="text", text="ambiguous")]))


@pytest.mark.parametrize("task", [{}, None, False, {"ttl": 60000}])
def test_unsupported_task_augmentation_refuses_before_admission(task):
    wire = dict(jsonrpc="2.0", id=1, method="tools/call", params=dict(name="transfer_funds",
        arguments=dict(amount_cents=1000000, currency="usd", recipient="synthetic-design-partner"), task=task))
    with pytest.raises(ValueError):
        validate_demo_call(wire)


@pytest.mark.parametrize("name,value", [("AGENTBRIDGE_ENV", "production"), ("AGENTBRIDGE_AUTHORITY_MODE", "multi_tenant")])
def test_production_and_tenant_mode_refuse_without_output(tmp_path, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    output = tmp_path / "refused"
    with pytest.raises((ValueError, RuntimeError)):
        asyncio.run(run_demo(output, approve=lambda: True))
    assert not output.exists()


def test_existing_output_is_not_reused(tmp_path):
    with pytest.raises(FileExistsError):
        asyncio.run(run_demo(tmp_path, approve=lambda: True))
