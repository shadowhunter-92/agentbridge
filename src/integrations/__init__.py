"""
Framework integrations — the Trojan Horse.

Agent frameworks (LangChain, CrewAI, AutoGen, LlamaIndex, the OpenAI SDK, ...) all
ultimately emit tool calls in the OpenAI function-calling shape. So a single helper lets
any of them reach a tool/agent that lives behind a DIFFERENT protocol (MCP, A2A, ACP,
Gemini, AGNTCY) through the bridge — without that framework implementing those protocols.

Zero new dependencies: this is a thin, tested convenience over the canonical mesh. Wrap it
as a LangChain Tool / CrewAI tool / AutoGen function in a few lines (see docs/INTEGRATIONS.md).

Pure translation (no network):
    target_wire = translate_tool_call("add", {"a": 2, "b": 3}, to="mcp")

Route to a live target (you provide the transport `invoke`):
    result = await bridge_tool_call("add", {"a": 2, "b": 3}, to="mcp", invoke=call_mcp)
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from ..protocols import default_registry, ProtocolRegistry


def _normalize_openai_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    """Accept the various shapes frameworks emit and return an OpenAI tool-call wire.

    Handles:
      - full OpenAI: {"id","type":"function","function":{"name","arguments"(JSON str|dict)}}
      - bare:        {"name": ..., "arguments"/"args": {...}}
    """
    if "function" in tool_call:
        return tool_call
    name = tool_call.get("name", "")
    args = tool_call.get("arguments", tool_call.get("args", {})) or {}
    import json
    return {
        "id": str(tool_call.get("id", "call_0")),
        "type": "function",
        "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)},
    }


def translate_tool_call(name: str, arguments: Optional[Dict[str, Any]] = None, *,
                        to: str, registry: Optional[ProtocolRegistry] = None) -> Dict[str, Any]:
    """Translate a framework tool call (name + arguments) into protocol `to`'s wire form.

    Pure function, no network. e.g. translate_tool_call("add", {"a":2,"b":3}, to="a2a").
    """
    reg = registry or default_registry
    openai_wire = _normalize_openai_tool_call({"name": name, "arguments": arguments or {}})
    return reg.translate_call(openai_wire, "openai", to)


async def bridge_tool_call(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    to: str,
    invoke: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
    registry: Optional[ProtocolRegistry] = None,
) -> Dict[str, Any]:
    """Route a framework tool call to a live target on protocol `to`, return an OpenAI
    tool-result message the framework can consume.

    `invoke(target_wire)` is your transport: it delivers the translated call to the live
    target and returns its raw response wire. (See src/proxy/transport.py for ready clients.)
    """
    reg = registry or default_registry
    target_wire = translate_tool_call(name, arguments, to=to, registry=reg)
    result_wire = await invoke(target_wire)
    return reg.translate_result(result_wire, to, "openai")


async def bridge_openai_tool_call(
    tool_call: Dict[str, Any],
    *,
    to: str,
    invoke: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
    registry: Optional[ProtocolRegistry] = None,
) -> Dict[str, Any]:
    """Same as `bridge_tool_call`, but takes a whole OpenAI tool-call object (what most
    frameworks hand you directly from the model)."""
    reg = registry or default_registry
    openai_wire = _normalize_openai_tool_call(tool_call)
    target_wire = reg.translate_call(openai_wire, "openai", to)
    result_wire = await invoke(target_wire)
    return reg.translate_result(result_wire, to, "openai")


__all__ = ["translate_tool_call", "bridge_tool_call", "bridge_openai_tool_call"]
