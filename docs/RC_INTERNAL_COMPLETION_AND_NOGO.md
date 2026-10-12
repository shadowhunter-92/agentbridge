# R4 release candidate: internal completion evidence and unresolved gates

**Status: ALPHA; unrestricted production NO-GO.**
This is the operating register for draft PR #34. Passing CI is not
a substitute for real deployment assurance, customer consent or review.

## Verified internally (disposable environments)

- Real PostgreSQL custom-format dump/restore into a separate database,
  state-preserving backup rollback, committed unknown operation no-replay.
- Physical PostgreSQL streaming standby, primary fenced by stopping the
  container before promotion; measured fence-to-promotion smoke duration.
- Actual isolated Docker network disconnection and reconnect of a
  PostgreSQL client, with preserved committed unknown state and duplicate
  primary-key denial. NOT a two-primary split-brain drill.
- PostgreSQL SQL-backed fencing epochs, rejected stale leader tokens,
  idempotent migration and downgrade refusal while live state is present.
  All consequential destinations still must enforce fencing tokens.
- Separate PostgreSQL SELECT-only readback identity, signed destination
  receipt and independently signed observation; source-of-truth integration
  with an outside organization is not demonstrated.
- Disposable egress-isolated worker; proxy denies unauthorized CONNECT
  and evaluates DNS/global IP and TLS ClientHello SNI against allowlist;
  TLS 1.3 mTLS identity/SPKI authorization primitives have unit tests.
  A real CNI deployment and operated mTLS egress remain unverified.
- Wheel rebuild equality, pinned Python base-image digest, complete-image
  CycloneDX SBOM, HIGH/CRITICAL image scanning and pip audit in CI;
  Ed25519 offline sign+verification commands and tests. Publisher custody,
  hash-locked transitive deps and authenticated artifact distribution remain.
- MCP unsupported methods reject rather than reinterpret; narrow official
  SDK schema tests; repeated PostgreSQL load smoke reports p99, throughput
  and process RSS under disposable thresholds.

## Internal work still open — do NOT classify as external

1. Deploy a real server-side authoritative outcome integration with separately
   administered observer keys, credentials, rotation and revocation policy,
   reconciliation and retention for missing/mismatched evidence.
2. Wire fencing epochs through every consequential dispatch and target so an
   old isolated leader cannot commit external effects. Implement end-to-end
   fault injection covering cross-node partitions, automated promotion,
   PITR restore and verified RPO/RTO under representative workloads.
3. Operate a separately privileged production egress proxy/service with
   workload identity and TLS destination validation, real Kubernetes CNI,
   metadata/IPv6/DNS escape tests, quotas and monitoring; reference Python
   CONNECT relay is explicitly sandbox-only.
4. Produce a hash-locked transitive Python graph and reproducible image build;
   sign/release externally using independently controlled keys; authenticate
   artifact provenance, scan published images, rehearse rolling upgrades.
5. Test documented protocol versions against pinned official reference agents,
   sessions, cancellation, errors, lifecycle and transports (not only models).
6. Run production-shaped sustained tests under failure, CPU/RSS limits,
   queue/load shedding, explicit p95/p99/error budgets and resource ceilings.
7. Prepare per-target deployment/security packet and maintain a clean,
   reviewable release PR, changelog and upgrade/rollback plan.

## Truly outside-dependent acceptance

- Authorized real customer/target access and target owner confirmation that
  the observer reads authoritative committed outcomes.
- Independent signing/witness authority, security assessment and operations
  team responsible for the deployment, including independent key custody.
- Third-party developer integrations, reviewer reports and paid pilot signals.

## Operator release decision checklist

All relevant CI checks must pass on one exact commit SHA; all images and
artifacts must be pinned by digest and have valid independently held signing
key lineage; reviewer-specific findings must be resolved, operator drill
logs retained, and real target isolation verified. Until then **NO-GO**.

Do not automatically merge this draft PR to protected main or release a
consequential-action service. In particular, do not infer that a signed
destination statement independently proves the outside effect happened.

## Engineering sprint follow-on (October 12) — evidence and limits

### P0 — Destination fencing and independently enrolled readback

- `src/governance/fenced_postgres_destination.py` now takes the
  authoritative PostgreSQL fence-row lock inside the **same transaction**
  that inserts a signed destination effect. Stale/expired epochs are denied.
  `tests/test_fenced_postgres_destination.py` covers lost acknowledgments,
  independent PostgreSQL readback, duplicate denial, lease turnover and
  old-leader denial.
- `observer_key_registry.py` and the SDK's
  `verify_registered_action_evidence` accept only explicitly enrolled active
  readback public keys. Unit tests reject staged/revoked identities, caller
  override, and duplicate key IDs.
- A genuine outside source, separate key custodian and operational key
  rotation and audit policy are NOT supplied by internal CI. Fencing MUST be
  implemented by every non-PostgreSQL destination in the future.

### P0 — Network and workload identity

- Actual TLS 1.3 loopback connections now exercise client certificates and
  operator-pinned client SPKI hashes; unenrolled certificates are rejected.
- Existing sealed Docker network denies direct worker egress; strict CONNECT
  allowlist/DNS/IP and TLS SNI guard tests continue.
- A real Kubernetes CNI and production workload-authenticated network proxy
  have not been deployed or adversarially accepted. Reference relay remains
  deliberately prohibited in production.

### P1 — Recovery

- A new disposable PostgreSQL 16 WAL archive drill
  (`tools/drill_postgres_pitr.py`) creates a base backup, marks a named
  restore point, writes a later row, restores and promotes an isolated new
  instance, and asserts the later row is absent. CI #334 ran the corrected
  PITR job successfully.
