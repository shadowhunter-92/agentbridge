# Durable retained-task capacity — October 16, 2026

Baseline: `573826fcb29039e9438ea5a8746a21faf9f7b409` (PR #66,
24 successful hosted checks). Existing active-task and event-count limits did
not bound accumulated terminal task history across owners or worker restarts.

The existing lifecycle now has a durable namespace-wide historical-task cap:
default 10,000, operator-configurable from 1 to 1,000,000. Counts include every
owner and terminal task. New task admission stops at capacity. Completion and
cancellation can still append their existing bounded events; no history, UNKNOWN
operation, reservation or held evidence is deleted to make room. This is a task
count limit, not an event-byte, evidence-byte or fleet stream limit.

Policy and metadata tables initialize only when both are absent. A missing row,
unsupported version, wrong relation kind or one missing table rejects startup
instead of restoring defaults. This is application recovery validation, not
tamper-proof protection from the database owner deleting both tables/guards.

Every create checks actual retained count under the existing SQL task lock.
Private tenant stores additionally install an INSERT trigger so supported older
tenant workers cannot omit the Python capacity check. PostgreSQL trigger reads
are schema-qualified, invoker-rights and serialized with advisory key 911006.
SQLite uses its writer boundary. New policy tables receive tenant write guards
in the bootstrap transaction. Operators/database owners are trusted; arbitrary
owner-level SQL, DDL, TRUNCATE or forged application code are outside this guard.

Standalone legacy stores retain the application-level cap without tenant SQL
triggers. Their historical ordinary-table migration contract stays intact. On
tenant helper bootstrap, database enforcement is installed. Existing snapshots,
events and signatures are not rewritten. Offline rollback remains conservative
after runtime helpers introduce schema objects; do not discard those objects or
tenant-era work to force an older schema through rollback.

`TenantSession.task_history_capacity` requires budget-read permission;
`set_task_history_capacity` requires policy-write permission and an exclusive
authority guard. Policy and its administrative audit commit together. A decrease
below retained usage is rejected. HTTP GET/PUT
`/v2/operator/task-history-capacity` provides the same strict tenant-scoped
controls; body `{"max_tasks": 10000}`. Requests select no database or namespace.
This administration endpoint does not create executable tasks.

Tests cover count saturation across owners/restarts, terminal-history retention,
tenant separation, competing workers, raw older-worker SQL, actual PostgreSQL
blocking/visibility, damaged policy recovery, immediate legacy-write guards,
operator HTTP permissions/strict validation, audit/outer rollback, and unchanged
task/migration/tenant regressions. Exact results/commit/CI belong in the phase
report; a test file alone is not acceptance.

COUNT reads actual storage rather than an independently driftable cache. Large
history/count contention and default capacity sizing are not performance SLOs.
Per-owner active/event limits still require identical replica configuration.
No claim of user-level historical fairness, safe retention, full protocol
conformance, executable tasks, external custody or production acceptance.
Unrestricted consequential-action production remains NO-GO.
