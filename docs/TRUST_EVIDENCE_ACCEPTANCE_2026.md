# Local Trust → Evidence acceptance workflow

This is a bounded synthetic acceptance package, not production approval or an independent custody claim. Run from the local continuation checkout:

```powershell
.\.venv\Scripts\python.exe -m examples.qualify_trust_evidence
```

The command generates ephemeral signing keys in memory, temporary SQLite databases and a machine-readable JSON report. It does not call cloud APIs, send messages, dispatch real business actions or publish artifacts. It removes the temporary databases on exit. Public verification keys, statements, signatures and audit records are safe to inspect; private keys are never exported.

## What the workflow exercises

1. A registered agent signs the exact action, target and operation identifier.
2. The gateway denies dispatch until the specific approval is granted.
3. Authorization reserves budget and durably claims the operation before dispatch.
4. The destination checks the leader epoch and commits one synthetic effect, then drops the acknowledgment.
5. Automatic replay is rejected; the operation stays unknown and its budget stays reserved.
6. A read-only observer independently reads the committed destination record.
7. A forged reviewer signature is rejected.
8. A controller-signed key revision revokes the old observer and activates its staged replacement. Old evidence cannot settle the operation.
9. A fresh replacement observation plus an exact signed reviewer decision settles the operation once.
10. State, budget, signed evidence and a hash-linked audit entry commit in one transaction.
11. A superseded leader cannot insert another effect at the destination.
12. A separately keyed local witness verifies the complete audit history.

## Integrating signed key lifecycle policy

`SigningTrustJournal(store, controller_keys=..., minimum_revisions=...)` binds controller public keys to the `destination` and `readback` domains. Controllers sign exact envelopes containing `domain`, `revision`, `previous_sha256` and an ordered list of `key_id`, `public_key_hex`, `state`. Use `canonical_registry_payload()` as the signing contract. Publish with `journal.publish(envelope)`; revisions are sequential and linked to the predecessor digest.

The initial enrollment is signed by the externally pinned controller. Subsequent revisions preserve key identities and key material, require staging before activation, and prohibit resurrection of revoked keys. A controller-signed statement alone does not prove that the controller operates independently.

Pass the operator-configured journal to `Reconciliation(store, trust_journal=journal)`. `record()` accepts `destination_key_id` and `observer_key_id`, resolves both against current signed histories, and requires exact destination/readback/reviewer signatures. Selecting a staged, revoked or unknown identity fails closed. Environment keys cannot override a configured journal. This opt-in embedded API does not automatically change existing environment-key integrations; those must be deliberately migrated by their owner.

The standalone `verify_journaled_action_evidence()` API applies the same current registry policy to both signers without starting the gateway. It verifies evidence only; it does not accept or settle an operation.

SQLite serializes publication and settlement with its write transaction. PostgreSQL uses transaction-scoped advisory lock 911005 for registry publication and settlement validation. Budget settlement also takes the normal per-agent mutation lock; audit appends take the existing audit lock. This ensures a revision cannot change between verification and commit.

## Evidence and rollback

`reconciliation_evidence` retains the signed destination receipt, readback attestation, reviewer signature and public trust context. The reconciliation audit entry includes the bundle SHA256, operation identity, outcome reference and accepted registry revisions/digests. Any audit insert failure rolls back the operation, budget and evidence write together. Existing rows are not rewritten or re-signed.

Signatures authenticate historical registry content; they do not prove freshness after storage rollback. Persist the latest minimum revisions outside the governed database and supply them after restore. A fresh process without those pins cannot detect an otherwise valid older complete registry snapshot.

An actual disposable PostgreSQL backup/restore drill is available:

```powershell
$env:AGENTBRIDGE_TEST_PG = '<explicit disposable localhost agentbridge_test DSN>'
$env:AGENTBRIDGE_DISPOSABLE_TRUST_RESTORE = '1'
.\.venv\Scripts\python.exe -m tools.drill_signing_trust_restore --container agentbridge-qualification-<your-test-id>
```

The tool creates two randomly named databases, backs up revision 1, rotates to revision 3, restores the old backup and requires the separately retained revision pin to reject it. It also verifies retained unknown state, replay denial, budget exposure and audit integrity, then removes both databases. The container must be your disposable local qualification server, not another application's database.

Schema changes are additive. A rollback to code that does not enforce the journal can bypass the newer revocation policy. Disable consequential settlement or run read-only before such an application rollback; do not claim security-preserving rollback merely because old code can open the database.

## Remaining production gates

Independent administration of controller, destination, observer, reviewer and witness credentials; a qualified external destination; authenticated production egress including DNS/IPv6; immutable external witness retention; automatic HA and split-brain handling; trusted publisher custody/provenance; declared official protocol transport/lifecycle compatibility; production-shaped resource and overload qualification; independent review; and genuine external evaluations remain open.

The demo has separate keys and separate read-only connections under one local operator. It demonstrates technical separation, not independent organizations, compliance certification, universal exactly-once execution or four completed commercial products.
