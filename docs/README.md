# Documentation index

Start with [current alpha status and exact source/artifact pins](CURRENT_ALPHA_STATUS.md),
[branch documentation dispositions](BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md),
[historical 88-row handoff register](HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md),
[supported roadmap](ROADMAP.md), [protocol scope](PROTOCOL_COMPATIBILITY_2026.md),
[deployment](DEPLOYMENT.md), and [four-product gates](FOUR_PRODUCT_EXECUTION_GATES_2026.md).

For SDK evaluation use [evaluator kit](OSS_EVALUATION_KIT.md),
[Trust/Evidence qualification](TRUST_EVIDENCE_ACCEPTANCE_2026.md),
[offline verifier](EXTERNAL_EVIDENCE_VERIFIER_ACCEPTANCE_2026.md), and
[durable task status](DURABLE_TASK_LIFECYCLE.md) and
[tenant-native status streaming](tenant-task-streams.md).

For historical repository evidence use [branch audit](BRANCH_REVIEW_2026-10-13.md),
[legacy reconciliation](LEGACY_BRANCH_RECONCILIATION_2026.md), and
[external claim checks](RESEARCH_CLAIM_CHECK_2026-10-13.md).

Dated sprint and AWS reports are historical evidence for their stated SHAs.
The current alpha status supersedes their pending-PR, branch-count and future-work
statements. Historical test counts remain attached to their original SHAs;
no historical experiment is promoted to production qualification.
Source layout: `src/protocols` for wire contracts and task status; `src/governance`
for authorization/evidence/SQL; `src/api` for HTTP controls; `src/proxy` for
transport/egress; `src/serve` for separate SDK/stdio surfaces; `tools` for explicit
operator checks; `tests` for reproducible behavior; deployment directories for
distinct topology references. The older `src/engine` is compatibility translation,
not an execution authority.

## Complete document catalog

