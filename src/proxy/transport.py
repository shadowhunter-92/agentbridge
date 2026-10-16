"""
Real transport clients for the in-line proxy (the meta-bridge mesh).

Unlike the routing mesh's plain HTTP-POST `/forward/*`, these are REAL protocol
clients that actually invoke live agents:

- `call_mcp_tool`   -> connects to a live MCP server over stdio and calls a tool.
- `send_a2a_message`-> connects to a live A2A agent over HTTP/JSON-RPC and sends a message.

Both use the official SDKs (`mcp`, `a2a-sdk`). They are async.
"""

from typing import Any, Dict, List, Optional


async def list_mcp_tools(command: str, args: List[str]) -> List[Dict[str, Any]]:
    """Discovery: connect to a live MCP server (stdio) and list the tools it offers.

    Returns: [{"name": ..., "description": ..., "input_schema": {...}}, ...]
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=command, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
    return [{"name": t.name,
             "description": getattr(t, "description", "") or "",
             "input_schema": getattr(t, "inputSchema", None)}
            for t in listed.tools]


async def fetch_a2a_card(base_url: str, timeout: float = 15.0,
                         proxy_url: Optional[str] = None) -> Dict[str, Any]:
    """Discovery: fetch a live A2A agent's AgentCard (its name, skills, capabilities).

    This is how you find out what a remote A2A agent can do before talking to it.
    """
    import httpx
    from a2a.client import A2ACardResolver

    async with httpx.AsyncClient(timeout=timeout,proxy=proxy_url,trust_env=False) as hc:
        card = await A2ACardResolver(hc, base_url).get_agent_card()
    return card.model_dump(mode="json", exclude_none=True)


async def call_mcp_tool(
    command: str,
    args: List[str],
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Invoke a tool on a live MCP server (stdio transport) and normalize the result.

    Returns: {"isError": bool, "content": [{"type": "text", "text": ...}, ...], "raw": <texts>}
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=command, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    content: List[Dict[str, Any]] = []
    texts: List[str] = []
    for block in (result.content or []):
        text = getattr(block, "text", None)
        if text is not None:
            content.append({"type": "text", "text": text})
            texts.append(text)
        else:
            content.append({"type": getattr(block, "type", "unknown"), "data": str(block)})

    return {
        "isError": bool(getattr(result, "isError", False)),
        "content": content,
        "raw": texts,
    }


async def send_a2a_message(
    base_url: str,
    text: str,
    message_id: str = "proxy-msg-1",
    timeout: float = 15.0,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a message to a live A2A agent (HTTP/JSON-RPC) and normalize the reply.

    Returns: {"texts": [...], "raw": <full result dict>}
    """
    import httpx

    # NOTE: a2a-sdk marks A2AClient deprecated in favor of ClientFactory; it still works
    # and is pinned via requirements. Migrate to ClientFactory when we bump a2a-sdk.
    from a2a.client import A2ACardResolver, A2AClient
    from a2a.types import Message, MessageSendParams, Part, Role, SendMessageRequest, TextPart

    async with httpx.AsyncClient(timeout=timeout,proxy=proxy_url,trust_env=False) as hc:
        card = await A2ACardResolver(hc, base_url).get_agent_card()
        client = A2AClient(hc, agent_card=card)
        msg = Message(
            role=Role.user,
            parts=[Part(root=TextPart(text=text))],
            message_id=message_id,
        )
        req = SendMessageRequest(id="rpc-proxy-1", params=MessageSendParams(message=msg))
        resp = await client.send_message(req)

    data = resp.model_dump(mode="json", exclude_none=True)
    result = data.get("result", data)

    # Pull any text parts out of the agent's reply (message or task history).
    texts: List[str] = []

    def _collect(parts):
        for p in parts or []:
            # JSON-RPC parts look like {"kind": "text", "text": "..."}
            if isinstance(p, dict):
                if p.get("kind") == "text" and "text" in p:
                    texts.append(p["text"])
                elif "root" in p and isinstance(p["root"], dict) and p["root"].get("kind") == "text":
                    texts.append(p["root"].get("text", ""))

    if isinstance(result, dict):
        _collect(result.get("parts"))
        for m in (result.get("history") or []):
            if isinstance(m, dict):
                _collect(m.get("parts"))

    return {"texts": texts, "raw": result}


