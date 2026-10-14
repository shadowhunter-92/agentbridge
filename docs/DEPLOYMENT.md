# Deployment Guide

> **Production target restriction:** HTTP named-target execution is disabled for
> generic MCP/A2A/ACP transports in `prod` and `production` until destination-atomic
> authority/fencing is qualified. Translation and nonproduction synthetic evaluation
> remain available. See [destination contract](PRODUCTION_TARGET_QUALIFICATION_2026-10-14.md).

AgentBridge ships two run surfaces from one codebase:

1. **Control plane** (HTTP API) — the mesh + governance, for operators and agents.
2. **Drop-in MCP server** (stdio) — point any MCP client at it to reach other protocols.

This guide covers running both, configuration, persistence backends, and a hardening
checklist. It is intentionally honest about what is and isn't production-grade yet.

---

## 1. Run locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # Windows; use bin/ on macOS/Linux

# Control plane (mesh + governance) — docs at http://localhost:8000/docs
uvicorn src.api.control_plane:app --host 127.0.0.1 --port 8000

# OR the drop-in MCP server (stdio)
python -m src.serve.mcp_gateway
```

## 2. Run with Docker

Set a unique `AGENTBRIDGE_ADMIN_KEY` in the current process or private environment
file, then run `docker compose up --build`. Root Compose binds loopback and uses
its named-volume SQLite store. The hardened PostgreSQL reference is
`docker-compose.release.yml`; its image installs the hash-locked PostgreSQL
supplemental graph. It starts in production configuration mode for acceptance
checks, which does not authorize consequential actions.

The core package/image provides translation, HTTP governance and Evidence.
Install the `[mcp]` extra for the stdio server and packaged synthetic demos;
install `[transports]` for live MCP/A2A/ACP dispatch. Configured targets whose SDK
is absent fail startup before a request can reserve budget.
The supplied minimal review image does not include optional protocol SDKs;
qualify and hash-lock any custom transport-enabled image separately.

## 3. Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` / `HOST` | `8000` / `0.0.0.0` | Used by `main.py`; Docker CMD fixes port 8000, CLI uses its flags |
| `AGENTBRIDGE_ADMIN_KEY` | auto-generated (logged) | Operator key for `X-Admin-Key` (role: admin). **Set this in production.** |
| `AGENTBRIDGE_DB` | unset (in-memory) | Persistence target — see §4 |
| `AGENTBRIDGE_RATE_LIMIT` | `240` | Max requests/min/IP to `/control/*` (blunts admin-key brute force) |
| `AGENTBRIDGE_OIDC_ISSUER` | unset (OIDC off) | Enable OIDC operator SSO: your IdP issuer URL |
| `AGENTBRIDGE_OIDC_AUDIENCE` | `agentbridge` | Expected `aud` claim |
| `AGENTBRIDGE_OIDC_PUBLIC_KEY_PEM` / `_FILE` | unset | IdP signing public key (inline PEM or file path) |
| `AGENTBRIDGE_OIDC_ROLE_CLAIM` | `role` | Token claim mapped to the RBAC role (admin/operator/viewer) |

## 4. Persistence backends

Chosen automatically from `AGENTBRIDGE_DB` via `make_store()`:

| `AGENTBRIDGE_DB` value | Backend | Use when |
|------------------------|---------|----------|
| *(unset)* | In-memory | Dev / tests. Lost on restart. |
| `/path/to/governance.db` | SQLite | Single node, durable across restarts. |
| `postgresql://user:pass@host/db` | Postgres | Multi-instance / horizontally-scaled control planes. Needs `pip install "psycopg[binary]"`. |

> The Postgres backend mirrors the SQLite one behind the same interface and is **verified
> against real `postgres:16`** — including the multi-worker advisory-lock concurrency path
> (`tests/test_postgres_store.py`, 6 tests). Still validate against *your* managed Postgres
> before relying on it: set `AGENTBRIDGE_TEST_PG` and run `pytest tests/test_postgres_store.py`.

