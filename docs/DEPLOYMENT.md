# Deployment Guide

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
uvicorn src.api.control_plane:app --host 0.0.0.0 --port 8000

# OR the drop-in MCP server (stdio)
python -m src.serve.mcp_gateway
```

## 2. Run with Docker

```bash
docker build -t agentbridge -f docker/Dockerfile .
docker run -p 8000:8000 \
  -e AGENTBRIDGE_ADMIN_KEY="$(openssl rand -hex 16)" \
  -e AGENTBRIDGE_DB=/data/governance.db \
  -v "$PWD/data:/data" \
  agentbridge
```

## 3. Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` / `HOST` | `8000` / `0.0.0.0` | Bind address |
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

> The Postgres backend mirrors the SQLite one behind the same interface. Validate it
> against a throwaway Postgres before relying on it: set `AGENTBRIDGE_TEST_PG` and run
> `pytest tests/test_postgres_store.py`.

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
- [ ] **Metrics/tracing** (OpenTelemetry) — roadmap.
- [ ] A formal security review before handling regulated production traffic.

See `docs/ROADMAP_AND_MONETIZATION.md` for what's gated on demand vs. built next.
