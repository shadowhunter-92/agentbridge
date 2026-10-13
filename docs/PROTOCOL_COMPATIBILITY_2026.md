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

## Release-scoped failure semantics matrix (not full conformance)

| Input path | In scope | Required behavior if outside scope |
|---|---|---|
| MCP stdio `tools/call` simple JSON argument map | Real SDK message validation and live add-tool example | Invalid or unavailable tool must produce an error; no implicit arbitrary fallback |
| MCP `resources/read`, `prompts/get`, sampling, notification, cancellation, session control | Not part of canonical action subset | Adapter rejects unsupported procedures; it MUST NOT convert them to tool actions |
| MCP Streamable HTTP session, auth, resumability | Unqualified | No conformance claim until official transport-level tests |
| A2A `Task` data schema from pinned 0.3.x SDK | Limited translation | Unknown task lifecycle, streaming, cancellation and notifications are unqualified |
| A2A 1.0 full interoperable service | Not qualified | Do not claim 1.0 support based on 0.3.x model validation |

Every supported protocol upgrade needs a pinned SDK family, a live reference
server/client test, expected error paths and explicit mapping of behaviors
that cannot be preserved across source/destination protocols. Test of model
parsing alone is not a protocol certificate.

## Standalone MCP gateway outbound execution gate (October 13 security update)

The drop-in `src.serve.mcp_gateway` exposes two outbound tools (`bridge_call_a2a`, `bridge_call_acp`). These tools now **deny remote execution by default** and require the deployment operator to set `AGENTBRIDGE_MCP_TARGET_ALLOWLIST_JSON` to a JSON list of exactly approved HTTPS origins and `AGENTBRIDGE_EGRESS_PROXY_URL` to the independently restricted outbound proxy. Example for a synthetic approved test only:

```bash
export AGENTBRIDGE_MCP_TARGET_ALLOWLIST_JSON='["https://trusted-agent.example"]'
export AGENTBRIDGE_EGRESS_PROXY_URL='http://approved-egress-proxy:3128'
```

The client cannot supply its own proxy or add targets; alternate local origins, URL credentials, arbitrary paths, query strings, IP literals and unknown destinations fail before transport. **An allowlist and configured proxy are not sufficient proof of workload identity, DNS/IP re-resolution safety or non-bypassable CNI egress.** Operators must independently verify the proxy and cluster network boundary. The developer CLI `AgentClient` remains an explicitly non-governed direct transport tool and is **not** approved for consequential actions.

The narrow A2A adapter now rejects unknown JSON-RPC procedures and malformed lifecycle statuses, rather than treating them as new actions. Its allowed legacy method subset is `tasks/send` only, not current A2A 1.0 full conformance.

## Non-executable A2A lifecycle model (experimental)

`src/protocols/task_lifecycle.py` adds a typed snapshot and monotonic transition model separate from `CanonicalCall`. Its transitions deny stale sequence numbers, terminal-task resurrection and unknown states. Snapshots are **not** executable instructions; parsing them never issues tool calls. This does **not** implement A2A streaming, notification delivery, server-owned sequencing, task persistence, stateful resumption, subscriptions or full A2A conformance. The caller must enforce durable atomic sequence transitions and authorize external effects separately. Run `python -m pytest tests/test_task_lifecycle.py -q` to evaluate this bounded contract.
