"""
Integration test for the in-line proxy (meta-bridge mesh).

Pipe 1 is fully self-contained (spawns a real MCP server over stdio, no network port),
so it runs reliably in CI. It proves: an A2A request, routed through the bridge, is
fulfilled by a REAL live MCP tool, with the reply returned in A2A form.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("mcp", reason="official mcp SDK not installed")
pytest.importorskip("a2a.types", reason="official a2a-sdk not installed")

from src.proxy.inline_proxy import InlineProxy

MCP_SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "examples", "mcp_server_agent.py")


def test_a2a_request_fulfilled_by_live_mcp_tool():
    """A2A -> [bridge] -> live MCP `add` tool -> A2A reply, end to end."""
    proxy = InlineProxy()
    a2a_in = {
        "jsonrpc": "2.0",
        "id": "t-1",
        "method": "tasks/send",
        "params": {
            "task": {
                "history": [
                    {
                        "kind": "message",
                        "messageId": "in-1",
                        "role": "user",
                        "parts": [{"kind": "data",
                                   "data": {"name": "add", "arguments": {"a": 2, "b": 3}}}],
                    }
                ]
            }
        },
    }

    out = asyncio.run(proxy.a2a_request_to_mcp_agent(a2a_in, sys.executable, [MCP_SERVER]))

    assert out["tool"] == "add"
    # The live MCP server actually computed 2 + 3 = 5 and it came back as an A2A message.
    assert out["a2a_message"]["kind"] == "message"
    assert out["a2a_message"]["parts"][0]["text"].strip() == "5"
    assert out["a2a_message"]["metadata"]["isError"] is False
