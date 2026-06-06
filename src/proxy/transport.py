"""
Real transport clients for the in-line proxy (the meta-bridge mesh).

Unlike the routing mesh's plain HTTP-POST `/forward/*`, these are REAL protocol
clients that actually invoke live agents:

- `call_mcp_tool`   -> connects to a live MCP server over stdio and calls a tool.
- `send_a2a_message`-> connects to a live A2A agent over HTTP/JSON-RPC and sends a message.

Both use the official SDKs (`mcp`, `a2a-sdk`). They are async.
"""

from typing import Any, Dict, List, Optional


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
) -> Dict[str, Any]:
    """Send a message to a live A2A agent (HTTP/JSON-RPC) and normalize the reply.

    Returns: {"texts": [...], "raw": <full result dict>}
    """
    import httpx
    # NOTE: a2a-sdk marks A2AClient deprecated in favor of ClientFactory; it still works
    # and is pinned via requirements. Migrate to ClientFactory when we bump a2a-sdk.
    from a2a.client import A2AClient, A2ACardResolver
    from a2a.types import (SendMessageRequest, MessageSendParams, Message,
                           TextPart, Part, Role)

    async with httpx.AsyncClient(timeout=timeout) as hc:
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
) -> Dict[str, Any]:
    """Invoke a live ACP agent (REST /runs, sync mode) and normalize the reply.

    The request/response are validated against the official `acp_sdk.models`.
    Returns: {"texts": [...], "raw": <run dict>}
    """
    import httpx
    from acp_sdk.models import RunCreateRequest, Run, Message, MessagePart

    req = RunCreateRequest(
        agent_name=agent_name,
        input=[Message(role="user",
                       parts=[MessagePart(content=text, content_type="text/plain")])],
    )
    async with httpx.AsyncClient(timeout=timeout) as hc:
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
