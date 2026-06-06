"""
Drop-in MCP server — the meta-bridge packaged as an MCP server.

This is the packaging the ecosystem actually asks for (cf. microsoft/mcp-gateway#31,
Roo-Code#12007): point any MCP client (Claude Desktop, an IDE, a gateway) at this server
and it can reach agents on OTHER protocols — A2A, ACP — plus translate between any of them.

Tools exposed:
  - bridge_list_protocols()                         -> the supported protocols
  - bridge_translate(src, dst, wire_json)           -> any-to-any translation (returns JSON)
  - bridge_call_a2a(base_url, message)              -> call a live A2A agent, return its text
  - bridge_call_acp(base_url, agent_name, message)  -> call a live ACP agent, return its text

The tool bodies are plain importable functions (so they're unit-testable) and are also
registered as MCP tools. Run:  python -m src.serve.mcp_gateway   (stdio)
"""

import json
from typing import Any, Dict

from ..protocols import default_registry


def bridge_list_protocols() -> list:
    """List the agent protocols this bridge can translate between."""
    return default_registry.protocols()


def bridge_translate(src: str, dst: str, wire_json: str) -> str:
    """Translate a call from protocol `src` to protocol `dst`. `wire_json` is the source
    message as JSON. Returns the translated message as JSON."""
    wire = json.loads(wire_json)
    out = default_registry.translate_call(wire, src, dst)
    return json.dumps(out)


async def bridge_call_a2a(base_url: str, message: str) -> str:
    """Send `message` to a live A2A agent at `base_url` and return its text reply."""
    from ..proxy import transport
    res = await transport.send_a2a_message(base_url, message)
    return " ".join(res.get("texts", []))


async def bridge_call_acp(base_url: str, agent_name: str, message: str) -> str:
    """Send `message` to a live ACP agent and return its text reply."""
    from ..proxy import transport
    res = await transport.call_acp_agent(base_url, agent_name, message)
    return " ".join(res.get("texts", []))


def build_server():
    """Construct the FastMCP server with the bridge tools registered."""
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("agentbridge-meta-bridge")
    mcp.tool()(bridge_list_protocols)
    mcp.tool()(bridge_translate)
    mcp.tool()(bridge_call_a2a)
    mcp.tool()(bridge_call_acp)
    return mcp


if __name__ == "__main__":
    build_server().run()  # stdio transport
