"""MCP adapter (Anthropic Model Context Protocol) — tools/call request + result."""

from typing import Any, Dict

from .base import ProtocolAdapter, require_mapping
from .canonical import CanonicalCall, CanonicalResult


class McpAdapter(ProtocolAdapter):
    name = "mcp"

    def to_canonical_call(self, wire: Dict[str, Any]) -> CanonicalCall:
        require_mapping(wire, self.name)
        params = wire.get("params", {}) or {}
        kwargs = dict(
            capability=params.get("name") or params.get("tool") or "",
            arguments=params.get("arguments", params.get("input", {})) or {},
            source_protocol=self.name,
        )
        if wire.get("id") is not None:
            kwargs["call_id"] = str(wire["id"])
        return CanonicalCall(**kwargs)

    def from_canonical_call(self, call: CanonicalCall) -> Dict[str, Any]:
        # Conforms to mcp.types JSONRPCRequest + CallToolRequestParams.
        return {
            "jsonrpc": "2.0",
            "id": call.call_id,
            "method": "tools/call",
            "params": {"name": call.capability, "arguments": call.arguments},
        }

    def to_canonical_result(self, wire: Dict[str, Any]) -> CanonicalResult:
        result = wire.get("result", wire) if isinstance(wire, dict) else {}
        content = []
        for block in (result.get("content") or []):
            if isinstance(block, dict) and "text" in block:
                content.append({"type": "text", "text": block["text"]})
        return CanonicalResult(content=content, is_error=bool(result.get("isError", False)))

    def from_canonical_result(self, result: CanonicalResult) -> Dict[str, Any]:
        # Conforms to mcp.types CallToolResult.
        return {
            "content": [{"type": "text", "text": b.get("text", "")} for b in result.content],
            "isError": result.is_error,
        }
