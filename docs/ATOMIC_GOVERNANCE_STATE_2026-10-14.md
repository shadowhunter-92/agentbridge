# Atomic local outcome settlement

When gateway identities, budgets, approvals, audit and operation ledger share
one durable SQL store instance, definite-success settlement commits spent
budget, operation outcome and the chained audit record in one transaction.
Pre-invocation cancellation likewise releases its owned reservation, marks its
claim failed and records the abort together. Tenant composition requires the
shared store; legacy caller-owned embeddings with separate or in-memory
participants retain a weaker accounting contract.

SQLite uses BEGIN IMMEDIATE with nested savepoints. PostgreSQL uses its native
transaction/savepoint contexts. Existing budget and audit implementations are
reused. Component locks follow the store-before-manager order, and durable audit
append relies on store serialization. These choices prevent an outer transaction
from inverting the previous component/store locking order.

A settlement exception rolls back local partial updates. The claimed operation
stays UNKNOWN with its original reservation available to reconciliation. Actual
worker-process death before commit has the same result. A remote effect cannot
be rolled back by this transaction: UNKNOWN is retained until authoritative
evidence resolves it, and the gateway does not automatically execute it again.

Metrics are emitted after the durable commit. A telemetry exception is logged
and does not invalidate a committed outcome. Audit records themselves remain a
required settlement participant; an audit append failure prevents local success
settlement. This is local SQL accounting, not independent proof of an external
physical or financial effect.

Operator cost is normalized through the existing budget validator before
fingerprinting, so equivalent integer and floating-point costs share the same
scope. Historical fingerprints are never rewritten. A legacy integer-cost
fingerprint from an older SDK may conservatively conflict after upgrade; inspect
the old operation and review/reissue any old approval rather than replaying it.
Tenant cost schedules were already normalized floating-point values.

Qualification covers injected ledger/audit failures, audit-chain rollback,
separate-connection visibility, nested savepoints, worker-process termination
during success and pre-invocation abort, cancellation and telemetry failures on
SQLite and PostgreSQL. Exact commit and CI evidence must accompany acceptance.

At this settlement unit's original checkpoint, admission still used separate
reservation, approval-consumption and operation-claim transactions. The cumulative
draft subsequently adds [shared-SQL atomic admission](ATOMIC_ADMISSION_2026-10-14.md)
and [aggregate tenant/human admission quotas](DURABLE_ADMISSION_QUOTAS_2026-10-15.md).
Those contracts require the stated shared store and supported tenant composition;
legacy separate/in-memory participants remain weaker. Retained task count and
event-byte caps are separate from audit/evidence retention, tenant-aware
reconciliation services and durable executable tasks, which remain open. See
[current status](CURRENT_ALPHA_STATUS.md). Production target restrictions and
unrestricted production NO-GO remain in force.
