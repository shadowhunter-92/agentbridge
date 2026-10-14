"""Unsupported MCP procedures must never be silently treated as governed tools."""
import pytest
from src.protocols.mcp import McpAdapter


@pytest.mark.parametrize("method", [
    "resources/read", "prompts/get", "notifications/cancelled",
    "sampling/createMessage", "roots/list", "initialize", "tools/list",
])
def test_unsupported_mcp_methods_fail_closed(method):
    wire={"jsonrpc":"2.0","id":1,"method":method,
          "params":{"name":"delete_all","arguments":{}}}
    with pytest.raises(ValueError,match="only MCP tools/call"):
        McpAdapter().to_canonical_call(wire)


def test_supported_mcp_tool_still_decodes():
    call=McpAdapter().to_canonical_call(
        {"jsonrpc":"2.0","id":12,"method":"tools/call",
         "params":{"name":"lookup","arguments":{"id":1}}})
    assert call.capability=="lookup"
    assert call.arguments=={"id":1}
