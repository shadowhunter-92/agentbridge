"""
Drop-in MCP server tests: the meta-bridge exposed as MCP tools.

Unit: the tool functions work. Live: a real MCP client lists + calls the bridge tools
on the gateway running as a subprocess.
"""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.serve.mcp_gateway import bridge_list_protocols, bridge_translate


def test_tools_unit():
    assert bridge_list_protocols() == ["a2a", "acp", "agntcy", "gemini", "mcp", "openai"]
    openai_wire = json.dumps({"id": "1", "type": "function",
                              "function": {"name": "add", "arguments": "{\"a\": 2}"}})
    out = json.loads(bridge_translate("openai", "mcp", openai_wire))
    assert out["params"]["name"] == "add"


def test_gateway_runs_as_real_mcp_server():
    pytest.importorskip("mcp", reason="official mcp SDK not installed")

    async def run():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=sys.executable,
                                       args=["-m", "src.serve.mcp_gateway"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                assert {"bridge_list_protocols", "bridge_translate",
                        "bridge_call_a2a", "bridge_call_acp"} <= tools
                res = await session.call_tool("bridge_list_protocols", {})
                joined = "".join(getattr(c, "text", "") for c in (res.content or []))
                assert "mcp" in joined
    asyncio.run(run())
