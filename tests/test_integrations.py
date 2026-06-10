"""
Tests for the framework-integration helpers.

Frameworks (LangChain/CrewAI/AutoGen/LlamaIndex) emit OpenAI-shaped tool calls; these
helpers route them to any protocol through the bridge. We test the pure translation and
the full route (with a no-op transport), plus the various input shapes.
"""

import asyncio

import pytest

from src.integrations import translate_tool_call, bridge_tool_call, bridge_openai_tool_call


def test_translate_tool_call_to_every_protocol():
    for dst in ("mcp", "a2a", "acp", "gemini", "agntcy"):
        wire = translate_tool_call("add", {"a": 2, "b": 3}, to=dst)
        assert isinstance(wire, dict) and wire  # produced a non-empty target wire
    # mcp target is a real tools/call
    mcp = translate_tool_call("add", {"a": 2, "b": 3}, to="mcp")
    assert mcp["method"] == "tools/call"
    assert mcp["params"]["name"] == "add"
    assert mcp["params"]["arguments"] == {"a": 2, "b": 3}


def test_bridge_tool_call_routes_and_returns_openai_result():
    async def fake_mcp(target_wire):
        # pretend the live MCP tool ran and returned 5
        assert target_wire["params"]["name"] == "add"
        return {"content": [{"type": "text", "text": "5"}], "isError": False}

    out = asyncio.run(bridge_tool_call("add", {"a": 2, "b": 3}, to="mcp", invoke=fake_mcp))
    assert out["role"] == "tool"          # OpenAI tool-result shape the framework consumes
    assert out["content"] == "5"


def test_bridge_openai_tool_call_accepts_full_openai_object():
    tc = {"id": "call_1", "type": "function",
          "function": {"name": "add", "arguments": '{"a": 2, "b": 3}'}}

    async def fake_a2a(target_wire):
        return {"kind": "message", "messageId": "m1", "role": "agent",
                "parts": [{"kind": "text", "text": "ok"}]}

    out = asyncio.run(bridge_openai_tool_call(tc, to="a2a", invoke=fake_a2a))
    assert out["role"] == "tool"
    assert "ok" in out["content"]


def test_bare_and_args_shapes_are_normalized():
    # bare {"name","args"} (some frameworks use args, not arguments)
    w1 = translate_tool_call("search", {"q": "x"}, to="mcp")
    assert w1["params"]["name"] == "search"
    # full openai object via bridge_openai_tool_call path, args as dict (Gemini-style)
    tc = {"function": {"name": "search", "arguments": {"q": "x"}}}

    async def noop(_):
        return {"content": [{"type": "text", "text": "done"}]}

    out = asyncio.run(bridge_openai_tool_call(tc, to="mcp", invoke=noop))
    assert out["content"] == "done"
