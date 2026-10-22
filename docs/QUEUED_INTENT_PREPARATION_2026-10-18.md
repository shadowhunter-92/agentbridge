# Private queued-intent preparation — October 18, 2026

This internal P04 unit revalidates a retained native queued intent. It does not
admit or execute it. There is no public route, SDK method, worker, operation
claim/linkage, budget reservation, approval consumption, result writer, execution
recovery or remote cancellation. P04 remains partial and production target gates
remain in force. Existing status and queued acceptance APIs keep their semantics.
The separate October 20 private first-admission extension is described below;
it does not turn preparation metadata into public request authority.

## Private contract

`TenantKernel._prepare_queued_intent(tenant_id, owner_id, task_id,
expected_intent_sha256)` is a context manager for trusted internal code. It
selects only an operator-bound tenant runtime and the exact retained row. It
accepts no serialized principal, target configuration, cost or executable wire.
The yielded object is process sealed and usable only on the originating thread,
inside that particular authority guard. Copies and new scopes cannot reactivate
an expired guard. `_assert_prepared_queued_intent` revalidates the object, retained
row, current authority and current preparation inputs; future code must use that
restricted check rather than extracting a principal for execution.

The authority guard reuses enrolled-row/current-scope validators for tenant,
agent, original delegation, user and grantor. SQLite uses the existing
BEGIN IMMEDIATE authority guard; PostgreSQL uses the existing shared transaction
advisory lock, which serializes with supported enrollment/revocation writers.
Preparation does not acquire an operation or lifecycle admission lock. It does
not promise atomicity with later tenant-policy, lifecycle or gateway mutations.
Both authority transactions and tenant readbacks require PostgreSQL READ
COMMITTED in this private path; repeatable-read and serializable modes fail
closed, including a changed tenant mode during an existing preparation. Existing
public authority transaction behavior is unchanged.

The immutable record must match its expected SHA-256 and its exact original
signed body digest and parsed submission. Tenant, exact owner, task/context,
agent, operation reference, native SUBMITTED sequence-zero history and original
result allowance must agree. Current status must still equal that initial
queued snapshot. Current enrolled revisions/scopes and signer key must match
accepted provenance, including the original delegation rather than a later
same-scope replacement. Tenant identity and enrollment keys must agree.

Original authorization ends at the original signed nonce timestamp plus 300
seconds, or earlier at the original delegation expiry. The stored deadline
must equal that bound, and preparation fails at or after it. Restart, fresh
inspection authentication and new process seals cannot extend it. An internal
context also has a maximum 30-second lifetime, bounded by that original deadline.
If that short context expires, another preparation may occur only while the
original authorization and all current checks still hold.
The saved object fails at its short deadline even while its guard remains open.
Reassertion cannot renew its seal; a fresh preparation creates a distinct context
and still admits no execution or governance mutation.

Current enrolled rows supply a new valid process HMAC seal. Stored
`Principal.binding()` JSON is only a constraint to compare against those rows;
it is never reusable request authority. The internal principal's public request
body SHA-256 and nonce fields are empty. Existing `assert_request`, submission
and synchronous route checks reject it, and the old nonce is not authenticated
or claimed again. Public request authentication still validates and claims its
own exact signed body and nonce before constructing a principal.

Preparation reparses the original action, checks translation support, current
capability/target scope, exact operator cost and resolved target configuration,
including production qualification. It evaluates current declarative deny rules
and reads whether approval would be required. It does not call the side-effecting
`PolicyEngine.authorize`, seed/read/prune/reserve budgets, request/consume
approvals, claim operations or invoke a target. The preparation metadata contains
the stable original signed wire, target and cost; translated wire and generated
correlation IDs are deliberately absent. `execution_admitted` remains false.
`approval_required_now` is an observation; the original
`approval_required_at_submission` remains in digest-bound provenance. Neither
flag grants or consumes approval. Future admission must bind its effective
approval requirement to the action and check/consume the actual matching grant
atomically with admission.

## Remaining execution work and evidence boundary

Preparation leaves the accepted row, lifecycle, audit, replay claims, budgets,
approvals and operations unchanged. The stored per-intent future result allowance
is preserved even when policy for new intents changes. This unit adds no schema,
result storage or cleanup.

Submission and preparation reserve neither the operation row nor its identity
against ordinary synchronous routing. The private first-admission extension below
handles concurrent/later operation collisions, establishes task/operation/event
linkage, and rechecks policy, quota, approval, budget, target and original deadline.
A preparation object is not evidence that an external effect started or completed.

`tests/test_queued_intent_preparation.py` exercises SQLite and real disposable
PostgreSQL: current and revoked enrollments/delegations, restart, strict original
and short delegation deadlines, request-proof separation, guard/thread lifetime,
exact references, inconsistent stored body/binding/digest/allowance, changed
cost/target/policy/production configuration, immutable returned metadata and
absence of accounting or invocation. Fault-injected inconsistent readbacks test
validation, not resistance to a database administrator coherently replacing all
accepted history. Trusted in-process code, database owners and independently
witnessed custody remain outside the local persistence contract.
PostgreSQL-only negatives independently cover both connections' unsupported
isolation modes; SQLite skips for those cases are not PostgreSQL evidence.

