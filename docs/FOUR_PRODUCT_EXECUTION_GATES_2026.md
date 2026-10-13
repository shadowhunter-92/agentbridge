# AgentBridge — four products, one kernel, measurable acceptance gates

**Status:** portfolio specification, not four validated standalone commercial products. No real customer revenue or independent production certification verified.

## Shared rule
A request-specific operation identity, approved fingerprint, durable ledger, policy decision and authoritative destination reconciliation must use one consistent kernel. Protocol adapters may translate only the explicitly supported semantics. Trust and Evidence must not silently fork security logic into separate implementations.

| Product | Core user / buyer hypothesis | Smallest deliverable | Pass criterion | Major remaining work | Commercial gate |
|---|---|---|---|---|---|
| OSS | Developer integrating MCP/A2A tools | Clean wheel install, bounded adapter/SDK example, documented failures | Three independent installs with exact SHA and reproduction logs | Official pinned protocol transport cases, docs accuracy, contributor maintenance | Repeated unsolicited use, not star count alone |
| Trust | Platform engineer; security owner funds | Request-bound auth/approval plus safe single external action | Stale leaders fail, duplicates denied and unknown outcomes fail closed under test | Third-party destination fencing, workload auth, multi-tenant boundary review and independent pen test | Buyer identifies named consequential workflow and budget |
| Evidence | Audit/platform team; risk or compliance sponsor | Receipt + independently retrieved authoritative readback + checkpoint validation/export | Independent custodian keys and source permissions; tamper/rollback attempts rejected | Separate administrative custody, witness durability, destination signature lifecycle and external attestation | One scoped supervised design-partner commitment |
| Enterprise | Ops/security procurement team | Reproducible managed staging with supported operations, retention, access and SLAs | External deployment owner signs recovery, monitoring, isolation, rotation and rollback evidence | Cluster hardening, HA split-brain, signing provenance, on-call, privacy/compliance and contract terms | Paid pilot and support obligations confirmed |

## P0/P1/P2 remaining
- **P0:** independent organization-controlled observer signer and readback credentials; enforce fencing at each real target; enforce authenticated workload egress and adversarial DNS/IPv6 paths on an operator-managed boundary.
- **P1:** automated HA leader election under partitions with repeated RPO/RTO measurements; independently controlled signing and publication; upgrade/rollback under live traffic and multi-version migrations.
- **P2:** genuine reference-client MCP/A2A transport/lifecycle matrix; production-shaped end-to-end p50/p95/p99, backpressure, faults, RSS/CPU and SLO decisions.

## First release wedge
Publish only the **synthetic/read-only Evidence SDK** and an optional Trust integration example, with pinned artifacts, clear unsupported operations, and a machine-readable verifier result. Do not allow production payments, trades, hiring or other consequential mutations. Explicitly distinguish signature validation of a claim from independently observed real-world fulfillment.

## Product decisions
- Keep OSS protocol compatibility focused rather than inventing a rival standard before adoption.
- Prefer an optional Evidence library alongside existing gateways; avoid forced full gateway replacement.
- Do not promise SOC 2, HIPAA, EU AI Act compliance, legally admissible proof or liability reductions without external validation.
- Do not price enterprise tiers from assumed TAM. Interview at least five budget owners and run one willingness-to-pay pilot with written acceptance criteria.
- Evaluate a future independently owned commercial control plane only after copyright and user-needs review; do not relicense existing Apache components by folder without due diligence.

## Stop/kill signals
No external installation after targeted outreach; no named buyer with urgent budget; an existing gateway solves the exact problem more cheaply; inability to gain authoritative readback access; operators cannot independently control keys; failover produces uncertain duplicate effects; deployment cannot meet a customer-owned SLO.

## Sequencing
1. Security hygiene + ownership protection and least-privilege publishing; reconcile docs to current integration state.
2. Ship a clean, fixed-SHA SDK evaluation package. Collect three independently consented reports.
3. Partner with one controlled destination owner to test true third-party readback/custody.
4. Repeat HA, partition and protocol failure tests in authorized staging. Collect externally witnessed evidence.
5. Only then design enterprise billing, managed hosting, sales contracts and a legal/IP-checked private commercial module.
