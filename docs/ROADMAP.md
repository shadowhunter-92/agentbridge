# Roadmap and supported scope

AgentBridge is an engineering alpha. The current [acceptance register](CURRENT_STATUS_2026-10-13.md)
records tested source and open work. Historical sprint reports describe their own
commits; their test counts and pending-PR statements are not current status.

## Implemented foundation

- Six adapter families translate a limited capability/arguments/text subset.
- Governed HTTP dispatch binds signed agent requests, scoped approval, target,
  operation identity and durable budget reservation.
- SQLite/PostgreSQL state supports tested concurrency, unknown-outcome recovery,
  destination reference fencing, signed readback and operator-reviewed settlement.
- Optional signed trust journals serialize key rotation and settlement; external
  revision floors remain necessary to reject an otherwise valid old backup.
- The offline Evidence verifier is installed as `agentbridge-verify-evidence`.
  Trust roots and expected action inputs must come from the verifier's operator.
- OIDC/RBAC, Prometheus metrics and optional OpenTelemetry already exist.
- A durable task-status SDK adds atomic transitions, owner scoping, bounded
  admission and cursor replay. It never executes a task or cancels an effect.

## Internal engineering still requiring qualification

1. Reference transport interoperability for each advertised SDK/version and
   supported behavior. The opt-in A2A 0.3 observer streams existing task status;
   it does not execute new tasks, cancel remote effects or provide push delivery.
   MCP HTTP client qualification is bounded; full lifecycle fidelity remains open.
2. Non-bypassable enforcement at one real external destination, beyond the
   participating PostgreSQL/SQLite examples.
3. Operated workload identity and egress tests covering DNS, IPv6 and direct
   connections on the intended cluster, with correct selectors and namespace.
4. Automated leader fencing and repeated partition/failover/RPO/RTO trials.
5. Approved publisher identity, immutable signed artifacts, provenance and
   two-version live-service migration/rollback.
6. End-to-end service latency, overload behavior and operational resource limits.
   A synthetic translation benchmark or SQL smoke threshold is not an SLO.
7. Service-level tenant isolation, retention/custody administration and incident
   operations. SDK owner IDs are not authenticated HTTP tenant isolation.

## External acceptance

Independent trust administrators, a destination owner, security reviewers,
three returned evaluator reports, five completed buyer interviews including
budget owners, and a supervised design partner remain distinct requirements.
Invitations, code complexity and passing CI do not satisfy these requirements.

See [four-product gates](FOUR_PRODUCT_EXECUTION_GATES_2026.md),
[protocol contract](PROTOCOL_COMPATIBILITY_2026.md), [deployment](DEPLOYMENT.md),
and [documentation index](README.md). No financial-grade or unrestricted
consequential-action production release is approved.
