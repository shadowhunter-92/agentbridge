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


def _approved_remote_target(base_url: str) -> str:
    """Explicit operator boundary for direct MCP tools with outbound side effects.

    A URL allowlist is NOT a DNS rebinding defense. The operator's egress
    proxy must independently enforce authenticated destination and IP policy.
    """
    import os
    from urllib.parse import urlsplit
    import ipaddress

    raw = os.environ.get("AGENTBRIDGE_MCP_TARGET_ALLOWLIST_JSON", "[]")
    try:
        allowed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid operator MCP target allowlist") from exc
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        raise ValueError("operator MCP target allowlist must be an array of URLs")
    if not isinstance(base_url, str) or base_url not in allowed:
        raise ValueError("remote MCP tool destination is not operator allowlisted")
    parsed = urlsplit(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment or parsed.query
            or parsed.path not in ("", "/") or "\\" in base_url
            or any(ch.isspace() for ch in base_url)):
        raise ValueError("remote MCP tool requires a plain HTTPS origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid MCP target port") from exc
    if port not in (None, 443) or parsed.hostname.endswith("."):
        raise ValueError("nonstandard or ambiguous remote MCP target")
    hostname = parsed.hostname.lower()
    if hostname in ("localhost",) or hostname.endswith(".localhost"):
        raise ValueError("loopback MCP target prohibited")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("IP-literal MCP target prohibited")
    # Require the operator-controlled outbound proxy even in evaluation,
    # to prevent direct client network paths from bypassing the egress plane.
    proxy_url = os.environ.get("AGENTBRIDGE_EGRESS_PROXY_URL")
    if not proxy_url:
        raise ValueError("remote MCP tools require operator-configured egress proxy")
    return proxy_url


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
    proxy_url = _approved_remote_target(base_url)
    res = await transport.send_a2a_message(base_url, message, proxy_url=proxy_url)
    return " ".join(res.get("texts", []))


async def bridge_call_acp(base_url: str, agent_name: str, message: str) -> str:
    """Send `message` to a live ACP agent and return its text reply."""
    from ..proxy import transport
    proxy_url = _approved_remote_target(base_url)
    res = await transport.call_acp_agent(base_url, agent_name, message, proxy_url=proxy_url)
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
