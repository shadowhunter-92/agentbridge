# Explicit historical tenant assignment

This offline alpha procedure assigns one existing governance SQL namespace to
one explicitly enrolled tenant. It preserves historical rows, opaque JSON,
signatures, audit hashes, approval records, reservations and UNKNOWN operations.
It does not infer which human or tenant owned historical records.

## Preparation

Stop ingress, workers, scheduled jobs and upgrade processes that can use the
source namespace. Retain the current package, configuration and backups. Use a
platform administrator enrolled in the separate authority directory; tenant
administrators cannot perform this assignment. File/database owners are trusted.
The write guards constrain supported legacy applications, not a malicious owner
able to alter SQL objects or Python code.

Create a private operator JSON configuration. For SQLite the shape is:

```json
{
  "operator_issuer": "https://identity.example.test",
  "authority": {
    "store": {"backend": "sqlite", "path": "/private/authority.sqlite"},
    "audience": "agentbridge-authority",
    "public_key_pem": "REPLACE_WITH_PINNED_IDP_PUBLIC_KEY_PEM"
  },
  "source": {"backend": "sqlite", "path": "/private/legacy.sqlite"},
  "restored": {"backend": "sqlite", "path": "/private/restored.sqlite"}
}
```

For PostgreSQL each store uses `{"backend":"postgres","dsn":"..."}` with
an explicit private search path. Protect the configuration if a DSN contains a
password. Supply a fresh operator JWT through `AGENTBRIDGE_OPERATOR_TOKEN` in the
operator process environment; tokens are not command-line arguments. The CLI
uses pinned public-key verification and performs no IdP discovery, cloud
provisioning, database dropping or restore-over-live operation.

## Freeze, backup, independently restore, verify and activate

```text
agentbridge-tenant-migrate --config operator-private.json freeze --tenant alpha
```

Freeze waits for existing SQL writers and records all historical table rows,
columns, indexes, constraints, triggers and sequence values. It installs write
guards on existing tables. A durable marker pins this migration to the original
physical source namespace. Restarting the operator tool is supported; a copied
backup cannot silently become another migration source.

Now make a real backup using SQLite's backup API or PostgreSQL's `pg_dump` custom
archive format. Independently restore that exact backup into a separate file or
disposable database. Configure `restored` to that namespace. Do not use a live
source connection or a hard link as a restore. Keep the archive immutable and
record which restore command consumed it. The CLI compares archive hashes and
complete restored SQL state; it does not independently prove an operator's
claimed archive-to-restore chain.

```text
agentbridge-tenant-migrate --config operator-private.json verify-backup --archive legacy-backup.dump
agentbridge-tenant-migrate --config operator-private.json activate --archive legacy-backup.dump
agentbridge-tenant-migrate --config operator-private.json status
```

For SQLite, `--archive` names the backup SQLite file instead of a `.dump` file.
Verification requires matching frozen migration metadata and historical state.
Activation rechecks source, restore and archive before atomically creating the
tenant binding and replacing freeze guards with the shared tenant write guards.
A failed activation leaves the source frozen. After a lost acknowledgment, read
`status` and inspect the binding rather than assuming activation failed.

Each mutating migration phase takes the exclusive authority boundary. Supported
tenant sessions already holding an authority guard finish first; new sessions
wait. PostgreSQL also serializes helper DDL and locks source tables. This is an
offline migration, not qualification of arbitrary rolling old/new deployments.
Keep legacy processes stopped: table guards reject their existing-table writes,
but database owners can still create or replace SQL objects. Unexpected tables
or schema changes prevent activation.

## Rollback and retained history

```text
agentbridge-tenant-migrate --config operator-private.json rollback
```

Structural rollback is permitted only while the historical manifest and
sequence values remain unchanged and any newly added tables are empty. It
atomically removes the binding and migration guards. Injected rollback failures
leave the active binding and guards intact. Any tenant-era data change requires
forward recovery; this tool does not discard new data or restore an old backup
over live work.

Legacy identity keys require explicit enrollment in the new authority directory.
Old approvals retain their exact scope and are not automatically converted into
tenant-bound grants: review and reissue approvals for new requests. Historical
UNKNOWN outcomes and their reserved exposure remain UNKNOWN. Legacy operations
without authority bindings and opaque task-owner keys remain preserved for
operator inspection; they are not silently assigned to a delegated human.

## Supported scope and qualification limits

The generic migration supports ordinary governance SQL tables. Views, virtual
tables, PostgreSQL custom routines/rules, RLS, foreign/partitioned/unlogged
tables, attached SQLite databases, unsupported SQL value types and preexisting
reserved migration objects require a separately qualified adapter. Refusal
preserves the source; the tool does not delete custom behavior to fit its model.

Tests use actual SQLite backup/restore and PostgreSQL 16 `pg_dump`/`pg_restore`
into disposable databases. They cover byte-preserved signed history, active
writers, legacy/new write guards, malformed/copied markers, source/restore/schema
drift, changed archives, activation/rollback faults, lost-ACK status inspection
and platform-role restrictions. Exact commit and CI evidence is recorded in the
phase register. This does not establish large-database migration performance,
independent institutional custody, fleet failover or production acceptance.
