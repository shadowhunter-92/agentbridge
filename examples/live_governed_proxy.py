"""
LIVE governed mesh demo — the moat in action with a real agent.

An OpenAI-style caller routes through the GovernanceGateway to a LIVE MCP `add` tool.
The gateway enforces identity + budget and writes a tamper-evident audit trail.

  1. Unverified caller            -> DENIED (no identity), audited as "deny".
  2. Verified caller, in budget   -> ALLOWED, routed openai->mcp to the live tool (=5),
                                     budget charged, audited as "allow".
  3. Verified caller, over budget -> DENIED, audited as "deny".
  4. Audit chain integrity verified; tampering is shown to break it.

Run:  python examples/live_governed_proxy.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.governance import (AgentIdentity, IdentityRegistry, Budget, BudgetManager,
                            GovernanceGateway, GovernanceError)
from src.protocols.canonical import CanonicalCall
from src.proxy import transport

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = os.path.join(HERE, "mcp_server_agent.py")


def line(c="-"):
    print(c * 70)


async def invoke_live_mcp(dst_wire):
    params = dst_wire["params"]
    res = await transport.call_mcp_tool(sys.executable, [MCP_SERVER],
                                        params["name"], params["arguments"])
    return res


async def main():
    ids = IdentityRegistry()
    buds = BudgetManager()
    buds.set_budget("trading-agent", Budget(spend_limit=2.0, rate_limit=100))
    gw = GovernanceGateway(identities=ids, budgets=buds)

    openai_call = gw.registry.get("openai").from_canonical_call(
        CanonicalCall("add", {"a": 2, "b": 3}))

    line("="); print("1) UNVERIFIED caller routes openai -> live MCP add"); line("=")
    try:
        await gw.route_call(agent_id="trading-agent", src_proto="openai", dst_proto="mcp",
                            src_wire=openai_call, invoke=invoke_live_mcp, cost=1.0)
        print("  ERROR: should have been denied")
    except GovernanceError as e:
        print(f"  DENIED as expected: {e}")

    line("="); print("2) Register identity (Ed25519 DID), then route again"); line("=")
    ident = AgentIdentity.generate("trading-agent")
    ids.register(ident)
    print(f"  Registered DID: {ident.did[:48]}...")
    res = await gw.route_call(agent_id="trading-agent", src_proto="openai", dst_proto="mcp",
                              src_wire=openai_call, invoke=invoke_live_mcp, cost=1.0)
    print(f"  ALLOWED. Live MCP tool returned: {res['raw']}  (add 2+3)")
    print(f"  Budget remaining: {gw.budgets.get('trading-agent').remaining()}")

    line("="); print("3) Spend the rest of the budget, then exceed it"); line("=")
    await gw.route_call(agent_id="trading-agent", src_proto="openai", dst_proto="mcp",
                        src_wire=openai_call, invoke=invoke_live_mcp, cost=1.0)
    try:
        await gw.route_call(agent_id="trading-agent", src_proto="openai", dst_proto="mcp",
                            src_wire=openai_call, invoke=invoke_live_mcp, cost=1.0)
        print("  ERROR: should have been denied")
    except GovernanceError as e:
        print(f"  DENIED (over budget) as expected: {e}")

    line("="); print("4) Tamper-evident audit trail"); line("=")
    for e in gw.audit.entries():
        print(f"  #{e.seq} {e.decision:5} {e.source_protocol}->{e.target_protocol} "
              f"{e.capability} cost={e.cost} hash={e.entry_hash[:10]}")
    print(f"  Audit integrity OK? {gw.audit.verify_integrity()}")
    gw.audit.entries()[1].cost = 0.0  # tamper
    print(f"  After tampering one entry -> integrity OK? {gw.audit.verify_integrity()}")

    line("="); print("RESULT: identity + budget enforced in the call path, audit chained. [moat]"); line("=")


if __name__ == "__main__":
    asyncio.run(main())
