# Checkpoint registry capacity

This unit extends `AuditTrustStore` and its existing `audit_checkpoints`
table. It preserves the checkpoint signature format, pinned signer,
complete genesis-chain verification, exact sequence/head binding and
duplicate-sequence rejection. It creates no new authorization or evidence
implementation. Current qualification is **PARTIALLY TESTED**. The final
two-module run on base `34d144c` passed 96 cases with 33 expected backend-specific
skips (129 distinct cases, zero failures/errors), using SQLite and real local
PostgreSQL. This includes offline restore, migration and rollback checks.
Earlier focused and composition results retain their own source association.
Exact-head CI and production acceptance remain pending.

The existing default checkpoint encoding measured 395 bytes in the retained
synthetic baseline. A valid signed checkpoint with extension metadata occupied
60,412 stored bytes and was accepted before this change. The new default
policy permits 10,000 retained checkpoints, 16 MiB of retained JSON payload,
and 8 KiB per newly inserted checkpoint. Trusted operator library configuration
can raise limits to 100,000 records, 128 MiB and 64 KiB per entry. These are
alpha resource controls, not an externally qualified capacity recommendation.

```python
trust = AuditTrustStore(existing_operator_selected_tenant_store)
usage = trust.checkpoint_capacity()
trust.set_checkpoint_capacity(
    max_records=10_000,
    max_bytes=16 * 1024 * 1024,
    max_entry_bytes=8 * 1024,
    audit=existing_transaction_bound_operator_audit_callback,
)
```

These methods provide a trusted library configuration boundary. They do not
create an HTTP endpoint or authorize an untrusted caller to change policy.
Audit payload limits and checkpoint limits are separate policies.

SQL INSERT triggers enforce limits for managed writes and direct older SQL
writers after installation. SQLite uses its write transaction. PostgreSQL
uses the existing audit fence before statement execution and unique-index
ownership. Checkpoint validation and insertion share the managed transaction
and audit fence. SQL UPDATE and DELETE of checkpoint rows are refused;
SQLite REPLACE is rejected before it can erase history, and PostgreSQL
TRUNCATE is refused. This adds no checkpoint eviction or deletion path.

Usage is computed with SQL COUNT and SUM of the actual stored JSON byte
length under the same fence. There are no cached checkpoint usage counters.
These measurements bound retained checkpoint rows and JSON payload bytes;
they do not measure or cap database pages, indexes, WAL or backup storage.
SQLite and PostgreSQL storage must use UTF-8 so SQL byte measurements match
that contract. Initialization rejects unsupported schema/value types rather
than rewriting history. Limits-only metadata stays empty until first use so
initial tenant binding remains possible. First successful insertion or operator
inspection records defaults; restart preserves configured policy.

PostgreSQL bootstrap and offline snapshot verification require both checkpoint
tables to be ordinary permanent relations (`relkind='r'`,
`relpersistence='p'`). Unlogged or session-local substitutes are refused.
The retained failed-before catalog reproduction accepted each of two unlogged
tables; draft 4 rejects them without changing existing rows, policy, audit,
holds or the held UNKNOWN reservation. This was a catalog/reopen check, not a
database crash or storage-loss drill.

Managed bootstrap, checkpoint, policy and hold methods refuse reserved TEMP
names on both backends. An embedding must not shadow audit, holds, checkpoint,
policy or tenant-binding objects with session-local data. A retained PostgreSQL
test reproduced a successful return with zero durable rows and one TEMP row
before this refusal was added. Direct SQL still requires explicit correct
namespace selection; no library can make arbitrary old SQL against a TEMP
table become a durable write.

An already installed checkpoint schema must retain the exact known function
bodies/attributes and trigger wiring, timing and enabled state. Startup refuses
modified or partial installations instead of repairing them silently. Complete
first installation is transactional. A metadata-only restore with dangling
checkpoint triggers is refused without initializing replacement policy.

Existing checkpoints survive activation, including entries over a new limit.
Policy shrink preserves every row. New growth that exceeds configured limits
fails atomically; a failed policy audit callback also rolls back its policy
change. A backend SQL exception reports insertion saturation; this unit does
not establish HTTP 429, remote backpressure or automatic recovery.

The aggregate and existing full-chain verification have a cost proportional
to retained history. Startup also checks historical SQLite row types and
known trigger definitions. Representative startup/admission measurements
remain necessary; these controls do not establish production latency or SLOs.