### Workers & scaling

The audit-chain append and budget reserve/commit are **atomic store-side operations**, so you
can run multiple workers/replicas **as long as they share a durable store**:

```bash
# Multiple workers, single node — share one SQLite file:
AGENTBRIDGE_DB=/var/lib/agentbridge/governance.db uvicorn src.api.control_plane:app --workers 4

# Multiple replicas behind a load balancer — share one Postgres:
AGENTBRIDGE_DB=postgresql://user:pass@host/db uvicorn src.api.control_plane:app --workers 4
```

The chain can't fork and budgets can't double-spend across workers (proven by
`tests/test_concurrency.py`). **Do not** run `--workers > 1` on the default in-memory store —
each worker would keep its own state. Current approvals and policy are durable;
shared SQL transactions do not by themselves establish split-brain-safe HA. See `docs/ENTERPRISE.md` → *Concurrency & scaling*.

## 5. Security model (what's enforced today)

- **Operator endpoints** require `X-Admin-Key`.
- **Agent endpoints** (`/control/route`, `/control/authorize`) require Ed25519 **signed
  requests**: `X-Agent-Id`, `X-Nonce`, `X-Signature`, with nonce-replay protection.
- **Rate limiting** on `/control/*` per client IP.
- **Audit** is hash-chained and tamper-evident; export via `/control/audit/export`.

## 6. Honest production checklist (not all done yet)

- [x] Admin-key auth on operator endpoints
- [x] Signed agent requests + nonce replay protection
- [x] Durable persistence (SQLite; Postgres for multi-instance)
- [x] Per-IP rate limiting on the control plane
- [x] Tamper-evident, exportable audit log
- [ ] **TLS** — terminate at a reverse proxy (nginx/Caddy) or a load balancer; do not
      expose the control plane plaintext on a public network.
- [x] **OIDC operator SSO + RBAC** (Okta/Azure AD/Auth0) — set the `AGENTBRIDGE_OIDC_*`
      env vars; role claim maps to admin/operator/viewer.
- [x] **Metrics/tracing** — Prometheus `/metrics` and optional OpenTelemetry exist; operator telemetry acceptance remains separate.
- [ ] A formal security review before handling regulated production traffic.

See `docs/ROADMAP_AND_MONETIZATION.md` for what's gated on demand vs. built next.


## Deployment acceptance

This is not authorization for consequential live actions. Bounded local/CI and
AWS replication, promotion and rollback evidence exists. Automated split-brain
safety, independent custody, external destination enforcement and production SLOs
remain unaccepted. See [current acceptance](CURRENT_STATUS_2026-10-13.md).

Root Compose now requires `AGENTBRIDGE_ADMIN_KEY` explicitly and binds loopback.
Generate a unique local secret in the current process, then run Compose:

```powershell
$env:AGENTBRIDGE_ADMIN_KEY = python -c "import secrets; print(secrets.token_hex(32))"
docker compose up --build
```

The compatibility file under `docker/` extends that same SQLite evaluation
service; its former Redis declarations did not persist governance state.
The hardened PostgreSQL specimen is `docker-compose.release.yml`. It is a
separate staging topology and requires external configuration and network review.
The Kubernetes worker/proxy NetworkPolicy specimen and HTTP deployment use
different roles and selectors; see [Kubernetes guide](../k8s/README.md).

OIDC JWKS removal takes effect after the configured cache TTL and successful
refresh; a brief global refresh cooldown bounds unknown-kid traffic. Expired
keys fail closed during issuer outages. Authentication I/O runs off the event
loop. Configure issuer keys, TLS and retention according to your deployment's
security requirements.

## Bounded routing telemetry

Unknown protocol identifiers are rejected before governance admission. The shared
metric consumer maps custom/unknown protocol names and unknown decisions to
`<other>`; custom execution registries remain usable. Capability metrics retain
at most 128 distinct names of at most 128 characters per process, then aggregate
overflow into `<other>`. These metric limits are not tenant or execution quotas.
