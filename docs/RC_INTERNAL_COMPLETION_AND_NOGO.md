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
