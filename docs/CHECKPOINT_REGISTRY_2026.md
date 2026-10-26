# Bounded checkpoint registry — October 24, 2026

**VERIFIED IN CI for the bounded checkpoint implementation; production NO-GO.**
This is the requested current index to the existing
[checkpoint capacity implementation and historical evidence](CHECKPOINT_CAPACITY_2026.md).
It adds no second registry or authorization/evidence implementation. This
documentation follow-up was reviewed and owner-merged in PR #74. Reviewed
source `9aaf6a1a0a460d3824ad2966a57f8c5f575bdfae` passed
[24 jobs across seven workflows](https://github.com/shadowhunter-92/agentbridge/actions/runs/40161311373).
Actual main `c154b28c34cfeab927753e51b93595cc1b485810` separately passed
[16 push-CI jobs](https://github.com/shadowhunter-92/agentbridge/actions/runs/40187737269).
These source-specific results do not qualify later changes or external destinations.

PR #72 merged corrected source `143c93d9d4230c3604c976563a6d1b228c0dae30`
into actual main `635288a76750bcd01d9fc9268dd9fe29897b269a` with explicit
owner approval. The reviewed source passed
[24 jobs across seven workflows](https://github.com/shadowhunter-92/agentbridge/actions/runs/40068956312).
The actual main merge independently passed
[16 jobs](https://github.com/shadowhunter-92/agentbridge/actions/runs/40070457044).
The main tree equals the reviewed source tree; these remain different commits
and different CI executions.

| Retained resource | Default | Trusted configuration ceiling |
| --- | --- | --- |
| Checkpoint records | 10,000 | 100,000 |
| Actual stored UTF-8 JSON bytes | 16 MiB (16,777,216) | 128 MiB (134,217,728) |
| Newly inserted checkpoint bytes | 8 KiB (8,192) | 64 KiB (65,536) |

`AuditTrustStore.checkpoint_capacity()` and `set_checkpoint_capacity(...)` are
trusted operator library methods, not public configuration endpoints. Actual
SQL COUNT/SUM measurements share the writer fence; there is no cached usage
counter to reset. Existing over-limit history and policy shrink retain every
row. New growth above any limit fails in the governance transaction.

**No eviction, refund or replay is added.** Checkpoints, legal holds, audit rows,
UNKNOWN operations and held reservations survive saturation. Mutation or replacement
of checkpoint history, policy removal and supported PostgreSQL TRUNCATE bypasses
are refused. Trusted policy updates remain supported under the writer fence. Capacity
does not grant a retention entitlement or permission to delete held evidence.

| Acceptance boundary | Existing implementation/tests |
| --- | --- |
| Saturation retains UNKNOWN, exact reservation, legal hold and audit | [Checkpoint tests](../tests/test_checkpoint_capacity.py), `test_saturation_preserves_unknown_reservation_hold_and_audit` |
| Concurrent independent SQL connections cannot overrun limits | Same module, `test_concurrent_independent_workers_cannot_overrun`: 12 connections, nine successes/three capacity denials under a nine-row policy |
| TEMP redirection and SQLite catalog-case aliases fail before changes | Same module, reserved-name/case matrices and PostgreSQL TEMP tests |
| Both PostgreSQL checkpoint tables must be ordinary permanent tables | Same module, `test_postgres_checkpoint_tables_require_ordinary_permanent_relations`; UNLOGGED rejection is a catalog test, not crash-loss qualification |
| Exact checkpoint JSON/policy/holds survive real backup and restore | [Migration tests](../tests/test_tenant_migration_checkpoint_capacity.py), `test_real_checkpoint_restore_assignment_and_rollback`; actual SQLite backup or PostgreSQL dump/restore |
| Stale transaction snapshots cannot over-admit | Checkpoint tests, RC/RR/SERIALIZABLE growth and policy-API cases; supported writes require READ COMMITTED |

The new Phase 1 follow-up adds `test_real_restore_rejects_checkpoint_json_text_drift`.
On October 25, its two focused cases passed on SQLite and PostgreSQL with no
skips or failures (source manifest SHA256 `f003ea26fe9cb8c1dc055f41eda9a9787cd10ded0115a07cbc2be847faa1b9a5`;
result SHA256 `f4e47e45a467a12c11a90cfd7e71196f9ae1f5dcea84296ff07e48df5c4f7dc9`).
A disposable real restore receives one valid-JSON whitespace change; both saved
UPDATE guards are restored before verification. Verification refuses the exact
historical-content mismatch and preserves altered target bytes, source bytes,
policy, markers, holds, UNKNOWN reservations, budget and audit. All 100 runtime
Python runtime files are unchanged. Status for this negative is **VERIFIED IN CI**
at reviewed source `9aaf6a1` and actual main `c154b28` in the runs above; it was
absent from the older `143c93d` and `635288a` CI executions. The local two-case
result and the later hosted results remain separate evidence.

Historical ccdd1a5, d3a6072 and 5b6981e each passed their own 24 jobs.
Historical `7a10a5f` passed 23/24: a stream-cap observation test failed.
That failure is retained, not rerun or reclassified. The subsequent 143c93d
test-only correction passed 24/24 before the approved merge. It preserves
all 100 runtime files and tests one immediate HTTP 429 while the stream is active,
then separately bounds revocation cleanup. A controlled delay reproduced an
observation-race failure mode; the exact uninstrumented CI cause is not claimed.

Other evidence journals, key histories, witness/receipt stores and reconciliation
bundles require their own policies. These JSON bounds do not cover physical
pages, indexes, WAL, backups or fleet disk quotas. Reference-indexed hold-safe
retention, large-history latency/contention, recovery headroom, independent
custody and production qualification remain open. Earlier draft PostgreSQL
routine bodies are deliberately refused rather than repaired at startup; a
separate stopped/drained known-predecessor upgrade is still being qualified.
No online migration, rolling-version compatibility or universal exactly-once
claim follows from this registry.

Follow the [complete nine-phase checklist](ENGINEERING_PHASE_PROGRESS_2026-10-24.md)
and [blocker register](BLOCKERS.md). A signed checkpoint authenticates its
signer's statement about an audit head; it is not independent proof of a
physical or financial effect. The isolated replay-capacity item remains
**BLOCKED** and untouched.
