# HA and recovery qualification — October 29, 2026

**PARTIALLY TESTED. Engineering alpha; production remains BLOCKED.**

This bounded follow-up starts from maintained source
`e0521ad67d7f05e4bec55685cdbb91c96fd158f0`. Its existing push CI passed
16/16 jobs; that result does not qualify later changes. Select the follow-up's
exact head and CI when assessing incorporation.

## Existing implementation

`PgFencing` already acquires and renews server-clock leases, defaults to a
30-second TTL, and increments an epoch when an expired scope is acquired.
`FencedPostgresDestination` checks the owner, epoch and live lease while taking
the authoritative fence row lock in the effect transaction. Its operation
primary key rejects a second effect with the same agent/operation identity.
These are participating, single-authority PostgreSQL reference controls.
Copying their tables into two writable primaries does not provide consensus
or independent old-primary fencing.

The existing CI includes PostgreSQL worker-kill, backend-termination,
lease/fenced-destination, backup/restore, client TCP partition, stale-worker,
physical standby promotion and named-point WAL recovery tests and drills.
The replica drill deliberately stops the old primary before promotion.
The separate [historical two-host AWS report](AWS_TWO_HOST_QUALIFICATION_2026-10-13.md)
also records controlled stop-before-promotion and one sampled preserved
effect, with its original limits. Neither establishes autonomous,
split-brain-safe database promotion or a production RPO/RTO.

[Tenant migration](TENANT_MIGRATION_2026-10-14.md) freezes writers, checks a
real restored backup, and refuses rollback that would discard tenant-era
state. That offline contract is distinct from a rolling migration under
continuous multi-version traffic.

## First bounded unit: database wait settings

The lease and reference destination now reuse a small connection helper in
the existing `pg_fencing.py`; there is no additional HA framework. It retains
trusted connection options and appends the service SQL limits after them.

| Setting | Value | Boundary |
|---|---|---|
| `connect_timeout` | 5 seconds | libpq connection attempt semantics; not a universal bound on DNS or multiple configured endpoints |
| `lock_timeout` | 5,000 milliseconds | PostgreSQL server lock waits; not the entire transaction |
| `statement_timeout` | 10,000 milliseconds | PostgreSQL server statement execution; not application signing, every network failure or end-to-end recovery |

The helper adds no retries. The separate expiry fix below adds a lock before
renewal's UPDATE and separates destination locking from its clock read.
It preserves transaction lock coverage,
effect identity, receipt encoding and lost-ACK behavior. A database or network
error after a possible commit still leaves the caller uncertain. Preserve
UNKNOWN and held exposure until authoritative readback resolves that exact
operation. A timeout is not proof of failure or permission to send again.

The default lease is 30 seconds and accepted TTLs remain 0.5–3,600 seconds.
The SQL wait settings do not promise completion within the chosen TTL, and
they alone do not establish expiry correctness after waiting for a row lock.
The separately tested fresh-clock fix below addresses that specific case.
Connection setup, multiple SQL statements, transaction completion and a
potentially unbounded external signer cannot be added up into a fixed
end-to-end deadline from these settings alone.
In particular, server SQL cancellation does not imply a bounded synchronous
client receive during an actual network blackhole. A real client/network
deadline and partition qualification remain open for a separate unit.

An offline, source-frozen regression used a controlled `psycopg.connect`
backend and no database or sockets. On the baseline, 18 of the same 52 cases
failed because the required bounds/options were absent; 34 passed. With the
connection change, all 52 passed. The cases inspect all six connection entry
points, namespace preservation, weaker option overrides, propagated
connection/query/lock errors without retries, stale fence refusal, rollback
paths, lost ACK, duplicate effects, the existing TTL parameters and signer
refusal before connecting. These are connection/control-flow tests, not
observed PostgreSQL time budgets, physical effects or HA acceptance.

Reproduce the offline contracts with:

~~~sh
python -m pytest tests/test_pg_fencing_deadlines.py -q
~~~

Those earlier mocked results do not establish PostgreSQL behavior. The
separate actual PostgreSQL follow-up below now supplies bounded local
evidence; hosted CI for the new source remains NOT STARTED.

## Confirmed expiry defect and fresh-clock correction — October 29

Actual PostgreSQL reproduction confirmed that renewal's expiry predicate and
the destination's live-clock projection could be evaluated before a wait on
an unchanged fence row. If the wait ended after expiry, renewal extended the
expired lease and destination admission inserted an effect.

Renewal now locks an existing scope row in a transaction before issuing its
owner/epoch/fresh-clock UPDATE. Destination admission first locks an existing
row, then reads owner, epoch and the database clock in a separate statement,
retaining that lock through the effect transaction. Both refuse a missing
locked row before any later query, preventing an unlocked concurrent-insert
path. The live-lease check is an admission boundary after acquiring the lock,
rather than a hard deadline on transaction commit. No automatic retry or
uncertain-effect replay is added.

Each invocation is preserved separately; these counts are not summed:

| Invocation | Result | Meaning |
|---|---|---|
| October 27 actual PG attempt1 | 61 passed / 10 failed of 71 | Lock-observer precondition failed; not an expiry verdict |
| October 27 actual PG attempt2 | 64 passed / 7 failed of 71 | Three baseline deadline failures plus four actual baseline/helper-only expiry failures |
| Fresh-clock offline run | 54/54 passed | Mocked lock-before-clock contracts |
| October 29 current1 | Zero tests, preflight code125 | Local Docker daemon absent; source unchanged |
| October 29 current2 | 70/70 passed; no failures, errors or skips | Fixed source against local PostgreSQL16.13 and offline contracts |

