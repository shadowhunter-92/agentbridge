# HA critical path — November 12, 2026

**PARTIALLY TESTED. Actual forced-stop/acquire-reply-loss/renew-reply-loss
trials: 3 accepted. Production remains BLOCKED.**

This current worktree report continues the immutable 468-file review packet.
That packet retains its pre-execution report. Root's separately reviewed
attempt 2 receipt is bound by SHA256
`59209ce12490424e58f4b6693b788a1a39b7617b157293f2450ed94a52fe423c`.
The first attempt's stopped-fixture refusal and zero-trial evidence remain
preserved; root restarted only the same owned fixture before a fresh review.

1. **Baseline / ending:** isolated branch `fix/ha-forced-stop-2026-11-04`
   remains based on `35f37222597341d2c23e9cd9d0baddf1e36f99f7`. No commit
   or hosted qualification is implied by this report.
2. **Audited:** existing lease/destination fencing, queued dispatch/recovery,
   shared process-crash tests, prepared November 5 supervisors and evidence.
   The four pre-existing dirty files and earlier evidence are retained.
3. **Existing controls:** database-clock expiry; epoch checks after row locks;
   single durable dispatch marker; one attempt; exact reserved exposure;
   signed, identity-bound readback; UNKNOWN without automatic resend.
4. **Changes:** the existing stale-leader CI job now selects all three explicit
   faults with separate reports and 90-second outer timeouts, preserving the
   original stale-leader and cooperative worker-lifecycle steps. A dated
   successor local operator uses explicit runtime/hash/exclusive-path gates
   before grant or directory creation. Optimized compilation, non-isolated
   execution and unreviewed interpreter contexts must refuse before reads,
   writes or child start. November 5 operators and packets remain historical.
5. **Tests:** the earlier 206 offline harness passes remain historical.
   Current source-bound offline harness/operator qualification is 256 passed
   with five process cases deselected, zero errors/warnings/denied actions, in
   `work/ha-faults-offline-20261112-attempt2/receipt.json`, outside this checkout.
   Its byte pins and JUnit results determine acceptance; a test definition is
   not an actual process fault or database qualification. The preserved first
   November 12 attempt encountered sandbox temporary-directory ACL failures.
6. **CI:** the workflow addition has not run on a hosted candidate. Local
   syntax/scenario checks do not qualify Ubuntu process termination or hosted
   PostgreSQL results. Exact candidate CI remains open.
7. **New defects / limitations:** the November 5 outer used `assert` for
   pre-write trust checks and lacked an explicit interpreter guard. Python
   optimization removed those checks. The successor replaces them with
   `if`/`raise` gates and rejects both optimized bytecode modes. No product
   runtime fencing architecture is added; this checkout uses the existing
   governance modules and has no `src/ha/worker_fence.py`.
8. **Internal partials:** three root-operated local fault trials accepted in
   27.265 seconds internally (28.515 seconds under the independent outer).
   Their artifact hashes, signed readback and native cleanup were rechecked.
   The two PostgreSQL governance crash cases are IMPLEMENTED / UNTESTED:
   their separately owner-approved operator refused at its read-only native
   role prerequisite because the lab grants TEMP to PUBLIC. No governed crash
   trial or role/schema write occurred. Physical service
   partition, end-to-end hard deadline and composed candidate qualification
   remain separately open until matching evidence exists. See the table below.
9. **External / permissions:** root reviewed the three-fault successor and
   executed the accepted bounded run. Automatic approval review initially
   rejected the separate governed-crash operator before process creation
   because retained login roles/schemas and scoped trigger DDL required owner
   approval. The owner then explicitly approved at most four isolated roles,
   six schemas and scoped initializer trigger changes. Root ran the exact
   pinned candidate, which safely refused before those database writes. That
   approval does not authorize changing PUBLIC privileges or weakening native
   tenant guards. Only the existing disposable PG16 fixture is in scope.
10. **Branch / PR:** the recorded qualification freeze preceded the local unit
    commit and draft publication. Exact later commit/PR/CI evidence belongs in
    the coordinating phase register. No main merge, branch cleanup, AWS,
    outside correspondence or release activity is included.
11. **Security / release gates:** production NO-GO; P35 remains untouched.
    Lease method return loss is application-boundary injection, not a real
    dropped packet. Forced stop intervals are not physical failover RTO.
    Local readback is not independent custody or permission to resend.
12. **Next:** retain the three accepted bounded fault results and governed
    preflight refusal; review the local candidate for commit/CI. The native
    crash fixture prerequisite and full-route deadline/partition controls
    remain open. No new runner attempt or privilege change is authorized here.

