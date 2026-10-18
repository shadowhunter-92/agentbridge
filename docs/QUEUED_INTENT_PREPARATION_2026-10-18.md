# Private queued-intent preparation — October 18, 2026

This internal P04 unit revalidates a retained native queued intent. It does not
admit or execute it. There is no public route, SDK method, worker, operation
claim/linkage, budget reservation, approval consumption, result writer, execution
recovery or remote cancellation. P04 remains partial and production target gates
remain in force. Existing status and queued acceptance APIs keep their semantics.

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
against ordinary synchronous routing. First execution admission must atomically
handle concurrent/later operation collisions, establish task/operation/event
linkage, and recheck policy, quota, approval, budget, target and original deadline.
It must never redispatch a previously claimed action or replay UNKNOWN. A
preparation object is not evidence that an external effect started or completed.

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
