# Bounded private queued dispatch and recovery — October 22, 2026

The implementation is an explicitly nonproduction, operator-configured SQLite demonstration destination. The actual effect is one committed row containing the exact canonical `write(value)` action and its deterministic result. It makes no claim about arbitrary MCP tools, physical or financial transactions, a generic production transport, or remote network partition tolerance.

The private synchronous worker accepts exact tenant, owner, task, immutable intent digest and admission-link digest references. No HTTP worker, poller or public execution capability was added. The initial SUBMITTED-only preparation loader remains strict; a distinct admitted loader checks the exact WORKING admission event, operation fingerprint, consumed approval proof and held reservation. Full dispatch checks are repeated in the owned transaction after operation and budget locks and under the lifecycle lock. The original authorization deadline remains fixed.

An immutable attempt is committed before the destination call. Only that live committed branch may send. Existing attempts, expired leases, UNKNOWN state, process restart, dropped returns and cancellation requests never reconstruct a send capability. A crash after the marker and before the call can therefore leave zero effects and an unresolved held reservation. Missing, mismatched, stale or locally unrecordable readback remains UNKNOWN; no authoritative absence-proof/refund protocol is claimed.

The destination checks signed authorization, the exact action bytes, owner/task/operation/tenant/store/target bindings and fencing epoch. It samples its SQL clock while holding the transaction and rechecks the clock and exact fence after the signer callback immediately before INSERT. `committed_at` records transaction acceptance time, not a hardware or fsync completion clock. SQLite lock waits and the signed window are bounded; arbitrary trusted Python signer or local file-system stalls cannot be forcibly preempted by this synchronous worker. There is one fail-fast worker slot per configured kernel; replica cardinality remains an operator deployment bound.

The worker ignores its own returned result for acceptance and opens the existing independent read-only observer. Only a sealed observation from that configured adapter can enter the concrete finalizer. The existing evidence SDK verifies destination and observer signatures and the immutable result allowance. Result, owned-token accounting, operation outcome, legal lifecycle append and chained audit commit in one tenant transaction. Post-effect local failures, including the actual SQL audit-capacity trigger, roll back those local participants and retain UNKNOWN/exposure for later authoritative readback. Automatic settlement may compose with an outer transaction; its outer rollback cannot undo the destination effect.

Existing held budget and quota admission is grandfathered: dispatch validates the exact original token and amount and does not run `can_afford`, reserve, consume an approval or admit quota again. The operator budget setter rejects a spend limit below spent plus reserved exposure. Lowering quota limits affects future claims and does not invalidate held work. Current identity, declarative policy, target, cost, original authority and any newly required approval still gate a first attempt. This behavior is covered separately from admission-capacity rejection.

Pre-attempt coordinated cancellation commits a closed decision, refunds only that operation's exact held token, records a failed operation and legally cancels a nonterminal task. Post-attempt cancellation records one bounded request and does not refund or assert effect cancellation. Existing terminal task history is preserved. A later verified execution outcome is retained separately, without rewriting a legacy CANCELED event into COMPLETED.

New manual settlement additionally requires a current tenant operator permission and an independently signed review of the exact receipt/readback. The entry permission check alone is insufficient. SQLite retains its existing authority-before-tenant guard and reuses the tenant storage resolver through the actual local commit. PostgreSQL takes the shared 911005 fence once on the tenant settlement connection, then uses a bounded independent raw authority read connection to reuse `_current` and `_tenant` for the resource tenant. Kernel setup captures the actual callback/session-selected authority schema, role, session user, search path, server endpoint and database before any tenant fence exists; these cannot be inferred from libpq parameters alone. The raw read transaction selects the pinned schema and role with `psycopg.sql.Identifier` and asserts the resulting identity. Entry checks refuse later authority namespace/configuration drift. No original directory-connection query or Python mutex wait occurs after the tenant fence is acquired. The raw reader performs no bootstrap or second advisory-lock acquisition. A nonplatform principal must match the resource tenant; a platform administrator must still target a currently active tenant. The held fence blocks revocation until commit, and principal lifetime is rechecked after all settlement waits and audit writes. Unsupported mixed backends or different PostgreSQL endpoints/databases fail closed for manual settlement. Trusted namespace/role configuration changes require rebuilding the configured kernel. Manual attribution requires its own actual commit, rather than a caller-controlled outer savepoint.

