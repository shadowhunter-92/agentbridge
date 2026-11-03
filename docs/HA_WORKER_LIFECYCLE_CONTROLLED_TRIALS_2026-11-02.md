# Participating-worker controlled trials and maintained integration — November 2, 2026

**PARTIALLY TESTED.** Three source-pinned raw destination trials were accepted in a self-operated controlled PostgreSQL fixture. The maintained-main composition passed 193 targeted local cases. Its new hosted CI evidence remains pending. Production remains **BLOCKED**.

The [October 30 preparation](HA_WORKER_LIFECYCLE_PREPARATION_2026-10-30.md) is preserved byte-for-byte as a historical preparation record. Its untested statements describe that earlier cutoff. This dated document adds later observations and does not rewrite the first failures or raw reports.

## Source and implementation boundary

The integration baseline is maintained main `3b8a246101e72667e09bf0416a6b8cd307099bd1`, tree `ec09fbb86e15a2fa5fbceb8ac67acbd77098897a`. Its baseline core CI run [41283398658](https://github.com/shadowhunter-92/agentbridge/actions/runs/41283398658) passed; that result does not cover this uncommitted candidate or the new scenario step.

The only intended implementation change is the existing [disposable PostgreSQL drill](../tools/drill_pg_stale_leader.py) explicit `worker-lifecycle` scenario, with its [offline negative harness](../tests/test_pg_worker_lifecycle_harness.py). Original `_delayed_worker`, `run_disposable_drill` and the default `stale-leader` scenario remain unchanged. No product `src/` module, Apache-2.0 rights or CODEOWNERS rule changes.

The controlled trials used the earlier immutable 458-file source manifest `3cf9c681b3e7a5d75cddbc344e6fe092c21b458f3d854327d1931146ed9ae63d`, based on `ec1754bc57db4a7835163c82796b83a6cc6d6200`. The integration copies only the three intended HA files from that source, retaining maintained-main files elsewhere. The tool, fence implementation, fenced destination and receipt verifier are byte-identical to the controlled-trial versions. The new composition has targeted local qualification; hosted verification remains open.

| Bound source | SHA256 |
| --- | --- |
| `tools/drill_pg_stale_leader.py` | `1d2b09aa5c1ed447fccd94c77e5da1d6039cedfe9a74155ab7cf9ff7031ea781` |
| `tests/test_pg_worker_lifecycle_harness.py` | `bc8b0dae2a34ce9d5d96d424e78f1e650a670ac07b9b2cddc377f80d734cd743` |
| `src/governance/pg_fencing.py` | `34404d6714ba345a20ae10b9dbd9f706da15279bb38dfa865221f68a5fe6f6d9` |
| `src/governance/fenced_postgres_destination.py` | `6141a1ff8ec14469ca53212571a473e88dbae51687bd89631d11e5a19b653d72` |
| `src/governance/destination_receipts.py` | `9322689efcd65de8deb01f0f554dcbb12aa8520158ef0f5699db3f083afcfdab` |

## Actual observations

The root-owned V5 supervisor accepted three serial trials on PostgreSQL 16.13, Python 3.12.10 and Windows. It used a freshly checked numeric-loopback port to the existing exact disposable container and exact `agentbridge_test` database. No cloud resource, physical promotion or network partition was involved. Raw reports, process witnesses, source associations and authoritative rows remain retained outside Git. A separate agent's saved-result review passed 101 checks, including receipt signatures, exact readback, stale refusal and natural cleanup. This is internal review of self-operated observations, not institutional independence.

Each old participant acquired epoch 1, acknowledged two renewals, deliberately drained renewal and was observed expired using the database clock. One replacement acquired epoch 2 and attempted one effect with an injected lost acknowledgment. The old worker resumed for precise stale-renewal and separately named stale-effect refusal probes. A separate connection observed the exact replacement operation/fingerprint and the preselected-key receipt verifier checked its signature. No uncertain effect was resent.

| Trial ID | TTL / renewal (s) | Epoch | Replacement effects / stale effects | Drain to observed higher epoch (s) | Drain to observed replacement effect (s) | Raw elapsed (s) |
| --- | --- | --- | --- | --- | --- | --- |
| `765ddb57dbc5419c8d5af92f888d8f1f` | 3 / 0.25 | 1 → 2 | 1 / 0 | 4.547 | 4.641 | 7.672 |
| `d2d9a21f9d63490287904e29a2dabf18` | 1.5 / 0.2 | 1 → 2 | 1 / 0 | 3.516 | 3.625 | 6.484 |
| `4e1a82548a8a484680f508c12e8bf307` | 4.5 / 0.3 | 1 → 2 | 1 / 0 | 6.469 | 6.969 | 10.157 |

All three parent observation windows were 30 seconds. The accepted source-pinned runner receipt elapsed time was 34.625 seconds; the separate root supervisor elapsed time was **35.266 seconds**. Those totals include their respective setup, observation and cleanup work. They are not added together or treated as a performance sample population.

Parent-observed drain timings include scheduling, expiry polling, queue delivery and signed readback. They exceed a lease TTL in these observations and are not database RTO, automatic failover time, a one-TTL fencing guarantee, production SLOs or cross-host clock measurements.

The raw `source_commit` and `source_manifest_sha256` remain null; outer immutable source associations supply their binding. `governed_unknown_count`, `governed_reservations`, `workload_rpo` and `physical_database_failover_rto` remain null. This destination-only drill does not exercise governed admission, budgets, reservations, a replicated physical database or recovery of a consequential remote transaction. A signed receipt authenticates this signer's statement; it does not prove an external physical or financial effect.

## Retained evidence

Local evidence directory: `work/tenant-authority-20261014/ha-worker-lifecycle-prepared-20261030/evidence/actual-pg-qualification-20261101-attempt2`. The directory date is the retained attempt name; the actual accepted receipt was recorded on November 2 at 02:46:43 UTC. No earlier failed attempt or raw result was overwritten.

| Raw report | SHA256 |
| --- | --- |
| `trial-01/raw-report.json` | `fc53f5f4ee9a17f67047595f075b1ce2b8073103e6851480edb477e44e869327` |
| `trial-02/raw-report.json` | `8d564b5ddb29ca771e883df41b3f605ef6aa9996369ca6f99ea6780854acf1f8` |
| `trial-03/raw-report.json` | `9137a797200195b604287485af413d1f6c06de39bee03fa305869809946f4a2f` |

Source-pinned runner receipt SHA256: `09318d0f894747851a7b1f179eb559570c80340e5fac08134c5370da2bacb2f8`. Root supervisor receipt SHA256: `7faf948c0c78e65c65f528de796c7a50e27e949db8d9d2fc7f9abc5cf1d75279`. Credentials and private signing bytes are not included in this document. These local records are not a published artifact, independently administered custody or external acceptance.

## Maintained-main local qualification

On November 2 at 07:59:56 UTC, the 464-file working composition based on main `3b8a246101e72667e09bf0416a6b8cd307099bd1` passed **193 distinct cases, zero failures/errors/skips**, in 47.812 seconds measured by its qualification runner. All source bytes remained unchanged during execution. The 123 offline worker-harness cases and 70 existing fencing/deadline/destination regressions are one combined run; overlapping historical runs are not added to this count.

The five modules were `tests/test_pg_worker_lifecycle_harness.py`, `tests/test_pg_fencing_deadlines.py`, `tests/test_pg_fencing_wait_boundaries.py`, `tests/test_pg_fencing.py` and `tests/test_fenced_postgres_destination.py`. Positive and negative coverage includes uncertain acquire/renew responses, no replay or regenerated identity, stale epochs, expiry while waiting, receipt/readback failures, resource cleanup, bounded contention and durable lost-ACK readback. Real PostgreSQL cases used the same exact disposable fixture and database with a freshly observed loopback port.

The local receipt is retained at `work/tenant-authority-20261014/ha-worker-lifecycle-main-qualification-20261102-attempt1/receipt.json`, SHA256 `7dc53620e162f82a08c5383e47d7cc77918341fca5575a4ad5ef1218a3e46c95`; its source manifest is `1675dc2e566d2a92d0461c90cd55a146a4ebb2b864f2b12771c25759f8ec41dd`. This paragraph is a later documentation-only addition to those tested bytes. The tool, tests, runtime and CI proposal remain unchanged. The GNU/Linux CI command has not run locally on Windows; its hosted execution remains a separate gate.

## CI proposal and next verification

The existing `postgres-stale-leader-drill` job already creates the exact local PostgreSQL service, numeric `127.0.0.1:5432` route, `agentbridge_test` database and disposable CLI opt-in. A second step after its unchanged default drill selects only `AGENTBRIDGE_STALE_LEADER_SCENARIO=worker-lifecycle` and a separate `postgres-worker-lifecycle-drill.json` path. GNU `timeout` supplies an additional 90-second outer bound with a 10-second kill-after limit. The existing nine-minute job bound and service configuration remain. Both JSON reports are retained by the existing always-run artifact upload.

The new scenario rejects `prod`/`production`, alternate or nonnumeric hosts, a database other than exact `agentbridge_test`, missing explicit port/user/password and invalid timing. It reconstructs `hostaddr=127.0.0.1`, public search path and existing 5-second connect, 5-second lock and 10-second statement limits. Those SQL limits do not prove a hard client receive deadline under a blackhole. CI is a controlled disposable route, not destination-operator acceptance.

The new harness is automatically discovered by existing full Python 3.11/3.12 and Windows suites. The focused PostgreSQL module list, existing assertions and original default drill are retained. Earlier offline evidence belongs to its original exact source; the maintained-main regressions above now supply separate composition evidence. Publication requires owner approval; the new exact-head hosted run must execute the additional CLI step before any main-merge review. No new hosted result is claimed here.

## Remaining acceptance

- **PARTIALLY TESTED:** controlled cooperative drain/expiry, higher-epoch replacement, one lost-ACK effect and exact self-operated readback. This remains a bounded raw-destination scenario.
- **PARTIALLY TESTED:** maintained-main composition, with 193 targeted local passes and preserved default behavior. Broader exact-head hosted verification remains open.
- **NOT STARTED:** new-head CI; forced participating-worker process failure, actual acquire/renew response-loss injection, real partition/rejoin, concurrent cold migration and full governed task/accounting recovery through this route.
- **BLOCKED:** physical HA acceptance requires an authoritative fencing/election topology that prevents divergent writable primaries, measured repeated RPO/RTO, safe restore/rollback and partition/rejoin evidence. This scenario adds no such promotion capability.
- **BLOCKED:** separately administered destination/readback custody, independent security/evaluator evidence, pilot acceptance and unrestricted consequential-action production.

No automatic replay of uncertainty, operation-ID regeneration, refund, eviction, legal-hold removal or production target enablement is added.
