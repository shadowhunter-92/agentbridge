# Protocol Support Matrix — the Meta-Bridge

**Date:** 2026-06-06
**Architecture:** canonical hub-and-spoke (`src/protocols/`). Every protocol maps to ONE
canonical model (`CanonicalCall` / `CanonicalResult`), so any-to-any translation is automatic and
adding a protocol is O(1) — write one adapter, get translation to/from every existing protocol for
free. No N² pairwise mappings.

## Support & test rigor

| Protocol | Adapter | Conformance vs **real official SDK** | Any-to-any | Live agent + in-line proxy | Notes |
|---|:---:|:---:|:---:|:---:|---|
| **MCP** (Anthropic) | ✅ | ✅ `mcp` 1.27 (`CallToolRequestParams`) | ✅ | ✅ real FastMCP server (stdio), `add`/`echo` | full |
| **A2A** (Google/LF, JSON-RPC) | ✅ | ✅ `a2a-sdk` 0.3 (`Task`, `Message`) | ✅ | ✅ real uvicorn agent, AgentCard + `message/send` | full |
| **ACP** (IBM/BeeAI/LF) | ✅ | ✅ `acp-sdk` 1.0 (`RunCreateRequest`, `Run`, `Message`) | ✅ | ✅ real REST `/runs` agent* | full* |
| **OpenAI function-calling** | ✅ | ✅ `openai` 2.x (`ChatCompletionMessageToolCall`) | ✅ | ✅ routed to live MCP/ACP agents | de-facto tool format |
| **Gemini function-calling** | ✅ | ✅ `google-genai` (`FunctionCall`, `FunctionResponse`) | ✅ | ✅ routed to live MCP tool | `args` is an object (not a JSON string) |
| **AGNTCY ACP** (Cisco AGNTCY) | ✅ | ✅ `agntcy-acp` (`RunCreateStateless`, `MessageTextBlock`) | ✅ | ✅ routed to live MCP tool | LangGraph-style run-create |
| **ANP** (Agent Network Protocol) | ⛔ deferred → governance | — | — | — | identity layer, see below + `GOVERNANCE.md` |

**6 call protocols live + rigorously tested.** Any-to-any matrix = **6×6 = 36 pairs**, all green.
Adding the 7th is one adapter file + one registry line + one conformance case.

`*` acp-sdk 1.0.3's bundled `Server` class is broken against current uvicorn (references removed
`uvicorn.config` symbols), so the live ACP agent (`examples/acp_server_agent.py`) serves the real
ACP REST shape with FastAPI while **validating every request/response against the official
`acp_sdk.models`**. The wire bytes are real ACP; only the SDK's server wrapper is bypassed.

## Proven live, end-to-end (real agents on both ends)
`examples/live_nprotocol_proxy.py` (all PASS):
- OpenAI tool-call → bridge → **live MCP `add` tool** → OpenAI result (`5`)
- ACP run request → bridge → **live MCP `add` tool** → ACP message (`5`)
- MCP `tools/call` → bridge → **live ACP echo agent** → MCP result (`echo: through the mesh`)

Plus the original A2A live handshakes (`examples/live_mcp_handshake.py`, `live_a2a_handshake.py`,
`live_inline_proxy.py`).

## Tests
- `tests/test_protocols_conformance.py` — each adapter's output validated against the real SDK
  type, **plus a full 6×6 any-to-any matrix** (36 pairs) proving intent survives every hop.
- `tests/test_nprotocol_live.py` — every source protocol (mcp/a2a/acp/openai/gemini/agntcy) routed
  to a **live** MCP tool, asserting it really computed 5.
- `tests/test_real_conformance.py`, `tests/test_inline_proxy.py` — MCP/A2A real-SDK + live proxy.
- `tests/test_concurrency.py` — multi-worker safety on SQLite: separate store connections +
  threads (a stand-in for separate processes) prove the audit chain doesn't fork and budgets
  don't double-spend on a shared store.
- `tests/test_postgres_store.py` — the same atomic ops on **real Postgres** (advisory-lock path),
  incl. 2 multi-connection concurrency tests; verified against `postgres:16`.
- Full suite: **150 passing; 156 with a Postgres DB** (6 Postgres integration tests skip without
  `AGENTBRIDGE_TEST_PG`).

## ANP — why it's deferred (and where it belongs)
ANP (`agent-connect`) is not a tool-call/message protocol like the others — it's an **identity +
discovery + transport-negotiation layer**: DID-based identity, end-to-end encryption, and a
"meta-protocol" negotiation step (`anp_crawler`, `authentication`, `e2e_encryption`,
`meta_protocol`). It doesn't map onto `CanonicalCall` (invoke a capability) without distortion.
Forcing an adapter would be fake. ANP instead informs the **trust/governance plane**
(identity/verification) — i.e. the meta-bridge's moat — and will be picked up there, not as a
call-translation adapter. Documented honestly rather than checkbox-faked.

## Adding the next protocol (recipe)
1. Add `src/protocols/<name>.py` implementing `ProtocolAdapter` (4 methods to/from canonical).
2. Register it in `src/protocols/registry.py`.
3. Add a conformance case in `tests/test_protocols_conformance.py` validating against its real SDK
   type; the any-to-any matrix picks it up automatically.
4. If it has a runnable server, add `examples/<name>_server_agent.py` + a live route.
