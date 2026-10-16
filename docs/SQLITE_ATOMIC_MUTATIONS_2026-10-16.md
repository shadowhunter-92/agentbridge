# Legacy SQLite mutation boundaries — October 16, 2026

Baseline: `eb2dcea8d722def931b95f15a8767d2592c54ad6` (PR #64,
24 hosted checks passed). This follows the task/budget transaction composition
fix and audits the six remaining operational standalone boundaries in SqliteStore.

`upsert_identity`, raw `append_audit`, `insert_approval` and `delete_approval`
committed their caller's transaction. `update_approval_status` and
`truncate_audit_before` rejected nesting by issuing `BEGIN IMMEDIATE` again.
The new tests reproduced seven failures on SQLite; the corresponding PostgreSQL
and production-retention cases passed (11 baseline passes).

All six methods now use the existing `sql_atomic` helper. Standalone calls still
commit; nested calls own a savepoint. Missing/non-pending approvals return false
without aborting the caller's work. Retention checks the same durable legal hold
under the same database writer boundary, and raw production deletion is still
forbidden. PostgreSQL behavior, approval compare-and-swap semantics and tenant
write guards are unchanged. Schema bootstrap remains initialization, not a
request-path operation; constructing a store inside a transaction is unsupported.

`test_store_atomic_mutations.py` runs on SQLite and real PostgreSQL. Each method
is tested for outer rollback and standalone persistence. Caught hold refusals,
missing/non-pending approvals and raw retention in both `prod` and `production`
must leave the outer transaction usable. The focused regression group covers
existing authority ordering, task process-death rollback, admission, governance,
policy, security and durable hold tests. Exact results/commit/CI are recorded in
the phase evidence report; files alone do not establish acceptance.

This is a SQL storage contract, not a cross-store or remote-effect transaction.
Any in-memory side effects/caches owned by higher-level consumers need their own
rollback/reload discipline before those consumers are composed atomically.
Raw audit append does not itself validate a signed chain, and no evidence
retention or production deletion policy is relaxed. Executable tasks, safe fleet
retention and production qualification remain separate requirements.
