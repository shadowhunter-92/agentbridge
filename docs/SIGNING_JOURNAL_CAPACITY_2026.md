# Retained signing-revision capacity — local qualification

This unit bounds the existing `SigningTrustJournal` history in one SQL
namespace. It adds no signature format, authorization path, public endpoint,
history deletion or eviction. Both `destination` and `readback` domains share
one persisted policy. SQLite and PostgreSQL implementations are locally
**PARTIALLY TESTED**. This is an engineering alpha; local qualification is not
hosted CI, production acceptance or independent custody. PostgreSQL new growth
and capacity policy operations require READ COMMITTED isolation and refuse
REPEATABLE READ or SERIALIZABLE writes explicitly.

| Limit | Initial policy | Allowed alpha ceiling |
| --- | --- | --- |
| Retained revisions across both domains | 10,000 | 100,000 |
| Actual stored UTF-8 envelope JSON | 64 MiB | 512 MiB |
| One new stored revision | 256 KiB | 1 MiB |

Limits must be positive integers, and the entry limit cannot exceed the total
byte limit. These bounds are alpha resource controls, not measured production
sizing. A valid 128-key signed envelope whose key IDs contain 128 astral
characters each was observed at 212,382 stored bytes using the current
`ensure_ascii` encoding; the default entry allowance accommodates that sample.
The byte sum uses the stored SQLite BLOB length, including older valid JSON
stored with literal Unicode. It is not the parsed string length or database
file size.

The policy table begins empty so an otherwise empty legacy namespace can still
receive its initial tenant binding. The first successful new revision, trusted
capacity inspection or trusted setter initializes the defaults. The setter may
participate in `sql_atomic` and an optional transaction-bound audit callback;
an aborted outer transaction or audit callback rolls back policy and audit
writes together. Only trusted operator library code may choose policy; there
is no request-selected tenant or public configuration route.

SQLite's existing `BEGIN IMMEDIATE` journal ownership serializes publication.
Direct older SQL writers encounter statement-atomic bounds and append-only
triggers before a duplicate insert can use `REPLACE` or `IGNORE` to remove or
mask history. No cached count or byte counter can drift independently of the
retained rows. SQL `COUNT` and `SUM` are read under the writer boundary. Exact
already-persisted latest envelopes remain idempotent at or above a limit;
new growth above any limit fails without changing history or a local revision
floor. Existing over-limit history survives installation, restart and a
policy shrink. Existing signatures, predecessor links, staged transitions,
independent controller keys and external minimum revision floors still apply.

Capacity denial is **not revocation**. If an emergency signed revocation cannot
be appended, the old committed revision and active key remain the truthful
policy. Operators must stop or drain affected execution, inspect usage and use
the trusted bounded policy raise before retrying the exact signed change. At
the absolute ceiling, keep affected execution disabled until an explicitly
reviewed maintenance or capacity migration is available. There is no automatic
revocation reserve, automatic limit increase, key disappearance, history reset,
refund or replay of uncertain effects.

Startup and offline snapshots verify exact supported table and trigger
definitions, key shape, stored value types, UTF-8 storage and absence of
reserved TEMP shadow objects. An installed policy with missing history, missing
metadata or modified/partial triggers is refused; startup does not silently
repair it. A deliberate privileged database owner can remove or rewrite these
objects, so these are supported-writer controls rather than independent
custody. The unchanged corrupt-history test explicitly removes the disposable
SQLite UPDATE guard before injecting a bad signature, retaining the
cryptographic history-verification check.

The October 23 catalog review additionally reproduced uppercase/mixed-case
TEMP history and policy names being mistaken for durable storage. Reserved
TEMP checks now use SQLite's ASCII case-insensitive identifier comparison.
Managed permanent table and trigger names must retain canonical spelling;
variant names are refused without repair, including pre-installation triggers
that `IF NOT EXISTS` would otherwise silently retain. The corrected local
SQLite run has 91 passed and 36 expected PostgreSQL skips, 127 distinct cases.
The earlier 75-pass snapshot and failed-before case evidence remain historical
records. No overlapping test-run totals are added together, and no PostgreSQL
capacity or hosted CI acceptance is inferred from those earlier SQLite results.

