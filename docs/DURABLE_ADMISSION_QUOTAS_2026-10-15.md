# Durable aggregate admission quotas

Tenant runtime admission can enforce aggregate tenant and enrolled human/machine
spend, recent admission rate and active-operation caps. Per-agent budgets remain
in force. These are synthetic operator-owned cost units; this feature does not
establish a financial accounting or compliance contract.

Policy is stored in the private tenant SQL namespace and reloaded for every
admission. Aggregate enforcement starts disabled for explicit operator review;
the operator must enable it. Attribution/history is recorded for new tenant
gateway admissions even while enforcement is disabled. Disabling enforcement
does not delete or reset usage. History capacity remains bounded in either mode.

An enrolled tenant administrator with `policy:write` can replace the limits:

```python
session.set_quotas(
    enabled=True,
    spend_limit=1000.0,
    user_spend_limit=100.0,
    rate_limit=10000,
    user_rate_limit=1000,
    window_seconds=3600,
    max_active=128,
    user_max_active=32,
    max_records=100000,
)
print(session.get_quotas())
```

`session` is obtained from `TenantKernel.session` using an authenticated,
currently enrolled operator principal. No request-supplied principal, role,
owner hash or arbitrary database connection grants this permission. The HTTP
equivalents are `PUT /v2/operator/quotas` and `GET /v2/operator/quotas`, with the
existing pinned-issuer bearer/tenant authentication. PUT replaces the policy;
omitted numeric fields use the documented defaults shown above. Reads require
`budgets:read`. Viewer/operator roles lacking `policy:write` cannot enable,
disable or change these limits. Policy replacement and its audit record commit
together; lowering a limit stops further admissions without discarding usage or
cancelling an operation already in flight.

The quota-owner domain is separate from exact-scope resource-view ownership.
It includes tenant, principal kind and enrolled issuer/subject, and deliberately
excludes delegation ID, grant revision, scope and agent for delegated humans.
Renewing/narrowing a grant or using another delegated agent cannot reset that
human's aggregate cap. Machine enrollment remains a distinct owner. A separately authorized machine action is not attributed to a human merely because that agent also holds a human delegation; delegated-only destination policy remains a separate authorization requirement.

Admission locks operation identity before the tenant quota fence, checks limits
and records cost/attribution before inserting the operation claim, then reserves
and links per-agent budget, consumes approval and rechecks authority. All commit
in the existing shared SQL transaction. A database trigger rejects an older
worker inserting an operation without its exact matching quota record whenever
aggregate enforcement is enabled or its policy version is unknown. This is a mixed-version participation guard;
it does not make a trusted database owner or in-process embedding untrusted.

Outcome state comes from the existing operation ledger. No second outcome
counter must be independently synchronized with gateway settlement or
reconciliation. UNKNOWN remains spend exposure and active capacity until an
authoritative terminal settlement; elapsed time never frees those resources.
Current spend includes every existing agent budget, including legacy/unmapped
spend and outstanding tokens. Unattributed exposure/active operations are
conservatively charged to every affected user cap, without inventing historical
ownership. Recent legacy operations conservatively count by their latest stored
timestamp, and legacy UNKNOWN operations continue to count. New admitted-rate
records retain their admission timestamp even after failed outcomes. Timestamps
come from the database clock; PostgreSQL workers do not supply local time.

Policy/cost/attribution history survives restart. Missing, malformed or unsupported
policy is rejected. Bootstrap inserts a disabled default only when both quota
tables are absent. A missing policy row, missing companion table or unexpected
relation type in an existing namespace requires reviewed recovery; restart must
not silently disable limits or recreate missing attribution history. Quota
bootstrap protects its own two tables within the same transaction, while the
kernel retains its final seal of all tenant helpers. Actual worker death before
commit must roll back the quota
record along with budget and claim. Full history capacity fails closed and calls
for reviewed archival; this component never deletes history, UNKNOWN outcomes,
reservations, holds, audit or evidence to regain capacity.

Limitations remain explicit: this unit does not provide approval/task/audit/evidence
storage retention, frontdoor request shedding, per-user custom limit overrides,
independent accounting custody, rolling HA acceptance or production throughput
qualification. Aggregate checks currently inspect existing budgets and operation
history; large-history contention/latency must be measured and improved before
production qualification. Direct raw SQL/database-owner mutation remains outside
the authenticated service boundary. Enabled quotas are an additional admission
control, not authorization for a destination effect. Production target restrictions
and engineering-alpha/production NO-GO boundaries remain.