- Already passing: committed unknown/no-replay across worker death, physical
  standby promotion after primary fencing, real Docker TCP network partition,
  guarded schema migration/rollback, measured disposable promotion duration.
- Automated distributed leader election/fencing against two simultaneously
  reachable primaries, multi-zone failure and real customer RPO/RTO remain
  unqualified. A SQL fence must be checked **at the destination**.

### P1 — Supply chain

- Both Python runtime-image stages use an observed SHA256-pinned Alpine base.
  Complete-image Trivy HIGH/CRITICAL gate and CycloneDX artifact are in CI,
  in addition to Python environment vulnerability scanning.
- Added an ephemeral, explicitly **untrusted CI signing rehearsal** that
  generates a throwaway Ed25519 key, signs the actual wheel digest and
  verifies the source commit and signature with the public-key verifier.
  No public publisher trust or independently held signing secret exists yet.
- Complete transitive hash lock, signed artifact provenance, public package
  registry and verified install/upgrade from signed published artifacts are
  outstanding engineering and operational tasks.

### P2 — Protocols

- MCP unsupported methods and A2A terminal/control lifecycle messages now
  reject instead of silently becoming new calls, with negative tests.
- Official multi-version transport/session/auth/cancellation interoperability
  matrix remains unqualified. SDK-shape assertions are not full compliance.

### P2 — Performance

- SQL concurrency CI includes measured 250-op/8-worker runs and three
  repeated batches with explicit p99, throughput and process RSS smoke limits.
- Saturation/soak, CPU budgets, error/queue/load shedding, actual external
  side-effect latency and contractual SLO acceptance remain open.

### Release posture

CI passing on the exact latest commit must be verified again after all
edits. No assumption of managed production readiness, no automatic merge,
no customer deployment or outside audit has occurred. **Unrestricted
production remains NO-GO.**

## CI #345 engineering evidence: 10/10 passed on c4a2bf5 (October 12)

The disposable sustained-load job uncovered PostgreSQL catalog races that
short-lived tests did not catch: concurrent `PostgresStore._init_schema`
and later `OperationLedger.__init__` invocations were performing independent
`CREATE TABLE IF NOT EXISTS` without a database-wide lock. Both now use
transaction-scoped advisory lock 911004 during schema creation. A new
eight-worker fresh-schema regression explicitly tests concurrent startup.
CI #345 passed all ten jobs, including the **90-second sustained
PostgreSQL SQL-governance soak** with enforced throughput, RSS and sampled
p99 smoke thresholds. This is not a production service-level guarantee.

The release review now commits `requirements-runtime.lock`, a SHA256-hash
locked Python 3.12 runtime dependency graph. `Dockerfile.release` and the
clean-wheel install enforce `pip install --require-hashes` and install
AgentBridge without unbounded dependency resolution. CI regenerates the
lock and diffs it against the committed copy to prevent resolution drift.
The build toolchain, Python 3.11 and optional protocol extras are not
yet under the same locked assurance.

The release job also rehearses detached signing of the actual wheel with
an **ephemeral test-only key** and checks the exact source commit and wheel
hashes through the independent verifier. This is not an operator-controlled
or publicly trusted release signature.

The protocol adapter now denies unsupported A2A terminal/control lifecycle
states in addition to unsupported MCP procedures, with negative tests.
This does not certify complete MCP/A2A transport, sessions or cross-version
interoperability.

The network reference has actual TLS 1.3 loopback mTLS client-certificate
tests, but no real CNI production deployment or independent trust operator.

**Remaining internal blockers:** cross-system authoritative fencing for
non-PostgreSQL targets; audited key rotation and separate operator identity;
production CNI and independently deployed egress identity; automatic
distributed failover and RPO/RTO on target topology; complete build/tool/test
extra hash locks and real signing/publishing custody; pinned official
MCP/A2A transport interoperability; production-shaped mixed target action
load and accepted latency/error budgets. Independent external security
review and customer consent are additional release gates.

**Unrestricted production NO-GO.** PR #34 stays draft.


## October 12 follow-up: production readback privilege check

Commit `c0dc454` adds a production-mode credential boundary in the PostgreSQL
readback adapter. Before reading evidence, it rejects elevated PostgreSQL
observer logins and direct INSERT/UPDATE/DELETE/TRUNCATE access to the effect
table. The check is defense in depth; credential administration, database
ownership/DDL grants, network separation, observer custody and real target
verification still require independent qualification. A disposable PostgreSQL
regression test was added in `27ecae3`.

**Verification:** the previous branch head passed CI #346 (10/10 jobs). CI
#348 was launched for these changes; record its final conclusion separately
before claiming they passed. No production release authorization is implied.

## October 12 — multiprocess stale-leader regression

- Added `tools/drill_pg_stale_leader.py`: one OS process prepares an
  operation, pauses before destination dispatch, and loses the PostgreSQL
  lease. A distinct process/connection acquires the higher epoch, performs
  the authorized effect with a deliberately lost acknowledgment, and refuses
  duplicate execution. The paused old process resumes and must be rejected
  by the destination-enforced fencing check.
- `postgres-stale-leader-drill` runs in CI with a disposable PostgreSQL 16
  service and uploads the structured evidence artifact. The drill job
  passed in run #351; the complete run may still be processing other jobs.
- This proves an important **single-authority PostgreSQL** boundary under
  process isolation. It does **NOT** prove two simultaneously writable
  primaries, stale work against third-party APIs, production cluster
  network isolation, automatically orchestrated HA, or accepted RPO/RTO.
- Independent developer discovery and synthetic/read-only SDK evaluations
  can begin now. Do not invite unsupervised consequential customer-system
  pilots while these gates are open. Three independent integrations and a
  qualified external security review remain explicit adoption/release goals.

**Release posture remains unrestricted production NO-GO; PR #34 stays draft.**
