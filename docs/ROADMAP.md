# Roadmap and supported scope

AgentBridge is an engineering alpha. The [current alpha status](CURRENT_ALPHA_STATUS.md)
records the merged main, historical source/evaluator pins and open work.
Historical sprint reports describe their own commits; their test counts and
pending-PR statements are not current status.

The [November 13 checkpoint](CURRENT_ALPHA_STATUS.md) records maintained main
`f309a35cb5c3ec4164acea5ba2622dc04be6807c`, tree
`17fd9e48708ebed43971a4d0b53b9e6cf703c609`, and its own successful 16-job main
CI run. The five owner-approved PRs #87–#91 each passed 24 checks separately.
The [independent audit](AUDIT_AND_RECONCILIATION_2026-11-13.md) distinguishes
those observations from older source, local qualification and external gates.
The [November 3 checkpoint](ALPHA_PROGRESS_2026-11-03.md) remains historical.

Bounded active-worker stop and committed acquire/renew method-return-loss
trials have run, and the supported worker/crash components are **VERIFIED IN
CI** within their selected cohorts. They do not qualify real dropped network
replies, client/gateway partition/rejoin, physical HA or sustained full-route
deadlines. External security, developer, buyer, destination-custody and pilot
acceptance remain separate gates. Dates depend on execution capacity,
permissions and participants; no completion deadline is asserted.

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
- The [governed MCP demonstration](GOVERNED_MCP_DEMO_2026-11-12.md) supplies an
  actual local stdio approval/effect/evidence flow and explicit negative cases.
  Its client and target are synthetic, under one operator; no LLM, native
  payment or independent custody is claimed.
- The [offline Stripe-style contract](OFFLINE_STRIPE_STYLE_CONTRACT_2026-11-12.md)
  reuses the existing fenced SQLite reference target. Mock key bindings and
  webhook deduplication do not prove external provider fencing or settlement.
- Unsupported MCP task augmentation refuses before admission; the
  [task-refusal unit](MCP_TASK_REFUSAL_2026-11-04.md) does not add full MCP task
  lifecycle support. [Audit retention namespace checks](AUDIT_RETENTION_NAMESPACE_2026-11-04.md)
  remain distinct from production retention/custody acceptance.
- Maintained main includes opt-in enrolled tenant SDK/HTTP authority, private SQL
  namespaces, bounded offline historical assignment and shared-SQL admission and
  settlement. Selected operator policy/signing/task mutations compose with SQL.
- Operator-enabled aggregate tenant/human admission spend, rate and active caps
  persist across replicas. They preserve UNKNOWN exposure and historical usage.
- The durable task-status SDK has namespace-wide retained-task count and UTF-8
  event-byte caps with control-event headroom. It never executes a task or cancels
  an external effect. Separate [audit payload limits](AUDIT_CAPACITY_AND_RETENTION_2026.md)
  count retained audit rows and UTF-8 JSON at the SQL boundary; other evidence
  journals, database/index/WAL/backup overhead and custody remain separate gates.
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
reservation and WORKING event. The [private dispatch follow-up](QUEUED_DISPATCH_AND_RECOVERY_2026-10-22.md)
adds one-shot synthetic execution, bounded immutable results and read-only
success reconciliation on SQLite or PostgreSQL tenant accounting. It never
automatically replays an uncertain effect. Its dated local final qualification recorded
830 passed/31 expected backend-specific skips, separate from selected-head CI.
Public worker/network dispatch, historical-key recovery, authoritative absence
proof and acknowledged remote cancellation remain open. Production remains NO-GO.

The [bounded HA follow-up](HA_CRITICAL_PATH_2026-11-12.md) records three accepted
local worker-fault trials. Its new PostgreSQL governance crash cases also ran
in PR #91's successful hosted PostgreSQL cohort; their destination remains the
SQLite demonstration. The separate controlled local crash operator refused
PUBLIC TEMP before creating roles/schemas and accepted no local staging
crash trial. Preserve both observations; neither establishes physical database
failover or arbitrary external execution recovery.

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
   remaining evidence-byte bounds, reference-indexed retention/custody and incident
   operations. The opt-in authenticated tenant HTTP factory is bounded; standalone
   owner IDs do not authenticate a network caller. Qualify frontdoor physical
   connection limits and coordinated stream stop/drain/restore; shared SQL
   allocations alone do not establish those operational controls.

Bounded follow-ups include the mock's aggregate storage limits, container
negative-scenario qualification and dependency hash closure, and a current
source-bound evaluator route. Accurate `/health`, `/ready`, `/version`,
`/metrics` and deployment-setting documentation identified by the legacy review
remains open for a separate narrow change. No runtime cherry-pick, broader
protocol promise or legacy production/compliance claim follows from that gap.

## External acceptance

Independent trust administrators, a destination owner, security reviewers,
three returned evaluator reports, five completed buyer interviews including
budget owners, and a supervised design partner remain distinct requirements.
Invitations, code complexity and passing CI do not satisfy these requirements.

See [four-product gates](FOUR_PRODUCT_EXECUTION_GATES_2026.md),
[protocol contract](PROTOCOL_COMPATIBILITY_2026.md), [deployment](DEPLOYMENT.md),
and [documentation index](README.md). No financial-grade or unrestricted
consequential-action production release is approved.
