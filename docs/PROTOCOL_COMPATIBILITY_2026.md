# AgentBridge protocol compatibility contract — October 2026

**Status: limited validated wire-shape subset; NOT complete protocol conformance.**

The adapter tests exercise message/tool-call translation, schema parsing and a 6 x 6
canonical call matrix using the repository-pinned SDK families. A successful
translation does **not** establish compliance with every feature of the modern
MCP or A2A specifications.

| Surface | Demonstrated subset | Not certified/supported as a general guarantee |
|---|---|---|
| MCP | `tools/call` parameter serialization/interpretation, stdio client tests | Latest HTTP transport session semantics, negotiated extensions, resources, prompts, elicitation, sampling, cancellation, error lifecycle, streaming |
| A2A | JSON-RPC message/task wire types against pinned `a2a-sdk 0.3.x`, limited live agent exchanges | A2A 1.0 general conformance, lifecycle, task state transitions, streaming, push notifications, authentication negotiation |
| BeeAI ACP | Limited run and message schemas | Full server runtime lifecycle and compatibility across ACP SDK revisions |
| OpenAI tools | Chat tool-call function payload | Broader API format, streaming and agent control flow |
| Gemini tools | FunctionCall/FunctionResponse shape | Full model streaming and tool lifecycle |
| AGNTCY ACP | Selected `RunCreateStateless` and message shapes | Full network interoperability or transport/security compliance |

## Source-of-truth tests

- `tests/test_protocols_conformance.py`: narrow official SDK schema checks and 36 call-route intent-preservation assertions.
- `tests/test_real_conformance.py`: MCP/A2A SDK model checks with the pinned SDK family.
- `tests/test_protocol_scope.py`: enforce that the published subset is synchronized with registered adapters.
- `tests/test_nprotocol_live.py`: selected live test-server examples, not complete production compatibility certification.

## Release policy

Do not advertise "MCP 2026-07-28 compliant" or "A2A 1.0 compliant" until an official current-version conformance run covers the claimed subset and negative/cross-version transport behaviors. Version upgrades must be done on a separate branch with SDK smoke tests and verified protocol semantics; changing dependency ranges without testing is not evidence. Preserve unexpected fields only when safe and explicit, and fail closed when important semantics cannot be represented in the canonical model.

The first supported customer-facing evaluation should be **synthetic/read-only MCP stdio tools/call bridging**. Features above that scope are research/compatibility backlog.
