# Control Plane API Reference

Base: the FastAPI app in `src/api/control_plane.py`. Interactive docs at `/docs`.

Three planes:
- **Public** — mesh translation, no auth.
- **Operator** — manage identities/budgets/approvals/policy/audit. Auth is EITHER
  `X-Admin-Key` (role: **admin**) OR — when OIDC is configured — an
  `Authorization: Bearer <jwt>` from your IdP whose role claim maps to RBAC
  (**admin** / **operator** / **viewer**). Each endpoint requires a permission;
  a role without it gets **403**.
- **Agent** — governed routing; requires an Ed25519 **signed request**.

All `/control/*` paths are rate-limited per client IP (`AGENTBRIDGE_RATE_LIMIT`/min).

OIDC env: `AGENTBRIDGE_OIDC_ISSUER`, `AGENTBRIDGE_OIDC_AUDIENCE`, and one of
`AGENTBRIDGE_OIDC_PUBLIC_KEY_PEM` / `AGENTBRIDGE_OIDC_PUBLIC_KEY_FILE`
(+ optional `AGENTBRIDGE_OIDC_ROLE_CLAIM`, default `role`).

---

## Public — mesh translation (no auth)

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/health` | — | `{status, version, protocols, store}` — liveness (always 200, even while draining) |
| GET | `/ready` | — | `{status, store}` — readiness; **503** while draining or if the store is unreachable |
| GET | `/version` | — | `{version, python, store}` |
| GET | `/metrics` | — | Prometheus exposition (text) |
| GET | `/control/protocols` | — | `{protocols: [...]}` |
| POST | `/control/translate/call` | `{src, dst, wire}` | `{wire}` — request translated src→dst |
| POST | `/control/translate/result` | `{src, dst, wire}` | `{wire}` — result translated src→dst |

Malformed wires (non-object, or empty/unroutable) return **400** with a clear reason.

## Operator — admin key or OIDC bearer token (RBAC-enforced)

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| POST | `/control/identities` | `identities:write` | Register an agent identity (DID). With `public_key_hex` registers a client key; without it, the server generates one and returns the private key **once**. |
| POST | `/control/identities/{agent_id}/revoke` | `identities:write` | Revoke an identity |
| GET | `/control/identities` | `identities:read` | List identities (DIDs) |
| PUT | `/control/budgets/{agent_id}` | `budgets:write` | Set spend/rate budget |
| GET | `/control/budgets/{agent_id}` | `budgets:read` | Read budget + spend |
| POST | `/control/capabilities/sensitive` | `policy:write` | Mark a capability as requiring approval |
| GET | `/control/approvals` | `approvals:read` | List pending approval requests |
| POST | `/control/approvals/{id}/approve` · `/deny` | `approvals:write` | Resolve an approval |
| GET | `/control/audit` | `audit:read` | Audit entries + integrity check |
| GET | `/control/audit/export` | `audit:export` | Audit log as JSONL (for SIEM/auditors) |
| POST | `/control/audit/checkpoint` | `audit:export` | Ed25519-sign the current audit head — a third party can later prove the log wasn't truncated/rewound past this point |
| POST | `/control/audit/retention` | `audit:export` | `{action:"truncate", seq}` drops entries before `seq` (chain stays verifiable); `{action:"legal_hold", on}` freezes truncation (**409** while a hold is active) |
| POST | `/control/policy/rules` | `policy:write` | Add a declarative policy rule (see below) |
| GET | `/control/policy/rules` | `policy:read` | List active policy rules |

Roles: **admin** = everything; **operator** = all of the above except `policy:write`;
**viewer** = the `:read` permissions only.

### Policy rules (`POST /control/policy/rules`)

Body: `{"type": "<rule>", "params": {...}}`. Types:

| type | params | effect |
|------|--------|--------|
| `max_cost` | `{"max_cost": 10}` | deny any single call costing more |
| `approval_above_cost` | `{"threshold": 5}` | require human approval above this cost |
| `deny_capabilities` | `{"capabilities": ["wire_transfer"]}` | never allow these |
| `allow_only_capabilities` | `{"capabilities": ["add","echo"]}` | allow nothing else |
| `business_hours` | `{"start_hour":9,"end_hour":17,"days":[0,1,2,3,4]}` | UTC window only |
| `deny_route` | `{"src":"a2a","dst":"mcp"}` | block a protocol route |

## Agent — requires a signed request

Headers: `X-Agent-Id`, `X-Nonce`, `X-Signature` (Ed25519 over `agent_id + nonce + body`,
see `src/governance/request_auth.py :: sign_request`).

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/control/authorize` | Check if a call would be allowed (identity + capability + budget + approval) |
| POST | `/control/route` | Governed any-to-any route: authorize → reserve budget → translate → invoke target → commit → audit |

Denials return **401/403** and are recorded in the audit log. Over-budget returns a
budget reason. Replayed nonces are rejected.

---

### Example: translate an OpenAI tool call to A2A
```bash
curl -s localhost:8000/control/translate/call -H 'content-type: application/json' -d '{
  "src": "openai", "dst": "a2a",
  "wire": {"id":"1","type":"function","function":{"name":"add","arguments":"{\"a\":2,\"b\":3}"}}
}'
```
