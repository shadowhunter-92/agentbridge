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

## The enterprise tier — built on first enterprise ask (NOT before)

The commercial/enterprise features below are real and on the roadmap, but they are
deliberately **not built yet**, because the right trigger is a buyer saying "I won't deploy
without X" — not speculation. Building an SSO/RBAC/SOC2 stack before a paying design partner
is the classic feature-creep trap. Each is scoped and ready to start the moment a real
enterprise conversation requires it:

- **SSO / SAML / OIDC** for operator login (Okta, Azure AD) — replaces the static admin key.
- **RBAC** for who can manage which agents' identities/budgets/approvals.
- **Immutable audit export** to SIEMs (Splunk, Datadog, S3) with signed checkpoints + retention.
- **Managed cloud** (hosted, SLA-backed) so customers don't run the Postgres/Redis themselves.
- **SOC 2 Type II / HIPAA** for the hosted offering (unlocks finance/health buyers).
- **Policy engine v2** — declarative rules (e.g. "human approval for any tool call > $5",
  "no external calls outside business hours"). Primitives (allowlist, budgets, approvals) exist.

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

## Performance

Measured in-process overhead is in `docs/BENCHMARKS.md` (reproduce with
`tools/benchmark.py`): translation is tens of microseconds; a full governed + audited call
is sub-millisecond in-memory — typically well under 1% of a networked agent call. A real
O(n²) hot-path bug in the rate-limiter (it rebuilt its recent-calls list every call) was
found and fixed via that benchmark.

## Single point of failure / high availability

As an inline component, AgentBridge is on the call path. Today it runs best as a single
instance (or as a per-developer drop-in MCP server). True multi-instance HA behind a load
balancer needs shared *runtime* state (below) so budgets/approvals don't diverge across
replicas. Until then: run it close to the agents, monitor it, and fail over by restart.

## Planned next (demand-gated)

In rough priority, built when a real use-case or user pulls for it:
1. Observability (OpenTelemetry traces + metrics) once running real traffic.
2. OAuth/OIDC operator SSO for enterprise deployments.
3. Shared runtime state (Redis / Postgres advisory locks) for true horizontal scaling + HA.
4. Async / buffered audit writes (queue + flush) if durable-store write latency becomes a
   bottleneck under high call volume.
5. A lightweight web dashboard for the control plane (live audit feed, budgets, pending
   approvals) — the "aha" surface for non-CLI stakeholders.
6. One-command `docker-compose` quickstart with mock agents (sub-60s time-to-first-demo).
7. Richer protocol semantics (streaming, resources) where a concrete integration needs it.
8. Audit-grade compliance features (signed checkpoints, retention, auditor export).
