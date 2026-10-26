# Signing publication transaction ownership — October 24, 2026

Status: **PARTIALLY TESTED**. This local follow-up is separate from the
signing-capacity draft and has no hosted CI or publication approval.

`SigningTrustJournal.publish` owns its database commit. PostgreSQL calls refuse
an already-active transaction before changing history, capacity policy or an
in-memory revision floor. The caller's transaction remains usable. The store's
lock covers the commit and subsequent floor update. SQLite retains its existing
owned `BEGIN IMMEDIATE` boundary. The policy setter can still compose with
outer transactions and audit callbacks; it does not publish a signed revision.

Previously, PostgreSQL publication could return after releasing only a nested
savepoint. An enclosing rollback removed the revision while leaving its floor
advanced, so that journal instance refused its older durable history. Four
focused real-PostgreSQL cases reproduced the missing ownership denial; the same
four passed with the guard, including outer commit/abort and explicit retry
after the caller ends its transaction. Non-READ-COMMITTED owned publications
remain refused independently. Broader regression evidence is recorded separately.

One source-stable six-module run on SQLite and actual disposable PostgreSQL
contains 195 distinct cases: 188 passed, seven backend-specific skips and no
failures or errors. It covers signing capacity/history, tenant coordination,
atomic settlement and PostgreSQL reconciliation. The four focused cases overlap
that run and are not added to its total. Hosted CI remains NOT STARTED.

No signature, transition, current-key check, external minimum pin, capacity or
tenant guard is weakened. A later commit acknowledgment loss still requires
authoritative inspection of retained history. This change does not reset a
floor, automatically replay a remote action, settle UNKNOWN or enable retention.
Arbitrary raw SQL, hostile database owners, historical-key recovery, independent
custody, generic transaction composition and production qualification remain
outside this bounded guarantee. The isolated replay-capacity candidate remains
**BLOCKED** and untouched.
