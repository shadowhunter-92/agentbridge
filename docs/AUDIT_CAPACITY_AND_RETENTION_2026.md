# Audit payload capacity and conservative retention

This bounded alpha unit extends the existing SQL audit store. It does not
create another authorization or evidence implementation. Retention remains
**PARTIALLY TESTED** and production audit deletion remains forbidden.

## Retained payload bounds

SQLite and PostgreSQL enforce audit capacity through SQL triggers, including
direct `append_audit`, chained appends, and older workers' SQL inserts and
updates after the schema upgrade. PostgreSQL acquires the existing `911001`
audit fence before statement execution, before any unique sequence ownership.
Row accounting then runs in the same transaction. The normal bootstrap uses
the existing `911004` schema lock. SQLite uses its native write transaction.

Default policy is 100,000 retained rows, 64 MiB of retained UTF-8 JSON payload,
and 16 KiB per new/updated entry. Trusted operator configuration can raise
these limits up to 1,000,000 rows, 1 GiB total payload and 64 KiB per entry.
Database pages, indexes, WAL, backups, other evidence tables and database
overhead are additional storage; this is not a filesystem or namespace quota.

```python
from src.governance.audit import AuditLog
from src.governance.audit_trust import AuditTrustStore

# store is an already initialized, operator-selected durable tenant store.
audit_trust = AuditTrustStore(store)
audit = AuditLog(store)
usage = audit_trust.capacity()
audit_trust.set_capacity(
    max_records=100_000,
    max_bytes=64 * 1024 * 1024,
    max_entry_bytes=16 * 1024,
    audit=lambda: audit.record(
        actor="trusted-operator", action="set_audit_capacity",
        source_protocol="control", target_protocol="control",
        capability="audit.capacity", decision="allow",
    ),
)
```

These are trusted library methods, with no new public endpoint or authority
bypass. A service exposing configuration must use its existing current
operator authorization and provide the transaction-bound audit callback.

Metadata starts empty so a new tenant namespace can be bound before writes.
The first audit mutation or operator inspection accounts preexisting rows.
Existing rows are preserved byte for byte, including rows above the new
per-entry default. Lowering policy preserves rows; saturation rejects further
writes and never evicts evidence. A restart preserves the recorded policy.
Capacity updates and their audit callbacks share the transaction, so a failed
audit callback rolls the policy change back.

Store startup verifies initialized counters against a real SQL count and UTF-8
byte sum under the audit fence or SQLite write transaction. A mismatch fails
closed without resetting policy, counters or history. This scans retained
payload at startup; it is an operational cost, not a constant-time operation.
Routine append accounting uses the persisted counters. The offline migration
snapshot repeats the consistency check under its exclusive table boundary.
PostgreSQL additionally checks exact metadata columns, nullability and the
singleton primary/unique key shape before installing the trigger contract.

Trigger saturation reports a backend SQL exception. Policy and schema
validation use `AuditCapacityDenied`. This unit does not add HTTP 429 or 503
mapping, remote backpressure or a new service admission endpoint.

Accounting covers inserts, updates and deletions through SQL triggers.
PostgreSQL duplicate `ON CONFLICT DO NOTHING` inserts remain uncharged.
SQLite rejects duplicate sequence inserts before selecting `IGNORE`/`REPLACE`:
`INSERT OR IGNORE` with a duplicate now raises a constraint error, and
`INSERT OR REPLACE` cannot silently remove historical evidence or bypass
delete accounting on a connection with `recursive_triggers=OFF`.

Saturation aborts its SQL statement and the owning governance transaction.
Before execution, tentative operation, reservation and consumed approval must
roll back together. After an effect may have happened, failure to durably
settle preserves the existing UNKNOWN operation and held reservation; these
limits do not authorize refunds or automatic remote replay. The test suite
models both boundaries. Actual dispatch and recovery qualification is a
separate requirement.

## Conservative retention eligibility

Existing store-library retention continues to reject production deletion and
durable legal holds. Its new conservative reference check also refuses audit
prefix deletion when the namespace contains any retained operation or task
operation link, nonterminal status task, or pending budget reservation.
Terminal task state cannot override an UNKNOWN operation.

The historical audit format has no exact operation-to-audit sequence range.
Therefore even a settled operation keeps the whole audit. Such a namespace
can remain ineligible for prefix pruning indefinitely. This is deliberate
preservation until a separately reviewed reference-indexed retention and
custody policy exists. No operation, task, intent, result, receipt, key history,
checkpoint or witness row is deleted by this unit.

For an eligible nonproduction namespace, an explicit prefix truncation updates
capacity counters in the same transaction and retains the current chain head.
A later append continues its sequence and predecessor rather than restarting
at genesis. A self-consistent suffix remains weaker than complete history.

Retention authorization is enforced at the existing store-library API, not by
the capacity trigger. A privileged raw SQL `DELETE` can bypass the hold and
operation-reference API checks; its counter update does not authorize that
deletion. The tests explicitly record this boundary. Existing old binaries
that run their own retention SQL also lack the new reference check. Operators
must stop/drain retention workers, upgrade every worker, and use the governed
API. Ad-hoc deletion and mixed-version retention remain unsupported. A
database operator able to alter tables, triggers, policy or functions is
outside the local capacity integrity guarantee.

The existing offline migration adapter now qualifies only the three exact
audit capacity PostgreSQL function definitions and safe attributes. A matching
name with modified source, security-definer privilege, volatility or search
path is refused. Unknown application routines remain unsupported. Real backup
and separately restored data must preserve policy, counters, history and
triggers before tenant activation or rollback is allowed. This is a stop/drain
offline migration contract, not migration while active operations execute.
Counter-only, table-only and selective partial restores are unsupported. An
empty metadata table is the first-upgrade lazy state; it cannot independently
prove the provenance of an arbitrary incomplete restore. Use a verified full
same-version backup and its preserved manifest, with all writers stopped.

## Acceptance still required

Audit capacity tests establish synthetic SQLite/PostgreSQL transaction and
resource behavior. They do not establish independent evidence custody, WORM
storage, production retention, legal compliance or outcome authenticity.
Reference-indexed hold-safe retention, bounds for the remaining evidence
journals/checkpoints, mixed-version operational qualification, sustained
full-route performance and external storage/custody acceptance remain open.
