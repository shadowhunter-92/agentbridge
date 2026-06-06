"""
LIVE N-protocol mesh demo — the meta-bridge routing across MANY protocols to live agents.

Uses the canonical registry (any->any translation) + real transport clients. Three cases,
each with the bridge in the middle and a REAL agent doing the work:

  Case 1: OpenAI tool-call  -> [bridge] -> LIVE MCP `add` tool -> OpenAI tool result
  Case 2: ACP run request   -> [bridge] -> LIVE MCP `add` tool -> ACP message
  Case 3: MCP tools/call     -> [bridge] -> LIVE ACP echo agent -> MCP result

So an OpenAI-style agent and an ACP agent both consumed an MCP tool, and an MCP client
consumed an ACP agent — all through one mesh. Run: python examples/live_nprotocol_proxy.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.protocols import default_registry as reg
from src.protocols.canonical import CanonicalCall
from src.proxy import transport

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = os.path.join(HERE, "mcp_server_agent.py")
ACP_SERVER = os.path.join(HERE, "acp_server_agent.py")
ACP_BASE = "http://127.0.0.1:8732"


def line(c="-"):
    print(c * 70)


def wait_http(url, timeout=25):
    start = time.time()
    while time.time() - start < timeout:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


async def case_to_live_mcp(src_proto, label):
    """src_proto call -> bridge -> live MCP `add` tool -> src_proto result."""
    src_wire = reg.get(src_proto).from_canonical_call(CanonicalCall("add", {"a": 2, "b": 3}))
    mcp_req = reg.translate_call(src_wire, src_proto, "mcp")
    mcp_res = await transport.call_mcp_tool(
        sys.executable, [MCP_SERVER],
        mcp_req["params"]["name"], mcp_req["params"]["arguments"])
    canon = reg.get("mcp").to_canonical_result(mcp_res)
    back = reg.get(src_proto).from_canonical_result(canon)
    print(f"  [{label}] {src_proto} -> live MCP add -> {src_proto}: result carries '{canon.text()}'")
    print("   ", json.dumps(back)[:220])
    return canon.text() == "5"


async def main():
    line("=")
    print("CASE 1 — OpenAI tool-call -> [bridge] -> LIVE MCP `add` tool -> OpenAI result")
    line("=")
    ok1 = await case_to_live_mcp("openai", "openai->mcp")

    line("=")
    print("CASE 2 — ACP run request -> [bridge] -> LIVE MCP `add` tool -> ACP message")
    line("=")
    ok2 = await case_to_live_mcp("acp", "acp->mcp")

    line("=")
    print("CASE 3 — MCP tools/call -> [bridge] -> LIVE ACP echo agent -> MCP result")
    line("=")
    proc = subprocess.Popen([sys.executable, ACP_SERVER],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok3 = False
    try:
        if not wait_http(f"{ACP_BASE}/agents"):
            print("  ACP agent did not start; skipping case 3.")
        else:
            mcp_call = {"jsonrpc": "2.0", "id": "n-3", "method": "tools/call",
                        "params": {"name": "echo", "arguments": {"text": "through the mesh"}}}
            canon = reg.get("mcp").to_canonical_call(mcp_call)
            acp_res = await transport.call_acp_agent(ACP_BASE, "echo", canon.best_text())
            reply = " ".join(acp_res["texts"])
            mcp_result = {"jsonrpc": "2.0", "id": "n-3",
                          "result": {"content": [{"type": "text", "text": reply}], "isError": False}}
            print(f"  MCP -> live ACP agent -> MCP: '{reply}'")
            print("   ", json.dumps(mcp_result)[:220])
            ok3 = reply == "echo: through the mesh"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    line("=")
    print("N-PROTOCOL MESH RESULT:")
    print(f"  - Case 1 (OpenAI -> live MCP tool):  {'PASS' if ok1 else 'FAIL'}")
    print(f"  - Case 2 (ACP    -> live MCP tool):  {'PASS' if ok2 else 'FAIL'}")
    print(f"  - Case 3 (MCP    -> live ACP agent): {'PASS' if ok3 else 'FAIL'}")
    print(f"  Protocols in the registry: {reg.protocols()}")
    line("=")


if __name__ == "__main__":
    asyncio.run(main())
