"""
Live N-protocol integration test.

For EVERY source protocol in the registry, route an `add(2,3)` call through the
canonical mesh to a REAL live MCP tool server (stdio, no network port) and assert the
live tool actually computed 5 and the result came back in the source protocol's shape.

This proves the meta-bridge routes any protocol -> a live agent, end to end.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("mcp", reason="official mcp SDK not installed")

from src.protocols import default_registry as reg
from src.protocols.canonical import CanonicalCall
from src.proxy import transport

MCP_SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "examples", "mcp_server_agent.py")


async def _route_to_live_mcp(src_proto: str) -> str:
    src_wire = reg.get(src_proto).from_canonical_call(CanonicalCall("add", {"a": 2, "b": 3}))
    mcp_req = reg.translate_call(src_wire, src_proto, "mcp")
    mcp_res = await transport.call_mcp_tool(
        sys.executable, [MCP_SERVER],
        mcp_req["params"]["name"], mcp_req["params"]["arguments"])
    return reg.get("mcp").to_canonical_result(mcp_res).text()


@pytest.mark.parametrize("src_proto", ["mcp", "a2a", "acp", "openai", "gemini", "agntcy"])
def test_any_protocol_reaches_live_mcp_tool(src_proto):
    result_text = asyncio.run(_route_to_live_mcp(src_proto))
    assert result_text == "5", f"{src_proto} -> live MCP add should yield 5, got {result_text!r}"
