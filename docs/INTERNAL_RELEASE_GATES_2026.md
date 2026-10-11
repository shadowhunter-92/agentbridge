# Internal release gate execution register — October 2026

**Branch:** `release/r4-internal-gates-2026-10` (draft PR #34).
**Decision:** NOT production-certified; keep `main` protected.

## Seven engineering workstreams

| Gate | Code added in this review | Evidence | Still required before production |
|---|---|---|---|
| Trusted reconciliation | Pinned Ed25519 destination signature, operation ID/fingerprint/outcome binding, hash check; production digest-only claims denied | `tests/test_destination_receipts.py`, `tests/test_production_reconciliation_receipts.py` | Establish real destination key enrollment/rotation, destination read-back, operator RBAC, trust in target-reported fact, witnessed test |
| Durable audit trust | SQL-backed legal-hold registry; SQL signed checkpoint registry validates pinned signer AND recorded hash-chain state | `tests/test_audit_trust.py`; production destructive retention remains disabled | Enforce holds on every retention path, independent off-database immutable anchoring and trusted signer service, atomic archive/retention and rollback tests |
| Network isolation | Named target ACLs plus mandatory explicit HTTP proxy configuration in production; proxy passed through supported A2A/ACP clients; local/IP target exclusions | `tests/test_proxy_boundary.py`, `tests/test_trusted_targets.py` | Actual locked-down proxy deployment, egress firewall/network policy, tested DNS rebinding/redirect handling; test non-HTTP stdio execution permissions |
| Protocol conformance | Written versioned support/unsupported matrix; limited registered-adapter test | `tests/test_protocol_scope.py`, prior pinned-SDK conformance tests | Official latest MCP and A2A 1.0 interoperability suites, server transports, streaming/task lifecycle; do NOT market as full conformance |
| Recovery | Real POSIX worker SIGKILL tests against SQLite and disposable PostgreSQL plus earlier lost-ack loopback tests | `tests/test_worker_kill_recovery.py`, `tests/test_pg_worker_kill_recovery.py` | Failover, network partition, backup/restore, remote action before/after acknowledgements, independent staging drill and operator reconciliation |
| Packaging | Nonroot isolated review container, secure local-only Compose, wheel/sdist and container build CI | `Dockerfile.release`, `docker-compose.release.yml`, package-review job | Immutable image digests, pinned SBOM/dependency locks, vulnerability scan, secrets/KMS, staging upgrade/rollback, signed artifacts |
| Performance | Repeatable synthetic translation and concurrent SQLite governance benchmark p50/p95/p99, checks budget and audit integrity | `tools/benchmark_synthetic.py`, `tools/benchmark_governance.py`, CI smoke | Real Postgres and remote agent traffic tests under expected load, SLOs, error-budget acceptance and independent deployment metrics |

## Release decision and branches

The original code remains on `main` pending a gate-based review. PR #32 is the consolidated earlier hardening draft. PR #34 is the isolated new internal-gates draft, branched from PR #32; **do not merge both separately**. Avoid deleting either until the proposed release commit is stable and rollback-rehearsed.

No independent security report, real operated staging failure drill or paid pilot is asserted by this document. A signed destination statement proves that a holder of the pinned key signed those fields, **not** that the physical or remote side effect actually took place. Likewise an internal SQL checkpoint is **not** an external tamper-resistant anchor.

**Decision:** no unrestricted production release or merge of PR #34 today. Separate code merge approval from go-live; if engineering review eventually approves an experimental, disabled-by-default feature merge, tag it clearly as alpha.

## October 11 follow-on engineering checkpoint

- Signed receipt verification rejects unknown unsigned metadata, missing fields, malformed signatures and ill-typed/oversized identifiers. Regression corpus: `tests/test_destination_receipt_envelope.py`.
- Production HTTP target and proxy configuration parsing rejects ambiguous authority/port/path/query/control-character combinations. Regression corpus: `tests/test_production_url_ambiguity.py`.
- These are source-level hardening changes, not a DNS rebinding solution: deployment must still constrain resolved IPs, redirect destinations, CONNECT tunneling, destination ports and post-DNS network access at the egress enforcement point.
- Latest follow-on changes must have successful CI against their exact final head before claiming tested status. Keep PR #34 draft and main untouched.
- Next acceptance work: external-state readback tied to operation identity, independent immutable audit anchoring, network-policy-backed egress with active adversarial DNS/redirect tests, and operated failover/restoration with signed evidence.

## Follow-up: PostgreSQL performance measurement

`tools/benchmark_postgres_governance.py` exercises multi-connection real
PostgreSQL budget reservations, operation handling and audit logging under
bounded concurrency, asserting that accounting and audit counts agree.
The CI PostgreSQL service now invokes it with 50 operations and 4 workers.
It emits p50/p95/p99 and throughput, but uses a simulated destination and
a local disposable database. These numbers are **not** production SLOs,
proof of horizontal HA scaling, or end-to-end customer-agent latency.
Production sizing, sustained-load failure behavior and SLO acceptance
remain open until a real operated deployment measures them.

## Independent readback contract (October 11)

Production unknown-operation settlement now requires **two distinct, operation-bound
cryptographic statements**: a pinned destination receipt plus a separately pinned,
fresh signed readback attestation. Missing, altered, stale, or same-key attestations
fail closed before the SQL reconciliation transaction. A SHA-256 digest of the
accepted readback attestation is saved transactionally with reconciliation.

Configuration: `AGENTBRIDGE_TRUSTED_READBACK_KEY_HEX` must contain the Ed25519 public
key of an independently operated destination-state readback verifier. The signing
component must use **separately controlled read-only credentials** and query the
authoritative system of record, not accept arbitrary caller-supplied claims or
simply re-sign the destination receipt. The verifier records a hash of its
observed source evidence and binds destination receipt, operation, fingerprint,
outcome, and external reference. Rotate and revoke keys with documented controls.

**Not yet accepted:** This is a verification *contract*, not a deployed
independent readback service or demonstration of real external action state.
A trusted key alone cannot establish independent sourcing. Production
qualification requires a real readback adapter for the selected target, a
separate operator/trust domain, and tampering/lost-acknowledgement tests on
staging. Do not close the overall reconciliation release gate yet.

## Production start-up fail-closed configuration checks

Production now rejects partial readback trust-root configuration, equal destination/readback
Ed25519 public keys, malformed public key encodings, non-HTTPS OIDC issuer configuration,
and non-finite shutdown-grace/slow-request logging values.
The pair of trust roots may be absent only for read-only/translation-only deployments;
unknown-action production reconciliation then remains unavailable (fail closed).
`tests/test_readback_config_validation.py` exercises these boundaries. These checks do
not validate independent operations of the readback service or certify key ownership.
