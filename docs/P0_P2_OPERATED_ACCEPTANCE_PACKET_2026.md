# P0–P2 qualification packet: engineering evidence versus operated acceptance

**Decision at creation:** production NO-GO. No operator authorization, cloud cluster, independently managed signer or managed HA system has been supplied to this workflow. Never treat a simulator/CI pass as operated production evidence.

## P0 — Independent trust, destination enforcement, CNI
- [ ] Separately administered observer principal with only required read privileges, and immutable audited key registration, dual-operator approvals, staged/active/revoked lifecycle. `validate_rotation` rejects invalid local transitions, but an authenticated operator control plane and external custody are still required.
- [ ] Test actual receiving system's atomic monotonic-epoch fence (or fail closed when unsupported). SQLite/PostgreSQL reference adapters do not fence arbitrary third-party SaaS tools.
- [ ] In isolated Kubernetes namespace using an enforcing CNI, record `kubectl version`, CNI name/version, applied NetworkPolicy and Pod selectors, plus negative IPv4/IPv6, metadata, direct outbound, DNS bypass, unauthorized workload and TLS/SNI tests. Use real workload identity, not the disposable Docker proxy identity. Capture policy decisions and signed operator acceptance.

## P1 — HA, RPO/RTO, releases and rollback
- [ ] Exercise automated failover under network partition with external fencing and two nodes, prove no simultaneous writable leaders, and record RPO bytes/time and RTO across representative workload samples. The current Docker standby promotion deliberately stops the old primary first and does not establish split-brain safety.
- [ ] Generate wheel/image SHA256, deterministic dependency-lock inputs, SBOM and a verifier-checkable SLSA-style provenance manifest (do not claim a SLSA level absent evaluation). Publish with a separately administered signing identity to a real registry, then independently fetch and verify immutable artifacts.
- [ ] Execute synthetic upgrade and rollback on an operated staging system: schema/data snapshots, audit-chain and witness state, old/new binary digest, resumed action outcomes, negative replay tests, timestamps and independent reviewer signature. A written runbook does not count as executed rollback.

## P2 — Transport protocols and sustained service SLOs
- [ ] Pin official MCP/A2A client and server versions. Exercise real transports, sessions, auth, streaming/cancellation/errors and async task lifecycle; report supported subsets and fail-closed unsupported operations. Schema-only compatibility is insufficient.
- [ ] Representative full-path workload (authorization → dispatch → destination effect → readback → reconciliation → audit), mixed failure injections, p50/p95/p99, throughput, CPU/RSS, queue length, backpressure and load shedding. Agree on service budgets with intended design partners before declaring SLO compliance.

## Minimum operator evidence packet per test
For each gate: exact commit SHA, deployed image digest, environment and permissions, independent observer/operator identities, test procedure, expected failure and success conditions, timestamped machine-readable results, logs/metrics with secrets redacted, reviewer signature, observed risks, disposition and rollback plan.

**Classification:** code available / CI verified / deployed staging verified / independently reviewed / production accepted are distinct states. Never skip states in the release register.
