# Roadmap and supported scope

AgentBridge is an engineering alpha. The [current alpha status](CURRENT_ALPHA_STATUS.md)
records the separate main, cumulative draft and evaluator pins and open work.
Historical sprint reports describe their own commits; their test counts and
pending-PR statements are not current status.

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
- The cumulative draft adds opt-in enrolled tenant SDK/HTTP authority, private SQL
  namespaces, bounded offline historical assignment and shared-SQL admission and
  settlement. Selected operator policy/signing/task mutations compose with SQL.
- Operator-enabled aggregate tenant/human admission spend, rate and active caps
  persist across replicas. They preserve UNKNOWN exposure and historical usage.
- The durable task-status SDK has namespace-wide retained-task count and UTF-8
  event-byte caps with control-event headroom. It never executes a task or cancels
  an external effect. These bounds do not include audit/evidence bytes.
- The opt-in [tenant-native status stream](tenant-task-streams.md) adds shared
  authority-database/namespace allocations across replicas, tenants and stable
  owners. It observes existing task history and does not execute or resume work.
  These allocations do not bound every physical connection or the legacy A2A
  endpoint's process-local streams.

## Internal engineering still requiring qualification

The [native queued-intent follow-up](TENANT_TASK_INTENTS_2026-10-17.md) accepts
signed bounded provenance and submitted status/audit atomically. The later
[private preparation and first-admission units](QUEUED_INTENT_PREPARATION_2026-10-18.md)
revalidate current enrolled authority and atomically link a new operation,
reservation and WORKING event. This is internal admission awaiting dispatch;
UNKNOWN and its exposure remain. No public executable-task API, worker, results,
settlement, tenant-aware recovery or remote cancellation is added. Each unit
requires its own exact-head evidence; the executable task requirements remain open.

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
7. Complete tenant coverage for evidence, reconciliation and background services,
   retained audit/evidence-byte bounds, protected retention/custody and incident
   operations. The opt-in authenticated tenant HTTP factory is bounded; standalone
   owner IDs do not authenticate a network caller. Qualify frontdoor physical
   connection limits and coordinated stream stop/drain/restore; shared SQL
   allocations alone do not establish those operational controls.

## External acceptance

Independent trust administrators, a destination owner, security reviewers,
three returned evaluator reports, five completed buyer interviews including
budget owners, and a supervised design partner remain distinct requirements.
Invitations, code complexity and passing CI do not satisfy these requirements.

See [four-product gates](FOUR_PRODUCT_EXECUTION_GATES_2026.md),
[protocol contract](PROTOCOL_COMPATIBILITY_2026.md), [deployment](DEPLOYMENT.md),
and [documentation index](README.md). No financial-grade or unrestricted
consequential-action production release is approved.
