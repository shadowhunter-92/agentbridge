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
- **Multi-worker safe with a shared store (audit chain + budgets).** The audit hash-chain
  append and budget reserve/commit/release run as **atomic, store-side operations**
  (`store.append_audit_chained` / `store.mutate_budget`) — SQLite `BEGIN IMMEDIATE` or Postgres
  transaction-scoped advisory locks. Multiple workers/replicas sharing one SQLite file or a
  Postgres DB cannot fork the chain or double-spend. Proven by `tests/test_concurrency.py`
  (separate store connections + threads simulate separate processes). See `docs/ENTERPRISE.md`.
- **153 passing tests; 159 with a Postgres DB** (6 Postgres integration tests — incl. real
  multi-worker concurrency — skip without `AGENTBRIDGE_TEST_PG`) + a one-screen live demo.

## Known limitations (today)

- **Tool-call focused canonical model.** The mesh maps capability + arguments + text well.
  It does **not** yet carry every protocol-specific feature (e.g. MCP resources/prompts/
  sampling, A2A streaming/push-notifications/status updates, ACP multi-turn sessions).
- **Multi-worker needs a shared durable store (not in-memory).** The cross-worker safety above
  holds **only** when workers share a SqliteStore file or PostgresStore (`AGENTBRIDGE_DB`). The
  default `InMemoryStore` is per-process and is for single-worker/dev only — running multiple
  workers on the in-memory store would still fork state. Set `AGENTBRIDGE_DB` to a SQLite path
  (single node) or a `postgres://` URL (multi-node) before scaling horizontally.
- **No TLS at the app layer.** Terminate TLS at a reverse proxy or load balancer; don't
  expose the control plane plaintext on a public network (see `docs/DEPLOYMENT.md`).
- **No metrics/tracing yet** — no OpenTelemetry/Prometheus export.
- **Postgres backend** — verified against real `postgres:16` (identity/budget/audit roundtrips
  **and** the multi-worker advisory-lock concurrency path; `tests/test_postgres_store.py`, 6
  tests). Still validate against *your* managed Postgres before production reliance
  (set `AGENTBRIDGE_TEST_PG`).

## The enterprise tier

Built (real, tested code — see `docs/ENTERPRISE.md` + `tests/test_enterprise_governance.py`):

- ✅ **Policy engine v2** — declarative rules (per-call cost cap, approval-above-cost,
  capability allow/deny, business-hours-only, blocked protocol routes).
- ✅ **RBAC** — operator roles (admin/operator/viewer) → permissions.
- ✅ **OIDC / JWT operator auth (SSO)** — verify IdP tokens (Okta/Azure AD/Auth0/Keycloak),
  role claim → RBAC role; replaces the shared admin key. (`pyjwt`, lazy import.)
- ✅ **Signed audit checkpoints** — third-party-verifiable proof the log wasn't truncated;
  JSONL export feeds SIEMs (Splunk/Datadog/S3).

Not code — handled honestly (see `docs/ENTERPRISE.md`):

- ⛔ **Managed cloud (SLA hosting)** — operations/business, not a library feature. Self-host
  pieces are all here (Docker, Postgres, rate limiting, TLS-at-proxy).
- ⛔ **SOC 2 Type II / HIPAA** — independent audits over months, not a code claim. The controls
  above are the technical evidence such an audit examines.

Still genuinely demand-gated:

- **SIEM push connectors** (turnkey Splunk/Datadog/S3 shippers) and **JWKS auto-fetch** for
  OIDC (today: configure the IdP key) — small additions, build on first real deployment.

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

As an inline component, AgentBridge is on the call path. Runtime state (audit chain, budgets)
is now safe across multiple instances **when they share a Postgres DB** (atomic advisory-locked
operations — see above), so you can run replicas behind a load balancer without diverging
budgets/audit. What's left for full HA is operational, not code: a managed/replicated Postgres,
health checks, and a load balancer. Approvals (`ApprovalQueue`) are still in-process and not yet
store-backed — route approval traffic to one instance or pin it until that's persisted (tracked
below). For a single drop-in MCP server, run it close to the agents and fail over by restart.

## Planned next (demand-gated)

In rough priority, built when a real use-case or user pulls for it:
1. Observability (OpenTelemetry traces + metrics) once running real traffic.
2. Store-back the `ApprovalQueue` (same `mutate`-style atomic pattern as budgets) so the
   *last* piece of in-process runtime state becomes multi-worker safe.
3. Async / buffered audit writes (queue + flush) if durable-store write latency becomes a
   bottleneck under high call volume.
4. A lightweight web dashboard for the control plane (live audit feed, budgets, pending
   approvals) — the "aha" surface for non-CLI stakeholders.
5. One-command `docker-compose` quickstart with mock agents (sub-60s time-to-first-demo).
6. Richer protocol semantics (streaming, resources) where a concrete integration needs it.
7. Retention policies / legal hold for the audit log (the remaining compliance gap).