The saturation regression verifies that an UNKNOWN operation, its exact held
budget reservation, legal hold, audit rows and existing checkpoints remain
unchanged after a refused checkpoint insertion. Capacity enforcement adds no
task-link rewrite, refund, audit-prefix pruning or uncertain-effect replay
path. The existing conservative retention and production deletion restrictions
remain in place. P35 remains **BLOCKED** and is unchanged by this unit.

Complete offline backup/restore must preserve policy, schema, checkpoint JSON,
signatures, audit and holds together. A selective restore or deliberate
removal of limits metadata is outside the supported recovery contract.
Operators must stop/drain writers for migration. Retained tests exercise
same-backend backup into a separate namespace, exact checkpoint JSON/policy
and hold preservation, tenant assignment, and rollback before tenant-era
changes. Draft 4 reran the three PostgreSQL checkpoint modes: initialized,
lazy first installation and preserved over-limit history. Modified or unknown
PostgreSQL routines are refused. This does not qualify online migration,
cross-backend conversion or restore over live tenant writes. Privileged DDL
or file replacement remains an operator trust boundary; this is not immutable
storage or independent custody.

The earlier draft 4 source for the focused PostgreSQL observations is retained under
`draft4-source-manifest.json`, SHA-256
`444c101f407d55b904743d0997bb6dc7c3179babb74824f882a00ecfb5363d83`,
on composed baseline `50e8b19be0b3e039fc424513f7c0229678ff6b60`.
Its checkpoint implementation hash is
`89c96b47343a9b75c8b305db96bef77bd1d9c6d839233a0ae8d9e2336bd28bef`.
That manifest preserves the earlier documentation bytes; this documentation
update has its own association and does not relabel any executed receipt.

The local evidence records below are separate observations with overlapping
case identities; their passing counts must not be added into a final-source
total.

| Source | Retained receipt | Local observation |
| --- | --- | --- |
| Draft 3 | `draft3-sqlite-final` | 50 passed, 9 expected SQLite skips for PostgreSQL routine-only cases; includes complete SQLite checkpoint migration. |
| Draft 3 | `draft3-pg-final` | 41 passed, 19 expected SQLite skips from PostgreSQL-specific case selection. |
| Draft 3 | `draft3-failed-regressions` | 17 PostgreSQL restore/migration and audit-capacity regressions passed, including three checkpoint restore modes. |
| Draft 3 on composed baseline 50e8b19 | `root-dispatch-composition-20261022` | 53 passed, 21 expected SQLite skips for PostgreSQL-only dispatch/manual cases. This is the earlier composition run. |
| Draft 3 helper with new regression tests | `draft4-unlogged-before` | Two expected failures and one ordinary-table control pass; unsupported unlogged tables were accepted. |
| Draft 4 | `draft4-unlogged-after` | Three PostgreSQL catalog/reopen cases passed. |
| Draft 4 | `draft4-pg-focused` | 30 PostgreSQL checkpoint, UNKNOWN/hold, audit rollback, concurrent-writer, namespace/drift and restore cases passed. Together with the preceding row: 33 distinct cases, no skips. |

Draft 3 remains frozen under `draft3-source-manifest.json`, SHA-256
`c7c5cca79fb91ee3013943b18ce537c03aab1f6463dccd2fcff4f39153c6d893`.
The composition and draft 4 association records identify the actual baseline
50e8b19; generic runner receipts retain their historical baseline 7415718
field. No earlier result is attributed to a later source.

The final `root-final-unit-20261022` run contains 96 passed and 33 expected
backend-specific skips with no duplicate case identities, failures or errors.
Its association records base `34d144c`, all runtime hashes and both test modules
before/after execution. Checkpoint and migration code/tests retain draft 4
hashes; audit-trust imports received formatting with an identical parsed Python
AST. The documentation index and explicit PostgreSQL CI selection were added
separately. Earlier overlapping totals are not added to this final run. No
hosted CI acceptance is inferred from local execution.

Implementation and focused tests:
[checkpoint capacity](../src/governance/checkpoint_capacity.py),
[audit trust](../src/governance/audit_trust.py),
[checkpoint tests](../tests/test_checkpoint_capacity.py), and
[offline migration tests](../tests/test_tenant_migration_checkpoint_capacity.py).

Other evidence journals, key revision history, witness state, reconciliation
bundles, destination effect identities, database pages/indexes/WAL/backups and
global tenant disk use require separate policies. A signed checkpoint proves
the signer's statement about an audit head; it does not independently prove a
physical or financial effect or qualify production retention.
