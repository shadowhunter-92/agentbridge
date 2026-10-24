# Current signing policy and PostgreSQL snapshots

Status: **PARTIALLY TESTED** for this local follow-up. No hosted CI or
production acceptance is claimed.

`SigningTrustJournal.settlement_keys` must decide using current committed key
policy. PostgreSQL READ COMMITTED is required for that decision. The existing
shared compatibility barrier and signing coordination row SHARE lock still
hold the selected policy against rotation through the surrounding transaction.
SQLite retains its existing transaction/writer-lock contract.

A retained baseline observation established an old repeatable-read history
snapshot, committed valid staged replacement and revocation on a second
connection, then resolved the previously active key from the old snapshot.
The READ COMMITTED control rejected it. The correction refuses unsupported
isolation before resolving keys; it does not refresh or retry the caller's
transaction, change signed history, revoke a key implicitly, settle a task or
retry an uncertain effect. Original controller roots, signatures, transitions,
floors, tenant guards and reservation ownership remain separate checks.

This is distinct from logical signing-journal capacity and the checkpoint row
limit. It does not qualify arbitrary transaction composition, historical-key
recovery, independent custody or production execution. The existing in-memory
revision-floor/outer-rollback limitation is not repaired by this check.

The focused run passed three actual PostgreSQL cases (READ COMMITTED,
REPEATABLE READ and SERIALIZABLE), with three expected SQLite skips. Each case
uses valid signed staged replacement/revocation and then confirms the current
replacement key is usable. One final source-stable four-module run contains
85 distinct cases: 78 passed and seven expected backend-specific skips, zero
failures/errors, covering signing history, tenant coordination, reconciliation
and atomic settlement. These runs overlap and are not added together.

Exact-head hosted CI and reviewed integration remain. These tests do not make
an older published head contain the correction. The isolated replay-capacity
candidate stays BLOCKED.
