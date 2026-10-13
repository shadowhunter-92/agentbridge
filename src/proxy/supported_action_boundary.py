"""Fail closed before legacy inline proxy dispatch when semantics are unrepresentable.

This validates only the explicitly supported single-action tool-call subset.
Approval/governance still belongs at the destination-enforced action boundary.
"""
from typing import Any, Dict
from src.protocols.a2a import A2aAdapter
from src.protocols.mcp import McpAdapter


def validated_a2a_tool_action(wire: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    if not isinstance(wire, dict) or wire.get("method") != "tasks/send":
        raise ValueError("unsupported A2A procedure: only scoped tasks/send tool actions")
    call = A2aAdapter().to_canonical_call(wire)
    if not isinstance(call.capability, str) or not call.capability.strip():
        raise ValueError("A2A request lacks explicit tool capability")
    if not isinstance(call.arguments, dict):
        raise ValueError("A2A tool arguments must be a JSON object")
    # Fail closed if text and tool name compete over the requested action.
    return call.capability, call.arguments


def validated_mcp_tool_action(wire: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    if not isinstance(wire, dict) or wire.get("method") != "tools/call":
        raise ValueError("unsupported MCP procedure: only tools/call")
    call = McpAdapter().to_canonical_call(wire)
    if not isinstance(call.capability, str) or not call.capability.strip():
        raise ValueError("MCP request lacks explicit tool name")
    if not isinstance(call.arguments, dict):
        raise ValueError("MCP tool arguments must be a JSON object")
    return call.capability, call.arguments