The observer correction calls `pg_stat_clear_snapshot()` in its own
transaction. It does not reset server statistics or weaken a refusal
assertion. Earlier failures remain defect evidence.

Current2 has 55 offline cases, 12 focused actual PostgreSQL cases and 3 existing
PostgreSQL regressions. It verifies early missing-row refusal, real held-lock
timeouts, eight simultaneous acquirers with one live owner, stale-owner
handoff, lost-ACK cross-connection readback and duplicate-effect refusal.
Six expiry-under-lock cases cover renewal and destination admission at
read committed, repeatable read and serializable isolation. All require the
precise refusal family, unchanged original expired lease and zero effects.
A separate connection observes the selected isolation from the same case
DSN; worker-specific isolation telemetry is not claimed.

Three held-lock cases observe 5-second lock and 10-second statement settings.
Current2 recorded 41.734 seconds for its guarded runner and 34.03 seconds for
pytest. Eleven warnings remain in the log, including absent pytest-timeout
configuration and xunit2 property compatibility; actual XML case properties
were checked. The runner also has a 900-second outer timeout.

The exact 456-file tested working-source manifest SHA256 is
`6e6e57032dae6ddb529faf383db95c08507255c5187ea05ac7dcd9bb10c6fc10`.
All before/after pins matched. Runtime SHA256 pins are:

- `pg_fencing.py`: `4ccd8badac6d98d50aef3634f44dbf6104be0914203912743721ea6c9f572025`
- `fenced_postgres_destination.py`: `80d1ad2b6621669fb5e9ae2bb7cc177f2fb7556f6f6065aa7b54ac484a948781`

This dated documentation update follows the test run; it is separately
associated with the unchanged tested runtime/test bytes. Private receipts
are in `ha-bounded-deadlines-pg-qualification-20261029-current2/`.
Independent result QA is
`AgentBridge-HA-current2-independent-QA-2026-10-29.json`: 527/527 consistency
checks, rather than additional runtime tests or an external security review.

Reproduce against a disposable PostgreSQL instance:

~~~sh
python -m pytest tests/test_pg_fencing_deadlines.py tests/test_pg_fencing_wait_boundaries.py tests/test_pg_fencing.py tests/test_fenced_postgres_destination.py -q
~~~

The wait-boundary module requires `AGENTBRIDGE_TEST_PG`. Ordinary selection
uses the working implementation. Explicit
`AGENTBRIDGE_HA_COMPARE_BASELINE=1` adds immutable e052 comparisons, including
failures demonstrating old behavior; do not hide those failures or treat
that comparison as a passing suite.

The result establishes narrow single-writer local PostgreSQL behavior.
Hosted CI for this follow-up remains **NOT STARTED**. It does not qualify
autonomous leader election, physical failover, an actual client-network
blackhole, independently authoritative old-primary fencing, rolling
migration, RPO/RTO, production SLOs or universal exactly-once execution.

## Remaining checklist

| Existing task | Status | Required next evidence |
|---|---|---|
| P4-01a: audit existing HA and recovery | PARTIALLY TESTED | Review this dated scope and its exact source; retain earlier records as historical |
| P4-01b: concurrent election, renewal/transfer, epoch enforcement | PARTIALLY TESTED | Local contenders and post-lock expiry tested; autonomous election and graceful transfer remain open |
| P4-02a: WAL/PITR and checksum/readback | PARTIALLY TESTED | Archive/checksum manifest and restored application-state verification, beyond the existing one-table named-point drill |
| P4-02b: active migration and safe rollback | PARTIALLY TESTED | Preserve the offline freeze/no-data-loss-rollback contract; separately qualify continuous-workload, multi-version changes |
| P4-02c: split-brain and dual-writer prevention | PARTIALLY TESTED | Independently authoritative old-primary fence and actual two-endpoint partition/rejoin trials |
| P4-03: unified repeated HA measurements | NOT STARTED | Extend existing drills with source-bound per-trial loss, duplicate, error, UNKNOWN, RPO and RTO records |
| P4-04: startup/partition/restore/migration negatives | PARTIALLY TESTED | Local lock-expiry/concurrency negatives verified; operated partition, restore and active-migration trials remain |
| P4-05: current HA runbook | PARTIALLY TESTED | This document records tested local source; exact-head hosted CI and operated procedures still required |
| P4-AC: repeatable accepted old-leader/loss/uncertainty behavior | PARTIALLY TESTED | Representative operated trials, explicit thresholds and independent acceptance |

**Bounded manual promotion is not complete HA qualification.**

Internal engineering owns the narrow source/tests and measured drill
automation. The maintainer owns execution approval and the intended topology.
A destination/topology operator must establish a real independent fence and
readback authority; a copied SQL lease does not supply either. Production
SLOs and independent review require the responsible external operators and
reviewers.

Continue through the existing [operator drill checklist](PRODUCTION_OPERATOR_DRILLS.md),
[operated acceptance packet](P0_P2_OPERATED_ACCEPTANCE_PACKET_2026.md) and
[release restrictions](RC_INTERNAL_COMPLETION_AND_NOGO.md). Passing an
internal simulation, signing a statement or observing a single successful
sample does not provide universal exactly-once execution, independent
institutional custody or production acceptance.
