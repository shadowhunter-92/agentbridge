# Task status transaction composition and tenant guards — October 16, 2026

Baseline: `d0881b937d2568e4e01fb02044bf466aea609e9a` (PR #63,
24 hosted checks passed). This unit retains the existing status-only lifecycle.

## Reproduced defects

`DurableTaskLifecycle._transaction` opened a fresh SQLite `BEGIN IMMEDIATE`
inside an existing governance transaction. A task-only nested write failed.
Separately, `SqliteStore.upsert_budget` called `commit()` unconditionally and
could commit an embedding operation before the caller's intended boundary.
Process-death tests demonstrated a budget mutation surviving an uncommitted
outer operation. PostgreSQL's existing nested transaction behavior did not have
these SQLite failures.

The lifecycle constructor created snapshot/event tables without immediately
installing the tenant legacy-write guards. An unscoped old connection could
delete both tables' rows on SQLite and PostgreSQL before a later kernel seal.

## Change

Reuse the existing `sql_atomic` boundary for task operations and SQLite budget
upserts. Nested calls use savepoints; success never commits the caller's outer
transaction and exceptions roll back only the nested call. PostgreSQL retains
its existing transaction advisory lock 911006 and cross-connection exclusion.
Install the existing tenant guards on the two task tables during the same
bootstrap transaction. The kernel's final all-table seal remains.

Initialize helpers before admitting work. All participants in a local atomic
operation must use the same store/connection. Database owner/administrator
credentials remain outside the tenant application boundary. This is not a
cross-database or remote-effect transaction.

## Acceptance evidence

`tests/test_task_atomic_scope.py` covers task-only and budget-only outer
rollback, combined rollback, caught nested failures followed by successful work,
terminal-state rollback, immediate legacy-write rejection on both tables, and
real child-process death before outer commit for creation and transition.
The tests run on SQLite and real PostgreSQL. Existing cross-connection lifecycle
contention, per-owner/event limits and reconnect tests remain unchanged.
The new file is added to PostgreSQL CI, rather than accepting skipped SQL tests
as PostgreSQL evidence. Exact command results and ending commit belong in the
phase evidence report; the presence of tests alone is not acceptance.

## Remaining boundaries

Status changes do not execute an action, cancel a destination request, refund a
reservation, or resolve UNKNOWN. Executable durable intent, authorization
revalidation after restart, operation linkage, network cancellation and result
artifacts remain separate work. Per-owner active/per-task event bounds do not
qualify fleet-wide storage/byte quotas or retention.

Other legacy SQLite methods still use standalone commit/transaction boundaries
(`upsert_identity`, raw `append_audit`, `insert_approval`,
`update_approval_status`, `delete_approval`, `truncate_audit_before`). Their
composition with an outer transaction needs a separate caller audit and
reproductions. This unit makes no general claim that every storage API can join
`sql_atomic`. Production remains NO-GO.

Follow-up: [legacy SQLite mutation boundaries](SQLITE_ATOMIC_MUTATIONS_2026-10-16.md)
records the separate reproductions and corrections for the six methods listed
above. The original task phase scope remains a historical observation.
