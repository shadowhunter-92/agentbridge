"""
InlineProxy — the meta-bridge mesh.

This is the piece that makes the bridge a *bridge* and not just a translator: it
sits BETWEEN two live agents speaking different protocols, translates the request,
invokes the real target agent over its real transport, then translates the reply back.

Flows:
  a2a_request_to_mcp_agent : an A2A caller -> [bridge] -> live MCP tool server -> A2A reply
  mcp_request_to_a2a_agent : an MCP caller -> [bridge] -> live A2A agent      -> MCP reply
"""

from typing import Any, Dict, List, Optional

from ..engine.translation_engine import TranslationEngine, TranslationDirection
from . import transport


class InlineProxy:
    def __init__(self, engine: Optional[TranslationEngine] = None):
        self.engine = engine or TranslationEngine()

    # --- A2A caller  ->  live MCP tool server  ->  A2A-shaped reply ---------------
    async def a2a_request_to_mcp_agent(
        self,
        a2a_wire: Dict[str, Any],
        mcp_command: str,
        mcp_args: List[str],
    ) -> Dict[str, Any]:
        # 1) translate the incoming A2A request into an MCP tools/call
        result = self.engine.translate(a2a_wire, TranslationDirection.A2A_TO_MCP.value)
        params = result.target_data.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not tool_name:
            raise ValueError("Could not extract an MCP tool name from the A2A request")

        # 2) actually call the live MCP server
        mcp_result = await transport.call_mcp_tool(mcp_command, mcp_args, tool_name, arguments)

        # 3) wrap the MCP result back into an A2A agent message (so the caller gets A2A)
        text = " ".join(mcp_result.get("raw", [])) or ""
        a2a_reply = {
            "kind": "message",
            "messageId": self.engine._generate_msg_id(),
            "role": "agent",
            "parts": [{"kind": "text", "text": text}],
            "metadata": {
                "proxied_via": "agentbridge",
                "source_protocol": "mcp",
                "tool": tool_name,
                "isError": mcp_result.get("isError", False),
            },
        }
        return {"a2a_message": a2a_reply, "mcp_raw": mcp_result, "tool": tool_name, "arguments": arguments}

    # --- MCP caller  ->  live A2A agent  ->  MCP-shaped reply ---------------------
    async def mcp_request_to_a2a_agent(
        self,
        mcp_request: Dict[str, Any],
        a2a_base_url: str,
    ) -> Dict[str, Any]:
        # 1) translate to A2A (also validates intent) and derive the text to send
        self.engine.translate(mcp_request, TranslationDirection.MCP_TO_A2A.value)
        params = mcp_request.get("params", {})
        args = params.get("arguments", params.get("input", {})) or {}
        text = (
            args.get("text")
            or args.get("query")
            or args.get("prompt")
            or " ".join(f"{k}={v}" for k, v in args.items())
            or params.get("name", "")
        )

        # 2) actually send to the live A2A agent
        a2a_result = await transport.send_a2a_message(a2a_base_url, str(text))

        # 3) wrap the A2A reply back into an MCP tools/call result
        reply_text = " ".join(a2a_result.get("texts", []))
        mcp_reply = {
            "jsonrpc": "2.0",
            "id": mcp_request.get("id"),
            "result": {
                "content": [{"type": "text", "text": reply_text}],
                "isError": False,
            },
        }
        return {"mcp_result": mcp_reply, "a2a_raw": a2a_result.get("raw"), "sent_text": str(text)}
