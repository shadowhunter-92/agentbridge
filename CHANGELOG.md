# Changelog

All notable changes to AgentBridge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — production-readiness pass

### Added — observability
- **Prometheus metrics** at `/metrics`: call counter (`agentbridge_calls_total{src,dst,capability,decision}`),
  call latency histogram (`agentbridge_call_duration_seconds`), translation latency histogram
  (`agentbridge_translate_duration_seconds`), audit-entry gauge, per-agent budget gauges,
  pending-approvals gauge, HTTP request counter + duration histogram, rate-limit-hit counter,
  auth-failure counter. Uses a private `CollectorRegistry` so it never collides with other libs.
- **OpenTelemetry tracing** (optional): set `OTEL_EXPORTER_OTLP_ENDPOINT` or
  `AGENTBRIDGE_OTEL_ENABLED=1` to ship spans. The governance gateway opens a span around
  `route_call` with `agent_id`/`src`/`dst`/`cost` attributes. Lazy-initialized, no-op safe
  when the OTel SDK isn't installed.
- **Structured JSON logging** (`AGENTBRIDGE_LOG_JSON=1`, on by default in production / k8s):
  one JSON object per line with `ts`, `level`, `logger`, `msg`, `request_id`, plus any
  `extra=` fields. Plain-text fallback for dev.
- **Correlation IDs**: every request gets an `X-Request-ID` (echoed in the response), and
  the log formatter picks it up via a `ContextVar`. Slow-request warnings logged above
  `AGENTBRIDGE_SLOW_LOG_SECONDS` (default 2s).

### Added — reliability
- **Graceful shutdown**: `lifespan` installs SIGTERM/SIGINT handlers that flip readiness
  to False, drain in-flight requests up to `AGENTBRIDGE_SHUTDOWN_GRACE` (default 10s),
  then close. The CLI passes the same value to uvicorn's `--timeout-graceful-shutdown`.
- **Split health probes**:
  - `/health` — liveness (always 200, even during drain, so k8s doesn't restart the pod mid-shutdown).
  - `/ready`  — readiness (503 during drain OR if the governance store is unreachable).
- **`/version`** endpoint (build + Python + store type).
- **Retry with backoff** on transient store errors: `append_audit_chained` and
  `mutate_budget` now retry on SQLite `database is locked` / psycopg `OperationalError`
  (up to 4 attempts, exponential + jitter, capped at 0.5s). Permanent errors bubble immediately.
- **Store-backed `ApprovalQueue`**: approvals now live in the durable store (InMemoryStore
  for tests, SQLite/Postgres in prod) instead of in-process state. Multi-worker safe —
  the last piece of in-process runtime state is gone. Atomic `approved -> consumed`
  transition via `consume_approval` so two workers can't double-consume a one-shot grant.
- **JWKS auto-fetch for OIDC**: when no static signing key is configured, the verifier
  fetches `<issuer>/.well-known/openid-configuration` to discover `jwks_uri`, then
  fetches + caches JWKS keys (TTL 15min, refresh on `kid` miss). Explicit
  `AGENTBRIDGE_OIDC_JWKS_URL` also supported.
- **Config validation at startup** (`src/config.py`): checks env vars before any state is
  created. Production requires `AGENTBRIDGE_ADMIN_KEY` and `AGENTBRIDGE_DB`; rate-limit
  and shutdown-grace values are range-checked; OIDC issuer must be a URL; psycopg must be
  importable when a postgres URL is configured. Errors raise `ConfigError` (fail-fast at boot).
- **Audit retention + legal hold**:
  - `POST /control/audit/checkpoint` — sign the current audit head with Ed25519 so a third
    party can later prove the log wasn't truncated before this point.
  - `POST /control/audit/retention` — `{"action":"truncate","seq":N}` removes entries with
    `seq < N`; `{"action":"legal_hold","on":true}` freezes truncation (returns 409 on
    subsequent truncation attempts). Backed by `store.truncate_audit_before` (InMemory/SQLite/Postgres).
- **CLI `serve` improvements**: `--workers N`, `--log-level`, disables uvicorn's noisy
  access log (we have our own structured middleware), passes graceful-shutdown timeout
  through to uvicorn.

### Added — production safety
- FastAPI docs (`/docs`, `/redoc`) are suppressed when `AGENTBRIDGE_ENV=production`
  unless `AGENTBRIDGE_DOCS=1` is set.
- Warnings emitted (not just logged) when admin key is missing/short, when in-memory
  store is used, when OIDC has no signing key configured.

### Tests
- `tests/test_production_readiness.py` — 21 new tests covering: store-backed approvals,
  audit retention + legal hold + checkpoint signing, Prometheus metrics rendering,
  structured JSON logging, config validation (5 scenarios), retry/backoff (3 scenarios),
  `/health` + `/ready` + `/version` + `/metrics` endpoints, request-ID echo, full
  audit-retention HTTP round-trip.

  Suite total: **157 passing, 7 skipped** (was 136; +21). Skips are the 6 Postgres
  integration tests (need `AGENTBRIDGE_TEST_PG`) and 1 conformance test that needs redis.

### Changed
- `pyproject.toml`: added `prometheus-client>=0.20.0` as a runtime dependency; added
  `[otel]` optional extra (`opentelemetry-sdk`, OTLP exporter, FastAPI instrumentation).

## [1.0.0]

### Added
- 6-protocol any-to-any mesh: MCP, A2A, ACP, OpenAI, Gemini, AGNTCY — conformance-tested vs the real SDKs.
- Canonical hub-and-spoke translation model (no N² pairwise mappings).
- Governance plane: Ed25519 agent identities, per-agent budgets, human-in-the-loop approvals, tamper-evident hash-chained audit.
- Policy engine v2: declarative rules (cost caps, capability allow/deny, business hours, route blocking).
- RBAC for operators (admin/operator/viewer); OIDC/JWT operator SSO.
- Control-plane HTTP API (FastAPI) with OpenAPI docs; drop-in MCP server packaging; in-line proxy.
- Framework integration helpers (LangChain, CrewAI, AutoGen, LlamaIndex).
- Multi-worker concurrency safety: atomic audit-chain + budget operations on a shared store (SQLite/Postgres).
- 153 passing tests (159 with a Postgres DB).
