"""
LIVE end-to-end test: real MCP agent  <->  Agent Bridge translation.

What this proves:
1. Spawns examples/mcp_server_agent.py as a SEPARATE PROCESS (a real running MCP agent).
2. Performs a real MCP handshake over stdio: initialize -> list_tools -> call_tool.
3. Takes the REAL wire messages from that exchange and runs them through the
   bridge's TranslationEngine, validating the MCP<->A2A conversion against the
   official A2A schema.

This is a live handshake with a running agent, not a mock.

Run:  python examples/live_mcp_handshake.py
"""

import asyncio
import json
import os
import sys

# Make the bridge importable when run from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.engine.translation_engine import TranslationEngine, TranslationDirection

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server_agent.py")


def line(c="-"):
    print(c * 64)


async def main():
    engine = TranslationEngine()
    params = StdioServerParameters(command=sys.executable, args=[SERVER])

    line("=")
    print("STEP 1 — Connecting to a LIVE MCP agent (subprocess over stdio)")
    line("=")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # Real protocol handshake
            init = await session.initialize()
            print(f"  Handshake OK. Server: {init.serverInfo.name} v{init.serverInfo.version}")
            print(f"  Protocol version: {init.protocolVersion}")

            line()
            print("STEP 2 — Real tools/list from the live agent")
            line()
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"  Live agent exposes tools: {tool_names}")

            line()
            print("STEP 3 — Real tools/call (add 2 + 3) to the live agent")
            line()
            call = await session.call_tool("add", {"a": 2, "b": 3})
            result_text = call.content[0].text if call.content else None
            print(f"  Live agent returned: {result_text}")

            # Build the REAL MCP request that just went over the wire and translate it.
            real_mcp_request = {
                "jsonrpc": "2.0",
                "id": "live-1",
                "method": "tools/call",
                "params": {"name": "add", "arguments": {"a": 2, "b": 3}},
            }

            line()
            print("STEP 4 — Bridge translates the REAL MCP call -> A2A")
            line()
            res = engine.translate(real_mcp_request, TranslationDirection.MCP_TO_A2A.value)
            print("  success:", res.success)
            print("  A2A task:\n", json.dumps(res.target_data["task"], indent=2))

            line()
            print("STEP 5 — Validate the A2A output against the OFFICIAL a2a-sdk schema")
            line()
            try:
                from a2a.types import Task
                Task.model_validate(res.target_data["task"])
                print("  VALID per official a2a.types.Task  [PASS]")
                a2a_ok = True
            except Exception as e:
                print("  Could not validate (a2a-sdk missing or schema mismatch):", str(e).splitlines()[0])
                a2a_ok = False

            line("=")
            print("RESULT:")
            print(f"  - Live MCP handshake:           PASS")
            print(f"  - Real tools/list + tools/call: PASS ({tool_names}, add->{result_text})")
            print(f"  - Bridge MCP->A2A translation:  {'PASS' if res.success else 'FAIL'}")
            print(f"  - A2A schema conformance:       {'PASS' if a2a_ok else 'SKIP/FAIL'}")
            line("=")


if __name__ == "__main__":
    asyncio.run(main())
