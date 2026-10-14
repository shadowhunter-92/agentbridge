# AgentBridge execution plan — October 14, 2026

The next work is sequenced by acceptance gates, not an unsupported production
date. Keep the shared OSS/Trust/Evidence kernel coherent; do not fork four
incompatible implementations or label unfinished internal engineering external.
No new paid cloud environment, outbound outreach or branch deletion is assumed.

## P0 — Preserve and consolidate the verified foundation

PR #51 has merged into integration. Before main changes, correct the newly
exposed SQLite lease-clock boundary, preserve every original branch head and
wait for exact-head checks. The reviewed reconciliation records 17 history
merges, preserving all 27 inventoried remote heads and 75 formerly divergent
commits. History-only merges leave the verified source tree unchanged; old
implementations remain recoverable in their original commits. Branch names
remain online. See [branch ledger](BRANCH_RECONCILIATION_2026-10-14.md).

Merge the corrective reconciliation PR using a merge commit, then merge PR #41
using a merge commit after its updated checks pass. Squashing this history
consolidation would undo the ancestry-preservation objective. Verify main's tree
and ancestry after each merge; retain a Git bundle and ref manifest. Later
branch cleanup must distinguish safe archival from deletion and preserve the
two protected release-history lines unless separately approved.

Acceptance: every inventoried head is reachable, original refs/bundle recover,
the corrected lease test passes on Windows and Linux, and required hosted CI
passes on the actual integration-to-main head. Do not bypass branch protections.

## P1 — Real authenticated task-status streams and MCP HTTP qualification

Use an isolated feature branch based on consolidated main. First qualify the
installed families: A2A SDK 0.3.26 / A2A 0.3 JSON-RPC and MCP SDK 1.30.0 with its
negotiated published protocol version. Record those exact versions in results.
Keep legacy `tasks/send` compatibility distinct from modern message methods.
Do not advertise general A2A 1.x or latest-draft MCP conformance from these tests.

### A2A status service

Build an opt-in application factory over DurableTaskLifecycle. Trusted workers
publish already admitted task states through the SQL SDK; network callers can
observe their own tasks, not create tool effects, provide their own owner scope,
replace a task identity or claim a successful effect. Authorize with verified
issuer/audience/subject claims; no administrator-key shortcut grants all owners.

Implement `tasks/get`, `tasks/resubscribe` and status-only existing-task use of
`message/send` / `message/stream`. Return specified JSON-RPC errors for unsupported
operations, unknown tasks, invalid requests and noncancelable tasks. Cancellation
must not falsely report that an external effect was canceled or a reservation
refunded. Actual worker cancellation requires a later explicit execution contract.

Stream real SSE responses containing A2A JSON-RPC Task/status updates. Close on
terminal or interrupted interactions; preserve order and expose a documented
owner/task-bound replay cursor. Reconnection resumes durable history without
resubmitting actions. Bound request size, replay page size, connection lifetime,
idle waits and simultaneous streams. Revalidate authorization during a stream;
close when identity expires or is revoked. These initial process limits must not
be described as fleet-wide tenant quotas.

Acceptance tests must use actual loopback HTTP sockets and an official A2A SDK
client, not only in-process ASGI mocks. Cover disconnect/reconnect, server restart,
missed-event replay, terminal/interrupted closure, cross-owner denial, tampered or
future cursors, JWT expiry/revocation, malformed/version-mismatched requests,
capacity rejection and cleanup after cancellation/disconnect. Assert lifecycle
network traffic cannot enter the canonical executable-call boundary.

### MCP HTTP client and reference server

Exercise official Streamable HTTP client/server implementations with a read-only
tool, negotiation, valid/invalid sessions, tool-error propagation and Origin
rejection. Keep the existing stdio qualification. A direct developer transport
utility remains distinct from the governed proxy; exposing HTTP execution through
the governed API requires the same operator target/capability/identity/egress
boundary, with no caller-chosen arbitrary endpoint or credentials.