PostgreSQL uses the existing shared advisory 911005 compatibility barrier, then
the signing coordination singleton's UPDATE lock. New statement-level SQL
fences take that order before unique-index ownership for direct older writers
too. Settlement's existing SHARE lock still excludes those writers. Actual
`COUNT` and `SUM(octet_length(envelope))` execute under that serialization;
READ COMMITTED is required because locking alone does not refresh an older
transaction snapshot. History UPDATE/DELETE/TRUNCATE and policy
DELETE/TRUNCATE are refused. A duplicate `DO NOTHING` insert remains a
zero-growth SQL operation; managed idempotency verifies the exact signed head.

PostgreSQL bootstrap and read-only snapshots require ordinary permanent
tables and refuse unlogged/temporary/partitioned/foreign or row-security-enabled
relations. Exact supported columns, keys, CHECK constraints, singleton state,
function bodies/attributes and trigger wiring are qualified before use. Three
known functions pin `search_path=pg_catalog`, schema-qualify their target tables
and retain invoker privileges. Complete new installation is distinguished from
missing/changed/overloaded functions or partial triggers; startup does not
repair an existing partial installation. Offline migration admits only those
exact qualified routines. The RLS catalog refusal is unsupported-schema
qualification, not a nonowner hidden-row/undercount or custody claim.

For the final RLS catalog draft, a local SQLite run passed 91 cases with 36
expected PG-only skips, and a focused cross-backend selection passed 25 cases:
19 actual PostgreSQL cases and 6 SQLite restore/tenant positives. A broader
preceding draft passed 163 cases with 4 expected SQLite-only skips, 167 distinct;
that earlier source is retained separately and is not a full run of the final
RLS draft. The final delta is the catalog-flag refusal, six negative cases and
documentation. These overlapping runs are not summed and establish no hosted
CI, staging, production or independent acceptance.

The capacity policy also begins empty on PostgreSQL, preserving its existing
normal tenant-binding-before-journal order. The preexisting signing coordination
singleton is already nonempty after journal initialization; a legacy journal
initialized before tenant binding still requires explicit populated-state
migration. No new policy row is manufactured during bootstrap to change that
contract.

Offline same-backend tenant migration includes the exact policy, triggers and every
history row in its complete backup/restore manifest. Snapshot verification is
read-only. Holds, UNKNOWN operations, reservations and audit records are kept;
this unit adds no retention entitlement. A database-only backup cannot supply
an independently retained minimum revision floor. A restored valid older
journal is refused when its external floor is newer than the stored head.

The existing SQLite `publish` method owns `BEGIN`/`COMMIT`; publication inside
an already-open outer SQLite transaction remains unsupported and is tested as
such. The new policy setter's savepoint composition must not be read as an
extension of publication semantics. The original capacity unit retained a
PostgreSQL limitation: publication could advance its in-memory floor after a
nested savepoint but before an enclosing transaction committed. A subsequent
[publication ownership extension](SIGNING_PUBLICATION_BOUNDARY_2026-10-24.md)
refuses an existing PostgreSQL transaction before publication can change history
or a floor. It holds the store lock through its own commit and floor advance.
Capacity-policy/audit savepoint composition remains supported. This is a bounded
library-publication contract; it does not promise arbitrary transaction
composition, safety against a privileged raw-SQL owner, or independent custody.

Logical envelope bytes do not include indexes, pages, WAL, backups, authority
rows, separate destination/witness journals or every tenant payload. General
disk quotas, emergency recovery headroom, independent custody and reference
indexed retention remain separate work. History loading already verifies a
complete domain; strict schema/usage checks add namespace scans under the
writer lock. Large-history startup, settlement, publication and contention
need measurements before a production performance claim.

Source and test evidence for this local unit is retained outside the repository
under `signing-journal-capacity-evidence-20261023`. Local test results do not
constitute CI, controlled staging, external acceptance or a release decision.
The isolated replay-capacity candidate remains **BLOCKED** and untouched.
