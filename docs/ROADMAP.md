# Roadmap & Known Limitations (honest)

AgentBridge is an early-stage working prototype. This page is deliberately candid about
what's done, what's a known limitation, and what's intentionally deferred — so you can
judge whether it fits your use case before relying on it.

---

## Done (verified)

- **6-protocol any-to-any mesh** — MCP, A2A, ACP, OpenAI & Gemini function-calling,
  AGNTCY ACP — through one canonical model; each adapter conformance-tested against the
  protocol's real official SDK.
- **In-line proxy** across live agents on different protocols.
- **Governance in the call path** — Ed25519 agent identity (signed requests + nonce
  replay protection), per-agent spend/rate budgets (atomic reserve/commit), human-in-the-loop
  approvals, and a hash-chained tamper-evident audit log.
- **Input validation** — adapters fail loudly (`MalformedWireError`) on malformed wire.
- **Persistence** — in-memory / SQLite (single node) / **Postgres** (multi-instance), one
  interface, chosen via `AGENTBRIDGE_DB`.
- **Control plane** — authenticated HTTP API + **per-IP rate limiting** on `/control/*`.
- **Drop-in MCP server** packaging.
- **124 passing tests** + a one-screen live demo.

## Known limitations (today)

- **Tool-call focused canonical model.** The mesh maps capability + arguments + text well.
  It does **not** yet carry every protocol-specific feature (e.g. MCP resources/prompts/
  sampling, A2A streaming/push-notifications/status updates, ACP multi-turn sessions).
- **Runtime state is in-memory in the gateway.** Postgres shares *persistence* across
  instances, but the `BudgetManager`/`ApprovalQueue` hold *live* state in-process — true
  multi-instance horizontal scaling needs shared runtime state (Redis/Postgres advisory
  locks). Single-instance deployments are unaffected.
- **No TLS at the app layer.** Terminate TLS at a reverse proxy or load balancer; don't
  expose the control plane plaintext on a public network (see `docs/DEPLOYMENT.md`).
- **No OAuth/OIDC for operators yet** — operator auth is an admin key today.
- **No metrics/tracing yet** — no OpenTelemetry/Prometheus export.
- **Postgres backend is new** — validate against a throwaway DB (`AGENTBRIDGE_TEST_PG`)
  before production reliance.

## Deferred on purpose (and why)

- **ANP (Agent Network Protocol).** Not a tool-call/message protocol like the other six —
  it's an identity + discovery + transport-negotiation layer. Forcing it in as a 7th
  call-translation adapter would distort it. The right home is the identity/discovery plane
  (DID-based discovery), which is a separate, larger effort — see `docs/PROTOCOL_SUPPORT.md`.
- **Engine/mesh consolidation.** The in-line proxy still uses the older `src/engine`
  translator; the canonical `src/protocols` mesh is the real one. Consolidating changes the
  proxy's wire bytes and must be re-validated against the live handshakes — low user impact,
  done on a branch rather than rushed.
- **Frameworks (LangChain/CrewAI/AutoGen)** are not wire protocols; they already emit
  OpenAI/MCP-shaped calls the bridge handles. No adapter needed.
- **Protobuf/gRPC A2A transport** — see `docs/PROTOBUF_A2A.md`; added when a real
  counterparty requires it.

## Planned next (demand-gated)

In rough priority, built when a real use-case or user pulls for it:
1. Observability (OpenTelemetry traces + metrics) once running real traffic.
2. OAuth/OIDC operator SSO for enterprise deployments.
3. Shared runtime state for true horizontal scaling.
4. Richer protocol semantics (streaming, resources) where a concrete integration needs it.
5. Audit-grade compliance features (signed checkpoints, retention, auditor export).
