# Enrolled tenant runtime and HTTP boundary

> **Runtime checkpoint with later bounded additions.** Test counts below apply
> to their stated runtime SHAs. The cumulative draft also includes durable task
> count/event-byte limits, shared status-stream allocations and policy/signing/SQL composition corrections; see
> [current alpha status](CURRENT_ALPHA_STATUS.md). Broad storage/retention and
> tenant service coverage remain incomplete.

This is an opt-in engineering alpha layer over the existing Trust Kernel. It
does not establish production acceptance or activate historical databases.

## Authority and storage

`TenantKernel` receives an operator-built `AuthorityDirectory`, explicit tenant
stores, cost schedules, and target records. A tenant owns a private SQLite file
or a private PostgreSQL schema with its own unprivileged direct login. PostgreSQL
tenant logins cannot inherit roles, create temporary objects, or have USAGE on
another configured tenant or authority schema. Authority lives separately.

Every `TenantSession` operation revalidates the sealed principal. Local governance
reads and mutations hold an authority lock: SQLite BEGIN IMMEDIATE, PostgreSQL a
shared advisory lock. Enrollment/revocation uses the exclusive boundary. This
serializes local admission with revocation; it does not make remote effects atomic.
The SQLite tradeoff is serialization across tenants sharing the authority file.

Existing identity/budget/approval/audit/operation/task classes operate inside the
bound namespace. Same agent and operation identifiers can exist in different
tenants. Stable authority revisions enter approval/operation fingerprints. Human
delegation changes ownership; a machine need not invent a human grant. Resource
ownership uses tenant, exact agent principal kind, issuer, subject, authenticated
agent, and canonical capability/target sets. Token or grant renewal with the same
scope preserves access; different agent or scope does not inherit history.
Operator operation inspection still requires audit:read and remains tenant-scoped.

Existing operation records retain complete bindings and can use this comparison
without rewriting old signatures or state. Earlier opaque task-owner hashes do
not contain enough authority metadata for safe automatic assignment. Their rows
remain unchanged and fail closed through the agent session API. Trusted operators
must retain them for explicit, independently evidenced reassignment or re-admission;
there is no fallback to the older, broader human ownership key. Only machine and
delegated-human principals use the agent task-session ownership API.

## Explicit HTTP mode

Set `AGENTBRIDGE_AUTHORITY_MODE=multi_tenant` and construct
`src.api.tenant_control_plane.create_tenant_app(kernel)` from trusted application
setup. This factory has no default database, global administrator key or login
bootstrap. CLI configuration loading is not yet provided. The legacy CLI/HTTP,
MCP server, A2A status factory and unscoped gateway refuse this mode. Legacy
single-tenant behavior remains available in `legacy_single_tenant`, the default.

Operator endpoints require `Authorization: Bearer`, `X-Issuer`, and a verified
enrolled tenant selected by `X-Tenant-Id`. Platform administrators authenticate
without a tenant selector and explicitly choose `X-Resource-Tenant` for tenant
resources. JWT role claims do not grant enrolled membership or platform authority.

Agent POST endpoints require `X-Tenant-Id`, `X-Agent-Id`, `X-Nonce`, `X-Signature`
and optional `X-Delegation-Id`. Ed25519 tenant-v2 proof covers the exact body and
selectors. A signed `request_scope` binds route versus operation/task lookup.
Duplicate authentication headers, duplicate JSON members, extra body fields,
compressed bodies and oversized bodies are rejected. Body reads have a deadline.
`TenantAgentClient` signs these requests, requires TLS except explicit loopback
evaluation, refuses redirects/environment proxies, bounds responses and never
automatically retries a consequential operation.

## Async admission and performance

The existing gateway offloads SQL admission and settlement from the event loop.
Cancellation before invocation completes cleanup; cancellation after dispatch
retains UNKNOWN exposure for reconciliation. A definite successful result settles
even if its caller disconnects. Duplicate losers cannot fail a winner's ledger row.

SQL audit initialization/count/head no longer load the complete audit history.
Explicit chain verification/export retain their full historical semantics. Local
30-sample microbenchmarks at 5,000 entries observed median initialization/count/
head latency fall from 118.714 to 5.647 ms on SQLite and 150.438 to 12.238 ms on
PostgreSQL. These observations are not network or production SLO measurements.
PostgreSQL COUNT still scans visible rows under MVCC.

## Qualification and remaining limits

The frozen runtime at `f76338fef677a7fe6a3923aa9ec53045fcbb4759`
passed 764 Windows/Python 3.12 tests and 767 Linux/Python 3.11 tests, with eight
subtests in each run. Eight Windows skips include three POSIX-only cases and
five PostgreSQL privilege cases on the SQLite fixture; Linux skips the latter
five. Both runs exercised SQLite and real PostgreSQL. These runs supersede
the intermediate 734-test qualification.

A subsequent separate-connection regression reproduced PostgreSQL authority
bootstrap holding the schema lock while waiting for admission to release the
authority lock. Bootstrap now acquires authority before schema, matching the
governance order. The regression and authority/runtime/HTTP group passed 87
tests, with one PostgreSQL-only case skipped on SQLite. Exact-head hosted CI
must be checked after this correction; earlier CI is not its qualification.

The packaging lock check seeds its candidate from the reviewed lock rather
than resolving new package releases implicitly. A Linux/Python 3.12 experiment
preserved all existing pins and detected a deliberately incompatible project
requirement. Dependency auditing and container vulnerability gates remain
separate required checks.

Tests cover same-ID tenant separation, PostgreSQL namespace privileges, issuer
and role confusion, replay/signature tampering, delegation revocation, operator
exports, real HTTP routing, body/header bounds, alternate legacy entry points,
async cancellation, duplicate admission and original production target gates.

Offline historical assignment and conservative rollback have a separate qualified procedure: [tenant migration](TENANT_MIGRATION_2026-10-14.md). Rolling and large-database migration remain unqualified.

Not complete: qualified storage quotas and
retention, tenant-aware reconciliation/evidence/background services, actual async
task execution/cancellation, MCP/A2A tenant network projections, workload identity,
qualified destination-atomic effects and observer readback, full-path performance,
trusted release qualification and independent acceptance. The generic production
target restriction remains in force, including standalone remote MCP tools. No
main merge, deployment, release publication or external contact occurs here.

Shared-SQL success settlement and pre-invocation abort now commit budget, operation state and audit together; see [atomic outcome accounting](ATOMIC_GOVERNANCE_STATE_2026-10-14.md). Shared-SQL admission now atomically binds reservation, approval and operation claim; see [atomic admission](ATOMIC_ADMISSION_2026-10-14.md). Operator-enabled durable aggregate admission quotas have a separate boundary: [tenant/user caps](DURABLE_ADMISSION_QUOTAS_2026-10-15.md). Durable [task-count](TASK_HISTORY_CAPACITY_2026-10-16.md) and [event-byte](TASK_EVENT_CAPACITY_2026-10-16.md) bounds now cover their stated namespaces. [Tenant-native status streams](tenant-task-streams.md) separately bound active authorized allocations across the shared authority database/namespace; frontdoor physical connection limits and coordinated recovery still require qualification. Audit/evidence-byte bounds and qualified retention remain separate work.
