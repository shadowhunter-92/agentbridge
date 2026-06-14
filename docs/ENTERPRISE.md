# Enterprise governance

Beyond the core mesh + identity/budget/audit, AgentBridge ships the governance controls
enterprises ask for. All of the below is real, tested code (see
`tests/test_enterprise_governance.py` for the modules and
`tests/test_control_plane_rbac.py` for the HTTP wiring). Two items in the "enterprise
tier" are **not** code — managed hosting and SOC 2 — and are called out honestly at the
bottom.

**All of it is live over the control plane HTTP API**: operator endpoints accept the admin
key (role: admin) or an OIDC bearer token (role claim → RBAC), each endpoint enforces a
permission, and policy rules are manageable via `POST /control/policy/rules` — see
`docs/API_REFERENCE.md`.

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

**Run the control plane as a single worker today.** The audit hash-chain and the budget
reservation ledger are maintained **in process** (with a per-process lock). That is correct
and safe for a single worker, but **multiple workers/replicas behind a load balancer would**:

- **fork the audit chain** — two workers read the same `prev_hash` and append concurrently, so
  `verify_integrity()` fails (the tamper-evidence breaks); and
- **double-spend budgets** — two workers both pass `can_afford()` on the same in-memory state and
  both reserve, overrunning the cap.

The control plane logs a loud warning about this at startup. **Shared-state HA** (an atomic
DB-side chain head + a `reservations` table with row-level locking, e.g. `SELECT … FOR UPDATE`)
is the fix and is on the roadmap (`docs/ROADMAP.md`) — built when a deployment actually needs
multi-node. Until then: one worker, vertically scaled, is the supported topology. (This is an
honest known limitation, not a hidden one — credit to external code review for sharpening it.)

## Not code — handled honestly

Two parts of the "enterprise tier" cannot be shipped as code in this repo:

- **Managed cloud (SLA-backed hosting):** that's running and operating servers, not a library
  feature. The pieces to self-host are here (Docker, Postgres backend, rate limiting, TLS at a
  proxy — see `docs/DEPLOYMENT.md`); a managed offering is an operations/business undertaking.
- **SOC 2 Type II / HIPAA:** these are independent audits with human auditors over months, not
  something a codebase can claim. The controls above (RBAC, OIDC, signed audit, retention) are
  the technical evidence such an audit would examine, but certification itself is a process.
