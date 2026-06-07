# Control Plane API Reference

Base: the FastAPI app in `src/api/control_plane.py`. Interactive docs at `/docs`.

Three planes:
- **Public** — mesh translation, no auth.
- **Operator** — manage identities/budgets/approvals/audit; requires `X-Admin-Key`.
- **Agent** — governed routing; requires an Ed25519 **signed request**.

All `/control/*` paths are rate-limited per client IP (`AGENTBRIDGE_RATE_LIMIT`/min).

---

## Public — mesh translation (no auth)

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/health` | — | `{status, protocols}` |
| GET | `/control/protocols` | — | `{protocols: [...]}` |
| POST | `/control/translate/call` | `{src, dst, wire}` | `{wire}` — request translated src→dst |
| POST | `/control/translate/result` | `{src, dst, wire}` | `{wire}` — result translated src→dst |

Malformed wires (non-object, or empty/unroutable) return **400** with a clear reason.

## Operator — requires header `X-Admin-Key`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/control/identities` | Register an agent identity (DID). With `public_key_hex` registers a client key; without it, the server generates one and returns the private key **once**. |
| POST | `/control/identities/{agent_id}/revoke` | Revoke an identity |
| GET | `/control/identities` | List identities (DIDs) |
| PUT | `/control/budgets/{agent_id}` | Set spend/rate budget |
| GET | `/control/budgets/{agent_id}` | Read budget + spend |
| POST | `/control/capabilities/sensitive` | Mark a capability as requiring approval |
| GET | `/control/approvals` | List pending approval requests |
| POST | `/control/approvals/{id}/approve` · `/deny` | Resolve an approval |
| GET | `/control/audit` | Audit entries + integrity check |
| GET | `/control/audit/export` | Audit log as JSONL (for SIEM/auditors) |

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
