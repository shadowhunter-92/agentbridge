"""
LIVE in-line proxy demo — the meta-bridge sitting BETWEEN two live agents.

Pipe 1 (A2A -> [bridge] -> live MCP tool server -> A2A):
    A request enters in A2A form asking to call `add(2,3)`. The bridge translates it,
    invokes the REAL MCP server's `add` tool over stdio, gets 5, and returns an A2A message.
    => An A2A-speaking caller just used an MCP tool, with the bridge in the middle.

Pipe 2 (MCP -> [bridge] -> live A2A agent -> MCP):
    An MCP `tools/call` (echo) is routed to the REAL A2A echo agent over HTTP, and the
    reply is returned as an MCP tool result.
    => An MCP-speaking caller just used an A2A agent, with the bridge in the middle.

Both agents are real running processes. This proves the in-line mesh, not just translation.

Run:  python examples/live_inline_proxy.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.proxy.inline_proxy import InlineProxy

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = os.path.join(HERE, "mcp_server_agent.py")
A2A_SERVER = os.path.join(HERE, "a2a_server_agent.py")
A2A_BASE = "http://127.0.0.1:8731"
A2A_CARD = f"{A2A_BASE}/.well-known/agent-card.json"


def line(c="-"):
    print(c * 66)


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


async def main():
    proxy = InlineProxy()

    line("=")
    print("PIPE 1 — A2A caller  ->  [AgentBridge]  ->  LIVE MCP `add` tool  ->  A2A reply")
    line("=")
    # Incoming A2A request that wants the MCP `add` tool with a=2, b=3
    a2a_in = {
        "jsonrpc": "2.0",
        "id": "proxy-1",
        "method": "tasks/send",
        "params": {
            "task": {
                "history": [
                    {
                        "kind": "message",
                        "messageId": "in-1",
                        "role": "user",
                        "parts": [{"kind": "data",
                                   "data": {"name": "add", "arguments": {"a": 2, "b": 3}}}],
                    }
                ]
            }
        },
    }
    out1 = await proxy.a2a_request_to_mcp_agent(a2a_in, sys.executable, [MCP_SERVER])
    print("  Bridge invoked the LIVE MCP tool:", out1["tool"], out1["arguments"])
    print("  A2A reply returned to caller:")
    print("   ", json.dumps(out1["a2a_message"]))
    pipe1_ok = out1["a2a_message"]["parts"][0]["text"].strip() == "5"
    print(f"  add(2,3) via the mesh == 5 ? {'PASS' if pipe1_ok else 'FAIL'}")

    line("=")
    print("PIPE 2 — MCP caller  ->  [AgentBridge]  ->  LIVE A2A echo agent  ->  MCP reply")
    line("=")
    proc = subprocess.Popen([sys.executable, A2A_SERVER],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pipe2_ok = False
    try:
        if not wait_http(A2A_CARD):
            print("  A2A agent did not start; skipping pipe 2.")
        else:
            mcp_in = {
                "jsonrpc": "2.0",
                "id": "proxy-2",
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "through the mesh"}},
            }
            out2 = await proxy.mcp_request_to_a2a_agent(mcp_in, A2A_BASE)
            print("  Bridge sent to LIVE A2A agent:", repr(out2["sent_text"]))
            print("  MCP result returned to caller:")
            print("   ", json.dumps(out2["mcp_result"]))
            reply = out2["mcp_result"]["result"]["content"][0]["text"]
            pipe2_ok = reply == "echo: through the mesh"
            print(f"  echo round-trip via the mesh ? {'PASS' if pipe2_ok else 'FAIL'}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    line("=")
    print("META-BRIDGE RESULT:")
    print(f"  - Pipe 1 (A2A -> live MCP tool -> A2A):  {'PASS' if pipe1_ok else 'FAIL'}")
    print(f"  - Pipe 2 (MCP -> live A2A agent -> MCP): {'PASS' if pipe2_ok else 'FAIL'}")
    print("  The bridge sat BETWEEN two live agents on different protocols. [in-line proxy]")
    line("=")


if __name__ == "__main__":
    asyncio.run(main())
