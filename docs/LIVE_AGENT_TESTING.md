# Live Agent Testing — agentbridge2

**Date:** 2026-06-06
**Goal:** Move beyond mocks. Prove the bridge works against *real, running* MCP and A2A
agents using the official SDKs, and that its translations conform to the real schemas.

## TL;DR
| Test | Result |
|---|---|
| Live MCP agent handshake (real subprocess, stdio) | ✅ PASS |
| Real MCP `initialize` / `tools/list` / `tools/call` | ✅ PASS (`add`→5, tools `['add','echo']`) |
| Bridge MCP→A2A on the real call, validated vs official `a2a.types.Task` | ✅ PASS |
| Live A2A agent handshake (real uvicorn HTTP server) | ✅ PASS |
| Real A2A AgentCard discovery + `message/send` | ✅ PASS (agent replied "echo: hello from the bridge") |
| Bridge A2A→MCP on the real message, validated vs official `mcp.types` | ✅ PASS |
| Full test suite (incl. real-SDK conformance) | ✅ 128 passing |

## How to reproduce
```bash
cd "agent-bridge"
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python examples/live_mcp_handshake.py     # real MCP agent end-to-end
.venv/Scripts/python examples/live_a2a_handshake.py     # real A2A agent end-to-end
.venv/Scripts/python -m pytest tests/ -q                # 75 passed
```

## What each example does
- `examples/mcp_server_agent.py` — a real MCP agent (FastMCP) with `add` and `echo` tools, stdio.
- `examples/live_mcp_handshake.py` — spawns it as a subprocess, does a real MCP handshake,
  then runs the real `tools/call` through the bridge and validates the A2A output.
- `examples/a2a_server_agent.py` — a real A2A agent (a2a-sdk, JSON-RPC) served by uvicorn,
  exposing an `echo` skill and an AgentCard at `/.well-known/agent-card.json`.
- `examples/live_a2a_handshake.py` — starts it, fetches the AgentCard, sends a real
  `message/send`, then runs the real A2A message through the bridge and validates the MCP output.

## SDK versions used
- `mcp` 1.27.x (Anthropic, official)
- `a2a-sdk` 0.3.26 — the 0.3.x line ships the **JSON-RPC pydantic types** we target. (a2a-sdk
  1.x switched to protobuf/gRPC — see `PROTOBUF_A2A.md`.)

## Honest limitation (important)
These tests prove two things:
1. The bridge can **stand up and complete a real handshake** with live MCP and A2A agents.
2. The bridge's **translation output conforms** to the *other* protocol's official schema.

They do **NOT** yet prove a single continuous in-line proxy flow — i.e. Agent A (MCP) calling
*through* the bridge which then invokes Agent B (A2A) live and returns the result in one pipe.
That requires the bridge's routing/forwarding layer to embed **real MCP (stdio/Streamable-HTTP)
and A2A (HTTP/JSON-RPC) transport clients**. Today the forwarding layer (`/forward/*`) does plain
HTTP POST, which is not how a real MCP server is invoked. Building the real in-line proxy is the
next engineering step IF the project continues (see DEMAND_VALIDATION.md before investing).
