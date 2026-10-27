# Retained manual-reconciliation evidence payload limits

Implementation baseline (historical): main
`609df6d66446ee9cf8b1acceb3d8f0461dab6e22`.
Local qualification recorded October 26 and reviewed October 27, 2026:
**PARTIALLY TESTED**. This unit adds bounds to the existing
`reconciliation_evidence` table; it does not create another evidence format
or authorization stack. The qualification record below binds local working
bytes and test invocations; it does not claim current-main integration or
hosted CI. Production remains **NO-GO**. No external-service fencing or
independent custody acceptance follows from these storage controls.

## Existing behavior and reproduced gap

Manual reconciliation already joins the operation decision, reservation
settlement, independently keyed readback statement, serialized evidence bundle
and audit-chain entry in one SQL transaction. A bounded audit row per bundle
indirectly limits the managed route's retained count. Queued task completion
has its own accepted result allowance and aggregate intent reservations; this
unit does not change that contract or add an alternative task completion path.

A synthetic nonproduction baseline reproduction accepted a 307,333-byte
optional evidence bundle, with its audit chain and legal hold preserved. That
reproduction isolates the missing independent payload limit. It is not a
demonstration of production authorization bypass or a real remote effect.

## Policy and accounting

| Limit | Default | Trusted operator ceiling |
| --- | ---: | ---: |
| Retained bundle records | 100,000 | 1,000,000 |
| Total stored bundle UTF-8 bytes | 64 MiB | 1 GiB |
| Individual stored bundle UTF-8 bytes | 256 KiB | 1 MiB |

These are bounded alpha defaults, not validated production sizing. Signed V1
Unicode sizing fixtures measured 41,345 bytes with ledger-compatible IDs and
59,777 bytes at the V1 verifier's broader 512-character identifier ceiling.
Those fixtures are not universal maxima for arbitrary historical, direct-SQL
or optional nonproduction data.

Usage comes from actual SQL `COUNT`, byte sum and largest retained bundle;
there are no independent cached counters to reset or partially restore. The
new singleton policy starts empty so constructing a helper alone does not
prevent a fresh namespace from being assigned to a tenant. Inspection or the
first successful append initializes defaults transactionally.

Lowering limits preserves every existing row, including oversized history.
Growth is rejected while retained count, total bytes or any existing bundle
exceed policy. No eviction, deletion, refund, replay or audit-prefix pruning
is added. Operators may explicitly raise policy within the ceilings; a
quota refusal never establishes that an uncertain remote action failed.

```python
from src.governance.reconciliation import Reconciliation

# An already authorized operator selects the durable store and audit callback.
reconciliation = Reconciliation(store)
usage = reconciliation.evidence_capacity()
reconciliation.set_evidence_capacity(
    max_records=100_000,
    max_bytes=64 * 1024 * 1024,
    max_entry_bytes=256 * 1024,
    audit=authorized_transactional_audit_callback,
)
```

These are trusted library methods. No new HTTP endpoint, caller-selected
namespace or operator authorization bypass is introduced. A service exposing
configuration must enforce its existing current operator authorization.

## SQL and transaction boundary

Direct and older SQL writers encounter the installed insert bounds and
append-only guards. Duplicate insert, upsert, replacement, UPDATE, DELETE and
PostgreSQL TRUNCATE cannot replace retained bundles through the supported
contract. PostgreSQL uses the existing `911001` audit fence before statement
execution and unique-index ownership. Growth requires READ COMMITTED;
REPEATABLE READ and SERIALIZABLE writes are refused rather than relying on
a stale snapshot. SQLite uses its native write transaction. Both backends
require UTF-8 storage for exact byte accounting.

Exact owned metadata, table shapes, constraints, trigger definitions and
PostgreSQL routine bodies/attributes are qualified. TEMP shadowing,
noncanonical SQLite owned names, PostgreSQL nonpermanent relations and
unsupported row filtering are refused. Missing or modified installed pieces
are not silently repaired. Helpers created after tenant binding install the
existing tenant write guards on their tables, including the new policy.

The original bundle JSON serialization and SHA-256 digest remain unchanged.
A capacity refusal aborts the owning settlement transaction: its decision,
budget update, readback marker, bundle and audit append must all roll back.
The operation stays UNKNOWN and its reservation stays held. An acknowledgment
lost after commit is resolved by inspecting durable state, not dispatching
the remote action again.

## Backup, holds and operational limits

The existing stop/drain migration adapter qualifies the exact new PostgreSQL
routines and verifies installed capacity during snapshots. A real full backup
and separate restore must preserve raw bundle text, policy and SQL guards,
not merely semantically equivalent JSON. Existing over-limit history remains
eligible for preservation. This is offline migration; rolling active-operation
migration and automated HA are separate gates.

Legal holds and conservative operation-reference retention remain in force.
No evidence is removed to create capacity. Selective reference-indexed
retention remains **NOT STARTED** in this unit. A database owner who can alter
guards or tables remains outside this local integrity boundary. Old binaries
must not perform their own unsupported retention SQL.

Bounds cover bundle payload, not identifiers, physical pages, indexes, WAL,
backups, all other journals or the entire tenant namespace. Serialization
still precedes the SQL check; this is not an ingress heap-memory limit or
HTTP backpressure guarantee. Actual usage scans cost time proportional to
retained payload. Sustained full-route performance and production capacity
qualification remain open.

## Qualification record

The first local SQLite/PostgreSQL 16 invocation selected 16 modules and
recorded 567 distinct cases: 476 passed, one test-fixture failure and 90
skipped. The failure occurred before schema qualification: SQLite rejected
the test helper's unnamed three-value INSERT into the deliberately unsupported
four-column fixture. Its PostgreSQL counterpart passed.

The only correction named the helper's `agent_id`, `operation_id` and
`bundle` INSERT columns, preserving the three placeholders and argument tuple.
The negative case and every assertion stayed unchanged. A separately granted
invocation reran the entire evidence-journal capacity module: 136 distinct
cases, 114 passed, 22 skipped and no failure or error. The SQLite extra-column
negative then passed; its PostgreSQL counterpart remained passing.

All 451 source pins were stable during each invocation. Between invocations,
only that test-helper file changed; all other 450 working files and all 102
runtime files were byte-identical. The same 136 module identities overlap both
runs. Selecting the later module observations yields 567 distinct identities:
477 passed and 90 skipped. This is two-invocation coverage reconciliation,
**not one fresh successful 567-case invocation**. The first failure is retained.

Exact local evidence:

- First source manifest:
  `f0b7fd811b5369fa75a1af2a1708e34ddfca1c393cccb3d155f54c1779c89bda`.
- First result receipt:
  `ec570a45bf4c8c78f6f0f2c6dc6cf4307deb16c2bd74c23ffacb6e1074e1ab43`.
- Corrective source manifest:
  `f38f5fdf8e23e543002be7ab8040385d9f878f8de4ef71479ed0b480dc4f8415`.
- Corrective result receipt:
  `0e5ca37c1eaf06911e4f87f071c1853ceb0608d96c744cfa84504c84821f62b0`.
- Raw corrected test file:
  `a61deb16722eec465f8f58ae3ffd01b5860cc75d008d18b1aa2b10d592a76bf5`.

These are local working-source observations, not claims that the baseline Git
tree itself contains the unit. Any stronger hosted-CI qualification must bind
the actual reviewed candidate commit and selected jobs separately. No tests
were rerun for this documentation-only status update. Local tests cannot
supply independent destination custody, production retention acceptance,
legal compliance or external outcome truth.
