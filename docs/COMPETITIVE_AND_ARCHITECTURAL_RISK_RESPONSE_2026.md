# AgentBridge 2026 competitor and engineering risk response

**Evidence status:** October 2026 internal code review and engineering plan. Competitor, regulatory, and customer claims must be independently reverified before sales publication. Engineering alpha, not production certified.

## Critical corrections to external market assessment

1. **"Kong only routes JSON" is false.** Kong AI Gateway documents MCP tooling/access-control capabilities. The rival set also includes Envoy-native agent gateways, API platforms and cloud IAM/audit tools. No verified claim that AgentBridge uniquely combines every feature.
2. **Python is not yet the measured bottleneck.** CI observed roughly 47,082/s *in-memory inert translations*, versus about 225/s for a *50-operation SQLite governance workload* with high tail latency; these are non-comparable. Run HTTP→authorization→durable DB→remote destination→signed readback with concurrency/CPU/RSS before considering a native proxy rewrite.
3. **Protocol portability is not full async fidelity.** CanonicalCall/Result represents bounded tool calls. MCP resources, long-running tasks, A2A cancellation/streaming/push, session resume, multi-turn workflows and OAuth negotiation are unqualified. The legacy inline proxy previously lacked the same fail-closed method boundary as the canonical adapters. This PR addresses *method/lifecycle rejection only*, not async functionality.
4. **Exactly-once and legal proof are overclaims.** Destination-atomic fencing is demonstrated on owned SQL targets, not arbitrary payment rails. An Ed25519 signature authenticates a signer's statement but not actual delivery, settlement, or human-approved economic result.
5. **Regulation:** EU AI Act obligations depend on classification, role and application dates; do not sell a generic "automatic logging equals compliance" promise. SOC 2 is an independently assessed organization-level controls report, not a legal mandate every AI operator automatically incurs.
6. **Open-source rights:** Prior Apache 2.0 grants remain. Theoretical forkability is not itself a commercial fatality: supportability, distribution, integrations, customer trust, independently administered witness networks, operational guarantees and protected *new* commercial modules can differentiate. Do not relicense existing directories without copyright and counsel diligence.

## Four-product focused offer

| Product | Current evidence | Critical weakness | Next falsifiable gate |
| --- | --- | --- | --- |
| OSS | Six protocol wire adapters; SDK and subset tests | Lifecycle semantic collapse; live proxy had older translation engine | Only advertise pinned MCP tools/call and narrow A2A action subset. Test official reference-client versions including negative streaming/notifications. |
| Trust | Policy, approvals, durable operations, SQL fencing | Generic external adapter can be bypassed absent real destination control | Separate destination owner rejects stale/unauthorized live sandbox effect; attacker has no direct egress. |
| Evidence | Signed receipts, readback, registry, offline verifier | Observer signing/readback custody not independently administered | External custodian signs actual destination-state readback; tamper/revocation/retention acceptance witnessed. |
| Enterprise | Docker/K8s/PG drills, RBAC/OIDC components | No operated tenant support, multi-region HA, ongoing SLA or customer procurement | Design partner accepts RTO/RPO/rotation/upgrade and staffing/on-call plan in supervised sandbox. |

## Engineering decision gates

**P0 protocol safety:** unsupported methods/states must fail before network dispatch; no fallback conversion to tools/call; property-based malformed wire tests; verify identity and approval at actual executor, not only at gateway.

**P0 performance:** synthetic E2E traffic matrix for no-op translation versus budget/auth/SQLite and Postgres+network (concurrency 1,8,32,128); record RPS, p50/p95/p99, error/timeout, CPU/RSS, lock waits, queue depth, unknown outcomes. Benchmark same workloads against Kong/Envoy plugin paths before deciding on Rust/Go or Python optimization.

**P1 lifecycle support:** preserve task identity, states, cancellation, streaming chunks, resumability, provenance and backpressure using a separate explicit task-lifecycle object, not forced conversion into a CanonicalCall. Gate each protocol/SDK revision and unsupported case before any claim of general interoperability.

**P1 distribution:** ship a self-contained install and eval in an existing MCP client/gateway rather than replacing the client's data plane. Inspect licensing and keep the Apache kernel; assess a **separately written** proprietary operator plane only with clear copyright ownership.

**P1 external validation:** 3 independent technical reports, 5 finance/IT/security buyer interviews, one written supervised evaluation; an emailed invitation is not an evaluation, and no presumed 30% insurance discount, paid Fortune 500 engagement or nine-figure valuation is evidence.

**Release classification:** build narrowly scoped, supervised read-only/synthetic SDK and Trust/Evidence integrations. Production consequential actions remain **NO-GO** pending independent custody, destination authorization, network enforcement, failover and external validation.
