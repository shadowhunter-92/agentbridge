# Durable queued tenant task intents — October 17, 2026

This first P04 unit accepts and inspects a signed tenant-native task intent.
Acceptance queues immutable provenance and initial status. **It does not execute
an action.** No worker, result writer, operation linkage, reservation, approval
consumption, cancellation command or successful completion is implemented.
Executable recovery and tenant-aware reconciliation remain required before P04
can be complete. The production target restriction remains in force.
Later [private preparation and first-admission units](QUEUED_INTENT_PREPARATION_2026-10-18.md)
add current-authority revalidation and atomic task/operation/event linkage.
They retain separate evidence and do not add a worker or public execution API.

## Signed acceptance and inspection

`POST /v2/tasks/submit` uses existing tenant-v2 authentication headers and requires:

```json
{
  "request_scope": "task.submit",
  "task_id": "native-task-1",
  "context_id": "native-context-1",
  "src": "mcp",
  "dst": "mcp",
  "wire": {"method": "tools/call", "params": {"name": "read", "arguments": {}}},
  "operation_id": "native-operation-0001",
  "target_id": "operator-registered-target"
}
```

Extra fields, caller-selected owners/principals/costs/target configuration,
duplicate JSON members, nonfinite JSON, wrong scope and changed signed bytes
are rejected. Direct `TenantSession.submit_task(body, nonce=...)` applies the
same schema and exact-body checks. The operator must register the target,
permit capability/target access in enrolled authority, and supply a tenant cost
schedule. Parsing and pure protocol translation must succeed before acceptance.

Current declarative deny rules prevent acceptance. Required approval is recorded
as submission-time information; no execution approval is created, checked or
consumed. Budget state is not checked, seeded, pruned or reserved. The
side-effecting `PolicyEngine.authorize` is not used as a read-only check. Actual
execution will need fresh policy, approval, budget, quota and target admission.

HTTP 202 returns `phase: "queued"`, `execution_admitted: false`, immutable
submission/provenance, `intent_sha256`, and a future result allowance. Lifecycle
provenance is explicitly `agentbridge`; MCP inputs are not relabeled A2A. Existing
A2A snapshots and signatures are unchanged.

`POST /v2/tasks/intents/read` accepts
`{"request_scope":"task.intent.read","task_id":"native-task-1"}` and returns
only the authenticated exact owner's retained intent in that tenant. Existing
snapshot, event and stream endpoints observe submitted status. Observation and
reconnect do not admit or execute anything.

`TenantAgentClient.submit_task(src, dst, wire, task_id=..., context_id=...,
operation_id=..., target_id=...)` and `task_intent(task_id)` sign these requests
and preserve the existing no-automatic-retry client behavior.

## Provenance and operation identity

The record retains exact original signed body bytes as UTF-8 text, body SHA-256,
nonce, enrolled signer public key, authority binding/revisions, original
authorization expiry, database acceptance time, capability, operator cost, and
resolved target-configuration digest. The acceptance audit binds the record
digest with zero charged cost. This is trusted accepted provenance, **not a
standalone reusable authorization token**. No process-local seal is retained;
there is no mint-from-binding or execution API.

A future worker needs a restricted revalidation path checking the original
deadline and current tenant, agent/delegation/user/grantor revisions and scopes.
It cannot deserialize the old principal or authenticate the old nonce again.
Fresh same-scope authentication may inspect history after the original request
expires; it does not extend or renew the intent's execution authorization.

The next [private preparation unit](QUEUED_INTENT_PREPARATION_2026-10-18.md)
implements restricted enrolled-row revalidation inside a process/thread-bound
guard. Preparation itself adds no admission. The later private first-admission
extension in that document uses the actual sealed object and has its own
qualification boundary. Neither extends this queued-acceptance unit's evidence
to executable tasks.

Retained task IDs are unique per exact owner; operation IDs are unique per
tenant-local agent within retained intents. Existing lifecycle identities and
operations are rejected at acceptance. Exact duplicates also conflict, without
replacing history.

**Submission reserves neither an operation row nor its identity against ordinary
gateway routing.** The initial lookup is not a claim or concurrency lock. A
concurrent or later synchronous route can claim that ID, leaving the queued
intent unchanged. The private first-admission extension atomically rejects any
existing claim and binds its own new operation fingerprint to the retained
intent/owner/task. Existing UNKNOWN operations must never be replayed, even if
a local marker suggests they were not sent. No action fingerprint or
task-operation correlation is established by queued acceptance itself.

## Durable bounds and transactions

The private tenant namespace gains `task_intents_v1`, `task_intent_policy_v1`,
and `task_intent_meta_v1`. Bootstrap installs existing tenant write guards
immediately. Application UPDATE, DELETE and PostgreSQL TRUNCATE of intent rows
are rejected. No history is deleted to make capacity.

| Persisted limit | Default | Allowed range |
| --- | ---: | ---: |
| Encoded intent/provenance bytes | 65,536 | 256–1,048,576 |
| Future result allowance per intent | 65,536 | 1–1,048,576 |
| Retained intent count | 1,024 | 1–1,000,000 |
| Aggregate retained bytes | 134,217,728 | 256–1,073,741,824 |

Aggregate usage is actual encoded record bytes plus each immutable future result
allowance. No result payload or writer exists yet; a future writer must enforce
the stored allowance. Policy changes do not resize old allowances. Lifecycle
event/history bounds remain separate and also apply to submitted status.

`GET /v2/operator/task-intent-capacity` requires budget-read permission. `PUT`
requires policy-write permission and all four fields: `max_intent_bytes`,
`max_result_bytes`, `max_intents`, `max_retained_bytes`. Policy and audit updates
share a transaction. Count/aggregate limits cannot be lowered below retained
usage; per-row policy changes govern future rows. Missing or unsupported policy
fails closed. Saturation maps to HTTP 429.

Submission also maps lifecycle owner/history/event capacity saturation to 429,
rolling back its tentative intent and audit. Existing status/read route error
semantics are unchanged. Malformed nested action JSON returns HTTP 400 before
acceptance, including invalid OpenAI function and ACP part shapes.

Intent, SUBMITTED snapshot/event and audit share one `sql_atomic` transaction
on the same tenant store. SQLite uses BEGIN IMMEDIATE and nested savepoints.
PostgreSQL supports READ COMMITTED only for this feature; the store and insertion
trigger reject other isolation modes rather than rely on stale count snapshots.
Advisory lock 911006 serializes intent limits with lifecycle work. SQL insertion
guards check persisted policy, payload length, count and aggregate allowance.
There is no invocation in this transaction or anywhere in the feature unit.

Restore these tables consistently with task/audit history, retaining original
provenance, allowances and policy. Database administrators, uncoordinated clones
or rollback, and independently witnessed integrity remain outside this local
application persistence contract.

## Verification scope

`tests/test_task_intents.py` and `tests/test_task_intents_http.py` cover direct
and real loopback/client acceptance, strict signed scope, tenant/exact-owner
views, duplicates/mutations, later synchronous operation collisions, independent
authority/tenant connection concurrency, durable bounds, immutable history,
restart, injected acceptance rollback, real
process death before commit, production gates and absence of execution/accounting.
Both are included in real PostgreSQL CI; skipped cases alone are not PostgreSQL
evidence. Protocol OAuth, remote cancellation, result delivery, external
completion, authoritative reconciliation and production readiness remain open.
