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

### Direct gateway signature hardening
Production direct gateway calls now reject missing or invalid Ed25519 signatures; the HTTP route forwards its authenticated raw request signature to the gateway. **Remaining caveat:** the direct SDK signer interface has not yet been independently reviewed for binding proof to the exact action, since callers can provide their own signed_data payload. Treat direct SDK usage as unsupported for production until that gap is closed and adversarial tests pass.

### R1 proof-binding update
The direct gateway now validates that the Ed25519-signed canonical payload corresponds to the same signed JSON request body, source and destination protocols, wire arguments, target identity and operation ID before authorizing production execution. HTTP forwards its already-validated raw signed body and nonce. Unlike the earlier implementation, an unrelated signed byte string does not authenticate an action. Direct SDK callers still need a reviewed shared-nonce replay policy; normal HTTP callers use the shared durable nonce ledger. No claim of universal direct-SDK safety is made.

### R3 preliminary work: independent audit evidence verification

An offline verifier at `src/governance/audit_verify.py` validates a signed audit checkpoint against an **independently pinned Ed25519 public key**, not merely the signer key embedded in a checkpoint. It verifies full-chain or checkpoint-anchored tail integrity, including explicit failure on wrong keys, altered entries and incorrect continuation hashes. Tests live in `tests/test_audit_verify.py`.

Scope limit: the verifier does not establish that a remote action actually occurred, and no trusted KMS signer, externally anchored checkpoint registry, durable legal hold or production retention transaction has yet been delivered. The destructive production retention endpoint remains disabled.

### R1–R7 acceptance milestones

| Stage | Production-grade acceptance gate | Evidence so far |
|---|---|---|
| R1 | All execution entry points fail closed for unauthorized identities/capabilities/actions; independent security review | Automated negative tests added; third-party audit missing |
| R2 | Durable operation state, crash/retry reconciliation, operator runbooks, concurrent recovery | Conservative SQL unknown-outcome ledger and synthetic failure tests; no external side effects or kill -9 exercise |
| R3 | Verified evidence and operations, recoverable HA deployment, current protocol conformance | Offline pinned-key verifier and PostgreSQL CI; trusted storage and staging missing |
| R4 | Three unrelated developer integrations and repeat usage | Not yet observed |
| R5 | First paid pilot with measured ROI | Not yet observed |
| R6 | Repeatable managed enterprise deployment and retention | Not yet observed |
| R7 | Multi-industry infrastructure adoption | Not yet observed |

## R3 follow-up: human-reviewed reconciliation groundwork (October 11, 2026)

A transactional SQL-backed `Reconciliation` class now records an operator's determination of an unknown operation, with reviewer identity, destination reference, and a 64-character SHA-256 evidence digest. Concurrent or repeated attempts cannot overwrite the initial determination. Synthetic SQLite cross-worker tests cover the state transition and rejection of unsupported claims.

**Critical limitations / incomplete:** the evidence hash is not proof that the external destination completed an action. Destination-specific read-back verification, trusted operator authorization through the control plane, verified signer identities, reconciled budget reservation settlement, audit event linkage and remote exactly-once guarantees remain unimplemented. This component is **not exposed as a general production HTTP API** and must not be used to approve consequential settlements without independent review.

R3 staging and live operations, protocol conformance, recovery under process kill/network partitions, external penetration testing, R4 integrations, paid R5 pilots, R6 managed distribution and R7 global adoption remain unproven. Do not merge merely because unit tests pass.
