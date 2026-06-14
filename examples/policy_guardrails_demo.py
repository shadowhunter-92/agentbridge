"""
THE GUARDRAILS DEMO — watch the policy engine STOP a risky agent, and prove it.

This is the "compliance" story in ~40 seconds. An agent makes four calls through the
mesh; AgentBridge's declarative policy engine allows the safe one and BLOCKS the three
risky ones IN THE CALL PATH — before the tool is ever invoked — then hands you a
tamper-evident, hash-chained audit trail of exactly what was allowed and denied and why.

That last part is the point for a regulated buyer: the EU AI Act (Article 12, applies to
high-risk systems from 2 Aug 2026) requires automatic, lifetime event logging. This is
what that looks like in practice.

Record your screen running this. Run:  python examples/policy_guardrails_demo.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.protocols import default_registry as reg
from src.protocols.canonical import CanonicalCall
from src.proxy import transport
from src.governance import (
    AgentIdentity, IdentityRegistry, BudgetManager, Budget, ApprovalQueue,
    PolicyEngine, PolicySet, GovernanceGateway, GovernanceError,
    MaxCostPerCall, DenyCapabilities, RequireApprovalAboveCost,
)

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = os.path.join(HERE, "mcp_server_agent.py")


def hr(c="="):
    print(c * 72)


async def main():
    print("\n   AgentBridge - governance in the call path (the guardrails demo)\n")
    hr()

    # --- set up identity, budget, and a declarative policy --------------------------------
    ids = IdentityRegistry()
    ids.register(AgentIdentity.generate("agent-007"))      # a known, registered agent
    buds = BudgetManager()
    buds.set_budget("agent-007", Budget(spend_limit=5.0, rate_limit=100))

    policy = PolicySet([
        DenyCapabilities(["wire_transfer", "delete_database"]),  # never allowed, full stop
        MaxCostPerCall(3.0),                                     # no single call may cost > 3
        RequireApprovalAboveCost(2.0),                          # >2 needs a human approval
    ])
    approvals = ApprovalQueue()
    engine = PolicyEngine(ids, buds, approvals=approvals, policy_set=policy)
    gw = GovernanceGateway(identities=ids, budgets=buds, approvals=approvals, policy=engine)

    async def invoke_live_mcp(dst_wire):
        p = dst_wire["params"]
        return await transport.call_mcp_tool(sys.executable, [MCP_SERVER],
                                             p["name"], p["arguments"])

    print("  Policy in force for agent-007:")
    print("    - DENY capabilities: wire_transfer, delete_database")
    print("    - MAX cost per call: 3.0")
    print("    - APPROVAL required above cost: 2.0\n")
    hr("-")

    async def attempt(label, capability, cost, args=None):
        args = args if args is not None else {"a": 2, "b": 3}
        wire = reg.get("openai").from_canonical_call(CanonicalCall(capability, args))
        try:
            res = await gw.route_call(agent_id="agent-007", src_proto="openai",
                                      dst_proto="mcp", src_wire=wire,
                                      invoke=invoke_live_mcp, cost=cost)
            answer = " ".join(res.get("raw", [])) or "ok"
            print(f"  [ALLOWED] {label}: {capability} (cost {cost}) -> {answer}")
        except GovernanceError as e:
            print(f"  [BLOCKED] {label}: {capability} (cost {cost})")
            print(f"            reason: {e}")

    # 1) safe, cheap call -> reaches the live MCP tool
    await attempt("safe call", "add", 1.0)
    # 2) explicitly forbidden capability -> denied by policy, tool never touched
    await attempt("forbidden capability", "wire_transfer", 1.0)
    # 3) over the per-call cost cap -> denied
    await attempt("too expensive", "add", 4.0)
    # 4) needs human approval (no approval granted yet) -> denied, approval opened
    await attempt("needs approval", "add", 2.5)

    print()
    hr("-")
    b = gw.budgets.get("agent-007")
    print(f"  Budget spent: {b.spent} / {b.spend_limit}   "
          f"(denied calls cost nothing - reservations released)")
    pend = approvals.pending()
    print(f"  Pending human approvals opened by policy: {len(pend)}")

    print("\n  Tamper-evident audit trail (every decision, hash-chained):")
    for e in gw.audit.entries():
        print(f"    #{e.seq}  {e.decision:5}  {e.capability:14}  "
              f"{e.entry_hash[:12]}  {('- ' + e.reason) if e.reason else ''}")
    print(f"\n  Audit integrity verified: {gw.audit.verify_integrity()}")
    print("  (EU AI Act Art. 12 calls this 'automatic recording of events over the "
          "system's lifetime'.)")
    hr()
    print("  Same mesh, any protocol in -> policy enforced -> provable log out.\n")


if __name__ == "__main__":
    asyncio.run(main())
