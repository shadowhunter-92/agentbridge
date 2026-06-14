"""
Tests for the human-facing AgentClient (discover + call), against the real example
MCP agent spawned as a subprocess (same pattern as the other live tests).
"""

import asyncio
import os
import sys

from src.serve.agent_client import AgentClient, AgentRef

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_SERVER = os.path.join(HERE, "examples", "mcp_server_agent.py")


def test_discover_mcp_lists_tools():
    client = AgentClient()
    ref = AgentRef.mcp(sys.executable, [MCP_SERVER])
    info = asyncio.run(client.discover(ref))
    assert info["protocol"] == "mcp"
    names = {t["name"] for t in info["tools"]}
    assert {"add", "echo"} <= names          # discovery surfaces the real tools


def test_call_mcp_tool_returns_result():
    client = AgentClient()
    ref = AgentRef.mcp(sys.executable, [MCP_SERVER])
    res = asyncio.run(client.call(ref, tool="add", arguments={"a": 2, "b": 3}))
    assert " ".join(res.get("raw", [])) == "5"


def test_call_mcp_without_tool_errors():
    import pytest
    client = AgentClient()
    ref = AgentRef.mcp(sys.executable, [MCP_SERVER])
    with pytest.raises(ValueError):
        asyncio.run(client.call(ref, message="hi"))   # MCP needs a tool, not a message