The new test module is included in the explicit PostgreSQL CI list. This
preparation unit requires its own exact selected-head evidence. Current
qualification is recorded in the selected head's
[PR #70 checks](https://github.com/shadowhunter-92/agentbridge/pull/70/checks)
and phase receipt. The separate
queued-acceptance baseline `de1194a0b568c820205ac0abaa7f774eb530ae83` has recorded
seven successful workflows / 24 jobs, including
[CI](https://github.com/shadowhunter-92/agentbridge/actions/runs/39013120802).
Those results do not verify these later preparation changes or executable tasks.

## Private first admission and immutable linkage — October 20, 2026

`TenantKernel._admit_queued_intent(tenant_id, owner_id, task_id,
expected_intent_sha256)` is a trusted internal first-admission boundary. It opens
the preparation guard and passes the actual sealed object to the exact
operator-bound gateway/store. It accepts no serialized principal, caller-chosen
cost/target configuration, authorization Boolean or replacement validator. There
is no new public route, client method, worker or invocation path.

Admission uses the existing SQL operation/quota/budget/approval transaction. The
queued fingerprint binds the exact owner, task and retained intent digest to the
original action scope; synchronous fingerprints and public request-proof checks
retain their existing contract. Authority, target, cost and original/short-context
deadlines are rechecked while acquiring the required locks. PostgreSQL requires
READ COMMITTED. The order is authority guard, tenant SQL, operation, quota,
per-agent budget, approval, lifecycle and audit; SQLite uses its existing write
transaction/savepoint boundary.

Queued admission requires an existing operator budget-policy row containing
`spend_limit`, `rate_limit` and `window_seconds`, checked under the per-agent
budget lock before policy can seed defaults. Missing, empty or incomplete policy
rows are denied; ordinary bookkeeping defaults remain available for an existing
operator policy. The public synchronous budget path is unchanged. Effective
approval is required when either accepted provenance or current policy requires
it. Admission checks and consumes an actual exact-action scoped grant. Approval
flags are not grants. A denied admission rolls back its tentative governance
changes; a pending approval request and denial audit, when applicable, are
recorded separately while the task remains SUBMITTED.

One successful transaction claims the previously unclaimed operation, applies
quota attribution, reserves budget, links the reservation, consumes any required
grant, changes native SUBMITTED sequence zero to WORKING sequence one, records
one immutable link and appends the admission audit. The original intent and
sequence-zero event remain unchanged. Current preparation is checked before the
transition; the sealed authority/lifetime is checked again before commit without
pretending WORKING is still an initial queued snapshot. Existing operations in
any state, including UNKNOWN, conflict; admission never adopts or replays them.

**WORKING means locally admitted and awaiting dispatch.** The operation begins
UNKNOWN and its reservation remains held. No destination has been invoked and
no effect is proved. Inspection via private `TenantKernel._queued_admission`
returns frozen admission metadata for the exact retained digest, not a live
operation outcome. Later status-only cancellation does not settle/refund the
operation or resolve UNKNOWN. Repeated admission cannot mint another link or
reservation.

`task_operation_links_v1` and `task_operation_links_meta_v1` are additive tenant
tables. At most one link exists per retained owner/task and per agent/operation.
Each link stores at most 8,192 encoded record bytes and 4,096 snapshot bytes,
plus bounded identifiers/digests and the event sequence. Native identifiers keep
their 128-character contract with a 512-byte encoding bound. These are logical
application-value bounds; database rows, indexes, WAL, backups and copies add
overhead. The link does not consume or shrink the immutable future result
allowance. Existing task count, event count and event-byte guards still apply.
No link/history cleanup or result payload storage is added.

Bootstrap creates both tables atomically under the existing PostgreSQL schema
bootstrap fence. Existing objects must match the retained schema version/digest,
columns, nullability, primary keys and exact expected unique-key shapes.
Unexpected unique restrictions, including partial or expression indexes, fail
closed. Partial/unknown schemas are not automatically migrated. SQL insertion
guards bind the exact intent, UNKNOWN operation, reservation token and matching
current sequence-one nonterminal snapshot/event. Supported admission writes
WORKING. Application UPDATE/DELETE and PostgreSQL
TRUNCATE are rejected. Restore the link, operation/reservation, intent, task and
audit history consistently; this is not a safe live migration or independently
witnessed anti-rollback contract.

The six admission test modules are `test_task_admission.py`,
`test_task_admission_cases.py`, `test_task_admission_transactions.py`,
`test_task_admission_waits.py`, `test_task_admission_recovery_boundaries.py` and
`test_task_admission_budget_policy.py`. They cover SQLite and disposable
PostgreSQL first-admission behavior, rejection/rollback, exact scope, concurrent
claims, real lock waits/deadlines, schema bounds and child-process death around
commit. All six are selected by the full-suite SQLite jobs and explicit
PostgreSQL integration job. Module presence or skipped PostgreSQL cases are not
qualification: use the exact selected-head CI and source-associated phase
receipts. The successful preparation head
`893fdba4d3d1928bd66491affcb87e01a263b063` does not verify this later extension.

Worker dispatch, durable results, definite settlement, tenant-aware UNKNOWN
reconciliation, execution recovery and acknowledged remote cancellation remain
open. This private local transaction does not supply destination fencing,
independent effect evidence or production acceptance. P04 remains PARTIALLY
TESTED; unrestricted consequential-action production remains NO-GO.
