# Next phase: isolated evidence pilot and SDK foundation

**Status:** engineering implementation underway; not a production release.
**Branch:** `release/r4-internal-gates-2026-10`; do not merge before final-head CI and security review.

## Objective

Prove one bounded consequential-action lifecycle and expose verification as a
reusable OSS component. Avoid four separate codebases. AgentBridge OSS hosts the
protocol and verification primitives; Trust owns authorization and execution;
Evidence owns readback and immutable audit witness integrations; Enterprise is
a future operated service contingent on customers.

## Work packages and acceptance

| Work package | Our implementation and internal test | External acceptance needed |
|---|---|---|
| Evidence witness | Separate-state monotonic witness journal, two-key proof checks, fork/rollback regressions | Operator-controlled immutable third-party anchor, independent witness assessment |
| Independent readback | Read-only authoritative sandbox target adapter; separately administered signing service; lost-ack/evidence-spoof tests | Actual target owner and independent key/credential control |
| Network egress | Locked-down proxy and network policy with DNS/redirect/CONNECT adversarial tests | Environment-specific network enforcement review |
| Recovery | Isolated PostgreSQL restore, partition and shutdown/kill drill automation with emitted evidence | Managed infrastructure acceptance and witnessed failover |
| Protocols | Explicit version-specific matrices and conformance tests for supported *subset* | External reference-system interoperability |
| Packaging | Repeatable wheel/container builds, pinned dependencies, SBOM and rollback dry run | Signed release and deployment qualification |
| Performance | Real SQL concurrency and representative synthetic target workload, baseline p50/p95/p99 and error rate | Real workload SLO acceptance |
| OSS SDK | Decouple `authorize`, lifecycle and verify APIs from gateway and document install | Three outside teams adopt independently |
| Enterprise | Operations architecture, tenant boundaries and customer deployment planning | Paid design partner and commercial evidence |

## Immediate go/no-go gates

1. All new tests pass on Python 3.11, 3.12 and disposable PostgreSQL.
2. The witness journal rejects stale, forked and truncated history after restart.
3. An independent read-only observer proves sandbox target state even if acknowledgments are lost.
4. No unknown operation silently re-executes. A proof unavailable or inconsistent stays unknown.
5. Operator drills produce immutable run artifacts and explicitly label simulations.
6. No claim of full MCP 2026/A2A 1.0 conformance from tool-call-only translations.
7. PR review and narrow release approvals separate from deployment and business validation.

## Actual current position

`src/governance/witness_journal.py` adds a durable **independently deployed**
SQLite witness-state prototype with monotonic sequence progression, fork checks,
an idempotent duplicate rule, and signed audit receipt verification. This is
not WORM storage. If an attacker can restore both AgentBridge and journal
backing stores or compromise witness signing, rollback resistance is lost.
Tests do not simulate independent ownership merely by opening a second file.

**Verdict:** BUILD THE FOUNDATION / RELEASE BLOCKED pending all applicable gates.

## October 12 implementation checkpoint

- `src/governance/sandbox_readback.py` provides a durable sandbox target and a separately keyed, read-only authoritative-state observer.
- `tests/test_sandbox_readback_lost_ack.py` exercises post-commit lost acknowledgment, no duplicate execution, persisted destination inspection, tamper rejection, and budget/operation settlement.
- `src/governance/trust_sdk.py` is a lightweight importable evidence verifier that does not require starting the HTTP gateway; `tests/test_trust_sdk_evidence.py` tests it.
- This establishes a **sandbox prototype and initial OSS SDK facade only**. It does not close external real-target readback, independent key custody, enterprise operations, network containment, protocol conformance, rollback or sustained production-load qualification.
- Keep the seven production release gates open and PR #34 draft until all required acceptance evidence is verified.

## October 12 packaging acceptance correction

A source/build-only CI job cannot prove an installable OSS SDK. The existing
`pyproject.toml` mapped discovered Python packages into the wrong hierarchy
and used an unavailable `cli:main` console entry point. The corrected package
discovery includes the actual `src` package and nested modules; the console
entry now points to `src.cli:main`.

The package-review CI job now creates a fresh virtual environment, installs
the built wheel from its artifact, imports `src.governance.trust_sdk` and the
sandbox readback module **outside the repository directory**, invokes
`agentbridge --version`, and runs `pip check`.

This is an internal reproducible installation gate, not a PyPI publication,
third-party adoption, SBOM, signed artifact or production release certification.
The follow-on release head must pass this new job before claiming the package
layout is repaired.

## October 12 continuation: sandbox service, package provenance, rollback test

- The separately importable `sandbox_observer_service` is a loopback-bound,
  authenticated, **non-production** FastAPI readback process. It refuses
  `AGENTBRIDGE_ENV=production`, reads state through the earlier read-only
  adapter and keeps its signing key in a restricted on-disk file.
- Its service-level authentication, unknown-state behavior and two-signature
  SDK integration are exercised by `tests/test_sandbox_observer_service.py`.
  The private-key reader preserves exactly 32 raw bytes and has a regression
  for otherwise lossy whitespace stripping.
- The package-review CI now records built wheel hashes, source commit SHA,
  dependency freeze and pip environment inventory as downloadable artifacts.
  This is a **dependency inventory**, not a locked reproducible build, a
  comprehensive SBOM, a vulnerability clearance or a signature.
- `tests/test_witness_backup_rollback.py` makes a real SQLite backup,
  advances the independent witness head, restores only the governance DB,
  and asserts rejection of the stale/forked view. This is **not** a managed
  PostgreSQL failover or offsite immutable archive test.
- Complete latest-head CI before calling these internal milestones verified.

### External versus internal work, unchanged

Our responsibility still includes production-ready target adapters, credential
and tenancy isolation, destination-state semantics, secure egress enforcement,
protocol-version tests, migration/rollback scripts, SBOM and security scans,
HA recovery rehearsal automation, and documentation. Real customer-system
permissions, independent operators/reviewers, actual managed HA infrastructure
and outside installations cannot be manufactured by internal unit tests.
