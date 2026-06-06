"""
THE 60-SECOND STORY — run this to see the whole product in one go.

It shows, against a REAL live agent:
  1. Many protocols, one mesh (MCP, A2A, ACP, OpenAI, Gemini, AGNTCY).
  2. A request from EACH protocol fulfilled by the SAME live MCP tool, through the bridge.
  3. Governance enforced in the path: unknown agent blocked, identity + budget checked.
  4. A tamper-evident audit trail at the end.

Record your screen running this; it's the demo to share. Run: python examples/demo_story.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.protocols import default_registry as reg
from src.protocols.canonical import CanonicalCall
from src.proxy import transport
from src.governance import (AgentIdentity, IdentityRegistry, BudgetManager, Budget,
                            GovernanceGateway, GovernanceError)

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = os.path.join(HERE, "mcp_server_agent.py")


def hr(c="="):
    print(c * 70)


async def main():
    print("\n   AgentBridge - one mesh every agent speaks through\n")
    hr()
    print("  Protocols in the mesh: " + ", ".join(reg.protocols()))
    hr()

    ids = IdentityRegistry()
    buds = BudgetManager()
    buds.set_budget("demo-agent", Budget(spend_limit=10, rate_limit=100))
    gw = GovernanceGateway(identities=ids, budgets=buds)

    async def invoke_live_mcp(dst_wire):
        p = dst_wire["params"]
        return await transport.call_mcp_tool(sys.executable, [MCP_SERVER], p["name"], p["arguments"])

    print("\n  1) An UNKNOWN agent tries to use the mesh:")
    src_wire = reg.get("openai").from_canonical_call(CanonicalCall("add", {"a": 2, "b": 3}))
    try:
        await gw.route_call(agent_id="demo-agent", src_proto="openai", dst_proto="mcp",
                            src_wire=src_wire, invoke=invoke_live_mcp)
    except GovernanceError as e:
        print(f"     [BLOCKED] {e}")

    print("\n  2) We register its identity (Ed25519 DID) and give it a budget.")
    ids.register(AgentIdentity.generate("demo-agent"))

    print("\n  3) Now the SAME live MCP `add` tool is reached from EVERY protocol,")
    print("     each translated + governed through the one mesh:\n")
    for proto in ["openai", "gemini", "acp", "agntcy", "a2a", "mcp"]:
        wire = reg.get(proto).from_canonical_call(CanonicalCall("add", {"a": 2, "b": 3}))
        res = await gw.route_call(agent_id="demo-agent", src_proto=proto, dst_proto="mcp",
                                  src_wire=wire, invoke=invoke_live_mcp, cost=1.0)
        answer = " ".join(res.get("raw", []))
        print(f"     {proto:7} -> bridge -> live MCP tool -> {answer}")

    b = gw.budgets.get("demo-agent")
    print(f"\n  4) Budget spent: {b.spent} / {b.spend_limit}")

    print("\n  5) Tamper-evident audit trail (every call, hash-chained):")
    for e in gw.audit.entries():
        print(f"     #{e.seq} {e.decision:5} {e.source_protocol:7}->{e.target_protocol} "
              f"{e.capability}  {e.entry_hash[:10]}")
    print(f"\n     Audit integrity verified: {gw.audit.verify_integrity()}")
    hr()
    print("  Translate . route . verify . govern - any protocol, one mesh.\n")


if __name__ == "__main__":
    asyncio.run(main())
