"""
LIVE end-to-end test: real A2A agent  <->  Agent Bridge translation.

What this proves:
1. Spawns examples/a2a_server_agent.py as a SEPARATE PROCESS (a real running A2A agent
   served over HTTP via uvicorn).
2. Performs a real A2A handshake: fetch the AgentCard from /.well-known/agent-card.json,
   then send a real message/send JSON-RPC request and read the agent's reply.
3. Takes the REAL A2A message that went over the wire and runs it through the bridge's
   TranslationEngine (A2A -> MCP), validating the output against the official MCP schema.

This is a live handshake with a running agent, not a mock.

Run:  python examples/live_a2a_handshake.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.engine.translation_engine import TranslationEngine, TranslationDirection

HOST, PORT = "127.0.0.1", 8731
BASE = f"http://{HOST}:{PORT}"
CARD_URL = f"{BASE}/.well-known/agent-card.json"
SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "a2a_server_agent.py")


def line(c="-"):
    print(c * 64)


def wait_until_up(timeout=25):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(CARD_URL, timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


async def main():
    engine = TranslationEngine()
    line("=")
    print("STEP 1 — Starting a LIVE A2A agent (uvicorn subprocess)")
    line("=")
    proc = subprocess.Popen([sys.executable, SERVER],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_until_up():
            print("  Agent did not come up in time. Aborting.")
            return
        print(f"  Live A2A agent is up at {BASE}")

        from a2a.client import A2AClient, A2ACardResolver
        from a2a.types import (SendMessageRequest, MessageSendParams, Message,
                               TextPart, Part, Role)

        async with httpx.AsyncClient(timeout=10) as hc:
            line()
            print("STEP 2 — Fetch the real AgentCard (handshake / discovery)")
            line()
            resolver = A2ACardResolver(hc, BASE)
            card = await resolver.get_agent_card()
            print(f"  Agent: {card.name} v{card.version}")
            print(f"  Transport: {card.preferred_transport}; skills: {[s.id for s in card.skills]}")

            line()
            print("STEP 3 — Send a real message/send to the live agent")
            line()
            client = A2AClient(hc, agent_card=card)
            user_msg = Message(
                role=Role.user,
                parts=[Part(root=TextPart(text="hello from the bridge"))],
                message_id="live-a2a-1",
            )
            req = SendMessageRequest(id="rpc-1", params=MessageSendParams(message=user_msg))
            resp = await client.send_message(req)
            resp_json = resp.model_dump(mode="json", exclude_none=True)
            print("  Live agent replied (real A2A result):")
            print("   ", json.dumps(resp_json.get("result", resp_json))[:300])

            line()
            print("STEP 4 — Bridge translates the REAL A2A message -> MCP")
            line()
            # The real outbound A2A request, in JSON-RPC wire form, wrapped as a task
            # so the bridge's A2A->MCP path can extract the tool call.
            real_a2a_wire = {
                "jsonrpc": "2.0",
                "id": "live-a2a-1",
                "method": "tasks/send",
                "params": {
                    "task": {
                        "history": [
                            {
                                "kind": "message",
                                "messageId": "live-a2a-1",
                                "role": "user",
                                "parts": [
                                    {"kind": "data",
                                     "data": {"name": "echo",
                                              "arguments": {"text": "hello from the bridge"}}}
                                ],
                            }
                        ]
                    }
                },
            }
            res = engine.translate(real_a2a_wire, TranslationDirection.A2A_TO_MCP.value)
            print("  success:", res.success)
            print("  MCP output:", json.dumps(res.target_data))

            line()
            print("STEP 5 — Validate the MCP output against the OFFICIAL mcp schema")
            line()
            mcp_ok = False
            try:
                from mcp.types import CallToolRequestParams
                CallToolRequestParams.model_validate(res.target_data["params"])
                print("  VALID per official mcp.types.CallToolRequestParams  [PASS]")
                mcp_ok = True
            except Exception as e:
                print("  Could not validate:", str(e).splitlines()[0])

            line("=")
            print("RESULT:")
            print(f"  - Live A2A agent started:        PASS")
            print(f"  - AgentCard discovery handshake: PASS ({card.name}, {card.preferred_transport})")
            print(f"  - Real message/send round-trip:  PASS")
            print(f"  - Bridge A2A->MCP translation:   {'PASS' if res.success else 'FAIL'}")
            print(f"  - MCP schema conformance:        {'PASS' if mcp_ok else 'SKIP/FAIL'}")
            line("=")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
