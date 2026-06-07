"""
Quickstart — the friction-free path. NO identity, NO budgets, NO audit, NO setup.

Governance is entirely OPT-IN. If you just want one agent/protocol to talk to another,
you use the mesh directly — three lines, zero keys. Add governance later, only when you
actually need identity / spend control / an audit trail (see examples/demo_story.py).

Run:  python examples/quickstart.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.protocols import default_registry as reg
from src.protocols.canonical import CanonicalCall
from src.proxy import transport

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = os.path.join(HERE, "mcp_server_agent.py")


def translate_only():
    """Pure any-to-any translation. No governance, no setup whatsoever."""
    print("1) Translate one tool call into every protocol (no setup):\n")
    call = reg.get("openai").from_canonical_call(CanonicalCall("add", {"a": 2, "b": 3}))
    for dst in ("mcp", "a2a", "acp", "gemini", "agntcy"):
        out = reg.translate_call(call, "openai", dst)
        print(f"   openai -> {dst:6} : {out}")


async def bridge_to_a_live_tool():
    """Reach a live MCP tool from an OpenAI-shaped call — still zero governance."""
    print("\n2) Bridge an OpenAI-shaped call to a LIVE MCP tool (still no governance):\n")
    call = reg.get("openai").from_canonical_call(CanonicalCall("add", {"a": 2, "b": 3}))
    mcp_wire = reg.translate_call(call, "openai", "mcp")
    p = mcp_wire["params"]
    result = await transport.call_mcp_tool(sys.executable, [MCP_SERVER], p["name"], p["arguments"])
    print(f"   openai add(2,3) -> bridge -> live MCP tool -> {' '.join(result.get('raw', []))}")
    print("\n   That's it. Add identity/budgets/audit only when you want them.\n")


if __name__ == "__main__":
    print("\nAgentBridge quickstart - governance is OPTIONAL\n" + "=" * 52)
    translate_only()
    asyncio.run(bridge_to_a_live_tool())