| Document |
| --- |
| [AgentBridge scoped developer-alpha release candidate](ALPHA_RELEASE_SCOPE_AND_ROLLBACK.md) |
| [Control Plane API Reference](API_REFERENCE.md) |
| [AWS PostgreSQL operational experiment — 2026-10-13](AWS_POSTGRES_STAGING_2026-10-13.md) |
| [Real AWS staging qualification — 2026-10-13](AWS_REAL_STAGING_TEST_2026-10-13.md) |
| [AWS two-host PostgreSQL qualification — 13 October 2026](AWS_TWO_HOST_QUALIFICATION_2026-10-13.md) |
| [AgentBridge AWS staging — strict $0 preparation](AWS_ZERO_COST_STAGING_PLAN.md) |
| [Benchmarks — what AgentBridge actually costs](BENCHMARKS.md) |
| [Branch reconciliation, historical CI, and merge gates](BRANCH_AND_CI_AUDIT.md) |
| [Branch lifecycle](BRANCH_LIFECYCLE.md) |
| [Branch qualification and consolidation — October 13, 2026](BRANCH_REVIEW_2026-10-13.md) |
| [AgentBridge code protection and intellectual-property controls](CODE_PROTECTION_AND_IP_POLICY_2026.md) |
| [AgentBridge commercial strategy decision memo — October 2026](COMMERCIAL_STRATEGY_DECISION_2026.md) |
| [AgentBridge 2026 competitor and engineering risk response](COMPETITIVE_AND_ARCHITECTURAL_RISK_RESPONSE_2026.md) |
| [Connectors — reach any tool, without building connectors](CONNECTORS.md) |
| [Current acceptance — local audit, October 13, 2026](CURRENT_STATUS_2026-10-13.md) |
| [Deployment Guide](DEPLOYMENT.md) |
| [Durable task-status SDK](DURABLE_TASK_LIFECYCLE.md) |
| [AgentBridge egress release review: verified tests vs production gaps](EGRESS_DEPLOYMENT_VERIFICATION.md) |
| [Enforced egress reference and next production blocking gates](EGRESS_ISOLATION_NEXT_GATES.md) |
| [Enterprise governance components](ENTERPRISE.md) |
| [External Evidence verifier and bounded HTTPS destination review](EXTERNAL_EVIDENCE_VERIFIER_ACCEPTANCE_2026.md) |
| [External security review and pilot program](EXTERNAL_REVIEW_AND_PILOTS.md) |
| [External evaluation candidates and outreach protocol — October 2026](EXTERNAL_REVIEW_CANDIDATES_2026.md) |
| [Frequently Asked Questions](FAQ.md) |
| [AgentBridge product architecture — one foundation, four potential offerings](FOUR_PRODUCT_ARCHITECTURE.md) |
| [AgentBridge — four products, one kernel, measurable acceptance gates](FOUR_PRODUCT_EXECUTION_GATES_2026.md) |
| [AgentBridge: hardening release gates (October 2026)](HARDENING_RELEASE_GATES.md) |
| [Independent AgentBridge evaluator report](INDEPENDENT_EVALUATOR_REPORT_TEMPLATE.md) |
| [AgentBridge independent security and pilot review package](INDEPENDENT_SECURITY_AND_PILOT_REVIEW.md) |
| [Security-boundary integration audit — 13 October 2026](INTEGRATION_SECURITY_REVIEW_2026.md) |
| [Framework integrations](INTEGRATIONS.md) |
| [Internal release gate execution register — October 2026](INTERNAL_RELEASE_GATES_2026.md) |
| [Legacy prod/readiness-pass reconciliation ledger — 13 October 2026](LEGACY_BRANCH_RECONCILIATION_2026.md) |
| [Live Agent Testing — agentbridge2](LIVE_AGENT_TESTING.md) |
| [Next phase: isolated evidence pilot and SDK foundation](NEXT_PHASE_EXECUTION.md) |
| [AgentBridge OSS — independent evaluator kit (alpha)](OSS_EVALUATION_KIT.md) |
| [Apply AgentBridge GitHub branch protections](OWNER_GITHUB_RULESET_BOOTSTRAP_2026.md) |
| [P0–P2 qualification packet: engineering evidence versus operated acceptance](P0_P2_OPERATED_ACCEPTANCE_PACKET_2026.md) |
| [Performance baseline — isolated GitHub CI, October 11, 2026](PERFORMANCE_BASELINE_2026.md) |
| [AgentBridge supervised staging and failure-injection checklist](PRODUCTION_OPERATOR_DRILLS.md) |
| [Deferred: A2A gRPC / Protobuf Transport Support](PROTOBUF_A2A.md) |
| [AgentBridge protocol compatibility contract — October 2026](PROTOCOL_COMPATIBILITY_2026.md) |
| [Protocol Support Matrix — the Meta-Bridge](PROTOCOL_SUPPORT.md) |
| [R4 release candidate: internal completion evidence and unresolved gates](RC_INTERNAL_COMPLETION_AND_NOGO.md) |
| [Current release workflow (draft; no production authorization)](RELEASE_PROCEDURE_2026.md) |
| [Production completion contract — internal engineering vs independent acceptance](RELEASE_WORKSTREAM_OWNERSHIP_2026.md) |
| [AgentBridge audit register — October 13, 2026](REPOSITORY_WIDE_AUDIT_AND_EXECUTION_2026-10.md) |
| [External claim checks — October 13, 2026](RESEARCH_CLAIM_CHECK_2026-10-13.md) |
| [Roadmap and supported scope](ROADMAP.md) |
| [Separate-process sandbox observer: operator quickstart](SANDBOX_OBSERVER_SERVICE.md) |
| [Bounded sandbox independent-readback demonstration](SANDBOX_READBACK_DEMONSTRATION.md) |
| [Local Trust → Evidence acceptance workflow](TRUST_EVIDENCE_ACCEPTANCE_2026.md) |
| [Trust → Evidence integrated evaluator sprint — October 2026](TRUST_EVIDENCE_E2E_SPRINT_2026.md) |
| [Local continuation status](LOCAL_CONTINUATION_STATE_2026-10-13.md) |
| [Consolidated audit publication](PUBLICATION_STATUS_2026-10-14.md) |
| [Branch reconciliation and preservation](BRANCH_RECONCILIATION_2026-10-14.md) |
| [Execution plan and acceptance gates](EXECUTION_PLAN_2026-10-14.md) |
| [Authenticated A2A status streaming](A2A_STATUS_STREAMING.md) |
| [Historical handoff acceptance register](HANDOFF_ACCEPTANCE_REGISTER_2026-10-14.md) |
| [Production destination qualification](PRODUCTION_TARGET_QUALIFICATION_2026-10-14.md) |
| [Atomic local admission](ATOMIC_ADMISSION_2026-10-14.md) |
| [Atomic local outcome settlement](ATOMIC_GOVERNANCE_STATE_2026-10-14.md) |
| [Durable aggregate admission quotas](DURABLE_ADMISSION_QUOTAS_2026-10-15.md) |
| [Legacy SQLite mutation boundaries — October 16, 2026](SQLITE_ATOMIC_MUTATIONS_2026-10-16.md) |
| [Task status transaction composition and tenant guards — October 16, 2026](TASK_ATOMIC_SCOPE_2026-10-16.md) |
| [Durable task event-byte capacity — October 16, 2026](TASK_EVENT_CAPACITY_2026-10-16.md) |
| [Durable retained-task capacity — October 16, 2026](TASK_HISTORY_CAPACITY_2026-10-16.md) |
| [Authenticated tenant authority foundation — October 14, 2026](TENANT_AUTHORITY_FOUNDATION_2026-10-14.md) |
| [Explicit historical tenant assignment](TENANT_MIGRATION_2026-10-14.md) |
| [Tenant policy publication — October 16, 2026](TENANT_POLICY_PUBLICATION_2026-10-16.md) |
| [Configured PostgreSQL namespace checks](TENANT_POSTGRES_NAMESPACE_CHECKS_2026-10-16.md) |
| [Enrolled tenant runtime and HTTP boundary](TENANT_RUNTIME_2026-10-14.md) |
| [Signing-policy coordination with tenant authority](TENANT_SIGNING_COORDINATION_2026-10-16.md) |
| [Tenant-native task streams and shared allocations](tenant-task-streams.md) |
| [Native queued tenant task acceptance](TENANT_TASK_INTENTS_2026-10-17.md) |
| [Private queued-intent preparation and first admission](QUEUED_INTENT_PREPARATION_2026-10-18.md) |
| [Current engineering alpha status — October 20, 2026](CURRENT_ALPHA_STATUS.md) |
| [Branch documentation dispositions — October 16, 2026](BRANCH_DOCUMENTATION_DISPOSITIONS_2026-10-16.md) |
| [Architecture decision records](adr/README.md) |
| [ADR-001: Canonical Hub-and-Spoke Model for Protocol Translation](adr/001-canonical-hub-and-spoke.md) |
| [ADR-002: Ed25519 for Agent Identity](adr/002-ed25519-identity.md) |
| [ADR-003: SHA-256 Hash Chain for Audit Trail](adr/003-sha256-audit-chain.md) |
