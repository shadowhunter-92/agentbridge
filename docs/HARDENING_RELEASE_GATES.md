# AgentBridge: hardening release gates (October 2026)

> STATUS: Engineering integration under review. NOT production-certified; do not merge/deploy based only on passing unit tests.

## What is implemented on the draft hardening branch

- Operator-managed execution targets identified by target_id; the caller cannot supply arbitrary executable/URL configurations.
- In production, targets have explicit capability and allowed_agents lists.
- Nonnegative, finite reserve costs; production cost schedule is owned by operators. This is **not** final usage metering.
- Signed requests use shared durable nonces in production and read current identity revocation from the durable store.
- Approved actions are scoped to a hash of agent, source and target protocol, source wire, cost, and target_id. The grant is consumed before tool execution.
- Governance policies and sensitive capability registration are durable in SQL and observable across independent worker connections.
- Audit views query durable records across workers; destructive audit retention and ad-hoc signing endpoints deliberately reject production requests.
- PR #17 production-readiness observability, metrics, resilience and startup controls were reconciled here; CI now exercises PostgreSQL.

## Breaking integration contract

The route endpoint accepts target_id (not target). Example operator configuration:

```bash
export AGENTBRIDGE_ENV=production
export AGENTBRIDGE_DB='postgresql://...'
export AGENTBRIDGE_ADMIN_KEY='<strong-random-secret>'
export AGENTBRIDGE_TARGETS_JSON='{"math":{"protocol":"mcp","kind":"mcp_stdio","command":"python","args":["examples/mcp_server_agent.py"],"capabilities":["add"],"allowed_agents":["example-agent"]}}'
export AGENTBRIDGE_COST_SCHEDULE_JSON='{"add":1.0}'
```

Production signed nonces have format `<unix_seconds>:<random_string_at_least_16_characters>`. The complete nonce is covered by the existing Ed25519 request signature. Clients using the older opaque nonce format must be migrated before production.

Do not expose the control plane before TLS, stable secrets, a shared database, trusted operator configuration and a reviewed target allowlist are correctly deployed.

## Mandatory unresolved release gates

1. **Trusted audit retention:** durable legal holds, externally trusted signing keys, atomic retained-chain anchoring, and recovery tests. Current production retention/checkpoint endpoints intentionally fail closed.
2. **Execution semantics:** timeout handling, crash-safe idempotency, unknown-outcome states, safe retries, and compensation workflows for side-effecting actions.
3. **Independent security:** review all HTTP/SDK paths for policy bypass, evaluate hostile agents, verify target isolation, review authorization races and dependency vulnerabilities.
4. **Protocol conformance:** test supported MCP and A2A versions against official reference runtimes; document streaming, sessions, cancellation, structured content, task lifecycle and unsupported behaviors.
5. **Operations:** backup/restore, rolling migrations, HA Postgres, multi-instance shutdown/restart drills, secret rotation, trusted JWKS configuration, TLS and isolation.
6. **Performance:** repeatable p50/p95/p99 concurrent latency and throughput using Postgres and real external target agents; adopt explicit SLOs.
7. **External deployment:** independently operated staging/pilot, security signoff, support plan, and recoverability evidence.
8. **Commercial proof:** actual third-party integrations and paying users; not a condition that source code can satisfy on its own.

## CI

- The Python 3.11 and 3.12 jobs run the full test suite. Tests requiring external resources must not be counted as passed when skipped.
- The postgres-integration job runs `tests/test_postgres_store.py` against a disposable PostgreSQL 16 service.
- Green CI confirms these checks only; it is not an independent penetration test, SOC 2 attestation, or production readiness certification.

## Merge rule

Keep PR #27 as a draft while the unresolved release gates remain. Keep `main` unchanged. Rebase/reconcile against latest main, review, rerun CI and obtain independent approval before changing protected deployment behavior.

## R1/R2 experimental follow-up (2026-10-11)

An independent follow-up branch adds production deny-by-default capability ACLs and a conservative SQL execution ledger. Production live execution now requires an `operation_id` (16–128 characters) and operators must explicitly set `AGENTBRIDGE_CAPABILITY_ALLOWLIST_JSON` to authorize the named agent and capability. This is a breaking configuration change for production.

The ledger atomically claims an (agent_id, operation_id, request fingerprint) before target invocation, records the outcome conservatively as `unknown` before execution, and updates to `succeeded` on success. Duplicate operation IDs never automatically reinvoke a target. A mismatched fingerprint is rejected. A post-dispatch transport failure remains `unknown` for external reconciliation; a failure after an external side effect cannot be reliably inferred from the exception.

**Important remaining limitations:** this is not exactly-once execution, a transactional outbox, automatic reconciliation, or a full execution-state machine. Authorization and approval verification need further independent review; notably direct library calls do not yet require explicit signed-request proof, and server-trusted targets still need SSRF/DNS rebinding hardening. Timeouts, cancellation, operation-status access control, signed receipts and durable checkpoint anchoring are not complete. An audit hash chain proves record integrity against simple tampering, not independent truth of a target's outcome.

### R1/R2 adversarial test matrix (current automated scope)

- Deny unallowlisted production capabilities even for registered identities.
- Detect repeated operation IDs across separate SQLite worker connections.
- Reject reuse of the same operation ID with different payloads.
- Refuse to reinvoke a successful operation.
- Refuse automatic reinvocation after an injected connection timeout, preserving an `unknown` outcome.

**Not yet exercised:** kill -9 at every transition, target acknowledgement loss, remote partial success, aggressive multi-node Postgres failover, hostile SSRF endpoints, external penetration testing, policy changes during execution, high load and real network partitions.

The R1/R2 branch and its PR must stay draft until final CI checks and independent acceptance gates pass. No production release is asserted.