Acceptance: Windows/Linux live tests pass, optional SDK requirements are explicit,
core packaging still installs without optional transports, the full suite passes,
and the new PR receives exact-head hosted checks. Document the precise supported
subset and unresolved MCP authentication/transport features instead of claiming
the entire protocol is certified.

## P2 — Versioned protocol interoperability and governed async execution

Upgrade A2A 1.x and newer MCP revisions on separate reviewable version branches.
Build a conformance matrix for every declared revision and transport: discovery,
negotiation, request/result/errors, lifecycle, artifacts, streaming, resumption,
cancellation and authentication. Label BeeAI ACP and AGNTCY compatibility scope
explicitly; model parsing and the 36-route translation matrix remain narrow tests.

Define message/task/operation correlation and idempotency independently. Require
durable admission before starting governed work, atomically link task events to
operation state, and preserve unknown outcomes after disconnect. Add controlled
worker cancellation with truthful acknowledgements. Prove no retry, double effect,
budget refund or success settlement is caused solely by reconnecting or consuming
a status event. Qualify cross-version incompatibility and failure behavior using
independently implemented clients/reference agents where available.

## P3 — Tenant service isolation, quotas and retention

Bind verified workload/user identities to durable tenant/agent scopes across all
tasks, operations, budgets, approvals, evidence and audit reads. Test two owners
sharing identifiers and malicious cross-scope requests on every endpoint. Use
database-atomic fleet quotas for active work, streams, historical tasks, event
bytes and retained evidence; process-local stream limits are insufficient.

Design retention with legal hold, independent review and immutable evidence
references. Add index/schema migrations, quota accounting and failure-safe
cleanup. Acceptance includes cross-worker/race tests, policy reload, revoked
identities and proofs that cleanup cannot release uncertain reservations or
erase held evidence. Replace broad operator access with explicit service roles.

## P4 — External enforcement, automated recovery and signed releases

Operate workload identity and non-bypassable destination/egress controls. Qualify
fencing against an independently authoritative destination; an SQL epoch cannot
by itself fence a partitioned actor in an unrelated SaaS service.

Define RPO, RTO, latency/error/load targets and measurement methods before running
experiments. Qualify automated split-brain-safe HA, backup/restore, schema upgrades,
rolling service migration and rollback under real faults. Preserve unknown actions
and signed-key revision floors across recovery. Bounded manual promotion or a wheel
swap is not complete service availability qualification. Reuse local disposable
environments first; cloud execution needs a concrete cost ceiling and approval.

Generate signed release provenance and SBOMs for actual immutable artifacts;
verify signatures independently before rollout. Package/image publication remains
behind explicit owner gates, with release versioning separate from source merges.

## P5 — Independent acceptance and commercial evidence

Prepare reproducible evaluator packages and failure cases in parallel with internal
work. Obtain separately administered signer, observer, destination and retention
identities, returned security/developer reports, real buyer interviews and a
supervised design partner. Record responses and test evidence; invitations and
synthetic demonstrations do not establish traction or independent custody.

Outbound messages, externally controlled access and partner scheduling require
appropriate owner authorization; they cannot be manufactured by local tests.
Each proposed offering must meet the [four-product gates](FOUR_PRODUCT_EXECUTION_GATES_2026.md)
before production or commercial claims change.

## Primary protocol references checked

- [A2A 0.3 specification](https://a2a-protocol.org/v0.3.0/specification/): JSON-RPC methods, SSE framing, task updates and error codes.
- [A2A 1.0.1 migration notes](https://a2a-protocol.org/v1.0.1/whats-new-v1/): treat the version upgrade as an explicit compatibility change.
- [MCP 2025-11-25 transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports): use a published version contract, independently of the evolving draft.

After every phase, update current acceptance with exact source/artifact identifiers,
executed checks, known limitations and remaining gates. Preserve recoverability
and keep claims proportional to the evidence.
