"""
AgentClient — the human-facing "talk to agents yourself" surface.

Point it at an agent on ANY protocol (an MCP server command, an A2A base URL, or an
ACP REST endpoint), DISCOVER what it can do, then CALL or TALK to it — optionally
through the governance gateway (identity / budget / audit). This is the personal
use case: a human (you) interacting with agents across protocols, with discovery.

CLI:
    python -m src.serve.agent_client discover --mcp "python examples/mcp_server_agent.py"
    python -m src.serve.agent_client call     --mcp "python examples/mcp_server_agent.py" --tool add --args '{"a":2,"b":3}'
    python -m src.serve.agent_client discover --a2a http://localhost:9100
    python -m src.serve.agent_client talk     --a2a http://localhost:9100 --message "hello"

Library:
    client = AgentClient()
    tools  = await client.discover(AgentRef.mcp("python", ["examples/mcp_server_agent.py"]))
    result = await client.call(ref, tool="add", arguments={"a": 2, "b": 3})
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..proxy import transport


@dataclass
class AgentRef:
    """Where an agent lives and what protocol it speaks."""
    protocol: str                                   # "mcp" | "a2a" | "acp"
    command: Optional[str] = None                   # mcp: executable
    args: List[str] = field(default_factory=list)   # mcp: argv
    base_url: Optional[str] = None                  # a2a / acp
    agent_name: str = "agent"                       # acp

    @classmethod
    def mcp(cls, command: str, args: Optional[List[str]] = None) -> "AgentRef":
        return cls(protocol="mcp", command=command, args=list(args or []))

    @classmethod
    def a2a(cls, base_url: str) -> "AgentRef":
        return cls(protocol="a2a", base_url=base_url)

    @classmethod
    def acp(cls, base_url: str, agent_name: str = "agent") -> "AgentRef":
        return cls(protocol="acp", base_url=base_url, agent_name=agent_name)


class AgentClient:
    """Discover and talk to agents across protocols, as a human."""

    async def discover(self, ref: AgentRef) -> Dict[str, Any]:
        """Return what the agent can do (MCP: its tools; A2A: its AgentCard)."""
        if ref.protocol == "mcp":
            tools = await transport.list_mcp_tools(ref.command, ref.args)
            return {"protocol": "mcp", "tools": tools}
        if ref.protocol == "a2a":
            return {"protocol": "a2a", "card": await transport.fetch_a2a_card(ref.base_url)}
        if ref.protocol == "acp":
            # ACP has no standard discovery doc; the agent_name is the handle.
            return {"protocol": "acp", "agent_name": ref.agent_name, "base_url": ref.base_url}
        raise ValueError(f"unknown protocol '{ref.protocol}'")

    async def call(self, ref: AgentRef, *, tool: Optional[str] = None,
                   arguments: Optional[Dict[str, Any]] = None,
                   message: Optional[str] = None) -> Dict[str, Any]:
        """Invoke the agent. For MCP give tool+arguments; for A2A/ACP give a message."""
        if ref.protocol == "mcp":
            if not tool:
                raise ValueError("MCP call needs a tool name (use discover to list them)")
            return await transport.call_mcp_tool(ref.command, ref.args, tool, arguments or {})
        if ref.protocol == "a2a":
            return await transport.send_a2a_message(ref.base_url, message or "")
        if ref.protocol == "acp":
            return await transport.call_acp_agent(ref.base_url, ref.agent_name, message or "")
        raise ValueError(f"unknown protocol '{ref.protocol}'")

    async def talk(self, ref: AgentRef, message: str) -> str:
        """Convenience: send free text, get the agent's text reply back as a string."""
        res = await self.call(ref, message=message,
                              tool=None, arguments=None)
        if ref.protocol == "mcp":  # MCP isn't text-chat; surface raw text if any
            return " ".join(res.get("raw", []))
        return " ".join(res.get("texts", []))


# ----------------------------- CLI -----------------------------

def _ref_from_args(ns) -> AgentRef:
    if ns.mcp:
        parts = shlex.split(ns.mcp)
        return AgentRef.mcp(parts[0], parts[1:])
    if ns.a2a:
        return AgentRef.a2a(ns.a2a)
    if ns.acp:
        return AgentRef.acp(ns.acp, ns.agent_name)
    raise SystemExit("specify one of --mcp '<cmd>' | --a2a <url> | --acp <url>")


def main() -> None:
    import argparse
    import asyncio
    import json

    p = argparse.ArgumentParser(description="Discover and talk to agents on any protocol.")
    p.add_argument("action", choices=["discover", "call", "talk"])
    p.add_argument("--mcp", help="MCP server command, e.g. \"python examples/mcp_server_agent.py\"")
    p.add_argument("--a2a", help="A2A agent base URL")
    p.add_argument("--acp", help="ACP agent base URL")
    p.add_argument("--agent-name", default="agent", help="ACP agent name")
    p.add_argument("--tool", help="MCP tool to call")
    p.add_argument("--args", default="{}", help="MCP tool arguments as JSON")
    p.add_argument("--message", default="", help="message for A2A/ACP talk")
    ns = p.parse_args()

    ref = _ref_from_args(ns)
    client = AgentClient()

    async def run():
        if ns.action == "discover":
            print(json.dumps(await client.discover(ref), indent=2))
        elif ns.action == "call":
            print(json.dumps(await client.call(ref, tool=ns.tool,
                                               arguments=json.loads(ns.args)), indent=2))
        else:  # talk
            print(await client.talk(ref, ns.message))

    asyncio.run(run())


if __name__ == "__main__":
    main()