async def call_acp_agent(
    base_url: str,
    agent_name: str,
    text: str,
    timeout: float = 15.0,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Invoke a live ACP agent (REST /runs, sync mode) and normalize the reply.

    The request/response are validated against the official `acp_sdk.models`.
    Returns: {"texts": [...], "raw": <run dict>}
    """
    import httpx
    from acp_sdk.models import Message, MessagePart, Run, RunCreateRequest

    req = RunCreateRequest(
        agent_name=agent_name,
        input=[Message(role="user",
                       parts=[MessagePart(content=text, content_type="text/plain")])],
    )
    async with httpx.AsyncClient(timeout=timeout,proxy=proxy_url,trust_env=False) as hc:
        resp = await hc.post(f"{base_url}/runs",
                             json=req.model_dump(mode="json", exclude_none=True))
        resp.raise_for_status()
        run = Run.model_validate(resp.json())  # validate reply against the REAL ACP schema

    texts: List[str] = []
    for msg in (run.output or []):
        for part in msg.parts:
            if (part.content_type or "").startswith("text/") and part.content:
                texts.append(part.content)
    return {"texts": texts, "raw": run.model_dump(mode="json", exclude_none=True)}

async def call_mcp_http_tool(
    endpoint: str,
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    timeout: float = 15.0,
    headers: Optional[Dict[str, str]] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Developer-owned Streamable HTTP tool call using the official MCP SDK.

    This direct client is not an execution authority or governed API route.
    Operators own endpoints/credentials; the public proxy must not map arbitrary
    agent URLs here. SDK negotiation/session handling remain protocol-versioned.
    """
    import asyncio
    import math
    from urllib.parse import urlsplit

    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    parsed = urlsplit(endpoint)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or \
            parsed.username or parsed.password or parsed.fragment or \
            (parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("explicit operator-owned HTTP(S) endpoint required")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or \
            not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise ValueError("bounded finite transport timeout required")
    if not isinstance(tool_name, str) or not tool_name or not isinstance(arguments, dict):
        raise ValueError("tool name and argument map required")
    deadline = asyncio.timeout(timeout)
    try:
        async with deadline, httpx.AsyncClient(timeout=timeout, headers=headers, proxy=proxy_url,
                                     trust_env=False, follow_redirects=False) as http:
            async with streamable_http_client(endpoint, http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
    except Exception as exc:
        # SDK TaskGroup/session cleanup can surface a secondary HTTP error after
        # our cancellation. Preserve a stable deadline result and its cause.
        if deadline.expired():
            raise TimeoutError("MCP HTTP deadline exceeded; remote outcome is unknown") from exc
        raise
    content, texts = [], []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            content.append({"type": "text", "text": text})
            texts.append(text)
        else:
            content.append({"type": getattr(block, "type", "unknown"), "data": str(block)})
    return {"isError": bool(result.isError), "content": content, "raw": texts,
            "protocolVersion": initialized.protocolVersion}


async def invoke_target(dst_proto: str, dst_wire: Dict[str, Any],
                         target: Optional[Dict[str, Any]], *, registry=None) -> Dict[str, Any]:
    """Invoke a live target if one is specified, else return the translated wire."""
    if not target:
        return {"translated_wire": dst_wire}
    from ..protocols import default_registry
    registry = registry or default_registry
    kind = target.get("kind")
    if kind == "mcp_stdio":
        params = dst_wire.get("params", {})
        res = await call_mcp_tool(target["command"], target.get("args", []),
                                            params.get("name"), params.get("arguments", {}))
        return {"result": res}
    if kind == "a2a_http":
        message = registry.get(dst_proto).to_canonical_call(dst_wire).best_text()
        return {"result": await send_a2a_message(target["base_url"], message,
                                                           proxy_url=target.get("proxy_url"))}
    if kind == "acp_http":
        return {"result": await call_acp_agent(target["base_url"],
                                                          target.get("agent_name", "agent"),
                                                          registry.get(dst_proto).to_canonical_call(dst_wire).best_text(),
                                                          proxy_url=target.get("proxy_url"))}
    raise ValueError(f"unknown target kind '{kind}'")