Current signing journal policy is checked after the execution authority guard exits and before operation/budget locks. Descriptor or pin rotation currently blocks old attempted-task readback and leaves UNKNOWN held. A separately qualified historical-key recovery path is not implemented. An already accepted immutable result can be returned idempotently before a newly supplied review signature is checked; the signed-review requirement applies to new manual settlement and does not claim to create a new review on every repeated read.

SQLite execution schema use rejects any TEMP object shadowing the four execution table names at bootstrap and before every execution read/write under the same connection lock. Partial schema, unknown version/digest, unsupported columns/keys and extra unique restrictions are refused. Decisions, results and cancellation requests are immutable and bounded. This prevents supported local connection use from mistaking transient TEMP history for durable one-shot state; it is a persistence/schema correctness qualification, not a remote-tenant security claim.

Qualification separates real subprocess death/restart and independent read-only SQL observations from a local callback that drops a committed return. No local post-commit exception is described as actual remote network ACK loss. The first unit assumes one authoritative non-cloned authority/accounting history, operator-controlled signers/configuration, cooperative supported fence/authority writers, and the shared host-clock assumptions recorded by the destination contract. Database rollback/cloning, HSM custody, production deployment and arbitrary external transports remain unqualified.

The retained manifests and JUnit receipts provide exact source associations. Historical 162 destination tests and pre-review 247-pass combined results are retained as historical evidence. Final acceptance must use the corrected immutable source manifest and final focused/shared receipts; overlapping run counts must be deduplicated by test identity.

## Reproducible local qualification

Status: PARTIALLY TESTED. The frozen 25-file runtime/test manifest has SHA-256
`3391f06654e13934fdafec7a42f89fa6a8cd49ca9306d080eabdc2ed3351c99b`.
One final source-stable run produced 830 passed/31 expected backend skips from
861 distinct identities. New modules: 309 cases, 288 passed/21 skips; shared
regressions: 552 cases, 542 passed/10 skips. All skipped cases are SQLite
variants of PostgreSQL-only checks, with passing PostgreSQL counterparts.
The 288 new passes include 34 real PostgreSQL authority/accounting cases;
the destination effect remains the SQLite demonstration. No overlaps are summed.
The actual final run used PostgreSQL16 locally, Python3.12/Windows and the
existing disposable container. Docker restart/port interruption evidence is
preserved separately from product failures. Hosted CI must qualify its own
exact selected Git head; main’s earlier CI does not qualify this follow-up.

The seven new modules are `test_queued_destination_v2.py`,
`test_queued_dispatch_local_state.py`, `test_queued_dispatch_execution.py`,
`test_queued_dispatch_boundaries.py`, `test_queued_dispatch_postgres.py`,
`test_queued_dispatch_schema.py` and `test_queued_manual_reconciliation.py`.
The PostgreSQL job explicitly selects all seven; full SQLite jobs discover them.
Tests cover concurrent workers, queued/synchronous identity collisions, revoked
delegation and changed approvals, held budgets/quotas, transaction and five
subprocess death boundaries, dropped local returns, restart, exact readback,
manual authority changes and SQL isolation/schema failures. A callback that
drops a return is not evidence of a real remote network partition.

## Initial local performance observation

A separate bounded, full private SQLite SDK-route pilot used automated scoped
approval and concurrency1/2/4, each capped at24 requests. Effect/result/success/
charge counts, original token bindings, held UNKNOWN exposure and chained audit
all reconciled. Concurrency1 returned24 successes; concurrency2 returned23
successes/1 busy rejection; concurrency4 returned12 successes/12 busy rejections.
Busy post-admission work retained its exact UNKNOWN/reservation; the harness
never resent or refunded it. Success p50/p95/p99 were125/173/219ms at concurrency1,
219/304/343ms at concurrency2 and402/671/671ms at concurrency4. These are tiny
host-specific samples, including local SQL/evidence/audit; HTTP/network,
PostgreSQL performance, human delay and separately administered custody are
excluded. Optional RSS sampling was unavailable. Sustained performance, memory,
comparative controls and production SLOs remain unqualified.
