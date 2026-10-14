# Enterprise governance components

These are experimental controls in one shared platform, not a released managed
Enterprise service. Operator administration uses admin-key/OIDC authentication
and RBAC. Durable approvals, policy and budgets exist; production retention,
trusted checkpoint custody, tenant service isolation, support and SLA acceptance
remain separate gates. See [current acceptance](CURRENT_STATUS_2026-10-13.md).

---

## 1. Declarative policy engine (policy engine v2)

Compose rules and attach them to the policy engine; the first deny wins, and a rule can
require human approval. Rules live in `src/governance/policy_rules.py`.

```python
from src.governance import (
    PolicyEngine, PolicySet, MaxCostPerCall, RequireApprovalAboveCost,
    DenyCapabilities, BusinessHoursOnly, DenyProtocolRoute,
)

policy = PolicySet([
    MaxCostPerCall(10),                       # block any single call costing > 10
    RequireApprovalAboveCost(5),              # human approval for calls > 5
    DenyCapabilities(["wire_transfer"]),      # never allow this capability
    BusinessHoursOnly(9, 17, days=[0,1,2,3,4]),  # Mon-Fri 09:00-17:00 UTC only
    DenyProtocolRoute("a2a", "mcp"),          # block a specific route
])

engine = PolicyEngine(identities, budgets, approvals=approvals, policy_set=policy)
```

Built-in rules: `MaxCostPerCall`, `RequireApprovalAboveCost`, `DenyCapabilities`,
`AllowOnlyCapabilities`, `BusinessHoursOnly`, `DenyProtocolRoute`. Add your own by
subclassing `Rule` (one `evaluate(ctx) -> RuleResult` method).

## 2. RBAC for operators

Operators of the control plane get a role; roles map to permissions
(`src/governance/rbac.py`).

| Role | Can |
|------|-----|
| `admin` | everything (`*`) |
| `operator` | manage identities, budgets, approvals; read/export audit |
| `viewer` | read identities, budgets, approvals, audit |

```python
from src.governance import role_can, require
role_can("operator", "budgets:write")   # True
require("viewer", "identities:write")   # raises AccessDenied
```

## 3. OIDC / JWT operator auth (SSO)

Replace the shared admin key with per-operator SSO. Operators present a JWT from your IdP
(Okta, Azure AD, Auth0, Keycloak); the signature is verified and a role claim maps to an
RBAC role. Code: `src/api/auth_oidc.py` (requires `pyjwt`, imported lazily).

```python
from src.api.auth_oidc import OidcConfig, OidcVerifier

verifier = OidcVerifier(OidcConfig(
    issuer="https://your-idp.example.com",
    audience="agentbridge",
    public_key_pem=IDP_SIGNING_PUBLIC_KEY,   # production: fetch JWKS by `kid`
    role_claim="role",
))
claims, role = verifier.authenticate(request.headers["Authorization"])  # ("Bearer <jwt>")
```

**Production note:** for real IdPs, fetch the signing keys from
`<issuer>/.well-known/openid-configuration` (JWKS) and select by `kid` rather than pinning a
single PEM. The verifier interface stays the same.

## 4. Signed audit checkpoints (compliance / SIEM)

The audit log is already hash-chained and tamper-evident. A **signed checkpoint** lets a
third party prove the log was not truncated or rewound past a point in time — sign the chain
head with an operator key and anyone can verify it later.

```python
cp = audit.checkpoint(sign=operator_identity.sign,
                      public_key_hex=operator_identity.public_key_hex)
AuditLog.verify_checkpoint(cp)   # True; tamper the head or signature -> False
```

For SIEM ingestion, export the chain as JSONL (`/control/audit/export`) into Splunk /
Datadog / S3 on a schedule, and store periodic signed checkpoints alongside it.

---

## Concurrency & scaling (read before you deploy)

**The tested atomic operations require a shared durable store.** This does not
qualify every deployment, failure mode or external destination. The audit hash-chain
append and the budget reserve/commit/release are **atomic, store-side operations**, not
in-memory read-modify-write:

- **Audit chain** — `store.append_audit_chained()` determines the next `(seq, prev_hash)` from
  the durable head *inside* an atomic section (SQLite `BEGIN IMMEDIATE`; Postgres
  transaction-scoped `pg_advisory_xact_lock`), then inserts. Concurrent workers serialize, so the
  chain can't fork and `verify_chain()` stays valid. `AuditLog.verify_durable()` checks the full
  persisted chain.
- **Budgets** — `store.mutate_budget()` reads the budget's persisted state (including outstanding
  reservations), runs the reserve/commit/release mutation, and writes it back, all under the same
  per-agent lock. Two workers can't both pass the cap; reservations are visible across workers.

The bounded concurrency tests demonstrate these paths: `tests/test_concurrency.py` spins up **separate store connections
in separate threads** (a faithful stand-in for separate OS processes) hammering the same SQLite
file, and asserts the chain is gap-free + verifiable and the budget never overspends. A negative
control in the same file confirms per-process **in-memory** state *would* fork — so the test
catches a regression rather than passing vacuously. The **same guarantees are verified on real
Postgres** (the `pg_advisory_xact_lock` path) in `tests/test_postgres_store.py` against
`postgres:16` — 6 tests, including 2 multi-connection concurrency tests.

**The one rule:** set `AGENTBRIDGE_DB` to a shared backend before running multiple workers — a
SQLite file path (single node, multiple workers) or a `postgres://` URL (multi-node). The default
`InMemoryStore` is per-process and is for single-worker/dev only. Approvals and declarative policies are store backed in the current control plane.
Process-local objects and uninstrumented SDK transports do not automatically inherit those controls.

## Not code — handled honestly

Two parts of the "enterprise tier" cannot be shipped as code in this repo:

- **Managed cloud (SLA-backed hosting):** that's running and operating servers, not a library
  feature. The pieces to self-host are here (Docker, Postgres backend, rate limiting, TLS at a
  proxy — see `docs/DEPLOYMENT.md`); a managed offering is an operations/business undertaking.
- **SOC 2 Type II / HIPAA:** these are independent audits with human auditors over months, not
  something a codebase can claim. The controls above (RBAC, OIDC, signed audit, retention) are
  the technical evidence such an audit would examine, but certification itself is a process.


## Security and compliance qualification (October 2026)

This document describes experimental components, not a certified enterprise release. In particular, in-production destructive audit retention and ad-hoc checkpoint signing are intentionally disabled. Process-local legal-hold controls and ephemeral signing keys are not acceptable compliance controls. Operator reconciliation requires independently verified external evidence before financial settlement. External security review, safe network egress, current protocol conformance and staged recoverability acceptance remain open. Please see `docs/HARDENING_RELEASE_GATES.md`.