| Requested failure | Existing evidence and exact boundary | Current gap / status |
| --- | --- | --- |
| Crash after dispatch before ACK | `test_queued_dispatch_execution.py` exits a real SQLite child after a demo destination effect commits and before adapter return. It retains UNKNOWN/exact reservation and recovers by readback without acquire or commit. `test_queued_dispatch_postgres.py` historically used exceptions at this boundary. | IMPLEMENTED / UNTESTED. Owner-approved native operator refused read-only prerequisite (PUBLIC TEMP), zero trials. Its target remains the SQLite demo destination. Actual PostgreSQL destination dispatch death remains unqualified. |
| Crash after ACK before settlement | SQLite `after-result-insert` death rolls back uncommitted settlement; generic atomic-settlement process death preserves UNKNOWN/exposure. New queued `after-ack` hook exits only after commit returns, before first readback/settlement. | IMPLEMENTED / UNTESTED. Same read-only native fixture refusal, zero trials. No claim for external target ACK durability. |
| Worker/gateway partition | `test_r3_loopback_transport.py` drops a real target TCP response after an in-memory effect and retains UNKNOWN/reservation. PG backend-termination tests kill connections around claim commit. | No actual worker/gateway partition, bidirectional service cut, rejoin or physical HA evidence. Deferred and unmatched. |
| Dual claim | `test_queued_dispatch_postgres.py::test_postgres_concurrent_independent_workers_commit_one_attempt` races independent workers; PgFencing wait-boundary tests race eight contenders and observe one winner/effect. Dispatch marker and unique operation identity prevent a second send. | Existing coverage; current source-bound PG rerun/composed qualification remains open. No universal exactly-once claim. |
| Contention deadline | `test_pg_fencing_wait_boundaries.py` holds the real fence lock for acquire/renew/commit and requires bounded failure/zero effects; expiry-after-wait is checked across three isolations. | Does not establish hard client blackhole timeout, full gateway/worker deadline under arbitrary contention, sustained SLO or physical RTO. Deferred and unmatched. |

All new real crash tests reuse the existing dispatch worker/reopen helpers and
governance stores. They add no alternate lease implementation. The prepared
local three-fault supervisor remains limited to active owned worker stop and
two successful lease-method returns deliberately withheld from the worker;
it does not run the separate governed crash-window test cohort.

## Root-operated local fault results

| Fault | Observed result | Boundaries |
| --- | --- | --- |
| Active owned worker stop | The exact old PID was live before owned termination and stopped afterward. Its epoch 1 lease expired; successor epoch 2 produced one signed succeeded effect. Stale-token probes produced zero effects. Stop-to-higher-epoch interval was 5.422 seconds. | Controlled application/process handoff; this interval is not physical failover RTO or a full governed task deadline. |
| Committed acquire return withheld | Worker stopped UNKNOWN; separate connection observed the exact recorded old-worker epoch 1 lease and zero effects. | Application method-return loss; no real network reply drop, automatic retry or settlement. |
| Committed renew return withheld | Worker stopped UNKNOWN; separate connection observed the exact recorded old-worker epoch 1 lease and zero effects. | Application method-return loss; no real network reply drop, automatic retry or settlement. |

All three native Job witnesses accepted, retained the application cap of three
and at most one pinned console helper, and finished with empty native PID
lists. Cleanup required no unexpected forced Job termination, reported no
errors/timeouts and closed each kill-on-close Job. The frozen source remained
468 files with the exact reviewed manifest. `governed_unknown`, physical RPO
and physical RTO remain null. The separate two PG governance crash cases are
still unexecuted; worker/gateway partition and full-route hard deadline remain
unqualified.

## Governed crash-window prerequisite refusal

After the owner's scoped approval, root invoked the exact reviewed harness
`7faec790f20bf2748d1e0801c5e87f6aa6b985a972e10a74aa6a257dc2b2780f`
with proposal
`e549c9f16bf7d8e7888c190b301d848113c8208330a1010de87874f5fdde690e`.
The receipt in
`work/tenant-authority-20261014/ha-governance-crashes-actual-20261112-attempt1`
records `accepted: false`, zero trials and a
`native-role-prerequisite-read-only` refusal after 0.829 seconds. It confirms
the same exact owned container, PG16.13, primary mode, a fresh loopback mapping
and `public_TEMP: true`. Database-wide privilege changes are false.

The code checks this prerequisite before creating trial directories, roles or
schemas. Only claim, preflight and receipt artifacts exist for that invocation.
The receipt's `retained_schemas_and_roles` field describes its retention policy;
it is not evidence that any were created. No trial fixture or target effect
was created by this refused run. Native TenantPostgresStore and registry guards
remain unmodified, PUBLIC privileges remain unchanged, and the immutable
468-file source is unchanged. Forty fake-only operator controls passed before
this invocation; they do not qualify the two governed crash cases.
