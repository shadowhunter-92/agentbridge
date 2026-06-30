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
- **Multi-worker safe with a shared store (audit chain + budgets + approvals).** The audit
  hash-chain append, budget reserve/commit/release, AND approval state all run as **atomic,
  store-side operations** — SQLite `BEGIN IMMEDIATE` or Postgres transaction-scoped advisory
  locks. Multiple workers/replicas sharing one SQLite file or a Postgres DB cannot fork the
  chain, double-spend, or double-consume a one-shot approval. Proven by
  `tests/test_concurrency.py`. See `docs/ENTERPRISE.md`.
- **157 passing tests; 159 with a Postgres DB** (6 PG integration tests skip without
  `AGENTBRIDGE_TEST_PG`; 1 conformance test skips without redis) + a one-screen live demo.

### Done in the production-readiness pass

- **Observability (was #1 on the demand-gated list).**
  - `/metrics` Prometheus endpoint: call counter, latency histograms, audit/budget/approval
    gauges, HTTP request metrics, rate-limit + auth-failure counters.
  - OpenTelemetry tracing (optional): gateway spans, lazy-initialized, no-op safe.
  - Structured JSON logging with per-request correlation IDs (`X-Request-ID`).
- **Store-backed `ApprovalQueue` (was #2).** The last piece of in-process runtime state is
  now durable — multi-worker safe with no instance pinning required for approvals.
- **JWKS auto-fetch for OIDC (was #3).** Discover `jwks_uri` from
  `<issuer>/.well-known/openid-configuration`; cache + refresh on `kid` miss. No more
  manual key configuration when the IdP exposes standard discovery.
- **Audit retention + legal hold.** `POST /control/audit/checkpoint` signs the audit head
  with Ed25519 so a third party can later prove the log wasn't truncated.
  `POST /control/audit/retention` truncates old entries (`seq < N`) when no legal hold is
  active. Closes the compliance gap that was previously deferred.
- **Graceful shutdown + split health probes.** `lifespan` handles SIGTERM, drains in-flight
  requests up to `AGENTBRIDGE_SHUTDOWN_GRACE`, then closes. `/health` (liveness) always
  returns 200; `/ready` (readiness) returns 503 during drain or if the store is unreachable.
  K8s probes should use `/ready` for traffic routing and `/health` for restart decisions.
- **Retry/backoff on transient store errors.** SQLite "database is locked" and psycopg
  `OperationalError` are retried with exponential jitter (max 4 attempts, 0.5s cap). Permanent
  errors bubble immediately.
- **Config validation at startup.** `src/config.py` checks env vars before any state is
  created; production deployments must set `AGENTBRIDGE_ADMIN_KEY` and `AGENTBRIDGE_DB` or
  the process exits non-zero with a clear error.

## Known limitations (today)

- **Tool-call focused canonical model.** The mesh maps capability + arguments + text well.
  It does **not** yet carry every protocol-specific feature (e.g. MCP resources/prompts/
  sampling, A2A streaming/push-notifications/status updates, ACP multi-turn sessions).
- **No TLS at the app layer.** Terminate TLS at a reverse proxy or load balancer; don't
  expose the control plane plaintext on a public network (see `docs/DEPLOYMENT.md`).
- **No SIEM push connectors yet** — audit is exported via `GET /control/audit/export`
  (JSONL) and the new signed-checkpoint / retention APIs; turnkey Splunk/Datadog/S3 shippers
  are still a small future addition (demand-gated).
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
  role claim → RBAC role; replaces the shared admin key. **JWKS auto-fetch** now supported
  (was deferred — `<issuer>/.well-known/openid-configuration` discovery + key rotation on
  `kid` miss).
- ✅ **Signed audit checkpoints** — third-party-verifiable proof the log wasn't truncated;
  JSONL export feeds SIEMs (Splunk/Datadog/S3).
- ✅ **Audit retention + legal hold** — `POST /control/audit/retention` truncates by seq or
  freezes truncation; `POST /control/audit/checkpoint` records a signed head before truncation.

Not code — handled honestly (see `docs/ENTERPRISE.md`):

- ⛔ **Managed cloud (SLA hosting)** — operations/business, not a library feature. Self-host
  pieces are all here (Docker, Postgres, rate limiting, TLS-at-proxy, graceful shutdown,
  /ready + /metrics).
- ⛔ **SOC 2 Type II / HIPAA** — independent audits over months, not a code claim. The controls
  above are the technical evidence such an audit examines.

Still genuinely demand-gated:

- **SIEM push connectors** (turnkey Splunk/Datadog/S3 shippers) — small addition; build on
  first real deployment. The plumbing is there (JSONL export + signed checkpoints).

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
found and fixed via that benchmark. The new observability layer (Prometheus + structured
logging) adds <0.1ms per request in our measurements.

## Single point of failure / high availability

As an inline component, AgentBridge is on the call path. Runtime state (audit chain, budgets,
approvals) is now safe across multiple instances **when they share a Postgres DB** (atomic
advisory-locked operations — see above), so you can run replicas behind a load balancer
without diverging budgets/audit/approvals. For full HA you still need operational pieces
that are not code: a managed/replicated Postgres, health checks (`/ready`), and a load
balancer. For a single drop-in MCP server, run it close to the agents and fail over by
restart.

## Planned next (demand-gated)

In rough priority, built when a real use-case or user pulls for it:
1. SIEM push connectors (turnkey Splunk/Datadog/S3 shippers) — the export + checkpoint
   primitives are in place; just needs the pushers.
2. Async / buffered audit writes (queue + flush) if durable-store write latency becomes a
   bottleneck under high call volume.
3. A lightweight web dashboard for the control plane (live audit feed, budgets, pending
   approvals) — the "aha" surface for non-CLI stakeholders.
4. Richer protocol semantics (streaming, resources) where a concrete integration needs it.
5. JWKS-based key rotation callbacks (today: refresh on `kid` miss, which is good enough
   for most IdPs; callback-driven rotation can be added if a customer needs it).
